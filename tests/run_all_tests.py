"""UNIVA Master Automated Test Suite Runner (P0 through P7 + Standalone DEX)."""
import os
import subprocess
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = [
    "test_dex.py",
    "tests/test_p0_security.py",
    "tests/test_p1_blockchain.py",
    "tests/test_p2_wallet.py",
    "tests/test_p3_p2p.py",
    "tests/test_p4_dex.py",
    "tests/test_p5_offline.py",
    "tests/test_p6_multichain_rpc.py",
    "tests/test_p7_mainnet_readiness.py",
]


def main() -> int:
    print("=" * 72)
    print("  UNIVA SOVEREIGN L1 — FULL AUDIT TEST RUNNER (P0 -> P7)")
    print("=" * 72)
    t_total = time.perf_counter()
    passed = 0
    failed = []
    for suite in SUITES:
        path = os.path.join(ROOT_DIR, suite)
        t0 = time.perf_counter()
        print(f"\n>>> Running {suite} ...")
        res = subprocess.run([sys.executable, path], cwd=ROOT_DIR)
        dt = time.perf_counter() - t0
        if res.returncode == 0:
            passed += 1
            print(f"[OK] {suite} ({dt:.2f}s)")
        else:
            failed.append(suite)
            print(f"[FAIL] {suite} (exit={res.returncode}, {dt:.2f}s)")
    print("\n" + "=" * 72)
    print(f"  SUMMARY: {passed}/{len(SUITES)} suites passed in {time.perf_counter() - t_total:.2f}s")
    if failed:
        print(f"  FAILED : {', '.join(failed)}")
        print("=" * 72)
        return 1
    print("  STATUS : ALL UNIVA AUDIT SUITES (P0..P7) PASSED!")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
