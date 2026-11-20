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
import hmac
import json
import secrets

_WALLET_KDF_ITERATIONS = 200_000


def _derive_wallet_keys(passphrase: str, salt: bytes, iterations: int = _WALLET_KDF_ITERATIONS):
    if not isinstance(passphrase, str) or len(passphrase) < 4:
        raise ValueError("Passphrase must be at least 4 characters")
    master = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, dklen=64)
    return master[:32], master[32:]


def _xor_keystream(data: bytes, enc_key: bytes, nonce: bytes) -> bytes:
    out = bytearray(len(data))
    counter = 0
    pos = 0
    while pos < len(data):
        block = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
        take = min(32, len(data) - pos)
        for i in range(take):
            out[pos + i] = data[pos + i] ^ block[i]
        pos += take
        counter += 1
    return bytes(out)


def encrypt_wallet_dict(data: dict, passphrase: str) -> dict:
    """Encrypt a wallet payload using PBKDF2-HMAC-SHA256 (200k) + CTR keystream + HMAC-SHA256."""
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _derive_wallet_keys(passphrase, salt)
    plaintext = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ciphertext = _xor_keystream(plaintext, enc_key, nonce)
    mac = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).hexdigest()
    return {
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": _WALLET_KDF_ITERATIONS,
        "cipher": "SHA256-CTR-HMAC",
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex(),
        "hmac": mac,
    }


def decrypt_wallet_dict(enc_data: dict, passphrase: str) -> dict:
    """Authenticate and decrypt a wallet payload created by encrypt_wallet_dict."""
    if not isinstance(enc_data, dict) or enc_data.get("cipher") != "SHA256-CTR-HMAC":
        raise ValueError("Unsupported encrypted wallet format")
    salt = bytes.fromhex(enc_data["salt"])
    nonce = bytes.fromhex(enc_data["nonce"])
    ciphertext = bytes.fromhex(enc_data["ciphertext"])
    iterations = int(enc_data.get("iterations", _WALLET_KDF_ITERATIONS))
    if iterations < 100_000:
        raise ValueError("Insecure KDF iteration count")
    enc_key, mac_key = _derive_wallet_keys(passphrase, salt, iterations)
    expected_mac = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_mac, str(enc_data.get("hmac", ""))):
        raise ValueError("Invalid passphrase or corrupted encrypted wallet")
    plaintext = _xor_keystream(ciphertext, enc_key, nonce)
    return json.loads(plaintext.decode("utf-8"))

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
TESTNET_PREFIX = "tuniv"
CHARSET = "23456789abcdefghjkmnpqrstuvwxyz"   # 31 karakter
SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def normalize_address(address: str) -> str:
    """Normalize EVM 0x addresses to lowercase while preserving Base31 L1 addresses."""
    if not isinstance(address, str):
        return ""
    s = address.strip()
    if (s.startswith("0x") or s.startswith("0X")) and len(s) == 42:
        return "0x" + s[2:].lower()
    return s


def to_checksum_evm_address(address: str) -> str:
    """Return mixed-case checksum formatting for a 42-char 0x EVM address."""
    norm = normalize_address(address)
    if not (norm.startswith("0x") and len(norm) == 42):
        return norm
    hex_body = norm[2:]
    digest = hashlib.sha3_256(hex_body.encode("ascii")).hexdigest()
    return "0x" + "".join(
        c.upper() if int(digest[i], 16) >= 8 and c in "abcdef" else c
        for i, c in enumerate(hex_body)
    )


def derive_sha256_pubkey_address(public_key_hex: str) -> str:
    """Backward-compatible P0 Base31 L1 address derived from SHA256(pubkey)."""
    pub_bytes = bytes.fromhex(public_key_hex)
    digest_hex = hashlib.sha256(pub_bytes).hexdigest()
    chars = []
    for i in range(25):
        pos = (i * 2) % 58
        sub = int(digest_hex[pos:pos + 2], 16)
        chars.append(CHARSET[sub % 31])
    return f"{PREFIX}{''.join(chars)}"


def get_valid_sender_addresses(public_key_hex: str) -> set:
    """All normalized valid L1 + EVM mirror addresses belonging to public_key_hex."""
    pub = (public_key_hex or "").strip().lower()
    if not pub:
        return set()
    origins = {
        derive_univa_address(pub),
        derive_testnet_address(pub),
        derive_legacy_20char_address(pub),
        derive_sha256_pubkey_address(pub),
        normalize_address(derive_evm_address(pub)),
    }
    for extra in REGISTERED_PWA_ORIGINS.get(pub, set()):
        origins.add(normalize_address(extra))
    return origins


