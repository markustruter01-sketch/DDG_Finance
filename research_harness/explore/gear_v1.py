"""GEAR-V1 exploration: the four declared candidates on 2007-01-01..2020-12-31.

Results go to research_harness/exploration_log.jsonl and a report; they are
NOT evidence. The held-out period is refused by the store (no registration).

    python -m research_harness.explore.gear_v1 --etf-dataset <name> --rates-dataset <name>
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
from research_harness.harness.holdout import EXPLORE_END
from research_harness.harness.portfolio import simulate
from research_harness.harness.store import BarStore
from research_harness.sleeves.gear import CANDIDATES, SIMPLICITY_ORDER, gear_stats, make_strategy

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "GEAR-V1"
SYMBOLS = ["SPY", "QQQ", "SSO", "QLD"]
LOAD_START = date(1998, 1, 1)            # bars before the window are warm-up only
WINDOW_START = date(2007, 1, 1)
MAX_DRAWDOWN_LIMIT_PCT = -20.0
STOP_PCT = 0.20
WHOLE_SHARES = True
COSTS = CostModel(commission_bps=0, half_spread_bps=2, slippage_bps=3,
                  short_borrow_bps_yr=0, financing_spread_bps_yr=0)
ROLL_SESSIONS = 756                      # 3 years


def _rets(curve):
    return {curve[i][0]: curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve))}


def worst_rolling_vs(curve, bench_curve, n: int = ROLL_SESSIONS) -> float | None:
    """Worst n-session stretch of (strategy return - benchmark return), in % points."""
    b = dict((d, v) for d, v, *_ in bench_curve)
    pts = [(d, v, b[d]) for d, v, *_ in curve if d in b]
    if len(pts) <= n:
        return None
    worst = min((pts[i][1] / pts[i - n][1]) - (pts[i][2] / pts[i - n][2]) for i in range(n, len(pts)))
    return round(worst * 100, 2)


def run_candidate(cid: str, bars, rf, start: date, end: date, registration_id: str | None = None):
    log: list = []
    res = simulate({s: bars[s] for s in bars}, make_strategy(cid, log), costs=COSTS, rf_annual=rf,
                   start=start, end=end, registration_id=registration_id,
                   whole_shares=WHOLE_SHARES, stop_pct=STOP_PCT)
    s = metrics.summarize(res.curve, res.trades, rf_annual=rf, cost_label=res.cost_label,
                          traded_notional=res.traded_notional, fills=res.fills)
    s["costs_paid_usd"] = round(res.costs_paid, 2)
    s["stops_hit"] = res.stops_hit
    s["gears"] = gear_stats(log, cid, start, end)
    return res, s


def spy_hold(bars, rf, start: date, end: date, registration_id: str | None = None):
    res = simulate({"SPY": bars["SPY"]}, lambda d, v: {"SPY": 1.0}, costs=COSTS, rf_annual=rf,
                   start=start, end=end, registration_id=registration_id)
    return res, metrics.summarize(res.curve, res.trades, rf_annual=rf,
                                  traded_notional=res.traded_notional, fills=res.fills)


def choose(candidates: dict[str, dict], spy_cagr: float) -> str | None:
    """Plan rule: max drawdown no worse than -20% AND CAGR above SPY's; then the
    highest CAGR; ties go to the simpler candidate."""
    ok = [c for c in SIMPLICITY_ORDER if c in candidates
          and candidates[c]["summary"]["max_drawdown_pct"] >= MAX_DRAWDOWN_LIMIT_PCT
          and (candidates[c]["summary"].get("cagr_pct") or float("-inf")) > spy_cagr]
    if not ok:
        return None
    best = max(candidates[c]["summary"]["cagr_pct"] for c in ok)
    return next(c for c in ok if candidates[c]["summary"]["cagr_pct"] == best)


def run(etf_dataset: str, rates_dataset: str, store: BarStore | None = None,
        *, log_path: Path | None = LOG_PATH) -> dict[str, Any]:
    store = store or BarStore()
    bars = {s: store.load(etf_dataset, s, start=LOAD_START, end=EXPLORE_END) for s in SYMBOLS}
    rf = store.load_rates(rates_dataset, "DTB3", start=LOAD_START, end=EXPLORE_END)
    spy, spy_s = spy_hold(bars, rf, WINDOW_START, EXPLORE_END)
    out: dict[str, Any] = {
        "plan": PLAN_ID, "window": [WINDOW_START.isoformat(), EXPLORE_END.isoformat()],
        "data": {"etf": [etf_dataset, store.manifest_hash(etf_dataset)],
                 "rates": [rates_dataset, store.manifest_hash(rates_dataset)]},
        "costs": COSTS.label() + " (assumed: 0 commission, 2 bps half-spread, 3 bps slippage)",
        "design": {"stop_pct": STOP_PCT, "whole_shares": WHOLE_SHARES, "signal": "SPY close vs 200-session "
                   "average; 20-session realised vol vs 20%", "leverage": "2x ETFs only, account gross <= 1.0"},
        "spy_buy_and_hold": spy_s,
        "candidates": {},
    }
    for cid in CANDIDATES:
        res, s = run_candidate(cid, bars, rf, WINDOW_START, EXPLORE_END)
        s["worst_3y_vs_spy_pct_points"] = worst_rolling_vs(res.curve, spy.curve)
        out["candidates"][cid] = {"mixes": CANDIDATES[cid], "summary": s}
    best = choose(out["candidates"], spy_s["cagr_pct"])
    out["chosen_for_registration"] = best
    out["note"] = ("Exploration only. Not evidence. Next: register the chosen candidate, then test once."
                   if best else "No candidate beat SPY with max drawdown no worse than -20%: nothing is "
                                "registered and GEAR-V1 is reported as FAILED (plan rule).")
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
    report = ROOT / ".local" / "claude_reports" / "GEAR-V1-EXPLORE.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
