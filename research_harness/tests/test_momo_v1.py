"""MOMO-V1 (plan: research_harness/explore/MOMO-V1-PLAN.md): sleeve, exploration
runner, data pull helpers and the declared exploration window. Synthetic data only."""

from __future__ import annotations

import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from research_harness import fetch  # noqa: E402
from research_harness.explore import momo_v1 as ex  # noqa: E402
from research_harness.harness import holdout  # noqa: E402
from research_harness.harness.holdout import HoldoutViolation  # noqa: E402
from research_harness.harness.portfolio import HistoryView, simulate  # noqa: E402
from research_harness.harness.store import BarStore  # noqa: E402
from research_harness.sleeves import core_v1  # noqa: E402
from research_harness.sleeves import momo_v1 as mv  # noqa: E402


def weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(date(2018, 1, 1), date(2020, 6, 30))


def path(n: int, seed: int, drift: float, vol: float = 0.01, start: float = 50.0) -> list[float]:
    rng = random.Random(seed)
    c = [start]
    for _ in range(n - 1):
        c.append(max(0.5, c[-1] * (1 + drift + vol * rng.gauss(0, 1))))
    return c


def bars(days, closes, volume=1e6):
    out, prev = [], None
    for d, c in zip(days, closes):
        o = prev or c
        out.append({"day": d, "open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": volume})
        prev = c
    return out


def make_panel(n_stocks=30, days=DAYS):
    stocks = {}
    for i in range(n_stocks):
        stocks[f"S{i:02d}"] = bars(days, path(len(days), i, drift=0.0002 * (i - 10)), volume=1e5 * (i + 1))
    return mv.Panel(stocks)


def make_etf(days=DAYS):
    etf = {s: bars(days, path(len(days), 100 + k, 0.0004, 0.008, 100.0)) for k, s in enumerate(ex.ETF_SYMBOLS)}
    return etf


# ── ranking and universe ──────────────────────────────────────────────────────
def test_momentum_12_1_skips_the_last_month():
    closes = [100.0] * 231 + [150.0] + [200.0] * 21          # 253 closes
    assert mv.momentum_12_1(closes) == pytest.approx(150.0 / 100.0 - 1)
    assert mv.momentum_12_1(closes[1:]) is None              # 252 closes: not enough


def test_universe_is_point_in_time_and_screens_price_history_and_listing():
    p = make_panel()
    d = DAYS[300]
    u = mv.universe_on(p, d, size=10)
    dv = {s: mv.dollar_volume(p.tail(s, d, mv.MIN_CLOSES)) for s in p.bars}
    assert u == sorted(dv, key=lambda s: -dv[s])[:10]                          # highest dollar volume first
    assert mv.dollar_volume(p.tail("S29", d, 60)) == pytest.approx(
        sum(b["close"] * b["volume"] for b in p.tail("S29", d, 60)) / 60)
    future = {s: [dict(b, close=b["close"] * (5 if b["day"] > d else 1), volume=b["volume"] * (100 if b["day"] > d and s == "S00" else 1))
                  for b in bs] for s, bs in p.bars.items()}
    assert mv.universe_on(mv.Panel(future), d, size=10) == u                     # later rows change nothing
    young = {"NEW": bars(DAYS[200:301], [10.0] * 101, 1e9)}
    assert "NEW" not in mv.universe_on(mv.Panel({**p.bars, **young}), d)         # < 253 closes
    cheap = {"PENNY": bars(DAYS[:301], [4.0] * 301, 1e12)}
    assert "PENNY" not in mv.universe_on(mv.Panel({**p.bars, **cheap}), d)       # under $5
    gone = {"GONE": bars(DAYS[:290], [60.0] * 290, 1e12)}
    assert "GONE" not in mv.universe_on(mv.Panel({**p.bars, **gone}), d)         # no bar on the signal day


