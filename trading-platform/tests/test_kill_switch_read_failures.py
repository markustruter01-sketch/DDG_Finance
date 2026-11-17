"""Fix window item 5: a broker that cannot be read pauses only that bot, after 3 failed checks in a row."""
from __future__ import annotations

from core import bot_state
from core import kill_switch as ks


def setup_function():
    ks._state.update(tripped=False, last_snapshot={}, missing_stop_since={}, mismatch_counts={},
                     read_fail_counts={}, read_fail_seen={})


def _snap(n: int, failing: tuple[str, ...] = ("jerome_macro",), readable: tuple[str, ...] = ("oracle", "spy_qqq_trend")):
    return {
        "captured_at": f"2026-11-18T00:0{n}:00+00:00",
        "accounts": [{"bot_id": b, "equity": 100.0, "cash": 10.0, "long_market_value": 50.0,
                      "positions": [], "orders": [], "vault_symbols": set()} for b in readable],
        "account_findings": [{"bot_id": b, "kind": "broker_read_failed", "status": "UNKNOWN", "detail": "timeout"}
                             for b in failing],
        "mismatches": [], "fleet_equity": 300.0, "fleet_hwm": 300.0,
    }


def _read_failures(flags):
    return [f for f in flags if f["trigger"] == "missing_account"]


def test_one_blip_pauses_nobody():
    assert _read_failures(ks.evaluate_snapshot(_snap(1), now=100.0)) == []
    # A good read next time starts the count again.
    ks.evaluate_snapshot(_snap(2, failing=(), readable=("oracle", "spy_qqq_trend", "jerome_macro")), now=100.0)
    assert ks._state["read_fail_counts"] == {}


def test_three_failed_checks_in_a_row_flag_only_that_bot():
    assert _read_failures(ks.evaluate_snapshot(_snap(1), now=100.0)) == []
    assert _read_failures(ks.evaluate_snapshot(_snap(2), now=100.0)) == []
    flags = _read_failures(ks.evaluate_snapshot(_snap(3), now=100.0))
    assert [(f["bot_id"], f["failed_checks"]) for f in flags] == [("jerome_macro", 3)]


def test_the_same_snapshot_seen_by_several_callers_counts_once():
    snap = _snap(1)
    for _ in range(5):        # the reconciliation run, the 5-minute check and the risk governor
        assert _read_failures(ks.evaluate_snapshot(snap, now=100.0)) == []
    assert ks._state["read_fail_counts"] == {"jerome_macro": 1}


def test_recovery_resets_the_count():
    ks.evaluate_snapshot(_snap(1), now=100.0)
    ks.evaluate_snapshot(_snap(2), now=100.0)
    ks.evaluate_snapshot(_snap(3, failing=(), readable=("oracle", "spy_qqq_trend", "jerome_macro")), now=100.0)
    assert _read_failures(ks.evaluate_snapshot(_snap(4), now=100.0)) == []   # 1 again, not 3


def test_trip_on_a_read_failure_pauses_only_that_bot_and_does_not_latch(monkeypatch):
    paused, all_paused, events = [], [], []
    monkeypatch.setattr(bot_state, "set_paused", lambda bot, value, reason=None: paused.append((bot, value, reason)))
    monkeypatch.setattr(ks, "_set_all_paused", lambda reason: all_paused.append(reason))
    monkeypatch.setattr(ks, "_write_event", lambda *args: events.append(args))
    for n in (1, 2, 3):
        flags = ks.evaluate_snapshot(_snap(n), now=100.0)
    result = ks.trip(_read_failures(flags), _snap(3))
    assert result["tripped"] is False and result["paused_bots"] == ["jerome_macro"]
    assert paused == [("jerome_macro", True, "missing_account")]
    assert not all_paused and not events and ks.is_tripped() is False


def test_a_fleet_level_read_failure_still_pauses_everything(monkeypatch):
    all_paused = []
    monkeypatch.setattr(ks, "_set_all_paused", lambda reason: all_paused.append(reason))
    monkeypatch.setattr(ks, "_write_event", lambda *args: None)
    assert ks.trip([{"trigger": "missing_account", "bot_id": "fleet"}], {"accounts": []})["tripped"] is True
    assert all_paused
    ks._state["tripped"] = False
