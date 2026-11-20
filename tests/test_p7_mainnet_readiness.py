"""UNIVA P7 - Mainnet Readiness, On-Chain Consensus DEX, Explorer, Multi-Node, Performance & Attack Suite."""
import asyncio
import json
import os
import re
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
)
from core.config import get_locked_protocol_manifest, get_network_config
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
import core.p2p as p2p
import core.network as net

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _DummyWS:
    def __init__(self, ip: str):
        self.remote_address = (ip, 5051)
        self.sent = []
        self.closed = False

    async def send(self, msg: str):
        self.sent.append(msg)

    async def close(self, code=1000, reason=""):
        self.closed = True


def _reset_p2p_state(bc=None):
    p2p._connected_peers.clear()
    p2p._inbound_peers.clear()
    p2p._outbound_peers.clear()
    p2p._peer_pubkeys.clear()
    p2p._peer_scores.clear()
    p2p._banned_ips.clear()
    p2p._peer_msg_buckets.clear()
    p2p._blockchain_ref = bc


def test_1_locked_protocol_constants_and_mainnet_testnet_isolation():
    manifest = get_locked_protocol_manifest("mainnet")
    assert manifest["project"] == "UNIVA"
    assert manifest["max_supply"] == 21_000_001.0 == MAX_SUPPLY
    assert manifest["initial_reward"] == 100.0 == INITIAL_REWARD
    assert manifest["target_block_time_sec"] == 60 == TARGET_BLOCK_TIME
    assert manifest["halving_interval_blocks"] == 43_200 == HALVING_INTERVAL
    assert manifest["difficulty_adjust_blocks"] == 60 == DIFFICULTY_ADJUST
    assert manifest["native_address_length"] == 30
    assert manifest["chain_id_dec"] == 210001 and manifest["chain_id_hex"] == "0x33451"

    t_manifest = get_locked_protocol_manifest("testnet")
    assert t_manifest["chain_id_dec"] == 210002 and t_manifest["chain_id_hex"] == "0x33452"
    assert t_manifest["address_prefix"] == "tuniva" and t_manifest["is_testnet"] is True

    # Mainnet Genesis hash matches live univa_chain.json Block #0 byte-for-byte
    bc_main = Blockchain(auto_load_path=None, network="mainnet")
    bc_test = Blockchain(auto_load_path=None, network="testnet")
    assert bc_main.chain[0].hash != bc_test.chain[0].hash
    live_chain = json.load(open(os.path.join(ROOT_DIR, "univa_chain.json"), encoding="utf-8"))
    assert live_chain["chain"][0]["hash"] == bc_main.chain[0].hash

    # Address isolation: Testnet tuniva... (30 chars) rejected on Mainnet, Mainnet univa... rejected on Testnet
    w_main = UnivaWallet(network="mainnet")
    w_test = UnivaWallet(network="testnet")
    assert len(w_main.address) == 30 and w_main.address.startswith("univa")
    assert len(w_test.address) == 30 and w_test.address.startswith("tuniva")
    assert validate_address(w_main.address, network="mainnet") is True
    assert validate_address(w_test.address, network="mainnet") is False
    assert validate_address(w_test.address, network="testnet") is True
    assert validate_address(w_main.address, network="testnet") is False

    # Protocol manifest API endpoint
    client = TestClient(net.app)
    r_m = client.get("/api/v1/protocol/manifest")
    assert r_m.status_code == 200
    assert r_m.json()["genesis_hash"] == bc_main.chain[0].hash
    print("[PASS] 1. Locked protocol constants, Mainnet Genesis lock & strict Mainnet/Testnet isolation verified")


