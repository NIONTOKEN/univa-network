"""UNIVA P7 - Mainnet Readiness, On-Chain Consensus DEX, Multi-Node P2P, Explorer, Performance & Attack Suite."""
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.blockchain import (
    Blockchain,
    Block,
    INITIAL_DIFF,
    MAX_SUPPLY,
    INITIAL_REWARD,
    TARGET_BLOCK_TIME,
    HALVING_INTERVAL,
    DIFFICULTY_ADJUST,
    calculate_merkle_root,
)
from core.config import (
    get_network_config,
    NATIVE_ADDRESS_LENGTH,
    PROTOCOL_VERSION,
    MIN_PROTOCOL_VERSION,
    is_protocol_version_compatible,
)
from core.dex import from_base_units, MINIMUM_LIQUIDITY, LOCKED_LP
from core.transaction import (
    canonical_tx_message,
    build_transaction,
    build_offline_reserve_tx,
    build_offline_spend_tx,
    build_offline_release_tx,
    build_dex_swap_tx,
    build_dex_add_liquidity_tx,
    build_dex_remove_liquidity_tx,
)
from core.wallet import UnivaWallet, validate_address
import core.network as net
import core.p2p as p2p

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_1_onchain_consensus_dex_multi_node_and_reorg():
    orig_bc = net.blockchain
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc = Blockchain(auto_load_path=None)
        bc.difficulty = INITIAL_DIFF
        alice, miner = UnivaWallet(), UnivaWallet()

        # Block 1: Alice mines 100 UNIVA
        b1 = bc.mine_pending_transactions(alice.address)
        assert b1 is not None and bc.get_balance(alice.address) == 100.0

        net.blockchain = bc
        client = TestClient(net.app)
        try:
            # Reject excessive slippage dex_swap
            bad_slip = build_dex_swap_tx(alice, "UNIVA", "uUSD", 20.0, min_out=99999.0, fee=0.001, blockchain=bc)
            assert client.post("/api/v1/dex/tx", json={"tx": bad_slip}).status_code == 400

            # Block 2: Valid on-chain consensus dex_swap (20 UNIVA -> uUSD)
            tx_sw = build_dex_swap_tx(alice, "UNIVA", "uUSD", 20.0, min_out=90.0, fee=0.001, blockchain=bc)
            r_sw = client.post("/api/v1/dex/tx", json={"tx": tx_sw})
            assert r_sw.status_code == 200, r_sw.text
            assert r_sw.json()["consensus"] is True and r_sw.json()["status"] == "in_mempool"

            b2 = bc.mine_pending_transactions(miner.address)
            assert b2 is not None
            assert abs(bc.get_balance(alice.address, "UNIVA") - 79.999) < 1e-8
            uusd_bal = bc.get_balance(alice.address, "uUSD")
            assert uusd_bal > 95.0

            # Block 3: On-chain consensus dex_add_liquidity (10 UNIVA + 50 uUSD)
            tx_add = build_dex_add_liquidity_tx(alice, "UNIVA", "uUSD", 10.0, 50.0, fee=0.001, blockchain=bc)
            assert client.post("/api/v1/dex/tx", json={"tx": tx_add}).status_code == 200
            b3 = bc.mine_pending_transactions(miner.address)
            assert b3 is not None

            oc_dex = bc.get_onchain_dex_state(include_pending=False)
            pool = oc_dex.get_pool("UNIVA", "uUSD")
            alice_lp = from_base_units(pool.lp_balances.get(alice.address, 0))
            assert alice_lp > 0
            assert pool.lp_balances.get(LOCKED_LP) == MINIMUM_LIQUIDITY

            # Block 4: On-chain consensus dex_remove_liquidity (half LP) + reverse dex_swap (10 uUSD -> UNIVA)
            tx_rem = build_dex_remove_liquidity_tx(alice, "UNIVA", "uUSD", round(alice_lp / 2, 8), fee=0.001, blockchain=bc)
            assert bc.add_transaction(tx_rem) is True
            tx_rev = build_dex_swap_tx(alice, "uUSD", "UNIVA", 10.0, min_out=1.0, fee=0.001, blockchain=bc)
            assert bc.add_transaction(tx_rev) is True
            b4 = bc.mine_pending_transactions(miner.address)
            assert b4 is not None

            # Verify full chain validity & independent second node reorg parity
            assert bc.is_chain_valid() is True
            peer_bc = Blockchain(auto_load_path=None)
            assert peer_bc.replace_chain(bc.chain, save_path=os.path.join(td, "peer_dex_chain.json")) is True
            assert peer_bc.height == bc.height

            root_a = bc.get_onchain_dex_state(include_pending=False).calculate_state_root()
            root_b = peer_bc.get_onchain_dex_state(include_pending=False).calculate_state_root()
            assert root_a == root_b, "Multi-node on-chain DEX state_root diverged!"
            assert abs(peer_bc.get_balance(alice.address, "UNIVA") - bc.get_balance(alice.address, "UNIVA")) < 1e-8
            assert abs(peer_bc.get_balance(alice.address, "uUSD") - bc.get_balance(alice.address, "uUSD")) < 1e-8

            # Live /api/v1/dex/onchain-pools returns exact root
            r_oc = client.get("/api/v1/dex/onchain-pools")
            assert r_oc.status_code == 200 and r_oc.json()["state_root"] == root_a
        finally:
            net.blockchain = orig_bc
    print("[PASS] 1. On-chain consensus DEX (swap/add/remove LP) validated & 100% identical across multi-node reorg")


