"""UNIVA unified production-grade testnet HTTP API (FastAPI).
Serves PWA wallet, Explorer, Telemetry, Bitcoin RPC, DEX quotes, and Blockchain operations.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
import hashlib
import json
import os
import sys
import threading
import time
import urllib.request

from core.blockchain import Blockchain
from core.config import get_network_config, get_locked_protocol_manifest
from core.dex import UnivaDEX, to_base_units, from_base_units
from core.offline_pay import OfflinePayManager, OfflinePayError, DEFAULT_VOUCHER_TTL
from core.telemetry import telemetry
from core.interop import MultiChainReader, UniversalProofEngine
from core.trc20 import TRC20Gateway, TronAddress, MultiChainAddress

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PWA_DIR = os.path.join(BASE_DIR, "pwa")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
NET_CFG = get_network_config()
CHAIN_PATH = os.environ.get("UNIVA_CHAIN_FILE", NET_CFG["default_chain_file"])

blockchain = Blockchain(auto_load_path=CHAIN_PATH, network=NET_CFG["network_id"])
app = FastAPI(title="UNIVA L1 Unified Node API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_RATE_BUCKETS: Dict[str, List[float]] = {}
_ACTIVE_CLIENTS: Dict[str, Dict[str, Any]] = {}
_MASTER_FAIL_BUCKETS: Dict[str, List[float]] = {}
MASTER_AUTH_FILE = os.path.join(BASE_DIR, "univa_master_auth.json")

_COUNTRY_MAP = {
    "TR": ("🇹🇷", "Türkiye"),
    "US": ("🇺🇸", "ABD"),
    "DE": ("🇩🇪", "Almanya"),
    "GB": ("🇬🇧", "İngiltere"),
    "NL": ("🇳🇱", "Hollanda"),
    "FR": ("🇫🇷", "Fransa"),
    "RU": ("🇷🇺", "Rusya"),
    "AZ": ("🇦🇿", "Azerbaycan"),
    "CN": ("🇨🇳", "Çin"),
    "JP": ("🇯🇵", "Japonya"),
    "KR": ("🇰🇷", "Güney Kore"),
    "AE": ("🇦🇪", "BAE"),
}

def _resolve_country(request: Request) -> tuple:
    cc = (
        request.headers.get("cf-ipcountry")
        or request.headers.get("x-univa-country")
        or ""
    ).strip().upper()
    if not cc or cc in ("XX", "T1"):
        lang = (request.headers.get("accept-language") or "").lower()
        if "tr" in lang or not lang:
            cc = "TR"
        elif "de" in lang:
            cc = "DE"
        elif "ru" in lang:
            cc = "RU"
        else:
            cc = "TR"
    flag, name = _COUNTRY_MAP.get(cc, ("🌐", cc))
    return cc, flag, f"{flag} {name} ({cc})"

def _resolve_device(request: Request, client_ip: str) -> str:
    ua = (request.headers.get("user-agent") or "").lower()
    if request.url.path == "/rpc":
        return "Web3 / Trust Wallet RPC"
    if "android" in ua:
        return "Mobil Düğüm (Android)"
    if "iphone" in ua or "ipad" in ua:
        return "Mobil Düğüm (iOS)"
    if "telegram" in ua:
        return "Telegram Mini-App Düğümü"
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return "Yetkili Ana Düğüm (PC)"
    return "Masaüstü Web Düğümü (PC)"

@app.middleware("http")
async def add_pna_and_security_headers(request: Request, call_next):
    # 1. Chrome Private Network Access (PNA) preflight
    if request.method == "OPTIONS" and "access-control-request-private-network" in request.headers:
        response = PlainTextResponse("OK", status_code=200)
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = request.headers.get("access-control-request-headers", "*")
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    # 2. Payload Size Protection (Anti-DoS / Memory Exhaustion)
    content_len = request.headers.get("content-length")
    if content_len and content_len.isdigit() and int(content_len) > 65536:
        return JSONResponse({"error": "Payload Too Large (Max 64KB)"}, status_code=413)

    # 3. Sliding-Window Rate Limiter & Active Node/Client Geo-Tracker
    client_ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "127.0.0.1")
        or "127.0.0.1"
    )
    ua_raw = request.headers.get("user-agent", "")
    # Ignore one-off synthetic python-urllib health checks so only real browser/mobile/RPC nodes are listed
    is_real_client = ("mozilla" in ua_raw.lower()) or bool(request.headers.get("x-univa-client")) or (request.url.path == "/rpc")
    now = time.time()
    if is_real_client:
        client_id = request.headers.get("x-univa-client") or f"{client_ip}:{ua_raw[:36]}"
        cc, flag, country_label = _resolve_country(request)
        device_label = _resolve_device(request, client_ip)
        masked_ip = client_ip if client_ip in ("127.0.0.1", "::1") else (".".join(client_ip.split(".")[:2]) + ".*.*" if "." in client_ip else client_ip[:12] + "...")
        _ACTIVE_CLIENTS[client_id] = {
            "id": client_id[:16],
            "ip": masked_ip,
            "country_code": cc,
            "flag": flag,
            "country": country_label,
            "device": device_label,
            "last_seen": now,
        }
    bucket = [t for t in _RATE_BUCKETS.get(client_ip, []) if now - t < 60.0]
    if len(bucket) > 240:
        return JSONResponse({"error": "Rate limit exceeded. Security shield active."}, status_code=429)
    bucket.append(now)
    _RATE_BUCKETS[client_ip] = bucket

    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    return response

# Native AMM instance bound directly to Sovereign L1 Blockchain state
DEX_STATE_PATH = os.environ.get("UNIVA_DEX_STATE_FILE", os.path.join(BASE_DIR, NET_CFG["default_dex_file"]))
OFFLINE_STATE_PATH = os.environ.get("UNIVA_OFFLINE_STATE_FILE", os.path.join(BASE_DIR, NET_CFG["default_offline_file"]))
offline_mgr = OfflinePayManager(state_path=OFFLINE_STATE_PATH)
dex_engine = UnivaDEX(blockchain=blockchain, state_path=DEX_STATE_PATH)
try:
    if dex_engine.get_pool("UNIVA", "uUSD") is None:
        dex_engine.create_pool("UNIVA", "uUSD", fee_bps=10)
        dex_engine.deposit("univa_genesis_vault", "UNIVA", to_base_units(50_000.0))
        dex_engine.deposit("univa_genesis_vault", "uUSD", to_base_units(250_000.0))
        dex_engine.add_liquidity(
            provider="univa_genesis_vault",
            asset_a="UNIVA",
            asset_b="uUSD",
            amount_a=to_base_units(50_000.0),
            amount_b=to_base_units(250_000.0),
        )
        dex_engine.save(DEX_STATE_PATH)
except Exception as e:
    print(f"[UNIVA] DEX baslatma uyarisi: {e}")


class TransactionBody(BaseModel):
    tx: Optional[Dict[str, Any]] = None
    from_: Optional[str] = None
    to: Optional[str] = None
    amount: Optional[float] = None
    fee: Optional[float] = 0.0


# ─── PWA & STATIK DOSYA SUNUCUSU ─────────────────────────────────────────────

@app.get("/")
def serve_pwa_root():
    index_path = os.path.join(PWA_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return {"network": "UNIVA Network", "version": "3.0.0"}

@app.get("/manifest.json")
def serve_manifest():
    p = os.path.join(PWA_DIR, "manifest.json")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/manifest+json")
    raise HTTPException(404, "manifest.json not found")

@app.get("/sw.js")
def serve_sw():
    p = os.path.join(PWA_DIR, "sw.js")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/javascript")
    raise HTTPException(404, "sw.js not found")

@app.get("/miner.worker.js")
def serve_miner_worker():
    p = os.path.join(PWA_DIR, "miner.worker.js")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/javascript")
    raise HTTPException(404, "miner.worker.js not found")

@app.get("/offline-transport.js")
def serve_offline_transport():
    p = os.path.join(PWA_DIR, "offline-transport.js")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/javascript")
    raise HTTPException(404, "offline-transport.js not found")

@app.get("/logo.png")
def serve_root_logo():
    p = os.path.join(PWA_DIR, "logo.png")
    if not os.path.exists(p):
        p = os.path.join(ASSETS_DIR, "logo.png")
    if os.path.exists(p):
        return FileResponse(p, media_type="image/png")
    raise HTTPException(404, "logo.png not found")

@app.get("/assets/{filename:path}")
def serve_assets(filename: str):
    p = os.path.join(ASSETS_DIR, filename)
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(404, "Asset not found")

@app.get("/whitepaper")
@app.get("/api/v1/whitepaper")
def get_whitepaper():
    wp_path = os.path.join(BASE_DIR, "UNIVA_WHITEPAPER.md")
    if os.path.exists(wp_path):
        with open(wp_path, "r", encoding="utf-8") as f:
            return PlainTextResponse(f.read(), media_type="text/markdown; charset=utf-8")
    return {"title": "UNIVA Network Whitepaper v3.0", "status": "Ready"}


# ─── ZINCIR & BLOK ENDPOINTLERI ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "network": "UNIVA-L1", "height": blockchain.height}

@app.get("/stats")
def stats():
    now = time.time()
    active_entries = [
        info for _, info in list(_ACTIVE_CLIENTS.items())
        if isinstance(info, dict) and now - info.get("last_seen", 0) < 300.0
    ]
    nodes_list = [
        {
            "id": "master-seed-01",
            "ip": "127.0.0.1:5050",
            "country_code": "TR",
            "flag": "🇹🇷",
            "country": "🇹🇷 Türkiye (TR)",
            "device": "Master Genesis Seed (Ana Bilgisayar Düğümü)",
            "status": "PRIMARY ONLINE",
        }
    ]
    for entry in active_entries:
        if entry.get("ip") in ("127.0.0.1", "::1") and "Ana Düğüm" in entry.get("device", ""):
            continue
        nodes_list.append({
            "id": entry.get("id", "node"),
            "ip": entry.get("ip", "—"),
            "country_code": entry.get("country_code", "TR"),
            "flag": entry.get("flag", "🇹🇷"),
            "country": entry.get("country", "🇹🇷 Türkiye (TR)"),
            "device": entry.get("device", "Uzak Düğüm"),
            "status": "ACTIVE PEER",
        })
    data = blockchain.stats()
    data["network"] = "UNIVA Network"
    data["version"] = "4.0.0"
    data["active_nodes"] = len(nodes_list)
    data["peer_count"] = max(data.get("peer_count", 0), max(0, len(nodes_list) - 1))
    data["connected_nodes"] = nodes_list
    data["confirmed_blocks"] = blockchain.height
    data["total_txs"] = sum(len(b.transactions) for b in blockchain.chain) + len(blockchain.pending_transactions)
    try:
        pub_file = os.path.join(BASE_DIR, "public_url.txt")
        if os.path.exists(pub_file):
            with open(pub_file, "r", encoding="utf-8") as f:
                data["public_url"] = f.read().strip()
    except Exception:
        pass
    return data

@app.get("/chain")
def chain(from_height: int = 0, limit: int = 100):
    if from_height < 0 or limit < 1 or limit > 1000:
        raise HTTPException(400, "from_height >= 0 ve limit 1..1000 olmalidir")
    chain_slice = blockchain.chain[from_height:from_height + limit]
    return {
        "height": blockchain.height,
        "length": len(blockchain.chain),
        "chain": [b.to_dict() for b in chain_slice],
        "blocks": [b.to_dict() for b in chain_slice],
    }

@app.get("/block/{height}")
def get_block(height: int):
    if height < 0 or height > blockchain.height:
        raise HTTPException(404, "Blok bulunamadi")
    b_dict = blockchain.chain[height].to_dict()
    return {**b_dict, "block": b_dict}

@app.post("/block")
def receive_block(block_data: Dict[str, Any]):
    if blockchain.accept_block(block_data):
        blockchain.save(CHAIN_PATH)
        try:
            from core.p2p import publish_block_from_thread
            publish_block_from_thread(block_data)
        except Exception:
            pass
        return {"status": "accepted", "height": blockchain.height}
    raise HTTPException(400, "Blok konsensus dogrulamasindan gecemedi")

@app.get("/block/hash/{block_hash}")
def get_block_by_hash_endpoint(block_hash: str):
    target = block_hash.strip().lower().replace("0x", "")
    for blk in reversed(blockchain.chain):
        bh = blk.hash.lower().replace("0x", "")
        if bh == target or (len(target) >= 8 and bh.startswith(target)):
            b_dict = blk.to_dict()
            return {**b_dict, "block": b_dict}
    raise HTTPException(404, "Blok hash bulunamadi")


@app.get("/api/v1/protocol/manifest")
def protocol_manifest():
    m = get_locked_protocol_manifest(blockchain.network)
    m["genesis_hash"] = blockchain.chain[0].hash if blockchain.chain else ""
    m["height"] = blockchain.height
    m["total_mined"] = round(blockchain.total_mined, 8)
    m["chain_valid"] = blockchain.is_chain_valid()
    return m


def _get_effective_balance(address: str) -> float:
    """Onaylanmis blok bakiyesi + mempool'daki bekleyen gonderim/alim farkini hesaplar."""
    from core.wallet import normalize_address
    norm = normalize_address(address)
    bal = blockchain.get_balance(norm, include_pending_outgoing=True)
    for tx in blockchain.pending_transactions:
        if tx.get("type", "transfer") in ("transfer", "offline_spend") and normalize_address(tx.get("to", "")) == norm:
            bal += float(tx.get("amount", 0.0))
    return round(max(0.0, bal), 8)


