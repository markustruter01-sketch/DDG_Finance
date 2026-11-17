"""
Time limits on every call to Alpaca (16 Nov 2026 order-path audit, F5), and the
no-crypto rule (Markus, 17 Nov 2026; core/no_crypto.py) on every order sent.

Neither Alpaca library sets a time limit on its HTTP calls: a connection that
hangs would stall that bot's cycle until the process is restarted. Every Alpaca
client is now made through this module, which gives it a session that gives up
after ``CONNECT_S`` seconds to connect and ``READ_S`` seconds waiting for an
answer, and raises ``requests.exceptions.Timeout``.

A time-out on an order is an unclear answer, not a failure. The order code
already handles that case (F1, PR #108): it looks the order up by its client
id before doing anything else and never sends it a second time. Neither library
resends a request after a time-out (they retry only on HTTP 429 and 504).
"""
from __future__ import annotations

import os
from typing import Any

import requests
from loguru import logger

CONNECT_S = 10.0
# Bar downloads for many symbols can take a while; an order or account read takes about a second.
READ_S = float(os.environ.get("ALPACA_READ_TIMEOUT_S", "45"))
TIMEOUT = (CONNECT_S, READ_S)


class TimeLimitedSession(requests.Session):
    """A requests session that never waits forever (every call gets a time limit)
    and never sends an order that would buy crypto."""

    def __init__(self, timeout: Any = TIMEOUT):
        super().__init__()
        self.time_limit = timeout

    def request(self, method, url, **kwargs):  # type: ignore[override]
        # No crypto, anywhere: an order that would buy crypto is never sent.
        if str(method).upper() in ("POST", "PATCH") and "/orders" in str(url):
            body = kwargs.get("json")
            if isinstance(body, dict):
                from core.no_crypto import refuse_crypto_buy
                refuse_crypto_buy(body.get("symbol"), body.get("side"), f"Alpaca {method} {url}")
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self.time_limit
        return super().request(method, url, **kwargs)


def with_time_limit(client: Any, timeout: Any = TIMEOUT) -> Any:
    """Swap the HTTP session inside an Alpaca client (alpaca-trade-api ``REST`` or
    alpaca-py ``TradingClient``) for a time-limited one. Both libraries send every
    call through ``client._session``. If a library update ever removes it, the
    client is returned unchanged and an error is logged (the tests fail too)."""
    old = getattr(client, "_session", None)
    if not isinstance(old, requests.Session):
        logger.error("broker_http | Alpaca client has no requests session; calls have NO time limit")
        return client
    new = TimeLimitedSession(timeout)
    new.headers.update(old.headers)
    new.mount("https://", old.get_adapter("https://"))
    new.mount("http://", old.get_adapter("http://"))
    client._session = new
    return client


def alpaca_rest(api_key: str, secret_key: str, base_url: str = "https://paper-api.alpaca.markets",
                timeout: Any = TIMEOUT) -> Any:
    """An alpaca-trade-api ``REST`` client whose calls all have a time limit."""
    import alpaca_trade_api as tradeapi

    return with_time_limit(tradeapi.REST(api_key, secret_key, base_url=base_url), timeout)
