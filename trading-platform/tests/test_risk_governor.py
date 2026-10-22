from core import risk_governor as rg


def _snap(equity=380_000.0, hwm=400_000.0, **extra):
    return {"accounts": [], "fleet_equity": equity, "fleet_hwm": hwm, "mismatches": [],
            "pause_state_disagreements": [], "account_findings": [], "liveness_findings": [], **extra}


def test_allows_new_risk_on_a_clean_snapshot_within_the_soft_limit():
    r = rg.new_risk_check(snapshot=_snap(), latch=lambda: False)
    assert r["allowed"] is True and r["fleet_drawdown"] == 0.05


def test_refuses_on_latch_soft_drawdown_or_would_trip():
    assert rg.new_risk_check(snapshot=_snap(), latch=lambda: True)["reasons"] == ["kill switch latched"]
    r = rg.new_risk_check(snapshot=_snap(equity=355_000.0), latch=lambda: False)
    assert not r["allowed"] and "soft limit" in r["reasons"][0]                 # 11.25% < 15% hard
    r = rg.new_risk_check(snapshot=_snap(liveness_findings=[{"trigger": "bot_stale", "bot_id": "oracle"}]),
                          latch=lambda: False)
    assert not r["allowed"] and r["reasons"] == ["kill switch would trip: bot_stale oracle"]


def test_fails_closed():
    assert rg.new_risk_check(snapshot=_snap(equity=None, hwm=None), latch=lambda: False)["allowed"] is False

    def boom():
        raise RuntimeError("db down")

    r = rg.new_risk_check(snapshot=_snap(), latch=boom)
    assert r == {"allowed": False, "reasons": ["risk check failed: RuntimeError"], "fleet_drawdown": None}
