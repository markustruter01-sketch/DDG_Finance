"""GEAR-V1 sleeve, exploration and held-out scripts (synthetic data only)."""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta

import pytest

from research_harness.harness.portfolio import HistoryView
from research_harness.harness.store import BarStore
from research_harness.sleeves import gear as g


def _days(n, start=date(1998, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(days, drift, vol, seed, start_px=100.0):
    rng, px, out = random.Random(seed), start_px, []
    for d in days:
        o = px
        px *= math.exp(drift + rng.gauss(0, vol))
        out.append({"day": d, "open": o, "high": max(o, px) * 1.001, "low": min(o, px) * 0.999, "close": px})
    return out


def test_gear_rules():
    assert g.gear_for([100.0] * 150) is None                         # not enough history
    calm_up = [100 * 1.0005 ** i for i in range(260)]                # rising, ~0 vol
    assert g.gear_for(calm_up) == "aggressive"
    rng = random.Random(1)
    choppy_up, px = [], 100.0
    for i in range(260):                                             # rising but ~32% vol
        px *= 1.002 * (1 + rng.choice((-0.02, 0.02)))
        choppy_up.append(px)
    choppy_up[-1] = max(choppy_up[-1], 1.2 * sum(choppy_up[-200:]) / 200)
    assert g.gear_for(choppy_up) == "normal"
    falling = [100 * 0.999 ** i for i in range(260)]
    assert g.gear_for(falling) == "safe"


def test_exposure_and_candidates_stay_unlevered_at_account_level():
    assert g.exposure(g.CANDIDATES["G2"]["aggressive"]) == 1.5
    assert g.exposure(g.CANDIDATES["G3"]["aggressive"]) == 1.25
    assert g.exposure(g.CANDIDATES["G4"]["aggressive"]) == 1.5
    for mixes in g.CANDIDATES.values():
        for w in mixes.values():
            assert abs(sum(w.values()) - 1.0) < 1e-9                 # account gross 1.0


def test_trades_only_on_gear_change_or_new_month():
    days = _days(320)
    spy = _series(days, 0.0008, 0.002, 3)
    view = HistoryView({"SPY": spy})
    strat = g.make_strategy("G2")
    calls = []
    for d in days:
        view.today = d
        w = strat(d, view)
        if w is not None:
            calls.append((d, w))
    # first signal day, then only month starts (calm uptrend never changes gear)
    assert all(w == g.CANDIDATES["G2"]["aggressive"] for _, w in calls)
    assert len(calls) == len({(d.year, d.month) for d, _ in calls})


def test_g1_has_two_gears_only():
    days = _days(320)
    view = HistoryView({"SPY": _series(days, 0.0008, 0.002, 3)})
    log = []
    strat = g.make_strategy("G1", log)
    for d in days:
        view.today = d
        strat(d, view)
    assert {x for _, x in log} <= {"normal", "safe"}


def _datasets(tmp_path, end=date(2026, 10, 15)):
    store = BarStore(tmp_path / "data")
    days = [d for d in _days(8000) if d <= end]
    etf = {"SPY": _series(days, 0.0003, 0.011, 1), "QQQ": _series(days, 0.0004, 0.014, 2)}
    lev_days = [d for d in days if d >= date(2006, 6, 21)]
    etf["SSO"] = _series(lev_days, 0.0005, 0.022, 3, 30.0)
    etf["QLD"] = _series(lev_days, 0.0006, 0.028, 4, 30.0)
    store.write_dataset("gear_t", source="synthetic", bars_by_symbol=etf)
    trend = {s: _series(days, 0.0002, 0.01, 10 + i) for i, s in enumerate(
        ["SPY", "IWM", "EFA", "EEM", "VNQ", "TLT", "IEF", "LQD", "TIP", "GLD", "DBC"])}
    store.write_dataset("etf_t", source="synthetic", bars_by_symbol=trend)
    store.write_dataset("fred_t", source="synthetic", fields=("day", "rate"), positive_fields=(),
                        bars_by_symbol={"DTB3": [{"day": date(1998, 1, 1), "rate": 0.02}]})
    return store


def test_exploration_runs_four_candidates_and_logs_once(tmp_path):
    from research_harness.explore import gear_v1
    store = _datasets(tmp_path, end=date(2020, 12, 31))
    log = tmp_path / "log.jsonl"
    out = gear_v1.run("gear_t", "fred_t", store, log_path=log)
    assert set(out["candidates"]) == {"G1", "G2", "G3", "G4"}
    assert out["window"] == ["2007-01-01", "2020-12-31"]
    for c in out["candidates"].values():
        s = c["summary"]
        assert s["to"] <= "2020-12-31" and s["max_gross_leverage"] <= 1.0001
        assert set(s["gears"]["time_in_gear_pct"]) == {"aggressive", "normal", "safe"}
    assert out["chosen_for_registration"] in {"G1", "G2", "G3", "G4", None}
    assert log.read_text().count("GEAR-V1") == 1


def test_choose_rule():
    from research_harness.explore.gear_v1 import choose

    def c(cagr, dd):
        return {"summary": {"cagr_pct": cagr, "max_drawdown_pct": dd}}
    assert choose({"G1": c(9, -15), "G2": c(14, -25), "G3": c(12, -18), "G4": c(13, -19)}, 10) == "G4"
    assert choose({"G1": c(11, -15), "G2": c(11, -15), "G3": c(11, -15), "G4": c(9, -10)}, 10) == "G1"
    assert choose({"G1": c(9, -15), "G2": c(14, -25)}, 10) is None


def test_heldout_runs_once_and_reports_the_bars(tmp_path, monkeypatch):
    from research_harness.harness.registry import RegistrationError
    from research_harness.heldout import gear_v1 as hg
    import research_harness.harness.registry as rg

    store = _datasets(tmp_path)
    regs = tmp_path / "regs"
    regs.mkdir()
    reg = {"id": "GEAR-V1-T", "registered_at": "test", "hypothesis": "h", "candidate": "G3",
           "candidate_id": "G3", "candidates_declared": 4, "prior_variants_tried": "10",
           "universe": ["SPY", "SSO"], "window": "w", "sizing": "s", "leverage": "2x ETF",
           "costs": "c", "pass_bar": "p",
           "data": {d: store.manifest_hash(d) for d in ("gear_t", "etf_t", "fred_t")}}
    (regs / "GEAR-V1-T.json").write_text(json.dumps(reg))
    real = rg.load_registration
    monkeypatch.setattr(rg, "load_registration", lambda reg_id, directory=regs: real(reg_id, regs))
    ledger = tmp_path / "ledger.jsonl"
    out = hg.run("GEAR-V1-T", store, directory=regs, ledger=ledger)
    assert set(out["pass_bar"]) >= {"1_cagr_beats_spy", "2_cagr_at_least_10.5pct",
                                    "3_max_drawdown_no_worse_than_-20pct"}
    assert out["verdict"].startswith(("PASS", "FAIL"))
    assert out["summary"]["from"] >= "2021-01-01" and out["summary"]["to"] <= "2026-10-15"
    with pytest.raises(RegistrationError):
        hg.run("GEAR-V1-T", store, directory=regs, ledger=ledger)
