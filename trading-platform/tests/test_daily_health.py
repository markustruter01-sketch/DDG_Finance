"""Daily health check summary (core/daily_health.py): pure, no DB, no Discord."""
from core.daily_health import CHECK_NAMES, summarize
from core.invariants import INVARIANT_FUNCTIONS, InvariantInputs, run_all_invariants


def _report(*statuses):
    return {"results": [{"name": n, "status": s, "message": f"msg {n}"} for n, s in statuses]}


def test_all_good_only_when_everything_passes():
    ok, lines = summarize(_report(("runner_heartbeat_is_fresh", "PASS")),
                          pause_states={"oracle": False}, unresolved=[], kill_switch_tripped=False)
    assert ok and lines == ["1/1 safety checks pass"]


def test_failures_pauses_kill_switch_and_alarms_are_listed():
    ok, lines = summarize(
        _report(("runner_heartbeat_is_fresh", "FAIL"), ("recent_reconciliation_is_clean", "UNKNOWN"),
                ("bot_cycle_success_freshness", "PASS")),
        pause_states={"oracle": True, "forex_ai": False},
        unresolved=[{"error_type": "close_failed", "severity": "critical"},
                    {"error_type": "close_failed", "severity": "error"},
                    {"error_type": "would_trip", "severity": "warning"},
                    {"error_type": "zero_unresolved_high_severity_degradations", "severity": "critical"}],
        kill_switch_tripped=True)
    assert not ok
    text = "\n".join(lines)
    assert lines[0] == "1/3 safety checks pass"
    assert "Kill switch is TRIPPED" in text and "Paused: oracle" in text
    assert "❌ Live runner heartbeat fresh" in text and "❓ Broker and ledger agree" in text
    assert "close_failed ×2" in text
    assert "would_trip" not in text and "zero_unresolved" not in text


def test_drift_is_a_note_not_a_failure():
    ok, lines = summarize(_report(("crypto_market_value_within_fleet_cap", "DRIFT")),
                          pause_states={}, unresolved=[], kill_switch_tripped=False)
    assert ok and lines[1].startswith("ℹ️ Crypto within the fleet cap")


def test_every_invariant_has_a_plain_name():
    names = {r["name"] for r in run_all_invariants(InvariantInputs())["results"]}
    assert len(names) == len(INVARIANT_FUNCTIONS) and names == set(CHECK_NAMES)
