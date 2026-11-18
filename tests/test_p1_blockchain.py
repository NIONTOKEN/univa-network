"""UNIVA P1 Blockchain Consensus, Transaction Parity, Difficulty, Max Supply & Reorg Test Suite."""
import copy
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.blockchain import (
    Block,
    Blockchain,
    DIFFICULTY_ADJUST,
    HALVING_INTERVAL,
    INITIAL_REWARD,
    MAX_SUPPLY,
)
from core.transaction import build_transaction, verify_transaction
from core.wallet import UnivaWallet


def test_1_existing_chain_still_valid_and_balances_intact():
    bc = Blockchain(auto_load_path=str(ROOT / "univa_chain.json"))
    assert bc.height >= 345
    assert bc.is_chain_valid() is True, "Existing mainnet/testnet chain MUST stay 100% valid after P1!"
    bal = bc.get_balance("univaf63aua23vxdvcmvkunx66yzh2")
    assert bal > 30000.0
    print(f"[PASS] 1. Existing univa_chain.json valid (height={bc.height}, diff={bc.difficulty}, bal={bal})")


def test_2_transaction_module_and_blockchain_parity():
    bc = Blockchain(auto_load_path=None)
    alice = UnivaWallet.create_new()
    bob = UnivaWallet.create_new()
    bc.mine_pending_transactions(alice.address)

    tx = build_transaction(alice, bob.address, 12.5, fee=0.001, blockchain=bc)
    assert verify_transaction(tx) is True, "core.transaction.verify_transaction failed on own tx"
    assert bc.verify_transaction(tx, include_pending=True) is True, "Blockchain rejected core.transaction tx!"
    assert bc.add_transaction(tx) is True

    # Reverse test: Blockchain.create_transaction accepted by core.transaction.verify_transaction
    tx2 = bc.create_transaction(alice, bob.address, 2.5, fee=0.001)
    assert verify_transaction(tx2) is True, "core.transaction rejected Blockchain.create_transaction tx!"
    assert bc.add_transaction(tx2) is True

    blk = bc.mine_pending_transactions(bob.address)
    assert blk is not None and bc.is_chain_valid() is True
    assert bc.get_balance(bob.address) == 115.002  # 100 reward + 12.5 + 2.5 + 0.002 fees
    print("[PASS] 2. core/transaction.py <-> core/blockchain.py canonical signing & verification 100% unified")


def test_3_mobile_reward_tier_accepted_across_nodes():
    node_a = Blockchain(auto_load_path=None)
    node_b = Blockchain(auto_load_path=None)
    # Sync node_a & node_b genesis
    node_b.chain = [copy.deepcopy(node_a.chain[0])]

    miner = UnivaWallet.create_new()
    mobile_blk = node_a.mine_pending_transactions(miner.address, reward_override=10.0)
    assert mobile_blk is not None and mobile_blk.reward == 10.0
    assert node_b.accept_block(mobile_blk.to_dict()) is True, "accept_block must accept mobile 10.0 UNIVA block!"
    assert node_b.total_mined == 10.0, f"total_mined should be 10.0, got {node_b.total_mined}"
    assert node_b.get_balance(miner.address) == 10.0
    assert node_b.is_chain_valid() is True

    # Reject over-subsidy block (> 100.0)
    bad_blk = copy.deepcopy(mobile_blk)
    bad_blk.index = 2
    bad_blk.previous_hash = node_b.last_block.hash
    bad_blk.reward = 150.0
    bad_blk.transactions[0]["amount"] = 150.0
    bad_blk.transactions[0]["subsidy"] = 150.0
    bad_blk.merkle_root = mobile_blk.merkle_root
    assert node_b.accept_block(bad_blk.to_dict()) is False, "Over-subsidy block must be rejected"
    print("[PASS] 3. Mobile 10.0 UNIVA blocks accepted cleanly by accept_block() & is_chain_valid(); over-subsidy rejected")


def test_4_difficulty_60_block_window_consistency():
    # Build synthetic timestamps checking epoch 60 (idx 1..60) and epoch 120 (idx 60..120 = exact 60 blocks)
    blocks = []
    t0 = 1750000000.0
    for i in range(121):
        # Fast blocks in 1..60 (10s each -> increase), target blocks in 61..120 (60s each -> hold)
        ts = 1735689600.0 if i == 0 else (t0 + (i * 10.0 if i <= 60 else 600.0 + (i - 60) * 60.0))
        blocks.append(Block(index=i, transactions=[], previous_hash="0" * 64, timestamp=ts, difficulty=4))
    d60 = Blockchain._compute_next_difficulty(blocks[:61], 4)
    assert d60 == 5, f"Fast epoch 60 should step 4 -> 5, got {d60}"
    # Window 60..120 has elapsed = 60*60 = 3600s == target -> MUST hold at 5 (whereas buggy i-59 was only 59*60=3540s!)
    span_elapsed = blocks[120].timestamp - blocks[60].timestamp
    assert span_elapsed == 3600.0
    d120 = Blockchain._compute_next_difficulty(blocks[:121], d60)
    assert d120 == 5, f"Exact 60s*60 window at height 120 should stay 5, got {d120}"
    print("[PASS] 4. Exact 60-block retargeting window consistent across epochs 60 and 120")