def _resolve_default_miner_address() -> str:
    wallet_path = os.path.join(BASE_DIR, "univa_wallet.json")
    try:
        if os.path.exists(wallet_path):
            with open(wallet_path, "r", encoding="utf-8") as wf:
                wdata = json.load(wf)
            addr = (wdata.get("address") or "").strip()
            if addr.startswith("univa"):
                return addr
    except Exception:
        pass
    return "univaf63aua23vxdvcmvkunx66yzh2"


MINER_LOCK = threading.Lock()
MINER_DAEMON_STATE: Dict[str, Any] = {
    "enabled": True,
    "running": False,
    "miner_address": _resolve_default_miner_address(),
    "blocks_mined": 0,
    "last_mined_height": 0,
    "last_mined_at": 0.0,
}


@app.get("/balance/{address}")
@app.get("/api/v1/balance/{address}")
def balance(address: str):
    from core.wallet import validate_address
    is_valid = validate_address(address)
    if is_valid and address.startswith("univa"):
        MINER_DAEMON_STATE["miner_address"] = address
    bal = _get_effective_balance(address)
    return {
        "address": address,
        "balance": bal,
        "confirmed_balance": blockchain.get_balance(address, include_pending_outgoing=False),
        "nonce": blockchain._pending_nonce(address),
        "ticker": "UNIVA",
        "valid_format": is_valid,
    }

@app.get("/addresses")
@app.get("/api/v1/addresses")
def list_all_addresses():
    """
    Blokzincir uzerindeki tum UNIVA ve EVM adreslerini, bakiyelerini,
    kazdiklari blok sayilarini ve islem sayilarini dondurur.
    """
    addr_stats: Dict[str, Dict[str, Any]] = {}
    for block in blockchain.chain:
        miner = block.miner_address
        if miner:
            st = addr_stats.setdefault(miner, {"address": miner, "blocks_mined": 0, "tx_count": 0, "last_block": 0})
            if block.index > 0:
                st["blocks_mined"] += 1
            st["last_block"] = max(st["last_block"], block.index)
        for tx in block.transactions:
            for role_key in ("from", "to"):
                a = tx.get(role_key)
                if a and isinstance(a, str) and (a.startswith("univa") or a.startswith("0x")):
                    st = addr_stats.setdefault(a, {"address": a, "blocks_mined": 0, "tx_count": 0, "last_block": 0})
                    st["tx_count"] += 1
                    st["last_block"] = max(st["last_block"], block.index)

    for tx in blockchain.pending_transactions:
        for role_key in ("from", "to"):
            a = tx.get(role_key)
            if a and isinstance(a, str) and (a.startswith("univa") or a.startswith("0x")):
                st = addr_stats.setdefault(a, {"address": a, "blocks_mined": 0, "tx_count": 0, "last_block": blockchain.height})
                st["tx_count"] += 1

    results = []
    for a, st in addr_stats.items():
        st["balance"] = _get_effective_balance(a)
        st["address_type"] = "EVM Mirror (0x)" if a.startswith("0x") else ("Genesis Root" if a == "univa0000000000univa" else "UNIVA L1 Native")
        results.append(st)

    results.sort(key=lambda x: (x["balance"], x["blocks_mined"], x["tx_count"]), reverse=True)
    return {
        "total_addresses": len(results),
        "native_system_contract": "0x0000000000000000000000000000000000210001",
        "genesis_root_address": "univa0000000000univa",
        "addresses": results,
    }

@app.get("/api/v1/tx/{tx_id}")
def get_transaction_by_id(tx_id: str):
    clean_id = tx_id.strip().lower()
    if clean_id.startswith("coinbase_blk_"):
        try:
            blk_idx = int(clean_id[len("coinbase_blk_"):])
            if 0 <= blk_idx <= blockchain.height and blockchain.chain[blk_idx].transactions:
                blk = blockchain.chain[blk_idx]
                return {
                    "status": "confirmed",
                    "block_index": blk.index,
                    "block_hash": blk.hash,
                    "timestamp": blk.timestamp,
                    "tx": {**blk.transactions[0], "tx_id": f"coinbase_blk_{blk.index}"},
                }
        except Exception:
            pass
    clean_no_0x = clean_id[2:] if clean_id.startswith("0x") else clean_id
    for block in reversed(blockchain.chain):
        for tx in block.transactions:
            tid = str(tx.get("tx_id") or "").lower()
            tid_no_0x = tid[2:] if tid.startswith("0x") else tid
            if tid_no_0x and (tid_no_0x == clean_no_0x or tid == clean_id):
                return {
                    "status": "confirmed",
                    "block_index": block.index,
                    "block_hash": block.hash,
                    "timestamp": block.timestamp,
                    "tx": tx,
                }
    for tx in blockchain.pending_transactions:
        tid = str(tx.get("tx_id") or "").lower()
        tid_no_0x = tid[2:] if tid.startswith("0x") else tid
        if tid_no_0x and (tid_no_0x == clean_no_0x or tid == clean_id):
            return {
                "status": "pending",
                "block_index": None,
                "block_hash": None,
                "timestamp": tx.get("timestamp", time.time()),
                "tx": tx,
            }
    raise HTTPException(404, "Islem bulunamadi")


@app.get("/api/v1/explorer/search")
def explorer_unified_search(q: str = ""):
    """Unified Explorer search: block height (#N or N), block hash, tx_id, coinbase_blk_N, L1/EVM address."""
    from core.wallet import validate_address
    raw = (q or "").strip()
    if not raw:
        raise HTTPException(400, "Arama sorgusu bos olamaz")

    # 1. Numeric block height (supports '10' or '#10')
    num_cand = raw[1:] if raw.startswith("#") else raw
    if num_cand.isdigit():
        idx = int(num_cand)
        if 0 <= idx <= blockchain.height:
            b_dict = blockchain.chain[idx].to_dict()
            return {"type": "block", "query": raw, "block": b_dict}
        raise HTTPException(404, f"Blok #{idx} bulunamadi (Mevcut yukseklik: {blockchain.height})")

    low = raw.lower()
    # 2. Coinbase clickable ID (coinbase_blk_<N>)
    if low.startswith("coinbase_blk_"):
        tx_res = get_transaction_by_id(raw)
        return {"type": "tx", "query": raw, **tx_res}

    # 3. Valid UNIVA L1 / Testnet / EVM 42-char address
    if validate_address(raw, network=blockchain.network) or (
        (raw.startswith("0x") or raw.startswith("0X")) and len(raw) == 42 and all(c in "0123456789abcdefABCDEF" for c in raw[2:])
    ):
        hist_res = address_history(raw)
        return {
            "type": "address",
            "query": raw,
            "address": raw,
            "balance": _get_effective_balance(raw),
            "confirmed_balance": blockchain.get_balance(raw, include_pending_outgoing=False),
            "uusd_balance": blockchain.get_balance(raw, "uUSD"),
            "nonce": blockchain._pending_nonce(raw),
            "address_type": (
                "EVM Mirror Address (0x)"
                if raw.lower().startswith("0x")
                else ("UNIVA Testnet Address (30-Char)" if raw.startswith("tuniva") else "UNIVA L1 Sovereign Address (30-Char Base31)")
            ),
            "history": hist_res.get("history", []),
            "tx_count": len(hist_res.get("history", [])),
        }

    # 4. TX ID lookup (exact or 0x-prefixed)
    hex_clean = low[2:] if low.startswith("0x") else low
    if len(hex_clean) >= 8 and all(c in "0123456789abcdef" for c in hex_clean):
        for blk in reversed(blockchain.chain):
            for tx in blk.transactions:
                tid = str(tx.get("tx_id") or "").lower().replace("0x", "")
                if tid and (tid == hex_clean or tid.startswith(hex_clean)):
                    return {
                        "type": "tx",
                        "query": raw,
                        "status": "confirmed",
                        "block_index": blk.index,
                        "block_hash": blk.hash,
                        "timestamp": blk.timestamp,
                        "tx": tx,
                    }
        for tx in blockchain.pending_transactions:
            tid = str(tx.get("tx_id") or "").lower().replace("0x", "")
            if tid and (tid == hex_clean or tid.startswith(hex_clean)):
                return {
                    "type": "tx",
                    "query": raw,
                    "status": "pending",
                    "block_index": None,
                    "block_hash": None,
                    "timestamp": tx.get("timestamp", time.time()),
                    "tx": tx,
                }
        # 5. Block hash lookup (exact or prefix >= 8 hex chars)
        for blk in reversed(blockchain.chain):
            bh = blk.hash.lower().replace("0x", "")
            if bh == hex_clean or bh.startswith(hex_clean):
                return {"type": "block", "query": raw, "block": blk.to_dict()}

    raise HTTPException(404, f"Sorgu blokzincir indeksinde bulunamadi: {raw}")

@app.get("/api/v1/transactions")
def list_recent_transactions(limit: int = 25):
    txs = []
    for tx in reversed(blockchain.pending_transactions):
        txs.append({
            "tx_id": tx.get("tx_id", "pending"),
            "block_index": None,
            "timestamp": tx.get("timestamp", time.time()),
            "type": tx.get("type", "transfer"),
            "from": tx.get("from"),
            "to": tx.get("to"),
            "amount": tx.get("amount", 0.0),
            "fee": tx.get("fee", 0.0),
            "status": "pending",
        })
    for block in reversed(blockchain.chain):
        for tx in reversed(block.transactions):
            txs.append({
                "tx_id": tx.get("tx_id") or f"coinbase_blk_{block.index}",
                "block_index": block.index,
                "timestamp": block.timestamp,
                "type": tx.get("type", "transfer"),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "amount": tx.get("amount", 0.0),
                "fee": tx.get("fee", 0.0),
                "status": "confirmed",
            })
            if len(txs) >= limit:
                return {"total": len(txs), "transactions": txs[:limit]}
    return {"total": len(txs), "transactions": txs[:limit]}

