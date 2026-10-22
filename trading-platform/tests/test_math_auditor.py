from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import math_auditor


def _run_audit(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entry: float | None,
    stop: float | None,
    current: float | None,
) -> dict[str, Any]:
    row = {
        "bot_id": "oracle",
        "symbol": "SPY",
        "entry_price": entry,
        "stop_price": stop,
        "entry_atr": 2.0,
    }
    logged: list[dict[str, Any]] = []

    monkeypatch.setattr(math_auditor, "_pg_query", lambda _sql: [row])
    monkeypatch.setattr(
        math_auditor,
        "_fetch_alpaca_current_prices",
        lambda _bot_id: {"SPY": current} if current is not None else None,
    )

    def fake_log_result(bot_id: str, formula_name: str, input_values: dict, **kwargs):
        logged.append(
            {
                "bot_id": bot_id,
                "formula_name": formula_name,
                "input_values": input_values,
                **kwargs,
            }
        )
        return kwargs["override_status"], None

    monkeypatch.setattr(math_auditor, "_log_result", fake_log_result)

    assert math_auditor.audit_atr_open_positions() == 1
    return logged[0]


def test_stop_below_entry_and_current_price_passes(monkeypatch):
    result = _run_audit(monkeypatch, entry=100.0, stop=95.0, current=110.0)

    assert result["override_status"] == "PASS"
    assert "stop is below entry" in result["notes"]
    assert "stop is below current price" in result["notes"]


def test_stop_above_entry_but_below_current_price_passes_as_locked_in_profit(
    monkeypatch,
):
    result = _run_audit(monkeypatch, entry=100.0, stop=105.0, current=110.0)

    assert result["override_status"] == "PASS"
    assert "above entry" in result["notes"]
    assert "locked-in profit" in result["notes"]
    assert "stop is below current price" in result["notes"]


def test_stop_at_or_above_current_price_fails(monkeypatch):
    result = _run_audit(monkeypatch, entry=100.0, stop=115.0, current=110.0)

    assert result["override_status"] == "FAIL"
    assert "at or above current price" in result["notes"]


@pytest.mark.parametrize("stop", [None])
def test_missing_stop_fails(monkeypatch, stop):
    result = _run_audit(monkeypatch, entry=100.0, stop=stop, current=110.0)

    assert result["override_status"] == "FAIL"
    assert "missing or invalid stop" in result["notes"]


@pytest.mark.parametrize("stop", [0.0, -1.0])
def test_zero_or_negative_stop_fails(monkeypatch, stop):
    result = _run_audit(monkeypatch, entry=100.0, stop=stop, current=110.0)

    assert result["override_status"] == "FAIL"
    assert "missing or invalid stop" in result["notes"]


def test_current_price_unavailable_warns_instead_of_failing(monkeypatch):
    result = _run_audit(monkeypatch, entry=100.0, stop=95.0, current=None)

    assert result["override_status"] == "UNKNOWN"
    assert result["bot_output"] is None
    assert result["auditor_output"] is None
    assert "current price unavailable" in result["notes"]
    assert "unknown, not a fault" in result["notes"]


def test_current_price_uses_fresh_latest_alpaca_trade(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")  # the fakes ignore keys, but the code requires some
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    from alpaca.data import historical, requests
    from alpaca.trading import client

    now = datetime.now(timezone.utc)

    class FakeTradingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_clock(self):
            return SimpleNamespace(is_open=True)

        def get_all_positions(self):
            return [SimpleNamespace(symbol="EWT", current_price=107.40)]

    class FakeStockHistoricalDataClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_stock_latest_trade(self, request):
            assert request.symbol_or_symbols == ["EWT"]
            return {"EWT": SimpleNamespace(price=110.94, timestamp=now)}

    monkeypatch.setattr(client, "TradingClient", FakeTradingClient)
    monkeypatch.setattr(historical, "StockHistoricalDataClient", FakeStockHistoricalDataClient)
    monkeypatch.setattr(
        requests,
        "StockLatestTradeRequest",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    assert math_auditor._fetch_alpaca_current_prices("oracle") == {"EWT": 110.94}


def test_current_price_ignores_stale_latest_alpaca_trade(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")  # the fakes ignore keys, but the code requires some
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    from alpaca.data import historical
    from alpaca.trading import client

    class FakeTradingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_clock(self):
            return SimpleNamespace(is_open=True)

        def get_all_positions(self):
            return [SimpleNamespace(symbol="EWT", current_price=107.40)]

    class FakeStockHistoricalDataClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_stock_latest_trade(self, _request):
            return {
                "EWT": SimpleNamespace(
                    price=107.40,
                    timestamp=datetime.now(timezone.utc) - timedelta(minutes=6),
                )
            }

    monkeypatch.setattr(client, "TradingClient", FakeTradingClient)
    monkeypatch.setattr(historical, "StockHistoricalDataClient", FakeStockHistoricalDataClient)

    assert math_auditor._fetch_alpaca_current_prices("oracle") == {}
