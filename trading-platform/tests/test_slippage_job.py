"""Execution cost from real fills: signs and references by hand, the nightly
read on a fake broker and a throwaway Postgres, and no order calls."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as O

import pytest

from core import slippage_job as sj
from twins_pg import make_get_conn, needs_pg

T = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731


def test_cost_is_signed_as_a_cost():
    assert sj.cost_bps("buy", 100.05, 100.0) == 5.0       # paid 5 bps more
    assert sj.cost_bps("sell", 99.95, 100.0) == 5.0       # got 5 bps less
    assert sj.cost_bps("buy", 99.99, 100.0) == -1.0       # a better price is a negative cost


def test_model_matches_the_league_cost_model():
    import twins  # noqa: F401
    from twins.config import SHARE_COSTS
    assert sj.MODEL_BPS == SHARE_COSTS.half_spread_bps + SHARE_COSTS.slippage_bps + SHARE_COSTS.commission_bps


def test_reference_is_the_first_minute_at_or_after_sending():
    bars = [{"t": "2026-11-18T14:31:00Z", "o": 101.0}, {"t": "2026-11-18T14:30:00Z", "o": 100.0}]
    assert sj.first_minute_open(bars, T("2026-11-18T14:30:42")) == 100.0
    assert sj.first_minute_open(bars, T("2026-11-18T09:00:00")) == 100.0      # queued before the open
    assert sj.first_minute_open(bars, T("2026-11-18T14:32:00")) is None


def order(**kw):
    base = dict(id="o1", symbol="SPY", side="buy", type="market", filled_qty="10", filled_avg_price="100.03",
                submitted_at="2026-11-18T14:30:42Z", filled_at="2026-11-18T14:30:43Z", stop_price=None, legs=None)
    return O(**{**base, **kw})


def bars_at(*_):
    return [{"t": "2026-11-18T14:30:00Z", "o": 100.0}]


def test_measure_market_stop_and_what_is_left_out():
    r = sj.measure("oracle", order(), bars_at)
    assert r["slippage_bps"] == 3.0 and r["ref_kind"] == "minute_open_at_submit"
    s = sj.measure("oracle", order(type="stop", side="sell", stop_price="95", filled_avg_price="94.81"), bars_at)
    assert s["slippage_bps"] == 20.0 and s["ref_kind"] == "stop_price"     # gapped 0.2% through the stop
    assert sj.measure("oracle", order(type="limit"), bars_at) is None
    assert sj.measure("oracle", order(filled_qty="0"), bars_at) is None
    assert sj.measure("oracle", order(symbol="BTC/USD"), bars_at) is None
    assert sj.measure("oracle", order(), lambda *a: []) is None             # no price: not guessed
    assert sj.measure("oracle", vars(order()), bars_at)["slippage_bps"] == 3.0   # a leg as a plain dict


class FakeApi:
    def __init__(self, orders, fail=False):
        self.orders, self.fail = orders, fail

    def list_orders(self, **kw):
        if self.fail:
            raise RuntimeError("401")
        assert kw["status"] == "closed"
        return self.orders

    def get_bars(self, symbol, tf, **kw):
        assert tf == "1Min"
        return O(_raw=bars_at())


@needs_pg
def test_nightly_read_stores_once_and_an_unreadable_account_is_reported():
    get_conn = make_get_conn()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS execution_slippage")
    stop_leg = order(id="o2", type="stop", side="sell", stop_price="95", filled_avg_price="94.81",
                     filled_at="2026-11-19T15:00:00Z")
    apis = {"oracle": FakeApi([order(legs=[stop_leg])]), "jerome_macro": FakeApi([], fail=True),
            "spy_qqq_trend": FakeApi([order(id="o3", type="limit")])}
    now = T("2026-11-19T22:50:00")
    rep = sj.run_daily(now, api_factory=apis.__getitem__, get_conn=get_conn)
    assert rep == {"oracle": {"measured": 2}, "jerome_macro": "unreadable: RuntimeError",
                   "spy_qqq_trend": {"measured": 0}}
    assert sj.run_daily(now, api_factory=apis.__getitem__, get_conn=get_conn)["oracle"] == {"measured": 0}
    s = sj.summary(get_conn, date(2026, 11, 1))
    assert s["groups"]["oracle:market"] == {"fills": 1, "median_bps": 3.0, "mean_bps": 3.0}
    assert s["groups"]["oracle:stop"]["median_bps"] == 20.0
    assert s["market_fills"] == {"fills": 1, "median_bps": 3.0, "above_model": False}


def test_runs_while_trading_is_paused_and_names_no_order_call():
    from core import scheduler as cs
    from test_twins_isolation import ORDER_WORDS

    assert "slippage_daily" in cs._ALWAYS_ACTIVE_JOBS
    src = Path(sj.__file__).read_text()
    assert not [w for w in ORDER_WORDS if w in src]
