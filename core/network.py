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
import time

from core.blockchain import Blockchain
from core.dex import UnivaDEX, to_base_units, from_base_units
from core.telemetry import telemetry
from core.interop import MultiChainReader, UniversalProofEngine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PWA_DIR = os.path.join(BASE_DIR, "pwa")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
CHAIN_PATH = os.environ.get("UNIVA_CHAIN_FILE", "univa_chain.json")

blockchain = Blockchain(auto_load_path=CHAIN_PATH)
app = FastAPI(title="UNIVA L1 Unified Node API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_pna_headers(request: Request, call_next):
    if request.method == "OPTIONS" and "access-control-request-private-network" in request.headers:
        response = PlainTextResponse("OK", status_code=200)
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = request.headers.get("access-control-request-headers", "*")
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

# Native AMM instance for testnet quotes and balance checking
dex_engine = UnivaDEX()
try:
    dex_engine.deposit("univa_genesis_vault", "UNIVA", to_base_units(50_000.0))
    dex_engine.deposit("univa_genesis_vault", "uUSD", to_base_units(250_000.0))
    dex_engine.add_liquidity(
        provider="univa_genesis_vault",
        asset_a="UNIVA",
        asset_b="uUSD",
        amount_a=to_base_units(50_000.0),
        amount_b=to_base_units(250_000.0),
    )
except Exception:
    pass


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
    data = blockchain.stats()
    data["network"] = "UNIVA Network"
    data["version"] = "3.0.0"
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

@app.get("/balance/{address}")
def balance(address: str):
    bal = blockchain.get_balance(address)
    return {
        "address": address,
        "balance": bal,
        "ticker": "UNIVA",
        "valid_format": len(address) == 20 and address.startswith("univa") and address.endswith("univa"),
    }

@app.get("/api/v1/history/{address}")
def address_history(address: str):
    """
    Belirtilen adresin dahil oldugu tum gonderilen, alinan ve madencilik (coinbase) islemlerini dondurur.
    """
    history = []
    # 1. Onaylanmis bloklardaki islemler
    for block in reversed(blockchain.chain):
        block_idx = block.index
        block_ts = block.timestamp
        for tx in block.transactions:
            tx_from = tx.get("from")
            tx_to = tx.get("to")
            tx_type = tx.get("type", "transfer")
            
            if tx_from == address or tx_to == address:
                is_incoming = (tx_to == address)
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
        if tx_from == address or tx_to == address:
            is_incoming = (tx_to == address)
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

@app.post("/api/v1/wallet/create")
async def create_or_recover_wallet(request: Request):
    """
    Kullaniciya tek ve kalici bir secp256k1 ECDSA cuzdani uretir veya
    mevcut private_key ile ayni 20 karakterlik adresi geri yukler.
    """
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
        "public_key": w.public_key,
        "private_key": w.private_key,
    }


@app.post("/transactions")
@app.post("/tx")
async def submit_transaction(request: Request):
    from core.wallet import UnivaWallet
    data = await request.json()
    tx = data.get("tx") if "tx" in data else data
    if not isinstance(tx, dict):
        raise HTTPException(400, "Gecersiz islem verisi")

    # Eger istemci private_key ile gonderdiyse secp256k1 ECDSA imzasini olustur
    priv_key = (tx.get("private_key") or data.get("private_key") or "").strip()
    if ("signature" not in tx or not tx.get("signature")) and len(priv_key) == 64:
        try:
            w = UnivaWallet(private_key_hex=priv_key)
            if tx.get("from") and tx.get("from") != w.address:
                raise HTTPException(400, "Ozel anahtar bu cuzdan adresine ait degil!")
            tx = blockchain.create_transaction(
                w, tx.get("to"), float(tx.get("amount", 0)), float(tx.get("fee", 0.0))
            )
        except ValueError as ve:
            raise HTTPException(400, str(ve))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Imzalama hatasi: {e}")

    # Otomatik sunucu cuzdani geri donusu
    elif "signature" not in tx or not tx.get("signature"):
        wallet_file = os.path.join(BASE_DIR, "univa_wallet.json")
        if os.path.exists(wallet_file):
            try:
                w = UnivaWallet.load(wallet_file)
                if tx.get("from") == w.address:
                    tx = blockchain.create_transaction(
                        w, tx.get("to"), float(tx.get("amount", 0)), float(tx.get("fee", 0.0))
                    )
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


