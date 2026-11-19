"""UNIVA Offline Pay Protocol Engine (P5).

Provides:
- Standardized Offline Voucher V2 encoding/decoding (`UNIVA:OFF:V2:<base64>`) with
  backward-compatible V1 support (`UNIVA:OFF:V1:<base64>`), TTL expiration, and
  optional reservation binding.
- Node-level Offline Balance Reservation (escrow lock) so senders can reserve a
  bounded UNIVA budget online before going air-gapped, preventing online spending
  or cumulative offline over-spending of reserved funds.
- Replay protection (`used_voucher_txids`, `used_signatures`, per-user offline nonces).
- Honest settlement status reporting (`signed_offline` -> `verified_unsettled` ->
  `in_mempool` -> `confirmed`), never marking unmined vouchers as final.

Note: Reservations here operate at the node/API guard layer without modifying
existing L1 block consensus rules. Full on-chain consensus escrow transactions
can be enabled later once approved by governance.
"""
import base64
import hashlib
import json
import os
import shutil
import threading
import time
from typing import Any, Dict, List, Optional

from core.transaction import canonical_tx_message
from core.wallet import UnivaWallet, get_valid_sender_addresses, normalize_address

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFLINE_STATE_FILE = os.path.join(_BASE_DIR, "univa_offline_state.json")

MIN_RESERVATION_TTL = 60          # 1 minute
MAX_RESERVATION_TTL = 30 * 86400  # 30 days
DEFAULT_VOUCHER_TTL = 24 * 3600   # 24 hours

VOUCHER_PREFIX_V2 = "UNIVA:OFF:V2:"
VOUCHER_PREFIX_V1 = "UNIVA:OFF:V1:"


def canonical_voucher_meta_message(tx_id: str, reservation_id: str, expires_at: int) -> str:
    return f"UNIVA_OFFLINE_V2|{tx_id}|{reservation_id or ''}|{int(expires_at)}"


def encode_voucher_v2(
    tx: dict,
    expires_at: int,
    reservation_id: str = "",
    transport: str = "qr",
    voucher_sig: str = "",
) -> str:
    payload = {
        "version": 2,
        "tx": tx,
        "created_at": int(time.time()),
        "expires_at": int(expires_at),
        "reservation_id": reservation_id or "",
        "transport": transport or "qr",
    }
    if voucher_sig:
        payload["voucher_sig"] = voucher_sig
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return VOUCHER_PREFIX_V2 + base64.b64encode(raw).decode("ascii")


def decode_voucher(raw_or_dict: Any) -> dict:
    if isinstance(raw_or_dict, dict):
        if "tx" in raw_or_dict and isinstance(raw_or_dict["tx"], dict):
            return {
                "version": int(raw_or_dict.get("version", 2)),
                "tx": dict(raw_or_dict["tx"]),
                "created_at": int(raw_or_dict.get("created_at", 0) or 0),
                "expires_at": int(raw_or_dict.get("expires_at", 0) or 0),
                "reservation_id": str(raw_or_dict.get("reservation_id") or "").strip(),
                "transport": str(raw_or_dict.get("transport") or "qr").strip().lower(),
                "voucher_sig": str(raw_or_dict.get("voucher_sig") or "").strip(),
            }
        # Raw V1 tx dict directly
        return {
            "version": 1,
            "tx": dict(raw_or_dict),
            "created_at": 0,
            "expires_at": 0,
            "reservation_id": "",
            "transport": "qr",
            "voucher_sig": "",
        }

    if not isinstance(raw_or_dict, str):
        raise ValueError("Invalid offline voucher format")

    token = raw_or_dict.strip()
    if token.startswith(VOUCHER_PREFIX_V2):
        b64 = token[len(VOUCHER_PREFIX_V2):]
        obj = json.loads(base64.b64decode(b64).decode("utf-8"))
        if not isinstance(obj, dict) or not isinstance(obj.get("tx"), dict):
            raise ValueError("Corrupted V2 offline voucher payload")
        return decode_voucher(obj)
    if token.startswith(VOUCHER_PREFIX_V1):
        b64 = token[len(VOUCHER_PREFIX_V1):]
        tx = json.loads(base64.b64decode(b64).decode("utf-8"))
        if not isinstance(tx, dict):
            raise ValueError("Corrupted V1 offline voucher payload")
        return decode_voucher({"version": 1, "tx": tx})

    raise ValueError("Offline voucher must start with UNIVA:OFF:V2: or UNIVA:OFF:V1:")


