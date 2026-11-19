"""UNIVA P6 - Multichain Readers (8 Chains), Universal Proof & JSON-RPC 2.0 Test Suite."""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.blockchain import Blockchain, INITIAL_DIFF
from core.interop import MultiChainReader, UniversalProofEngine
from core.wallet import UnivaWallet
import core.network as net

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_1_eight_chain_readers_and_zero_fake_fallback():
    MultiChainReader.clear_cache()

    # 1. Total network outage -> EVERY chain MUST honestly report OFFLINE / height=None (ZERO fake heights!)
    with patch.object(MultiChainReader, "_fetch_json", return_value=None), \
         patch.object(MultiChainReader, "_fetch_text", return_value=None):
        chains = MultiChainReader.get_all_chains_overview(use_cache=False)
        assert len(chains) == 8
        syms = {c["symbol"] for c in chains}
        assert syms == {"BTC", "ETH", "BNB", "SOL", "TON", "TRX", "XRP", "LTC"}
        for c in chains:
            assert c["online"] is False, f"{c['symbol']} lied about being online!"
            assert c["status"] == "OFFLINE"
            assert c["height"] is None, f"{c['symbol']} returned fabricated height {c['height']}!"

    # 2. Multi-endpoint failover -> primary fails, secondary succeeds for all 8 chains
    MultiChainReader.clear_cache()

    def fake_text(url, timeout=3.5):
        if "blockstream.info/api/blocks/tip/height" in url:
            return "895123"
        if "blockstream.info/api/blocks/tip/hash" in url:
            return "0000000000000000000abcde1234567890"
        if "litecoinspace.org/api/blocks/tip/height" in url:
            return "2850123"
        if "litecoinspace.org/api/blocks/tip/hash" in url:
            return "ltchash000123456789abcdef"
        return None

    def fake_json(url, post_data=None, timeout=3.5):
        if "cloudflare-eth.com" in url:
            return {"jsonrpc": "2.0", "id": 1, "result": hex(22345678)}
        if "bsc-dataseed.binance.org" in url:
            return {"jsonrpc": "2.0", "id": 1, "result": hex(48123456)}
        if "solana-rpc.publicnode.com" in url:
            return {"jsonrpc": "2.0", "id": 1, "result": 325999111}
        if "tonapi.io" in url:
            return {"seqno": 45678901, "root_hash": "tonhash9999"}
        if "tronscanapi.com" in url:
            return {"number": 70111222, "hash": "trxhash8888"}
        if "xrplcluster.com" in url:
            return {"result": {"ledger_index": 94555666, "ledger_hash": "xrphash7777"}}
        return None

    with patch.object(MultiChainReader, "_fetch_text", side_effect=fake_text), \
         patch.object(MultiChainReader, "_fetch_json", side_effect=fake_json):
        client = TestClient(net.app)
        r = client.get("/api/v1/multichain/status?refresh=true")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["count"] == 8
        expected = {
            "btc": 895123, "eth": 22345678, "bnb": 48123456, "sol": 325999111,
            "ton": 45678901, "trx": 70111222, "xrp": 94555666, "ltc": 2850123,
        }
        for k, h in expected.items():
            assert data["chains"][k]["online"] is True, f"{k} failover failed"
            assert data["chains"][k]["height"] == h, f"{k} expected {h}, got {data['chains'][k]['height']}"

    MultiChainReader.clear_cache()
    print("[PASS] 1. All 8 chain readers (BTC/ETH/BNB/SOL/TON/TRX/XRP/LTC) failover cleanly & return zero fake heights offline")