# ─── MADENCILIK ENDPOINTI ────────────────────────────────────────────────────

@app.post("/mine/{miner_address}")
@app.get("/api/v1/faucet/{miner_address}")
@app.post("/api/v1/faucet/{miner_address}")
def mine_block(miner_address: str):
    from core.wallet import validate_address
    if not validate_address(miner_address):
        raise HTTPException(400, f"Gecersiz 20 karakter UNIVA adresi: {miner_address}")
    
    block = blockchain.mine_pending_transactions(miner_address)
    if block is None:
        raise HTTPException(409, "Maksimum arza ulasildi veya madencilik basarisiz")
    
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

    # DEX icin test bakiyesi ekle
    try:
        dex_engine.deposit(miner_address, "uUSD", to_base_units(500.0))
        dex_engine.deposit(miner_address, "UNIVA", to_base_units(100.0))
    except Exception:
        pass

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

@app.get("/api/v1/dex/pools")
def dex_pools():
    res = [p.to_dict() for p in dex_engine.pools.values()]
    return {"pools": res, "count": len(res)}

@app.get("/api/v1/dex/balances/{address}")
def dex_balances(address: str):
    chain_univa = blockchain.get_balance(address)
    dex_univa = from_base_units(dex_engine.get_balance(address, "UNIVA"))
    return {
        "UNIVA": round(max(chain_univa, dex_univa), 8),
        "uUSD": from_base_units(dex_engine.get_balance(address, "uUSD")),
    }

@app.post("/api/v1/dex/quote")
async def dex_quote(request: Request):
    data = await request.json()
    asset_in = data.get("asset_in", "UNIVA")
    asset_out = data.get("asset_out", "uUSD")
    amount_in_float = float(data.get("amount_in", 0.0))
    if amount_in_float <= 0:
        raise HTTPException(400, "Miktar pozitif olmalidir")
    pool = dex_engine.get_pool(asset_in, asset_out)
    if not pool:
        raise HTTPException(404, "Havuz bulunamadi")
    try:
        amt_in_base = to_base_units(amount_in_float)
        out_base, fee_base = dex_engine.get_amount_out(pool, asset_in, amt_in_base)
        return {
            "asset_in": asset_in,
            "asset_out": asset_out,
            "amount_in": amount_in_float,
            "amount_out": from_base_units(out_base),
            "fee": from_base_units(fee_base),
            "fee_bps": pool.fee_bps,
        }
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/v1/dex/swap")
async def dex_swap(request: Request):
    data = await request.json()
    user = data.get("user")
    asset_in = data.get("asset_in", "UNIVA")
    asset_out = data.get("asset_out", "uUSD")
    amount_in_float = float(data.get("amount_in", 0.0))
    min_out_float = float(data.get("min_out", 0.0))

    if not user or amount_in_float <= 0:
        raise HTTPException(400, "Gecersiz istek")
    try:
        amt_in = to_base_units(amount_in_float)
        min_out = to_base_units(min_out_float)
        if asset_in == "UNIVA":
            chain_bal = blockchain.get_balance(user)
            dex_bal = from_base_units(dex_engine.get_balance(user, "UNIVA"))
            total_avail = max(chain_bal, dex_bal)
            if total_avail < amount_in_float:
                raise HTTPException(400, f"Yetersiz bakiye! Mevcut: {total_avail}, Gerekli: {amount_in_float}")
            dex_engine.set_balance(user, "UNIVA", to_base_units(total_avail))

        out_base = dex_engine.swap(user, asset_in, asset_out, amt_in, min_out)
        out_float = from_base_units(out_base)
        return {
            "status": "ok",
            "user": user,
            "swapped_in": amount_in_float,
            "received_out": out_float,
            "asset_out": asset_out,
        }
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── INTEROPERABILITY & PROOFS ───────────────────────────────────────────────

@app.get("/api/v1/interop/chains")
def interop_chains():
    overview = MultiChainReader.get_all_chains_overview()
    return {"chains": overview, "univa_height": blockchain.height}

@app.get("/api/v1/interop/proof/{tx_id}")
def interop_proof(tx_id: str):
    proof = UniversalProofEngine.generate_proof_for_tx(blockchain, tx_id)
    if not proof:
        raise HTTPException(404, "Islem bulunamadi")
    return proof