def test_top_momentum_picks_the_20_strongest_and_selection_has_no_look_ahead():
    p = make_panel()
    d = DAYS[300]
    u = mv.universe_on(p, d)
    top = mv.top_momentum(p, d, u)
    assert len(top) == mv.TOP_N
    moms = {s: mv.momentum_12_1([b["close"] for b in p.upto(s, d)]) for s in u}
    assert min(moms[s] for s in top) >= max(moms[s] for s in u if s not in top)
    sig = mv.month_first_sessions(DAYS, date(2019, 2, 1), date(2019, 12, 31))
    sel = mv.monthly_selection(p, sig)
    cut = date(2019, 7, 1)
    shocked = mv.Panel({s: [dict(b, close=b["close"] * (0.2 if s in ("S29", "S28") and b["day"] >= cut else 1))
                            for b in bs] for s, bs in p.bars.items()})
    sel2 = mv.monthly_selection(shocked, sig)
    assert {d: v for d, v in sel.items() if d < cut} == {d: v for d, v in sel2.items() if d < cut}


# ── dial and weights ──────────────────────────────────────────────────────────
def test_dial_is_fleet_v1s_scaled_to_the_candidate():
    spy = [b["close"] for b in make_etf()["SPY"][:400]]
    v, e2 = mv.exposure(spy, 1.5)
    assert e2 == pytest.approx(core_v1.target_exposure(core_v1.votes(spy[-core_v1.NEED:]),
                                                       core_v1.vol20(spy[-core_v1.NEED:])))
    _, e1 = mv.exposure(spy, 1.0)
    assert e1 <= 1.0 and (e1 == 0 or e1 == pytest.approx(min(1.0, e2 / 1.5)) or e2 / 1.5 < 0.1)
    assert mv.exposure(spy[:200], 1.0) is None


@pytest.mark.parametrize("e,gear", [(0.0, False), (0.4, False), (1.0, False), (0.7, True), (1.2, True), (1.5, True)])
def test_book_weights_equal_weight_gross_at_most_one_and_gear_split(e, gear):
    names = [f"S{i:02d}" for i in range(20)]
    w = mv.book_weights(names, e, gear)
    assert sum(w.values()) <= 1.0 + 1e-12
    stocks = [w[s] for s in names if s in w]
    assert len(set(round(x, 12) for x in stocks)) <= 1                         # equal weight
    exposure = sum(stocks) + 2 * w.get(mv.GEAR, 0.0)
    assert exposure == pytest.approx(e * (0.99 if e > 1 else 1.0))
    if e <= 1:
        assert mv.GEAR not in w
    assert mv.book_weights(names[:15], 1.0, False) == {s: 1 / 20 for s in names[:15]}   # missing slots stay cash


# ── strategy behaviour ────────────────────────────────────────────────────────
def _calm_up_spy(days):
    return bars(days, [100 * 1.0006 ** i * (1 + 0.001 * (-1) ** i) for i in range(len(days))])


def test_events_only_at_month_start_or_vote_change_and_x18_ignores_votes():
    etf = make_etf()
    p = make_panel()
    sig = mv.month_first_sessions(DAYS, date(2019, 2, 1), date(2020, 6, 30))
    sel = mv.monthly_selection(p, sig)
    view = HistoryView({"SPY": etf["SPY"], **{s: p.bars[s] for s in ex.held_symbols(sel)}})
    for use_dial in (True, False):
        log: list = []
        strat = mv.make_strategy("M1", sel, log, use_dial=use_dial)
        events = []
        for d in DAYS:
            view.today = d
            if strat(d, view) is not None:
                events.append(d)
        rows = {r[0]: r for r in log}
        prev = None
        for d in sorted(rows):
            new_month = prev is None or (d.year, d.month) != (prev.year, prev.month)
            changed = use_dial and prev is not None and rows[d][1] != rows[prev][1]
            assert (d in events) == (new_month or changed), d
            prev = d
        if not use_dial:
            assert all(r[2] == 1.0 for r in log)


