"""Markus's own pretend account (twins/human.py). No orders; same engine as the bots."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

import twins  # noqa: F401
from twins import human, store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

NY = lambda y, m, d, h=12, mi=0: datetime(y, m, d, h, mi, tzinfo=NEW_YORK)


def test_catalog_has_every_class_and_two_way_currencies():
    cats = {c["id"]: c for c in human.catalog(["AAPL", "MSFT"])}
    assert [a["symbol"] for a in cats["shares"]["assets"]] == ["AAPL", "MSFT"]
    assert "SPY" in [a["symbol"] for a in cats["index"]["assets"]]
    assert cats["fx"]["two_way"] and "USD_CHF" in [a["symbol"] for a in cats["fx"]["assets"]]
    assert "shares" not in {c["id"] for c in human.catalog([])}           # no list today: no share class


def test_fill_step_never_looks_ahead():
    assert human.step_for(NY(2026, 11, 25, 8, 0)) == date(2026, 11, 24)      # before the open: fills today's open
    assert human.step_for(NY(2026, 11, 25, 11, 0)) == date(2026, 11, 25)     # in the session: next open
    assert human.step_for(NY(2026, 11, 28, 11, 0)) == date(2026, 11, 27)     # Saturday: Monday's open
    assert human.version_for(NY(2026, 12, 31, 15)) == 0 and human.version_for(NY(2027, 1, 2)) == 1


@needs_pg
def test_trades_rules_reasons_and_account_view():
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    now = NY(2026, 11, 23, 11)
    t = lambda **k: human.trade(get_conn, now, members=["AAPL"], **k)
    out = t(asset="SPY", side="buy", percent=40, reason="Trend is up and rates look steady")
    assert out["weights"] == {"BIL": 0.6, "SPY": 0.4} and out["fills_at_open_after"] == "2026-11-23"
    out = t(asset="USD_CHF", side="buy", percent=30, reason="Dollar strength against the franc")
    assert out["weights"] == {"BIL": 0.3, "CHF_USD": -0.3, "SPY": 0.4}
    for bad, msg in ((dict(asset="AAPL", side="buy", percent=40, reason="too much in one go"), "limit is 100%"),
                     (dict(asset="QQQ", side="sell", percent=10, reason="short the nasdaq please"), "sold short"),
                     (dict(asset="SPY", side="buy", percent=10, reason="why"), "reason"),
                     (dict(asset="TSLA", side="buy", percent=10, reason="not in the index list"), "not on the list")):
        with pytest.raises(ValueError, match=msg):
            t(**bad)
    out = t(asset="SPY", side="buy", percent=0, reason="Taking profit before the holidays")
    assert out["weights"] == {"BIL": 0.7, "CHF_USD": -0.3}
    view = human.account(get_conn)["accounts"][0]
    assert view["label"] == "Practice" and [h["asset"] for h in view["target"]] == ["USD_CHF"]
    assert view["target"][0]["percent"] == 30.0
    assert view["trades"][0]["reason"] == "Taking profit before the holidays" and len(view["trades"]) == 3
    assert not store.verify_chain(store.decisions(get_conn, human.twin_id(0)))


@needs_pg
def test_replay_mixes_shares_and_currencies_and_shows_on_the_board(monkeypatch):
    from twins import job, leaderboard
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    human.trade(get_conn, NY(2026, 11, 20, 20), members=[], asset="SPY", side="buy", percent=50,
                reason="Half in the index to start")
    human.trade(get_conn, NY(2026, 11, 20, 20), members=[], asset="EUR_USD", side="sell", percent=20,
                reason="Euro looks weak this month")
    days = [date(2026, 11, 20) + timedelta(days=i) for i in range(10) if (date(2026, 11, 20) + timedelta(days=i)).weekday() < 5]
    bar = lambda d, px: {"day": d, "open": px, "high": px, "low": px, "close": px}
    bars = {"SPY": [bar(d, 600 + i) for i, d in enumerate(days) if d != date(2026, 11, 26)],   # US holiday
            "BIL": [bar(d, 91.0) for d in days if d != date(2026, 11, 26)],
            "EUR_USD": [bar(d, 1.10 - 0.002 * i) for i, d in enumerate(days)]}
    acct = next(a for a in store.accounts(get_conn) if a["twin_id"] == human.twin_id(0))
    res = job.replay_twin(get_conn, acct, bars)
    assert res.curve and res.curve[-1][1] > human.START_EQUITY            # index up, euro down: both made money
    assert {f["symbol"] for f in res.fills} >= {"SPY", "EUR_USD"}
    monkeypatch.setattr(job, "_portfolios", lambda *a: {})
    assert "SPY" in job.share_symbols(get_conn, {}) and "EUR_USD" not in job.share_symbols(get_conn, {})
    store.upsert_equity(get_conn, acct["twin_id"], list(res.curve))
    rows = leaderboard.read(get_conn)["rows"]
    assert any(r["id"] == "HUMAN" and r["kind"] == "human" for r in rows)
