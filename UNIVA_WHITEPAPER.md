# UNIVA NETWORK WHITEPAPER (v3.0.0)
## Evrensel Egemen Layer 1 Blokzincir Protokolü

**Yazar / Mimar:** UNIVA Core Engineering  
**Genesis Tarihi:** 2026  
**Ağ Durumu:** Canlı (Mainnet Alpha)  
**Standart:** SHA-256 PoW · MTP BIP-113 · 20-Karakter Adres Standardi  

---

## 1. Giriş

UNIVA, Bitcoin felsefesiyle inşa edilmiş, kendi mutabakat kurallarına, bağımsız madencilik algoritmasına, yerel DEX durum geçişine ve benzersiz **20 karakterlik** adres standardına sahip özgür bir Layer 1 blokzinciridir.

---

## 2. Para Politikası

| Parametre | Değer |
|-----------|-------|
| Maksimum Arz | **21,000,001.0 UNIVA** (değiştirilemez) |
| Başlangıç Blok Ödülü | **100.0 UNIVA / blok** |
| Hedef Blok Süresi | **60 saniye** |
| Yarılanma Periyodu | Her **43,200 blok** (~30 gün) |
| Konsensüs | **SHA-256 Proof of Work** |
| Zorluk Ayarlama | Her 60 blokta bir otomatik |

---

## 3. 20 Karakterlik Adres Standardı

$$\text{univa} + \underbrace{X \times 10}_{\text{Base31}} + \text{univa} = 20 \text{ karakter}$$

- **Kapasite:** $31^{10} \approx 819$ Trilyon benzersiz adres
- **Charset:** `23456789abcdefghjkmnpqrstuvwxyz` (karışan 0,O,1,I,L çıkarıldı)
- Örnek: `univad8b5aba3q9univa`

---

## 4. Çift Katmanlı Depolama

1. **JSON Zinciri** (`univa_chain.json`): İnsan okunabilir, silinmez kayıt defteri
2. **SQLite3 WAL** (`univa_chain.db`): Kurumsal hız indeksi

---

## 5. Yerel AMM (Native DEX)

- Formül: $x \cdot y = k$ (Sabit Çarpım)
- Protokol Ücreti: **%0.10**
- Akıllı sözleşme değil, doğrudan **blok durum geçişi** olarak çalışır

---

## 6. API Standartları

- **Port 5050:** HTTP REST + Bitcoin Core JSON-RPC 2.0 (`POST /rpc`)
- **Port 5051:** asyncio WebSocket P2P (Gossip Protokolü)

---

## 7. Borsa & Cüzdan Entegrasyonu

UNIVA, `POST /rpc` üzerinde Bitcoin Core ile aynı komutları destekler:
`getblockchaininfo`, `getblock`, `getblockhash`, `sendrawtransaction`, `getmininginfo`

Bu sayede mevcut borsa entegrasyon yazılımları UNIVA'yı sıfır ek geliştirme ile listeler.

---

*UNIVA Network — Tüm Ağlar, Tek Çatı Altında*

## Evrensel Egemen Layer 1 Blokzincir Protokolü (Sovereign Layer 1)

**Yazar / Mimar:** UNIVA Core Engineering  
**Genesis Tarihi:** 2026  
**Ağ Durumu:** Canlı (Mainnet Alpha)  
**Resmi Standart:** SHA-256 Proof of Work / MTP BIP-113 / Dual-Layer Storage  

---

## 1. Giriş ve Varoluş Nedeni (Executive Summary)

Kripto para dünyası binlerce kopya EVM fork'u, merkezi sunucularda çalışan sahte "merkeziyetsiz" ağlar ve aşırı karmaşık köprü (bridge) protokolleriyle doludur. Çoğu ağ, kendi güvenliğini sağlayamaz ve Ethereum veya Binance Smart Chain'e göbekten bağlıdır.

**UNIVA Network, bir token veya EVM klonu DEĞİLDİR.**  
UNIVA, Bitcoin felsefesiyle inşa edilmiş, kendi mutabakat kurallarına (Consensus), bağımsız madencilik algoritmasına, yerel DEX durum geçişine (State Transition) ve benzersiz 16 karakterlik adres standardına sahip **özgür bir Layer 1 blokzinciridir**.

