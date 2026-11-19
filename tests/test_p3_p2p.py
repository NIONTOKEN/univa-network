"""UNIVA P3 P2P Security, Sybil/Eclipse Defense, Paginated Sync & Fork Reorg Test Suite."""
import asyncio
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.blockchain import Blockchain
from core.wallet import UnivaWallet
from core import p2p


class MockWebSocket:
    def __init__(self, remote_ip="198.51.100.10", remote_port=5051, incoming=None):
        self.remote_address = (remote_ip, remote_port)
        self.sent = []
        self.closed = False
        self.close_code = None
        self.close_reason = None
        self._incoming = list(incoming or [])

    async def send(self, msg):
        self.sent.append(msg)

    async def close(self, code=1000, reason=""):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed or not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


def _reset_p2p_state(bc=None):
    p2p._connected_peers.clear()
    p2p._inbound_peers.clear()
    p2p._outbound_peers.clear()
    p2p._peer_pubkeys.clear()
    p2p._peer_scores.clear()
    p2p._banned_ips.clear()
    p2p._peer_msg_buckets.clear()
    p2p._blockchain_ref = bc


def test_1_handshake_and_genesis_mismatch_ban():
    bc = Blockchain(auto_load_path=None)
    _reset_p2p_state(bc)
    try:
        ws = MockWebSocket("203.0.113.10", 5051)
        peer_id = "203.0.113.10:5051"

        # Mismatched genesis hash -> immediate ban & close
        asyncio.run(p2p.handle_handshake(ws, peer_id, {
            "network": "UNIVA Network",
            "genesis_hash": "f" * 64,
            "height": 100,
        }))
        assert ws.closed is True and p2p.is_ip_banned("203.0.113.10") is True

        # Valid genesis from unbanned higher-chain peer -> sends get_chain(from_height=1)
        ws2 = MockWebSocket("203.0.113.20", 5051)
        asyncio.run(p2p.handle_handshake(ws2, "203.0.113.20:5051", {
            "network": "UNIVA Network",
            "genesis_hash": bc.chain[0].hash,
            "height": 5,
            "chain_work": 100000,
        }))
        assert ws2.closed is False and len(ws2.sent) == 1
        req = json.loads(ws2.sent[0])
        assert req["type"] == "get_chain" and req["payload"]["from_height"] == 1
    finally:
        _reset_p2p_state(None)
    print("[PASS] 1. Handshake rejects mismatched genesis with immediate ban and requests sync from taller valid peer")


def test_2_sybil_and_eclipse_defenses():
    bc = Blockchain(auto_load_path=None)
    _reset_p2p_state(bc)
    try:
        # Per-IP limit (MAX_PEERS_PER_IP = 4)
        for port in range(4):
            pid = f"198.51.100.5:{5000 + port}"
            ok, reason = p2p.can_accept_peer("198.51.100.5", is_outbound=False)
            assert ok is True, reason
            p2p._connected_peers[pid] = MockWebSocket("198.51.100.5", 5000 + port)
            p2p._inbound_peers.add(pid)
        ok_5th, reason_5th = p2p.can_accept_peer("198.51.100.5", is_outbound=False)
        assert ok_5th is False and reason_5th == "per_ip_limit"

        # /24 Subnet Eclipse limit (MAX_PEERS_PER_SUBNET = 8)
        for host_octet in range(10, 14):
            pid = f"198.51.100.{host_octet}:5051"
            ok, _ = p2p.can_accept_peer(f"198.51.100.{host_octet}", is_outbound=False)
            assert ok is True
            p2p._connected_peers[pid] = MockWebSocket(f"198.51.100.{host_octet}", 5051)
            p2p._inbound_peers.add(pid)
        ok_sub, reason_sub = p2p.can_accept_peer("198.51.100.99", is_outbound=False)
        assert ok_sub is False and reason_sub == "per_subnet_limit"

        # Inbound saturation does NOT exhaust outbound slots (eclipse protection)
        _reset_p2p_state(bc)
        for idx in range(p2p.MAX_INBOUND_PEERS):
            ip = f"10.{(idx // 250) + 1}.{(idx % 250) + 1}:5051"
            p2p._connected_peers[ip] = MockWebSocket(ip.split(":")[0], 5051)
            p2p._inbound_peers.add(ip)
        ok_in, r_in = p2p.can_accept_peer("172.16.1.1", is_outbound=False)
        ok_out, r_out = p2p.can_accept_peer("172.16.1.2", is_outbound=True)
        assert ok_in is False and r_in == "max_inbound_reached"
        assert ok_out is True, f"Outbound slot should remain reserved, got {r_out}"
    finally:
        _reset_p2p_state(None)
    print("[PASS] 2. Sybil & Eclipse defenses verified (per-IP, /24 subnet, inbound/outbound slot isolation)")


