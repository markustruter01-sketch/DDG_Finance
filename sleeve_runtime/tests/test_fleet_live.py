"""FLEET-V1 live cycle against a fake broker+ledger (no network, no DB).
Spec: sleeve_runtime/FLEET-V1-LIVE-SPEC.md, "Tests Opus must add"."""

from __future__ import annotations

import importlib.util
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from research_harness.harness.portfolio import HistoryView
from research_harness.sleeves import core_v1, xasset_v1
from sleeve_runtime import fleet_live as fl
from sleeve_runtime.planner import plan_rebalance
from sleeve_runtime.tests.test_trend_executor import FakeEngine

BOT = "oracle"
FRI_OPEN = datetime(2026, 10, 23, 14, 30, tzinfo=timezone.utc)      # 10:30 NY; Thu 22 Oct is final
LAST = date(2026, 10, 22)
SOFT, HARD = 0.15, 0.22


def _series(end: date, start_px: float, daily: float, wiggle: float):
    out, d, px = [], end - timedelta(days=420), start_px
    while d <= end:
        if d.weekday() < 5:
            px *= 1 + daily
            px *= 1 + (wiggle if len(out) % 2 else -wiggle)
            out.append({"day": d, "close": round(px, 4)})
        d += timedelta(days=1)
    return out


def _bars(end=date(2026, 10, 23), spy_daily=0.001, wiggle=0.002, lines_daily=0.0008, extra=()):
    """SPY rising and calm (3 votes, E = 1.5); every cross-asset line rising (on)."""
    bars = {"SPY": _series(end, 400.0, spy_daily, wiggle),
            "QQQ": _series(end, 350.0, spy_daily, wiggle),
            "SSO": _series(end, 80.0, 2 * spy_daily, 2 * wiggle),
            "QLD": _series(end, 90.0, 2 * spy_daily, 2 * wiggle)}
    for i, s in enumerate(xasset_v1.LINES):
        bars[s] = _series(end, 50.0 + 10 * i, lines_daily, 0.004)
    for s in extra:
        bars[s] = _series(end, 30.0, 0.0, 0.003)
    return bars


def _engine(bars, positions, cash, rows, last_equity=None):
    eng = FakeEngine(positions, cash, rows)
    eng.px = {s: [b for b in v if b["day"] <= LAST][-1]["close"] for s, v in bars.items()}
    eng.px.update(BIL=91.0, VOO=700.0, SGOV=100.0)
    eng.last_equity = last_equity
    return eng


def _run(eng, bars, state=None, now=FRI_OPEN, **kw):
    saved = {"state": dict(state or {})}
    events = []
    out = fl.run_fleet_cycle(
        eng, bot_id=BOT, fetch_bars=lambda syms, start: {s: bars[s] for s in syms if s in bars},
        vault={"BIL", "VOO"}, cash_park={"SGOV"},
        read_state=lambda: saved["state"], write_state=lambda st: saved.update(state=st),
        kill_tripped=kw.get("kill", lambda: False),
        unpark=lambda e, live: events.append("unpark"),
        park=lambda e, live, cash: events.append(("park", round(cash, 2))),
        alert=lambda sev, msg: events.append((sev, msg)),
        risk_check=kw.get("risk", lambda: {"allowed": True, "reasons": []}),
        soft=SOFT, hard=HARD, now=now, variant=kw.get("variant", fl.F1))
    return out, saved["state"], events


# ── target vector ─────────────────────────────────────────────────────────────
def test_fleet_vector_is_065_core_plus_035_xasset_with_gross_at_most_one():
    core = core_v1.weights_for(1.5, core_v1.MIXES["C1"])
    xa = {"IEF": 0.25, "GLD": 0.25, "DBC": 0.25, "UUP": 0.25}
    w = fl.fleet_weights(core, xa, fl.F1)
    for s, x in core.items():
        assert w[s] == pytest.approx(0.65 * x)
    for s in xa:
        assert w[s] == pytest.approx(0.35 * 0.25)
    assert sum(w.values()) <= 1.0
    assert sum(w.values()) == pytest.approx(0.65 * 0.99 + 0.35)       # SGOV takes the remainder
    assert fl.fleet_weights(core, xa, fl.C1) == pytest.approx(core)    # control: core alone
    half = fl.fleet_weights(core, xa, fl.F1, scale=0.5)
    assert {s: 2 * x for s, x in half.items()} == pytest.approx(w)
    assert fl.fleet_weights(core, xa, fl.F1, scale=0.0) == {}


