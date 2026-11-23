"""
Injects the TRC-20 (TRON USDT) & BEP-20 USDT Bridge & Kasası UI into pwa/index.html.
"""

import sys

def main():
    with open('pwa/index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    print(f"Original size: {len(html)} bytes")

    # Target 1: In view-multichain, replace the old mc-admin-usdt-guide with the full TRC-20 & BEP-20 Gateway Hub
    old_guide = """        <div class="card" id="mc-admin-usdt-guide" style="display:none;margin-top:18px;">
          <div class="card-header">
            <div class="card-title">💱 Çoklu EVM Uyumu ve İlk UNIVA / USDT Likidite Rehberi (AMM)</div>
            <button class="btn btn-metallic btn-sm" onclick="fetchMultichainStatus()">🔄 Canlı Ağları Yenile</button>
          </div>
          <div style="font-size:0.84rem;color:var(--text-muted);line-height:1.65;">
            <p style="margin-bottom:8px;">
              • <strong>Çoklu EVM Uyumu (ETH / BNB / Polygon / Base / Arbitrum):</strong> UNIVA, <code>0x...</code> EVM ayna adresleri ve <code>Chain ID: 210001</code> JSON-RPC ile tüm EVM cüzdanlarına uyumludur.
            </p>
            <p style="margin-bottom:0;">
              • <strong>İlk UNIVA Değeri İçin Hangi Ağda USDT Yatırılmalı?</strong> En düşük işlem ücreti (~$0.05) ve kolay likidite için <strong>BNB Smart Chain (BEP-20 USDT — PancakeSwap)</strong> veya <strong>Base/Arbitrum (ERC-20 USDT)</strong> önerilir. Örneğin <code>10.000 wUNIVA + 1.000 USDT</code> havuzu açıldığında piyasa başlangıç fiyatı otomatik olarak <strong>1 UNIVA = 0.10 USDT</strong> olur. (UNIVA içi Native DEX sayfası şu an protokol içi test havuzudur; dış USDT kabulü için BEP-20 Wrapped UNIVA köprüsü gerekir.)
            </p>
          </div>
        </div>"""

    new_hub = """        <!-- TRC-20 & BEP-20 GERÇEK USDT KÖPRÜSÜ VE KASASI (PREMIUM DUAL-CHAIN GATEWAY) -->
        <div class="card" style="margin-top:20px;border-color:rgba(212, 175, 55, 0.55);box-shadow:0 12px 36px rgba(212, 175, 55, 0.12);">
          <div class="card-header">
            <div class="card-title" style="color:#D4AF37;display:flex;align-items:center;gap:8px;">
              <span>💎</span> <span>TRC-20 & BEP-20 Gerçek USDT Kasası & Köprüsü</span>
            </div>
            <span class="badge badge-live">Canlı Dış USDT Ağları Aktif</span>
          </div>

          <p style="font-size:0.85rem;color:var(--text-muted);line-height:1.6;margin-bottom:16px;">
            Dış dünyadan (Binance, BtcTurk, Paribu, Trust Wallet vb.) <strong>TRON (TRC-20)</strong> veya <strong>BNB Chain (BEP-20)</strong> üzerinden gerçek USDT yatırabilir, anında UNIVA ile takas edebilir ve kazandığınız USDT'leri dış cüzdanınıza çekebilirsiniz.
          </p>

          <!-- DUAL CHAIN SELECTION TABS -->
          <div style="display:flex;gap:10px;margin-bottom:16px;">
            <button type="button" class="btn btn-primary btn-sm" id="trc20-tab-tron" onclick="switchTrc20Tab('tron')" style="flex:1;">
              🔴 TRON Ağı (TRC-20 USDT)
            </button>
            <button type="button" class="btn btn-metallic btn-sm" id="trc20-tab-bnb" onclick="switchTrc20Tab('bnb')" style="flex:1;">
              🟡 BNB Smart Chain (BEP-20 USDT)
            </button>
          </div>

          <!-- TRON (TRC-20) PANEL -->
          <div id="trc20-panel-tron" style="background:rgba(255,255,255,0.7);padding:16px;border-radius:14px;border:1px solid #D0D5DD;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:6px;">
              <div style="font-weight:800;color:#20242B;font-size:0.9rem;">🔴 TRON Resmi USDT Kasası & Yatırma Adresi:</div>
              <span class="badge badge-native">TRC-20 (6 Decimals)</span>
            </div>
            
            <div class="addr-bar" style="margin-bottom:10px;">
              <span id="trc20-vault-addr" class="mono">TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t</span>
              <button class="copy-icon-btn" onclick="copyElemText('trc20-vault-addr', 'TRON Adresi Kopyalandı!')" data-tooltip="TRON Kasasını Panoya Kopyala">📋 Kopyala</button>
            </div>

            <div style="font-size:0.78rem;color:var(--text-muted);line-height:1.5;margin-bottom:12px;">
              • <strong>Sözleşme:</strong> <code class="mono">TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t</code> (Tether USD Official TRON)<br>
              • <strong>İşlem Süresi:</strong> ~1 dakika (TRON DPoS Anlık Onay)
            </div>

            <!-- LIVE BALANCE & INCOMING SCANNER -->
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
              <input class="form-input mono" id="trc20-lookup-input" placeholder="Sorgulanacak TRON Adresini Yapıştırın (T...)" style="flex:1;min-width:220px;font-size:0.84rem;">
              <button class="btn btn-metallic btn-sm" onclick="lookupTronAccountOverview()" data-tooltip="Bu adresteki gerçek TRX ve USDT bakiyesini sorgula">🔍 Bakiye Sorgula</button>
              <button class="btn btn-primary btn-sm" onclick="triggerTrc20DepositCheck()" data-tooltip="Ağdaki gelen transferleri gerçek zamanlı tara">🔄 Transferleri Tara</button>
            </div>
            <div id="trc20-lookup-result" style="display:none;padding:10px 14px;border-radius:10px;background:#F9FAFB;border:1px solid #C5CCD5;font-size:0.84rem;margin-bottom:12px;"></div>
            <div id="trc20-deposits-result" style="display:none;padding:10px 14px;border-radius:10px;background:#F9FAFB;border:1px solid #C5CCD5;font-size:0.84rem;"></div>
          </div>

          <!-- BNB CHAIN (BEP-20) PANEL -->
          <div id="trc20-panel-bnb" style="display:none;background:rgba(255,255,255,0.7);padding:16px;border-radius:14px;border:1px solid #D0D5DD;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:6px;">
              <div style="font-weight:800;color:#20242B;font-size:0.9rem;">🟡 BNB Smart Chain (BEP-20) Yatırma Adresi:</div>
              <span class="badge badge-native">BEP-20 (EVM Mirror)</span>
            </div>
            <div class="addr-bar" style="margin-bottom:10px;">
              <span id="trc20-bnb-addr" class="mono">0x915ee9e3ef45a87a20b6a9aa450ac4d6e7552be3</span>
              <button class="copy-icon-btn" onclick="copyElemText('trc20-bnb-addr', 'BNB Adresi Kopyalandı!')" data-tooltip="BNB Adresini Kopyala">📋 Kopyala</button>
            </div>
            <div style="font-size:0.78rem;color:var(--text-muted);line-height:1.5;">
              • <strong>Sözleşme:</strong> <code class="mono">0x55d398326f99059fF775485246999027B3197955</code> (Binance-Peg BSC-USD)<br>
              • <strong>Komisyon:</strong> ~$0.05 (En ucuz transfer)<br>
              • <strong>EVM Uyumlu:</strong> MetaMask veya Binance'ten doğrudan çekilebilir.
            </div>
          </div>

          <!-- WITHDRAWAL ACTION -->
          <div style="border-top:1px solid var(--border);padding-top:14px;">
            <div style="font-weight:800;color:#20242B;font-size:0.88rem;margin-bottom:8px;">💸 Dış Cüzdana Gerçek USDT Çek (Withdraw):</div>
            <div style="display:flex;gap:10px;flex-wrap:wrap;">
              <input class="form-input mono" id="trc20-withdraw-addr" placeholder="Alıcı TRON Adresi (T...)" style="flex:2;min-width:200px;font-size:0.84rem;">
              <input class="form-input mono" type="number" id="trc20-withdraw-amt" placeholder="Miktar (USDT)" min="1" style="flex:1;min-width:110px;font-size:0.84rem;">
              <button class="btn btn-primary btn-sm" onclick="executeTrc20Withdrawal()" data-tooltip="Belirtilen TRON adresine USDT çekim emri ver">Çekim Talebi Ver</button>
            </div>
            <div id="trc20-withdraw-feedback" style="margin-top:8px;font-size:0.82rem;"></div>
          </div>
        </div>"""

    if old_guide not in html:
        print("ERROR: old_guide not found in html!")
        sys.exit(1)
    html = html.replace(old_guide, new_hub, 1)

    # Target 2: Add JavaScript helper functions for TRC-20 Gateway
    js_anchor = "    async function fetchMultichainStatus() {"
    new_js = """    // ─── TRC-20 & BEP-20 USDT GATEWAY CLIENT LOGIC ───
    function switchTrc20Tab(tab) {
      const pTron = document.getElementById('trc20-panel-tron');
      const pBnb = document.getElementById('trc20-panel-bnb');
      const bTron = document.getElementById('trc20-tab-tron');
      const bBnb = document.getElementById('trc20-tab-bnb');
      if (tab === 'tron') {
        if (pTron) pTron.style.display = 'block';
        if (pBnb) pBnb.style.display = 'none';
        if (bTron) { bTron.className = 'btn btn-primary btn-sm'; }
        if (bBnb) { bBnb.className = 'btn btn-metallic btn-sm'; }
      } else {
        if (pTron) pTron.style.display = 'none';
        if (pBnb) pBnb.style.display = 'block';
        if (bTron) { bTron.className = 'btn btn-metallic btn-sm'; }
        if (bBnb) { bBnb.className = 'btn btn-primary btn-sm'; }
      }
    }

    async function lookupTronAccountOverview() {
      const inp = document.getElementById('trc20-lookup-input');
      const resEl = document.getElementById('trc20-lookup-result');
      if (!inp || !resEl) return;
      const addr = inp.value.trim();
      if (!addr) {
        showToast('Lütfen geçerli bir TRON adresi girin.');
        return;
      }
      resEl.style.display = 'block';
      resEl.innerHTML = '<span style="color:var(--blue);">🔍 TRON blokzinciri ve akıllı sözleşmesi sorgulanıyor...</span>';

      const data = await apiCall('/api/v1/bridge/trc20/account/' + encodeURIComponent(addr));
      if (!data || !data.valid) {
        resEl.innerHTML = `<span style="color:var(--error);">✕ Geçersiz veya bulunamayan TRON adresi: ${escapeHtml(addr)}</span>`;
        return;
      }
      resEl.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
          <div>
            <strong>TRON Adresi:</strong> <span class="mono">${escapeHtml(data.address)}</span><br>
            <strong>EVM Ayna:</strong> <span class="mono">${escapeHtml(data.evm_equivalent)}</span>
          </div>
          <div style="text-align:right;">
            <div style="font-size:1.1rem;font-weight:800;color:var(--success);">${escapeHtml(data.formatted_usdt)}</div>
            <div style="font-size:0.78rem;color:var(--text-muted);">${Number(data.trx_balance || 0).toFixed(4)} TRX</div>
          </div>
        </div>
        <div style="margin-top:6px;font-size:0.75rem;">
          <a href="${escapeHtml(data.explorer_url)}" target="_blank" style="color:var(--blue);text-decoration:none;">TronScan'de İncele ↗</a>
        </div>
      `;
    }

    async function triggerTrc20DepositCheck() {
      const resEl = document.getElementById('trc20-deposits-result');
      if (!resEl) return;
      resEl.style.display = 'block';
      resEl.innerHTML = '<span style="color:var(--blue);">🔄 TRON USDT transferleri taranıyor...</span>';

      const data = await apiCall('/api/v1/bridge/trc20/check-deposits', { method: 'POST' });
      if (!data || data.status !== 'ok') {
        resEl.innerHTML = '<span style="color:var(--text-muted);">Transfer sorgulanamadı veya henüz yeni transfer yok.</span>';
        return;
      }

      const count = data.new_deposits_count || 0;
      const total = (data.total_stats && data.total_stats.stats) ? data.total_stats.stats.total_deposited_usdt : 0;
      let html = `<div style="font-weight:700;color:#20242B;margin-bottom:6px;">✓ Tarama Tamamlandı: ${count} Yeni İşlem | Toplam Kasa: ${Number(total).toLocaleString()} USDT</div>`;

      if (Array.isArray(data.new_deposits) && data.new_deposits.length > 0) {
        html += '<div style="max-height:160px;overflow-y:auto;">';
        data.new_deposits.forEach(d => {
          html += `<div style="font-size:0.78rem;display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #E5E7EB;">
            <span>${escapeHtml(d.from_tron.substring(0,8))}... ➔ <strong>+${d.amount_usdt} USDT</strong></span>
            <span class="badge badge-live">Onaylandı</span>
          </div>`;
        });
        html += '</div>';
      } else {
        html += '<div style="font-size:0.78rem;color:var(--text-muted);">Bekleyen yeni yatırma işlemi tespit edilmedi.</div>';
      }
      resEl.innerHTML = html;
      showToast(`TRON USDT taraması tamamlandı.`);
    }

    async function executeTrc20Withdrawal() {
      const addrInp = document.getElementById('trc20-withdraw-addr');
      const amtInp = document.getElementById('trc20-withdraw-amt');
      const feed = document.getElementById('trc20-withdraw-feedback');
      if (!addrInp || !amtInp || !feed) return;

      const addr = addrInp.value.trim();
      const amt = parseFloat(amtInp.value);

      if (!addr || !addr.startsWith('T') || addr.length !== 34) {
        feed.innerHTML = '<span style="color:var(--error);">Lütfen geçerli bir TRON cüzdan adresi girin (T... ile başlamalı, 34 karakter).</span>';
        return;
      }
      if (isNaN(amt) || amt < 1.0) {
        feed.innerHTML = '<span style="color:var(--error);">Minimum çekim miktarı 1.00 USDT dir.</span>';
        return;
      }

      feed.innerHTML = '<span style="color:var(--blue);">Çekim talebi hazırlanıyor...</span>';
      const uTxt = document.getElementById('header-user-text');
      const uname = uTxt ? uTxt.textContent.trim() : 'Sovereign User';

      const res = await apiCall('/api/v1/bridge/trc20/request-withdrawal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          univa_user: uname,
          destination_tron: addr,
          amount_usdt: amt
        })
      });

      if (!res || res.status !== 'ok') {
        feed.innerHTML = `<span style="color:var(--error);">${escapeHtml((res && res.detail) ? res.detail : 'Çekim talebi reddedildi.')}</span>`;
        return;
      }

      feed.innerHTML = `<span style="color:var(--success);font-weight:700;">✓ Çekim Talebi Alındı! ${amt} USDT (${res.withdrawal.net_amount} Net) sıcak cüzdan kuyruğuna iletildi. Takip No: ${res.withdrawal.withdrawal_id}</span>`;
      addrInp.value = '';
      amtInp.value = '';
      showToast('USDT Çekim talebi başarıyla oluşturuldu.');
    }

"""

    if js_anchor not in html:
        print("ERROR: js_anchor not found in html!")
        sys.exit(1)
    html = html.replace(js_anchor, new_js + "\n    async function fetchMultichainStatus() {", 1)

    with open('pwa/index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Patched successfully! New size: {len(html)} bytes")

if __name__ == '__main__':
    main()
