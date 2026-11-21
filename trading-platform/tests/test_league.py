"""Shadow League (roadmap Phase 1): each family's holdings checked by hand on
made-up prices, the shared rebalance rule, and one night end to end on a
throwaway Postgres. No network."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

import twins  # noqa: F401  (puts research_harness on the path)
from research_harness.harness.portfolio import HistoryView
from research_harness.league import base, families as fam
from research_harness.sleeves import core_v1
from twins import league, store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

# ── made-up market ────────────────────────────────────────────────────────────
CAL = tuple(date(2024, 1, 1) + timedelta(days=i) for i in range(1100)
            if (date(2024, 1, 1) + timedelta(days=i)).weekday() < 5)


def bars_from(closes: list[float], days=CAL) -> list[dict]:
    days = days[-len(closes):]
    return [{"day": d, "open": c, "high": c, "low": c, "close": c} for d, c in zip(days, closes)]


def steady(rate: float, n: int = len(CAL), start: float = 100.0, wiggle: float = 0.0) -> list[float]:
    """Compound growth at ``rate`` per session, with an alternating +/- wiggle."""
    return [start * (1 + rate) ** i * (1 + (wiggle if i % 2 else -wiggle)) for i in range(n)]


def ctx(universe=(), sectors=None, cal=CAL):
    return base.Context(calendar=cal, universe=tuple(universe), sectors=sectors or {})


def view_at(bars, day):
    v = HistoryView(bars)
    v.today = day
    return v


# ── the shared pieces ─────────────────────────────────────────────────────────
def test_with_cash_parks_the_rest_in_bills_and_refuses_borrowing():
    assert base.with_cash({"SPY": 0.6}) == {"BIL": 0.4, "SPY": 0.6}
    assert base.with_cash({}) == {"BIL": 1.0}
    assert base.with_cash({"SPY": 1.0}) == {"SPY": 1.0}
    with pytest.raises(ValueError):
        base.with_cash({"SPY": 0.7, "QQQ": 0.4})
    with pytest.raises(ValueError):
        base.with_cash({"SPY": -0.1})


def test_calendar_helpers():
    assert base.is_month_start(CAL, date(2026, 11, 2)) and not base.is_month_start(CAL, date(2026, 11, 3))
    assert base.is_week_start(CAL, date(2026, 11, 16)) and not base.is_week_start(CAL, date(2026, 11, 17))
    assert base.month_sessions(CAL, date(2026, 11, 4)) == [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]


def test_monthly_rule_sends_on_month_start_and_on_a_state_change_only():
    flips = {date(2026, 11, 11)}       # state changes on this session

    def target(view, c):
        return base.Call({"SPY": 1.0}, state="b" if view.today >= min(flips) else "a")

    s = base.Strategy("X", "trend", "x", "monthly", ("SPY",), target)
    bars = {"SPY": bars_from(steady(0.0))}
    v = HistoryView(bars)
    assert base.decide(s, v, ctx(), date(2026, 11, 5), has_decision=False) is not None   # first ever
    assert base.decide(s, v, ctx(), date(2026, 11, 5), has_decision=True) is None        # mid-month, same
    assert base.decide(s, v, ctx(), date(2026, 11, 11), has_decision=True) is not None   # state changed
    assert base.decide(s, v, ctx(), date(2026, 11, 12), has_decision=True) is None
    assert base.decide(s, v, ctx(), date(2026, 12, 1), has_decision=True) is not None    # new month


# ── yardsticks ────────────────────────────────────────────────────────────────
def test_yardsticks_hold_fixed_mixes():
    bars = {s: bars_from(steady(0.0003)) for s in ("SPY", "AGG", "BIL")}
    v = HistoryView(bars)
    d = date(2026, 11, 2)
    assert base.decide(fam.BY_ID["Y-SPX"], v, ctx(), d, False).weights == {"SPY": 1.0}
    assert base.decide(fam.BY_ID["Y-SPX"], v, ctx(), date(2026, 12, 1), True) is None     # bought once
    assert base.decide(fam.BY_ID["Y-6040"], v, ctx(), d, True).weights == {"AGG": 0.4, "SPY": 0.6}
    assert base.decide(fam.BY_ID["Y-CASH"], v, ctx(), d, False).weights == {"BIL": 1.0}


# ── trend and gearing ─────────────────────────────────────────────────────────
def test_cap_1_5_is_exactly_the_atlas_rule():
    for rate, wiggle in ((0.001, 0.0), (0.001, 0.02), (-0.001, 0.0), (0.0004, 0.006)):
        c = steady(rate, 300, wiggle=wiggle)
        v, e = fam.atlas_exposure(c, 1.5)
        assert v == core_v1.votes(c)
        assert e == pytest.approx(core_v1.target_exposure(v, core_v1.vol20(c)))


def test_atlas_holdings_by_hand_at_1x_1_5x_2x_and_cash():
    up = {s: bars_from(steady(0.001)) for s in ("SPY", "QQQ", "SSO", "QLD", "BIL")}   # calm rise: 3 votes, s = 1
    v = HistoryView(up)
    d = date(2026, 11, 2)
    w1 = base.decide(fam.BY_ID["T-1X"], v, ctx(), d, False).weights
    assert w1 == pytest.approx({"SPY": 0.6, "QQQ": 0.4})                        # E = 1: all in 1x funds
    w15 = base.decide(fam.BY_ID["T-15X"], v, ctx(), d, False).weights
    # E = 1.5: each index half in its 1x fund, half in its 2x fund, x 0.99; 1% to bills
    assert w15 == pytest.approx({"SPY": 0.297, "SSO": 0.297, "QQQ": 0.198, "QLD": 0.198, "BIL": 0.01})
    w2 = base.decide(fam.BY_ID["T-2X"], v, ctx(), d, False).weights
    assert w2 == pytest.approx({"SSO": 0.594, "QLD": 0.396, "BIL": 0.01})         # E = 2: all in 2x funds
    down = {s: bars_from(steady(-0.001)) for s in ("SPY", "QQQ", "SSO", "QLD", "BIL")}
    assert base.decide(fam.BY_ID["T-15X"], HistoryView(down), ctx(), d, False).weights == {"BIL": 1.0}


def test_f1_is_65_percent_core_and_35_percent_cross_asset():
    bars = {s: bars_from(steady(0.001)) for s in ("SPY", "QQQ", "SSO", "QLD", "BIL")}
    for s in ("IEF", "GLD", "DBC", "UUP"):
        bars[s] = bars_from(steady(0.0005, wiggle=0.005))
    v = HistoryView(bars)
    d = date(2026, 11, 2)
    w = base.decide(fam.BY_ID["T-F1"], v, ctx(), d, False).weights
    x = fam.xasset_v1.target_weights(view_at(bars, d))
    assert set(x) == {"IEF", "GLD", "DBC", "UUP"}
    for s in x:
        assert w[s] == pytest.approx(0.35 * x[s])
    assert w["SPY"] == pytest.approx(0.65 * 0.297)


# ── diversifiers ──────────────────────────────────────────────────────────────
def test_gold_trend_all_in_or_out():
    up = {"SPY": bars_from(steady(0.0)), "GLD": bars_from(steady(0.001)), "BIL": bars_from(steady(0.0))}
    assert base.decide(fam.BY_ID["D-GOLD"], HistoryView(up), ctx(), date(2026, 11, 2), False).weights == {"GLD": 1.0}
    down = {**up, "GLD": bars_from(steady(-0.001))}
    assert base.decide(fam.BY_ID["D-GOLD"], HistoryView(down), ctx(), date(2026, 11, 2), False).weights == {"BIL": 1.0}


def test_risk_parity_weights_by_hand():
    # Alternating +/-w moves: each return is about +-2w, so the volatility is in proportion to w.
    bars = {"SPY": bars_from(steady(0.0, wiggle=0.01)), "IEF": bars_from(steady(0.0, wiggle=0.005)),
            "GLD": bars_from(steady(0.0, wiggle=0.01))}
    w = base.decide(fam.BY_ID["D-RP"], HistoryView(bars), ctx(), date(2026, 11, 2), False).weights
    # 1/vol in the ratio 1 : 2 : 1  ->  25% / 50% / 25% (to within the made-up series' rounding)
    assert w["SPY"] == pytest.approx(0.25, abs=0.002)
    assert w["IEF"] == pytest.approx(0.50, abs=0.002)
    assert w["GLD"] == pytest.approx(0.25, abs=0.002)


# ── short-term ────────────────────────────────────────────────────────────────
def test_dip_enters_on_a_5_session_low_in_an_uptrend_and_leaves_on_the_bounce():
    c = steady(0.002, 260)
    x = c[-1]                                    # the 4 closes before it are x/1.002 ... x/1.002^4 (0.992 x)
    assert fam.dip_state(c + [x * 0.995]) == "out"           # a dip, but not the lowest of 5
    c += [x * 0.99]                                           # the lowest of 5, above the 200-session average
    assert fam.dip_state(c) == "in"
    assert fam.dip_state(c + [x * 0.985]) == "in"            # still below its 5-session average
    assert fam.dip_state(c + [x * 1.01]) == "out"            # bounced above it


def test_dip_leaves_after_5_sessions_held():
    c = steady(0.002, 260)
    x = c[-1]
    c += [x * 0.99, x * 0.97, x * 0.96, x * 0.95, x * 0.94]  # entered, then 4 sessions held, still falling
    assert fam.dip_state(c) == "in"
    assert fam.dip_state(c + [x * 0.93]) == "out"            # the 5th session held


def test_turn_of_month_by_hand():
    cal = CAL
    assert fam.tom_state(date(2026, 11, 25), cal) == "out"      # Wed: 3 weekdays left
    assert fam.tom_state(date(2026, 11, 27), cal) == "in"       # Fri: only Mon 30 left -> buy at its open
    assert fam.tom_state(date(2026, 11, 30), cal) == "in"       # last weekday
    assert fam.tom_state(date(2026, 12, 1), cal) == "in"        # 1st session
    assert fam.tom_state(date(2026, 12, 2), cal) == "in"        # 2nd
    assert fam.tom_state(date(2026, 12, 3), cal) == "out"       # decided at the 3rd close: sell next open


# ── stock picking ─────────────────────────────────────────────────────────────
def stock_market(n=60, cal=CAL):
    """n names; name k rises at a rate growing with k (k = n-1 strongest), and the
    volatility shrinks with k for the first 30 (S00 calmest)."""
    bars = {"SPY": bars_from(steady(0.0003), cal), "BIL": bars_from(steady(0.0), cal)}
    names = [f"S{k:02d}" for k in range(n)]
    for k, s in enumerate(names):
        bars[s] = bars_from(steady(0.0002 + 0.00002 * k, wiggle=0.001 + 0.0002 * k), cal)
    return bars, names


def test_defensive_picks_the_50_calmest():
    bars, names = stock_market()
    call = base.decide(fam.BY_ID["S-DEF"], HistoryView(bars), ctx(names), date(2026, 11, 2), False)
    assert sorted(n for n in call.weights if n != "BIL") == names[:50]
    assert all(call.weights[n] == pytest.approx(0.02) for n in names[:50])


def test_momentum_picks_the_top_50_at_2_percent_times_s():
    bars, names = stock_market()
    call = base.decide(fam.BY_ID["S-MOMO"], HistoryView(bars), ctx(names), date(2026, 11, 2), False)
    held = sorted(n for n in call.weights if n != "BIL")
    assert held == names[10:]                       # the 50 fastest risers
    slot = call.weights[held[0]]
    assert 0 < slot <= 0.02 and all(call.weights[n] == slot for n in held)


def test_sector_cap_allows_at_most_12_names_per_sector():
    bars, names = stock_market(80)
    sectors = {n: ("Tech" if k >= 50 else f"Other{k % 5}") for k, n in enumerate(names)}
    call = base.decide(fam.BY_ID["S-MOMO-CAP"], HistoryView(bars), ctx(names, sectors), date(2026, 11, 2), False)
    held = [n for n in call.weights if n != "BIL"]
    assert len(held) == 50
    assert sorted(n for n in held if sectors[n] == "Tech") == names[68:]   # only the 12 strongest Tech names
    assert sorted(n for n in held if sectors[n] != "Tech") == names[12:50]  # then the next-best others


def test_momentum_brake_goes_to_cash_mid_month_and_waits_for_the_next_month():
    bars, names = stock_market()
    fall_from = date(2026, 11, 10)
    for s in names:                                  # every name drops 15% on 10 Nov and stays there
        bars[s] = [dict(b, close=b["close"] * (0.85 if b["day"] >= fall_from else 1.0),
                        open=b["open"] * (0.85 if b["day"] >= fall_from else 1.0),
                        high=b["high"] * (0.85 if b["day"] >= fall_from else 1.0),
                        low=b["low"] * (0.85 if b["day"] >= fall_from else 1.0)) for b in bars[s]]
    v = HistoryView(bars)
    momo, weekly = fam.BY_ID["S-MOMO"], fam.BY_ID["S-MOMO-CAP"]
    assert base.decide(momo, v, ctx(names), date(2026, 11, 10), True).weights == {"BIL": 1.0}   # brake
    assert base.decide(momo, v, ctx(names), date(2026, 11, 11), True) is None                   # stays out
    # Weekly re-entry needs the index back above its 100-session average: not by 16 Nov here.
    assert base.decide(weekly, v, ctx(names), date(2026, 11, 16), True) is None


def test_league_copies_of_book_index_and_brakes_match_the_live_momentum_code():
    from sleeve_runtime import momo_live

    bars, names = stock_market(55)
    sel, upto = date(2026, 6, 1), date(2026, 11, 13)
    live = momo_live.book_index(bars, names[:50], sel, upto)
    mine = fam.book_index(view_at(bars, upto), names[:50], sel)
    assert mine == pytest.approx(live)
    levels = [x for _, x in live]
    b = momo_live.brakes(live)
    assert fam.brakes(levels) == (b["trend_on"], pytest.approx(b["s"]))
    assert (fam.MOMO_TOP, fam.MOMO_TREND, fam.MOMO_VOL, fam.MOMO_VOL_TARGET) == (
        momo_live.TOP_N, momo_live.TREND_SESSIONS, momo_live.VOL_SESSIONS, momo_live.VOL_TARGET)


def test_f1_split_matches_the_live_fleet():
    from twins.config import FLEET_F1_SPLIT
    assert fam.F1_SPLIT == FLEET_F1_SPLIT          # test_twins_config.py ties that to fleet_live.F1


# ── the catalogue and its registrations ───────────────────────────────────────
def test_every_strategy_has_a_registration_and_no_crypto_anywhere():
    from core.no_crypto import is_crypto

    assert len(fam.STRATEGIES) == 19 and len(fam.BY_ID) == 19         # incl. FX-BT1-CAP (21 Nov); + FX-COUNCIL = 20 lines
    assert sum(1 for s in fam.STRATEGIES if s.family == "yardstick") == 3
    for s in fam.STRATEGIES:
        reg = league.load_registration(s.id)
        assert reg is not None, s.id
        for field in ("rules", "universe", "rebalance_day", "stops", "leverage", "costs", "pass_bar",
                      "data_needed", "status"):
            assert reg.get(field), (s.id, field)
    assert not [s for s in fam.fixed_symbols() if is_crypto(s)]


def test_run_days_catches_up_a_short_outage_and_reports_a_long_one():
    days, skipped = league.run_days(CAL, None, date(2026, 11, 18))
    assert days == [date(2026, 11, 18)] and skipped == 0
    days, skipped = league.run_days(CAL, date(2026, 11, 13), date(2026, 11, 18))
    assert days == [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)] and skipped == 0
    days, skipped = league.run_days(CAL, date(2026, 10, 1), date(2026, 11, 18))
    assert len(days) == league.CATCH_UP_SESSIONS and skipped > 0


# ── one night end to end ──────────────────────────────────────────────────────
LIVE_CAL = tuple(d for d in CAL if d <= date(2026, 11, 18))


def fake_fetch(symbols, start):
    bars, names = stock_market(60, LIVE_CAL)
    for s in ("QQQ", "SSO", "QLD", "AGG", "IEF", "GLD", "DBC", "UUP", "RSP"):
        bars[s] = bars_from(steady(0.0005, len(LIVE_CAL), wiggle=0.004), LIVE_CAL)
    return {s: [b for b in bars.get(s, []) if b["day"] >= start] for s in symbols if s in bars}


def fake_fx_now(pairs):
    """OANDA-shaped daily candles closing on every weekday up to 18 Nov 2026."""
    from research_harness.league import forex as fx
    out = {}
    for k, p in enumerate(pairs):
        rows, px = [], 1.0 + k / 10
        for i, d in enumerate(LIVE_CAL):
            px *= 1.0004 * (1.003 if i % 2 else 0.997) if k % 2 else 0.9996 * (1.003 if i % 2 else 0.997)
            opened = datetime.combine(d - timedelta(days=1), time(17, 0), NEW_YORK)
            rows.append({"time": opened.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                         "complete": True, "mid": {"o": str(px), "h": str(px * 1.002), "l": str(px * 0.998),
                                                   "c": str(px)}})
        out[p] = rows
    assert set(out) <= set(fx.PAIRS)
    return out


def fake_universe():
    _, names = stock_market(60, LIVE_CAL)
    return tuple(names), {n: f"Sector{i % 8}" for i, n in enumerate(names)}, "test"


@needs_pg
def test_two_nights_start_every_line_value_it_and_keep_the_chain(tmp_path):
    from twins import job

    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    alarms = []
    now = datetime.combine(date(2026, 11, 17), time(17, 15), NEW_YORK)
    report, bars = league.run(get_conn, now, date(2026, 11, 17), fetch_daily=fake_fetch, universe_loader=fake_universe,
                              fetch_fx_daily=fake_fx_now)
    assert report["started"] and len(report["started"]) == 19   # 18 + FX-BT1-CAP (21 Nov)
    accts = [a for a in store.accounts(get_conn) if a["bot_id"] == league.LEAGUE_BOT]
    assert len(accts) == 19 and all(a["start_equity"] == 100_000 for a in accts)
    assert all(a["config"]["registration_hash"] for a in accts)
    for a in accts:                                  # every line decided on its first night
        rows = store.decisions(get_conn, a["twin_id"])
        assert rows and not rows[0]["missed"], a["twin_id"]
        if a["config"]["family"] != "forex":
            assert abs(sum(rows[-1]["weights"].values()) - 1.0) < 1e-6
    # The second night runs through the twins job, which replays and values every line.
    now2 = datetime.combine(date(2026, 11, 18), time(17, 15), NEW_YORK)
    from test_twins_job import _platform_tables
    _platform_tables(get_conn)          # no real accounts in this test: the bot twins do not start
    out = job.nightly(now2, record_fx_rates=lambda g, n: 0, ai_call=False, get_conn=get_conn, fetch_daily=fake_fetch, universe_loader=fake_universe,
                      fetch_fx_daily=fake_fx_now,
                      fetch_hourly=lambda pairs, start: {},
                      alarm=lambda *a, **k: alarms.append(a), resolve=lambda *a: None, commit="abc1234")
    assert out.get("error") is None, out
    assert isinstance(out["league"], dict), out["league"]
    for a in accts:
        eq = store.equity_rows(get_conn, a["twin_id"])
        assert [r["day"] for r in eq][-1] == date(2026, 11, 18), a["twin_id"]
        assert all(r["equity"] and r["equity"] > 0 for r in eq)
    assert not [a for a in alarms if a[1] in ("twin_replay_failed", "league_failed", "twin_ledger_broken")], alarms
    # Nothing new to say on a re-run of the same night: decisions are not repeated.
    before = {a["twin_id"]: len(store.decisions(get_conn, a["twin_id"])) for a in accts}
    league.run(get_conn, now2, date(2026, 11, 18), fetch_daily=fake_fetch, universe_loader=fake_universe,
               fetch_fx_daily=fake_fx_now)
    assert before == {a["twin_id"]: len(store.decisions(get_conn, a["twin_id"])) for a in accts}


@needs_pg
def test_no_member_list_is_a_missed_decision_for_stock_lines_only():
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)

    def broken():
        raise RuntimeError("down")

    now = datetime.combine(date(2026, 11, 17), time(17, 15), NEW_YORK)
    report, _ = league.run(get_conn, now, date(2026, 11, 17), fetch_daily=fake_fetch, universe_loader=broken)
    assert report["universe"].startswith("unavailable")
    for sid in ("S-MOMO", "S-MOMO-CAP", "S-DEF"):
        rows = store.decisions(get_conn, league.twin_id(sid))
        assert rows and all(r["missed"] for r in rows)
    assert not store.decisions(get_conn, league.twin_id("Y-SPX"))[0]["missed"]


def test_load_universe_takes_sectors_from_ivv_when_ssga_has_none(monkeypatch):
    import sleeve_runtime.sp500_universe as su

    names = [f"N{i:03d}" for i in range(10)]
    monkeypatch.setattr(su, "load_sp500_rows",
                        lambda get: (names, [{"ticker": n, "sector": "-"} for n in names], "ssga_spy"))
    ivv = "Ticker,Name,Sector,Asset Class,Market Value,Weight (%)\n" + "".join(
        f"{n},CO {n},Sector{i % 3},Equity,1,1\n" for i, n in enumerate(names))
    tickers, sectors, source = league.load_universe(lambda url: ivv.encode())
    assert tickers == tuple(names) and source == "ssga_spy; sectors from ishares_ivv"
    assert sectors["N004"] == "Sector1" and all(sectors.values())

    def no_ivv(url):
        raise OSError("down")
    tickers, sectors, source = league.load_universe(no_ivv)
    assert source == "ssga_spy; no sectors (ishares_ivv OSError, wikipedia OSError)"
    assert not any(sectors.values())                                   # kept empty, not invented


def test_load_universe_falls_back_to_wikipedia_when_ivv_returns_a_web_page(monkeypatch):
    # 20 Nov 2026: the IVV link returned a page with no CSV in it, and the label still said "ishares_ivv".
    import sleeve_runtime.sp500_universe as su

    names = ["AAPL", "BRK.B", "XOM", "JPM"]
    monkeypatch.setattr(su, "load_sp500_rows",
                        lambda get: (names, [{"ticker": n, "sector": "-"} for n in names], "ssga_spy"))
    wiki = ('<table class="wikitable" id="constituents"><tbody>'
            '<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th></tr>'
            '<tr><td><a href="#">AAPL</a></td><td>Apple Inc.</td><td>Information Technology</td><td>x</td></tr>'
            '<tr><td><a href="#">BRK.B</a></td><td>Berkshire Hathaway</td><td>Financials</td><td>x</td></tr>'
            '<tr><td>XOM</td><td>ExxonMobil</td><td>Energy</td><td>x</td></tr>'
            '<tr><td>JPM</td><td>JPMorgan Chase</td><td>Financials</td><td>x</td></tr>'
            '</tbody></table><table id="changes"><tr><th>Symbol</th><th>GICS Sector</th></tr>'
            '<tr><td>OLD</td><td>Energy</td></tr></table>')
    page = lambda url: (wiki if url == su.WIKI_SP500_URL else '<html>productTicker: "ivv",</html>').encode()
    tickers, sectors, source = league.load_universe(page)
    assert source == "ssga_spy; sectors from wikipedia"
    assert sectors == {"AAPL": "Information Technology", "BRK.B": "Financials", "XOM": "Energy", "JPM": "Financials"}


def test_wikipedia_parser_ignores_other_tables_and_non_gics_values():
    import sleeve_runtime.sp500_universe as su
    html = ('<table id="constituents"><tr><th>Symbol</th><th>GICS Sector</th></tr>'
            '<tr><td>BF-B</td><td>Consumer Staples</td></tr><tr><td>ZZZ</td><td>Not a sector</td></tr></table>'
            '<table id="other"><tr><th>Symbol</th><th>GICS Sector</th></tr><tr><td>Q</td><td>Energy</td></tr></table>')
    assert su.parse_wikipedia_sectors(html) == {"BF.B": "Consumer Staples"}
    assert su.parse_wikipedia_sectors("<html>no table</html>") == {}


@needs_pg
def test_sector_cap_line_misses_the_night_without_a_sector_list():
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    now = datetime.combine(date(2026, 11, 17), time(17, 15), NEW_YORK)

    def no_sectors():
        names, _, src = fake_universe()
        return names, {n: "" for n in names}, src
    report, _ = league.run(get_conn, now, date(2026, 11, 17), fetch_daily=fake_fetch, universe_loader=no_sectors,
                           fetch_fx_daily=fake_fx_now)
    cap = store.decisions(get_conn, league.twin_id("S-MOMO-CAP"))
    assert cap and all(r["missed"] for r in cap)
    assert report[league.twin_id("S-MOMO-CAP")].endswith("S&P 500 sector list unavailable")
    momo = store.decisions(get_conn, league.twin_id("S-MOMO"))
    assert momo and not momo[0]["missed"]                       # the uncapped line is unaffected
