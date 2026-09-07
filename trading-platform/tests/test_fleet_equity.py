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