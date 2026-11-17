"""No crypto, anywhere (Markus, 17 Nov 2026).

An order that would buy crypto is refused before it leaves the machine, on every
path: the Alpaca libraries (through the session every client now uses), the old
Bot 3 sender and the OANDA order call. Selling (a stop, closing a holding) still
works, so the one remaining holding stays protected.
"""
from __future__ import annotations

import socket
import threading

import pytest

from core.broker_http import TimeLimitedSession
from core.no_crypto import CryptoTradingBlocked, is_crypto, refuse_crypto_buy


@pytest.mark.parametrize("symbol", ["BTC/USD", "BTCUSD", "ETH/USD", "ethusd", "SOL/USDT", "BTC_USD",
                                    "ETH-USD", "IBIT", "GBTC", "ETHA", "FBTC", "BITO"])
def test_coins_and_crypto_funds_count_as_crypto(symbol):
    assert is_crypto(symbol)


@pytest.mark.parametrize("symbol", ["SPY", "QQQ", "SGOV", "BIL", "GLD", "UUP", "DBC", "EUR_USD", "AUD_USD",
                                    "BRK-B", "LINK", "SKY", "", None])
def test_stocks_funds_and_currencies_do_not(symbol):
    assert not is_crypto(symbol)


def test_a_crypto_buy_is_refused_and_a_sell_passes():
    with pytest.raises(CryptoTradingBlocked):
        refuse_crypto_buy("BTC/USD", "buy", "test")
    refuse_crypto_buy("BTC/USD", "sell", "test")   # a stop or a close only reduces crypto
    refuse_crypto_buy("SPY", "buy", "test")


@pytest.fixture
def counting_server():
    """Counts connections; never answers."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    seen: list[socket.socket] = []
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                seen.append(srv.accept()[0])
            except OSError:
                continue

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}", seen
    stop.set()
    t.join(1)
    for c in seen:
        c.close()
    srv.close()


def test_the_broker_session_never_sends_a_crypto_buy(counting_server):
    url, seen = counting_server
    session = TimeLimitedSession((1.0, 0.3))
    with pytest.raises(CryptoTradingBlocked):
        session.post(url + "/v2/orders", json={"symbol": "BTC/USD", "side": "buy", "qty": "0.1"})
    assert seen == [], "the order must not even reach the broker"


def test_the_broker_session_still_sends_a_crypto_sell(counting_server):
    import requests

    url, seen = counting_server
    session = TimeLimitedSession((1.0, 0.3))
    with pytest.raises(requests.exceptions.Timeout):   # it was sent (the fake broker never answers)
        session.post(url + "/v2/orders", json={"symbol": "BTC/USD", "side": "sell", "qty": "0.1"})


def test_alpaca_trade_api_refuses_a_crypto_buy(counting_server):
    from core.broker_http import alpaca_rest

    url, seen = counting_server
    api = alpaca_rest("key", "secret", base_url=url, timeout=(1.0, 0.3))
    with pytest.raises(CryptoTradingBlocked):
        api.submit_order(symbol="BTC/USD", qty=0.1, side="buy", type="market", time_in_force="gtc")
    with pytest.raises(CryptoTradingBlocked):
        api.submit_order(symbol="IBIT", qty=1, side="buy", type="market", time_in_force="day")
    assert seen == []


def test_alpaca_py_refuses_a_crypto_buy(counting_server):
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    from core.broker_http import with_time_limit

    url, seen = counting_server
    client = with_time_limit(TradingClient("key", "secret", paper=True, url_override=url), (1.0, 0.3))
    with pytest.raises(CryptoTradingBlocked):
        client.submit_order(MarketOrderRequest(symbol="ETH/USD", qty=1, side=OrderSide.BUY,
                                               time_in_force=TimeInForce.GTC))
    assert seen == []


def test_oanda_refuses_any_crypto_order(monkeypatch):
    from core.oanda_trader import OandaTrader

    monkeypatch.setenv("OANDA_API_TOKEN", "dummy")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "dummy")

    class NoNetwork:
        def request(self, *a, **k):
            raise AssertionError("must not be sent")

        def close(self):
            pass

    with pytest.raises(CryptoTradingBlocked):
        OandaTrader(http_client=NoNetwork()).market_order("BTC_USD", 1, "50000")