def test_3_rate_limiting_and_misbehavior_ban():
    _reset_p2p_state(None)
    try:
        pid = "203.0.113.88:5051"
        for _ in range(p2p.MAX_MSGS_PER_MIN):
            assert p2p.check_peer_rate_limit(pid) is True
        # Exceeding triggers rate limit and immediate ban
        assert p2p.check_peer_rate_limit(pid) is False
        assert p2p.is_ip_banned("203.0.113.88") is True
    finally:
        _reset_p2p_state(None)
    print("[PASS] 3. Per-peer message rate limit triggers auto-ban when threshold exceeded")


def test_4_paginated_sync_and_p2p_fork_reorg():
    with tempfile.TemporaryDirectory() as td:
        tmp_chain_path = str(Path(td) / "p2p_reorg_chain.json")
        orig_chain_path = None
        bc_local = Blockchain(auto_load_path=None)
        bc_peer = Blockchain(auto_load_path=None)
        bc_peer.chain = [copy.deepcopy(bc_local.chain[0])]

        alice = UnivaWallet.create_new()
        bob = UnivaWallet.create_new()

        # Both share block #1
        b1 = bc_local.mine_pending_transactions(alice.address)
        assert bc_peer.accept_block(b1.to_dict()) is True

        # Local mines competing shorter branch block #2
        bc_local.mine_pending_transactions(bob.address)
        assert bc_local.height == 2

        # Peer mines heavier branch: blocks #2, #3, #4
        for _ in range(3):
            bc_peer.mine_pending_transactions(bob.address)
        assert bc_peer.height == 4

        # Patch chain save path safely inside Blockchain module for reorg save
        import core.blockchain as bc_mod
        orig_chain_path = bc_mod.CHAIN_FILE_PATH
        bc_mod.CHAIN_FILE_PATH = tmp_chain_path
        _reset_p2p_state(bc_local)
        try:
            ws = MockWebSocket("198.51.100.44", 5051)
            pid = "198.51.100.44:5051"

            # Peer announces block #3 on competing fork (index == our_height + 1, different prev_hash)
            asyncio.run(p2p.handle_new_block(ws, pid, {"block": bc_peer.chain[3].to_dict()}))
            assert len(ws.sent) == 1
            sync_req = json.loads(ws.sent[0])
            assert sync_req["type"] == "get_chain" and sync_req["payload"]["from_height"] == 0

            # Peer responds using paginated handle_get_chain
            ws_peer = MockWebSocket("198.51.100.45", 5051)
            p2p._blockchain_ref = bc_peer
            asyncio.run(p2p.handle_get_chain(ws_peer, "local:5051", {"from_height": 0}))
            chain_resp_msg = json.loads(ws_peer.sent[0])
            assert chain_resp_msg["type"] == "chain_response"
            assert len(chain_resp_msg["payload"]["blocks"]) == 5

            # Local processes chain_response and reorgs cleanly to height 4!
            p2p._blockchain_ref = bc_local
            asyncio.run(p2p.handle_chain_response(ws, pid, chain_resp_msg["payload"]))
            assert bc_local.height == 4
            assert bc_local.last_block.hash == bc_peer.last_block.hash
            assert bc_local.is_chain_valid() is True
        finally:
            bc_mod.CHAIN_FILE_PATH = orig_chain_path
            _reset_p2p_state(None)
    print("[PASS] 4. Paginated get_chain / chain_response sync & P2P fork reorganization verified (height 2 -> 4)")


def test_5_identity_spoofing_rejection_and_cleanup():
    bc = Blockchain(auto_load_path=None)
    _reset_p2p_state(bc)
    try:
        w_a = UnivaWallet.create_new()
        w_b = UnivaWallet.create_new()

        def build_signed(w, msg_type, payload):
            import secrets
            m = {
                "type": msg_type,
                "version": p2p.P2P_VERSION,
                "time": round(time.time(), 3),
                "nonce": secrets.token_hex(12),
                "payload": payload,
                "node_pubkey": w.public_key,
            }
            m["sig"] = w.sign(p2p._canonical_p2p_body(m))
            return json.dumps(m)

        # First message binds peer_id to w_a.public_key; second spoofed with w_b.public_key must trigger close + ban!
        msg1 = build_signed(w_a, "ping", {})
        msg2 = build_signed(w_b, "ping", {})
        ws = MockWebSocket("203.0.113.99", 5051, incoming=[msg1, msg2])
        asyncio.run(p2p.connection_handler(ws))

        assert ws.closed is True and ws.close_reason == "Peer identity mismatch"
        assert p2p.is_ip_banned("203.0.113.99") is True
        assert p2p.get_peer_count() == 0 and bc.peer_count == 0
    finally:
        _reset_p2p_state(None)
    print("[PASS] 5. Mid-session pubkey spoofing rejected/banned and peer connection state cleaned up cleanly")


if __name__ == "__main__":
    test_1_handshake_and_genesis_mismatch_ban()
    test_2_sybil_and_eclipse_defenses()
    test_3_rate_limiting_and_misbehavior_ban()
    test_4_paginated_sync_and_p2p_fork_reorg()
    test_5_identity_spoofing_rejection_and_cleanup()
    print("\nALL_P3_P2P_TESTS_PASSED (5/5)")
