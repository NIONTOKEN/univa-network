"""UNIVA P4 - Native DEX Consensus & L1 State Integration Test Suite."""
import os
import sys
import tempfile
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.blockchain import Blockchain, INITIAL_DIFF
from core.dex import (
    UnivaDEX,
    Pool,
    to_base_units,
    from_base_units,
    MINIMUM_LIQUIDITY,
    LOCKED_LP,
)
from core.wallet import UnivaWallet
import core.network as net


def _make_isolated_env(tmpdir: str):
    bc = Blockchain(auto_load_path=None)
    bc.difficulty = 1
    dex_path = os.path.join(tmpdir, "test_dex_state.json")
    dex = UnivaDEX(blockchain=bc, state_path=dex_path)
    dex.create_pool("UNIVA", "uUSD", fee_bps=10)
    dex.deposit("univa_genesis_vault", "UNIVA", to_base_units(50_000.0))
    dex.deposit("univa_genesis_vault", "uUSD", to_base_units(250_000.0))
    dex.add_liquidity(
        "univa_genesis_vault",
        "UNIVA",
        "uUSD",
        to_base_units(50_000.0),
        to_base_units(250_000.0),
    )
    dex.save(dex_path)
    return bc, dex, dex_path


def test_1_pool_serialization_persistence_and_startup():
    with tempfile.TemporaryDirectory() as td:
        _, dex, dex_path = _make_isolated_env(td)
        pool = dex.get_pool("UNIVA", "uUSD")
        assert pool is not None
        p_dict = pool.to_dict()
        assert p_dict["pool_id"] == "UNIVA/uUSD"
        assert p_dict["reserve_a_float"] == 50_000.0
        assert p_dict["reserve_b_float"] == 250_000.0
        assert p_dict["spot_price_a_in_b"] == 5.0
        restored_pool = Pool.from_dict(p_dict)
        assert restored_pool.to_dict() == p_dict

        root_before = dex.calculate_state_root()
        assert len(root_before) == 64

        reloaded = UnivaDEX(state_path=dex_path)
        assert reloaded.calculate_state_root() == root_before
        assert reloaded.get_pool("UNIVA", "uUSD").reserve_a == to_base_units(50_000.0)

    # Also verify live FastAPI app startup pools endpoint
    client = TestClient(net.app)
    r = client.get("/api/v1/dex/pools")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert len(body["state_root"]) == 64
    assert body["pools"][0]["pool_id"] == "UNIVA/uUSD"
    print("[PASS] 1. Pool.to_dict(), atomic persistence (.bak), deterministic state_root & startup /api/v1/dex/pools")


def test_2_real_l1_balance_separation_and_no_fake_mine_deposit():
    orig_bc, orig_dex = net.blockchain, net.dex_engine
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc, dex, _ = _make_isolated_env(td)
        net.blockchain = bc
        net.dex_engine = dex
        client = TestClient(net.app)
        try:
            miner = UnivaWallet()
            bystander = UnivaWallet()

            # Mining block #1 must ONLY award L1 coinbase subsidy, ZERO fake DEX uUSD/extra UNIVA
            r_mine = client.post(f"/mine/{miner.address}")
            assert r_mine.status_code == 200, r_mine.text
            assert bc.get_balance(miner.address, "UNIVA") == 100.0
            assert dex.get_balance(miner.address, "uUSD") == 0

            # Sandbox deposits stay strictly isolated from real L1/DEX swap balances
            dex.deposit(bystander.address, "UNIVA", to_base_units(999.0), sandbox=True)
            r_bal = client.get(f"/api/v1/dex/balances/{bystander.address}")
            assert r_bal.status_code == 200, r_bal.text
            bal_json = r_bal.json()
            assert bal_json["UNIVA"] == 0.0
            assert bal_json["sandbox_isolated"] is True
            assert bal_json["sandbox_balances"]["UNIVA"] == 999.0

            sig_msg = f"UNIVA_DEX|swap|{bystander.address}|UNIVA|uUSD|10|0|0"
            sig = bystander.sign(sig_msg)
            r_swap = client.post(
                "/api/v1/dex/swap",
                json={
                    "user": bystander.address,
                    "asset_in": "UNIVA",
                    "asset_out": "uUSD",
                    "amount_in": 10,
                    "min_out": 0,
                    "nonce": 0,
                    "public_key": bystander.public_key,
                    "signature": sig,
                },
            )
            assert r_swap.status_code == 400
            assert "Insufficient balance" in r_swap.text
        finally:
            net.blockchain = orig_bc
            net.dex_engine = orig_dex
    print("[PASS] 2. No fake DEX deposit on block mine & strict sandbox isolation enforced")


