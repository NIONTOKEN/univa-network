"""
UNIVA NETWORK — TRC-20 (TRON) GATEWAY COMPREHENSIVE TEST SUITE
Verifies:
1. Pure-Python Base58Check validation, double-SHA256 checksums, and invalid address rejection.
2. Bidirectional EVM 0x <-> TRON T... address conversion.
3. TRC-20 USDT contract configuration (Mainnet & Nile).
4. TRC-20 Gateway state management, anti-replay deposit protection, and withdrawal queueing.
5. Live/Mock network balance query and overview response formatting.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.trc20 import TronAddress, TRC20Gateway, TRON_NETWORKS


class TestTRC20Gateway(unittest.TestCase):

    def test_1_tron_address_validation_and_checksum(self):
        # Official Tether USDT on TRON
        usdt_addr = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        self.assertTrue(TronAddress.is_valid(usdt_addr), "Official USDT address must be valid")

        # Official Binance TRON hot wallet
        binance_addr = "TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs"
        self.assertTrue(TronAddress.is_valid(binance_addr), "Valid Tron address must pass")

        # Invalid addresses
        self.assertFalse(TronAddress.is_valid(""), "Empty address must be invalid")
        self.assertFalse(TronAddress.is_valid("0x1234567890123456789012345678901234567890"), "EVM 0x is not Tron Base58")
        self.assertFalse(TronAddress.is_valid("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6X"), "Tampered checksum must be rejected")
        self.assertFalse(TronAddress.is_valid("AR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"), "Address not starting with T must be rejected")
        self.assertFalse(TronAddress.is_valid("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj"), "Too short address must be rejected")

    def test_2_bidirectional_evm_and_tron_conversions(self):
        usdt_addr = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        evm_equiv = TronAddress.to_evm(usdt_addr)
        self.assertTrue(evm_equiv.startswith("0x"), "EVM equivalent must start with 0x")
        self.assertEqual(len(evm_equiv), 42, "EVM equivalent must be 42 characters (20 bytes hex)")
        self.assertEqual(evm_equiv.lower(), "0xa614f803b6fd780986a42c78ec9c7f77e6ded13c")

        # Roundtrip back to Tron
        re_encoded = TronAddress.from_evm(evm_equiv)
        self.assertEqual(re_encoded, usdt_addr, "EVM to Tron roundtrip must match original exactly")

        # Custom EVM address
        test_evm = "0x915ee9e3ef45a87a20b6a9aa450ac4d6e7552be3"
        tron_converted = TronAddress.from_evm(test_evm)
        self.assertTrue(tron_converted.startswith("T"), "Converted Tron address must start with T")
        self.assertEqual(len(tron_converted), 34, "Converted Tron address must be 34 characters")
        self.assertTrue(TronAddress.is_valid(tron_converted), "Converted Tron address must be valid Base58Check")
        self.assertEqual(TronAddress.to_evm(tron_converted), test_evm.lower())

    def test_3_network_constants_and_contracts(self):
        mainnet = TRON_NETWORKS["mainnet"]
        self.assertEqual(mainnet["usdt_contract"], "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
        self.assertEqual(mainnet["decimals"], 6)

        nile = TRON_NETWORKS["nile"]
        self.assertEqual(nile["usdt_contract"], "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf")
        self.assertEqual(nile["decimals"], 6)

    def test_4_gateway_deposit_idempotency_and_anti_replay(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            gw = TRC20Gateway(network="mainnet", state_path=tmp_path)
            fake_tx_id = "a1b2c3d4e5f60718293a4b5c6d7e8f901234567890abcdef1234567890abcdef"

            # 1. First credit must succeed
            res1 = gw.register_user_deposit(
                tx_id=fake_tx_id,
                univa_user="kaya",
                amount_usdt=50.0,
                from_address="TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs"
            )
            self.assertTrue(res1["success"])
            self.assertEqual(res1["deposit"]["amount_usdt"], 50.0)
            self.assertEqual(res1["deposit"]["univa_user"], "kaya")

            # 2. Second credit with SAME tx_id must be strictly rejected (anti-replay)
            res2 = gw.register_user_deposit(
                tx_id=fake_tx_id,
                univa_user="hacker",
                amount_usdt=50.0,
                from_address="TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs"
            )
            self.assertFalse(res2["success"], "Duplicate deposit must be rejected")
            self.assertIn("replay protected", res2["error"])

            # 3. Reload from disk and verify persistence
            gw2 = TRC20Gateway(network="mainnet", state_path=tmp_path)
            stats = gw2.get_stats()
            self.assertEqual(stats["stats"]["deposit_count"], 1)
            self.assertEqual(stats["stats"]["total_deposited_usdt"], 50.0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_5_gateway_withdrawal_request(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            gw = TRC20Gateway(network="mainnet", state_path=tmp_path)

            # Invalid address must fail
            res_bad = gw.request_withdrawal("kaya", "invalid_address", 20.0)
            self.assertFalse(res_bad["success"])

            # Valid address must succeed
            target_tron = "TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs"
            res_ok = gw.request_withdrawal("kaya", target_tron, 25.0)
            self.assertTrue(res_ok["success"])
            w = res_ok["withdrawal"]
            self.assertEqual(w["net_amount"], 24.0)  # 25 - 1 fee
            self.assertEqual(w["status"], "QUEUED_HOT_WALLET")

            # Verify stats
            stats = gw.get_stats()
            self.assertEqual(stats["stats"]["withdrawal_count"], 1)
            self.assertEqual(stats["stats"]["total_withdrawn_usdt"], 25.0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_6_account_overview_format(self):
        gw = TRC20Gateway(network="mainnet")
        usdt_addr = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        overview = gw.get_account_overview(usdt_addr)
        self.assertTrue(overview["valid"])
        self.assertEqual(overview["address"], usdt_addr)
        self.assertIn("formatted_usdt", overview)
        self.assertEqual(overview["network"], "TRON Mainnet")


if __name__ == "__main__":
    unittest.main()