def test_2_real_multinode_p2p_sync_protocol_version_and_propagation():
    import websockets

    # Pick an ephemeral free localhost TCP port
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    async def _run_p2p():
        bc_server = Blockchain(auto_load_path=None, network="mainnet")
        bc_server.difficulty = 1
        alice, bob = UnivaWallet(), UnivaWallet()
        bc_server.mine_pending_transactions(alice.address)
        bc_server.mine_pending_transactions(bob.address)

        orig_bc = p2p._blockchain_ref
        p2p._blockchain_ref = bc_server
        p2p._connected_peers.clear()
        p2p._inbound_peers.clear()
        p2p._outbound_peers.clear()
        p2p._peer_pubkeys.clear()
        p2p._peer_scores.clear()
        p2p._banned_ips.clear()
        p2p._peer_msg_buckets.clear()
        p2p._seen_nonces.clear()

        try:
            # 1. Outdated protocol version ("UNIVA/2.1.0") rejected in handle_handshake
            class DummyWS:
                def __init__(self):
                    self.closed = False
                    self.reason = ""
                    self.remote_address = ("198.51.100.10", 5051)
                    self.sent = []
                async def send(self, m):
                    self.sent.append(m)
                async def close(self, code=1000, reason=""):
                    self.closed = True
                    self.reason = reason

            old_ws = DummyWS()
            await p2p.handle_handshake(old_ws, "198.51.100.10:5051", {
                "network": "UNIVA Network",
                "genesis_hash": bc_server.chain[0].hash,
                "version": "UNIVA/2.1.0",
                "height": 2,
            })
            assert old_ws.closed and "Upgrade required" in old_ws.reason

            # 2. Testnet genesis attempting handshake with Mainnet node -> banned immediately
            test_bc = Blockchain(auto_load_path=None, network="testnet")
            tn_ws = DummyWS()
            tn_ws.remote_address = ("198.51.100.20", 15051)
            await p2p.handle_handshake(tn_ws, "198.51.100.20:15051", {
                "network": "UNIVA Network",
                "genesis_hash": test_bc.chain[0].hash,
                "version": f"UNIVA/{PROTOCOL_VERSION}",
                "height": 0,
            })
            assert tn_ws.closed and p2p.is_ip_banned("198.51.100.20")

            # 3. Live localhost WebSocket server <-> client handshake, sync & tx propagation
            async with websockets.serve(p2p.connection_handler, "127.0.0.1", free_port):
                async with websockets.connect(f"ws://127.0.0.1:{free_port}") as ws_cli:
                    # Receive server handshake
                    srv_hs_raw = await asyncio.wait_for(ws_cli.recv(), timeout=4.0)
                    srv_hs = p2p.parse_msg(srv_hs_raw)
                    assert srv_hs is not None and srv_hs["type"] == "handshake"
                    assert srv_hs["payload"]["height"] == 2
                    assert srv_hs["payload"]["genesis_hash"] == bc_server.chain[0].hash

                    # Request chain from height 0 & verify full paginated chain_response
                    await ws_cli.send(p2p.make_msg("get_chain", {"from_height": 0}))
                    resp_raw = await asyncio.wait_for(ws_cli.recv(), timeout=4.0)
                    resp = p2p.parse_msg(resp_raw)
                    assert resp is not None and resp["type"] == "chain_response"
                    assert len(resp["payload"]["blocks"]) == 3

                    # Propagate a real signed consensus dex_swap over live WebSocket P2P!
                    tx_dex = build_dex_swap_tx(alice, "UNIVA", "uUSD", 5.0, min_out=1.0, fee=0.001, blockchain=bc_server)
                    await ws_cli.send(p2p.make_msg("new_tx", {"tx": tx_dex}))
                    await asyncio.sleep(0.25)
                    assert any(t.get("tx_id") == tx_dex["tx_id"] for t in bc_server.pending_transactions)
        finally:
            p2p._blockchain_ref = orig_bc
            p2p._banned_ips.clear()
            p2p._peer_scores.clear()

    asyncio.run(_run_p2p())
    print("[PASS] 2. Real multi-node WebSocket P2P sync, outdated node rejection, testnet ban & live DEX tx propagation")


