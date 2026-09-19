from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from unittest.mock import patch

import pytest

from core import degradation_tracker
from core.invariants import (
    CRYPTO_EXPOSURE_LIMIT,
    PROPOSED_CRYPTO_DRIFT_BAND,
    InvariantInputs,
    check_crypto_exposure,
    check_cycle_freshness,
    check_degradations,
    check_kill_switch_parity,
    check_ledger_broker_presence,
    check_ledger_broker_quantities,
    check_published_runner_liveness,
    check_reconciliation_health,
    check_runner_heartbeat_fresh,
    check_stop_coverage,
    read_database_inputs,
    run_all_invariants,
)


@pytest.fixture
def base_inputs() -> InvariantInputs:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    return InvariantInputs(
        now=now,
        broker_positions={
            "oracle": [
                {
                    "symbol": "SPY",
                    "qty": 10.0,
                    "side": "long",
                    "market_value": 1000.0,
                }
            ],
            "spy_qqq_trend": [],
            "jerome_macro": [],
        },
        broker_orders={
            "oracle": [
                {
                    "symbol": "SPY",
                    "qty": 10.0,
                    "side": "sell",
                    "type": "stop",
                }
            ],
            "spy_qqq_trend": [],
            "jerome_macro": [],
        },
        ledger_positions={
            "oracle": [{"symbol": "SPY", "qty": 10.0}],
            "spy_qqq_trend": [],
            "jerome_macro": [],
        },
        vault_symbols={
            "oracle": {"BIL"},
            "spy_qqq_trend": {"BIL"},
            "jerome_macro": {"BIL", "VOO"},
        },
        fleet_equity=100_000.0,
        cycle_rows={
            bot_id: {
                "last_success_at": now - timedelta(seconds=60),
                "cycle_count": 3,
                "status": "success",
            }
            for bot_id in ("oracle", "spy_qqq_trend", "jerome_macro")
        },
        cycle_intervals={
            "oracle": 3600.0,
            "spy_qqq_trend": 3600.0,
            "jerome_macro": 3600.0,
        },
        reconciliation_rows=[
            {
                "run_ts": now - timedelta(minutes=1),
                "clean": True,
                "flags": [],
            }
        ],
        unresolved_degradations=[],
        kill_switch_runtime=False,
        kill_switch_config=False,
        published_runner=True,
        runner_heartbeat={
            "verdict": "ALIVE",
            "age_seconds": 4.0,
            "threshold_seconds": 15.0,
            "row": {"instance_token": "runner:v2:test"},
        },
    )


def _copy(inputs: InvariantInputs) -> InvariantInputs:
    return deepcopy(inputs)


class _DatabaseCursor:
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

    def __init__(self, heartbeat_row=None):
        self.heartbeat_row = heartbeat_row
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.query = query

    def fetchall(self):
        return []

    def fetchone(self):
        return self.heartbeat_row


class _DatabaseConnection:
    def __init__(self, heartbeat_row=None):
        self.cursor_instance = _DatabaseCursor(heartbeat_row)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def test_all_invariants_pass_with_clean_inputs(base_inputs):
    report = run_all_invariants(base_inputs)
    assert report["overall"] == "PASS"
    assert len(report["results"]) == 10
    assert all(
        {"name", "status", "actual", "expected", "difference", "message"}
        <= set(result)
        for result in report["results"]
    )


def test_runner_heartbeat_invariant_passes_for_fresh_heartbeat():
    result = check_runner_heartbeat_fresh(
        InvariantInputs(
            runner_heartbeat={
                "verdict": "ALIVE",
                "age_seconds": 4.0,
                "threshold_seconds": 15.0,
                "row": {"instance_token": "runner:v2:test"},
            }
        )
    )

    assert result["status"] == "PASS"


def test_runner_heartbeat_invariant_fails_for_stale_heartbeat():
    result = check_runner_heartbeat_fresh(
        InvariantInputs(
            runner_heartbeat={
                "verdict": "STALE",
                "age_seconds": 16.0,
                "threshold_seconds": 15.0,
                "row": {"instance_token": "runner:v2:test"},
            }
        )
    )

    assert result["status"] == "FAIL"
    assert "16.00 seconds" in result["message"]


