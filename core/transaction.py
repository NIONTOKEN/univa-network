"""
UNIVA Network - Transaction Module
Unified canonical signing and verification format aligned with Blockchain consensus.
"""

import hashlib
import json
import time
from typing import Optional
from core.wallet import UnivaWallet


def canonical_tx_message(tx: dict) -> str:
    """Single canonical JSON representation signed by wallets and verified by consensus."""
    fields = {
        k: tx.get(k)
        for k in ("type", "from", "to", "amount", "fee", "nonce", "public_key")
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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


def verify_transaction(tx: dict) -> bool:
    """Stateless cryptographic verification using the exact consensus canonical message."""
    required = ("from", "to", "amount", "fee", "nonce", "public_key", "signature", "tx_id")
    if not isinstance(tx, dict) or tx.get("type", "transfer") != "transfer":
        return False
    if any(k not in tx for k in required):
        return False
    try:
        from core.wallet import (
            REGISTERED_PWA_ORIGINS,
            derive_evm_address,
            derive_legacy_20char_address,
            derive_univa_address,
            validate_address,
        )

        amount = float(tx["amount"])
        fee = float(tx["fee"])
        nonce = tx["nonce"]
        if not (amount > 0 and fee >= 0 and amount < float("inf") and fee < float("inf")):
            return False
        if round(amount, 8) != amount or round(fee, 8) != fee:
            return False
        if not isinstance(nonce, int) or isinstance(nonce, bool) or nonce < 0:
            return False
        if not validate_address(tx["from"]) or not validate_address(tx["to"]):
            return False

        valid_origins = {
            derive_univa_address(tx["public_key"]),
            derive_legacy_20char_address(tx["public_key"]),
            derive_evm_address(tx["public_key"]),
        } | REGISTERED_PWA_ORIGINS.get(tx["public_key"], set())
        if tx["from"] not in valid_origins:
            return False

        canon_tx = {**tx, "type": tx.get("type", "transfer")}
        msg = canonical_tx_message(canon_tx)
        tx_digest = hashlib.sha256(msg.encode("utf-8")).hexdigest()
        if tx["tx_id"] != tx_digest:
            return False
        return UnivaWallet.verify_signature(tx["public_key"], msg, tx["signature"])
    except Exception:
        return False
