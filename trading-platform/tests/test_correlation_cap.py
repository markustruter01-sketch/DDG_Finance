"""Regression tests for the live correlation-cap entry gate."""

from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "kraken-bot"))

import asia_trend_strategy as asia
import bot3_hard_assets_strategy as bot3
import sgov_parking
from alpaca_etf_engine import AlpacaEtfEngine
from core.correlation_cap import corr_cap_check
from core import kill_switch


def test_import_failure_blocks_when_held_etf_exists(monkeypatch) -> None:
    monkeypatch.setattr(asia, "_CORR_CAP_OK", False)

    allowed, reason = asia._corr_cap_check("EWT", ["EWY"])

    assert (allowed, reason) == (False, "corr_cap_unavailable")


def test_empty_held_list_allows_even_when_cap_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(asia, "_CORR_CAP_OK", False)

    allowed, reason = asia._corr_cap_check("EWT", [])

    assert (allowed, reason) == (True, "no_held_etfs")


def test_missing_candidate_history_blocks() -> None:
    allowed, reason = corr_cap_check(
        "EWT",
        ["EWY"],
        {"EWY": [100.0, 101.0]},
    )

    assert (allowed, reason) == (False, "corr_cap_no_candidate_history")


def test_missing_held_history_still_allows_with_candidate_history() -> None:
    allowed, reason = corr_cap_check(
        "EWT",
        ["EWY"],
        {"EWT": [100.0, 101.0, 102.0]},
        max_correlated=1,
    )

    assert (allowed, reason) == (True, None)


def test_etf_account_preserves_absent_long_market_value() -> None:
    engine = object.__new__(AlpacaEtfEngine)
    engine.api = SimpleNamespace(
        get_account=lambda: SimpleNamespace(
            equity="100000",
            cash="25000",
            buying_power="50000",
        )
    )

    account = engine.get_account()

    assert account == {
        "equity": 100000.0,
        "cash": 25000.0,
        "buying_power": 50000.0,
    }
    assert "long_market_value" not in account


class _AsiaEngine:
    def __init__(self, *args, **kwargs):
        type(self).last_instance = self
        self.position_snapshots = []
        self.position_results = []
        self.buy_calls = []
        self.events = []

    def get_account(self):
        return {
            "equity": 100000.0,
            "cash": 20000.0,
            "buying_power": 100000.0,
        }

    def get_positions(self):
        self.position_snapshots.append(True)
        if len(self.position_snapshots) == 4:
            result = [{"symbol": "QQQ", "market_value": 90000.0, "qty": 900.0}]
        else:
            result = []
        self.position_results.append(result)
        return result

    def get_db_positions(self, bot_id):
        return []

    def reconcile_protective_stops(self, bot_id, positions):
        return None

    def record_scan_decision(self, **kwargs):
        return 1

    def buy_market(self, symbol, shares):
        self.buy_calls.append((symbol, shares))
        return {"order_id": "should-not-submit"}


def _patch_single_asia_candidate(monkeypatch, engine_cls, *, position_count=0):
    monkeypatch.setattr(asia, "AlpacaEtfEngine", engine_cls)
    monkeypatch.setattr(asia, "_in_entry_window", lambda: True)
    monkeypatch.setattr(asia, "_get_cross_bot_held_etfs", lambda **kwargs: [])
    monkeypatch.setattr(asia, "_corr_cap_check", lambda *args: (True, None))
    monkeypatch.setattr(asia, "_vol_scaled_size", lambda *args: 100)
    monkeypatch.setattr(asia, "_regional_regime", lambda symbol: {
        "regime": "BULL",
        "source": "test",
    })
    target = asia.UNIVERSE[0]
    monkeypatch.setattr(
        asia,
        "_should_enter",
        lambda symbol: (
            True,
            {"current_price": 100.0, "ema_fast": 90.0, "atr": 1.0},
        )
        if symbol == target
        else (False, {}),
    )
    monkeypatch.setattr(kill_switch, "_vault_symbols", lambda bot_id: set())
    monkeypatch.setattr(sgov_parking, "unpark_for_entry", lambda *args: 0.0)
    monkeypatch.setattr(sgov_parking, "park_idle_cash", lambda *args, **kwargs: None)


