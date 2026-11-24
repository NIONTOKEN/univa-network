import re

# 1. Update core/network.py
with open("core/network.py", "r", encoding="utf-8") as f:
    net_content = f.read()

net_old = """    reward_override = 10.0 if is_mobile else None
    miner_tier = "Mobil Light Miner (10 UNIVA)" if is_mobile else "PC Full CPU Miner (100 UNIVA)\""""

net_new = """    reward_override = 0.00001 if is_mobile else None
    miner_tier = "Mobil Light Miner (0.00001 UNIVA)" if is_mobile else "PC Full CPU Miner (100 UNIVA)\""""

if net_old in net_content:
    net_content = net_content.replace(net_old, net_new)
    with open("core/network.py", "w", encoding="utf-8") as f:
        f.write(net_content)
    print("core/network.py updated successfully!")
else:
    print("WARNING: net_old not found in core/network.py")

# 2. Update pwa/index.html
with open("pwa/index.html", "r", encoding="utf-8") as f:
    pwa_content = f.read()

# Replace block subsidy label
pwa_content = pwa_content.replace(
    '<span class="mono">100.0 UNIVA (PC) / 10.0 UNIVA (Mobile)</span>',
    '<span class="mono">100.0 UNIVA (PC) / 0.00001 UNIVA (Mobil)</span>'
)

# Replace mining tier sub
pwa_content = pwa_content.replace(
    '<div class="stat-sub" id="mining-tier-sub">PC CPU: 100.0 UNIVA · Mobil: 10.0 UNIVA / Blok</div>',
    '<div class="stat-sub" id="mining-tier-sub">PC CPU: 100.0 UNIVA · Mobil: 0.00001 UNIVA / Blok</div>'
)

# Replace worker task reward
pwa_content = pwa_content.replace(
    "reward: (/android|iphone|ipad|mobile/i.test(navigator.userAgent || '') ? 10.0 : 100.0),",
    "reward: (/android|iphone|ipad|mobile/i.test(navigator.userAgent || '') ? 0.00001 : 100.0),"
)

# Replace defaultRew
pwa_content = pwa_content.replace(
    "const defaultRew = /android|iphone|ipad|mobile/i.test(navigator.userAgent || '') ? 10.0 : 100.0;",
    "const defaultRew = /android|iphone|ipad|mobile/i.test(navigator.userAgent || '') ? 0.00001 : 100.0;"
)

# Replace mobRew
pwa_content = pwa_content.replace(
    "const mobRew = /android|iphone|ipad|mobile/i.test(navigator.userAgent || '') ? 10.0 : 100.0;",
    "const mobRew = /android|iphone|ipad|mobile/i.test(navigator.userAgent || '') ? 0.00001 : 100.0;"
)

# Replace tierTag logic
pwa_content = pwa_content.replace(
    "const tierTag = rew <= 10.0 ? '<span class=\"badge badge-native\" style=\"margin-left:6px;font-size:0.68rem;\">📱 Mobile</span>' : '<span class=\"badge\" style=\"margin-left:6px;font-size:0.68rem;background:#EEF2F7;color:#20242B;\">🖥️ PC</span>';",
    "const tierTag = rew < 100.0 ? '<span class=\"badge badge-native\" style=\"margin-left:6px;font-size:0.68rem;\">📱 Mobil</span>' : '<span class=\"badge\" style=\"margin-left:6px;font-size:0.68rem;background:#EEF2F7;color:#20242B;\">🖥️ PC</span>';"
)

# Format mining rewards so 0.00001 doesn't show as 0.00
pwa_content = pwa_content.replace(
    "document.getElementById('mining-reward-val').textContent = sessionMinedRewards.toFixed(2);",
    "document.getElementById('mining-reward-val').textContent = (sessionMinedRewards < 0.01) ? sessionMinedRewards.toFixed(5) : sessionMinedRewards.toFixed(2);"
)

