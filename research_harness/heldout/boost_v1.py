"""BOOST-V1: the ONE held-out test of the registered booster candidate.

The registration (research_harness/registrations/<id>.json) names the
candidate ("candidate_id") and pins the crypto, ETF and T-bill datasets.
Refuses to run if it was already tested, edited after registering, or the
data differ from the pinned hashes. Result goes to research_harness/ledger.jsonl.

    python -m research_harness.heldout.boost_v1 --registration BOOST-V1-<X>
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from research_harness.explore.boost_v1 import COSTS, LOAD_START, TREND_COSTS, TREND_UNIVERSE
from research_harness.harness import metrics, registry
from research_harness.harness.fleet import _aligned, correlation, fleet_returns
from research_harness.harness.holdout import HOLDOUT_START
from research_harness.harness.portfolio import simulate
from research_harness.sleeves.booster import (
    BTC, CANDIDATES, ETH, MAX_DRAWDOWN_LIMIT, SLEEVE_FLEET_WEIGHT, STOP_PCT, make_candidate, to_sessions,
)
from research_harness.harness.store import BarStore
from research_harness.sleeves.trend import TrendParams, make_strategy as trend_strategy

HELDOUT_END = date(2026, 10, 15)
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
    crypto_ds = next(d for d in pinned if d.startswith("crypto"))
    etf_ds = next(d for d in pinned if d.startswith("etf"))
    rates_ds = next(d for d in pinned if d.startswith("fred"))

    def load(ds, s):
        return store.load(ds, s, start=LOAD_START, end=HELDOUT_END, registration_id=reg_id)

    etf = {s: load(etf_ds, s) for s in TREND_UNIVERSE}
    sessions = [b["day"] for b in etf["SPY"]]
    crypto = {s: to_sessions(load(crypto_ds, s), sessions) for s in (BTC, ETH)}
    rf = store.load_rates(rates_ds, "DTB3", start=LOAD_START, end=HELDOUT_END, registration_id=reg_id)

    spec = CANDIDATES[cid]
    res = simulate({s: crypto[s] for s in spec["symbols"]}, make_candidate(cid), costs=COSTS,
                   rf_annual=rf, start=HOLDOUT_START, end=HELDOUT_END, registration_id=reg_id,
                   whole_shares=False, stop_pct=STOP_PCT)
    # TREND-V1-B re-simulated exactly as registered (same code, data, costs):
    trend = simulate(etf, trend_strategy(TREND_UNIVERSE, TrendParams(rule="sma_210")), costs=TREND_COSTS,
                     rf_annual=rf, start=HOLDOUT_START, end=HELDOUT_END, registration_id=reg_id,
                     whole_shares=True, stop_pct=0.20)
    ref = simulate({BTC: crypto[BTC]}, lambda d, v: {BTC: 1.0}, costs=COSTS, rf_annual=rf,
                   start=HOLDOUT_START, end=HELDOUT_END, registration_id=reg_id)

    summary = metrics.summarize(res.curve, res.trades, rf_annual=rf, cost_label=res.cost_label,
                                traded_notional=res.traded_notional, fills=res.fills)
    summary["stops_hit"] = res.stops_hit
    days, rets = _aligned({"boost": res.curve, "trend": trend.curve})
    c = correlation(rets["boost"], rets["trend"])
    corr = round(c, 3) if c is not None else None
    w = SLEEVE_FLEET_WEIGHT
    with_boost = fleet_returns(rets, {"boost": w, "trend": 1 - w})
    sharpe_with, sharpe_without = _excess_sharpe(days, with_boost, rf), _excess_sharpe(days, rets["trend"], rf)

    bars = {
        "1_beats_tbills_after_costs": (summary.get("excess_return_vs_tbill_pct") or float("-inf")) > 0,
        "2_max_drawdown_no_worse_than_-50pct": summary["max_drawdown_pct"] >= MAX_DRAWDOWN_LIMIT * 100,
        "3_correlation_to_trend_below_0.5": corr is not None and corr < 0.5,
        "4_fleet_sharpe_rises_with_4pct_booster": (
            sharpe_with is not None and sharpe_without is not None and sharpe_with > sharpe_without),
    }
    passed = all(bars.values())
    out = {
        "registration": reg_id, "candidate": cid,
        "window": [HOLDOUT_START.isoformat(), HELDOUT_END.isoformat()],
        "summary": summary,
        "correlation_to_trend_v1_b": corr,
        "fleet_proxy": {"weights": {"booster": w, "trend_v1_b": 1 - w},
                        "sharpe_excess_tbill_with": sharpe_with, "sharpe_excess_tbill_without": sharpe_without,
                        "note": "Fleet = TREND-V1-B + booster only; momentum has no reproducible backtest yet."},
        "btc_buy_and_hold_reference": metrics.summarize(ref.curve, ref.trades, rf_annual=rf),
        "pass_bar": {**bars, "full_fleet_test": "NOT YET TESTABLE (momentum sleeve not reproducible)"},
        "verdict": ("PASS on all four registered bars (full-fleet test still pending)" if passed
                    else "FAIL: " + ", ".join(k for k, v in bars.items() if not v)),
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
