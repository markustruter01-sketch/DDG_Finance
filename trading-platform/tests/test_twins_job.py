"""AI twins jobs end to end on a throwaway Postgres: start, mirror, baselines,
the mirror check and its alarm, the change log. Fake prices; no network."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from twins import config, job, store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

D0, D1, D2, D3 = date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)
SESSIONS = (D0, D1, D2, D3)
# (open, close) per session; anything not listed trades flat at 100.
PRICES = {
    "SPY": {D0: (600, 600), D1: (600, 602), D2: (603, 606), D3: (606, 600)},
    "SSO": {D0: (100, 100), D1: (100, 101), D2: (101, 102), D3: (102, 100)},
    "QQQ": {D0: (500, 500), D1: (500, 505), D2: (506, 510), D3: (510, 505)},
}


def ny(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), NEW_YORK)


def fetch_daily(symbols, start):
    out = {}
    for s in symbols:
        rows = []
        for d in SESSIONS:
            if d < start:
                continue
            o, c = PRICES.get(s, {}).get(d, (100, 100))
            rows.append({"day": d, "open": float(o), "high": float(max(o, c)), "low": float(min(o, c)),
                         "close": float(c)})
        out[s] = rows
    return out


FX_NOW = {"t": None}


def fetch_hourly(pairs, start):
    """Flat prices with a 1 pip spread, complete hourly candles up to FX_NOW."""
    out = {}
    t = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = []
    while t + timedelta(hours=1) <= FX_NOW["t"]:
        hours.append(t)
        t += timedelta(hours=1)
    for p in pairs:
        px = 150.0 if p.startswith("USD_JPY") else 1.25
        pip = 0.01 if "JPY" in p else 0.0001
        out[p] = [{"time": f"{h:%Y-%m-%dT%H:%M:%S}.000000000Z", "complete": True,
                   "mid": {k: str(px) for k in "ohlc"},
                   "bid": {k: str(px - pip / 2) for k in "ohlc"},
                   "ask": {k: str(px + pip / 2) for k in "ohlc"}} for h in hours]
    return out


def _platform_tables(get_conn):
    schema = (Path(__file__).resolve().parents[1] / "db" / "postgres.py").read_text()
    ddl = [re.search(rf"CREATE TABLE IF NOT EXISTS {t} \(.*?\);", schema, re.S).group(0)
           for t in ("bots_state", "bot_portfolio")]
    with get_conn() as conn, conn.cursor() as cur:
        for d in ddl:
            cur.execute(d)
        for bot, paused, meta in (("oracle", False, {}), ("jerome_macro", False, {}),
                                  ("spy_qqq_trend", False, {"momo_v2": {"names": ["AAPL", "MSFT"]}}),
                                  ("forex_ai", False, {})):
            cur.execute("INSERT INTO bots_state (bot_id, paused, metadata) VALUES (%s, %s, %s::jsonb)",
                        (bot, paused, json.dumps(meta)))


def _account(get_conn, bot, cash, positions, at, equity=0.0):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO bot_portfolio (bot_id, cash_usd, equity_usd, positions, last_updated)
                       VALUES (%s, %s, %s, %s::jsonb, %s)
                       ON CONFLICT (bot_id) DO UPDATE SET cash_usd = EXCLUDED.cash_usd,
                         equity_usd = EXCLUDED.equity_usd, positions = EXCLUDED.positions,
                         last_updated = EXCLUDED.last_updated""",
                    (bot, cash, equity, json.dumps(positions), at))


def _shares(**qty):
    return [{"symbol": s, "qty": str(q), "side": "long"} for s, q in qty.items()]


def _forex(units):
    return [{"instrument": "EUR_USD", "long": {"units": str(max(units, 0))}, "short": {"units": str(min(units, 0))}}]


class Alarms:
    def __init__(self):
        self.raised, self.resolved = [], []

    def alarm(self, severity, error_type, message, bot_id=None):
        self.raised.append((error_type, bot_id, message))

    def resolve(self, error_type):
        self.resolved.append(error_type)


def _night(get_conn, day, alarms, commit="abc1234"):
    FX_NOW["t"] = ny(day, 17, 15)
    return job.nightly(ny(day, 17, 15), get_conn=get_conn, fetch_daily=fetch_daily, fetch_hourly=fetch_hourly,
                       alarm=alarms.alarm, resolve=alarms.resolve, commit=commit,
                       with_league=False,   # the league has its own tests (test_league.py)
                       record_fx_rates=lambda get_conn, now: 0)   # financing: test_twins_financing.py


def _hour(get_conn, day, alarms):
    FX_NOW["t"] = ny(day, 16, 55)
    return job.hourly(ny(day, 16, 55), get_conn=get_conn, fetch_hourly=fetch_hourly, alarm=alarms.alarm,
                      commit="abc1234")


def _row(get_conn, twin_id, day):
    return next(r for r in store.equity_rows(get_conn, twin_id) if r["day"] == day)


