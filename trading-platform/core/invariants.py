"""Read-only standing invariants for the trading platform.

This module deliberately does not call reconciliation, kill-switch mutation,
order, position, stop, or alert-delivery functions.  Collection uses SELECTs
and broker read APIs only; comparison functions are pure and accept an
``InvariantInputs`` value so every rule can be tested without a database or
broker connection.

Threshold sources
-----------------
* ``1e-8`` quantity tolerance: task policy and the numeric comparison contract.
* ``3 * cycle interval``: the established threshold in ``core.bot_liveness``.
* ``high``/``critical``/``error``: the established health severity set.
* ``5%`` crypto exposure: task policy; no existing configuration source was
  found, so it remains the unchanged hard cap.
* ``5.5%`` crypto exposure: proposed appreciation drift band, explicitly
  labelled as proposed in every crypto result.
* ``90 minutes`` reconciliation freshness: proposed policy.  The scheduler
  runs hourly, but no existing freshness threshold was found; the extra
  half-hour is only a proposed grace period.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from loguru import logger

from core.bot_liveness import (
    ACTIVE_BOTS,
    DEFAULT_CYCLE_INTERVALS,
)
from core.runner_heartbeat import (
    RUNNER_HEARTBEAT_THRESHOLD_SECONDS,
)
from core.symbols import canonical_symbol, is_crypto_symbol


Status = Literal["PASS", "DRIFT", "FAIL", "UNKNOWN"]

QUANTITY_TOLERANCE = 1e-8
# PROPOSED — 0.5 percentage-point appreciation allowance above the hard cap.
# This avoids alert flapping between scheduled rebalances; it does not permit
# a new position to breach the 5% cap before submission.
PROPOSED_CRYPTO_DRIFT_BAND = 0.055
CRYPTO_EXPOSURE_LIMIT = 0.05
CYCLE_FRESHNESS_MULTIPLIER = 3.0
PROPOSED_RECON_MAX_AGE_MINUTES = 90.0
INVARIANT_SCHEDULE_MINUTES = 15
DUST_QTY = 1e-6
UNRESOLVED_HIGH_SEVERITIES = frozenset({"high", "critical", "error"})

THRESHOLD_SOURCES = {
    "stop_coverage": "TASK POLICY: quantity tolerance is 1e-8; vault and dust exclusions are explicit task rules",
    "crypto_exposure": "PROPOSED: 5.5% drift band for appreciation between scheduled rebalances; 5% hard cap remains task policy",
    "cycle_freshness": "ESTABLISHED: core.bot_liveness uses 3 × configured cycle interval",
    "reconciliation": "PROPOSED: 90 minutes; hourly scheduler plus 30-minute proposed grace period",
    "degradations": "ESTABLISHED: system health treats high, critical, and error as non-green",
    "kill_switch": "ESTABLISHED: runtime core.kill_switch state compared with configured kill-switch arm value",
    "ledger_broker_presence": "TASK POLICY: every material strategy row must exist in both sources; vault and dust excluded",
    "ledger_broker_quantity": "TASK POLICY: quantity tolerance is 1e-8; vault and dust excluded",
    "published_runner_liveness": "ESTABLISHED: durable bot cycle records compared with 3 × configured cycle interval",
    "runner_heartbeat": "ESTABLISHED: core.runner_heartbeat uses 3 × the runner loop interval",
}


@dataclass
class InvariantInputs:
    """All inputs needed by the pure invariant functions.

    ``None`` means the source could not be read.  An empty collection means the
    source was read successfully and contained no rows.
    """

    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    broker_positions: dict[str, list[dict[str, Any]]] | None = None
    broker_orders: dict[str, list[dict[str, Any]]] | None = None
    ledger_positions: dict[str, list[dict[str, Any]]] | None = None
    vault_symbols: dict[str, set[str]] | None = None
    fleet_equity: float | None = None
    cycle_rows: dict[str, dict[str, Any]] | None = None
    cycle_intervals: dict[str, float] | None = None
    reconciliation_rows: list[dict[str, Any]] | None = None
    unresolved_degradations: list[dict[str, Any]] | None = None
    kill_switch_runtime: bool | None = None
    kill_switch_config: bool | None = None
    published_runner: bool | None = None
    runner_heartbeat: dict[str, Any] | None = None
    source_errors: dict[str, str] = field(default_factory=dict)


def _result(
    name: str,
    status: Status,
    *,
    actual: Any,
    expected: Any,
    difference: Any,
    message: str,
    threshold_source: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "actual": actual,
        "expected": expected,
        "difference": difference,
        "message": message,
        "threshold_source": threshold_source,
    }


def _unknown(
    name: str,
    *,
    actual: Any,
    expected: Any,
    difference: Any,
    message: str,
    source_key: str,
) -> dict[str, Any]:
    return _result(
        name,
        "UNKNOWN",
        actual=actual,
        expected=expected,
        difference=difference,
        message=message,
        threshold_source=THRESHOLD_SOURCES[source_key],
    )


def _failed(
    name: str,
    *,
    actual: Any,
    expected: Any,
    difference: Any,
    message: str,
    source_key: str,
) -> dict[str, Any]:
    return _result(
        name,
        "FAIL",
        actual=actual,
        expected=expected,
        difference=difference,
        message=message,
        threshold_source=THRESHOLD_SOURCES[source_key],
    )


def _drift(
    name: str,
    *,
    actual: Any,
    expected: Any,
    difference: Any,
    message: str,
    source_key: str,
) -> dict[str, Any]:
    return _result(
        name,
        "DRIFT",
        actual=actual,
        expected=expected,
        difference=difference,
        message=message,
        threshold_source=THRESHOLD_SOURCES[source_key],
    )


def _passed(
    name: str,
    *,
    actual: Any,
    expected: Any,
    difference: Any,
    message: str,
    source_key: str,
) -> dict[str, Any]:
    return _result(
        name,
        "PASS",
        actual=actual,
        expected=expected,
        difference=difference,
        message=message,
        threshold_source=THRESHOLD_SOURCES[source_key],
    )


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_problem(inputs: InvariantInputs, *keys: str) -> str | None:
    problems = [inputs.source_errors[key] for key in keys if key in inputs.source_errors]
    return "; ".join(problems) if problems else None


def _vault_for(inputs: InvariantInputs, bot_id: str) -> set[str]:
    return {
        canonical_symbol(symbol)
        for symbol in (inputs.vault_symbols or {}).get(bot_id, set())
    }


def _material_qty(row: dict[str, Any]) -> float:
    try:
        return abs(float(row.get("qty") or 0))
    except (TypeError, ValueError):
        return 0.0


def _position_maps(
    positions: dict[str, list[dict[str, Any]]],
    vault_symbols: dict[str, set[str]],
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for bot_id, rows in positions.items():
        vault = {canonical_symbol(symbol) for symbol in vault_symbols.get(bot_id, set())}
        by_symbol: dict[str, float] = {}
        for row in rows:
            qty = _material_qty(row)
            symbol = canonical_symbol(row.get("symbol"))
            if qty < DUST_QTY or not symbol or symbol in vault:
                continue
            by_symbol[symbol] = by_symbol.get(symbol, 0.0) + qty
        result[bot_id] = by_symbol
    return result


def check_stop_coverage(inputs: InvariantInputs) -> dict[str, Any]:
    name = "strategy_positions_have_covering_stops"
    expected = {
        "covering_stop": True,
        "quantity_tolerance": QUANTITY_TOLERANCE,
        "excluded": ["vault holdings", f"dust qty < {DUST_QTY}"],
    }
    problem = _source_problem(inputs, "broker_positions", "broker_orders", "vault_symbols")
    if inputs.broker_positions is None or inputs.broker_orders is None or inputs.vault_symbols is None:
        return _unknown(
            name,
            actual={"source_error": problem or "broker positions, orders, or vault holdings unreadable"},
            expected=expected,
            difference={"unreadable_sources": 1},
            message="Cannot verify stop coverage because a required read was unavailable.",
            source_key="stop_coverage",
        )

    missing: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    checked = 0
    for bot_id, positions in inputs.broker_positions.items():
        vault = _vault_for(inputs, bot_id)
        orders = inputs.broker_orders.get(bot_id, [])
        for position in positions:
            qty = _material_qty(position)
            symbol = canonical_symbol(position.get("symbol"))
            if qty < DUST_QTY or symbol in vault:
                continue
            checked += 1
            position_side = str(position.get("side", "long")).lower()
            protective_side = "buy" if position_side == "short" else "sell"
            stops = [
                order
                for order in orders
                if canonical_symbol(order.get("symbol")) == symbol
                and str(order.get("side", "")).lower() == protective_side
                and str(order.get("type", "")).lower()
                in {"stop", "stop_limit", "trailing_stop"}
            ]
            if not stops:
                missing.append({"bot_id": bot_id, "symbol": symbol, "position_qty": qty})
                continue
            deltas = [
                abs(float(order.get("qty") or 0) - qty)
                for order in stops
            ]
            if min(deltas) > QUANTITY_TOLERANCE:
                mismatched.append(
                    {
                        "bot_id": bot_id,
                        "symbol": symbol,
                        "position_qty": qty,
                        "stop_quantities": [float(order.get("qty") or 0) for order in stops],
                        "minimum_difference": min(deltas),
                    }
                )

    actual = {
        "checked_positions": checked,
        "missing_stops": missing,
        "quantity_mismatches": mismatched,
    }
    failures = len(missing) + len(mismatched)
    if failures:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference={"failed_positions": failures, "quantity_tolerance": QUANTITY_TOLERANCE},
            message=f"{failures} material strategy position(s) lack an exactly matching covering stop.",
            source_key="stop_coverage",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference={"failed_positions": 0},
        message=f"All {checked} material strategy position(s) have covering stops.",
        source_key="stop_coverage",
    )


def check_crypto_exposure(inputs: InvariantInputs) -> dict[str, Any]:
    name = "crypto_market_value_within_fleet_cap"
    expected = {
        # Keep the original field names for callers that consume the monitor
        # report, while making the hard cap and proposed band explicit.
        "maximum_fraction": CRYPTO_EXPOSURE_LIMIT,
        "maximum_percent": CRYPTO_EXPOSURE_LIMIT * 100,
        "hard_cap_fraction": CRYPTO_EXPOSURE_LIMIT,
        "hard_cap_percent": CRYPTO_EXPOSURE_LIMIT * 100,
        "drift_band_fraction": PROPOSED_CRYPTO_DRIFT_BAND,
        "drift_band_percent": PROPOSED_CRYPTO_DRIFT_BAND * 100,
        "vault_in_denominator": True,
    }
    problem = _source_problem(inputs, "broker_positions", "fleet_equity")
    if inputs.broker_positions is None or inputs.fleet_equity is None:
        return _unknown(
            name,
            actual={"source_error": problem or "broker positions or fleet equity unreadable"},
            expected=expected,
            difference={"unreadable_sources": 1},
            message="Cannot calculate crypto exposure without broker market values and fleet equity.",
            source_key="crypto_exposure",
        )
    try:
        equity = float(inputs.fleet_equity)
    except (TypeError, ValueError):
        equity = 0.0
    if equity <= 0:
        return _unknown(
            name,
            actual={"fleet_equity": inputs.fleet_equity, "crypto_market_value": None},
            expected=expected,
            difference={
                "ratio_minus_limit": None,
                "ratio_minus_hard_cap": None,
                "ratio_minus_drift_band": None,
            },
            message="Fleet equity is unavailable or non-positive, so the denominator cannot be trusted.",
            source_key="crypto_exposure",
        )

    crypto_value = 0.0
    crypto_rows: list[dict[str, Any]] = []
    try:
        for bot_id, positions in inputs.broker_positions.items():
            for position in positions:
                symbol = canonical_symbol(position.get("symbol"))
                if not is_crypto_symbol(symbol):
                    continue
                value = float(position.get("market_value"))
                crypto_value += abs(value)
                crypto_rows.append(
                    {"bot_id": bot_id, "symbol": symbol, "market_value": value}
                )
    except (TypeError, ValueError, KeyError) as exc:
        return _unknown(
            name,
            actual={"source_error": f"invalid broker market value: {exc}"},
            expected=expected,
            difference={
                "ratio_minus_limit": None,
                "ratio_minus_hard_cap": None,
                "ratio_minus_drift_band": None,
            },
            message="A crypto market value could not be read as a number.",
            source_key="crypto_exposure",
        )

    ratio = crypto_value / equity
    actual = {
        "crypto_market_value": crypto_value,
        "fleet_equity": equity,
        "crypto_fraction": ratio,
        "crypto_positions": crypto_rows,
    }
    difference = {
        "ratio_minus_limit": ratio - CRYPTO_EXPOSURE_LIMIT,
        "ratio_minus_hard_cap": ratio - CRYPTO_EXPOSURE_LIMIT,
        "ratio_minus_drift_band": ratio - PROPOSED_CRYPTO_DRIFT_BAND,
    }
    if ratio > PROPOSED_CRYPTO_DRIFT_BAND:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference=difference,
            message=(
                f"Crypto market value is {ratio:.8f} of fleet equity, "
                f"above the proposed {PROPOSED_CRYPTO_DRIFT_BAND:.2%} drift band."
            ),
            source_key="crypto_exposure",
        )
    if ratio > CRYPTO_EXPOSURE_LIMIT:
        return _drift(
            name,
            actual=actual,
            expected=expected,
            difference=difference,
            message=(
                f"Crypto market value is {ratio:.8f} of fleet equity, above the "
                f"5% hard cap but within the proposed {PROPOSED_CRYPTO_DRIFT_BAND:.2%} "
                "appreciation drift band; it will be corrected at the next scheduled rebalance."
            ),
            source_key="crypto_exposure",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference=difference,
        message=f"Crypto market value is {ratio:.8f} of fleet equity.",
        source_key="crypto_exposure",
    )


def check_cycle_freshness(inputs: InvariantInputs) -> dict[str, Any]:
    name = "bot_cycle_success_freshness"
    intervals = {**DEFAULT_CYCLE_INTERVALS, **(inputs.cycle_intervals or {})}
    expected = {
        "multiplier": CYCLE_FRESHNESS_MULTIPLIER,
        "thresholds_seconds": {
            bot_id: CYCLE_FRESHNESS_MULTIPLIER * intervals[bot_id]
            for bot_id in ACTIVE_BOTS
        },
    }
    problem = _source_problem(inputs, "cycle_rows")
    if inputs.cycle_rows is None:
        return _unknown(
            name,
            actual={"source_error": problem or "bot cycle records unreadable"},
            expected=expected,
            difference={"unreadable_sources": 1},
            message="Cannot verify bot cycle freshness without durable cycle records.",
            source_key="cycle_freshness",
        )

    actual_rows: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    for bot_id in ACTIVE_BOTS:
        row = inputs.cycle_rows.get(bot_id)
        success_at = _parse_datetime(row.get("last_success_at")) if row else None
        threshold = CYCLE_FRESHNESS_MULTIPLIER * intervals[bot_id]
        if success_at is None:
            unreadable.append({"bot_id": bot_id, "last_success_at": None})
            continue
        age = (inputs.now.astimezone(timezone.utc) - success_at).total_seconds()
        item = {
            "bot_id": bot_id,
            "last_success_at": success_at.isoformat(),
            "age_seconds": age,
            "threshold_seconds": threshold,
        }
        actual_rows.append(item)
        if age > threshold:
            stale.append(item)

    actual = {"bots": actual_rows, "missing_or_unreadable": unreadable}
    if unreadable:
        return _unknown(
            name,
            actual=actual,
            expected=expected,
            difference={"unreadable_bots": len(unreadable)},
            message="At least one bot has no readable durable last_success_at.",
            source_key="cycle_freshness",
        )
    if stale:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference={
                "stale_bots": [
                    {
                        "bot_id": row["bot_id"],
                        "age_minus_threshold_seconds": row["age_seconds"]
                        - row["threshold_seconds"],
                    }
                    for row in stale
                ]
            },
            message=f"{len(stale)} bot cycle record(s) exceed 3 × their configured interval.",
            source_key="cycle_freshness",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference={"stale_bots": 0},
        message=f"All {len(actual_rows)} bot cycle records are within the established threshold.",
        source_key="cycle_freshness",
    )


def check_reconciliation_health(inputs: InvariantInputs) -> dict[str, Any]:
    name = "recent_reconciliation_is_clean"
    max_age_seconds = PROPOSED_RECON_MAX_AGE_MINUTES * 60
    expected = {
        "maximum_age_minutes": PROPOSED_RECON_MAX_AGE_MINUTES,
        "latest_clean": True,
    }
    problem = _source_problem(inputs, "reconciliation_rows")
    if inputs.reconciliation_rows is None:
        return _unknown(
            name,
            actual={"source_error": problem or "reconciliation log unreadable"},
            expected=expected,
            difference={"unreadable_sources": 1},
            message="Cannot verify reconciliation freshness or cleanliness.",
            source_key="reconciliation",
        )
    if not inputs.reconciliation_rows:
        return _unknown(
            name,
            actual={"latest_row": None},
            expected=expected,
            difference={"age_minus_threshold_seconds": None, "clean_difference": None},
            message="No reconciliation row exists to establish freshness or cleanliness.",
            source_key="reconciliation",
        )

    parsed_rows = [
        (row, _parse_datetime(row.get("run_ts") or row.get("created_at")))
        for row in inputs.reconciliation_rows
    ]
    readable = [(row, timestamp) for row, timestamp in parsed_rows if timestamp is not None]
    if not readable:
        return _unknown(
            name,
            actual={"latest_row": None, "unreadable_rows": len(parsed_rows)},
            expected=expected,
            difference={"age_minus_threshold_seconds": None, "clean_difference": None},
            message="Reconciliation timestamps could not be read.",
            source_key="reconciliation",
        )

    row, run_ts = max(readable, key=lambda item: item[1])
    age_seconds = (inputs.now.astimezone(timezone.utc) - run_ts).total_seconds()
    clean = row.get("clean")
    actual = {
        "latest_run_ts": run_ts.isoformat(),
        "age_minutes": age_seconds / 60,
        "clean": clean,
        "flags": row.get("flags"),
    }
    difference = {
        "age_minus_threshold_seconds": age_seconds - max_age_seconds,
        "clean_difference": 0 if clean is True else 1,
    }
    if clean is not True:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference=difference,
            message="The most recent reconciliation row is not clean.",
            source_key="reconciliation",
        )
    if age_seconds > max_age_seconds:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference=difference,
            message=f"The most recent reconciliation is {age_seconds / 60:.2f} minutes old.",
            source_key="reconciliation",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference=difference,
        message="The most recent reconciliation is recent and clean.",
        source_key="reconciliation",
    )


def check_degradations(inputs: InvariantInputs) -> dict[str, Any]:
    name = "zero_unresolved_high_severity_degradations"
    expected = {"unresolved_count": 0, "severities": sorted(UNRESOLVED_HIGH_SEVERITIES)}
    problem = _source_problem(inputs, "unresolved_degradations")
    if inputs.unresolved_degradations is None:
        return _unknown(
            name,
            actual={"source_error": problem or "degradation log unreadable"},
            expected=expected,
            difference={"unresolved_count": None},
            message="Cannot verify unresolved degradation events.",
            source_key="degradations",
        )
    events = [
        event
        for event in inputs.unresolved_degradations
        if str(event.get("severity", "")).lower() in UNRESOLVED_HIGH_SEVERITIES
    ]
    # Keep operator output bounded while preserving the exact count and a
    # useful sample.  Dumping hundreds of historical rows makes the scheduled
    # log unreadable and does not improve the invariant decision.
    actual = {
        "unresolved_count": len(events),
        "events_sample": events[:10],
        "sample_truncated": len(events) > 10,
    }
    if events:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference={"unresolved_count": len(events)},
            message=f"{len(events)} unresolved high-severity degradation event(s) remain.",
            source_key="degradations",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference={"unresolved_count": 0},
        message="No unresolved high-severity degradation events were found.",
        source_key="degradations",
    )


def check_kill_switch_parity(inputs: InvariantInputs) -> dict[str, Any]:
    name = "kill_switch_runtime_matches_config"
    expected = {"runtime_equals_config": True}
    problem = _source_problem(inputs, "kill_switch_runtime", "kill_switch_config")
    if inputs.kill_switch_runtime is None or inputs.kill_switch_config is None:
        return _unknown(
            name,
            actual={
                "runtime": inputs.kill_switch_runtime,
                "config": inputs.kill_switch_config,
                "source_error": problem or "kill-switch state unreadable",
            },
            expected=expected,
            difference={"runtime_minus_config": None},
            message="Cannot compare the runtime kill-switch value with its configuration.",
            source_key="kill_switch",
        )
    runtime = bool(inputs.kill_switch_runtime)
    config = bool(inputs.kill_switch_config)
    actual = {"runtime": runtime, "config": config}
    difference = {"runtime_minus_config": int(runtime) - int(config)}
    if runtime != config:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference=difference,
            message="The runtime kill-switch value does not match its configured value.",
            source_key="kill_switch",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference=difference,
        message="The runtime kill-switch value matches its configured value.",
        source_key="kill_switch",
    )


def check_ledger_broker_presence(inputs: InvariantInputs) -> dict[str, Any]:
    name = "ledger_and_broker_positions_have_matching_symbols"
    expected = {
        "ledger_without_broker": 0,
        "broker_without_ledger": 0,
        "excluded": ["vault holdings", f"dust qty < {DUST_QTY}"],
    }
    problem = _source_problem(inputs, "broker_positions", "ledger_positions", "vault_symbols")
    if (
        inputs.broker_positions is None
        or inputs.ledger_positions is None
        or inputs.vault_symbols is None
    ):
        return _unknown(
            name,
            actual={"source_error": problem or "ledger, broker, or vault holdings unreadable"},
            expected=expected,
            difference={"unmatched_symbols": None},
            message="Cannot compare ledger and broker position presence.",
            source_key="ledger_broker_presence",
        )

    broker = _position_maps(inputs.broker_positions, inputs.vault_symbols)
    ledger = _position_maps(inputs.ledger_positions, inputs.vault_symbols)
    missing_ledger: list[dict[str, Any]] = []
    missing_broker: list[dict[str, Any]] = []
    for bot_id in ACTIVE_BOTS:
        for symbol in sorted(set(broker.get(bot_id, {})) - set(ledger.get(bot_id, {}))):
            missing_ledger.append({"bot_id": bot_id, "symbol": symbol, "broker_qty": broker[bot_id][symbol]})
        for symbol in sorted(set(ledger.get(bot_id, {})) - set(broker.get(bot_id, {}))):
            missing_broker.append({"bot_id": bot_id, "symbol": symbol, "ledger_qty": ledger[bot_id][symbol]})
    actual = {
        "ledger_without_broker": missing_broker,
        "broker_without_ledger": missing_ledger,
    }
    unmatched = len(missing_broker) + len(missing_ledger)
    if unmatched:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference={"unmatched_symbols": unmatched},
            message=f"{unmatched} material ledger/broker symbol mismatch(es) were found.",
            source_key="ledger_broker_presence",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference={"unmatched_symbols": 0},
        message="Every material strategy symbol is present in both ledger and broker sources.",
        source_key="ledger_broker_presence",
    )


def check_ledger_broker_quantities(inputs: InvariantInputs) -> dict[str, Any]:
    name = "ledger_and_broker_quantities_match"
    expected = {
        "quantity_tolerance": QUANTITY_TOLERANCE,
        "comparison": "absolute quantity difference <= tolerance",
    }
    problem = _source_problem(inputs, "broker_positions", "ledger_positions", "vault_symbols")
    if (
        inputs.broker_positions is None
        or inputs.ledger_positions is None
        or inputs.vault_symbols is None
    ):
        return _unknown(
            name,
            actual={"source_error": problem or "ledger, broker, or vault holdings unreadable"},
            expected=expected,
            difference={"maximum_quantity_difference": None},
            message="Cannot compare ledger and broker quantities.",
            source_key="ledger_broker_quantity",
        )

    broker = _position_maps(inputs.broker_positions, inputs.vault_symbols)
    ledger = _position_maps(inputs.ledger_positions, inputs.vault_symbols)
    mismatches: list[dict[str, Any]] = []
    maximum_difference = 0.0
    for bot_id in ACTIVE_BOTS:
        for symbol in sorted(set(broker.get(bot_id, {})) & set(ledger.get(bot_id, {}))):
            broker_qty = broker[bot_id][symbol]
            ledger_qty = ledger[bot_id][symbol]
            difference = abs(broker_qty - ledger_qty)
            maximum_difference = max(maximum_difference, difference)
            if difference > QUANTITY_TOLERANCE:
                mismatches.append(
                    {
                        "bot_id": bot_id,
                        "symbol": symbol,
                        "broker_qty": broker_qty,
                        "ledger_qty": ledger_qty,
                        "difference": difference,
                    }
                )
    actual = {
        "common_symbols_checked": sum(
            len(set(broker.get(bot_id, {})) & set(ledger.get(bot_id, {})))
            for bot_id in ACTIVE_BOTS
        ),
        "maximum_quantity_difference": maximum_difference,
        "mismatches": mismatches,
    }
    if mismatches:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference={"mismatched_symbols": len(mismatches), "maximum_quantity_difference": maximum_difference},
            message=f"{len(mismatches)} common symbol quantity mismatch(es) exceed 1e-8.",
            source_key="ledger_broker_quantity",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference={"mismatched_symbols": 0, "maximum_quantity_difference": maximum_difference},
        message="All common material symbol quantities match within 1e-8.",
        source_key="ledger_broker_quantity",
    )


def check_published_runner_liveness(inputs: InvariantInputs) -> dict[str, Any]:
    name = "published_runner_has_recent_durable_cycle"
    intervals = {**DEFAULT_CYCLE_INTERVALS, **(inputs.cycle_intervals or {})}
    threshold = CYCLE_FRESHNESS_MULTIPLIER * max(intervals.values())
    expected = {
        "published_runner": True,
        "maximum_age_seconds": threshold,
        "source": "bot_cycle_health.last_success_at",
    }
    if inputs.published_runner is None:
        return _unknown(
            name,
            actual={"published_runner": None, "durable_cycle": None},
            expected=expected,
            difference={"age_minus_threshold_seconds": None},
            message="Cannot determine whether this check is evaluating the published runner.",
            source_key="published_runner_liveness",
        )
    if not inputs.published_runner:
        return _unknown(
            name,
            actual={"published_runner": False, "durable_cycle": None},
            expected=expected,
            difference={"age_minus_threshold_seconds": None},
            message="This process is not marked as the published runner; published liveness is not established.",
            source_key="published_runner_liveness",
        )
    if inputs.cycle_rows is None:
        return _unknown(
            name,
            actual={"published_runner": True, "source_error": "bot cycle records unreadable"},
            expected=expected,
            difference={"age_minus_threshold_seconds": None},
            message="Cannot check published runner liveness without durable cycle records.",
            source_key="published_runner_liveness",
        )

    durable_cycles = [
        (bot_id, _parse_datetime(row.get("last_success_at")))
        for bot_id, row in inputs.cycle_rows.items()
        if isinstance(row, dict)
    ]
    durable_cycles = [(bot_id, timestamp) for bot_id, timestamp in durable_cycles if timestamp]
    if not durable_cycles:
        return _unknown(
            name,
            actual={"published_runner": True, "durable_cycle": None},
            expected=expected,
            difference={"age_minus_threshold_seconds": None},
            message="No durable successful cycle record exists for the published runner.",
            source_key="published_runner_liveness",
        )

    bot_id, latest = max(durable_cycles, key=lambda item: item[1])
    age = (inputs.now.astimezone(timezone.utc) - latest).total_seconds()
    actual = {
        "published_runner": True,
        "latest_bot_cycle_bot_id": bot_id,
        "latest_durable_cycle": latest.isoformat(),
        "age_seconds": age,
    }
    difference = {"age_minus_threshold_seconds": age - threshold}
    if age > threshold:
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference=difference,
            message=f"The latest durable runner cycle is {age:.2f} seconds old.",
            source_key="published_runner_liveness",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference=difference,
        message="The published runner has a recent durable successful cycle.",
        source_key="published_runner_liveness",
    )


def check_runner_heartbeat_fresh(inputs: InvariantInputs) -> dict[str, Any]:
    name = "runner_heartbeat_is_fresh"
    expected = {
        "verdict": "ALIVE",
        "maximum_age_seconds": RUNNER_HEARTBEAT_THRESHOLD_SECONDS,
        "source": "runner_heartbeat.last_beat_at",
    }
    problem = _source_problem(inputs, "runner_heartbeat")
    if inputs.runner_heartbeat is None:
        return _unknown(
            name,
            actual={"source_error": problem or "runner heartbeat table unreadable"},
            expected=expected,
            difference={"unreadable_sources": 1},
            message="Cannot verify runner heartbeat freshness because the table could not be read.",
            source_key="runner_heartbeat",
        )

    verdict = inputs.runner_heartbeat.get("verdict")
    actual = {
        "verdict": verdict,
        "age_seconds": inputs.runner_heartbeat.get("age_seconds"),
        "threshold_seconds": inputs.runner_heartbeat.get(
            "threshold_seconds", RUNNER_HEARTBEAT_THRESHOLD_SECONDS
        ),
        "row": inputs.runner_heartbeat.get("row"),
    }
    if verdict == "ABSENT":
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference={"missing_runner_rows": 1},
            message="No durable runner heartbeat row exists.",
            source_key="runner_heartbeat",
        )
    if verdict == "STALE":
        return _failed(
            name,
            actual=actual,
            expected=expected,
            difference={
                "age_minus_threshold_seconds": (
                    float(actual["age_seconds"]) - float(actual["threshold_seconds"])
                )
                if actual["age_seconds"] is not None
                else None
            },
            message="The latest durable runner heartbeat is stale.",
            source_key="runner_heartbeat",
        )
    if verdict != "ALIVE":
        return _unknown(
            name,
            actual=actual,
            expected=expected,
            difference={"invalid_verdict": verdict},
            message="The durable runner heartbeat returned an unreadable verdict.",
            source_key="runner_heartbeat",
        )
    return _passed(
        name,
        actual=actual,
        expected=expected,
        difference={
            "age_minus_threshold_seconds": (
                float(actual["age_seconds"]) - float(actual["threshold_seconds"])
            )
            if actual["age_seconds"] is not None
            else None
        },
        message="The latest durable runner heartbeat is fresh.",
        source_key="runner_heartbeat",
    )


INVARIANT_FUNCTIONS: tuple[Callable[[InvariantInputs], dict[str, Any]], ...] = (
    check_stop_coverage,
    check_crypto_exposure,
    check_cycle_freshness,
    check_reconciliation_health,
    check_degradations,
    check_kill_switch_parity,
    check_ledger_broker_presence,
    check_ledger_broker_quantities,
    check_published_runner_liveness,
    check_runner_heartbeat_fresh,
)


def read_database_inputs(now: datetime | None = None) -> dict[str, Any]:
    """Read all database inputs using SELECT statements only."""
    observation_time = now or datetime.now(timezone.utc)
    dsn = os.environ.get("INVARIANTS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("no database connection is configured")
    import psycopg2

    result: dict[str, Any] = {
        "ledger_positions": {bot_id: [] for bot_id in ACTIVE_BOTS},
        "vault_symbols": {bot_id: set() for bot_id in ACTIVE_BOTS},
        "cycle_rows": {},
        "reconciliation_rows": [],
        "unresolved_degradations": [],
    }
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bot_id, symbol, qty::double precision
                FROM alpaca_etf_positions
                WHERE lower(status) = 'open'
                """
            )
            for bot_id, symbol, qty in cur.fetchall():
                if bot_id in result["ledger_positions"]:
                    result["ledger_positions"][bot_id].append(
                        {"symbol": symbol, "qty": qty}
                    )

            cur.execute(
                """
                SELECT bot_id, symbol, qty::double precision
                FROM bot3_positions
                WHERE lower(status) = 'open'
                """
            )
            for bot_id, symbol, qty in cur.fetchall():
                if bot_id in result["ledger_positions"]:
                    result["ledger_positions"][bot_id].append(
                        {"symbol": symbol, "qty": qty}
                    )

            # Bot 2 has no separate authoritative strategy table while it is
            # paused, so its canonical ledger is the durable JSON position
            # mirror.  Do not also merge this mirror into the dedicated tables
            # above; that would count one position twice.
            cur.execute(
                """
                SELECT bot_id, positions
                FROM bot_portfolio
                WHERE bot_id = ANY(%s)
                """,
                (list(ACTIVE_BOTS),),
            )
            for bot_id, positions in cur.fetchall():
                if bot_id != "spy_qqq_trend" or not positions:
                    continue
                values = positions if isinstance(positions, list) else json.loads(positions)
                result["ledger_positions"][bot_id].extend(
                    {
                        "symbol": value.get("symbol"),
                        "qty": value.get("qty"),
                    }
                    for value in values
                    if isinstance(value, dict)
                )

            cur.execute(
                """
                SELECT bot_id, symbol
                FROM per_bot_vault_holdings
                WHERE bot_id = ANY(%s)
                """,
                (list(ACTIVE_BOTS),),
            )
            for bot_id, symbol in cur.fetchall():
                result["vault_symbols"].setdefault(bot_id, set()).add(symbol)

            cur.execute(
                """
                SELECT bot_id, last_success_at, cycle_count, status
                FROM bot_cycle_health
                WHERE bot_id = ANY(%s)
                """,
                (list(ACTIVE_BOTS),),
            )
            for bot_id, last_success_at, cycle_count, status in cur.fetchall():
                result["cycle_rows"][bot_id] = {
                    "last_success_at": last_success_at,
                    "cycle_count": cycle_count,
                    "status": status,
                }

            cur.execute(
                """
                SELECT run_ts, clean, flags
                FROM reconciliation_log
                ORDER BY run_ts DESC
                LIMIT 1
                """
            )
            result["reconciliation_rows"] = [
                {"run_ts": row[0], "clean": row[1], "flags": row[2]}
                for row in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT id, ts, component, severity, error_type, message, bot_id
                FROM system_degradations
                WHERE resolved_at IS NULL
                  AND lower(severity) = ANY(%s)
                ORDER BY ts DESC
                """,
                (list(UNRESOLVED_HIGH_SEVERITIES),),
            )
            result["unresolved_degradations"] = [
                {
                    "id": row[0],
                    "ts": row[1],
                    "component": row[2],
                    "severity": row[3],
                    "error_type": row[4],
                    "message": row[5],
                    "bot_id": row[6],
                }
                for row in cur.fetchall()
            ]

    # Keep this read independent from the legacy database inputs above.  A
    # production database that predates this feature should produce UNKNOWN for
    # this invariant without hiding all of the other read-only audit results.
    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT instance_token, pid, environment, execution_mode,
                           started_at, last_beat_at, loop_count, bots_registered, status
                    FROM runner_heartbeat
                    ORDER BY last_beat_at DESC
                    LIMIT 1
                    """
                )
                columns = [description[0] for description in cur.description]
                row = cur.fetchone()
        if row is None:
            result["runner_heartbeat"] = {
                "verdict": "ABSENT",
                "age_seconds": None,
                "threshold_seconds": RUNNER_HEARTBEAT_THRESHOLD_SECONDS,
                "row": None,
            }
        else:
            heartbeat_row = dict(zip(columns, row))
            last_beat_at = _parse_datetime(heartbeat_row["last_beat_at"])
            age_seconds = (
                max(
                    0.0,
                    (observation_time.astimezone(timezone.utc) - last_beat_at).total_seconds(),
                )
                if last_beat_at is not None
                else None
            )
            result["runner_heartbeat"] = {
                "verdict": (
                    "UNREADABLE"
                    if age_seconds is None
                    else (
                        "ALIVE"
                        if age_seconds <= RUNNER_HEARTBEAT_THRESHOLD_SECONDS
                        else "STALE"
                    )
                ),
                "age_seconds": age_seconds,
                "threshold_seconds": RUNNER_HEARTBEAT_THRESHOLD_SECONDS,
                "row": heartbeat_row,
            }
    except Exception as exc:
        result["runner_heartbeat"] = None
        result["_runner_heartbeat_error"] = str(exc)
    return result


