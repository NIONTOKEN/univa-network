"""UNIVA P5 - Offline Pay Protocol (QR + NFC + BLE + Reservation + Native Mobile Bridge) Test Suite."""
import json
import os
import subprocess
import sys
import tempfile
import time
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.blockchain import Blockchain
from core.offline_pay import (
    OfflinePayManager,
    OfflinePayError,
    canonical_voucher_meta_message,
    encode_voucher_v2,
    decode_voucher,
)
from core.wallet import UnivaWallet
import core.network as net

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_v2_voucher(bc, sender: UnivaWallet, recipient: str, amount: float, expires_at: int, res_id: str = "", transport: str = "qr", nonce_override=None):
    tx = bc.create_transaction(sender, recipient, amount, fee=0.001)
    if nonce_override is not None:
        from core.transaction import build_transaction
        tx = build_transaction(sender, recipient, amount, fee=0.001, nonce=nonce_override)
    meta_msg = canonical_voucher_meta_message(tx["tx_id"], res_id, expires_at)
    v_sig = sender.sign(meta_msg)
    token = encode_voucher_v2(tx, expires_at=expires_at, reservation_id=res_id, transport=transport, voucher_sig=v_sig)
    return tx, token


def test_1_voucher_v2_v1_signing_expiry_and_tamper_guards():
    bc = Blockchain(auto_load_path=None)
    bc.difficulty = 1
    alice, bob = UnivaWallet(), UnivaWallet()
    bc.mine_pending_transactions(alice.address)
    mgr = OfflinePayManager()

    now = int(time.time())
    tx, tok = _make_v2_voucher(bc, alice, bob.address, 5.0, expires_at=now + 3600, res_id="res_abc123", transport="nfc")
    parsed = mgr.validate_voucher(tok, now=now)
    assert parsed["version"] == 2
    assert parsed["tx"]["tx_id"] == tx["tx_id"]
    assert parsed["transport"] == "nfc"

    # Tampering expires_at must fail meta signature check (401)
    tampered = decode_voucher(tok)
    tampered["expires_at"] = now + 999999
    try:
        mgr.validate_voucher(tampered, now=now)
        assert False, "Tampered expires_at should have been rejected"
    except OfflinePayError as oe:
        assert oe.status_code == 401 and oe.code == "invalid_meta_sig"

    # Expired voucher rejected (410)
    _, expired_tok = _make_v2_voucher(bc, alice, bob.address, 5.0, expires_at=now - 10)
    try:
        mgr.validate_voucher(expired_tok, now=now)
        assert False, "Expired voucher should have been rejected"
    except OfflinePayError as oe:
        assert oe.status_code == 410 and oe.code == "voucher_expired"

    # 1-second voucher accepted & >1 hour (3600s) voucher rejected (400)
    _, one_sec_tok = _make_v2_voucher(bc, alice, bob.address, 1.0, expires_at=now + 1)
    assert mgr.validate_voucher(one_sec_tok, now=now)["version"] == 2
    _, too_long_tok = _make_v2_voucher(bc, alice, bob.address, 1.0, expires_at=now + 7200)
    try:
        mgr.validate_voucher(too_long_tok, now=now)
        assert False, "Voucher > 1 hour should have been rejected"
    except OfflinePayError as oe:
        assert oe.status_code == 400 and oe.code == "voucher_ttl_exceeded"

    # Backward-compatible V1 voucher validates cleanly
    import base64
    v1_tok = "UNIVA:OFF:V1:" + base64.b64encode(json.dumps(tx).encode()).decode()
    parsed_v1 = mgr.validate_voucher(v1_tok, now=now)
    assert parsed_v1["version"] == 1 and parsed_v1["tx"]["tx_id"] == tx["tx_id"]

    print("[PASS] 1. V2/V1 offline voucher encoding, ECDSA tx+meta verification, tamper & TTL expiry rejection")