def test_runner_heartbeat_invariant_fails_when_heartbeat_is_absent():
    result = check_runner_heartbeat_fresh(
        InvariantInputs(
            runner_heartbeat={
                "verdict": "ABSENT",
                "age_seconds": None,
                "threshold_seconds": 15.0,
                "row": None,
            }
        )
    )

    assert result["status"] == "FAIL"
    assert result["actual"]["verdict"] == "ABSENT"


def test_runner_heartbeat_invariant_is_unknown_when_timestamp_is_unreadable():
    result = check_runner_heartbeat_fresh(
        InvariantInputs(
            runner_heartbeat={
                "verdict": "UNREADABLE",
                "age_seconds": None,
                "threshold_seconds": 15.0,
                "row": {"instance_token": "runner:v2:test"},
            }
        )
    )

    assert result["status"] == "UNKNOWN"
    assert result["difference"] == {"invalid_verdict": "UNREADABLE"}
    assert "unreadable verdict" in result["message"]


def test_read_database_inputs_with_now_none_does_not_raise(monkeypatch):
    heartbeat_row = (
        "runner:v2:test",
        123,
        "dev",
        "read_only",
        datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 31, 12, 0, 4, tzinfo=timezone.utc),
        4,
        3,
        "running",
    )
    connection = _DatabaseConnection(heartbeat_row)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    with patch("psycopg2.connect", return_value=connection):
        result = read_database_inputs(now=None)

    assert result["runner_heartbeat"]["verdict"] in {"ALIVE", "STALE"}
    assert result["runner_heartbeat"]["age_seconds"] is not None


def test_read_database_inputs_marks_unparseable_heartbeat_unreadable(monkeypatch):
    heartbeat_row = (
        "runner:v2:test",
        123,
        "dev",
        "read_only",
        datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        "not-a-timestamp",
        4,
        3,
        "running",
    )
    connection = _DatabaseConnection(heartbeat_row)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    with patch("psycopg2.connect", return_value=connection):
        result = read_database_inputs(
            now=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        )

    assert result["runner_heartbeat"]["verdict"] == "UNREADABLE"
    assert result["runner_heartbeat"]["age_seconds"] is None