# Replace toast / log display formatting
old_log1 = "minedBlockInfo ? (minedBlockInfo.reward ?? defaultRew) : defaultRew;"
new_log1 = """minedBlockInfo ? (minedBlockInfo.reward ?? defaultRew) : defaultRew;
        const rewDisplay = (rewardAmt < 0.01) ? rewardAmt.toFixed(5) : rewardAmt;"""
pwa_content = pwa_content.replace(old_log1, new_log1)

pwa_content = pwa_content.replace(
    "(+${rewardAmt} UNIVA)",
    "(+${rewDisplay} UNIVA)"
)
pwa_content = pwa_content.replace(
    "'+' + rewardAmt + ' UNIVA'",
    "'+' + rewDisplay + ' UNIVA'"
)

pwa_content = pwa_content.replace(
    "(+${mobRew} UNIVA)",
    "(+${mobRew < 0.01 ? mobRew.toFixed(5) : mobRew} UNIVA)"
)
pwa_content = pwa_content.replace(
    "'+' + mobRew + ' UNIVA'",
    "'+' + (mobRew < 0.01 ? mobRew.toFixed(5) : mobRew) + ' UNIVA'"
)

# 3. Center mobile styling in pwa/index.html
old_mobile_css = """.content-wrap { padding: 20px 14px; max-width: 100vw; overflow-x: hidden; }
      .card { padding: 16px; }
      .grid-2, .grid-3 { grid-template-columns: 1fr; gap: 14px; }
      .grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
      .stat-box { padding: 14px 12px; }
      .stat-num { font-size: 1.2rem; word-break: break-word; }
      .stat-label { font-size: 0.68rem; }
      .hero-content { padding: 18px; }
      .hero-title { font-size: clamp(1.75rem, 6.5vw, 2.35rem); }
      .hero-desc { font-size: 0.92rem; margin-bottom: 20px; }"""

new_mobile_css = """/* CENTERED CLEAN MOBILE APP VIEWPORT (PREVENTS FULL-SCREEN STRETCH) */
      main.app-main {
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        width: 100% !important;
      }
      .view-section {
        width: 100% !important;
      }
      .view-section.active {
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        width: 100% !important;
      }
      .content-wrap {
        width: 100% !important;
        max-width: 480px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        padding: 16px 12px 84px 12px !important;
        box-sizing: border-box !important;
        overflow-x: hidden;
      }
      .univa-hero {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        padding: 28px 12px !important;
        min-height: auto !important;
      }
      .univa-hero-inner {
        max-width: 480px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        justify-content: center !important;
        display: flex !important;
        padding: 0 !important;
      }
      .hero-content {
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 auto !important;
        text-align: center !important;
        padding: 22px 16px !important;
      }
      .hero-actions {
        justify-content: center !important;
      }
      .hero-stats-row {
        justify-content: center !important;
      }
      .card { padding: 16px; border-radius: 16px; }
      .grid-2, .grid-3 { grid-template-columns: 1fr; gap: 14px; }
      .grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
      .stat-box { padding: 14px 12px; }
      .stat-num { font-size: 1.2rem; word-break: break-word; }
      .stat-label { font-size: 0.68rem; }
      .hero-title { font-size: clamp(1.65rem, 6vw, 2.15rem); }
      .hero-desc { font-size: 0.90rem; margin-bottom: 18px; }"""

if old_mobile_css in pwa_content:
    pwa_content = pwa_content.replace(old_mobile_css, new_mobile_css)
    print("Mobile CSS centered successfully!")
else:
    print("WARNING: old_mobile_css not found, trying fallback patch...")
    # fallback
    pwa_content = pwa_content.replace(
        ".content-wrap { padding: 20px 14px; max-width: 100vw; overflow-x: hidden; }",
        new_mobile_css
    )

with open("pwa/index.html", "w", encoding="utf-8") as f:
    f.write(pwa_content)
print("pwa/index.html written successfully!")