def test_2_signed_reservation_lock_online_guard_and_release():
    orig_bc, orig_mgr = net.blockchain, net.offline_mgr
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc = Blockchain(auto_load_path=None)
        bc.difficulty = 1
        mgr = OfflinePayManager(state_path=os.path.join(td, "offline_state.json"))
        alice, bob = UnivaWallet(), UnivaWallet()
        bc.mine_pending_transactions(alice.address)  # +100 UNIVA
        net.blockchain, net.offline_mgr = bc, mgr
        client = TestClient(net.app)
        try:
            # private_key forbidden (400), forged signer rejected (403)
            assert client.post("/api/v1/offline/reserve", json={"address": alice.address, "private_key": alice.private_key, "amount": 10}).status_code == 400
            bad_sig = bob.sign(f"UNIVA_OFFLINE|reserve|{alice.address}|60|3600|0")
            assert client.post("/api/v1/offline/reserve", json={
                "address": alice.address, "amount": 60, "ttl_seconds": 3600, "nonce": 0,
                "public_key": bob.public_key, "signature": bad_sig,
            }).status_code == 403

            # Signed reservation: lock 60 UNIVA for 1h
            sig = alice.sign(f"UNIVA_OFFLINE|reserve|{alice.address}|60|3600|0")
            r_res = client.post("/api/v1/offline/reserve", json={
                "address": alice.address, "amount": 60, "ttl_seconds": 3600, "nonce": 0,
                "public_key": alice.public_key, "signature": sig,
            })
            assert r_res.status_code == 200, r_res.text
            res_id = r_res.json()["reservation"]["reservation_id"]
            assert r_res.json()["unreserved_spendable"] == 40.0

            # Online /tx attempting to spend 50 UNIVA (> 40 unreserved) MUST be blocked (400)
            tx_blocked = bc.create_transaction(alice, bob.address, 50.0, fee=0.001)
            r_blk = client.post("/tx", json={"tx": tx_blocked})
            assert r_blk.status_code == 400, r_blk.text

            # Online /tx spending 20 UNIVA (<= 40 unreserved) succeeds
            tx_ok = bc.create_transaction(alice, bob.address, 20.0, fee=0.001)
            r_ok = client.post("/tx", json={"tx": tx_ok})
            assert r_ok.status_code == 200, r_ok.text

            # Release reservation unlocks remaining 60 UNIVA
            rel_sig = alice.sign(f"UNIVA_OFFLINE|release|{alice.address}|{res_id}|1")
            r_rel = client.post("/api/v1/offline/release", json={
                "address": alice.address, "reservation_id": res_id, "nonce": 1,
                "public_key": alice.public_key, "signature": rel_sig,
            })
            assert r_rel.status_code == 200, r_rel.text
            assert r_rel.json()["released_amount"] == 60.0

            # Replay of release signature blocked (409)
            r_rep = client.post("/api/v1/offline/release", json={
                "address": alice.address, "reservation_id": res_id, "nonce": 1,
                "public_key": alice.public_key, "signature": rel_sig,
            })
            assert r_rep.status_code == 409
        finally:
            net.blockchain, net.offline_mgr = orig_bc, orig_mgr
    print("[PASS] 2. Signed offline reservation lock, online /tx double-spend guard & signed release/anti-replay")


def test_3_offline_double_spend_budget_and_replay_protection():
    orig_bc, orig_mgr = net.blockchain, net.offline_mgr
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc = Blockchain(auto_load_path=None)
        bc.difficulty = 1
        mgr = OfflinePayManager(state_path=os.path.join(td, "offline_state.json"))
        alice, bob, charlie = UnivaWallet(), UnivaWallet(), UnivaWallet()
        bc.mine_pending_transactions(alice.address)  # +100 UNIVA
        net.blockchain, net.offline_mgr = bc, mgr
        client = TestClient(net.app)
        try:
            # Lock 30 UNIVA budget
            sig = alice.sign(f"UNIVA_OFFLINE|reserve|{alice.address}|30|3600|0")
            r_res = client.post("/api/v1/offline/reserve", json={
                "address": alice.address, "amount": 30, "ttl_seconds": 3600, "nonce": 0,
                "public_key": alice.public_key, "signature": sig,
            })
            res_id = r_res.json()["reservation"]["reservation_id"]

            exp = int(time.time()) + 3600
            tx1, tok1 = _make_v2_voucher(bc, alice, bob.address, 20.0, expires_at=exp, res_id=res_id, transport="ble", nonce_override=0)
            tx2, tok2 = _make_v2_voucher(bc, alice, charlie.address, 15.0, expires_at=exp, res_id=res_id, transport="nfc", nonce_override=1)

            # Submit voucher 1 -> honest status "in_mempool", finalized=False
            r1 = client.post("/api/v1/offline/submit", json={"token": tok1, "transport": "ble"})
            assert r1.status_code == 200, r1.text
            b1 = r1.json()
            assert b1["status"] == "in_mempool" and b1["finalized"] is False

            # Replay voucher 1 -> 409 Conflict
            r1_rep = client.post("/api/v1/offline/submit", json={"token": tok1})
            assert r1_rep.status_code == 409, r1_rep.text

            # Submit voucher 2 (20.001 + 15.001 > 30.0 reserved budget) -> 409 double-spend blocked
            r2 = client.post("/api/v1/offline/submit", json={"token": tok2, "transport": "nfc"})
            assert r2.status_code == 409, r2.text
            assert tx2["tx_id"] not in {t.get("tx_id") for t in bc.pending_transactions}
        finally:
            net.blockchain, net.offline_mgr = orig_bc, orig_mgr
    print("[PASS] 3. Reservation budget blocks cumulative offline double-spend (409) & exact voucher replay (409)")


