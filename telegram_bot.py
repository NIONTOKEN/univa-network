"""
UNIVA Network - Telegram Mini App Bot (Universal Lightweight Runner)
===================================================================
Python 3.14+ tam uyumlu, sifir harici kutuphane bagimliligi.
Telegram WebApp Mini App + /start komutu ve buton yonetimi.
"""

import urllib.request
import json
import time
import sys

BOT_TOKEN = "9078631819:AAFc2foI-f1EP4t3Gov07qmrVwEbOUpy0zA"
WEBAPP_URL = "https://univa-network-l1.vercel.app"
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def api_call(method, payload=None):
    url = f"{API_BASE}/{method}"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[BOT API ERROR] {method}: {e}", file=sys.stderr)
        return None

def get_webapp_url():
    base = WEBAPP_URL
    try:
        with open("public_url.txt", "r", encoding="utf-8") as f:
            pub = f.read().strip()
            if pub.startswith("https://"):
                return f"{base}?node={pub}"
    except Exception:
        pass
    return base

def send_welcome(chat_id, first_name):
    app_url = get_webapp_url()
    welcome_text = (
        f"👋 **Merhaba {first_name}!**\n\n"
        "🌐 **UNIVA Network Resmi Cüzdan ve Madencilik Botuna Hoş Geldiniz.**\n\n"
        "⚡ **Sovereign Layer 1 Blockchain**\n"
        "⛏️ **SHA-256 Proof-of-Work Madencilik**\n"
        "🔗 **EVM & MetaMask Hibrit Köprüsü (Chain ID: 210001)**\n"
        "💎 **21.000.001 UNIVA Maksimum Arz**\n\n"
        "Cüzdanınızı açmak, bakiye görüntülemek ve tek tıkla madencilik başlatmak için aşağıdaki butona dokunun! 👇"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "🚀 UNIVA WebApp Cüzdanını Aç",
                    "web_app": {"url": app_url}
                }
            ],
            [
                {"text": "🌐 Web Cüzdan", "url": app_url},
                {"text": "📖 GitHub Kaynak", "url": "https://github.com/NIONTOKEN/univa-network"}
            ]
        ]
    }
    payload = {
        "chat_id": chat_id,
        "text": welcome_text,
        "parse_mode": "Markdown",
        "reply_markup": reply_markup
    }
    return api_call("sendMessage", payload)

def main():
    print(f"[UNIVA TELEGRAM BOT] Baslatiliyor... Token: {BOT_TOKEN[:10]}...")
    me = None
    while not me or not me.get("ok"):
        me = api_call("getMe")
        if not me or not me.get("ok"):
            print("[UYARI] Telegram API baglantisi bekleniyor, 5 sn sonra tekrar denenecek...")
            time.sleep(5)

    bot_info = me["result"]
    print(f"[UNIVA TELEGRAM BOT] Aktif: @{bot_info.get('username')} ({bot_info.get('first_name')})")

    # Set Menu Button
    api_call("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "🚀 UNIVA Cüzdan",
            "web_app": {"url": get_webapp_url()}
        }
    })

    offset = 0
    print("[UNIVA TELEGRAM BOT] Mesaj dinleme moduna gecildi...")
    while True:
        try:
            updates = api_call("getUpdates", {"offset": offset, "timeout": 20})
            if updates and updates.get("ok"):
                for u in updates.get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message")
                    if not msg:
                        continue
                    text = msg.get("text", "")
                    chat = msg.get("chat", {})
                    chat_id = chat.get("id")
                    first_name = msg.get("from", {}).get("first_name", "Kullanıcı")

                    if text.startswith("/start"):
                        send_welcome(chat_id, first_name)
            time.sleep(1)
        except KeyboardInterrupt:
            print("Bot durduruldu.")
            break
        except Exception as e:
            print(f"[HATA] Döngü hatası: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
