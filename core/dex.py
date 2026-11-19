"""UNIVA Native DEX & Constant-Product AMM State Engine (x * y = k).

P4 Consensus & Ledger Integration:
- All pool reserves, LP tokens, user nonces, and balances operate in integer base units
  (1 UNIVA = 10**8 units); zero floating-point drift inside pool accounting.
- When attached to a UNIVA L1 Blockchain instance, UNIVA swaps and liquidity provisioning
  bind directly to real confirmed L1 spendable UNIVA balances via tracked net deltas
  (`univa_net_deltas`) while non-native assets (e.g. uUSD) and LP shares are tracked in
  persisted DEX state with atomic disk checkpoints (`univa_dex_state.json`) and SHA-256
  `state_root` commitments.
- Sandbox/test balances (`test_balances`) are strictly isolated from real AMM pools.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from math import isqrt
import os
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

UNIT = 100_000_000
MINIMUM_LIQUIDITY = 1_000
BPS = 10_000
LOCKED_LP = "0x000_LOCKED"
GENESIS_POOL_PROVIDER = "univa_genesis_vault"

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEX_STATE_FILE = os.path.join(_BASE_DIR, "univa_dex_state.json")


def to_base_units(value) -> int:
    try:
        if isinstance(value, float):
            d = Decimal(f"{value:.8f}")
        else:
            d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid amount") from exc
    if not d.is_finite() or d < 0:
        raise ValueError("Amount must be finite and non-negative")
    scaled = d * UNIT
    if scaled != scaled.to_integral_value():
        raise ValueError("Amount supports at most 8 decimal places")
    return int(scaled)


def from_base_units(value: int) -> float:
    return float(Decimal(int(value)) / UNIT)


@dataclass
class Pool:
    asset_a: str
    asset_b: str
    fee_bps: int = 10
    reserve_a: int = 0
    reserve_b: int = 0
    total_lp: int = 0
    lp_balances: Dict[str, int] = field(default_factory=dict)

    @property
    def pool_id(self) -> str:
        return f"{self.asset_a}/{self.asset_b}"

    def to_dict(self) -> dict:
        spot_a_in_b = round(self.reserve_b / self.reserve_a, 8) if self.reserve_a > 0 else 0.0
        spot_b_in_a = round(self.reserve_a / self.reserve_b, 8) if self.reserve_b > 0 else 0.0
        return {
            "pool_id": self.pool_id,
            "asset_a": self.asset_a,
            "asset_b": self.asset_b,
            "fee_bps": int(self.fee_bps),
            "reserve_a": int(self.reserve_a),
            "reserve_b": int(self.reserve_b),
            "reserve_a_float": from_base_units(self.reserve_a),
            "reserve_b_float": from_base_units(self.reserve_b),
            "total_lp": int(self.total_lp),
            "total_lp_float": from_base_units(self.total_lp),
            "spot_price_a_in_b": spot_a_in_b,
            "spot_price_b_in_a": spot_b_in_a,
            "lp_balances": {str(k): int(v) for k, v in self.lp_balances.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pool":
        return cls(
            asset_a=str(d["asset_a"]),
            asset_b=str(d["asset_b"]),
            fee_bps=int(d.get("fee_bps", 10)),
            reserve_a=int(d.get("reserve_a", 0)),
            reserve_b=int(d.get("reserve_b", 0)),
            total_lp=int(d.get("total_lp", 0)),
            lp_balances={str(k): int(v) for k, v in (d.get("lp_balances") or {}).items()},
        )


class UnivaDEX:
    def __init__(self, blockchain=None, state_path: Optional[str] = None):
        self._lock = threading.RLock()
        self.balances: Dict[str, Dict[str, int]] = {}
        self.test_balances: Dict[str, Dict[str, int]] = {}
        self.univa_net_deltas: Dict[str, int] = {}
        self.pools: Dict[str, Pool] = {}
        self.user_nonces: Dict[str, int] = {}
        self.used_signatures: set = set()
        self.history: List[dict] = []
        self.blockchain = None
        self.state_path: Optional[str] = state_path
        if blockchain is not None:
            self.attach_blockchain(blockchain, state_path=state_path)
        elif state_path and os.path.exists(state_path):
            self.load(state_path)

    def attach_blockchain(self, blockchain, state_path: Optional[str] = None):
        with self._lock:
            self.blockchain = blockchain
            if blockchain is not None:
                blockchain.dex_state = self
            if state_path is not None:
                self.state_path = state_path
            if self.state_path and os.path.exists(self.state_path):
                self.load(self.state_path)

    @staticmethod
    def _asset(asset: str) -> str:
        if not isinstance(asset, str) or not asset.strip():
            raise ValueError("Asset symbol is required")
        cleaned = asset.strip().upper()
        return "uUSD" if cleaned == "UUSD" else cleaned

    def _norm_user(self, user: str) -> str:
        if not isinstance(user, str):
            return ""
        s = user.strip()
        if s in (GENESIS_POOL_PROVIDER, LOCKED_LP, "DEAD_ADDRESS"):
            return s
        if self.blockchain is not None:
            from core.wallet import normalize_address
            return normalize_address(s)
        return s

    @staticmethod
    def _pool_key(asset_a: str, asset_b: str) -> str:
        return "/".join(sorted((asset_a, asset_b), key=str.lower))

    def get_univa_net_delta_float(self, user: str) -> float:
        norm = self._norm_user(user)
        return from_base_units(self.univa_net_deltas.get(norm, 0))

    def get_user_nonce(self, user: str) -> int:
        return int(self.user_nonces.get(self._norm_user(user), 0))

    def deposit(self, user: str, asset: str, amount: int, sandbox: bool = False) -> None:
        if not user or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("User and positive integer amount required")
        norm = self._norm_user(user)
        asset_name = self._asset(asset)
        with self._lock:
            store = self.test_balances if sandbox else self.balances
            acct = store.setdefault(norm, {})
            acct[asset_name] = acct.get(asset_name, 0) + amount
            if not sandbox and self.state_path:
                self.save(self.state_path)

    def set_balance(self, user: str, asset: str, amount: int, sandbox: bool = False) -> None:
        if not user or not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise ValueError("User and non-negative integer amount required")
        norm = self._norm_user(user)
        asset_name = self._asset(asset)
        with self._lock:
            store = self.test_balances if sandbox else self.balances
            acct = store.setdefault(norm, {})
            acct[asset_name] = int(amount)
            if not sandbox and self.state_path:
                self.save(self.state_path)

    def get_balance(self, user: str, asset: str, sandbox: bool = False) -> int:
        norm = self._norm_user(user)
        asset_name = self._asset(asset)
        if sandbox:
            return int(self.test_balances.get(norm, {}).get(asset_name, 0))
        if (
            self.blockchain is not None
            and asset_name == "UNIVA"
            and norm != GENESIS_POOL_PROVIDER
        ):
            l1_bal = float(self.blockchain.get_balance(user, "UNIVA"))
            if l1_bal <= 0:
                return 0
            return to_base_units(f"{l1_bal:.8f}")
        return int(self.balances.get(norm, {}).get(asset_name, 0))

    def _debit_asset(self, user: str, asset_name: str, amount: int) -> None:
        norm = self._norm_user(user)
        if amount <= 0:
            return
        if self.get_balance(user, asset_name) < amount:
            raise ValueError(f"Insufficient {asset_name} balance")
        if (
            self.blockchain is not None
            and asset_name == "UNIVA"
            and norm != GENESIS_POOL_PROVIDER
        ):
            self.univa_net_deltas[norm] = self.univa_net_deltas.get(norm, 0) - int(amount)
        else:
            acct = self.balances.setdefault(norm, {})
            acct[asset_name] = acct.get(asset_name, 0) - int(amount)

    def _credit_asset(self, user: str, asset_name: str, amount: int) -> None:
        norm = self._norm_user(user)
        if amount <= 0:
            return
        if (
            self.blockchain is not None
            and asset_name == "UNIVA"
            and norm != GENESIS_POOL_PROVIDER
        ):
            self.univa_net_deltas[norm] = self.univa_net_deltas.get(norm, 0) + int(amount)
        else:
            acct = self.balances.setdefault(norm, {})
            acct[asset_name] = acct.get(asset_name, 0) + int(amount)

    def _pool(self, asset_a: str, asset_b: str) -> Pool:
        a, b = self._asset(asset_a), self._asset(asset_b)
        if a == b:
            raise ValueError("Pool assets must be different")
        key = self._pool_key(a, b)
        pool = self.pools.get(key)
        if pool is None:
            raise ValueError("Pool does not exist")
        return pool

    def get_pool(self, asset_a: str, asset_b: str) -> Optional[Pool]:
        try:
            a, b = self._asset(asset_a), self._asset(asset_b)
            if a == b:
                return None
            return self.pools.get(self._pool_key(a, b))
        except Exception:
            return None

    def create_pool(self, asset_a: str, asset_b: str, fee_bps: int = 10) -> Pool:
        a, b = self._asset(asset_a), self._asset(asset_b)
        if a == b:
            raise ValueError("Pool assets must be different")
        if not isinstance(fee_bps, int) or isinstance(fee_bps, bool) or not (0 <= fee_bps < BPS):
            raise ValueError("fee_bps must be an integer from 0 to 9999")
        key = self._pool_key(a, b)
        with self._lock:
            if key in self.pools:
                raise ValueError("Pool already exists")
            pool = Pool(a, b, fee_bps)
            self.pools[key] = pool
            if self.state_path:
                self.save(self.state_path)
            return pool

    def _resolve_pool(self, asset_a: str, asset_b: str) -> Pool:
        p = self._pool(asset_a, asset_b)
        if {p.asset_a, p.asset_b} != {self._asset(asset_a), self._asset(asset_b)}:
            raise ValueError("Pool asset mismatch")
        return p

    def add_liquidity(
        self,
        provider: str,
        asset_a: str,
        asset_b: str,
        amount_a: int,
        amount_b: int,
    ) -> int:
        if (
            not provider
            or not isinstance(amount_a, int)
            or isinstance(amount_a, bool)
            or not isinstance(amount_b, int)
            or isinstance(amount_b, bool)
            or amount_a <= 0
            or amount_b <= 0
        ):
            raise ValueError("Positive integer amounts and provider are required")
        with self._lock:
            p = self._resolve_pool(asset_a, asset_b)
            a, b = self._asset(asset_a), self._asset(asset_b)
            norm = self._norm_user(provider)
            if self.get_balance(norm, a) < amount_a or self.get_balance(norm, b) < amount_b:
                raise ValueError("Insufficient balance for liquidity")

            if a == p.asset_a:
                pool_a, pool_b = amount_a, amount_b
            else:
                pool_a, pool_b = amount_b, amount_a

            if p.reserve_a == 0 and p.reserve_b == 0:
                minted = isqrt(pool_a * pool_b)
                if minted <= MINIMUM_LIQUIDITY:
                    raise ValueError("Initial liquidity too small")
                used_a, used_b = pool_a, pool_b
                provider_lp = minted - MINIMUM_LIQUIDITY
                new_total_lp = minted
            else:
                if p.reserve_a <= 0 or p.reserve_b <= 0:
                    raise ValueError("Invalid pool reserves")
                used_a = min(pool_a, pool_b * p.reserve_a // p.reserve_b)
                used_b = min(pool_b, pool_a * p.reserve_b // p.reserve_a)
                minted = min(
                    used_a * p.total_lp // p.reserve_a,
                    used_b * p.total_lp // p.reserve_b,
                )
                if minted <= 0 or used_a <= 0 or used_b <= 0:
                    raise ValueError("Liquidity contribution too small")
                provider_lp = minted
                new_total_lp = p.total_lp + minted

            if a == p.asset_a:
                user_used_a, user_used_b = used_a, used_b
            else:
                user_used_a, user_used_b = used_b, used_a

            if self.get_balance(norm, a) < user_used_a or self.get_balance(norm, b) < user_used_b:
                raise ValueError("Insufficient balance for liquidity")

            self._debit_asset(norm, a, user_used_a)
            self._debit_asset(norm, b, user_used_b)

            if p.reserve_a == 0 and p.reserve_b == 0:
                p.lp_balances[LOCKED_LP] = MINIMUM_LIQUIDITY
            p.total_lp = new_total_lp
            p.reserve_a += used_a
            p.reserve_b += used_b
            p.lp_balances[norm] = p.lp_balances.get(norm, 0) + provider_lp

            if self.state_path:
                self.save(self.state_path)
            return provider_lp

    def get_amount_out(self, pool: Pool, asset_in: str, amount_in: int) -> Tuple[int, int]:
        if not isinstance(amount_in, int) or isinstance(amount_in, bool) or amount_in <= 0:
            raise ValueError("amount_in must be a positive integer")
        a_in = self._asset(asset_in)
        if a_in == pool.asset_a:
            reserve_in, reserve_out = pool.reserve_a, pool.reserve_b
        elif a_in == pool.asset_b:
            reserve_in, reserve_out = pool.reserve_b, pool.reserve_a
        else:
            raise ValueError("Input asset is not in this pool")
        if reserve_in <= 0 or reserve_out <= 0:
            raise ValueError("Insufficient pool liquidity")
        fee = amount_in * pool.fee_bps // BPS
        amount_after_fee = amount_in - fee
        if amount_after_fee <= 0:
            raise ValueError("Input is too small after fee")
        amount_out = (amount_after_fee * reserve_out) // (reserve_in + amount_after_fee)
        if amount_out <= 0 or amount_out >= reserve_out:
            raise ValueError("Insufficient output liquidity")
        return amount_out, fee

    def get_quote_details(self, asset_in: str, asset_out: str, amount_in: int) -> dict:
        p = self._resolve_pool(asset_in, asset_out)
        a_in = self._asset(asset_in)
        a_out = self._asset(asset_out)
        if a_in == a_out:
            raise ValueError("Input and output assets must differ")
        amount_out, fee = self.get_amount_out(p, a_in, amount_in)
        if a_in == p.asset_a:
            res_in, res_out = p.reserve_a, p.reserve_b
        else:
            res_in, res_out = p.reserve_b, p.reserve_a
        spot_before = res_out / res_in if res_in > 0 else 0.0
        spot_after = (res_out - amount_out) / (res_in + amount_in)
        effective_price = amount_out / amount_in if amount_in > 0 else 0.0
        price_impact_pct = (
            max(0.0, (spot_before - effective_price) / spot_before * 100.0)
            if spot_before > 0
            else 0.0
        )
        return {
            "pool_id": p.pool_id,
            "asset_in": a_in,
            "asset_out": a_out,
            "amount_in": int(amount_in),
            "amount_out": int(amount_out),
            "fee": int(fee),
            "fee_bps": int(p.fee_bps),
            "spot_price_before": round(spot_before, 8),
            "spot_price_after": round(spot_after, 8),
            "effective_price": round(effective_price, 8),
            "price_impact_pct": round(price_impact_pct, 4),
        }

    def swap(
        self,
        user: str,
        asset_in: str,
        asset_out: str,
        amount_in: int,
        min_amount_out: int = 0,
    ) -> int:
        if not user:
            raise ValueError("User address is required")
        with self._lock:
            p = self._resolve_pool(asset_in, asset_out)
            a_in, a_out = self._asset(asset_in), self._asset(asset_out)
            norm = self._norm_user(user)
            if a_in == a_out:
                raise ValueError("Input and output assets must differ")
            if (
                not isinstance(min_amount_out, int)
                or isinstance(min_amount_out, bool)
                or min_amount_out < 0
            ):
                raise ValueError("min_amount_out must be a non-negative integer")
            if self.get_balance(norm, a_in) < amount_in:
                raise ValueError("Insufficient balance")
            amount_out, _fee = self.get_amount_out(p, a_in, amount_in)
            if amount_out < min_amount_out:
                raise ValueError("Slippage: output below min_amount_out")

            self._debit_asset(norm, a_in, amount_in)
            self._credit_asset(norm, a_out, amount_out)
            if a_in == p.asset_a:
                p.reserve_a += amount_in
                p.reserve_b -= amount_out
            else:
                p.reserve_b += amount_in
                p.reserve_a -= amount_out

            if self.state_path:
                self.save(self.state_path)
            return amount_out

    def remove_liquidity(
        self,
        provider: str,
        asset_a: str,
        asset_b: str,
        lp_tokens_to_burn: int,
    ) -> Tuple[int, int]:
        if not provider:
            raise ValueError("Provider is required")
        with self._lock:
            p = self._resolve_pool(asset_a, asset_b)
            norm = self._norm_user(provider)
            if (
                not isinstance(lp_tokens_to_burn, int)
                or isinstance(lp_tokens_to_burn, bool)
                or lp_tokens_to_burn <= 0
            ):
                raise ValueError("LP amount must be positive")
            if norm == LOCKED_LP or provider == LOCKED_LP:
                raise ValueError("Minimum liquidity is permanently locked")
            owned = p.lp_balances.get(norm, 0)
            if lp_tokens_to_burn > owned:
                raise ValueError("Insufficient LP balance")
            if p.total_lp <= 0:
                raise ValueError("No LP supply")
            amount_a = lp_tokens_to_burn * p.reserve_a // p.total_lp
            amount_b = lp_tokens_to_burn * p.reserve_b // p.total_lp
            if amount_a <= 0 or amount_b <= 0:
                raise ValueError("LP amount too small to withdraw")
            p.lp_balances[norm] = owned - lp_tokens_to_burn
            p.total_lp -= lp_tokens_to_burn
            p.reserve_a -= amount_a
            p.reserve_b -= amount_b
            self._credit_asset(norm, p.asset_a, amount_a)
            self._credit_asset(norm, p.asset_b, amount_b)

            if self.state_path:
                self.save(self.state_path)
            if self._asset(asset_a) == p.asset_a:
                return amount_a, amount_b
            return amount_b, amount_a

    def record_signed_operation(
        self,
        op_type: str,
        user: str,
        public_key: str,
        signature: str,
        payload: dict,
        nonce: Optional[int] = None,
    ) -> dict:
        with self._lock:
            norm = self._norm_user(user)
            ts = time.time()
            block_h = self.blockchain.height if self.blockchain is not None else 0
            op_id = hashlib.sha256(
                f"{op_type}|{norm}|{signature}|{ts}".encode("utf-8")
            ).hexdigest()
            self.used_signatures.add(signature)
            expected_nonce = self.user_nonces.get(norm, 0)
            self.user_nonces[norm] = (
                int(nonce) + 1 if nonce is not None else expected_nonce + 1
            )
            record = {
                "op_id": op_id,
                "type": op_type,
                "user": norm,
                "public_key": public_key,
                "signature": signature,
                "nonce": expected_nonce if nonce is None else int(nonce),
                "block_height": block_h,
                "timestamp": ts,
                "payload": dict(payload),
                "state_root": self.calculate_state_root(),
            }
            self.history.append(record)
            if len(self.history) > 1000:
                self.history = self.history[-1000:]
            if self.state_path:
                self.save(self.state_path)
            return record

    def calculate_state_root(self) -> str:
        with self._lock:
            state_obj = {
                "pools": {k: self.pools[k].to_dict() for k in sorted(self.pools.keys())},
                "balances": {
                    u: {a: self.balances[u][a] for a in sorted(self.balances[u].keys())}
                    for u in sorted(self.balances.keys())
                },
                "univa_net_deltas": {
                    u: self.univa_net_deltas[u] for u in sorted(self.univa_net_deltas.keys())
                },
                "user_nonces": {
                    u: self.user_nonces[u] for u in sorted(self.user_nonces.keys())
                },
            }
            canonical = json.dumps(state_obj, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "version": 2,
                "state_root": self.calculate_state_root(),
                "pools": {k: p.to_dict() for k, p in self.pools.items()},
                "balances": {
                    str(u): {str(a): int(v) for a, v in assets.items()}
                    for u, assets in self.balances.items()
                },
                "univa_net_deltas": {
                    str(u): int(v) for u, v in self.univa_net_deltas.items()
                },
                "user_nonces": {str(u): int(v) for u, v in self.user_nonces.items()},
                "used_signatures": sorted(self.used_signatures)[-5000:],
                "history": list(self.history[-1000:]),
            }

    @classmethod
    def from_dict(
        cls,
        d: dict,
        blockchain=None,
        state_path: Optional[str] = None,
    ) -> "UnivaDEX":
        inst = cls(blockchain=None, state_path=state_path)
        inst._apply_state_dict(d)
        if blockchain is not None:
            inst.blockchain = blockchain
            blockchain.dex_state = inst
        return inst

    def _apply_state_dict(self, d: dict) -> None:
        self.pools = {
            str(k): Pool.from_dict(v) for k, v in (d.get("pools") or {}).items()
        }
        self.balances = {
            str(u): {str(a): int(v) for a, v in (assets or {}).items()}
            for u, assets in (d.get("balances") or {}).items()
        }
        self.univa_net_deltas = {
            str(u): int(v) for u, v in (d.get("univa_net_deltas") or {}).items()
        }
        self.user_nonces = {
            str(u): int(v) for u, v in (d.get("user_nonces") or {}).items()
        }
        self.used_signatures = set(str(s) for s in (d.get("used_signatures") or []))
        self.history = list(d.get("history") or [])

    def save(self, path: Optional[str] = None) -> bool:
        target = path or self.state_path or DEX_STATE_FILE
        with self._lock:
            try:
                if os.path.exists(target):
                    try:
                        shutil.copyfile(target, target + ".bak")
                    except Exception:
                        pass
                tmp_path = target + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, target)
                return True
            except Exception:
                return False

    def load(self, path: Optional[str] = None) -> bool:
        target = path or self.state_path or DEX_STATE_FILE
        with self._lock:
            for candidate in (target, target + ".bak"):
                if not os.path.exists(candidate):
                    continue
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict) or "pools" not in data:
                        continue
                    self._apply_state_dict(data)
                    return True
                except Exception:
                    continue
            return False
