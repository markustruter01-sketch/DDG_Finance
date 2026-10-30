"""GEAR-V2: the ONE held-out test of the registered configuration.

The registration (research_harness/registrations/<id>.json) names the Part A
engine ("part_a") and Part B choice ("part_b") and pins the datasets. Refuses
to run if already tested, edited after registering, or the pinned data
differ. DBMF (A2) is information only: its dataset was pulled after
registration, so its manifest hash is recorded here, not pinned there.
Result goes to research_harness/ledger.jsonl.

    QT_RESEARCH_DATA=research_harness/data \
    python -m research_harness.heldout.gear_v2 --registration GEAR-V2-<X> [--dbmf-dataset <name>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from research_harness.explore.gear_v1 import spy_hold, worst_rolling_vs
from research_harness.explore.gear_v2 import (
    ENGINE_DATASET, GEAR_DATASET, RATES_DATASET, STRESS_COSTS, fund_summary, load_bars,
    run_engine, run_slice,
)
from research_harness.harness import registry
from research_harness.harness.fleet import evaluate_sleeve
from research_harness.harness.holdout import HOLDOUT_START
from research_harness.harness.store import BarStore
from research_harness.sleeves.gear_v2 import ENGINES, SLICE_WEIGHT

HELDOUT_END = date(2026, 10, 15)
TARGET_CAGR_PCT = 12.5
G4_LEDGER = {"cagr_pct": 18.05, "max_drawdown_pct": -24.50}   # GEAR-V1-G4 held-out (ledger)
KEYS = ("cagr_pct", "max_drawdown_pct", "vol_pct", "sharpe_excess_tbill", "total_return_pct")
ROOT = Path(__file__).resolve().parents[2]


def _brief(s: dict) -> dict:
    return {k: s.get(k) for k in KEYS}


def run(reg_id: str, store: BarStore | None = None, *, dbmf_dataset: str | None = None,
        directory: Path = registry.REGISTRATIONS_DIR, ledger: Path = registry.LEDGER_PATH,
        record: bool = True) -> dict[str, Any]:
    store = store or BarStore()
    reg = registry.begin_run(reg_id, "holdout_test", directory=directory, ledger=ledger)
    a, b = reg["part_a"], reg["part_b"]
    if a not in ENGINES or b not in ("B0", "B1"):
        raise RuntimeError(f"unknown configuration {a}+{b}; refusing to run")
    want = dict((GEAR_DATASET, ENGINE_DATASET, RATES_DATASET))
    if reg["data"] != want:
        raise RuntimeError("registration data differ from the plan's pinned datasets; refusing to run")
    dbmf = (dbmf_dataset, store.manifest_hash(dbmf_dataset)) if dbmf_dataset else None
    bars, rf, hashes = load_bars(store, HELDOUT_END, registration_id=reg_id, dbmf=dbmf)
    start, end = HOLDOUT_START, HELDOUT_END
    spy, spy_s = spy_hold(bars, rf, start, end, registration_id=reg_id)

    core, core_s = run_engine(a, bars, rf, start, end, registration_id=reg_id)
    core_s["worst_3y_vs_spy_pct_points"] = worst_rolling_vs(core.curve, spy.curve)
    result, corr = core_s, None
    out: dict[str, Any] = {"registration": reg_id, "configuration": f"{a}+{b}",
                           "window": [start.isoformat(), end.isoformat()],
                           "spy_buy_and_hold": spy_s, "core": core_s}
    if b == "B1":
        sl, sl_s = run_slice(bars, rf, start, end, registration_id=reg_id)
        test = evaluate_sleeve("slice", {"core": core.curve, "slice": sl.curve},
                               {"core": 1 - SLICE_WEIGHT, "slice": SLICE_WEIGHT}, rf)
        fund_curve, result = fund_summary(core.curve, sl.curve, rf)
        result["worst_3y_vs_spy_pct_points"] = worst_rolling_vs(fund_curve, spy.curve)
        corr = test["correlations"]["core"]
        stress_res, stress = run_slice(bars, rf, start, end, costs=STRESS_COSTS, registration_id=reg_id)
        _, stress_fund = fund_summary(core.curve, stress_res.curve, rf)
        out.update(slice_alone=sl_s, sleeve_test=test, fund=result,
                   stress_100bps_borrow_information_only={"slice": _brief(stress),
                                                          "fund": _brief(stress_fund)})
    cagr = result.get("cagr_pct")
    checks = {
        "1_cagr_beats_spy": cagr is not None and cagr > spy_s["cagr_pct"],
        "2_cagr_at_least_12.5pct": cagr is not None and cagr >= TARGET_CAGR_PCT,
        "3_max_drawdown_smaller_than_spy": result["max_drawdown_pct"] > spy_s["max_drawdown_pct"],
        "4_sharpe_excess_tbill_above_spy": (result.get("sharpe_excess_tbill") is not None
                                            and result["sharpe_excess_tbill"] > spy_s["sharpe_excess_tbill"]),
    }
    if b == "B1":
        checks["5_slice_correlation_below_0_5"] = corr is not None and corr < 0.5
    info: dict[str, Any] = {}
    if a != "A0":
        _, a0 = run_engine("A0", bars, rf, start, end, registration_id=reg_id)
        info["A0_g4_as_registered"] = _brief(a0)
    else:
        info["A0_matches_ledger"] = all(abs(core_s[k] - v) < 0.005 for k, v in G4_LEDGER.items())
    if dbmf:
        _, a2 = run_engine("A2", bars, rf, start, end, registration_id=reg_id)
        info["A2_dbmf_safe_gear"] = {**_brief(a2), "safe_gear": a2["safe_gear"]}
    else:
        info["A2_dbmf_safe_gear"] = "not run: no DBMF dataset given"
    out.update(pass_bar=checks, information_only=info,
               verdict="PASS" if all(checks.values())
               else "FAIL: " + ", ".join(k for k, v in checks.items() if not v))
    if record:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                    text=True, cwd=ROOT).stdout.strip() or None
        except OSError:
            commit = None
        registry.record_run(reg, "holdout_test", out, code_commit=commit, ledger=ledger,
                            data_manifest_hashes=hashes)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registration", required=True)
    ap.add_argument("--dbmf-dataset")
    a = ap.parse_args(argv)
    out = run(a.registration, dbmf_dataset=a.dbmf_dataset)
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / f"{a.registration}-HELDOUT.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