def test_2_onchain_consensus_dex_swap_liquidity_slippage_and_reorg():
    orig_bc = net.blockchain
    net._RATE_BUCKETS.clear()
    bc = Blockchain(auto_load_path=None, network="mainnet")
    bc.difficulty = INITIAL_DIFF
    alice, miner = UnivaWallet(), UnivaWallet()
    bc.mine_pending_transactions(alice.address)  # Block 1: +100 UNIVA

    net.blockchain = bc
    client = TestClient(net.app)
    try:
        # 1. Impossible slippage min_out rejected at L1 consensus
        bad_swap = build_dex_swap_tx(alice, "UNIVA", "uUSD", amount_in=10.0, min_out=99999.0, fee=0.001, blockchain=bc)
        assert client.post("/api/v1/dex/tx", json={"tx": bad_swap}).status_code == 400

        # 2. Valid on-chain dex_swap: 20 UNIVA -> uUSD
        swap1 = build_dex_swap_tx(alice, "UNIVA", "uUSD", amount_in=20.0, min_out=90.0, fee=0.001, blockchain=bc)
        r_s1 = client.post("/api/v1/dex/tx", json={"tx": swap1})
        assert r_s1.status_code == 200, r_s1.text
        assert r_s1.json()["status"] == "in_mempool" and r_s1.json()["finalized"] is False
        bc.mine_pending_transactions(miner.address)  # Block 2

        assert abs(bc.get_balance(alice.address, "UNIVA") - 79.999) < 1e-8
        uusd_after_s1 = bc.get_balance(alice.address, "uUSD")
        assert uusd_after_s1 > 99.0

        # 3. On-chain dex_add_liquidity: 10 UNIVA + 50 uUSD
        add_liq = build_dex_add_liquidity_tx(alice, "UNIVA", "uUSD", 10.0, 50.0, fee=0.001, blockchain=bc)
        assert client.post("/api/v1/dex/tx", json={"tx": add_liq}).status_code == 200
        bc.mine_pending_transactions(miner.address)  # Block 3

        sim3, _ = bc.replay_onchain_dex_state(include_pending=False)
        pool3 = sim3.get_pool("UNIVA", "uUSD")
        alice_lp_float = round(pool3.lp_balances[alice.address] / 100_000_000, 8)
        assert alice_lp_float > 0

        # 4. On-chain dex_remove_liquidity: burn half LP + reverse swap uUSD -> UNIVA
        rem_liq = build_dex_remove_liquidity_tx(alice, "UNIVA", "uUSD", round(alice_lp_float / 2, 8), fee=0.001, blockchain=bc)
        assert client.post("/api/v1/dex/tx", json={"tx": rem_liq}).status_code == 200
        bc.mine_pending_transactions(miner.address)  # Block 4

        swap2 = build_dex_swap_tx(alice, "uUSD", "UNIVA", amount_in=20.0, min_out=3.0, fee=0.001, blockchain=bc)
        assert client.post("/api/v1/dex/tx", json={"tx": swap2}).status_code == 200
        bc.mine_pending_transactions(miner.address)  # Block 5

        assert bc.is_chain_valid() is True

        # 5. Independent peer node replays the entire chain and reaches BYTE-FOR-BYTE identical DEX state_root & balances!
        peer_bc = Blockchain(auto_load_path=None, network="mainnet")
        assert peer_bc.replace_chain(bc.chain) is True
        sim_a, _ = bc.replay_onchain_dex_state(include_pending=False)
        sim_b, _ = peer_bc.replay_onchain_dex_state(include_pending=False)
        assert sim_a.calculate_state_root() == sim_b.calculate_state_root()
        assert abs(bc.get_balance(alice.address, "UNIVA") - peer_bc.get_balance(alice.address, "UNIVA")) < 1e-8
        assert abs(bc.get_balance(alice.address, "uUSD") - peer_bc.get_balance(alice.address, "uUSD")) < 1e-8
    finally:
        net.blockchain = orig_bc
    print("[PASS] 2. On-chain consensus dex_swap/add/remove_liquidity, slippage revert & multi-node deterministic replay verified")


