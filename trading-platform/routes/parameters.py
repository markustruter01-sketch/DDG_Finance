"""Bot parameter control endpoints.

GET  /parameters/oracle             — current Oracle params + bounds
GET  /parameters/navigator          — current Navigator params + bounds
POST /parameters/oracle             — apply Oracle parameter overrides
POST /parameters/navigator          — apply Navigator parameter overrides
POST /parameters/oracle/reset       — reset Oracle params to factory defaults
POST /parameters/navigator/reset    — reset Navigator params to factory defaults
GET  /parameters/audit              — audit history (all bots, recent N rows)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from analysis.claude_parameter_advisor import (
    ORACLE_BOUNDS, ORACLE_STEPS,
    NAVIGATOR_BOUNDS, NAVIGATOR_STEPS,
    get_oracle_params, get_navigator_params,
    apply_oracle_params, apply_navigator_params,
    reset_oracle_params, reset_navigator_params,
    get_parameter_audit_history,
)

parameters_router = APIRouter(prefix="/parameters", tags=["Parameters"])


# ── Request models ────────────────────────────────────────────────────────────

class OracleParamRequest(BaseModel):
    conviction_threshold: float | None = Field(None, ge=0.60, le=0.95)
    max_positions: int | None = Field(None, ge=1, le=10)
    cash_reserve_pct: float | None = Field(None, ge=0.30, le=0.80)
    reasoning: str = Field("Operator override", description="Why this change is being made")


class NavigatorParamRequest(BaseModel):
    position_size_usd: float | None = Field(None, ge=5000, le=25000)
    reasoning: str = Field("Operator override", description="Why this change is being made")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _oracle_bounds_view() -> dict:
    return {k: {"min": v[0], "max": v[1], "step": ORACLE_STEPS[k]} for k, v in ORACLE_BOUNDS.items()}


def _navigator_bounds_view() -> dict:
    return {k: {"min": v[0], "max": v[1], "step": NAVIGATOR_STEPS[k]} for k, v in NAVIGATOR_BOUNDS.items()}


# ── GET endpoints ─────────────────────────────────────────────────────────────

@parameters_router.get("/oracle")
async def get_oracle() -> dict:
    return {
        "bot": "oracle",
        "current": get_oracle_params(),
        "bounds":  _oracle_bounds_view(),
        "defaults": {"conviction_threshold": 0.75, "max_positions": 10, "cash_reserve_pct": 0.60},
    }


@parameters_router.get("/navigator")
async def get_navigator() -> dict:
    return {
        "bot": "navigator",
        "current": get_navigator_params(),
        "bounds":  _navigator_bounds_view(),
        "defaults": {"position_size_usd": 10000.0},
    }


@parameters_router.get("/audit")
async def get_audit(limit: int = 50) -> dict:
    rows = get_parameter_audit_history(min(limit, 200))
    return {"history": rows, "count": len(rows)}


# ── POST endpoints ────────────────────────────────────────────────────────────

@parameters_router.post("/oracle")
async def update_oracle(request: OracleParamRequest) -> dict:
    params: dict = {}
    if request.conviction_threshold is not None:
        params["conviction_threshold"] = request.conviction_threshold
    if request.max_positions is not None:
        params["max_positions"] = request.max_positions
    if request.cash_reserve_pct is not None:
        params["cash_reserve_pct"] = request.cash_reserve_pct

    if not params:
        raise HTTPException(400, "No parameters provided")

    ok = apply_oracle_params(params, reasoning=request.reasoning, source="operator_ui")
    if not ok:
        raise HTTPException(500, "Failed to apply Oracle parameters")

    return {"status": "ok", "applied": params, "current": get_oracle_params()}


@parameters_router.post("/navigator")
async def update_navigator(request: NavigatorParamRequest) -> dict:
    params: dict = {}
    if request.position_size_usd is not None:
        params["position_size_usd"] = request.position_size_usd

    if not params:
        raise HTTPException(400, "No parameters provided")

    ok = apply_navigator_params(params, reasoning=request.reasoning, source="operator_ui")
    if not ok:
        raise HTTPException(500, "Failed to apply Navigator parameters")

    return {"status": "ok", "applied": params, "current": get_navigator_params()}


@parameters_router.post("/oracle/reset")
async def reset_oracle() -> dict:
    ok = reset_oracle_params(source="operator_ui_reset")
    if not ok:
        raise HTTPException(500, "Failed to reset Oracle parameters")
    return {"status": "ok", "current": get_oracle_params()}


@parameters_router.post("/navigator/reset")
async def reset_navigator() -> dict:
    ok = reset_navigator_params(source="operator_ui_reset")
    if not ok:
        raise HTTPException(500, "Failed to reset Navigator parameters")
    return {"status": "ok", "current": get_navigator_params()}
