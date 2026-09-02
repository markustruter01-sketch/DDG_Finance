from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from copy import deepcopy

import pytest

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


def test_all_invariants_pass_with_clean_inputs(base_inputs):
    report = run_all_invariants(base_inputs)
    assert report["overall"] == "PASS"
    assert len(report["results"]) == 10
    assert all(
        {"name", "status", "actual", "expected", "difference", "message"}
        <= set(result)
        for result in report["results"]
    )


def test_stop_coverage_fires_when_stop_is_missing(base_inputs):
    inputs = _copy(base_inputs)
    inputs.broker_orders["oracle"] = []
    result = check_stop_coverage(inputs)
    assert result["status"] == "FAIL"
    assert result["actual"]["missing_stops"][0]["symbol"] == "SPY"


def test_stop_coverage_unknown_when_input_is_unreadable(base_inputs):
    result = check_stop_coverage(replace(base_inputs, broker_positions=None))
    assert result["status"] == "UNKNOWN"


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


def test_degradations_unknown_when_log_is_unreadable(base_inputs):
    result = check_degradations(
        replace(base_inputs, unresolved_degradations=None)
    )
    assert result["status"] == "UNKNOWN"


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