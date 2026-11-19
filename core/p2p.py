"""
UNIVA Network - Hardened asyncio + WebSocket P2P Layer (P3)
============================================================
Port: 5051 (WebSocket)
Port: 5050 (HTTP API - network.py)

Ozellikler:
  - ECDSA imzali P2P mesaj protokolu + +-120s zaman penceresi + nonce replay korumasi
  - Peer kimlik baglama (node_pubkey spoofing reddi) + Genesis hash dogrulamasi
  - Sybil & Eclipse savunmasi (MAX_PEERS, inbound/outbound kotasi, IP, /24 alt-ag & pubkey limitleri)
  - Skor tabanli davranis takibi, oran sinirlandirma ve otomatik IP banlama
  - Sayfalanmis artimli senkronizasyon + en agir gecerli zincirle tam fork/reorg cozumlemesi
"""

import asyncio
import json
import os
import secrets
import time
import hashlib
import threading
import websockets
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple

P2P_PORT             = 5051
P2P_VERSION          = "UNIVA/2.1.0"
MAX_PEERS            = 64
MAX_INBOUND_PEERS    = 48
MAX_OUTBOUND_PEERS   = 16
MAX_PEERS_PER_IP     = 4
MAX_PEERS_PER_SUBNET = 8
MAX_PEERS_PER_PUBKEY = 2
MAX_SYNC_BLOCKS      = 500
MAX_MSG_BYTES        = 1_048_576  # 1 MB max frame
MAX_MSGS_PER_MIN     = 180
MAX_TIME_DRIFT       = 120.0      # +-120 seconds replay window
MAX_NONCES           = 5000
BAN_DURATION         = 900.0

# Aktif baglanti ve guvenlik durumu
_connected_peers: Dict[str, Any] = {}
_inbound_peers: Set[str] = set()
_outbound_peers: Set[str] = set()
_peer_pubkeys: Dict[str, str] = {}
_peer_scores: Dict[str, int] = {}
_banned_ips: Dict[str, float] = {}
_peer_msg_buckets: Dict[str, List[float]] = {}
_peer_lock = asyncio.Lock()
_seen_nonces: "OrderedDict[str, float]" = OrderedDict()
_nonce_lock = threading.Lock()
_node_wallet_cache = None

# Disaridan erisim icin referans
_blockchain_ref = None
_db_path        = "univa_chain.db"
_p2p_loop       = None


def _get_node_wallet():
    global _node_wallet_cache
    if _node_wallet_cache is not None:
        return _node_wallet_cache
    from core.wallet import UnivaWallet
    wallet_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "univa_wallet.json")
    if os.path.exists(wallet_path):
        try:
            _node_wallet_cache = UnivaWallet.load(wallet_path)
            return _node_wallet_cache
        except Exception:
            pass
    _node_wallet_cache = UnivaWallet.create_new()
    return _node_wallet_cache


# ════════════════════════════════════════════════════════════════
# SYBIL / ECLIPSE / BAN & KAYNAK KORUMA YARDIMCILARI
# ════════════════════════════════════════════════════════════════

def _extract_ip(peer_or_ip: str) -> str:
    s = str(peer_or_ip or "").strip()
    if ":" in s and not s.startswith("["):
        parts = s.rsplit(":", 1)
        if parts[1].isdigit():
            return parts[0]
    return s


def _ip_subnet(ip: str) -> str:
    clean = _extract_ip(ip)
    if "." in clean:
        parts = clean.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3]) + ".0/24"
    if ":" in clean:
        parts = clean.split(":")
        return ":".join(parts[:4]) + "::/64"
    return clean


def is_ip_banned(ip: str) -> bool:
    clean = _extract_ip(ip)
    until = _banned_ips.get(clean)
    if not until:
        return False
    if time.time() >= until:
        _banned_ips.pop(clean, None)
        _peer_scores.pop(clean, None)
        return False
    return True