def test_4_honest_settlement_lifecycle_and_state_persistence():
    orig_bc, orig_mgr = net.blockchain, net.offline_mgr
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        state_path = os.path.join(td, "offline_state.json")
        bc = Blockchain(auto_load_path=None)
        bc.difficulty = 1
        mgr = OfflinePayManager(state_path=state_path)
        alice, bob = UnivaWallet(), UnivaWallet()
        bc.mine_pending_transactions(alice.address)
        net.blockchain, net.offline_mgr = bc, mgr
        client = TestClient(net.app)
        try:
            exp = int(time.time()) + 3600
            tx, tok = _make_v2_voucher(bc, alice, bob.address, 12.5, expires_at=exp, transport="qr")
            r_sub = client.post("/api/v1/offline/submit", json={"token": tok})
            assert r_sub.status_code == 200, r_sub.text

            # Before block mining: strictly NOT finalized
            st_pre = client.get(f"/api/v1/offline/status/{tx['tx_id']}").json()
            assert st_pre["status"] == "in_mempool"
            assert st_pre["finalized"] is False
            assert st_pre["block_index"] is None
            assert st_pre["confirmations"] == 0

            # Mine block -> NOW confirmed & finalized
            bc.mine_pending_transactions(bob.address)
            st_post = client.get(f"/api/v1/offline/status/{tx['tx_id']}").json()
            assert st_post["status"] == "confirmed"
            assert st_post["finalized"] is True
            assert st_post["block_index"] == 2
            assert st_post["confirmations"] >= 1

            # Reload from disk preserves anti-replay set
            reloaded = OfflinePayManager(state_path=state_path)
            assert tx["tx_id"] in reloaded.used_voucher_txids
        finally:
            net.blockchain, net.offline_mgr = orig_bc, orig_mgr
    print("[PASS] 4. Honest lifecycle (in_mempool/finalized=False -> confirmed/block_index=2) & disk persistence")


