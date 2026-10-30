"""GEAR-V2: safe-gear engines, the long/short trend, selection rules and the
fund curve (synthetic data only; no real dataset is read)."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from research_harness.explore import gear_v2 as ex
from research_harness.harness.costs import CostModel
from research_harness.harness.fleet import fleet_curve
from research_harness.harness.holdout import EXPLORE_END
from research_harness.harness.portfolio import HistoryView, simulate
from research_harness.sleeves import gear as g
from research_harness.sleeves import gear_v2 as v2
from research_harness.sleeves.trend import TrendParams, target_weights

FREE = CostModel(0, 0, 0, 0, 0)


def _days(n, start=date(2000, 1, 3)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(days, drift, vol, seed, px=100.0):
    rng, out = random.Random(seed), []
    for d in days:
        o = px
        px *= math.exp(drift + rng.gauss(0, vol))
        out.append({"day": d, "open": o, "high": max(o, px) * 1.001, "low": min(o, px) * 0.999, "close": px})
    return out


def _view(bars, day):
    v = HistoryView(bars)
    v.today = day
    return v


def test_long_short_trend_shorts_off_etfs_and_default_is_unchanged():
    days = _days(300)
    bars = {"UP": _series(days, 0.002, 0.005, 1), "DOWN": _series(days, -0.002, 0.005, 2)}
    view = _view(bars, days[-1])
    long_only = target_weights(view, ["UP", "DOWN"], TrendParams(rule="sma_210", max_weight=1.0))
    ls = target_weights(view, ["UP", "DOWN"], TrendParams(rule="sma_210", max_weight=1.0, short_when_off=True))
    assert set(long_only) == {"UP"}                                  # TREND-V1-B behaviour unchanged
    assert ls["UP"] == pytest.approx(long_only["UP"])
    assert ls["DOWN"] < 0                                            # off -> short, same sizing rule
    assert sum(abs(w) for w in ls.values()) <= 1.0 + 1e-9


def test_registered_g4_safe_gear_is_still_t_bills():
    days = _days(320)
    falling = {"SPY": _series(days, -0.003, 0.002, 3)}
    strat = g.make_strategy("G4")
    out = [strat(d, _view(falling, d)) for d in days]
    assert {} in out and all(w in (None, {}) for w in out)           # safe gear: empty weights


def test_safe_callable_fills_the_safe_gear_only():
    days = _days(320)
    falling = {"SPY": _series(days, -0.003, 0.002, 3), "GLD": _series(days, 0, 0.01, 4),
               "IEF": _series(days, 0, 0.003, 5)}
    strat = v2.make_strategy("A1")
    out = [w for w in (strat(d, _view(falling, d)) for d in days) if w is not None]
    assert out and all(w == {"GLD": 0.5, "IEF": 0.5} for w in out)
    rising = {"SPY": [dict(b, close=100 * 1.0005 ** i, open=100 * 1.0005 ** i)
                      for i, b in enumerate(_series(days, 0, 0, 6))]}
    up = [w for w in (v2.make_strategy("A1")(d, _view(rising, d)) for d in days) if w is not None]
    assert up and all(w == g.CANDIDATES["G4"]["aggressive"] for w in up)


def test_engine_weights():
    days = _days(300)
    bars = {s: _series(days, 0.0005, 0.01, i) for i, s in enumerate(v2.TREND_UNIVERSE)}
    view = _view(bars, days[-1])
    assert v2.engine_weights("A0", view) == {}
    assert v2.engine_weights("A1", view) == {"GLD": 0.5, "IEF": 0.5}
    assert v2.engine_weights("A2", view) == {}                       # no DBMF data -> T-bills
    bars["DBMF"] = _series(days[-5:], 0, 0.01, 99)
    assert v2.engine_weights("A2", _view(bars, days[-1])) == {"DBMF": 1.0}
    assert v2.engine_weights("A2", _view(bars, days[-10])) == {}     # before its first bar
    a3 = v2.engine_weights("A3", view)
    assert len(a3) == len(v2.TREND_UNIVERSE)                          # every eligible ETF long or short
    assert sum(abs(w) for w in a3.values()) <= 1.0 + 1e-9
    with pytest.raises(ValueError):
        v2.engine_weights("A9", view)


def test_short_leg_carries_a_buy_stop_above():
    days = _days(40)
    bars = {"X": _series(days, 0, 0.001, 7)}
    for b in bars["X"][20:]:
        b["high"] = b["open"] * 1.30                                  # trades through +20%
    res = simulate(bars, lambda d, v: {"X": -0.5}, costs=FREE, rf_annual=None, start=days[0],
                   end=EXPLORE_END, allow_short=True, stop_pct=0.20)
    assert res.stops_hit >= 1 and res.trades[0]["exit"] == "stop"


def test_choose_part_a():
    s = lambda c, dd: {"cagr_pct": c, "max_drawdown_pct": dd}
    assert ex.choose_part_a({"A0": s(11.7, -32.1), "A1": s(12, -30), "A3": s(13, -31)}) == "A3"
    assert ex.choose_part_a({"A0": s(11.7, -32.1), "A1": s(12, -30), "A3": s(13, -33)}) == "A1"
    assert ex.choose_part_a({"A0": s(11.7, -32.1), "A1": s(11, -20), "A3": s(13, -40)}) == "A0"
    assert ex.choose_part_a({"A0": s(11.7, -32.1), "A1": s(13, -30), "A3": s(13, -25)}) == "A1"


def test_choose_part_b():
    passing, failing = {"passes": True}, {"passes": False}
    assert ex.choose_part_b(passing, {"max_drawdown_pct": -30}, {"max_drawdown_pct": -25}) == "B1"
    assert ex.choose_part_b(passing, {"max_drawdown_pct": -30}, {"max_drawdown_pct": -30}) == "B0"
    assert ex.choose_part_b(failing, {"max_drawdown_pct": -30}, {"max_drawdown_pct": -10}) == "B0"


def test_fleet_curve_rebalances_daily():
    d = _days(3)
    a = [(d[0], 100.0, 1.0), (d[1], 110.0, 1.0), (d[2], 99.0, 1.0)]     # +10%, -10%
    b = [(d[0], 50.0, 0.0), (d[1], 50.0, 0.0), (d[2], 50.0, 0.0)]       # flat
    c = fleet_curve({"a": a, "b": b}, {"a": 0.75, "b": 0.25}, start_equity=1000.0)
    assert [p[1] for p in c] == pytest.approx([1000.0, 1075.0, 1075.0 * 0.925])
    assert [p[2] for p in c] == pytest.approx([0.75, 0.75, 0.75])


def test_safe_gear_stats_counts_sessions_held_under_a_safe_decision():
    d = _days(4)
    curve = [(d[0], 100.0, 0), (d[1], 110.0, 0), (d[2], 99.0, 0), (d[3], 99.0, 0)]
    log = [(d[0], "safe"), (d[1], "aggressive"), (d[2], "safe")]
    st = ex.safe_gear_stats(curve, log)
    assert st["sessions"] == 2 and st["compounded_return_pct"] == pytest.approx(10.0)


def test_a0_reproduction_check():
    assert ex.a0_reproduces({"cagr_pct": 11.70, "max_drawdown_pct": -32.10})
    assert not ex.a0_reproduces({"cagr_pct": 11.71, "max_drawdown_pct": -32.10})


def test_pinned_hash_mismatch_stops_the_run(tmp_path):
    from research_harness.harness.store import BarStore
    store = BarStore(tmp_path)
    for name, _ in (ex.GEAR_DATASET, ex.ENGINE_DATASET, ex.RATES_DATASET):
        store.write_dataset(name, source="test", bars_by_symbol={"SPY": _series(_days(5), 0, 0.01, 1)})
    with pytest.raises(ex.PinnedDataError):
        ex.load_bars(store, EXPLORE_END)


def _synthetic_store(tmp_path):
    """Datasets with the plan's names but synthetic prices (2003..2026-10-15)."""
    from research_harness.harness.store import BarStore
    store = BarStore(tmp_path / "data")
    days = [d for d in _days(6300, date(2003, 1, 6)) if d <= date(2026, 10, 15)]
    seed = iter(range(100, 200))
    store.write_dataset(ex.GEAR_DATASET[0], source="t", bars_by_symbol={
        s: _series(days, 0.0003, 0.012, next(seed)) for s in ex.GEAR_SYMBOLS})
    store.write_dataset(ex.ENGINE_DATASET[0], source="t", bars_by_symbol={
        s: _series(days, 0.0001, 0.008, next(seed)) for s in ex.ENGINE_SYMBOLS})
    store.write_dataset(ex.RATES_DATASET[0], source="t", fields=("day", "rate"), positive_fields=(),
                        bars_by_symbol={"DTB3": [{"day": d, "rate": 0.02} for d in days]})
    store.write_dataset("dbmf_t", source="t", bars_by_symbol={
        "DBMF": _series([d for d in days if d >= date(2019, 5, 8)], 0.0001, 0.008, 7)})
    return store