def record_peer_misbehavior(peer_id: str, points: int, reason: str = "") -> bool:
    """Increase peer misbehavior score; returns True if IP reached ban threshold (>= 100)."""
    ip = _extract_ip(peer_id)
    new_score = _peer_scores.get(ip, 0) + int(points)
    _peer_scores[ip] = new_score
    if new_score >= 100:
        _banned_ips[ip] = time.time() + BAN_DURATION
        print(f"[P2P] Peer IP banlandi ({ip}, skor={new_score}, sebep={reason})")
        return True
    return False


def can_accept_peer(remote_ip: str, is_outbound: bool = False) -> Tuple[bool, str]:
    clean_ip = _extract_ip(remote_ip)
    if is_ip_banned(clean_ip):
        return False, "ip_banned"
    if len(_connected_peers) >= MAX_PEERS:
        return False, "max_peers_reached"
    if is_outbound and len(_outbound_peers) >= MAX_OUTBOUND_PEERS:
        return False, "max_outbound_reached"
    if not is_outbound and len(_inbound_peers) >= MAX_INBOUND_PEERS:
        return False, "max_inbound_reached"

    ip_count = sum(1 for pid in _connected_peers if _extract_ip(pid) == clean_ip)
    if ip_count >= MAX_PEERS_PER_IP:
        return False, "per_ip_limit"

    target_subnet = _ip_subnet(clean_ip)
    subnet_count = sum(1 for pid in _connected_peers if _ip_subnet(pid) == target_subnet)
    if subnet_count >= MAX_PEERS_PER_SUBNET:
        return False, "per_subnet_limit"

    return True, "ok"


def check_peer_rate_limit(peer_id: str) -> bool:
    now = time.time()
    bucket = [t for t in _peer_msg_buckets.get(peer_id, []) if now - t < 60.0]
    if len(bucket) >= MAX_MSGS_PER_MIN:
        record_peer_misbehavior(peer_id, 100, "rate_limit_exceeded")
        return False
    bucket.append(now)
    _peer_msg_buckets[peer_id] = bucket
    return True


def _sync_peer_count():
    if _blockchain_ref is not None:
        _blockchain_ref.peer_count = len(_connected_peers)


# ════════════════════════════════════════════════════════════════
# MESAJ PROTOKOLÜ (ECDSA İMZALI + REPLAY KORUMALI)
# ════════════════════════════════════════════════════════════════