def _num_variants(raw_val: Any, fval: float) -> List[str]:
    out: List[str] = []
    for item in (
        str(raw_val) if raw_val is not None else "",
        f"{fval:g}",
        str(int(fval)) if float(fval).is_integer() else str(fval),
        str(float(fval)),
        f"{fval:.8f}",
    ):
        if item and item not in out:
            out.append(item)
    return out


class OfflinePayError(ValueError):
    def __init__(self, message: str, status_code: int = 400, code: str = "offline_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class OfflinePayManager:
    def __init__(self, state_path: Optional[str] = None):
        self._lock = threading.RLock()
        self.state_path = state_path
        self.reservations: Dict[str, dict] = {}
        self.vouchers: Dict[str, dict] = {}
        self.user_nonces: Dict[str, int] = {}
        self.used_signatures: set = set()
        self.used_voucher_txids: set = set()
        if state_path and os.path.exists(state_path):
            self.load(state_path)

    def get_user_nonce(self, address: str) -> int:
        return int(self.user_nonces.get(normalize_address(address), 0))

    def expire_stale_reservations(self, now: Optional[float] = None) -> int:
        ts = float(now if now is not None else time.time())
        changed = 0
        with self._lock:
            for r in self.reservations.values():
                if r.get("status") == "active" and ts >= float(r.get("expires_at", 0)):
                    r["status"] = "expired"
                    changed += 1
            if changed and self.state_path:
                self.save(self.state_path)
        return changed

    def get_active_reserved(self, address: str, now: Optional[float] = None) -> float:
        ts = float(now if now is not None else time.time())
        norm = normalize_address(address)
        with self._lock:
            self.expire_stale_reservations(ts)
            total = 0.0
            for r in self.reservations.values():
                if r.get("owner") == norm and r.get("status") == "active" and ts < float(r.get("expires_at", 0)):
                    rem = max(0.0, float(r.get("amount", 0.0)) - float(r.get("spent", 0.0)))
                    total += rem
            return round(total, 8)

    def get_unreserved_spendable(self, blockchain, address: str, now: Optional[float] = None) -> float:
        l1_bal = float(blockchain.get_balance(address, "UNIVA"))
        reserved = self.get_active_reserved(address, now=now)
        return round(max(0.0, l1_bal - reserved), 8)

    def list_reservations(self, blockchain, address: str, now: Optional[float] = None) -> dict:
        ts = float(now if now is not None else time.time())
        norm = normalize_address(address)
        with self._lock:
            self.expire_stale_reservations(ts)
            items = [
                dict(r, consensus=False, remaining=round(max(0.0, float(r["amount"]) - float(r["spent"])), 8))
                for r in self.reservations.values()
                if r.get("owner") == norm
            ]
            # Also include deterministic on-chain consensus reservations (P5-A)
            onchain_active_reserved = 0.0
            if hasattr(blockchain, "get_onchain_reservations"):
                onchain_map = blockchain.get_onchain_reservations(include_pending=True, at_timestamp=ts)
                for oc in onchain_map.values():
                    if oc.get("owner") == norm:
                        if oc.get("status") == "active":
                            onchain_active_reserved += float(oc.get("remaining", 0.0))
                        items.append({
                            "reservation_id": oc["reservation_id"],
                            "owner": oc["owner"],
                            "amount": oc["amount"],
                            "spent": oc["spent"],
                            "remaining": oc["remaining"],
                            "expires_at": oc["expires_at"],
                            "status": oc["status"],
                            "confirmed": oc["confirmed"],
                            "block_index": oc["block_index"],
                            "tx_id": oc["tx_id"],
                            "consensus": True,
                            "created_at": oc.get("expires_at", 0),
                        })
            items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            active_reserved = self.get_active_reserved(address, now=ts)
            l1_bal = float(blockchain.get_balance(address, "UNIVA"))
            return {
                "address": address,
                "l1_balance": l1_bal,
                "active_reserved": active_reserved,
                "onchain_active_reserved": round(onchain_active_reserved, 8),
                "unreserved_spendable": round(max(0.0, l1_bal - active_reserved), 8),
                "offline_nonce": self.get_user_nonce(address),
                "reservations": items,
            }

    def create_reservation(
        self,
        blockchain,
        owner: str,
        amount: float,
        ttl_seconds: int,
        public_key: str,
        signature: str,
        nonce: int,
        raw_amount: Any = None,
        now: Optional[float] = None,
    ) -> dict:
        ts = float(now if now is not None else time.time())
        owner_clean = (owner or "").strip()
        norm = normalize_address(owner_clean)
        if not owner_clean or not public_key or not signature:
            raise OfflinePayError("Adres, public_key ve ECDSA imzasi gereklidir", 401, "missing_auth")
        if len(public_key) != 128:
            raise OfflinePayError("Gecersiz public_key uzunlugu", 401, "invalid_pubkey")
        if isinstance(nonce, bool) or not isinstance(nonce, int) or nonce < 0:
            raise OfflinePayError("Gecersiz offline nonce", 400, "invalid_nonce")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise OfflinePayError("TTL tamsayi saniye olmalidir", 400, "invalid_ttl")
        if not (MIN_RESERVATION_TTL <= ttl_seconds <= MAX_RESERVATION_TTL):
            raise OfflinePayError(
                f"Rezervasyon suresi {MIN_RESERVATION_TTL}s ile {MAX_RESERVATION_TTL}s arasinda olmalidir",
                400,
                "invalid_ttl",
            )
        amt = round(float(amount), 8)
        if amt <= 0:
            raise OfflinePayError("Rezervasyon tutari pozitif olmalidir", 400, "invalid_amount")

        with self._lock:
            self.expire_stale_reservations(ts)
            if signature in self.used_signatures:
                raise OfflinePayError("Rezervasyon imzasi daha once kullanildi (replay)", 409, "replay_blocked")
            expected_nonce = self.get_user_nonce(owner_clean)
            if nonce != expected_nonce:
                raise OfflinePayError(
                    f"Gecersiz offline nonce: beklenen {expected_nonce}, gelen {nonce}",
                    409,
                    "nonce_mismatch",
                )
            if norm not in get_valid_sender_addresses(public_key):
                raise OfflinePayError("Public key bu adrese ait degil", 403, "pubkey_mismatch")

            cands = [
                f"UNIVA_OFFLINE|reserve|{owner_clean}|{a_s}|{ttl_seconds}|{nonce}"
                for a_s in _num_variants(raw_amount if raw_amount is not None else amount, amt)
            ]
            if not any(UnivaWallet.verify_signature(public_key, msg, signature) for msg in cands):
                raise OfflinePayError("Gecersiz rezervasyon ECDSA imzasi", 401, "invalid_signature")

            available = self.get_unreserved_spendable(blockchain, owner_clean, now=ts)
            if available < amt:
                raise OfflinePayError(
                    f"Yetersiz rezerve edilmemis L1 bakiyesi (Mevcut: {available}, Istenen: {amt})",
                    400,
                    "insufficient_balance",
                )

            res_id = "res_" + hashlib.sha256(
                f"{norm}|{amt}|{ttl_seconds}|{nonce}|{signature}".encode("utf-8")
            ).hexdigest()[:20]
            record = {
                "reservation_id": res_id,
                "owner": norm,
                "owner_raw": owner_clean,
                "amount": amt,
                "spent": 0.0,
                "remaining": amt,
                "created_at": int(ts),
                "expires_at": int(ts + ttl_seconds),
                "ttl_seconds": int(ttl_seconds),
                "status": "active",
                "nonce": int(nonce),
                "public_key": public_key,
                "signature": signature,
                "voucher_tx_ids": [],
            }
            self.reservations[res_id] = record
            self.used_signatures.add(signature)
            self.user_nonces[norm] = expected_nonce + 1
            if self.state_path:
                self.save(self.state_path)
            return dict(record)

    def release_reservation(
        self,
        owner: str,
        reservation_id: str,
        public_key: str,
        signature: str,
        nonce: int,
        now: Optional[float] = None,
    ) -> dict:
        ts = float(now if now is not None else time.time())
        owner_clean = (owner or "").strip()
        norm = normalize_address(owner_clean)
        res_id = (reservation_id or "").strip()
        if not owner_clean or not res_id or not public_key or not signature:
            raise OfflinePayError("Eksik parametreler", 401, "missing_auth")
        if len(public_key) != 128:
            raise OfflinePayError("Gecersiz public_key", 401, "invalid_pubkey")
        if isinstance(nonce, bool) or not isinstance(nonce, int) or nonce < 0:
            raise OfflinePayError("Gecersiz offline nonce", 400, "invalid_nonce")

        with self._lock:
            self.expire_stale_reservations(ts)
            if signature in self.used_signatures:
                raise OfflinePayError("Imza daha once kullanildi (replay)", 409, "replay_blocked")
            expected_nonce = self.get_user_nonce(owner_clean)
            if nonce != expected_nonce:
                raise OfflinePayError(
                    f"Gecersiz offline nonce: beklenen {expected_nonce}, gelen {nonce}",
                    409,
                    "nonce_mismatch",
                )
            if norm not in get_valid_sender_addresses(public_key):
                raise OfflinePayError("Public key bu adrese ait degil", 403, "pubkey_mismatch")
            msg = f"UNIVA_OFFLINE|release|{owner_clean}|{res_id}|{nonce}"
            if not UnivaWallet.verify_signature(public_key, msg, signature):
                raise OfflinePayError("Gecersiz ECDSA imzasi", 401, "invalid_signature")

            rec = self.reservations.get(res_id)
            if not rec:
                raise OfflinePayError("Rezervasyon bulunamadi", 404, "not_found")
            if rec.get("owner") != norm:
                raise OfflinePayError("Bu rezervasyon size ait degil", 403, "not_owner")
            if rec.get("status") != "active":
                raise OfflinePayError(f"Rezervasyon aktif degil ({rec.get('status')})", 400, "not_active")

            released_amt = round(max(0.0, float(rec["amount"]) - float(rec["spent"])), 8)
            rec["status"] = "released"
            rec["released_at"] = int(ts)
            rec["remaining"] = 0.0
            self.used_signatures.add(signature)
            self.user_nonces[norm] = expected_nonce + 1
            if self.state_path:
                self.save(self.state_path)
            return {
                "reservation_id": res_id,
                "status": "released",
                "released_amount": released_amt,
                "offline_nonce": self.user_nonces[norm],
            }

    def validate_voucher(self, voucher_or_token: Any, now: Optional[float] = None) -> dict:
        """Pure cryptographic + expiry validation (supports L1 transfer & consensus offline_spend)."""
        ts = float(now if now is not None else time.time())
        voucher = decode_voucher(voucher_or_token)
        tx = voucher["tx"]
        tx_type = tx.get("type", "transfer")
        if tx_type == "offline_spend":
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
        else:
            required = ("from", "to", "amount", "fee", "nonce", "public_key", "signature", "tx_id")
        if any(k not in tx for k in required):
            raise OfflinePayError("Eksik islem alanlari", 400, "malformed_tx")

        canon = canonical_tx_message(tx)
        digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        if tx["tx_id"] != digest:
            raise OfflinePayError("Islem ozeti (tx_id) gecersiz veya degistirilmis", 400, "bad_tx_id")

        sender_norm = normalize_address(tx["from"])
        if sender_norm not in get_valid_sender_addresses(tx["public_key"]):
            raise OfflinePayError("Public key gonderici adresiyle eslesmiyor", 403, "pubkey_mismatch")

        if not UnivaWallet.verify_signature(tx["public_key"], canon, tx["signature"]):
            raise OfflinePayError("Kriptografik ECDSA islem imzasi gecersiz", 401, "invalid_signature")

        # V2 metadata signature integrity check (prevents stripping reservation_id or extending expires_at)
        expires_at = int(voucher.get("expires_at") or tx.get("expires_at") or 0)
        reservation_id = voucher.get("reservation_id") or tx.get("reservation_id") or ""
        voucher_sig = voucher.get("voucher_sig") or ""
        if voucher_sig:
            meta_msg = canonical_voucher_meta_message(tx["tx_id"], reservation_id, expires_at)
            if not UnivaWallet.verify_signature(tx["public_key"], meta_msg, voucher_sig):
                raise OfflinePayError("Cevrimdisi fis ustveri imzasi gecersiz (tamper)", 401, "invalid_meta_sig")

        if expires_at > 0 and ts >= expires_at:
            raise OfflinePayError("Cevrimdisi odeme fisinin suresi dolmus (expired)", 410, "voucher_expired")

        return voucher

    def submit_voucher(
        self,
        blockchain,
        voucher_or_token: Any,
        transport: Optional[str] = None,
        now: Optional[float] = None,
    ) -> dict:
        ts = float(now if now is not None else time.time())
        voucher = self.validate_voucher(voucher_or_token, now=ts)
        tx = voucher["tx"]
        tx_id = tx["tx_id"]
        sender_norm = normalize_address(tx["from"])
        total_cost = round(float(tx["amount"]) + float(tx["fee"]), 8)
        res_id = voucher.get("reservation_id") or ""
        used_transport = (transport or voucher.get("transport") or "qr").strip().lower()

        with self._lock:
            self.expire_stale_reservations(ts)

            # Strict replay protection
            if tx_id in self.used_voucher_txids or tx["signature"] in self.used_signatures:
                raise OfflinePayError(
                    "Bu cevrimdisi odeme fisi daha once islendi (replay engellendi)",
                    409,
                    "replay_blocked",
                )
            for b in blockchain.chain:
                for btx in b.transactions:
                    if btx.get("tx_id") == tx_id:
                        raise OfflinePayError("Islem zaten blokzincirinde onayli (replay)", 409, "already_confirmed")
            for ptx in blockchain.pending_transactions:
                if ptx.get("tx_id") == tx_id:
                    raise OfflinePayError("Islem zaten mempool kuyrugunda (replay)", 409, "already_in_mempool")

            # Reservation / double-spend guard
            backed_by_reservation = False
            consensus_escrow = tx.get("type") == "offline_spend"
            rec = None
            if consensus_escrow:
                # On-chain consensus escrow: validated directly by blockchain.add_transaction(tx)
                res_id = str(tx.get("reservation_id") or res_id)
                backed_by_reservation = True
            elif res_id:
                rec = self.reservations.get(res_id)
                if not rec:
                    raise OfflinePayError("Bagli rezervasyon bulunamadi", 404, "reservation_not_found")
                if rec.get("owner") != sender_norm:
                    raise OfflinePayError("Rezervasyon gondericiye ait degil", 403, "reservation_owner_mismatch")
                if rec.get("status") != "active" or ts >= float(rec.get("expires_at", 0)):
                    raise OfflinePayError("Rezervasyon suresi dolmus veya kapatilmis", 410, "reservation_inactive")
                remaining = round(float(rec["amount"]) - float(rec["spent"]), 8)
                if total_cost > remaining + 1e-8:
                    self.vouchers[tx_id] = {
                        "tx_id": tx_id,
                        "from": tx["from"],
                        "to": tx["to"],
                        "amount": float(tx["amount"]),
                        "fee": float(tx["fee"]),
                        "reservation_id": res_id,
                        "transport": used_transport,
                        "status": "double_spend_blocked",
                        "finalized": False,
                        "submitted_at": int(ts),
                    }
                    if self.state_path:
                        self.save(self.state_path)
                    raise OfflinePayError(
                        f"Rezervasyon limiti asildi (cift harcama engellendi: kalan {remaining}, istenen {total_cost})",
                        409,
                        "double_spend_blocked",
                    )
                backed_by_reservation = True
            else:
                # Unreserved voucher cannot steal funds locked in active reservations
                unreserved = self.get_unreserved_spendable(blockchain, tx["from"], now=ts)
                if unreserved + 1e-8 < total_cost:
                    raise OfflinePayError(
                        f"Yetersiz rezerve edilmemis L1 bakiye (serbest: {unreserved}, gerekli: {total_cost})",
                        400,
                        "reserved_funds_protected",
                    )

            # Submit to L1 mempool (full consensus signature, nonce/voucher_nonce, escrow, balance & conflict checks)
            if not blockchain.add_transaction(tx):
                raise OfflinePayError(
                    "L1 konsensüs/mempool islemi reddetti (yetersiz rezervasyon/bakiye, sure dolumu, nonce veya cift harcama)",
                    409 if consensus_escrow else 400,
                    "consensus_rejected" if consensus_escrow else "mempool_rejected",
                )

            if rec is not None:
                rec["spent"] = round(float(rec["spent"]) + total_cost, 8)
                rec["remaining"] = round(max(0.0, float(rec["amount"]) - rec["spent"]), 8)
                rec.setdefault("voucher_tx_ids", []).append(tx_id)
                if rec["remaining"] <= 1e-8:
                    rec["status"] = "exhausted"

            self.used_voucher_txids.add(tx_id)
            self.used_signatures.add(tx["signature"])

            v_record = {
                "tx_id": tx_id,
                "type": tx.get("type", "transfer"),
                "from": tx["from"],
                "to": tx["to"],
                "amount": float(tx["amount"]),
                "fee": float(tx["fee"]),
                "nonce": int(tx["voucher_nonce"]) if consensus_escrow else int(tx["nonce"]),
                "reservation_id": res_id,
                "backed_by_reservation": backed_by_reservation,
                "consensus_escrow": consensus_escrow,
                "expires_at": int(voucher.get("expires_at") or tx.get("expires_at") or 0),
                "transport": used_transport,
                "status": "in_mempool",
                "finalized": False,
                "confirmations": 0,
                "block_index": None,
                "submitted_at": int(ts),
                "settlement_note": "Islem L1 mempool'a eklendi; blok madenciligi onayina kadar kesinlesmis sayilmaz.",
            }
            self.vouchers[tx_id] = v_record
            if self.state_path:
                self.save(self.state_path)
            return dict(v_record)

    def get_voucher_status(self, blockchain, tx_id: str) -> dict:
        tid = (tx_id or "").strip()
        for b in blockchain.chain:
            for tx in b.transactions:
                if tx.get("tx_id") == tid:
                    confs = max(1, blockchain.height - b.index + 1)
                    meta = self.vouchers.get(tid, {})
                    return {
                        "tx_id": tid,
                        "status": "confirmed",
                        "finalized": True,
                        "block_index": b.index,
                        "confirmations": confs,
                        "reservation_id": meta.get("reservation_id", ""),
                        "transport": meta.get("transport", "qr"),
                        "settlement_note": f"Blok #{b.index} icinde zincirde kalici olarak onaylandi ({confs} onay).",
                    }
        for tx in blockchain.pending_transactions:
            if tx.get("tx_id") == tid:
                meta = self.vouchers.get(tid, {})
                return {
                    "tx_id": tid,
                    "status": "in_mempool",
                    "finalized": False,
                    "block_index": None,
                    "confirmations": 0,
                    "reservation_id": meta.get("reservation_id", ""),
                    "transport": meta.get("transport", "qr"),
                    "settlement_note": "Mempool'da blok onayi bekliyor (henuz kesinlesmedi).",
                }
        if tid in self.vouchers:
            rec = dict(self.vouchers[tid])
            rec["finalized"] = False
            rec["confirmations"] = 0
            return rec
        return {
            "tx_id": tid,
            "status": "not_found",
            "finalized": False,
            "block_index": None,
            "confirmations": 0,
            "settlement_note": "Bu islem dugumde henuz gorulmedi.",
        }

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "version": 1,
                "reservations": dict(self.reservations),
                "vouchers": dict(self.vouchers),
                "user_nonces": dict(self.user_nonces),
                "used_signatures": sorted(self.used_signatures)[-5000:],
                "used_voucher_txids": sorted(self.used_voucher_txids)[-5000:],
            }

    def save(self, path: Optional[str] = None) -> bool:
        target = path or self.state_path or OFFLINE_STATE_FILE
        with self._lock:
            try:
                if os.path.exists(target):
                    try:
                        shutil.copyfile(target, target + ".bak")
                    except Exception:
                        pass
                tmp = target + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
                os.replace(tmp, target)
                return True
            except Exception:
                return False

    def load(self, path: Optional[str] = None) -> bool:
        target = path or self.state_path or OFFLINE_STATE_FILE
        with self._lock:
            for cand in (target, target + ".bak"):
                if not os.path.exists(cand):
                    continue
                try:
                    with open(cand, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    if not isinstance(d, dict):
                        continue
                    self.reservations = dict(d.get("reservations") or {})
                    self.vouchers = dict(d.get("vouchers") or {})
                    self.user_nonces = {str(k): int(v) for k, v in (d.get("user_nonces") or {}).items()}
                    self.used_signatures = set(str(x) for x in (d.get("used_signatures") or []))
                    self.used_voucher_txids = set(str(x) for x in (d.get("used_voucher_txids") or []))
                    return True
                except Exception:
                    continue
            return False
