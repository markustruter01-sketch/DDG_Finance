"""Tests for the shared backtest harness (research/harness)."""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "kraken-bot"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

from research_harness.harness import fleet, metrics, registry  # noqa: E402
from research_harness.harness.costs import CostModel  # noqa: E402
from research_harness.harness.holdout import EXPLORE_END, HOLDOUT_START, HoldoutViolation, check_window  # noqa: E402
from research_harness.harness.portfolio import StrategyError, simulate  # noqa: E402
from research_harness.harness.store import BarStore, DataIntegrityError  # noqa: E402

FREE = CostModel(0, 0, 0, 0, 0, omitted=())
D0 = date(2010, 1, 4)


def weekdays(n: int, start: date = D0) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def flat_bars(prices: list[tuple[float, float]], start: date = D0) -> list[dict]:
    """prices: (open, close) per day."""
    return [{"day": d, "open": o, "high": max(o, c), "low": min(o, c), "close": c}
            for d, (o, c) in zip(weekdays(len(prices), start), prices)]


# ── holdout ──────────────────────────────────────────────────────────────────

def test_holdout_blocks_unregistered_reads():
    check_window(EXPLORE_END, None)
    with pytest.raises(HoldoutViolation):
        check_window(HOLDOUT_START, None)
    check_window(HOLDOUT_START, "FX-BT1")  # a real, committed registration
    with pytest.raises(HoldoutViolation, match="no registration file"):
        check_window(HOLDOUT_START, "made-up-id")


# ── store ────────────────────────────────────────────────────────────────────

def test_store_roundtrip_hash_and_holdout(tmp_path):
    store = BarStore(tmp_path)
    bars = flat_bars([(10, 11), (11, 12), (12, 13)])
    store.write_dataset("ds", source="test", bars_by_symbol={"AAA": bars})
    got = store.load("ds", "AAA", start=D0, end=EXPLORE_END)
    assert [b["close"] for b in got] == [11, 12, 13]
    assert got[0]["day"] == D0
    with pytest.raises(FileExistsError):
        store.write_dataset("ds", source="test", bars_by_symbol={"AAA": bars})
    with pytest.raises(HoldoutViolation):
        store.load("ds", "AAA", start=D0, end=HOLDOUT_START)
    (tmp_path / "ds" / "AAA.csv").write_text("day,open,high,low,close\n2010-01-04,1,1,1,1\n")
    with pytest.raises(DataIntegrityError):
        store.load("ds", "AAA", start=D0, end=EXPLORE_END)


def test_failed_write_leaves_name_free(tmp_path):
    store = BarStore(tmp_path)
    bad = flat_bars([(10, 11)])
    bad[0]["close"] = float("nan")
    with pytest.raises(ValueError):
        store.write_dataset("ds", source="t", bars_by_symbol={"A": bad})
    store.write_dataset("ds", source="t", bars_by_symbol={"A": flat_bars([(10, 11)])})
    assert store.manifest("ds")["symbols"]["A"]["rows"] == 1


def test_store_rejects_bad_prices_but_allows_zero_rates(tmp_path):
    store = BarStore(tmp_path)
    bad = flat_bars([(10, 11)])
    bad[0]["close"] = 0
    with pytest.raises(ValueError):
        store.write_dataset("bad", source="t", bars_by_symbol={"A": bad})
    store.write_dataset("rates", source="t", fields=("day", "rate"), positive_fields=(),
                        bars_by_symbol={"DTB3": [{"day": D0, "rate": 0.0}]})
    assert store.load_rates("rates", "DTB3", start=D0, end=EXPLORE_END) == {D0: 0.0}


# ── registry ─────────────────────────────────────────────────────────────────

def _reg(tmp_path, reg_id="R1", **extra):
    body = {f: "x" for f in registry.REQUIRED_FIELDS}
    body.update(id=reg_id, **extra)
    (tmp_path / f"{reg_id}.json").write_text(json.dumps(body))
    return body


