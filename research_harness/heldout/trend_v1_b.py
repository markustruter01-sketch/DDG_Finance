"""TREND-V1-B: the ONE held-out test of the registered trend candidate.

Refuses to run if the registration was already held-out tested, if it was
edited after registering, or if the data files differ from the pinned
manifest hashes. The result is recorded in research_harness/ledger.jsonl.

    python -m research_harness.heldout.trend_v1_b
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from research_harness.explore.trend_v1 import COSTS, LOAD_START, STOP_PCT, UNIVERSE, WHOLE_SHARES
from research_harness.harness import metrics, registry
from research_harness.harness.fleet import correlation
from research_harness.harness.holdout import HOLDOUT_START
from research_harness.harness.portfolio import simulate
from research_harness.harness.store import BarStore
from research_harness.sleeves.trend import TrendParams, make_strategy

REG_ID = "TREND-V1-B"
HELDOUT_END = date(2026, 10, 15)
ROOT = Path(__file__).resolve().parents[2]


def _rets(curve):
    return {curve[i][0]: curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve))}


def run(store: BarStore | None = None, *, directory: Path = registry.REGISTRATIONS_DIR,
        ledger: Path = registry.LEDGER_PATH, record: bool = True) -> dict[str, Any]:
    store = store or BarStore()
    reg = registry.begin_run(REG_ID, "holdout_test", directory=directory, ledger=ledger)
    (etf_ds, etf_hash), (rates_ds, rates_hash) = sorted(
        reg["data"].items(), key=lambda kv: not kv[0].startswith("etf"))
    for ds, pinned in ((etf_ds, etf_hash), (rates_ds, rates_hash)):
        if store.manifest_hash(ds) != pinned:
            raise RuntimeError(f"{ds} does not match the pinned manifest hash; refusing to run")
    if list(reg["universe"]) != UNIVERSE:
        raise RuntimeError("universe differs from the registration; refusing to run")

    bars = {s: store.load(etf_ds, s, start=LOAD_START, end=HELDOUT_END, registration_id=REG_ID)
            for s in UNIVERSE}
    rf = store.load_rates(rates_ds, "DTB3", start=LOAD_START, end=HELDOUT_END, registration_id=REG_ID)
    res = simulate(bars, make_strategy(UNIVERSE, TrendParams(rule="sma_210")), costs=COSTS,
                   rf_annual=rf, start=HOLDOUT_START, end=HELDOUT_END, registration_id=REG_ID,
                   whole_shares=WHOLE_SHARES, stop_pct=STOP_PCT)
    spy = simulate({"SPY": bars["SPY"]}, lambda d, v: {"SPY": 1.0}, costs=COSTS, rf_annual=rf,
                   start=HOLDOUT_START, end=HELDOUT_END, registration_id=REG_ID)
    summary = metrics.summarize(res.curve, res.trades, rf_annual=rf, cost_label=res.cost_label,
                                traded_notional=res.traded_notional, fills=res.fills)
    summary["stops_hit"] = res.stops_hit
    r, sr = _rets(res.curve), _rets(spy.curve)
    common = sorted(set(r) & set(sr))
    corr = correlation([r[d] for d in common], [sr[d] for d in common])
    summary["correlation_to_spy"] = round(corr, 3) if corr is not None else None
    beats_tbills = (summary.get("excess_return_vs_tbill_pct") or float("-inf")) > 0
    out = {
        "registration": REG_ID,
        "window": [HOLDOUT_START.isoformat(), HELDOUT_END.isoformat()],
        "summary": summary,
        "spy_buy_and_hold_reference": metrics.summarize(spy.curve, spy.trades, rf_annual=rf),
        "pass_bar": {"1_beats_tbills_after_costs": beats_tbills,
                     "2_fleet_correlation_and_sharpe": "NOT YET TESTABLE"},
        "verdict": ("BAR 1 PASSED; sleeve not yet passed (bar 2 pending)" if beats_tbills
                    else "FAIL: did not beat T-bills after costs"),
    }
    if record:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                    text=True, cwd=ROOT).stdout.strip() or None
        except OSError:
            commit = None
        registry.record_run(reg, "holdout_test", out, code_commit=commit, ledger=ledger,
                            data_manifest_hashes={etf_ds: etf_hash, rates_ds: rates_hash})
    return out


def main() -> int:
    out = run()
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / "TREND-V1-B-HELDOUT.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