def test_a_stopped_name_stays_out_until_the_next_month_and_matches_the_simulator():
    days = weekdays(date(2018, 1, 1), date(2019, 8, 30))
    spy_closes = [100 * 1.0005 ** i for i in range(len(days))]
    crash_day = date(2019, 3, 12)
    turn_day = date(2019, 3, 20)
    # SPY: a dip that drops one vote mid-March (forces a resize), then recovers
    spy_closes = [c * (0.93 if turn_day <= d < date(2019, 3, 26) else 1.0) for c, d in zip(spy_closes, days)]
    stocks = {}
    for i in range(20):
        closes = [50 * 1.001 ** k for k in range(len(days))]
        if i == 0:
            closes = [c * (0.7 if d >= crash_day else 1.0) for c, d in zip(closes, days)]   # -30%: stop fires
        stocks[f"S{i:02d}"] = bars(days, closes)
    panel = mv.Panel(stocks)
    sel = {date(2019, 3, 1): sorted(stocks), date(2019, 4, 1): sorted(stocks)}
    etf = {"SPY": bars(days, spy_closes)}
    weights_seen: list = []
    strat = mv.make_strategy("M1", sel)

    def spy_strat(d, v):
        w = strat(d, v)
        if w is not None:
            weights_seen.append((d, dict(w)))
        return w

    res = simulate({"SPY": etf["SPY"], **stocks}, spy_strat, costs=ex.costs_for(list(stocks)),
                   rf_annual=None, start=date(2019, 2, 1), end=date(2019, 4, 30), stop_pct=mv.STOP_PCT)
    assert res.stops_hit >= 1
    stopped_exit = [t for t in res.trades if t["symbol"] == "S00" and t["exit"] == "stop"]
    assert stopped_exit and stopped_exit[0]["close"] == crash_day
    mid = [w for d, w in weights_seen if date(2019, 3, 2) <= d < date(2019, 4, 1)]
    assert mid, "the SPY dip should cause a mid-month resize"
    assert all("S00" not in w for w in mid)                                    # not re-bought after its stop
    april = [w for d, w in weights_seen if d >= date(2019, 4, 1)]
    assert april and "S00" in april[0]                                         # back at the next ranking


# ── selection and pass bar ────────────────────────────────────────────────────
def test_selection_rule():
    b = {"cagr": 0.10, "sharpe": 0.6, "max_dd": -0.34}
    nums = {"M1": {"cagr": 0.125, "sharpe": 0.8, "max_dd": -0.22},
            "M2": {"cagr": 0.13, "sharpe": 0.82, "max_dd": -0.24}}
    r = ex.select(nums, b, x18_sharpe=0.7, r_p95=0.75)
    assert r["selected"] == "M1"                                     # M2 within 1 point: the simpler one
    nums["M2"]["cagr"] = 0.15
    assert ex.select(nums, b, 0.7, 0.75)["selected"] == "M2"
    nums["M2"]["max_dd"] = -0.26                                     # breaks the -25% floor
    assert ex.select(nums, b, 0.7, 0.75)["selected"] == "M1"
    assert ex.select(nums, b, 0.9, 0.75)["verdict"] == "FAILED"     # dial lost the premium vs X18
    assert ex.select(nums, {**b, "max_dd": -0.20}, 0.7, 0.75)["verdict"] == "FAILED"   # not 0.75 x B's fall


def test_pass_bar():
    b = {"cagr": 0.10, "sharpe": 0.6, "max_dd": -0.30}
    good = {"cagr": 0.13, "sharpe": 0.9, "max_dd": -0.20}
    assert ex.pass_bar(good, b, 0.93)["verdict"] == "PASS"
    out = ex.pass_bar({**good, "cagr": 0.11}, b, 0.80)
    assert out["failed"] == ["1_cagr_ge_B_plus_2pts", "3_deflated_sharpe_gt_0.90"]


# ── declared exploration window ───────────────────────────────────────────────
def test_declared_exploration_window_is_the_plans_and_nothing_else():
    holdout.check_window(date(2024, 12, 31), None, plan="MOMO-V1")
    with pytest.raises(HoldoutViolation, match="declared exploration end"):
        holdout.check_window(date(2025, 1, 2), None, plan="MOMO-V1")
    with pytest.raises(HoldoutViolation, match="declares no exploration window"):
        holdout.check_window(date(2022, 1, 3), None, plan="FLEET-V1")
    with pytest.raises(HoldoutViolation):
        holdout.check_window(date(2022, 1, 3), None)                     # legacy lock unchanged
    text = (ROOT / "research_harness" / "explore" / "MOMO-V1-PLAN.md").read_text()
    assert "Exploration 2019-02-01..2024-12-31" in text
    assert holdout.DECLARED_EXPLORATION_END == {"MOMO-V1": date(2024, 12, 31)}
    assert ex.EXPLORE[1] == holdout.DECLARED_EXPLORATION_END["MOMO-V1"]
    assert ex.LOCKED_FROM == date(2025, 1, 1)


