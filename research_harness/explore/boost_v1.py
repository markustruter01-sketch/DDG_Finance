"""BOOST-V1 exploration: the three declared candidates on 2015–2020 only.

Plan: research_harness/explore/BOOST-V1-PLAN.md (committed before any crypto
data was pulled). Results go to exploration_log.jsonl and a report; they are
NOT evidence. The store refuses held-out reads without a registration.

    python -m research_harness.explore.boost_v1 --crypto-dataset <name> \
        --etf-dataset etf_daily_yf_2026-10-16 --rates-dataset fred_dtb3_2026-10-16
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
from research_harness.sleeves.booster import (
    BTC, CANDIDATES, ETH, MAX_DRAWDOWN_LIMIT, STOP_PCT, make_candidate, to_sessions,
)
from research_harness.sleeves.trend import TrendParams, make_strategy as trend_strategy

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "BOOST-V1"
LOAD_START = date(2010, 1, 1)
WINDOW_START = date(2015, 1, 1)
# Plan "Costs": Alpaca crypto taker fee 25 bps (Tier 1, docs read 22 Oct 2026),
# 5 bps half-spread and 5 bps slippage (assumed, not measured).
COSTS = CostModel(commission_bps=25, half_spread_bps=5, slippage_bps=5,
                  short_borrow_bps_yr=0, financing_spread_bps_yr=0)
TREND_UNIVERSE = ["SPY", "IWM", "EFA", "EEM", "VNQ", "TLT", "IEF", "LQD", "TIP", "GLD", "DBC"]
TREND_COSTS = CostModel(0, 2, 3, 0, 0)


def _rets(curve):
    return {curve[i][0]: curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve))}


def _corr(a: dict, b: dict) -> float | None:
    common = sorted(set(a) & set(b))
    c = correlation([a[d] for d in common], [b[d] for d in common])
    return round(c, 3) if c is not None else None


def choose(candidates: dict[str, dict[str, Any]]) -> str | None:
    """Plan rule: drawdown gate first, then highest Sharpe vs T-bills; ties to
    the simpler candidate (A, B, C). None if no candidate passes the gate."""
    order = list(CANDIDATES)
    ok = [c for c in order
          if (candidates[c]["summary"].get("max_drawdown_pct") or -100) >= MAX_DRAWDOWN_LIMIT * 100]
    if not ok:
        return None
    return max(ok, key=lambda c: (candidates[c]["summary"].get("sharpe_excess_tbill")
                                  or float("-inf"), -order.index(c)))


def run(crypto_dataset: str, etf_dataset: str, rates_dataset: str, store: BarStore | None = None,
        *, log_path: Path | None = LOG_PATH) -> dict[str, Any]:
    store = store or BarStore()
    etf = {s: store.load(etf_dataset, s, start=LOAD_START, end=EXPLORE_END) for s in TREND_UNIVERSE}
    sessions = [b["day"] for b in etf["SPY"]]
    crypto = {s: to_sessions(store.load(crypto_dataset, s, start=LOAD_START, end=EXPLORE_END), sessions)
              for s in (BTC, ETH)}
    rf = store.load_rates(rates_dataset, "DTB3", start=LOAD_START, end=EXPLORE_END)

    def btc_hold_no_stop(day, view):
        return {BTC: 1.0}

    ref = simulate({BTC: crypto[BTC]}, btc_hold_no_stop, costs=COSTS, rf_annual=rf,
                   start=WINDOW_START, end=EXPLORE_END)
    trend = simulate(etf, trend_strategy(TREND_UNIVERSE, TrendParams(rule="sma_210")), costs=TREND_COSTS,
                     rf_annual=rf, start=WINDOW_START, end=EXPLORE_END, whole_shares=True, stop_pct=0.20)
    trend_rets = _rets(trend.curve)
    out: dict[str, Any] = {
        "plan": PLAN_ID, "window": [WINDOW_START.isoformat(), EXPLORE_END.isoformat()],
        "data": {"crypto": [crypto_dataset, store.manifest_hash(crypto_dataset)],
                 "etf_calendar": [etf_dataset, store.manifest_hash(etf_dataset)],
                 "rates": [rates_dataset, store.manifest_hash(rates_dataset)]},
        "costs": COSTS.label() + " (25 bps Alpaca Tier-1 taker fee; 5+5 bps spread/slippage assumed)",
        "design": {"stop_pct": STOP_PCT, "fractional": True, "sessions": "US trading days (SPY)"},
        "btc_buy_and_hold_no_stop": metrics.summarize(ref.curve, ref.trades, rf_annual=rf,
                                                      traded_notional=ref.traded_notional, fills=ref.fills),
        "candidates": {},
    }
    for cid, spec in CANDIDATES.items():
        bars = {s: crypto[s] for s in spec["symbols"]}
        res = simulate(bars, make_candidate(cid), costs=COSTS, rf_annual=rf,
                       start=WINDOW_START, end=EXPLORE_END, whole_shares=False, stop_pct=STOP_PCT)
        s = metrics.summarize(res.curve, res.trades, rf_annual=rf, cost_label=res.cost_label,
                              traded_notional=res.traded_notional, fills=res.fills)
        s["costs_paid_usd"] = round(res.costs_paid, 2)
        s["stops_hit"] = res.stops_hit
        s["correlation_to_trend_v1_b_explore"] = _corr(_rets(res.curve), trend_rets)
        out["candidates"][cid] = {"spec": spec, "summary": s}
    best = choose(out["candidates"])
    out["chosen_for_registration"] = best
    out["note"] = ("Exploration only. Not evidence. Next: register the chosen candidate, then test once."
                   if best else "No candidate met the -50% drawdown gate: nothing is registered (plan rule).")
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
    ap.add_argument("--crypto-dataset", required=True)
    ap.add_argument("--etf-dataset", required=True)
    ap.add_argument("--rates-dataset", required=True)
    a = ap.parse_args(argv)
    out = run(a.crypto_dataset, a.etf_dataset, a.rates_dataset)
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / "BOOST-V1-EXPLORE.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
