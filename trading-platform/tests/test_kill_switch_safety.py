from __future__ import annotations

import pytest

from core import kill_switch as ks


def setup_function():
    ks._state["tripped"] = False
    ks._state["last_snapshot"] = {}
    ks._state["missing_stop_since"] = {}
    ks._state["mismatch_counts"] = {}


def account(**overrides):
    value = {
        "bot_id": "oracle",
        "cash": 10.0,
        "equity": 100.0,
        "long_market_value": 50.0,
        "positions": [],
        "orders": [],
    }
    value.update(overrides)
    return value


def test_clean_account_has_no_flags():
    assert ks.evaluate_account(account(), now=100.0) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"cash": -1.0}, "negative_cash"),
        ({"long_market_value": 101.0}, "leverage"),
        ({"long_market_value": 86.0}, "deployment"),
    ],
)
def test_account_triggers(changes, expected):
    flags = ks.evaluate_account(account(**changes), now=100.0)
    assert expected in {flag["trigger"] for flag in flags}


def test_jerome_monitoring_cap_allows_fully_invested_strategy():
    flags = ks.evaluate_account(
        account(bot_id="jerome_macro", equity=100.0, long_market_value=100.0),
        now=100.0,
    )
    assert "deployment" not in {flag["trigger"] for flag in flags}


def test_missing_stop_requires_more_than_sixty_seconds():
    position = {"symbol": "ECH", "qty": 10, "side": "long"}
    snapshot = {"accounts": [account(positions=[position])], "fleet_equity": 100, "fleet_hwm": 100}
    assert ks.evaluate_snapshot(snapshot, now=100.0) == []
    assert ks.evaluate_snapshot(snapshot, now=160.0) == []
    assert "missing_protective_stop" in {
        f["trigger"] for f in ks.evaluate_snapshot(snapshot, now=160.1)
    }


def test_protective_stop_covers_position():
    position = {"symbol": "ECH", "qty": 10, "side": "long"}
    stop = {"symbol": "ECH", "qty": 10, "side": "sell", "type": "stop"}
    assert ks.evaluate_account(account(positions=[position], orders=[stop]), now=100) == []


def test_crypto_symbol_forms_match_for_stop_coverage():
    position = {"symbol": "BTCUSD", "qty": 0.3, "side": "long"}
    stop = {"symbol": "BTC/USD", "qty": 0.3, "side": "sell", "type": "stop_limit"}
    assert ks.evaluate_account(account(positions=[position], orders=[stop]), now=100) == []


def test_mismatch_must_persist_for_two_checks():
    snapshot = {
        "accounts": [account()],
        "fleet_equity": 100,
        "fleet_hwm": 100,
        "mismatches": [{"bot_id": "oracle", "symbol": "ECH", "kind": "broker_without_ledger"}],
    }
    assert ks.evaluate_snapshot(snapshot, now=100) == []
    flags = ks.evaluate_snapshot(snapshot, now=101)
    assert flags[0]["trigger"] == "broker_ledger_mismatch"


def test_fleet_drawdown_trigger():
    snapshot = {"accounts": [], "fleet_equity": 84, "fleet_hwm": 100}
    assert ks.evaluate_snapshot(snapshot, now=100)[0]["trigger"] == "fleet_drawdown"


def test_trip_pauses_bots_and_only_cancels_non_protective_orders(monkeypatch):
    paused = []
    cancelled = []

    monkeypatch.setattr(ks, "_set_all_paused", lambda reason: paused.append(reason))
    client = type("Client", (), {
        "cancel_order_by_id": lambda self, order_id: cancelled.append(order_id)
    })()
    snapshot = {
        "accounts": [{
            "bot_id": "oracle",
            "_client": client,
            "orders": [
                {"id": "limit-1", "side": "buy", "type": "limit"},
                {"id": "stop-1", "side": "sell", "type": "stop"},
            ],
        }]
    }
    monkeypatch.setattr(ks, "_write_event", lambda *args: None)
    result = ks.trip([{"trigger": "negative_cash"}], snapshot)
    assert result["tripped"] is True
    assert paused
    assert cancelled == ["limit-1"]
    assert "protective_stops_preserved" in result["action"]


def test_reset_requires_exact_confirmation_when_latched():
    ks._state["tripped"] = True
    with pytest.raises(ValueError):
        ks.reset()
    ks.reset(confirmation_token=ks.RESET_CONFIRMATION)
    assert ks.is_tripped() is False