def test_missing_long_market_value_uses_positions_and_blocks_overdeployment(
    monkeypatch,
) -> None:
    _patch_single_asia_candidate(monkeypatch, _AsiaEngine)

    asia.run_asia_cycle(
        {
            "ALPACA_API_KEY": "key",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_BASE_URL": "https://paper.example",
            "MAX_POSITIONS": 6,
            "MAX_DEPLOYMENT": 0.80,
            "VOL_CAP": 0.13,
        },
        db_id=0,
    )

    engine = asia.AlpacaEtfEngine.last_instance
    assert any(engine.position_results)
    assert engine.buy_calls == []


class _PartialFillEngine(_AsiaEngine):
    last_instance = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).last_instance = self

    def get_positions(self):
        self.position_snapshots.append(True)
        self.position_results.append([])
        return []

    def get_account(self):
        return {
            "equity": 100000.0,
            "cash": 20000.0,
            "buying_power": 100000.0,
            "long_market_value": 0.0,
        }

    def buy_market(self, symbol, shares):
        self.events.append("buy")
        return {"order_id": "entry-1"}

    def poll_entry_order(self, order_id):
        return {
            "status": "partially_filled",
            "filled_qty": 10.0,
            "filled_avg_price": 100.0,
        }

    def cancel_order(self, order_id):
        self.events.append("cancel")

    def record_open(self, **kwargs):
        self.events.append("record_open")
        return False

    def record_scan_outcome(self, *args, **kwargs):
        self.events.append("record_scan")

    def arm_protective_stop_after_fill(self, *args, **kwargs):
        self.events.append("arm_stop")


def test_partial_fill_arms_stop_before_failed_db_record(monkeypatch) -> None:
    _patch_single_asia_candidate(monkeypatch, _PartialFillEngine)

    asia.run_asia_cycle(
        {
            "ALPACA_API_KEY": "key",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_BASE_URL": "https://paper.example",
            "MAX_POSITIONS": 6,
            "MAX_DEPLOYMENT": 0.80,
            "VOL_CAP": 0.13,
        },
        db_id=0,
    )

    engine = _PartialFillEngine.last_instance
    assert engine.events.index("arm_stop") < engine.events.index("record_scan")


class _BackstopClient:
    def __init__(self, orders):
        self.orders = orders
        self.submissions = []

    def open_orders(self):
        return self.orders

    def positions(self):
        return [{"symbol": "GLD", "qty": "10"}]

    def submit(self, symbol, side, qty, order_type, **extra):
        self.submissions.append((symbol, side, qty, order_type, extra))
        return {"id": "market-exit-1"}


def test_partial_quantity_stop_is_uncovered(monkeypatch) -> None:
    client = _BackstopClient(
        [{"symbol": "GLD", "side": "sell", "type": "stop", "qty": "5"}]
    )
    armed = []
    monkeypatch.setattr(
        bot3,
        "_arm_stop",
        lambda *args: armed.append(args) or {"id": "replacement", "status": "new"},
    )
    monkeypatch.setattr(bot3, "_remember_stop", lambda *args: None)
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    bot3._maintain_protective_stops(
        client,
        [{"symbol": "GLD", "qty": 10.0, "entry_price": 100.0}],
        "test-cycle",
        equity_session_open=True,
    )

    assert len(armed) == 1


def test_limit_sell_is_not_a_protective_stop_for_backstop(monkeypatch) -> None:
    client = _BackstopClient(
        [{"symbol": "GLD", "side": "sell", "type": "limit", "qty": "10"}]
    )
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    bot3._software_backstop(
        client,
        [{
            "symbol": "GLD",
            "qty": 10.0,
            "current_price": 90.0,
            "stop_price": 100.0,
        }],
        "test-cycle",
        equity_session_open=True,
    )

    assert len(client.submissions) == 1
    assert client.submissions[0][:4] == ("GLD", "sell", 10.0, "market")