@needs_pg
def test_three_nights_start_mirror_baselines_check_and_alarm(monkeypatch):
    # An owner-kept line, as BTC was until 17 Nov (the live list is empty now; the mechanism stays).
    import core.bot_registry as reg
    monkeypatch.setattr(reg, "OWNER_KEPT", {"jerome_macro": frozenset({"BTCUSD"})})
    get_conn = make_get_conn()
    _platform_tables(get_conn)
    alarms = Alarms()

    # ── Mon 16 Nov: the first night creates every twin from the real accounts ──
    oracle_cash = 100_000 - 100 * 602 - 200 * 101          # what is left after its holdings (close value)
    _account(get_conn, "oracle", oracle_cash, _shares(SPY=100, SSO=200), ny(D1, 15, 45))
    _account(get_conn, "jerome_macro", 20_000, _shares(SPY=50) + [{"symbol": "BTCUSD", "qty": "0.1", "side": "long"}],
             ny(D1, 15, 50))
    _account(get_conn, "spy_qqq_trend", 99_000, _shares(SGOV=10), ny(D1, 15, 40))
    _account(get_conn, "forex_ai", 100_000, _forex(40_000), ny(D1, 16, 5), equity=100_000)
    report = _night(get_conn, D1, alarms)
    assert report.get("error") is None, report
    ids = {a["twin_id"] for a in store.accounts(get_conn)}
    assert ids == {s.twin_id for s in config.phase_a_twins()}
    starts = {a["twin_id"]: a["start_equity"] for a in store.accounts(get_conn)}
    assert starts["oracle:mirror:v1"] == starts["oracle:baseline_spy:v1"] == 100_000.0
    assert starts["jerome_macro:mirror:v1"] == 20_000 + 50 * 602          # BTC (owner-kept) left out
    assert starts["forex_ai:mirror:v1"] == starts["forex_ai:baseline_spy:v1"] == 100_000.0
    momo = store.decisions(get_conn, "spy_qqq_trend:baseline_full:v1")
    assert momo[-1]["weights"] == {"AAPL": 0.5, "MSFT": 0.5}
    kinds = [store.last_change(get_conn, ("publish",))["detail"]["commit"]]
    assert kinds == ["abc1234"]

    # ── Tue 17 Nov: Atlas sells its SSO and buys 100 QQQ at the open ──
    oracle_cash += 200 * 101 - 100 * 506                   # traded at the 17 Nov opens (SSO 101, QQQ 506)
    _account(get_conn, "oracle", oracle_cash, _shares(SPY=100, QQQ=100), ny(D2, 15, 45))
    _account(get_conn, "jerome_macro", 20_000, _shares(SPY=50), ny(D2, 15, 50))
    _account(get_conn, "spy_qqq_trend", 99_000, _shares(SGOV=10), ny(D2, 15, 40))
    _account(get_conn, "forex_ai", 100_000, _forex(-40_000), ny(D2, 16, 5), equity=100_000)
    assert _hour(get_conn, D2, alarms)["forex"] == "changed"
    report = _night(get_conn, D2, alarms)
    assert report.get("error") is None, report
    oracle_mirror = store.decisions(get_conn, "oracle:mirror:v1")
    assert [d["inputs"]["qty"] for d in oracle_mirror] == [{"SPY": 100.0, "SSO": 200.0}, {"QQQ": 100.0, "SPY": 100.0}]

    # ── Wed 18 Nov: an unexplained 5,000 appears in Atlas's real account ──
    _account(get_conn, "oracle", oracle_cash + 5_000, _shares(SPY=100, QQQ=100), ny(D3, 15, 45))
    _account(get_conn, "jerome_macro", 20_000, _shares(SPY=50), ny(D3, 15, 50))
    _account(get_conn, "spy_qqq_trend", 99_000, _shares(SGOV=10), ny(D3, 15, 40))
    _account(get_conn, "forex_ai", 100_000, _forex(-40_000), ny(D3, 16, 5), equity=100_000)
    _hour(get_conn, D3, alarms)
    report = _night(get_conn, D3, alarms)
    assert report.get("error") is None, report

    # The mirror tracked the real account to within costs while the account was explained...
    d2 = _row(get_conn, "oracle:mirror:v1", D2)
    assert d2["gap_pp"] == 0.0                              # the base day
    jerome = _row(get_conn, "jerome_macro:mirror:v1", D3)
    assert abs(jerome["gap_pp"]) < 0.01
    # ...and the unexplained 5,000 (about 5%) raised the alarm for Atlas only.
    d3 = _row(get_conn, "oracle:mirror:v1", D3)
    assert d3["gap_pp"] < -4.5
    assert [(e, b) for e, b, _ in alarms.raised] == [("twin_mirror_drift", "oracle")]
    tonight = alarms.resolved[alarms.resolved.index("twin_replay_failed", len(alarms.resolved) - 6):]
    assert tonight[0] == "twin_replay_failed" and tonight[-1] == "twin_job_failed"
    assert "twin_mirror_drift" not in tonight                                  # drift stays open
    fx = [_row(get_conn, "forex_ai:mirror:v1", d)["gap_pp"] for d in (D1, D2, D3)]
    assert fx[0] is None and fx[1] == 0.0 and abs(fx[2]) < 0.01   # flat prices: only the spread
    assert report["chains"] == {}

    # Baseline by hand: 100,000 into SPY at the 17 Nov open (603) less 5 bps, marked at 600.
    spy = _row(get_conn, "oracle:baseline_spy:v1", D3)
    assert spy["equity"] == pytest.approx(100_000 - 100_000 * 5e-4 + 100_000 / 603 * (600 - 603))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM twin_fills WHERE twin_id = 'oracle:mirror:v1'")
        fills_before = cur.fetchone()[0]
    _night(get_conn, D3, alarms)                           # a re-run of the same night
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM twin_fills WHERE twin_id = 'oracle:mirror:v1'")
        assert cur.fetchone()[0] == fills_before
    assert len(store.decisions(get_conn, "oracle:mirror:v1")) == 2   # same holdings: no new decision