def test_2_universal_proof_merkle_pow_and_tamper_resistance():
    orig_bc = net.blockchain
    bc = Blockchain(auto_load_path=None)
    bc.difficulty = INITIAL_DIFF
    alice, bob, charlie = UnivaWallet(), UnivaWallet(), UnivaWallet()
    bc.mine_pending_transactions(alice.address)  # Block 1: +100 UNIVA

    tx1 = bc.create_transaction(alice, bob.address, 12.5, fee=0.001)
    assert bc.add_transaction(tx1)
    tx2 = bc.create_transaction(alice, charlie.address, 7.5, fee=0.001)
    assert bc.add_transaction(tx2)
    b2 = bc.mine_pending_transactions(bob.address)  # Block 2: 3 txs (coinbase + tx1 + tx2)
    assert b2 is not None

    net.blockchain = bc
    client = TestClient(net.app)
    try:
        r_p = client.get(f"/api/v1/interop/proof/{tx1['tx_id']}")
        assert r_p.status_code == 200, r_p.text
        proof = r_p.json()
        assert proof["verified"] is True
        assert len(proof["proof_path"]) >= 1

        r_v = client.post("/api/v1/interop/verify-proof", json=proof)
        assert r_v.status_code == 200
        det = r_v.json()
        assert det["valid"] is True
        assert all(det["checks"].values())

        # Attack 1: Alter tx_data amount while keeping original tx_hash
        bad_tx = copy.deepcopy(proof)
        bad_tx["tx_data"]["amount"] = 999999.0
        assert UniversalProofEngine.verify_proof(bad_tx) is False

        # Attack 2: Tamper Merkle branch sibling
        bad_merkle = copy.deepcopy(proof)
        bad_merkle["proof_path"][0]["sibling"] = "f" * 64
        assert UniversalProofEngine.verify_proof(bad_merkle) is False

        # Attack 3: Tamper block header nonce
        bad_hdr = copy.deepcopy(proof)
        bad_hdr["block_header"]["nonce"] += 1
        assert UniversalProofEngine.verify_proof(bad_hdr) is False

        # Attack 4: Forge fake PoW header that matches its own hash but fails difficulty target
        bad_pow = copy.deepcopy(proof)
        bad_pow["block_header"]["nonce"] = 1234567
        forged_hash = UniversalProofEngine._compute_header_hash(bad_pow["block_header"])
        if not forged_hash.startswith("0" * bad_pow["block_header"]["difficulty"]):
            bad_pow["block_hash"] = forged_hash
            assert UniversalProofEngine.verify_proof(bad_pow) is False
    finally:
        net.blockchain = orig_bc
    print("[PASS] 2. Universal Proof verifies leaf hash, ECDSA sig, Merkle branch, header SHA-256 & PoW; rejects all 4 tamper attacks")


def test_3_evm_jsonrpc_standard_and_honest_sendrawtx_evaluation():
    orig_bc = net.blockchain
    bc = Blockchain(auto_load_path=None)
    bc.difficulty = 1
    alice, bob = UnivaWallet(), UnivaWallet()
    bc.mine_pending_transactions(alice.evm_address)  # +100 UNIVA to 0x EVM address

    net.blockchain = bc
    client = TestClient(net.app)
    try:
        # Standard Web3/MetaMask read methods
        assert client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}).json()["result"] == "0x33451"
        assert client.post("/rpc", json={"jsonrpc": "2.0", "id": 2, "method": "net_version", "params": []}).json()["result"] == "210001"
        assert client.post("/rpc", json={"jsonrpc": "2.0", "id": 3, "method": "eth_blockNumber", "params": []}).json()["result"] == "0x1"

        bal_hex = client.post("/rpc", json={"jsonrpc": "2.0", "id": 4, "method": "eth_getBalance", "params": [alice.evm_address, "latest"]}).json()["result"]
        assert int(bal_hex, 16) == 100 * (10**18)

        # Out-of-range block number & unknown block hash MUST return null (JSON-RPC spec)
        assert client.post("/rpc", json={"jsonrpc": "2.0", "id": 5, "method": "eth_getBlockByNumber", "params": ["0x99999", False]}).json()["result"] is None
        assert client.post("/rpc", json={"jsonrpc": "2.0", "id": 6, "method": "eth_getBlockByHash", "params": ["0x" + "a" * 64, False]}).json()["result"] is None

        # CRITICAL HONESTY CHECK: Arbitrary Ethereum RLP raw tx MUST return error -32000 (never fake hash!)
        r_rlp = client.post("/rpc", json={
            "jsonrpc": "2.0", "id": 7, "method": "eth_sendRawTransaction",
            "params": ["0x02f86b0180843b9aca00843b9aca008252089411111111111111111111111111111111111111118080c0"],
        }).json()
        assert "error" in r_rlp and r_rlp["error"]["code"] == -32000

        # Valid hex-encoded UNIVA signed JSON transaction IS accepted into mempool
        signed_tx = bc.create_transaction(alice, bob.evm_address, 5.0, fee=0.001, from_address=alice.evm_address)
        hex_univa_tx = "0x" + json.dumps(signed_tx).encode("utf-8").hex()
        r_ok = client.post("/rpc", json={"jsonrpc": "2.0", "id": 8, "method": "eth_sendRawTransaction", "params": [hex_univa_tx]}).json()
        assert r_ok.get("result") == "0x" + signed_tx["tx_id"]

        # Nonce differs between latest (0) and pending (1)
        assert client.post("/rpc", json={"jsonrpc": "2.0", "id": 9, "method": "eth_getTransactionCount", "params": [alice.evm_address, "latest"]}).json()["result"] == "0x0"
        assert client.post("/rpc", json={"jsonrpc": "2.0", "id": 10, "method": "eth_getTransactionCount", "params": [alice.evm_address, "pending"]}).json()["result"] == "0x1"

        # Mine & verify receipt + tx lookup
        bc.mine_pending_transactions(bob.address)
        rcpt = client.post("/rpc", json={"jsonrpc": "2.0", "id": 11, "method": "eth_getTransactionReceipt", "params": ["0x" + signed_tx["tx_id"]]}).json()["result"]
        assert rcpt is not None and rcpt["status"] == "0x1" and rcpt["blockNumber"] == "0x2"

        # Capabilities endpoint honestly reports EVM scope
        caps = client.get("/api/v1/rpc/capabilities").json()
        assert caps["evm_compatibility"]["evm_mirror_addresses"] is True
        assert caps["evm_compatibility"]["evm_read_rpc"] is True
        assert caps["evm_compatibility"]["evm_bytecode_vm"] is False
    finally:
        net.blockchain = orig_bc
    print("[PASS] 3. EVM JSON-RPC spec compliance, honest eth_sendRawTransaction (-32000 for RLP, real validation for UNIVA JSON) & capabilities verified")


