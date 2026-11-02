"""MOMO-V1 exploration (plan: research_harness/explore/MOMO-V1-PLAN.md).

Runs M1 and M2, the controls (B, X18, F1) and the random-20 null (R) on the
warm-up + exploration data only (2018-01-01 .. 2024-12-31), applies the
plan's selection rule and appends one record to exploration_log.jsonl.
Reads past the legacy 2021 lock go through MOMO-V1's declared exploration
window (holdout.DECLARED_EXPLORATION_END); rows from 2025 are in the
datasets' locked parts and are never read here.

    QT_RESEARCH_DATA=research_harness/data python -m research_harness.explore.momo_v1

Process step 3 (Fable) runs this once on real data. Until then it is only
run on synthetic data by the tests.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from research_harness.explore import fleet_v1
from research_harness.harness import metrics, overfit
from research_harness.harness.costs import SymbolCosts
from research_harness.harness.fleet import fleet_curve
from research_harness.harness.metrics import CurvePoint, rf_daily_for
from research_harness.harness.portfolio import simulate
from research_harness.sleeves import momo_v1 as mv

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "MOMO-V1"

# ── declared values (plan) ────────────────────────────────────────────────────
WARMUP_START = date(2018, 1, 1)
EXPLORE = (date(2019, 2, 1), date(2024, 12, 31))
HELDOUT = (date(2025, 1, 1), date(2026, 10, 31))
LOCKED_FROM = HELDOUT[0]
N_TRIALS = 8
R_DRAWS = 500
R_SEED = 20261102                       # fixed before any run
STOCK_BPS, GEAR_BPS, SELL_FEE_BPS = 5.0, 10.0, 0.3
CASH_SPREAD = 0.005
SELECT = {"cagr_margin": 0.02, "dd_floor": -0.25, "dd_vs_b": 0.75, "tie": 0.01}
HELDOUT_DSR = 0.90
DATASETS = {"panel": "momo_panel", "etf": "momo_etf_y", "rates": "momo_rates_fred"}
ETF_SYMBOLS = ("SPY", "SSO", "QQQ", "QLD", "IEF", "GLD", "DBC", "UUP")


def costs_for(symbols: Sequence[str]) -> SymbolCosts:
    bps = {s: STOCK_BPS for s in symbols}
    bps.update({"SPY": STOCK_BPS, mv.GEAR: GEAR_BPS})
    return SymbolCosts(per_trade_bps=bps, sell_fee_bps=SELL_FEE_BPS,
                       short_borrow_bps_yr=0.0, financing_spread_bps_yr=0.0)


def held_symbols(selection: dict[date, list[str]]) -> set[str]:
    return {s for names in selection.values() for s in names}


def run_book(cid: str, panel: mv.Panel, etf: dict[str, list[dict]], selection: dict[date, list[str]],
             rf_cash: dict[date, float], start: date, end: date, *, use_dial: bool = True,
             plan: str | None = PLAN_ID, grant: Any = None):
    """One stock-book run (M1, M2, X18 or a null draw): only the bars it can hold."""
    names = held_symbols(selection)
    bars = {s: panel.bars[s] for s in names if s in panel.bars}
    bars["SPY"] = etf["SPY"]
    if mv.CANDIDATES[cid]["gear"] and use_dial:
        bars[mv.GEAR] = etf[mv.GEAR]
    log: list = []
    res = simulate(bars, mv.make_strategy(cid, selection, log, use_dial=use_dial),
                   costs=costs_for(names), rf_annual=rf_cash, start=start, end=end,
                   whole_shares=True, stop_pct=mv.STOP_PCT, plan=plan, grant=grant)
    return res, log


def random_pick(rng: random.Random):
    def pick(panel: mv.Panel, day: date, universe: list[str]) -> list[str]:
        return sorted(rng.sample(universe, min(mv.TOP_N, len(universe))))
    return pick


def run_null(panel, etf, signal_days, rf_cash, dtb3, start, end, draws=R_DRAWS, seed=R_SEED) -> dict[str, Any]:
    """Random 20 from each month's universe, M1's dial and stops; Sharpe distribution."""
    rng = random.Random(seed)
    universes = {d: mv.universe_on(panel, d) for d in signal_days}     # computed once, reused per draw
    sharpes = []
    for _ in range(draws):
        sel = {d: sorted(rng.sample(u, min(mv.TOP_N, len(u)))) for d, u in universes.items()}
        res, _ = run_book("M1", panel, etf, sel, rf_cash, start, end)
        n = fleet_v1.numbers(res.curve, start, end, dtb3)
        sharpes.append(n["sharpe"] if n else 0.0)
    return {"draws": draws, "seed": seed,
            "sharpe_p95": overfit.percentile(sharpes, 95) if sharpes else None,
            "sharpe_median": overfit.percentile(sharpes, 50) if sharpes else None}


def run_f1(etf, rf_cash, start, end, plan=PLAN_ID):
    """FLEET-V1-F1 from its own code, on the real ETFs (all listed before 2018)."""
    c1, _ = fleet_v1.run_core(etf, "C1", rf_cash, start, end, plan=plan)
    s2, _ = fleet_v1.run_xasset(etf, rf_cash, start, end, plan=plan)
    return fleet_curve({"core": c1.curve, "xasset": s2.curve}, fleet_v1.FLEET_WEIGHTS)


def select(nums: dict[str, dict[str, float]], b: dict[str, float], x18_sharpe: float,
           r_p95: float) -> dict[str, Any]:
    """The plan's rule (a)-(d); the higher CAGR wins, ties within 1 point to M1."""
    checks = {}
    for cid in mv.SIMPLICITY_ORDER:
        n = nums[cid]
        checks[cid] = {
            "a_cagr_ge_B_plus_2pts": n["cagr"] >= b["cagr"] + SELECT["cagr_margin"],
            "b_max_dd_ge_-25%_and_ge_0.75xB": n["max_dd"] >= SELECT["dd_floor"]
                                              and n["max_dd"] >= SELECT["dd_vs_b"] * b["max_dd"],
            "c_sharpe_above_R_p95": n["sharpe"] > r_p95,
            "d_sharpe_ge_X18": n["sharpe"] >= x18_sharpe,
        }
    ok = [c for c in mv.SIMPLICITY_ORDER if all(checks[c].values())]
    if not ok:
        return {"checks": checks, "qualified": [], "selected": None, "verdict": "FAILED"}
    best = max(nums[c]["cagr"] for c in ok)
    pick = next(c for c in mv.SIMPLICITY_ORDER if c in ok and nums[c]["cagr"] >= best - SELECT["tie"])
    return {"checks": checks, "qualified": ok, "selected": pick, "verdict": "SELECTED"}


