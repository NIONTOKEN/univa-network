"""
UNIVA NETWORK — TRC-20 (TRON) GATEWAY & HOT WALLET ENGINE
High-grade, zero-dependency TRON (TRC-20 USDT) integration for UNIVA L1.

Features:
- Pure-Python Base58Check encoding & decoding with double-SHA256 validation.
- Bidirectional EVM (0x) <-> TRON (T...) address translation (same secp256k1 curve).
- Real-time TRC-20 USDT (TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t) balance reader.
- Automatic deposit watcher with anti-replay & idempotent disk persistence.
- Mainnet & Nile Testnet multi-endpoint failover with zero external package dependencies.
"""

import hashlib
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Base58 Bitcoin/Tron alphabet
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# TRON Networks
TRON_NETWORKS = {
    "mainnet": {
        "name": "TRON Mainnet",
        "usdt_contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "usdt_contract_hex": "41a614f803b6fd780986a42c78ec9c7f77e6ded13c",
        "decimals": 6,
        "endpoints": [
            "https://api.trongrid.io",
            "https://tron-rpc.publicnode.com",
            "https://apilist.tronscanapi.com"
        ],
        "explorer_tx": "https://tronscan.org/#/transaction/",
        "explorer_addr": "https://tronscan.org/#/address/"
    },
    "nile": {
        "name": "TRON Nile Testnet",
        "usdt_contract": "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf",
        "usdt_contract_hex": "41ec5170a049101d2936a6cf4906f030bc98a3e790",
        "decimals": 6,
        "endpoints": [
            "https://nile.trongrid.io"
        ],
        "explorer_tx": "https://nile.tronscan.org/#/transaction/",
        "explorer_addr": "https://nile.tronscan.org/#/address/"
    }
}


class TronAddress:
    """Pure-Python cryptographic TRON address conversions & validations."""

    @staticmethod
    def b58decode(s: str) -> bytes:
        n = 0
        for char in s:
            idx = B58_ALPHABET.find(char)
            if idx == -1:
                raise ValueError(f"Invalid Base58 character: {char}")
            n = n * 58 + idx
        res = bytearray()
        while n > 0:
            res.append(n & 0xFF)
            n >>= 8
        res = bytes(reversed(res))
        pad = 0
        for char in s:
            if char == "1":
                pad += 1
            else:
                break
        return b"\x00" * pad + res

    @staticmethod
    def b58encode(b: bytes) -> str:
        n = int.from_bytes(b, "big")
        chars = []
        while n > 0:
            n, r = divmod(n, 58)
            chars.append(B58_ALPHABET[r])
        pad = 0
        for byte in b:
            if byte == 0:
                pad += 1
            else:
                break
        return "1" * pad + "".join(reversed(chars))

    @classmethod
    def is_valid(cls, address: str) -> bool:
        """Validates whether a string is a valid Base58Check TRON address."""
        if not address or not isinstance(address, str):
            return False
        addr = address.strip()
        if len(addr) != 34 or not addr.startswith("T"):
            return False
        try:
            raw = cls.b58decode(addr)
            if len(raw) != 25:
                return False
            payload = raw[:-4]
            checksum = raw[-4:]
            if payload[0] != 0x41:  # TRON address prefix
                return False
            expected_checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
            return checksum == expected_checksum
        except Exception:
            return False

    @classmethod
    def to_hex(cls, address: str) -> str:
        """Converts Base58Check TRON address (T...) to 41... hex string."""
        if not cls.is_valid(address):
            raise ValueError(f"Invalid TRON address: {address}")
        raw = cls.b58decode(address.strip())
        return raw[:-4].hex()

    @classmethod
    def to_evm(cls, address: str) -> str:
        """Converts TRON address (T...) to EVM representation (0x...)."""
        h = cls.to_hex(address)
        # Drop the 41 prefix (2 hex chars) -> 40 hex chars (20 bytes)
        return "0x" + h[2:].lower()

    @classmethod
    def from_hex(cls, hex_address: str) -> str:
        """Converts 41... or 0x... hex address to Base58Check TRON address."""
        clean = hex_address.strip()
        if clean.startswith("0x") or clean.startswith("0X"):
            clean = "41" + clean[2:]
        elif not clean.startswith("41"):
            clean = "41" + clean
        if len(clean) != 42:
            raise ValueError(f"Invalid hex address length: expected 42 hex chars (got {len(clean)})")
        payload = bytes.fromhex(clean)
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        return cls.b58encode(payload + checksum)

    @classmethod
    def from_evm(cls, evm_address: str) -> str:
        """Converts EVM 0x address directly into TRON T... address."""
        clean = evm_address.strip()
        if clean.startswith("0x") or clean.startswith("0X"):
            clean = clean[2:]
        return cls.from_hex(clean)


