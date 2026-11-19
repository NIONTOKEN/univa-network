/**
 * UNIVA Offline Pay Unified Transport Layer (QR + NFC + BLE)
 * Works seamlessly in:
 *   1. Native Android / iOS Capacitor App via window.Capacitor.Plugins.{UnivaNFC, UnivaBLE}
 *      or window.UnivaNativeBridge (Full Phone-to-Phone BLE Peripheral+Central & Android/iOS NFC)
 *   2. Web Browser PWA (QR Camera/Canvas + Android Chrome Web NFC + Web Bluetooth Central)
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.UnivaOfflineTransport = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // UNIVA Custom BLE GATT Service & Characteristics (RFC 4122 UUIDs; ASCII prefix "univa")
  const BLE_SERVICE_UUID = '756e6976-6100-4000-8000-000000000001';
  const BLE_TX_CHAR_UUID = '756e6976-6100-4000-8000-000000000002'; // Notify / Read (Sender -> Receiver)
  const BLE_RX_CHAR_UUID = '756e6976-6100-4000-8000-000000000003'; // Write (Sender Central -> POS / Receiver)
  const BLE_FRAME_MAGIC  = 0x55; // 'U'
  const BLE_HEADER_LEN   = 4;    // [magic, seqIdx, totalChunks, crc8]

  function crc8(bytes) {
    let crc = 0x00;
    for (let i = 0; i < bytes.length; i++) {
      crc ^= bytes[i];
      for (let b = 0; b < 8; b++) {
        crc = (crc & 0x80) ? ((crc << 1) ^ 0x07) & 0xff : (crc << 1) & 0xff;
      }
    }
    return crc;
  }

  function utf8Encode(str) {
    if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(str);
    return Uint8Array.from(Buffer.from(str, 'utf8'));
  }

  function utf8Decode(bytes) {
    if (typeof TextDecoder !== 'undefined') return new TextDecoder('utf-8').decode(bytes);
    return Buffer.from(bytes).toString('utf8');
  }

  /**
   * Split an offline voucher string into MTU-safe BLE frames with CRC-8 integrity checks.
   * Supports legacy BLE 4.0 (MTU=20 -> 16B payload) through BLE 5.0 (MTU=180..512).
   */
  function encodeBleFrames(voucherToken, mtu) {
    const safeMtu = Math.max(20, Math.min(512, parseInt(mtu || 180, 10)));
    const payloadMax = safeMtu - BLE_HEADER_LEN;
    const raw = utf8Encode(String(voucherToken || ''));
    if (raw.length === 0) throw new Error('Voucher payload cannot be empty');
    const totalChunks = Math.ceil(raw.length / payloadMax);
    if (totalChunks > 255) throw new Error('Voucher exceeds maximum BLE frame count (255)');
    const frames = [];
    for (let i = 0; i < totalChunks; i++) {
      const slice = raw.slice(i * payloadMax, (i + 1) * payloadMax);
      const frame = new Uint8Array(BLE_HEADER_LEN + slice.length);
      frame[0] = BLE_FRAME_MAGIC;
      frame[1] = i;
      frame[2] = totalChunks;
      frame[3] = crc8(slice);
      frame.set(slice, BLE_HEADER_LEN);
      frames.push(frame);
    }
    return frames;
  }

  class BleFrameAssembler {
    constructor() {
      this.reset();
    }
    reset() {
      this.total = 0;
      this.chunks = new Map();
    }
    pushFrame(frameInput) {
      const frame = frameInput instanceof Uint8Array
        ? frameInput
        : new Uint8Array(frameInput.buffer || frameInput);
      if (frame.length <= BLE_HEADER_LEN || frame[0] !== BLE_FRAME_MAGIC) {
        throw new Error('Invalid BLE frame header');
      }
      const seq = frame[1];
      const total = frame[2];
      const expectedCrc = frame[3];
      const payload = frame.slice(BLE_HEADER_LEN);
      if (total <= 0 || seq >= total) {
        throw new Error('Invalid BLE frame sequence bounds');
      }
      if (crc8(payload) !== expectedCrc) {
        throw new Error('BLE frame CRC-8 checksum mismatch');
      }
      if (this.total !== 0 && this.total !== total) {
        this.reset();
      }
      this.total = total;
      this.chunks.set(seq, payload);
      if (this.chunks.size === this.total) {
        let fullLen = 0;
        for (let i = 0; i < this.total; i++) fullLen += this.chunks.get(i).length;
        const merged = new Uint8Array(fullLen);
        let offset = 0;
        for (let i = 0; i < this.total; i++) {
          const part = this.chunks.get(i);
          merged.set(part, offset);
          offset += part.length;
        }
        this.reset();
        return utf8Decode(merged);
      }
      return null;
    }
  }

  function getNativeBridge() {
    const w = typeof window !== 'undefined' ? window : {};
    const capPlugins = (w.Capacitor && w.Capacitor.Plugins) ? w.Capacitor.Plugins : {};
    const custom = w.UnivaNativeBridge || {};
    return {
      isCapacitor: Boolean(w.Capacitor && typeof w.Capacitor.isNativePlatform === 'function' && w.Capacitor.isNativePlatform()),
      nfc: capPlugins.UnivaNFC || (custom.nfcWrite ? { writeVoucher: custom.nfcWrite, readVoucher: custom.nfcRead } : null),
      ble: capPlugins.UnivaBLE || (custom.bleAdvertise ? {
        advertiseVoucher: custom.bleAdvertise,
        scanAndReceive: custom.bleScanAndReceive,
        sendToPeripheral: custom.bleSendToPeripheral
      } : null)
    };
  }

  function detectCapabilities() {
    const w = typeof window !== 'undefined' ? window : {};
    const nav = typeof navigator !== 'undefined' ? navigator : {};
    const native = getNativeBridge();
    const hasWebNfc = Boolean('NDEFReader' in w);
    const hasWebBle = Boolean(nav.bluetooth && typeof nav.bluetooth.requestDevice === 'function');
    const hasCameraQr = Boolean('BarcodeDetector' in w && nav.mediaDevices && nav.mediaDevices.getUserMedia);

    const nfc = native.nfc
      ? { supported: true, write: true, read: true, mode: 'native-android-ios', reason: 'Yerel Android/iOS NFC Köprüsü Aktif' }
      : hasWebNfc
        ? { supported: true, write: true, read: true, mode: 'web-nfc-android', reason: 'Android Chrome Web NFC Aktif' }
        : { supported: false, write: false, read: false, mode: 'unavailable', reason: 'Web NFC yalnızca Android Chrome’da veya yerel Android/iOS uygulamasında çalışır' };

    const ble = native.ble
      ? { supported: true, central: true, peripheral: true, mode: 'native-android-ios', reason: 'Yerel Android/iOS Çift Yönlü BLE Aktif' }
      : hasWebBle
        ? { supported: true, central: true, peripheral: false, mode: 'web-ble-central-only', reason: 'Tarayıcı Web BLE yalnızca İstemci (POS/Alıcıya bağlanma) destekler; telefondan telefona BLE yayını yerel Android/iOS uygulamasında aktif olur' }
        : { supported: false, central: false, peripheral: false, mode: 'unavailable', reason: 'Web Bluetooth bu tarayıcıda desteklenmiyor (yerel Android/iOS uygulamasında aktif olur)' };

    return {
      runtime: native.isCapacitor ? 'native-mobile' : 'web-browser',
      qr: { supported: true, write: true, scanCamera: hasCameraQr, paste: true },
      nfc,
      ble,
      gatt: {
        serviceUuid: BLE_SERVICE_UUID,
        txCharUuid: BLE_TX_CHAR_UUID,
        rxCharUuid: BLE_RX_CHAR_UUID
      }
    };
  }

  async function sendViaNfc(voucherToken) {
    const native = getNativeBridge();
    if (native.nfc && typeof native.nfc.writeVoucher === 'function') {
      await native.nfc.writeVoucher({ token: voucherToken });
      return { ok: true, mode: 'native-android-ios' };
    }
    if (typeof window !== 'undefined' && 'NDEFReader' in window) {
      const ndef = new window.NDEFReader();
      await ndef.write({
        records: [{ recordType: 'text', data: String(voucherToken) }]
      });
      return { ok: true, mode: 'web-nfc-android' };
    }
    throw new Error('NFC bu cihazda/tarayıcıda desteklenmiyor (Android Chrome veya yerel Android/iOS uygulaması gerekir).');
  }

  async function receiveViaNfc(onVoucher) {
    const native = getNativeBridge();
    if (native.nfc && typeof native.nfc.readVoucher === 'function') {
      const res = await native.nfc.readVoucher();
      if (res && res.token && typeof onVoucher === 'function') onVoucher(res.token, 'nfc');
      return { ok: true, mode: 'native-android-ios', stop: function () {} };
    }
    if (typeof window !== 'undefined' && 'NDEFReader' in window) {
      const abortCtrl = new AbortController();
      const ndef = new window.NDEFReader();
      await ndef.scan({ signal: abortCtrl.signal });
      ndef.onreading = function (event) {
        try {
          for (const rec of event.message.records) {
            if (rec.recordType === 'text' || rec.recordType === 'mime') {
              const txt = utf8Decode(new Uint8Array(rec.data.buffer));
              if (txt && (txt.startsWith('UNIVA:OFF:V2:') || txt.startsWith('UNIVA:OFF:V1:'))) {
                if (typeof onVoucher === 'function') onVoucher(txt.trim(), 'nfc');
                abortCtrl.abort();
                return;
              }
            }
          }
        } catch (e) {}
      };
      return { ok: true, mode: 'web-nfc-android', stop: function () { abortCtrl.abort(); } };
    }
    throw new Error('NFC okuma bu cihazda/tarayıcıda desteklenmiyor (Android Chrome veya yerel Android/iOS uygulaması gerekir).');
  }

  async function advertiseViaBle(voucherToken) {
    const frames = encodeBleFrames(voucherToken, 180);
    const native = getNativeBridge();
    if (native.ble && typeof native.ble.advertiseVoucher === 'function') {
      await native.ble.advertiseVoucher({
        serviceUuid: BLE_SERVICE_UUID,
        txCharUuid: BLE_TX_CHAR_UUID,
        rxCharUuid: BLE_RX_CHAR_UUID,
        token: voucherToken,
        framesBase64: frames.map(f => btoa(String.fromCharCode.apply(null, f)))
      });
      return { ok: true, mode: 'native-android-ios', frameCount: frames.length };
    }
    throw new Error('Web tarayıcıları BLE Peripheral (yayın) modunu kısıtlar. Yerel Android/iOS uygulaması derlendiğinde otomatik çalışacaktır; tarayıcıda "BLE POS/Alıcıya Gönder" veya QR/NFC kullanın.');
  }

  async function sendViaBleCentral(voucherToken) {
    const frames = encodeBleFrames(voucherToken, 180);
    const native = getNativeBridge();
    if (native.ble && typeof native.ble.sendToPeripheral === 'function') {
      await native.ble.sendToPeripheral({
        serviceUuid: BLE_SERVICE_UUID,
        rxCharUuid: BLE_RX_CHAR_UUID,
        framesBase64: frames.map(f => btoa(String.fromCharCode.apply(null, f)))
      });
      return { ok: true, mode: 'native-android-ios', frameCount: frames.length };
    }
    if (typeof navigator !== 'undefined' && navigator.bluetooth && navigator.bluetooth.requestDevice) {
      const device = await navigator.bluetooth.requestDevice({
        filters: [{ services: [BLE_SERVICE_UUID] }]
      });
      const server = await device.gatt.connect();
      const service = await server.getPrimaryService(BLE_SERVICE_UUID);
      const rxChar = await service.getCharacteristic(BLE_RX_CHAR_UUID);
      for (const frame of frames) {
        await rxChar.writeValue(frame);
      }
      try { device.gatt.disconnect(); } catch (e) {}
      return { ok: true, mode: 'web-ble-central', frameCount: frames.length, deviceName: device.name || 'UNIVA BLE' };
    }
    throw new Error('Bu tarayıcıda Web Bluetooth desteklenmiyor (Chrome/Edge veya yerel Android/iOS uygulaması gerekir).');
  }

  async function scanViaBle(onVoucher) {
    const native = getNativeBridge();
    if (native.ble && typeof native.ble.scanAndReceive === 'function') {
      const res = await native.ble.scanAndReceive({
        serviceUuid: BLE_SERVICE_UUID,
        txCharUuid: BLE_TX_CHAR_UUID
      });
      if (res && res.token && typeof onVoucher === 'function') onVoucher(res.token, 'ble');
      return { ok: true, mode: 'native-android-ios' };
    }
    if (typeof navigator !== 'undefined' && navigator.bluetooth && navigator.bluetooth.requestDevice) {
      const device = await navigator.bluetooth.requestDevice({
        filters: [{ services: [BLE_SERVICE_UUID] }]
      });
      const server = await device.gatt.connect();
      const service = await server.getPrimaryService(BLE_SERVICE_UUID);
      const txChar = await service.getCharacteristic(BLE_TX_CHAR_UUID);
      const assembler = new BleFrameAssembler();
      await txChar.startNotifications();
      txChar.addEventListener('characteristicvaluechanged', function (ev) {
        try {
          const dv = ev.target.value;
          const bytes = new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength);
          const complete = assembler.pushFrame(bytes);
          if (complete) {
            if (typeof onVoucher === 'function') onVoucher(complete, 'ble');
            try { device.gatt.disconnect(); } catch (e) {}
          }
        } catch (e) {}
      });
      return { ok: true, mode: 'web-ble-central', deviceName: device.name || 'UNIVA BLE' };
    }
    throw new Error('Bu tarayıcıda Web Bluetooth desteklenmiyor (yerel Android/iOS uygulaması gerekir).');
  }

  return {
    BLE_SERVICE_UUID,
    BLE_TX_CHAR_UUID,
    BLE_RX_CHAR_UUID,
    crc8,
    encodeBleFrames,
    BleFrameAssembler,
    detectCapabilities,
    sendViaNfc,
    receiveViaNfc,
    advertiseViaBle,
    sendViaBleCentral,
    scanViaBle
  };
});