def test_5_double_spend_nonce_conflict_and_replay_rejected():
    bc = Blockchain(auto_load_path=None)
    alice = UnivaWallet.create_new()
    bob = UnivaWallet.create_new()
    carol = UnivaWallet.create_new()
    bc.mine_pending_transactions(alice.address)

    tx1 = build_transaction(alice, bob.address, 40.0, fee=0.001, nonce=0)
    tx1_conflict = build_transaction(alice, carol.address, 40.0, fee=0.001, nonce=0)
    tx_gap = build_transaction(alice, bob.address, 5.0, fee=0.001, nonce=2)
    tx_overspend = build_transaction(alice, bob.address, 200.0, fee=0.001, nonce=1)

    assert bc.add_transaction(tx1) is True
    assert bc.add_transaction(tx1) is False, "Duplicate mempool TX must be rejected"
    assert bc.add_transaction(tx1_conflict) is False, "Same (from, nonce) double-spend must be rejected"
    assert bc.add_transaction(tx_gap) is False, "Nonce gap must be rejected"
    assert bc.add_transaction(tx_overspend) is False, "Overspend must be rejected"

    blk = bc.mine_pending_transactions(carol.address)
    assert blk is not None
    # Replay of confirmed tx1 must fail
    assert bc.add_transaction(tx1) is False, "Confirmed TX replay must be rejected"
    assert bc.get_balance(bob.address) == 40.0
    print("[PASS] 5. Mempool/block double-spend, same-nonce conflict, nonce gap, overspend & replay rejected")


def test_6_halving_and_max_supply_cap():
    bc = Blockchain(auto_load_path=None)
    assert bc.get_current_reward(1) == INITIAL_REWARD
    assert bc.get_current_reward(HALVING_INTERVAL) == INITIAL_REWARD / 2.0
    assert bc.get_current_reward(HALVING_INTERVAL * 2) == INITIAL_REWARD / 4.0

    # Near cap clamping
    bc.total_mined = MAX_SUPPLY - 12.5
    assert bc.get_current_reward(1) == 12.5
    bc.total_mined = MAX_SUPPLY
    assert bc.get_current_reward(1) == 0.0
    assert bc.mine_pending_transactions(UnivaWallet.create_new().address) is None
    print("[PASS] 6. Halving schedule (43,200 blocks) and MAX_SUPPLY (21,000,001 UNIVA) strictly enforced")


def test_7_fork_resolution_reorg_and_orphaned_tx_recovery():
    bc_main = Blockchain(auto_load_path=None)
    bc_fork = Blockchain(auto_load_path=None)
    bc_fork.chain = [copy.deepcopy(bc_main.chain[0])]

    alice = UnivaWallet.create_new()
    bob = UnivaWallet.create_new()

    # Shared block #1 giving Alice 100 UNIVA
    b1 = bc_main.mine_pending_transactions(alice.address)
    assert bc_fork.accept_block(b1.to_dict()) is True

    # Shorter fork gets mined block #2 with Alice->Bob transfer (height=2)
    tx = build_transaction(alice, bob.address, 25.0, fee=0.001, blockchain=bc_main)
    assert bc_main.add_transaction(tx) is True
    b2 = bc_main.mine_pending_transactions(alice.address)
    assert b2 is not None and bc_main.height == 2
    assert bc_main.get_balance(bob.address) == 25.0

    # Competing heavier fork mines blocks #2, #3, #4 (without Alice->Bob tx!)
    bc_fork.mine_pending_transactions(UnivaWallet.create_new().address)
    bc_fork.mine_pending_transactions(UnivaWallet.create_new().address)
    bc_fork.mine_pending_transactions(UnivaWallet.create_new().address)
    assert bc_fork.height == 4
    assert Blockchain.calculate_chain_work(bc_fork.chain) > Blockchain.calculate_chain_work(bc_main.chain)

    with tempfile.TemporaryDirectory() as td:
        tmp_chain = str(Path(td) / "reorg_chain.json")
        # Shorter weaker chain must NOT replace heavier chain
        assert bc_fork.replace_chain(bc_main.chain, save_path=tmp_chain) is False
        # Heavier valid chain DOES replace shorter fork AND recovers orphaned transfer back to mempool!
        ok = bc_main.replace_chain(bc_fork.chain, save_path=tmp_chain)
        assert ok is True
        assert bc_main.height == 4
        assert bc_main.is_chain_valid() is True
        assert any(t.get("tx_id") == tx["tx_id"] for t in bc_main.pending_transactions), "Orphaned tx must be recovered to mempool!"
    print("[PASS] 7. Fork resolution (replace_chain) adopts heaviest valid chain & recovers orphaned txs")


if __name__ == "__main__":
    test_1_existing_chain_still_valid_and_balances_intact()
    test_2_transaction_module_and_blockchain_parity()
    test_3_mobile_reward_tier_accepted_across_nodes()
    test_4_difficulty_60_block_window_consistency()
    test_5_double_spend_nonce_conflict_and_replay_rejected()
    test_6_halving_and_max_supply_cap()
    test_7_fork_resolution_reorg_and_orphaned_tx_recovery()
    print("\nALL_P1_CONSENSUS_TESTS_PASSED (7/7)")
