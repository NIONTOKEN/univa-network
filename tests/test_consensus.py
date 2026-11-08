import copy

from core.blockchain import Blockchain, Block
from core.wallet import UnivaWallet


def test_wallet_signature_and_transaction_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    alice, bob = UnivaWallet(), UnivaWallet()
    chain = Blockchain(auto_load_path=None)
    block = chain.mine_pending_transactions(alice.address)
    assert block is not None
    assert chain.get_balance(alice.address) == 100.0

    tx = chain.create_transaction(alice, bob.address, 2.5, 0.01)
    assert chain.verify_transaction(tx)
    assert chain.add_transaction(tx)
    assert not chain.add_transaction(tx)  # replay / duplicate pending tx rejected
    assert chain.get_balance(bob.address) == 0.0  # unconfirmed incoming funds are not spendable

    tampered = copy.deepcopy(tx)
    tampered["amount"] = 99.0
    assert not chain.add_transaction(tampered)

    mined = chain.mine_pending_transactions(alice.address)
    assert mined is not None
    assert chain.get_balance(bob.address) == 2.5
    assert chain.get_balance(alice.address) == 197.5  # subsidy + returned fee - transfer
    assert chain.is_chain_valid()


def test_reject_invalid_block_and_sync_valid_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    miner = UnivaWallet()
    source = Blockchain(auto_load_path=None)
    target = Blockchain(auto_load_path=None)
    block = source.mine_pending_transactions(miner.address)
    assert block is not None
    bad_hash = block.to_dict()
    bad_hash["hash"] = "f" * 64
    assert not target.accept_block(bad_hash)
    bad = Block.from_dict(block.to_dict())
    bad.reward = 999999
    bad.hash = bad.calculate_hash()
    assert bad.mine(bad.difficulty)
    assert not target.accept_block(bad.to_dict())  # valid PoW cannot authorize excess subsidy
    assert target.height == 0
    assert target.accept_block(block.to_dict())
    assert target.height == 1
    assert target.is_chain_valid()


def test_chain_persists_and_reloads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    miner = UnivaWallet()
    chain = Blockchain(auto_load_path=None)
    chain.mine_pending_transactions(miner.address)
    assert chain.save("test-chain.json")
    restored = Blockchain(auto_load_path=None)
    assert restored.load("test-chain.json")
    assert restored.height == 1
    assert restored.total_mined == 100.0
    assert restored.is_chain_valid()


def test_unsigned_transaction_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chain = Blockchain(auto_load_path=None)
    assert not chain.add_transaction({"from": "alice", "to": "bob", "amount": 1.0})


def test_insufficient_balance_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    alice, bob = UnivaWallet(), UnivaWallet()
    chain = Blockchain(auto_load_path=None)
    tx = chain.create_transaction(alice, bob.address, 1.0, 0.01)
    assert not chain.add_transaction(tx)
