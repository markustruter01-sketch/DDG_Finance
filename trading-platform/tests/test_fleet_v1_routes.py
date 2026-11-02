"""FLEET-V1 dashboard API: the browser gets read values only (spec section 7)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from routes import fleet_v1


def test_since_cutover_is_computed_server_side_and_none_without_marks():
    st = {"cutover": {"day": "2026-11-03", "equity": 100_000.0, "spy": 500.0},
          "mark": {"day": "2026-12-01", "equity": 103_000.0, "spy": 510.0}}
    out = fleet_v1.since_cutover(st)
    assert out["account_return"] == pytest.approx(0.03)
    assert out["spy_price_return"] == pytest.approx(0.02)
    assert fleet_v1.since_cutover({}) is None


def test_record_view_picks_the_logged_figures():
    exploration = {
        "plan": "FLEET-V1", "window": ["1987-01-01", "2010-12-31"],
        "candidates": {"F1": {"exact": {"cagr": 0.1068, "sharpe": 0.583, "max_dd": -0.2035},
                              "max_dd_after_haircut": -0.2211, "vol_pct": 11.69, "correlation_to_B": 0.63}},
        "controls": {"B": {"exact": {"cagr": 0.0935, "sharpe": 0.351, "max_dd": -0.5519}},
                     "N2": {"sharpe_p95": 0.472}},
        "selection": {"selected": "F1", "verdict": "SELECTED"},
        "rolling": {"by_candidate": {"F1": {"win_share": 13 / 15}}},
    }
    heldout = {"registration_id": "FLEET-V1-F1", "kind": "holdout_test",
               "result": {"verdict": "FAIL: 1_cagr_ge_B, 2_sharpe_ge_B_plus_0.10",
                          "test": {"window": ["2011-01-01", "2020-12-31"],
                                   "series": {"F1": {"exact": {"cagr": 0.0859, "sharpe": 0.768, "max_dd": -0.157}}},
                                   "pass_bar": {"items": {"1_cagr_ge_B": False}},
                                   "deflated_sharpe_F1": {"dsr": 0.979}},
                          "spent_information_only": {"window": ["2021-01-01", "2026-10-31"],
                                                     "label": "information only, spent", "series": {}}}}
    out = fleet_v1.record_view(exploration, heldout)
    assert out["exploration"]["selected"] == "F1"
    assert out["exploration"]["series"]["F1"]["max_drawdown_after_haircut"] == -0.2211
    assert out["exploration"]["n2_sharpe_p95"] == 0.472
    assert out["heldout"]["verdict"].startswith("FAIL")
    assert out["heldout"]["test"]["series"]["F1"]["cagr"] == 0.0859
    assert out["heldout"]["test"]["deflated_sharpe"] == 0.979
    assert fleet_v1.record_view(None, None) == {"plan": "research_harness/explore/FLEET-V1-PLAN.md",
                                                "exploration": None, "heldout": None}


def test_clear_halt_needs_the_owner_token(monkeypatch):
    monkeypatch.delenv(fleet_v1.CLEAR_CONFIRMATION_ENV_VAR, raising=False)
    req = fleet_v1.ClearHaltRequest(confirmation_token="x")
    with pytest.raises(HTTPException) as e:
        asyncio.run(fleet_v1.fleet_v1_clear_halt("oracle", req))
    assert e.value.status_code == 403
    monkeypatch.setenv(fleet_v1.CLEAR_CONFIRMATION_ENV_VAR, "right")
    with pytest.raises(HTTPException) as e:
        asyncio.run(fleet_v1.fleet_v1_clear_halt("oracle", req))
    assert e.value.status_code == 403


def test_clear_halt_refuses_an_account_that_is_not_halted(monkeypatch):
    monkeypatch.setenv(fleet_v1.CLEAR_CONFIRMATION_ENV_VAR, "right")
    monkeypatch.setattr(fleet_v1, "_read_state", lambda bot_id: {"drawdown": {"mode": "normal"}})
    req = fleet_v1.ClearHaltRequest(confirmation_token="right")
    with pytest.raises(HTTPException) as e:
        asyncio.run(fleet_v1.fleet_v1_clear_halt("oracle", req))
    assert e.value.status_code == 409


def test_only_fleet_accounts_are_served():
    with pytest.raises(HTTPException) as e:
        fleet_v1._variant("jerome_macro")
    assert e.value.status_code == 404