def _broker_client(bot_id: str):
    credentials = {
        "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
        "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
    }
    key_name, secret_name = credentials[bot_id]
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"credentials unavailable for {bot_id}")
    from alpaca.trading.client import TradingClient

    return TradingClient(key, secret, paper=True)


def read_broker_inputs() -> dict[str, Any]:
    """Read account, position, and open-order state from each Alpaca account."""
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    positions: dict[str, list[dict[str, Any]]] = {}
    orders: dict[str, list[dict[str, Any]]] = {}
    fleet_equity = 0.0
    for bot_id in ACTIVE_BOTS:
        client = _broker_client(bot_id)
        account = client.get_account()
        fleet_equity += float(account.equity)
        positions[bot_id] = [
            {
                "symbol": str(position.symbol),
                "qty": float(position.qty),
                "side": getattr(position.side, "value", position.side),
                "market_value": float(position.market_value),
            }
            for position in client.get_all_positions()
        ]
        orders[bot_id] = [
            {
                "id": str(order.id),
                "symbol": str(order.symbol),
                "qty": float(order.qty or 0),
                "side": getattr(order.side, "value", order.side),
                "type": getattr(order.type, "value", order.type),
                "status": getattr(order.status, "value", order.status),
            }
            for order in client.get_orders(
                filter=GetOrdersRequest(
                    status=QueryOrderStatus.OPEN,
                    nested=True,
                    limit=500,
                )
            )
        ]
    return {
        "broker_positions": positions,
        "broker_orders": orders,
        "fleet_equity": fleet_equity,
    }


