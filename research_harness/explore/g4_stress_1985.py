"""G4-STRESS-1985 (information only; plan: research_harness/explore/G4-STRESS-1985-PLAN.md).

G4's registered rules on instruments rebuilt from index closes, so it can be
seen through the 1987 crash and the 2000-02 dot-com crash. Also runs the same
reconstruction on 2007-2020 to show how far it is from G4 on the real ETFs.
Nothing here changes G4 or any registration.

    QT_RESEARCH_DATA=research_harness/data python -m research_harness.explore.g4_stress_1985
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from research_harness.explore.gear_v1 import COSTS, STOP_PCT
from research_harness.harness import metrics
from research_harness.harness.holdout import EXPLORE_END
from research_harness.harness.metrics import TRADING_DAYS, rf_daily_for
from research_harness.harness.portfolio import simulate
from research_harness.harness.store import BarStore
from research_harness.sleeves.gear import SMA_SESSIONS, gear_stats, make_strategy

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "G4-STRESS-1985"
INDEX_DATASET = "index_ych_2026-10-30"
RATES_DATASET = "fred_dtb3_1985_2026-10-30"
SP, NDX = "^GSPC", "^NDX"
FEES = {"SSO": 0.0088, "QLD": 0.0096}        # ProShares gross expense ratios (read 30 Oct 2026)
STRESS_END = date(2006, 12, 31)
FIDELITY = (date(2007, 1, 1), date(2020, 12, 31))
G4_REAL_2007_2020 = {"cagr_pct": 11.70, "max_drawdown_pct": -32.10}   # GEAR-V1 exploration log
SUB_WINDOWS = {"1987": (date(1987, 1, 1), date(1987, 12, 31)),
               "2000-2002": (date(2000, 1, 1), date(2002, 12, 31))}


def close_to_close(closes: list[tuple[date, float]]) -> list[dict[str, Any]]:
    """Bars whose open is the previous close and whose high/low are the close."""
    out, prev = [], None
    for d, c in closes:
        o = c if prev is None else prev
        out.append({"day": d, "open": o, "high": c, "low": c, "close": c})
        prev = c
    return out


def levered(closes: list[tuple[date, float]], rf_annual: dict[date, float], lev: float,
            fee_annual: float, start_value: float = 100.0) -> list[tuple[date, float]]:
    """Daily-reset leveraged series: lev x the index's daily return, minus the
    T-bill rate on the borrowed (lev - 1), minus the fund's yearly fee."""
    days = [d for d, _ in closes]
    rf_d = rf_daily_for(days, rf_annual)
    out = [(days[0], start_value)]
    for i in range(1, len(closes)):
        r = closes[i][1] / closes[i - 1][1] - 1
        r_lev = lev * r - (lev - 1) * rf_d[i] - fee_annual / TRADING_DAYS
        out.append((days[i], max(out[-1][1] * (1 + r_lev), 1e-6)))
    return out


def build_instruments(index: dict[str, list[dict]], rf: dict[date, float]) -> dict[str, list[dict]]:
    sp = [(b["day"], b["close"]) for b in index[SP]]
    nd = [(b["day"], b["close"]) for b in index[NDX]]
    return {"SPY": close_to_close(sp), "QQQ": close_to_close(nd),
            "SSO": close_to_close(levered(sp, rf, 2.0, FEES["SSO"])),
            "QLD": close_to_close(levered(nd, rf, 2.0, FEES["QLD"]))}


def first_tradable_day(bars: dict[str, list[dict]]) -> date:
    """First day with 200 S&P sessions behind it and a Nasdaq-100 bar."""
    return max(bars["SPY"][SMA_SESSIONS - 1]["day"], bars["QQQ"][0]["day"])


def run_window(bars, rf, start: date, end: date) -> dict[str, Any]:
    log: list = []
    res = simulate(bars, make_strategy("G4", log), costs=COSTS, rf_annual=rf, start=start, end=end,
                   whole_shares=False, stop_pct=STOP_PCT)
    s = metrics.summarize(res.curve, res.trades, rf_annual=rf, cost_label=res.cost_label,
                          traded_notional=res.traded_notional, fills=res.fills)
    s["stops_hit"] = res.stops_hit
    s["gears"] = gear_stats(log, "G4", start, end)
    s["sub_windows"] = {k: metrics.summarize(res.curve, res.trades, start=a, end=b, rf_annual=rf)
                        for k, (a, b) in SUB_WINDOWS.items() if a >= start and b <= end}
    return s


def hold(bars, sym: str, rf, start: date, end: date) -> dict[str, Any]:
    res = simulate({sym: bars[sym]}, lambda d, v: {sym: 1.0}, costs=COSTS, rf_annual=rf,
                   start=start, end=end, whole_shares=False)
    s = metrics.summarize(res.curve, res.trades, rf_annual=rf)
    s["sub_windows"] = {k: metrics.summarize(res.curve, res.trades, start=a, end=b, rf_annual=rf)
                        for k, (a, b) in SUB_WINDOWS.items() if a >= start and b <= end}
    return s


def run(store: BarStore | None = None, *, log_path: Path | None = LOG_PATH) -> dict[str, Any]:
    store = store or BarStore()
    lo = date(1985, 1, 1)
    index = {s: store.load(INDEX_DATASET, s, start=lo, end=EXPLORE_END) for s in (SP, NDX)}
    rf = store.load_rates(RATES_DATASET, "DTB3", start=lo, end=EXPLORE_END)
    bars = build_instruments(index, rf)
    start = first_tradable_day(bars)
    out: dict[str, Any] = {
        "plan": PLAN_ID, "kind": "information only (reconstructed instruments, price indices, no dividends)",
        "data": {INDEX_DATASET: store.manifest_hash(INDEX_DATASET),
                 RATES_DATASET: store.manifest_hash(RATES_DATASET)},
        "costs": COSTS.label() + "; 2x fees 0.88% / 0.96% a year; borrowed 1x pays T-bills",
        "stress": {"window": [start.isoformat(), STRESS_END.isoformat()],
                   "G4_reconstructed": run_window(bars, rf, start, STRESS_END),
                   "sp500_price_hold": hold(bars, "SPY", rf, start, STRESS_END),
                   "nasdaq100_price_hold": hold(bars, "QQQ", rf, start, STRESS_END)},
        "fidelity_2007_2020": {"G4_reconstructed": run_window(bars, rf, *FIDELITY),
                               "G4_real_etfs_logged": G4_REAL_2007_2020},
    }
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
    argparse.ArgumentParser().parse_args(argv)
    out = run()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