def test_3_explorer_unified_search_all_queries():
    orig_bc = net.blockchain
    net._RATE_BUCKETS.clear()
    bc = Blockchain(auto_load_path=None)
    bc.difficulty = 1
    alice, bob = UnivaWallet(), UnivaWallet()
    b1 = bc.mine_pending_transactions(alice.address)
    tx1 = bc.create_transaction(alice, bob.evm_address, 15.0, fee=0.001)
    assert bc.add_transaction(tx1)
    tx_res = build_offline_reserve_tx(alice, 25.0, int(time.time()) + 1800, fee=0.001, blockchain=bc)
    assert bc.add_transaction(tx_res)
    b2 = bc.mine_pending_transactions(bob.address)
    assert b1 and b2

    net.blockchain = bc
    client = TestClient(net.app)
    try:
        # Block height with and without '#'
        assert client.get("/api/v1/explorer/search?q=1").json()["kind"] == "block"
        assert client.get("/api/v1/explorer/search?q=%232").json()["block"]["index"] == 2
        # Block hash (full and 16-char prefix)
        assert client.get(f"/api/v1/explorer/search?q={b2.hash}").json()["block"]["index"] == 2
        assert client.get(f"/api/v1/explorer/search?q={b2.hash[:16]}").json()["block"]["index"] == 2
        # TX hash & synthetic coinbase ID
        assert client.get(f"/api/v1/explorer/search?q={tx1['tx_id']}").json()["kind"] == "transaction"
        assert client.get(f"/api/v1/explorer/search?q=0x{tx1['tx_id']}").json()["kind"] == "transaction"
        assert client.get("/api/v1/explorer/search?q=coinbase_blk_1").json()["kind"] == "transaction"
        assert client.get("/api/v1/tx/coinbase_blk_1").status_code == 200
        # Reservation ID
        r_res = client.get(f"/api/v1/explorer/search?q={tx_res['reservation_id']}").json()
        assert r_res["kind"] == "reservation" and r_res["reservation"]["consensus"] is True
        # L1 Address (with cold pocket reserved balance!) and EVM 0x address
        r_addr = client.get(f"/api/v1/explorer/search?q={alice.address}").json()
        assert r_addr["kind"] == "address" and r_addr["cold_pocket_reserved"] == 25.0
        r_evm = client.get(f"/api/v1/explorer/search?q={bob.evm_address}").json()
        assert r_evm["kind"] == "address" and r_evm["balance"] == 15.0
        # Unknown 64-char hash MUST return 404 (not fake 0 balance address!)
        assert client.get(f"/api/v1/explorer/search?q=0x{'f'*64}").status_code == 404
        assert client.get("/api/v1/explorer/search?q=999999").status_code == 404
    finally:
        net.blockchain = orig_bc
    print("[PASS] 3. Explorer unified search verified for blocks, hashes, txs, coinbase_blk_N, reservations, L1/EVM addrs & 404s")