def test_3_signed_swap_l1_balance_sync_and_fee_invariants():
    orig_bc, orig_dex = net.blockchain, net.dex_engine
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc, dex, _ = _make_isolated_env(td)
        # Keep real INITIAL_DIFF for is_chain_valid() check below
        bc.difficulty = INITIAL_DIFF
        trader = UnivaWallet()
        peer = UnivaWallet()
        blk1 = bc.mine_pending_transactions(trader.address)
        assert blk1 is not None and bc.get_balance(trader.address, "UNIVA") == 100.0

        # Also put a confirmed L1 transfer in block 2 so we verify chain replay stays valid after swap
        tx_out = bc.create_transaction(trader, peer.address, 10.0, fee=0.001)
        assert bc.add_transaction(tx_out)
        blk2 = bc.mine_pending_transactions(peer.address)
        assert blk2 is not None
        pre_swap_univa = bc.get_balance(trader.address, "UNIVA")
        assert abs(pre_swap_univa - 89.999) < 1e-8

        net.blockchain = bc
        net.dex_engine = dex
        client = TestClient(net.app)
        try:
            pool = dex.get_pool("UNIVA", "uUSD")
            k_before = pool.reserve_a * pool.reserve_b

            # Auth guards: private_key forbidden (400), wrong signer rejected (403), tampered amount (401)
            assert client.post("/api/v1/dex/swap", json={"user": trader.address, "private_key": trader.private_key, "amount_in": 10}).status_code == 400
            wrong_sig = peer.sign(f"UNIVA_DEX|swap|{trader.address}|UNIVA|uUSD|20|0|0")
            assert client.post("/api/v1/dex/swap", json={
                "user": trader.address, "asset_in": "UNIVA", "asset_out": "uUSD",
                "amount_in": 20, "min_out": 0, "nonce": 0,
                "public_key": peer.public_key, "signature": wrong_sig,
            }).status_code == 403

            good_msg = f"UNIVA_DEX|swap|{trader.address}|UNIVA|uUSD|20|90|0"
            good_sig = trader.sign(good_msg)
            assert client.post("/api/v1/dex/swap", json={
                "user": trader.address, "asset_in": "UNIVA", "asset_out": "uUSD",
                "amount_in": 25, "min_out": 90, "nonce": 0,
                "public_key": trader.public_key, "signature": good_sig,
            }).status_code == 401

            # Execute real signed swap: 20 UNIVA -> uUSD
            r_ok = client.post("/api/v1/dex/swap", json={
                "user": trader.address, "asset_in": "UNIVA", "asset_out": "uUSD",
                "amount_in": 20, "min_out": 90, "nonce": 0,
                "public_key": trader.public_key, "signature": good_sig,
            })
            assert r_ok.status_code == 200, r_ok.text
            res = r_ok.json()
            assert res["status"] == "success"
            assert res["dex_nonce"] == 1
            got_uusd = res["amount_out"]
            assert got_uusd > 90.0
            assert abs(bc.get_balance(trader.address, "UNIVA") - 69.999) < 1e-8
            assert abs(bc.get_balance(trader.address, "uUSD") - got_uusd) < 1e-8
            assert (pool.reserve_a * pool.reserve_b) >= k_before

            # Double-spend attempt on L1 using already-swapped UNIVA must be blocked
            overspend_tx = bc.create_transaction(trader, peer.address, 75.0, fee=0.001)
            assert bc.verify_transaction(overspend_tx) is False

            # Historical L1 PoW chain validation MUST still pass despite off-block DEX delta
            assert bc.is_chain_valid() is True

            # Replay attack using identical signature must be blocked (409)
            r_replay = client.post("/api/v1/dex/swap", json={
                "user": trader.address, "asset_in": "UNIVA", "asset_out": "uUSD",
                "amount_in": 20, "min_out": 90, "nonce": 0,
                "public_key": trader.public_key, "signature": good_sig,
            })
            assert r_replay.status_code == 409, r_replay.text

            # Reverse signed swap: 50 uUSD -> UNIVA (nonce=1)
            rev_msg = f"UNIVA_DEX|swap|{trader.address}|uUSD|UNIVA|50|5|1"
            rev_sig = trader.sign(rev_msg)
            r_rev = client.post("/api/v1/dex/swap", json={
                "user": trader.address, "asset_in": "uUSD", "asset_out": "UNIVA",
                "amount_in": 50, "min_out": 5, "nonce": 1,
                "public_key": trader.public_key, "signature": rev_sig,
            })
            assert r_rev.status_code == 200, r_rev.text
            rev_json = r_rev.json()
            assert rev_json["dex_nonce"] == 2
            assert abs(bc.get_balance(trader.address, "UNIVA") - (69.999 + rev_json["amount_out"])) < 1e-7
        finally:
            net.blockchain = orig_bc
            net.dex_engine = orig_dex
    print("[PASS] 3. Signed swap syncs real L1 UNIVA balance, preserves x*y>=k, blocks L1 double-spend & signature replay")


