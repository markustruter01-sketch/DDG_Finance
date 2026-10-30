from __future__ import annotations

import inspect
import pathlib
import sys
from types import SimpleNamespace

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "trading-platform"))
sys.path.insert(1, str(_ROOT / "kraken-bot"))

import asia_trend_strategy as atlas_strategy
import sgov_parking
from core.cash_park import CASH_PARK_SYMBOLS


def test_safe_close_treats_market_closed_as_deferred_without_degradation(monkeypatch) -> None:
    records: list[dict] = []
    notifications: list[str] = []

    class FakeEngine:
        _last_close_deferred_market_closed = False

        def get_db_positions(self, _bot_id):
            return [{"symbol": "EPOL", "stop_order_id": "stop-1", "stop_price": 40.95}]

        def close_position(self, *_args, **_kwargs):
            self._last_close_deferred_market_closed = True
            return False

    monkeypatch.setattr(
        "core.degradation_tracker.record_degradation",
        lambda **kwargs: records.append(kwargs),
    )
    monkeypatch.setattr(
        "notifications.discord.notify_capital_risk",
        lambda message, **_kwargs: notifications.append(message),
    )

    assert atlas_strategy._safe_close(FakeEngine(), "EPOL", "trend exit", None, "oracle") is False
    assert records == []
    assert notifications == []


def test_safe_close_still_degrades_for_non_market_closed_false(monkeypatch) -> None:
    records: list[dict] = []

    class FakeEngine:
        _last_close_deferred_market_closed = False

        def get_db_positions(self, _bot_id):
            return []

        def close_position(self, *_args, **_kwargs):
            return False

    monkeypatch.setattr(
        "core.degradation_tracker.record_degradation",
        lambda **kwargs: records.append(kwargs),
    )
    monkeypatch.setattr(
        "notifications.discord.notify_capital_risk",
        lambda *_args, **_kwargs: None,
    )

    assert atlas_strategy._safe_close(FakeEngine(), "EPOL", "trend exit", None, "oracle") is False
    assert len(records) == 1
    assert records[0]["error_type"] == "close_position_failed"


def test_deployment_percentage_excludes_parked_cash() -> None:
    positions = [
        {"symbol": "SPY", "market_value": 30_000.0},
        {"symbol": "s/gov", "market_value": 60_000.0},
    ]

    assert atlas_strategy._strategy_deployed_pct(positions, 100_000.0) == 0.3
    assert atlas_strategy._strategy_deployed_pct(
        [{"symbol": "SGOV", "market_value": 90_000.0}],
        100_000.0,
    ) == 0.0


def test_cash_park_is_excluded_from_deployment_but_retained_in_gross_long_value() -> None:
    positions = [
        {"symbol": "SPY", "market_value": 10_000.0},
        {"symbol": "s-gov", "market_value": 80_000.0},
    ]

    assert atlas_strategy._long_market_values(90_000.0, positions) == (
        90_000.0,
        10_000.0,
    )
    assert atlas_strategy._long_market_values(None, positions) == (
        90_000.0,
        10_000.0,
    )


def test_atlas_unparks_parked_cash_before_candidate_entry(monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    class FakeEngine:
        cash = 10.0

        def get_positions(self):
            return [{"symbol": "s-gov", "market_value": 500.0}]

        def close_position(self, symbol):
            events.append(("close", symbol))
            return True

        def buy_market(self, symbol, _qty):
            events.append(("entry", symbol))

    monkeypatch.setattr(sgov_parking, "_nyse_is_open", lambda: True)
    engine = FakeEngine()
    candidate = {"symbol": "SPY", "notional": 50.0}
    assert engine.cash < candidate["notional"]

    result = atlas_strategy._unpark_before_entries(
        engine,
        [candidate],
    )
    engine.buy_market("SPY", 1)

    assert result == 500.0
    assert events == [("close", next(iter(CASH_PARK_SYMBOLS))), ("entry", "SPY")]

    cycle_source = inspect.getsource(atlas_strategy.run_asia_cycle)
    assert cycle_source.index(
        "_unpark_before_entries(engine, candidates)"
    ) < cycle_source.index("for cand in candidates:")


def test_sgov_dust_left_by_a_full_sale_does_not_block_parking() -> None:
    import sgov_parking

    class Engine:
        def __init__(self):
            self.orders = []

        def place_order(self, symbol, side, notional):
            self.orders.append((symbol, side, notional))
            return {"order_id": "o1"}

    dust = [{"symbol": "SGOV", "qty": 0.000000004, "market_value": 0.0}]
    engine = Engine()
    sgov_parking.park_idle_cash(engine, "GearG4", dust, 12_000.0)
    assert engine.orders == [("SGOV", "buy", 11_950.0)]
    assert sgov_parking.unpark_for_entry(engine, "GearG4", dust) == 0.0

    held = [{"symbol": "SGOV", "qty": 434.0, "market_value": 43_716.82}]
    engine = Engine()
    sgov_parking.park_idle_cash(engine, "GearG4", held, 12_000.0)
    assert engine.orders == []                     # a real holding: still skipped, as before