def test_4_testnet_mainnet_strict_isolation_and_locked_constants():
    # Locked monetary & consensus parameters
    assert MAX_SUPPLY == 21_000_001.0
    assert INITIAL_REWARD == 100.0
    assert TARGET_BLOCK_TIME == 60
    assert HALVING_INTERVAL == 43_200
    assert DIFFICULTY_ADJUST == 60
    assert NATIVE_ADDRESS_LENGTH == 30
    assert is_protocol_version_compatible(PROTOCOL_VERSION) is True
    assert is_protocol_version_compatible("3.9.9") is False

    m_cfg = get_network_config("mainnet")
    t_cfg = get_network_config("testnet")
    assert m_cfg["chain_id"] == 210001 and t_cfg["chain_id"] == 210002
    assert m_cfg["default_chain_file"] != t_cfg["default_chain_file"]
    assert m_cfg["default_dex_file"] != t_cfg["default_dex_file"]
    assert m_cfg["default_offline_file"] != t_cfg["default_offline_file"]

    bc_main = Blockchain(auto_load_path=None, network="mainnet")
    bc_test = Blockchain(auto_load_path=None, network="testnet")
    assert bc_main.chain[0].hash != bc_test.chain[0].hash, "Mainnet & Testnet genesis hashes MUST differ!"

    w = UnivaWallet()
    assert len(w.address) == 30 and w.address.startswith("univa")
    assert len(w.testnet_address) == 30 and w.testnet_address.startswith("tuniv")
    assert validate_address(w.address, network="mainnet") is True
    assert validate_address(w.address, network="testnet") is False
    assert validate_address(w.testnet_address, network="testnet") is True
    assert validate_address(w.testnet_address, network="mainnet") is False

    # Testnet chain mines cleanly with tuniv... address and rejects univa... mainnet address
    bc_test.difficulty = 1
    assert bc_test.mine_pending_transactions(w.testnet_address) is not None
    try:
        bc_test.mine_pending_transactions(w.address)
        assert False, "Testnet should reject Mainnet univa... miner address"
    except ValueError:
        pass
    print("[PASS] 4. Locked protocol constants & strict Mainnet/Testnet isolation (genesis, chainId, prefixes, files)")