class TRC20Gateway:
    """
    Production-grade TRON & TRC-20 USDT Gateway.
    Handles balances, incoming deposits, and state persistence.
    """

    def __init__(self, network: str = "mainnet", state_path: Optional[str] = None):
        if network not in TRON_NETWORKS:
            network = "mainnet"
        self.network_key = network
        self.config = TRON_NETWORKS[network]
        self.usdt_contract = self.config["usdt_contract"]
        self.usdt_contract_hex = self.config["usdt_contract_hex"]
        self.decimals = self.config["decimals"]
        self.endpoints = list(self.config["endpoints"])

        # State persistence
        root_dir = Path(__file__).resolve().parent.parent
        self.state_file = Path(state_path) if state_path else (root_dir / f"univa_trc20_state_{network}.json")
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "network": self.network_key,
            "vault_address": "",
            "processed_deposits": {},
            "pending_withdrawals": {},
            "last_poll_timestamp": 0,
            "stats": {
                "total_deposited_usdt": 0.0,
                "total_withdrawn_usdt": 0.0,
                "deposit_count": 0,
                "withdrawal_count": 0
            }
        }

    def _save_state(self) -> None:
        try:
            tmp_path = str(self.state_file) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            if os.path.exists(self.state_file):
                os.replace(tmp_path, self.state_file)
            else:
                os.rename(tmp_path, self.state_file)
        except Exception as e:
            print(f"[TRC20] Error saving state: {e}")

    def set_vault_address(self, address: str) -> bool:
        """Sets the official UNIVA TRON deposit vault address."""
        if not TronAddress.is_valid(address):
            raise ValueError(f"Invalid TRON address: {address}")
        self.state["vault_address"] = address
        self._save_state()
        return True

    def get_vault_address(self) -> str:
        """Returns the configured vault address (or fallback to Tether Treasury for testing)."""
        return self.state.get("vault_address") or "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

    def _request_json(self, url: str, post_data: Optional[Dict] = None, timeout: int = 8) -> Optional[Dict]:
        """Performs robust HTTP request with automatic headers and error handling."""
        headers = {
            "User-Agent": "UNIVA-TRC20-Engine/3.0.0",
            "Accept": "application/json"
        }
        data_bytes = None
        if post_data is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(post_data).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except Exception as e:
            return None

    def get_trx_balance(self, address: str) -> float:
        """Queries native TRX balance for an address."""
        if not TronAddress.is_valid(address):
            return 0.0
        hex_addr = TronAddress.to_hex(address)

        for base_url in self.endpoints:
            url = f"{base_url}/v1/accounts/{address}"
            res = self._request_json(url)
            if res and res.get("success") and res.get("data"):
                data_item = res["data"][0]
                sun_bal = data_item.get("balance", 0)
                return sun_bal / 1_000_000.0

            # Fallback direct wallet API
            url_direct = f"{base_url}/wallet/getaccount"
            res_direct = self._request_json(url_direct, post_data={"address": hex_addr})
            if res_direct and "balance" in res_direct:
                return float(res_direct["balance"]) / 1_000_000.0

        return 0.0

    def get_usdt_balance(self, address: str) -> float:
        """
        Queries official TRC-20 USDT smart contract balanceOf(address).
        Returns exact floating point USDT (6 decimals).
        """
        if not TronAddress.is_valid(address):
            return 0.0
        evm_hex = TronAddress.to_evm(address)[2:]  # 40 hex chars
        param_padded = "000000000000000000000000" + evm_hex

        payload = {
            "owner_address": "410000000000000000000000000000000000000000",
            "contract_address": self.usdt_contract_hex,
            "function_selector": "balanceOf(address)",
            "parameter": param_padded,
            "visible": False
        }

        for base_url in self.endpoints:
            url = f"{base_url}/wallet/triggerconstantcontract"
            res = self._request_json(url, post_data=payload)
            if res and res.get("result", {}).get("result"):
                const_res = res.get("constant_result", [])
                if const_res and len(const_res) > 0:
                    try:
                        sun_val = int(const_res[0], 16)
                        return sun_val / (10 ** self.decimals)
                    except Exception:
                        pass

        return 0.0

    def get_account_overview(self, address: str) -> Dict[str, Any]:
        """Returns comprehensive balance and network status for an address."""
        is_valid = TronAddress.is_valid(address)
        if not is_valid:
            return {
                "valid": False,
                "address": address,
                "error": "Invalid TRON Base58Check address"
            }

        trx_bal = self.get_trx_balance(address)
        usdt_bal = self.get_usdt_balance(address)
        evm_mirror = TronAddress.to_evm(address)

        return {
            "valid": True,
            "address": address,
            "evm_equivalent": evm_mirror,
            "network": self.config["name"],
            "network_key": self.network_key,
            "usdt_contract": self.usdt_contract,
            "trx_balance": trx_bal,
            "usdt_balance": usdt_bal,
            "formatted_usdt": f"{usdt_bal:,.2f} USDT",
            "explorer_url": self.config["explorer_addr"] + address,
            "timestamp": time.time()
        }

    def fetch_incoming_trc20_transactions(self, address: str, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Retrieves real-time TRC-20 USDT transfer events where to == address.
        """
        if not TronAddress.is_valid(address):
            return []

        for base_url in self.endpoints:
            url = f"{base_url}/v1/accounts/{address}/transactions/trc20?contract_address={self.usdt_contract}&limit={limit}"
            res = self._request_json(url)
            if res and res.get("success") and "data" in res:
                items = []
                for tx in res["data"]:
                    try:
                        raw_val = int(tx.get("value", 0))
                        amt_usdt = raw_val / (10 ** self.decimals)
                        tx_id = tx.get("transaction_id", "")
                        from_addr = tx.get("from", "")
                        to_addr = tx.get("to", "")
                        block_ts = tx.get("block_timestamp", int(time.time() * 1000)) / 1000.0

                        # Only incoming transfers
                        if to_addr.lower() == address.lower():
                            items.append({
                                "tx_id": tx_id,
                                "from": from_addr,
                                "to": to_addr,
                                "amount_usdt": amt_usdt,
                                "timestamp": block_ts,
                                "explorer_url": self.config["explorer_tx"] + tx_id,
                                "token_symbol": tx.get("token_info", {}).get("symbol", "USDT")
                            })
                    except Exception:
                        continue
                return items

        return []

    def poll_and_process_deposits(self, vault_address: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Polls vault incoming transactions and registers new uncredited deposits.
        Idempotent: Transactions are only credited once.
        """
        target_vault = vault_address or self.get_vault_address()
        if not TronAddress.is_valid(target_vault):
            return []

        txs = self.fetch_incoming_trc20_transactions(target_vault, limit=20)
        new_deposits = []

        for tx in txs:
            tx_id = tx["tx_id"]
            if tx_id in self.state["processed_deposits"]:
                continue  # already credited / processed

            # Register deposit
            record = {
                "tx_id": tx_id,
                "from_tron": tx["from"],
                "vault_tron": tx["to"],
                "amount_usdt": tx["amount_usdt"],
                "timestamp": tx["timestamp"],
                "detected_at": time.time(),
                "status": "CONFIRMED",
                "credited_univa": True
            }
            self.state["processed_deposits"][tx_id] = record
            self.state["stats"]["total_deposited_usdt"] += tx["amount_usdt"]
            self.state["stats"]["deposit_count"] += 1
            new_deposits.append(record)

        if new_deposits:
            self._save_state()

        return new_deposits

    def register_user_deposit(self, tx_id: str, univa_user: str, amount_usdt: float, from_address: str) -> Dict[str, Any]:
        """
        Explicitly registers a verified deposit credited to a specific UNIVA username/wallet.
        """
        clean_tx = tx_id.strip().lower()
        if clean_tx in self.state["processed_deposits"]:
            return {
                "success": False,
                "error": "This TRC-20 transaction hash has already been credited (replay protected).",
                "deposit": self.state["processed_deposits"][clean_tx]
            }

        record = {
            "tx_id": clean_tx,
            "univa_user": univa_user,
            "from_tron": from_address,
            "amount_usdt": float(amount_usdt),
            "timestamp": time.time(),
            "status": "CREDITED",
            "credited_univa": True
        }
        self.state["processed_deposits"][clean_tx] = record
        self.state["stats"]["total_deposited_usdt"] += float(amount_usdt)
        self.state["stats"]["deposit_count"] += 1
        self._save_state()

        return {
            "success": True,
            "deposit": record
        }

    def request_withdrawal(self, univa_user: str, destination_tron_address: str, amount_usdt: float) -> Dict[str, Any]:
        """
        Validates and registers an outbound USDT withdrawal to a TRON address.
        """
        if not TronAddress.is_valid(destination_tron_address):
            return {
                "success": False,
                "error": f"Invalid destination TRON address: {destination_tron_address}"
            }
        if amount_usdt < 1.0:
            return {
                "success": False,
                "error": "Minimum withdrawal amount is 1.00 USDT."
            }

        withdrawal_id = f"w-{int(time.time())}-{hashlib.sha256(f'{univa_user}{amount_usdt}{time.time()}'.encode()).hexdigest()[:10]}"
        record = {
            "withdrawal_id": withdrawal_id,
            "univa_user": univa_user,
            "destination_tron": destination_tron_address,
            "amount_usdt": float(amount_usdt),
            "network": self.config["name"],
            "fee_usdt": 1.0,  # Standard network fee
            "net_amount": float(amount_usdt) - 1.0,
            "status": "QUEUED_HOT_WALLET",
            "requested_at": time.time()
        }

        self.state["pending_withdrawals"][withdrawal_id] = record
        self.state["stats"]["total_withdrawn_usdt"] += float(amount_usdt)
        self.state["stats"]["withdrawal_count"] += 1
        self._save_state()

        return {
            "success": True,
            "withdrawal": record
        }

    def get_stats(self) -> Dict[str, Any]:
        """Returns Gateway operational statistics."""
        return {
            "network": self.config["name"],
            "usdt_contract": self.usdt_contract,
            "vault_address": self.get_vault_address(),
            "processed_deposits_count": len(self.state.get("processed_deposits", {})),
            "pending_withdrawals_count": len(self.state.get("pending_withdrawals", {})),
            "stats": self.state.get("stats", {})
        }
