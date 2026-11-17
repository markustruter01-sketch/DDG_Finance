"""The bots' Alpaca clients are built with a time limit on every call (audit F5).
The time limit itself is tested in trading-platform/tests/test_broker_time_limits.py."""
from __future__ import annotations

import alpaca_etf_engine as etf_engine_module
import jerome_alpaca
from core.broker_http import TimeLimitedSession


def test_the_etf_engine_client_has_a_time_limit(monkeypatch):
    monkeypatch.setattr(etf_engine_module.AlpacaEtfEngine, "_ensure_schema", lambda self: None)
    engine = etf_engine_module.AlpacaEtfEngine("key", "secret")
    assert isinstance(engine.api._session, TimeLimitedSession)


def test_the_commodity_account_client_has_a_time_limit():
    assert isinstance(jerome_alpaca.JeromeAlpaca("key", "secret").api._session, TimeLimitedSession)