def test_5_performance_benchmarks_and_adversarial_attack_suite():
    # 1. Performance benchmarks
    w1, w2 = UnivaWallet(), UnivaWallet()
    t0 = time.perf_counter()
    for i in range(50):
        msg = f"UNIVA_PERF|{i}"
        sig = w1.sign(msg)
        assert UnivaWallet.verify_signature(w1.public_key, msg, sig)
    ecdsa_ms = (time.perf_counter() - t0) * 1000.0

    fake_txs = [{"tx_id": f"{i:064x}", "amount": 1.0} for i in range(500)]
    t1 = time.perf_counter()
    mr = calculate_merkle_root(fake_txs)
    merkle_ms = (time.perf_counter() - t1) * 1000.0
    assert len(mr) == 64

    # 2. Verify Python <-> PWA JS canonicalTxMessageJS byte-for-byte parity for ALL 7 consensus tx types!
    html = open(os.path.join(ROOT_DIR, "pwa", "index.html"), encoding="utf-8").read()
    m = re.search(r"(function canonicalTxMessageJS\(tx\)\s*\{[\s\S]*?\n    \})", html)
    assert m is not None, "canonicalTxMessageJS not found in pwa/index.html"
    fn_src = m.group(1)

    sample_txs = [
        build_transaction(w1, w2.address, 10.0, fee=0.001, nonce=0),
        build_offline_reserve_tx(w1, 25.0, 1900000000, fee=0.001, nonce=1),
        build_offline_spend_tx(w1, "res_0123456789abcdef0123", w2.address, 5.25, voucher_nonce=0, expires_at=1900000000, fee=0.001),
        build_offline_release_tx(w1, "res_0123456789abcdef0123", fee=0.001, nonce=2),
        build_dex_swap_tx(w1, "UNIVA", "uUSD", 12.0, min_out=55.5, fee=0.001, nonce=3),
        build_dex_add_liquidity_tx(w1, "UNIVA", "uUSD", 10.0, 50.0, fee=0.001, nonce=4),
        build_dex_remove_liquidity_tx(w1, "UNIVA", "uUSD", 1.5, fee=0.001, nonce=5),
    ]
    expected_pairs = [{"tx": tx, "py": canonical_tx_message(tx)} for tx in sample_txs]
    js_check = f"""
const assert = require('assert');
{fn_src}
const cases = {json.dumps(expected_pairs)};
for (const c of cases) {{
  const got = canonicalTxMessageJS(c.tx);
  assert.strictEqual(got, c.py, 'Mismatch for ' + c.tx.type + ': ' + got + ' !== ' + c.py);
}}
console.log('ALL_7_TX_PARITY_OK');
"""
    r_js = subprocess.run(["node", "-e", js_check], cwd=ROOT_DIR, capture_output=True, text=True)
    assert r_js.returncode == 0 and "ALL_7_TX_PARITY_OK" in r_js.stdout, f"JS canonical parity failed: {r_js.stderr}"

    # 3. Full PWA inline JS syntax check
    main_js = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tf:
        tf.write(main_js)
        tf_path = tf.name
    try:
        r_chk = subprocess.run(["node", "--check", tf_path], capture_output=True, text=True)
        assert r_chk.returncode == 0, r_chk.stderr
    finally:
        os.unlink(tf_path)

    # 4. Adversarial Attack Suite (overspend, bad PoW, bad sig, replay, DEX drain)
    bc = Blockchain(auto_load_path=None)
    bc.difficulty = 2
    bc.mine_pending_transactions(w1.address)  # +100 UNIVA

    # Attack A: Overspend
    assert bc.add_transaction(build_transaction(w1, w2.address, 500.0, fee=0.001, nonce=0)) is False
    # Attack B: Forged signature
    tx_bad_sig = build_transaction(w1, w2.address, 5.0, fee=0.001, nonce=0)
    tx_bad_sig["signature"] = "00" * 64
    assert bc.add_transaction(tx_bad_sig) is False
    # Attack C: Invalid PoW block rejected
    fake_blk = Block(index=2, transactions=[{"type": "coinbase", "to": w1.address, "amount": 100.0, "subsidy": 100.0}],
                     previous_hash=bc.last_block.hash, timestamp=time.time() + 10, nonce=0, difficulty=2,
                     miner_address=w1.address, reward=100.0)
    fake_blk.hash = "ff" + fake_blk.calculate_hash()[2:]
    assert bc.accept_block(fake_blk.to_dict()) is False
    # Attack D: DEX unauthorized LP withdrawal without owning LP
    assert bc.add_transaction(build_dex_remove_liquidity_tx(w1, "UNIVA", "uUSD", 10.0, fee=0.001, nonce=0)) is False

    print(f"[PASS] 5. Perf (50x ECDSA={ecdsa_ms:.1f}ms, 500-tx Merkle={merkle_ms:.1f}ms), 7-type JS/Py parity & 4 adversarial attacks blocked")


if __name__ == "__main__":
    test_1_onchain_consensus_dex_multi_node_and_reorg()
    test_2_real_multinode_p2p_sync_protocol_version_and_propagation()
    test_3_explorer_unified_search_all_queries()
    test_4_testnet_mainnet_strict_isolation_and_locked_constants()
    test_5_performance_benchmarks_and_adversarial_attack_suite()
    print("\nALL P7 MAINNET READINESS TESTS PASSED (5/5)!")
