"""GEAR-V2 exploration (plan: research_harness/explore/GEAR-V2-PLAN.md).

Runs A0 (must reproduce G4's logged exploration result), A1 and A3 on
2007-01-01..2020-12-31, picks Part A by the plan rule, then tests Part B's
always-on slice. Results go to research_harness/exploration_log.jsonl and a
report; they are NOT evidence. The held-out period is refused by the store.

    QT_RESEARCH_DATA=research_harness/data python -m research_harness.explore.gear_v2
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from research_harness.explore.gear_v1 import LOAD_START, STOP_PCT, WHOLE_SHARES, spy_hold, worst_rolling_vs
from research_harness.harness import metrics
from research_harness.harness.costs import CostModel
from research_harness.harness.fleet import evaluate_sleeve, fleet_curve
from research_harness.harness.holdout import EXPLORE_END
from research_harness.harness.portfolio import simulate
from research_harness.harness.store import BarStore
from research_harness.sleeves.gear import gear_stats
from research_harness.sleeves.gear_v2 import (
    CORE, DBMF, SELECTABLE, SLICE_WEIGHT, TREND_UNIVERSE, make_slice_strategy, make_strategy,
)

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "GEAR-V2"
WINDOW_START = date(2007, 1, 1)
HALVES = ((date(2007, 1, 1), date(2013, 12, 31)), (date(2014, 1, 1), date(2020, 12, 31)))

# Pinned data (plan section "Data"). A different manifest hash stops the run.
GEAR_DATASET = ("gear_etf_ych_2026-10-22", "eb7d2e469206b93406fb8986766542f602bd67ec233c2b99333467169a01127b")
ENGINE_DATASET = ("etf_daily_yf_2026-10-16", "119c8e0ff7781b560c4049ac4c965445bfbd3e97c24747e3b4cfb718a8168221")
RATES_DATASET = ("fred_dtb3_2026-10-16", "008c90e42510326b9ed9098e4e634c5fd1a1949e3dfcd7651edf1ec85fb216df")
GEAR_SYMBOLS = ["SPY", "QQQ", "SSO", "QLD"]
ENGINE_SYMBOLS = [s for s in TREND_UNIVERSE if s not in GEAR_SYMBOLS]   # one SPY series: the gearbox's

COSTS = CostModel(commission_bps=0, half_spread_bps=2, slippage_bps=3,
                  short_borrow_bps_yr=0, financing_spread_bps_yr=650)
STRESS_COSTS = CostModel(commission_bps=0, half_spread_bps=2, slippage_bps=3,
                         short_borrow_bps_yr=100, financing_spread_bps_yr=650)
A0_LOGGED = {"cagr_pct": 11.70, "max_drawdown_pct": -32.10}   # GEAR-V1 exploration log, G4


class PinnedDataError(RuntimeError):
    """A dataset's manifest hash differs from the one the plan pinned."""


def load_bars(store: BarStore, end: date, registration_id: str | None = None,
              dbmf: tuple[str, str] | None = None) -> tuple[dict, dict, dict[str, str]]:
    """Bars for every symbol GEAR-V2 uses, the T-bill rate, and the manifest
    hashes. ``dbmf`` = (dataset, pinned hash) for A2, or None."""
    pinned = [GEAR_DATASET, ENGINE_DATASET, RATES_DATASET] + ([dbmf] if dbmf else [])
    hashes = {}
    for name, want in pinned:
        got = store.manifest_hash(name)
        if got != want:
            raise PinnedDataError(f"{name}: manifest hash {got} != pinned {want}")
        hashes[name] = got
    kw = dict(start=LOAD_START, end=end, registration_id=registration_id)
    bars = {s: store.load(GEAR_DATASET[0], s, **kw) for s in GEAR_SYMBOLS}
    bars.update({s: store.load(ENGINE_DATASET[0], s, **kw) for s in ENGINE_SYMBOLS})
    if dbmf:
        bars[DBMF] = store.load(dbmf[0], DBMF, **kw)
    rf = store.load_rates(RATES_DATASET[0], "DTB3", **kw)
    return bars, rf, hashes


def safe_gear_stats(curve, log) -> dict[str, Any]:
    """Compounded return on the sessions held under a safe-gear decision (the
    gear decided at the previous close was safe): the part GEAR-V2 changes."""
    gear = dict(log)
    growth, n = 1.0, 0
    for i in range(1, len(curve)):
        if gear.get(curve[i - 1][0]) == "safe":
            growth *= curve[i][1] / curve[i - 1][1]
            n += 1
    return {"sessions": n, "compounded_return_pct": round((growth - 1) * 100, 2)}


def _summary(res, rf, start: date, end: date) -> dict[str, Any]:
    s = metrics.summarize(res.curve, res.trades, rf_annual=rf, cost_label=res.cost_label,
                          traded_notional=res.traded_notional, fills=res.fills)
    s.update(costs_paid_usd=round(res.costs_paid, 2), borrow_paid_usd=round(res.borrow_paid, 2),
             financing_paid_usd=round(res.financing_paid, 2), stops_hit=res.stops_hit)
    s["halves"] = {f"{a.isoformat()}..{b.isoformat()}": metrics.summarize(
        res.curve, res.trades, start=a, end=b, rf_annual=rf) for a, b in HALVES
        if a >= start and b <= end}
    return s


def run_engine(engine: str, bars, rf, start: date, end: date, *, costs: CostModel = COSTS,
               registration_id: str | None = None):
    """G4 with ``engine`` in the safe gear. Returns (SimResult, summary)."""
    log: list = []
    res = simulate(bars, make_strategy(engine, log), costs=costs, rf_annual=rf, start=start, end=end,
                   registration_id=registration_id, whole_shares=WHOLE_SHARES, stop_pct=STOP_PCT,
                   allow_short=True)
    s = _summary(res, rf, start, end)
    s["gears"] = gear_stats(log, CORE, start, end)
    s["safe_gear"] = safe_gear_stats(res.curve, log)
    return res, s