def test_5_mobile_bridge_ble_framing_and_pwa_js_validation():
    # 1. Verify mobile Capacitor config & package.json
    cap_cfg = json.load(open(os.path.join(ROOT_DIR, "mobile", "capacitor.config.json"), encoding="utf-8"))
    pkg_cfg = json.load(open(os.path.join(ROOT_DIR, "mobile", "package.json"), encoding="utf-8"))
    assert cap_cfg["webDir"] == "../pwa"
    assert cap_cfg["plugins"]["UnivaBLE"]["serviceUuid"] == "756e6976-6100-4000-8000-000000000001"
    assert "@capacitor/android" in pkg_cfg["devDependencies"] and "@capacitor/ios" in pkg_cfg["devDependencies"]

    # 2. Verify /offline-transport.js served by FastAPI
    client = TestClient(net.app)
    r_js = client.get("/offline-transport.js")
    assert r_js.status_code == 200 and "UnivaOfflineTransport" in r_js.text

    # 3. Node.js tests for BLE MTU chunk framing, out-of-order reassembly, CRC-8 corruption & native capability detection
    js_test = r"""
const assert = require('assert');
const T = require('./pwa/offline-transport.js');

const sampleVoucher = 'UNIVA:OFF:V2:' + 'A'.repeat(480);

// Legacy BLE 4.0 MTU=20 (16B payload/frame) & BLE 5.0 MTU=180
for (const mtu of [20, 180]) {
  const frames = T.encodeBleFrames(sampleVoucher, mtu);
  assert(frames.length > 1, 'Expected multiple BLE frames');
  const asm = new T.BleFrameAssembler();
  // Feed frames in reverse order (out-of-order resilience)
  let out = null;
  for (let i = frames.length - 1; i >= 0; i--) {
    out = asm.pushFrame(frames[i]);
  }
  assert.strictEqual(out, sampleVoucher, 'Reassembled BLE voucher mismatch for MTU=' + mtu);
}

// Single-bit corruption must be rejected by CRC-8
const badFrames = T.encodeBleFrames(sampleVoucher, 180);
badFrames[0][5] ^= 0x01;
const asmBad = new T.BleFrameAssembler();
let crcCaught = false;
try { asmBad.pushFrame(badFrames[0]); } catch (e) { crcCaught = e.message.includes('CRC-8'); }
assert(crcCaught, 'Corrupted BLE frame was not rejected by CRC-8');

// Native Android/iOS Capacitor plugin capability detection
global.window = {
  Capacitor: {
    isNativePlatform: () => true,
    Plugins: {
      UnivaNFC: { writeVoucher: async () => ({ok:true}), readVoucher: async () => ({token:sampleVoucher}) },
      UnivaBLE: { advertiseVoucher: async () => ({ok:true}), scanAndReceive: async () => ({token:sampleVoucher}), sendToPeripheral: async () => ({ok:true}) }
    }
  }
};
const nativeCaps = T.detectCapabilities();
assert.strictEqual(nativeCaps.runtime, 'native-mobile');
assert.strictEqual(nativeCaps.nfc.mode, 'native-android-ios');
assert.strictEqual(nativeCaps.ble.mode, 'native-android-ios');
assert.strictEqual(nativeCaps.ble.peripheral, true);
console.log('NODE_BLE_MOBILE_OK');
"""
    r = subprocess.run(["node", "-e", js_test], cwd=ROOT_DIR, capture_output=True, text=True)
    assert r.returncode == 0 and "NODE_BLE_MOBILE_OK" in r.stdout, f"Node BLE test failed: {r.stderr}"

    # 4. Syntax check offline-transport.js and pwa/index.html main inline script
    r_chk = subprocess.run(["node", "--check", "pwa/offline-transport.js"], cwd=ROOT_DIR, capture_output=True, text=True)
    assert r_chk.returncode == 0, r_chk.stderr

    import re
    html = open(os.path.join(ROOT_DIR, "pwa", "index.html"), encoding="utf-8").read()
    main_js = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tf:
        tf.write(main_js)
        tf_path = tf.name
    try:
        r_html = subprocess.run(["node", "--check", tf_path], capture_output=True, text=True)
        assert r_html.returncode == 0, r_html.stderr
    finally:
        os.unlink(tf_path)

    print("[PASS] 5. BLE MTU=20/180 framing, out-of-order reassembly, CRC-8 guard, Android/iOS Capacitor bridge & JS syntax")


