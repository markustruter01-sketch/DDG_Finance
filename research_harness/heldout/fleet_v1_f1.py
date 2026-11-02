"""FLEET-V1-F1: the ONE held-out test of the registered fleet candidate.

Registration: research_harness/registrations/FLEET-V1-F1.json. F1 is the
65% geared equity trend core (sleeve 1, cid C1) plus 35% long-only
cross-asset trend (sleeve 2), combined daily by harness.fleet.fleet_curve,
exactly as explored in research_harness/explore/fleet_v1.py, with whole
shares (the 2011-2020 window is real ETFs throughout).

It runs ONCE. registry.begin_locked_run writes a start marker before any
locked row is read, so a second start is refused even if the first crashed;
a fail is reported as a fail. The test window is 2011-01-01..2020-12-31;
2021-01-01..2026-10-31 was spent by earlier tests and is reported for
information only, never with a verdict. Bars before 2011 are warm-up and the
signal history.

It must run where the locked data lives (the DDG - Finance Replit): the
locked parts of fleet_idx_y, fleet_etf_y, fleet_rates_fred and fleet_shiller
are not in this repository.

    QT_RESEARCH_DATA=research_harness/data python -m research_harness.heldout.fleet_v1_f1
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from research_harness.explore import fleet_v1 as fv
from research_harness.harness import metrics, overfit, registry
from research_harness.harness.fleet import fleet_curve
from research_harness.harness.metrics import rf_daily_for
from research_harness.recon import reconstruct as rc
from research_harness.sleeves import core_v1, xasset_v1

REG_ID = "FLEET-V1-F1"
LOAD_START = date(1985, 1, 1)
SIM_START = fv.WARMUP_START                     # 1985-10-01
END = date(2026, 10, 31)
TEST = (date(2011, 1, 1), date(2020, 12, 31))
SPENT = (date(2021, 1, 1), END)
SHARPE_MARGIN = 0.10
MAX_DD_FLOOR = -0.25
DSR_MIN = 0.95
ROLLING_TEXT = "13 of 15"                       # from the registration's pass bar item 5
ROOT = Path(__file__).resolve().parents[2]


def evaluate_pass_bar(f1: dict[str, float], b: dict[str, float], dsr: float,
                      rolling_met: bool = True) -> dict[str, Any]:
    """The registered pass bar on one window. f1/b: fleet_v1.numbers() dicts
    (cagr, sharpe excess DTB3, max_dd as a negative fraction); dsr: deflated
    Sharpe probability."""
    items = {
        "1_cagr_ge_B": f1["cagr"] >= b["cagr"],
        "2_sharpe_ge_B_plus_0.10": f1["sharpe"] >= b["sharpe"] + SHARPE_MARGIN,
        "3_max_dd_ge_-25%_and_smaller_than_B": f1["max_dd"] >= MAX_DD_FLOOR and f1["max_dd"] > b["max_dd"],
        "4_deflated_sharpe_gt_0.95": dsr > DSR_MIN,
        f"5_rolling_met_in_exploration_({ROLLING_TEXT})": bool(rolling_met),
    }
    failed = [k for k, ok in items.items() if not ok]
    return {"items": items, "failed": failed, "all_met": not failed}


def _window_report(a: date, b: date, res: dict, curves: dict, logs: dict, dtb3: dict,
                   var_sharpe: float) -> dict[str, Any]:
    nums = {k: fv.numbers(c, a, b, dtb3) for k, c in curves.items()}
    out: dict[str, Any] = {"window": [a.isoformat(), b.isoformat()], "series": {}}
    for k in ("F1", "C1", "S2", "B"):
        r = res.get(k)
        trades = r.trades if r is not None else []
        s = metrics.summarize(curves[k], trades, start=a, end=b, rf_annual=dtb3,
                              cost_label=r.cost_label if r is not None else None)
        s["exact"] = nums[k]
        s["correlation_to_B"] = fv.corr_to(curves[k], curves["B"], a, b) if k != "B" else 1.0
        s["worst_3y_vs_B"] = fv.worst_3y_vs(curves[k], curves["B"], a, b) if k != "B" else None
        if r is not None:
            s["stops_hit"] = sum(1 for t in r.trades if t.get("exit") == "stop" and a <= t["close"] <= b)
        out["series"][k] = s
    out["series"]["C1"]["signal"] = core_v1.core_stats(logs["C1"], a, b)
    out["series"]["S2"]["signal"] = xasset_v1.xasset_stats(logs["S2"], a, b)
    out["series"]["F1"]["stops_hit"] = out["series"]["C1"]["stops_hit"] + out["series"]["S2"]["stops_hit"]

    pts = [p for p in curves["F1"] if a <= p[0] <= b]
    rets = metrics.daily_returns(pts)
    dsr = overfit.deflated_sharpe([x for _, x in rets], rf_daily_for([d for d, _ in rets], dtb3),
                                  n_trials=fv.N_TRIALS, var_sharpe=var_sharpe)
    out["deflated_sharpe_F1"] = dsr
    out["pass_bar"] = evaluate_pass_bar(nums["F1"], nums["B"], dsr["dsr"], rolling_met=True)
    return out


def heldout(instr: dict[str, list[dict]], dtb3: dict[date, float], var_sharpe: float, *,
            grant=None, sim_start: date = SIM_START, end: date = END,
            test: tuple[date, date] = TEST, spent: tuple[date, date] = SPENT) -> dict[str, Any]:
    """Simulate C1, S2, F1 and B and report the test and spent windows."""
    rf_cash = fv.cash_rate(dtb3)
    ws = fv.HELDOUT_WHOLE_SHARES
    res, logs = {}, {}
    res["C1"], logs["C1"] = fv.run_core(instr, "C1", rf_cash, sim_start, end, whole_shares=ws, grant=grant)
    res["S2"], logs["S2"] = fv.run_xasset(instr, rf_cash, sim_start, end, whole_shares=ws, grant=grant)
    res["B"] = fv.run_hold(instr, rf_cash, sim_start, end, whole_shares=ws, grant=grant)
    curves = {k: v.curve for k, v in res.items()}
    curves["F1"] = fleet_curve({"core": curves["C1"], "xasset": curves["S2"]}, fv.FLEET_WEIGHTS)

    t = _window_report(*test, res, curves, logs, dtb3, var_sharpe)
    s = _window_report(*spent, res, curves, logs, dtb3, var_sharpe)
    s["label"] = "information only, spent"
    s["pass_bar"]["note"] = "computed for information only; no verdict on a spent window"
    pb = t["pass_bar"]
    verdict = "PASS" if pb["all_met"] else "FAIL: " + ", ".join(pb["failed"])
    return {
        "test": t,
        "spent_information_only": s,
        "whole_simulation": {
            k: {"from": sim_start.isoformat(), "to": end.isoformat(), "fills": r.fills,
                "traded_notional": r.traded_notional, "costs_paid": r.costs_paid,
                "cash_interest": r.cash_interest, "stops_hit": r.stops_hit}
            for k, r in res.items()},
        "verdict": verdict,
    }


def run(store=None, *, directory: Path = registry.REGISTRATIONS_DIR, ledger: Path = registry.LEDGER_PATH,
        run_starts: Path = registry.RUN_STARTS_PATH, record: bool = True) -> dict[str, Any]:
    from research_harness.harness.store import BarStore

    store = store or BarStore()
    # Checks that read no locked row, before the single-use start is spent.
    pre = registry.load_registration(REG_ID, directory)
    if sorted(pre["universe"]) != sorted(fv.UNIVERSE["F1"]):
        raise RuntimeError("universe differs from the registration; refusing to run")
    if ROLLING_TEXT not in pre["pass_bar"]:
        raise RuntimeError("registration pass bar does not record the exploration rolling result")
    for ds in fv.DATASETS.values():
        if store.manifest_hash(ds) != pre["data"][ds]:
            raise RuntimeError(f"{ds} does not match the pinned manifest hash; refusing to run")

    reg, grant = registry.begin_locked_run(REG_ID, "holdout_test", directory=directory,
                                           ledger=ledger, run_starts=run_starts)
    D = fv.DATASETS
    kw = dict(start=LOAD_START, end=END, grant=grant)
    idx = {s: store.load(D["index"], s, **kw) for s in rc.INDEX.values()}
    etfs = {s: store.load(D["etf"], s, **kw) for s in rc.REAL_ETF}
    rates = {s: store.load_rates(D["rates"], s, **kw) for s in ("DTB3", "DGS10")}
    shiller = store.load(D["shiller"], "SP500", **kw)
    instr = rc.build(idx, etfs, rates, shiller)["instruments"]

    body = heldout(instr, rates["DTB3"], reg["exploration_var_sharpe_per_period"], grant=grant)
    result = {"registration": REG_ID, "candidate": "F1",
              "costs": fv.COSTS.label() + "; cash earns DTB3 - 0.50% (floored at 0); whole shares",
              "rolling_check_from_exploration": {"met": True, "detail": ROLLING_TEXT},
              **body}
    hashes: dict[str, str] = {}
    for ds in D.values():
        hashes[ds] = store.manifest_hash(ds)
        hashes[f"{ds}/_locked"] = store.locked_manifest_hash(ds)
    result["data_manifests"] = hashes
    if record:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                    text=True, cwd=ROOT).stdout.strip() or None
        except OSError:
            commit = None
        registry.record_run(reg, "holdout_test", result, data_manifest_hashes=hashes,
                            code_commit=commit, ledger=ledger, grant=grant)
    return result


def main() -> int:
    out = run()
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / "FLEET-V1-F1-HELDOUT.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
