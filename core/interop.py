"""
UNIVA Network - Universal Interoperability Engine (P6)
Real multi-chain state readers (BTC, ETH, BNB, SOL, TON, TRX, XRP, LTC) with
multi-endpoint failover and ZERO fabricated/hardcoded fallback heights, plus
cryptographically verified Universal Merkle + Header PoW Proof Engine.
"""

import concurrent.futures
import hashlib
import json
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


class MultiChainReader:
    """Multi-chain live state reader with multi-RPC failover and honest offline reporting."""

    CACHE_TTL_SECONDS = 30.0
    _cache_lock = threading.RLock()
    _cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    ENDPOINTS = {
        "BTC": [
            "https://mempool.space/api/blocks/tip/height",
            "https://blockstream.info/api/blocks/tip/height",
            "https://blockchain.info/latestblock",
        ],
        "ETH": [
            "https://ethereum-rpc.publicnode.com",
            "https://cloudflare-eth.com",
            "https://1rpc.io/eth",
        ],
        "BNB": [
            "https://bsc-rpc.publicnode.com",
            "https://bsc-dataseed.binance.org",
            "https://1rpc.io/bnb",
        ],
        "SOL": [
            "https://api.mainnet-beta.solana.com",
            "https://solana-rpc.publicnode.com",
        ],
        "TON": [
            "https://toncenter.com/api/v2/getMasterchainInfo",
            "https://tonapi.io/v2/blockchain/masterchain-head",
        ],
        "TRX": [
            "https://tron-rpc.publicnode.com/wallet/getnowblock",
            "https://api.trongrid.io/wallet/getnowblock",
            "https://apilist.tronscanapi.com/api/block/latest",
        ],
        "XRP": [
            "https://s1.ripple.com:51234",
            "https://xrplcluster.com",
        ],
        "LTC": [
            "https://litecoinspace.org/api/blocks/tip/height",
            "https://api.blockcypher.com/v1/ltc/main",
        ],
    }

    @staticmethod
    def _fetch_text(url: str, timeout: float = 3.5) -> Optional[str]:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "UNIVA-Universal-Node/4.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8").strip()
        except Exception:
            return None

    @staticmethod
    def _fetch_json(url: str, post_data: Optional[dict] = None, timeout: float = 3.5) -> Optional[dict]:
        try:
            headers = {
                "User-Agent": "UNIVA-Universal-Node/4.0",
                "Content-Type": "application/json",
            }
            if post_data is not None:
                data_bytes = json.dumps(post_data).encode("utf-8")
                req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
            else:
                req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    @staticmethod
    def _offline_result(chain_name: str, symbol: str, reason: str = "Upstream RPC unreachable") -> Dict[str, Any]:
        return {
            "chain": chain_name,
            "symbol": symbol,
            "status": "OFFLINE",
            "online": False,
            "height": None,
            "latest_hash": None,
            "source": None,
            "error": reason,
            "time": int(time.time()),
        }

    @classmethod
    def _cached(cls, symbol: str, fetcher, use_cache: bool = True) -> Dict[str, Any]:
        now = time.time()
        if use_cache:
            with cls._cache_lock:
                hit = cls._cache.get(symbol)
                if hit and (now - hit[0]) < cls.CACHE_TTL_SECONDS:
                    return dict(hit[1])
        data = fetcher()
        if data.get("online"):
            with cls._cache_lock:
                cls._cache[symbol] = (now, dict(data))
        return data

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache.clear()

    @classmethod
    def read_bitcoin(cls, use_cache: bool = True) -> Dict[str, Any]:
        def _run():
            for url in cls.ENDPOINTS["BTC"]:
                if url.endswith("/latestblock"):
                    res = cls._fetch_json(url)
                    if res and isinstance(res.get("height"), int):
                        h_str = str(res.get("hash") or "")
                        return {
                            "chain": "Bitcoin (BTC)",
                            "symbol": "BTC",
                            "status": "ONLINE",
                            "online": True,
                            "height": int(res["height"]),
                            "latest_hash": h_str[:24] + "..." if len(h_str) > 24 else h_str,
                            "source": url,
                            "time": int(res.get("time") or time.time()),
                        }
                else:
                    txt = cls._fetch_text(url)
                    if txt and txt.isdigit():
                        hash_url = url.replace("/tip/height", "/tip/hash")
                        h_str = cls._fetch_text(hash_url) or ""
                        return {
                            "chain": "Bitcoin (BTC)",
                            "symbol": "BTC",
                            "status": "ONLINE",
                            "online": True,
                            "height": int(txt),
                            "latest_hash": h_str[:24] + "..." if len(h_str) > 24 else (h_str or None),
                            "source": url,
                            "time": int(time.time()),
                        }
            return cls._offline_result("Bitcoin (BTC)", "BTC")

        return cls._cached("BTC", _run, use_cache=use_cache)

    @classmethod
    def _read_evm_chain(cls, chain_name: str, symbol: str, use_cache: bool = True) -> Dict[str, Any]:
        def _run():
            payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
            for url in cls.ENDPOINTS[symbol]:
                res = cls._fetch_json(url, post_data=payload)
                if res and isinstance(res.get("result"), str) and res["result"].startswith("0x"):
                    try:
                        height = int(res["result"], 16)
                        return {
                            "chain": chain_name,
                            "symbol": symbol,
                            "status": "ONLINE",
                            "online": True,
                            "height": height,
                            "latest_hash": res["result"],
                            "source": url,
                            "time": int(time.time()),
                        }
                    except Exception:
                        continue
            return cls._offline_result(chain_name, symbol)

        return cls._cached(symbol, _run, use_cache=use_cache)

    @classmethod
    def read_ethereum(cls, use_cache: bool = True) -> Dict[str, Any]:
        return cls._read_evm_chain("Ethereum (ETH)", "ETH", use_cache=use_cache)

    @classmethod
    def read_bnb(cls, use_cache: bool = True) -> Dict[str, Any]:
        return cls._read_evm_chain("BNB Smart Chain (BNB)", "BNB", use_cache=use_cache)

    @classmethod
    def read_solana(cls, use_cache: bool = True) -> Dict[str, Any]:
        def _run():
            payload = {"jsonrpc": "2.0", "method": "getSlot", "params": [], "id": 1}
            for url in cls.ENDPOINTS["SOL"]:
                res = cls._fetch_json(url, post_data=payload)
                if res and isinstance(res.get("result"), int):
                    slot = int(res["result"])
                    return {
                        "chain": "Solana (SOL)",
                        "symbol": "SOL",
                        "status": "ONLINE",
                        "online": True,
                        "height": slot,
                        "latest_hash": f"Slot #{slot}",
                        "source": url,
                        "time": int(time.time()),
                    }
            return cls._offline_result("Solana (SOL)", "SOL")

        return cls._cached("SOL", _run, use_cache=use_cache)

    @classmethod
    def read_ton(cls, use_cache: bool = True) -> Dict[str, Any]:
        def _run():
            for url in cls.ENDPOINTS["TON"]:
                res = cls._fetch_json(url)
                if not res:
                    continue
                if res.get("ok") and isinstance(res.get("result", {}).get("last", {}).get("seqno"), int):
                    last_block = res["result"]["last"]
                    rh = str(last_block.get("root_hash") or "")
                    return {
                        "chain": "The Open Network (TON)",
                        "symbol": "TON",
                        "status": "ONLINE",
                        "online": True,
                        "height": int(last_block["seqno"]),
                        "latest_hash": rh[:24] + "..." if len(rh) > 24 else rh,
                        "source": url,
                        "time": int(time.time()),
                    }
                if isinstance(res.get("seqno"), int):
                    rh = str(res.get("root_hash") or "")
                    return {
                        "chain": "The Open Network (TON)",
                        "symbol": "TON",
                        "status": "ONLINE",
                        "online": True,
                        "height": int(res["seqno"]),
                        "latest_hash": rh[:24] + "..." if len(rh) > 24 else rh,
                        "source": url,
                        "time": int(time.time()),
                    }
            return cls._offline_result("The Open Network (TON)", "TON")

        return cls._cached("TON", _run, use_cache=use_cache)

    @classmethod
    def read_tron(cls, use_cache: bool = True) -> Dict[str, Any]:
        def _run():
            for url in cls.ENDPOINTS["TRX"]:
                if "getnowblock" in url:
                    res = cls._fetch_json(url, post_data={})
                    num = (res or {}).get("block_header", {}).get("raw_data", {}).get("number")
                    bid = str((res or {}).get("blockID") or "")
                else:
                    res = cls._fetch_json(url)
                    num = (res or {}).get("number")
                    bid = str((res or {}).get("hash") or "")
                if isinstance(num, int):
                    return {
                        "chain": "TRON (TRX)",
                        "symbol": "TRX",
                        "status": "ONLINE",
                        "online": True,
                        "height": int(num),
                        "latest_hash": bid[:24] + "..." if len(bid) > 24 else (bid or None),
                        "source": url,
                        "time": int(time.time()),
                    }
            return cls._offline_result("TRON (TRX)", "TRX")

        return cls._cached("TRX", _run, use_cache=use_cache)

    @classmethod
    def read_xrp(cls, use_cache: bool = True) -> Dict[str, Any]:
        def _run():
            payload = {"method": "ledger_closed", "params": [{}]}
            for url in cls.ENDPOINTS["XRP"]:
                res = cls._fetch_json(url, post_data=payload)
                r = (res or {}).get("result") or {}
                idx = r.get("ledger_index")
                lh = str(r.get("ledger_hash") or "")
                if isinstance(idx, int):
                    return {
                        "chain": "XRP Ledger (XRP)",
                        "symbol": "XRP",
                        "status": "ONLINE",
                        "online": True,
                        "height": int(idx),
                        "latest_hash": lh[:24] + "..." if len(lh) > 24 else (lh or None),
                        "source": url,
                        "time": int(time.time()),
                    }
            return cls._offline_result("XRP Ledger (XRP)", "XRP")

        return cls._cached("XRP", _run, use_cache=use_cache)

    @classmethod
    def read_litecoin(cls, use_cache: bool = True) -> Dict[str, Any]:
        def _run():
            for url in cls.ENDPOINTS["LTC"]:
                if "litecoinspace.org" in url:
                    txt = cls._fetch_text(url)
                    if txt and txt.isdigit():
                        h_str = cls._fetch_text(url.replace("/tip/height", "/tip/hash")) or ""
                        return {
                            "chain": "Litecoin (LTC)",
                            "symbol": "LTC",
                            "status": "ONLINE",
                            "online": True,
                            "height": int(txt),
                            "latest_hash": h_str[:24] + "..." if len(h_str) > 24 else (h_str or None),
                            "source": url,
                            "time": int(time.time()),
                        }
                else:
                    res = cls._fetch_json(url)
                    if res and isinstance(res.get("height"), int):
                        h_str = str(res.get("hash") or "")
                        return {
                            "chain": "Litecoin (LTC)",
                            "symbol": "LTC",
                            "status": "ONLINE",
                            "online": True,
                            "height": int(res["height"]),
                            "latest_hash": h_str[:24] + "..." if len(h_str) > 24 else (h_str or None),
                            "source": url,
                            "time": int(time.time()),
                        }
            return cls._offline_result("Litecoin (LTC)", "LTC")

        return cls._cached("LTC", _run, use_cache=use_cache)

    @classmethod
    def get_all_chains_map(cls, use_cache: bool = True, timeout: float = 5.0) -> Dict[str, Dict[str, Any]]:
        readers = {
            "btc": ("Bitcoin (BTC)", "BTC", lambda: cls.read_bitcoin(use_cache=use_cache)),
            "eth": ("Ethereum (ETH)", "ETH", lambda: cls.read_ethereum(use_cache=use_cache)),
            "bnb": ("BNB Smart Chain (BNB)", "BNB", lambda: cls.read_bnb(use_cache=use_cache)),
            "sol": ("Solana (SOL)", "SOL", lambda: cls.read_solana(use_cache=use_cache)),
            "ton": ("The Open Network (TON)", "TON", lambda: cls.read_ton(use_cache=use_cache)),
            "trx": ("TRON (TRX)", "TRX", lambda: cls.read_tron(use_cache=use_cache)),
            "xrp": ("XRP Ledger (XRP)", "XRP", lambda: cls.read_xrp(use_cache=use_cache)),
            "ltc": ("Litecoin (LTC)", "LTC", lambda: cls.read_litecoin(use_cache=use_cache)),
        }
        out: Dict[str, Dict[str, Any]] = {}
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(readers))
        futs = {k: ex.submit(fn) for k, (_, _, fn) in readers.items()}
        concurrent.futures.wait(futs.values(), timeout=timeout)
        for k, fut in futs.items():
            cname, sym, _ = readers[k]
            if fut.done():
                try:
                    out[k] = fut.result(timeout=0)
                except Exception as exc:
                    out[k] = cls._offline_result(cname, sym, str(exc))
            else:
                fut.cancel()
                out[k] = cls._offline_result(cname, sym, "Timeout")
        ex.shutdown(wait=False, cancel_futures=True)
        return out

    @classmethod
    def get_all_chains_overview(cls, use_cache: bool = True, timeout: float = 5.0) -> List[Dict[str, Any]]:
        m = cls.get_all_chains_map(use_cache=use_cache, timeout=timeout)
        order = ("btc", "eth", "bnb", "sol", "ton", "trx", "xrp", "ltc")
        return [m[k] for k in order if k in m]


