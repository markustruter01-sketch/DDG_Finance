"""GEAR-V1-G4 live cycle against a fake broker+ledger (no network, no DB)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from research_harness.sleeves.gear import CANDIDATES
from sleeve_runtime import gear_live as gl
from sleeve_runtime.tests.test_trend_executor import FakeEngine

BOT = "oracle"
FRI_OPEN = datetime(2026, 10, 23, 14, 30, tzinfo=timezone.utc)      # 10:30 NY; Thu 22 Oct is final


def _series(end: date, start_px: float, daily: float, wiggle: float, calm_days: int = 0):
    out, d, px = [], end - timedelta(days=420), start_px
    while d <= end:
        if d.weekday() < 5:
            px *= 1 + daily
            px *= 1 + (wiggle if len(out) % 2 else -wiggle)
            out.append({"day": d, "close": round(px, 4)})
        d += timedelta(days=1)
    return out


def _bars(end=date(2026, 10, 23), spy_daily=0.001, wiggle=0.002, extra=("EWT", "EWZ")):
    """SPY rising (above its 200-day average); small wiggle = calm = aggressive."""
    bars = {"SPY": _series(end, 400.0, spy_daily, wiggle),
            "QQQ": _series(end, 350.0, spy_daily, wiggle),
            "SSO": _series(end, 80.0, 2 * spy_daily, 2 * wiggle),
            "QLD": _series(end, 90.0, 2 * spy_daily, 2 * wiggle)}
    for s in extra:
        bars[s] = _series(end, 50.0, 0.0, 0.003)
    return bars


def _engine(bars, positions, cash, rows):
    eng = FakeEngine(positions, cash, rows)
    last = date(2026, 10, 22)
    eng.px = {s: [b for b in v if b["day"] <= last][-1]["close"] for s, v in bars.items()}
    eng.px.update(BIL=91.0, VOO=700.0, SGOV=100.0)
    return eng


def _run(eng, bars, state=None, now=FRI_OPEN, **kw):
    saved = {"state": dict(state or {})}
    events = []
    out = gl.run_gear_cycle(
        eng, bot_id=BOT, fetch_bars=lambda syms, start: {s: bars[s] for s in syms if s in bars},
        vault={"BIL", "VOO"}, cash_park={"SGOV"},
        read_state=lambda: saved["state"], write_state=lambda st: saved.update(state=st),
        kill_tripped=kw.get("kill", lambda: False),
        unpark=lambda e, live: events.append("unpark"),
        park=lambda e, live, cash: events.append(("park", round(cash, 2))),
        alert=lambda sev, msg: events.append((sev, msg)),
        risk_check=kw.get("risk", lambda: {"allowed": True, "reasons": []}),
        now=now)
    return out, saved["state"], events


def test_gear_rules_match_the_registered_candidate():
    bars = _bars()
    assert gl.gear_on(bars, date(2026, 10, 22)) == "aggressive"
    assert gl.target_weights("aggressive") == CANDIDATES["G4"]["aggressive"]
    assert gl.target_weights("normal") == {"SPY": 0.5, "QQQ": 0.5}
    assert gl.target_weights("safe") == {} and gl.target_weights(None) == {}
    falling = _bars(spy_daily=-0.002)
    assert gl.gear_on(falling, date(2026, 10, 22)) == "safe"
    jumpy = _bars(wiggle=0.02)               # above the average, ~30% vol
    assert gl.gear_on(jumpy, date(2026, 10, 22)) == "normal"


def test_first_cycle_replaces_legacy_atlas_holdings_with_g4():
    bars = _bars()
    positions = {"EWT": 100, "EWZ": 50.5, "SPY": 10, "BIL": 25.3, "VOO": 3.29, "SGOV": 100}
    rows = [{"symbol": s, "qty": q, "stop_price": 1.0, "stop_order_id": f"s-{s}"}
            for s, q in (("EWT", 100), ("EWZ", 50.5), ("SPY", 10))]
    eng = _engine(bars, positions, 50_000.0, rows)
    out, state, events = _run(eng, bars)
    assert out["status"] == "rebalanced to aggressive"
    assert state["key"] == "2026-10|aggressive" and state["done"] is True and state["attempts"] == 1
    held = {s for s, q in eng.pos.items() if q >= 1}
    assert {"SPY", "QQQ", "SSO", "QLD"} <= held
    assert "EWT" not in eng.pos and "EWZ" not in eng.pos          # legacy sold in full, fraction too
    assert eng.pos["BIL"] == 25.3 and eng.pos["VOO"] == 3.29      # vault never traded
    for sym in ("SPY", "QQQ", "SSO", "QLD"):                       # every holding has its 20% stop
        qty, stop = eng.stops[sym]
        assert qty == int(eng.pos[sym]) and stop == pytest.approx(eng.px[sym] * 0.8, abs=0.01)
    assert ("record_close", "EWT", gl.EXIT_REASON) in eng.orders
    assert "unpark" in events and not [e for e in events if isinstance(e, tuple) and e[0] in ("critical", "error")]
    # same day, same gear: nothing more to do
    out2, state2, _ = _run(eng, bars, state=state)
    assert out2["status"] == "no rebalance due" and state2 == state


def test_gear_change_and_new_month_are_due_but_nothing_else():
    bars = _bars()
    done = {"key": "2026-10|aggressive", "done": True, "attempts": 1}
    assert gl.gear_due(bars, date(2026, 10, 23), done) is None
    assert gl.gear_due(bars, date(2026, 10, 23), {"key": "2026-10|normal", "done": True})[1] == "aggressive"
    assert gl.gear_due(bars, date(2026, 10, 23), {"key": "2026-09|aggressive", "done": True})[2] == "2026-10|aggressive"
    failed_out = {"key": "2026-10|aggressive", "done": False, "attempts": 3}
    assert gl.gear_due(bars, date(2026, 10, 23), failed_out) is None
    assert gl.gear_due(bars, date(2026, 10, 30), {}) is None       # newest bar 8 days old: stale feed


def test_safe_gear_sells_everything_into_parked_cash():
    bars = _bars(spy_daily=-0.002)
    positions = {"SPY": 20, "QQQ": 20, "SSO": 50, "QLD": 50}
    rows = [{"symbol": s, "qty": q, "stop_price": 1.0, "stop_order_id": None} for s, q in positions.items()]
    eng = _engine(bars, positions, 1_000.0, rows)
    out, state, events = _run(eng, bars, state={"key": "2026-10|aggressive", "done": True})
    assert out["status"] == "rebalanced to safe"
    assert not any(q >= 1 for s, q in eng.pos.items() if s in ("SPY", "QQQ", "SSO", "QLD"))
    assert events[-1][0] == "park" and events[-1][1] > 1_000.0


def test_no_trading_when_kill_switch_tripped_or_market_closed():
    bars = _bars()
    eng = _engine(bars, {}, 10_000.0, [])
    assert _run(eng, bars, kill=lambda: True)[0]["status"] == "kill switch tripped: no trading"
    eng.market_open = False
    assert _run(eng, bars)[0]["status"] == "market closed"
    assert eng.orders == []


def test_risk_governor_refusal_still_sells_and_is_reported():
    bars = _bars()
    eng = _engine(bars, {"EWT": 100}, 10_000.0,
                  [{"symbol": "EWT", "qty": 100, "stop_price": 1.0, "stop_order_id": "s"}])
    out, state, events = _run(eng, bars, risk=lambda: {"allowed": False, "reasons": ["fleet drawdown"]})
    assert "EWT" not in eng.pos
    assert not any(o[0] == "buy" for o in eng.orders)
    assert state["done"] is False and "risk governor" in state["errors"][0]
    assert out["status"] == "rebalance attempt 1 incomplete"
