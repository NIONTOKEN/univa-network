"""UNIVA P2 Wallet Standardization, Python <-> PWA Derivation Parity & Legacy Compatibility Test Suite."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecdsa import SigningKey, SECP256k1
from ecdsa.util import sigencode_string
import hashlib

from core.blockchain import Blockchain
from core.transaction import build_transaction, verify_transaction
from core.wallet import (
    REGISTERED_PWA_ORIGINS,
    SECP256K1_ORDER,
    UnivaWallet,
    derive_evm_address,
    derive_legacy_20char_address,
    derive_sha256_pubkey_address,
    derive_univa_address,
    get_valid_sender_addresses,
    normalize_address,
    to_checksum_evm_address,
)


def _extract_js_crypto_snippet() -> str:
    html = (ROOT / "pwa" / "index.html").read_text(encoding="utf-8")
    # Extract CHARSET + ripemd160 + generateKeypair + secp256k1 + canonicalTxMessageJS cleanly
    m_charset = re.search(r"const CHARSET = '[^']+';", html)
    start_gen = html.index("    function ripemd160(bytes) {")
    end_gen = html.index("    function initWalletSecurity()")
    start_secp = html.index("    // ─── PURE-JS SECP256K1")
    end_secp = html.index("    async function ensurePubkeyBound()")
    return "\n".join([
        m_charset.group(0),
        html[start_gen:end_gen],
        html[start_secp:end_secp],
    ])


def test_1_chain_and_all_balances_preserved():
    bc = Blockchain(auto_load_path=str(ROOT / "univa_chain.json"))
    assert bc.is_chain_valid() is True
    assert bc.height >= 345
    master_bal = bc.get_balance("univaf63aua23vxdvcmvkunx66yzh2")
    evm1_bal = bc.get_balance("0x915ee9e3ef45a87a20b6a9aa450ac4d6e7552be3")
    evm2_mixed = bc.get_balance("0xC6c41426Cb0d4EcffF7e0c515F0eE2e0626f6D9d")
    evm2_lower = bc.get_balance("0xc6c41426cb0d4ecfff7e0c515f0ee2e0626f6d9d")
    assert master_bal > 30000.0
    assert evm1_bal == 4.0
    assert evm2_mixed == 1.0 and evm2_mixed == evm2_lower
    print(f"[PASS] 1. Chain valid (height={bc.height}), L1 & EVM balances preserved ({master_bal}, {evm1_bal}, {evm2_mixed})")


def test_2_python_and_pwa_js_exact_address_parity():
    snippet = _extract_js_crypto_snippet()
    w1 = UnivaWallet.create_new()
    w2 = UnivaWallet.create_new()
    master = UnivaWallet.load(str(ROOT / "univa_wallet.json"))
    privs = [w1.private_key, w2.private_key, master.private_key]

    js_runner = snippet + f"""
(async () => {{
  const privs = {json.dumps(privs)};
  const out = [];
  for (const p of privs) {{
    const kp = await generateKeypair(p);
    out.push({{ address: kp.address, evm_address: kp.evm_address, public_key: kp.public_key }});
  }}
  console.log(JSON.stringify(out));
}})().catch(e => {{ console.error(e); process.exit(1); }});
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js_runner)
        tmp_js = f.name
    try:
        res = subprocess.run(["node", tmp_js], capture_output=True, text=True)
        assert res.returncode == 0, f"Node parity run failed: {res.stderr}"
        js_kps = json.loads(res.stdout.strip())
    finally:
        os.unlink(tmp_js)

    for py_w, js_kp in zip([w1, w2, master], js_kps):
        assert js_kp["public_key"] == py_w.public_key, "Public key mismatch!"
        assert js_kp["address"] == py_w.address, f"L1 address mismatch: JS={js_kp['address']} vs PY={py_w.address}"
        assert js_kp["evm_address"] == py_w.evm_address, f"EVM address mismatch: JS={js_kp['evm_address']} vs PY={py_w.evm_address}"
        assert len(js_kp["address"]) == 30 and js_kp["address"].startswith("univa")
    print("[PASS] 2. Exact byte-for-byte Python <-> PWA JS L1 (RIPEMD160 Base31) & EVM address parity verified")


