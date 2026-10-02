from __future__ import annotations

import inspect
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "trading-platform"))
sys.path.insert(1, str(_ROOT / "kraken-bot"))

import asia_trend_strategy as atlas_strategy
import sgov_parking
from core.cash_park import CASH_PARK_SYMBOLS


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