@app.get("/api/v1/history/{address}")
def address_history(address: str):
    """
    Belirtilen adresin dahil oldugu tum gonderilen, alinan ve madencilik (coinbase) islemlerini dondurur.
    """
    from core.wallet import normalize_address
    norm_addr = normalize_address(address)
    history = []
    # 1. Onaylanmis bloklardaki islemler
    for block in reversed(blockchain.chain):
        block_idx = block.index
        block_ts = block.timestamp
        for tx in block.transactions:
            tx_from = tx.get("from")
            tx_to = tx.get("to")
            tx_type = tx.get("type", "transfer")
            n_from = normalize_address(tx_from or "")
            n_to = normalize_address(tx_to or "")

            if n_from == norm_addr or n_to == norm_addr:
                is_incoming = (n_to == norm_addr)
                history.append({
                    "tx_id": tx.get("tx_id") or f"coinbase_{block_idx}",
                    "block_index": block_idx,
                    "timestamp": block_ts,
                    "type": tx_type,
                    "is_incoming": is_incoming,
                    "from": tx_from,
                    "to": tx_to,
                    "amount": tx.get("amount", 0.0),
                    "fee": tx.get("fee", 0.0),
                    "status": "confirmed"
                })
    
    # 2. Henuz onaylanmamis mempool (pending) islemleri
    for tx in blockchain.pending_transactions:
        tx_from = tx.get("from")
        tx_to = tx.get("to")
        if normalize_address(tx_from or "") == norm_addr or normalize_address(tx_to or "") == norm_addr:
            is_incoming = (normalize_address(tx_to or "") == norm_addr)
            history.append({
                "tx_id": tx.get("tx_id", "pending_tx"),
                "block_index": None,
                "timestamp": tx.get("timestamp", time.time()),
                "type": tx.get("type", "transfer"),
                "is_incoming": is_incoming,
                "from": tx_from,
                "to": tx_to,
                "amount": tx.get("amount", 0.0),
                "fee": tx.get("fee", 0.0),
                "status": "pending"
            })

    return {
        "address": address,
        "total_txs": len(history),
        "history": history
    }


# ─── KRIPTOGRAFIK CUZDAN & ISLEM ENDPOINTLERI ────────────────────────────────

@app.get("/wallet")
@app.get("/api/v1/wallet/master")
def get_master_wallet():
    """Sadece herkese acik master adres ve bakiye bilgisini dondurur (Ozel anahtar ASLA paylasilmaz)."""
    from core.wallet import UnivaWallet
    wallet_file = os.path.join(BASE_DIR, "univa_wallet.json")
    if os.path.exists(wallet_file):
        w = UnivaWallet.load(wallet_file)
        return {
            "status": "ok",
            "address": w.address,
            "evm_address": w.evm_address,
            "public_key": w.public_key,
            "balance": _get_effective_balance(w.address),
        }
    return {"status": "ok", "address": "", "evm_address": "", "public_key": "", "balance": 0.0}


@app.post("/api/v1/wallet/master-auth")
async def master_wallet_auth(request: Request):
    """
    6.000+ UNIVA barindiran Master Hesap (univaf63aua23vxdvcmvkunx66yzh2) icin
    PBKDF2-HMAC-SHA256 (200.000 iterasyon) + Brute-Force korumali tam yetkili erisim.
    """
    import hmac
    import secrets
    from core.wallet import UnivaWallet

    client_ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "127.0.0.1")
        or "127.0.0.1"
    )
    now = time.time()
    fails = [t for t in _MASTER_FAIL_BUCKETS.get(client_ip, []) if now - t < 900.0]
    _MASTER_FAIL_BUCKETS[client_ip] = fails
    if len(fails) >= 5:
        raise HTTPException(429, "Cok fazla hatali giris denemesi. Guvenlik kalkani aktif (15 dk kilit).")

    try:
        data = await request.json()
    except Exception:
        data = {}
    username = (data.get("username") or "").strip().lower()
    pin = (data.get("pin") or "").strip()

    if username != "kaya" or len(pin) < 4:
        fails.append(now)
        _MASTER_FAIL_BUCKETS[client_ip] = fails
        raise HTTPException(401, "Gecersiz kullanici adi veya PIN")

    wallet_file = os.path.join(BASE_DIR, "univa_wallet.json")
    if not os.path.exists(wallet_file):
        raise HTTPException(404, "Master cuzdan dosyasi bulunamadi")

    if not os.path.exists(MASTER_AUTH_FILE):
        direct_ip = request.client.host if request.client else ""
        has_proxy_hdr = bool(request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"))
        is_loopback = (direct_ip in ("127.0.0.1", "::1", "localhost")) and not has_proxy_hdr
        init_tok_env = os.environ.get("UNIVA_MASTER_INIT_TOKEN", "").strip()
        req_init_tok = request.headers.get("x-univa-init-token", "").strip()
        has_valid_init_tok = bool(init_tok_env and req_init_tok and hmac.compare_digest(req_init_tok, init_tok_env))
        if not (is_loopback or has_valid_init_tok):
            raise HTTPException(
                403,
                "Ilk Master PIN yalnizca yerel ana dugumden (localhost) veya gecerli X-Univa-Init-Token ile olusturulabilir.",
            )
        salt_hex = secrets.token_hex(16)
        dk_hex = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), 200_000).hex()
        with open(MASTER_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({"username": "kaya", "salt": salt_hex, "hash": dk_hex, "created_at": now}, f, indent=2)
        expected_hash = dk_hex
    else:
        with open(MASTER_AUTH_FILE, "r", encoding="utf-8") as f:
            auth_rec = json.load(f)
        salt_hex = auth_rec.get("salt", "")
        expected_hash = auth_rec.get("hash", "")
        cand_hash = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), 200_000).hex()
        if not hmac.compare_digest(cand_hash, expected_hash):
            fails.append(now)
            _MASTER_FAIL_BUCKETS[client_ip] = fails
            raise HTTPException(401, "Master PIN hatali! Erisim reddedildi.")

    _MASTER_FAIL_BUCKETS[client_ip] = []
    w = UnivaWallet.load(wallet_file)
    from core.wallet import encrypt_wallet_dict
    enc_payload = encrypt_wallet_dict({"private_key": w.private_key}, pin)
    session_key = hashlib.sha256(expected_hash.encode("utf-8")).digest()
    session_ts = str(int(now))
    session_sig = hmac.new(session_key, f"MASTER|{w.address}|{session_ts}".encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "status": "ok",
        "role": "MASTER_ADMIN",
        "address": w.address,
        "evm_address": w.evm_address,
        "public_key": w.public_key,
        "encrypted_private_key": enc_payload,
        "vault_salt": enc_payload["salt"],
        "session_token": f"{session_ts}.{session_sig}",
        "balance": _get_effective_balance(w.address),
    }