def test_3_deterministic_low_s_and_cross_signature_verification():
    w = UnivaWallet.create_new()
    msg = "UNIVA_P2_CROSS_VERIFY_PAYLOAD"
    sig1 = w.sign(msg)
    sig2 = w.sign(msg)
    assert sig1 == sig2, "RFC 6979 deterministic signature must repeat identically"
    s_int = int(sig1[64:], 16)
    assert 0 < s_int <= SECP256K1_ORDER // 2, "Signature s must satisfy Low-S bound!"

    # Also test direct SHA-256 signature verification compatibility
    d256 = hashlib.sha256(msg.encode()).digest()
    sk = SigningKey.from_string(bytes.fromhex(w.private_key), curve=SECP256k1)
    direct_sig = sk.sign_digest_deterministic(d256, hashfunc=hashlib.sha256, sigencode=sigencode_string).hex()
    assert UnivaWallet.verify_signature(w.public_key, msg, sig1) is True
    assert UnivaWallet.verify_signature(w.public_key, msg, direct_sig) is True

    # Out-of-bounds (r=0, s=0, r>=N) must be rejected
    assert UnivaWallet.verify_signature(w.public_key, msg, "00" * 64) is False

    # Cross-verify Python sig + direct SHA-256 sig inside PWA JS verifySecp256k1Offline, and JS sig inside Python
    snippet = _extract_js_crypto_snippet()
    js_runner = snippet + f"""
(async () => {{
  const okPy = await verifySecp256k1Offline({json.dumps(w.public_key)}, {json.dumps(msg)}, {json.dumps(sig1)});
  const okDirect = await verifySecp256k1Offline({json.dumps(w.public_key)}, {json.dumps(msg)}, {json.dumps(direct_sig)});
  const jsSigned = await signSecp256k1Offline({json.dumps(w.private_key)}, {json.dumps(msg)});
  console.log(JSON.stringify({{ okPy, okDirect, jsSig: jsSigned.signature }}));
}})().catch(e => {{ console.error(e); process.exit(1); }});
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js_runner)
        tmp_js = f.name
    try:
        res = subprocess.run(["node", tmp_js], capture_output=True, text=True)
        assert res.returncode == 0, f"Node cross-verify failed: {res.stderr}"
        out = json.loads(res.stdout.strip())
    finally:
        os.unlink(tmp_js)

    assert out["okPy"] is True and out["okDirect"] is True
    assert UnivaWallet.verify_signature(w.public_key, msg, out["jsSig"]) is True
    print("[PASS] 3. Deterministic Low-S ECDSA & Python <-> PWA JS bidirectional signature cross-verification passed")


def test_4_evm_case_insensitive_balance_nonce_and_spending():
    bc = Blockchain(auto_load_path=None)
    sender = UnivaWallet.create_new()
    recv = UnivaWallet.create_new()

    mixed_evm = to_checksum_evm_address(sender.evm_address)
    lower_evm = normalize_address(sender.evm_address)
    assert mixed_evm.lower() == lower_evm

    # Mine block reward to checksummed mixed-case EVM address
    blk = bc.mine_pending_transactions(mixed_evm)
    assert blk is not None
    assert bc.get_balance(mixed_evm) == 100.0
    assert bc.get_balance(lower_evm) == 100.0

    # Spend from lowercase EVM mirror using sender's keypair!
    tx = build_transaction(sender, recv.address, 15.0, fee=0.001, blockchain=bc, from_address=lower_evm)
    assert verify_transaction(tx) is True
    assert bc.add_transaction(tx) is True
    blk2 = bc.mine_pending_transactions(recv.address)
    assert blk2 is not None and bc.is_chain_valid() is True
    assert bc.get_balance(mixed_evm) == round(100.0 - 15.0 - 0.001, 8)
    print("[PASS] 4. Case-insensitive EVM 0x address balance, nonce, checksum, and spend parity verified")


def test_5_legacy_20char_sha256_and_bound_pwa_compatibility():
    bc = Blockchain(auto_load_path=None)
    w = UnivaWallet.create_new()
    recv = UnivaWallet.create_new()

    legacy20 = derive_legacy_20char_address(w.public_key)
    sha256_l1 = derive_sha256_pubkey_address(w.public_key)
    origins = get_valid_sender_addresses(w.public_key)
    assert legacy20 in origins and sha256_l1 in origins and w.address in origins

    # Spend cleanly from both legacy 20-char and P0 SHA-256 derived L1 addresses
    bc.mine_pending_transactions(legacy20)
    tx_legacy = build_transaction(w, recv.address, 5.0, fee=0.001, blockchain=bc, from_address=legacy20)
    assert bc.add_transaction(tx_legacy) is True

    bc.mine_pending_transactions(sha256_l1)
    tx_sha = build_transaction(w, recv.address, 5.0, fee=0.001, blockchain=bc, from_address=sha256_l1)
    assert bc.add_transaction(tx_sha) is True

    blk = bc.mine_pending_transactions(recv.address)
    assert blk is not None and bc.is_chain_valid() is True
    print("[PASS] 5. Legacy 20-char univa...univa, P0 SHA-256 L1, and bound PWA addresses 100% compatible")


if __name__ == "__main__":
    test_1_chain_and_all_balances_preserved()
    test_2_python_and_pwa_js_exact_address_parity()
    test_3_deterministic_low_s_and_cross_signature_verification()
    test_4_evm_case_insensitive_balance_nonce_and_spending()
    test_5_legacy_20char_sha256_and_bound_pwa_compatibility()
    print("\nALL_P2_WALLET_TESTS_PASSED (5/5)")
