"""FLEET-V1 exploration (plan: research_harness/explore/FLEET-V1-PLAN.md).

Runs the four candidates (C1, C2, F1, F2), the controls (B, A0, N1, S2) and
the random-gear null (N2) on the warm-up + exploration data only
(1985-10-01 .. 2010-12-31), applies the plan's selection rule, and appends
one record to exploration_log.jsonl. It never reads a locked row: every
load ends on 2010-12-31.

    QT_RESEARCH_DATA=research_harness/data python -m research_harness.explore.fleet_v1

Process step 6 (Fable) runs this once on real data. Until then it is only
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

from research_harness.harness import metrics, overfit
from research_harness.harness.costs import SymbolCosts
from research_harness.harness.fleet import _aligned, correlation, fleet_curve
from research_harness.harness.metrics import CurvePoint, rf_daily_for
from research_harness.harness.portfolio import HistoryView, simulate
from research_harness.recon import calibrate as cb
from research_harness.recon import reconstruct as rc
from research_harness.sleeves import core_v1, gear, xasset_v1

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "FLEET-V1"

# ── declared values (plan) ────────────────────────────────────────────────────
WARMUP_START = date(1985, 10, 1)
EXPLORE = (date(1987, 1, 1), date(2010, 12, 31))
FLEET_WEIGHTS = {"core": 0.65, "xasset": 0.35}
CASH_SPREAD = 0.005                       # cash earns DTB3 - 0.50% a year
N_TRIALS = 19
N2_DRAWS = 1000
N2_SEED = 20261102                        # fixed before any run
N1_EXPOSURE = 1.2
SELECT = {"sharpe_margin": 0.10, "max_dd_floor": -0.30, "tie": 0.02}
SIMPLICITY_ORDER = ["C2", "C1", "F2", "F1"]
ROLLING_YEARS = 10
ROLLING_WIN_SHARE = 0.70
ROLLING_DECLARED = 25                     # the plan's count; see rolling_windows()
NDX_SENSITIVITY = (0.0, 0.015)            # plus the declared 0.8%
# The held-out window 2011-2020 is entirely in the real-ETF era, so the
# held-out run (Process step 7) uses whole shares; exploration stays fractional.
HELDOUT_WHOLE_SHARES = True

COSTS = SymbolCosts(
    per_trade_bps={"SPY": 5.0, "QQQ": 5.0, "IEF": 5.0, "GLD": 5.0,
                   "SSO": 10.0, "QLD": 10.0, "UBT": 10.0, "UGL": 10.0, "DBC": 10.0, "UUP": 10.0},
    sell_fee_bps=0.3, short_borrow_bps_yr=0.0, financing_spread_bps_yr=0.0,
)
UNIVERSE = {
    "C1": ("SPY", "SSO", "QQQ", "QLD"), "C2": ("SPY", "SSO"),
    "S2": xasset_v1.LINES, "B": ("SPY",), "A0": ("SPY", "SSO", "QQQ", "QLD"), "N1": ("SPY", "SSO"),
}
UNIVERSE["F1"] = UNIVERSE["C1"] + UNIVERSE["S2"]
UNIVERSE["F2"] = UNIVERSE["C2"] + UNIVERSE["S2"]
CALIBRATION_PAIR = {                      # instrument -> calibration pairs whose haircut applies
    "SPY": ("SPX_TR vs SPY",), "SSO": ("SSO_R vs SSO",), "QLD": ("QLD_R vs QLD",),
    "QQQ": ("NDX_TR 0.8% vs QQQ",), "IEF": ("UST10_TR vs IEF",), "GLD": ("GOLD vs GLD",),
    "DBC": ("GSCI + T-bill vs DBC",),     # the lines use the + T-bill series (step-5 decision)
    "UUP": ("DXY + T-bill vs UUP",),
}
DATASETS = {"index": "fleet_idx_y", "etf": "fleet_etf_y", "rates": "fleet_rates_fred",
            "shiller": "fleet_shiller"}


# ── helpers ───────────────────────────────────────────────────────────────────
def cash_rate(dtb3: dict[date, float]) -> dict[date, float]:
    """What idle cash earns: DTB3 - 0.50%, floored at zero."""
    return {d: max(0.0, r - CASH_SPREAD) for d, r in dtb3.items()}


def numbers(curve: Sequence[CurvePoint], a: date, b: date, dtb3: dict[date, float]) -> dict[str, float] | None:
    """Unrounded CAGR, Sharpe (excess DTB3) and max drawdown of a curve over [a, b]."""
    pts = [p for p in curve if a <= p[0] <= b]
    if len(pts) < 3:
        return None
    rets = metrics.daily_returns(pts)
    r = [x for _, x in rets]
    rf = rf_daily_for([d for d, _ in rets], dtb3)
    years = (pts[-1][0] - pts[0][0]).days / 365.25
    s = metrics.sharpe(r, rf)
    return {"cagr": (pts[-1][1] / pts[0][1]) ** (1 / years) - 1 if years > 0 else 0.0,
            "sharpe": s if s is not None else 0.0,
            "max_dd": metrics.max_drawdown([p[1] for p in pts])}


def rolling_windows(explore: tuple[date, date] = EXPLORE) -> list[tuple[date, date]]:
    """Every 10-year window starting 1 Jan, stepped one year, that ends inside
    exploration. The plan's '25 windows' (starts 1987-2011) would run into the
    held-out period; only the 15 that fit (starts 1987-2001) are used."""
    out, y = [], explore[0].year
    while date(y + ROLLING_YEARS - 1, 12, 31) <= explore[1]:
        out.append((date(y, 1, 1), date(y + ROLLING_YEARS - 1, 12, 31)))
        y += 1
    return out


def haircut_for(cid: str, window_start: date, rebuilt_until: dict[str, date | None],
                haircuts: dict[str, float]) -> float | None:
    """The largest haircut among the candidate's instruments that are rebuilt
    for part of the window. rebuilt_until maps each instrument that has a
    rebuilt part to its real ETF's first day (None: rebuilt throughout).
    None if such an instrument has no calibration (reported, never guessed)."""
    worst = 0.0
    for sym in UNIVERSE[cid]:
        if sym not in rebuilt_until:
            continue                                   # real ETF only (or absent): nothing rebuilt
        first = rebuilt_until[sym]
        if first is not None and first <= window_start:
            continue                                   # real ETF for the whole window
        vals = [haircuts[p] for p in CALIBRATION_PAIR[sym] if p in haircuts]
        if not vals:
            return None
        worst = max(worst, max(vals))
    return worst


def worst_3y_vs(curve: Sequence[CurvePoint], bench: Sequence[CurvePoint], a: date, b: date) -> dict[str, Any] | None:
    """The 3-year stretch (monthly starts) where the curve's CAGR trailed the benchmark's most."""
    cv = {d: v for d, v, _ in curve if a <= d <= b}
    bv = {d: v for d, v, _ in bench if a <= d <= b}
    days = sorted(set(cv) & set(bv))
    firsts, seen = [], set()
    for d in days:
        if (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            firsts.append(d)
    worst = None
    for i in range(len(firsts) - 36):
        d0, d1 = firsts[i], firsts[i + 36]
        yrs = (d1 - d0).days / 365.25
        gap = (cv[d1] / cv[d0]) ** (1 / yrs) - (bv[d1] / bv[d0]) ** (1 / yrs)
        if worst is None or gap < worst["cagr_gap"]:
            worst = {"from": d0.isoformat(), "to": d1.isoformat(), "cagr_gap": gap}
    return worst


def corr_to(curve: Sequence[CurvePoint], bench: Sequence[CurvePoint], a: date, b: date) -> float | None:
    _, rets = _aligned({"x": [p for p in curve if a <= p[0] <= b], "b": [p for p in bench if a <= p[0] <= b]})
    return correlation(rets["x"], rets["b"])


# ── runs ──────────────────────────────────────────────────────────────────────
def _sim(bars, strategy, rf_cash, start, end, stop_pct=None, *, whole_shares=False, grant=None, plan=None):
    """Exploration: fractional shares, no grant. The held-out runner passes
    whole_shares=HELDOUT_WHOLE_SHARES and its read grant. ``plan``: another
    plan running F1 as a control inside its own declared exploration window."""
    return simulate(bars, strategy, costs=COSTS, rf_annual=rf_cash, start=start, end=end,
                    whole_shares=whole_shares, stop_pct=stop_pct, grant=grant, plan=plan)


def run_core(instr, cid, rf_cash, start, end, *, whole_shares=False, grant=None, plan=None):
    log: list = []
    bars = {s: instr[s] for s in UNIVERSE[cid] if s in instr}
    return _sim(bars, core_v1.make_strategy(cid, log), rf_cash, start, end, core_v1.STOP_PCT,
                whole_shares=whole_shares, grant=grant, plan=plan), log


def run_xasset(instr, rf_cash, start, end, *, whole_shares=False, grant=None, plan=None):
    log: list = []
    bars = {s: instr[s] for s in xasset_v1.LINES if s in instr}
    return _sim(bars, xasset_v1.make_strategy(log), rf_cash, start, end,
                whole_shares=whole_shares, grant=grant, plan=plan), log


def run_hold(instr, rf_cash, start, end, *, whole_shares=False, grant=None):
    return _sim({"SPY": instr["SPY"]}, lambda d, v: {"SPY": 1.0}, rf_cash, start, end,
                whole_shares=whole_shares, grant=grant)


def run_a0(instr, rf_cash, start, end):
    """GEAR-V1-G4 rules as registered (200-day average, 20% vol line, 20% stops),
    on the reconstructed instruments, with FLEET-V1's costs and cash rate."""
    log: list = []
    bars = {s: instr[s] for s in UNIVERSE["A0"]}
    return _sim(bars, gear.make_strategy("G4", log), rf_cash, start, end, core_v1.STOP_PCT), log


