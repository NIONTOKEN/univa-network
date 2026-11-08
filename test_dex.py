"""
UNIVA Native DEX - Kapsamli Test Paketi
1. Birim Testleri (Unit Tests)
2. Sabit Carpim & Rezerv Korunumu (Invariant x * y >= k)
3. %0.1 Ucret Dogrulamasi (Fee Math)
4. Fiyat Kaymasi & Slippage Korumasi
5. Guvenlik Senaryolari (Yetersiz Bakiye, Slippage, Ayni Varlik, Kilitli LP)
"""

import sys
sys.path.insert(0, '.')
from core.dex import UnivaDEX, to_base_units, from_base_units, MINIMUM_LIQUIDITY

print("=" * 65)
print("     UNIVA NATIVE DEX - PROTOKOL DOGRULAMA TESTLERI")
print("=" * 65)

dex = UnivaDEX()
ALICE = "univa111111univa"
BOB   = "univa222222univa"

# Test Varliklari
ASSET_UNIVA = "UNIVA"
ASSET_UUSD  = "uUSD"

# 1. Bakiye Doldurma
dex.deposit(ALICE, ASSET_UNIVA, to_base_units(10_000.0))
dex.deposit(ALICE, ASSET_UUSD,  to_base_units(50_000.0))
dex.deposit(BOB,   ASSET_UNIVA, to_base_units(1_000.0))
dex.deposit(BOB,   ASSET_UUSD,  to_base_units(1_000.0))

print("[TEST 1] Havuz Olusturma:")
# Ayni varlikla havuz engellenmeli
try:
    dex.create_pool("UNIVA", "UNIVA")
    assert False, "Ayni varlikla havuz engellenemedi!"
except ValueError:
    print("  OK: Ayni varligin iki kopyasiyla havuz basariyla engellendi.")

pool = dex.create_pool(ASSET_UNIVA, ASSET_UUSD, fee_bps=10) # %0.1
print(f"  OK: Havuz olusturuldu -> {pool.pool_id} (Ucret: %0.1)")

# 2. Ilk Likidite Ekleme (Initial Liquidity)
print("\n[TEST 2] Ilk Likidite ve Kilit Korumasi:")
lp_alice = dex.add_liquidity(
    provider=ALICE,
    asset_a=ASSET_UNIVA,
    asset_b=ASSET_UUSD,
    amount_a=to_base_units(1_000.0), # 1,000 UNIVA
    amount_b=to_base_units(5_000.0), # 5,000 uUSD (Fiyat: 1 UNIVA = 5 uUSD)
)
print(f"  Alice'e verilen LP Token: {from_base_units(lp_alice)}")
print(f"  Kilitlenen Kalici Minimum Likidite: {pool.lp_balances.get('0x000_LOCKED')} base units")
assert pool.lp_balances.get("0x000_LOCKED") == MINIMUM_LIQUIDITY, "Minimum likidite kilitlenmedi!"
assert pool.reserve_a == to_base_units(1_000.0)
assert pool.reserve_b == to_base_units(5_000.0)
print("  OK: Ilk likidite ve kilit payi basariyla muhasebelestirildi.")

# 3. Sabit Carpim ve Takas (Swap & Constant Product Invariant)
print("\n[TEST 3] Takas Motoru & %0.1 Ucret & Rezerv Korunumu:")
k_before = pool.reserve_a * pool.reserve_b

# Bob 100 UNIVA verip uUSD aliyor
amount_in = to_base_units(100.0)
expected_out, fee = dex.get_amount_out(pool, ASSET_UNIVA, amount_in)
print(f"  Girdi: 100 UNIVA -> Beklenen Cikti: {from_base_units(expected_out)} uUSD (Ucret: {from_base_units(fee)} UNIVA)")
assert fee == to_base_units(0.1), "%0.1 fee math is incorrect"

