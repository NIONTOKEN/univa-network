import re
import sys

def main():
    with open('pwa/index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    print(f"Original size: {len(html)} bytes")

    # 1. Update CSS: Left-docked layout across all sections, frosted glass cards, premium gold widgets, tooltip, user menu
    css_target = """.content-wrap { max-width: 1280px; margin: 0 auto; padding: 32px 24px; width: 100%; position: relative; z-index: 2; }
    .content-wrap > .card-header:first-child {
      background: rgba(255, 255, 255, 0.90);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      padding: 18px 24px;
      border-radius: 16px;
      border: 1px solid rgba(255, 255, 255, 0.72);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.28);
    }

    /* PREMIUM FROSTED CARDS OVER 3D CANOPY STAGE */
    .card {
      background: rgba(255, 255, 255, 0.90);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      border: 1px solid rgba(221, 225, 231, 0.85);
      border-radius: 14px;
      padding: 24px;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.22);
      transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
      position: relative;
    }
    .card:hover { border-color: #C5CCD5; box-shadow: 0 6px 18px rgba(32, 36, 43, 0.06); }"""

    css_replacement = """/* MODERN LEFT-DOCKED COLUMN LAYOUT ACROSS ALL SECTIONS — PRESERVES CLEAR 3D VIEWPORT */
    .content-wrap {
      max-width: 650px;
      margin: 0;
      margin-left: clamp(20px, 4vw, 56px);
      margin-right: auto;
      padding: 24px 14px 80px 14px;
      width: 100%;
      position: relative;
      z-index: 2;
    }
    @media (max-width: 960px) {
      .content-wrap {
        max-width: 100%;
        margin: 0 auto;
        padding: 16px 12px 60px 12px;
      }
    }
    .content-wrap > .card-header:first-child {
      background: rgba(255, 255, 255, 0.88);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      padding: 18px 22px;
      border-radius: 18px;
      border: 1px solid rgba(212, 175, 55, 0.35);
      box-shadow: 0 10px 32px rgba(18, 22, 34, 0.08);
    }

    /* MODERN TRANSLUCENT FROSTED GLASS CARDS (CLEAN & BREATHABLE OVER 3D CANOPY) */
    .card {
      background: rgba(255, 255, 255, 0.85);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(218, 224, 233, 0.88);
      border-radius: 18px;
      padding: 22px 22px;
      box-shadow: 0 12px 36px rgba(18, 24, 38, 0.07);
      transition: all 0.24s cubic-bezier(0.16, 1, 0.3, 1);
      position: relative;
    }
    .card:hover {
      border-color: rgba(212, 175, 55, 0.55);
      box-shadow: 0 14px 40px rgba(212, 175, 55, 0.14), 0 4px 14px rgba(0,0,0,0.04);
      transform: translateY(-1px);
    }"""

    if css_target not in html:
        print("ERROR: css_target not found in html!")
        sys.exit(1)
    html = html.replace(css_target, css_replacement, 1)

    # 1b. Update .univa-hero-inner to dock left as well
    hero_inner_target = """.univa-hero-inner {
      position: relative;
      z-index: 3;
      max-width: 1280px;
      margin: 0 auto;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding-left: 8px;
      pointer-events: none;
    }"""

    hero_inner_replacement = """.univa-hero-inner {
      position: relative;
      z-index: 3;
      max-width: 650px;
      margin: 0;
      margin-left: clamp(20px, 4vw, 56px);
      margin-right: auto;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      padding-left: 0;
      pointer-events: none;
    }
    @media (max-width: 960px) {
      .univa-hero-inner {
        max-width: 100%;
        margin: 0 auto;
        padding: 0 8px;
      }
    }
    .hero-content {
      pointer-events: auto;
      max-width: 580px;
    }"""

    if hero_inner_target not in html:
        print("ERROR: hero_inner_target not found in html!")
        sys.exit(1)
    html = html.replace(hero_inner_target, hero_inner_replacement, 1)

    # 1c. Add CSS for Tooltips, Premium User Pill, Mini Gold Logo, User Dropdown, Auth Tabs
    extra_css = """
    /* ─── PREMIUM GOLD CONTROLS, TOOLTIPS & USER MENU ─── */
    .premium-user-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 6px 14px;
      border-radius: 99px;
      background: linear-gradient(135deg, rgba(255, 255, 255, 0.96) 0%, rgba(254, 250, 238, 0.98) 100%);
      border: 1px solid rgba(212, 175, 55, 0.55);
      color: #20242B;
      font-size: 0.78rem;
      font-weight: 800;
      letter-spacing: 0.3px;
      cursor: pointer;
      box-shadow: 0 2px 10px rgba(212, 175, 55, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.9);
      transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
      position: relative;
      user-select: none;
    }
    .premium-user-pill:hover {
      background: linear-gradient(135deg, #FFFDF8 0%, #FDF7E7 100%);
      border-color: #D4AF37;
      box-shadow: 0 4px 16px rgba(212, 175, 55, 0.35), inset 0 1px 0 #FFFFFF;
      transform: translateY(-1px);
    }
    .mini-gold-univa-icon {
      width: 18px;
      height: 18px;
      display: inline-block;
      flex-shrink: 0;
      filter: drop-shadow(0 1px 2px rgba(212, 175, 55, 0.45));
    }

    /* PREMIUM GOLD LANGUAGE SELECTOR */
    .lang-selector-wrap {
      position: relative;
      display: inline-flex;
      align-items: center;
    }
    .lang-select {
      background: linear-gradient(135deg, rgba(255, 255, 255, 0.96) 0%, rgba(253, 249, 238, 0.98) 100%);
      border: 1px solid rgba(212, 175, 55, 0.5);
      color: #20242B;
      padding: 6px 13px;
      border-radius: 99px;
      font-size: 0.77rem;
      font-weight: 800;
      font-family: inherit;
      cursor: pointer;
      outline: none;
      box-shadow: 0 2px 8px rgba(212, 175, 55, 0.12);
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .lang-select:hover, .lang-select:focus {
      border-color: #D4AF37;
      box-shadow: 0 0 14px rgba(212, 175, 55, 0.32);
      transform: translateY(-1px);
    }

    /* USER DROPDOWN MENU */
    #user-menu-dropdown {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      width: 250px;
      background: rgba(255, 255, 255, 0.98);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid rgba(212, 175, 55, 0.45);
      border-radius: 14px;
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.18), 0 0 12px rgba(212, 175, 55, 0.15);
      padding: 10px;
      display: none;
      flex-direction: column;
      gap: 6px;
      z-index: 2000;
      animation: userMenuPop 0.18s cubic-bezier(0.16, 1, 0.3, 1);
    }
    #user-menu-dropdown.active {
      display: flex;
    }
    @keyframes userMenuPop {
      from { opacity: 0; transform: translateY(-6px) scale(0.96); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .user-menu-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 8px;
      font-size: 0.82rem;
      font-weight: 700;
      color: #20242B;
      cursor: pointer;
      transition: all 0.15s ease;
      border: 1px solid transparent;
      background: transparent;
      text-align: left;
      width: 100%;
    }
    .user-menu-item:hover {
      background: rgba(212, 175, 55, 0.12);
      border-color: rgba(212, 175, 55, 0.35);
      color: #997D3D;
    }
    .user-menu-item.danger:hover {
      background: rgba(220, 38, 38, 0.08);
      border-color: rgba(220, 38, 38, 0.3);
      color: var(--error);
    }

    /* UNIVERSAL FLOATING TOOLTIP */
    #univa-floating-tooltip {
      position: fixed;
      z-index: 999999;
      pointer-events: none;
      background: rgba(18, 22, 34, 0.94);
      color: #F8F9FB;
      border: 1px solid rgba(212, 175, 55, 0.6);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38), 0 0 12px rgba(212, 175, 55, 0.22);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 0.77rem;
      font-weight: 600;
      line-height: 1.35;
      letter-spacing: 0.2px;
      max-width: 290px;
      opacity: 0;
      transform: translateY(4px);
      transition: opacity 0.12s ease, transform 0.12s ease;
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
    }
    #univa-floating-tooltip.visible {
      opacity: 1;
      transform: translateY(0);
    }

    /* AUTH MODAL TABS */
    .vault-tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
    }
    .vault-tab-btn {
      flex: 1;
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 0.82rem;
      font-weight: 700;
      cursor: pointer;
      border: 1px solid #C5CCD5;
      background: #F8F9FA;
      color: #5A6270;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
    .vault-tab-btn.active {
      background: linear-gradient(135deg, rgba(212, 175, 55, 0.16) 0%, rgba(243, 229, 171, 0.12) 100%);
      border-color: #D4AF37;
      color: #20242B;
      box-shadow: 0 2px 8px rgba(212, 175, 55, 0.18);
    }
    .saved-user-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: 99px;
      background: #F4F6F8;
      border: 1px solid #D0D5DD;
      font-size: 0.78rem;
      font-weight: 700;
      color: #20242B;
      cursor: pointer;
      transition: all 0.18s ease;
    }
    .saved-user-chip:hover, .saved-user-chip.selected {
      background: #FFFDF7;
      border-color: #D4AF37;
      color: #997D3D;
      box-shadow: 0 2px 8px rgba(212, 175, 55, 0.2);
    }
"""
    # Insert extra_css before </style>
    style_end = "</style>"
    if style_end not in html:
        print("ERROR: </style> not found in html!")
        sys.exit(1)
    html = html.replace(style_end, extra_css + "\n  </style>", 1)

    # 2. Update Header: Premium User Pill + Mini Gold UNIVA Logo + User Menu Dropdown + Turkish Launch Dashboard
    header_old = """      <div class="net-indicator" id="header-user-pill" style="display:none;background:rgba(35,139,255,0.12);border-color:rgba(35,139,255,0.35);color:var(--metallic-light);cursor:pointer;" onclick="navigate('wallet')" title="Active Vault Identity">
        <span>👤</span>
        <span id="header-user-text">—</span>
      </div>
      <div class="net-indicator" id="header-net-pill">
        <div class="net-dot"></div>
        <span id="header-net-text">Node Syncing...</span>
      </div>
      <button class="btn btn-primary btn-sm header-launch-btn" onclick="navigate('dashboard')">Launch Dashboard</button>"""

    header_new = """      <!-- LUXURY METALLIC GOLD USER ACCOUNT PILL -->
      <div style="position:relative;">
        <div class="premium-user-pill" id="header-user-pill" style="display:none;" onclick="toggleUserMenu()" data-tooltip="Kullanıcı Menüsü: Hesap Değiştir, Çıkış Yap veya Cüzdanı Aç">
          <svg class="mini-gold-univa-icon" viewBox="0 0 24 24" fill="none">
            <defs>
              <linearGradient id="goldMiniIconGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#FDF3CF"/>
                <stop offset="50%" stop-color="#D4AF37"/>
                <stop offset="100%" stop-color="#997D3D"/>
              </linearGradient>
            </defs>
            <path d="M5.5 5.5v7a6.5 6.5 0 0 0 13 0v-7" stroke="url(#goldMiniIconGrad)" stroke-width="2.4" stroke-linecap="round"/>
            <path d="M8.8 5.5v7a3.2 3.2 0 0 0 6.4 0v-7" stroke="url(#goldMiniIconGrad)" stroke-width="2.0" stroke-linecap="round"/>
            <path d="M8 18.5c1.2.7 2.6 1 4 1s2.8-.3 4-1" stroke="url(#goldMiniIconGrad)" stroke-width="1.8" stroke-linecap="round"/>
          </svg>
          <span id="header-user-text">—</span>
          <span style="font-size:0.65rem;opacity:0.6;margin-left:2px;">▼</span>
        </div>
        <!-- USER MANAGEMENT DROPDOWN -->
        <div id="user-menu-dropdown">
          <div style="padding:4px 8px;border-bottom:1px solid var(--border);margin-bottom:4px;">
            <div style="font-size:0.72rem;color:var(--text-muted);text-transform:uppercase;font-weight:700;">Aktif Hesap</div>
            <div id="user-menu-active-name" style="font-size:0.92rem;font-weight:800;color:#20242B;">—</div>
            <div id="user-menu-active-addr" class="mono" style="font-size:0.7rem;color:var(--text-muted);word-break:break-all;">—</div>
          </div>
          <button class="user-menu-item" type="button" onclick="openNewUserModal()">
            <span>✨</span> <span>Yeni Kullanıcı / Cüzdan Ekle</span>
          </button>
          <button class="user-menu-item" type="button" onclick="openSwitchUserModal()">
            <span>🔄</span> <span>Kullanıcı Değiştir</span>
          </button>
          <button class="user-menu-item" type="button" onclick="navigate('wallet');closeUserMenu();">
            <span>🛡️</span> <span>Cüzdan Kasasını Aç</span>
          </button>
          <button class="user-menu-item danger" type="button" onclick="logoutActiveUser()">
            <span>🚪</span> <span>Çıkış Yap (Cüzdanı Kilitle)</span>
          </button>
        </div>
      </div>
      <div class="net-indicator" id="header-net-pill" data-tooltip="UNIVA L1 Düğüm Bağlantısı ve Blok Yüksekliği">
        <div class="net-dot"></div>
        <span id="header-net-text">Node Syncing...</span>
      </div>
      <button class="btn btn-primary btn-sm header-launch-btn" id="header-launch-btn" onclick="navigate('dashboard')" data-tooltip="Operasyon ve Ağ Kontrol Panelini Başlat" data-i18n="Kontrol Paneli">Kontrol Paneli</button>"""

    if header_old not in html:
        print("ERROR: header_old not found in html!")
        sys.exit(1)
    html = html.replace(header_old, header_new, 1)

    # 3. Update Hero Texts & Search Bar & Architectural Pillars to Turkish
    hero_old = """            <div class="hero-tag">Sovereign Layer-1 Blockchain</div>
            <h1 class="hero-title">ONE NETWORK.<br>INFINITE POSSIBILITIES.</h1>
            <p class="hero-desc">
              UNIVA is an independent Layer-1 blockchain infrastructure engineered to unify decentralized networks, global computing power, and sovereign digital value with Bitcoin-grade security and EVM liquidity interoperability.
            </p>
            <div class="hero-buttons">
              <button class="btn btn-primary" onclick="navigate('dashboard')">Explore UNIVA</button>
              <button class="btn btn-metallic" onclick="navigate('network')">Enter Network</button>
              <button class="btn btn-outline" onclick="navigate('core')">Discover Technology</button>
            </div>"""

    hero_new = """            <div class="hero-tag" data-i18n="Egemen Katman-1 Blokzinciri">Egemen Katman-1 Blokzinciri</div>
            <h1 class="hero-title" data-i18n="TEK AĞ.<br>SONSUZ İMKANLAR.">TEK AĞ.<br>SONSUZ İMKANLAR.</h1>
            <p class="hero-desc" data-i18n="UNIVA; merkeziyetsiz ağları, küresel hesaplama gücünü ve egemen dijital değeri Bitcoin seviyesinde güvenlik ve EVM likidite köprüsüyle birleştirmek üzere tasarlanmış bağımsız bir Katman-1 blokzincir altyapısıdır.">
              UNIVA; merkeziyetsiz ağları, küresel hesaplama gücünü ve egemen dijital değeri Bitcoin seviyesinde güvenlik ve EVM likidite köprüsüyle birleştirmek üzere tasarlanmış bağımsız bir Katman-1 blokzincir altyapısıdır.
            </p>
            <div class="hero-buttons">
              <button class="btn btn-primary" onclick="navigate('dashboard')" data-tooltip="Operasyon ve ağ kontrol panelini aç" data-i18n="UNIVA'yı Keşfet">UNIVA'yı Keşfet</button>
              <button class="btn btn-metallic" onclick="navigate('network')" data-tooltip="Eşler ve düğüm haritasına göz at" data-i18n="Ağa Katıl">Ağa Katıl</button>
              <button class="btn btn-outline" onclick="navigate('core')" data-tooltip="Blokzincir çekirdek mimarisini incele" data-i18n="Teknolojiyi İncele">Teknolojiyi İncele</button>
            </div>"""

    if hero_old not in html:
        print("ERROR: hero_old not found in html!")
        sys.exit(1)
    html = html.replace(hero_old, hero_new, 1)

    # 3b. Search bar on home page
    search_old = """        <!-- GOOGLE-STYLE UNIVA EXPLORER SEARCH BAR ON HOME PAGE -->
        <div class="card" style="margin-top:-12px;margin-bottom:28px;padding:22px 26px;border-radius:18px;border:1px solid #C5CCD5;box-shadow:0 8px 28px rgba(32,36,43,0.06);">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px;">
            <div style="font-size:0.86rem;font-weight:800;color:#20242B;display:flex;align-items:center;gap:8px;">
              <span>🔍</span> UNIVA Block Explorer — Instant On-Chain Search
            </div>
            <span class="badge badge-native">Block · Transaction (0x...) · Address (univa... / 0x...)</span>
          </div>
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
            <input class="form-input mono" id="home-explorer-query" style="flex:1;min-width:220px;border-radius:99px;padding:13px 20px;font-size:0.92rem;border:1px solid #C5CCD5;background:#F9FAFB;" placeholder="Enter Block Height (e.g. 62), TX Hash (0x...), or Wallet Address (univa... / 0x...)..." onkeydown="if(event.key==='Enter')executeHomeExplorerSearch()">
            <button class="btn btn-primary" onclick="executeHomeExplorerSearch()" style="border-radius:99px;padding:13px 26px;">Search Explorer</button>
          </div>
        </div>"""

    search_new = """        <!-- GOOGLE-STYLE UNIVA EXPLORER SEARCH BAR ON HOME PAGE -->
        <div class="card" style="margin-top:-12px;margin-bottom:24px;">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px;">
            <div style="font-size:0.86rem;font-weight:800;color:#20242B;display:flex;align-items:center;gap:8px;">
              <span>🔍</span> <span data-i18n="UNIVA Blok Gezgini — Anlık Zincir Üzeri Arama">UNIVA Blok Gezgini — Anlık Zincir Üzeri Arama</span>
            </div>
            <span class="badge badge-native" data-i18n="Blok · İşlem (0x...) · Adres (univa... / 0x...)">Blok · İşlem (0x...) · Adres (univa... / 0x...)</span>
          </div>
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
            <input class="form-input mono" id="home-explorer-query" style="flex:1;min-width:220px;border-radius:99px;padding:13px 20px;font-size:0.92rem;border:1px solid #C5CCD5;background:#F9FAFB;" placeholder="Blok numarası (ör. 62), İşlem Hash (0x...) veya Cüzdan Adresi (univa... / 0x...) yazın..." onkeydown="if(event.key==='Enter')executeHomeExplorerSearch()" data-tooltip="Aranacak Blok No, TX Hash veya Cüzdan Adresi">
            <button class="btn btn-primary" onclick="executeHomeExplorerSearch()" style="border-radius:99px;padding:13px 24px;" data-tooltip="Zincirde arama yap" data-i18n="Gezginde Ara">Gezginde Ara</button>
          </div>
        </div>"""

    if search_old not in html:
        print("ERROR: search_old not found in html!")
        sys.exit(1)
    html = html.replace(search_old, search_new, 1)

    # 4. Update Vault Modal HTML: Add Mode Switcher ("Yeni Kullanıcı" vs "Giriş Yap")
    vault_modal_old = """  <!-- PIN ENCRYPTION MODAL -->
  <div class="modal-overlay" id="vault-modal">
    <div class="modal-content">
      <div class="card-header">
        <div class="card-title" id="vault-modal-title">UNIVA SECURE VAULT</div>
      </div>
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:16px;" id="vault-modal-desc">
        Enter your 4-8 digit security PIN to unlock your encrypted sovereign key.
      </p>
      <div class="form-group">
        <label class="form-label">Username / Kullanıcı Adı</label>
        <input class="form-input" type="text" id="vault-username-input" placeholder="Enter Username (e.g. Kaya)" autocomplete="username" onkeydown="if(event.key==='Enter')document.getElementById('vault-pin-input').focus()">
      </div>
      <div class="form-group">
        <label class="form-label">Security PIN / Şifre (4-8 Digits)</label>
        <input class="form-input mono" type="password" id="vault-pin-input" placeholder="Enter Security PIN (4-8 Digits)" autocomplete="off" spellcheck="false" data-lpignore="true" data-1p-ignore="true" onkeydown="if(event.key==='Enter')submitVaultPin()">
      </div>
      <div id="vault-import-wrap" style="display:none;" class="form-group">
        <label class="form-label">12 Kelimelik Kurtarma İfadesi veya 64 Haneli Özel Anahtar</label>
        <textarea class="form-input mono" id="vault-import-key" rows="3" placeholder="12 kelimenizi aralarında boşluk bırakarak yazın (veya 64 haneli hex anahtar girin)" style="resize:vertical;line-height:1.5;"></textarea>
        <div style="font-size:0.75rem;color:var(--text-muted);margin-top:6px;">
          Aynı 12 kelimeyi hangi cihazda girerseniz girin aynı UNIVA ve 0x EVM cüzdanınız kalıcı olarak açılır.
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;gap:10px;margin-top:18px;flex-wrap:wrap;">
        <button class="btn btn-primary" onclick="submitVaultPin()" style="flex:1;min-width:160px;">Onayla ve Giriş Yap</button>
        <button class="btn btn-metallic" id="vault-import-toggle" onclick="toggleImportMode()">🔑 12 Kelime ile Kurtar</button>
      </div>
    </div>
  </div>"""

    vault_modal_new = """  <!-- PIN ENCRYPTION & MULTI-USER VAULT MODAL -->
  <div class="modal-overlay" id="vault-modal">
    <div class="modal-content" style="max-width:480px;">
      <!-- MODE SWITCHER TABS: YENİ KULLANICI vs GİRİŞ YAP -->
      <div class="vault-tabs">
        <button type="button" class="vault-tab-btn active" id="vault-tab-login" onclick="setVaultAuthMode('login')">
          <span>🔐</span> <span>Giriş Yap (Mevcut Cüzdan)</span>
        </button>
        <button type="button" class="vault-tab-btn" id="vault-tab-new" onclick="setVaultAuthMode('new')">
          <span>✨</span> <span>Yeni Kullanıcı Oluştur</span>
        </button>
      </div>

      <div class="card-header" style="margin-bottom:10px;">
        <div class="card-title" id="vault-modal-title">UNIVA GÜVENLİ CÜZDAN GİRİŞİ</div>
        <button class="btn btn-metallic btn-sm" onclick="closeVaultModalIfUnlocked()" id="vault-close-btn" style="display:none;">✕</button>
      </div>
      <p style="font-size:0.84rem;color:var(--text-muted);margin-bottom:14px;line-height:1.5;" id="vault-modal-desc">
        Kullanıcı adınızı ve güvenlik PIN'inizi girerek cüzdan kilidini açın.
      </p>

      <!-- SAVED USERS SELECTOR (WHEN IN LOGIN MODE) -->
      <div id="vault-saved-users-wrap" style="display:none;margin-bottom:14px;">
        <div style="font-size:0.75rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;margin-bottom:6px;">Kayıtlı Kullanıcılar:</div>
        <div id="vault-saved-users-list" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      </div>

      <div class="form-group">
        <label class="form-label" id="vault-user-label">Kullanıcı Adı</label>
        <input class="form-input" type="text" id="vault-username-input" placeholder="Kullanıcı Adı Girin (ör. Kaya, Ahmet...)" autocomplete="username" onkeydown="if(event.key==='Enter')document.getElementById('vault-pin-input').focus()">
      </div>
      <div class="form-group">
        <label class="form-label" id="vault-pin-label">Güvenlik PIN / Şifre (4-8 Haneli)</label>
        <input class="form-input mono" type="password" id="vault-pin-input" placeholder="4-8 Haneli PIN Kodunuz" autocomplete="off" spellcheck="false" data-lpignore="true" data-1p-ignore="true" onkeydown="if(event.key==='Enter')submitVaultPin()">
      </div>
      <div id="vault-confirm-pin-wrap" style="display:none;" class="form-group">
        <label class="form-label">PIN Kodunu Tekrar Girin</label>
        <input class="form-input mono" type="password" id="vault-pin-confirm" placeholder="PIN Kodunuzu Doğrulayın" autocomplete="off" spellcheck="false" onkeydown="if(event.key==='Enter')submitVaultPin()">
      </div>
      <div id="vault-import-wrap" style="display:none;" class="form-group">
        <label class="form-label">12 Kelimelik Kurtarma İfadesi veya 64 Haneli Özel Anahtar</label>
        <textarea class="form-input mono" id="vault-import-key" rows="3" placeholder="12 kelimenizi aralarında boşluk bırakarak yazın (veya 64 haneli hex anahtar girin)" style="resize:vertical;line-height:1.5;"></textarea>
        <div style="font-size:0.75rem;color:var(--text-muted);margin-top:6px;">
          Aynı 12 kelimeyi hangi cihazda girerseniz girin aynı UNIVA ve 0x EVM cüzdanınız kalıcı olarak açılır.
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;gap:10px;margin-top:16px;flex-wrap:wrap;">
        <button class="btn btn-primary" id="vault-submit-btn" onclick="submitVaultPin()" style="flex:1;min-width:160px;" data-tooltip="İşlemi onayla ve cüzdana devam et">🔓 Giriş Yap</button>
        <button class="btn btn-metallic" id="vault-import-toggle" onclick="toggleImportMode()" data-tooltip="12 Kelimelik gizli tohum veya hex anahtar girerek cüzdanı kurtar">🔑 12 Kelime ile Kurtar</button>
      </div>
    </div>
  </div>"""

    if vault_modal_old not in html:
        print("ERROR: vault_modal_old not found in html!")
        sys.exit(1)
    html = html.replace(vault_modal_old, vault_modal_new, 1)

    # 5. Canopy 3D Particles: Optimize density & crisp golden vector sprites
    # In initHeroCanvas(), reduce COUNT, upgrade vector sprites to 72x72 crisp golden coins
    canopy_old = """      const isMobileInit = window.innerWidth <= 768;
      const COUNT = isMobileInit ? 1550 : 3000;
      const BG_GLYPHS = isMobileInit ? 20 : 36;"""

    canopy_new = """      const isMobileInit = window.innerWidth <= 768;
      // REDUCED DENSITY (~68% fewer particles) FOR RAZOR-SHARP UNIVA LOGO RESOLUTION & BREATHABILITY
      const COUNT = isMobileInit ? 520 : 980;
      const BG_GLYPHS = isMobileInit ? 14 : 24;"""

    if canopy_old not in html:
        print("ERROR: canopy_old not found in html!")
        sys.exit(1)
    html = html.replace(canopy_old, canopy_new, 1)

    # 5b. Upgrade buildVectorSprites to 72x72 crisp golden coins
    sprites_old = """      // Build 5 brightness tiers of crisp UNIVA Logo Leaf Sprites (from deep shadow to blazing champagne platinum)
      const SHADE_PALETTE = [
        [44, 39, 31],     // 0: deep bronze-obsidian shadow
        [106, 94, 70],    // 1: muted antique bronze
        [176, 157, 114],  // 2: brushed gold-silver midtone
        [232, 212, 162],  // 3: warm champagne gold
        [252, 245, 222]   // 4: blazing platinum-ivory ridge highlight
      ];

      function buildVectorSprites() {
        return SHADE_PALETTE.map(([r, g, b]) => {
          const off = document.createElement('canvas');
          off.width = 48; off.height = 48;
          const octx = off.getContext('2d');
          octx.translate(24, 24);
          octx.strokeStyle = `rgb(${r},${g},${b})`;
          octx.lineCap = 'round';
          octx.lineJoin = 'round';
          // Outer U arc
          octx.lineWidth = 4.2;
          octx.beginPath();
          octx.moveTo(-13, -13); octx.lineTo(-13, 2);
          octx.arc(0, 2, 13, Math.PI, 0, true);
          octx.lineTo(13, -13);
          octx.stroke();
          // Inner U arc
          octx.lineWidth = 3.4;
          octx.beginPath();
          octx.moveTo(-6.2, -13); octx.lineTo(-6.2, 2);
          octx.arc(0, 2, 6.2, Math.PI, 0, true);
          octx.lineTo(6.2, -13);
          octx.stroke();
          // Sovereign base crescent arc
          octx.lineWidth = 2.8;
          octx.beginPath();
          octx.arc(0, 17.5, 9, Math.PI * 1.15, Math.PI * 1.85, false);
          octx.stroke();
          return off;
        });
      }"""

    sprites_new = """      // HIGH-CONTRAST GOLDEN PALETTE (DEEP BURNISHED BRONZE TO BLAZING CHAMPAGNE PLATINUM)
      const SHADE_PALETTE = [
        [90, 72, 34],     // 0: deep burnished bronze shadow
        [155, 126, 56],   // 1: rich antique gold
        [214, 175, 55],   // 2: brilliant sovereign gold (#D4AF37)
        [245, 224, 145],  // 3: warm champagne gold
        [255, 248, 225]   // 4: blazing platinum highlight
      ];

      // RENDER CRISP, HIGH-DEFINITION 72x72 UNIVA LOGO EMBLEM SPRITES (CLEAR GAP & SOVEREIGN CRESCENT)
      function buildVectorSprites() {
        return SHADE_PALETTE.map(([r, g, b], idx) => {
          const off = document.createElement('canvas');
          off.width = 72; off.height = 72;
          const octx = off.getContext('2d');
          octx.translate(36, 36);

          // Subtle metallic glow on higher tiers
          if (idx >= 3) {
            octx.shadowColor = `rgba(${r},${g},${b},0.4)`;
            octx.shadowBlur = 8;
          }

          octx.strokeStyle = `rgb(${r},${g},${b})`;
          octx.lineCap = 'round';
          octx.lineJoin = 'round';

          // Outer U arc — razor sharp
          octx.lineWidth = 5.2;
          octx.beginPath();
          octx.moveTo(-18, -17);
          octx.lineTo(-18, 2);
          octx.arc(0, 2, 18, Math.PI, 0, true);
          octx.lineTo(18, -17);
          octx.stroke();

          // Inner U arc — crisp definition
          octx.lineWidth = 4.2;
          octx.beginPath();
          octx.moveTo(-9, -17);
          octx.lineTo(-9, 2);
          octx.arc(0, 2, 9, Math.PI, 0, true);
          octx.lineTo(9, -17);
          octx.stroke();

          // Sovereign base crescent arc — clear gap
          octx.lineWidth = 3.6;
          octx.beginPath();
          octx.arc(0, 24, 12, Math.PI * 1.18, Math.PI * 1.82, false);
          octx.stroke();

          return off;
        });
      }"""

    if sprites_old not in html:
        print("ERROR: sprites_old not found in html!")
        sys.exit(1)
    html = html.replace(sprites_old, sprites_new, 1)

    # 5c. Size and draw adjustments in draw()
    draw_size_old = """          pr.size = (5.2 + 5.6 * (pt.sSize + (pt.tSize - pt.sSize) * ease)) * depth * (0.45 + 0.55);
          pr.shadeIdx = Math.min(4, Math.floor(shade * 5));
          pr.alpha = Math.min(1, 0.38 + shade * 0.62);
          pr.rot = (pt.sTilt + (pt.tTilt - pt.sTilt) * ease) * 0.35 + vortex * (Math.cos(pt.phase) * 1.6) + Math.sin(t * 1.1 + pt.phase) * 0.14;
        }

        // Depth sort back-to-front for dramatic 3D Panokod depth
        projected.sort((a, b) => a.z - b.z);

        // Self-occlusion shadow core inside tree crown so inner crevices stay deeply obsidian
        if (currentShape === 'tree' && morphProgress > 0.72) {
          const coreShade = ctx.createRadialGradient(viewShiftX, viewShiftY - scale * 0.06, scale * 0.05, viewShiftX, viewShiftY - scale * 0.06, scale * 0.85);
          coreShade.addColorStop(0, `rgba(7, 9, 13, ${(0.88 * (morphProgress - 0.72) / 0.28).toFixed(2)})`);
          coreShade.addColorStop(1, 'rgba(7, 9, 13, 0)');
          ctx.fillStyle = coreShade;
          ctx.beginPath();
          ctx.arc(viewShiftX, viewShiftY - scale * 0.06, scale * 0.85, 0, Math.PI * 2);
          ctx.fill();
        }

        for (let i = 0; i < COUNT; i++) {
          const item = projected[i];
          const sprite = leafSprites[item.shadeIdx];
          const half = item.size * 0.65;"""

    draw_size_new = """          // LARGER & CRISPER EMBLEM SIZING WITH CLEAN SPACING
          pr.size = (9.2 + 8.4 * (pt.sSize + (pt.tSize - pt.sSize) * ease)) * depth;
          pr.shadeIdx = Math.min(4, Math.floor(shade * 5));
          pr.alpha = Math.min(1, 0.44 + shade * 0.56);
          pr.rot = (pt.sTilt + (pt.tTilt - pt.sTilt) * ease) * 0.35 + vortex * (Math.cos(pt.phase) * 1.6) + Math.sin(t * 1.1 + pt.phase) * 0.14;
        }

        // Depth sort back-to-front for dramatic 3D Panokod depth
        projected.sort((a, b) => a.z - b.z);

        // Self-occlusion shadow core inside tree crown so inner crevices stay deeply obsidian
        if (currentShape === 'tree' && morphProgress > 0.72) {
          const coreShade = ctx.createRadialGradient(viewShiftX, viewShiftY - scale * 0.06, scale * 0.05, viewShiftX, viewShiftY - scale * 0.06, scale * 0.85);
          coreShade.addColorStop(0, `rgba(7, 9, 13, ${(0.88 * (morphProgress - 0.72) / 0.28).toFixed(2)})`);
          coreShade.addColorStop(1, 'rgba(7, 9, 13, 0)');
          ctx.fillStyle = coreShade;
          ctx.beginPath();
          ctx.arc(viewShiftX, viewShiftY - scale * 0.06, scale * 0.85, 0, Math.PI * 2);
          ctx.fill();
        }

        for (let i = 0; i < COUNT; i++) {
          const item = projected[i];
          const sprite = leafSprites[item.shadeIdx];
          const half = item.size * 0.95;"""

    if draw_size_old not in html:
        print("ERROR: draw_size_old not found in html!")
        sys.exit(1)
    html = html.replace(draw_size_old, draw_size_new, 1)

    # 6. JavaScript: Web Audio Click Synthesizer + Universal Tooltip Engine + Multi-User Vault Functions
    # Insert new JS functions right before initWalletSecurity()
    js_vault_anchor = "    function initWalletSecurity() {"

    new_js_system = """    // ─── WEB AUDIO API CLICK SOUND FX (ZERO ASSETS / LOW LATENCY) ───
    let uiAudioCtx = null;
    function playUiClickSound(type = 'nav') {
      try {
        if (!uiAudioCtx) {
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          if (!AudioCtx) return;
          uiAudioCtx = new AudioCtx();
        }
        if (uiAudioCtx.state === 'suspended') {
          uiAudioCtx.resume();
        }
        const now = uiAudioCtx.currentTime;
        const osc = uiAudioCtx.createOscillator();
        const gain = uiAudioCtx.createGain();

        if (type === 'nav') {
          // Crisp high-tech metallic navigation click
          osc.type = 'sine';
          osc.frequency.setValueAtTime(1300, now);
          osc.frequency.exponentialRampToValueAtTime(320, now + 0.038);
          gain.gain.setValueAtTime(0.08, now);
          gain.gain.exponentialRampToValueAtTime(0.001, now + 0.038);
          osc.connect(gain);
          gain.connect(uiAudioCtx.destination);
          osc.start(now);
          osc.stop(now + 0.038);
        } else if (type === 'action') {
          // Tactile confirmation click
          osc.type = 'triangle';
          osc.frequency.setValueAtTime(860, now);
          osc.frequency.exponentialRampToValueAtTime(430, now + 0.045);
          gain.gain.setValueAtTime(0.06, now);
          gain.gain.exponentialRampToValueAtTime(0.001, now + 0.045);
          osc.connect(gain);
          gain.connect(uiAudioCtx.destination);
          osc.start(now);
          osc.stop(now + 0.045);
        }
      } catch (_) {}
    }

    // Attach sound click triggers to interactive elements
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('button, .nav-btn, .mobile-nav-link, .lang-select, .premium-user-pill, .copy-icon-btn, .vault-tab-btn, .saved-user-chip');
      if (btn) {
        playUiClickSound(btn.classList.contains('nav-btn') || btn.classList.contains('mobile-nav-link') ? 'nav' : 'action');
      }
    }, { passive: true });

    // ─── UNIVERSAL FLOATING TOOLTIP ENGINE (MOUSE HOVER FEEDBACK) ───
    function initUniversalTooltips() {
      let tip = document.getElementById('univa-floating-tooltip');
      if (!tip) {
        tip = document.createElement('div');
        tip.id = 'univa-floating-tooltip';
        document.body.appendChild(tip);
      }

      function resolveTooltip(el) {
        if (!el || el === document.body || el === document.documentElement) return null;
        if (el.getAttribute('data-tooltip')) return el.getAttribute('data-tooltip');
        if (el.title) {
          const t = el.title;
          el.setAttribute('data-tooltip', t);
          el.removeAttribute('title');
          return t;
        }
        if (el.classList && el.classList.contains('nav-btn')) {
          const view = el.getAttribute('data-view');
          const lbl = el.querySelector('.nav-label') ? el.querySelector('.nav-label').textContent : view;
          return `${lbl} sayfasına git ve modülü yönet`;
        }
        if (el.classList && el.classList.contains('copy-icon-btn')) {
          return 'Adresi / anahtarı panoya kopyala';
        }
        if (el.tagName === 'BUTTON' && el.textContent.trim().length > 0 && el.textContent.trim().length < 30) {
          return `${el.textContent.trim()} işlemini çalıştır`;
        }
        return null;
      }

      let activeEl = null;

      document.addEventListener('mouseover', (e) => {
        const target = e.target.closest('[data-tooltip], [title], .nav-btn, .copy-icon-btn, .btn, .premium-user-pill, .lang-select, .form-input');
        if (!target) {
          tip.classList.remove('visible');
          activeEl = null;
          return;
        }
        const text = resolveTooltip(target);
        if (!text) {
          tip.classList.remove('visible');
          activeEl = null;
          return;
        }
        activeEl = target;
        tip.textContent = text;
        tip.classList.add('visible');
        posTip(e);
      }, { passive: true });

      document.addEventListener('mousemove', (e) => {
        if (activeEl) posTip(e);
      }, { passive: true });

      document.addEventListener('mouseout', (e) => {
        if (activeEl && !activeEl.contains(e.relatedTarget)) {
          tip.classList.remove('visible');
          activeEl = null;
        }
      }, { passive: true });

      function posTip(e) {
        const pad = 12;
        let x = e.clientX + 14;
        let y = e.clientY + 18;
        const w = tip.offsetWidth;
        const h = tip.offsetHeight;
        if (x + w > window.innerWidth - pad) x = e.clientX - w - 10;
        if (y + h > window.innerHeight - pad) y = e.clientY - h - 10;
        tip.style.left = Math.max(pad, x) + 'px';
        tip.style.top = Math.max(pad, y) + 'px';
      }
    }

    // ─── MULTI-USER VAULT & ACCOUNT MANAGEMENT ENGINE ───
    let currentVaultMode = 'login'; // 'login' or 'new'

    function getSavedVaultUsers() {
      try {
        return JSON.parse(localStorage.getItem('univa_vault_users') || '{}');
      } catch (_) {
        return {};
      }
    }

    function saveVaultUserEntry(username, vaultData) {
      const users = getSavedVaultUsers();
      users[username.toLowerCase()] = {
        username: username,
        vault: vaultData,
        saved_at: Date.now()
      };
      localStorage.setItem('univa_vault_users', JSON.stringify(users));
      localStorage.setItem('univa_vault_v5', JSON.stringify(vaultData));
      localStorage.setItem('univa_vault_username', username);
    }

    function setVaultAuthMode(mode) {
      currentVaultMode = mode;
      const tabLogin = document.getElementById('vault-tab-login');
      const tabNew = document.getElementById('vault-tab-new');
      const title = document.getElementById('vault-modal-title');
      const desc = document.getElementById('vault-modal-desc');
      const submitBtn = document.getElementById('vault-submit-btn');
      const confirmWrap = document.getElementById('vault-confirm-pin-wrap');
      const savedWrap = document.getElementById('vault-saved-users-wrap');
      const importToggle = document.getElementById('vault-import-toggle');
      const importWrap = document.getElementById('vault-import-wrap');
      const userInput = document.getElementById('vault-username-input');

      if (mode === 'new') {
        if (tabNew) tabNew.classList.add('active');
        if (tabLogin) tabLogin.classList.remove('active');
        if (title) title.textContent = '✨ YENİ KULLANICI & CÜZDAN OLUŞTUR';
        if (desc) desc.textContent = 'Yeni bir kullanıcı adı ve 4-8 haneli PIN belirleyin. Otomatik olarak benzersiz 12 kelimelik tohum anahtarı üretilecektir.';
        if (submitBtn) submitBtn.innerHTML = '🚀 Yeni Cüzdanımı Oluştur';
        if (confirmWrap) confirmWrap.style.display = 'block';
        if (savedWrap) savedWrap.style.display = 'none';
        if (importToggle) importToggle.style.display = 'none';
        if (importWrap) importWrap.style.display = 'none';
        if (userInput && userInput.value.toLowerCase() === 'kaya') userInput.value = '';
      } else {
        if (tabLogin) tabLogin.classList.add('active');
        if (tabNew) tabNew.classList.remove('active');
        if (title) title.textContent = '🔐 UNIVA GÜVENLİ CÜZDAN GİRİŞİ';
        if (desc) desc.textContent = 'Kullanıcı adınızı ve güvenlik PIN\\'inizi girerek cüzdan kilidini açın veya kayıtlı hesabı seçin.';
        if (submitBtn) submitBtn.innerHTML = '🔓 Giriş Yap';
        if (confirmWrap) confirmWrap.style.display = 'none';
        if (importToggle) importToggle.style.display = 'inline-flex';
        renderSavedUsersChips();
      }
    }

    function renderSavedUsersChips() {
      const wrap = document.getElementById('vault-saved-users-wrap');
      const list = document.getElementById('vault-saved-users-list');
      if (!wrap || !list) return;

      const users = getSavedVaultUsers();
      const keys = Object.keys(users);

      // Include 'kaya' master default if not already listed
      if (!users['kaya'] && localStorage.getItem('univa_vault_v5')) {
        const u = localStorage.getItem('univa_vault_username') || 'kaya';
        users[u.toLowerCase()] = { username: u, vault: JSON.parse(localStorage.getItem('univa_vault_v5') || '{}') };
        keys.push(u.toLowerCase());
      }

      if (keys.length === 0) {
        wrap.style.display = 'none';
        return;
      }

      wrap.style.display = 'block';
      const activeName = (localStorage.getItem('univa_vault_username') || '').toLowerCase();

      list.innerHTML = keys.map(k => {
        const u = users[k];
        const isSel = (k === activeName);
        return `<div class="saved-user-chip ${isSel ? 'selected' : ''}" onclick="selectSavedUser('${escapeHtml(u.username)}')">
          <span>👤</span> <span>${escapeHtml(u.username)}</span>
        </div>`;
      }).join('');
    }

    function selectSavedUser(uname) {
      const inp = document.getElementById('vault-username-input');
      if (inp) inp.value = uname;
      const pin = document.getElementById('vault-pin-input');
      if (pin) pin.focus();
      document.querySelectorAll('.saved-user-chip').forEach(c => {
        c.classList.toggle('selected', c.textContent.includes(uname));
      });
    }

    function toggleUserMenu() {
      const menu = document.getElementById('user-menu-dropdown');
      if (!menu) return;
      const willOpen = !menu.classList.contains('active');
      menu.classList.toggle('active', willOpen);
      if (willOpen) {
        const uTxt = document.getElementById('header-user-text');
        const activeName = uTxt ? uTxt.textContent : (localStorage.getItem('univa_vault_username') || 'Kaya');
        const nEl = document.getElementById('user-menu-active-name');
        const aEl = document.getElementById('user-menu-active-addr');
        if (nEl) nEl.textContent = activeName;
        if (aEl) aEl.textContent = walletAddr || 'Adres Hazırlanıyor...';
      }
    }

    function closeUserMenu() {
      const menu = document.getElementById('user-menu-dropdown');
      if (menu) menu.classList.remove('active');
    }

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#header-user-pill') && !e.target.closest('#user-menu-dropdown')) {
        closeUserMenu();
      }
    });

    function openNewUserModal() {
      closeUserMenu();
      setVaultAuthMode('new');
      const m = document.getElementById('vault-modal');
      const closeBtn = document.getElementById('vault-close-btn');
      if (closeBtn) closeBtn.style.display = walletAddr ? 'inline-flex' : 'none';
      if (m) m.classList.add('active');
      const inp = document.getElementById('vault-username-input');
      if (inp) { inp.value = ''; inp.focus(); }
    }

    function openSwitchUserModal() {
      closeUserMenu();
      setVaultAuthMode('login');
      const m = document.getElementById('vault-modal');
      const closeBtn = document.getElementById('vault-close-btn');
      if (closeBtn) closeBtn.style.display = walletAddr ? 'inline-flex' : 'none';
      if (m) m.classList.add('active');
      const inp = document.getElementById('vault-username-input');
      if (inp) { inp.focus(); }
    }

    function logoutActiveUser() {
      closeUserMenu();
      walletAddr = '';
      walletEvm = '';
      walletPrivKey = '';
      walletMnemonic = '';
      const userPill = document.getElementById('header-user-pill');
      if (userPill) userPill.style.display = 'none';
      setVaultAuthMode('login');
      const m = document.getElementById('vault-modal');
      const closeBtn = document.getElementById('vault-close-btn');
      if (closeBtn) closeBtn.style.display = 'none';
      if (m) m.classList.add('active');
      showToast('Cüzdan güvenle kilitlendi.');
    }

    function closeVaultModalIfUnlocked() {
      if (walletAddr) {
        document.getElementById('vault-modal').classList.remove('active');
      }
    }

"""

    if js_vault_anchor not in html:
        print("ERROR: js_vault_anchor not found in html!")
        sys.exit(1)
    html = html.replace(js_vault_anchor, new_js_system + "\n    function initWalletSecurity() {", 1)

    # 7. Update submitVaultPin() to fully support Multi-User ("new" vs "login")
    submit_pin_old = """    async function submitVaultPin() {
      const usernameEl = document.getElementById('vault-username-input');
      const username = usernameEl ? usernameEl.value.trim() : '';
      const pin = document.getElementById('vault-pin-input').value.trim();
      const importWrap = document.getElementById('vault-import-wrap');
      const customInput = document.getElementById('vault-import-key').value.trim();
      const isRecoveryMode = importWrap && importWrap.style.display !== 'none' && customInput.length > 0;

      if (!username || username.length < 2) {
        alert('Lütfen geçerli bir kullanıcı adı girin (en az 2 karakter).');
        return;
      }
      if (!pin || pin.length < 4) {
        alert('Şifre en az 4 haneli olmalıdır.');
        return;
      }

      // Master Admin Hesabi ('kaya') sunucu tarafinda PBKDF2-SHA256 + Brute-Force kalkani ile dogrulanir
      if (!isRecoveryMode && username.toLowerCase() === 'kaya') {
        const authRes = await apiCall('/api/v1/wallet/master-auth', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: 'kaya', pin: pin })
        });
        if (authRes && authRes.status === 'ok' && authRes.encrypted_private_key) {
          const decPriv = await decryptServerWalletPayload(authRes.encrypted_private_key, pin);
          const kp = {
            address: authRes.address,
            evm_address: authRes.evm_address,
            public_key: authRes.public_key,
            private_key: decPriv.private_key,
            session_token: authRes.session_token,
            username: 'kaya',
            role: 'MASTER_ADMIN'
          };
          const vault = await encryptSecret(JSON.stringify(kp), pin);
          localStorage.setItem('univa_vault_v5', JSON.stringify(vault));
          localStorage.setItem('univa_vault_username', 'kaya');
          activateWallet(kp);
          document.getElementById('vault-modal').classList.remove('active');
          document.getElementById('vault-pin-input').value = '';
          return;
        } else if (nodeConnected) {
          alert('Master PIN hatalı veya güvenlik kilidi aktif! Lütfen doğru PIN girin.');
          return;
        }
      }

      const stored = localStorage.getItem('univa_vault_v5');
      if (!stored || isRecoveryMode) {
        let kp = null;
        let showBackupModal = false;

        if (customInput) {
          if (/^[0-9a-fA-F]{64}$/.test(customInput)) {
            kp = await generateKeypair(customInput.toLowerCase());
          } else {
            const check = await validateMnemonic12(customInput);
            if (!check.valid) {
              alert(check.reason);
              return;
            }
            kp = await deriveKeypairFromMnemonic(check.normalized);
          }
        } else {
          const phrase = await generateMnemonic12();
          kp = await deriveKeypairFromMnemonic(phrase);
          showBackupModal = true;
        }

        kp.username = username;
        const vault = await encryptSecret(JSON.stringify(kp), pin);
        localStorage.setItem('univa_vault_v5', JSON.stringify(vault));
        localStorage.setItem('univa_vault_username', username);
        activateWallet(kp);
        document.getElementById('vault-modal').classList.remove('active');
        document.getElementById('vault-pin-input').value = '';
        document.getElementById('vault-import-key').value = '';
        if (showBackupModal && kp.mnemonic) {
          openSeedBackupModal(kp.mnemonic);
        }
        return;
      } else {
        try {
          const vault = JSON.parse(stored);
          const decrypted = await decryptSecret(vault, pin);
          const kp = JSON.parse(decrypted);
          if (kp.username && kp.username.toLowerCase() !== username.toLowerCase()) {
            alert('Kullanıcı adı veya şifre hatalı!');
            return;
          }
          if (!kp.username) {
            kp.username = username;
            const updatedVault = await encryptSecret(JSON.stringify(kp), pin);
            localStorage.setItem('univa_vault_v5', JSON.stringify(updatedVault));
          }
          localStorage.setItem('univa_vault_username', kp.username);
          activateWallet(kp);
        } catch (e) {
          alert('Kullanıcı adı veya şifre hatalı!');
          return;
        }
      }

      document.getElementById('vault-modal').classList.remove('active');
      document.getElementById('vault-pin-input').value = '';
    }"""

    submit_pin_new = """    async function submitVaultPin() {
      const usernameEl = document.getElementById('vault-username-input');
      const username = usernameEl ? usernameEl.value.trim() : '';
      const pin = document.getElementById('vault-pin-input').value.trim();
      const confirmPinEl = document.getElementById('vault-pin-confirm');
      const confirmPin = confirmPinEl ? confirmPinEl.value.trim() : '';
      const importWrap = document.getElementById('vault-import-wrap');
      const customInput = document.getElementById('vault-import-key').value.trim();
      const isRecoveryMode = importWrap && importWrap.style.display !== 'none' && customInput.length > 0;
      const isNewUserMode = (currentVaultMode === 'new');

      if (!username || username.length < 2) {
        alert('Lütfen geçerli bir kullanıcı adı girin (en az 2 karakter).');
        return;
      }
      if (!pin || pin.length < 4) {
        alert('PIN kodu en az 4 haneli olmalıdır.');
        return;
      }
      if (isNewUserMode && confirmPin && pin !== confirmPin) {
        alert('Girdiğiniz PIN kodları birbiriyle eşleşmiyor! Lütfen tekrar kontrol edin.');
        return;
      }

      // 1. Master Admin Hesabı ('kaya')
      if (!isRecoveryMode && !isNewUserMode && username.toLowerCase() === 'kaya') {
        const authRes = await apiCall('/api/v1/wallet/master-auth', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: 'kaya', pin: pin })
        });
        if (authRes && authRes.status === 'ok' && authRes.encrypted_private_key) {
          const decPriv = await decryptServerWalletPayload(authRes.encrypted_private_key, pin);
          const kp = {
            address: authRes.address,
            evm_address: authRes.evm_address,
            public_key: authRes.public_key,
            private_key: decPriv.private_key,
            session_token: authRes.session_token,
            username: 'kaya',
            role: 'MASTER_ADMIN'
          };
          const vault = await encryptSecret(JSON.stringify(kp), pin);
          saveVaultUserEntry('kaya', vault);
          activateWallet(kp);
          document.getElementById('vault-modal').classList.remove('active');
          document.getElementById('vault-pin-input').value = '';
          showToast('Master Admin (Kaya) başarıyla açıldı.');
          return;
        } else if (nodeConnected) {
          alert('Master PIN hatalı veya güvenlik kilidi aktif! Lütfen doğru PIN girin.');
          return;
        }
      }

      // 2. Yeni Kullanıcı Oluşturma Modu veya Kurtarma Modu
      if (isNewUserMode || isRecoveryMode) {
        let kp = null;
        let showBackupModal = false;

        if (customInput) {
          if (/^[0-9a-fA-F]{64}$/.test(customInput)) {
            kp = await generateKeypair(customInput.toLowerCase());
          } else {
            const check = await validateMnemonic12(customInput);
            if (!check.valid) {
              alert(check.reason);
              return;
            }
            kp = await deriveKeypairFromMnemonic(check.normalized);
          }
        } else {
          const phrase = await generateMnemonic12();
          kp = await deriveKeypairFromMnemonic(phrase);
          showBackupModal = true;
        }

        kp.username = username;
        const vault = await encryptSecret(JSON.stringify(kp), pin);
        saveVaultUserEntry(username, vault);
        activateWallet(kp);
        document.getElementById('vault-modal').classList.remove('active');
        document.getElementById('vault-pin-input').value = '';
        if (confirmPinEl) confirmPinEl.value = '';
        document.getElementById('vault-import-key').value = '';
        showToast(`✨ Hoş geldiniz, ${username}! Cüzdanınız hazır.`);
        if (showBackupModal && kp.mnemonic) {
          openSeedBackupModal(kp.mnemonic);
        }
        return;
      }

      // 3. Mevcut Kullanıcı Girişi Modu
      const allUsers = getSavedVaultUsers();
      const targetUserEntry = allUsers[username.toLowerCase()];
      let vaultPayload = targetUserEntry ? targetUserEntry.vault : null;

      // Fallback: Check univa_vault_v5 if single user exists
      if (!vaultPayload) {
        const legacyStored = localStorage.getItem('univa_vault_v5');
        const legacyUser = localStorage.getItem('univa_vault_username') || '';
        if (legacyStored && (legacyUser.toLowerCase() === username.toLowerCase() || !legacyUser)) {
          try { vaultPayload = JSON.parse(legacyStored); } catch (_) {}
        }
      }

      if (!vaultPayload) {
        alert(`'${username}' adlı kayıtlı cüzdan bulunamadı. Yeni bir cüzdan oluşturmak için 'Yeni Kullanıcı Oluştur' sekmesini seçebilirsiniz.`);
        return;
      }

      try {
        const decrypted = await decryptSecret(vaultPayload, pin);
        const kp = JSON.parse(decrypted);
        kp.username = username;
        saveVaultUserEntry(username, vaultPayload);
        activateWallet(kp);
        document.getElementById('vault-modal').classList.remove('active');
        document.getElementById('vault-pin-input').value = '';
        showToast(`🔓 Giriş başarılı: ${username}`);
      } catch (e) {
        alert('Kullanıcı adı veya şifre hatalı!');
      }
    }"""

    if submit_pin_old not in html:
        print("ERROR: submit_pin_old not found in html!")
        sys.exit(1)
    html = html.replace(submit_pin_old, submit_pin_new, 1)

    # 8. Update initWalletSecurity() to invoke renderSavedUsersChips & default mode
    init_sec_old = """    function initWalletSecurity() {
      const stored = localStorage.getItem('univa_vault_v5');
      const modal = document.getElementById('vault-modal');
      const title = document.getElementById('vault-modal-title');
      const desc = document.getElementById('vault-modal-desc');
      const toggleBtn = document.getElementById('vault-import-toggle');

      if (!stored) {
        title.textContent = 'UNIVA GÜVENLİ CÜZDAN OLUŞTUR';
        desc.textContent = 'Yeni bir 12 kelimelik cüzdan oluşturun veya mevcut 12 kelimenizle hesabınızı kalıcı olarak kurtarın.';
        if (toggleBtn) toggleBtn.style.display = 'inline-flex';
        modal.classList.add('active');
      } else {
        title.textContent = 'UNIVA CÜZDAN KİLİDİNİ AÇ';
        desc.textContent = 'Kullanıcı adınızı ve şifrenizi girin veya 12 kelimenizle başka bir cüzdanı kurtarın.';
        if (toggleBtn) toggleBtn.style.display = 'inline-flex';
        modal.classList.add('active');
      }
    }"""

    init_sec_new = """    function initWalletSecurity() {
      const stored = localStorage.getItem('univa_vault_v5');
      const allUsers = getSavedVaultUsers();
      const hasAnyUser = stored || Object.keys(allUsers).length > 0;
      const modal = document.getElementById('vault-modal');

      if (!hasAnyUser) {
        setVaultAuthMode('new');
      } else {
        setVaultAuthMode('login');
      }
      if (modal) modal.classList.add('active');
      initUniversalTooltips();
    }"""

    if init_sec_old not in html:
        print("ERROR: init_sec_old not found in html!")
        sys.exit(1)
    html = html.replace(init_sec_old, init_sec_new, 1)

    # 9. Register Translation pairs in UNIVA_EXTRA_I18N_PAIRS
    i18n_old = 'const UNIVA_EXTRA_I18N_PAIRS = ['
    i18n_new = """const UNIVA_EXTRA_I18N_PAIRS = [
      ["Launch Dashboard", "Kontrol Paneli"],
      ["Explore UNIVA", "UNIVA'yı Keşfet"],
      ["Enter Network", "Ağa Katıl"],
      ["Discover Technology", "Teknolojiyi İncele"],
      ["Egemen Katman-1 Blokzinciri", "Sovereign Layer-1 Blockchain"],
      ["Sovereign Layer-1 Blockchain", "Egemen Katman-1 Blokzinciri"],
      ["TEK AĞ.<br>SONSUZ İMKANLAR.", "ONE NETWORK.<br>INFINITE POSSIBILITIES."],
      ["ONE NETWORK.<br>INFINITE POSSIBILITIES.", "TEK AĞ.<br>SONSUZ İMKANLAR."],
      ["UNIVA; merkeziyetsiz ağları, küresel hesaplama gücünü ve egemen dijital değeri Bitcoin seviyesinde güvenlik ve EVM likidite köprüsüyle birleştirmek üzere tasarlanmış bağımsız bir Katman-1 blokzincir altyapısıdır.", "UNIVA is an independent Layer-1 blockchain infrastructure engineered to unify decentralized networks, global computing power, and sovereign digital value with Bitcoin-grade security and EVM liquidity interoperability."],
      ["UNIVA is an independent Layer-1 blockchain infrastructure engineered to unify decentralized networks, global computing power, and sovereign digital value with Bitcoin-grade security and EVM liquidity interoperability.", "UNIVA; merkeziyetsiz ağları, küresel hesaplama gücünü ve egemen dijital değeri Bitcoin seviyesinde güvenlik ve EVM likidite köprüsüyle birleştirmek üzere tasarlanmış bağımsız bir Katman-1 blokzincir altyapısıdır."],
      ["SHA-256 Konsensüsü", "SHA-256 Consensus"],
      ["SHA-256 Consensus", "SHA-256 Konsensüsü"],
      ["Hibrit EVM Köprüsü", "Hybrid EVM Bridge"],
      ["Hybrid EVM Bridge", "Hibrit EVM Köprüsü"],
      ["Çift Katmanlı Depolama", "Dual-Layer Storage"],
      ["Dual-Layer Storage", "Çift Katmanlı Depolama"],
      ["UNIVA Ekosistem Altyapısı", "UNIVA Ecosystem Infrastructure"],
      ["UNIVA Ecosystem Infrastructure", "UNIVA Ekosistem Altyapısı"],
      ["Çekirdek Modüller", "Core Modules"],
      ["Core Modules", "Çekirdek Modüller"],
      ["Blokzincir Gezgini", "Blockchain Explorer"],
      ["Blockchain Explorer", "Blokzincir Gezgini"],
      ["Madencilik Merkezi", "Mining Center"],
      ["Mining Center", "Madencilik Merkezi"],
      ["Gezginde Ara", "Search Explorer"],
      ["Search Explorer", "Gezginde Ara"],
"""

    if i18n_old not in html:
        print("ERROR: i18n_old not found in html!")
        sys.exit(1)
    html = html.replace(i18n_old, i18n_new, 1)

    with open('pwa/index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Patched successfully! New size: {len(html)} bytes")

if __name__ == '__main__':
    main()