def test_3_explorer_unified_search_all_query_types():
    orig_bc = net.blockchain
    net._RATE_BUCKETS.clear()
    bc = Blockchain(auto_load_path=None, network="mainnet")
    bc.difficulty = 1
    alice, bob = UnivaWallet(), UnivaWallet()
    b1 = bc.mine_pending_transactions(alice.address)
    tx1 = bc.create_transaction(alice, bob.evm_address, 5.0, fee=0.001)
    assert bc.add_transaction(tx1)
    b2 = bc.mine_pending_transactions(bob.address)

    net.blockchain = bc
    client = TestClient(net.app)
    try:
        # Height, #height, full block hash, 12-char block hash prefix
        assert client.get("/api/v1/explorer/search?q=0").json()["type"] == "block"
        assert client.get("/api/v1/explorer/search?q=%232").json()["block"]["index"] == 2
        assert client.get(f"/api/v1/explorer/search?q={b2.hash}").json()["block"]["index"] == 2
        assert client.get(f"/api/v1/explorer/search?q={b2.hash[:12]}").json()["block"]["index"] == 2

        # Transfer TX ID, 0x-prefixed TX ID, and clickable coinbase_blk_1
        assert client.get(f"/api/v1/explorer/search?q={tx1['tx_id']}").json()["type"] == "tx"
        assert client.get(f"/api/v1/explorer/search?q=0x{tx1['tx_id']}").json()["tx"]["amount"] == 5.0
        cb_res = client.get("/api/v1/explorer/search?q=coinbase_blk_1").json()
        assert cb_res["type"] == "tx" and cb_res["block_index"] == 1

        # L1 30-char address & EVM 0x address (case-insensitive!)
        r_l1 = client.get(f"/api/v1/explorer/search?q={alice.address}").json()
        assert r_l1["type"] == "address" and abs(r_l1["balance"] - 94.999) < 1e-8
        r_evm = client.get(f"/api/v1/explorer/search?q={bob.evm_address.upper().replace('0X', '0x')}").json()
        assert r_evm["type"] == "address" and abs(r_evm["balance"] - 5.0) < 1e-8

        # Missing queries cleanly return 404
        assert client.get("/api/v1/explorer/search?q=999999").status_code == 404
        assert client.get("/api/v1/explorer/search?q=not_a_valid_query").status_code == 404
    finally:
        net.blockchain = orig_bc
    print("[PASS] 3. Explorer unified search verified across block #, #height, hash/prefix, TX ID, coinbase_blk_N, L1 & EVM 0x addresses")


def test_4_multi_node_p2p_sync_fork_resolution_and_cross_network_ban():
    async def _run():
        _reset_p2p_state(None)
        miner_a, miner_b = UnivaWallet(), UnivaWallet()
        node_a = Blockchain(auto_load_path=None, network="mainnet")
        node_b = Blockchain(auto_load_path=None, network="mainnet")
        node_c = Blockchain(auto_load_path=None, network="mainnet")
        node_test = Blockchain(auto_load_path=None, network="testnet")
        node_a.difficulty = node_b.difficulty = node_c.difficulty = INITIAL_DIFF

        # Node A mines 2 blocks (including an on-chain dex_swap)
        node_a.mine_pending_transactions(miner_a.address)
        sw = build_dex_swap_tx(miner_a, "UNIVA", "uUSD", 10.0, 40.0, 0.001, blockchain=node_a)
        assert node_a.add_transaction(sw)
        node_a.mine_pending_transactions(miner_a.address)

        # Node B mines heavier 4-block competing chain (including offline_reserve + dex_swap)
        node_b.mine_pending_transactions(miner_b.address)
        exp = int(time.time()) + 3600
        res_tx = build_offline_reserve_tx(miner_b, 25.0, exp, 0.001, blockchain=node_b)
        assert node_b.add_transaction(res_tx)
        node_b.mine_pending_transactions(miner_b.address)
        sw_b = build_dex_swap_tx(miner_b, "UNIVA", "uUSD", 15.0, 60.0, 0.001, blockchain=node_b)
        assert node_b.add_transaction(sw_b)
        node_b.mine_pending_transactions(miner_b.address)
        node_b.mine_pending_transactions(miner_b.address)

        try:
            # Cross-network protection: Testnet peer sending handshake to Mainnet Node A is IMMEDIATELY banned
            p2p._blockchain_ref = node_a
            ws_rogue = _DummyWS("198.51.100.77")
            await p2p.handle_handshake(ws_rogue, "198.51.100.77:5051", {
                "network": "UNIVA Testnet",
                "height": node_test.height,
                "genesis_hash": node_test.chain[0].hash,
                "chain_work": node_test.calculate_chain_work(node_test.chain),
            })
            assert ws_rogue.closed is True and p2p.is_ip_banned("198.51.100.77") is True

            # Node A and Node C sync from Node B via P2P get_chain / chain_response
            for target_node, ip in ((node_a, "198.51.100.11"), (node_c, "198.51.100.12")):
                pid = f"{ip}:5051"
                ws_peer = _DummyWS(ip)
                p2p._blockchain_ref = node_b
                await p2p.handle_get_chain(ws_peer, pid, {"from_height": 0, "limit": 100})
                assert ws_peer.sent
                resp = json.loads(ws_peer.sent[-1])
                p2p._blockchain_ref = target_node
                await p2p.handle_chain_response(ws_peer, pid, resp["payload"])
                assert target_node.height == 4
                assert target_node.last_block.hash == node_b.last_block.hash
                assert target_node.is_chain_valid() is True

            sim_a, _ = node_a.replay_onchain_dex_state()
            sim_b, _ = node_b.replay_onchain_dex_state()
            sim_c, _ = node_c.replay_onchain_dex_state()
            assert sim_a.calculate_state_root() == sim_b.calculate_state_root() == sim_c.calculate_state_root()
        finally:
            _reset_p2p_state(None)

    asyncio.run(_run())
    print("[PASS] 4. Multi-node 3-peer P2P sync, heaviest-fork convergence (with DEX+Offline txs) & Testnet->Mainnet handshake ban verified")


