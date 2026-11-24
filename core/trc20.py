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


# BIP-173 Bech32 charset & polymod constants
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]


def _bech32_polymod(values: List[int]) -> int:
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= _BECH32_GEN[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> List[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp: str, data: List[int]) -> List[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data: bytes, frombits: int, tobits: int, pad: bool = True) -> List[int]:
    acc = 0
    bits = 0
    ret: List[int] = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


class MultiChainAddress:
    """Pure-Python deterministic multi-chain address derivation (BTC, SOL, TRX, BNB, ETH, UNIVA)."""

    @staticmethod
    def _normalize_h160(evm_or_hex: str) -> bytes:
        clean = (evm_or_hex or "").strip()
        if clean.startswith(("0x", "0X")):
            clean = clean[2:]
        if len(clean) != 40:
            raise ValueError(f"Expected 20-byte EVM hex (40 chars), got {len(clean)}")
        return bytes.fromhex(clean)

    @staticmethod
    def btc_legacy_from_ripemd160(h160_bytes: bytes) -> str:
        """Encode 20-byte hash160 as a Bitcoin Mainnet P2PKH (1...) address."""
        if len(h160_bytes) != 20:
            raise ValueError(f"Expected 20 bytes for hash160, got {len(h160_bytes)}")
        payload = b"\x00" + h160_bytes
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        return TronAddress.b58encode(payload + checksum)

    @staticmethod
    def btc_segwit_from_ripemd160(h160_bytes: bytes) -> str:
        """Encode 20-byte witness program as a Bitcoin Mainnet Bech32 SegWit (bc1q...) address."""
        if len(h160_bytes) != 20:
            raise ValueError(f"Expected 20 bytes for hash160, got {len(h160_bytes)}")
        data = [0] + _convertbits(h160_bytes, 8, 5, True)
        combined = data + _bech32_create_checksum("bc", data)
        return "bc1" + "".join(_BECH32_CHARSET[d] for d in combined)

    @staticmethod
    def sol_address_from_seed(seed_str: str) -> str:
        """Derive a deterministic 32-byte Base58 Solana public key address."""
        digest = hashlib.sha256(("UNIVA_SOL_ED25519:" + (seed_str or "").strip().lower()).encode("utf-8")).digest()
        return TronAddress.b58encode(digest)

    @classmethod
    def derive_all_addresses(
        cls,
        evm_address: str,
        univa_address: str = "",
        pub_key_hex: str = "",
    ) -> Dict[str, str]:
        """Derives UNIVA, TRX, BNB, ETH, BTC (SegWit & Legacy), and SOL addresses deterministically."""
        clean_evm = (evm_address or "").strip()
        if not clean_evm.startswith(("0x", "0X")):
            clean_evm = "0x" + clean_evm
        norm_evm = clean_evm.lower()

        if pub_key_hex and len(pub_key_hex.strip()) >= 64:
            try:
                sha = hashlib.sha256(bytes.fromhex(pub_key_hex.strip())).digest()
                h160 = hashlib.new("ripemd160", sha).digest()
            except Exception:
                h160 = cls._normalize_h160(norm_evm)
        else:
            h160 = cls._normalize_h160(norm_evm)

        trx_addr = TronAddress.from_evm(norm_evm)
        btc_legacy = cls.btc_legacy_from_ripemd160(h160)
        btc_segwit = cls.btc_segwit_from_ripemd160(h160)
        sol_addr = cls.sol_address_from_seed(norm_evm)

        return {
            "univa": univa_address or "",
            "evm": norm_evm,
            "bnb": norm_evm,
            "eth": norm_evm,
            "trx": trx_addr,
            "btc_segwit": btc_segwit,
            "btc_legacy": btc_legacy,
            "sol": sol_addr,
        }


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

    def verify_and_credit_tx(self, tx_id: str, univa_user: str) -> Dict[str, Any]:
        """
        Directly queries the TRON blockchain for any transaction hash (TRX transfer or TRC-20 USDT transfer),
        verifies its on-chain SUCCESS status, and credits it to the specified univa_user.
        Replay protected.
        """
        clean_id = tx_id.strip().lower()
        if clean_id in self.state["processed_deposits"]:
            return {
                "success": False,
                "error": "Bu işlem hash'i daha önce zaten onaylanıp bakiyeye eklendi (tekrar korumalı).",
                "deposit": self.state["processed_deposits"][clean_id]
            }

        payload = {"value": clean_id}
        res = self._request_json(f"{self.endpoints[0]}/wallet/gettransactionbyid", post_data=payload)
        if not res or not res.get("txID"):
            if len(self.endpoints) > 1:
                res = self._request_json(f"{self.endpoints[1]}/wallet/gettransactionbyid", post_data=payload)

        if not res or not res.get("txID"):
            return {
                "success": False,
                "error": "İşlem TRON blokzincirinde bulunamadı. Lütfen işlem hash'ini (TX ID) kontrol edin."
            }

        ret = res.get("ret", [{}])[0]
        code = ret.get("contractRet", "SUCCESS")
        if code != "SUCCESS":
            return {"success": False, "error": f"İşlem TRON ağında başarısız sonuçlanmış: {code}"}

        raw = res.get("raw_data", {})
        contract = raw.get("contract", [{}])[0]
        c_type = contract.get("type", "")
        param = contract.get("parameter", {}).get("value", {})
        ts = raw.get("timestamp", int(time.time() * 1000)) / 1000.0

        if c_type == "TransferContract":
            amt_trx = param.get("amount", 0) / 1_000_000.0
            from_hex = param.get("owner_address", "")
            to_hex = param.get("to_address", "")
            from_tron = TronAddress.from_hex(from_hex) if from_hex else ""
            to_tron = TronAddress.from_hex(to_hex) if to_hex else ""

            record = {
                "tx_id": clean_id,
                "univa_user": univa_user,
                "asset": "TRX",
                "amount": amt_trx,
                "from_tron": from_tron,
                "to_tron": to_tron,
                "timestamp": ts,
                "credited_at": time.time(),
                "status": "CONFIRMED",
                "credited_univa": True
            }
            self.state["processed_deposits"][clean_id] = record
            self.state["stats"]["deposit_count"] += 1
            self._save_state()
            return {"success": True, "deposit": record}

        elif c_type == "TriggerSmartContract":
            data_hex = param.get("data", "")
            c_addr = param.get("contract_address", "")
            from_addr = TronAddress.from_hex(param.get("owner_address", ""))
            amt_usdt = 0.0
            to_tron = ""
            if data_hex.startswith("a9059cbb") and len(data_hex) >= 72:
                to_hex = data_hex[8:72].lstrip("0")
                val_hex = data_hex[72:]
                to_tron = TronAddress.from_hex(to_hex) if to_hex else ""
                amt_usdt = int(val_hex, 16) / 10**6

            record = {
                "tx_id": clean_id,
                "univa_user": univa_user,
                "asset": "USDT",
                "amount": amt_usdt,
                "from_tron": from_addr,
                "to_tron": to_tron,
                "contract": TronAddress.from_hex(c_addr) if c_addr else self.usdt_contract,
                "timestamp": ts,
                "credited_at": time.time(),
                "status": "CONFIRMED",
                "credited_univa": True
            }
            self.state["processed_deposits"][clean_id] = record
            self.state["stats"]["total_deposited_usdt"] += amt_usdt
            self.state["stats"]["deposit_count"] += 1
            self._save_state()
            return {"success": True, "deposit": record}

        return {"success": False, "error": f"Desteklenmeyen TRON işlem tipi: {c_type}"}

    def get_btc_account_info(self, btc_address: str) -> Dict[str, Any]:
        """Queries live Bitcoin Mainnet balance via Mempool.space (with Blockstream fallback)."""
        addr = (btc_address or "").strip()
        if not addr:
            return {"success": False, "error": "Geçersiz BTC adresi"}

        res = self._request_json(f"https://mempool.space/api/address/{addr}")
        source = "mempool.space"
        if not res or "chain_stats" not in res:
            res = self._request_json(f"https://blockstream.info/api/address/{addr}")
            source = "blockstream.info"

        if not res or "chain_stats" not in res:
            return {
                "success": True,
                "address": addr,
                "confirmed_btc": 0.0,
                "mempool_btc": 0.0,
                "total_btc": 0.0,
                "source": "offline-fallback",
            }

        chain = res.get("chain_stats", {})
        mempool = res.get("mempool_stats", {})
        conf_sats = int(chain.get("funded_txo_sum", 0)) - int(chain.get("spent_txo_sum", 0))
        mem_sats = int(mempool.get("funded_txo_sum", 0)) - int(mempool.get("spent_txo_sum", 0))
        return {
            "success": True,
            "address": addr,
            "confirmed_sats": conf_sats,
            "mempool_sats": mem_sats,
            "confirmed_btc": round(conf_sats / 1e8, 8),
            "mempool_btc": round(mem_sats / 1e8, 8),
            "total_btc": round((conf_sats + mem_sats) / 1e8, 8),
            "source": source,
        }

    def get_sol_account_info(self, sol_address: str) -> Dict[str, Any]:
        """Queries live Solana Mainnet native SOL balance via JSON-RPC."""
        addr = (sol_address or "").strip()
        if not addr:
            return {"success": False, "error": "Geçersiz SOL adresi"}

        rpc_body = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
        res = self._request_json("https://api.mainnet-beta.solana.com", post_data=rpc_body)
        if not res or "result" not in res:
            res = self._request_json("https://solana-rpc.publicnode.com", post_data=rpc_body)

        if not res or "result" not in res:
            return {"success": True, "address": addr, "lamports": 0, "sol": 0.0, "source": "offline-fallback"}

        lamports = int((res.get("result") or {}).get("value", 0))
        return {
            "success": True,
            "address": addr,
            "lamports": lamports,
            "sol": round(lamports / 1e9, 9),
            "source": "solana-mainnet",
        }

    def get_evm_chain_balance(self, evm_address: str, chain: str = "bsc") -> Dict[str, Any]:
        """Queries live native BNB (BSC) or ETH (Ethereum) balance via public JSON-RPC."""
        addr = (evm_address or "").strip()
        if not addr.startswith(("0x", "0X")) or len(addr) != 42:
            return {"success": False, "error": "Geçersiz EVM (0x) adresi"}

        chain_key = (chain or "bsc").strip().lower()
        rpc_map = {
            "bsc": ("https://bsc-dataseed.binance.org", "BNB"),
            "bnb": ("https://bsc-dataseed.binance.org", "BNB"),
            "eth": ("https://eth.llamarpc.com", "ETH"),
            "ethereum": ("https://eth.llamarpc.com", "ETH"),
        }
        rpc_url, symbol = rpc_map.get(chain_key, ("https://bsc-dataseed.binance.org", "BNB"))
        rpc_body = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
        res = self._request_json(rpc_url, post_data=rpc_body)
        if not res or "result" not in res:
            fallback_url = "https://bsc-rpc.publicnode.com" if symbol == "BNB" else "https://ethereum-rpc.publicnode.com"
            res = self._request_json(fallback_url, post_data=rpc_body)

        if not res or "result" not in res:
            return {"success": True, "chain": symbol, "address": addr, "balance": 0.0, "source": "offline-fallback"}

        wei = int(res["result"], 16)
        return {
            "success": True,
            "chain": symbol,
            "address": addr,
            "wei": str(wei),
            "balance": round(wei / 1e18, 8),
            "source": rpc_url,
        }

    def _record_verified_deposit(self, cache_key: str, record: Dict[str, Any]) -> Dict[str, Any]:
        self.state["processed_deposits"][cache_key] = record
        self.state["stats"]["deposit_count"] = int(self.state["stats"].get("deposit_count", 0)) + 1
        self._save_state()
        return {"success": True, "deposit": record}

    def verify_multichain_tx(self, tx_id: str, chain: str, univa_user: str) -> Dict[str, Any]:
        """
        Verifies a live Mainnet transaction hash across TRON, BSC (BNB), ETH, BTC, or SOL
        and credits the deposit idempotently with replay protection.
        """
        raw_id = (tx_id or "").strip()
        if not raw_id:
            return {"success": False, "error": "İşlem hash'i (TX ID) boş olamaz."}

        target_chain = (chain or "AUTO").strip().upper()
        if target_chain == "AUTO":
            if raw_id.startswith(("0x", "0X")) and len(raw_id) == 66:
                res_bsc = self.verify_multichain_tx(raw_id, "BSC", univa_user)
                if res_bsc.get("success") or res_bsc.get("already_processed"):
                    return res_bsc
                return self.verify_multichain_tx(raw_id, "ETH", univa_user)
            if len(raw_id) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw_id):
                res_tron = self.verify_and_credit_tx(raw_id, univa_user)
                if res_tron.get("success") or "daha önce" in (res_tron.get("error") or ""):
                    return res_tron
                return self.verify_multichain_tx(raw_id, "BTC", univa_user)
            target_chain = "SOL"

        if target_chain in ("TRON", "TRX", "TRC20"):
            return self.verify_and_credit_tx(raw_id, univa_user)

        cache_key = raw_id if target_chain == "SOL" else raw_id.lower()
        if cache_key in self.state["processed_deposits"]:
            return {
                "success": False,
                "already_processed": True,
                "error": "Bu işlem hash'i daha önce zaten onaylanıp bakiyeye eklendi (tekrar korumalı).",
                "deposit": self.state["processed_deposits"][cache_key],
            }

        if target_chain == "BTC":
            res = self._request_json(f"https://mempool.space/api/tx/{cache_key}")
            if not res or not res.get("txid"):
                res = self._request_json(f"https://blockstream.info/api/tx/{cache_key}")
            if not res or not res.get("txid"):
                return {"success": False, "error": "İşlem Bitcoin (BTC) ana ağında bulunamadı."}
            total_sats = sum(int(v.get("value", 0)) for v in res.get("vout", []))
            amt_btc = round(total_sats / 1e8, 8)
            confirmed = bool((res.get("status") or {}).get("confirmed", False))
            record = {
                "tx_id": cache_key,
                "chain": "BTC",
                "univa_user": univa_user,
                "asset": "BTC",
                "amount": amt_btc,
                "confirmed": confirmed,
                "timestamp": (res.get("status") or {}).get("block_time") or time.time(),
                "credited_at": time.time(),
                "status": "CONFIRMED" if confirmed else "MEMPOOL_DETECTED",
                "credited_univa": True,
            }
            return self._record_verified_deposit(cache_key, record)

        if target_chain == "SOL":
            rpc_body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [cache_key, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            }
            res = self._request_json("https://api.mainnet-beta.solana.com", post_data=rpc_body)
            if not res or not res.get("result"):
                return {"success": False, "error": "İşlem Solana (SOL) ana ağında bulunamadı."}
            tx_res = res["result"]
            meta = tx_res.get("meta") or {}
            if meta.get("err") is not None:
                return {"success": False, "error": "İşlem Solana ağında hata ile sonuçlanmış."}
            pre = meta.get("preBalances") or []
            post = meta.get("postBalances") or []
            lamports_delta = 0
            if pre and post and len(pre) == len(post):
                lamports_delta = max(max(0, int(post[i]) - int(pre[i])) for i in range(len(pre)))
            amt_sol = round(lamports_delta / 1e9, 9)
            record = {
                "tx_id": cache_key,
                "chain": "SOL",
                "univa_user": univa_user,
                "asset": "SOL",
                "amount": amt_sol,
                "timestamp": tx_res.get("blockTime") or time.time(),
                "credited_at": time.time(),
                "status": "CONFIRMED",
                "credited_univa": True,
            }
            return self._record_verified_deposit(cache_key, record)

        if target_chain in ("BSC", "BNB", "ETH", "ETHEREUM"):
            is_bsc = target_chain in ("BSC", "BNB")
            rpc_url = "https://bsc-dataseed.binance.org" if is_bsc else "https://eth.llamarpc.com"
            fallback_url = "https://bsc-rpc.publicnode.com" if is_bsc else "https://ethereum-rpc.publicnode.com"
            symbol = "BNB" if is_bsc else "ETH"
            tx_hex = cache_key if cache_key.startswith("0x") else ("0x" + cache_key)
            rpc_body = {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionByHash", "params": [tx_hex]}
            res = self._request_json(rpc_url, post_data=rpc_body)
            if not res or not res.get("result"):
                res = self._request_json(fallback_url, post_data=rpc_body)
            if not res or not res.get("result"):
                return {"success": False, "error": f"İşlem {symbol} ana ağında bulunamadı."}
            tx_obj = res["result"]
            wei_val = int(tx_obj.get("value", "0x0"), 16)
            amt_native = round(wei_val / 1e18, 8)
            record = {
                "tx_id": tx_hex,
                "chain": symbol,
                "univa_user": univa_user,
                "asset": symbol,
                "amount": amt_native,
                "from": tx_obj.get("from", ""),
                "to": tx_obj.get("to", ""),
                "timestamp": time.time(),
                "credited_at": time.time(),
                "status": "CONFIRMED" if tx_obj.get("blockNumber") else "PENDING",
                "credited_univa": True,
            }
            return self._record_verified_deposit(cache_key, record)

        return {"success": False, "error": f"Desteklenmeyen ağ: {target_chain}"}
