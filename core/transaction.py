"""
UNIVA Network - Transaction Module
Unified canonical signing and verification format aligned with Blockchain consensus.
Supports L1 `transfer` and on-chain P5-A Offline Pay escrow types:
  - `offline_reserve`: locks UNIVA into an on-chain time-bounded escrow reservation
  - `offline_spend`: spends directly from an active reservation without touching account nonce
  - `offline_release`: releases remaining unspent escrow back to the owner before expiry
"""

import hashlib
import json
import time
from typing import Optional
from core.wallet import UnivaWallet

NONCE_TX_TYPES = ("transfer", "offline_reserve", "offline_release")
SUPPORTED_TX_TYPES = ("transfer", "offline_reserve", "offline_spend", "offline_release")


def canonical_tx_message(tx: dict) -> str:
    """Single canonical JSON representation signed by wallets and verified by consensus."""
    tx_type = tx.get("type", "transfer")
    if tx_type == "offline_reserve":
        fields = {
            k: tx.get(k)
            for k in ("type", "from", "amount", "fee", "nonce", "expires_at", "public_key")
        }
    elif tx_type == "offline_spend":
        fields = {
            k: tx.get(k)
            for k in (
                "type",
                "reservation_id",
                "from",
                "to",
                "amount",
                "fee",
                "voucher_nonce",
                "expires_at",
                "public_key",
            )
        }
    elif tx_type == "offline_release":
        fields = {
            k: tx.get(k)
            for k in ("type", "reservation_id", "from", "fee", "nonce", "public_key")
        }
    else:
        fields = {
            k: tx.get(k)
            for k in ("type", "from", "to", "amount", "fee", "nonce", "public_key")
        }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def derive_reservation_id(tx_id: str) -> str:
    return "res_" + str(tx_id)[:20]


def build_transaction(
    sender_wallet: UnivaWallet,
    to_address: str,
    amount: float,
    fee: float = 0.001,
    memo: str = "",
    nonce: Optional[int] = None,
    blockchain=None,
    from_address: Optional[str] = None,
) -> dict:
    from core.wallet import validate_address

    if not validate_address(to_address):
        raise ValueError(f"Invalid recipient address: {to_address}")
    sender = from_address if (from_address and validate_address(from_address)) else sender_wallet.address
    amt = round(float(amount), 8)
    tx_fee = round(float(fee), 8)
    if amt <= 0 or tx_fee < 0:
        raise ValueError("Amount must be positive and fee non-negative")

    if nonce is None:
        resolved_nonce = blockchain._pending_nonce(sender) if blockchain is not None else 0
    else:
        resolved_nonce = int(nonce)

    tx = {
        "type": "transfer",
        "from": sender,
        "to": to_address,
        "amount": amt,
        "fee": tx_fee,
        "nonce": resolved_nonce,
        "public_key": sender_wallet.public_key,
    }
    msg = canonical_tx_message(tx)
    tx["signature"] = sender_wallet.sign(msg)
    tx["tx_id"] = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    tx["timestamp"] = time.time()
    if memo:
        tx["memo"] = memo
    return tx


def build_offline_reserve_tx(
    sender_wallet: UnivaWallet,
    amount: float,
    expires_at: int,
    fee: float = 0.001,
    nonce: Optional[int] = None,
    blockchain=None,
    from_address: Optional[str] = None,
) -> dict:
    from core.wallet import validate_address

    sender = from_address if (from_address and validate_address(from_address)) else sender_wallet.address
    amt = round(float(amount), 8)
    tx_fee = round(float(fee), 8)
    exp = int(expires_at)
    if amt <= 0 or tx_fee < 0 or exp <= 0:
        raise ValueError("Invalid offline_reserve amount, fee, or expires_at")

    resolved_nonce = (
        blockchain._pending_nonce(sender)
        if (nonce is None and blockchain is not None)
        else int(nonce or 0)
    )
    tx = {
        "type": "offline_reserve",
        "from": sender,
        "amount": amt,
        "fee": tx_fee,
        "nonce": resolved_nonce,
        "expires_at": exp,
        "public_key": sender_wallet.public_key,
    }
    msg = canonical_tx_message(tx)
    tx_id = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    tx["tx_id"] = tx_id
    tx["reservation_id"] = derive_reservation_id(tx_id)
    tx["signature"] = sender_wallet.sign(msg)
    tx["timestamp"] = time.time()
    return tx


def build_offline_spend_tx(
    sender_wallet: UnivaWallet,
    reservation_id: str,
    to_address: str,
    amount: float,
    voucher_nonce: int,
    expires_at: int,
    fee: float = 0.001,
    from_address: Optional[str] = None,
) -> dict:
    from core.wallet import validate_address

    if not validate_address(to_address):
        raise ValueError(f"Invalid recipient address: {to_address}")
    res_id = str(reservation_id or "").strip()
    if not res_id:
        raise ValueError("reservation_id is required for offline_spend")
    sender = from_address if (from_address and validate_address(from_address)) else sender_wallet.address
    amt = round(float(amount), 8)
    tx_fee = round(float(fee), 8)
    v_nonce = int(voucher_nonce)
    exp = int(expires_at)
    if amt <= 0 or tx_fee < 0 or v_nonce < 0 or exp <= 0:
        raise ValueError("Invalid offline_spend parameters")

    tx = {
        "type": "offline_spend",
        "reservation_id": res_id,
        "from": sender,
        "to": to_address,
        "amount": amt,
        "fee": tx_fee,
        "voucher_nonce": v_nonce,
        "expires_at": exp,
        "public_key": sender_wallet.public_key,
    }
    msg = canonical_tx_message(tx)
    tx["tx_id"] = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    tx["signature"] = sender_wallet.sign(msg)
    tx["timestamp"] = time.time()
    return tx