def test_5_performance_load_and_attack_fuzzing_suite():
    orig_bc = net.blockchain
    net._RATE_BUCKETS.clear()
    bc = Blockchain(auto_load_path=None, network="mainnet")
    bc.difficulty = 1
    whale = UnivaWallet()
    receivers = [UnivaWallet() for _ in range(10)]
    bc.mine_pending_transactions(whale.address)  # +100 UNIVA

    # 1. Performance & Load: build, sign, verify & insert 100 L1 transfers into mempool + mine block
    t0 = time.perf_counter()
    for i in range(100):
        tx = build_transaction(whale, receivers[i % 10].address, 0.5, fee=0.001, nonce=i)
        assert bc.add_transaction(tx) is True
    blk_load = bc.mine_pending_transactions(receivers[0].address)
    t_mine = time.perf_counter() - t0
    assert blk_load is not None and len(blk_load.transactions) == 101  # 1 coinbase + 100 transfers
    assert t_mine < 15.0, f"Load test too slow: {t_mine:.2f}s"
    assert abs(bc.get_balance(whale.address) - (100.0 - 100 * 0.501)) < 1e-6

    # 2. Consensus Attack Suite
    # 2a) Forged PoW block (hash fails difficulty zeros)
    bc.difficulty = 4
    fake_blk = Block(
        index=bc.height + 1,
        transactions=[{"type": "coinbase", "from": "network_mint", "to": whale.address, "amount": 100.0, "subsidy": 100.0, "fees": 0.0}],
        previous_hash=bc.last_block.hash,
        timestamp=time.time() + 10,
        nonce=0,
        difficulty=4,
        miner_address=whale.address,
        reward=100.0,
    )
    fake_blk.hash = "ffff" + fake_blk.calculate_hash()[4:]
    assert bc.accept_block(fake_blk.to_dict()) is False

    # 2b) Future timestamp attack (+20000s > 7200s limit) & MTP violation
    bc.difficulty = 1
    bad_ts_blk = Block(
        index=bc.height + 1,
        transactions=[{"type": "coinbase", "from": "network_mint", "to": whale.address, "amount": 100.0, "subsidy": 100.0, "fees": 0.0}],
        previous_hash=bc.last_block.hash,
        timestamp=time.time() + 20000,
        difficulty=1,
        miner_address=whale.address,
        reward=100.0,
    )
    bad_ts_blk.mine(1)
    assert bc.accept_block(bad_ts_blk.to_dict()) is False

    # 2c) Over-subsidy minting attack (500 UNIVA instead of 100 UNIVA)
    over_blk = Block(
        index=bc.height + 1,
        transactions=[{"type": "coinbase", "from": "network_mint", "to": whale.address, "amount": 500.0, "subsidy": 500.0, "fees": 0.0}],
        previous_hash=bc.last_block.hash,
        timestamp=max(time.time(), bc.get_median_time_past(11) + 2),
        difficulty=1,
        miner_address=whale.address,
        reward=500.0,
    )
    over_blk.mine(1)
    assert bc.accept_block(over_blk.to_dict()) is False

    # 3. API & JSON-RPC Fuzzing (zero 500 Internal Server Errors!)
    net.blockchain = bc
    client = TestClient(net.app)
    try:
        fuzz_rpcs = [
            {},
            [],
            {"jsonrpc": "2.0", "id": 1, "method": 12345},
            {"jsonrpc": "2.0", "id": 2, "method": "eth_getBalance", "params": []},
            {"jsonrpc": "2.0", "id": 3, "method": "eth_sendRawTransaction", "params": ["0xdeadbeef"]},
            {"jsonrpc": "2.0", "id": 4, "method": "getblockhash", "params": [-5]},
            {"jsonrpc": "2.0", "id": 5, "method": "sendrawtransaction", "params": ["not_a_dict"]},
        ]
        for payload in fuzz_rpcs:
            r = client.post("/rpc", json=payload)
            assert r.status_code == 200 and "error" in r.json(), f"Fuzz failed for {payload}: {r.text}"

        # 50 rapid Explorer queries latency check
        t_exp0 = time.perf_counter()
        for _ in range(50):
            assert client.get(f"/api/v1/explorer/search?q={whale.address}").status_code == 200
        t_exp = time.perf_counter() - t_exp0
        assert t_exp < 10.0
    finally:
        net.blockchain = orig_bc

    # 4. Byte-for-byte Python <-> PWA JS canonicalTxMessageJS parity across ALL 7 consensus tx types!
    html = open(os.path.join(ROOT_DIR, "pwa", "index.html"), encoding="utf-8").read()
    main_js = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tf:
        tf.write(main_js)
        tf_path = tf.name
    try:
        r_chk = subprocess.run(["node", "--check", tf_path], capture_output=True, text=True)
        assert r_chk.returncode == 0, r_chk.stderr
    finally:
        os.unlink(tf_path)

    fn_match = re.search(r"function canonicalTxMessageJS\(tx\)\s*\{[\s\S]*?\n    \}", main_js)
    assert fn_match, "canonicalTxMessageJS not found in pwa/index.html"
    sample_txs = [
        {"type": "transfer", "from": whale.address, "to": receivers[0].address, "amount": 10.0, "fee": 0.001, "nonce": 0, "public_key": whale.public_key},
        {"type": "offline_reserve", "from": whale.address, "amount": 25.5, "fee": 0.001, "nonce": 1, "expires_at": 1800000000, "public_key": whale.public_key},
        {"type": "offline_spend", "reservation_id": "res_1234567890", "from": whale.address, "to": receivers[0].address, "amount": 5.0, "fee": 0.001, "voucher_nonce": 0, "expires_at": 1800000000, "public_key": whale.public_key},
        {"type": "offline_release", "reservation_id": "res_1234567890", "from": whale.address, "fee": 0.001, "nonce": 2, "public_key": whale.public_key},
        {"type": "dex_swap", "from": whale.address, "asset_in": "UNIVA", "asset_out": "uUSD", "amount_in": 10.0, "min_out": 49.5, "fee": 0.001, "nonce": 3, "public_key": whale.public_key},
        {"type": "dex_add_liquidity", "from": whale.address, "asset_a": "UNIVA", "asset_b": "uUSD", "amount_a": 10.0, "amount_b": 50.0, "fee": 0.001, "nonce": 4, "public_key": whale.public_key},
        {"type": "dex_remove_liquidity", "from": whale.address, "asset_a": "UNIVA", "asset_b": "uUSD", "lp_amount": 1.25, "fee": 0.001, "nonce": 5, "public_key": whale.public_key},
    ]
    node_script = fn_match.group(0) + "\nconst txs = " + json.dumps(sample_txs) + ";\nconsole.log(JSON.stringify(txs.map(canonicalTxMessageJS)));"
    r_par = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
    assert r_par.returncode == 0, r_par.stderr
    js_canons = json.loads(r_par.stdout)
    for tx, js_c in zip(sample_txs, js_canons):
        py_c = canonical_tx_message(tx)
        assert py_c == js_c, f"Canonical mismatch for {tx['type']}:\nPY={py_c}\nJS={js_c}"

    print(f"[PASS] 5. Performance (100 signed txs mined in {t_mine:.2f}s), attack/fuzz defense & 7-type Python<->JS canonical parity verified")


if __name__ == "__main__":
    test_1_locked_protocol_constants_and_mainnet_testnet_isolation()
    test_2_onchain_consensus_dex_swap_liquidity_slippage_and_reorg()
    test_3_explorer_unified_search_all_query_types()
    test_4_multi_node_p2p_sync_fork_resolution_and_cross_network_ban()
    test_5_performance_load_and_attack_fuzzing_suite()
    print("\nALL P7 MAINNET READINESS TESTS PASSED (5/5)!")