def test_fleet_vector_raises_rather_than_clamps_above_gross_one():
    with pytest.raises(ValueError, match="no-borrowing"):
        fl.fleet_weights({"SPY": 1.0}, {"IEF": 1.0}, fl.FleetVariant("X", "x", "x", 0.8, 0.8))


def test_signal_is_the_registered_core_and_xasset_code():
    bars = _bars()
    sig = fl.core_signal(bars, LAST)
    closes = [b["close"] for b in bars["SPY"] if b["day"] <= LAST]
    assert sig["votes"] == core_v1.votes(closes) == 3
    assert sig["exposure"] == pytest.approx(core_v1.target_exposure(3, core_v1.vol20(closes)))
    assert sig["weights"] == core_v1.weights_for(sig["exposure"], core_v1.MIXES["C1"])
    first = fl.month_first_session(bars, LAST)
    assert first == date(2026, 10, 1)
    view = HistoryView({s: bars[s] for s in xasset_v1.LINES})
    view.today = first
    assert fl.xasset_signal(bars, LAST) == xasset_v1.target_weights(view)
    assert set(fl.xasset_signal(bars, LAST)) == set(xasset_v1.LINES)


def test_parity_live_targets_equal_what_the_backtest_would_hold_next_session():
    """Same bars into research_harness's strategies and into the live targets."""
    bars = _bars()
    days = [b["day"] for b in bars["SPY"] if b["day"] <= LAST]
    view = HistoryView({s: [b for b in v if b["day"] <= LAST] for s, v in bars.items()})
    core_strat = core_v1.make_strategy("C1")
    xa_strat = xasset_v1.make_strategy()
    core_w = xa_w = None
    for d in days:
        view.today = d
        cw = core_strat(d, view)
        xw = xa_strat(d, view)
        core_w = cw if cw is not None else core_w
        xa_w = xw if xw is not None else xa_w
    expected = fl.fleet_weights(core_w, xa_w, fl.F1)
    live = fl.targets_on(bars, LAST, fl.F1, "normal")["fleet"]
    assert live == pytest.approx(expected)


# ── schedule ──────────────────────────────────────────────────────────────────
def test_due_only_on_vote_change_month_start_or_mode_change():
    bars = _bars()
    done = {"key": "2026-10|v3|normal", "done": True, "attempts": 1}
    assert fl.fleet_due(bars, date(2026, 10, 23), done, "normal") is None          # nothing new
    assert fl.fleet_due(bars, date(2026, 10, 23), {"key": "2026-10|v2|normal", "done": True}, "normal")
    assert fl.fleet_due(bars, date(2026, 10, 23), {"key": "2026-09|v3|normal", "done": True}, "normal")
    assert fl.fleet_due(bars, date(2026, 10, 23), done, "soft")[2] == "2026-10|v3|soft"
    assert fl.fleet_due(bars, date(2026, 10, 23), {"key": "2026-10|v3|normal", "attempts": 3}, "normal") is None
    assert fl.fleet_due(bars, date(2026, 10, 30), {}, "normal") is None             # stale feed


def test_xasset_weights_only_change_at_month_start():
    """A mid-month core event re-uses the month's first-session cross-asset weights."""
    bars = _bars()
    a = fl.xasset_signal(bars, date(2026, 10, 1))
    b = fl.xasset_signal(bars, LAST)
    assert a == b


def test_a_day_with_nothing_due_places_no_orders():
    bars = _bars()
    eng = _engine(bars, {}, 100_000.0, [])
    _, state, _ = _run(eng, bars)
    n = len(eng.orders)
    out, state2, _ = _run(eng, bars, state=state)
    assert out["status"] == "no rebalance due" and len(eng.orders) == n