def run_n1(instr, rf_cash, start, end):
    """Constant 1.2x S&P 500 (SPY/SSO split as in sleeve 1), rebalanced monthly, no signal, no stops."""
    w = core_v1.weights_for(N1_EXPOSURE, {"SP": 1.0})
    state: dict[str, Any] = {"month": None}

    def strategy(day: date, view: HistoryView):
        m = (day.year, day.month)
        if m == state["month"]:
            return None
        state["month"] = m
        return dict(w)

    return _sim({s: instr[s] for s in UNIVERSE["N1"]}, strategy, rf_cash, start, end)


def gear_replay(gears: dict[date, str]):
    """A G4 strategy whose gear each day comes from a given sequence (the N2 null)."""
    mixes = gear.CANDIDATES["G4"]
    state: dict[str, Any] = {"gear": None, "month": None}

    def strategy(day: date, view: HistoryView):
        g = gears.get(day)
        if g is None:
            return None
        m = (day.year, day.month)
        changed, new_month = g != state["gear"], m != state["month"]
        state["gear"], state["month"] = g, m
        if not (changed or new_month):
            return None
        return {} if g == "safe" else dict(mixes[g])

    return strategy


def run_n2(instr, rf_cash, dtb3, a0_log, start, end, draws=N2_DRAWS, seed=N2_SEED) -> dict[str, Any]:
    """Random-gear null: A0's gear sequence over the window, shuffled in monthly
    blocks (same time in each gear), run through G4's mixes and stops."""
    rows = [(d, g) for d, g in a0_log if start <= d <= end]
    days = [d for d, _ in rows]
    labels = [g for _, g in rows]
    rng = random.Random(seed)
    bars = {s: instr[s] for s in UNIVERSE["A0"]}
    sharpes = []
    for _ in range(draws):
        seq = overfit.block_shuffle(days, labels, rng)
        res = _sim(bars, gear_replay(dict(zip(days, seq))), rf_cash, start, end, core_v1.STOP_PCT)
        n = numbers(res.curve, start, end, dtb3)
        sharpes.append(n["sharpe"] if n else 0.0)
    share = {g: labels.count(g) / len(labels) for g in ("aggressive", "normal", "safe")} if labels else {}
    return {"draws": draws, "seed": seed, "time_in_gear": share,
            "sharpe_p95": overfit.percentile(sharpes, 95) if sharpes else None,
            "sharpe_median": overfit.percentile(sharpes, 50) if sharpes else None}


