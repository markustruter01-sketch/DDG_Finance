"""Every Alpaca call has a time limit (16 Nov 2026 order-path audit, F5).

A broker that accepts the connection and then never answers must not stall a
bot: the call gives up after its time limit and raises a time-out, which the
order code already treats as an unclear answer (look the order up by its
client id, never send it again; covered by kraken-bot/test_lost_order_replies.py).
"""
from __future__ import annotations

import socket
import threading
import time

import pytest
import requests

from core.broker_http import TIMEOUT, TimeLimitedSession, alpaca_rest, with_time_limit

FAST = (1.0, 0.5)  # connect, read: short so the tests stay quick


@pytest.fixture
def silent_broker():
    """A server that accepts connections and reads the request, then never answers."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    conns: list[socket.socket] = []
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conns.append(conn)  # keep it open; never reply
            except OSError:
                continue

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}"
    stop.set()
    t.join(1)
    for c in conns:
        c.close()
    srv.close()


def _gives_up_quickly(call) -> None:
    started = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout):
        call()
    assert time.monotonic() - started < 5, "the call waited far longer than its time limit"


def test_the_session_adds_a_time_limit_to_every_call(silent_broker):
    session = TimeLimitedSession(FAST)
    _gives_up_quickly(lambda: session.get(silent_broker + "/v2/account"))


def test_a_caller_can_still_ask_for_its_own_time_limit(silent_broker):
    session = TimeLimitedSession((1.0, 30.0))
    _gives_up_quickly(lambda: session.get(silent_broker + "/v2/account", timeout=(1.0, 0.5)))


def test_the_default_limit_is_finite():
    connect, read = TIMEOUT
    assert 0 < connect <= 30 and 0 < read <= 120


def test_alpaca_trade_api_client_gives_up_on_a_silent_broker(silent_broker):
    api = alpaca_rest("key", "secret", base_url=silent_broker, timeout=FAST)
    assert isinstance(api._session, TimeLimitedSession)
    _gives_up_quickly(api.get_account)


def test_an_order_to_a_silent_broker_raises_a_time_out_and_is_sent_once(silent_broker):
    """The library must not resend after a time-out (a resend could double the order)."""
    api = alpaca_rest("key", "secret", base_url=silent_broker, timeout=FAST)
    calls = []
    real = api._session.request

    def counting(method, url, **kw):
        calls.append((method, url))
        return real(method, url, **kw)

    api._session.request = counting
    _gives_up_quickly(lambda: api.submit_order(symbol="SPY", qty=1, side="buy", type="market",
                                               time_in_force="day", client_order_id="test-f5-1"))
    assert [m for m, _ in calls] == ["POST"]


@pytest.mark.parametrize("make", ["trading", "stock_data", "crypto_data"])
def test_alpaca_py_clients_get_a_time_limited_session(make):
    from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    client = {
        "trading": lambda: TradingClient("key", "secret", paper=True),
        "stock_data": lambda: StockHistoricalDataClient("key", "secret"),
        "crypto_data": lambda: CryptoHistoricalDataClient("key", "secret"),
    }[make]()
    assert isinstance(with_time_limit(client)._session, TimeLimitedSession)


def test_alpaca_py_trading_client_gives_up_on_a_silent_broker(silent_broker):
    from alpaca.trading.client import TradingClient

    client = with_time_limit(TradingClient("key", "secret", paper=True, url_override=silent_broker), FAST)
    _gives_up_quickly(client.get_account)


def test_a_client_without_a_session_is_returned_unchanged():
    class Odd:
        pass

    odd = Odd()
    assert with_time_limit(odd) is odd
