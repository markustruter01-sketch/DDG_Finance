from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core import kill_switch as ks
from core import invariants
from core.bot_registry import active_bot_ids
from core.invariants import (
    InvariantInputs,
    check_ledger_broker_presence,
    check_reconciliation_health,
    check_stop_coverage,
    read_database_inputs,
)
from db import postgres
from execution import reconciliation


def _trade(
    *,
    trade_id: str = "trade-1",
    instrument: str = "EUR_USD",
    signed_units: float = 1000.0,
    stop_order_id: str | None = "stop-1",
    stop: dict | None = None,
) -> dict:
    return {
        "trade_id": trade_id,
        "instrument": instrument,
        "signed_units": signed_units,
        "stop_order_id": stop_order_id,
        "stop_loss_order": stop,
    }


def _covering_stop(
    *,
    trade_id: str = "trade-1",
    order_id: str = "stop-1",
    qty: float = 1000.0,
    side: str = "sell",
) -> dict:
    return {
        "id": order_id,
        "trade_id": trade_id,
        "qty": qty,
        "side": side,
        "type": "STOP_LOSS",
        "status": "pending",
    }


def _invariant_inputs(
    *,
    oanda_trades: list[dict] | None = None,
    forex_ai_trades: list[dict] | None = None,
) -> InvariantInputs:
    return InvariantInputs(
        broker_positions={bot_id: [] for bot_id in ks.ACTIVE_BOTS},
        broker_orders={bot_id: [] for bot_id in ks.ACTIVE_BOTS},
        ledger_positions={bot_id: [] for bot_id in ks.ACTIVE_BOTS},
        vault_symbols={bot_id: set() for bot_id in ks.ACTIVE_BOTS},
        oanda_trades=oanda_trades,
        forex_ai_trades=forex_ai_trades,
    )


@pytest.fixture(autouse=True)
def _clear_kill_switch_timers():
    ks._state["missing_stop_since"].clear()
    ks._state["mismatch_counts"].clear()
    yield
    ks._state["missing_stop_since"].clear()
    ks._state["mismatch_counts"].clear()


def test_registry_and_profile_include_paused_forex_safety_metadata():
    assert set(ks.ACTIVE_BOTS) == set(active_bot_ids())
    assert "forex_ai" in ks.ACTIVE_BOTS

    profile = ks._BOT_PROFILES["forex_ai"]
    assert "LEVERAGE_TIERS" not in profile
    assert profile["FOREX_MAX_GROSS"] == pytest.approx(2.0)
    assert "BOT_PAUSED" not in profile  # bots_state.paused is the only switch


@pytest.mark.parametrize(
    ("gross_multiple", "trips"),
    [(1.9, False), (2.0, False), (2.01, True)],
)
def test_forex_gross_cap_trips_only_above_2x_nav(gross_multiple, trips):
    account = {
        "bot_id": "forex_ai",
        "nav": 100.0,
        "equity": 100.0,
        "cash": -25.0,
        "long_market_value": 1000.0,
        "gross_exposure_usd": gross_multiple * 100.0,
        "positions": [],
        "orders": [],
    }

    triggers = ks.evaluate_account(account, now=100.0)
    trigger_names = {trigger["trigger"] for trigger in triggers}

    assert ("forex_gross_exposure" in trigger_names) is trips
    assert "negative_cash" not in trigger_names
    assert "leverage" not in trigger_names
    assert "deployment" not in trigger_names


@pytest.mark.parametrize("bot_id", ["oracle", "spy_qqq_trend", "jerome_macro"])
def test_alpaca_account_checks_keep_negative_cash_and_leverage_rules(bot_id):
    triggers = ks.evaluate_account(
        {
            "bot_id": bot_id,
            "equity": 100.0,
            "cash": -1.0,
            "long_market_value": 101.0,
            "positions": [],
            "vault_symbols": set(),
            "max_deployment": 1.0,
        },
        now=100.0,
    )
    trigger_names = {trigger["trigger"] for trigger in triggers}
    assert "negative_cash" in trigger_names
    assert "leverage" in trigger_names
    assert "forex_gross_exposure" not in trigger_names


def test_invariant_broker_reader_remains_limited_to_three_alpaca_accounts(monkeypatch):
    account_ids = []

    class _Account:
        equity = "100"

    class _AlpacaReadOnly:
        def get_account(self):
            return _Account()

        def get_all_positions(self):
            return []

        def get_orders(self, *, filter):
            assert filter.limit == 500
            return []

    def get_client(bot_id):
        account_ids.append(bot_id)
        return _AlpacaReadOnly()

    monkeypatch.setattr(invariants, "_broker_client", get_client)
    result = invariants.read_broker_inputs()

    assert account_ids == list(ks.ALPACA_BOTS)
    assert "forex_ai" not in result["broker_positions"]
    assert result["fleet_equity"] == 300.0


