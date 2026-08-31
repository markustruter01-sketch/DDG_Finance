"""Focused Bot 3 stop-ledger regressions."""

from __future__ import annotations

import importlib.util
import pathlib
import sys


_MODULE_PATH = pathlib.Path(__file__).with_name("bot3_hard_assets_strategy.py")
_SPEC = importlib.util.spec_from_file_location(
    "bot3_hard_assets_strategy_test", _MODULE_PATH
)
assert _SPEC and _SPEC.loader
bot3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot3
_SPEC.loader.exec_module(bot3)


class _EntryClient:
    def __init__(self) -> None:
        self.qty = 0.0

    def submit(self, symbol, side, qty, order_type, **_extra):
        if side == "buy":
            self.qty = float(qty)
            return {"id": "entry-order"}
        return {"id": "replacement-stop-order"}

    def wait_for_fill(self, order_id):
        return {
            "status": "filled",
            "filled_qty": self.qty,
            "filled_avg_price": 100.0,
        }

    def positions(self):
        return [{"symbol": "BTC/USD", "qty": self.qty}]


def test_confirmed_entry_explicitly_remembers_stop_order_id(monkeypatch) -> None:
    client = _EntryClient()
    recorded = []
    remembered = []

    monkeypatch.setattr(
        bot3,
        "_record_open",
        lambda fill, qty, stop_price, stop_order_id: recorded.append(
            (fill, qty, stop_price, stop_order_id)
        ),
    )
    monkeypatch.setattr(
        bot3,
        "_remember_stop",
        lambda symbol, stop_order_id: remembered.append((symbol, stop_order_id)),
    )
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    result = bot3._place_confirmed_entry(client, "BTC/USD", 0.5, "cycle")

    assert result["status"] == "filled"
    assert recorded[0][3] == "replacement-stop-order"
    assert remembered == [("BTC/USD", "replacement-stop-order")]