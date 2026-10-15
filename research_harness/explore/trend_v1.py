"""TREND-V1 exploration: run the three declared candidates on 2006–2020 only.

Results go to research_harness/exploration_log.jsonl and a report; they are
NOT evidence. The held-out period is refused by the store (no registration).

    python -m research_harness.explore.trend_v1 --etf-dataset <name> --rates-dataset <name>
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from research_harness.harness import metrics
from research_harness.harness.costs import CostModel
from research_harness.harness.fleet import correlation
from research_harness.harness.holdout import EXPLORE_END
from research_harness.harness.portfolio import simulate
from research_harness.harness.store import BarStore
from research_harness.sleeves.trend import TrendParams, make_strategy

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "TREND-V1"
UNIVERSE = ["SPY", "IWM", "EFA", "EEM", "VNQ", "TLT", "IEF", "LQD", "TIP", "GLD", "DBC"]
CANDIDATES = {"A": "tsmom_252", "B": "sma_210", "C": "blend_63_126_252"}
LOAD_START = date(1990, 1, 1)   # everything before the window is warm-up
WINDOW_START = date(2006, 1, 1)
COSTS = CostModel(commission_bps=0, half_spread_bps=2, slippage_bps=3,
                  short_borrow_bps_yr=0, financing_spread_bps_yr=0)


def _rets(curve):
    return {curve[i][0]: curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve))}


def run(etf_dataset: str, rates_dataset: str, store: BarStore | None = None,
        *, log_path: Path | None = LOG_PATH) -> dict[str, Any]:
    store = store or BarStore()
    bars = {s: store.load(etf_dataset, s, start=LOAD_START, end=EXPLORE_END) for s in UNIVERSE}
    rf = store.load_rates(rates_dataset, "DTB3", start=LOAD_START, end=EXPLORE_END)

    def spy_hold(day, view):
        return {"SPY": 1.0}

    spy = simulate({"SPY": bars["SPY"]}, spy_hold, costs=COSTS, rf_annual=rf,
                   start=WINDOW_START, end=EXPLORE_END)
    spy_rets = _rets(spy.curve)
    out: dict[str, Any] = {
        "plan": PLAN_ID, "window": [WINDOW_START.isoformat(), EXPLORE_END.isoformat()],
        "data": {"etf": [etf_dataset, store.manifest_hash(etf_dataset)],
                 "rates": [rates_dataset, store.manifest_hash(rates_dataset)]},
        "costs": COSTS.label() + " (assumed: 0 commission, 2 bps half-spread, 3 bps slippage)",
        "spy_buy_and_hold": metrics.summarize(spy.curve, spy.trades, rf_annual=rf,
                                              traded_notional=spy.traded_notional, fills=spy.fills),
        "candidates": {},
    }
    for cid, rule in CANDIDATES.items():
        res = simulate(bars, make_strategy(UNIVERSE, TrendParams(rule=rule)), costs=COSTS,
                       rf_annual=rf, start=WINDOW_START, end=EXPLORE_END)
        s = metrics.summarize(res.curve, res.trades, rf_annual=rf, cost_label=res.cost_label,
                              traded_notional=res.traded_notional, fills=res.fills)
        r = _rets(res.curve)
        common = sorted(set(r) & set(spy_rets))
        corr = correlation([r[d] for d in common], [spy_rets[d] for d in common])
        s["correlation_to_spy"] = round(corr, 3) if corr is not None else None
        s["costs_paid_usd"] = round(res.costs_paid, 2)
        out["candidates"][cid] = {"rule": rule, "summary": s}
    order = list(CANDIDATES)  # tie-break: simpler rule first
    best = max(order, key=lambda c: (out["candidates"][c]["summary"].get("sharpe_excess_tbill")
                                     or float("-inf"), -order.index(c)))
    out["chosen_for_registration"] = best
    out["note"] = "Exploration only. Not evidence. Next: register the chosen candidate, then test once."
    if log_path is not None:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                    text=True, cwd=ROOT).stdout.strip() or None
        except OSError:
            commit = None
        with log_path.open("a") as fh:
            fh.write(json.dumps({"ran_at": datetime.now(timezone.utc).isoformat(),
                                 "code_commit": commit, **out}, sort_keys=True, default=str) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--etf-dataset", required=True)
    ap.add_argument("--rates-dataset", required=True)
    a = ap.parse_args(argv)
    out = run(a.etf_dataset, a.rates_dataset)
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / "TREND-V1-EXPLORE.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