def test_naked_forex_trade_trips_after_sixty_seconds():
    account = {
        "bot_id": "forex_ai",
        "nav": 10_000.0,
        "gross_exposure_usd": 1_000.0,
        "positions": [
            {
                "asset_class": "forex",
                "trade_id": "trade-1",
                "symbol": "EUR_USD",
                "signed_units": 1000.0,
                "qty": 1000.0,
                "side": "long",
            }
        ],
        "orders": [],
    }

    assert ks.evaluate_account(account, now=100.0) == []
    assert ks.evaluate_account(account, now=160.0) == []
    triggers = ks.evaluate_account(account, now=160.1)
    assert triggers[0]["trigger"] == "missing_protective_stop"
    assert triggers[0]["trade_id"] == "trade-1"


def test_attached_full_size_forex_stop_covers_its_trade():
    position = {
        "asset_class": "forex",
        "trade_id": "trade-1",
        "symbol": "EUR_USD",
        "signed_units": 1000.0,
        "qty": 1000.0,
        "side": "long",
    }
    assert ks._covers(position, _covering_stop())
    assert not ks._covers(position, _covering_stop(trade_id="other-trade"))
    assert not ks._covers(position, _covering_stop(qty=999.0))
    assert not ks._covers(position, _covering_stop(side="buy"))


def test_oanda_reader_returns_nav_gross_positions_and_attached_stop():
    class _ReadOnlyOanda:
        def account_summary(self):
            return {"currency": "USD", "nav": "10000", "balance": "9800"}

        def open_trades(self):
            return [
                {
                    "id": "trade-1",
                    "instrument": "EUR_USD",
                    "currentUnits": "1000",
                    "price": "1.10",
                    "openTime": "2026-10-05T00:00:00Z",
                    "stopLossOrder": {
                        "id": "stop-1",
                        "tradeID": "trade-1",
                        "state": "PENDING",
                        "price": "1.05",
                    },
                }
            ]

        def current_bid_ask(self, instrument):
            assert instrument == "EUR_USD"
            return {"bid": 1.09, "ask": 1.11}

    snapshot = ks.read_oanda_account_snapshot(_ReadOnlyOanda())
    assert snapshot["nav"] == 10_000.0
    assert snapshot["cash"] == 9_800.0
    assert snapshot["gross_exposure_usd"] == pytest.approx(1_100.0)
    assert snapshot["positions"][0]["trade_id"] == "trade-1"
    assert ks._covers(snapshot["positions"][0], snapshot["orders"][0])
    assert snapshot["open_trades"][0]["stop_order_id"] == "stop-1"


def test_stop_coverage_invariant_checks_forex_trades_and_unknown_data():
    live_trade = _trade(stop=_covering_stop())
    result = check_stop_coverage(
        _invariant_inputs(oanda_trades=[live_trade], forex_ai_trades=[])
    )
    assert result["status"] == "PASS"

    naked = _trade(stop_order_id=None, stop=None)
    result = check_stop_coverage(
        _invariant_inputs(oanda_trades=[naked], forex_ai_trades=[])
    )
    assert result["status"] == "FAIL"
    assert result["actual"]["missing_stops"][0]["trade_id"] == "trade-1"

    inputs = _invariant_inputs(oanda_trades=None, forex_ai_trades=[])
    result = check_stop_coverage(inputs)
    assert result["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("instrument", "GBP_USD"),
        ("signed_units", 900.0),
        ("stop_order_id", "stop-2"),
    ],
)
def test_ledger_invariant_flags_each_oanda_trade_field_mismatch(field, changed_value):
    broker_trade = _trade()
    ledger_trade = _trade()
    ledger_trade[field] = changed_value

    result = check_ledger_broker_presence(
        _invariant_inputs(
            oanda_trades=[broker_trade],
            forex_ai_trades=[ledger_trade],
        )
    )
    assert result["status"] == "FAIL"
    assert field in result["actual"]["forex_trade_mismatches"][0]["differences"]


def test_ledger_invariant_passes_matching_forex_rows():
    trade = _trade()
    result = check_ledger_broker_presence(
        _invariant_inputs(oanda_trades=[trade], forex_ai_trades=[trade.copy()])
    )
    assert result["status"] == "PASS"


def test_forex_ledger_invariant_is_unknown_when_either_source_is_unreadable():
    trade = _trade()
    for inputs in (
        _invariant_inputs(oanda_trades=None, forex_ai_trades=[trade]),
        _invariant_inputs(oanda_trades=[trade], forex_ai_trades=None),
    ):
        assert check_ledger_broker_presence(inputs)["status"] == "UNKNOWN"


def test_reconciliation_health_reports_unknown_for_oanda_read_failure():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    result = check_reconciliation_health(
        InvariantInputs(
            now=now,
            reconciliation_rows=[
                {
                    "run_ts": now,
                    "clean": False,
                    "flags": [
                        {
                            "bot_id": "forex_ai",
                            "kind": "oanda_read_failed",
                            "status": "UNKNOWN",
                        }
                    ],
                }
            ],
        )
    )
    assert result["status"] == "UNKNOWN"


