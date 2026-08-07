"""
_test_infra_stage1.py — Combined unit-test runner for Stage 1 infrastructure
-----------------------------------------------------------------------------
Runs the self-tests for all 3 new modules and prints a consolidated summary.

Usage:
    cd trading-platform
    python3 core/_test_infra_stage1.py

This is a DEV test script — not production code.  It makes live Yahoo Finance
requests and will fail if the network is unavailable.
"""
import sys
import os
import time

# Run from trading-platform/ or from project root
_here = os.path.dirname(os.path.abspath(__file__))
_tp   = os.path.dirname(_here)   # trading-platform/
if _tp not in sys.path:
    sys.path.insert(0, _tp)

import logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")

print()
print("╔══════════════════════════════════════════════════════════════════════╗")
print("║  STAGE 1 INFRASTRUCTURE — COMBINED UNIT TESTS                       ║")
print("║  core/vol_targeting.py  ·  core/correlation_cap.py                  ║")
print("║  core/regional_regime.py                                             ║")
print("╚══════════════════════════════════════════════════════════════════════╝")
print()

results = {}

# ── Module 1 — vol_targeting ──────────────────────────────────────────────────
t0 = time.time()
try:
    from core.vol_targeting import _selftest as _vt_test
    ok = _vt_test()
    results["vol_targeting"] = ("PASS" if ok else "FAIL", time.time() - t0)
except Exception as exc:
    results["vol_targeting"] = ("ERROR", time.time() - t0)
    print(f"\nvol_targeting import/run error: {exc}")

# ── Module 2 — correlation_cap ────────────────────────────────────────────────
print()
t0 = time.time()
try:
    from core.correlation_cap import _selftest as _cc_test
    ok = _cc_test()
    results["correlation_cap"] = ("PASS" if ok else "FAIL", time.time() - t0)
except Exception as exc:
    results["correlation_cap"] = ("ERROR", time.time() - t0)
    print(f"\ncorrelation_cap import/run error: {exc}")

# ── Module 3 — regional_regime ────────────────────────────────────────────────
print()
t0 = time.time()
try:
    from core.regional_regime import _selftest as _rr_test
    ok = _rr_test()
    results["regional_regime"] = ("PASS" if ok else "FAIL", time.time() - t0)
except Exception as exc:
    results["regional_regime"] = ("ERROR", time.time() - t0)
    print(f"\nregional_regime import/run error: {exc}")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("╔══════════════════════════════════════════════════════════════════════╗")
print("║  SUMMARY                                                             ║")
print("╠══════════════════════════════════════════════════════════════════════╣")
all_pass = True
for module, (status, elapsed) in results.items():
    icon = "✅" if status == "PASS" else "❌"
    print(f"║  {icon}  {module:<28}  {status:<6}  ({elapsed:.1f}s)               ║")
    if status != "PASS":
        all_pass = False
print("╠══════════════════════════════════════════════════════════════════════╣")
overall = "ALL TESTS PASS" if all_pass else "SOME TESTS FAILED"
print(f"║  {overall:<68}  ║")
print("╚══════════════════════════════════════════════════════════════════════╝")
print()

sys.exit(0 if all_pass else 1)
