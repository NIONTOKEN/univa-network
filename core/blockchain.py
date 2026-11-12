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
    def __init__(self, auto_load_path: str = CHAIN_FILE_PATH):
        self._lock                = threading.RLock()
        self.chain: List[Block]   = []
        self.pending_transactions = []
        self.difficulty           = INITIAL_DIFF
        self.total_mined          = 0.0
        self.peer_count           = 0
        self.custom_balances      = {} # Token/Asset balances
        self.dex_state            = None # Injected by DEX engine

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
            "message":   GENESIS_MESSAGE,
            "timestamp": GENESIS_TIME,
            "to":        GENESIS_MINER,
            "amount":    0.0,
        }]
        genesis = Block(
            index          = 0,
            transactions   = genesis_tx,
            previous_hash  = "0" * 64,
            timestamp      = GENESIS_TIME,
            nonce          = 0,
            difficulty     = 1,
            miner_address  = GENESIS_MINER,
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
        return sum(1 for block in self.chain for tx in block.transactions
                   if tx.get("type", "transfer") == "transfer" and tx.get("from") == address)

    def _pending_nonce(self, address: str) -> int:
        return self._account_nonce(address) + sum(1 for tx in self.pending_transactions
            if tx.get("type", "transfer") == "transfer" and tx.get("from") == address)

    @staticmethod
    def _canonical_tx_message(tx: dict) -> str:
        fields = {k: tx.get(k) for k in ("type", "from", "to", "amount", "fee", "nonce", "public_key")}
        return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def verify_transaction(self, tx: dict, include_pending: bool = True) -> bool:
        """Validate a signed transfer. Coinbase/genesis are accepted only in block validation."""
        if not isinstance(tx, dict) or tx.get("type", "transfer") != "transfer":
            return False
        required = ("from", "to", "amount", "fee", "nonce", "public_key", "signature", "tx_id")
        if any(k not in tx for k in required):
            return False
        try:
            amount, fee = float(tx["amount"]), float(tx["fee"])
            nonce = tx["nonce"]
            if not (amount > 0 and fee >= 0 and amount < float("inf") and fee < float("inf")):
                return False
            if round(amount, 8) != amount or round(fee, 8) != fee or not isinstance(nonce, int) or nonce < 0:
                return False
            from core.wallet import derive_univa_address, derive_legacy_20char_address, derive_evm_address, validate_address, UnivaWallet, REGISTERED_PWA_ORIGINS
            if not validate_address(tx["from"]) or not validate_address(tx["to"]):
                return False
            # Gönderen adresi: Yeni L1 adresi, eski 20-karakter adresi, EVM ayna adresi veya kayıtlı PWA adresi olabilir
            valid_origins = {
                derive_univa_address(tx["public_key"]),
                derive_legacy_20char_address(tx["public_key"]),
                derive_evm_address(tx["public_key"]),
            } | REGISTERED_PWA_ORIGINS.get(tx["public_key"], set())
            if tx["from"] not in valid_origins:
                return False
            message = self._canonical_tx_message(tx)
            if not UnivaWallet.verify_signature(tx["public_key"], message, tx["signature"]):
                return False
            tx_digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
            if tx["tx_id"] != tx_digest or tx_digest in self._confirmed_tx_ids():
                return False
            expected_nonce = self._pending_nonce(tx["from"]) if include_pending else self._account_nonce(tx["from"])
            if nonce != expected_nonce:
                return False
            available = self.get_balance(tx["from"], include_pending_outgoing=include_pending)
            return available >= amount + fee
        except Exception:
            return False

    def create_transaction(self, wallet, to_address: str, amount: float, fee: float = 0.0, from_address: str = None) -> dict:
        """Create a locally signed transfer compatible with verify_transaction()."""
        from core.wallet import validate_address
        if not validate_address(to_address):
            raise ValueError("Invalid recipient address")
        sender = from_address if (from_address and validate_address(from_address)) else wallet.address
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

    def mine_pending_transactions(self, miner_address: str, stop_event=None, on_progress=None) -> Optional[Block]:
        with self._lock:
            from core.wallet import validate_address
            if not validate_address(miner_address):
                raise ValueError("Invalid miner address")
            index = self.height + 1
            subsidy = self.get_current_reward(index)
            mtp = self.get_median_time_past(11)
            block_ts = max(time.time(), mtp + 1.0)
            # Re-check mempool against confirmed state, one transaction at a time.
            accepted, fees = [], 0.0
            original_pending = list(self.pending_transactions)
            self.pending_transactions = []
            for tx in original_pending:
                if self.verify_transaction(tx, include_pending=True):
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
        """Validate and append exactly the next block. Used by the P2P testnet."""
        try:
            block = block_data if isinstance(block_data, Block) else Block.from_dict(block_data)
            if block.index != self.height + 1 or block.previous_hash != self.last_block.hash:
                return False
            if block.difficulty != self.difficulty:
                return False
            if block.hash != block.calculate_hash() or not block.hash.startswith("0" * block.difficulty):
                return False
            if block.merkle_root != calculate_merkle_root(block.transactions):
                return False
            if block.timestamp <= self.get_median_time_past(11):
                return False
            if not block.transactions or block.transactions[0].get("type") != "coinbase":
                return False
            coinbase = block.transactions[0]
            subsidy = self.get_current_reward(block.index)
            txs = block.transactions[1:]
            fees = 0.0
            # Validate sequentially against a temporary mempool, preserving rollback on failure.
            old_pending = list(self.pending_transactions)
            self.pending_transactions = []
            for tx in txs:
                if not self.verify_transaction(tx, include_pending=True):
                    self.pending_transactions = old_pending
                    return False
                self.pending_transactions.append(tx)
                fees = round(fees + float(tx["fee"]), 8)
            self.pending_transactions = old_pending
            if abs(float(block.reward) - subsidy) > 1e-8:
                return False
            if abs(float(coinbase.get("amount", -1)) - round(subsidy + fees, 8)) > 1e-8:
                return False
            if coinbase.get("to") != block.miner_address:
                return False
            self.chain.append(block)
            self.total_mined = round(self.total_mined + subsidy, 8)
            # Remove confirmed transactions from mempool.
            confirmed = {tx.get("tx_id") for tx in txs}
            self.pending_transactions = [tx for tx in old_pending if tx.get("tx_id") not in confirmed]
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

    def _adjust_difficulty(self):
        if self.height % DIFFICULTY_ADJUST != 0 or self.height < DIFFICULTY_ADJUST:
            return
        prev = self.chain[-DIFFICULTY_ADJUST]
        elapsed = self.last_block.timestamp - prev.timestamp
        target = TARGET_BLOCK_TIME * DIFFICULTY_ADJUST
        if elapsed < target / 2:
            self.difficulty += 1
        elif elapsed > target * 2:
            self.difficulty = max(1, self.difficulty - 1)

    def add_transaction(self, tx: dict) -> bool:
        if not self.verify_transaction(tx, include_pending=True):
            return False
        self.pending_transactions.append(dict(tx))
        return True

    def get_balance(self, address: str, asset: str = "UNIVA", include_pending_outgoing: bool = True) -> float:
        if asset != "UNIVA":
            return self.custom_balances.get((address, asset), 0.0)
        bal = 0.0
        for block in self.chain:
            for tx in block.transactions:
                if tx.get("to") == address:
                    bal += float(tx.get("amount", 0.0))
                if tx.get("from") == address and tx.get("type") == "transfer":
                    bal -= float(tx.get("amount", 0.0)) + float(tx.get("fee", 0.0))
        if include_pending_outgoing:
            for tx in self.pending_transactions:
                if tx.get("from") == address and tx.get("type", "transfer") == "transfer":
                    bal -= float(tx.get("amount", 0.0)) + float(tx.get("fee", 0.0))
        return round(bal, 8)

    def is_chain_valid(self) -> bool:
        original_chain = self.chain
        original_total = self.total_mined
        original_pending = self.pending_transactions
        if not original_chain or original_chain[0].index != 0:
            return False
        total_subsidy = 0.0
        expected_difficulty = INITIAL_DIFF
        try:
            genesis = original_chain[0]
            if genesis.hash != genesis.calculate_hash() or genesis.previous_hash != "0" * 64:
                return False
            if genesis.merkle_root != calculate_merkle_root(genesis.transactions):
                return False
            for i in range(1, len(original_chain)):
                cur, prev = original_chain[i], original_chain[i - 1]
                if cur.index != i or cur.previous_hash != prev.hash:
                    return False
                if cur.hash != cur.calculate_hash() or cur.merkle_root != calculate_merkle_root(cur.transactions):
                    return False
                if cur.difficulty != expected_difficulty or not cur.hash.startswith("0" * cur.difficulty):
                    return False
                if cur.timestamp <= self._median_for_chain(original_chain[:i], 11):
                    return False
                if not cur.transactions or cur.transactions[0].get("type") != "coinbase":
                    return False
                subsidy = max(0.0, min(INITIAL_REWARD / (2 ** (i // HALVING_INTERVAL)), MAX_SUPPLY - total_subsidy))
                if abs(float(cur.reward) - round(subsidy, 8)) > 1e-8:
                    return False
                coinbase = cur.transactions[0]
                if coinbase.get("to") != cur.miner_address:
                    return False
                if len([tx for tx in cur.transactions if tx.get("type") == "coinbase"]) != 1:
                    return False
                # Replay transactions against the prefix so balance, nonce, signature and replay checks are contextual.
                self.chain = original_chain[:i]
                self.total_mined = total_subsidy
                self.pending_transactions = []
                fees = 0.0
                for tx in cur.transactions[1:]:
                    if not self.verify_transaction(tx, include_pending=True):
                        return False
                    self.pending_transactions.append(tx)
                    fees = round(fees + float(tx["fee"]), 8)
                expected_coinbase = round(subsidy + fees, 8)
                if abs(float(coinbase.get("amount", -1)) - expected_coinbase) > 1e-8:
                    return False
                if abs(float(coinbase.get("subsidy", subsidy)) - subsidy) > 1e-8:
                    return False
                total_subsidy = round(total_subsidy + subsidy, 8)
                if total_subsidy > MAX_SUPPLY + 1e-8:
                    return False
                if i % DIFFICULTY_ADJUST == 0 and i >= DIFFICULTY_ADJUST:
                    prev_window = original_chain[i - 59]
                    elapsed = cur.timestamp - prev_window.timestamp
                    target = TARGET_BLOCK_TIME * DIFFICULTY_ADJUST
                    if elapsed < target / 2:
                        expected_difficulty += 1
                    elif elapsed > target * 2:
                        expected_difficulty = max(1, expected_difficulty - 1)
            return True
        except Exception:
            return False
        finally:
            self.chain = original_chain
            self.total_mined = original_total
            self.pending_transactions = original_pending

    @staticmethod
    def _median_for_chain(chain, n=11):
        timestamps = sorted(b.timestamp for b in chain[-n:])
        return timestamps[len(timestamps)//2] if timestamps else 0.0

    def stats(self) -> dict:
        elapsed_months = self.height // HALVING_INTERVAL
        next_halving   = HALVING_INTERVAL - (self.height % HALVING_INTERVAL)
        return {
            "network":         NETWORK_NAME,
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

    def save(self, path: str = CHAIN_FILE_PATH):
        """Kalıcı ve güvenli kayıt: Asla var olan blokları ezmez, otomatik .bak yedeği alır."""
        # Diskteki var olan dosya bizden uzunsa ASLA ezme!
        if os.path.exists(path):
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
        candidates = [p for p in (path, path + ".bak") if os.path.exists(p)]
        for target_path in candidates:
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded_chain = [Block.from_dict(b) for b in data["chain"]]
                if not loaded_chain:
                    continue
                old_chain, old_total, old_pending = self.chain, self.total_mined, self.pending_transactions
                self.chain = loaded_chain
                if not self.is_chain_valid():
                    self.chain, self.total_mined, self.pending_transactions = old_chain, old_total, old_pending
                    continue
                self.difficulty = int(data.get("difficulty", loaded_chain[-1].difficulty))
                self.total_mined = round(sum(float(b.reward) for b in loaded_chain[1:]), 8)
                self.pending_transactions = []
                print(f"[UNIVA] Zincir yüklendi: {target_path} | yükseklik={len(loaded_chain)-1}")
                return True
            except Exception as e:
                print(f"[UNIVA] Zincir okuma hatası ({target_path}): {e}")
        return False
