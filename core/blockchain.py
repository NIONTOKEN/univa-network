"""
UNIVA Network - Core Blockchain Engine
SHA-256 Proof of Work - Layer 1
Genesis: 2026 - "UNIVA Network - Evrensel Ozgurluk Agi"

Ekonomi & Parametreler:
  - Ilk Blok Odulu : 100.0 UNIVA
  - Yarlanma       : Her ay (~43,200 blok = 30 gun * 24 saat * 60 dk)
  - Hedef Sure     : 60 saniye / blok
  - Maksimum Arz   : 21,000,001.0 UNIVA
  - Adres Formati  : univa......univa (Tam 16 karakter - 887.5M Kapasite)
  - Kalici Guvenlik: Asla veri silmez, otomatik yedekleme (.bak) yapar.
"""

import os
import shutil
import hashlib
import json
import time
import threading
from typing import List, Optional

NETWORK_NAME       = "UNIVA Network"
TICKER             = "UNIVA"
ADDRESS_FORMAT     = "univa..........univa"
TOTAL_ADDR_LENGTH  = 20

MAX_SUPPLY         = 21_000_001.0
INITIAL_REWARD     = 100.0
TARGET_BLOCK_TIME  = 60
HALVING_INTERVAL   = 43_200
DIFFICULTY_ADJUST  = 60
INITIAL_DIFF       = 4

GENESIS_MESSAGE    = "UNIVA Network 2026 - Tum Aglar Tek Cati Altinda - Evrensel Ozgurluk Agi"
GENESIS_MINER      = "univa0000000000univa"  # 20 karakter standart genesis adresi
GENESIS_TIME       = 1735689600.0
VERSION            = "3.0.0"
CHAIN_FILE_PATH    = "univa_chain.json"


def calculate_merkle_root(transactions: list) -> str:
    if not transactions:
        return "0" * 64
    
    tx_hashes = []
    for tx in transactions:
        tx_str = json.dumps(tx, sort_keys=True)
        tx_hashes.append(hashlib.sha256(tx_str.encode("utf-8")).hexdigest())

    while len(tx_hashes) > 1:
        if len(tx_hashes) % 2 != 0:
            tx_hashes.append(tx_hashes[-1])
        new_level = []
        for i in range(0, len(tx_hashes), 2):
            combined = tx_hashes[i] + tx_hashes[i + 1]
            parent_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
            new_level.append(parent_hash)
        tx_hashes = new_level

    return tx_hashes[0]


class Block:
    def __init__(
        self,
        index: int,
        transactions: list,
        previous_hash: str,
        timestamp: float = None,
        nonce: int = 0,
        difficulty: int = INITIAL_DIFF,
        miner_address: str = "",
        reward: float = 0.0,
        merkle_root: str = None,
    ):
        self.index         = index
        self.timestamp     = timestamp or time.time()
        self.transactions  = transactions
        self.previous_hash = previous_hash
        self.nonce         = nonce
        self.difficulty    = difficulty
        self.miner_address = miner_address
        self.reward        = reward
        self.merkle_root   = merkle_root or calculate_merkle_root(transactions)
        self.hash          = self.calculate_hash()

    def calculate_hash(self) -> str:
        data = json.dumps({
            "index":         self.index,
            "timestamp":     self.timestamp,
            "merkle_root":   self.merkle_root,
            "previous_hash": self.previous_hash,
            "nonce":         self.nonce,
            "difficulty":    self.difficulty,
            "miner_address": self.miner_address,
            "reward":        self.reward,
        }, sort_keys=True)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def mine(self, difficulty: int, stop_event=None) -> bool:
        target = "0" * difficulty
        self.nonce = 0
        while not self.hash.startswith(target):
            if stop_event and stop_event.is_set():
                return False
            self.nonce += 1
            self.hash = self.calculate_hash()
        return True

    def to_dict(self) -> dict:
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "merkle_root":   self.merkle_root,
            "transactions":  self.transactions,
            "previous_hash": self.previous_hash,
            "nonce":         self.nonce,
            "difficulty":    self.difficulty,
            "miner_address": self.miner_address,
            "reward":        self.reward,
            "hash":          self.hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        b = cls(
            index         = d["index"],
            transactions  = d["transactions"],
            previous_hash = d["previous_hash"],
            timestamp     = d["timestamp"],
            nonce         = d["nonce"],
            difficulty    = d["difficulty"],
            miner_address = d.get("miner_address", ""),
            reward        = d.get("reward", 0.0),
            merkle_root   = d.get("merkle_root"),
        )
        b.hash = d["hash"]
        return b