def run_slice(bars, rf, start: date, end: date, *, costs: CostModel = COSTS,
              registration_id: str | None = None):
    """Part B's always-on long/short trend on its own."""
    uni = {s: bars[s] for s in TREND_UNIVERSE}
    res = simulate(uni, make_slice_strategy(), costs=costs, rf_annual=rf, start=start, end=end,
                   registration_id=registration_id, whole_shares=WHOLE_SHARES, stop_pct=STOP_PCT,
                   allow_short=True)
    return res, _summary(res, rf, start, end)


def fund_summary(core_curve, slice_curve, rf) -> tuple[list, dict[str, Any]]:
    """B1: (1 - SLICE_WEIGHT) core + SLICE_WEIGHT slice, rebalanced daily."""
    curve = fleet_curve({"core": core_curve, "slice": slice_curve},
                        {"core": 1 - SLICE_WEIGHT, "slice": SLICE_WEIGHT})
    s = metrics.summarize(curve, [], rf_annual=rf)
    s["note"] = "fund curve: constant weights rebalanced daily (harness rule); trade counts live in the sleeves"
    return curve, s


def choose_part_a(summaries: dict[str, dict]) -> str:
    """Plan rule: CAGR above A0's AND max drawdown no worse than A0's; then the
    highest CAGR; ties to the simpler (A1, then A3). None qualifies -> A0."""
    a0 = summaries["A0"]
    ok = [e for e in SELECTABLE if e in summaries
          and summaries[e]["cagr_pct"] > a0["cagr_pct"]
          and summaries[e]["max_drawdown_pct"] >= a0["max_drawdown_pct"]]
    if not ok:
        return "A0"
    best = max(summaries[e]["cagr_pct"] for e in ok)
    return next(e for e in ok if summaries[e]["cagr_pct"] == best)


def choose_part_b(sleeve_test: dict, b0: dict, b1: dict) -> str:
    """Plan rule: the slice passes the rebuild-plan sleeve test AND B1's max
    drawdown is smaller than B0's."""
    return "B1" if sleeve_test["passes"] and b1["max_drawdown_pct"] > b0["max_drawdown_pct"] else "B0"


def a0_reproduces(s: dict) -> bool:
    return all(abs(s[k] - v) < 0.005 for k, v in A0_LOGGED.items())


def run(store: BarStore | None = None, *, log_path: Path | None = LOG_PATH) -> dict[str, Any]:
    store = store or BarStore()
    bars, rf, hashes = load_bars(store, EXPLORE_END)
    start, end = WINDOW_START, EXPLORE_END
    spy, spy_s = spy_hold(bars, rf, start, end)
    out: dict[str, Any] = {
        "plan": PLAN_ID, "window": [start.isoformat(), end.isoformat()], "data": hashes,
        "costs": COSTS.label() + " (assumed: 0 commission, 2 bps half-spread, 3 bps slippage, "
                 "0 bps borrow per Alpaca ETB docs, 650 bps financing spread that should never apply)",
        "spy_buy_and_hold": spy_s, "candidates": {},
    }
    curves = {}
    for engine in ("A0",) + SELECTABLE:
        res, s = run_engine(engine, bars, rf, start, end)
        s["worst_3y_vs_spy_pct_points"] = worst_rolling_vs(res.curve, spy.curve)
        out["candidates"][engine] = s
        curves[engine] = res.curve
    if not a0_reproduces(out["candidates"]["A0"]):
        out["stopped"] = (f"A0 did not reproduce the logged G4 exploration result {A0_LOGGED}; "
                          "nothing is selected until the difference is explained (plan rule)")
    else:
        a = choose_part_a(out["candidates"])
        sl_res, sl_s = run_slice(bars, rf, start, end)
        test = evaluate_sleeve("slice", {"core": curves[a], "slice": sl_res.curve},
                               {"core": 1 - SLICE_WEIGHT, "slice": SLICE_WEIGHT}, rf)
        b0 = out["candidates"][a]
        b1_curve, b1 = fund_summary(curves[a], sl_res.curve, rf)
        b1["worst_3y_vs_spy_pct_points"] = worst_rolling_vs(b1_curve, spy.curve)
        b = choose_part_b(test, b0, b1)
        out["part_a"] = {"chosen": a, "rule": "CAGR > A0 and max drawdown no worse than A0; highest CAGR"}
        out["part_b"] = {"chosen": b, "slice_alone": sl_s, "sleeve_test": test, "B1_fund": b1,
                         "rule": "slice passes sleeve test AND B1 max drawdown smaller than B0's"}
        stress = {}
        for name in ("A3", "slice"):
            r, s = (run_engine("A3", bars, rf, start, end, costs=STRESS_COSTS) if name == "A3"
                    else run_slice(bars, rf, start, end, costs=STRESS_COSTS))
            stress[name] = {k: s[k] for k in ("cagr_pct", "max_drawdown_pct", "sharpe_excess_tbill",
                                              "borrow_paid_usd")}
        out["stress_100bps_borrow_information_only"] = stress
        out["chosen_for_registration"] = None if (a, b) == ("A0", "B0") else f"{a}+{b}"
        out["note"] = ("Exploration only. Not evidence. Next: register the chosen configuration, then test once."
                       if out["chosen_for_registration"] else
                       "No improvement found: G4 stays as registered; no held-out test (plan rule).")
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
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / "GEAR-V2-EXPLORE.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