def test_4_slippage_protection_and_quote_accuracy():
    orig_bc, orig_dex = net.blockchain, net.dex_engine
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc, dex, _ = _make_isolated_env(td)
        trader = UnivaWallet()
        bc.mine_pending_transactions(trader.address)

        net.blockchain = bc
        net.dex_engine = dex
        client = TestClient(net.app)
        try:
            rq = client.post("/api/v1/dex/quote", json={"asset_in": "UNIVA", "asset_out": "uUSD", "amount_in": 10})
            assert rq.status_code == 200, rq.text
            q = rq.json()
            assert q["fee_bps"] == 10
            assert q["fee_paid"] == 0.01
            assert q["amount_out"] > 0

            pool = dex.get_pool("UNIVA", "uUSD")
            res_before = (pool.reserve_a, pool.reserve_b)
            # Unrealistic min_out violates slippage -> 400 with zero mutation
            bad_min = round(q["amount_out"] * 2, 8)
            sig = trader.sign(f"UNIVA_DEX|swap|{trader.address}|UNIVA|uUSD|10|{bad_min}|0")
            r_slip = client.post("/api/v1/dex/swap", json={
                "user": trader.address, "asset_in": "UNIVA", "asset_out": "uUSD",
                "amount_in": 10, "min_out": bad_min, "nonce": 0,
                "public_key": trader.public_key, "signature": sig,
            })
            assert r_slip.status_code == 400
            assert (pool.reserve_a, pool.reserve_b) == res_before
            assert bc.get_balance(trader.address, "UNIVA") == 100.0
            assert dex.get_user_nonce(trader.address) == 0

            # Excessive price impact blocked by max_slippage_bps
            sig2 = trader.sign(f"UNIVA_DEX|swap|{trader.address}|UNIVA|uUSD|100|0|0")
            r_imp = client.post("/api/v1/dex/swap", json={
                "user": trader.address, "asset_in": "UNIVA", "asset_out": "uUSD",
                "amount_in": 100, "min_out": 0, "max_slippage_bps": 1, "nonce": 0,
                "public_key": trader.public_key, "signature": sig2,
            })
            assert r_imp.status_code == 400
            assert bc.get_balance(trader.address, "UNIVA") == 100.0
        finally:
            net.blockchain = orig_bc
            net.dex_engine = orig_dex
    print("[PASS] 4. Quote fee accuracy (10 bps), min_out slippage revert & max_slippage_bps enforcement")