# ─── BITCOIN CORE COMPATIBLE JSON-RPC 2.0 ────────────────────────────────────

# ─── UNIVA HİBRİT EVM & BITCOIN JSON-RPC ADAPTÖRÜ ─────────────────────────────
# MetaMask, Trust Wallet ve Web3 cüzdanları için standart EVM metodları (eth_...)
# ve borsa/analiz için Bitcoin Core metodları (getblockchaininfo, ...) desteklenir.
UNIVA_CHAIN_ID_DEC = 210001
UNIVA_CHAIN_ID_HEX = hex(UNIVA_CHAIN_ID_DEC) # '0x33451'

def _process_rpc_call(body: dict) -> dict:
    method = body.get("method", "")
    params = body.get("params") or []
    req_id = body.get("id", 1)

    try:
        # === 1. METAMASK / TRUST WALLET / EVM WEB3 METODLARI ===
        if method == "eth_chainId":
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
            addr = str(params[0]) if params else "0x0"
            bal = blockchain.get_balance(addr)
            # 18 decimal Wei formatına çevir (1 UNIVA = 10^18 wei)
            wei_val = int(bal * 10**18)
            result = hex(wei_val)
        elif method in ("eth_gasPrice", "eth_maxPriorityFeePerGas"):
            result = "0x3b9aca00" # 1 Gwei
        elif method == "eth_estimateGas":
            result = "0x5208"     # 21000 standart transfer gazı
        elif method in ("eth_call", "eth_getCode", "eth_getStorageAt"):
            result = "0x"
        elif method == "eth_getTransactionCount":
            # Adresin onaylanmış nonce sayısını döndür
            addr = str(params[0]) if params else ""
            nonce = blockchain._account_nonce(addr)
            result = hex(nonce)
        elif method in ("eth_getBlockByNumber", "eth_getBlockByHash"):
            tag = params[0] if params else "latest"
            if method == "eth_getBlockByNumber":
                idx = blockchain.height if tag in ("latest", "pending", "safe", "finalized") else (
                    0 if tag == "earliest" else int(str(tag), 16)
                )
                idx = max(0, min(idx, blockchain.height))
                blk = blockchain.chain[idx]
            else:
                target_h = str(tag).lower().replace("0x", "")
                blk = next((b for b in blockchain.chain if b.hash.lower().replace("0x", "") == target_h), blockchain.last_block)
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
                "totalDifficulty": hex(blk.difficulty * (blk.index + 1)),
                "extraData": "0x554e495641", # 'UNIVA'
                "size": hex(1000),
                "gasLimit": "0x1c9c380", # 30,000,000
                "gasUsed": "0x5208",
                "baseFeePerGas": "0x3b9aca00",
                "timestamp": hex(int(blk.timestamp)),
                "transactions": [tx.get("tx_id") for tx in blk.transactions if tx.get("tx_id")],
                "uncles": []
            }
        elif method == "eth_sendRawTransaction":
            # Ham işlem alındı bildirimi
            raw_tx = params[0] if params else ""
            tx_id = hashlib.sha256(raw_tx.encode()).hexdigest()
            result = "0x" + tx_id

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
                "chainwork": hex(blockchain.height),
            }
        elif method == "getblockcount":
            result = blockchain.height
        elif method == "getbestblockhash":
            result = blockchain.last_block.hash
        elif method == "getblockhash":
            h = int(params[0])
            result = blockchain.chain[h].hash
        elif method == "getblock":
            h = int(params[0])
            result = blockchain.chain[h].to_dict()
        elif method == "getbalance":
            result = blockchain.get_balance(str(params[0]))
        elif method == "getnetworkinfo":
            result = {"network": "UNIVA-L1", "version": "4.0.0", "connections": 1}
        elif method == "getmininginfo":
            result = blockchain.stats()
        elif method == "sendrawtransaction":
            tx = params[0]
            if not blockchain.add_transaction(tx):
                raise ValueError("Transaction rejected")
            result = tx.get("tx_id")
        else:
            raise ValueError(f"Unknown RPC method: {method}")

        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": str(exc)}}


@app.post("/rpc")
@app.post("/")
async def rpc(request: Request):
    try:
        body = await request.json()
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}

    if isinstance(body, list):
        return [_process_rpc_call(item) for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        return _process_rpc_call(body)
    return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
