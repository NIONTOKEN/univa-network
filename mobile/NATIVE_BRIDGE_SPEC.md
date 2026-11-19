# UNIVA Android & iOS Native Mobile Bridge Specification

Bu klasör, UNIVA PWA arayüzünün (`../pwa`) **Capacitor** üzerinden gerçek **Android (APK/AAB)** ve **iOS (IPA)** uygulamalarına paketlenmesi için hazır altyapıyı içerir.

`pwa/offline-transport.js` dosyası çalıştığı ortamı otomatik algılar:
- **Web tarayıcıda:** QR (tam destek), Android Chrome Web NFC, Web Bluetooth Central (yalnızca istemci).
- **Android / iOS yerel uygulamada (`window.Capacitor.Plugins.UnivaNFC` / `UnivaBLE`):** Tam çift yönlü telefondan telefona BLE (Peripheral + Central) ve Android HCE / iOS CoreNFC desteği otomatik devreye girer.

## 1. BLE GATT Protokol Sözleşmesi
- **Service UUID:** `756e6976-6100-4000-8000-000000000001`
- **TX Characteristic (Notify / Read):** `756e6976-6100-4000-8000-000000000002`
- **RX Characteristic (Write):** `756e6976-6100-4000-8000-000000000003`
- **Çerçeve Formatı (`encodeBleFrames`):** `[0x55, seqIdx, totalChunks, crc8, ...utf8Payload]`

## 2. Native Plugin Arayüzleri (Kotlin / Swift)
### `UnivaNFC`
- `writeVoucher({ token: string }) -> Promise<{ ok: true }>`
- `readVoucher() -> Promise<{ token: string }>`

### `UnivaBLE`
- `advertiseVoucher({ serviceUuid, txCharUuid, rxCharUuid, token, framesBase64 }) -> Promise<{ ok: true }>`
- `scanAndReceive({ serviceUuid, txCharUuid }) -> Promise<{ token: string }>`
- `sendToPeripheral({ serviceUuid, rxCharUuid, framesBase64 }) -> Promise<{ ok: true }>`

## 3. Zorunlu Platform İzinleri
### Android (`AndroidManifest.xml`)
- `android.permission.CAMERA`
- `android.permission.NFC`
- `android.permission.BLUETOOTH_SCAN`
- `android.permission.BLUETOOTH_CONNECT`
- `android.permission.BLUETOOTH_ADVERTISE`

### iOS (`Info.plist`)
- `NSCameraUsageDescription`: "UNIVA QR ödeme fişlerini taramak için kamera izni gerektirir."
- `NFCReaderUsageDescription`: "UNIVA çevrimdışı ödeme fişlerini NFC ile okumak/yazmak için gereklidir."
- `NSBluetoothAlwaysUsageDescription`: "UNIVA çevrimdışı ödeme fişlerini yakındaki cihazlarla Bluetooth LE üzerinden aktarmak için gereklidir."

## 4. Derleme Adımları (Denetim P0–P7 Bittiğinde)
```bash
cd mobile
npm install
npm run android:add   # Android Studio projesi oluşturur
npm run ios:add       # Xcode projesi oluşturur (macOS)
npm run cap:sync      # ../pwa dosyalarını senkronize eder
```