def select(nums: dict[str, dict[str, float]], hair_dd: dict[str, float | None],
           b: dict[str, float], n1_sharpe: float, n2_p95: float) -> dict[str, Any]:
    """The plan's selection rule (a)-(d); ties within 0.02 go to the simpler candidate."""
    checks = {}
    for cid in SIMPLICITY_ORDER:
        n, dd = nums[cid], hair_dd[cid]
        checks[cid] = {
            "a_cagr_ge_B": n["cagr"] >= b["cagr"],
            "b_sharpe_ge_B_plus_0.10": n["sharpe"] >= b["sharpe"] + SELECT["sharpe_margin"],
            "c_max_dd_after_haircut_ge_-30%": dd is not None and dd >= SELECT["max_dd_floor"],
            "d_sharpe_above_N2_p95_and_N1": n["sharpe"] > n2_p95 and n["sharpe"] > n1_sharpe,
        }
    ok = [c for c in SIMPLICITY_ORDER if all(checks[c].values())]
    if not ok:
        return {"checks": checks, "qualified": [], "selected": None, "verdict": "FAILED"}
    best = max(nums[c]["sharpe"] for c in ok)
    pick = next(c for c in SIMPLICITY_ORDER if c in ok and nums[c]["sharpe"] >= best - SELECT["tie"])
    return {"checks": checks, "qualified": ok, "selected": pick, "verdict": "SELECTED"}