def pass_bar(n: dict[str, float], b: dict[str, float], dsr: float) -> dict[str, Any]:
    """Held-out (and 2027 paper) bar: CAGR >= B + 2pts; drawdown >= -25% and
    >= 0.75 x B's; deflated Sharpe > 0.90 with N = 8."""
    items = {
        "1_cagr_ge_B_plus_2pts": n["cagr"] >= b["cagr"] + SELECT["cagr_margin"],
        "2_max_dd_ge_-25%_and_ge_0.75xB": n["max_dd"] >= SELECT["dd_floor"]
                                          and n["max_dd"] >= SELECT["dd_vs_b"] * b["max_dd"],
        "3_deflated_sharpe_gt_0.90": dsr > HELDOUT_DSR,
    }
    failed = [k for k, ok in items.items() if not ok]
    return {"items": items, "failed": failed, "verdict": "PASS" if not failed else f"FAIL: {', '.join(failed)}"}


def turnover(res, curve: Sequence[CurvePoint], start: date, end: date) -> float | None:
    pts = [p for p in curve if start <= p[0] <= end]
    years = (pts[-1][0] - pts[0][0]).days / 365.25 if len(pts) > 1 else 0
    avg = sum(p[1] for p in pts) / len(pts) if pts else 0
    return res.traded_notional / avg / years if years > 0 and avg > 0 else None


def exposure_stats(log, start: date, end: date) -> dict[str, Any]:
    rows = [r for r in log if start <= r[0] <= end]
    if not rows:
        return {"note": "no signal in window"}
    n = len(rows)
    return {"sessions": n,
            "time_in_cash_pct": round(100 * sum(1 for r in rows if r[2] == 0) / n, 1),
            "exposure_avg": round(sum(r[2] for r in rows) / n, 3),
            "exposure_max": round(max(r[2] for r in rows), 3),
            "vote_changes": sum(1 for i in range(1, n) if rows[i][1] != rows[i - 1][1])}


