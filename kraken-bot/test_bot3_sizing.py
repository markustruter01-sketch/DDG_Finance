"""Regression tests for Bot 3's cash-aware target and order guards."""

from __future__ import annotations

import importlib.util
import pathlib
import sys


_MODULE_PATH = pathlib.Path(__file__).with_name("bot3_hard_assets_strategy.py")
_SPEC = importlib.util.spec_from_file_location("bot3_hard_assets_strategy_sizing", _MODULE_PATH)
assert _SPEC and _SPEC.loader
bot3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot3
_SPEC.loader.exec_module(bot3)


class _AccountClient:
    def __init__(self, accounts: list[dict[str, float]], positions=None) -> None:
        self.accounts = accounts
        self.positions_snapshot = positions or []
        self.account_calls = 0
        self.position_calls = 0

    def account(self) -> dict[str, float]:
        account = self.accounts[min(self.account_calls, len(self.accounts) - 1)]
        self.account_calls += 1
        return account

    def positions(self) -> list[dict]:
        self.position_calls += 1
        return self.positions_snapshot


def _targets() -> dict[str, float]:
    return {symbol: 0.25 for symbol in bot3.ASSETS}


def test_plan_subtracts_vault_market_value_from_investable_base(monkeypatch) -> None:
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    plan = bot3._plan_orders(
        {"equity": 100_000.0},
        [{"symbol": "VOO", "market_value": 5_000.0}],
        _targets(),
        "test-cycle",
        {symbol: 100.0 for symbol in bot3.ASSETS},
    )

    assert {item["side"] for item in plan} == {"buy"}
    assert sum(item["notional"] for item in plan) == 95_000.0
    assert all(item["notional"] == 23_750.0 for item in plan)


def test_plan_scales_target_base_to_configured_deployment_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    plan = bot3._plan_orders(
        {"equity": 100_000.0},
        [{"symbol": "BIL", "market_value": 5_000.0}],
        _targets(),
        "test-cycle",
        {symbol: 100.0 for symbol in bot3.ASSETS},
        max_deployment=0.80,
    )

    assert sum(item["notional"] for item in plan) == 75_000.0


def test_fresh_buy_guard_rejects_insufficient_cash() -> None:
    client = _AccountClient([{
        "equity": 100_000.0,
        "cash": 10_000.0,
        "long_market_value": 90_000.0,
    }])

    allowed, projection = bot3._fresh_buy_guard(
        client,
        {"symbol": "BTC/USD", "qty": 100.0, "price": 200.0},
        max_deployment=1.0,
    )

    assert not allowed
    assert projection["projected_cash"] == -10_000.0
    assert client.account_calls == 1


def test_fresh_buy_guard_rejects_deployment_overage() -> None:
    client = _AccountClient([{
        "equity": 100_000.0,
        "cash": 50_000.0,
        "long_market_value": 80_000.0,
    }])

    allowed, projection = bot3._fresh_buy_guard(
        client,
        {"symbol": "ETH/USD", "qty": 150.0, "price": 200.0},
        max_deployment=1.0,
    )

    assert not allowed
    assert projection["projected_long_market_value"] == 110_000.0
    assert projection["projected_deployment"] == 1.10


def test_plan_sells_before_buys(monkeypatch) -> None:
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    plan = bot3._plan_orders(
        {"equity": 100_000.0},
        [{
            "symbol": "BTC/USD",
            "market_value": 40_000.0,
            "current_price": 100.0,
            "qty": 400.0,
        }],
        _targets(),
        "test-cycle",
        {symbol: 100.0 for symbol in bot3.ASSETS},
    )

    assert plan[0]["side"] == "sell"
    assert all(item["side"] == "buy" for item in plan[1:])


def test_fresh_buy_guard_falls_back_to_fresh_positions_snapshot() -> None:
    client = _AccountClient(
        [{
            "equity": 100_000.0,
            "cash": 80_000.0,
        }],
        positions=[{"symbol": "VOO", "market_value": 20_000.0}],
    )

    allowed, projection = bot3._fresh_buy_guard(
        client,
        {"symbol": "GLD", "qty": 801.0, "price": 100.0},
        max_deployment=1.0,
    )

    assert not allowed
    assert projection["fresh_long_market_value"] == 20_000.0
    assert client.position_calls == 1