def _canonical_p2p_body(msg: dict) -> str:
    body = {
        "type": msg.get("type"),
        "version": msg.get("version"),
        "time": msg.get("time"),
        "nonce": msg.get("nonce"),
        "payload": msg.get("payload", {}),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_msg(msg_type: str, payload: dict = None) -> str:
    msg = {
        "type":    msg_type,
        "version": P2P_VERSION,
        "time":    round(time.time(), 3),
        "nonce":   secrets.token_hex(12),
        "payload": payload or {},
    }
    w = _get_node_wallet()
    msg["node_pubkey"] = w.public_key
    msg["sig"] = w.sign(_canonical_p2p_body(msg))
    return json.dumps(msg, ensure_ascii=False)


def verify_p2p_msg(msg: dict) -> bool:
    """Verify P2P timestamp window, nonce uniqueness (anti-replay), and ECDSA signature."""
    if not isinstance(msg, dict) or not msg.get("type"):
        return False
    msg_time = msg.get("time")
    if not isinstance(msg_time, (int, float)) or abs(time.time() - float(msg_time)) > MAX_TIME_DRIFT:
        return False

    nonce = msg.get("nonce")
    pub = str(msg.get("node_pubkey") or "").strip().lower()
    sig = str(msg.get("sig") or "").strip().lower()

    if not sig:
        if os.environ.get("UNIVA_P2P_ALLOW_UNSIGNED") == "1":
            return True
        return False

    if len(pub) != 128 or not isinstance(nonce, str) or len(nonce) < 8:
        return False

    from core.wallet import UnivaWallet
    if not UnivaWallet.verify_signature(pub, _canonical_p2p_body(msg), sig):
        return False

    replay_key = f"{pub[:16]}:{nonce}"
    with _nonce_lock:
        if replay_key in _seen_nonces:
            return False
        _seen_nonces[replay_key] = float(msg_time)
        while len(_seen_nonces) > MAX_NONCES:
            _seen_nonces.popitem(last=False)
    return True


def parse_msg(raw: str) -> Optional[dict]:
    try:
        if isinstance(raw, bytes):
            if len(raw) > MAX_MSG_BYTES:
                return None
            raw = raw.decode("utf-8")
        elif isinstance(raw, str) and len(raw.encode("utf-8")) > MAX_MSG_BYTES:
            return None
        msg = json.loads(raw)
        if not verify_p2p_msg(msg):
            return None
        return msg
    except Exception:
        return None


def _build_handshake_msg() -> str:
    our_height = _blockchain_ref.height if _blockchain_ref else 0
    genesis_hash = _blockchain_ref.chain[0].hash if (_blockchain_ref and _blockchain_ref.chain) else ""
    chain_work = _blockchain_ref.calculate_chain_work(_blockchain_ref.chain) if _blockchain_ref else 0
    best_hash = _blockchain_ref.last_block.hash if (_blockchain_ref and _blockchain_ref.chain) else ""
    return make_msg("handshake", {
        "version":      P2P_VERSION,
        "height":       our_height,
        "p2p_port":     P2P_PORT,
        "network":      "UNIVA Network",
        "genesis_hash": genesis_hash,
        "chain_work":   chain_work,
        "best_hash":    best_hash,
    })


# ════════════════════════════════════════════════════════════════
# BROADCAST
# ════════════════════════════════════════════════════════════════

async def broadcast(msg_str: str, exclude_peer: str = None):
    """Bağlı tüm peer'lara mesaj yayınla."""
    async with _peer_lock:
        peers = dict(_connected_peers)
    dead = []
    for peer_id, ws in peers.items():
        if peer_id == exclude_peer:
            continue
        try:
            await ws.send(msg_str)
        except Exception:
            dead.append(peer_id)
    if dead:
        async with _peer_lock:
            for d in dead:
                _connected_peers.pop(d, None)
                _inbound_peers.discard(d)
                _outbound_peers.discard(d)
                _peer_pubkeys.pop(d, None)
                _peer_msg_buckets.pop(d, None)
            _sync_peer_count()


async def broadcast_block(block_dict: dict):
    """Yeni mined bloğu tüm peer'lara yayınla."""
    msg = make_msg("new_block", {"block": block_dict})
    await broadcast(msg)
    print(f"[P2P] Blok #{block_dict.get('index')} yayınlandı ({len(_connected_peers)} peer)")


async def broadcast_tx(tx_dict: dict):
    """Yeni TX'i tüm peer'lara yayınla."""
    msg = make_msg("new_tx", {"tx": tx_dict})
    await broadcast(msg)


# ════════════════════════════════════════════════════════════════
# MESAJ İŞLEYİCİLER
# ════════════════════════════════════════════════════════════════

async def handle_handshake(ws, peer_id: str, payload: dict):
    network_name = payload.get("network", "UNIVA Network")
    if network_name != "UNIVA Network":
        record_peer_misbehavior(peer_id, 100, "wrong_network")
        try:
            await ws.close(code=1008, reason="Network mismatch")
        except Exception:
            pass
        return

    their_genesis = payload.get("genesis_hash")
    if _blockchain_ref and _blockchain_ref.chain and their_genesis:
        if their_genesis != _blockchain_ref.chain[0].hash:
            record_peer_misbehavior(peer_id, 100, "genesis_mismatch")
            try:
                await ws.close(code=1008, reason="Genesis block mismatch")
            except Exception:
                pass
            return

    their_height = int(payload.get("height", 0) or 0)
    their_work   = int(payload.get("chain_work", 0) or 0)
    our_height   = _blockchain_ref.height if _blockchain_ref else 0
    our_work     = _blockchain_ref.calculate_chain_work(_blockchain_ref.chain) if _blockchain_ref else 0
    version      = str(payload.get("version", "?"))

    # DB'ye peer kaydet (gecerli port siniri ile)
    try:
        from core.database import upsert_peer
        remote = getattr(ws, "remote_address", None)
        host = str(remote[0]) if remote else _extract_ip(peer_id)
        port = int(payload.get("p2p_port", P2P_PORT))
        if 1 <= port <= 65535 and not is_ip_banned(host):
            upsert_peer(peer_id, host, port, version, _db_path)
    except Exception:
        pass

    print(f"[P2P] Handshake: {peer_id} | yükseklik={their_height} | sürüm={version}")

    if not _blockchain_ref:
        return
    if their_height > our_height:
        await ws.send(make_msg("get_chain", {"from_height": our_height + 1}))
    elif their_work > our_work or (
        their_height == our_height
        and payload.get("best_hash")
        and payload.get("best_hash") != _blockchain_ref.last_block.hash
        and their_work >= our_work
    ):
        await ws.send(make_msg("get_chain", {"from_height": 0}))


async def handle_new_block(ws, peer_id: str, payload: dict):
    """Validate and append or trigger fork resolution before relaying a received block."""
    if not _blockchain_ref:
        return
    block_data = payload.get("block")
    if not isinstance(block_data, dict):
        record_peer_misbehavior(peer_id, 25, "malformed_block")
        return
    index = block_data.get("index", -1)
    our_height = _blockchain_ref.height
    if index <= our_height:
        return
    if index > our_height + 1:
        await ws.send(make_msg("get_chain", {"from_height": our_height + 1}))
        return
    # Fork detected at tip height + 1: request full chain from genesis to weigh chainwork
    if block_data.get("previous_hash") != _blockchain_ref.last_block.hash:
        await ws.send(make_msg("get_chain", {"from_height": 0}))
        return
    if _blockchain_ref.accept_block(block_data):
        await broadcast(make_msg("new_block", {"block": block_data}), exclude_peer=peer_id)
        print(f"[P2P] Blok #{index} doğrulandı ve eklendi")
    else:
        record_peer_misbehavior(peer_id, 50, "invalid_block")
        print(f"[P2P] Blok #{index} reddedildi: konsensüs doğrulaması başarısız")


async def handle_new_tx(ws, peer_id: str, payload: dict):
    """Gelen TX'i doğrula ve mempool'a ekle."""
    if not _blockchain_ref:
        return
    tx = payload.get("tx")
    if not isinstance(tx, dict):
        record_peer_misbehavior(peer_id, 15, "malformed_tx")
        return

    existing_ids = {t.get("tx_id") for t in _blockchain_ref.pending_transactions}
    tx_id = tx.get("tx_id") or hashlib.sha256(
        json.dumps(tx, sort_keys=True).encode()
    ).hexdigest()

    if tx_id not in existing_ids:
        if _blockchain_ref.add_transaction(tx):
            print(f"[P2P] TX mempool'a eklendi: {tx_id[:16]}...")
            await broadcast(make_msg("new_tx", {"tx": tx}), exclude_peer=peer_id)
        else:
            record_peer_misbehavior(peer_id, 10, "invalid_tx")


async def handle_get_chain(ws, peer_id: str, payload: dict):
    """Peer'a sayfalanmis (max 500 blok) zincir verisi gönder."""
    if not _blockchain_ref:
        return
    try:
        from_h = max(0, int(payload.get("from_height", 0) or 0))
    except Exception:
        from_h = 0
    slice_blocks = _blockchain_ref.chain[from_h : from_h + MAX_SYNC_BLOCKS]
    blocks = [b.to_dict() for b in slice_blocks]
    await ws.send(make_msg("chain_response", {
        "from_height": from_h,
        "blocks":      blocks,
        "height":      _blockchain_ref.height,
        "chain_work":  _blockchain_ref.calculate_chain_work(_blockchain_ref.chain),
    }))
    print(f"[P2P] {len(blocks)} blok gönderildi (from={from_h}) → {peer_id}")


async def handle_chain_response(ws, peer_id: str, payload: dict):
    """Incremental sync or heaviest-valid-chain fork reorganization with pagination."""
    if not _blockchain_ref:
        return
    blocks = payload.get("blocks", [])
    if not isinstance(blocks, list) or len(blocks) > MAX_SYNC_BLOCKS:
        record_peer_misbehavior(peer_id, 50, "oversized_chain_response")
        return
    if not blocks:
        return

    from core.blockchain import Block
    their_tip_h = int(payload.get("height", _blockchain_ref.height) or 0)

    # Full chain from Genesis -> evaluate fork reorganization via cumulative PoW chainwork
    if isinstance(blocks[0], dict) and blocks[0].get("index") == 0:
        if _blockchain_ref.replace_chain(blocks):
            print(f"[P2P] Reorg tamamlandi: yeni yukseklik={_blockchain_ref.height}")
            if len(blocks) == MAX_SYNC_BLOCKS and _blockchain_ref.height < their_tip_h:
                await ws.send(make_msg("get_chain", {"from_height": _blockchain_ref.height + 1}))
        else:
            try:
                parsed = [Block.from_dict(b) for b in blocks]
                ok, _, _ = _blockchain_ref._validate_chain_state(parsed)
                if not ok:
                    record_peer_misbehavior(peer_id, 50, "invalid_reorg_chain")
            except Exception:
                record_peer_misbehavior(peer_id, 50, "corrupt_reorg_chain")
        return

    # Incremental block append
    added = 0
    for bd in blocks:
        if not isinstance(bd, dict):
            record_peer_misbehavior(peer_id, 25, "malformed_sync_block")
            break
        idx = bd.get("index", -1)
        if idx <= _blockchain_ref.height:
            continue
        if idx == _blockchain_ref.height + 1 and bd.get("previous_hash") != _blockchain_ref.last_block.hash:
            # Diverged branch detected mid-sync -> fetch from genesis to weigh forks cleanly
            await ws.send(make_msg("get_chain", {"from_height": 0}))
            return
        if not _blockchain_ref.accept_block(bd):
            record_peer_misbehavior(peer_id, 50, "invalid_sync_block")
            print(f"[P2P] Senkronizasyon durdu: blok #{idx} geçersiz")
            break
        added += 1

    if added:
        print(f"[P2P] {added} blok doğrulanarak senkronize edildi")
        if _blockchain_ref.height < their_tip_h:
            await ws.send(make_msg("get_chain", {"from_height": _blockchain_ref.height + 1}))


async def handle_ping(ws, peer_id: str, payload: dict):
    await ws.send(make_msg("pong", {"height": _blockchain_ref.height if _blockchain_ref else 0}))


async def handle_get_peers(ws, peer_id: str, payload: dict):
    """Peer listesini gönder."""
    try:
        from core.database import get_active_peers
        peers = get_active_peers(_db_path)
        await ws.send(make_msg("peers_list", {"peers": peers[:20]}))
    except Exception:
        await ws.send(make_msg("peers_list", {"peers": []}))


async def handle_peers_list(ws, peer_id: str, payload: dict):
    """Validate exchanged peer entries against port bounds and active bans."""
    peers = payload.get("peers", [])
    if not isinstance(peers, list):
        return
    try:
        from core.database import upsert_peer
        for p in peers[:20]:
            if not isinstance(p, dict):
                continue
            host = str(p.get("host") or "").strip()
            try:
                port = int(p.get("port", 0))
            except Exception:
                continue
            if not host or not (1 <= port <= 65535) or is_ip_banned(host):
                continue
            pid = str(p.get("peer_id") or f"{host}:{port}")[:64]
            upsert_peer(pid, host, port, str(p.get("version", "?")), _db_path)
    except Exception:
        pass


# Mesaj yönlendirici
MSG_HANDLERS = {
    "handshake":      handle_handshake,
    "new_block":      handle_new_block,
    "new_tx":         handle_new_tx,
    "get_chain":      handle_get_chain,
    "chain_response": handle_chain_response,
    "ping":           handle_ping,
    "get_peers":      handle_get_peers,
    "peers_list":     handle_peers_list,
}


# ════════════════════════════════════════════════════════════════
# BAĞLANTI YÖNETİMİ
# ════════════════════════════════════════════════════════════════

async def _process_incoming_ws(ws, peer_id: str):
    """Shared verified message loop enforcing rate limits, pubkey binding, and ban disconnect."""
    async for raw in ws:
        if is_ip_banned(peer_id) or not check_peer_rate_limit(peer_id):
            try:
                await ws.close(code=1008, reason="Peer rate-limited or banned")
            except Exception:
                pass
            break
        msg = parse_msg(raw)
        if not msg:
            if record_peer_misbehavior(peer_id, 25, "invalid_or_replayed_msg"):
                try:
                    await ws.close(code=1008, reason="Invalid messages exceeded threshold")
                except Exception:
                    pass
                break
            continue

        msg_pub = str(msg.get("node_pubkey") or "").strip().lower()
        if msg_pub:
            bound_pub = _peer_pubkeys.get(peer_id)
            if bound_pub is None:
                same_pub_count = sum(1 for k, pk in _peer_pubkeys.items() if pk == msg_pub)
                if same_pub_count >= MAX_PEERS_PER_PUBKEY:
                    record_peer_misbehavior(peer_id, 100, "pubkey_sybil_limit")
                    try:
                        await ws.close(code=1008, reason="Pubkey connection limit exceeded")
                    except Exception:
                        pass
                    break
                _peer_pubkeys[peer_id] = msg_pub
            elif bound_pub != msg_pub:
                record_peer_misbehavior(peer_id, 100, "identity_spoofing")
                try:
                    await ws.close(code=1008, reason="Peer identity mismatch")
                except Exception:
                    pass
                break

        msg_type = msg.get("type")
        handler = MSG_HANDLERS.get(msg_type)
        if handler:
            await handler(ws, peer_id, msg.get("payload", {}))
        else:
            print(f"[P2P] Bilinmeyen mesaj tipi: {msg_type}")

        if is_ip_banned(peer_id):
            try:
                await ws.close(code=1008, reason="Peer banned")
            except Exception:
                pass
            break


async def _cleanup_peer(peer_id: str):
    async with _peer_lock:
        _connected_peers.pop(peer_id, None)
        _inbound_peers.discard(peer_id)
        _outbound_peers.discard(peer_id)
        _peer_pubkeys.pop(peer_id, None)
        _peer_msg_buckets.pop(peer_id, None)
        _sync_peer_count()


async def connection_handler(ws, path=None):
    """Gelen peer baglantisini Sybil/Eclipse/Ban limitleriyle kabul eder."""
    remote = ws.remote_address or ("unknown", 0)
    remote_ip = str(remote[0])
    peer_id = f"{remote_ip}:{remote[1]}"

    async with _peer_lock:
        allowed, reason = can_accept_peer(remote_ip, is_outbound=False)
        if not allowed:
            try:
                await ws.close(code=1008, reason=reason)
            except Exception:
                pass
            return
        _connected_peers[peer_id] = ws
        _inbound_peers.add(peer_id)
        _sync_peer_count()

    print(f"[P2P] OK Baglandi: {peer_id} | Toplam: {len(_connected_peers)}")
    await ws.send(_build_handshake_msg())

    try:
        await _process_incoming_ws(ws, peer_id)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[P2P] Bağlantı hatası ({peer_id}): {e}")
    finally:
        await _cleanup_peer(peer_id)
        print(f"[P2P] Baglanti kapandi: {peer_id} | Kalan: {len(_connected_peers)}")
        try:
            from core.database import mark_peer_inactive
            mark_peer_inactive(peer_id, _db_path)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# OUTBOUND BAĞLANTI (diğer peer'lara bağlan)
# ════════════════════════════════════════════════════════════════

async def connect_to_peer(host: str, port: int = None):
    """Uzak peer'a bağlan. Host alanı host:port biçimini de kabul eder."""
    if port is None:
        port = P2P_PORT
    if isinstance(host, str) and "://" not in host and host.count(":") == 1:
        maybe_host, maybe_port = host.rsplit(":", 1)
        if maybe_port.isdigit():
            host, port = maybe_host, int(maybe_port)

    allowed, _ = can_accept_peer(host, is_outbound=True)
    if not allowed:
        return

    uri = f"ws://{host}:{port}"
    peer_id = f"{host}:{port}"
    try:
        async with websockets.connect(uri, ping_interval=30, ping_timeout=10, max_size=MAX_MSG_BYTES) as ws:
            async with _peer_lock:
                ok_in, _ = can_accept_peer(host, is_outbound=True)
                if not ok_in:
                    return
                _connected_peers[peer_id] = ws
                _outbound_peers.add(peer_id)
                _sync_peer_count()

            await ws.send(_build_handshake_msg())
            print(f"[P2P] OK Baglandi (outbound): {uri}")
            await _process_incoming_ws(ws, peer_id)

    except Exception as e:
        print(f"[P2P] Peer bağlantısı başarısız ({uri}): {e}")
    finally:
        await _cleanup_peer(peer_id)


async def periodic_peer_connect(seed_peers: list, interval: int = 60):
    """Bilinen peer'lara periyodik olarak bağlanmayı dene."""
    while True:
        try:
            from core.database import get_active_peers
            db_peers = get_active_peers(_db_path)
            all_peers = list({(p["host"], p["port"]) for p in db_peers} |
                             {(h, P2P_PORT) for h in seed_peers})
            for host, port in all_peers:
                if is_ip_banned(host):
                    continue
                pid = f"{host}:{port}"
                async with _peer_lock:
                    if pid not in _connected_peers and len(_outbound_peers) < MAX_OUTBOUND_PEERS:
                        asyncio.create_task(connect_to_peer(host, port))
        except Exception as e:
            print(f"[P2P] Peer tarama hatası: {e}")
        await asyncio.sleep(interval)


# ════════════════════════════════════════════════════════════════
# ANA SUNUCU BAŞLATICI
# ════════════════════════════════════════════════════════════════

async def start_p2p_server(blockchain_instance, seed_peers: list = None,
                           host: str = "0.0.0.0", port: int = P2P_PORT,
                           db_path: str = "univa_chain.db"):
    """P2P sunucusunu başlat."""
    global _blockchain_ref, _db_path, P2P_PORT
    _blockchain_ref = blockchain_instance
    _db_path        = db_path
    P2P_PORT        = port

    server = await websockets.serve(
        connection_handler,
        host, port,
        ping_interval=20,
        ping_timeout=10,
        max_size=MAX_MSG_BYTES,
    )
    print(f"[P2P] WebSocket P2P sunucusu baslatildi: ws://{host}:{port}")

    if seed_peers:
        for peer_host in seed_peers:
            asyncio.create_task(connect_to_peer(peer_host, P2P_PORT))

    asyncio.create_task(periodic_peer_connect(seed_peers or [], interval=120))
    return server


def run_p2p_in_thread(blockchain_instance, seed_peers: list = None,
                      host: str = "0.0.0.0", port: int = P2P_PORT,
                      db_path: str = "univa_chain.db"):
    """P2P sunucusunu ayrı bir thread'de başlat."""
    global _p2p_loop
    loop = asyncio.new_event_loop()
    _p2p_loop = loop

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            start_p2p_server(blockchain_instance, seed_peers, host, port, db_path)
        )
        loop.run_forever()

    t = threading.Thread(target=_run, daemon=True, name="UNIVA-P2P")
    t.start()
    print(f"[P2P] Thread başlatıldı (port {port})")
    return t, loop


def get_peer_count() -> int:
    return len(_connected_peers)


def get_peer_list() -> list:
    return list(_connected_peers.keys())


def publish_block_from_thread(block_dict: dict) -> bool:
    """Schedule block broadcast from a synchronous API/miner thread."""
    loop = _p2p_loop
    if loop is None or not loop.is_running():
        return False
    asyncio.run_coroutine_threadsafe(broadcast_block(block_dict), loop)
    return True


def publish_tx_from_thread(tx_dict: dict) -> bool:
    loop = _p2p_loop
    if loop is None or not loop.is_running():
        return False
    asyncio.run_coroutine_threadsafe(broadcast_tx(tx_dict), loop)
    return True
