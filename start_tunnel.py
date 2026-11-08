"""
UNIVA Network - Cloudflare Tunnel Daemon (HTTP/2 + IPv4)
=========================================================
Exposes UNIVA Node (port 5050) to the global internet via Cloudflare Quick Tunnel.
Bypasses ISP QUIC/UDP blocking using --protocol http2 and --edge-ip-version 4.
Saves the live URL into 'public_url.txt'.
"""

import subprocess
import time
import re
import os

URL_FILE = "public_url.txt"
EXE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflared.exe")

def run():
    cmd = [
        EXE_PATH,
        "tunnel",
        "--url", "http://127.0.0.1:5050",
        "--protocol", "http2",
        "--edge-ip-version", "4",
        "--no-autoupdate",
    ]
    print("[CLOUDFLARE] Tunnel baslatiliyor...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    for line in proc.stdout:
        print("[CF]", line.strip(), flush=True)
        if "trycloudflare.com" in line:
            m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if m:
                public_url = m.group(0)
                print(f"\n[CLOUDFLARE LIVE URL]: {public_url}\n", flush=True)
                with open(URL_FILE, "w", encoding="utf-8") as f:
                    f.write(public_url.strip())

    proc.wait()
    print("[CLOUDFLARE] Tunnel kapandi, 5 sn icinde tekrar baglanacak...")

if __name__ == "__main__":
    while True:
        try:
            run()
        except Exception as e:
            print(f"[CLOUDFLARE HATA]: {e}")
        time.sleep(5)
