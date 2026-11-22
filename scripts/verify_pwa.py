import re
import subprocess
import os

with open('pwa/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
print(f"Found {len(scripts)} inline script block(s)")

for i, s in enumerate(scripts):
    tmp_name = f'tmp_check_{i}.js'
    with open(tmp_name, 'w', encoding='utf-8') as f:
        f.write(s)
    res = subprocess.run(['node', '--check', tmp_name], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Script #{i}: VALID JAVASCRIPT (syntax check PASS)")
    else:
        print(f"Script #{i}: SYNTAX ERROR:\n{res.stderr}")
    if os.path.exists(tmp_name):
        os.remove(tmp_name)
