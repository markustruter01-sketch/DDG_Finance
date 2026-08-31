from __future__ import annotations

import asyncio

from core import scheduler
from execution import reconciliation
from notifications import condition_alerts


def test_stale_cycle_condition_alerts_once_then_suppresses(monkeypatch):
    sent = []
    condition_alerts.reset_condition_alerts()
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    assert condition_alerts.alert_condition(
        source="bot_liveness",
        condition="bot_cycle_stale",
        bot_id="oracle",
        title="Stale bot cycle",
        description="last_success_at is old",
        now=100.0,
    )
    assert not condition_alerts.alert_condition(
        source="bot_liveness",
        condition="bot_cycle_stale",
        bot_id="oracle",
        title="Stale bot cycle",
        description="last_success_at is even older",
        now=100.0 + 1,
    )
    assert len(sent) == 1


def test_cleared_condition_alerts_again_when_it_recurs(monkeypatch):
    sent = []
    condition_alerts.reset_condition_alerts()
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    kwargs = {
        "source": "bot_liveness",
        "condition": "bot_cycle_stale",
        "bot_id": "oracle",
        "title": "Stale bot cycle",
        "description": "cycle is stale",
    }
    assert condition_alerts.alert_condition(**kwargs, now=200.0)
    condition_alerts.clear_condition("bot_liveness", "bot_cycle_stale", "oracle")
    assert condition_alerts.alert_condition(**kwargs, now=201.0)
    assert len(sent) == 2


def test_stale_cycle_invariant_is_recorded_for_alerting(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "core.invariants.run_all_invariants",
        lambda: {
            "overall": "FAIL",
            "counts": {"PASS": 0, "DRIFT": 0, "FAIL": 1, "UNKNOWN": 0},
            "checked_at": "2026-08-31T12:00:00+00:00",
            "results": [
                {
                    "name": "bot_cycle_success_freshness",
                    "status": "FAIL",
                    "actual": {"bots": [{"bot_id": "oracle", "age_seconds": 10801}]},
                    "expected": {"threshold_seconds": 10800},
                    "difference": {"stale_bots": [{"bot_id": "oracle"}]},
                    "message": "The Oracle cycle is stale.",
                    "threshold_source": "ESTABLISHED: core.bot_liveness uses 3 × configured cycle interval",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "core.degradation_tracker.record_degradation",
        lambda **kwargs: recorded.append(kwargs),
    )
    monkeypatch.setattr("core.degradation_tracker.mark_resolved", lambda *args, **kwargs: 0)

    asyncio.run(scheduler._standing_invariants_job())

    assert recorded[0]["error_type"] == "bot_cycle_success_freshness"
    assert recorded[0]["severity"] == "critical"


def test_naked_position_alerts_once_and_sends_recovery(monkeypatch):
    condition_alerts.reset_condition_alerts()
    sent = []
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )
    monkeypatch.setattr("core.kill_switch._load_acknowledgements", lambda: {})
    monkeypatch.setattr(reconciliation, "collect_live_snapshot", lambda: {
        "accounts": [{"bot_id": "oracle"}],
    })
    flags = [{
        "trigger": "missing_protective_stop",
        "bot_id": "oracle",
        "symbol": "SPY",
    }]
    observations = iter([flags, flags, []])
    monkeypatch.setattr("core.kill_switch.evaluate_snapshot", lambda _snapshot: next(observations))
    monkeypatch.setattr("core.kill_switch.report", lambda snapshot: {"snapshot": snapshot})

    reconciliation.run_kill_switch_check(report_only=True)
    reconciliation.run_kill_switch_check(report_only=True)
    assert len(sent) == 1
    assert sent[0][0][0] == "Naked position detected"

    reconciliation.run_kill_switch_check(report_only=True)

    assert len(sent) == 2
    assert sent[1][0][0] == "Recovered: kill_switch/missing_protective_stop"