def derive_univa_address(public_key_hex: str) -> str:
    """
    Public key'den standart UNIVA Mainnet L1 adresi üretir.
    Format: 'univa' + 25 karakterlik Base31 kriptografik özet (Toplam 30 karakter).
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


def derive_testnet_address(public_key_hex: str) -> str:
    """
    Public key'den 30 karakterlik izole UNIVA Testnet adresi üretir ('tuniv' + 25 Base31).
    Mainnet adresleriyle asla çakışmaz.
    """
    pub_bytes = bytes.fromhex(public_key_hex)
    sha256    = hashlib.sha256(pub_bytes).digest()
    ripemd160 = hashlib.new("ripemd160", sha256).digest()
    num = int.from_bytes(ripemd160[:15], "big")
    chars = []
    for _ in range(25):
        chars.append(CHARSET[num % 31])
        num //= 31
    return f"{TESTNET_PREFIX}{''.join(chars)}"


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


def validate_address(address: str, network: str = None) -> bool:
    """
    Geçerli UNIVA adresi doğrulaması:
    - Mainnet L1 Formatı: 'univa' + Base31 (30 karakter; eski 20-karakter uyumlu)
    - Testnet L1 Formatı: 'tuniv' + Base31 (30 karakter; genesis 'tuniv0000000000tuniv')
    - EVM Formatı: 0x... veya 0X... (42 karakter hex)
    `network='mainnet'` verilirse Testnet 'tuniv...' adresleri reddedilir;
    `network='testnet'` verilirse Mainnet 'univa...' adresleri reddedilir.
    """
    if not isinstance(address, str) or not address:
        return False
    # EVM adresi doğrulaması (büyük/küçük harf duyarsız)
    if (address.startswith("0x") or address.startswith("0X")) and len(address) == 42:
        return all(c in "0123456789abcdefABCDEF" for c in address[2:])

    net_mode = (network or "").strip().lower()
    if address.startswith(PREFIX):
        if net_mode == "testnet":
            return False
        if address == "univa0000000000univa":
            return True
        body = address[len(PREFIX):]
        if len(body) < 10 or len(body) > 32:
            return False
        if address.endswith("univa") and len(address) == 20:
            return True
        return all(c in CHARSET for c in body)

    if address.startswith(TESTNET_PREFIX):
        if net_mode == "mainnet":
            return False
        if address == "tuniv0000000000tuniv":
            return True
        body = address[len(TESTNET_PREFIX):]
        if len(body) < 10 or len(body) > 32:
            return False
        return all(c in CHARSET for c in body)

    return False


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
            origins = REGISTERED_PWA_ORIGINS.setdefault(self.public_key, set())
            origins.update({
                derive_sha256_pubkey_address(self.public_key),
                derive_pwa_address(self.private_key),
                derive_pwa_evm_address(self.private_key),
            })
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

    @property
    def testnet_address(self) -> str:
        return derive_testnet_address(self.public_key)

    @staticmethod
    def _normalize_low_s(raw_sig: bytes) -> str:
        r = int.from_bytes(raw_sig[:32], "big")
        s = int.from_bytes(raw_sig[32:], "big")
        if s > SECP256K1_ORDER // 2:
            s = SECP256K1_ORDER - s
        return r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex()

    def sign(self, message: str) -> str:
        msg_bytes = hashlib.sha256(message.encode()).digest()
        if ECDSA_AVAILABLE:
            raw = self._sk.sign_deterministic(msg_bytes)
            return self._normalize_low_s(raw)
        der = self._crypto_sk.sign(msg_bytes, ec.ECDSA(hashes.SHA1()))
        r, s = utils.decode_dss_signature(der)
        return self._normalize_low_s(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    @staticmethod
    def verify_signature(public_key_hex: str, message: str, signature_hex: str) -> bool:
        try:
            sig = bytes.fromhex(signature_hex)
            if len(sig) != 64:
                return False
            r = int.from_bytes(sig[:32], "big")
            s = int.from_bytes(sig[32:], "big")
            if not (0 < r < SECP256K1_ORDER and 0 < s < SECP256K1_ORDER):
                return False
            msg_b = hashlib.sha256(message.encode()).digest()
            if ECDSA_AVAILABLE:
                vk = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=SECP256k1)
                try:
                    return vk.verify(sig, msg_b)
                except Exception:
                    return vk.verify_digest(sig, msg_b)
            if CRYPTOGRAPHY_FALLBACK:
                pub = bytes.fromhex(public_key_hex)
                if len(pub) != 64:
                    return False
                vk = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), b"\x04" + pub)
                der = utils.encode_dss_signature(r, s)
                try:
                    vk.verify(der, msg_b, ec.ECDSA(hashes.SHA1()))
                    return True
                except Exception:
                    vk.verify(der, msg_b, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
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
        if isinstance(data, dict) and data.get("cipher") == "SHA256-CTR-HMAC":
            raise ValueError("Encrypted wallet requires load_encrypted(path, passphrase)")
        w = cls(private_key_hex=data["private_key"])
        print(f"[UNIVA] Cuzdan yuklendi -> {w.address} (Uzunluk: {len(w.address)})")
        return w

    def save_encrypted(self, path: str, passphrase: str) -> None:
        enc_payload = encrypt_wallet_dict(self.to_dict(), passphrase)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(enc_payload, f, indent=2)

    @classmethod
    def load_encrypted(cls, path: str, passphrase: str) -> "UnivaWallet":
        with open(path, "r", encoding="utf-8") as f:
            enc_data = json.load(f)
        data = decrypt_wallet_dict(enc_data, passphrase)
        return cls(private_key_hex=data["private_key"])