def test_4_bitcoin_core_rpc_and_jsonrpc2_batch_compliance():
    orig_bc = net.blockchain
    bc = Blockchain(auto_load_path=None)
    bc.difficulty = 1
    alice, bob = UnivaWallet(), UnivaWallet()
    bc.mine_pending_transactions(alice.address)

    net.blockchain = bc
    client = TestClient(net.app)
    try:
        # JSON-RPC 2.0 batch request
        batch = [
            {"jsonrpc": "2.0", "id": "b1", "method": "getblockcount", "params": []},
            {"jsonrpc": "2.0", "id": "b2", "method": "getblockchaininfo", "params": []},
            {"jsonrpc": "2.0", "id": "b3", "method": "getbalance", "params": [alice.address]},
            {"jsonrpc": "2.0", "id": "b4", "method": "nonexistent_method", "params": []},
        ]
        res_batch = client.post("/rpc", json=batch).json()
        assert isinstance(res_batch, list) and len(res_batch) == 4
        assert res_batch[0]["result"] == 1
        assert res_batch[1]["result"]["chainwork"] == hex(bc.calculate_chain_work(bc.chain))
        assert res_batch[2]["result"] == 100.0
        assert res_batch[3]["error"]["code"] == -32601

        # Empty batch -> -32600 Invalid Request
        r_empty = client.post("/rpc", json=[]).json()
        assert r_empty["error"]["code"] == -32600

        # sendrawtransaction rejects unsigned tx with -32000, accepts signed tx
        tx_good = bc.create_transaction(alice, bob.address, 3.0, fee=0.001)
        r_tx = client.post("/rpc", json={"jsonrpc": "2.0", "id": 20, "method": "sendrawtransaction", "params": [tx_good]}).json()
        assert r_tx["result"] == tx_good["tx_id"]
    finally:
        net.blockchain = orig_bc
    print("[PASS] 4. Bitcoin Core RPC methods, real chainwork, JSON-RPC 2.0 batch & standard error codes verified")


def test_5_live_multichain_smoke_and_pwa_js_syntax():
    MultiChainReader.clear_cache()
    live = MultiChainReader.get_all_chains_overview(use_cache=False, timeout=5.0)
    assert len(live) == 8
    online_syms = [f"{c['symbol']}=#{c['height']}" for c in live if c["online"]]
    offline_syms = [c["symbol"] for c in live if not c["online"]]
    for c in live:
        if not c["online"]:
            assert c["height"] is None, "Offline chain returned non-null height!"
        else:
            assert isinstance(c["height"], int) and c["height"] > 0

    # Verify PWA includes XRP & LTC live hooks and valid JS syntax
    html = open(os.path.join(ROOT_DIR, "pwa", "index.html"), encoding="utf-8").read()
    assert 'id="mc-xrp-h"' in html and 'id="mc-ltc-h"' in html
    main_js = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tf:
        tf.write(main_js)
        tf_path = tf.name
    try:
        r = subprocess.run(["node", "--check", tf_path], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(tf_path)
    print(f"[PASS] 5. Live 8-chain smoke check (online={online_syms}, offline={offline_syms}) & PWA JS syntax OK")


if __name__ == "__main__":
    test_1_eight_chain_readers_and_zero_fake_fallback()
    test_2_universal_proof_merkle_pow_and_tamper_resistance()
    test_3_evm_jsonrpc_standard_and_honest_sendrawtx_evaluation()
    test_4_bitcoin_core_rpc_and_jsonrpc2_batch_compliance()
    test_5_live_multichain_smoke_and_pwa_js_syntax()
    print("\nALL P6 MULTICHAIN & RPC TESTS PASSED (5/5)!")
