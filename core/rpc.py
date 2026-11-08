"""
UNIVA Network - Bitcoin Core Compatible JSON-RPC 2.0 Engine
============================================================
Enables exchanges, third-party block explorers, hardware wallets
and mining pools to communicate with UNIVA using standard Bitcoin RPC calls.
"""

import json
import time
from typing import Dict, Any, Optional

def handle_bitcoin_rpc(blockchain, wallet, rpc_request: Dict[str, Any]) -> Dict[str, Any]:
    """Bitcoin JSON-RPC 2.0 formatındaki istekleri karşılar ve standart yanıt üretir."""
    req_id = rpc_request.get("id", 1)
    method = rpc_request.get("method", "")
    params = rpc_request.get("params", [])

    def success(result_data):
        return {
            "result": result_data,
            "error": None,
            "id": req_id
        }

    def error(code: int, message: str):
        return {
            "result": None,
            "error": {"code": code, "message": message},
            "id": req_id
        }

    # ── Yöntemler ────────────────────────────────────────────────────────
    if method == "getblockchaininfo":
        mtp = blockchain.get_median_time_past(11) if hasattr(blockchain, "get_median_time_past") else time.time()
        return success({
            "chain": "main",
            "blocks": blockchain.height,
            "headers": blockchain.height,
            "bestblockhash": blockchain.last_block.hash,
            "difficulty": blockchain.difficulty,
            "mediantime": int(mtp),
            "verificationprogress": 1.0,
            "initialblockdownload": False,
            "chainwork": hex(blockchain.height),
            "size_on_disk": len(blockchain.chain) * 2048,
            "pruned": False,
            "softforks": {},
            "bip9_softforks": {},
            "warnings": ""
        })

    elif method == "getblockcount":
        return success(blockchain.height)

    elif method == "getbestblockhash":
        return success(blockchain.last_block.hash)

    elif method == "getblockhash":
        if not params or not isinstance(params[0], int):
            return error(-1, "Blok indeksi (height) parametresi gereklidir")
        idx = params[0]
        if idx < 0 or idx >= len(blockchain.chain):
            return error(-8, "Blok yüksekliği sınırların dışında")
        return success(blockchain.chain[idx].hash)

    elif method == "getblock":
        if not params:
            return error(-1, "Blok hash veya yükseklik parametresi gereklidir")
        identifier = params[0]
        target_block = None
        if isinstance(identifier, int):
            if 0 <= identifier < len(blockchain.chain):
                target_block = blockchain.chain[identifier]
        else:
            for b in blockchain.chain:
                if b.hash == identifier:
                    target_block = b
                    break
        if not target_block:
            return error(-5, "Blok bulunamadı")

        b_dict = target_block.to_dict()
        return success({
            "hash": b_dict["hash"],
            "confirmations": blockchain.height - b_dict["index"] + 1,
            "size": len(json.dumps(b_dict)),
            "height": b_dict["index"],
            "version": 1,
            "merkleroot": b_dict.get("merkle_root", "0"*64),
            "tx": [t.get("tx_id", "coinbase") if isinstance(t, dict) else str(t) for t in b_dict.get("transactions", [])],
            "time": int(b_dict["timestamp"]),
            "mediantime": int(b_dict["timestamp"]),
            "nonce": b_dict["nonce"],
            "difficulty": b_dict["difficulty"],
            "previousblockhash": b_dict["previous_hash"],
            "miner": b_dict.get("miner_address", ""),
            "reward": b_dict.get("reward", 0.0),
        })

    elif method == "getmininginfo":
        return success({
            "blocks": blockchain.height,
            "difficulty": blockchain.difficulty,
            "networkhashps": blockchain.difficulty * 125000,
            "pooledtx": len(blockchain.pending_transactions),
            "chain": "main",
            "warnings": ""
        })

    elif method == "getnetworkinfo":
        return success({
            "version": 2010000,
            "subversion": "/UNIVA:2.1.0(Universal Sovereign L1)/",
            "protocolversion": 70016,
            "localservices": "000000000000040d",
            "localrelay": True,
            "timeoffset": 0,
            "networkactive": True,
            "connections": getattr(blockchain, "peer_count", 1) + 1,
            "networks": [{"name": "ipv4", "limited": False, "reachable": True, "proxy": ""}],
            "relayfee": 0.00001,
            "incrementalfee": 0.00001,
            "localaddresses": [],
            "warnings": ""
        })

    elif method == "getpeerinfo":
        from core.p2p import get_peer_list
        try:
            peers = get_peer_list()
        except Exception:
            peers = []
        peer_info = []
        for p in peers:
            peer_info.append({
                "id": p,
                "addr": p,
                "services": "000000000000040d",
                "lastsend": int(time.time()),
                "lastrecv": int(time.time()),
                "conntime": int(time.time()),
                "pingtime": 0.024,
                "version": 70016,
                "subver": "/UNIVA:2.1.0/",
                "inbound": False,
                "startingheight": blockchain.height,
            })
        return success(peer_info)

    elif method == "getrawmempool":
        return success([t.get("tx_id", "tx") for t in blockchain.pending_transactions])

    elif method == "sendrawtransaction":
        if not params:
            return error(-1, "İşlem nesnesi (tx) gereklidir")
        raw_tx = params[0]
        if isinstance(raw_tx, str):
            try:
                raw_tx = json.loads(raw_tx)
            except Exception:
                return error(-22, "İşlem JSON formatında olmalıdır")
        
        if blockchain.add_transaction(raw_tx):
            return success(raw_tx.get("tx_id", "tx_broadcasted"))
        return error(-26, "İşlem reddedildi: yetersiz bakiye veya geçersiz imza")

    elif method == "ping":
        return success("pong")

    else:
        return error(-32601, f"Desteklenmeyen RPC metodu: {method}")
