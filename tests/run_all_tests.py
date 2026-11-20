"""UNIVA Master Automated Test Runner — Executes P0 through P7 + Standalone DEX Suites."""
import os
import subprocess
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = [
    ("P0 Security", "tests/test_p0_security.py"),
    ("P1 Consensus", "tests/test_p1_blockchain.py"),
    ("P2 Wallet", "tests/test_p2_wallet.py"),
    ("P3 P2P", "tests/test_p3_p2p.py"),
    ("P4 DEX", "tests/test_p4_dex.py"),
    ("P4 Standalone DEX", "test_dex.py"),
    ("P5 Offline Pay & Escrow", "tests/test_p5_offline.py"),
    ("P6 Multichain & RPC", "tests/test_p6_multichain_rpc.py"),
    ("P7 Mainnet Readiness", "tests/test_p7_mainnet.py"),
]


def main() -> int:
    print("=" * 72)
    print("  UNIVA SOVEREIGN LAYER-1 — FULL AUDIT TEST RUNNER (P0 -> P7)")
    print("=" * 72)
    failed = []
    total_start = time.perf_counter()
    for label, rel_path in SUITES:
        full_path = os.path.join(ROOT_DIR, rel_path)
        t0 = time.perf_counter()
        res = subprocess.run([sys.executable, full_path], cwd=ROOT_DIR, capture_output=True, text=True)
        dt = time.perf_counter() - t0
        status = "PASS" if res.returncode == 0 else "FAIL"
        print(f"  [{status}] {label:<26} ({rel_path:<32})  {dt:5.2f}s")
        if res.returncode != 0:
            failed.append((label, rel_path, res.stdout, res.stderr))
    total_dt = time.perf_counter() - total_start
    print("=" * 72)
    if failed:
        print(f"FAILED SUITES: {len(failed)}/{len(SUITES)} (total {total_dt:.2f}s)")
        for label, rel_path, out, err in failed:
            print(f"\n--- FAILURE: {label} ({rel_path}) ---")
            print(out[-1200:])
            print(err[-1200:])
        return 1
    print(f"ALL {len(SUITES)}/{len(SUITES)} TEST SUITES PASSED! (total {total_dt:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