def explore(instr: dict[str, list[dict]], dtb3: dict[date, float], haircuts: dict[str, float],
            rebuilt_until: dict[str, date | None], *, window: tuple[date, date] = EXPLORE, sim_start: date = WARMUP_START,
            n2_draws: int = N2_DRAWS, rebuild=None) -> dict[str, Any]:
    """Every exploration figure the plan asks for. ``rebuild(ndx_yield)`` returns
    instruments rebuilt with another Nasdaq-100 yield (dividend sensitivity)."""
    a, b = window
    rf_cash = cash_rate(dtb3)

    res, logs = {}, {}
    for cid in ("C1", "C2"):
        res[cid], logs[cid] = run_core(instr, cid, rf_cash, sim_start, b)
    res["S2"], logs["S2"] = run_xasset(instr, rf_cash, sim_start, b)
    res["B"] = run_hold(instr, rf_cash, sim_start, b)
    res["A0"], logs["A0"] = run_a0(instr, rf_cash, sim_start, b)
    res["N1"] = run_n1(instr, rf_cash, sim_start, b)
    curves = {k: v.curve for k, v in res.items()}
    w = FLEET_WEIGHTS
    curves["F1"] = fleet_curve({"core": curves["C1"], "xasset": curves["S2"]}, w)
    curves["F2"] = fleet_curve({"core": curves["C2"], "xasset": curves["S2"]}, w)
    n2 = run_n2(instr, rf_cash, dtb3, logs["A0"], a, b, draws=n2_draws)

    nums = {k: numbers(c, a, b, dtb3) for k, c in curves.items()}
    hair = {k: haircut_for(k, a, rebuilt_until, haircuts) for k in curves if k in UNIVERSE}
    hair_dd = {k: (None if hair[k] is None else nums[k]["max_dd"] - hair[k]) for k in hair}

    report: dict[str, Any] = {"window": [a.isoformat(), b.isoformat()], "candidates": {}, "controls": {}}
    for k in ("C1", "C2", "F1", "F2", "B", "A0", "N1", "S2"):
        tr = res[k].trades if k in res else []
        s = metrics.summarize(curves[k], tr, start=a, end=b, rf_annual=dtb3,
                              traded_notional=res[k].traded_notional if k in res else None,
                              fills=res[k].fills if k in res else None)
        s["exact"] = nums[k]
        s["haircut"] = hair[k]
        s["max_dd_after_haircut"] = hair_dd[k]
        s["correlation_to_B"] = corr_to(curves[k], curves["B"], a, b) if k != "B" else 1.0
        s["worst_3y_vs_B"] = worst_3y_vs(curves[k], curves["B"], a, b) if k != "B" else None
        if k in res:
            s["stops_hit"] = res[k].stops_hit
        if k in ("C1", "C2"):
            s["signal"] = core_v1.core_stats(logs[k], a, b)
        if k == "S2":
            s["signal"] = xasset_v1.xasset_stats(logs["S2"], a, b)
        if k == "A0":
            s["signal"] = gear.gear_stats(logs["A0"], "G4", a, b)
        report["candidates" if k in SIMPLICITY_ORDER else "controls"][k] = s
    report["controls"]["N2"] = n2

    wins = rolling_windows(window)
    roll = {}
    for cid in SIMPLICITY_ORDER:
        rows = []
        for wa, wb in wins:
            x, y = numbers(curves[cid], wa, wb, dtb3), numbers(curves["B"], wa, wb, dtb3)
            rows.append({"from": wa.isoformat(), "sharpe": x["sharpe"], "B_sharpe": y["sharpe"],
                         "beats_B": x["sharpe"] > y["sharpe"]})
        share = sum(r["beats_B"] for r in rows) / len(rows) if rows else None
        roll[cid] = {"windows": rows, "win_share": share,
                     "pass": share is not None and share >= ROLLING_WIN_SHARE}
    report["rolling"] = {"declared_windows": ROLLING_DECLARED, "windows_used": len(wins),
                         "note": "only windows ending by 2010-12-31 fit inside exploration", "by_candidate": roll}

    report["selection"] = select({c: nums[c] for c in SIMPLICITY_ORDER}, hair_dd, nums["B"],
                                 nums["N1"]["sharpe"], n2["sharpe_p95"] if n2["sharpe_p95"] is not None else math.inf)

    # Deflated Sharpe (information only in exploration; the pass bar uses the held-out window).
    rf_series = {}
    per_sr = []
    for cid in SIMPLICITY_ORDER:
        pts = [p for p in curves[cid] if a <= p[0] <= b]
        rets = metrics.daily_returns(pts)
        rf_series[cid] = ([x for _, x in rets], rf_daily_for([d for d, _ in rets], dtb3))
        per_sr.append(overfit.sharpe_per_period(*rf_series[cid]))
    var_sr = overfit.variance(per_sr)
    report["deflated_sharpe_exploration"] = {
        cid: overfit.deflated_sharpe(*rf_series[cid], n_trials=N_TRIALS, var_sharpe=var_sr)
        for cid in SIMPLICITY_ORDER}
    report["var_sharpe_across_candidates"] = var_sr

    if rebuild is not None:
        sens = {}
        for y in NDX_SENSITIVITY:
            alt = rebuild(y)
            c1, _ = run_core(alt, "C1", rf_cash, sim_start, b)
            s2, _ = run_xasset(alt, rf_cash, sim_start, b)
            f1 = fleet_curve({"core": c1.curve, "xasset": s2.curve}, w)
            sens[f"{y:.1%}"] = {"C1": numbers(c1.curve, a, b, dtb3), "F1": numbers(f1, a, b, dtb3)}
        report["ndx_dividend_sensitivity"] = sens
    return report


