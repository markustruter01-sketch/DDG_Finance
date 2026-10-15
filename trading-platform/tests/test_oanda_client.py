from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from core.oanda_client import (
    OandaClient,
    OandaClientError,
    OandaConfigurationError,
)


TEST_TOKEN = "test-oanda-token-must-not-leak"
TEST_ACCOUNT_ID = "practice-account-id"


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class FakeHTTPClient:
    def __init__(self, responses: list[FakeResponse] | None = None, error=None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict] = []

    def get(self, url: str, *, params=None, headers=None) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "headers": headers})
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


@pytest.fixture
def credentials(monkeypatch) -> None:
    monkeypatch.setenv("OANDA_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("OANDA_ACCOUNT_ID", TEST_ACCOUNT_ID)


def test_account_summary_uses_practice_api_and_returns_read_fields(credentials) -> None:
    http = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "account": {
                        "currency": "USD",
                        "balance": "10000.00",
                        "NAV": "10025.50",
                        "marginUsed": "125.50",
                    }
                }
            )
        ]
    )

    with OandaClient(http_client=http) as client:
        summary = client.account_summary()

    assert summary == {
        "currency": "USD",
        "balance": Decimal("10000.00"),
        "nav": Decimal("10025.50"),
        "margin_used": Decimal("125.50"),
    }
    assert http.calls[0]["url"].startswith(
        "https://api-fxpractice.oanda.com/v3/accounts/"
    )
    assert http.calls[0]["headers"]["Authorization"] == f"Bearer {TEST_TOKEN}"


def test_tradeable_instruments_preserves_details(credentials) -> None:
    details = [
        {"name": "EUR_USD", "type": "CURRENCY", "financing": {"longRate": "0.02"}},
        {"name": "AUD_USD", "type": "CURRENCY"},
    ]
    client = OandaClient(http_client=FakeHTTPClient([FakeResponse({"instruments": details})]))

    assert client.tradeable_instruments() == details


def test_daily_candles_requests_mid_and_drops_in_progress_candle(credentials) -> None:
    candles = [
        {"time": "2026-01-01T00:00:00Z", "complete": True, "mid": {"c": "1.1"}},
        {"time": "2026-01-02T00:00:00Z", "complete": True, "mid": {"c": "1.2"}},
        {"time": "2026-01-03T00:00:00Z", "complete": False, "mid": {"c": "1.3"}},
        {"time": "2026-01-04T00:00:00Z", "complete": True, "mid": {"c": "1.4"}},
    ]
    http = FakeHTTPClient([FakeResponse({"candles": candles})])
    client = OandaClient(http_client=http)

    result = client.daily_candles("EUR_USD", count=3)

    assert [candle["time"] for candle in result] == [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-04T00:00:00Z",
    ]
    assert all(candle["complete"] is True and "mid" in candle for candle in result)
    assert http.calls[0]["params"] == {
        "granularity": "D",
        "price": "M",
        "count": 4,
    }


def test_current_bid_ask_returns_top_of_book_and_spread(credentials) -> None:
    http = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "prices": [
                        {
                            "instrument": "EUR_USD",
                            "status": "tradeable",
                            "time": "2026-01-01T12:00:00Z",
                            "bids": [{"price": "1.1000", "liquidity": "10"}],
                            "asks": [{"price": "1.1002", "liquidity": "11"}],
                        }
                    ]
                }
            )
        ]
    )
    client = OandaClient(http_client=http)

    result = client.current_bid_ask("EUR_USD")

    assert result["bid"] == Decimal("1.1000")
    assert result["ask"] == Decimal("1.1002")
    assert result["spread"] == Decimal("0.0002")
    assert http.calls[0]["params"] == {"instruments": "EUR_USD"}


@pytest.mark.parametrize(
    ("method_name", "response_key", "resource"),
    [
        ("open_trades", "trades", "openTrades"),
        ("open_orders", "orders", "orders"),
        ("open_positions", "positions", "openPositions"),
    ],
)
def test_open_account_resources_are_read_only(
    credentials, method_name: str, response_key: str, resource: str
) -> None:
    items = [{"id": "read-only-result"}]
    http = FakeHTTPClient([FakeResponse({response_key: items})])
    client = OandaClient(http_client=http)

    assert getattr(client, method_name)() == items
    assert http.calls[0]["url"].endswith(f"/{resource}")


@pytest.mark.parametrize("missing_name", ["OANDA_API_TOKEN", "OANDA_ACCOUNT_ID"])
def test_missing_secret_raises_without_disclosing_values(
    monkeypatch, missing_name: str
) -> None:
    monkeypatch.setenv("OANDA_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("OANDA_ACCOUNT_ID", TEST_ACCOUNT_ID)
    monkeypatch.delenv(missing_name)

    with pytest.raises(OandaConfigurationError) as exc_info:
        OandaClient(http_client=FakeHTTPClient())

    assert missing_name in str(exc_info.value)
    assert TEST_TOKEN not in str(exc_info.value)


def test_token_never_appears_in_transport_errors_or_logs(credentials, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    client = OandaClient(
        http_client=FakeHTTPClient(error=RuntimeError(f"transport leaked {TEST_TOKEN}"))
    )

    with pytest.raises(OandaClientError) as exc_info:
        client.account_summary()

    assert TEST_TOKEN not in str(exc_info.value)
    assert TEST_TOKEN not in caplog.text


def test_token_never_appears_in_http_errors_or_logs(credentials, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    client = OandaClient(
        http_client=FakeHTTPClient(
            [FakeResponse({"errorMessage": TEST_TOKEN}, status_code=401)]
        )
    )

    with pytest.raises(OandaClientError) as exc_info:
        client.account_summary()

    assert "401" in str(exc_info.value)
    assert TEST_TOKEN not in str(exc_info.value)
    assert TEST_TOKEN not in caplog.text


def test_client_has_no_order_or_trade_mutation_methods(credentials) -> None:
    client = OandaClient(http_client=FakeHTTPClient())
    mutating_methods = (
        "create_order",
        "place_order",
        "submit_order",
        "modify_order",
        "cancel_order",
        "create_trade",
        "close_trade",
        "modify_trade",
    )

    assert all(not hasattr(client, name) for name in mutating_methods)

def test_daily_candles_bid_ask_passes_optional_end_time(credentials) -> None:
    candle = {"complete": True, "time": "2026-10-08T21:00:00Z",
              "bid": {"o": "1", "h": "1", "l": "1", "c": "1"},
              "ask": {"o": "1", "h": "1", "l": "1", "c": "1"}}
    http = FakeHTTPClient([FakeResponse({"candles": [candle]}), FakeResponse({"candles": [candle]})])
    client = OandaClient(http_client=http)

    client.daily_candles_bid_ask("EUR_USD", count=3)
    client.daily_candles_bid_ask("EUR_USD", count=3, to="2026-10-10T00:00:00Z")

    assert "to" not in http.calls[0]["params"]
    assert http.calls[1]["params"]["to"] == "2026-10-10T00:00:00Z"
    assert http.calls[1]["params"]["count"] == 4