@needs_pg
def test_pause_resume_and_publish_land_in_the_change_log_once():
    get_conn = make_get_conn()
    _platform_tables(get_conn)
    store.ensure_schema(get_conn)
    now = ny(D1, 12)
    assert job.capture_changes(get_conn, now, "abc1234") == ["publish:abc1234"]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE bots_state SET paused = TRUE, pause_reason = 'owner', paused_at = %s "
                    "WHERE bot_id = 'oracle'", (now,))
    assert job.capture_changes(get_conn, now, "abc1234") == ["oracle:pause"]
    assert job.capture_changes(get_conn, now, "abc1234") == []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE bots_state SET paused = FALSE WHERE bot_id = 'oracle'")
    assert job.capture_changes(get_conn, now, "def5678") == ["oracle:resume", "publish:def5678"]


@needs_pg
def test_an_unreadable_account_is_a_missed_read_not_a_guess():
    get_conn = make_get_conn()
    _platform_tables(get_conn)
    alarms = Alarms()
    _account(get_conn, "oracle", 50_000, _shares(SPY=10), ny(D1, 15, 45))
    _account(get_conn, "jerome_macro", 20_000, _shares(SPY=50), ny(D1, 15, 50))
    _account(get_conn, "spy_qqq_trend", 99_000, [], ny(D1, 15, 40))
    _account(get_conn, "forex_ai", 100_000, [], ny(D1, 16, 5), equity=100_000)
    _night(get_conn, D1, alarms)
    _account(get_conn, "oracle", 50_000, _shares(SPY=10), ny(D2, 11, 0))       # stale: before the last hour
    report = _night(get_conn, D2, alarms)
    assert report["share_close"]["oracle"].startswith("missed")
    rows = store.decisions(get_conn, "oracle:mirror:v1")
    assert rows[-1]["missed"] and rows[-1]["weights"] is None
    assert not any(r["day"] == D2 and r["ref_equity"] for r in store.equity_rows(get_conn, "oracle:mirror:v1"))


@needs_pg
def test_mirror_gap_uses_the_value_recorded_on_the_day_so_a_dividend_counts_once():
    # 100 shares at 100, 1.00 dividend: ex-date D2 (price 99), cash paid D3. The real account
    # is worth 10,000 / 9,900 / 10,000. The mirror (total-return prices) stays at 10,000.
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    tid = "oracle:mirror:v1"
    store.create_account(get_conn, twin_id=tid, bot_id="oracle", kind="mirror", version=1, bars="alpaca_daily",
                         start_at=ny(D0, 16), start_equity=10_000.0, config={})
    for day, real in ((D0, 10_000.0), (D1, 10_000.0), (D2, 9_900.0), (D3, 10_000.0)):
        store.record_ref(get_conn, tid, day, real, ny(day, 16), {"cash": 0.0, "qty": {"SPY": 100.0}})
    store.upsert_equity(get_conn, tid, [(d, 10_000.0, 1.0) for d in (D0, D1, D2, D3)])
    acct = store.accounts(get_conn)[0]
    assert job.check_mirror(get_conn, acct, None) == 0.0          # after the pay date: no gap left
    gaps = {r["day"]: r["gap_pp"] for r in store.equity_rows(get_conn, tid)}
    assert gaps == {D0: None, D1: 0.0, D2: 1.0, D3: 0.0}          # open only between ex-date and pay date


def test_simulator_symbols_map_back_to_real_oanda_pairs():
    # 17-19 Nov: the Forex twin asked OANDA for "CHF_USD" (no such pair, HTTP 400).
    from research_harness.league.forex import PAIRS
    from twins import engine
    from twins.job import _pair_of

    assert _pair_of("CHF_USD") == "USD_CHF"
    assert _pair_of("JPY_USD") == "USD_JPY"
    assert _pair_of("EUR_USD") == "EUR_USD"
    assert sorted(_pair_of(engine.synthetic(p)) for p in PAIRS) == sorted(PAIRS)
