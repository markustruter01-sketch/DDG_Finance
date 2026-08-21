import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).with_name("migrate_global_etf.py")
spec = importlib.util.spec_from_file_location("migrate_global_etf", MODULE_PATH)
migration = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = migration
spec.loader.exec_module(migration)


def test_global_universe_and_safety_constants():
    assert len(migration.TARGET_SYMBOLS) == 16
    assert {"SPY", "QQQ", "EWM", "EPOL", "GREK", "TUR"} <= migration.TARGET_SYMBOLS
    assert migration.CONFIRMATION == "CONSOLIDATE-PAPER-ETF-ACCOUNTS"


def test_stop_detection_requires_sell_protective_order():
    assert migration._is_stop(SimpleNamespace(side="sell", type="stop"))
    assert migration._is_stop(SimpleNamespace(side="sell", type="trailing_stop"))
    assert not migration._is_stop(SimpleNamespace(side="buy", type="stop"))
    assert not migration._is_stop(SimpleNamespace(side="sell", type="market"))


def test_inventory_excludes_unrelated_positions():
    client = SimpleNamespace(
        get_account=lambda: SimpleNamespace(equity="100000", cash="50000"),
        get_all_positions=lambda: [
            SimpleNamespace(symbol="SPY", qty="2", market_value="1000"),
            SimpleNamespace(symbol="BTCUSD", qty="1", market_value="50000"),
            SimpleNamespace(symbol="SGOV", qty="0.000000001", market_value="0"),
        ],
        get_orders=lambda filter: [],
    )
    snapshot = migration.inventory(client)
    assert [p["symbol"] for p in snapshot["positions"]] == ["SPY", "SGOV"]


def test_flatten_refuses_position_without_covered_protective_stop():
    client = SimpleNamespace(
        get_clock=lambda: SimpleNamespace(is_open=True),
        get_open_position=lambda symbol: SimpleNamespace(qty="2"),
    )
    snapshot = {
        "positions": [{"symbol": "SPY", "qty": 2.987862516}],
        "open_orders": [{
            "id": "legacy-stop",
            "symbol": "SPY",
            "side": "sell",
            "type": "stop",
            "qty": 1.0,
            "stop_price": 700.0,
        }],
    }
    with pytest.raises(migration.MigrationError, match="floor\\(position_qty\\)=2"):
        migration.flatten_account(client, snapshot)