"""GEAR-V1: the ONE held-out test of the registered gearbox candidate.

The registration (research_harness/registrations/<id>.json) names the
candidate ("candidate_id") and pins the gearbox ETF data, the T-bill data and
the TREND-V1-B ETF data (used only for the information-only fleet mix).
Refuses to run if already tested, edited after registering, or the data
differ from the pinned hashes. Result goes to research_harness/ledger.jsonl.

    python -m research_harness.heldout.gear_v1 --registration GEAR-V1-<X>
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from research_harness.explore.gear_v1 import (
    LOAD_START, SYMBOLS, run_candidate, spy_hold, worst_rolling_vs,
)
from research_harness.harness import metrics, registry
from research_harness.harness.fleet import _aligned, fleet_returns
from research_harness.harness.holdout import HOLDOUT_START
from research_harness.harness.portfolio import simulate
from research_harness.harness.store import BarStore
from research_harness.sleeves.gear import CANDIDATES
from research_harness.sleeves.trend import TrendParams, make_strategy as trend_strategy

HELDOUT_END = date(2026, 10, 15)
TARGET_CAGR_PCT = 10.5
TREND_UNIVERSE = ["SPY", "IWM", "EFA", "EEM", "VNQ", "TLT", "IEF", "LQD", "TIP", "GLD", "DBC"]
# Information only, fixed here before the test: 80% gearbox + 20% TREND-V1-B.
INFO_MIX = {"gear": 0.8, "trend": 0.2}
ROOT = Path(__file__).resolve().parents[2]


def _excess_sharpe(days, r, rf):
    s = metrics.sharpe(r, metrics.rf_daily_for(days, rf))
    return round(s, 3) if s is not None else None


def run(reg_id: str, store: BarStore | None = None, *, directory: Path = registry.REGISTRATIONS_DIR,
        ledger: Path = registry.LEDGER_PATH, record: bool = True) -> dict[str, Any]:
    store = store or BarStore()
    reg = registry.begin_run(reg_id, "holdout_test", directory=directory, ledger=ledger)
    cid = reg["candidate_id"]
    if cid not in CANDIDATES:
        raise RuntimeError(f"unknown candidate {cid!r}; refusing to run")
    pinned = reg["data"]
    for ds, h in pinned.items():
        if store.manifest_hash(ds) != h:
            raise RuntimeError(f"{ds} does not match the pinned manifest hash; refusing to run")
    gear_ds = next(d for d in pinned if d.startswith("gear"))
    trend_ds = next(d for d in pinned if d.startswith("etf"))
    rates_ds = next(d for d in pinned if d.startswith("fred"))

    def load(ds, s):
        return store.load(ds, s, start=LOAD_START, end=HELDOUT_END, registration_id=reg_id)

    bars = {s: load(gear_ds, s) for s in SYMBOLS}
    rf = store.load_rates(rates_ds, "DTB3", start=LOAD_START, end=HELDOUT_END, registration_id=reg_id)
    res, summary = run_candidate(cid, bars, rf, HOLDOUT_START, HELDOUT_END, registration_id=reg_id)
    spy, spy_s = spy_hold(bars, rf, HOLDOUT_START, HELDOUT_END, registration_id=reg_id)
    summary["worst_3y_vs_spy_pct_points"] = worst_rolling_vs(res.curve, spy.curve)

    trend_bars = {s: load(trend_ds, s) for s in TREND_UNIVERSE}
    from research_harness.explore.trend_v1 import COSTS as TREND_COSTS
    trend = simulate(trend_bars, trend_strategy(TREND_UNIVERSE, TrendParams(rule="sma_210")),
                     costs=TREND_COSTS, rf_annual=rf, start=HOLDOUT_START, end=HELDOUT_END,
                     registration_id=reg_id, whole_shares=True, stop_pct=0.20)
    days, rets = _aligned({"gear": res.curve, "trend": trend.curve})
    mix = fleet_returns(rets, INFO_MIX)

    cagr = summary.get("cagr_pct")
    bars_ = {
        "1_cagr_beats_spy": cagr is not None and cagr > spy_s["cagr_pct"],
        "2_cagr_at_least_10.5pct": cagr is not None and cagr >= TARGET_CAGR_PCT,
        # Amendment 2 (GEAR-V1-PLAN.md): smaller worst fall than SPY's, same window.
        "3_max_drawdown_smaller_than_spy": summary["max_drawdown_pct"] > spy_s["max_drawdown_pct"],
    }
    passed = all(bars_.values())
    out = {
        "registration": reg_id, "candidate": cid, "mixes": CANDIDATES[cid],
        "window": [HOLDOUT_START.isoformat(), HELDOUT_END.isoformat()],
        "summary": summary,
        "spy_buy_and_hold": spy_s,
        "pass_bar": {**bars_, "4_fleet_test": "NOT YET TESTABLE (momentum sleeve not reproducible)"},
        "information_only": {
            "mix_weights": INFO_MIX,
            "sharpe_excess_tbill_gear_alone": _excess_sharpe(days, rets["gear"], rf),
            "sharpe_excess_tbill_mix": _excess_sharpe(days, mix, rf),
        },
        "verdict": ("PASS on bars 1-3 (fleet test still pending)" if passed
                    else "FAIL: " + ", ".join(k for k, v in bars_.items() if not v)),
    }
    if record:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                    text=True, cwd=ROOT).stdout.strip() or None
        except OSError:
            commit = None
        registry.record_run(reg, "holdout_test", out, code_commit=commit, ledger=ledger,
                            data_manifest_hashes=dict(pinned))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registration", required=True)
    a = ap.parse_args(argv)
    out = run(a.registration)
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / f"{a.registration}-HELDOUT.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
