"""Forex overnight financing for the pretend accounts (audit AU5). Figures by hand."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

import twins  # noqa: F401
from twins import financing
from twins.config import DAILY, HOURLY
from twins.engine import NEW_YORK

ALL_DAYS = {d: 1 for d in financing.WEEKDAYS} | {"WEDNESDAY": 3, "SATURDAY": 0, "SUNDAY": 0}


def instrument(name, long_rate, short_rate, days=None):
    return {"name": name, "financing": {"longRate": str(long_rate), "shortRate": str(short_rate),
            "financingDaysOfWeek": [{"dayOfWeek": k, "daysCharged": v} for k, v in (days or ALL_DAYS).items()]}}


def all_pairs(**over):
    return [over.get(p) or instrument(p, -0.01, 0.005) for p in financing.pairs()]


def test_parse_reads_rates_and_weekday_days():
    rows = {r["pair"]: r for r in financing.parse(all_pairs(USD_CHF=instrument("USD_CHF", 0.031, -0.052)))}
    assert rows["USD_CHF"]["long_rate"] == 0.031 and rows["USD_CHF"]["short_rate"] == -0.052
    assert rows["USD_CHF"]["days_charged"]["WEDNESDAY"] == 3


def test_parse_fails_loud_on_missing_rates_or_pairs():
    bad = all_pairs(EUR_USD={"name": "EUR_USD", "financing": {}})
    with pytest.raises(ValueError, match="no financing"):
        financing.parse(bad)
    with pytest.raises(ValueError, match="missing"):
        financing.parse(all_pairs()[1:])


def rate(day, pair, long_rate, short_rate):
    return {"day": day, "pair": pair, "long_rate": long_rate, "short_rate": short_rate, "days_charged": ALL_DAYS}


def test_daily_line_pays_by_side_weekday_and_rates_of_the_evening_before():
    days = [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)]          # Mon, Tue, Wed
    curve = [(d, 100_000.0, 0.0) for d in days]
    bars = {"CHF_USD": [{"day": d, "close": 1.25} for d in days],
            "EUR_USD": [{"day": d, "close": 1.10} for d in days]}
    open_at = datetime.combine(days[0], datetime.min.time(), NEW_YORK) + timedelta(hours=9, minutes=30)
    fills = [{"filled_at": open_at, "symbol": "CHF_USD", "n": 0, "qty": 40_000.0},     # long CHF = short USD_CHF
             {"filled_at": open_at, "symbol": "EUR_USD", "n": 0, "qty": -10_000.0}]    # short EUR_USD
    rates = [rate(date(2026, 11, 22), "USD_CHF", 0.03, -0.05), rate(date(2026, 11, 22), "EUR_USD", -0.02, 0.01),
             rate(date(2026, 11, 24), "USD_CHF", 0.03, -0.073)]   # read Tue evening: used from Wed
    out, info = financing.apply(curve, fills, bars, DAILY, rates)
    chf_notional, eur_notional = 40_000 * 1.25, 10_000 * 1.10
    mon = chf_notional * -0.05 / 365 + eur_notional * 0.01 / 365
    wed = 3 * (chf_notional * -0.073 / 365 + eur_notional * 0.01 / 365)
    assert out[0][1] == pytest.approx(100_000 + mon)
    assert out[1][1] == pytest.approx(100_000 + 2 * mon)
    assert out[2][1] == pytest.approx(100_000 + 2 * mon + wed)
    assert info["rolls_charged"] == 6 and info["no_rate_rolls"] == 0


def test_no_rate_no_charge_and_hourly_charges_only_at_the_17h_roll():
    start = datetime(2026, 11, 23, 15, 0, tzinfo=NEW_YORK)                     # 15:00, 16:00 (closes 17:00), 17:00
    steps = [start + timedelta(hours=i) for i in range(3)]
    curve = [(s, 50_000.0, 0.0) for s in steps]
    bars = {"EUR_USD": [{"day": s, "close": 1.0} for s in steps]}
    fills = [{"filled_at": steps[0], "symbol": "EUR_USD", "n": 0, "qty": 20_000.0}]
    out, info = financing.apply(curve, fills, bars, HOURLY, [])
    assert [p[1] for p in out] == [50_000.0] * 3 and info["no_rate_rolls"] == 1
    out, info = financing.apply(curve, fills, bars, HOURLY, [rate(date(2026, 11, 20), "EUR_USD", -0.02, 0.01)])
    charge = 20_000 * -0.02 / 365
    assert [round(p[1], 6) for p in out] == [50_000.0, round(50_000 + charge, 6), round(50_000 + charge, 6)]
    assert info["rolls_charged"] == 1


from twins_pg import make_get_conn, needs_pg  # noqa: E402


@needs_pg
def test_rates_are_stored_once_per_day_and_never_rewritten():
    from twins import store
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    rows = financing.parse(all_pairs())

    class Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def tradeable_instruments(self): return all_pairs()
    now = datetime(2026, 11, 20, 17, 15, tzinfo=NEW_YORK)
    assert financing.read_and_record(get_conn, now, client_factory=Client) == len(rows) == 7
    assert financing.read_and_record(get_conn, now, client_factory=Client) == 0       # same day: kept
    stored = store.fx_rates(get_conn)
    assert {r["pair"] for r in stored} == set(financing.pairs()) and stored[0]["day"] == date(2026, 11, 20)
    with get_conn() as conn, conn.cursor() as cur, pytest.raises(Exception, match="append-only"):
        cur.execute("UPDATE twin_fx_financing SET long_rate = 0")