def test_load_never_reads_locked_rows(tmp_path):
    store = BarStore(tmp_path)
    d1 = weekdays(date(2024, 12, 1), date(2024, 12, 31))
    d2 = weekdays(date(2025, 1, 1), date(2025, 1, 31))
    store.write_dataset("p", source="t", bars_by_symbol={"A": bars(d1, [10.0] * len(d1))},
                        fields=fetch.PANEL_FIELDS, locked_from=ex.LOCKED_FROM)
    store.write_dataset("p", source="t", bars_by_symbol={"A": bars(d2, [11.0] * len(d2))},
                        fields=fetch.PANEL_FIELDS, locked=True)
    rows = store.load("p", "A", start=date(2024, 1, 1), end=date(2024, 12, 31), plan="MOMO-V1")
    assert rows[-1]["day"] == date(2024, 12, 31)
    with pytest.raises(HoldoutViolation):
        store.load("p", "A", start=date(2024, 1, 1), end=date(2025, 1, 31), plan="MOMO-V1")


# ── data pull helpers ─────────────────────────────────────────────────────────
def test_panel_pruning_keeps_every_monthly_universe_exactly():
    p = make_panel(40)
    keep = fetch.panel_symbols_to_keep(p.bars, date(2019, 2, 1), date(2020, 6, 30))
    pruned = mv.Panel({s: p.bars[s] for s in keep})
    for d in mv.month_first_sessions(DAYS, date(2019, 2, 1), date(2020, 6, 30)):
        assert mv.universe_on(pruned, d, size=15) == mv.universe_on(p, d, size=15)


def test_split_panel_gives_a_2025_ipo_an_empty_open_file():
    d = weekdays(date(2024, 12, 1), date(2025, 2, 28))
    data = {"OLD": bars(d, [10.0] * len(d)), "IPO": bars([x for x in d if x.year == 2025], [20.0] * 41)}
    open_part, locked_part = fetch.split_panel(data, {"OLD", "IPO"}, date(2025, 1, 1))
    assert open_part["IPO"] == [] and locked_part["IPO"]
    assert all(b["day"] < date(2025, 1, 1) for b in open_part["OLD"])
    assert all(b["day"] >= date(2025, 1, 1) for b in locked_part["OLD"])


# ── runner ────────────────────────────────────────────────────────────────────
def test_exploration_runs_end_to_end_on_synthetic_data():
    p = make_panel(40)
    etf = make_etf()
    dtb3 = {DAYS[0]: 0.02}
    out = ex.explore(p, etf, dtb3, window=(date(2019, 2, 1), date(2020, 6, 30)), r_draws=3)
    assert set(out["candidates"]) == {"M1", "M2"}
    assert set(out["controls"]) == {"B", "X18", "F1", "R"}
    assert out["selection"]["verdict"] in ("SELECTED", "FAILED")
    assert out["controls"]["R"]["draws"] == 3
    for k in ("M1", "M2"):
        assert out["candidates"][k]["max_gross_leverage"] <= 1.0 + 1e-6
        assert out["candidates"][k]["exposure"]["exposure_max"] <= mv.CANDIDATES[k]["max_exposure"] + 1e-9
    assert out["universe"]["names_ever_held"] >= mv.TOP_N
    assert math.isfinite(out["deflated_sharpe_exploration"]["M1"]["dsr"])


def test_momo_candidates_needs_an_explicit_delisted_choice(monkeypatch):
    tp = ROOT / "trading-platform"
    monkeypatch.syspath_prepend(str(tp))
    pytest.importorskip("loguru")              # core.equity_universe's dependency; on Replit
    records = [{"symbol": "LIVE", "asset_class": "us_equity", "status": "active", "tradable": True,
                "exchange": "NYSE", "name": "Live Corp Common Stock"},
               {"symbol": "DEAD", "asset_class": "us_equity", "status": "inactive", "tradable": False,
                "exchange": "OTC", "name": "Dead Corp Common Stock"}]
    assert fetch.momo_candidates(records, "exclude") == {"LIVE"}
    assert fetch.momo_candidates(records, "include") == {"LIVE", "DEAD"}
    with pytest.raises(ValueError):
        fetch.momo_candidates(records, "maybe")
