"""UNIVA P0 Critical Security Audit & Regression Test Suite."""
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from core.blockchain import Blockchain
from core.wallet import UnivaWallet, decrypt_wallet_dict, encrypt_wallet_dict
from core import p2p
import core.network as net


def test_1_chain_and_balance_preserved():
    bc = Blockchain(auto_load_path=str(ROOT / "univa_chain.json"))
    assert bc.height >= 252, f"Unexpected height {bc.height}"
    assert bc.is_chain_valid() is True, "Existing univa_chain.json failed validation"
    master_bal = bc.get_balance("univaf63aua23vxdvcmvkunx66yzh2")
    assert master_bal > 0, f"Master balance should be > 0, got {master_bal}"
    print(f"[PASS] 1. Chain valid (height={bc.height}), master balance preserved ({master_bal} UNIVA)")


def test_2_wallet_encryption_roundtrip():
    w = UnivaWallet.create_new()
    with tempfile.TemporaryDirectory() as td:
        enc_path = os.path.join(td, "wallet_enc.json")
        w.save_encrypted(enc_path, "StrongPass#2026")
        raw = json.loads(Path(enc_path).read_text(encoding="utf-8"))
        assert "private_key" not in json.dumps(raw)
        assert raw["cipher"] == "SHA256-CTR-HMAC"

        # Wrong passphrase must fail
        try:
            UnivaWallet.load_encrypted(enc_path, "WrongPass")
            raise AssertionError("Wrong passphrase should fail decryption")
        except ValueError:
            pass

        # Tampered ciphertext must fail HMAC
        tampered = dict(raw)
        tampered["ciphertext"] = ("00" if not raw["ciphertext"].startswith("00") else "ff") + raw["ciphertext"][2:]
        try:
            decrypt_wallet_dict(tampered, "StrongPass#2026")
            raise AssertionError("Tampered ciphertext must fail HMAC verification")
        except ValueError:
            pass

        loaded = UnivaWallet.load_encrypted(enc_path, "StrongPass#2026")
        assert loaded.address == w.address
        assert loaded.private_key == w.private_key
    print("[PASS] 2. Wallet encryption/decryption roundtrip, wrong PIN, and HMAC tamper detection")


def test_3_no_private_key_to_server_and_client_signed_tx():
    net._RATE_BUCKETS.clear()
    net._RATE_LIMIT_LOG.clear()
    client = TestClient(net.app)

    # Create funded sender on an isolated in-memory test blockchain inside net
    orig_bc = net.blockchain
    try:
        test_bc = Blockchain(auto_load_path=None)
        sender = UnivaWallet.create_new()
        recv = UnivaWallet.create_new()
        test_bc.mine_pending_transactions(sender.address)
        assert test_bc.get_balance(sender.address) == 100.0
        net.blockchain = test_bc

        # (a) Reject private_key in POST /tx
        r_tx_bad = client.post("/tx", json={
            "from": sender.address,
            "to": recv.address,
            "amount": 1.0,
            "private_key": sender.private_key,
        })
        assert r_tx_bad.status_code == 400, r_tx_bad.text

        # (b) Reject private_key in POST /api/v1/dex/swap
        r_dex_bad = client.post("/api/v1/dex/swap", json={
            "user": sender.address,
            "asset_in": "UNIVA",
            "asset_out": "uUSD",
            "amount_in": 1.0,
            "private_key": sender.private_key,
        })
        assert r_dex_bad.status_code == 400, r_dex_bad.text

        # (c) Reject remote /api/v1/wallet/create when proxied (non-loopback)
        r_create = client.post("/api/v1/wallet/create", json={}, headers={"x-forwarded-for": "8.8.8.8"})
        assert r_create.status_code == 403, r_create.text

        # (d) Accept strictly client-signed transaction (zero private_key over wire)
        signed_tx = test_bc.create_transaction(sender, recv.address, 5.0, fee=0.001)
        assert "private_key" not in signed_tx
        r_tx_ok = client.post("/tx", json={"tx": signed_tx})
        assert r_tx_ok.status_code == 200, r_tx_ok.text
        assert r_tx_ok.json().get("accepted") is True
    finally:
        net.blockchain = orig_bc
    print("[PASS] 3. Server rejects private_key in /tx & /dex/swap (400), remote /wallet/create (403), accepts client-signed TX")