def test_heldout_runs_once_end_to_end(tmp_path, monkeypatch):
    import json
    import research_harness.harness.registry as rg
    from research_harness.harness.registry import RegistrationError
    from research_harness.heldout import gear_v2 as hv

    store = _synthetic_store(tmp_path)
    pins = {n: (ds[0], store.manifest_hash(ds[0])) for n, ds in
            (("GEAR_DATASET", ex.GEAR_DATASET), ("ENGINE_DATASET", ex.ENGINE_DATASET),
             ("RATES_DATASET", ex.RATES_DATASET))}
    for mod in (ex, hv):
        for n, v in pins.items():
            monkeypatch.setattr(mod, n, v)
    regs = tmp_path / "regs"
    regs.mkdir()
    reg = {"id": "GEAR-V2-T", "registered_at": "t", "hypothesis": "h", "candidate": "c",
           "candidates_declared": 4, "prior_variants_tried": "15", "universe": [], "window": "w",
           "sizing": "s", "leverage": "l", "costs": "c", "pass_bar": "p",
           "part_a": "A0", "part_b": "B1", "data": dict(pins.values())}
    (regs / "GEAR-V2-T.json").write_text(json.dumps(reg))
    real = rg.load_registration
    monkeypatch.setattr(rg, "load_registration", lambda reg_id, directory=regs: real(reg_id, regs))
    ledger = tmp_path / "ledger.jsonl"
    out = hv.run("GEAR-V2-T", store, dbmf_dataset="dbmf_t", directory=regs, ledger=ledger)
    assert set(out["pass_bar"]) == {"1_cagr_beats_spy", "2_cagr_at_least_12.5pct",
                                    "3_max_drawdown_smaller_than_spy",
                                    "4_sharpe_excess_tbill_above_spy", "5_slice_correlation_below_0_5"}
    assert out["verdict"].startswith(("PASS", "FAIL"))
    assert out["fund"]["from"] >= "2021-01-01" and out["fund"]["to"] <= "2026-10-15"
    assert isinstance(out["information_only"]["A2_dbmf_safe_gear"], dict)
    entry = json.loads(ledger.read_text().splitlines()[0])
    assert "dbmf_t" in entry["data_manifests"]
    with pytest.raises(RegistrationError):
        hv.run("GEAR-V2-T", store, directory=regs, ledger=ledger)
