"""
UNIVA Network - asyncio + WebSocket P2P Katmanı
================================================
Port: 5051 (WebSocket)
Port: 5050 (HTTP API - network.py ile)

Özellikler:
  - asyncio tabanlı, çift yönlü WebSocket bağlantıları
  - Otomatik peer keşfi ve bağlanma
  - Blok ve TX yayını (broadcast)
  - MTP zaman damgası doğrulaması
  - DB'ye peer kaydı
  - Zincir senkronizasyonu (en uzun zincir kazanır)
"""

import asyncio
import json
import time
import hashlib
import threading
import websockets
from typing import Set, Dict, Optional

P2P_PORT    = 5051
P2P_VERSION = "UNIVA/2.1.0"

# Aktif bağlantı seti (thread-safe için asyncio.Lock ile kullanılır)
_connected_peers: Dict[str, websockets.WebSocketServerProtocol] = {}
_peer_lock = asyncio.Lock()

# Dışarıdan erişim için referans
_blockchain_ref = None
_db_path        = "univa_chain.db"
_p2p_loop = None


# ════════════════════════════════════════════════════════════════
# MESAJ PROTOKOLÜ
# ════════════════════════════════════════════════════════════════

def make_msg(msg_type: str, payload: dict = None) -> str:
    return json.dumps({
        "type":    msg_type,
        "version": P2P_VERSION,
        "time":    time.time(),
        "payload": payload or {}
    }, ensure_ascii=False)