# ── cycle ─────────────────────────────────────────────────────────────────────
def test_cutover_from_g4_buys_the_fleet_with_stops_on_core_only():
    bars = _bars()
    positions = {"SPY": 20, "QQQ": 20, "SSO": 100, "QLD": 100, "BIL": 25.3, "VOO": 3.29, "SGOV": 50}
    rows = [{"symbol": s, "qty": q, "stop_price": 1.0, "stop_order_id": f"s-{s}"}
            for s, q in (("SPY", 20), ("QQQ", 20), ("SSO", 100), ("QLD", 100))]
    eng = _engine(bars, positions, 20_000.0, rows)
    eng.stops = {s: (int(q), 1.0) for s, q in positions.items() if s in ("SPY", "QQQ", "SSO", "QLD")}
    out, state, events = _run(eng, bars)
    assert out["status"].startswith("rebalanced (2026-10|v3|normal)")
    assert state["done"] is True and state["votes"] == 3
    held = {s for s, q in eng.pos.items() if q >= 1}
    assert set(core_v1.INSTRUMENTS["SP"]) | set(core_v1.INSTRUMENTS["NDX"]) <= held
    assert set(xasset_v1.LINES) <= held
    for s in ("SPY", "QQQ", "SSO", "QLD"):
        qty, stop = eng.stops[s]
        assert qty == int(eng.pos[s]) and stop == pytest.approx(eng.px[s] * 0.8, abs=0.01)
    for s in xasset_v1.LINES:
        assert s not in eng.stops                                # stop-free by design
    assert eng.pos["BIL"] == 25.3 and eng.pos["VOO"] == 3.29     # vault never traded
    assert not [e for e in events if isinstance(e, tuple) and e[0] in ("critical", "error")]
    equity = eng.get_account()["equity"] - 25.3 * 91.0 - 3.29 * 700.0
    gross = sum(eng.pos[s] * eng.px[s] for s in fl.F1.symbols if s in eng.pos) / equity
    assert gross <= 1.0


def test_control_account_holds_the_core_only():
    bars = _bars()
    eng = _engine(bars, {"DBMF": 100}, 50_000.0,
                  [{"symbol": "DBMF", "qty": 100, "stop_price": 1.0, "stop_order_id": None}])
    eng.px["DBMF"] = 25.0
    bars["DBMF"] = _series(date(2026, 10, 23), 25.0, 0.0, 0.0)
    out, state, _ = _run(eng, bars, variant=fl.C1)
    assert state["done"] is True
    assert "DBMF" not in eng.pos                                 # the G4+DBMF holding is sold
    assert not set(xasset_v1.LINES) & {s for s, q in eng.pos.items() if q >= 1}
    assert {"SPY", "QQQ", "SSO", "QLD"} <= set(eng.stops)


def test_planner_gives_no_stop_to_no_stop_symbols():
    plan = plan_rebalance(weights={"SPY": 0.5, "IEF": 0.4}, equity=100_000.0, cash=100_000.0,
                          positions={}, prices={"SPY": 500.0, "IEF": 95.0}, stop_pct=0.2,
                          cash_buffer_pct=0.01, no_stop=frozenset({"IEF"}))
    assert [a.symbol for a in plan.stops] == ["SPY"]
    assert plan.final_qty["IEF"] > 0


# ── drawdown governor ─────────────────────────────────────────────────────────
def test_drawdown_modes_fire_at_15_and_22_percent_and_not_before():
    m = lambda eq, prev="normal", halted=False: fl.drawdown_mode(eq, 100.0, prev, halted, soft=SOFT, hard=HARD)
    assert m(86.0) == "normal"                 # 14% down
    assert m(84.9) == "soft"                   # 15.1% down
    assert m(78.1) == "soft"                   # 21.9%
    assert m(77.9) == "halt"                   # 22.1%
    assert m(94.0, prev="soft") == "soft"      # recovering, not yet back to 95% of the mark
    assert m(95.0, prev="soft") == "normal"
    assert m(120.0, halted=True) == "halt"     # a halt never clears itself


