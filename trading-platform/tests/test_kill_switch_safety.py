from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from core import kill_switch as ks
from core import bot_state
from core.bot_registry import normalise_bot_id
from execution import reconciliation


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
        "vault_symbols": set(),
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


@pytest.mark.parametrize("symbol", ["SGOV", "sgov", "S-GOV", "s/gov"])
def test_cash_park_symbol_variants_match_canonically(symbol):
    assert ks.is_cash_park(symbol)


def test_cash_park_is_not_deployed_or_missing_a_stop():
    position = {
        "symbol": "s/gov",
        "qty": 900,
        "market_value": 80_000.0,
        "side": "long",
    }
    snapshot = account(
        equity=100_000.0,
        long_market_value=90_000.0,
        max_deployment=0.20,
        positions=[position],
    )

    assert ks.evaluate_account(snapshot, now=100.0) == []
    flags = ks.evaluate_account(snapshot, now=160.1)
    assert "deployment" not in {flag["trigger"] for flag in flags}
    assert "missing_protective_stop" not in {flag["trigger"] for flag in flags}


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


def test_equity_fractional_remainder_above_whole_share_stop_is_covered():
    position = {"symbol": "EWY", "qty": 43.355, "side": "long", "asset_class": "us_equity"}
    stop = {"symbol": "EWY", "qty": 43, "side": "sell", "type": "stop"}
    assert ks._covers(position, stop) is True


def test_equity_whole_share_shortfall_is_uncovered():
    position = {"symbol": "EWY", "qty": 44.355, "side": "long", "asset_class": "us_equity"}
    stop = {"symbol": "EWY", "qty": 43, "side": "sell", "type": "stop"}
    assert ks._covers(position, stop) is False


def test_equity_exact_whole_share_shortfall_is_uncovered():
    position = {"symbol": "EWY", "qty": 43.0, "side": "long", "asset_class": "us_equity"}
    stop = {"symbol": "EWY", "qty": 42, "side": "sell", "type": "stop"}
    assert ks._covers(position, stop) is False


def test_crypto_fractional_stop_remains_covered():
    position = {"symbol": "BTCUSD", "qty": 0.115235221, "side": "long", "asset_class": "crypto"}
    stop = {"symbol": "BTCUSD", "qty": 0.115235221, "side": "sell", "type": "stop_limit"}
    assert ks._covers(position, stop) is True


def test_crypto_fractional_shortfall_remains_uncovered():
    position = {"symbol": "BTCUSD", "qty": 0.115235221, "side": "long", "asset_class": "crypto"}
    stop = {"symbol": "BTCUSD", "qty": 0.11, "side": "sell", "type": "stop_limit"}
    assert ks._covers(position, stop) is False


def test_missing_asset_class_uses_equity_tolerance():
    position = {"symbol": "EWY", "qty": 43.355, "side": "long"}
    stop = {"symbol": "EWY", "qty": 43, "side": "sell", "type": "stop"}
    assert ks._covers(position, stop) is True


def test_crypto_symbol_forms_match_for_stop_coverage():
    position = {"symbol": "BTCUSD", "qty": 0.3, "side": "long"}
    stop = {"symbol": "BTC/USD", "qty": 0.3, "side": "sell", "type": "stop_limit"}
    assert ks.evaluate_account(account(positions=[position], orders=[stop]), now=100) == []


def test_unknown_vault_symbols_skip_stop_coverage_for_that_bot():
    position = {"symbol": "ECH", "qty": 10, "side": "long"}

    flags = ks.evaluate_account(
        account(positions=[position], vault_symbols=None),
        now=160.1,
    )
    trigger_names = {flag["trigger"] for flag in flags}

    assert "vault_symbols_unknown" in trigger_names
    assert "missing_protective_stop" not in trigger_names


def test_missing_vault_symbols_skip_stop_coverage_for_that_bot():
    position = {"symbol": "ECH", "qty": 10, "side": "long"}
    value = account(positions=[position])
    value.pop("vault_symbols")

    flags = ks.evaluate_account(value, now=160.1)
    trigger_names = {flag["trigger"] for flag in flags}

    assert "vault_symbols_unknown" in trigger_names
    assert "missing_protective_stop" not in trigger_names


def test_valid_vault_symbols_still_exclude_vault_positions():
    position = {"symbol": "ECH", "qty": 10, "side": "long"}

    flags = ks.evaluate_account(
        account(positions=[position], vault_symbols={"ECH"}),
        now=160.1,
    )

    assert flags == []


def test_one_bot_vault_failure_does_not_suppress_another_bots_triggers():
    position = {"symbol": "ECH", "qty": 10, "side": "long"}
    snapshot = {
        "accounts": [
            account(positions=[position], vault_symbols=None),
            account(bot_id="jerome_macro", positions=[position]),
        ],
        "fleet_equity": 100,
        "fleet_hwm": 100,
    }

    ks.evaluate_snapshot(snapshot, now=100)
    flags = ks.evaluate_snapshot(snapshot, now=161)
    trigger_names = {flag["trigger"] for flag in flags}

    assert "vault_symbols_unknown" in trigger_names
    assert "missing_protective_stop" in trigger_names