def parse_msg(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except Exception:
        return None


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
    for d in dead:
        async with _peer_lock:
            _connected_peers.pop(d, None)


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
    their_height = payload.get("height", 0)
    our_height   = len(_blockchain_ref.chain) - 1 if _blockchain_ref else 0
    version      = payload.get("version", "?")

    # DB'ye peer kaydet
    try:
        from core.database import upsert_peer
        host = ws.remote_address[0] if ws.remote_address else "unknown"
        port = payload.get("p2p_port", P2P_PORT)
        upsert_peer(peer_id, host, port, version, _db_path)
    except Exception:
        pass

    print(f"[P2P] Handshake: {peer_id} | yükseklik={their_height} | sürüm={version}")

    # Onlarda daha uzun zincir varsa talep et
    if their_height > our_height:
        await ws.send(make_msg("get_chain", {"from_height": our_height + 1}))


async def handle_new_block(ws, peer_id: str, payload: dict):
    """Validate and append a received block before relaying it."""
    if not _blockchain_ref:
        return
    block_data = payload.get("block")
    if not isinstance(block_data, dict):
        return
    index = block_data.get("index", -1)
    our_height = _blockchain_ref.height
    if index <= our_height:
        return
    if index > our_height + 1:
        await ws.send(make_msg("get_chain", {"from_height": our_height + 1}))
        return
    if _blockchain_ref.accept_block(block_data):
        await broadcast(make_msg("new_block", {"block": block_data}), exclude_peer=peer_id)
        print(f"[P2P] Blok #{index} doğrulandı ve eklendi")
    else:
        print(f"[P2P] Blok #{index} reddedildi: konsensüs doğrulaması başarısız")


async def handle_new_tx(ws, peer_id: str, payload: dict):
    """Gelen TX'i mempool'a ekle."""
    if not _blockchain_ref:
        return
    tx = payload.get("tx")
    if not tx:
        return

    # Duplicate kontrolü
    existing_ids = {t.get("tx_id") for t in _blockchain_ref.pending_transactions}
    tx_id = tx.get("tx_id") or hashlib.sha256(
        json.dumps(tx, sort_keys=True).encode()
    ).hexdigest()

    if tx_id not in existing_ids and _blockchain_ref.add_transaction(tx):
        print(f"[P2P] TX mempool'a eklendi: {tx_id[:16]}...")
        await broadcast(make_msg("new_tx", {"tx": tx}), exclude_peer=peer_id)


async def handle_get_chain(ws, peer_id: str, payload: dict):
    """Peer'a istenen yükseklikten itibaren blokları gönder."""
    if not _blockchain_ref:
        return
    from_h = payload.get("from_height", 0)
    blocks = [
        b.to_dict() for b in _blockchain_ref.chain
        if b.index >= from_h
    ]
    await ws.send(make_msg("chain_response", {
        "blocks": blocks,
        "height": len(_blockchain_ref.chain) - 1
    }))
    print(f"[P2P] {len(blocks)} blok gönderildi → {peer_id}")


async def handle_chain_response(ws, peer_id: str, payload: dict):
    """Sequentially validate every downloaded block; stop on the first invalid block."""
    if not _blockchain_ref:
        return
    blocks = payload.get("blocks", [])
    if not isinstance(blocks, list):
        return
    added = 0
    for bd in blocks:
        if not isinstance(bd, dict):
            break
        if bd.get("index", -1) <= _blockchain_ref.height:
            continue
        if not _blockchain_ref.accept_block(bd):
            print(f"[P2P] Senkronizasyon durdu: blok #{bd.get('index')} geçersiz")
            break
        added += 1
    if added:
        print(f"[P2P] {added} blok doğrulanarak senkronize edildi")


async def handle_ping(ws, peer_id: str, payload: dict):
    await ws.send(make_msg("pong", {"height": len(_blockchain_ref.chain) - 1 if _blockchain_ref else 0}))


async def handle_get_peers(ws, peer_id: str, payload: dict):
    """Peer listesini gönder."""
    try:
        from core.database import get_active_peers
        peers = get_active_peers(_db_path)
        await ws.send(make_msg("peers_list", {"peers": peers[:20]}))
    except Exception:
        await ws.send(make_msg("peers_list", {"peers": []}))


# Mesaj yönlendirici
MSG_HANDLERS = {
    "handshake":      handle_handshake,
    "new_block":      handle_new_block,
    "new_tx":         handle_new_tx,
    "get_chain":      handle_get_chain,
    "chain_response": handle_chain_response,
    "ping":           handle_ping,
    "get_peers":      handle_get_peers,
}


# ════════════════════════════════════════════════════════════════
# BAĞLANTI YÖNETİMİ
# ════════════════════════════════════════════════════════════════

async def connection_handler(ws, path=None):
    """Her gelen bağlantı için çalışır."""
    remote = ws.remote_address or ("unknown", 0)
    peer_id = f"{remote[0]}:{remote[1]}"

    async with _peer_lock:
        _connected_peers[peer_id] = ws

    print(f"[P2P] OK Baglandi: {peer_id} | Toplam: {len(_connected_peers)}")

    # Handshake gönder
    our_height = len(_blockchain_ref.chain) - 1 if _blockchain_ref else 0
    await ws.send(make_msg("handshake", {
        "version":   P2P_VERSION,
        "height":    our_height,
        "p2p_port":  P2P_PORT,
        "network":   "UNIVA Network",
    }))

    try:
        async for raw in ws:
            msg = parse_msg(raw)
            if not msg:
                continue
            msg_type = msg.get("type")
            handler  = MSG_HANDLERS.get(msg_type)
            if handler:
                await handler(ws, peer_id, msg.get("payload", {}))
            else:
                print(f"[P2P] Bilinmeyen mesaj tipi: {msg_type}")
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[P2P] Bağlantı hatası ({peer_id}): {e}")
    finally:
        async with _peer_lock:
            _connected_peers.pop(peer_id, None)
        print(f"[P2P] Baglanti kapandi: {peer_id} | Kalan: {len(_connected_peers)}")

        # DB'de peer'ı pasif yap
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
    uri = f"ws://{host}:{port}"
    peer_id = f"{host}:{port}"
    try:
        async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
            async with _peer_lock:
                _connected_peers[peer_id] = ws

            # Handshake
            our_height = len(_blockchain_ref.chain) - 1 if _blockchain_ref else 0
            await ws.send(make_msg("handshake", {
                "version":  P2P_VERSION,
                "height":   our_height,
                "p2p_port": P2P_PORT,
                "network":  "UNIVA Network",
            }))

            print(f"[P2P] OK Baglandi (outbound): {uri}")

            async for raw in ws:
                msg = parse_msg(raw)
                if not msg:
                    continue
                msg_type = msg.get("type")
                handler  = MSG_HANDLERS.get(msg_type)
                if handler:
                    await handler(ws, peer_id, msg.get("payload", {}))

    except Exception as e:
        print(f"[P2P] Peer bağlantısı başarısız ({uri}): {e}")
    finally:
        async with _peer_lock:
            _connected_peers.pop(peer_id, None)


async def periodic_peer_connect(seed_peers: list, interval: int = 60):
    """Bilinen peer'lara periyodik olarak bağlanmayı dene."""
    while True:
        try:
            from core.database import get_active_peers
            db_peers = get_active_peers(_db_path)
            all_peers = list({(p["host"], p["port"]) for p in db_peers} |
                             {(h, P2P_PORT) for h in seed_peers})
            for host, port in all_peers:
                pid = f"{host}:{port}"
                async with _peer_lock:
                    if pid not in _connected_peers:
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
    )
    print(f"[P2P] WebSocket P2P sunucusu baslatildi: ws://{host}:{port}")

    # Seed peer'lara bağlan
    if seed_peers:
        for peer_host in seed_peers:
            asyncio.create_task(connect_to_peer(peer_host, P2P_PORT))

    # Periyodik yeniden bağlanma
    asyncio.create_task(periodic_peer_connect(seed_peers or [], interval=120))

    return server


def run_p2p_in_thread(blockchain_instance, seed_peers: list = None,
                      host: str = "0.0.0.0", port: int = P2P_PORT,
                      db_path: str = "univa_chain.db"):
    """
    P2P sunucusunu ayrı bir thread'de başlat.
    Flask (network.py) ile aynı anda çalışabilir.
    """
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
