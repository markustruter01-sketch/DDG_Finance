from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.bot_liveness import PORTFOLIO_STALE_THRESHOLDS
from core.degradation_resolver import (
    RESOLVABLE_ERROR_TYPES,
    resolution_for_event,
)


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _state(*, paused=False, recon_clean=True, cycle_status="success", stale=False):
    return {
        "checked_at": NOW,
        "pauses": {
            "oracle": {"paused": paused, "status": "paused" if paused else "running"},
        },
        "portfolios": {
            "oracle": {
                "last_updated": NOW - timedelta(
                    seconds=PORTFOLIO_STALE_THRESHOLDS["oracle"] + 1
                    if stale
                    else PORTFOLIO_STALE_THRESHOLDS["oracle"] - 1
                ),
            },
        },
        "cycles": {
            "oracle": {
                "last_success_at": NOW - timedelta(minutes=1),
                "status": cycle_status,
                "consecutive_failures": 0 if cycle_status == "success" else 1,
            },
        },
        "reconciliation": {
            "run_ts": NOW - timedelta(minutes=1),
            "clean": recon_clean,
            "flags": [] if recon_clean else [{"bot_id": "oracle"}],
            "snapshot": {},
        },
        "invariants": {
            "strategy_positions_have_covering_stops": "PASS"
            if recon_clean
            else "FAIL",
        },
    }


def _event(error_type: str) -> dict:
    return {
        "id": 1,
        "component": "oracle",
        "error_type": error_type,
        "severity": "high",
        "bot_id": "oracle",
    }


@pytest.mark.parametrize("error_type", RESOLVABLE_ERROR_TYPES)
def test_each_error_type_resolves_after_recovery(error_type):
    state = _state()
    assert resolution_for_event(_event(error_type), state), error_type


@pytest.mark.parametrize("error_type", RESOLVABLE_ERROR_TYPES)
def test_each_error_type_stays_open_while_condition_holds(error_type):
    state = _state(
        paused=False,
        recon_clean=False,
        cycle_status="failed",
        stale=True,
    )
    assert resolution_for_event(_event(error_type), state) is None, error_type


def test_paused_bot_stale_event_is_resolvable_without_fresh_portfolio():
    event = _event("bot_stale_workflow")
    state = _state(paused=True, stale=True)
    assert resolution_for_event(event, state) == (
        "database pause is active; paused bots are not stale"
    )


def test_unknown_or_ambiguous_state_fails_closed():
    event = _event("entry_order_failed")
    state = _state()
    state["pauses"] = {}
    assert resolution_for_event(event, state) is None

def test_atr_stop_audit_fail_needs_coverage_pass_and_fresh_clean_recon():
    event = _event("audit_fail_atr_stop_check")
    assert resolution_for_event(event, _state()) == (
        "stop-coverage invariant PASS and latest reconciliation is clean"
    )
    stale = _state()
    stale["reconciliation"]["run_ts"] = NOW - timedelta(hours=3)
    assert resolution_for_event(event, stale) is None
    uncovered = _state()
    uncovered["invariants"]["strategy_positions_have_covering_stops"] = "FAIL"
    assert resolution_for_event(event, uncovered) is None
