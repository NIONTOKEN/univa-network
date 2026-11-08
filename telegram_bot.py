"""
UNIVA Network - Telegram Mini App Bot
=====================================
Bu bot, Telegram kullanıcılarının Telegram'dan çıkmadan UNIVA cüzdanına,
madenciliğe ve transferlere tek tıkla erişmesini sağlayan resmi WebApp botudur.

Gereksinimler:
pip install python-telegram-bot
"""

import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Telegram Bot Token'ınızı buraya ekleyin veya ortam değişkeni olarak verin:
# BotFather'dan /newbot diyerek aldığınız token:
TELEGRAM_BOT_TOKEN = os.getenv("UNIVA_BOT_TOKEN", "BOT_TOKENINIZI_BURAYA_GIRIN")

# WebApp URL: Vercel adresiniz veya Cloudflare Live URL'niz:
WEBAPP_URL = os.getenv("UNIVA_WEBAPP_URL", "https://univa-network.vercel.app")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"👋 Merhaba {user.first_name}!\n\n"
        "🏛 **UNIVA Network Resmi Cüzdan ve Madencilik Botuna Hoş Geldiniz.**\n\n"
        "🔹 **Sovereign Layer 1 Blockchain**\n"
        "🔹 **SHA-256 Proof-of-Work Madencilik**\n"
        "🔹 **EVM & MetaMask Hibrit Köprüsü**\n"
        "🔹 **21.000.001 UNIVA Maksimum Arz**\n\n"
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
            InlineKeyboardButton("🌐 Web Explorer", url=f"{WEBAPP_URL}"),
            InlineKeyboardButton("📖 Whitepaper", url=f"{WEBAPP_URL}/whitepaper")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

def main():
    if TELEGRAM_BOT_TOKEN == "BOT_TOKENINIZI_BURAYA_GIRIN":
        print("[UNIVA BOT] Lutfen BotFather'dan aldiginiz token'i telegram_bot.py icine girin.")
        return
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("[UNIVA BOT] Telegram botu dinlemede...")
    app.run_polling()

if __name__ == "__main__":
    main()