def test_5_signed_liquidity_add_remove_and_minimum_liquidity_lock():
    orig_bc, orig_dex = net.blockchain, net.dex_engine
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc, dex, dex_path = _make_isolated_env(td)
        lp_provider = UnivaWallet()
        bc.mine_pending_transactions(lp_provider.address)  # +100 UNIVA L1
        dex.deposit(lp_provider.address, "uUSD", to_base_units(100.0))

        net.blockchain = bc
        net.dex_engine = dex
        client = TestClient(net.app)
        try:
            # Unsigned add_liquidity rejected (401)
            assert client.post("/api/v1/dex/liquidity/add", json={
                "user": lp_provider.address, "asset_a": "UNIVA", "asset_b": "uUSD",
                "amount_a": 10, "amount_b": 50,
            }).status_code == 401

            # Signed add_liquidity: 10 UNIVA + 50 uUSD
            add_sig = lp_provider.sign(f"UNIVA_DEX|add_liquidity|{lp_provider.address}|UNIVA|uUSD|10|50|0")
            r_add = client.post("/api/v1/dex/liquidity/add", json={
                "user": lp_provider.address, "asset_a": "UNIVA", "asset_b": "uUSD",
                "amount_a": 10, "amount_b": 50, "nonce": 0,
                "public_key": lp_provider.public_key, "signature": add_sig,
            })
            assert r_add.status_code == 200, r_add.text
            lp_minted = r_add.json()["lp_minted"]
            assert lp_minted > 0
            assert bc.get_balance(lp_provider.address, "UNIVA") == 90.0
            assert bc.get_balance(lp_provider.address, "uUSD") == 50.0

            pool = dex.get_pool("UNIVA", "uUSD")
            assert pool.lp_balances[LOCKED_LP] == MINIMUM_LIQUIDITY

            # Signed remove_liquidity: withdraw all user LP
            rem_sig = lp_provider.sign(f"UNIVA_DEX|remove_liquidity|{lp_provider.address}|UNIVA|uUSD|{lp_minted}|1")
            r_rem = client.post("/api/v1/dex/liquidity/remove", json={
                "user": lp_provider.address, "asset_a": "UNIVA", "asset_b": "uUSD",
                "lp_amount": lp_minted, "nonce": 1,
                "public_key": lp_provider.public_key, "signature": rem_sig,
            })
            assert r_rem.status_code == 200, r_rem.text
            rem_json = r_rem.json()
            assert rem_json["amount_a"] > 9.99 and rem_json["amount_b"] > 49.99
            assert abs(bc.get_balance(lp_provider.address, "UNIVA") - 100.0) < 1e-6
            assert pool.lp_balances[LOCKED_LP] == MINIMUM_LIQUIDITY

            # State survived to disk and reloads cleanly
            reloaded = UnivaDEX(blockchain=bc, state_path=dex_path)
            assert reloaded.get_user_nonce(lp_provider.address) == 2
        finally:
            net.blockchain = orig_bc
            net.dex_engine = orig_dex
    print("[PASS] 5. Signed add/remove liquidity synced with L1 balances, persisted state & MINIMUM_LIQUIDITY lock")


if __name__ == "__main__":
    test_1_pool_serialization_persistence_and_startup()
    test_2_real_l1_balance_separation_and_no_fake_mine_deposit()
    test_3_signed_swap_l1_balance_sync_and_fee_invariants()
    test_4_slippage_protection_and_quote_accuracy()
    test_5_signed_liquidity_add_remove_and_minimum_liquidity_lock()
    print("\nALL P4 DEX TESTS PASSED (5/5)!")