def explore(panel: mv.Panel, etf: dict[str, list[dict]], dtb3: dict[date, float], *,
            window: tuple[date, date] = EXPLORE, sim_start: date = WARMUP_START,
            r_draws: int = R_DRAWS, plan: str | None = PLAN_ID, with_f1: bool = True) -> dict[str, Any]:
    a, b = window
    rf_cash = fleet_v1.cash_rate(dtb3)
    signal_days = mv.month_first_sessions([x["day"] for x in etf["SPY"]], a, b)
    selection = mv.monthly_selection(panel, signal_days)

    res, logs, curves = {}, {}, {}
    for cid in mv.SIMPLICITY_ORDER:
        res[cid], logs[cid] = run_book(cid, panel, etf, selection, rf_cash, sim_start, b, plan=plan)
    res["X18"], _ = run_book("M1", panel, etf, selection, rf_cash, sim_start, b, use_dial=False, plan=plan)
    res["B"] = simulate({"SPY": etf["SPY"]}, lambda d, v: {"SPY": 1.0}, costs=costs_for([]),
                        rf_annual=rf_cash, start=sim_start, end=b, whole_shares=True, plan=plan)
    curves = {k: r.curve for k, r in res.items()}
    if with_f1:
        curves["F1"] = run_f1(etf, rf_cash, sim_start, b, plan=plan)
    null = run_null(panel, etf, signal_days, rf_cash, dtb3, sim_start, b, draws=r_draws)

    nums = {k: fleet_v1.numbers(c, a, b, dtb3) for k, c in curves.items()}
    report: dict[str, Any] = {"window": [a.isoformat(), b.isoformat()], "candidates": {}, "controls": {}}
    for k, c in curves.items():
        r = res.get(k)
        s = metrics.summarize(c, r.trades if r else [], start=a, end=b, rf_annual=dtb3)
        s["exact"] = nums[k]
        s["correlation_to_B"] = fleet_v1.corr_to(c, curves["B"], a, b) if k != "B" else 1.0
        s["worst_3y_vs_B"] = fleet_v1.worst_3y_vs(c, curves["B"], a, b) if k != "B" else None
        if r is not None:
            s.update(stops_hit=r.stops_hit, fills=r.fills, costs_paid=round(r.costs_paid, 2),
                     turnover_per_year=turnover(r, c, a, b))
        if k in logs:
            s["exposure"] = exposure_stats(logs[k], a, b)
        report["candidates" if k in mv.CANDIDATES else "controls"][k] = s
    report["controls"]["R"] = null
    report["selection"] = select({c: nums[c] for c in mv.SIMPLICITY_ORDER}, nums["B"],
                                 nums["X18"]["sharpe"],
                                 null["sharpe_p95"] if null["sharpe_p95"] is not None else math.inf)
    per_sr, rets = [], {}
    for cid in mv.SIMPLICITY_ORDER:
        pts = [p for p in curves[cid] if a <= p[0] <= b]
        dr = metrics.daily_returns(pts)
        rets[cid] = ([x for _, x in dr], rf_daily_for([d for d, _ in dr], dtb3))
        per_sr.append(overfit.sharpe_per_period(*rets[cid]))
    var_sr = overfit.variance(per_sr)
    report["var_sharpe_across_candidates"] = var_sr
    report["deflated_sharpe_exploration"] = {
        c: overfit.deflated_sharpe(*rets[c], n_trials=N_TRIALS, var_sharpe=var_sr) for c in mv.SIMPLICITY_ORDER}
    report["universe"] = {"signal_days": len(signal_days),
                          "names_ever_held": len(held_symbols(selection)),
                          "first_selection": {k.isoformat(): v for k, v in list(selection.items())[:1]}}
    return report


def load(store, end: date = EXPLORE[1], plan: str | None = PLAN_ID, grant: Any = None):
    """The three MOMO datasets up to ``end`` (exploration: never past 2024)."""
    lo = WARMUP_START
    panel_symbols = sorted(store.manifest(DATASETS["panel"])["symbols"])
    panel = mv.Panel({s: store.load(DATASETS["panel"], s, start=lo, end=end, plan=plan, grant=grant)
                      for s in panel_symbols})
    etf = {s: store.load(DATASETS["etf"], s, start=lo, end=end, plan=plan, grant=grant) for s in ETF_SYMBOLS}
    dtb3 = store.load_rates(DATASETS["rates"], "DTB3", start=lo, end=end, plan=plan, grant=grant)
    return panel, etf, dtb3


def run(store=None, *, log_path: Path | None = LOG_PATH, r_draws: int = R_DRAWS) -> dict[str, Any]:
    from research_harness.harness.store import BarStore

    store = store or BarStore()
    panel, etf, dtb3 = load(store)
    report = explore(panel, etf, dtb3, r_draws=r_draws)
    out = {"plan": PLAN_ID, "kind": "exploration (2019-02..2024-12), one run",
           "data": {ds: store.manifest_hash(ds) for ds in DATASETS.values()},
           "costs": f"{STOCK_BPS} bp stocks/SPY, {GEAR_BPS} bp SSO, SEC {SELL_FEE_BPS} bp on sales; "
                    "cash DTB3 - 0.50% (floored at 0); whole shares",
           **report}
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
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--no-log", action="store_true")
    args = p.parse_args(argv)
    print(json.dumps(run(log_path=None if args.no_log else LOG_PATH), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
