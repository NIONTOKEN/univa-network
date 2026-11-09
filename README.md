# UNIVA Network

**Egemen Layer 1 Blokzincir · SHA-256 PoW · EVM Hibrit Köprüsü**

[![Vercel](https://img.shields.io/badge/PWA-Canlı-brightgreen)](https://univa-network-l1.vercel.app)
[![GitHub](https://img.shields.io/badge/GitHub-NIONTOKEN/univa--network-blue)](https://github.com/NIONTOKEN/univa-network)
[![Telegram](https://img.shields.io/badge/Telegram-@UnivaNetworkBot-blue)](https://t.me/UnivaNetworkBot)
[![Chain ID](https://img.shields.io/badge/Chain%20ID-210001-orange)](https://univa-network-l1.vercel.app)

---

## 🌐 Hızlı Erişim

| Platform | Link |
|----------|------|
| **Web PWA Cüzdan** | https://univa-network-l1.vercel.app |
| **Telegram Mini App** | https://t.me/UnivaNetworkBot |
| **GitHub Kaynak** | https://github.com/NIONTOKEN/univa-network |

---

## ℹ️ Ağ Durumu

**UNIVA şu anda Mainnet Alpha aşamasındadır.**

| Bileşen | Durum |
|---------|-------|
| SHA-256 PoW Konsensüsü | ✅ Üretimde |
| L1 Cüzdan (30 karakter) | ✅ Üretimde |
| Bitcoin Core RPC | ✅ Üretimde |
| EVM JSON-RPC Köprüsü (Chain ID: 210001) | ✅ Üretimde |
| PWA / Telegram Mini App | ✅ Canlı |
| P2P Gossip Protokolü | ✅ Aktif |
| DEX Konsensüs Entegrasyonu | 🔄 Geliştirmede |
| Bağımsız Güvenlik Denetimi | 📋 Planlandı |

> **Not:** DEX (`core/dex.py`) şu anda bir in-process AMM simülasyonudur. Rezervler L1 konsensüs blok durumuna henüz tam entegre edilmemiştir. Bu özellik aktif geliştirme altındadır.

---

## 🏗️ Mimari

UNIVA, bir EVM klonu veya token değildir. Bitcoin felsefesiyle inşa edilmiş **bağımsız bir Layer 1 blokzinciridir**:

- **Konsensüs:** SHA-256 Proof of Work
- **Adres Standardı:** `univa` + 25 Base31 karakter = **30 karakter** (örn: `univaf63aua23vxdvcmvkunx66yzh2`)
- **EVM Uyumluluğu:** MetaMask / Trust Wallet için JSON-RPC köprüsü (Chain ID: 210001)
- **Depolama:** JSON zinciri (konsensüs kaynağı) + SQLite3 WAL (hız indeksi)
- **DEX:** x·y=k AMM motoru, %0.10 protokol ücreti
- **Maksimum Arz:** 21,000,001.0 UNIVA

---

## 🚀 Kurulum (Yerel Düğüm)

Python 3.10+ gereklidir.

```bash
git clone https://github.com/NIONTOKEN/univa-network.git
cd univa-network

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
python run.py --node
```

Düğüm `http://127.0.0.1:5050` adresinde başlar.

---

## 💳 Adres Standardı

| Versiyon | Format | Uzunluk | Kapasite | Durum |
|----------|--------|---------|----------|-------|
| **v4.0 (Yeni)** | `univa` + 25 Base31 | **30 karakter** | 2.48 × 10³⁷ | ✅ Birincil |
| v3.0 (Eski) | `univa` + 10 Base31 + `univa` | 20 karakter | 819 trilyon | ⚠️ Geriye dönük uyumluluk |

Eski v3 adresler doğrulama için hâlâ kabul edilir ancak yeni cüzdanlar otomatik olarak v4 formatında oluşturulur.

---

## 🔗 MetaMask ile Bağlanma

| Alan | Değer |
|------|-------|
| Ağ Adı | UNIVA Network |
| RPC URL | `http://127.0.0.1:5050/rpc` (yerel) |
| Chain ID | `210001` |
| Sembol | `UNIVA` |
| Explorer | https://univa-network-l1.vercel.app |

---

## 🛠️ API Referansı

```bash
# Zincir istatistikleri
GET http://127.0.0.1:5050/stats

# Bakiye sorgulama
GET http://127.0.0.1:5050/api/v1/balance/{adres}

# İşlem geçmişi
GET http://127.0.0.1:5050/api/v1/history/{adres}

# Yeni cüzdan oluştur
POST http://127.0.0.1:5050/api/v1/wallet/create

# İşlem gönder
POST http://127.0.0.1:5050/tx

# EVM JSON-RPC (MetaMask uyumlu)
POST http://127.0.0.1:5050/rpc
{"method": "eth_chainId"}        → "0x33451"
{"method": "eth_blockNumber"}    → güncel blok yüksekliği

# Bitcoin Core JSON-RPC
{"method": "getblockchaininfo"}  → zincir bilgisi
{"method": "getmininginfo"}      → madencilik bilgisi
```

---

## 📁 Proje Yapısı

```
univa-network/
├── core/
│   ├── blockchain.py    # SHA-256 PoW konsensüs motoru
│   ├── wallet.py        # L1 + EVM adres türetme (secp256k1)
│   ├── network.py       # FastAPI REST + RPC sunucusu
│   ├── miner.py         # Madencilik motoru
│   ├── dex.py           # AMM DEX motoru (geliştirmede)
│   ├── p2p.py           # WebSocket P2P gossip protokolü
│   ├── database.py      # SQLite3 WAL indeksi
│   └── node.py          # Düğüm başlatıcı
├── pwa/
│   ├── index.html       # Web cüzdan PWA
│   ├── manifest.json    # PWA manifesti
│   └── sw.js            # Service Worker
├── telegram_bot.py      # Telegram Mini App botu
├── run.py               # Ana başlatıcı
├── vercel.json          # Vercel PWA dağıtım yapılandırması
├── requirements.txt     # Python bağımlılıkları
└── UNIVA_WHITEPAPER.md  # Teknik Whitepaper v4.0
```

---

## ⚠️ Önemli Notlar

- **Özel anahtarlarınızı** asla kimseyle paylaşmayın ve güvenli yerde saklayın.
- DEX konsensüs entegrasyonu tamamlanana kadar Swap işlemleri simülasyon modunda çalışır.
- P2P katmanı henüz adversarial testlerden geçmemiştir; üretime alınmadan önce güvenlik denetimi planlanmaktadır.

---

*UNIVA Network — Tüm Ağlar, Tek Çatı Altında*  
*v4.0.0 · Genesis 2026 · Chain ID 210001*
