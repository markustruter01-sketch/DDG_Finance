"""OANDA practice order client: request shape and response parsing (no network)."""
from __future__ import annotations

import json

import httpx
import pytest

from core import oanda_trader
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

    monkeypatch.setenv("RUNNER_ENVIRONMENT", "published")
    res = _trader(monkeypatch, handler).market_order("EUR_USD", 41666, "1.06920")
    assert seen["url"] == "https://api-fxpractice.oanda.com/v3/accounts/101-001-1-001/orders"
    client_id = res["client_id"]
    assert client_id.startswith("pub-fx-eur_usd-") and len(client_id) <= 48
    assert seen["body"] == {"order": {"type": "MARKET", "instrument": "EUR_USD", "units": "41666",
                                      "timeInForce": "FOK", "positionFill": "OPEN_ONLY",
                                      "stopLossOnFill": {"price": "1.06920", "timeInForce": "GTC"},
                                      "clientExtensions": {"id": client_id, "tag": "forex_ai"},
                                      "tradeClientExtensions": {"id": f"{client_id}-t", "tag": "forex_ai"}}}
    assert res == {"filled": True, "trade_id": "6410", "price": "1.08120", "units": "41666", "reason": None,
                   "client_id": client_id, "unclear": False}


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
    monkeypatch.setattr(oanda_trader, "LOOKUP_PAUSE_SECONDS", 0)

    def handler(request):
        raise httpx.ConnectError(f"boom {request.headers['Authorization']}")

    with pytest.raises(OandaClientError) as err:
        _trader(monkeypatch, handler).close_trade("77")
    assert TOKEN not in str(err.value) and err.value.__cause__ is None
    res = _trader(monkeypatch, handler).market_order("EUR_USD", 1, "1.0")
    assert res["unclear"] is True and TOKEN not in res["reason"]


class _Oanda:
    """Answers the order POST with ``post`` (a status, or an exception), then
    read-backs of GET orders/@<client id> from ``reads`` in turn."""

    def __init__(self, post, reads):
        self.post, self.reads, self.posts, self.read_paths = post, list(reads), 0, []

    def __call__(self, request):
        if request.method == "POST":
            self.posts += 1
            if isinstance(self.post, Exception):
                raise self.post
            return httpx.Response(self.post, json={})
        self.read_paths.append(request.url.path)
        answer = self.reads.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer[0], json=answer[1])


@pytest.mark.parametrize(("post", "reads", "expected"), [
    # 504, but OANDA filled it: adopted with OANDA's trade id
    (504, [(200, {"order": {"state": "FILLED", "tradeOpenedID": "6411"}})],
     {"filled": True, "trade_id": "6411", "unclear": False}),
    # 401 (the auth check timing out): never reached the book
    (401, [(404, {"errorMessage": "The Order specified does not exist"})],
     {"filled": False, "trade_id": None, "unclear": False}),
    # connection lost; first read 401, second shows the FOK cancel
    (httpx.ReadTimeout("lost"), [(401, {}), (200, {"order": {"state": "CANCELLED"}})],
     {"filled": False, "trade_id": None, "unclear": False}),
    # nothing can be read: unclear, reported as possibly filled
    (502, [(503, {}), httpx.ConnectError("x"), (401, {})],
     {"filled": False, "trade_id": None, "unclear": True}),
])
def test_unclear_order_answer_is_read_back_never_resent(monkeypatch, post, reads, expected):
    monkeypatch.setattr(oanda_trader, "LOOKUP_PAUSE_SECONDS", 0)
    oanda = _Oanda(post, reads)
    res = _trader(monkeypatch, oanda).market_order("EUR_USD", 41666, "1.06920")
    assert oanda.posts == 1
    assert {k: res[k] for k in expected} == expected
    assert all(path.endswith(f"/orders/@{res['client_id']}") for path in oanda.read_paths)


def test_zero_or_fractional_units_are_refused(monkeypatch):
    trader = _trader(monkeypatch, lambda r: httpx.Response(500))
    for bad in (0, 1.5):
        with pytest.raises(ValueError):
            trader.market_order("EUR_USD", bad, "1.0")
