from __future__ import annotations

import pytest

from core import kill_switch
from core import fleet_equity
from execution import reconciliation


class _Account:
    def __init__(self, equity: float):
        self.equity = equity


class _Client:
    def __init__(self, equity: float):
        self._equity = equity

    def get_account(self):
        return _Account(self._equity)


def _patch_clients(monkeypatch, clients):
    monkeypatch.setattr(
        reconciliation,
        "_client_for",
        lambda bot_id: clients[bot_id],
    )
    # These legacy Alpaca-only cases intentionally exercise a three-account
    # subset; separate tests below cover the production four-bot registry.
    monkeypatch.setattr(
        "core.bot_registry.active_bot_ids",
        lambda: tuple(clients),
    )


class _OandaClient:
    def __init__(self, summary=None, error=None):
        self.summary = summary or {"currency": "USD", "nav": 400.0}
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def account_summary(self):
        if self.error:
            raise self.error
        return self.summary


def _patch_complete_fleet(monkeypatch, *, summary=None, error=None):
    clients = {
        "oracle": _Client(100.0),
        "spy_qqq_trend": _Client(200.0),
        "jerome_macro": _Client(300.0),
    }
    monkeypatch.setattr(
        reconciliation,
        "_client_for",
        lambda bot_id: clients[bot_id],
    )
    monkeypatch.setattr(
        "core.oanda_client.OandaClient",
        lambda: _OandaClient(summary=summary, error=error),
    )


def test_get_fleet_equity_returns_sum_and_breakdown(monkeypatch):
    clients = {
        "oracle": _Client(100.0),
        "spy_qqq_trend": _Client(200.0),
        "jerome_macro": _Client(300.0),
    }
    _patch_clients(monkeypatch, clients)

    total, breakdown = fleet_equity.get_fleet_equity()

    assert total == 600.0
    assert breakdown == {
        "oracle": 100.0,
        "spy_qqq_trend": 200.0,
        "jerome_macro": 300.0,
    }


def test_get_fleet_equity_raises_and_returns_nothing_when_account_read_fails(
    monkeypatch,
):
    class _FailingClient:
        def get_account(self):
            raise RuntimeError("broker unavailable")

    clients = {
        "oracle": _Client(100.0),
        "spy_qqq_trend": _FailingClient(),
        "jerome_macro": _Client(300.0),
    }
    _patch_clients(monkeypatch, clients)

    with pytest.raises(RuntimeError, match="spy_qqq_trend"):
        fleet_equity.get_fleet_equity()


def test_get_fleet_equity_raises_for_zero_equity(monkeypatch):
    clients = {
        "oracle": _Client(100.0),
        "spy_qqq_trend": _Client(0.0),
        "jerome_macro": _Client(300.0),
    }
    _patch_clients(monkeypatch, clients)

    with pytest.raises(RuntimeError, match="spy_qqq_trend"):
        fleet_equity.get_fleet_equity()


def test_get_fleet_equity_raises_for_missing_credentials(monkeypatch):
    def build_client(bot_id):
        key_name, secret_name = kill_switch.ACCOUNT_ENV[bot_id]
        if bot_id == "spy_qqq_trend":
            monkeypatch.delenv(key_name, raising=False)
            monkeypatch.delenv(secret_name, raising=False)
            raise RuntimeError(f"missing credentials for {bot_id}")
        return _Client(100.0 if bot_id == "oracle" else 300.0)

    monkeypatch.setattr(reconciliation, "_client_for", build_client)

    with pytest.raises(RuntimeError, match="spy_qqq_trend"):
        fleet_equity.get_fleet_equity()


def test_get_fleet_equity_includes_usd_oanda_nav(monkeypatch):
    _patch_complete_fleet(monkeypatch)

    total, breakdown = fleet_equity.get_fleet_equity()

    assert total == 1000.0
    assert breakdown["forex_ai"] == 400.0


@pytest.mark.parametrize(
    ("summary", "error"),
    [
        ({"currency": "EUR", "nav": 400.0}, None),
        (None, RuntimeError("OANDA unavailable")),
    ],
)
def test_get_fleet_equity_rejects_oanda_failure_or_non_usd(
    monkeypatch,
    summary,
    error,
):
    _patch_complete_fleet(monkeypatch, summary=summary, error=error)

    with pytest.raises(RuntimeError, match="forex_ai"):
        fleet_equity.get_fleet_equity()