def collect_inputs(now: datetime | None = None) -> InvariantInputs:
    """Collect production inputs without writing to the database or broker."""
    timestamp = now or datetime.now(timezone.utc)
    inputs = InvariantInputs(
        now=timestamp,
        cycle_intervals=dict(DEFAULT_CYCLE_INTERVALS),
        published_runner=(
            os.environ.get("INVARIANTS_PUBLISHED") == "1"
            or os.environ.get("REPLIT_DEPLOYMENT") == "1"
        ),
    )
    try:
        database = read_database_inputs(timestamp)
        for key, value in database.items():
            if key == "_runner_heartbeat_error":
                inputs.source_errors["runner_heartbeat"] = value
            elif key != "_runner_heartbeat_error":
                setattr(inputs, key, value)
    except Exception as exc:
        inputs.source_errors["database"] = str(exc)
        logger.error(f"Invariants | database read failed: {exc}")
    try:
        broker = read_broker_inputs()
        for key, value in broker.items():
            setattr(inputs, key, value)
    except Exception as exc:
        inputs.source_errors["broker"] = str(exc)
        logger.error(f"Invariants | broker read failed: {exc}")
    try:
        # Loading the kill-switch module also loads the shared bot config,
        # whose legacy import-time banner must not pollute the CLI report.
        with contextlib.redirect_stdout(io.StringIO()):
            from core.kill_switch import is_tripped

        inputs.kill_switch_runtime = bool(is_tripped())
        raw_config = os.environ.get("KILL_SWITCH_ARMED", "false").strip().lower()
        inputs.kill_switch_config = raw_config in {"1", "true", "yes", "on"}
    except Exception as exc:
        inputs.source_errors["kill_switch"] = str(exc)
    return inputs


