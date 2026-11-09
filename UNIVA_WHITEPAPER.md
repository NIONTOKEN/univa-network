# UNIVA NETWORK WHITEPAPER (v4.0.0)
## Evrensel Egemen Layer 1 Blokzincir Protokolü

**Yazar / Mimar:** UNIVA Core Engineering  
**Genesis Tarihi:** 2026  
**Ağ Durumu:** Mainnet Alpha (Canlı — Erken Erişim)  
**Resmi Standart:** SHA-256 PoW · MTP BIP-113 · 30-Karakter L1 Adres Standardı v4.0 · EVM Hibrit Köprüsü  
**Versiyon Notu:** v4.0.0 — 30 karakterlik yeni adres standardı ve EVM Hibrit desteği eklendi. Eski 20-karakter format geriye dönük uyumluluk için korunmaktadır ancak artık birincil standart değildir.

---

## 1. Giriş ve Varoluş Nedeni (Executive Summary)

Kripto para dünyası binlerce kopya EVM fork'u, merkezi sunucularda çalışan sahte "merkeziyetsiz" ağlar ve aşırı karmaşık köprü (bridge) protokolleriyle doludur. Çoğu ağ, kendi güvenliğini sağlayamaz ve Ethereum veya Binance Smart Chain'e göbekten bağlıdır.

**UNIVA Network, bir token veya EVM klonu DEĞİLDİR.**  
UNIVA, Bitcoin felsefesiyle inşa edilmiş, kendi mutabakat kurallarına (Consensus), bağımsız madencilik algoritmasına, yerel DEX durum geçişine (State Transition) ve benzersiz **30 karakterlik** adres standardına sahip **özgür bir Layer 1 blokzinciridir**.

UNIVA aynı zamanda MetaMask ve diğer EVM cüzdanları için **EVM JSON-RPC köprüsü** sunar (Chain ID: 210001).

### Temel Soru: Neden UNIVA?
1. **Gerçek Bağımsızlık:** Akıllı sözleşme hacklerine ve gas manipülasyonlarına açık EVM yerine, doğrudan protokol seviyesinde çalışan yerleşik AMM (Automated Market Maker) motoru.
2. **İnsan Odaklı Adres Standardı:** 42 karakterlik karmaşık heksadesimal diziler yerine, insan gözünün anında tanıdığı ve 2.48 × 10³⁷ benzersiz kapasite sunan `univaXXXXXXXXXXXXXXXXXXXXXXXXX` mimarisi (toplam 30 karakter).
3. **Zaman Damgası Koruması:** Bitcoin BIP-113 Median Time Past (MTP) ile zorluk ve madenci zaman hilelerine karşı %100 matematiksel bağışıklık.
4. **Borsa ve Cüzdan Uyumluluğu:** Bitcoin Core JSON-RPC 2.0 standardı ve EVM JSON-RPC köprüsü sayesinde hem geleneksel borsalar hem MetaMask/Trust Wallet entegrasyonu desteklenir.

---

## 2. Para Politikası ve Matematiksel Kurallar

UNIVA'nın arz kuralları protokole kazınmıştır ve asla değiştirilemez:

| Parametre | Değer |
|-----------|-------|
| **Maksimum Arz** | 21,000,001.0 UNIVA (değiştirilemez) |
| **Başlangıç Blok Ödülü** | 100.0 UNIVA / blok |
| **Hedef Blok Süresi** | 60 saniye |
| **Yarılanma Periyodu** | Her 43,200 blok (~30 gün) |
| **Konsensüs** | SHA-256 Proof of Work |
| **Zorluk Ayarlama** | Her 60 blokta bir otomatik |
| **EVM Chain ID** | 210001 (hex: 0x33451) |

---

## 3. Adres Standardı v4.0 (30 Karakter — Birincil)

UNIVA L1 adresleri kriptografik olarak türetilir:

$$\text{adres} = \underbrace{\text{``univa''}}_{\text{5 karakter önek}} + \underbrace{B_{31}^{25}}_{\text{25 karakter Base31 özet}} = 30 \text{ karakter}$$

- **Kapasite:** $31^{25} \approx 2.48 \times 10^{37}$ benzersiz adres (pratik olarak tükenmez)
- **Charset:** `23456789abcdefghjkmnpqrstuvwxyz` (karışan 0, O, 1, I, L çıkarıldı)
- **Türetme:** `SHA-256(pubkey) → RIPEMD-160 → Base31`
- **Örnek:** `univaf63aua23vxdvcmvkunx66yzh2`

### Geriye Dönük Uyumluluk (Eski v3 Format — 20 karakter)
Eski format `univa` + 10 Base31 karakter + `univa` = 20 karakter yapısını kullanır (örnek: `univad8b5aba3q9univa`). Bu format **artık birincil standart değildir**, yalnızca eski zincirlerin doğrulanması için korunmaktadır. Yeni cüzdanlar otomatik olarak v4 (30 karakter) formatında oluşturulur.

### EVM Ayna Adresi (MetaMask Uyumluluğu)
Her UNIVA L1 cüzdanının bir EVM ayna adresi (`0x...`) de mevcuttur. MetaMask kullanıcıları UNIVA'yı **Özel Ağ** olarak şu bilgilerle ekleyebilir:
- RPC URL: `https://[NODE_URL]/rpc`
- Chain ID: `210001`
- Sembol: `UNIVA`