def rebuilt_until(built: dict[str, Any], etf_bars: dict[str, list[dict]]) -> dict[str, date | None]:
    """Instruments with a rebuilt part -> their real ETF's first day (None if no ETF pulled)."""
    return {s: (etf_bars[s][0]["day"] if etf_bars.get(s) else None)
            for s, name in rc.REAL_ETF.items() if name in built["recon"]}


def run(store=None, *, log_path: Path | None = LOG_PATH, n2_draws: int = N2_DRAWS) -> dict[str, Any]:
    from research_harness.harness.store import BarStore

    store = store or BarStore()
    lo, hi = date(1985, 1, 1), EXPLORE[1]
    idx = {s: store.load(DATASETS["index"], s, start=lo, end=hi) for s in rc.INDEX.values()}
    etfs = {}
    for s in rc.REAL_ETF:
        try:
            etfs[s] = store.load(DATASETS["etf"], s, start=lo, end=hi)
        except KeyError:
            etfs[s] = []
    rates = {s: store.load_rates(DATASETS["rates"], s, start=lo, end=hi) for s in ("DTB3", "DGS10")}
    shiller = store.load(DATASETS["shiller"], "SP500", start=lo, end=hi)
    cal = cb.calibrate(idx, etfs, rates, shiller)
    haircuts = {k: v["haircut"] for k, v in cal["pairs"].items()}

    def instruments(ndx_yield: float = rc.NDX_YIELD):
        return rc.build(idx, etfs, rates, shiller, ndx_yield=ndx_yield)["instruments"]

    built = rc.build(idx, etfs, rates, shiller)
    report = explore(built["instruments"], rates["DTB3"], haircuts, rebuilt_until(built, etfs),
                     n2_draws=n2_draws, rebuild=instruments)
    out = {"plan": PLAN_ID, "kind": "exploration (1987-2010), one run",
           "data": {ds: store.manifest_hash(ds) for ds in DATASETS.values()},
           "costs": COSTS.label() + "; cash earns DTB3 - 0.50% (floored at 0); fractional shares",
           "calibration": cal, **report}
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
    out = run(log_path=None if args.no_log else LOG_PATH)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
