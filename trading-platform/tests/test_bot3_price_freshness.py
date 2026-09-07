from __future__ import annotations

import importlib.util
import pathlib
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest


_MODULE_PATH = (
    pathlib.Path(__file__).parents[2] / "kraken-bot" / "bot3_hard_assets_strategy.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "bot3_hard_assets_strategy_price_freshness_test",
    _MODULE_PATH,
)
assert _SPEC and _SPEC.loader
bot3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot3
_SPEC.loader.exec_module(bot3)


class _FakeCursor:
    def __init__(self, rows_by_db_symbol: dict[str, list[tuple[float, date]]]) -> None:
        self.rows_by_db_symbol = rows_by_db_symbol
        self.rows: list[tuple[float, date]] = []

    def execute(self, query: str, params: tuple[str, int]) -> None:
        self.rows = self.rows_by_db_symbol[params[0]]

    def fetchall(self) -> list[tuple[float, date]]:
        return self.rows


class _FakeConnection:
    def __init__(self, rows_by_db_symbol: dict[str, list[tuple[float, date]]]) -> None:
        self.cursor_instance = _FakeCursor(rows_by_db_symbol)

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance


def _rows(newest: date, count: int = 61) -> list[tuple[float, date]]:
    return [
        (100.0 + index, newest - timedelta(days=count - 1 - index))
        for index in range(count)
    ][::-1]


def _database_rows(
    newest_by_symbol: dict[str, date],
    counts: dict[str, int] | None = None,
) -> dict[str, list[tuple[float, date]]]:
    counts = counts or {}
    return {
        db_symbol: _rows(newest_by_symbol[symbol], counts.get(symbol, 61))
        for symbol, (_, db_symbol) in bot3.PRICE_TABLES.items()
    }


@contextmanager
def _fake_get_conn(rows_by_db_symbol: dict[str, list[tuple[float, date]]]):
    yield _FakeConnection(rows_by_db_symbol)


def _fresh_dates() -> dict[str, date]:
    today = datetime.now(timezone.utc).date()
    return {symbol: today for symbol in bot3.ASSETS}


def test_all_assets_fresh_and_complete_return_closes(monkeypatch):
    rows = _database_rows(_fresh_dates())
    monkeypatch.setattr(bot3, "get_conn", lambda: _fake_get_conn(rows))

    closes = bot3._load_recent_closes()

    assert set(closes) == set(bot3.ASSETS)
    assert all(len(values) == bot3.VOL_LOOKBACK + 1 for values in closes.values())


def test_crypto_four_days_old_raises_with_symbol(monkeypatch):
    newest = _fresh_dates()
    newest["BTC/USD"] -= timedelta(days=4)
    rows = _database_rows(newest)
    monkeypatch.setattr(bot3, "get_conn", lambda: _fake_get_conn(rows))

    with pytest.raises(RuntimeError, match=r"BTC/USD.*4 days.*threshold 3 days"):
        bot3._load_recent_closes()


def test_metal_seven_days_old_raises_with_symbol(monkeypatch):
    newest = _fresh_dates()
    newest["GLD"] -= timedelta(days=7)
    rows = _database_rows(newest)
    monkeypatch.setattr(bot3, "get_conn", lambda: _fake_get_conn(rows))

    with pytest.raises(RuntimeError, match=r"GLD.*7 days.*threshold 6 days"):
        bot3._load_recent_closes()


def test_metal_five_days_old_and_crypto_two_days_old_are_fresh(monkeypatch):
    newest = _fresh_dates()
    newest["GLD"] -= timedelta(days=5)
    newest["BTC/USD"] -= timedelta(days=2)
    rows = _database_rows(newest)
    monkeypatch.setattr(bot3, "get_conn", lambda: _fake_get_conn(rows))

    closes = bot3._load_recent_closes()

    assert all(len(values) == bot3.VOL_LOOKBACK + 1 for values in closes.values())


def test_one_asset_with_sixty_rows_raises_with_symbol_and_count(monkeypatch):
    rows = _database_rows(_fresh_dates(), {"SLV": 60})
    monkeypatch.setattr(bot3, "get_conn", lambda: _fake_get_conn(rows))

    with pytest.raises(RuntimeError, match=r"SLV.*got 60.*need 61"):
        bot3._load_recent_closes()


def test_inverse_vol_targets_rejects_sixty_values():
    closes = {symbol: [100.0] * 61 for symbol in bot3.ASSETS}
    closes["ETH/USD"] = [100.0] * 60

    with pytest.raises(RuntimeError, match=r"ETH/USD.*got 60.*need 61"):
        bot3.inverse_vol_targets(closes)