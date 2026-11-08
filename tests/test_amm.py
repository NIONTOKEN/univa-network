import pytest
from core.dex import UnivaDEX, MINIMUM_LIQUIDITY, to_base_units


def test_fee_constant_product_and_atomic_slippage():
    dex = UnivaDEX()
    dex.deposit("alice", "UNIVA", to_base_units(1000))
    dex.deposit("alice", "uUSD", to_base_units(5000))
    dex.deposit("bob", "UNIVA", to_base_units(100))
    pool = dex.create_pool("UNIVA", "uUSD", fee_bps=10)
    dex.add_liquidity("alice", "UNIVA", "uUSD", to_base_units(1000), to_base_units(5000))
    before_k = pool.reserve_a * pool.reserve_b
    out, fee = dex.get_amount_out(pool, "UNIVA", to_base_units(100))
    assert fee == to_base_units("0.1")
    assert dex.swap("bob", "UNIVA", "uUSD", to_base_units(100), out) == out
    assert pool.reserve_a * pool.reserve_b >= before_k
    dex.deposit("bob", "UNIVA", to_base_units(1))
    snapshot = (dex.get_balance("bob", "UNIVA"), pool.reserve_a, pool.reserve_b)
    with pytest.raises(ValueError, match="Slippage"):
        dex.swap("bob", "UNIVA", "uUSD", to_base_units(1), to_base_units(1000))
    assert snapshot == (dex.get_balance("bob", "UNIVA"), pool.reserve_a, pool.reserve_b)


def test_locked_minimum_liquidity_cannot_be_removed():
    dex = UnivaDEX()
    dex.deposit("alice", "UNIVA", to_base_units(1000))
    dex.deposit("alice", "uUSD", to_base_units(5000))
    dex.create_pool("UNIVA", "uUSD")
    dex.add_liquidity("alice", "UNIVA", "uUSD", to_base_units(1000), to_base_units(5000))
    with pytest.raises(ValueError, match="permanently locked"):
        dex.remove_liquidity("0x000_LOCKED", "UNIVA", "uUSD", MINIMUM_LIQUIDITY)


def test_reversed_asset_order_keeps_reserves_correct():
    dex = UnivaDEX()
    dex.deposit("alice", "UNIVA", to_base_units(1000))
    dex.deposit("alice", "uUSD", to_base_units(5000))
    pool = dex.create_pool("UNIVA", "uUSD")
    dex.add_liquidity("alice", "uUSD", "UNIVA", to_base_units(5000), to_base_units(1000))
    assert pool.reserve_a == to_base_units(1000)
    assert pool.reserve_b == to_base_units(5000)
    lp = pool.lp_balances["alice"] // 2
    out_uusd, out_univa = dex.remove_liquidity("alice", "uUSD", "UNIVA", lp)
    assert out_uusd > 0 and out_univa > 0
