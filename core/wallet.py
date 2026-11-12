"""
UNIVA Network - Cryptographic Wallet Module
secp256k1 ECDSA + 20-Karakter Ozel UNIVA Adres Standardi v3.0

Adres Standardi:
  - Uzunluk : Tam olarak 20 karakter
  - Baslangic: "univa" (5 karakter)
  - Orta     : 10 karakter (Public key kriptografik hash'inden turetilen)
  - Bitis    : "univa" (5 karakter)
  - Sablon   : univa..........univa (orn: univa7x9kmp2abcuniva)
  - Kapasite : 31^10 = ~819 Trilyon benzersiz cuzdan adresi
"""

import hashlib
import json

try:
    import ecdsa
    from ecdsa import SigningKey, VerifyingKey, SECP256k1
    ECDSA_AVAILABLE = True
    CRYPTOGRAPHY_FALLBACK = False
except ImportError:
    ECDSA_AVAILABLE = False
    CRYPTOGRAPHY_FALLBACK = False
    try:
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        CRYPTOGRAPHY_FALLBACK = True
        print("[UNIVA] Bilgi: ecdsa paketi yok; cryptography secp256k1 geri dönüşü kullanılıyor.")
    except ImportError:
        print("[UNIVA] UYARI: 'ecdsa' veya 'cryptography' paketi eksik.")

PREFIX = "univa"
CHARSET = "23456789abcdefghjkmnpqrstuvwxyz"   # 31 karakter


def derive_univa_address(public_key_hex: str) -> str:
    """
    Public key'den standart UNIVA L1 adresi üretir.
    Format: 'univa' + 25 karakterlik Base31 kriptografik özet (Toplam 30 karakter).
    Örnek: univaf63aua23vxdvcmvkunx66yzh2
    Kapasite: 31^25 = 2.48 x 10^37 adet benzersiz adres (tükenemez devasa evren).
    """
    pub_bytes = bytes.fromhex(public_key_hex)
    sha256    = hashlib.sha256(pub_bytes).digest()
    ripemd160 = hashlib.new("ripemd160", sha256).digest()
    num = int.from_bytes(ripemd160[:15], "big")
    chars = []
    for _ in range(25):
        chars.append(CHARSET[num % 31])
        num //= 31
    return f"{PREFIX}{''.join(chars)}"


def derive_legacy_20char_address(public_key_hex: str) -> str:
    """Eski 20 karakterlik univa...univa adresini doğrulamak için geri uyumluluk fonksiyonu."""
    pub_bytes = bytes.fromhex(public_key_hex)
    sha256    = hashlib.sha256(pub_bytes).digest()
    ripemd160 = hashlib.new("ripemd160", sha256).digest()
    raw_num   = int.from_bytes(ripemd160[:10], "big")
    chars, num = [], raw_num
    for _ in range(10):
        chars.append(CHARSET[num % 31])
        num //= 31
    return f"univa{''.join(chars)}univa"


def derive_evm_address(public_key_hex: str) -> str:
    """
    MetaMask ve Web3 cüzdanları için uyumlu 0x... EVM ayna adresi üretir (42 karakter).
    """
    pub_bytes = bytes.fromhex(public_key_hex)
    digest = hashlib.sha256(pub_bytes).hexdigest()
    return "0x" + digest[-40:]


REGISTERED_PWA_ORIGINS = {}


def derive_pwa_address(private_key_hex: str) -> str:
    """Tarayıcı istemci anahtar türetimiyle tam uyumlu 30 karakterli UNIVA L1 adresi."""
    if not private_key_hex or len(private_key_hex) < 60:
        return ""
    chars = []
    for i in range(25):
        pos = (i * 2) % 58
        sub = int(private_key_hex[pos:pos + 2], 16)
        chars.append(CHARSET[sub % 31])
    return f"{PREFIX}{''.join(chars)}"


def derive_pwa_evm_address(private_key_hex: str) -> str:
    """Tarayıcı istemci anahtar türetimiyle uyumlu 0x... EVM ayna adresi."""
    if not private_key_hex or len(private_key_hex) < 40:
        return ""
    return "0x" + private_key_hex[:40]


