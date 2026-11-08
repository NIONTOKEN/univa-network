"""UNIVA Native DEX reference implementation for local testnet experiments.

This is an in-process AMM simulation, not yet a consensus-integrated on-chain DEX.
All amounts are integer base units (1 UNIVA = 10**8 units); no float math is used
inside pool accounting.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from math import isqrt
from typing import Dict, Tuple

UNIT = 100_000_000
MINIMUM_LIQUIDITY = 1_000
BPS = 10_000
LOCKED_LP = "0x000_LOCKED"


def to_base_units(value) -> int:
    try:
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


class UnivaDEX:
    def __init__(self):
        self.balances: Dict[Tuple[str, str], int] = {}
        self.pools: Dict[str, Pool] = {}

    @staticmethod
    def _asset(asset: str) -> str:
        if not isinstance(asset, str) or not asset.strip():
            raise ValueError("Asset symbol is required")
        return asset.strip().upper() if asset.strip().upper() != "UUSD" else "uUSD"

    def deposit(self, user: str, asset: str, amount: int) -> None:
        if not user or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("User and positive integer amount required")
        asset = self._asset(asset)
        key = (user, asset)
        self.balances[key] = self.balances.get(key, 0) + amount

    def get_balance(self, user: str, asset: str) -> int:
        return self.balances.get((user, self._asset(asset)), 0)

    def _pool(self, asset_a: str, asset_b: str) -> Pool:
        a, b = self._asset(asset_a), self._asset(asset_b)
        if a == b:
            raise ValueError("Pool assets must be different")
        key = "/".join(sorted((a, b), key=str.lower))
        pool = self.pools.get(key)
        if pool is None:
            raise ValueError("Pool does not exist")
        return pool

    def create_pool(self, asset_a: str, asset_b: str, fee_bps: int = 10) -> Pool:
        a, b = self._asset(asset_a), self._asset(asset_b)
        if a == b:
            raise ValueError("Pool assets must be different")
        if not isinstance(fee_bps, int) or not (0 <= fee_bps < BPS):
            raise ValueError("fee_bps must be an integer from 0 to 9999")
        key = "/".join(sorted((a, b), key=str.lower))
        if key in self.pools:
            raise ValueError("Pool already exists")
        # Keep the pool's asset order exactly as requested for caller compatibility.
        pool = Pool(a, b, fee_bps)
        self.pools[key] = pool
        return pool

    def _resolve_pool(self, asset_a: str, asset_b: str) -> Pool:
        p = self._pool(asset_a, asset_b)
        if {p.asset_a, p.asset_b} != {self._asset(asset_a), self._asset(asset_b)}:
            raise ValueError("Pool asset mismatch")
        return p

    def add_liquidity(self, provider: str, asset_a: str, asset_b: str,
                      amount_a: int, amount_b: int) -> int:
        p = self._resolve_pool(asset_a, asset_b)
        if (not provider or not isinstance(amount_a, int) or isinstance(amount_a, bool)
                or not isinstance(amount_b, int) or isinstance(amount_b, bool)
                or amount_a <= 0 or amount_b <= 0):
            raise ValueError("Positive integer amounts and provider are required")
        a, b = self._asset(asset_a), self._asset(asset_b)
        if self.get_balance(provider, a) < amount_a or self.get_balance(provider, b) < amount_b:
            raise ValueError("Insufficient balance for liquidity")
        # Convert caller order to the pool's immutable reserve order.
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
            p.lp_balances[LOCKED_LP] = MINIMUM_LIQUIDITY
            p.total_lp = minted
        else:
            if p.reserve_a <= 0 or p.reserve_b <= 0:
                raise ValueError("Invalid pool reserves")
            used_a = min(pool_a, pool_b * p.reserve_a // p.reserve_b)
            used_b = min(pool_b, pool_a * p.reserve_b // p.reserve_a)
            minted = min(used_a * p.total_lp // p.reserve_a,
                         used_b * p.total_lp // p.reserve_b)
            if minted <= 0 or used_a <= 0 or used_b <= 0:
                raise ValueError("Liquidity contribution too small")
            provider_lp = minted
            p.total_lp += minted
        # Convert actual used amounts back to caller order before debiting balances.
        if a == p.asset_a:
            user_used_a, user_used_b = used_a, used_b
        else:
            user_used_a, user_used_b = used_b, used_a
        self.balances[(provider, a)] -= user_used_a
        self.balances[(provider, b)] -= user_used_b
        p.reserve_a += used_a
        p.reserve_b += used_b
        p.lp_balances[provider] = p.lp_balances.get(provider, 0) + provider_lp
        return provider_lp

    def get_amount_out(self, pool: Pool, asset_in: str, amount_in: int):
        if not isinstance(amount_in, int) or amount_in <= 0:
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

    def swap(self, user: str, asset_in: str, asset_out: str, amount_in: int,
             min_amount_out: int = 0) -> int:
        p = self._resolve_pool(asset_in, asset_out)
        a_in, a_out = self._asset(asset_in), self._asset(asset_out)
        if a_in == a_out:
            raise ValueError("Input and output assets must differ")
        if not isinstance(min_amount_out, int) or min_amount_out < 0:
            raise ValueError("min_amount_out must be a non-negative integer")
        if self.get_balance(user, a_in) < amount_in:
            raise ValueError("Insufficient balance")
        amount_out, _fee = self.get_amount_out(p, a_in, amount_in)
        if amount_out < min_amount_out:
            raise ValueError("Slippage: output below min_amount_out")
        # No mutation occurs until every validation above succeeds.
        self.balances[(user, a_in)] -= amount_in
        self.balances[(user, a_out)] = self.balances.get((user, a_out), 0) + amount_out
        if a_in == p.asset_a:
            p.reserve_a += amount_in
            p.reserve_b -= amount_out
        else:
            p.reserve_b += amount_in
            p.reserve_a -= amount_out
        return amount_out

    def remove_liquidity(self, provider: str, asset_a: str, asset_b: str,
                         lp_tokens_to_burn: int):
        p = self._resolve_pool(asset_a, asset_b)
        if not isinstance(lp_tokens_to_burn, int) or lp_tokens_to_burn <= 0:
            raise ValueError("LP amount must be positive")
        if provider == LOCKED_LP:
            raise ValueError("Minimum liquidity is permanently locked")
        owned = p.lp_balances.get(provider, 0)
        if lp_tokens_to_burn > owned:
            raise ValueError("Insufficient LP balance")
        if p.total_lp <= 0:
            raise ValueError("No LP supply")
        amount_a = lp_tokens_to_burn * p.reserve_a // p.total_lp
        amount_b = lp_tokens_to_burn * p.reserve_b // p.total_lp
        if amount_a <= 0 or amount_b <= 0:
            raise ValueError("LP amount too small to withdraw")
        p.lp_balances[provider] = owned - lp_tokens_to_burn
        p.total_lp -= lp_tokens_to_burn
        p.reserve_a -= amount_a
        p.reserve_b -= amount_b
        self.balances[(provider, p.asset_a)] = self.balances.get((provider, p.asset_a), 0) + amount_a
        self.balances[(provider, p.asset_b)] = self.balances.get((provider, p.asset_b), 0) + amount_b
        if self._asset(asset_a) == p.asset_a:
            return amount_a, amount_b
        return amount_b, amount_a