---

## 4. Çift Katmanlı Depolama

1. **JSON Zinciri** (`univa_chain.json`): İnsan okunabilir, silinmez kayıt defteri — **konsensüsün asıl kaynağı**
2. **SQLite3 WAL** (`univa_chain.db`): Kurumsal hız indeksi — JSON'dan yeniden inşa edilebilir, konsensüs kaynağı değildir

---

## 5. Yerel AMM (Native DEX)

UNIVA'nın yerleşik DEX motoru, akıllı sözleşmeler olmadan doğrudan protokol katmanında çalışır:

- **Formül:** $x \cdot y = k$ (Sabit çarpım AMM)
- **Protokol Ücreti:** %0.10 (10 bps)
- **Minimum Likidite:** 1,000 baz birim (LP kilidi)
- **Slippage Koruması:** Her swap için kontrol edilir

> [!IMPORTANT]
> **Mevcut Durum (Mainnet Alpha):** DEX motoru (`core/dex.py`) şu anda bir in-process AMM simülasyonudur. Rezervler ve token bakiyeleri L1 konsensüs/durum geçişine henüz tam olarak entegre edilmemiştir. DEX'in konsensüs katmanına tam entegrasyonu aktif geliştirme aşamasındadır.

---

## 6. API Standartları

| Port | Protokol | Açıklama |
|------|----------|----------|
| **5050** | HTTP REST | Cüzdan, blok, işlem, istatistik uç noktaları |
| **5050** | JSON-RPC (`POST /rpc`) | Bitcoin Core RPC uyumlu + EVM JSON-RPC adaptörü |
| **5051** | WebSocket P2P | asyncio Gossip Protokolü (düğümler arası senkronizasyon) |

### Desteklenen Bitcoin Core RPC Metodları
`getblockchaininfo`, `getblock`, `getblockhash`, `getblockcount`, `sendrawtransaction`, `getmininginfo`, `getbalance`, `getnetworkinfo`, `getbestblockhash`

### Desteklenen EVM JSON-RPC Metodları
`eth_chainId`, `eth_blockNumber`, `eth_getBalance`, `eth_gasPrice`, `eth_estimateGas`, `eth_getTransactionCount`, `eth_getBlockByNumber`, `eth_sendRawTransaction`

---

## 7. Borsa & Cüzdan Entegrasyonu

UNIVA iki farklı entegrasyon yolunu destekler:

### Yol A — Doğal UNIVA Cüzdanı (Önerilen)
PWA, Android APK, Windows Uygulaması ve Telegram Mini App cüzdanı üzerinden kullanıcılar doğrudan 30 karakterlik UNIVA L1 adresleriyle işlem yapar.

### Yol B — EVM RPC Köprüsü (MetaMask/Trust Wallet İçin)
`POST /rpc` uç noktası EVM JSON-RPC protokolünü taklit eder. MetaMask kullanıcıları "Özel Ağ Ekle" ile Chain ID 210001 üzerinden bağlanabilir. Adres formatı farkı (univa... vs 0x...) köprü katmanı tarafından çözülür.

---

## 8. Mevcut Durum ve Yol Haritası

| Bileşen | Durum |
|---------|-------|
| SHA-256 PoW Konsensüsü | ✅ Üretimde |
| L1 Cüzdan (30-karakter) | ✅ Üretimde |
| P2P Gossip Protokolü | ✅ Aktif (testnet ölçeği) |
| Bitcoin Core RPC | ✅ Üretimde |
| EVM JSON-RPC Köprüsü | ✅ Üretimde |
| PWA / Telegram Mini App | ✅ Canlı |
| Çift Katmanlı Depolama | ✅ Üretimde |
| DEX Konsensüs Entegrasyonu | 🔄 Geliştirmede |
| P2P DDoS / Eclipse Koruması | 🔄 Geliştirmede |
| Bağımsız Güvenlik Denetimi | 📋 Planlandı |

> [!NOTE]
> UNIVA şu anda **Mainnet Alpha** aşamasındadır. Çekirdek konsensüs, madencilik ve cüzdan işlevleri canlıdır. DEX konsensüs entegrasyonu ve P2P güvenlik sertleştirmesi aktif geliştirme altındadır. Kullanıcıların mevcut yetenekler hakkında bilinçli olmaları önerilir.

---

## 9. Teknik Mimari Özeti

```
┌─────────────────────────────────────────────────────┐
│                   UNIVA NETWORK                     │
├─────────────────┬───────────────────────────────────┤
│  PWA / Mini App │  Telegram Bot / Android APK       │
├─────────────────┴───────────────────────────────────┤
│           HTTP REST API (port 5050)                 │
│    Bitcoin RPC · EVM RPC · DEX · Explorer           │
├─────────────────────────────────────────────────────┤
│          UNIVA Core Blockchain Engine               │
│  SHA-256 PoW · UTXO/Account Hibrit · AMM DEX        │
├──────────────────────┬──────────────────────────────┤
│  JSON Chain (Konsensüs)  │  SQLite3 WAL (İndeks)   │
├──────────────────────┴──────────────────────────────┤
│        P2P WebSocket Gossip (port 5051)             │
└─────────────────────────────────────────────────────┘
```

---

*UNIVA Network — Tüm Ağlar, Tek Çatı Altında*  
*Whitepaper v4.0.0 · Genesis 2026 · Chain ID 210001*
