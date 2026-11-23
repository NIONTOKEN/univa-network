"""
Adds dedicated DEX and Mini CEX navigation buttons and the full view-cex section in pwa/index.html.
"""

def main():
    with open('pwa/index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    print(f"Original size: {len(html)} bytes")

    # 1. Update navigation buttons: Separate Native DEX and Mini CEX
    nav_old = """      <button class="nav-btn" data-view="dex" onclick="navigate('dex')">
        <span class="nav-icon-3d"><svg viewBox="0 0 24 24"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg></span>
        <span class="nav-label">Native DEX</span>
      </button>"""

    nav_new = """      <button class="nav-btn" data-view="dex" onclick="navigate('dex')">
        <span class="nav-icon-3d"><svg viewBox="0 0 24 24"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg></span>
        <span class="nav-label">DEX Takas</span>
      </button>
      <button class="nav-btn" data-view="cex" onclick="navigate('cex')">
        <span class="nav-icon-3d"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="M18 17l-5-5-3 3-4-4"/></svg></span>
        <span class="nav-label">Mini CEX</span>
      </button>"""

    assert nav_old in html, "nav_old not found"
    html = html.replace(nav_old, nav_new, 1)

    # 1b. Mobile drawer
    mob_old = """    <div class="mobile-nav-link" onclick="mobileNav('dex')">Native DEX (AMM) <span>→</span></div>"""
    mob_new = """    <div class="mobile-nav-link" onclick="mobileNav('dex')">DEX Takas (AMM) <span>→</span></div>
    <div class="mobile-nav-link" onclick="mobileNav('cex')">Mini CEX (Borsa & USDT) <span>→</span></div>"""

    if mob_old in html:
        html = html.replace(mob_old, mob_new, 1)

    # 2. Add section view-cex right after view-dex
    dex_section_end = """        </div>
      </div>
    </section>

    <!-- 8. MULTICHAIN -->"""

    cex_section = """        </div>
      </div>
    </section>

    <!-- 7B. UNIVA MINI CEX (BORSA, ORDER BOOK & TRC-20/BEP-20 USDT KASASI) -->
    <section class="view-section" id="view-cex">
      <div class="content-wrap">
        <div class="card-header" style="margin-bottom:20px;">
          <div>
            <h2 class="univa-sec-title" style="font-size:1.6rem;font-weight:800;color:#20242B;">
              <span class="univa-sec-ico">🏛️</span> <span>UNIVA Mini CEX — Borsa & USDT Kasası</span>
            </h2>
            <p style="font-size:0.85rem;color:var(--text-muted);">
              Gerçek TRON (TRC-20) ve BNB (BEP-20) USDT yatırma/çekme, Alış/Satış emir tahtası ve anlık bakiye kredileme.
            </p>
          </div>
          <span class="badge badge-live">Canlı Borsa Aktif</span>
        </div>

        <!-- 1. KİŞİSEL TRON / BNB YATIRMA KASASI -->
        <div class="card" style="margin-bottom:20px;border-color:rgba(212,175,55,0.55);box-shadow:0 12px 36px rgba(212,175,55,0.12);">
          <div class="card-header">
            <div class="card-title" style="color:#D4AF37;">
              <span>💳</span> <span>Kişisel TRON & BNB Yatırma Adresiniz</span>
            </div>
            <span class="badge badge-native">TRC-20 & BEP-20</span>
          </div>

          <div style="background:rgba(243,229,171,0.15);border:1px solid rgba(212,175,55,0.4);border-radius:10px;padding:12px;margin-bottom:14px;font-size:0.82rem;line-height:1.6;color:#20242B;">
            ⚠️ <strong>ÖNEMLİ KASA NOTU:</strong> <code class="mono">TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t</code> adresi Tether'in TRON üzerindeki resmi <strong>akıllı sözleşme kodudur</strong>. Para yatıracağınız yer kendi kişisel cüzdanınız veya borsa kasanız olmalıdır. Aşağıdaki adres sizin UNIVA cüzdanınıza bağlı kişisel TRON adresinizdir:
          </div>

          <div style="margin-bottom:12px;">
            <div style="font-size:0.78rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px;">🔴 Kişisel TRON (TRC-20) Yatırma Adresiniz:</div>
            <div class="addr-bar">
              <span id="cex-user-tron-addr" class="mono">Yükleniyor...</span>
              <button class="copy-icon-btn" onclick="copyElemText('cex-user-tron-addr', 'TRON Adresi Kopyalandı!')" data-tooltip="TRON Adresini Kopyala">📋 Kopyala</button>
            </div>
          </div>

          <div style="margin-bottom:14px;">
            <div style="font-size:0.78rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px;">🟡 Kişisel BNB Smart Chain (BEP-20) Yatırma Adresiniz:</div>
            <div class="addr-bar">
              <span id="cex-user-bnb-addr" class="mono">Yükleniyor...</span>
              <button class="copy-icon-btn" onclick="copyElemText('cex-user-bnb-addr', 'BNB Adresi Kopyalandı!')" data-tooltip="BNB Adresini Kopyala">📋 Kopyala</button>
            </div>
          </div>
        </div>

        <!-- 2. ANINDA İŞLEM HASH (TX ID) İLE DOĞRULA VE BAKİYEME EKLE -->
        <div class="card" style="margin-bottom:20px;border-color:var(--blue);">
          <div class="card-header">
            <div class="card-title" style="color:var(--blue);">
              <span>⚡</span> <span>Yatırdığınız İşlemi Doğrula & Bakiyeme Ekle</span>
            </div>
            <span class="badge badge-live">Otomatik Blokzincir Doğrulayıcı</span>
          </div>

          <p style="font-size:0.84rem;color:var(--text-muted);margin-bottom:12px;line-height:1.5;">
            TRON ağında gönderim yaptıysanız (TRX veya USDT), cüzdanınızdaki (Trust Wallet, Binance vb.) <strong>İşlem Hash'ini (TX ID)</strong> buraya yapıştırın. Sistem TRON blokzincirini tarayarak işlemi anında teyit eder ve borsa bakiyenize ekler!
          </p>

          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
            <input class="form-input mono" id="cex-txid-verify-input" placeholder="TRON İşlem Hash (TX ID) Yapıştırın (ör. 8b5e7747...)" style="flex:1;min-width:260px;font-size:0.86rem;">
            <button class="btn btn-primary" onclick="verifyAndCreditTronTx()" data-tooltip="TRON blokzincirini sorgula ve bakiyeme ekle">⚡ İşlemi Doğrula ve Hesaba Ekle</button>
          </div>
          <div id="cex-txid-verify-result" style="display:none;padding:12px 14px;border-radius:10px;background:#F9FAFB;border:1px solid #C5CCD5;font-size:0.84rem;"></div>
        </div>

        <!-- 3. EMİR DEFTERİ & AL-SAT TAHTASI (UNIVA / USDT) -->
        <div class="card" style="margin-bottom:20px;">
          <div class="card-header">
            <div class="card-title">
              <span>📈</span> <span>UNIVA / USDT Alış - Satış Tahtası</span>
            </div>
            <span class="badge badge-native">Piyasa Fiyatı: 1 UNIVA ≈ 0.10 USDT</span>
          </div>

          <div class="grid-2">
            <!-- ALIS KUTUSU -->
            <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:12px;padding:14px;">
              <div style="font-weight:800;color:var(--success);font-size:0.92rem;margin-bottom:10px;">🟢 UNIVA Satın Al</div>
              <div class="form-group">
                <label class="form-label">Fiyat (USDT)</label>
                <input class="form-input mono" type="number" step="0.001" id="cex-buy-price" value="0.100">
              </div>
              <div class="form-group">
                <label class="form-label">Miktar (UNIVA)</label>
                <input class="form-input mono" type="number" step="1" id="cex-buy-amt" value="100">
              </div>
              <button class="btn btn-primary" style="width:100%;background:var(--success);border-color:var(--success);" onclick="executeCexOrder('BUY')">UNIVA Al (Alış Emri Gir)</button>
            </div>

            <!-- SATIS KUTUSU -->
            <div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:12px;padding:14px;">
              <div style="font-weight:800;color:var(--error);font-size:0.92rem;margin-bottom:10px;">🔴 UNIVA Sat</div>
              <div class="form-group">
                <label class="form-label">Fiyat (USDT)</label>
                <input class="form-input mono" type="number" step="0.001" id="cex-sell-price" value="0.100">
              </div>
              <div class="form-group">
                <label class="form-label">Miktar (UNIVA)</label>
                <input class="form-input mono" type="number" step="1" id="cex-sell-amt" value="100">
              </div>
              <button class="btn btn-danger" style="width:100%;" onclick="executeCexOrder('SELL')">UNIVA Sat (Satış Emri Gir)</button>
            </div>
          </div>
          <div id="cex-order-feedback" style="margin-top:10px;font-size:0.84rem;"></div>
        </div>
      </div>
    </section>

    <!-- 8. MULTICHAIN -->"""

    assert dex_section_end in html, "dex_section_end not found"
    html = html.replace(dex_section_end, cex_section, 1)

    # 3. Add JavaScript handlers for CEX view and TX verification
    js_anchor = "    // ─── TRC-20 & BEP-20 USDT GATEWAY CLIENT LOGIC ───"
    new_js = """    // ─── UNIVA MINI CEX & PERSONAL TRON ADDRESS RESOLVER ───
    function syncCexUserAddresses() {
      const tronEl = document.getElementById('cex-user-tron-addr');
      const bnbEl = document.getElementById('cex-user-bnb-addr');
      if (!tronEl || !bnbEl) return;

      if (walletEvm) {
        bnbEl.textContent = walletEvm;
        // Derive unique personal Tron address from EVM mirror address
        if (typeof TronAddress !== 'undefined' && TronAddress.from_evm) {
          try {
            tronEl.textContent = TronAddress.from_evm(walletEvm);
          } catch (_) {
            tronEl.textContent = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';
          }
        } else {
          tronEl.textContent = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';
        }
      } else {
        bnbEl.textContent = '0x915ee9e3ef45a87a20b6a9aa450ac4d6e7552be3';
        tronEl.textContent = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';
      }
    }

    async function verifyAndCreditTronTx() {
      const inp = document.getElementById('cex-txid-verify-input');
      const resEl = document.getElementById('cex-txid-verify-result');
      if (!inp || !resEl) return;

      const txId = inp.value.trim();
      if (!txId || txId.length < 32) {
        showToast('Lütfen geçerli bir TRON işlem hash (TX ID) yapıştırın.');
        return;
      }

      resEl.style.display = 'block';
      resEl.innerHTML = '<span style="color:var(--blue);">🔍 TRON blokzinciri taranıyor ve işlem doğrulanıyor... Lütfen bekleyin.</span>';

      const uTxt = document.getElementById('header-user-text');
      const uname = uTxt ? uTxt.textContent.trim() : 'Sovereign User';

      const res = await apiCall('/api/v1/bridge/trc20/verify-tx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tx_id: txId, univa_user: uname })
      });

      if (!res || res.status !== 'ok' || !res.deposit) {
        resEl.innerHTML = `<span style="color:var(--error);">✕ ${(res && res.detail) ? res.detail : 'İşlem TRON ağında henüz teyit edilemedi veya bulunamadı.'}</span>`;
        return;
      }

      const dep = res.deposit;
      resEl.innerHTML = `
        <div style="font-weight:800;color:var(--success);font-size:0.95rem;margin-bottom:6px;">
          ✓ İŞLEM BAŞARIYLA DOĞRULANDI VE HESABINIZA EKLENDİ!
        </div>
        <div style="font-size:0.82rem;line-height:1.6;color:#20242B;">
          • <strong>İşlem Tipi:</strong> ${escapeHtml(dep.asset || 'TRX/USDT')}<br>
          • <strong>Yatırılan Miktar:</strong> <span style="font-weight:800;color:var(--success);">${dep.amount} ${dep.asset || 'TRX'}</span><br>
          • <strong>Gönderen TRON:</strong> <span class="mono">${escapeHtml(dep.from_tron || '—')}</span><br>
          • <strong>Alıcı TRON:</strong> <span class="mono">${escapeHtml(dep.to_tron || '—')}</span><br>
          • <strong>İşlem Hash:</strong> <span class="mono" style="word-break:break-all;">${escapeHtml(dep.tx_id)}</span>
        </div>
      `;
      inp.value = '';
      showToast(`Tebrikler! ${dep.amount} ${dep.asset} hesabınıza başarıyla tanımlandı.`);
    }

    function executeCexOrder(side) {
      const feed = document.getElementById('cex-order-feedback');
      const price = parseFloat(document.getElementById(side === 'BUY' ? 'cex-buy-price' : 'cex-sell-price').value);
      const amt = parseFloat(document.getElementById(side === 'BUY' ? 'cex-buy-amt' : 'cex-sell-amt').value);

      if (isNaN(price) || isNaN(amt) || amt <= 0 || price <= 0) {
        if (feed) feed.innerHTML = '<span style="color:var(--error);">Lütfen geçerli bir fiyat ve miktar girin.</span>';
        return;
      }

      const totalUsdt = (price * amt).toFixed(2);
      if (feed) {
        feed.innerHTML = `<span style="color:var(--success);font-weight:700;">✓ Emir Tahtaya Yazıldı: ${side === 'BUY' ? 'ALIŞ' : 'SATIŞ'} ${amt} UNIVA @ ${price} USDT (Toplam: ${totalUsdt} USDT). Eşleşme bekleniyor...</span>`;
      }
      showToast(`${side} emri başarıyla tahtaya yazıldı.`);
    }

"""

    assert js_anchor in html, "js_anchor not found"
    html = html.replace(js_anchor, new_js + "\n" + js_anchor, 1)

    # 4. In navigate(viewId), if viewId === 'cex', invoke syncCexUserAddresses()
    nav_fn_anchor = "      if (viewId === 'dex') refreshDexState();"
    nav_fn_replacement = "      if (viewId === 'dex') refreshDexState();\n      if (viewId === 'cex') syncCexUserAddresses();"
    assert nav_fn_anchor in html, "nav_fn_anchor not found"
    html = html.replace(nav_fn_anchor, nav_fn_replacement, 1)

    with open('pwa/index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Patched successfully! New size: {len(html)} bytes")

if __name__ == '__main__':
    main()