class Blockchain:
    def __init__(self, auto_load_path: str = CHAIN_FILE_PATH, network: Optional[str] = None):
        from core.config import get_network_config
        cfg = get_network_config(network)
        self._lock                = threading.RLock()
        self.network              = cfg["network"]
        self.chain_id             = cfg["chain_id"]
        self.genesis_message      = cfg["genesis_message"]
        self.genesis_time         = cfg["genesis_time"]
        self.genesis_miner        = cfg["genesis_miner"]
        self.chain: List[Block]   = []
        self.pending_transactions = []
        self.difficulty           = INITIAL_DIFF
        self.total_mined          = 0.0
        self.peer_count           = 0
        self.custom_balances      = {} # Token/Asset balances
        self.dex_state            = None # Injected by DEX engine
        self._validating_chain    = False

        # Guvenli Baslatma: Eger diskte zincir varsa ASLA SIFIRLAMA, dogrudan yukle!
        if auto_load_path and os.path.exists(auto_load_path):
            loaded = self.load(auto_load_path)
            if not loaded or len(self.chain) == 0:
                self._create_genesis_block()
        else:
            self._create_genesis_block()

    def _create_genesis_block(self):
        genesis_tx = [{
            "type":      "genesis",
            "message":   self.genesis_message,
            "timestamp": self.genesis_time,
            "to":        self.genesis_miner,
            "amount":    0.0,
        }]
        genesis = Block(
            index          = 0,
            transactions   = genesis_tx,
            previous_hash  = "0" * 64,
            timestamp      = self.genesis_time,
            nonce          = 0,
            difficulty     = 1,
            miner_address  = self.genesis_miner,
            reward         = 0.0,
        )
        genesis.hash = genesis.calculate_hash()
        self.chain = [genesis]

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    @property
    def height(self) -> int:
        return len(self.chain) - 1

    def get_current_reward(self, block_index: int = None) -> float:
        idx = block_index if block_index is not None else (self.height + 1)
        halvings = idx // HALVING_INTERVAL
        reward = INITIAL_REWARD / (2 ** halvings)
        remaining = MAX_SUPPLY - self.total_mined
        return round(max(0.0, min(reward, remaining)), 8)

    def get_median_time_past(self, n: int = 11) -> float:
        """
        MTP - Median Time Past (Bitcoin BIP-113):
        Son N bloğun zaman damgasının medyanını döndürür.
        Yeni bloklar bu değerden büyük bir timestamp'e sahip olmak ZORUNDA.
        """
        recent = self.chain[-n:] if len(self.chain) >= n else self.chain[:]
        if not recent:
            return 0.0
        timestamps = sorted(b.timestamp for b in recent)
        mid = len(timestamps) // 2
        return timestamps[mid]

    def _confirmed_tx_ids(self):
        return {tx.get("tx_id") for block in self.chain for tx in block.transactions if tx.get("tx_id")}

    def _account_nonce(self, address: str) -> int:
        from core.transaction import NONCE_TX_TYPES
        from core.wallet import normalize_address
        norm = normalize_address(address)
        return sum(
            1
            for block in self.chain
            for tx in block.transactions
            if tx.get("type", "transfer") in NONCE_TX_TYPES
            and normalize_address(tx.get("from", "")) == norm
        )

    def _pending_nonce(self, address: str) -> int:
        from core.transaction import NONCE_TX_TYPES
        from core.wallet import normalize_address
        norm = normalize_address(address)
        return self._account_nonce(norm) + sum(
            1
            for tx in self.pending_transactions
            if tx.get("type", "transfer") in NONCE_TX_TYPES
            and normalize_address(tx.get("from", "")) == norm
        )

    @staticmethod
    def _canonical_tx_message(tx: dict) -> str:
        from core.transaction import canonical_tx_message
        return canonical_tx_message(tx)

    def get_onchain_reservations(
        self,
        include_pending: bool = True,
        at_timestamp: Optional[float] = None,
    ) -> dict:
        """Compute deterministic on-chain offline_reserve / offline_spend / offline_release escrow state."""
        from core.transaction import derive_reservation_id
        from core.wallet import normalize_address

        eff_ts = float(
            at_timestamp
            if at_timestamp is not None
            else max(time.time(), self.last_block.timestamp if self.chain else 0.0)
        )
        reservations: dict = {}

        def _apply(tx: dict, block_index: Optional[int]):
            tx_type = tx.get("type", "transfer")
            if tx_type == "offline_reserve":
                rid = tx.get("reservation_id") or derive_reservation_id(tx.get("tx_id", ""))
                reservations[rid] = {
                    "reservation_id": rid,
                    "owner": normalize_address(tx.get("from", "")),
                    "owner_raw": tx.get("from", ""),
                    "amount": round(float(tx.get("amount", 0.0)), 8),
                    "spent": 0.0,
                    "expires_at": int(tx.get("expires_at", 0)),
                    "released": False,
                    "confirmed": block_index is not None,
                    "block_index": block_index,
                    "tx_id": tx.get("tx_id", ""),
                    "used_voucher_nonces": set(),
                    "spend_tx_ids": [],
                }
            elif tx_type == "offline_spend":
                rid = str(tx.get("reservation_id") or "")
                rec = reservations.get(rid)
                if rec is not None:
                    cost = round(float(tx.get("amount", 0.0)) + float(tx.get("fee", 0.0)), 8)
                    rec["spent"] = round(rec["spent"] + cost, 8)
                    if "voucher_nonce" in tx:
                        rec["used_voucher_nonces"].add(int(tx["voucher_nonce"]))
                    if tx.get("tx_id"):
                        rec["spend_tx_ids"].append(tx["tx_id"])
            elif tx_type == "offline_release":
                rid = str(tx.get("reservation_id") or "")
                rec = reservations.get(rid)
                if rec is not None:
                    rec["released"] = True

        for blk in self.chain:
            for tx in blk.transactions:
                _apply(tx, blk.index)
        if include_pending:
            for tx in self.pending_transactions:
                _apply(tx, None)

        for rec in reservations.values():
            rem = round(max(0.0, rec["amount"] - rec["spent"]), 8)
            rec["remaining"] = rem
            if rec["released"]:
                rec["status"] = "released"
            elif eff_ts >= float(rec["expires_at"]):
                rec["status"] = "expired"
            elif rem <= 1e-8:
                rec["status"] = "exhausted"
            else:
                rec["status"] = "active"
        return reservations

    def _has_dex_transactions(self, include_pending: bool = True) -> bool:
        from core.transaction import DEX_TX_TYPES
        for b in self.chain:
            for tx in b.transactions:
                if tx.get("type") in DEX_TX_TYPES:
                    return True
        if include_pending:
            for tx in self.pending_transactions:
                if tx.get("type") in DEX_TX_TYPES:
                    return True
        return False

    @staticmethod
    def _apply_onchain_dex_tx(dex, univa_deltas: dict, tx: dict) -> dict:
        """Deterministically execute a single consensus DEX tx on a standalone integer UnivaDEX."""
        from core.dex import to_base_units
        from core.wallet import normalize_address

        tx_type = tx.get("type")
        user = normalize_address(tx.get("from", ""))
        if tx_type == "dex_swap":
            a_in = dex._asset(tx["asset_in"])
            a_out = dex._asset(tx["asset_out"])
            amt_in = to_base_units(tx["amount_in"])
            min_out = to_base_units(tx.get("min_out", 0.0))
            if a_in == "UNIVA":
                dex.deposit(user, "UNIVA", amt_in)
            out_base = dex.swap(user, a_in, a_out, amt_in, min_out)
            if a_in == "UNIVA":
                univa_deltas[user] = univa_deltas.get(user, 0) - amt_in
            if a_out == "UNIVA":
                cur_u = dex.get_balance(user, "UNIVA")
                dex.set_balance(user, "UNIVA", max(0, cur_u - out_base))
                univa_deltas[user] = univa_deltas.get(user, 0) + out_base
            return {"amount_out_base": out_base}

        if tx_type == "dex_add_liquidity":
            a = dex._asset(tx["asset_a"])
            b = dex._asset(tx["asset_b"])
            amt_a = to_base_units(tx["amount_a"])
            amt_b = to_base_units(tx["amount_b"])
            pre_u = dex.get_balance(user, "UNIVA")
            dep_u = 0
            if a == "UNIVA":
                dex.deposit(user, "UNIVA", amt_a)
                dep_u = amt_a
            elif b == "UNIVA":
                dex.deposit(user, "UNIVA", amt_b)
                dep_u = amt_b
            lp_minted = dex.add_liquidity(user, a, b, amt_a, amt_b)
            if dep_u > 0:
                rem_u = dex.get_balance(user, "UNIVA") - pre_u
                used_u = max(0, dep_u - max(0, rem_u))
                dex.set_balance(user, "UNIVA", pre_u)
                univa_deltas[user] = univa_deltas.get(user, 0) - used_u
            return {"lp_minted_base": lp_minted}

        if tx_type == "dex_remove_liquidity":
            a = dex._asset(tx["asset_a"])
            b = dex._asset(tx["asset_b"])
            lp_base = to_base_units(tx["lp_amount"])
            pre_u = dex.get_balance(user, "UNIVA")
            out_a, out_b = dex.remove_liquidity(user, a, b, lp_base)
            post_u = dex.get_balance(user, "UNIVA")
            if post_u > pre_u:
                gained_u = post_u - pre_u
                dex.set_balance(user, "UNIVA", pre_u)
                univa_deltas[user] = univa_deltas.get(user, 0) + gained_u
            return {"out_a_base": out_a, "out_b_base": out_b}

        raise ValueError(f"Unsupported DEX tx type: {tx_type}")

    def get_onchain_dex_state(self, include_pending: bool = True):
        """Deterministic replay of all confirmed (+ optional pending) consensus DEX transactions."""
        from core.dex import UnivaDEX, to_base_units, GENESIS_POOL_PROVIDER
        from core.transaction import DEX_TX_TYPES

        dex = UnivaDEX()
        dex.create_pool("UNIVA", "uUSD", fee_bps=10)
        dex.deposit(GENESIS_POOL_PROVIDER, "UNIVA", to_base_units(50_000.0))
        dex.deposit(GENESIS_POOL_PROVIDER, "uUSD", to_base_units(250_000.0))
        dex.add_liquidity(
            GENESIS_POOL_PROVIDER,
            "UNIVA",
            "uUSD",
            to_base_units(50_000.0),
            to_base_units(250_000.0),
        )
        univa_deltas: dict = {}
        for blk in self.chain:
            for tx in blk.transactions:
                if tx.get("type") in DEX_TX_TYPES:
                    self._apply_onchain_dex_tx(dex, univa_deltas, tx)
        if include_pending:
            for tx in self.pending_transactions:
                if tx.get("type") in DEX_TX_TYPES:
                    self._apply_onchain_dex_tx(dex, univa_deltas, tx)
        dex.univa_net_deltas = univa_deltas
        return dex

    def verify_transaction(
        self,
        tx: dict,
        include_pending: bool = True,
        block_timestamp: Optional[float] = None,
    ) -> bool:
        """Validate a signed L1 tx (transfer, offline escrow, and on-chain DEX)."""
        from core.transaction import (
            SUPPORTED_TX_TYPES,
            NONCE_TX_TYPES,
            DEX_TX_TYPES,
            derive_reservation_id,
            verify_transaction as stateless_verify_tx,
        )
        from core.wallet import normalize_address

        if not isinstance(tx, dict):
            return False
        tx_type = tx.get("type", "transfer")
        if tx_type not in SUPPORTED_TX_TYPES:
            return False
        if not stateless_verify_tx(tx, network=self.network):
            return False
        try:
            tx_id = tx["tx_id"]
            if tx_id in self._confirmed_tx_ids():
                return False

            eff_ts = float(
                block_timestamp
                if block_timestamp is not None
                else max(time.time(), self.last_block.timestamp if self.chain else 0.0)
            )
            sender_norm = normalize_address(tx["from"])

            if tx_type in NONCE_TX_TYPES:
                expected_nonce = (
                    self._pending_nonce(tx["from"]) if include_pending else self._account_nonce(tx["from"])
                )
                if tx["nonce"] != expected_nonce:
                    return False

            if tx_type == "transfer":
                amount, fee = float(tx["amount"]), float(tx["fee"])
                available = self.get_balance(
                    tx["from"], include_pending_outgoing=include_pending, at_timestamp=eff_ts
                )
                return available + 1e-8 >= amount + fee

            if tx_type == "offline_reserve":
                amount, fee = float(tx["amount"]), float(tx["fee"])
                if int(tx["expires_at"]) <= int(eff_ts):
                    return False
                rid = tx.get("reservation_id") or derive_reservation_id(tx_id)
                existing_res = self.get_onchain_reservations(include_pending=include_pending, at_timestamp=eff_ts)
                if rid in existing_res:
                    return False
                available = self.get_balance(
                    tx["from"], include_pending_outgoing=include_pending, at_timestamp=eff_ts
                )
                return available + 1e-8 >= amount + fee

            if tx_type == "offline_spend":
                rid = str(tx["reservation_id"])
                amount, fee = float(tx["amount"]), float(tx["fee"])
                v_nonce = int(tx["voucher_nonce"])
                v_exp = int(tx["expires_at"])
                res_map = self.get_onchain_reservations(include_pending=include_pending, at_timestamp=eff_ts)
                rec = res_map.get(rid)
                # Reservation MUST be confirmed on-chain before offline spends can settle against it
                if rec is None or not rec.get("confirmed"):
                    return False
                if rec["owner"] != sender_norm:
                    return False
                if rec["released"]:
                    return False
                if eff_ts >= float(rec["expires_at"]) or eff_ts >= float(v_exp):
                    return False
                if v_nonce in rec["used_voucher_nonces"]:
                    return False
                return rec["remaining"] + 1e-8 >= round(amount + fee, 8)

            if tx_type == "offline_release":
                rid = str(tx["reservation_id"])
                fee = float(tx["fee"])
                res_map = self.get_onchain_reservations(include_pending=include_pending, at_timestamp=eff_ts)
                rec = res_map.get(rid)
                if rec is None or not rec.get("confirmed"):
                    return False
                if rec["owner"] != sender_norm:
                    return False
                if rec["released"]:
                    return False
                available = self.get_balance(
                    tx["from"], include_pending_outgoing=include_pending, at_timestamp=eff_ts
                )
                return available + 1e-8 >= fee

            if tx_type in DEX_TX_TYPES:
                fee = float(tx["fee"])
                available_univa = self.get_balance(
                    tx["from"], "UNIVA", include_pending_outgoing=include_pending, at_timestamp=eff_ts
                )
                if available_univa + 1e-8 < fee:
                    return False
                dex = self.get_onchain_dex_state(include_pending=include_pending)
                if tx_type == "dex_swap":
                    if dex._asset(tx["asset_in"]) == "UNIVA":
                        if available_univa + 1e-8 < fee + float(tx["amount_in"]):
                            return False
                elif tx_type == "dex_add_liquidity":
                    a, b = dex._asset(tx["asset_a"]), dex._asset(tx["asset_b"])
                    need_u = float(tx["amount_a"]) if a == "UNIVA" else (float(tx["amount_b"]) if b == "UNIVA" else 0.0)
                    if available_univa + 1e-8 < fee + need_u:
                        return False
                # Dry-run deterministic AMM execution (validates pool, slippage, reserves & LP balance)
                self._apply_onchain_dex_tx(dex, dict(dex.univa_net_deltas), tx)
                return True

            return False
        except Exception:
            return False

    def create_transaction(self, wallet, to_address: str, amount: float, fee: float = 0.0, from_address: str = None) -> dict:
        """Create a locally signed transfer compatible with verify_transaction()."""
        from core.wallet import validate_address
        if not validate_address(to_address, network=self.network):
            raise ValueError("Invalid recipient address")
        default_sender = wallet.testnet_address if self.network == "testnet" else wallet.address
        sender = from_address if (from_address and validate_address(from_address, network=self.network)) else default_sender
        amount, fee = round(float(amount), 8), round(float(fee), 8)
        if amount <= 0 or fee < 0:
            raise ValueError("Amount must be positive and fee non-negative")
        tx = {"type": "transfer", "from": sender, "to": to_address,
              "amount": amount, "fee": fee, "nonce": self._pending_nonce(sender),
              "public_key": wallet.public_key}
        message = self._canonical_tx_message(tx)
        tx["signature"] = wallet.sign(message)
        tx["tx_id"] = hashlib.sha256(message.encode("utf-8")).hexdigest()
        return tx

    def mine_pending_transactions(self, miner_address: str, stop_event=None, on_progress=None, reward_override: Optional[float] = None) -> Optional[Block]:
        with self._lock:
            from core.wallet import validate_address
            if not validate_address(miner_address, network=self.network):
                raise ValueError("Invalid miner address")
            index = self.height + 1
            base_subsidy = self.get_current_reward(index)
            if reward_override is not None:
                subsidy = round(max(0.0, min(float(reward_override), base_subsidy)), 8)
            else:
                subsidy = base_subsidy
            mtp = self.get_median_time_past(11)
            block_ts = max(time.time(), mtp + 1.0)
            # Re-check mempool against confirmed state, one transaction at a time.
            accepted, fees = [], 0.0
            original_pending = list(self.pending_transactions)
            self.pending_transactions = []
            for tx in original_pending:
                if self.verify_transaction(tx, include_pending=True, block_timestamp=block_ts):
                    self.pending_transactions.append(tx)
                    accepted.append(tx)
                    fees = round(fees + float(tx["fee"]), 8)
            self.pending_transactions = accepted
            if subsidy <= 0 and fees <= 0:
                self.pending_transactions = original_pending
                return None
            coinbase_tx = {"type": "coinbase", "from": "network_mint", "to": miner_address,
                           "amount": round(subsidy + fees, 8), "subsidy": subsidy, "fees": fees,
                           "message": f"UNIVA Block #{index} Mining Reward", "timestamp": block_ts}
            txs = [coinbase_tx] + list(accepted)
            new_block = Block(index=index, transactions=txs, previous_hash=self.last_block.hash,
                              timestamp=block_ts, difficulty=self.difficulty,
                              miner_address=miner_address, reward=subsidy)
            if not new_block.mine(self.difficulty, stop_event):
                return None
            self.chain.append(new_block)
            self.pending_transactions = []
            self.total_mined = round(self.total_mined + subsidy, 8)
            self._adjust_difficulty()
            self.save()
            try:
                from core.database import insert_block, insert_transactions
                bd = new_block.to_dict()
                insert_block(bd)
                insert_transactions(bd)
            except Exception:
                pass  # the validated JSON chain remains authoritative
            if on_progress:
                on_progress(new_block)
            return new_block

    def accept_block(self, block_data: dict) -> bool:
        """Validate and append exactly the next block with full reward-tier, PoW, MTP, and tx consensus checks."""
        with self._lock:
            try:
                from core.wallet import validate_address
                block = block_data if isinstance(block_data, Block) else Block.from_dict(block_data)
                if block.index != self.height + 1 or block.previous_hash != self.last_block.hash:
                    return False
                if block.difficulty != self.difficulty:
                    return False
                if block.hash != block.calculate_hash() or not block.hash.startswith("0" * block.difficulty):
                    return False
                if block.merkle_root != calculate_merkle_root(block.transactions):
                    return False
                if block.timestamp <= self.get_median_time_past(11) or block.timestamp > time.time() + 7200:
                    return False
                if not validate_address(block.miner_address, network=self.network):
                    return False
                if not block.transactions or block.transactions[0].get("type") != "coinbase":
                    return False
                if len([tx for tx in block.transactions if tx.get("type") == "coinbase"]) != 1:
                    return False

                coinbase = block.transactions[0]
                max_subsidy = self.get_current_reward(block.index)
                blk_reward = float(block.reward)
                # Parity with is_chain_valid(): allow valid rewards <= max_subsidy (e.g. mobile 10.0 vs PC 100.0)
                if blk_reward < 0 or blk_reward > round(max_subsidy, 8) + 1e-8:
                    return False
                if self.total_mined + blk_reward > MAX_SUPPLY + 1e-8:
                    return False

                txs = block.transactions[1:]
                fees = 0.0
                old_pending = list(self.pending_transactions)
                self.pending_transactions = []
                seen_block_txids = set()
                for tx in txs:
                    tid = tx.get("tx_id")
                    if tid in seen_block_txids or not self.verify_transaction(
                        tx, include_pending=True, block_timestamp=block.timestamp
                    ):
                        self.pending_transactions = old_pending
                        return False
                    seen_block_txids.add(tid)
                    self.pending_transactions.append(tx)
                    fees = round(fees + float(tx["fee"]), 8)
                self.pending_transactions = old_pending

                if blk_reward <= 0 and fees <= 0:
                    return False
                expected_coinbase = round(blk_reward + fees, 8)
                if abs(float(coinbase.get("amount", -1)) - expected_coinbase) > 1e-8:
                    return False
                if abs(float(coinbase.get("subsidy", blk_reward)) - blk_reward) > 1e-8:
                    return False
                if coinbase.get("to") != block.miner_address:
                    return False

                self.chain.append(block)
                self.total_mined = round(self.total_mined + blk_reward, 8)
                from core.transaction import NONCE_TX_TYPES
                confirmed = {tx.get("tx_id") for tx in txs}
                confirmed_nonces = {
                    (tx.get("from"), tx.get("nonce"))
                    for tx in txs
                    if tx.get("type", "transfer") in NONCE_TX_TYPES
                }
                confirmed_vouchers = {
                    (tx.get("reservation_id"), tx.get("voucher_nonce"))
                    for tx in txs
                    if tx.get("type") == "offline_spend"
                }
                self.pending_transactions = [
                    tx for tx in old_pending
                    if tx.get("tx_id") not in confirmed
                    and not (
                        tx.get("type", "transfer") in NONCE_TX_TYPES
                        and (tx.get("from"), tx.get("nonce")) in confirmed_nonces
                    )
                    and not (
                        tx.get("type") == "offline_spend"
                        and (tx.get("reservation_id"), tx.get("voucher_nonce")) in confirmed_vouchers
                    )
                ]
                self._adjust_difficulty()
                self.save()
                try:
                    from core.database import insert_block, insert_transactions
                    insert_block(block.to_dict())
                    insert_transactions(block.to_dict())
                except Exception:
                    pass
                return True
            except Exception:
                return False

    @staticmethod
    def _compute_next_difficulty(chain_slice: List[Block], current_diff: int) -> int:
        """Exact 60-block retargeting formula shared across live mining, reorg, and chain validation."""
        height = len(chain_slice) - 1
        if height < DIFFICULTY_ADJUST or height % DIFFICULTY_ADJUST != 0:
            return current_diff
        # Height 60 starts from block #1 (excluding static historical Genesis timestamp); all subsequent epochs span 60 blocks.
        start_idx = max(1, height - DIFFICULTY_ADJUST)
        elapsed = float(chain_slice[-1].timestamp) - float(chain_slice[start_idx].timestamp)
        span = max(1, height - start_idx)
        target = TARGET_BLOCK_TIME * span
        if elapsed < target / 2:
            return current_diff + 1
        elif elapsed > target * 2:
            return max(1, current_diff - 1)
        return current_diff

    def _adjust_difficulty(self):
        self.difficulty = self._compute_next_difficulty(self.chain, self.difficulty)

    def add_transaction(self, tx: dict) -> bool:
        with self._lock:
            from core.transaction import NONCE_TX_TYPES
            from core.wallet import normalize_address
            if not isinstance(tx, dict):
                return False
            tid = tx.get("tx_id")
            tx_type = tx.get("type", "transfer")
            sender_norm = normalize_address(tx.get("from", ""))
            for p in self.pending_transactions:
                if p.get("tx_id") == tid:
                    return False
                p_type = p.get("type", "transfer")
                if tx_type in NONCE_TX_TYPES and p_type in NONCE_TX_TYPES:
                    if normalize_address(p.get("from", "")) == sender_norm and p.get("nonce") == tx.get("nonce"):
                        return False
                if tx_type == "offline_spend" and p_type == "offline_spend":
                    if p.get("reservation_id") == tx.get("reservation_id") and p.get("voucher_nonce") == tx.get("voucher_nonce"):
                        return False
            if not self.verify_transaction(tx, include_pending=True):
                return False
            self.pending_transactions.append(dict(tx))
            return True

    def get_balance(
        self,
        address: str,
        asset: str = "UNIVA",
        include_pending_outgoing: bool = True,
        include_dex: bool = True,
        at_timestamp: Optional[float] = None,
    ) -> float:
        from core.transaction import DEX_TX_TYPES
        from core.wallet import normalize_address
        norm = normalize_address(address)

        if asset != "UNIVA":
            total_asset = 0.0
            if self._has_dex_transactions(include_pending=include_pending_outgoing):
                try:
                    oc_dex = self.get_onchain_dex_state(include_pending=include_pending_outgoing)
                    total_asset += oc_dex.get_balance(norm, asset) / 100_000_000
                except Exception:
                    pass
            if not getattr(self, "_validating_chain", False) and self.dex_state is not None:
                try:
                    total_asset += self.dex_state.get_balance(address, asset) / 100_000_000
                except Exception:
                    pass
            if total_asset > 0:
                return round(total_asset, 8)
            return self.custom_balances.get((address, asset), 0.0)

        eff_ts = float(
            at_timestamp
            if at_timestamp is not None
            else max(time.time(), self.last_block.timestamp if self.chain else 0.0)
        )
        bal = 0.0
        for block in self.chain:
            for tx in block.transactions:
                ttype = tx.get("type", "transfer")
                if ttype in ("coinbase", "genesis", "transfer", "offline_spend") and normalize_address(tx.get("to", "")) == norm:
                    bal += float(tx.get("amount", 0.0))
                if normalize_address(tx.get("from", "")) == norm:
                    if ttype in ("transfer", "offline_reserve"):
                        bal -= float(tx.get("amount", 0.0)) + float(tx.get("fee", 0.0))
                    elif ttype in ("offline_release",) or ttype in DEX_TX_TYPES:
                        bal -= float(tx.get("fee", 0.0))

        # Automatic deterministic refund of unspent expired or released on-chain reservations
        confirmed_res = self.get_onchain_reservations(include_pending=False, at_timestamp=eff_ts)
        for rec in confirmed_res.values():
            if rec["owner"] == norm and (rec["released"] or eff_ts >= float(rec["expires_at"])):
                bal += rec["remaining"]

        # Deterministic on-chain consensus DEX UNIVA balance delta
        if self._has_dex_transactions(include_pending=include_pending_outgoing):
            try:
                oc_dex = self.get_onchain_dex_state(include_pending=include_pending_outgoing)
                bal += oc_dex.get_univa_net_delta_float(norm)
            except Exception:
                pass

        if include_pending_outgoing:
            for tx in self.pending_transactions:
                ttype = tx.get("type", "transfer")
                if normalize_address(tx.get("from", "")) == norm:
                    if ttype in ("transfer", "offline_reserve"):
                        bal -= float(tx.get("amount", 0.0)) + float(tx.get("fee", 0.0))
                    elif ttype in ("offline_release",) or ttype in DEX_TX_TYPES:
                        bal -= float(tx.get("fee", 0.0))
        if (
            include_dex
            and not getattr(self, "_validating_chain", False)
            and self.dex_state is not None
            and hasattr(self.dex_state, "get_univa_net_delta_float")
        ):
            bal += self.dex_state.get_univa_net_delta_float(norm)
        return round(max(0.0, bal), 8)

    @staticmethod
    def calculate_chain_work(chain_slice: List[Block]) -> int:
        """Cumulative SHA-256 Proof-of-Work score for heaviest-chain fork choice."""
        return sum(16 ** max(1, int(b.difficulty)) for b in chain_slice)

    def _validate_chain_state(self, candidate_chain: List[Block]):
        """Validate full chain and return (True, total_subsidy, next_difficulty) or (False, 0.0, INITIAL_DIFF)."""
        original_chain = self.chain
        original_total = self.total_mined
        original_pending = self.pending_transactions
        prev_validating = getattr(self, "_validating_chain", False)
        self._validating_chain = True
        if not candidate_chain or candidate_chain[0].index != 0:
            self._validating_chain = prev_validating
            return False, 0.0, INITIAL_DIFF
        total_subsidy = 0.0
        expected_difficulty = INITIAL_DIFF
        try:
            from core.wallet import validate_address
            genesis = candidate_chain[0]
            if genesis.hash != genesis.calculate_hash() or genesis.previous_hash != "0" * 64:
                return False, 0.0, INITIAL_DIFF
            if genesis.merkle_root != calculate_merkle_root(genesis.transactions):
                return False, 0.0, INITIAL_DIFF
            for i in range(1, len(candidate_chain)):
                cur, prev = candidate_chain[i], candidate_chain[i - 1]
                if cur.index != i or cur.previous_hash != prev.hash:
                    return False, 0.0, INITIAL_DIFF
                if cur.hash != cur.calculate_hash() or cur.merkle_root != calculate_merkle_root(cur.transactions):
                    return False, 0.0, INITIAL_DIFF
                if cur.difficulty != expected_difficulty or not cur.hash.startswith("0" * cur.difficulty):
                    return False, 0.0, INITIAL_DIFF
                if cur.timestamp <= self._median_for_chain(candidate_chain[:i], 11):
                    return False, 0.0, INITIAL_DIFF
                if not validate_address(cur.miner_address, network=self.network):
                    return False, 0.0, INITIAL_DIFF
                if not cur.transactions or cur.transactions[0].get("type") != "coinbase":
                    return False, 0.0, INITIAL_DIFF
                subsidy = max(0.0, min(INITIAL_REWARD / (2 ** (i // HALVING_INTERVAL)), MAX_SUPPLY - total_subsidy))
                if cur.reward < 0 or float(cur.reward) > round(subsidy, 8) + 1e-8:
                    return False, 0.0, INITIAL_DIFF
                coinbase = cur.transactions[0]
                if coinbase.get("to") != cur.miner_address:
                    return False, 0.0, INITIAL_DIFF
                if len([tx for tx in cur.transactions if tx.get("type") == "coinbase"]) != 1:
                    return False, 0.0, INITIAL_DIFF

                self.chain = candidate_chain[:i]
                self.total_mined = total_subsidy
                self.pending_transactions = []
                fees = 0.0
                seen_block_txids = set()
                for tx in cur.transactions[1:]:
                    tid = tx.get("tx_id")
                    if tid in seen_block_txids or not self.verify_transaction(
                        tx, include_pending=True, block_timestamp=cur.timestamp
                    ):
                        return False, 0.0, INITIAL_DIFF
                    seen_block_txids.add(tid)
                    self.pending_transactions.append(tx)
                    fees = round(fees + float(tx["fee"]), 8)
                expected_coinbase = round(float(cur.reward) + fees, 8)
                if cur.reward <= 0 and fees <= 0:
                    return False, 0.0, INITIAL_DIFF
                if abs(float(coinbase.get("amount", -1)) - expected_coinbase) > 1e-8:
                    return False, 0.0, INITIAL_DIFF
                if abs(float(coinbase.get("subsidy", cur.reward)) - cur.reward) > 1e-8:
                    return False, 0.0, INITIAL_DIFF
                total_subsidy = round(total_subsidy + float(cur.reward), 8)
                if total_subsidy > MAX_SUPPLY + 1e-8:
                    return False, 0.0, INITIAL_DIFF
                expected_difficulty = self._compute_next_difficulty(candidate_chain[:i + 1], expected_difficulty)
            return True, total_subsidy, expected_difficulty
        except Exception:
            return False, 0.0, INITIAL_DIFF
        finally:
            self._validating_chain = prev_validating
            self.chain = original_chain
            self.total_mined = original_total
            self.pending_transactions = original_pending

    def is_chain_valid(self) -> bool:
        with self._lock:
            valid, _, _ = self._validate_chain_state(self.chain)
            return valid

    def replace_chain(self, candidate_blocks: list, save_path: Optional[str] = None) -> bool:
        """Heaviest-valid-chain fork resolution (reorg) with orphaned mempool transaction recovery."""
        with self._lock:
            try:
                candidate = [
                    b if isinstance(b, Block) else Block.from_dict(b)
                    for b in candidate_blocks
                ]
                if not candidate or candidate[0].hash != self.chain[0].hash:
                    return False
                if self.calculate_chain_work(candidate) <= self.calculate_chain_work(self.chain):
                    return False
                valid, total_subsidy, next_diff = self._validate_chain_state(candidate)
                if not valid:
                    return False

                new_tx_ids = {
                    tx.get("tx_id") for b in candidate for tx in b.transactions if tx.get("tx_id")
                }
                # Recover valid L1 transactions (transfer + offline_reserve/spend/release) from orphaned tail blocks + old mempool
                from core.transaction import SUPPORTED_TX_TYPES
                orphaned_transfers = [
                    tx for b in self.chain[1:] for tx in b.transactions
                    if tx.get("type", "transfer") in SUPPORTED_TX_TYPES and tx.get("tx_id") not in new_tx_ids
                ]
                carry_candidates = orphaned_transfers + [
                    tx for tx in self.pending_transactions if tx.get("tx_id") not in new_tx_ids
                ]

                self.chain = candidate
                self.total_mined = round(total_subsidy, 8)
                self.difficulty = int(next_diff)
                self.pending_transactions = []
                for tx in carry_candidates:
                    if self.verify_transaction(tx, include_pending=True):
                        self.pending_transactions.append(dict(tx))

                self.save(save_path or CHAIN_FILE_PATH, force=True)
                try:
                    from core.database import rebuild_index
                    rebuild_index(self.chain)
                except Exception:
                    pass
                return True
            except Exception:
                return False

    @staticmethod
    def _median_for_chain(chain, n=11):
        timestamps = sorted(b.timestamp for b in chain[-n:])
        return timestamps[len(timestamps)//2] if timestamps else 0.0

    def stats(self) -> dict:
        elapsed_months = self.height // HALVING_INTERVAL
        next_halving   = HALVING_INTERVAL - (self.height % HALVING_INTERVAL)
        return {
            "network":         NETWORK_NAME,
            "network_mode":    self.network,
            "chain_id":        self.chain_id,
            "genesis_hash":    self.chain[0].hash if self.chain else "",
            "ticker":          TICKER,
            "version":         VERSION,
            "height":          self.height,
            "difficulty":      self.difficulty,
            "total_mined":     round(self.total_mined, 8),
            "max_supply":      MAX_SUPPLY,
            "supply_percent":  round(self.total_mined / MAX_SUPPLY * 100, 4),
            "current_reward":  self.get_current_reward(),
            "next_halving_in": next_halving,
            "months_elapsed":  elapsed_months,
            "pending_tx":      len(self.pending_transactions),
            "chain_valid":     self.is_chain_valid(),
            "last_hash":       self.last_block.hash,
            "peer_count":      self.peer_count,
        }

    def to_dict(self) -> dict:
        return {
            "network":     NETWORK_NAME,
            "ticker":      TICKER,
            "version":     VERSION,
            "height":      self.height,
            "difficulty":  self.difficulty,
            "total_mined": self.total_mined,
            "chain":       [b.to_dict() for b in self.chain],
        }

    def save(self, path: str = CHAIN_FILE_PATH, force: bool = False):
        """Kalıcı ve güvenli kayıt: Asla var olan blokları ezmez, otomatik .bak yedeği alır."""
        # Diskteki var olan dosya bizden uzunsa ASLA ezme (yalnizca dogrulanmis reorg haric)!
        if os.path.exists(path):
            if not force:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        disk_d = json.load(f)
                        if len(disk_d.get("chain", [])) > len(self.chain):
                            return False # Diskteki veri daha guncel
                except Exception:
                    pass
            # Otomatik .bak yedegi olustur
            try:
                shutil.copyfile(path, path + ".bak")
            except Exception:
                pass

        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
        return True

    def load(self, path: str = CHAIN_FILE_PATH) -> bool:
        # Ensure persisted PWA pubkey bindings & local treasury wallet are registered before validating blocks
        try:
            from core.wallet import REGISTERED_PWA_ORIGINS, UnivaWallet
            base_dir = os.path.dirname(os.path.abspath(path))
            bindings_path = os.path.join(base_dir, "univa_pubkey_bindings.json")
            if os.path.exists(bindings_path):
                with open(bindings_path, "r", encoding="utf-8") as bf:
                    bdata = json.load(bf)
                if isinstance(bdata, dict):
                    for pk, addrs in bdata.items():
                        if isinstance(addrs, list):
                            REGISTERED_PWA_ORIGINS.setdefault(pk, set()).update(addrs)
            wallet_path = os.path.join(base_dir, "univa_wallet.json")
            if os.path.exists(wallet_path):
                w = UnivaWallet.load(wallet_path)
                REGISTERED_PWA_ORIGINS.setdefault(w.public_key, set()).add(w.address)
        except Exception:
            pass

        candidates = [p for p in (path, path + ".bak") if os.path.exists(p)]
        for target_path in candidates:
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded_chain = [Block.from_dict(b) for b in data["chain"]]
                if not loaded_chain:
                    continue
                old_chain, old_total, old_pending = self.chain, self.total_mined, self.pending_transactions
                valid, total_sub, next_diff = self._validate_chain_state(loaded_chain)
                if not valid:
                    # Recover longest valid prefix so a corrupted tail block never resets the chain to 0
                    lo, hi, best = 1, len(loaded_chain), 0
                    while lo <= hi:
                        mid = (lo + hi) // 2
                        ok, _, _ = self._validate_chain_state(loaded_chain[:mid])
                        if ok:
                            best = mid
                            lo = mid + 1
                        else:
                            hi = mid - 1
                    if best > 1:
                        print(f"[UNIVA] UYARI: {target_path} sonundaki bozuk blok(lar) temizlendi -> kurtarilan yukseklik={best-1}")
                        loaded_chain = loaded_chain[:best]
                        valid, total_sub, next_diff = self._validate_chain_state(loaded_chain)
                    else:
                        self.chain, self.total_mined, self.pending_transactions = old_chain, old_total, old_pending
                        continue
                self.chain = loaded_chain
                self.difficulty = int(next_diff)
                self.total_mined = round(total_sub, 8)
                self.pending_transactions = []
                print(f"[UNIVA] Zincir yüklendi: {target_path} | yükseklik={len(loaded_chain)-1}")
                return True
            except Exception as e:
                print(f"[UNIVA] Zincir okuma hatası ({target_path}): {e}")
        return False
