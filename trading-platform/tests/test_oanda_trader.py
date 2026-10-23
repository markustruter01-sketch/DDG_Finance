"""OANDA practice order client: request shape and response parsing (no network)."""
from __future__ import annotations

import json

import httpx
import pytest

from core.oanda_client import OandaClientError
from core.oanda_trader import OandaTrader

TOKEN = "secret-token-never-logged"


def _trader(monkeypatch, handler):
    monkeypatch.setenv("OANDA_API_TOKEN", TOKEN)
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "101-001-1-001")
    return OandaTrader(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_market_order_goes_to_practice_with_its_stop_and_reads_the_trade_id(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(201, json={"orderFillTransaction": {
            "price": "1.08120", "tradeOpened": {"tradeID": "6410", "units": "41666", "price": "1.08120"}}})

    res = _trader(monkeypatch, handler).market_order("EUR_USD", 41666, "1.06920")
    assert seen["url"] == "https://api-fxpractice.oanda.com/v3/accounts/101-001-1-001/orders"
    assert seen["body"] == {"order": {"type": "MARKET", "instrument": "EUR_USD", "units": "41666",
                                      "timeInForce": "FOK", "positionFill": "OPEN_ONLY",
                                      "stopLossOnFill": {"price": "1.06920", "timeInForce": "GTC"}}}
    assert res == {"filled": True, "trade_id": "6410", "price": "1.08120", "units": "41666", "reason": None}


@pytest.mark.parametrize(("status", "payload", "reason"), [
    (201, {"orderCancelTransaction": {"reason": "MARKET_HALTED"}}, "MARKET_HALTED"),
    (400, {"orderRejectTransaction": {"rejectReason": "INSUFFICIENT_MARGIN"}}, "INSUFFICIENT_MARGIN"),
    (400, {"errorCode": "STOP_LOSS_ON_FILL_LOSS"}, "STOP_LOSS_ON_FILL_LOSS"),
])
def test_unfilled_orders_report_why(monkeypatch, status, payload, reason):
    res = _trader(monkeypatch, lambda r: httpx.Response(status, json=payload)).market_order("EUR_USD", -5, "1.1")
    assert res["filled"] is False and res["reason"] == reason


def test_close_trade_whole_and_already_gone(monkeypatch):
    seen = {}

    def handler(request):
        seen["method"], seen["body"] = request.method, json.loads(request.content)
        if request.url.path.endswith("/trades/77/close"):
            return httpx.Response(200, json={"orderFillTransaction": {"price": "1.0801", "pl": "-12.50"}})
        return httpx.Response(404, json={"errorMessage": "The Trade specified does not exist"})

    trader = _trader(monkeypatch, handler)
    assert trader.close_trade("77") == {"closed": True, "already_closed": False, "price": "1.0801",
                                        "pl": "-12.50", "reason": None}
    assert seen == {"method": "PUT", "body": {"units": "ALL"}}
    assert trader.close_trade("78")["already_closed"] is True


def test_network_errors_never_carry_the_token(monkeypatch):
    def handler(request):
        raise httpx.ConnectError(f"boom {request.headers['Authorization']}")

    with pytest.raises(OandaClientError) as err:
        _trader(monkeypatch, handler).market_order("EUR_USD", 1, "1.0")
    assert TOKEN not in str(err.value) and err.value.__cause__ is None


def test_zero_or_fractional_units_are_refused(monkeypatch):
    trader = _trader(monkeypatch, lambda r: httpx.Response(500))
    for bad in (0, 1.5):
        with pytest.raises(ValueError):
            trader.market_order("EUR_USD", bad, "1.0")
