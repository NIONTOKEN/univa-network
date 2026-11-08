"""
UNIVA Network - Persistent Background Tunnel Manager
===================================================
Establishes and maintains an SSH tunnel via localhost.run to expose port 5050.
Writes active public URL to 'tunnel_url.txt'.
"""

import subprocess
import time
import re
import os

URL_FILE = "tunnel_url.txt"

def run_tunnel():
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=20",
        "-o", "ServerAliveCountMax=3",
        "-R", "80:127.0.0.1:5050",
        "nokey@localhost.run"
    ]
    
    print("[TUNNEL] localhost.run baglantisi kuruluyor...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    tunnel_url = None
    for line in proc.stdout:
        print("[SSH]", line.strip())
        if ".lhr.life" in line or ".lhr.rocks" in line:
            m = re.search(r'https://[a-zA-Z0-9-]+\.lhr\.(life|rocks)', line)
            if m:
                tunnel_url = m.group(0)
                print(f"[TUNNEL BULUNDU]: {tunnel_url}")
                with open(URL_FILE, "w", encoding="utf-8") as f:
                    f.write(tunnel_url.strip())
    
    proc.wait()
    print("[TUNNEL] Baglanti koptu, 5 sn icinde tekrar denenecek...")

if __name__ == "__main__":
    while True:
        try:
            run_tunnel()
        except Exception as e:
            print(f"[TUNNEL HATA]: {e}")
        time.sleep(5)
