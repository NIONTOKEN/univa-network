"""
UNIVA Network - Transaction Module
"""

import hashlib
import json
import time
from core.wallet import UnivaWallet


def build_transaction(
    sender_wallet: UnivaWallet,
    to_address: str,
    amount: float,
    fee: float = 0.001,
    memo: str = "",
) -> dict:
    tx_body = {
        "from":      sender_wallet.address,
        "to":        to_address,
        "amount":    round(amount, 8),
        "fee":       round(fee, 8),
        "memo":      memo,
        "timestamp": time.time(),
        "nonce":     int(time.time() * 1000),
    }
    msg       = json.dumps(tx_body, sort_keys=True)
    signature = sender_wallet.sign(msg)

    return {
        **tx_body,
        "type":       "transfer",
        "public_key": sender_wallet.public_key,
        "signature":  signature,
        "tx_id":      hashlib.sha256(msg.encode()).hexdigest(),
    }


def verify_transaction(tx: dict) -> bool:
    try:
        tx_body = {k: tx[k] for k in
                   ["from", "to", "amount", "fee", "memo", "timestamp", "nonce"]}
        msg = json.dumps(tx_body, sort_keys=True)
        return UnivaWallet.verify_signature(tx["public_key"], msg, tx["signature"])
    except Exception:
        return False
