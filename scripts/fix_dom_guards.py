with open('pwa/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Protect first document.addEventListener
t1 = """    // Attach sound click triggers to interactive elements
    document.addEventListener('click', (e) => {"""
r1 = """    // Attach sound click triggers to interactive elements
    if (typeof document !== 'undefined') {
      document.addEventListener('click', (e) => {"""

t1_end = """        playUiClickSound(btn.classList.contains('nav-btn') || btn.classList.contains('mobile-nav-link') ? 'nav' : 'action');
      }
    }, { passive: true });"""
r1_end = """        playUiClickSound(btn.classList.contains('nav-btn') || btn.classList.contains('mobile-nav-link') ? 'nav' : 'action');
      }
    }, { passive: true });
    }"""

assert t1 in html, "t1 not found"
html = html.replace(t1, r1, 1)
assert t1_end in html, "t1_end not found"
html = html.replace(t1_end, r1_end, 1)

# 2. Protect initUniversalTooltips
t2 = """    // ─── UNIVERSAL FLOATING TOOLTIP ENGINE (MOUSE HOVER FEEDBACK) ───
    function initUniversalTooltips() {
      let tip = document.getElementById('univa-floating-tooltip');"""
r2 = """    // ─── UNIVERSAL FLOATING TOOLTIP ENGINE (MOUSE HOVER FEEDBACK) ───
    function initUniversalTooltips() {
      if (typeof document === 'undefined') return;
      let tip = document.getElementById('univa-floating-tooltip');"""

assert t2 in html, "t2 not found"
html = html.replace(t2, r2, 1)

# 3. Protect second document.addEventListener (user menu closer)
t3 = """    document.addEventListener('click', (e) => {
      if (!e.target.closest('#header-user-pill') && !e.target.closest('#user-menu-dropdown')) {
        closeUserMenu();
      }
    });"""

r3 = """    if (typeof document !== 'undefined') {
      document.addEventListener('click', (e) => {
        if (!e.target.closest('#header-user-pill') && !e.target.closest('#user-menu-dropdown')) {
          closeUserMenu();
        }
      });
    }"""

assert t3 in html, "t3 not found"
html = html.replace(t3, r3, 1)

with open('pwa/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Protected all DOM calls with typeof document !== 'undefined'!")