def test_stop_coverage_fires_when_stop_is_missing(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_orders["oracle"] = []
    result = check_stop_coverage(inputs)
    assert result["status"] == "FAIL"
    assert result["actual"]["missing_stops"][0]["symbol"] == "SPY"


def test_stop_coverage_unknown_when_input_is_unreadable(base_inputs):
    result = check_stop_coverage(replace(base_inputs, broker_positions=None))
    assert result["status"] == "UNKNOWN"


def test_stop_coverage_accepts_fractional_equity_remainder(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_positions["oracle"] = [
        {
            "symbol": "EWY",
            "qty": 43.355,
            "side": "long",
            "asset_class": "us_equity",
        }
    ]
    inputs.broker_orders["oracle"] = [
        {"symbol": "EWY", "qty": 43.0, "side": "sell", "type": "stop"}
    ]

    result = check_stop_coverage(inputs)

    assert result["status"] == "PASS"


def test_stop_coverage_rejects_equity_shortfall_of_a_whole_share(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_positions["oracle"] = [
        {
            "symbol": "EWY",
            "qty": 44.355,
            "side": "long",
            "asset_class": "us_equity",
        }
    ]
    inputs.broker_orders["oracle"] = [
        {"symbol": "EWY", "qty": 43.0, "side": "sell", "type": "stop"}
    ]

    result = check_stop_coverage(inputs)

    assert result["status"] == "FAIL"
    assert result["actual"]["quantity_mismatches"][0] == {
        "bot_id": "oracle",
        "symbol": "EWY",
        "position_qty": 44.355,
        "stop_quantities": [43.0],
        "covering_stop": False,
    }


def test_stop_coverage_accepts_exact_crypto_stop(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_positions["oracle"] = [
        {
            "symbol": "BTCUSD",
            "qty": 0.115235221,
            "side": "long",
            "asset_class": "crypto",
        }
    ]
    inputs.broker_orders["oracle"] = [
        {
            "symbol": "BTCUSD",
            "qty": 0.115235221,
            "side": "sell",
            "type": "stop",
        }
    ]

    result = check_stop_coverage(inputs)

    assert result["status"] == "PASS"


def test_stop_coverage_rejects_crypto_shortfall(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_positions["oracle"] = [
        {
            "symbol": "BTCUSD",
            "qty": 0.115235221,
            "side": "long",
            "asset_class": "crypto",
        }
    ]
    inputs.broker_orders["oracle"] = [
        {"symbol": "BTCUSD", "qty": 0.11, "side": "sell", "type": "stop"}
    ]

    result = check_stop_coverage(inputs)

    assert result["status"] == "FAIL"


def test_stop_coverage_still_reports_position_with_no_stop(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_positions["oracle"] = [
        {
            "symbol": "EWY",
            "qty": 43.355,
            "side": "long",
            "asset_class": "us_equity",
        }
    ]
    inputs.broker_orders["oracle"] = []

    result = check_stop_coverage(inputs)

    assert result["status"] == "FAIL"
    assert result["actual"]["missing_stops"] == [
        {"bot_id": "oracle", "symbol": "EWY", "position_qty": 43.355}
    ]


def test_stop_coverage_still_excludes_vault_symbol_without_stop(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_positions["oracle"] = [
        {
            "symbol": "BIL",
            "qty": 43.355,
            "side": "long",
            "asset_class": "us_equity",
        }
    ]
    inputs.broker_orders["oracle"] = []

    result = check_stop_coverage(inputs)

    assert result["status"] == "PASS"
    assert result["actual"]["checked_positions"] == 0
    assert result["actual"]["missing_stops"] == []


def _with_crypto_exposure(base_inputs, market_value: float) -> InvariantInputs:
    inputs = _copy(base_inputs)
    crypto_position = {
        "symbol": "BTC/USD",
        "qty": 0.1,
        "side": "long",
        "market_value": market_value,
    }
    inputs.broker_positions["jerome_macro"] = [crypto_position]
    inputs.broker_orders["jerome_macro"] = [
        {
            "symbol": "BTC/USD",
            "qty": 0.1,
            "side": "sell",
            "type": "stop",
        }
    ]
    inputs.ledger_positions["jerome_macro"] = [
        {"symbol": "BTC/USD", "qty": 0.1}
    ]
    return inputs


def test_crypto_exposure_passes_at_hard_cap(base_inputs):
    result = check_crypto_exposure(
        _with_crypto_exposure(base_inputs, base_inputs.fleet_equity * CRYPTO_EXPOSURE_LIMIT)
    )
    assert result["status"] == "PASS"
    assert result["actual"]["crypto_fraction"] == CRYPTO_EXPOSURE_LIMIT
    assert result["difference"]["ratio_minus_hard_cap"] == 0


def test_crypto_exposure_reports_drift_above_hard_cap(base_inputs):
    inputs = _with_crypto_exposure(base_inputs, 5001.0)
    result = check_crypto_exposure(inputs)
    assert result["status"] == "DRIFT"
    assert CRYPTO_EXPOSURE_LIMIT < result["actual"]["crypto_fraction"] <= PROPOSED_CRYPTO_DRIFT_BAND
    assert result["difference"]["ratio_minus_hard_cap"] > 0
    assert result["difference"]["ratio_minus_drift_band"] < 0


def test_crypto_exposure_reports_drift_at_proposed_band_boundary(base_inputs):
    result = check_crypto_exposure(
        _with_crypto_exposure(
            base_inputs, base_inputs.fleet_equity * PROPOSED_CRYPTO_DRIFT_BAND
        )
    )
    assert result["status"] == "DRIFT"
    assert result["difference"]["ratio_minus_drift_band"] == 0


def test_crypto_exposure_fails_above_proposed_drift_band(base_inputs):
    inputs = _with_crypto_exposure(base_inputs, 5501.0)
    result = check_crypto_exposure(inputs)
    assert result["status"] == "FAIL"
    assert result["actual"]["crypto_fraction"] > PROPOSED_CRYPTO_DRIFT_BAND
    assert result["difference"]["ratio_minus_drift_band"] > 0


def test_crypto_drift_does_not_fail_overall(base_inputs):
    inputs = _with_crypto_exposure(base_inputs, 5001.0)
    report = run_all_invariants(inputs)
    assert report["overall"] == "PASS"
    assert report["counts"]["DRIFT"] == 1
    assert report["counts"]["FAIL"] == 0


def test_crypto_exposure_unknown_when_equity_is_unreadable(base_inputs):
    result = check_crypto_exposure(replace(base_inputs, fleet_equity=None))
    assert result["status"] == "UNKNOWN"


def test_cycle_freshness_fires_when_success_is_older_than_three_intervals(base_inputs):
    inputs = _copy(base_inputs)
    inputs.cycle_rows["oracle"]["last_success_at"] = (
        inputs.now - timedelta(seconds=10_801)
    )
    result = check_cycle_freshness(inputs)
    assert result["status"] == "FAIL"
    assert result["difference"]["stale_bots"][0]["bot_id"] == "oracle"


def test_cycle_freshness_unknown_when_records_are_unreadable(base_inputs):
    result = check_cycle_freshness(replace(base_inputs, cycle_rows=None))
    assert result["status"] == "UNKNOWN"


def test_cycle_freshness_excludes_paused_bot_with_missing_success(base_inputs):
    inputs = replace(
        _copy(base_inputs),
        pause_states={
            "oracle": True,
            "spy_qqq_trend": False,
            "jerome_macro": False,
        },
    )
    inputs.cycle_rows["oracle"]["last_success_at"] = None

    result = check_cycle_freshness(inputs)

    assert result["status"] == "PASS"
    assert result["actual"]["paused"] == [
        {"bot_id": "oracle", "reason": "intentionally paused"}
    ]
    assert result["actual"]["missing_or_unreadable"] == []


def test_cycle_freshness_keeps_unpaused_missing_success_unknown(base_inputs):
    inputs = _copy(base_inputs)
    inputs.pause_states = {
        "oracle": False,
        "spy_qqq_trend": False,
        "jerome_macro": False,
    }
    inputs.cycle_rows["oracle"]["last_success_at"] = None

    result = check_cycle_freshness(inputs)

    assert result["status"] == "UNKNOWN"
    assert result["actual"]["missing_or_unreadable"] == [
        {"bot_id": "oracle", "last_success_at": None}
    ]


def test_cycle_freshness_names_stale_unpaused_bot_while_paused_bot_is_excluded(
    base_inputs,
):
    inputs = replace(
        _copy(base_inputs),
        pause_states={
            "oracle": True,
            "spy_qqq_trend": False,
            "jerome_macro": False,
        },
    )
    inputs.cycle_rows["oracle"]["last_success_at"] = None
    inputs.cycle_rows["spy_qqq_trend"]["last_success_at"] = (
        inputs.now - timedelta(seconds=10_801)
    )

    result = check_cycle_freshness(inputs)

    assert result["status"] == "FAIL"
    assert [row["bot_id"] for row in result["difference"]["stale_bots"]] == [
        "spy_qqq_trend"
    ]
    assert result["actual"]["paused"] == [
        {"bot_id": "oracle", "reason": "intentionally paused"}
    ]


def test_cycle_freshness_without_pause_states_matches_previous_behavior(base_inputs):
    inputs = _copy(base_inputs)
    inputs.cycle_rows["oracle"]["last_success_at"] = None

    result = check_cycle_freshness(inputs)

    assert result["status"] == "UNKNOWN"
    assert result["actual"]["paused"] == []
    assert result["actual"]["missing_or_unreadable"] == [
        {"bot_id": "oracle", "last_success_at": None}
    ]


def test_cycle_freshness_passes_when_all_active_bots_are_paused(base_inputs):
    inputs = replace(
        _copy(base_inputs),
        pause_states={
            "oracle": True,
            "spy_qqq_trend": True,
            "jerome_macro": True,
        },
    )
    for row in inputs.cycle_rows.values():
        row["last_success_at"] = None

    result = check_cycle_freshness(inputs)

    assert result["status"] == "PASS"
    assert [row["bot_id"] for row in result["actual"]["paused"]] == [
        "oracle",
        "spy_qqq_trend",
        "jerome_macro",
    ]
    assert result["actual"]["missing_or_unreadable"] == []
    assert (
        result["message"]
        == "No bot is expected to be cycling because all active bots are intentionally paused."
    )


def test_reconciliation_fires_when_latest_row_is_not_clean(base_inputs):
    inputs = _copy(base_inputs)
    inputs.reconciliation_rows[0]["clean"] = False
    result = check_reconciliation_health(inputs)
    assert result["status"] == "FAIL"
    assert result["actual"]["clean"] is False


def test_reconciliation_unknown_when_log_is_unreadable(base_inputs):
    result = check_reconciliation_health(
        replace(base_inputs, reconciliation_rows=None)
    )
    assert result["status"] == "UNKNOWN"


def test_degradations_fires_for_unresolved_high_severity_event(base_inputs):
    inputs = _copy(base_inputs)
    inputs.unresolved_degradations = [
        {"id": 7, "severity": "high", "message": "test degradation"}
    ]
    result = check_degradations(inputs)
    assert result["status"] == "FAIL"
    assert result["actual"]["unresolved_count"] == 1


def test_degradations_ignores_only_its_own_unresolved_rows(base_inputs):
    inputs = _copy(base_inputs)
    inputs.unresolved_degradations = [
        {
            "id": 7,
            "severity": "high",
            "error_type": "zero_unresolved_high_severity_degradations",
        }
    ]

    result = check_degradations(inputs)

    assert result["status"] == "PASS"
    assert result["actual"]["unresolved_count"] == 0
    assert result["actual"]["excluded_self_count"] == 1


def test_degradations_counts_other_rows_but_not_its_own(base_inputs):
    inputs = _copy(base_inputs)
    inputs.unresolved_degradations = [
        {
            "id": 7,
            "severity": "critical",
            "error_type": "zero_unresolved_high_severity_degradations",
        },
        {
            "id": 8,
            "severity": "high",
            "error_type": "different_condition",
        },
    ]

    result = check_degradations(inputs)

    assert result["status"] == "FAIL"
    assert result["actual"]["unresolved_count"] == 1
    assert result["actual"]["excluded_self_count"] == 1
    assert result["message"] == "1 unresolved high-severity degradation event(s) remain."


def test_degradations_unknown_when_log_is_unreadable(base_inputs):
    result = check_degradations(
        replace(base_inputs, unresolved_degradations=None)
    )
    assert result["status"] == "UNKNOWN"


class _FakeDegradationCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executions = []
        self.rowcount = 0
        self._fetchone = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params=()):
        self.executions.append((sql, params))
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("SELECT COUNT"):
            component, error_type = params
            self._fetchone = (
                sum(
                    1
                    for row in self.rows
                    if not row["resolved"]
                    and row["component"] == component
                    and row["error_type"] == error_type
                ),
            )
            return
        if normalized.startswith("UPDATE"):
            reason, *filters = params
            if "ID = %S" in normalized:
                event_id = filters[0]
                matching = [
                    row
                    for row in self.rows
                    if not row["resolved"] and row["id"] == event_id
                ]
            else:
                component, error_type = filters
                matching = [
                    row
                    for row in self.rows
                    if not row["resolved"]
                    and row["component"] == component
                    and row["error_type"] == error_type
                ]
            for row in matching:
                row["resolved"] = True
                row["reason"] = reason
            self.rowcount = len(matching)

    def fetchone(self):
        return self._fetchone


class _FakeDegradationConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return self.cursor_value


def _patch_degradation_database(monkeypatch, cursor):
    import db.postgres

    monkeypatch.setattr(db.postgres, "is_pg_available", lambda: True)
    monkeypatch.setattr(
        db.postgres,
        "get_conn",
        lambda: _FakeDegradationConnection(cursor),
    )


def test_mark_resolved_with_event_id_resolves_exactly_that_row(monkeypatch):
    cursor = _FakeDegradationCursor(
        [
            {"id": 7, "component": "oracle", "error_type": "stale", "resolved": False},
            {"id": 8, "component": "oracle", "error_type": "stale", "resolved": False},
        ]
    )
    _patch_degradation_database(monkeypatch, cursor)

    assert degradation_tracker.mark_resolved(
        "oracle",
        "stale",
        event_id=7,
    ) == 1
    assert cursor.rows[0]["resolved"] is True
    assert cursor.rows[1]["resolved"] is False
    assert len(cursor.executions) == 1


def test_mark_resolved_without_event_id_resolves_all_five_matching_rows(monkeypatch):
    cursor = _FakeDegradationCursor(
        [
            {"id": index, "component": "oracle", "error_type": "stale", "resolved": False}
            for index in range(1, 6)
        ]
    )
    _patch_degradation_database(monkeypatch, cursor)

    assert degradation_tracker.mark_resolved("oracle", "stale") == 5
    assert all(row["resolved"] for row in cursor.rows)
    assert len(cursor.executions) == 2


def test_mark_resolved_without_event_id_does_not_touch_different_error_type(monkeypatch):
    cursor = _FakeDegradationCursor(
        [
            {"id": 1, "component": "oracle", "error_type": "stale", "resolved": False},
            {"id": 2, "component": "oracle", "error_type": "other", "resolved": False},
        ]
    )
    _patch_degradation_database(monkeypatch, cursor)

    assert degradation_tracker.mark_resolved("oracle", "stale") == 1
    assert cursor.rows[0]["resolved"] is True
    assert cursor.rows[1]["resolved"] is False


def test_mark_resolved_bulk_guard_resolves_nothing_above_limit(monkeypatch):
    cursor = _FakeDegradationCursor(
        [
            {
                "id": index,
                "component": "oracle",
                "error_type": "stale",
                "resolved": False,
            }
            for index in range(degradation_tracker.MAX_BULK_RESOLVE_ROWS + 1)
        ]
    )
    _patch_degradation_database(monkeypatch, cursor)

    with patch.object(degradation_tracker.logger, "error") as log_error:
        assert degradation_tracker.mark_resolved("oracle", "stale") == 0

    assert all(not row["resolved"] for row in cursor.rows)
    assert len(cursor.executions) == 1
    log_error.assert_called_once()


def test_kill_switch_parity_fires_when_runtime_disagrees(base_inputs):
    result = check_kill_switch_parity(
        replace(base_inputs, kill_switch_runtime=True)
    )
    assert result["status"] == "FAIL"
    assert result["difference"]["runtime_minus_config"] == 1


def test_kill_switch_parity_unknown_when_runtime_is_unreadable(base_inputs):
    result = check_kill_switch_parity(
        replace(base_inputs, kill_switch_runtime=None)
    )
    assert result["status"] == "UNKNOWN"


def test_ledger_broker_presence_fires_for_ledger_orphan(base_inputs):
    inputs = _copy(base_inputs)
    inputs.ledger_positions["oracle"].append({"symbol": "QQQ", "qty": 1.0})
    result = check_ledger_broker_presence(inputs)
    assert result["status"] == "FAIL"
    assert result["actual"]["ledger_without_broker"][0]["symbol"] == "QQQ"


def test_ledger_broker_presence_unknown_when_ledger_is_unreadable(base_inputs):
    result = check_ledger_broker_presence(
        replace(base_inputs, ledger_positions=None)
    )
    assert result["status"] == "UNKNOWN"


def test_ledger_broker_quantities_fires_for_common_quantity_mismatch(base_inputs):
    inputs = _copy(base_inputs)
    inputs.ledger_positions["oracle"][0]["qty"] = 10.5
    result = check_ledger_broker_quantities(inputs)
    assert result["status"] == "FAIL"
    assert result["actual"]["mismatches"][0]["difference"] == 0.5


def test_ledger_broker_quantities_unknown_when_broker_is_unreadable(base_inputs):
    result = check_ledger_broker_quantities(
        replace(base_inputs, broker_positions=None)
    )
    assert result["status"] == "UNKNOWN"


def test_published_runner_liveness_fires_for_stale_durable_cycle(base_inputs):
    inputs = _copy(base_inputs)
    for row in inputs.cycle_rows.values():
        row["last_success_at"] = inputs.now - timedelta(seconds=10_801)
    result = check_published_runner_liveness(inputs)
    assert result["status"] == "FAIL"
    assert result["difference"]["age_minus_threshold_seconds"] > 0


def test_published_runner_liveness_unknown_when_durable_source_is_unreadable(
    base_inputs,
):
    result = check_published_runner_liveness(
        replace(base_inputs, cycle_rows=None)
    )
    assert result["status"] == "UNKNOWN"