def test_4_master_auth_hardening():
    net._RATE_BUCKETS.clear()
    net._RATE_LIMIT_LOG.clear()
    net._MASTER_FAIL_BUCKETS.clear()
    client = TestClient(net.app)

    orig_master_file = net.MASTER_AUTH_FILE
    with tempfile.TemporaryDirectory() as td:
        tmp_auth = os.path.join(td, "master_auth.json")
        net.MASTER_AUTH_FILE = tmp_auth
        try:
            # 1) Remote First-PIN takeover without UNIVA_MASTER_INIT_TOKEN must be blocked (403)
            r_remote = client.post(
                "/api/v1/wallet/master-auth",
                json={"username": "kaya", "pin": "123456"},
                headers={"x-forwarded-for": "203.0.113.55"},
            )
            assert r_remote.status_code == 403, r_remote.text
            assert not os.path.exists(tmp_auth)

            # 2) Allowed via valid UNIVA_MASTER_INIT_TOKEN
            os.environ["UNIVA_MASTER_INIT_TOKEN"] = "init-secret-99"
            try:
                r_init = client.post(
                    "/api/v1/wallet/master-auth",
                    json={"username": "kaya", "pin": "StrongPin99"},
                    headers={"x-forwarded-for": "203.0.113.55", "x-univa-init-token": "init-secret-99"},
                )
            finally:
                os.environ.pop("UNIVA_MASTER_INIT_TOKEN", None)

            assert r_init.status_code == 200, r_init.text
            body = r_init.json()
            assert "private_key" not in body, "Plaintext private_key MUST NOT be returned in master-auth response!"
            assert "encrypted_private_key" in body and "session_token" in body
            dec = decrypt_wallet_dict(body["encrypted_private_key"], "StrongPin99")
            assert len(dec["private_key"]) == 64

            # 3) Brute-force lockout after 5 bad PINs -> 429
            for _ in range(5):
                r_bad = client.post(
                    "/api/v1/wallet/master-auth",
                    json={"username": "kaya", "pin": "wrongpin"},
                    headers={"x-forwarded-for": "203.0.113.77"},
                )
                assert r_bad.status_code == 401
            r_locked = client.post(
                "/api/v1/wallet/master-auth",
                json={"username": "kaya", "pin": "StrongPin99"},
                headers={"x-forwarded-for": "203.0.113.77"},
            )
            assert r_locked.status_code == 429, r_locked.text
        finally:
            net.MASTER_AUTH_FILE = orig_master_file
    print("[PASS] 4. Master auth blocks remote First-PIN takeover (403), encrypts key in response, enforces 429 brute-force shield")


def test_5_get_faucet_disabled():
    client = TestClient(net.app)
    r = client.get("/api/v1/faucet/univa0000000000univa")
    assert r.status_code == 405, f"Expected 405 Method Not Allowed for GET faucet, got {r.status_code}"
    print("[PASS] 5. GET /api/v1/faucet blocked with 405 Method Not Allowed")


def test_6_p2p_auth_and_replay_protection():
    # Signed message passes once
    raw = p2p.make_msg("ping", {"height": 123})
    parsed = p2p.parse_msg(raw)
    assert parsed is not None and parsed["type"] == "ping" and parsed["payload"]["height"] == 123

    # Replaying exact same message must fail
    assert p2p.parse_msg(raw) is None, "Replayed P2P message must be rejected"

    # Tampered payload must fail signature check
    tampered_obj = json.loads(raw)
    tampered_obj["nonce"] = "freshnonce123456"
    tampered_obj["payload"] = {"height": 999999}
    assert p2p.parse_msg(json.dumps(tampered_obj)) is None, "Tampered P2P message must be rejected"

    # Unsigned message must be rejected
    unsigned = json.dumps({"type": "ping", "version": p2p.P2P_VERSION, "time": time.time(), "payload": {}})
    assert p2p.parse_msg(unsigned) is None, "Unsigned P2P message must be rejected"

    # Expired timestamp (> 120s) must be rejected
    stale = json.loads(p2p.make_msg("ping", {}))
    stale["time"] = time.time() - 300
    assert p2p.verify_p2p_msg(stale) is False, "Stale P2P message must be rejected"
    print("[PASS] 6. P2P ECDSA authentication, tamper rejection, stale timestamp check, and anti-replay verified")


def test_7_pwa_js_syntax_and_no_privkey_leaks():
    html = (ROOT / "pwa" / "index.html").read_text(encoding="utf-8")
    assert "priv.substring(0, 40)" not in html, "Legacy EVM privkey leak still present in generateKeypair!"
    assert "private_key: walletPrivKey" not in html, "executeSendTransaction still sends private_key to server!"
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(scripts[-1])
        tmp_js = f.name
    try:
        res = subprocess.run(["node", "-c", tmp_js], capture_output=True, text=True)
        assert res.returncode == 0, f"node -c failed: {res.stderr}"
    finally:
        os.unlink(tmp_js)
    print("[PASS] 7. pwa/index.html JS syntax clean (node -c exit 0) & no EVM privkey slice / no /tx private_key transmission")


if __name__ == "__main__":
    test_1_chain_and_balance_preserved()
    test_2_wallet_encryption_roundtrip()
    test_3_no_private_key_to_server_and_client_signed_tx()
    test_4_master_auth_hardening()
    test_5_get_faucet_disabled()
    test_6_p2p_auth_and_replay_protection()
    test_7_pwa_js_syntax_and_no_privkey_leaks()
    print("\nALL_P0_SECURITY_TESTS_PASSED (7/7)")