def test_live_reconciliation_records_oanda_read_failure_as_unknown(monkeypatch):
    def fail_oanda():
        raise RuntimeError("OANDA practice API request failed")

    monkeypatch.setattr(reconciliation, "ACTIVE_BOTS", ("forex_ai",))
    monkeypatch.setattr(reconciliation, "read_oanda_account_snapshot", fail_oanda)
    monkeypatch.setattr(reconciliation, "_pause_state_disagreements", lambda: [])
    monkeypatch.setattr(reconciliation, "_ledger_orphan_findings", lambda _positions: [])
    monkeypatch.setattr("core.fleet_equity.get_fleet_equity", lambda: (None, None))
    monkeypatch.setattr("core.bot_liveness.evaluate_liveness", lambda: [])

    snapshot = reconciliation.collect_live_snapshot()
    finding = snapshot["account_findings"][0]
    assert finding["kind"] == "oanda_read_failed"
    assert finding["status"] == "UNKNOWN"
    # One failed read is a blip: nothing trips. Three checks in a row: that bot's trigger (item 5).
    ks._state["read_fail_counts"] = {}; ks._state["read_fail_seen"] = {}
    assert not any(f["trigger"] == "missing_account" for f in ks.evaluate_snapshot(snapshot, now=100.0))
    for n in (2, 3):
        snapshot = {**snapshot, "captured_at": f"check-{n}"}
        flags = ks.evaluate_snapshot(snapshot, now=100.0)
    assert any(
        flag["trigger"] == "missing_account" and flag["status"] == "UNKNOWN" and flag["bot_id"] == "forex_ai"
        for flag in flags
    )
    result = check_reconciliation_health(
        InvariantInputs(
            now=datetime.now(timezone.utc),
            reconciliation_rows=[
                {
                    "run_ts": datetime.now(timezone.utc),
                    "clean": False,
                    "flags": flags,
                }
            ],
        )
    )
    assert result["status"] == "UNKNOWN"


class _StrictCursor:
    description = [
        ("instance_token",),
        ("pid",),
        ("environment",),
        ("execution_mode",),
        ("started_at",),
        ("last_beat_at",),
        ("loop_count",),
        ("bots_registered",),
        ("status",),
    ]

    def __init__(self, rows_by_table=None, fail_table=None):
        self.rows_by_table = rows_by_table or {}
        self.fail_table = fail_table
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        params = () if params is None else params
        if query.count("%s") != len(params):
            raise AssertionError("SQL placeholders and parameters do not match")
        self.query = query
        if self.fail_table and f"FROM {self.fail_table}" in query:
            raise RuntimeError("simulated read failure")

    def fetchall(self):
        for table, rows in self.rows_by_table.items():
            if f"FROM {table}" in self.query:
                return rows
        return []

    def fetchone(self):
        return None


class _StrictConnection:
    def __init__(self, rows_by_table=None, fail_table=None):
        self._cursor = _StrictCursor(rows_by_table, fail_table)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


def test_forex_database_reader_and_reconciliation_reader_use_strict_sql(monkeypatch):
    ledger_row = (
        "trade-1",
        "EUR_USD",
        1000.0,
        "stop-1",
        1.10,
        "standard",
        "open",
        datetime(2026, 10, 5, tzinfo=timezone.utc),
        None,
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    with patch(
        "psycopg2.connect",
        side_effect=lambda _dsn: _StrictConnection(
            {"forex_ai_trades": [ledger_row]}
        ),
    ):
        result = read_database_inputs(
            now=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
        )
    assert result["forex_ai_trades"][0]["trade_id"] == "trade-1"
    assert result["forex_ai_trades"][0]["signed_units"] == 1000.0

    monkeypatch.setattr(
        postgres,
        "get_conn",
        lambda: _StrictConnection({"forex_ai_trades": [ledger_row]}),
    )
    assert reconciliation._forex_ai_ledger_rows()[0]["stop_order_id"] == "stop-1"


def test_forex_database_read_failure_stays_unknown(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    with patch(
        "psycopg2.connect",
        side_effect=lambda _dsn: _StrictConnection(fail_table="forex_ai_trades"),
    ):
        result = read_database_inputs(
            now=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
        )
    assert result["forex_ai_trades"] is None
    assert result["_forex_ai_trades_error"] == "simulated read failure"


def test_forex_trade_schema_is_additive_and_contains_required_columns():
    sql = postgres._SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS forex_ai_trades" in sql
    for column in (
        "trade_id",
        "instrument",
        "signed_units",
        "entry_price",
        "stop_order_id",
        "leverage_tier",
        "status",
        "opened_at",
        "closed_at",
    ):
        assert column in sql