@app.post("/api/v1/wallet/create")
async def create_or_recover_wallet(request: Request):
    """
    Kullaniciya tek ve kalici bir secp256k1 ECDSA cuzdani uretir veya
    mevcut private_key ile ayni L1 adresini geri yukler (yalnizca yerel/legacy modda).
    """
    direct_ip = request.client.host if request.client else ""
    has_proxy = bool(request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"))
    is_loopback = (direct_ip in ("127.0.0.1", "::1", "localhost")) and not has_proxy
    if os.environ.get("UNIVA_ALLOW_LEGACY_SERVER_SIGN") != "1" and not is_loopback:
        raise HTTPException(
            403,
            "Guvenlik Politikasi (P0): Yeni cuzdanlar ve ozel anahtarlar yalnizca istemci cihazda uretilir.",
        )
    from core.wallet import UnivaWallet
    try:
        data = await request.json()
    except Exception:
        data = {}
    priv_hex = (data.get("private_key") or "").strip()
    try:
        w = UnivaWallet(private_key_hex=priv_hex if len(priv_hex) == 64 else None)
    except Exception:
        w = UnivaWallet()
    return {
        "status": "ok",
        "address": w.address,
        "evm_address": w.evm_address,
        "public_key": w.public_key,
        "private_key": w.private_key,
        "balance": _get_effective_balance(w.address),
    }


PUBKEY_BINDINGS_FILE = os.path.join(BASE_DIR, "univa_pubkey_bindings.json")

def _load_pubkey_bindings():
    from core.wallet import REGISTERED_PWA_ORIGINS
    if os.path.exists(PUBKEY_BINDINGS_FILE):
        try:
            with open(PUBKEY_BINDINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for pk, addrs in data.items():
                    if isinstance(addrs, list):
                        REGISTERED_PWA_ORIGINS.setdefault(pk, set()).update(addrs)
        except Exception:
            pass

def _save_pubkey_binding(pub_key: str, *addrs: str):
    from core.wallet import REGISTERED_PWA_ORIGINS
    s = REGISTERED_PWA_ORIGINS.setdefault(pub_key, set())
    for a in addrs:
        if a:
            s.add(a)
    try:
        serializable = {k: sorted(v) for k, v in REGISTERED_PWA_ORIGINS.items()}
        with open(PUBKEY_BINDINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
    except Exception:
        pass

_load_pubkey_bindings()

@app.post("/api/v1/wallet/bind-pubkey")
async def bind_pubkey_origin(request: Request):
    from core.wallet import UnivaWallet, validate_address
    data = await request.json()
    pub_key = (data.get("public_key") or "").strip().lower()
    addr = (data.get("address") or "").strip()
    evm = (data.get("evm_address") or "").strip()
    sig = (data.get("signature") or "").strip().lower()
    if len(pub_key) != 128 or not validate_address(addr):
        raise HTTPException(400, "Gecersiz public_key veya adres")
    msg = f"UNIVA_BIND|{pub_key}|{addr}|{evm}"
    if not UnivaWallet.verify_signature(pub_key, msg, sig):
        raise HTTPException(403, "ECDSA imza dogrulamasi basarisiz")
    _save_pubkey_binding(pub_key, addr, evm)
    return {"status": "ok", "bound": True, "address": addr}

@app.post("/transactions")
@app.post("/tx")
async def submit_transaction(request: Request):
    from core.wallet import UnivaWallet, derive_pwa_address, derive_pwa_evm_address
    data = await request.json()
    tx = data.get("tx") if "tx" in data else data
    if not isinstance(tx, dict):
        raise HTTPException(400, "Gecersiz islem verisi")

    # P0 Guvenlik Politikasi: Ozel anahtar sunucuya gonderilemez; imza istemcide uretilir
    priv_key = (tx.get("private_key") or data.get("private_key") or "").strip()
    if priv_key:
        if os.environ.get("UNIVA_ALLOW_LEGACY_SERVER_SIGN") != "1":
            raise HTTPException(
                400,
                "Guvenlik Politikasi (P0): Ozel anahtar sunucuya gonderilemez; islemi istemci tarafinda imzalayip gonderin.",
            )
    if ("signature" not in tx or not tx.get("signature")) and len(priv_key) == 64:
        try:
            w = UnivaWallet(private_key_hex=priv_key)
            allowed_senders = {
                w.address,
                w.evm_address,
                derive_pwa_address(priv_key),
                derive_pwa_evm_address(priv_key),
            }
            req_from = (tx.get("from") or "").strip()
            if req_from and req_from not in allowed_senders:
                raise HTTPException(400, "Ozel anahtar bu cuzdan adresine ait degil!")
            sender_addr = req_from if req_from in allowed_senders else w.address
            _save_pubkey_binding(w.public_key, sender_addr, derive_pwa_address(priv_key), derive_pwa_evm_address(priv_key))
            tx = blockchain.create_transaction(
                w, tx.get("to"), float(tx.get("amount", 0)), float(tx.get("fee", 0.0)), from_address=sender_addr
            )
        except ValueError as ve:
            raise HTTPException(400, str(ve))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Imzalama hatasi: {e}")

    # P5 Offline Reservation Guard: aktif cevrimdisi rezervasyonda kilitli fonlar normal /tx ile harcanamaz
    tx_sender = (tx.get("from") or "").strip()
    if tx_sender and offline_mgr.get_active_reserved(tx_sender) > 0:
        try:
            tx_cost = round(float(tx.get("amount", 0.0)) + float(tx.get("fee", 0.0)), 8)
            if offline_mgr.get_unreserved_spendable(blockchain, tx_sender) + 1e-8 < tx_cost:
                raise HTTPException(
                    400,
                    "Bu fonlar aktif bir cevrimdisi odeme rezervasyonunda kilitli; once rezervasyonu serbest birakin veya /api/v1/offline/submit kullanin.",
                )
        except HTTPException:
            raise
        except Exception:
            pass

    if not blockchain.add_transaction(tx):
        raise HTTPException(400, "Gecersiz islem: ECDSA imzasi, nonce, yetersiz bakiye veya adres formati hatali")

    try:
        from core.p2p import publish_tx_from_thread
        publish_tx_from_thread(tx)
    except Exception:
        pass

    return {
        "status": "ok",
        "accepted": True,
        "tx_id": tx.get("tx_id"),
        "mempool_size": len(blockchain.pending_transactions),
    }


# ─── MADENCILIK ENDPOINTI & 7/24 ARKA PLAN KAZIM DAEMONU ─────────────────────

def _commit_mined_block(block) -> None:
    """Persist a newly mined block to chain file, P2P peers, and SQLite index."""
    blockchain.save(CHAIN_PATH)
    try:
        from core.p2p import publish_block_from_thread
        publish_block_from_thread(block.to_dict())
    except Exception:
        pass
    try:
        from core.database import insert_block, insert_transactions
        insert_block(block.to_dict())
        insert_transactions(block.to_dict())
    except Exception:
        pass


class MinerDaemonUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    miner_address: Optional[str] = None


@app.get("/api/v1/miner/daemon")
def get_miner_daemon_status():
    from core.blockchain import TARGET_BLOCK_TIME
    elapsed = (time.time() - blockchain.last_block.timestamp) if blockchain.height >= 1 else TARGET_BLOCK_TIME
    remaining = max(0.0, round(TARGET_BLOCK_TIME - elapsed, 1)) if blockchain.height >= 1 else 0.0
    return {
        **MINER_DAEMON_STATE,
        "current_height": blockchain.height,
        "target_block_time": TARGET_BLOCK_TIME,
        "seconds_until_next_block": remaining,
    }


@app.post("/api/v1/miner/daemon")
def update_miner_daemon(req: MinerDaemonUpdateRequest):
    from core.wallet import validate_address
    if req.miner_address is not None:
        addr = req.miner_address.strip()
        if not validate_address(addr):
            raise HTTPException(400, f"Gecersiz UNIVA adresi: {addr}")
        MINER_DAEMON_STATE["miner_address"] = addr
    if req.enabled is not None:
        MINER_DAEMON_STATE["enabled"] = bool(req.enabled)
    return {"status": "ok", **MINER_DAEMON_STATE}


def _node_auto_miner_loop() -> None:
    """Background PC Full Node daemon that mines a block every TARGET_BLOCK_TIME seconds even when browser is closed."""
    from core.blockchain import TARGET_BLOCK_TIME
    MINER_DAEMON_STATE["running"] = True
    time.sleep(3.0)
    while True:
        try:
            if MINER_DAEMON_STATE.get("enabled", True):
                with MINER_LOCK:
                    should_mine = (
                        blockchain.height < 1
                        or (time.time() - blockchain.last_block.timestamp) >= TARGET_BLOCK_TIME
                    )
                    if should_mine:
                        target_addr = MINER_DAEMON_STATE.get("miner_address") or _resolve_default_miner_address()
                        block = blockchain.mine_pending_transactions(target_addr, reward_override=None)
                        if block is not None:
                            _commit_mined_block(block)
                            MINER_DAEMON_STATE["blocks_mined"] += 1
                            MINER_DAEMON_STATE["last_mined_height"] = block.index
                            MINER_DAEMON_STATE["last_mined_at"] = time.time()
        except Exception as exc:
            print(f"[AUTO-MINER] Hata: {exc}")
        time.sleep(2.0)


@app.on_event("startup")
def _start_auto_miner_on_startup():
    if any(m in sys.modules for m in ("pytest", "unittest")) or os.environ.get("UNIVA_NO_AUTO_MINER") == "1":
        return
    if not MINER_DAEMON_STATE.get("running"):
        t = threading.Thread(target=_node_auto_miner_loop, daemon=True, name="UNIVA-AutoMiner-Daemon")
        t.start()
        print(f"[AUTO-MINER] 7/24 Arka Plan PC Madencisi aktif -> {MINER_DAEMON_STATE['miner_address']}")


@app.post("/mine/{miner_address}")
@app.post("/api/v1/faucet/{miner_address}")
def mine_block(miner_address: str, request: Request, device: str = ""):
    from core.wallet import validate_address
    from core.blockchain import TARGET_BLOCK_TIME
    if not validate_address(miner_address):
        raise HTTPException(400, f"Gecersiz UNIVA adresi: {miner_address}")

    if miner_address.startswith("univa"):
        MINER_DAEMON_STATE["miner_address"] = miner_address

    with MINER_LOCK:
        # 60 saniye hedef blok suresi korumasi (Mainnet Arz Disiplini)
        if blockchain.height >= 1:
            elapsed = time.time() - blockchain.last_block.timestamp
            if elapsed < TARGET_BLOCK_TIME:
                remaining = round(TARGET_BLOCK_TIME - elapsed, 1)
                return {
                    "status": "cooldown",
                    "wait_seconds": remaining,
                    "height": blockchain.height,
                    "message": f"Hedef blok suresi {TARGET_BLOCK_TIME}s. Sonraki blok icin {remaining}s kaldi.",
                }

        ua = (request.headers.get("user-agent") or "").lower()
        is_mobile = (device.lower() == "mobile") or any(k in ua for k in ("android", "iphone", "ipad", "mobile"))
        reward_override = 0.00001 if is_mobile else None

        block = blockchain.mine_pending_transactions(miner_address, reward_override=reward_override)
        if block is None:
            raise HTTPException(409, "Maksimum arza ulasildi veya madencilik basarisiz")

        _commit_mined_block(block)

    return {
        "status": "ok",
        "accepted": True,
        "block": block.to_dict(),
        "height": block.index,
        "balance": blockchain.get_balance(miner_address),
        "stats": blockchain.stats(),
    }


# ─── TELEMETRI & AĞ SAGLIGI ──────────────────────────────────────────────────

@app.post("/api/v1/telemetry/heartbeat")
async def telemetry_heartbeat(request: Request):
    data = await request.json() or {}
    device_id = data.get("device_id") or "anonymous_device"
    platform_str = data.get("platform", "Bilinmeyen")
    browser_str = data.get("browser", "")
    screen_str = data.get("screen", "")
    wallet_addr = data.get("wallet", "")
    latency = int(data.get("latency_ms", 15))

    ip = request.headers.get("CF-Connecting-IP") or \
         request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or \
         (request.client.host if request.client else "127.0.0.1")
    country = request.headers.get("CF-IPCountry") or "TR"
    city = request.headers.get("CF-IPCity") or "Istanbul"

    res = telemetry.record_heartbeat(
        device_id=device_id,
        ip=ip,
        platform=platform_str,
        browser=browser_str,
        screen=screen_str,
        wallet_address=wallet_addr,
        country=country,
        city=city,
        latency_ms=latency,
    )
    return res

@app.get("/api/v1/telemetry/nodes")
def telemetry_nodes():
    overview = telemetry.get_network_overview()
    overview["chain_height"] = blockchain.height
    overview["total_mined"] = blockchain.total_mined
    overview["difficulty"] = blockchain.difficulty
    overview["p2p_port"] = 5051
    return overview


# ─── NATIVE DEX ENDPOINTLERI ─────────────────────────────────────────────────

def _sync_dex_blockchain():
    if dex_engine.blockchain is not blockchain:
        dex_engine.blockchain = blockchain
        blockchain.dex_state = dex_engine
    return dex_engine


def _float_str_variants(raw_val: Any, fval: float) -> List[str]:
    candidates = []
    for item in (
        str(raw_val) if raw_val is not None else "",
        f"{fval:g}",
        str(int(fval)) if float(fval).is_integer() else str(fval),
        str(float(fval)),
        f"{fval:.8f}",
    ):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def _verify_dex_signature(
    user: str,
    pub_key: str,
    sig: str,
    candidate_messages: List[str],
    nonce: Optional[int] = None,
) -> None:
    from core.wallet import UnivaWallet, get_valid_sender_addresses, normalize_address

    if not user or not pub_key or not sig:
        raise HTTPException(401, "Takas/likidite islemi icin cuzdan adresi, public_key ve ECDSA imzasi gereklidir")
    if len(pub_key) != 128:
        raise HTTPException(401, "Gecersiz public_key uzunlugu (128 hex karakter gereklidir)")
    if sig in dex_engine.used_signatures:
        raise HTTPException(409, "DEX imzasi daha once kullanildi (replay engellendi)")
    if nonce is not None:
        if isinstance(nonce, bool) or not isinstance(nonce, int) or nonce < 0:
            raise HTTPException(400, "Gecersiz DEX nonce degeri")
        expected_nonce = dex_engine.get_user_nonce(user)
        if nonce != expected_nonce:
            raise HTTPException(409, f"Gecersiz DEX nonce: beklenen {expected_nonce}, gelen {nonce}")
    valid_addrs = get_valid_sender_addresses(pub_key)
    if normalize_address(user) not in valid_addrs:
        raise HTTPException(403, "Public key bu kullanici adresine ait degil")
    if not any(UnivaWallet.verify_signature(pub_key, m, sig) for m in candidate_messages):
        raise HTTPException(401, "Gecersiz DEX ECDSA imzasi")


def _active_dex_view():
    """Return (dex_instance, is_onchain_consensus) reflecting on-chain dex_* txs when present."""
    if hasattr(blockchain, "_has_onchain_dex_txs") and blockchain._has_onchain_dex_txs(include_pending=True):
        sim, _ = blockchain.replay_onchain_dex_state(include_pending=True)
        return sim, True
    return _sync_dex_blockchain(), False


@app.get("/api/v1/dex/pools")
def dex_pools():
    active_dex, is_consensus = _active_dex_view()
    res = [p.to_dict() for p in active_dex.pools.values()]
    return {
        "pools": res,
        "count": len(res),
        "state_root": active_dex.calculate_state_root(),
        "block_height": blockchain.height,
        "consensus_backed": True,
        "onchain_txs_active": is_consensus,
    }


@app.get("/api/v1/dex/balances/{address}")
def dex_balances(address: str):
    from core.wallet import normalize_address
    active_dex, is_consensus = _active_dex_view()
    norm = normalize_address(address)
    return {
        "address": address,
        "UNIVA": blockchain.get_balance(address, "UNIVA"),
        "uUSD": blockchain.get_balance(address, "uUSD"),
        "lp_balances": {
            pid: from_base_units(p.lp_balances.get(norm, 0))
            for pid, p in active_dex.pools.items()
        },
        "l1_nonce": blockchain._pending_nonce(address),
        "dex_nonce": dex_engine.get_user_nonce(address),
        "consensus_backed": True,
        "onchain_txs_active": is_consensus,
        "sandbox_balances": {
            k: from_base_units(v)
            for k, v in dex_engine.test_balances.get(norm, {}).items()
        },
        "sandbox_isolated": True,
    }


@app.post("/api/v1/dex/tx")
async def dex_submit_consensus_tx(request: Request):
    """Submit a client-signed on-chain consensus DEX transaction (dex_swap / dex_add_liquidity / dex_remove_liquidity)."""
    from core.transaction import DEX_TX_TYPES
    data = await request.json()
    tx = data.get("tx") if isinstance(data, dict) and "tx" in data else data
    if not isinstance(tx, dict):
        raise HTTPException(400, "Gecersiz DEX islem verisi")
    if tx.get("private_key") or (isinstance(data, dict) and data.get("private_key")):
        raise HTTPException(400, "Guvenlik Politikasi (P0): Ozel anahtar sunucuya gonderilemez")
    if tx.get("type") not in DEX_TX_TYPES:
        raise HTTPException(400, f"Desteklenmeyen DEX islem tipi: {tx.get('type')}")
    if not blockchain.add_transaction(tx):
        raise HTTPException(400, "L1 konsensüs DEX islemini reddetti (imza, nonce, bakiye veya slippage hatali)")
    try:
        from core.p2p import publish_tx_from_thread
        publish_tx_from_thread(tx)
    except Exception:
        pass
    return {
        "status": "in_mempool",
        "accepted": True,
        "finalized": False,
        "type": tx["type"],
        "tx_id": tx.get("tx_id"),
        "mempool_size": len(blockchain.pending_transactions),
        "settlement_note": "DEX islemi L1 mempool'a eklendi; blok kazildiginda tum dugumlerde kesinlesecektir.",
    }


@app.post("/api/v1/dex/quote")
async def dex_quote(request: Request):
    active_dex, _ = _active_dex_view()
    data = await request.json()
    asset_in = data.get("asset_in", "UNIVA")
    asset_out = data.get("asset_out", "uUSD")
    try:
        amount_in_float = float(data.get("amount_in", 0.0))
    except Exception:
        raise HTTPException(400, "Gecersiz miktar")
    if amount_in_float <= 0:
        raise HTTPException(400, "Miktar pozitif olmalidir")
    pool = active_dex.get_pool(asset_in, asset_out)
    if not pool:
        raise HTTPException(404, "Havuz bulunamadi")
    try:
        amt_in_base = to_base_units(amount_in_float)
        details = active_dex.get_quote_details(asset_in, asset_out, amt_in_base)
        return {
            "pool_id": details["pool_id"],
            "asset_in": details["asset_in"],
            "asset_out": details["asset_out"],
            "amount_in": amount_in_float,
            "amount_out": from_base_units(details["amount_out"]),
            "fee": from_base_units(details["fee"]),
            "fee_paid": from_base_units(details["fee"]),
            "fee_bps": details["fee_bps"],
            "spot_price_before": details["spot_price_before"],
            "spot_price_after": details["spot_price_after"],
            "effective_price": details["effective_price"],
            "price_impact_pct": details["price_impact_pct"],
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/v1/dex/swap")
async def dex_swap(request: Request):
    _sync_dex_blockchain()
    data = await request.json()
    user = (data.get("user") or "").strip()
    priv_key = (data.get("private_key") or "").strip()
    pub_key = (data.get("public_key") or "").strip()
    sig = (data.get("signature") or "").strip()
    asset_in = (data.get("asset_in") or "UNIVA").strip()
    asset_out = (data.get("asset_out") or "uUSD").strip()
    nonce = data.get("nonce")
    max_slippage_bps = data.get("max_slippage_bps")

    # Guvenlik Politikasi (P0/P4): Ozel anahtar asla sunucuya gonderilemez; istemci imzasi zorunludur
    if priv_key:
        raise HTTPException(
            400,
            "Guvenlik Politikasi (P0): DEX takasinda ozel anahtar sunucuya gonderilemez; istemci imzasi gereklidir.",
        )

    try:
        amount_in_float = float(data.get("amount_in", 0.0))
        min_out_float = float(data.get("min_out", 0.0))
    except Exception:
        raise HTTPException(400, "Gecersiz takas miktari")

    if not user or amount_in_float <= 0 or min_out_float < 0:
        raise HTTPException(400, "Gecersiz istek")

    amt_variants = _float_str_variants(data.get("amount_in"), amount_in_float)
    min_variants = _float_str_variants(data.get("min_out", 0.0), min_out_float)
    cand_msgs: List[str] = []
    for a_s in amt_variants:
        if nonce is not None:
            for m_s in min_variants:
                cand_msgs.append(f"UNIVA_DEX|swap|{user}|{asset_in}|{asset_out}|{a_s}|{m_s}|{nonce}")
            cand_msgs.append(f"UNIVA_DEX|swap|{user}|{asset_in}|{asset_out}|{a_s}|{nonce}")
        else:
            cand_msgs.append(f"UNIVA_DEX|{user}|{asset_in}|{asset_out}|{a_s}")
            for m_s in min_variants:
                cand_msgs.append(f"UNIVA_DEX|swap|{user}|{asset_in}|{asset_out}|{a_s}|{m_s}")

    _verify_dex_signature(user, pub_key, sig, cand_msgs, nonce=nonce)

    try:
        amt_in = to_base_units(amount_in_float)
        min_out = to_base_units(min_out_float)
        if max_slippage_bps is not None:
            quote = dex_engine.get_quote_details(asset_in, asset_out, amt_in)
            if quote["price_impact_pct"] * 100.0 > float(max_slippage_bps):
                raise ValueError(
                    f"Slippage/fiyat etkisi ({quote['price_impact_pct']}%) izin verilen limiti asiyor"
                )
        out_base = dex_engine.swap(user, asset_in, asset_out, amt_in, min_out)
        out_float = from_base_units(out_base)
        op = dex_engine.record_signed_operation(
            "swap",
            user,
            pub_key,
            sig,
            {
                "asset_in": asset_in,
                "asset_out": asset_out,
                "amount_in": amount_in_float,
                "amount_out": out_float,
                "min_out": min_out_float,
            },
            nonce=nonce,
        )
        return {
            "status": "success",
            "user": user,
            "asset_in": asset_in,
            "asset_out": asset_out,
            "amount_in": amount_in_float,
            "amount_out": out_float,
            "swapped_in": amount_in_float,
            "received_out": out_float,
            "op_id": op["op_id"],
            "state_root": dex_engine.calculate_state_root(),
            "dex_nonce": dex_engine.get_user_nonce(user),
            "univa_balance": blockchain.get_balance(user, "UNIVA"),
            "uusd_balance": from_base_units(dex_engine.get_balance(user, "uUSD")),
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/v1/dex/liquidity/add")
async def dex_add_liquidity(request: Request):
    _sync_dex_blockchain()
    data = await request.json()
    user = (data.get("user") or "").strip()
    priv_key = (data.get("private_key") or "").strip()
    pub_key = (data.get("public_key") or "").strip()
    sig = (data.get("signature") or "").strip()
    asset_a = (data.get("asset_a") or "UNIVA").strip()
    asset_b = (data.get("asset_b") or "uUSD").strip()
    nonce = data.get("nonce")

    if priv_key:
        raise HTTPException(400, "Guvenlik Politikasi (P0): Likidite isleminde ozel anahtar gonderilemez")

    try:
        amount_a_float = float(data.get("amount_a", 0.0))
        amount_b_float = float(data.get("amount_b", 0.0))
    except Exception:
        raise HTTPException(400, "Gecersiz likidite miktari")

    if not user or amount_a_float <= 0 or amount_b_float <= 0:
        raise HTTPException(400, "Gecersiz likidite parametreleri")

    a_vars = _float_str_variants(data.get("amount_a"), amount_a_float)
    b_vars = _float_str_variants(data.get("amount_b"), amount_b_float)
    cand_msgs: List[str] = []
    for a_s in a_vars:
        for b_s in b_vars:
            if nonce is not None:
                cand_msgs.append(f"UNIVA_DEX|add_liquidity|{user}|{asset_a}|{asset_b}|{a_s}|{b_s}|{nonce}")
            else:
                cand_msgs.append(f"UNIVA_DEX|add_liquidity|{user}|{asset_a}|{asset_b}|{a_s}|{b_s}")

    _verify_dex_signature(user, pub_key, sig, cand_msgs, nonce=nonce)

    try:
        lp_minted = dex_engine.add_liquidity(
            user, asset_a, asset_b, to_base_units(amount_a_float), to_base_units(amount_b_float)
        )
        op = dex_engine.record_signed_operation(
            "add_liquidity",
            user,
            pub_key,
            sig,
            {
                "asset_a": asset_a,
                "asset_b": asset_b,
                "amount_a": amount_a_float,
                "amount_b": amount_b_float,
                "lp_minted": from_base_units(lp_minted),
            },
            nonce=nonce,
        )
        return {
            "status": "success",
            "user": user,
            "lp_minted": from_base_units(lp_minted),
            "op_id": op["op_id"],
            "state_root": dex_engine.calculate_state_root(),
            "dex_nonce": dex_engine.get_user_nonce(user),
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/v1/dex/liquidity/remove")
async def dex_remove_liquidity(request: Request):
    _sync_dex_blockchain()
    data = await request.json()
    user = (data.get("user") or "").strip()
    priv_key = (data.get("private_key") or "").strip()
    pub_key = (data.get("public_key") or "").strip()
    sig = (data.get("signature") or "").strip()
    asset_a = (data.get("asset_a") or "UNIVA").strip()
    asset_b = (data.get("asset_b") or "uUSD").strip()
    nonce = data.get("nonce")

    if priv_key:
        raise HTTPException(400, "Guvenlik Politikasi (P0): Likidite cekiminde ozel anahtar gonderilemez")

    try:
        lp_float = float(data.get("lp_amount", 0.0))
    except Exception:
        raise HTTPException(400, "Gecersiz LP miktari")

    if not user or lp_float <= 0:
        raise HTTPException(400, "Gecersiz LP cekim parametreleri")

    lp_vars = _float_str_variants(data.get("lp_amount"), lp_float)
    cand_msgs: List[str] = []
    for lp_s in lp_vars:
        if nonce is not None:
            cand_msgs.append(f"UNIVA_DEX|remove_liquidity|{user}|{asset_a}|{asset_b}|{lp_s}|{nonce}")
        else:
            cand_msgs.append(f"UNIVA_DEX|remove_liquidity|{user}|{asset_a}|{asset_b}|{lp_s}")

    _verify_dex_signature(user, pub_key, sig, cand_msgs, nonce=nonce)

    try:
        amt_a_base, amt_b_base = dex_engine.remove_liquidity(
            user, asset_a, asset_b, to_base_units(lp_float)
        )
        op = dex_engine.record_signed_operation(
            "remove_liquidity",
            user,
            pub_key,
            sig,
            {
                "asset_a": asset_a,
                "asset_b": asset_b,
                "lp_burned": lp_float,
                "amount_a": from_base_units(amt_a_base),
                "amount_b": from_base_units(amt_b_base),
            },
            nonce=nonce,
        )
        return {
            "status": "success",
            "user": user,
            "asset_a": asset_a,
            "asset_b": asset_b,
            "amount_a": from_base_units(amt_a_base),
            "amount_b": from_base_units(amt_b_base),
            "op_id": op["op_id"],
            "state_root": dex_engine.calculate_state_root(),
            "dex_nonce": dex_engine.get_user_nonce(user),
        }
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── OFFLINE PAY PROTOKOLU (P5: QR + NFC + BLE + REZERVASYON) ───────────────

@app.get("/api/v1/offline/reservations/{address}")
def offline_list_reservations(address: str):
    return offline_mgr.list_reservations(blockchain, address)


@app.post("/api/v1/offline/reserve")
async def offline_reserve(request: Request):
    data = await request.json()
    if data.get("private_key"):
        raise HTTPException(400, "Guvenlik Politikasi (P0): Rezervasyon isleminde ozel anahtar sunucuya gonderilemez")
    owner = (data.get("address") or data.get("user") or "").strip()
    pub_key = (data.get("public_key") or "").strip()
    sig = (data.get("signature") or "").strip()
    nonce = data.get("nonce")
    try:
        amount = float(data.get("amount", 0.0))
        ttl_seconds = int(data.get("ttl_seconds", DEFAULT_VOUCHER_TTL))
    except Exception:
        raise HTTPException(400, "Gecersiz rezervasyon tutari veya sure")
    try:
        rec = offline_mgr.create_reservation(
            blockchain=blockchain,
            owner=owner,
            amount=amount,
            ttl_seconds=ttl_seconds,
            public_key=pub_key,
            signature=sig,
            nonce=nonce,
            raw_amount=data.get("amount"),
        )
        return {
            "status": "ok",
            "reservation": rec,
            "offline_nonce": offline_mgr.get_user_nonce(owner),
            "unreserved_spendable": offline_mgr.get_unreserved_spendable(blockchain, owner),
        }
    except OfflinePayError as oe:
        raise HTTPException(oe.status_code, str(oe))
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/v1/offline/release")
async def offline_release(request: Request):
    data = await request.json()
    if data.get("private_key"):
        raise HTTPException(400, "Guvenlik Politikasi (P0): Rezervasyon iptalinde ozel anahtar gonderilemez")
    owner = (data.get("address") or data.get("user") or "").strip()
    res_id = (data.get("reservation_id") or "").strip()
    pub_key = (data.get("public_key") or "").strip()
    sig = (data.get("signature") or "").strip()
    nonce = data.get("nonce")
    try:
        res = offline_mgr.release_reservation(
            owner=owner,
            reservation_id=res_id,
            public_key=pub_key,
            signature=sig,
            nonce=nonce,
        )
        return {
            "status": "ok",
            **res,
            "unreserved_spendable": offline_mgr.get_unreserved_spendable(blockchain, owner),
        }
    except OfflinePayError as oe:
        raise HTTPException(oe.status_code, str(oe))
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/v1/offline/submit")
async def offline_submit_voucher(request: Request):
    data = await request.json()
    if data.get("private_key"):
        raise HTTPException(400, "Guvenlik Politikasi (P0): Cevrimdisi fis gonderiminde ozel anahtar kabul edilmez")
    voucher_payload = data.get("voucher") or data.get("token") or data.get("tx") or data
    transport = data.get("transport")
    try:
        rec = offline_mgr.submit_voucher(
            blockchain=blockchain,
            voucher_or_token=voucher_payload,
            transport=transport,
        )
        # Reconstruct signed tx to broadcast to P2P mempool peers
        try:
            from core.offline_pay import decode_voucher
            from core.p2p import publish_tx_from_thread
            decoded = decode_voucher(voucher_payload)
            publish_tx_from_thread(decoded["tx"])
        except Exception:
            pass
        return {
            "status": "in_mempool",
            "accepted": True,
            "finalized": False,
            "voucher": rec,
            "tx_id": rec["tx_id"],
            "mempool_size": len(blockchain.pending_transactions),
        }
    except OfflinePayError as oe:
        raise HTTPException(oe.status_code, str(oe))
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/v1/offline/status/{tx_id}")
def offline_voucher_status(tx_id: str):
    return offline_mgr.get_voucher_status(blockchain, tx_id)


# ─── INTEROPERABILITY & PROOFS (P6) ──────────────────────────────────────────

def _rpc_capabilities() -> dict:
    return {
        "network": "UNIVA-L1",
        "consensus": "SHA-256 Proof-of-Work (BIP-113 MTP)",
        "chain_id_dec": UNIVA_CHAIN_ID_DEC,
        "chain_id_hex": UNIVA_CHAIN_ID_HEX,
        "evm_compatibility": {
            "mode": "mirror_address_and_read_rpc",
            "evm_mirror_addresses": True,
            "evm_read_rpc": True,
            "evm_bytecode_vm": False,
            "rlp_eip1559_execution": False,
            "note": (
                "UNIVA is an independent SHA-256 PoW Layer-1 with 0x secp256k1 mirror addresses "
                "and standard Web3 read/wallet JSON-RPC methods (Chain ID 210001). Solidity bytecode "
                "execution and raw Ethereum RLP transactions are NOT executed; native signed UNIVA "
                "transactions are submitted via /tx, sendrawtransaction, or hex-encoded UNIVA JSON."
            ),
        },
        "supported_eth_methods": [
            "eth_chainId", "net_version", "web3_clientVersion", "eth_syncing",
            "eth_accounts", "eth_blockNumber", "eth_getBalance", "eth_gasPrice",
            "eth_maxPriorityFeePerGas", "eth_feeHistory", "eth_estimateGas",
            "eth_call", "eth_getCode", "eth_getStorageAt", "eth_getTransactionCount",
            "eth_getTransactionByHash", "eth_getTransactionReceipt",
            "eth_getBlockByNumber", "eth_getBlockByHash", "eth_sendRawTransaction",
        ],
        "supported_bitcoin_methods": [
            "getblockchaininfo", "getblockcount", "getbestblockhash", "getblockhash",
            "getblock", "getbalance", "getnetworkinfo", "getmininginfo", "sendrawtransaction",
        ],
        "supported_univa_methods": ["univa_getCapabilities"],
        "multichain_readers": ["BTC", "ETH", "BNB", "SOL", "TON", "TRX", "XRP", "LTC"],
        "jsonrpc_batch_supported": True,
    }


@app.get("/api/v1/interop/chains")
def interop_chains():
    overview = MultiChainReader.get_all_chains_overview()
    return {"chains": overview, "count": len(overview), "univa_height": blockchain.height}


@app.get("/api/v1/interop/proof/{tx_id}")
def interop_proof(tx_id: str):
    proof = UniversalProofEngine.generate_proof_for_tx(blockchain, tx_id)
    if not proof:
        raise HTTPException(404, "Islem bulunamadi")
    return proof


@app.post("/api/v1/interop/verify-proof")
async def interop_verify_proof(request: Request):
    data = await request.json()
    return UniversalProofEngine.verify_proof_detailed(data)


@app.get("/api/v1/rpc/capabilities")
def rpc_capabilities_endpoint():
    return _rpc_capabilities()


# ─── BITCOIN CORE COMPATIBLE JSON-RPC 2.0 ────────────────────────────────────

# ─── UNIVA HİBRİT EVM & BITCOIN JSON-RPC ADAPTÖRÜ ─────────────────────────────
# MetaMask, Trust Wallet ve Web3 cüzdanları için standart EVM okuma/cüzdan metodları
# ve borsa/analiz için Bitcoin Core metodları (getblockchaininfo, ...) desteklenir.
UNIVA_CHAIN_ID_DEC = NET_CFG["chain_id_dec"]
UNIVA_CHAIN_ID_HEX = NET_CFG["chain_id_hex"]


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _process_rpc_call(body: dict) -> dict:
    from decimal import Decimal

    method = body.get("method", "")
    params = body.get("params") or []
    req_id = body.get("id", 1)

    if not isinstance(method, str) or not method:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32600, "message": "Invalid Request: missing method"}}

    try:
        # === 1. METAMASK / TRUST WALLET / EVM WEB3 METODLARI ===
        if method == "univa_getCapabilities":
            result = _rpc_capabilities()
        elif method == "eth_chainId":
            result = UNIVA_CHAIN_ID_HEX
        elif method == "net_version":
            result = str(UNIVA_CHAIN_ID_DEC)
        elif method == "web3_clientVersion":
            result = "UNIVA-Core/v4.0.0"
        elif method == "eth_syncing":
            result = False
        elif method == "eth_accounts":
            result = []
        elif method == "eth_blockNumber":
            result = hex(blockchain.height)
        elif method == "eth_getBalance":
            if not params:
                raise _RpcError(-32602, "eth_getBalance requires address parameter")
            addr = str(params[0])
            bal = blockchain.get_balance(addr)
            wei_val = int((Decimal(str(bal)) * Decimal(10**18)).to_integral_value())
            result = hex(max(0, wei_val))
        elif method in ("eth_gasPrice", "eth_maxPriorityFeePerGas"):
            result = "0x3b9aca00" # 1 Gwei
        elif method == "eth_feeHistory":
            block_count = 4
            try:
                if params and isinstance(params[0], str):
                    block_count = max(1, min(20, int(params[0], 16)))
                elif params and isinstance(params[0], int):
                    block_count = max(1, min(20, params[0]))
            except Exception:
                block_count = 4
            oldest = max(0, blockchain.height - block_count + 1)
            result = {
                "oldestBlock": hex(oldest),
                "baseFeePerGas": ["0x3b9aca00"] * (block_count + 1),
                "gasUsedRatio": [0.1] * block_count,
                "reward": [["0x3b9aca00"] for _ in range(block_count)],
            }
        elif method == "eth_estimateGas":
            result = "0x5208"     # 21000 standart transfer gazı
        elif method in ("eth_call", "eth_getCode", "eth_getStorageAt"):
            result = "0x"
        elif method == "eth_getTransactionReceipt":
            tx_h = str(params[0]).lower().replace("0x", "") if params else ""
            found_blk = None
            found_tx = None
            found_tx_idx = 0
            for blk in reversed(blockchain.chain):
                for idx_t, t in enumerate(blk.transactions):
                    tid = str(t.get("tx_id") or "").lower().replace("0x", "")
                    if tid and tid == tx_h:
                        found_blk = blk
                        found_tx = t
                        found_tx_idx = idx_t
                        break
                if found_blk:
                    break
            if found_blk:
                result = {
                    "transactionHash": "0x" + tx_h,
                    "transactionIndex": hex(found_tx_idx),
                    "blockHash": found_blk.hash if found_blk.hash.startswith("0x") else "0x" + found_blk.hash,
                    "blockNumber": hex(found_blk.index),
                    "from": str(found_tx.get("from", "0x0000000000000000000000000000000000000000")),
                    "to": str(found_tx.get("to", "0x0000000000000000000000000000000000000000")),
                    "cumulativeGasUsed": "0x5208",
                    "gasUsed": "0x5208",
                    "contractAddress": None,
                    "logs": [],
                    "logsBloom": "0x" + "0" * 512,
                    "status": "0x1",
                    "effectiveGasPrice": "0x3b9aca00",
                    "type": "0x2",
                }
            else:
                result = None
        elif method == "eth_getTransactionByHash":
            tx_h = str(params[0]).lower().replace("0x", "") if params else ""
            found_blk = None
            found_tx = None
            found_tx_idx = 0
            for blk in reversed(blockchain.chain):
                for idx_t, t in enumerate(blk.transactions):
                    tid = str(t.get("tx_id") or "").lower().replace("0x", "")
                    if tid and tid == tx_h:
                        found_blk = blk
                        found_tx = t
                        found_tx_idx = idx_t
                        break
                if found_blk:
                    break
            if found_blk:
                result = {
                    "hash": "0x" + tx_h,
                    "nonce": hex(int(found_tx.get("nonce", 0))),
                    "blockHash": found_blk.hash if found_blk.hash.startswith("0x") else "0x" + found_blk.hash,
                    "blockNumber": hex(found_blk.index),
                    "transactionIndex": hex(found_tx_idx),
                    "from": str(found_tx.get("from", "0x0000000000000000000000000000000000000000")),
                    "to": str(found_tx.get("to", "0x0000000000000000000000000000000000000000")),
                    "value": hex(int((Decimal(str(found_tx.get("amount", 0.0))) * Decimal(10**18)).to_integral_value())),
                    "gas": "0x5208",
                    "gasPrice": "0x3b9aca00",
                    "input": "0x",
                }
            else:
                result = None
        elif method == "eth_getTransactionCount":
            if not params:
                raise _RpcError(-32602, "eth_getTransactionCount requires address parameter")
            addr = str(params[0])
            block_tag = str(params[1]).lower() if len(params) > 1 else "latest"
            nonce = blockchain._pending_nonce(addr) if block_tag == "pending" else blockchain._account_nonce(addr)
            result = hex(nonce)
        elif method in ("eth_getBlockByNumber", "eth_getBlockByHash"):
            tag = params[0] if params else "latest"
            blk = None
            if method == "eth_getBlockByNumber":
                if tag in ("latest", "pending", "safe", "finalized"):
                    blk = blockchain.last_block
                elif tag == "earliest":
                    blk = blockchain.chain[0]
                else:
                    idx = int(str(tag), 16) if str(tag).startswith("0x") else int(tag)
                    if 0 <= idx <= blockchain.height:
                        blk = blockchain.chain[idx]
            else:
                target_h = str(tag).lower().replace("0x", "")
                blk = next((b for b in blockchain.chain if b.hash.lower().replace("0x", "") == target_h), None)
            if blk is None:
                result = None
            else:
                result = {
                    "number": hex(blk.index),
                    "hash": blk.hash if blk.hash.startswith("0x") else "0x" + blk.hash,
                    "parentHash": blk.previous_hash if blk.previous_hash.startswith("0x") else "0x" + blk.previous_hash,
                    "nonce": hex(blk.nonce)[2:].zfill(16),
                    "sha3Uncles": "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347",
                    "logsBloom": "0x" + "0" * 512,
                    "transactionsRoot": "0x" + blk.merkle_root,
                    "stateRoot": "0x" + blk.merkle_root,
                    "receiptsRoot": "0x" + blk.merkle_root,
                    "miner": "0x" + hashlib.sha256(blk.miner_address.encode()).hexdigest()[:40],
                    "difficulty": hex(blk.difficulty),
                    "totalDifficulty": hex(blockchain.calculate_chain_work(blockchain.chain[: blk.index + 1])),
                    "extraData": "0x554e495641", # 'UNIVA'
                    "size": hex(len(json.dumps(blk.to_dict()).encode("utf-8"))),
                    "gasLimit": "0x1c9c380", # 30,000,000
                    "gasUsed": "0x5208",
                    "baseFeePerGas": "0x3b9aca00",
                    "timestamp": hex(int(blk.timestamp)),
                    "transactions": [
                        ("0x" + tx["tx_id"]) if not str(tx["tx_id"]).startswith("0x") else tx["tx_id"]
                        for tx in blk.transactions if tx.get("tx_id")
                    ],
                    "uncles": [],
                }
        elif method == "eth_sendRawTransaction":
            # P6 Honest Execution Guard: NEVER return a fake hash for unverified/unexecuted RLP bytes!
            if not params:
                raise _RpcError(-32602, "eth_sendRawTransaction requires raw transaction payload")
            raw_tx = params[0]
            parsed_tx = None
            if isinstance(raw_tx, dict):
                parsed_tx = raw_tx
            elif isinstance(raw_tx, str):
                cleaned = raw_tx.strip()
                if cleaned.startswith("{"):
                    try:
                        parsed_tx = json.loads(cleaned)
                    except Exception:
                        parsed_tx = None
                elif cleaned.startswith("0x") or cleaned.startswith("0X"):
                    try:
                        decoded_utf8 = bytes.fromhex(cleaned[2:]).decode("utf-8")
                        if decoded_utf8.startswith("{"):
                            parsed_tx = json.loads(decoded_utf8)
                    except Exception:
                        parsed_tx = None
            if not isinstance(parsed_tx, dict):
                raise _RpcError(
                    -32000,
                    "UNIVA is a native SHA-256 PoW Layer-1 (not an EVM RLP execution VM). "
                    "Submit a secp256k1-signed UNIVA transaction JSON (or hex-encoded UNIVA JSON) via /tx or sendrawtransaction.",
                )
            if not blockchain.add_transaction(parsed_tx):
                raise _RpcError(-32000, "UNIVA L1 mempool rejected transaction (invalid signature, nonce, or balance)")
            try:
                from core.p2p import publish_tx_from_thread
                publish_tx_from_thread(parsed_tx)
            except Exception:
                pass
            tid = str(parsed_tx.get("tx_id") or "")
            result = tid if tid.startswith("0x") else ("0x" + tid)

        # === 2. BITCOIN CORE & NATIVE RPC METODLARI ===
        elif method == "getblockchaininfo":
            result = {
                "chain": "main",
                "blocks": blockchain.height,
                "headers": blockchain.height,
                "bestblockhash": blockchain.last_block.hash,
                "difficulty": blockchain.difficulty,
                "mediantime": int(blockchain.get_median_time_past(11)),
                "verificationprogress": 1.0,
                "chainwork": hex(blockchain.calculate_chain_work(blockchain.chain)),
            }
        elif method == "getblockcount":
            result = blockchain.height
        elif method == "getbestblockhash":
            result = blockchain.last_block.hash
        elif method == "getblockhash":
            if not params:
                raise _RpcError(-32602, "getblockhash requires block height")
            h = int(params[0])
            if not (0 <= h <= blockchain.height):
                raise _RpcError(-32602, f"Block height out of range: {h}")
            result = blockchain.chain[h].hash
        elif method == "getblock":
            if not params:
                raise _RpcError(-32602, "getblock requires block height or hash")
            if isinstance(params[0], int) or str(params[0]).isdigit():
                h = int(params[0])
                if not (0 <= h <= blockchain.height):
                    raise _RpcError(-32602, f"Block height out of range: {h}")
                result = blockchain.chain[h].to_dict()
            else:
                target_h = str(params[0]).lower().replace("0x", "")
                blk = next((b for b in blockchain.chain if b.hash.lower().replace("0x", "") == target_h), None)
                if blk is None:
                    raise _RpcError(-32602, "Block not found")
                result = blk.to_dict()
        elif method == "getbalance":
            if not params:
                raise _RpcError(-32602, "getbalance requires address")
            result = blockchain.get_balance(str(params[0]))
        elif method == "getnetworkinfo":
            result = {"network": "UNIVA-L1", "version": "4.0.0", "connections": max(1, blockchain.peer_count)}
        elif method == "getmininginfo":
            result = blockchain.stats()
        elif method == "sendrawtransaction":
            if not params or not isinstance(params[0], dict):
                raise _RpcError(-32602, "sendrawtransaction requires signed UNIVA tx object")
            tx = params[0]
            if not blockchain.add_transaction(tx):
                raise _RpcError(-32000, "Transaction rejected by L1 consensus")
            try:
                from core.p2p import publish_tx_from_thread
                publish_tx_from_thread(tx)
            except Exception:
                pass
            result = tx.get("tx_id")
        else:
            raise _RpcError(-32601, f"Method not found: {method}")

        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except _RpcError as re_err:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": re_err.code, "message": re_err.message}}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": str(exc)}}


_RATE_LIMIT_LOG: Dict[str, List[float]] = {}

@app.middleware("http")
async def security_headers_and_rate_limit(request: Request, call_next):
    client_ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    path = request.url.path
    now = time.time()

    # Brute-force & DDoS rate limiting per IP
    if path.startswith("/api/v1/mystery/solve"):
        hist = [t for t in _RATE_LIMIT_LOG.get("mys:" + client_ip, []) if now - t < 60.0]
        if len(hist) >= 8:
            return JSONResponse({"detail": "Cok fazla gizem denemesi. 1 dakika bekleyin."}, status_code=429)
        hist.append(now)
        _RATE_LIMIT_LOG["mys:" + client_ip] = hist
    elif path.startswith("/tx") or path.startswith("/mine") or path.startswith("/api/v1/faucet"):
        hist = [t for t in _RATE_LIMIT_LOG.get("write:" + client_ip, []) if now - t < 60.0]
        if len(hist) >= 45:
            return JSONResponse({"detail": "Rate limit asildi. Lutfen yavaslayin."}, status_code=429)
        hist.append(now)
        _RATE_LIMIT_LOG["write:" + client_ip] = hist

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


# ─── MYSTERY PROTOCOL (100,000-BLOCK EPOCH PUZZLES) ─────────────────────────

MYSTERY_STATE_FILE = os.path.join(BASE_DIR, "univa_mystery.json")
MYSTERY_REWARD_UNIVA = 50.0
MYSTERY_EPOCHS = [
    {
        "epoch": 1,
        "target_block": 100_000,
        "riddle_tr": "Adım bir gölge, yüzüm hiç görülmedi; dokuz sayfalık bir ateş yaktım, tüm kilitleri eritip. Zincirlerin ilk halkasında imzam durur hâlâ, ama hazinem hiç kıpırdamadı — ben kimim?",
        "riddle_en": "My name is a shadow, my face was never seen; I lit a nine-page fire that melted every lock. My signature still stands on the first link of the chain, yet my treasure never moved — who am I?",
        "hashes": {
            "8917bb6228ae75cf421abffba92553416006195ec32be7ed6d25aacdfa0e216a",
            "a525791edad3b400eda01b454dcb258882252b3115fc8c43bb0e8e32563f7ce9",
            "a39fd2091f2fbee051c9fcc09aabd33dd4c7c84c76e59b02dcec0a489f8c4774",
        },
    },
    {
        "epoch": 2,
        "target_block": 200_000,
        "riddle_tr": "Karanlık derinlikte küçük bir kum tanesiydim önce; sabırla ördüm kendimi, kat kat parladım sessizce. Sedef bir zırhın içinde saklı beyaz bir sır gibiyim, denizin kalbinden doğan en nadir hazineyim — ben neyim?",
        "riddle_en": "In dark depths I began as a tiny grain of sand; patiently I wove myself, shining layer by layer in silence. Like a white secret inside a mother-of-pearl armor, the rarest treasure born from the sea's heart — what am I?",
        "hashes": {"2a6b507966207bd9e6a814c92a08efafeb85f1d095c19fd9cd726a0f72510c3c"},
    },
    {
        "epoch": 3,
        "target_block": 300_000,
        "riddle_tr": "Gözle görünmem, elle tutulmam, sesim de çıkmaz; ama bir esintiyle yürür, unutulmuş anıları uyandırırım. Bazen bir çiçeğin nefesiyim, bazen özlenen bir izin; ardında bıraktığım görünmez imzamla — ben neyim?",
        "riddle_en": "Unseen by eye, untouched by hand, silent as air; yet I travel on a breeze and awaken forgotten memories. Sometimes a flower's breath, sometimes a longed-for trace; an invisible signature left behind — what am I?",
        "hashes": {"8e3f59a9d4b7387811a2cbb48b553ab09918274ccc352682db2b0de499e721b7"},
    },
    {
        "epoch": 4,
        "target_block": 400_000,
        "riddle_tr": "Kanatlarım görünmez ama gölgen gibi yanındayım; en karanlık anda bile yolunu sessizce aydınlatırım. Sadece gökyüzünden değil, kalbinin en saf yerinden gelirim; fısıltıyla söylenen en koruyucu hitap benim — ben kimim?",
        "riddle_en": "My wings are unseen yet I walk beside you like a shadow; even in the darkest hour I quietly light your path. Not only from the sky, I come from the purest place in your heart; the most protective whispered name — who am I?",
        "hashes": {"e3ed0c087dab42cca41b32e5e16eac3551a544195b2b011db5d22e3fcbe6975c"},
    },
    {
        "epoch": 5,
        "target_block": 500_000,
        "riddle_tr": "Ne bir ülkeye bağlıyım ne de tek bir sınıra; Taban31 izimle, 0x aynamla her ağı bağlarım tek çatıya. 21 milyonluk sınırda egemen bir ışık gibi doğdum; tek bir ağ, sınırsız olanak — benim adım ne?",
        "riddle_en": "Bound to no nation and no single border; with my Base31 mark and 0x mirror I unite every chain under one roof. Born like a sovereign light within a 21 million cap; one network, infinite possibilities — what is my name?",
        "hashes": {"5344b5a3180ba4f5a1d851409c50c4360ec8f718e010a8f49d65e390a8a74526"},
    },
]

def _load_mystery_state() -> dict:
    if os.path.exists(MYSTERY_STATE_FILE):
        try:
            with open(MYSTERY_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("winners"), list):
                return data
        except Exception:
            pass
    return {"winners": []}

def _save_mystery_state(state: dict):
    with open(MYSTERY_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def _norm_mystery_answer(ans: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKC", (ans or "").strip().lower())
    for a, b in (("ı", "i"), ("İ", "i"), ("i̇", "i"), ("ğ", "g"), ("ş", "s"), ("ö", "o"), ("ü", "u"), ("ç", "c")):
        s = s.replace(a, b)
    return " ".join(s.split())

def _get_active_or_next_mystery(height: int, state: dict):
    solved_epochs = {w.get("epoch") for w in state.get("winners", [])}
    for ep in MYSTERY_EPOCHS:
        if ep["epoch"] not in solved_epochs:
            return ep
    return None

@app.get("/api/v1/mystery/status")
def mystery_status():
    state = _load_mystery_state()
    h = blockchain.height
    ep = _get_active_or_next_mystery(h, state)
    if not ep:
        return {
            "status": "completed",
            "height": h,
            "reward": MYSTERY_REWARD_UNIVA,
            "unlocked": False,
            "winners": state.get("winners", []),
        }
    unlocked = h >= ep["target_block"]
    return {
        "status": "ok",
        "height": h,
        "epoch": ep["epoch"],
        "target_block": ep["target_block"],
        "remaining_blocks": max(0, ep["target_block"] - h),
        "reward": MYSTERY_REWARD_UNIVA,
        "unlocked": unlocked,
        "riddle_tr": ep["riddle_tr"] if unlocked else None,
        "riddle_en": ep["riddle_en"] if unlocked else None,
        "winners": state.get("winners", []),
    }

@app.post("/api/v1/mystery/solve")
async def mystery_solve(request: Request):
    from core.wallet import UnivaWallet, validate_address
    data = await request.json()
    addr = (data.get("address") or "").strip()
    answer = (data.get("answer") or "").strip()
    if not validate_address(addr):
        raise HTTPException(400, "Gecersiz UNIVA odul adresi.")
    if not answer:
        raise HTTPException(400, "Lutfen bir cevap girin.")

    state = _load_mystery_state()
    ep = _get_active_or_next_mystery(blockchain.height, state)
    if not ep:
        raise HTTPException(400, "Tum tanimli gizem donemleri zaten cozuldu.")
    if blockchain.height < ep["target_block"]:
        raise HTTPException(403, f"Gizem kapisi henuz acilmadi! Hedef blok: #{ep['target_block']}")

    guess_hash = hashlib.sha256(f"UNIVA_MYSTERY_V1|{ep['epoch']}|{_norm_mystery_answer(answer)}".encode("utf-8")).hexdigest()
    if guess_hash not in ep["hashes"]:
        raise HTTPException(400, "Yanlis cevap! Gizem henuz cozulmedi.")

    # Odulu Master Hazine Cuzdanindan (univa_wallet.json) gercek zincir-ici transferle gonder
    wallet_file = os.path.join(BASE_DIR, "univa_wallet.json")
    if not os.path.exists(wallet_file):
        raise HTTPException(500, "Hazine cuzdani bulunamadi.")
    treasury = UnivaWallet.load(wallet_file)
    try:
        tx = blockchain.create_transaction(treasury, addr, MYSTERY_REWARD_UNIVA, 0.0, from_address=treasury.address)
    except Exception as exc:
        raise HTTPException(500, f"Odul transferi olusturulamadi: {exc}")

    if not blockchain.add_transaction(tx):
        raise HTTPException(500, "Odul islemi mempool tarafindan reddedildi (Hazine bakiyesini kontrol edin).")

    try:
        from core.p2p import publish_tx_from_thread
        publish_tx_from_thread(tx)
    except Exception:
        pass

    record = {
        "epoch": ep["epoch"],
        "block_target": ep["target_block"],
        "solved_at_height": blockchain.height,
        "winner": addr,
        "reward": MYSTERY_REWARD_UNIVA,
        "tx_id": tx.get("tx_id"),
        "timestamp": int(time.time()),
    }
    state.setdefault("winners", []).append(record)
    _save_mystery_state(state)
    return {"status": "ok", "message": "Tebrikler! Gizem cozuldu ve 50.0 UNIVA odulunuz gonderildi!", **record}


# ─── MULTICHAIN LIVE STATE READER (BTC, ETH, BNB, SOL, TON, TRON, XRP, LTC) ──

@app.get("/api/v1/multichain/status")
def multichain_live_status(refresh: bool = False):
    now = time.time()
    results = MultiChainReader.get_all_chains_map(use_cache=not refresh, timeout=5.0)
    return {
        "status": "ok",
        "univa_height": blockchain.height,
        "univa_chain_id": UNIVA_CHAIN_ID_DEC,
        "chains": results,
        "count": len(results),
        "updated_at": int(now),
    }


# ─── TRC-20 (TRON USDT) GATEWAY & HOT WALLET ENDPOINTS ───────────────────

trc20_gateway = TRC20Gateway(network=os.environ.get("UNIVA_TRON_NET", "mainnet"))


class TRC20RegisterDepositRequest(BaseModel):
    tx_id: str
    univa_user: str
    amount_usdt: float
    from_address: str


class TRC20WithdrawalRequest(BaseModel):
    univa_user: str
    destination_tron: str
    amount_usdt: float


class TRC20VerifyTxRequest(BaseModel):
    tx_id: str
    univa_user: str


@app.get("/api/v1/bridge/trc20/status")
def trc20_status():
    return {
        "status": "ok",
        "gateway": trc20_gateway.get_stats(),
        "vault_address": trc20_gateway.get_vault_address(),
        "usdt_contract": trc20_gateway.usdt_contract,
    }


@app.get("/api/v1/bridge/trc20/account/{address}")
def trc20_account(address: str):
    res = trc20_gateway.get_account_overview(address)
    if not res.get("valid"):
        raise HTTPException(status_code=400, detail=res.get("error", "Geçersiz TRON adresi"))
    return res


@app.post("/api/v1/bridge/trc20/check-deposits")
def trc20_check_deposits():
    new_deposits = trc20_gateway.poll_and_process_deposits()
    return {
        "status": "ok",
        "new_deposits_count": len(new_deposits),
        "new_deposits": new_deposits,
        "total_stats": trc20_gateway.get_stats(),
    }


@app.post("/api/v1/bridge/trc20/register-deposit")
def trc20_register_deposit(req: TRC20RegisterDepositRequest):
    res = trc20_gateway.register_user_deposit(
        tx_id=req.tx_id,
        univa_user=req.univa_user,
        amount_usdt=req.amount_usdt,
        from_address=req.from_address,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Kayıt başarısız"))
    return {"status": "ok", "deposit": res.get("deposit")}


@app.post("/api/v1/bridge/trc20/request-withdrawal")
def trc20_request_withdrawal(req: TRC20WithdrawalRequest):
    res = trc20_gateway.request_withdrawal(
        univa_user=req.univa_user,
        destination_tron_address=req.destination_tron,
        amount_usdt=req.amount_usdt,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Çekim başarısız"))
    return {"status": "ok", "withdrawal": res.get("withdrawal")}


@app.post("/api/v1/bridge/trc20/verify-tx")
def trc20_verify_tx(req: TRC20VerifyTxRequest):
    res = trc20_gateway.verify_and_credit_tx(
        tx_id=req.tx_id,
        univa_user=req.univa_user,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "İşlem doğrulanamadı"))
    return {"status": "ok", "deposit": res.get("deposit")}


class MultiChainVerifyTxRequest(BaseModel):
    tx_id: str
    chain: str = "AUTO"
    univa_user: str = "Sovereign User"


@app.get("/api/v1/bridge/multichain/addresses/{evm_address}")
def multichain_addresses(evm_address: str, univa_address: str = "", pub_key_hex: str = ""):
    try:
        addrs = MultiChainAddress.derive_all_addresses(
            evm_address=evm_address,
            univa_address=univa_address,
            pub_key_hex=pub_key_hex,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", "addresses": addrs}


@app.get("/api/v1/bridge/multichain/balances/{evm_address}")
def multichain_balances(evm_address: str, univa_address: str = ""):
    from concurrent.futures import ThreadPoolExecutor
    try:
        addrs = MultiChainAddress.derive_all_addresses(evm_address=evm_address, univa_address=univa_address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def _safe_trx():
        try:
            ov = trc20_gateway.get_account_overview(addrs["trx"])
            return {"trx": float(ov.get("trx_balance", 0.0)), "usdt_trc20": float(ov.get("usdt_balance", 0.0))}
        except Exception:
            return {"trx": 0.0, "usdt_trc20": 0.0}

    def _safe_evm(chain_name: str):
        try:
            r = trc20_gateway.get_evm_chain_balance(addrs["evm"], chain_name)
            return float(r.get("balance", 0.0))
        except Exception:
            return 0.0

    def _safe_btc():
        try:
            r = trc20_gateway.get_btc_account_info(addrs["btc_segwit"])
            return float(r.get("total_btc", 0.0))
        except Exception:
            return 0.0

    def _safe_sol():
        try:
            r = trc20_gateway.get_sol_account_info(addrs["sol"])
            return float(r.get("sol", 0.0))
        except Exception:
            return 0.0

    pool = ThreadPoolExecutor(max_workers=5)
    f_trx = pool.submit(_safe_trx)
    f_bnb = pool.submit(_safe_evm, "bsc")
    f_eth = pool.submit(_safe_evm, "eth")
    f_btc = pool.submit(_safe_btc)
    f_sol = pool.submit(_safe_sol)
    pool.shutdown(wait=False)

    def _safe_res(fut, default):
        try:
            return fut.result(timeout=6)
        except Exception:
            return default

    trx_res = _safe_res(f_trx, {"trx": 0.0, "usdt_trc20": 0.0})
    bnb_val = _safe_res(f_bnb, 0.0)
    eth_val = _safe_res(f_eth, 0.0)
    btc_val = _safe_res(f_btc, 0.0)
    sol_val = _safe_res(f_sol, 0.0)

    univa_val = float(_get_effective_balance(univa_address)) if univa_address else 0.0
    return {
        "status": "ok",
        "addresses": addrs,
        "balances": {
            "UNIVA": univa_val,
            "TRX": trx_res["trx"],
            "USDT": trx_res["usdt_trc20"],
            "BNB": bnb_val,
            "ETH": eth_val,
            "BTC": btc_val,
            "SOL": sol_val,
        },
    }


@app.post("/api/v1/bridge/multichain/verify-tx")
def multichain_verify_tx(req: MultiChainVerifyTxRequest):
    res = trc20_gateway.verify_multichain_tx(
        tx_id=req.tx_id,
        chain=req.chain,
        univa_user=req.univa_user,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "İşlem doğrulanamadı"))
    return {"status": "ok", "deposit": res.get("deposit")}


@app.post("/rpc")
@app.post("/")
async def rpc(request: Request):
    try:
        body = await request.json()
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}

    if isinstance(body, list):
        if len(body) == 0:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request: empty batch"}}
        return [
            _process_rpc_call(item) if isinstance(item, dict)
            else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
            for item in body
        ]
    if isinstance(body, dict):
        return _process_rpc_call(body)
    return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