### Temel Soru: Neden UNIVA?
1. **Gerçek Bağımsızlık:** Akıllı sözleşme hacklerine ve gas manipülasyonlarına açık EVM yerine, doğrudan protokol seviyesinde çalışan yerleşik AMM (Automated Market Maker) motoru.
2. **Kusursuz İnsan Odaklı Adres Standardı:** 42 karakterlik karmaşık heksadesimal diziler yerine, insan gözünün anında tanıdığı ve 887.5 milyon benzersiz kapasite sunan `univaXXXXXXuniva` mimarisi.
3. **Zaman Damgası Koruması:** Bitcoin BIP-113 Median Time Past (MTP) ile zorluk ve madenci zaman hilelerine karşı %100 matematiksel bağışıklık.
4. **Borsa ve Cüzdan Uyumluluğu:** Bitcoin Core JSON-RPC 2.0 standardı sayesinde tüm küresel borsalar ve donanım cüzdanları UNIVA'yı 1 satır kodla entegre edebilir.

---

## 2. Para Politikası ve Matematiksel Kurallar

UNIVA'nın arz kuralları protokole kazınmıştır ve asla değiştirilemez:

* **Maksimum Arz (Hard Cap):** Tam olarak `21,000,001.0 UNIVA` (Bir adet bile fazla üretilemez).
* **Başlangıç Blok Ödülü:** `100.0 UNIVA` / blok.
* **Hedef Blok Süresi:** `60 saniye`.
* **Yarılanma (Halving) Periyodu:** Her `43,200 blok`ta bir (~30 günde bir blok ödülü yarıya iner).
* **Konsensüs Algoritması:** SHA-256 Proof of Work (PoW).
* **Zorluk Ayarlama:** Her 60 blokta bir ağ hashrate'ine göre otomatik hesaplanır.

---

## 3. 16 Karakterlik Adres Standardı

Geleneksel blokzincirlerde adresler ya çok uzundur ya da yanlış yazılmaya müsaittir. UNIVA, insan odaklı benzersiz bir formül kullanır:

$$\text{Format: } \underbrace{\text{univa}}_{5\text{ harf}} + \underbrace{\text{XXXXXX}}_{6\text{ karakter (Base32)}} + \underbrace{\text{univa}}_{5\text{ harf}} = \mathbf{16\text{ Karakter}}$$

* **Karakter Seti:** `23456789abcdefghjkmnpqrstuvwxyz` (0, O, 1, I, L gibi karışan karakterler elenmiştir).
* **Adres Havuzu:** $31^6 = \mathbf{887,503,681}$ adet bağımsız cüzdan kapasitesi.
* **Doğrulama:** Protokol seviyesinde `univa` ön eki ve son eki olmayan hiçbir işleme izin verilmez.

---

## 4. Çift Katmanlı Depolama Mimarisi (Dual-Layer Storage)

UNIVA, güvenliği ve hızı aynı anda sağlamak için çift katmanlı depolama modeli uygular:
1. **Append-Only JSON Zinciri (`univa_chain.json`):** İnsan tarafından okunabilir, silinemez, otomatik `.bak` korumalı mutlak kayıt defteri.
2. **SQLite3 WAL İndeks Katmanı (`univa_chain.db`):** Mikrosaniyeler seviyesinde bakiye, işlem ve blok sorguları için kurumsal veritabanı.

---

## 5. Yerel AMM ve Durum Geçişi (Native Protocol AMM)

UNIVA, merkeziyetsiz takasları akıllı sözleşme olarak değil, **blok durum geçişi (State Transition)** olarak yürütür:
* Sabit Ürün Formülü: $x \cdot y = k$
* Protokol İşlem Ücreti: %0.10 (10 bps)
* Likidite havuzu doğrudan blok mutabakatı ile güvence altına alınır; hiçbir akıllı sözleşme açığı protokolü hackleyemez.

---

## 6. Küresel Entegrasyon ve API Arayüzü

Borsaların ve üçüncü parti servislerin bağlanabilmesi için UNIVA iki ana port üzerinden hizmet verir:

* **Port 5050 (HTTP REST & Bitcoin Core JSON-RPC):**
  - `POST /rpc` -> Standart Bitcoin Core komutları (`getblockchaininfo`, `getblock`, `sendrawtransaction`, `getmininginfo`, `getpeerinfo`)
  - `GET /stats` -> Anlık ağ istatistikleri
  - `POST /api/v1/dex/swap` -> Yerel takas
  - `GET /api/v1/telemetry/nodes` -> Küresel canlı düğüm ve cihaz haritası
* **Port 5051 (WebSocket P2P):**
  - asyncio tabanlı çift yönlü P2P blok/işlem yayını (Gossip protocol).

---

## 7. Sonuç

UNIVA, merkezi otoritelerden bağımsız, matematiksel kurallarla korunan, insan için tasarlanmış gerçek bir egemen blokzincirdir. Kod açık, zincir canlıdır.
