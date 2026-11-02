"""VOL-V1 exploration (plan: research_harness/explore/VOL-V1-PLAN.md).

Runs the candidates (V1 ATM, V2 2% OTM estimate) and the controls (B: S&P 500
TR held; PUT: the CBOE index ungated; N1: the S&P TR held at the gate's N)
over the exploration window 2007-07-02 .. 2015-12-31 (plan Amendment 1;
warm-up from 2006-06), applies the plan's selection rule, and appends one
record to exploration_log.jsonl. Every load ends on 2015-12-31, before the
datasets' lock, so no locked row is read.

    QT_RESEARCH_DATA=research_harness/data python -m research_harness.explore.vol_v1

Data (all locked from 2016-01-01): ``vol_put_cboe_b`` (CBOE PUT, daily from
2007-06-29), ``vol_gate_y`` (SPY adjusted = the dial's S&P TR series, ^GSPC =
the price index for contract counts), ``vol_rates_fred`` (DTB3). If the PUT
dataset is missing the run stops (the plan declares no fallback).

Process step 3 (Fable) runs this once on real data. Until then it is only run
on synthetic data by the tests.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from research_harness.explore import fleet_v1 as fv
from research_harness.harness import metrics, overfit
from research_harness.harness.metrics import CurvePoint, rf_daily_for
from research_harness.sleeves import vol_v1

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "research_harness" / "exploration_log.jsonl"
PLAN_ID = "VOL-V1"

# ── declared values (plan) ────────────────────────────────────────────────────
WARMUP_START = date(2006, 6, 1)           # Amendment 1: CBOE's daily PUT history starts 2007-06-29
EXPLORE = (date(2007, 7, 2), date(2015, 12, 31))
HELDOUT = (date(2016, 1, 1), date(2020, 12, 31))
LOCKED_FROM = HELDOUT[0]
CASH_SPREAD = fv.CASH_SPREAD              # cash earns DTB3 - 0.50% a year
N_TRIALS = 22                             # 2 candidates + FLEET-V1's 19 (shared dial) + 1 amendment
SELECT = {"sharpe_margin": 0.15, "max_dd_floor": -0.25, "dd_vs_b": 0.6, "cagr_slack": 0.01, "tie": 0.005}
SIMPLICITY_ORDER = ["V1", "V2"]
PUT_DATASET = "vol_put_cboe_b"
PUT_SYMBOL = "PUT"
GATE_DATASET = "vol_gate_y"
GATE_SYMBOL, SPX_SYMBOL = "SPY", "^GSPC"
RATES_DATASET = "vol_rates_fred"
DATASETS = {"put": PUT_DATASET, "gate": GATE_DATASET, "rates": RATES_DATASET}


def _levels(rows: list[dict]) -> dict[date, float]:
    return {r["day"]: float(r["close"]) for r in rows}


def numbers(curve: Sequence[CurvePoint], a: date, b: date, dtb3: dict[date, float]) -> dict[str, float] | None:
    return fv.numbers(curve, a, b, dtb3)


def select(nums: dict[str, dict[str, float] | None], b: dict[str, float], put: dict[str, float]) -> dict[str, Any]:
    """The plan's rule: (a) Sharpe >= B's + 0.15; (b) max drawdown >= -25% and
    >= 0.6 x B's; (c) CAGR >= B's - 1 point; (d) Sharpe > PUT's. Among those that
    pass, the higher CAGR; ties within 0.5 point go to V1."""
    checks = {}
    for cid in SIMPLICITY_ORDER:
        n = nums.get(cid)
        if n is None:
            checks[cid] = {"no_data": False}
            continue
        checks[cid] = {
            "a_sharpe_ge_B_plus_0.15": n["sharpe"] >= b["sharpe"] + SELECT["sharpe_margin"],
            "b_max_dd_ge_-25%_and_0.6xB": (n["max_dd"] >= SELECT["max_dd_floor"]
                                          and n["max_dd"] >= SELECT["dd_vs_b"] * b["max_dd"]),
            "c_cagr_ge_B_minus_1pt": n["cagr"] >= b["cagr"] - SELECT["cagr_slack"],
            "d_sharpe_above_PUT": n["sharpe"] > put["sharpe"],
        }
    ok = [c for c in SIMPLICITY_ORDER if all(checks[c].values())]
    if not ok:
        return {"checks": checks, "qualified": [], "selected": None, "verdict": "VOL-V1 FAILED"}
    best = max(nums[c]["cagr"] for c in ok)
    pick = next(c for c in SIMPLICITY_ORDER if c in ok and nums[c]["cagr"] >= best - SELECT["tie"])
    return {"checks": checks, "qualified": ok, "selected": pick, "verdict": "SELECTED"}


def explore(put: dict[date, float], spy_tr: dict[date, float], spx: dict[date, float],
            dtb3: dict[date, float], *, window: tuple[date, date] = EXPLORE,
            f1_curve: Sequence[CurvePoint] | None = None) -> dict[str, Any]:
    """Every exploration figure the plan asks for. ``spy_tr``: the S&P 500 TR
    series the dial reads (FLEET-V1's spliced SPY); ``spx``: the S&P 500 price
    index (contract counts, V2's put losses); ``f1_curve``: FLEET-V1-F1 over
    the same window (control)."""
    a, b = window
    cash = fv.cash_rate(dtb3)
    days = sorted(put)
    # V2's cash leg is PUT's T-bill collateral (full DTB3), not the account's
    # idle-cash rate; the account rate applies to the (1 - N) part in model().
    rf = dict(zip(days, rf_daily_for(days, dtb3) or []))
    v2 = vol_v1.v2_levels(put, spx, rf)

    logs: dict[str, list] = {"V1": [], "V2": [], "N1": []}
    curves: dict[str, list[CurvePoint]] = {
        "V1": vol_v1.model(put, spy_tr, spx, cash, a, b, log=logs["V1"]),
        "V2": vol_v1.model(v2, spy_tr, spx, cash, a, b, log=logs["V2"]),
        "N1": vol_v1.model(spy_tr, spy_tr, spx, cash, a, b, option_costs=False, log=logs["N1"]),
        "PUT": vol_v1.model(put, spy_tr, spx, cash, a, b, ungated=True),
        "B": vol_v1.model(spy_tr, spy_tr, spx, cash, a, b, ungated=True),
    }
    if f1_curve:
        curves["F1"] = [p for p in f1_curve if a <= p[0] <= b]
    nums = {k: numbers(c, a, b, dtb3) for k, c in curves.items()}

    report: dict[str, Any] = {"window": [a.isoformat(), b.isoformat()], "candidates": {}, "controls": {}}
    for k, c in curves.items():
        s = metrics.summarize(c, [], start=a, end=b, rf_annual=dtb3)
        s["exact"] = nums[k]
        s["correlation_to_B"] = fv.corr_to(c, curves["B"], a, b) if k != "B" else 1.0
        s["worst_3y_vs_B"] = fv.worst_3y_vs(c, curves["B"], a, b) if k != "B" else None
        if k in logs:
            s["gate"] = vol_v1.gate_stats(logs[k], a, b)
        report["candidates" if k in SIMPLICITY_ORDER else "controls"][k] = s
    report["controls"]["B"]["note"] = "S&P 500 TR (FLEET-V1's spliced SPY) held, cash-free"
    report["controls"]["PUT"]["note"] = "CBOE PUT index ungated, no costs: what the gate adds"
    report["controls"]["N1"]["note"] = "S&P 500 TR held at the gate's N: is the premium worth more than the index"
    report["candidates"]["V2"]["note"] = ("estimate: PUT with 0.70 x premium and losses from 2% lower; "
                                          "judged live, not historically")

    if nums["B"] is None or nums["PUT"] is None:
        report["selection"] = {"verdict": "NO DATA", "selected": None}
        return report
    report["selection"] = select({c: nums[c] for c in SIMPLICITY_ORDER}, nums["B"], nums["PUT"])

    # Deflated Sharpe (information only in exploration; the pass bar uses the held-out window).
    series, per_sr = {}, []
    for cid in SIMPLICITY_ORDER:
        rets = metrics.daily_returns([p for p in curves[cid] if a <= p[0] <= b])
        series[cid] = ([x for _, x in rets], rf_daily_for([d for d, _ in rets], dtb3))
        per_sr.append(overfit.sharpe_per_period(*series[cid]))
    var_sr = overfit.variance(per_sr)
    report["deflated_sharpe_exploration"] = {
        cid: overfit.deflated_sharpe(*series[cid], n_trials=N_TRIALS, var_sharpe=var_sr) for cid in SIMPLICITY_ORDER}
    report["var_sharpe_across_candidates"] = var_sr
    return report


def run(store=None, *, log_path: Path | None = LOG_PATH) -> dict[str, Any]:
    from research_harness.harness.store import BarStore

    store = store or BarStore()
    hi = EXPLORE[1]
    try:
        put_rows = store.load(PUT_DATASET, PUT_SYMBOL, start=WARMUP_START, end=hi)
    except FileNotFoundError as exc:
        raise SystemExit(f"VOL-V1 STOPS: the CBOE PUT dataset is not pulled ({exc}). "
                         "The plan declares no fallback.") from exc
    for ds in (PUT_DATASET, GATE_DATASET, RATES_DATASET):
        if store.manifest(ds).get("locked_from") != LOCKED_FROM.isoformat():
            raise SystemExit(f"VOL-V1 STOPS: {ds} is not locked from {LOCKED_FROM} (plan Amendment 1)")
    spy_tr = _levels(store.load(GATE_DATASET, GATE_SYMBOL, start=date(2005, 1, 1), end=hi))
    spx = _levels(store.load(GATE_DATASET, SPX_SYMBOL, start=date(2005, 1, 1), end=hi))
    dtb3 = store.load_rates(RATES_DATASET, "DTB3", start=date(2005, 1, 1), end=hi)
    report = explore(_levels(put_rows), spy_tr, spx, dtb3)
    out = {"plan": PLAN_ID, "kind": "exploration (2007-07..2015-12, plan Amendment 1), one run",
           "data": {ds: store.manifest_hash(ds) for ds in DATASETS.values()},
           "costs": (f"{vol_v1.COST_BPS_PER_LEG:g} bp of notional per roll leg + ${vol_v1.CONTRACT_FEE} per "
                     "contract per leg (two legs a month); cash DTB3 - 0.50% (floored at 0); fractional contracts"),
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
    out = run(log_path=None if args.no_log else LOG_PATH)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
