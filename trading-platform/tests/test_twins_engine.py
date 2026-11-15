"""AI twins engine: hand-worked examples (spec, Phase A tests)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from twins import engine
from twins.config import DAILY, HOURLY, SHARE_COSTS
from research_harness.harness.costs import CostModel

D1, D2, D3, D4 = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19)
FIVE_BPS = CostModel(commission_bps=0, half_spread_bps=2, slippage_bps=3,
                     short_borrow_bps_yr=0, financing_spread_bps_yr=0)


def bar(day, o, c, h=None, lo=None):
    return {"day": day, "open": o, "high": h or max(o, c), "low": lo or min(o, c), "close": c}


def run(decisions, bars, *, mirror=False, start=D1, equity=100_000.0, costs=FIVE_BPS, kind=DAILY, **kw):
    return engine.replay(bars_kind=kind, mirror=mirror, start=start, start_equity=equity,
                         decisions=decisions, bars=bars, costs=costs,
                         max_gross=kw.pop("max_gross", 1.0), allow_short=kw.pop("allow_short", False), **kw)


def test_shares_by_hand():
    # Decided after the 16 Nov close; filled at the 17 Nov open (100): 1,000 shares for
    # 100,000 plus 5 bps (50) -> cash -50. 17 Nov close 110: -50 + 110,000 = 109,950.
    # 18 Nov close 99: -50 + 99,000 = 98,950.
    bars = {"SPY": [bar(D1, 95, 96), bar(D2, 100, 110), bar(D3, 108, 99)]}
    res = run([{"id": 1, "step": D1, "weights": {"SPY": 1.0}}], bars)
    assert [round(e, 2) for _, e, _ in res.curve] == [100_000.0, 109_950.0, 98_950.0]
    (fill,) = res.fills
    assert (fill["symbol"], fill["qty"], fill["price"], round(fill["cost"], 6), fill["reason"],
            fill["decision_id"]) == ("SPY", 1000.0, 100.0, 50.0, "rebalance", 1)
    assert fill["filled_at"] == datetime(2026, 11, 17, 9, 30, tzinfo=engine.NEW_YORK)


def test_forex_usd_base_pair_by_hand():
    # Long 100,000 US dollars of USD/JPY at 150 is held as a short of JPY_USD. P&L in
    # dollars = 100,000 x (1 - 150/151.5) = 990.10; the 1 bp half spread costs 10.00.
    h0 = datetime(2026, 11, 16, 15, tzinfo=timezone.utc)
    h1, h2 = h0 + engine.HOUR, h0 + 2 * engine.HOUR
    candles = {"USD_JPY": [
        {"time": f"{t:%Y-%m-%dT%H:%M:%S}.000000000Z", "complete": True,
         "mid": {"o": str(o), "h": str(max(o, c)), "l": str(min(o, c)), "c": str(c)}}
        for t, o, c in ((h0, 149.8, 150.0), (h1, 150.0, 151.5), (h2, 151.5, 151.5))]}
    bars = engine.forex_bars(candles)
    assert list(bars) == ["JPY_USD"] and bars["JPY_USD"][1]["open"] == pytest.approx(1 / 150)
    snap = engine.forex_snapshot([{"instrument": "USD_JPY", "long": {"units": "100000"},
                                   "short": {"units": "0"}}], "100000", {})
    assert snap["weights"] == {"JPY_USD": -1.0}
    res = run([{"id": 7, "step": h0, "weights": snap["weights"]}], bars, start=h0, kind=HOURLY,
              costs=engine.forex_costs({"USD_JPY": 1.0}), max_gross=10, allow_short=True)
    assert round(res.curve[1][1], 2) == round(100_000 + 100_000 * (1 - 150 / 151.5) - 10, 2) == 100_980.10


def test_forex_usd_quote_pair_weight_is_dollars_over_nav():
    snap = engine.forex_snapshot([{"instrument": "EUR_USD", "long": {"units": "0"}, "short": {"units": "-40000"}}],
                                 100_000, {"EUR_USD": 1.25})
    assert snap["weights"] == {"EUR_USD": pytest.approx(-0.5)} and snap["units"] == {"EUR_USD": -40000.0}
    with pytest.raises(engine.SnapshotError):
        engine.forex_snapshot([{"instrument": "EUR_GBP", "long": {"units": "10"}}], 100_000, {})
    with pytest.raises(engine.SnapshotError):
        engine.forex_snapshot([{"instrument": "EUR_USD", "long": {"units": "10"}}], 100_000, {})  # no price


def test_mirror_copies_holdings_from_the_open_they_were_bought_at():
    # The real account held A at the 16 Nov close and B at the 18 Nov close: the bot bought
    # A before 16 Nov and B at the 18 Nov open. The mirror buys A at the 17 Nov open (its
    # first chance) and B at the 18 Nov open, the same open the bot used.
    bars = {s: [bar(d, 10, 10) for d in (D1, D2, D3, D4)] for s in ("A", "B")}
    decisions = [{"id": 1, "step": D1, "weights": {"A": 1.0}}, {"id": 2, "step": D3, "weights": {"B": 1.0}}]
    res = run(decisions, bars, mirror=True, costs=SHARE_COSTS)
    assert [(f["filled_at"].date(), f["symbol"], f["qty"] > 0, f["decision_id"]) for f in res.fills] == [
        (D2, "A", True, 1), (D3, "A", False, 2), (D3, "B", True, 2)]
    plain = run(decisions, bars, costs=SHARE_COSTS)          # any other twin: the open after its decision
    assert [(f["filled_at"].date(), f["symbol"]) for f in plain.fills] == [(D2, "A"), (D4, "A"), (D4, "B")]


def test_missed_vote_holds_and_a_decision_is_sent_once():
    bars = {"A": [bar(d, 10, 10 + i) for i, d in enumerate((D1, D2, D3, D4))]}
    decisions = [{"id": 1, "step": D1, "weights": {"A": 0.5}}, {"id": 2, "step": D2, "weights": None}]
    res = run(decisions, bars)
    assert len(res.fills) == 1          # no re-trade on the missed vote, no drift rebalancing


def test_share_snapshot_leaves_owner_kept_lines_out():
    positions = [{"symbol": "SPY", "qty": "10", "side": "long"}, {"symbol": "BTC/USD", "qty": "0.1", "side": "long"},
                 {"symbol": "QQQ", "qty": "-5", "side": "short"}]
    snap = engine.share_snapshot(positions, 1_000, {"SPY": 500.0, "QQQ": 400.0}, frozenset({"BTCUSD"}))
    assert snap["equity"] == 1_000 + 5_000 - 2_000
    assert snap["weights"] == {"QQQ": pytest.approx(-0.5), "SPY": pytest.approx(1.25)}
    assert snap["qty"] == {"QQQ": -5.0, "SPY": 10.0}
    with pytest.raises(engine.SnapshotError):
        engine.share_snapshot([{"symbol": "IEF", "qty": 1}], 0, {"SPY": 1.0})
    with pytest.raises(engine.SnapshotError):
        engine.share_snapshot([{"symbol": "SPY", "qty": "nan"}], 0, {"SPY": 1.0})


def test_forex_bars_inverts_usd_base_pairs_and_rejects_bad_candles():
    c = {"time": "2026-11-16T15:00:00.000000000Z", "mid": {"o": "2", "h": "4", "l": "1", "c": "2"}}
    (b,) = engine.forex_bars({"USD_CHF": [c]})["CHF_USD"]
    assert (b["open"], b["high"], b["low"], b["close"]) == (0.5, 1.0, 0.25, 0.5)
    with pytest.raises(engine.SnapshotError):
        engine.forex_bars({"EUR_USD": [{**c, "mid": {"o": "2", "h": "1.5", "l": "1", "c": "2"}}]})


def test_half_spread_is_the_median_at_the_opens():
    rows = [{"bid": {"o": str(1 - s)}, "ask": {"o": str(1 + s)}, "mid": {"o": "1"}} for s in (1e-4, 2e-4, 9e-4)]
    assert engine.half_spread_bps(rows) == 2.0


def test_forex_day_points_follow_new_york_in_both_seasons():
    def curve(start_utc):
        return [(start_utc + timedelta(hours=i), 100.0 + i, 0.0) for i in range(30)]
    winter = engine.daily_points(curve(datetime(2026, 11, 16, 0, tzinfo=timezone.utc)), HOURLY)
    summer = engine.daily_points(curve(datetime(2026, 7, 13, 0, tzinfo=timezone.utc)), HOURLY)
    assert [d for d, _, _ in winter] == [date(2026, 11, 16)] and winter[0][1] == 100.0 + 21  # 21:00 UTC bar
    assert [d for d, _, _ in summer] == [date(2026, 7, 13)] and summer[0][1] == 100.0 + 20  # 20:00 UTC bar


def test_mirror_gap_starts_after_the_first_full_day():
    pts = [(D1, 100.0, 100.0), (D2, 101.0, 102.0), (D3, 102.01, 103.02), (D4, 103.0, None)]
    assert engine.mirror_gaps(pts) == {D2: 0.0, D3: 0.0}
    assert engine.mirror_gaps([(D1, 100.0, 100.0), (D2, 100.0, 100.0), (D3, 102.0, 100.0)]) == {D2: 0.0, D3: 2.0}


def test_steps_round_trip():
    assert engine.step_of(engine.step_close(D2, DAILY), DAILY) == D2
    h = datetime(2026, 11, 16, 21, tzinfo=timezone.utc)
    assert engine.step_of(engine.step_close(h, HOURLY), HOURLY) == h
    assert engine.bar_hour(datetime(2026, 11, 16, 16, 55, tzinfo=engine.NEW_YORK)) == h