def test_6_onchain_consensus_offline_escrow_nonce_isolation_expiry_and_reorg():
    from core.blockchain import INITIAL_DIFF
    from core.transaction import (
        build_offline_reserve_tx,
        build_offline_spend_tx,
        build_offline_release_tx,
    )

    orig_bc, orig_mgr = net.blockchain, net.offline_mgr
    net._RATE_BUCKETS.clear()
    with tempfile.TemporaryDirectory() as td:
        bc = Blockchain(auto_load_path=None)
        bc.difficulty = INITIAL_DIFF
        mgr = OfflinePayManager(state_path=os.path.join(td, "offline_consensus.json"))
        alice, bob, charlie, miner = UnivaWallet(), UnivaWallet(), UnivaWallet(), UnivaWallet()

        # Block 1: Alice mines 100.0 UNIVA
        b1 = bc.mine_pending_transactions(alice.address)
        assert b1 is not None and bc.get_balance(alice.address) == 100.0

        net.blockchain, net.offline_mgr = bc, mgr
        client = TestClient(net.app)
        try:
            now = int(time.time())
            exp = now + 3600

            # Block 2: On-chain offline_reserve (40 UNIVA + 0.001 fee)
            tx_res = build_offline_reserve_tx(alice, amount=40.0, expires_at=exp, fee=0.001, blockchain=bc)
            r_res = client.post("/tx", json={"tx": tx_res})
            assert r_res.status_code == 200, r_res.text
            res_id = tx_res["reservation_id"]
            b2 = bc.mine_pending_transactions(miner.address)
            assert b2 is not None
            assert abs(bc.get_balance(alice.address) - 59.999) < 1e-8
            assert bc._account_nonce(alice.address) == 1

            # Create an unbroadcast voucher #0 + real voucher #1 (15 UNIVA + 0.001 fee)
            tx_unbroadcast = build_offline_spend_tx(alice, res_id, bob.address, 5.0, voucher_nonce=0, expires_at=exp, fee=0.001)
            tx_spend_bob = build_offline_spend_tx(alice, res_id, bob.address, 15.0, voucher_nonce=1, expires_at=exp, fee=0.001)

            # Submit voucher #1 via /api/v1/offline/submit
            r_sp = client.post("/api/v1/offline/submit", json={"voucher": {"version": 2, "tx": tx_spend_bob, "expires_at": exp, "reservation_id": res_id, "transport": "ble"}})
            assert r_sp.status_code == 200, r_sp.text
            assert r_sp.json()["finalized"] is False and r_sp.json()["status"] == "in_mempool"

            # Prove normal transfer works without being blocked by unbroadcast voucher #0 or voucher #1!
            tx_norm = bc.create_transaction(alice, charlie.address, 10.0, fee=0.001)
            assert tx_norm["nonce"] == 1
            assert client.post("/tx", json={"tx": tx_norm}).status_code == 200

            # Consensus double-spend rejection: over-budget (30 > remaining 24.999) & duplicate voucher_nonce=1
            tx_over = build_offline_spend_tx(alice, res_id, charlie.address, 30.0, voucher_nonce=2, expires_at=exp, fee=0.001)
            assert bc.add_transaction(tx_over) is False
            tx_dup_vn = build_offline_spend_tx(alice, res_id, charlie.address, 1.0, voucher_nonce=1, expires_at=exp, fee=0.001)
            assert bc.add_transaction(tx_dup_vn) is False

            # Block 3: Mine offline_spend + normal transfer
            b3 = bc.mine_pending_transactions(miner.address)
            assert b3 is not None
            assert abs(bc.get_balance(bob.address) - 15.0) < 1e-8
            assert abs(bc.get_balance(charlie.address) - 10.0) < 1e-8
            assert abs(bc.get_balance(alice.address) - 49.998) < 1e-8  # 59.999 - 10.001

            # Block 4: Early on-chain offline_release refunds unspent 24.999 UNIVA back to Alice
            tx_rel = build_offline_release_tx(alice, res_id, fee=0.001, blockchain=bc)
            assert tx_rel["nonce"] == 2
            assert client.post("/tx", json={"tx": tx_rel}).status_code == 200
            b4 = bc.mine_pending_transactions(miner.address)
            assert b4 is not None
            # 49.998 + 24.999 - 0.001 = 74.996
            assert abs(bc.get_balance(alice.address) - 74.996) < 1e-8

            # After release, previously unbroadcast voucher #0 is rejected by consensus!
            assert bc.add_transaction(tx_unbroadcast) is False

            # Block 5: Short-TTL reservation expires automatically without needing release tx
            short_exp = max(int(b4.timestamp), int(time.time())) + 10
            tx_res2 = build_offline_reserve_tx(alice, amount=20.0, expires_at=short_exp, fee=0.001, blockchain=bc)
            assert bc.add_transaction(tx_res2) is True
            b5 = bc.mine_pending_transactions(miner.address)
            assert b5 is not None
            # At timestamp >= short_exp, unspent 20.0 automatically returns to Alice's spendable balance
            bal_after_expiry = bc.get_balance(alice.address, at_timestamp=short_exp + 5)
            assert abs(bal_after_expiry - 74.995) < 1e-8
            # And an offline_spend attempted after expiry is rejected by consensus
            tx_late = build_offline_spend_tx(alice, tx_res2["reservation_id"], bob.address, 5.0, voucher_nonce=0, expires_at=short_exp + 100, fee=0.001)
            assert bc.verify_transaction(tx_late, block_timestamp=short_exp + 5) is False

            # Full chain validation & independent peer node reorg verification
            assert bc.is_chain_valid() is True
            peer_bc = Blockchain(auto_load_path=None)
            assert peer_bc.replace_chain(bc.chain, save_path=os.path.join(td, "peer_chain.json")) is True
            assert peer_bc.height == bc.height
            assert abs(peer_bc.get_balance(bob.address) - 15.0) < 1e-8
            assert abs(peer_bc.get_balance(alice.address, at_timestamp=short_exp + 5) - 74.995) < 1e-8
        finally:
            net.blockchain, net.offline_mgr = orig_bc, orig_mgr
    print("[PASS] 6. On-chain consensus offline_reserve/spend/release, nonce isolation, auto-expiry & peer reorg verified")


if __name__ == "__main__":
    test_1_voucher_v2_v1_signing_expiry_and_tamper_guards()
    test_2_signed_reservation_lock_online_guard_and_release()
    test_3_offline_double_spend_budget_and_replay_protection()
    test_4_honest_settlement_lifecycle_and_state_persistence()
    test_5_mobile_bridge_ble_framing_and_pwa_js_validation()
    test_6_onchain_consensus_offline_escrow_nonce_isolation_expiry_and_reorg()
    print("\nALL P5 OFFLINE PAY & CONSENSUS ESCROW TESTS PASSED (6/6)!")