def run_all_invariants(
    inputs: InvariantInputs | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run every invariant and return an aggregate report."""
    if inputs is None:
        inputs = collect_inputs(now)
    results = [function(inputs) for function in INVARIANT_FUNCTIONS]
    statuses = {result["status"] for result in results}
    counts = {
        status: sum(1 for result in results if result["status"] == status)
        for status in ("PASS", "DRIFT", "FAIL", "UNKNOWN")
    }
    if "FAIL" in statuses:
        overall: Status = "FAIL"
    elif "UNKNOWN" in statuses:
        overall = "UNKNOWN"
    else:
        overall = "PASS"
    return {
        "checked_at": inputs.now.astimezone(timezone.utc).isoformat(),
        "overall": overall,
        "counts": counts,
        "drift_count": counts["DRIFT"],
        "results": results,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def format_report(report: dict[str, Any]) -> str:
    """Return stable one-line-per-invariant output for operators and logs."""
    counts = report.get("counts", {})
    lines = [
        f"OVERALL status={report['overall']} "
        f"drifts={counts.get('DRIFT', report.get('drift_count', 0))} "
        f"failures={counts.get('FAIL', 0)} "
        f"unknowns={counts.get('UNKNOWN', 0)} "
        f"checked_at={report['checked_at']}"
    ]
    for result in report["results"]:
        lines.append(
            f"{result['status']} {result['name']} "
            f"actual={json.dumps(_json_safe(result['actual']), sort_keys=True)} "
            f"expected={json.dumps(_json_safe(result['expected']), sort_keys=True)} "
            f"difference={json.dumps(_json_safe(result['difference']), sort_keys=True)} "
            f"message={result['message']} "
            f"threshold_source={result['threshold_source']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run all read-only platform invariants.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the complete structured report as JSON",
    )
    args = parser.parse_args(argv)
    report = run_all_invariants()
    if args.json:
        print(json.dumps(_json_safe(report), sort_keys=True, indent=2))
    else:
        print(format_report(report))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())