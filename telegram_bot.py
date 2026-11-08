"""
UNIVA Network - Telegram Mini App Bot
=====================================
Bu bot, Telegram kullanıcılarının Telegram'dan çıkmadan UNIVA cüzdanına,
madenciliğe ve transferlere tek tıkla erişmesini sağlayan resmi WebApp botudur.
"""

import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_BOT_TOKEN = os.getenv("UNIVA_BOT_TOKEN", "9078631819:AAFc2foI-f1EP4t3GovO7qmrVwEb0UpyOzA")
WEBAPP_URL = os.getenv("UNIVA_WEBAPP_URL", "https://univa-network-l1.vercel.app")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"👋 Merhaba {user.first_name}!\n\n"
        "🌐 **UNIVA Network Resmi Cüzdan ve Madencilik Botuna Hoş Geldiniz.**\n\n"
        "⚡ **Sovereign Layer 1 Blockchain**\n"
        "⛏️ **SHA-256 Proof-of-Work Madencilik**\n"
        "🔗 **EVM & MetaMask Hibrit Köprüsü (Chain ID: 210001)**\n"
        "💎 **21.000.001 UNIVA Maksimum Arz**\n\n"
        "Cüzdanınızı açmak, bakiye görüntülemek ve tek tıkla madencilik başlatmak için aşağıdaki butona dokunun! 👇"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🚀 UNIVA WebApp Cüzdanını Aç",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )
        ],
        [
            InlineKeyboardButton("🌐 Web Cüzdan", url=WEBAPP_URL),
            InlineKeyboardButton("📖 Whitepaper", url=f"{WEBAPP_URL}/#whitepaper")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

def main():
    print(f"[UNIVA BOT] Token: {TELEGRAM_BOT_TOKEN[:10]}... WebApp: {WEBAPP_URL}")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("[UNIVA BOT] Telegram botu aktif ve dinlemede...")
    app.run_polling()

if __name__ == "__main__":
    main()
