from __future__ import annotations

import asyncio

from core import scheduler
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
    monkeypatch.setattr("core.degradation_tracker.has_recent_open", lambda *args, **kwargs: False)

    asyncio.run(scheduler._standing_invariants_job())

    assert recorded[0]["error_type"] == "bot_cycle_success_freshness"
    assert recorded[0]["severity"] == "critical"


def test_failing_invariant_with_an_open_row_is_not_recorded_again(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "core.invariants.run_all_invariants",
        lambda: {
            "overall": "FAIL",
            "counts": {"PASS": 0, "DRIFT": 0, "FAIL": 1, "UNKNOWN": 0},
            "checked_at": "2026-10-31T00:00:00+00:00",
            "results": [{"name": "zero_unresolved_high_severity_degradations", "status": "FAIL",
                         "actual": {}, "expected": {}, "difference": {}, "message": "3 remain.",
                         "threshold_source": "test"}],
        },
    )
    monkeypatch.setattr("core.degradation_tracker.record_degradation", lambda **kwargs: recorded.append(kwargs))
    monkeypatch.setattr("core.degradation_tracker.mark_resolved", lambda *args, **kwargs: 0)
    monkeypatch.setattr("core.degradation_tracker.has_recent_open", lambda *args, **kwargs: True)

    asyncio.run(scheduler._standing_invariants_job())

    assert recorded == []

def _unknown_report(name="strategy_positions_have_covering_stops"):
    return {
        "overall": "UNKNOWN",
        "counts": {"PASS": 0, "DRIFT": 0, "FAIL": 0, "UNKNOWN": 1},
        "checked_at": "2026-11-10T21:04:00+00:00",
        "results": [{"name": name, "status": "UNKNOWN", "actual": {}, "expected": {}, "difference": {},
                     "message": "Cannot verify stop coverage because a required read was unavailable.",
                     "threshold_source": "test"}],
    }


def _patch_tracker(monkeypatch, recorded, resolved):
    monkeypatch.setattr(scheduler, "_unknown_runs", {})
    monkeypatch.setattr("core.degradation_tracker.record_degradation", lambda **kwargs: recorded.append(kwargs))
    monkeypatch.setattr("core.degradation_tracker.mark_resolved", lambda *args, **kwargs: resolved.append(args) or 0)
    monkeypatch.setattr("core.degradation_tracker.has_recent_open", lambda *args, **kwargs: False)


def test_one_unknown_run_is_a_blip_two_in_a_row_alarm(monkeypatch):
    """10 Nov 21:04 UTC: one unavailable broker read raised two error rows at once."""
    recorded, resolved = [], []
    _patch_tracker(monkeypatch, recorded, resolved)
    monkeypatch.setattr("core.invariants.run_all_invariants", _unknown_report)

    asyncio.run(scheduler._standing_invariants_job())
    assert recorded == [] and resolved == []  # first UNKNOWN: no alarm, nothing resolved

    asyncio.run(scheduler._standing_invariants_job())
    assert [r["error_type"] for r in recorded] == ["strategy_positions_have_covering_stops"]
    assert recorded[0]["severity"] == "error"


def test_unknown_count_restarts_after_a_pass(monkeypatch):
    recorded, resolved = [], []
    _patch_tracker(monkeypatch, recorded, resolved)
    reports = iter([
        _unknown_report(),
        {**_unknown_report(), "overall": "PASS", "results": [{**_unknown_report()["results"][0], "status": "PASS"}]},
        _unknown_report(),
    ])
    monkeypatch.setattr("core.invariants.run_all_invariants", lambda: next(reports))

    for _ in range(3):
        asyncio.run(scheduler._standing_invariants_job())
    assert recorded == []  # UNKNOWN, PASS, UNKNOWN: never two in a row


def test_fail_still_alarms_on_the_first_run(monkeypatch):
    recorded, resolved = [], []
    _patch_tracker(monkeypatch, recorded, resolved)
    fail = _unknown_report()
    fail["results"][0]["status"] = "FAIL"
    monkeypatch.setattr("core.invariants.run_all_invariants", lambda: fail)

    asyncio.run(scheduler._standing_invariants_job())
    assert [r["severity"] for r in recorded] == ["critical"]