class UniversalProofEngine:
    """Cryptographic SPV Merkle + Block Header PoW Proof generator and verifier."""

    @staticmethod
    def _hash_tx(tx: dict) -> str:
        # Must match core.blockchain.calculate_merkle_root leaf hashing exactly!
        tx_str = json.dumps(tx, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(tx_str.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_header_hash(header: dict) -> str:
        payload = json.dumps(
            {
                "index": header["index"],
                "merkle_root": header["merkle_root"],
                "previous_hash": header["previous_hash"],
                "timestamp": header["timestamp"],
                "nonce": header["nonce"],
                "difficulty": header["difficulty"],
                "miner_address": header["miner_address"],
                "reward": header["reward"],
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def generate_proof_for_tx(cls, blockchain, tx_id: str) -> Optional[Dict[str, Any]]:
        target_block = None
        target_tx = None
        tx_index = -1

        for block in blockchain.chain:
            for idx, tx in enumerate(block.transactions):
                current_id = tx.get("tx_id") or cls._hash_tx(tx)
                if current_id == tx_id or (
                    tx.get("type") == "coinbase" and tx_id in ("coinbase", str(block.index))
                ):
                    target_block = block
                    target_tx = tx
                    tx_index = idx
                    break
            if target_block:
                break

        if not target_block or target_tx is None:
            return None

        tx_hashes = [cls._hash_tx(t) for t in target_block.transactions]
        proof_hashes = []
        cur_idx = tx_index

        while len(tx_hashes) > 1:
            if len(tx_hashes) % 2 != 0:
                tx_hashes.append(tx_hashes[-1])
            new_level = []
            for i in range(0, len(tx_hashes), 2):
                combined = tx_hashes[i] + tx_hashes[i + 1]
                parent = hashlib.sha256(combined.encode("utf-8")).hexdigest()
                new_level.append(parent)
                if i == cur_idx:
                    proof_hashes.append({"sibling": tx_hashes[i + 1], "position": "right"})
                elif i + 1 == cur_idx:
                    proof_hashes.append({"sibling": tx_hashes[i], "position": "left"})
            cur_idx //= 2
            tx_hashes = new_level

        block_header = {
            "index": target_block.index,
            "previous_hash": target_block.previous_hash,
            "timestamp": target_block.timestamp,
            "nonce": target_block.nonce,
            "difficulty": target_block.difficulty,
            "miner_address": target_block.miner_address,
            "reward": target_block.reward,
            "merkle_root": target_block.merkle_root,
        }

        proof = {
            "univa_protocol": "UNIVA-Universal-Interop-v3",
            "chain_id": "UNIVA-MAIN-1",
            "block_index": target_block.index,
            "block_hash": target_block.hash,
            "block_header": block_header,
            "merkle_root": target_block.merkle_root,
            "timestamp": target_block.timestamp,
            "tx_hash": cls._hash_tx(target_tx),
            "tx_data": target_tx,
            "proof_path": proof_hashes,
        }
        proof["verified"] = cls.verify_proof(proof)
        return proof

    @classmethod
    def verify_proof_detailed(cls, proof_data: dict) -> Dict[str, Any]:
        checks = {
            "tx_hash_matches_data": False,
            "tx_signature_valid": False,
            "merkle_root_valid": False,
            "header_hash_valid": False,
            "header_pow_valid": False,
        }
        try:
            if not isinstance(proof_data, dict):
                return {"valid": False, "checks": checks, "error": "Proof must be a JSON object"}
            tx_data = proof_data.get("tx_data")
            merkle_root = proof_data.get("merkle_root")
            if not isinstance(tx_data, dict) or not merkle_root:
                return {"valid": False, "checks": checks, "error": "Missing tx_data or merkle_root"}

            # 1. Recompute leaf hash directly from tx_data (never trust untrusted tx_hash alone)
            computed_tx_hash = cls._hash_tx(tx_data)
            if proof_data.get("tx_hash") and proof_data["tx_hash"] != computed_tx_hash:
                return {"valid": False, "checks": checks, "error": "tx_hash does not match tx_data"}
            checks["tx_hash_matches_data"] = True

            # 2. If signed L1 tx (not coinbase/genesis), verify ECDSA signature statelessly
            tx_type = tx_data.get("type", "transfer")
            if tx_type in ("coinbase", "genesis"):
                checks["tx_signature_valid"] = True
            else:
                from core.transaction import verify_transaction
                if not verify_transaction(tx_data):
                    return {"valid": False, "checks": checks, "error": "Invalid ECDSA tx signature inside proof"}
                checks["tx_signature_valid"] = True

            # 3. Walk Merkle branch up to merkle_root
            current_hash = computed_tx_hash
            for step in proof_data.get("proof_path") or []:
                sibling = step.get("sibling")
                pos = step.get("position")
                if not sibling or pos not in ("left", "right"):
                    return {"valid": False, "checks": checks, "error": "Malformed Merkle proof step"}
                combined = (current_hash + sibling) if pos == "right" else (sibling + current_hash)
                current_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
            if current_hash != merkle_root:
                return {"valid": False, "checks": checks, "error": "Merkle root mismatch"}
            checks["merkle_root_valid"] = True

            # 4. Verify Block Header SHA-256 hash & Proof-of-Work target
            header = proof_data.get("block_header")
            block_hash = proof_data.get("block_hash")
            if isinstance(header, dict) and block_hash:
                if header.get("merkle_root") != merkle_root:
                    return {"valid": False, "checks": checks, "error": "Header merkle_root mismatch"}
                computed_blk_hash = cls._compute_header_hash(header)
                if computed_blk_hash != block_hash:
                    return {"valid": False, "checks": checks, "error": "Block header hash mismatch"}
                checks["header_hash_valid"] = True

                diff = int(header.get("difficulty", 0))
                idx = int(header.get("index", 0))
                if idx > 0 and (diff < 1 or not block_hash.startswith("0" * diff)):
                    return {"valid": False, "checks": checks, "error": "Block PoW difficulty target not met"}
                checks["header_pow_valid"] = True
            else:
                return {"valid": False, "checks": checks, "error": "Missing block_header or block_hash"}

            return {"valid": True, "checks": checks, "error": None}
        except Exception as exc:
            return {"valid": False, "checks": checks, "error": str(exc)}

    @classmethod
    def verify_proof(cls, proof_data: dict) -> bool:
        return bool(cls.verify_proof_detailed(proof_data).get("valid"))