def test_update_drawdown_raises_mark_once_per_session_and_halt_needs_owner_clear():
    st = fl.update_drawdown({}, 100_000.0, date(2026, 10, 20), soft=SOFT, hard=HARD)
    assert st["mode"] == "normal" and st["hwm"] == 100_000.0
    st = fl.update_drawdown(st, 110_000.0, date(2026, 10, 21), soft=SOFT, hard=HARD)
    assert st["hwm"] == 110_000.0
    same_day = fl.update_drawdown(st, 50_000.0, date(2026, 10, 21), soft=SOFT, hard=HARD)
    assert same_day == st                      # once per session
    st = fl.update_drawdown(st, 85_000.0, date(2026, 10, 22), soft=SOFT, hard=HARD)
    assert st["mode"] == "halt" and st["halted"] is True
    st = fl.update_drawdown(st, 120_000.0, date(2026, 10, 23), soft=SOFT, hard=HARD)
    assert st["mode"] == "halt"                # still halted
    cleared = fl.clear_halt(st, 85_000.0, by="markus")
    assert cleared["mode"] == "normal" and cleared["hwm"] == 85_000.0
    unknown = fl.update_drawdown(cleared, None, date(2026, 10, 26), soft=SOFT, hard=HARD)
    assert unknown["mode"] == "normal" and "error" in unknown


def test_soft_mode_halves_every_target():
    bars = _bars()
    eng = _engine(bars, {}, 100_000.0, [], last_equity=80_000.0)
    state = {"drawdown": {"hwm": 100_000.0, "mode": "normal", "as_of": "2026-10-21"},
             "key": "2026-10|v3|normal", "done": True}
    out, st, events = _run(eng, bars, state=state)
    assert st["drawdown"]["mode"] == "soft" and st["key"] == "2026-10|v3|soft"
    full = fl.targets_on(bars, LAST, fl.F1, "normal")["fleet"]
    assert st["targets"] == pytest.approx({s: round(w / 2, 4) for s, w in full.items()}, abs=1e-4)
    assert any(e[0] == "error" and "normal -> soft" in e[1] for e in events if isinstance(e, tuple))


def test_hard_mode_goes_to_cash_then_stays_there_until_cleared():
    bars = _bars()
    positions = {"SPY": 50, "IEF": 100}
    rows = [{"symbol": "SPY", "qty": 50, "stop_price": 1.0, "stop_order_id": None},
            {"symbol": "IEF", "qty": 100, "stop_price": None, "stop_order_id": None}]
    eng = _engine(bars, positions, 10_000.0, rows, last_equity=70_000.0)
    state = {"drawdown": {"hwm": 100_000.0, "mode": "normal", "as_of": "2026-10-21"},
             "key": "2026-10|v3|normal", "done": True}
    out, st, events = _run(eng, bars, state=state)
    assert st["drawdown"]["halted"] is True and st["done"] is True
    assert not any(q >= 1 for s, q in eng.pos.items() if s in fl.F1.symbols)
    assert any(e[0] == "critical" and "-> halt" in e[1] for e in events if isinstance(e, tuple))
    n = len(eng.orders)
    eng.last_equity = 130_000.0                                  # even a recovery does not resume
    out2, st2, _ = _run(eng, bars, state=st, now=FRI_OPEN + timedelta(days=3))
    assert st2["drawdown"]["mode"] == "halt" and len(eng.orders) == n


def test_no_trading_when_kill_switch_tripped_or_market_closed():
    bars = _bars()
    eng = _engine(bars, {}, 100_000.0, [])
    out, _, _ = _run(eng, bars, kill=lambda: True)
    assert out["status"].startswith("kill switch") and not eng.orders
    eng.market_open = False
    out, _, _ = _run(eng, bars)
    assert out["status"] == "market closed" and not eng.orders


def test_no_stop_symbols_match_the_platforms_stop_policy():
    path = Path(__file__).resolve().parents[2] / "trading-platform" / "core" / "stop_policy.py"
    spec = importlib.util.spec_from_file_location("_stop_policy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.TREND_EXIT_LINES == fl.NO_STOP_SYMBOLS
    assert mod.stop_exempt("oracle", "IEF") and not mod.stop_exempt("oracle", "SPY")
    assert not mod.stop_exempt("jerome_macro", "GLD")            # other accounts keep their stops


def test_drawdown_limits_match_the_platforms_risk_limits():
    path = Path(__file__).resolve().parents[2] / "trading-platform" / "core" / "risk_limits.py"
    spec = importlib.util.spec_from_file_location("_risk_limits", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.SOFT_DRAWDOWN, mod.HARD_DRAWDOWN) == (SOFT, HARD)
    assert mod.ENFORCE_DRAWDOWN_LIMITS is True
