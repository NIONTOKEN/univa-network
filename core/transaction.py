"""
UNIVA Network - Transaction Module
Unified canonical signing and verification format aligned with Blockchain consensus.
Supports:
  - `transfer`: standard L1 UNIVA transfer
  - `offline_reserve` / `offline_spend` / `offline_release`: P5-A on-chain offline escrow
  - `dex_swap` / `dex_add_liquidity` / `dex_remove_liquidity`: P7 on-chain consensus DEX AMM
"""

import hashlib
import json
import time
from typing import Optional
from core.wallet import UnivaWallet

DEX_TX_TYPES = ("dex_swap", "dex_add_liquidity", "dex_remove_liquidity")
NONCE_TX_TYPES = (
    "transfer",
    "offline_reserve",
    "offline_release",
    "dex_swap",
    "dex_add_liquidity",
    "dex_remove_liquidity",
)
SUPPORTED_TX_TYPES = (
    "transfer",
    "offline_reserve",
    "offline_spend",
    "offline_release",
    "dex_swap",
    "dex_add_liquidity",
    "dex_remove_liquidity",
)


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
    elif tx_type == "dex_swap":
        fields = {
            k: tx.get(k)
            for k in (
                "type",
                "from",
                "asset_in",
                "asset_out",
                "amount_in",
                "min_out",
                "fee",
                "nonce",
                "public_key",
            )
        }
    elif tx_type == "dex_add_liquidity":
        fields = {
            k: tx.get(k)
            for k in (
                "type",
                "from",
                "asset_a",
                "asset_b",
                "amount_a",
                "amount_b",
                "fee",
                "nonce",
                "public_key",
            )
        }
    elif tx_type == "dex_remove_liquidity":
        fields = {
            k: tx.get(k)
            for k in (
                "type",
                "from",
                "asset_a",
                "asset_b",
                "lp_amount",
                "fee",
                "nonce",
                "public_key",
            )
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


def build_dex_swap_tx(
    sender_wallet: UnivaWallet,
    asset_in: str,
    asset_out: str,
    amount_in: float,
    min_out: float = 0.0,
    fee: float = 0.001,
    nonce: Optional[int] = None,
    blockchain=None,
    from_address: Optional[str] = None,
) -> dict:
    from core.wallet import validate_address

    sender = from_address if (from_address and validate_address(from_address)) else sender_wallet.address
    amt_in = round(float(amount_in), 8)
    m_out = round(float(min_out), 8)
    tx_fee = round(float(fee), 8)
    a_in = str(asset_in or "").strip()
    a_out = str(asset_out or "").strip()
    if not a_in or not a_out or a_in.upper() == a_out.upper() or amt_in <= 0 or m_out < 0 or tx_fee < 0:
        raise ValueError("Invalid dex_swap parameters")

    resolved_nonce = (
        blockchain._pending_nonce(sender)
        if (nonce is None and blockchain is not None)
        else int(nonce or 0)
    )
    tx = {
        "type": "dex_swap",
        "from": sender,
        "asset_in": "uUSD" if a_in.upper() == "UUSD" else a_in.upper(),
        "asset_out": "uUSD" if a_out.upper() == "UUSD" else a_out.upper(),
        "amount_in": amt_in,
        "min_out": m_out,
        "fee": tx_fee,
        "nonce": resolved_nonce,
        "public_key": sender_wallet.public_key,
    }
    msg = canonical_tx_message(tx)
    tx["tx_id"] = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    tx["signature"] = sender_wallet.sign(msg)
    tx["timestamp"] = time.time()
    return tx


def build_dex_add_liquidity_tx(
    sender_wallet: UnivaWallet,
    asset_a: str,
    asset_b: str,
    amount_a: float,
    amount_b: float,
    fee: float = 0.001,
    nonce: Optional[int] = None,
    blockchain=None,
    from_address: Optional[str] = None,
) -> dict:
    from core.wallet import validate_address

    sender = from_address if (from_address and validate_address(from_address)) else sender_wallet.address
    amt_a = round(float(amount_a), 8)
    amt_b = round(float(amount_b), 8)
    tx_fee = round(float(fee), 8)
    a_s = "uUSD" if str(asset_a).strip().upper() == "UUSD" else str(asset_a).strip().upper()
    b_s = "uUSD" if str(asset_b).strip().upper() == "UUSD" else str(asset_b).strip().upper()
    if not a_s or not b_s or a_s == b_s or amt_a <= 0 or amt_b <= 0 or tx_fee < 0:
        raise ValueError("Invalid dex_add_liquidity parameters")

    resolved_nonce = (
        blockchain._pending_nonce(sender)
        if (nonce is None and blockchain is not None)
        else int(nonce or 0)
    )
    tx = {
        "type": "dex_add_liquidity",
        "from": sender,
        "asset_a": a_s,
        "asset_b": b_s,
        "amount_a": amt_a,
        "amount_b": amt_b,
        "fee": tx_fee,
        "nonce": resolved_nonce,
        "public_key": sender_wallet.public_key,
    }
    msg = canonical_tx_message(tx)
    tx["tx_id"] = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    tx["signature"] = sender_wallet.sign(msg)
    tx["timestamp"] = time.time()
    return tx


def build_dex_remove_liquidity_tx(
    sender_wallet: UnivaWallet,
    asset_a: str,
    asset_b: str,
    lp_amount: float,
    fee: float = 0.001,
    nonce: Optional[int] = None,
    blockchain=None,
    from_address: Optional[str] = None,
) -> dict:
    from core.wallet import validate_address

    sender = from_address if (from_address and validate_address(from_address)) else sender_wallet.address
    lp_amt = round(float(lp_amount), 8)
    tx_fee = round(float(fee), 8)
    a_s = "uUSD" if str(asset_a).strip().upper() == "UUSD" else str(asset_a).strip().upper()
    b_s = "uUSD" if str(asset_b).strip().upper() == "UUSD" else str(asset_b).strip().upper()
    if not a_s or not b_s or a_s == b_s or lp_amt <= 0 or tx_fee < 0:
        raise ValueError("Invalid dex_remove_liquidity parameters")

    resolved_nonce = (
        blockchain._pending_nonce(sender)
        if (nonce is None and blockchain is not None)
        else int(nonce or 0)
    )
    tx = {
        "type": "dex_remove_liquidity",
        "from": sender,
        "asset_a": a_s,
        "asset_b": b_s,
        "lp_amount": lp_amt,
        "fee": tx_fee,
        "nonce": resolved_nonce,
        "public_key": sender_wallet.public_key,
    }
    msg = canonical_tx_message(tx)
    tx["tx_id"] = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    tx["signature"] = sender_wallet.sign(msg)
    tx["timestamp"] = time.time()
    return tx


def verify_transaction(tx: dict, network: Optional[str] = None) -> bool:
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
            if not validate_address(tx["from"], network=network) or not validate_address(tx["to"], network=network):
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
            if not validate_address(tx["from"], network=network):
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
            if not validate_address(tx["from"], network=network) or not validate_address(tx["to"], network=network):
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
            if not validate_address(tx["from"], network=network):
                return False
        elif tx_type == "dex_swap":
            required = (
                "from", "asset_in", "asset_out", "amount_in", "min_out",
                "fee", "nonce", "public_key", "signature", "tx_id",
            )
            if any(k not in tx for k in required):
                return False
            amount_in, min_out, fee, nonce = (
                float(tx["amount_in"]), float(tx["min_out"]), float(tx["fee"]), tx["nonce"]
            )
            if not (amount_in > 0 and min_out >= 0 and fee >= 0 and amount_in < float("inf")):
                return False
            if round(amount_in, 8) != amount_in or round(min_out, 8) != min_out or round(fee, 8) != fee:
                return False
            if not isinstance(nonce, int) or isinstance(nonce, bool) or nonce < 0:
                return False
            if not tx["asset_in"] or not tx["asset_out"] or str(tx["asset_in"]).upper() == str(tx["asset_out"]).upper():
                return False
            if not validate_address(tx["from"], network=network):
                return False
        elif tx_type == "dex_add_liquidity":
            required = (
                "from", "asset_a", "asset_b", "amount_a", "amount_b",
                "fee", "nonce", "public_key", "signature", "tx_id",
            )
            if any(k not in tx for k in required):
                return False
            amt_a, amt_b, fee, nonce = (
                float(tx["amount_a"]), float(tx["amount_b"]), float(tx["fee"]), tx["nonce"]
            )
            if not (amt_a > 0 and amt_b > 0 and fee >= 0 and amt_a < float("inf") and amt_b < float("inf")):
                return False
            if round(amt_a, 8) != amt_a or round(amt_b, 8) != amt_b or round(fee, 8) != fee:
                return False
            if not isinstance(nonce, int) or isinstance(nonce, bool) or nonce < 0:
                return False
            if not tx["asset_a"] or not tx["asset_b"] or str(tx["asset_a"]).upper() == str(tx["asset_b"]).upper():
                return False
            if not validate_address(tx["from"], network=network):
                return False
        elif tx_type == "dex_remove_liquidity":
            required = (
                "from", "asset_a", "asset_b", "lp_amount",
                "fee", "nonce", "public_key", "signature", "tx_id",
            )
            if any(k not in tx for k in required):
                return False
            lp_amt, fee, nonce = float(tx["lp_amount"]), float(tx["fee"]), tx["nonce"]
            if not (lp_amt > 0 and fee >= 0 and lp_amt < float("inf")):
                return False
            if round(lp_amt, 8) != lp_amt or round(fee, 8) != fee:
                return False
            if not isinstance(nonce, int) or isinstance(nonce, bool) or nonce < 0:
                return False
            if not tx["asset_a"] or not tx["asset_b"] or str(tx["asset_a"]).upper() == str(tx["asset_b"]).upper():
                return False
            if not validate_address(tx["from"], network=network):
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