def test_collect_live_snapshot_keeps_other_bots_when_vault_read_fails(monkeypatch):
    class _Client:
        def get_account(self):
            return SimpleNamespace(equity="100", cash="50")

    def fake_vault_symbols(bot_id):
        if bot_id == "oracle":
            raise RuntimeError("vault database unavailable")
        return set()

    monkeypatch.setattr(reconciliation, "_vault_symbols", fake_vault_symbols)
    monkeypatch.setattr(reconciliation, "_client_for", lambda _bot_id: _Client())
    monkeypatch.setattr(reconciliation, "_positions", lambda _client: [])
    monkeypatch.setattr(reconciliation, "_orders", lambda _client: [])
    monkeypatch.setattr(reconciliation, "_ledger_positions", lambda _bot_id: [])
    monkeypatch.setattr(reconciliation, "_mismatches", lambda *_args: [])
    monkeypatch.setattr(
        reconciliation,
        "_authoritative_quantity_mismatches",
        lambda *_args: [],
    )
    monkeypatch.setattr(reconciliation, "_order_mismatches", lambda *_args: [])
    monkeypatch.setattr(reconciliation, "_stale_portfolio", lambda _bot_id: [])
    monkeypatch.setattr(
        reconciliation,
        "_ledger_orphan_findings",
        lambda _positions: [],
    )
    monkeypatch.setattr(reconciliation, "_pause_state_disagreements", lambda: [])
    monkeypatch.setattr(
        "core.fleet_equity.get_fleet_equity",
        lambda: (None, None),
    )
    monkeypatch.setattr("core.bot_liveness.evaluate_liveness", lambda: [])

    snapshot = reconciliation.collect_live_snapshot()
    accounts = {
        account["bot_id"]: account
        for account in snapshot["accounts"]
    }

    assert accounts["oracle"]["vault_symbols"] is None
    assert accounts["jerome_macro"]["vault_symbols"] == set()
    assert {
        "kind": "reconciliation_check_failed",
        "check": "vault_symbols_read",
        "error": "vault database unavailable",
        "bot_id": "oracle",
    } in snapshot["mismatches"]


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


def test_unknown_fleet_equity_triggers_fail_closed_without_drawdown():
    snapshot = {"accounts": [], "fleet_equity": None, "fleet_hwm": 100}

    triggers = ks.evaluate_snapshot(snapshot, now=100)
    trigger_names = {trigger["trigger"] for trigger in triggers}

    assert "fleet_equity_unknown" in trigger_names
    assert "fleet_drawdown" not in trigger_names


def test_zero_fleet_equity_triggers_fail_closed():
    snapshot = {"accounts": [], "fleet_equity": 0, "fleet_hwm": 100}

    triggers = ks.evaluate_snapshot(snapshot, now=100)

    assert "fleet_equity_unknown" in {trigger["trigger"] for trigger in triggers}


def test_valid_fleet_equity_below_high_water_mark_triggers_drawdown():
    snapshot = {"accounts": [], "fleet_equity": 84, "fleet_hwm": 100}

    triggers = ks.evaluate_snapshot(snapshot, now=100)
    trigger_names = {trigger["trigger"] for trigger in triggers}

    assert "fleet_drawdown" in trigger_names
    assert "fleet_equity_unknown" not in trigger_names


def test_fleet_equity_at_high_water_mark_has_neither_trigger():
    snapshot = {"accounts": [], "fleet_equity": 100, "fleet_hwm": 100}

    triggers = ks.evaluate_snapshot(snapshot, now=100)
    trigger_names = {trigger["trigger"] for trigger in triggers}

    assert "fleet_equity_unknown" not in trigger_names
    assert "fleet_drawdown" not in trigger_names


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


def test_reset_requires_exact_confirmation_when_latched(monkeypatch):
    ks._state["tripped"] = True
    monkeypatch.delenv("KILL_SWITCH_RESET_CONFIRMATION", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        ks.reset()

    monkeypatch.setenv("KILL_SWITCH_RESET_CONFIRMATION", "unit-test-confirmation")
    with pytest.raises(ValueError, match="Invalid"):
        ks.reset(confirmation_token="wrong")
    ks.reset(confirmation_token=os.environ["KILL_SWITCH_RESET_CONFIRMATION"])
    assert ks.is_tripped() is False
    assert "reset_confirmation" not in ks.get_state()


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("oracle", "oracle"),
        ("bot1_global", "oracle"),
        ("asia_trend_strategy", "oracle"),
        ("davy-jones", "oracle"),
        ("bot2_spy_qqq", "spy_qqq_trend"),
        ("spy_qqq_trend", "spy_qqq_trend"),
        ("bot3_reserved", "jerome_macro"),
        ("blackbeard", "jerome_macro"),
    ],
)
def test_all_stage_2b_aliases_resolve_to_canonical_ids(alias, canonical):
    assert normalise_bot_id(alias) == canonical


class _PauseCursor:
    description = [("paused",)]

    def __init__(self, paused):
        self.paused = paused
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, _query, params):
        self.params = params

    def fetchone(self):
        return (self.paused,)


class _PauseConnection:
    def __init__(self, paused):
        self.cursor_instance = _PauseCursor(paused)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("bot1_global", "oracle"),
        ("davy-jones", "oracle"),
        ("bot2_spy_qqq", "spy_qqq_trend"),
        ("bot3_reserved", "jerome_macro"),
        ("blackbeard", "jerome_macro"),
    ],
)
def test_pause_lookup_by_any_alias_uses_same_canonical_row(monkeypatch, alias, canonical):
    connection = _PauseConnection(True)
    monkeypatch.setattr(bot_state, "_get_conn", lambda: connection)
    assert bot_state.is_paused(alias) is True
    assert connection.cursor_instance.params == (canonical,)