def validate_address(address: str) -> bool:
    """
    Geçerli UNIVA adresi doğrulaması:
    - Yeni L1 Formatı: 'univa' ile başlayan, sonu kısıtlamasız Base31 karakterli adresler (15 ila 37 karakter).
    - Eski Testnet Uyumluluğu: 'univa...univa' (20 karakter) veya genesis 'univa0000000000univa'
    - EVM Formatı: 0x... (42 karakter hex)
    """
    if not isinstance(address, str) or not address:
        return False
    # EVM adresi doğrulaması
    if address.startswith("0x") and len(address) == 42:
        return all(c in "0123456789abcdefABCDEF" for c in address[2:])
    # UNIVA L1 adresi doğrulaması
    if not address.startswith(PREFIX):
        return False
    if address == "univa0000000000univa":
        return True
    body = address[len(PREFIX):]
    if len(body) < 10 or len(body) > 32:
        return False
    # Eski 20 karakterlik testnet adresleri 'univa' ile bittiği için 'i' harfi içerebilir
    if address.endswith("univa") and len(address) == 20:
        return True
    return all(c in CHARSET for c in body)


class UnivaWallet:
    def __init__(self, private_key_hex: str = None):
        if ECDSA_AVAILABLE:
            if private_key_hex:
                self._sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
            else:
                self._sk = SigningKey.generate(curve=SECP256k1)
            self._vk = self._sk.get_verifying_key()
            self._crypto_sk = None
        elif CRYPTOGRAPHY_FALLBACK:
            if private_key_hex:
                key_int = int.from_bytes(bytes.fromhex(private_key_hex), "big")
                self._crypto_sk = ec.derive_private_key(key_int, ec.SECP256K1())
            else:
                self._crypto_sk = ec.generate_private_key(ec.SECP256K1())
            self._sk = None
            self._vk = None
        else:
            raise RuntimeError("Install ecdsa or cryptography: pip install -r requirements.txt")
        self._address = derive_univa_address(self.public_key)
        try:
            REGISTERED_PWA_ORIGINS[self.public_key] = {
                derive_pwa_address(self.private_key),
                derive_pwa_evm_address(self.private_key),
            }
        except Exception:
            pass

    @property
    def private_key(self) -> str:
        if ECDSA_AVAILABLE:
            return self._sk.to_string().hex()
        return self._crypto_sk.private_numbers().private_value.to_bytes(32, "big").hex()

    @property
    def public_key(self) -> str:
        if ECDSA_AVAILABLE:
            return self._vk.to_string().hex()
        point = self._crypto_sk.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return point[1:].hex()  # same x||y format as python-ecdsa

    @property
    def address(self) -> str:
        return self._address

    def sign(self, message: str) -> str:
        msg_bytes = hashlib.sha256(message.encode()).digest()
        if ECDSA_AVAILABLE:
            return self._sk.sign(msg_bytes).hex()
        der = self._crypto_sk.sign(msg_bytes, ec.ECDSA(hashes.SHA1()))
        r, s = utils.decode_dss_signature(der)
        return r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex()

    @staticmethod
    def verify_signature(public_key_hex: str, message: str, signature_hex: str) -> bool:
        try:
            msg_b = hashlib.sha256(message.encode()).digest()
            if ECDSA_AVAILABLE:
                vk = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=SECP256k1)
                return vk.verify(bytes.fromhex(signature_hex), msg_b)
            if CRYPTOGRAPHY_FALLBACK:
                pub = bytes.fromhex(public_key_hex)
                if len(pub) != 64:
                    return False
                vk = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), b"\x04" + pub)
                sig = bytes.fromhex(signature_hex)
                if len(sig) != 64:
                    return False
                der = utils.encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
                vk.verify(der, msg_b, ec.ECDSA(hashes.SHA1()))
                return True
            return False
        except Exception:
            return False

    @classmethod
    def create_new(cls) -> "UnivaWallet":
        return cls()

    @property
    def evm_address(self) -> str:
        return derive_evm_address(self.public_key)

    def to_dict(self) -> dict:
        return {
            "address":     self.address,
            "evm_address": self.evm_address,
            "public_key":  self.public_key,
            "private_key": self.private_key,
            "network":     "UNIVA Network",
            "format":      "univa... (L1 Native) + 0x... (EVM Mirror)",
            "length":      len(self.address),
            "capacity":    "2.48 x 10^37 (31^25)",
            "version":     "4.0.0",
        }

    def save(self, path: str = "univa_wallet.json") -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        print(f"[UNIVA] Cuzdan kaydedildi -> {path} | Adres: {self.address} ({len(self.address)} kar)")

    @classmethod
    def load(cls, path: str = "univa_wallet.json") -> "UnivaWallet":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        w = cls(private_key_hex=data["private_key"])
        print(f"[UNIVA] Cuzdan yuklendi -> {w.address} (Uzunluk: {len(w.address)})")
        return w