uusd_before = dex.get_balance(BOB, ASSET_UUSD)
actual_out = dex.swap(
    user=BOB,
    asset_in=ASSET_UNIVA,
    asset_out=ASSET_UUSD,
    amount_in=amount_in,
    min_amount_out=expected_out # Sifir kayma toleransi
)
uusd_after = dex.get_balance(BOB, ASSET_UUSD)
assert (uusd_after - uusd_before) == actual_out
print(f"  OK: Takas gerceklesti. Bob {from_base_units(actual_out)} uUSD aldi.")

# Invariant kontrolu: Takas sonrasi k degeri ucretler nedeniyle artmali veya esit kalmali
k_after = pool.reserve_a * pool.reserve_b
assert k_after >= k_before, "Sabit carpim korunamadi (k dustu)!"
print(f"  OK: Sabit Carpim Korumasi Basarili (k_after >= k_before: {k_after >= k_before})")

# 4. Slippage Korumasi Testi
print("\n[TEST 4] Fiyat Kaymasi (Slippage) Korumasi:")
before_slippage_balance = dex.get_balance(BOB, ASSET_UNIVA)
before_slippage_reserves = (pool.reserve_a, pool.reserve_b)
try:
    # Bob 10 UNIVA verip piyasadan fazla (örn 100 uUSD) beklerse islem reddedilmeli
    dex.swap(
        user=BOB,
        asset_in=ASSET_UNIVA,
        asset_out=ASSET_UUSD,
        amount_in=to_base_units(10.0),
        min_amount_out=to_base_units(100.0) # Imkansiz min cikti
    )
    assert False, "Slippage ihlali yakalanamadi!"
except ValueError as e:
    print(f"  OK: Slippage korumasi calisti -> '{e}'")
assert dex.get_balance(BOB, ASSET_UNIVA) == before_slippage_balance
assert (pool.reserve_a, pool.reserve_b) == before_slippage_reserves
print("  OK: Reddedilen takas bakiye ve rezervleri degistirmedi.")

# 5. Yetersiz Bakiye ve Guvenlik Testi
print("\n[TEST 5] Yetersiz Bakiye ve Saldiri Korumasi:")
try:
    # Bob sahip oldugundan fazla parayla takas denerse
    dex.swap(
        user=BOB,
        asset_in=ASSET_UNIVA,
        asset_out=ASSET_UUSD,
        amount_in=to_base_units(999_999.0)
    )
    assert False, "Yetersiz bakiye engellenemedi!"
except ValueError as e:
    print(f"  OK: Yetersiz bakiye basariyla engellendi -> '{e}'")

# 6. Kilitli minimum likidite cekilememeli
print("\n[TEST 6] Kalici Minimum Likidite Kilidi:")
try:
    dex.remove_liquidity("0x000_LOCKED", ASSET_UNIVA, ASSET_UUSD, MINIMUM_LIQUIDITY)
    assert False, "Kilitli minimum LP cekilebildi!"
except ValueError as e:
    print(f"  OK: Minimum likidite cekilemedi -> '{e}'")

# 7. Likidite Cekme Testi
print("\n[TEST 7] Likidite Cekme & Orantisal Pay:")
alice_lp = pool.lp_balances.get(ALICE)
burn_half = alice_lp // 2
withdrawn_a, withdrawn_b = dex.remove_liquidity(
    provider=ALICE,
    asset_a=ASSET_UNIVA,
    asset_b=ASSET_UUSD,
    lp_tokens_to_burn=burn_half
)
print(f"  Alice yarisini yakti -> Cekilen: {from_base_units(withdrawn_a)} UNIVA, {from_base_units(withdrawn_b)} uUSD")
assert withdrawn_a > 0 and withdrawn_b > 0
print("  OK: Likidite basariyla cekildi ve bakiye guncellendi.")

print("=" * 65)
print("     TUM YEREL DEX SIMULASYON TESTLERI GECTI (L1 ENTEGRASYONU DEGIL)")
print("=" * 65)
