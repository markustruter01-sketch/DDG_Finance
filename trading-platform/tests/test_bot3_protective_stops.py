"""Regression tests for Bot 3 protective-stop maintenance."""

from __future__ import annotations

import importlib.util
import logging
import pathlib
import sys

import pytest


_MODULE_PATH = (
    pathlib.Path(__file__).parents[2] / "kraken-bot" / "bot3_hard_assets_strategy.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "bot3_hard_assets_strategy_protective_stop_test", _MODULE_PATH
)
assert _SPEC and _SPEC.loader
bot3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot3
_SPEC.loader.exec_module(bot3)


class _StopClient:
    def __init__(self, response):
        self.response = response
        self.submissions = []

    def open_orders(self):
        return []

    def submit(self, symbol, side, qty, order_type, **extra):
        self.submissions.append((symbol, side, qty, order_type, extra))
        return self.response


def test_missing_metals_stop_is_armed_when_equity_session_is_closed(monkeypatch) -> None:
    client = _StopClient({"id": "gld-replacement", "status": "new"})
    remembered = []
    decisions = []

    monkeypatch.setattr(
        bot3,
        "_remember_stop",
        lambda symbol, stop_order_id: remembered.append((symbol, stop_order_id)),
    )
    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decisions.append((args, kwargs)),
    )

    bot3._maintain_protective_stops(
        client,
        [{"symbol": "GLD", "qty": 61.0, "entry_price": 397.05}],
        "closed-session-cycle",
        equity_session_open=False,
    )

    assert len(client.submissions) == 1
    assert client.submissions[0][:4] == ("GLD", "sell", 61, "stop")
    assert remembered == [("GLD", "gld-replacement")]
    assert decisions == [
        (
            ("closed-session-cycle", "PROTECTIVE_STOP_REARMED"),
            {
                "order_id": "gld-replacement",
                "outcome": "new",
                "symbol": "GLD",
            },
        )
    ]


def test_broker_rejection_logs_and_records_arm_failure(monkeypatch, caplog) -> None:
    broker_response = {
        "status": "rejected",
        "code": 42210000,
        "message": "insufficient qty",
    }
    client = _StopClient(broker_response)
    decisions = []

    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decisions.append((args, kwargs)),
    )

    with caplog.at_level(logging.CRITICAL, logger="bot3.hard_assets"):
        with pytest.raises(RuntimeError, match="broker rejected protective stop"):
            bot3._maintain_protective_stops(
                client,
                [{"symbol": "SLV", "qty": 297.0, "entry_price": 58.24}],
                "rejection-cycle",
                equity_session_open=False,
            )

    assert "raw_broker_response=" + repr(broker_response) in caplog.text
    assert decisions == [
        (
            ("rejection-cycle", "PROTECTIVE_STOP_ARM_FAILED"),
            {
                "context": {
                    "error": "RuntimeError: broker rejected protective stop with status=rejected",
                    "raw_broker_response": repr(broker_response),
                },
                "reason": "RuntimeError: broker rejected protective stop with status=rejected",
                "symbol": "SLV",
            },
        )
    ]