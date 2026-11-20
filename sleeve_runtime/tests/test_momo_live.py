"""MOMO-V2 live (research_harness/explore/MOMO-V2-PLAN.md, "Live build" tests). Synthetic only."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from research_harness.sleeves.momo_v1 import momentum_12_1
from sleeve_runtime import momo_live as ml
from sleeve_runtime import sp500_universe as su
from sleeve_runtime.tests.test_trend_executor import FakeEngine

BOT = "spy_qqq_trend"
MON_OPEN = datetime(2026, 11, 2, 15, 30, tzinfo=timezone.utc)       # 10:30 NY, Mon 2 Nov
LAST = date(2026, 10, 30)                                            # last completed session (Fri)


def weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(date(2025, 6, 2), date(2026, 11, 2))


def series(drift: float, start: float = 50.0, wiggle: float = 0.002, crash_from: date | None = None,
           crash: float = 0.0, days=DAYS):
    out, px = [], start
    for i, d in enumerate(days):
        px *= 1 + drift + (wiggle if i % 2 else -wiggle)
        if crash_from and d >= crash_from:
            px *= 1 + crash
        out.append({"day": d, "close": round(px, 4)})
    return out


def universe(n=80, **kw):
    """S000.. with rising drift: higher index = stronger momentum."""
    return {f"S{i:03d}": series(0.0001 * i, **kw) for i in range(n)}


# ── universe loader ──────────────────────────────────────────────────────────
def test_members_one_class_per_company_and_common_stock_only():
    rows = [{"ticker": "GOOGL", "name": "Alphabet Inc. Class A", "weight": 2.1},
            {"ticker": "GOOG", "name": "Alphabet Inc. Class C", "weight": 1.8},
            {"ticker": "BRK.B", "name": "Berkshire Hathaway Inc. Class B", "weight": 1.7},
            {"ticker": "AAPL", "name": "Apple Inc.", "weight": 7.0},
            {"ticker": "CASH_USD", "name": "US DOLLAR", "weight": 0.1},
            {"ticker": "-", "name": "Futures", "weight": 0.2}]
    assert su.members(rows) == ["AAPL", "BRK.B", "GOOGL"]


def test_ivv_csv_parses_equities_and_fixes_class_tickers():
    text = ('iShares Core S&P 500 ETF\nFund Holdings as of,"Oct 30, 2026"\n\n'
            'Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value\n'
            'AAPL,APPLE INC,Information Technology,Equity,"1,000",7.01,"1,000"\n'
            'BRKB,BERKSHIRE HATHAWAY INC CLASS B,Financials,Equity,"500",1.70,"500"\n'
            'XTSLA,BLK CSH FND TREASURY SL AGENCY,Cash and/or Derivatives,Money Market,"10",0.10,"10"\n')
    rows = su.parse_ivv_csv(text)
    assert su.members(rows) == ["AAPL", "BRK.B"]


def test_loader_falls_back_then_fails_loud():
    good = ("Ticker,Name,Sector,Asset Class,Market Value,Weight (%)\n" +
            "".join(f"T{i:03d},CO {i},X,Equity,1,0.2\n".replace("T", "A") for i in range(0)) +
            "".join(f"{''.join(chr(65 + int(c)) for c in f'{i:03d}')},CO {i},X,Equity,1,0.2\n" for i in range(500)))

    def http(url):
        if url == su.SSGA_URL:
            raise ConnectionError("blocked")
        return good.encode()

    tickers, source = su.load_sp500(http)
    assert source == "ishares_ivv" and len(tickers) == 500
    with pytest.raises(su.UniverseUnavailable, match="ssga_spy.*ishares_ivv"):
        su.load_sp500(lambda url: (_ for _ in ()).throw(ConnectionError("down")))
    short = "Ticker,Name,Sector,Asset Class,Market Value,Weight (%)\nAAPL,APPLE,X,Equity,1,7\n"
    with pytest.raises(su.UniverseUnavailable, match="only 1 members"):
        su.load_sp500(lambda url: (_ for _ in ()).throw(ConnectionError()) if url == su.SSGA_URL else short.encode())


# ── ranking, book index, brakes ──────────────────────────────────────────────
def test_rank_top_is_12_1_momentum_and_needs_a_bar_on_the_day():
    bars = universe(80)
    top = ml.rank_top(bars, sorted(bars), LAST, n=50)
    assert top == [f"S{i:03d}" for i in range(79, 29, -1)]
    m = {s: momentum_12_1(ml.closes_upto(bars, s, LAST)) for s in bars}
    assert min(m[s] for s in top) >= max(m[s] for s in bars if s not in top)
    bars["S079"] = [b for b in bars["S079"] if b["day"] != LAST]          # no bar on the signal day
    assert "S079" not in ml.rank_top(bars, sorted(bars), LAST, n=50)


def test_book_index_is_rebased_at_selection_and_built_from_each_names_own_history():
    bars = {"A": [{"day": DAYS[i], "close": 10.0 * (1 + 0.01 * i)} for i in range(10)],
            "B": [{"day": DAYS[i], "close": 20.0} for i in range(10)]}
    idx = ml.book_index(bars, ["A", "B"], DAYS[5], DAYS[9])
    level = dict(idx)
    assert level[DAYS[5]] == pytest.approx(100.0)                           # rebased at the selection
    assert level[DAYS[0]] == pytest.approx(100 * (1.0 / 1.05 + 1.0) / 2)    # history before it, own series
    assert level[DAYS[9]] == pytest.approx(100 * (1.09 / 1.05 + 1.0) / 2)


def test_brakes_read_the_book_not_the_market():
    rising = [(d, 100 * 1.001 ** i) for i, d in enumerate(DAYS[:150])]
    falling = rising[:120] + [(d, rising[119][1] * 0.97 ** k) for k, (d, _) in enumerate(rising[120:], 1)]
    assert ml.brakes(rising)["trend_on"] is True
    assert ml.brakes(falling)["trend_on"] is False
    assert 0 < ml.brakes(falling)["s"] <= 1
    assert ml.brakes(rising[:50])["trend_on"] is None                      # not enough history


def test_book_weights_equal_2pct_times_s_and_never_above_one():
    names = [f"S{i:03d}" for i in range(50)]
    w = ml.book_weights(names, 1.0, stopped=set(), mode="normal")
    assert all(x == pytest.approx(0.02) for x in w.values()) and sum(w.values()) == pytest.approx(1.0)
    w = ml.book_weights(names, 0.6, stopped={"S000", "S001"}, mode="normal")
    assert len(w) == 48 and all(x == pytest.approx(0.012) for x in w.values())   # stopped slots stay cash
    assert sum(ml.book_weights(names, 0.6, stopped=set(), mode="soft").values()) == pytest.approx(0.3)
    assert ml.book_weights(names, 1.0, stopped=set(), mode="halt") == {}


def test_unaffordable_names_are_reported():
    assert ml.unaffordable(["A", "B"], 0.02, 100_000.0, {"A": 2500.0, "B": 150.0}) == ["A"]


# ── schedule ──────────────────────────────────────────────────────────────────
def test_decide_monthly_brake_and_no_midmonth_reentry():
    assert ml.decide({}, "2026-11", True, "normal") == ("2026-11|in|normal", "in", "monthly")
    assert ml.decide({}, "2026-11", False, "normal")[1] == "out"            # starts in cash if the brake is on
    held_in = {"month": "2026-11", "held": "in", "key": "2026-11|in|normal", "done": True}
    assert ml.decide(held_in, "2026-11", True, "normal") is None           # nothing between months
    assert ml.decide(held_in, "2026-11", False, "normal") == ("2026-11|out|normal", "out", "brake")
    out = {"month": "2026-11", "held": "out", "key": "2026-11|out|normal", "done": True}
    assert ml.decide(out, "2026-11", True, "normal") is None               # re-entry waits for December
    assert ml.decide(out, "2026-12", True, "normal") == ("2026-12|in|normal", "in", "monthly")
    assert ml.decide(held_in, "2026-11", True, "soft") == ("2026-11|in|soft", "in", "mode")
    assert ml.MIDMONTH_REENTRY is False


# ── the cycle ─────────────────────────────────────────────────────────────────
def _engine(bars, positions=None, cash=100_000.0, rows=None, last_equity=None):
    eng = FakeEngine(positions or {}, cash, rows or [])
    eng.px = {s: [b for b in v if b["day"] <= LAST][-1]["close"] for s, v in bars.items()}
    eng.px.update(BIL=91.0, VOO=700.0, SGOV=100.0)
    eng.last_equity = last_equity
    return eng


def _run(eng, bars, members, state=None, now=MON_OPEN, **kw):
    box = {"state": dict(state or {}), "events": []}
    out = ml.run_momo_cycle(
        eng, bot_id=BOT, fetch_bars=lambda syms, start: {s: bars[s] for s in syms if s in bars},
        fetch_universe=kw.get("universe", lambda: (members, "test")),
        vault={"BIL", "VOO"}, cash_park={"SGOV"},
        read_state=lambda: box["state"], write_state=lambda st: box.update(state=st),
        kill_tripped=lambda: False, unpark=lambda e, live: None,
        park=lambda e, live, cash: None, alert=lambda sev, msg: box["events"].append((sev, msg)),
        risk_check=lambda: {"allowed": True, "reasons": []}, soft=0.15, hard=0.22, now=now)
    return out, box["state"], box["events"]


def test_first_cycle_buys_the_top_50_with_stops_and_leaves_old_holdings_out():
    bars = universe(80)
    bars["SPY"] = series(0.0004, 400.0)
    bars["DBMF"] = series(0.0, 25.0)
    members = sorted(s for s in bars if s.startswith("S"))
    eng = _engine(bars, positions={"DBMF": 100, "BIL": 25.0},
                  rows=[{"symbol": "DBMF", "qty": 100, "stop_price": 1.0, "stop_order_id": None}])
    out, st, events = _run(eng, bars, members)
    # 10:30 NY on Mon 2 Nov: the last completed session is Fri 30 Oct, so the signal month is October.
    assert out["status"].startswith("rebalanced (2026-10|in|normal, monthly)"), events
    held = {s for s, q in eng.pos.items() if q >= 1}
    assert held - {"BIL"} == set(st["names"]) and len(st["names"]) == 50
    assert "DBMF" not in eng.pos and eng.pos["BIL"] == 25.0                # old holding sold, vault untouched
    assert all(s in eng.stops for s in st["names"])                        # every name has its 20% stop
    out2, st2, _ = _run(eng, bars, members, state=st)
    assert out2["status"] == "no rebalance due"


def test_universe_failure_trades_nothing_and_alerts_critical():
    bars = universe(10)
    bars["SPY"] = series(0.0004, 400.0)
    eng = _engine(bars)

    def broken():
        raise su.UniverseUnavailable("both sources down")

    out, _, events = _run(eng, bars, [], universe=broken)
    assert out["status"] == "universe unavailable: no trading" and not eng.orders
    assert events and events[0][0] == "critical"


def test_brake_sells_the_book_midmonth_and_stays_out_until_next_month():
    crash = date(2026, 11, 3)
    bars = universe(80, crash_from=None)
    bars["SPY"] = series(0.0004, 400.0)
    members = sorted(s for s in bars if s.startswith("S"))
    eng = _engine(bars)
    tue = datetime(2026, 11, 3, 15, 30, tzinfo=timezone.utc)               # signal day Mon 2 Nov: November
    bars = {k: v + ([{"day": date(2026, 11, 3), "close": v[-1]["close"]}] if v[-1]["day"] == date(2026, 11, 2) else [])
            for k, v in bars.items()}
    _, st, _ = _run(eng, bars, members, now=tue)
    assert st["month"] == "2026-11" and st["held"] == "in"
    # the book collapses over the next weeks (the market does not): index below its 100-day average
    later = weekdays(date(2026, 11, 3), date(2026, 11, 20))
    for s in st["names"]:
        last = bars[s][-1]["close"]
        bars[s] = [b for b in bars[s] if b["day"] < crash] + [{"day": d, "close": last * 0.96 ** (k + 1)}
                                                             for k, d in enumerate(later)]
    spy_base = [b for b in bars["SPY"] if b["day"] < crash]
    bars["SPY"] = spy_base + [{"day": d, "close": spy_base[-1]["close"] * 1.001 ** (k + 1)}
                              for k, d in enumerate(later)]
    for s in st["names"]:
        eng.px[s] = bars[s][-1]["close"]
    eng.px["SPY"] = bars["SPY"][-1]["close"]
    now = datetime(2026, 11, 23, 15, 30, tzinfo=timezone.utc)
    out, st2, _ = _run(eng, bars, members, state=st, now=now)
    assert st2["trend_on"] is False and st2["held"] == "out" and st2["why"] == "brake"
    assert not [s for s in st2["names"] if eng.pos.get(s, 0) >= 1]          # the whole book is in cash
    out3, st3, _ = _run(eng, bars, members, state=st2, now=now + timedelta(days=1))
    assert out3["status"] == "no rebalance due"                             # stays out until December


def test_a_stopped_name_stays_out_at_a_midmonth_resize():
    days = weekdays(date(2025, 6, 2), date(2026, 11, 4))
    bars = {f"S{i:03d}": series(0.0001 * i, days=days) for i in range(80)}
    bars["SPY"] = series(0.0004, 400.0, days=days)
    members = sorted(s for s in bars if s.startswith("S"))
    eng = _engine(bars, last_equity=100_000.0)
    tue = datetime(2026, 11, 3, 15, 30, tzinfo=timezone.utc)            # signal day Mon 2 Nov
    _, st, _ = _run(eng, bars, members, now=tue)
    assert st["month"] == "2026-11" and st["why"] == "monthly"
    victim = st["names"][0]
    eng.pos.pop(victim)                                                 # its 20% stop filled at the broker
    eng.stops.pop(victim, None)
    eng.last_equity = 84_000.0                                          # 16% below the mark: soft mode
    wed = tue + timedelta(days=1)                                       # signal day Tue 3 Nov: same month
    out, st2, _ = _run(eng, bars, members, state=st, now=wed)
    assert st2["why"] == "mode" and st2["key"] == "2026-11|in|soft"
    assert st2["stopped"] == [victim]
    assert eng.pos.get(victim, 0) == 0                                  # not re-bought before December
    held = [s for s in st2["names"] if eng.pos.get(s, 0) >= 1]
    assert len(held) == 49


def test_placeholder_sectors_count_as_missing():
    # 20 Nov 2026: SSGA's Sector column held "-" for all 500 members.
    rows = [{"ticker": "AAPL", "sector": "-"}, {"ticker": "MSFT", "sector": "Information Technology"}]
    by = su.sectors(rows, ["AAPL", "MSFT", "XOM"])
    assert by == {"AAPL": "", "MSFT": "Information Technology", "XOM": ""}
    assert su.sector_share(by) == 1 / 3 and su.sector_share({}) == 0.0


def test_ivv_sectors_for_given_members():
    text = ('Ticker,Name,Sector,Asset Class,Market Value,Weight (%)\n'
            'AAPL,APPLE INC,Information Technology,Equity,1,7.0\n'
            'BRKB,BERKSHIRE HATHAWAY INC CLASS B,Financials,Equity,1,1.7\n')
    got = su.load_ivv_sectors(lambda url: text.encode() if url == su.IVV_URL else b"", ["AAPL", "BRK.B", "XOM"])
    assert got == {"AAPL": "Information Technology", "BRK.B": "Financials", "XOM": ""}
