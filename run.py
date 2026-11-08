"""
UNIVA Network - Ana Başlatıcı v3.0 (Unified Launcher)
=====================================================
- Tek tıkla P2P WebSocket (ws://0.0.0.0:5051)
- FastAPI HTTP / PWA Web Gateway (http://127.0.0.1:5050)
- MTP BIP-113 korumalı SHA-256 Proof of Work
- 20 Karakterlik Güvenli Adres Standardı
"""

import sys
import os
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

WALLET_FILE = os.path.join(BASE_DIR, "univa_wallet.json")
CHAIN_FILE  = os.path.join(BASE_DIR, "univa_chain.json")
DB_FILE     = os.path.join(BASE_DIR, "univa_chain.db")


def print_banner():
    print("=" * 65)
    print("   UNIVA NETWORK v3.0.0")
    print("   Sovereign Layer 1 Blockchain")
    print("   Adres Formati : univa..........univa (20 Karakter)")
    print("   Maksimum Arz  : 21,000,001 UNIVA")
    print("   Ilk Odul      : 100 UNIVA/blok")
    print("   PWA & Web     : http://127.0.0.1:5050")
    print("   P2P WebSocket : ws://0.0.0.0:5051")
    print("=" * 65)


def load_or_create_wallet():
    from core.wallet import UnivaWallet
    if os.path.exists(WALLET_FILE):
        try:
            w = UnivaWallet.load(WALLET_FILE)
            print(f"[UNIVA] Cuzdan yuklendi: {w.address} ({len(w.address)} kar)")
            return w
        except Exception:
            pass
    print("[UNIVA] Yeni 20 karakterlik guvenli cuzdan uretiliyor...")
    w = UnivaWallet.create_new()
    w.save(WALLET_FILE)
    print(f"[UNIVA] Yeni Cuzdan: {w.address}")
    return w


def main():
    print_banner()
    parser = argparse.ArgumentParser(description="UNIVA Network Node")
    parser.add_argument("--node", action="store_true", help="Node modu")
    parser.add_argument("--host", default="0.0.0.0", help="Dinleme adresi")
    parser.add_argument("--api-port", type=int, default=5050, help="HTTP API portu")
    parser.add_argument("--p2p-port", type=int, default=5051, help="P2P portu")
    parser.add_argument("--peer", action="append", default=[], help="Seed peer adresi")
    args = parser.parse_args()

    os.chdir(BASE_DIR)

    # 1. Cüzdan kontrol
    wallet = load_or_create_wallet()

    # 2. Blockchain & DB Index
    from core.network import blockchain, app
    from core.database import rebuild_index
    print(f"[UNIVA] Zincir yuksekligi: {blockchain.height} | Toplam madeni: {blockchain.total_mined} UNIVA")
    try:
        rebuild_index(blockchain.chain, db_path=DB_FILE)
    except Exception as e:
        print(f"[UNIVA] DB index notu: {e}")

    # 3. P2P WebSocket Baslat (Thread)
    from core.p2p import run_p2p_in_thread
    run_p2p_in_thread(blockchain, seed_peers=args.peer, host=args.host, port=args.p2p_port, db_path=DB_FILE)

    # 4. FastAPI Web Server & PWA Gateway
    import uvicorn
    print(f"[UNIVA] Sunucu baslatildi -> http://{args.host}:{args.api_port}")
    uvicorn.run(app, host=args.host, port=args.api_port, log_level="info")


if __name__ == "__main__":
    main()
