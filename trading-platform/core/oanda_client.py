"""Read-only client for an OANDA practice account."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

BASE_URL = "https://api-fxpractice.oanda.com/v3"
REQUEST_TIMEOUT_SECONDS = 15.0


class OandaClientError(RuntimeError):
    """Raised when a practice-account request cannot be completed safely."""


class OandaConfigurationError(OandaClientError):
    """Raised when required OANDA practice credentials are unavailable."""


class OandaClient:
    """Expose read-only account, instrument, pricing, and position endpoints."""

    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        token = os.environ.get("OANDA_API_TOKEN", "").strip()
        account_id = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
        missing = [
            name
            for name, value in (
                ("OANDA_API_TOKEN", token),
                ("OANDA_ACCOUNT_ID", account_id),
            )
            if not value
        ]
        if missing:
            raise OandaConfigurationError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )

        self._token = token
        self._account_id = account_id
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        )

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> OandaClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _account_path(self, resource: str) -> str:
        account_id = quote(self._account_id, safe="")
        return f"/accounts/{account_id}/{resource}"

    def _get(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._http_client.get(
                f"{BASE_URL}{path}",
                params=params,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                },
            )
        except Exception:
            # Do not propagate transport exceptions: some HTTP libraries include
            # request details in their text, and request headers contain a token.
            raise OandaClientError("OANDA practice API request failed") from None

        try:
            status_code = response.status_code
        except Exception:
            raise OandaClientError("OANDA practice API returned an invalid response") from None
        if status_code < 200 or status_code >= 300:
            raise OandaClientError(
                f"OANDA practice API returned HTTP {status_code}"
            )

        try:
            payload = response.json()
        except Exception:
            raise OandaClientError("OANDA practice API returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise OandaClientError("OANDA practice API returned an invalid response")
        return payload

    @staticmethod
    def _decimal(value: Any, field: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise OandaClientError(
                f"OANDA response is missing a valid {field}"
            ) from None
        if not result.is_finite():
            raise OandaClientError(f"OANDA response is missing a valid {field}")
        return result

    def account_summary(self) -> dict[str, Any]:
        payload = self._get(self._account_path("summary"))
        account = payload.get("account")
        if not isinstance(account, dict):
            raise OandaClientError("OANDA response is missing account summary")
        currency = account.get("currency")
        if not isinstance(currency, str) or not currency:
            raise OandaClientError("OANDA response is missing a valid currency")
        return {
            "currency": currency,
            "balance": self._decimal(account.get("balance"), "balance"),
            "nav": self._decimal(account.get("NAV"), "NAV"),
            "margin_used": self._decimal(account.get("marginUsed"), "margin used"),
        }

    def tradeable_instruments(self) -> list[dict[str, Any]]:
        payload = self._get(self._account_path("instruments"))
        instruments = payload.get("instruments")
        if not isinstance(instruments, list) or any(
            not isinstance(instrument, dict) for instrument in instruments
        ):
            raise OandaClientError("OANDA response is missing instrument details")
        return instruments

    def daily_candles(
        self,
        instrument: str,
        *,
        count: int = 5,
    ) -> list[dict[str, Any]]:
        if not instrument or not isinstance(instrument, str):
            raise ValueError("instrument must be a non-empty string")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4999:
            raise ValueError("count must be an integer between 1 and 4999")

        payload = self._get(
            f"/instruments/{quote(instrument, safe='')}/candles",
            params={"granularity": "D", "price": "M", "count": count + 1},
        )
        candles = payload.get("candles")
        if not isinstance(candles, list) or any(
            not isinstance(candle, dict) for candle in candles
        ):
            raise OandaClientError("OANDA response is missing daily candles")
        complete = [candle for candle in candles if candle.get("complete") is True]
        return complete[-count:]

    def daily_candles_bid_ask(
        self,
        instrument: str,
        *,
        count: int = 5,
    ) -> list[dict[str, Any]]:
        """Complete daily candles with bid and ask OHLC (read-only)."""
        if not instrument or not isinstance(instrument, str):
            raise ValueError("instrument must be a non-empty string")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4999:
            raise ValueError("count must be an integer between 1 and 4999")
        payload = self._get(
            f"/instruments/{quote(instrument, safe='')}/candles",
            params={"granularity": "D", "price": "BA", "count": count + 1},
        )
        candles = payload.get("candles")
        if not isinstance(candles, list) or any(
            not isinstance(candle, dict) for candle in candles
        ):
            raise OandaClientError("OANDA response is missing daily candles")
        complete = [candle for candle in candles if candle.get("complete") is True]
        return complete[-count:]

    def current_bid_ask(self, instrument: str) -> dict[str, Any]:
        if not instrument or not isinstance(instrument, str):
            raise ValueError("instrument must be a non-empty string")
        payload = self._get(
            self._account_path("pricing"),
            params={"instruments": instrument},
        )
        prices = payload.get("prices")
        if not isinstance(prices, list):
            raise OandaClientError("OANDA response is missing instrument pricing")
        quote_data = next(
            (
                item
                for item in prices
                if isinstance(item, dict) and item.get("instrument") == instrument
            ),
            None,
        )
        if quote_data is None:
            raise OandaClientError("OANDA response is missing instrument pricing")

        bid = self._top_price(quote_data, "bids", "closeoutBid")
        ask = self._top_price(quote_data, "asks", "closeoutAsk")
        if ask < bid:
            raise OandaClientError("OANDA response contains an invalid bid/ask spread")
        return {
            "instrument": instrument,
            "bid": bid,
            "ask": ask,
            "spread": ask - bid,
            "status": quote_data.get("status"),
            "time": quote_data.get("time"),
        }

    @classmethod
    def _top_price(
        cls,
        quote_data: dict[str, Any],
        side: str,
        closeout_field: str,
    ) -> Decimal:
        levels = quote_data.get(side)
        if isinstance(levels, list) and levels and isinstance(levels[0], dict):
            value = levels[0].get("price")
        else:
            value = quote_data.get(closeout_field)
        return cls._decimal(value, side[:-1] if side.endswith("s") else side)

    def open_trades(self) -> list[dict[str, Any]]:
        return self._list_resource("openTrades", "trades")

    def open_orders(self) -> list[dict[str, Any]]:
        return self._list_resource("orders", "orders")

    def open_positions(self) -> list[dict[str, Any]]:
        return self._list_resource("openPositions", "positions")

    def _list_resource(self, resource: str, response_key: str) -> list[dict[str, Any]]:
        payload = self._get(self._account_path(resource))
        values = payload.get(response_key)
        if not isinstance(values, list) or any(
            not isinstance(value, dict) for value in values
        ):
            raise OandaClientError(f"OANDA response is missing {response_key}")
        return values