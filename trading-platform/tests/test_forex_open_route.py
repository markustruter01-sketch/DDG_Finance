"""GET /forex/open: OANDA balance and open trades, read-only."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import core.oanda_client as oc
from routes.forex_council_log import forex_open


class FakeClient:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def account_summary(self):
        return {"currency": "USD", "balance": Decimal("100000"), "nav": Decimal("101000.5"), "margin_used": Decimal("2000")}
    def open_trades(self):
        return [{"instrument": "EUR_USD", "currentUnits": "-39040", "price": "1.15", "unrealizedPL": "120.5",
                 "stopLossOrder": {"price": "1.13433"}, "openTime": "2026-11-18T21:00:00Z"},
                {"instrument": "USD_CHF", "currentUnits": "37013", "price": "0.80", "openTime": "x"}]


def test_open_trades_are_read_and_shaped(monkeypatch):
    monkeypatch.setattr(oc, "OandaClient", FakeClient)
    out = asyncio.run(forex_open())
    assert out["nav"] == 101000.5 and out["balance"] == 100000.0
    assert out["open"][0] == {"pair": "EUR_USD", "side": "sell", "units": 39040.0, "entry": 1.15, "stop": 1.13433,
                              "unrealized_usd": 120.5, "opened": "2026-11-18T21:00:00Z"}
    assert out["open"][1]["side"] == "buy" and out["open"][1]["stop"] is None