def test_holdout_test_runs_once_and_edits_are_refused(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _reg(tmp_path)
    reg = registry.begin_run("R1", "holdout_test", directory=tmp_path, ledger=ledger)
    registry.record_run(reg, "holdout_test", {"ok": 1}, data_manifest_hashes={}, code_commit=None, ledger=ledger)
    with pytest.raises(registry.RegistrationError, match="already had"):
        registry.begin_run("R1", "holdout_test", directory=tmp_path, ledger=ledger)
    registry.begin_run("R1", "replication", directory=tmp_path, ledger=ledger)
    _reg(tmp_path, hypothesis="changed")
    with pytest.raises(registry.RegistrationError, match="edited"):
        registry.begin_run("R1", "replication", directory=tmp_path, ledger=ledger)


def test_registration_needs_every_field(tmp_path):
    (tmp_path / "R2.json").write_text(json.dumps({"id": "R2"}))
    with pytest.raises(registry.RegistrationError, match="missing"):
        registry.load_registration("R2", tmp_path)


def test_real_fx_bt1_registration_is_valid():
    reg = registry.load_registration("FX-BT1")
    assert reg["original_result"]["trades"] == 792


# ── costs ────────────────────────────────────────────────────────────────────

def test_cost_model_validation_and_label():
    with pytest.raises(ValueError):
        CostModel(-1, 0, 0, 0, 0)
    with pytest.raises(ValueError):
        CostModel(0, 0, 0, 0, 0, omitted=("taxes",))
    c = CostModel(1, 2, 3, 0, 0, omitted=("financing",))
    assert c.trade_cost(10_000) == pytest.approx(6.0)
    assert c.label().startswith("OPTIMISTIC")


# ── metrics ──────────────────────────────────────────────────────────────────

def test_summarize_matches_fx_bt1_formula():
    import forex_baseline_backtest as fx

    rng = random.Random(7)
    eq, curve = 100_000.0, []
    for d in weekdays(600):
        eq *= 1 + rng.gauss(0.0002, 0.01)
        curve.append((d, eq, rng.random() * 2))
    trades = [{"close": d, "pnl": rng.gauss(0, 100), "r": rng.gauss(0, 1)} for d in weekdays(50)]
    ours, theirs = metrics.summarize(curve, trades), fx.stats(curve, trades)
    assert all(ours[k] == v for k, v in theirs.items())


def test_summarize_tbill_excess():
    curve = [(d, 100.0 * (1.0002 ** i), 1.0) for i, d in enumerate(weekdays(300))]
    out = metrics.summarize(curve, [], rf_annual={D0: 0.0504})  # 0.0504/252 = 0.0002 a day
    assert out["excess_return_vs_tbill_pct"] == pytest.approx(0.0, abs=0.01)


# ── portfolio simulator ──────────────────────────────────────────────────────

def test_buy_and_hold_trades_next_open_no_lookahead():
    bars = {"A": flat_bars([(10, 10), (20, 22), (22, 24), (24, 30)])}
    seen = []

    def strat(day, view):
        seen.append(len(view.bars("A")))
        return {"A": 1.0}

    res = simulate(bars, strat, costs=FREE, rf_annual=None, start=D0, end=EXPLORE_END)
    assert seen == [1, 2, 3, 4]                       # never sees a future bar
    assert res.curve[0][1] == 100_000                  # day 0: nothing bought yet
    assert res.curve[-1][1] == pytest.approx(100_000 * 30 / 20)  # bought at day-1 open
    assert res.fills == 1


def test_trade_costs_and_round_trip_record():
    bars = {"A": flat_bars([(10, 10)] * 4)}
    plan = iter([{"A": 1.0}, {}, None, None])
    res = simulate(bars, lambda d, v: next(plan), costs=CostModel(10, 0, 0, 0, 0),
                   rf_annual=None, start=D0, end=EXPLORE_END)
    assert res.fills == 2
    assert res.costs_paid == pytest.approx(100_000 * 0.001 + res.traded_notional / 2 * 0.001, rel=1e-3)
    assert len(res.trades) == 1 and res.trades[0]["pnl"] < 0
    assert res.curve[-1][1] == pytest.approx(100_000 - res.costs_paid)


def test_cash_interest_financing_and_borrow():
    bars = {"A": flat_bars([(10, 10)] * 253)}
    cash = simulate(bars, lambda d, v: None, costs=FREE, rf_annual={D0: 0.05},
                    start=D0, end=EXPLORE_END)
    assert cash.curve[-1][1] == pytest.approx(100_000 * (1 + 0.05 / 252) ** 253)
    lev = simulate(bars, lambda d, v: {"A": 1.5}, costs=CostModel(0, 0, 0, 0, 100),
                   rf_annual={D0: 0.0}, start=D0, end=EXPLORE_END, max_gross=1.5)
    assert lev.financing_paid > 0 and lev.curve[-1][1] < 100_000
    short = simulate(bars, lambda d, v: {"A": -1.0}, costs=CostModel(0, 0, 0, 100, 0),
                     rf_annual=None, start=D0, end=EXPLORE_END, allow_short=True)
    assert short.borrow_paid > 0


def test_short_proceeds_earn_no_interest():
    bars = {"A": flat_bars([(10, 10)] * 50)}
    short = simulate(bars, lambda d, v: {"A": -1.0}, costs=FREE, rf_annual={D0: 0.05},
                     start=D0, end=EXPLORE_END, allow_short=True)
    cash_only = simulate(bars, lambda d, v: None, costs=FREE, rf_annual={D0: 0.05},
                         start=D0, end=EXPLORE_END)
    # Same own cash earns the same interest; the proceeds add nothing.
    assert short.cash_interest == pytest.approx(cash_only.cash_interest, rel=0.05)
    assert short.cash_interest < cash_only.cash_interest * 1.5


def test_history_window_matches_bars():
    bars = {"A": flat_bars([(i + 1, i + 1) for i in range(30)])}

    def strat(day, view):
        assert view.window("A", 5) == view.bars("A")[-5:]
        return None

    simulate(bars, strat, costs=FREE, rf_annual=None, start=D0, end=EXPLORE_END)


def test_limits_are_enforced():
    bars = {"A": flat_bars([(10, 10)] * 3)}
    with pytest.raises(StrategyError, match="short"):
        simulate(bars, lambda d, v: {"A": -0.5}, costs=FREE, rf_annual=None, start=D0, end=EXPLORE_END)
    with pytest.raises(StrategyError, match="cap"):
        simulate(bars, lambda d, v: {"A": 1.2}, costs=FREE, rf_annual=None, start=D0, end=EXPLORE_END)
    with pytest.raises(HoldoutViolation):
        simulate(bars, lambda d, v: None, costs=FREE, rf_annual=None, start=D0, end=HOLDOUT_START)


def test_flip_long_to_short_closes_round_trip():
    bars = {"A": flat_bars([(10, 10), (10, 12), (12, 12), (12, 12)])}
    plan = iter([{"A": 1.0}, {"A": -1.0}, None, None])
    res = simulate(bars, lambda d, v: next(plan), costs=FREE, rf_annual=None,
                   start=D0, end=EXPLORE_END, allow_short=True)
    assert len(res.trades) == 1 and res.trades[0]["pnl"] == pytest.approx(20_000)


def test_order_waits_for_missing_bar():
    a = flat_bars([(10, 10)] * 4)
    b = [x for i, x in enumerate(flat_bars([(5, 5)] * 4)) if i != 1]  # B has no bar on day 1
    res = simulate({"A": a, "B": b}, lambda d, v: {"B": 1.0}, costs=FREE, rf_annual=None,
                   start=D0, end=EXPLORE_END)
    assert res.curve[1][2] == 0.0 and res.curve[2][2] == pytest.approx(1.0)


# ── fleet ────────────────────────────────────────────────────────────────────

def _curve(rets):
    vals, out = 1.0, []
    for d, r in zip(weekdays(len(rets) + 1), [0.0] + rets):
        vals *= 1 + r
        out.append((d, vals, 1.0))
    return out


def test_fleet_sleeve_checks():
    rng = random.Random(1)
    a = [rng.gauss(0.0005, 0.01) for _ in range(500)]
    b = [rng.gauss(0.0005, 0.01) for _ in range(500)]
    out = fleet.evaluate_sleeve("B", {"A": _curve(a), "B": _curve(b)}, {"A": 1, "B": 1}, {D0: 0.0})
    assert out["checks"]["correlation_below_0_5"]
    clone = fleet.evaluate_sleeve("B", {"A": _curve(a), "B": _curve(a)}, {"A": 1, "B": 1}, {D0: 0.0})
    assert not clone["checks"]["correlation_below_0_5"] and not clone["passes"]


def test_fleet_aligns_on_common_days_only():
    days = weekdays(4)
    a = [(days[0], 100.0, 1), (days[1], 110.0, 1), (days[2], 121.0, 1), (days[3], 121.0, 1)]
    b = [(days[0], 100.0, 1), (days[2], 120.0, 1), (days[3], 120.0, 1)]  # B closed on day 1
    common, rets = fleet._aligned({"A": a, "B": b})
    assert common == [days[2], days[3]]
    assert rets["A"][0] == pytest.approx(0.21) and rets["B"][0] == pytest.approx(0.20)


def test_fleet_vs_spy_needs_both_sharpe_and_drawdown():
    rng = random.Random(2)
    spy = [rng.gauss(0.0004, 0.012) for _ in range(500)]
    calm = [x * 0.5 + 0.0002 for x in spy]
    assert fleet.evaluate_fleet_vs_spy(_curve(calm), _curve(spy), None)["passes"]
    assert not fleet.evaluate_fleet_vs_spy(_curve(spy), _curve(spy), None)["passes"]


# ── FX-BT1 replication plumbing (synthetic data; real run happens in Replit) ─

def test_fx_bt1_replication_runs_on_synthetic_data(tmp_path):
    from research_harness.fetch import FX_FIELDS
    from research_harness.replications import fx_bt1

    rng = random.Random(3)
    store = BarStore(tmp_path)
    data = {}
    for pair in registry.load_registration("FX-BT1")["universe"]:
        px, rows = 1.2, []
        for d in weekdays(400, date(2024, 1, 1)):
            px *= 1 + rng.gauss(0, 0.006)
            bid = {"bo": px, "bh": px * 1.004, "bl": px * 0.996, "bc": px * (1 + rng.gauss(0, 0.002))}
            rows.append({"day": d, **bid, **{"a" + k[1:]: v * 1.0001 for k, v in bid.items()}})
        data[pair] = rows
    store.write_dataset("fx", source="synthetic", bars_by_symbol=data, fields=FX_FIELDS)
    out = fx_bt1.run("fx", store, record=False)
    assert out["harness_metrics_match_original_formula"] is True
    assert out["reproduced"] is False  # synthetic data must not "reproduce" the real result


# ── live-parity options: whole shares and protective stops ──────────────────

def test_whole_shares_rounds_toward_zero():
    bars = {"A": flat_bars([(30, 30)] * 3)}
    res = simulate(bars, lambda d, v: {"A": 1.0}, costs=FREE, rf_annual=None,
                   start=D0, end=EXPLORE_END, whole_shares=True, start_equity=1000)
    # 1000 / 30 = 33.33 -> 33 shares; 10 dollars stays in cash
    assert res.traded_notional == pytest.approx(33 * 30)


def test_stop_exits_at_stop_and_stays_flat_until_next_rebalance():
    prices = [(100, 100), (100, 100), (100, 85), (85, 90), (90, 95)]
    bars = {"A": flat_bars(prices)}
    plan = iter([{"A": 1.0}, None, None, None, None])
    res = simulate(bars, lambda d, v: next(plan), costs=FREE, rf_annual=None,
                   start=D0, end=EXPLORE_END, stop_pct=0.10)
    assert res.stops_hit == 1
    assert res.trades[0]["exit"] == "stop"
    assert res.trades[0]["pnl"] == pytest.approx(-10_000)    # 100 -> stop at 90
    assert res.curve[-1][2] == 0.0                            # still flat afterwards


def test_stop_fills_at_open_when_price_gaps_through():
    prices = [(100, 100), (100, 100), (80, 82)]
    bars = {"A": flat_bars(prices)}
    plan = iter([{"A": 1.0}, None, None])
    res = simulate(bars, lambda d, v: next(plan), costs=FREE, rf_annual=None,
                   start=D0, end=EXPLORE_END, stop_pct=0.10)
    assert res.trades[0]["pnl"] == pytest.approx(-20_000)    # gapped to 80, not 90


def test_stop_resets_at_each_rebalance():
    prices = [(100, 100), (100, 120), (120, 120), (120, 120), (120, 106)]
    bars = {"A": flat_bars(prices)}
    plan = iter([{"A": 1.0}, None, {"A": 1.0}, None, None])
    res = simulate(bars, lambda d, v: next(plan), costs=FREE, rf_annual=None,
                   start=D0, end=EXPLORE_END, stop_pct=0.10)
    # second rebalance at open 120 moves the stop to 108; day 5 low 106 hits it
    assert res.stops_hit == 1 and res.trades[0]["exit"] == "stop"


def test_parse_fred_csv_handles_both_headers_and_missing_values():
    from research_harness.fetch import parse_fred_csv

    for header in ("DATE,DTB3", "observation_date,DTB3"):
        rows = parse_fred_csv(f"{header}\n2020-01-02,1.52\n2020-01-03,.\n2020-01-06,\n2020-01-07,0.00\n")
        assert rows == [{"day": date(2020, 1, 2), "rate": pytest.approx(0.0152)},
                        {"day": date(2020, 1, 7), "rate": 0.0}]
    with pytest.raises(RuntimeError):
        parse_fred_csv("<html>blocked</html>")


# ── 2 Nov 2026: a carried order must not sell the rest of the book ──────────
def _bars_simple(days, px, skip=()):
    return [{"day": d, "open": px, "high": px, "low": px, "close": px} for d in days if d not in skip]


def test_carried_order_leaves_other_holdings_alone_and_delisting_closes_a_dead_name():
    from datetime import date, timedelta
    from research_harness.harness.costs import CostModel
    from research_harness.harness.portfolio import DELISTED_AFTER, simulate

    days, d = [], date(2020, 1, 1)
    while len(days) < 40:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    # B has no bar on the fill day (days[1]); C stops trading after days[5]
    bars = {"A": _bars_simple(days, 10.0), "B": _bars_simple(days, 20.0, skip={days[1]}),
            "C": _bars_simple(days[:6], 30.0)}
    calls = {"n": 0}

    def strat(day, view):
        calls["n"] += 1
        return {"A": 0.3, "B": 0.3, "C": 0.3} if day == days[0] else None

    costs = CostModel(commission_bps=0.0, half_spread_bps=0.0, slippage_bps=0.0,
                      short_borrow_bps_yr=0.0, financing_spread_bps_yr=0.0)
    res = simulate(bars, strat, costs=costs, rf_annual=None, start=days[0], end=days[-1])
    # A and C filled on days[1]; B carried to days[2]. Nothing was sold on days[2].
    assert not [t for t in res.trades if t["symbol"] in ("A",) ]          # A never closed
    b_opened = [t for t in res.trades if t["symbol"] == "B"]
    assert not b_opened                                                    # B still held at the end
    # C's last bar is days[5]; it is closed as delisted DELISTED_AFTER sessions later, at its last close.
    c = [t for t in res.trades if t["symbol"] == "C"]
    assert len(c) == 1 and c[0]["exit"] == "delisted"
    assert c[0]["close"] == days[5 + DELISTED_AFTER]
    _, equity, gross = res.curve[-1]
    assert gross == pytest.approx(0.6, abs=0.02)                          # A and B still held, C gone to cash
