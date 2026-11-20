"""Shadow League forex lines: FX-BT1 walked exactly as its registered
backtest, the simple currency trend by hand, OANDA candle labels, and one
night end to end (forex prices never go to Alpaca). No network."""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

import twins  # noqa: F401
from research_harness.harness.portfolio import HistoryView
from research_harness.league import base, families as fam
from research_harness.league import forex as fx
from twins import engine, league, store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

sys.path.append(str(Path(__file__).resolve().parents[2] / "kraken-bot"))

DAYS = tuple(date(2024, 1, 1) + timedelta(days=i) for i in range(650)
             if (date(2024, 1, 1) + timedelta(days=i)).weekday() < 5)
DAYS = tuple(d for d in DAYS if d <= date(2026, 10, 9))      # the backtest stops at its LAST_DAY


def walk(seed: int, drift: float, n: int = len(DAYS), start: float = 1.2, step: float = 0.006):
    """A random price path with a slowly turning drift (so trends start and stop)."""
    rnd, px, out = random.Random(seed), start, []
    for i in range(n):
        d = drift * (1 if (i // 120) % 2 == 0 else -1)
        o = px
        px = px * (1 + d + rnd.gauss(0, step))
        hi, lo = max(o, px) * (1 + abs(rnd.gauss(0, step / 2))), min(o, px) * (1 - abs(rnd.gauss(0, step / 2)))
        out.append({"day": DAYS[i], "open": o, "high": hi, "low": lo, "close": px})
    return out


def market():
    return {p: walk(seed=k, drift=0.0006 * (k + 1) / 4, start=1.0 + k / 10) for k, p in enumerate(fx.PAIRS)}


def test_constants_match_the_registered_rule():
    import forex_baseline_backtest as bt
    import forex_quant_desk as desk

    assert (fx.TREND_SMA_DAYS, fx.MOMENTUM_DAYS, fx.ATR_DAYS, fx.STOP_ATR_MULTIPLE) == (
        desk.TREND_SMA_DAYS, desk.MOMENTUM_DAYS, desk.ATR_DAYS, desk.STOP_ATR_MULTIPLE)
    assert (fx.RISK_PER_TRADE, fx.MAX_OPEN, fx.GROSS_CAP) == (bt.RISK_PER_TRADE, bt.MAX_OPEN, bt.GROSS_CAP)
    assert fx.PAIRS == tuple(desk.FOREX_PAIRS)
    assert all(fx.synthetic(p) == engine.synthetic(p) for p in fx.PAIRS)


def test_long_usd_jpy_is_short_yen():
    assert fx.signed_weight("USD_JPY", "long", 0.3) == ("JPY_USD", -0.3)
    assert fx.signed_weight("EUR_USD", "short", 0.3) == ("EUR_USD", -0.3)


def test_the_walk_trades_exactly_as_the_registered_backtest():
    """Same entries, exits and stops, day for day, as forex_baseline_backtest.run_backtest
    (bid = ask = mid here, so the backtest's prices equal the walk's)."""
    import forex_baseline_backtest as bt

    data = market()
    as_bt = {p: [{"day": b["day"], **{s + f: b[k] for s in ("b", "a")
                                      for f, k in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}}
                 for b in rows] for p, rows in data.items()}
    res = bt.run_backtest(as_bt)
    theirs = sorted((t["pair"], t["dir"], t["open"], t["close"], t["reason"]) for t in res["trades"])
    assert len(theirs) > 20 and {t[4] for t in theirs} == {"stop", "signal"}   # both exits happen
    view = HistoryView(data)
    view.today = DAYS[-1]
    trail: list = []
    pos = fx.bt1_positions(view, DAYS[0], trail)
    assert sorted(trail) == theirs
    assert len(pos) == res["open_at_end"]


def test_fx_bt1_weights_are_sized_to_half_a_percent_at_the_stop():
    data = market()
    view = HistoryView(data)
    view.today = DAYS[-1]
    pos = fx.bt1_positions(view, DAYS[0])
    call = base.decide(fam.BY_ID["FX-BT1"], view, base.Context(calendar=DAYS, start=DAYS[0]), DAYS[-1], False)
    assert len(pos) <= 4 and sum(q["w"] for q in pos.values()) <= 2.0 + 1e-9
    for p, q in pos.items():
        sym, w = fx.signed_weight(p, q["dir"], q["w"])
        assert call.weights[sym] == pytest.approx(w)
        assert abs(q["entry"] - q["stop"]) * q["w"] / q["entry"] == pytest.approx(0.005)  # loss at stop = 0.5%
    assert "BIL" not in call.weights


def test_simple_trend_by_hand():
    up = {p: [{"day": d, "open": 1.0 * 1.0005 ** i, "high": 1.0, "low": 1.0,
               "close": 1.0 * 1.0005 ** i * (1.004 if i % 2 else 0.996)} for i, d in enumerate(DAYS)]
          for p in fx.PAIRS}
    for p in up:
        for b in up[p]:
            b["high"], b["low"] = max(b["open"], b["close"]), min(b["open"], b["close"])
    call = base.decide(fam.BY_ID["FX-TREND"], HistoryView(up), base.Context(calendar=DAYS), DAYS[-1], False)
    vol = base.ann_vol([b["close"] for b in up["EUR_USD"]][-64:], 63)
    each = min(0.10 / vol / 7, 2.0 / 7)
    assert call.weights["EUR_USD"] == pytest.approx(each)               # rising: long euro
    assert call.weights["JPY_USD"] == pytest.approx(-each)              # rising USD_JPY: long dollar = short yen
    assert sum(abs(w) for w in call.weights.values()) <= 2.0 + 1e-9


def test_oanda_daily_candles_are_labelled_with_the_day_they_close():
    candles = {"USD_JPY": [{"time": "2026-11-18T22:00:00.000000000Z", "complete": True,
                            "mid": {"o": "150.0", "h": "151.0", "l": "149.0", "c": "150.5"}}],
               "EUR_USD": [{"time": "2026-11-18T22:00:00.000000000Z", "complete": True,
                            "mid": {"o": "1.1", "h": "1.0", "l": "1.0", "c": "1.1"}}]}   # bad: high < open
    bars = fx.bars_from_daily_candles(candles)
    assert bars["USD_JPY"][0]["day"] == date(2026, 11, 19)
    assert bars["JPY_USD"][0]["close"] == pytest.approx(1 / 150.5)
    assert bars["JPY_USD"][0]["high"] == pytest.approx(1 / 149.0)
    assert bars["EUR_USD"] == []                                        # bad candle left out, not repaired


# ── one night end to end ──────────────────────────────────────────────────────
def fake_fx(pairs):
    data = market()
    out = {}
    for p in pairs:
        rows = []
        for b in data[p]:
            opened = datetime.combine(b["day"] - timedelta(days=1), time(17, 0), NEW_YORK)
            rows.append({"time": opened.astimezone(engine.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                         "complete": True, "mid": {k: str(b[f]) for k, f in
                                                   (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}})
        out[p] = rows
    return out


@needs_pg
def test_forex_lines_start_trade_short_and_never_ask_alpaca_for_currencies():
    from test_league import fake_fetch, fake_universe
    from test_twins_job import _platform_tables
    from twins import job

    asked = set()

    def alpaca(symbols, start):
        asked.update(symbols)
        return fake_fetch(symbols, start)

    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    _platform_tables(get_conn)
    day = DAYS[-1]                                                    # Fri 9 Oct 2026
    now = datetime.combine(day, time(17, 15), NEW_YORK)
    report, _ = league.run(get_conn, now, day, fetch_daily=alpaca, universe_loader=fake_universe,
                           fetch_fx_daily=fake_fx)
    assert report["forex"] == "ok"
    for sid in ("FX-BT1", "FX-TREND"):
        acct = next(a for a in store.accounts(get_conn) if a["twin_id"] == league.twin_id(sid))
        assert acct["config"]["allow_short"] is True and acct["config"]["max_gross"] == 2.0
        rows = store.decisions(get_conn, acct["twin_id"])
        assert rows and not rows[0]["missed"]
    trend = store.decisions(get_conn, league.twin_id("FX-TREND"))[-1]["weights"]
    assert any(w < 0 for w in trend.values()) and "BIL" not in trend
    nxt = date(2026, 10, 12)
    out = job.nightly(datetime.combine(nxt, time(17, 15), NEW_YORK), record_fx_rates=lambda g, n: 0, ai_call=False, get_conn=get_conn, fetch_daily=alpaca,
                      universe_loader=fake_universe, fetch_fx_daily=lambda pairs: fake_fx_ext(pairs, nxt),
                      fetch_hourly=lambda pairs, start: {}, alarm=lambda *a, **k: None,
                      resolve=lambda *a: None, commit="abc1234")
    assert out.get("error") is None, out
    for sid in ("FX-BT1", "FX-TREND"):
        assert store.equity_rows(get_conn, league.twin_id(sid)), (sid, out["replay"].get(league.twin_id(sid)))
    assert not asked & {fx.synthetic(p) for p in fx.PAIRS} - {"SPY"}
    assert not asked & set(fx.PAIRS)


def fake_fx_ext(pairs, last):
    """fake_fx plus one more forex day closing on ``last``."""
    out = fake_fx(pairs)
    for p, rows in out.items():
        c = rows[-1]["mid"]["c"]
        opened = datetime.combine(last - timedelta(days=1), time(17, 0), NEW_YORK)
        rows.append({"time": opened.astimezone(engine.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                     "complete": True, "mid": {"o": c, "h": c, "l": c, "c": c}})
    return out


@needs_pg
def test_no_oanda_tonight_is_a_missed_decision_for_forex_lines_only():
    from test_league import fake_fetch, fake_universe

    def broken(pairs):
        raise RuntimeError("401")

    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    day = DAYS[-1]
    report, _ = league.run(get_conn, datetime.combine(day, time(17, 15), NEW_YORK), day, fetch_daily=fake_fetch,
                           universe_loader=fake_universe, fetch_fx_daily=broken)
    assert report["forex"].startswith("unavailable")
    assert all(r["missed"] for r in store.decisions(get_conn, league.twin_id("FX-BT1")))
    assert not store.decisions(get_conn, league.twin_id("Y-SPX"))[0]["missed"]


@needs_pg
def test_the_council_line_is_the_forex_mirror_on_the_board():
    from twins import leaderboard as lb

    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    start = datetime(2026, 11, 16, 22, tzinfo=engine.timezone.utc)
    store.create_account(get_conn, twin_id="forex_ai:mirror:v1", bot_id="forex_ai", kind="mirror", version=1,
                         bars="oanda_h1", start_at=start, start_equity=100_000.0,
                         config={"spread_bps": {}, "max_gross": 6.0, "allow_short": True})
    store.upsert_equity(get_conn, "forex_ai:mirror:v1", [(date(2026, 11, 17), 100_500.0, 1.0),
                                                         (date(2026, 11, 18), 101_000.0, 1.0)])
    for d, real in ((date(2026, 11, 17), 100_400.0), (date(2026, 11, 18), 100_900.0)):
        store.record_ref(get_conn, "forex_ai:mirror:v1", d, real, start)
    with get_conn() as conn, conn.cursor() as cur:       # Home's daily closes, which the board's real row uses
        cur.execute("DROP TABLE IF EXISTS bot_daily_returns")
        cur.execute("CREATE TABLE bot_daily_returns (bot_id TEXT, date DATE, equity_close DOUBLE PRECISION, source TEXT)")
        cur.execute("INSERT INTO bot_daily_returns VALUES ('forex_ai', '2026-11-17', 100400, NULL), "
                    "('forex_ai', '2026-11-18', 100900, NULL), ('forex_ai', '2026-11-01', 1, NULL)")
    rows = {r["id"]: r for r in lb.read(get_conn)["rows"]}
    assert rows["FX-COUNCIL"]["kind"] == "shadow" and rows["FX-COUNCIL"]["return_pct"] == 1.0   # engine value
    assert rows["forex_ai"]["kind"] == "real" and rows["forex_ai"]["equity"] == 100_900.0     # real value