def build_offline_release_tx(
    sender_wallet: UnivaWallet,
    reservation_id: str,
    fee: float = 0.001,
    nonce: Optional[int] = None,
    blockchain=None,
    from_address: Optional[str] = None,
) -> dict:
    from core.wallet import validate_address

    res_id = str(reservation_id or "").strip()
    if not res_id:
        raise ValueError("reservation_id is required for offline_release")
    sender = from_address if (from_address and validate_address(from_address)) else sender_wallet.address
    tx_fee = round(float(fee), 8)
    if tx_fee < 0:
        raise ValueError("Fee must be non-negative")

    resolved_nonce = (
        blockchain._pending_nonce(sender)
        if (nonce is None and blockchain is not None)
        else int(nonce or 0)
    )
    tx = {
        "type": "offline_release",
        "reservation_id": res_id,
        "from": sender,
        "fee": tx_fee,
        "nonce": resolved_nonce,
        "public_key": sender_wallet.public_key,
    }
    msg = canonical_tx_message(tx)
    tx["tx_id"] = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    tx["signature"] = sender_wallet.sign(msg)
    tx["timestamp"] = time.time()
    return tx


def verify_transaction(tx: dict) -> bool:
    """Stateless cryptographic verification using the exact consensus canonical message."""
    if not isinstance(tx, dict):
        return False
    tx_type = tx.get("type", "transfer")
    if tx_type not in SUPPORTED_TX_TYPES:
        return False
    try:
        from core.wallet import get_valid_sender_addresses, normalize_address, validate_address

        if tx_type == "transfer":
            required = ("from", "to", "amount", "fee", "nonce", "public_key", "signature", "tx_id")
            if any(k not in tx for k in required):
                return False
            amount, fee, nonce = float(tx["amount"]), float(tx["fee"]), tx["nonce"]
            if not (amount > 0 and fee >= 0 and amount < float("inf") and fee < float("inf")):
                return False
            if round(amount, 8) != amount or round(fee, 8) != fee:
                return False
            if not isinstance(nonce, int) or isinstance(nonce, bool) or nonce < 0:
                return False
            if not validate_address(tx["from"]) or not validate_address(tx["to"]):
                return False
        elif tx_type == "offline_reserve":
            required = ("from", "amount", "fee", "nonce", "expires_at", "public_key", "signature", "tx_id")
            if any(k not in tx for k in required):
                return False
            amount, fee, nonce, exp = float(tx["amount"]), float(tx["fee"]), tx["nonce"], tx["expires_at"]
            if not (amount > 0 and fee >= 0 and amount < float("inf") and fee < float("inf")):
                return False
            if round(amount, 8) != amount or round(fee, 8) != fee:
                return False
            if not isinstance(nonce, int) or isinstance(nonce, bool) or nonce < 0:
                return False
            if not isinstance(exp, int) or isinstance(exp, bool) or exp <= 0:
                return False
            if not validate_address(tx["from"]):
                return False
            expected_rid = derive_reservation_id(tx["tx_id"])
            if tx.get("reservation_id") and tx.get("reservation_id") != expected_rid:
                return False
        elif tx_type == "offline_spend":
            required = (
                "reservation_id",
                "from",
                "to",
                "amount",
                "fee",
                "voucher_nonce",
                "expires_at",
                "public_key",
                "signature",
                "tx_id",
            )
            if any(k not in tx for k in required):
                return False
            amount, fee = float(tx["amount"]), float(tx["fee"])
            v_nonce, exp = tx["voucher_nonce"], tx["expires_at"]
            if not (amount > 0 and fee >= 0 and amount < float("inf") and fee < float("inf")):
                return False
            if round(amount, 8) != amount or round(fee, 8) != fee:
                return False
            if not isinstance(v_nonce, int) or isinstance(v_nonce, bool) or v_nonce < 0:
                return False
            if not isinstance(exp, int) or isinstance(exp, bool) or exp <= 0:
                return False
            if not str(tx.get("reservation_id") or "").strip():
                return False
            if not validate_address(tx["from"]) or not validate_address(tx["to"]):
                return False
        elif tx_type == "offline_release":
            required = ("reservation_id", "from", "fee", "nonce", "public_key", "signature", "tx_id")
            if any(k not in tx for k in required):
                return False
            fee, nonce = float(tx["fee"]), tx["nonce"]
            if not (fee >= 0 and fee < float("inf")) or round(fee, 8) != fee:
                return False
            if not isinstance(nonce, int) or isinstance(nonce, bool) or nonce < 0:
                return False
            if not str(tx.get("reservation_id") or "").strip():
                return False
            if not validate_address(tx["from"]):
                return False

        if normalize_address(tx["from"]) not in get_valid_sender_addresses(tx["public_key"]):
            return False

        canon_tx = {**tx, "type": tx_type}
        msg = canonical_tx_message(canon_tx)
        tx_digest = hashlib.sha256(msg.encode("utf-8")).hexdigest()
        if tx["tx_id"] != tx_digest:
            return False
        return UnivaWallet.verify_signature(tx["public_key"], msg, tx["signature"])
    except Exception:
        return False
