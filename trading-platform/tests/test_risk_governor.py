from core import risk_governor as rg
from core import risk_limits


def _snap(equity=380_000.0, hwm=400_000.0, **extra):
    return {"accounts": [], "fleet_equity": equity, "fleet_hwm": hwm, "mismatches": [],
            "pause_state_disagreements": [], "account_findings": [], "liveness_findings": [], **extra}


def _check(snapshot, *, latch=False, enforce=False):
    recorded = []
    r = rg.new_risk_check(snapshot=snapshot, latch=lambda: latch, enforce_drawdown=enforce,
                          record=lambda dd, snap, reasons: recorded.append((dd, reasons)))
    return r, recorded


def test_fleet_v1_limits_are_the_single_definition():
    # FLEET-V1-LIVE-SPEC.md section 4 (2 Nov 2026): 15% soft, 22% hard, enforced.
    assert (risk_limits.RISK_PROFILE, risk_limits.SOFT_DRAWDOWN, risk_limits.HARD_DRAWDOWN) == ("fleet_v1", 0.15, 0.22)
    assert risk_limits.ENFORCE_DRAWDOWN_LIMITS is True
    from core import kill_switch
    assert kill_switch.HARD_DRAWDOWN is risk_limits.HARD_DRAWDOWN


def test_allows_new_risk_on_a_clean_snapshot_within_the_soft_limit():
    r, recorded = _check(_snap())
    assert r["allowed"] is True and r["fleet_drawdown"] == 0.05 and recorded == []
    assert "record_only" not in r


def test_record_only_mode_still_records_instead_of_refusing():
    # The record-only path stays available as an explicit option (enforce=False).
    r, recorded = _check(_snap(equity=330_000.0))                             # 17.5%: soft only
    assert r["allowed"] is True and r["reasons"] == []
    assert r["record_only"] == ["fleet drawdown 17.5% above the 15% soft limit"]
    assert recorded == [(0.175, r["record_only"])]
    r, recorded = _check(_snap(equity=290_000.0))                             # 27.5%: soft and hard
    assert r["allowed"] is True
    assert r["record_only"][0] == "kill switch would trip: fleet_drawdown"
    assert len(recorded) == 1


def test_enforced_limits_refuse_new_risk_past_the_soft_limit():
    r, recorded = _check(_snap(equity=330_000.0), enforce=True)              # 17.5%
    assert not r["allowed"] and "15% soft limit" in r["reasons"][0] and recorded == []
    r, _ = _check(_snap(equity=290_000.0), enforce=True)                     # 27.5%: hard too
    assert not r["allowed"] and r["reasons"][0] == "kill switch would trip: fleet_drawdown"


def test_enforcement_is_the_default():
    r = rg.new_risk_check(snapshot=_snap(equity=330_000.0), latch=lambda: False,
                          record=lambda *a: (_ for _ in ()).throw(AssertionError("must not record")))
    assert r["allowed"] is False and "record_only" not in r


def test_integrity_problems_still_refuse_while_drawdown_is_record_only():
    assert _check(_snap(), latch=True)[0]["reasons"] == ["kill switch latched"]
    r, _ = _check(_snap(liveness_findings=[{"trigger": "bot_stale", "bot_id": "oracle"}]))
    assert not r["allowed"] and r["reasons"] == ["kill switch would trip: bot_stale oracle"]
    r, recorded = _check(_snap(equity=290_000.0, liveness_findings=[{"trigger": "bot_stale", "bot_id": "oracle"}]))
    assert not r["allowed"] and r["reasons"] == ["kill switch would trip: bot_stale oracle"] and len(recorded) == 1


def test_fails_closed():
    assert _check(_snap(equity=None, hwm=None))[0]["allowed"] is False

    def boom():
        raise RuntimeError("db down")

    r = rg.new_risk_check(snapshot=_snap(), latch=boom, record=lambda *a: None)
    assert r == {"allowed": False, "reasons": ["risk check failed: RuntimeError"], "fleet_drawdown": None}
