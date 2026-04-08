"""Bot parameter control endpoints.

GET  /parameters                    — all active overrides (oracle + navigator + kraken summary)
GET  /parameters/oracle             — current Oracle params + bounds + expiry
GET  /parameters/navigator          — current Navigator params + bounds + expiry
GET  /parameters/history            — unified audit history (all bots)
POST /parameters/oracle             — apply Oracle parameter overrides (24h expiry)
POST /parameters/navigator          — apply Navigator parameter overrides (24h expiry)
POST /parameters/oracle/reset       — reset Oracle params to factory defaults
POST /parameters/navigator/reset    — reset Navigator params to factory defaults
POST /parameters/oracle/pause       — toggle Oracle paused state
POST /parameters/navigator/pause    — toggle Navigator paused state
POST /parameters/kraken/{bot_id}    — apply Kraken param overrides (24h expiry + audit)
POST /parameters/kraken/{bot_id}/pause — toggle Kraken bot paused state
POST /parameters/{bot_id}/reset     — unified reset for oracle | navigator | kraken bots
GET  /parameters/audit              — audit history alias (all bots, recent N rows)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from analysis.claude_parameter_advisor import (
    ORACLE_BOUNDS, ORACLE_STEPS, ORACLE_DEFAULTS,
    NAVIGATOR_BOUNDS, NAVIGATOR_STEPS, NAVIGATOR_DEFAULTS,
    get_oracle_params, get_navigator_params,
    get_all_active_overrides,
    apply_oracle_params, apply_navigator_params,
    reset_oracle_params, reset_navigator_params,
    set_oracle_paused, set_navigator_paused,
    get_parameter_audit_history,
)

parameters_router = APIRouter(prefix="/parameters", tags=["Parameters"])


# ── Request models ────────────────────────────────────────────────────────────

class OracleParamRequest(BaseModel):
    conviction_threshold: float | None = Field(None, ge=0.60, le=0.95)
    max_positions: int | None = Field(None, ge=1, le=10)
    cash_reserve_pct: float | None = Field(None, ge=0.30, le=0.80)
    paused: bool | None = Field(None, description="Kill-switch: pause Oracle trading")
    reasoning: str = Field("Operator override", description="Why this change is being made")
    ttl_hours: int = Field(24, ge=1, le=168, description="Override TTL in hours (1-168)")


class NavigatorParamRequest(BaseModel):
    position_size_usd: float | None = Field(None, ge=5000, le=25000)
    paused: bool | None = Field(None, description="Kill-switch: pause Navigator trading")
    reasoning: str = Field("Operator override", description="Why this change is being made")
    ttl_hours: int = Field(24, ge=1, le=168, description="Override TTL in hours (1-168)")


class KrakenParamRequest(BaseModel):
    ZSCORE_ENTRY: float | None = Field(None, ge=0.70, le=1.50)
    ZSCORE_EXIT: float | None = Field(None, ge=0.10, le=0.55)
    STOP_LOSS_PCT: float | None = Field(None, ge=0.008, le=0.040)
    TRAIL_PCT: float | None = Field(None, ge=0.030, le=0.100)
    MIN_NET_PROFIT_PCT: float | None = Field(None, ge=0.006, le=0.020)
    paused: bool | None = Field(None, description="Kill-switch: pause this Kraken bot")
    reasoning: str = Field("Operator override", description="Why this change is being made")
    ttl_hours: int = Field(24, ge=1, le=168, description="Override TTL in hours (1-168)")


class PauseRequest(BaseModel):
    paused: bool
    reasoning: str = Field("Operator pause toggle")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _oracle_bounds_view() -> dict:
    return {k: {"min": v[0], "max": v[1], "step": ORACLE_STEPS[k]} for k, v in ORACLE_BOUNDS.items()}


def _navigator_bounds_view() -> dict:
    return {k: {"min": v[0], "max": v[1], "step": NAVIGATOR_STEPS[k]} for k, v in NAVIGATOR_BOUNDS.items()}


def _compute_seconds_remaining(expires_at_str: str | None) -> int | None:
    if not expires_at_str:
        return None
    try:
        exp = datetime.fromisoformat(expires_at_str)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        secs = int((exp - datetime.now(timezone.utc)).total_seconds())
        return max(0, secs)
    except Exception:
        return None


def _get_kraken_active_overrides() -> dict:
    """Return current Kraken adaptive params for all 3 bots with TTL and paused state."""
    try:
        from analysis.fleet_enforcer import _load_current_kraken_params, BOT_ID_TO_DB_ID, BOUNDS, STEPS, KRAKEN_DEFAULTS
        result = {}
        for bot_key, db_id in BOT_ID_TO_DB_ID.items():
            params = _load_current_kraken_params(db_id)
            if params is not None:
                expires_at = params.get("override_expires_at")
                secs = _compute_seconds_remaining(expires_at)
                clean_params = {k: v for k, v in params.items() if k in BOUNDS}
                result[bot_key] = {
                    "params": clean_params,
                    "bounds": {k: {"min": v[0], "max": v[1], "step": STEPS[k]} for k, v in BOUNDS.items()},
                    "defaults": KRAKEN_DEFAULTS,
                    "has_active_override": secs is not None and secs > 0,
                    "seconds_remaining": secs,
                    "override_expires_at": expires_at,
                    "override_set_at": params.get("override_set_at"),
                    "paused": bool(params.get("paused", False)),
                }
        return result
    except Exception:
        return {}


def _kraken_bot_id_to_key(bot_id: str) -> str | None:
    mapping = {
        "davy-jones": "davy_jones",
        "davy_jones":  "davy_jones",
        "blackbeard":  "blackbeard",
        "calypso":     "calypso",
    }
    return mapping.get(bot_id.lower().strip())


def _write_kraken_control_json(bot_key: str, paused: bool) -> None:
    """Write the kraken control.json so the running bot picks up the pause state immediately."""
    try:
        bid = bot_key.replace("_", "-")
        ctrl_path = Path(f"../kraken-bot/{bid}_control.json")
        if not ctrl_path.exists():
            ctrl_path = Path("../kraken-bot/control.json")
        ctrl_path.write_text(json.dumps({"bot_paused": paused}, indent=2))
    except Exception:
        pass


# ── GET endpoints ─────────────────────────────────────────────────────────────

@parameters_router.get("")
async def get_all_parameters() -> dict:
    """Consolidated view of all active parameter overrides across the entire fleet."""
    overrides = get_all_active_overrides()
    kraken = _get_kraken_active_overrides()
    return {
        "oracle":    overrides["oracle"],
        "navigator": overrides["navigator"],
        "kraken":    kraken,
    }


@parameters_router.get("/oracle")
async def get_oracle() -> dict:
    current = get_oracle_params()
    return {
        "bot": "oracle",
        "current": current,
        "bounds":  _oracle_bounds_view(),
        "defaults": ORACLE_DEFAULTS,
        "has_active_override": bool(current.get("override_expires_at")),
        "override_expires_at": current.get("override_expires_at"),
        "override_set_at": current.get("override_set_at"),
    }


@parameters_router.get("/navigator")
async def get_navigator() -> dict:
    current = get_navigator_params()
    return {
        "bot": "navigator",
        "current": current,
        "bounds":  _navigator_bounds_view(),
        "defaults": NAVIGATOR_DEFAULTS,
        "has_active_override": bool(current.get("override_expires_at")),
        "override_expires_at": current.get("override_expires_at"),
        "override_set_at": current.get("override_set_at"),
    }


@parameters_router.get("/history")
async def get_history(limit: int = 100) -> dict:
    """Unified parameter audit history across all bots."""
    rows = get_parameter_audit_history(min(limit, 500))
    return {"history": rows, "count": len(rows)}


@parameters_router.get("/audit")
async def get_audit(limit: int = 50) -> dict:
    """Alias for /history."""
    rows = get_parameter_audit_history(min(limit, 200))
    return {"history": rows, "count": len(rows)}


# ── Oracle / Navigator POST endpoints ─────────────────────────────────────────

@parameters_router.post("/oracle")
async def update_oracle(request: OracleParamRequest) -> dict:
    params: dict = {}
    if request.conviction_threshold is not None:
        params["conviction_threshold"] = request.conviction_threshold
    if request.max_positions is not None:
        params["max_positions"] = request.max_positions
    if request.cash_reserve_pct is not None:
        params["cash_reserve_pct"] = request.cash_reserve_pct
    if request.paused is not None:
        params["paused"] = request.paused

    if not params:
        raise HTTPException(400, "No parameters provided")

    ok = apply_oracle_params(params, reasoning=request.reasoning,
                              source="operator_ui", ttl_hours=request.ttl_hours)
    if not ok:
        raise HTTPException(500, "Failed to apply Oracle parameters")

    current = get_oracle_params()
    return {
        "status": "ok",
        "applied": params,
        "current": current,
        "override_expires_at": current.get("override_expires_at"),
    }


@parameters_router.post("/navigator")
async def update_navigator(request: NavigatorParamRequest) -> dict:
    params: dict = {}
    if request.position_size_usd is not None:
        params["position_size_usd"] = request.position_size_usd
    if request.paused is not None:
        params["paused"] = request.paused

    if not params:
        raise HTTPException(400, "No parameters provided")

    ok = apply_navigator_params(params, reasoning=request.reasoning,
                                 source="operator_ui", ttl_hours=request.ttl_hours)
    if not ok:
        raise HTTPException(500, "Failed to apply Navigator parameters")

    current = get_navigator_params()
    return {
        "status": "ok",
        "applied": params,
        "current": current,
        "override_expires_at": current.get("override_expires_at"),
    }


@parameters_router.post("/oracle/pause")
async def pause_oracle(request: PauseRequest) -> dict:
    ok = set_oracle_paused(request.paused, reasoning=request.reasoning)
    if not ok:
        raise HTTPException(500, "Failed to toggle Oracle pause state")
    return {"status": "ok", "paused": request.paused, "current": get_oracle_params()}


@parameters_router.post("/navigator/pause")
async def pause_navigator(request: PauseRequest) -> dict:
    ok = set_navigator_paused(request.paused, reasoning=request.reasoning)
    if not ok:
        raise HTTPException(500, "Failed to toggle Navigator pause state")
    return {"status": "ok", "paused": request.paused, "current": get_navigator_params()}


# ── Kraken POST endpoints ──────────────────────────────────────────────────────

@parameters_router.post("/kraken/{bot_id}")
async def update_kraken_params(bot_id: str, request: KrakenParamRequest) -> dict:
    """Apply parameter overrides to a Kraken bot with 24h TTL and full audit trail."""
    bot_key = _kraken_bot_id_to_key(bot_id)
    if not bot_key:
        raise HTTPException(404, f"Unknown Kraken bot: {bot_id}. Valid: davy-jones, blackbeard, calypso")

    from analysis.fleet_enforcer import BOT_ID_TO_DB_ID, _write_kraken_params, _load_current_kraken_params, BOUNDS
    db_id = BOT_ID_TO_DB_ID.get(bot_key)
    if not db_id:
        raise HTTPException(404, f"No DB ID for bot: {bot_key}")

    # Build params dict from request
    params: dict = {}
    for field in ("ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"):
        val = getattr(request, field)
        if val is not None:
            params[field] = val

    if request.paused is not None:
        params["paused"] = request.paused

    if not params:
        raise HTTPException(400, "No parameters provided")

    # Merge with existing to preserve non-updated keys
    existing = _load_current_kraken_params(db_id) or {}
    for k in BOUNDS:
        if k not in params and k in existing:
            params[k] = existing[k]

    ok = _write_kraken_params(
        db_id, bot_key, params,
        reasoning=request.reasoning,
        ttl_hours=request.ttl_hours,
        source="operator_ui",
    )
    if not ok:
        raise HTTPException(500, f"Failed to apply {bot_id} parameters")

    # Also update control.json if paused toggled
    if request.paused is not None:
        _write_kraken_control_json(bot_key, request.paused)

    updated = _load_current_kraken_params(db_id) or {}
    return {
        "status": "ok",
        "bot_id": bot_id,
        "applied": params,
        "current": {k: v for k, v in updated.items() if k in BOUNDS},
        "override_expires_at": updated.get("override_expires_at"),
        "paused": bool(updated.get("paused", False)),
    }


@parameters_router.post("/kraken/{bot_id}/pause")
async def pause_kraken(bot_id: str, request: PauseRequest) -> dict:
    """Pause or resume a Kraken bot (writes to DB + control.json immediately)."""
    bot_key = _kraken_bot_id_to_key(bot_id)
    if not bot_key:
        raise HTTPException(404, f"Unknown Kraken bot: {bot_id}. Valid: davy-jones, blackbeard, calypso")

    from analysis.fleet_enforcer import BOT_ID_TO_DB_ID, _write_kraken_params, _load_current_kraken_params, BOUNDS
    db_id = BOT_ID_TO_DB_ID.get(bot_key)
    if not db_id:
        raise HTTPException(404, f"No DB ID for bot: {bot_key}")

    # Load existing params and preserve them
    existing = _load_current_kraken_params(db_id) or {}
    params = {k: existing[k] for k in BOUNDS if k in existing}
    params["paused"] = request.paused

    ok = _write_kraken_params(
        db_id, bot_key, params,
        reasoning=request.reasoning,
        ttl_hours=24,
        source="operator_ui_pause",
    )
    if not ok:
        raise HTTPException(500, f"Failed to toggle pause state for {bot_id}")

    # Immediately propagate to running bot via control.json
    _write_kraken_control_json(bot_key, request.paused)

    return {
        "status": "ok",
        "bot_id": bot_id,
        "paused": request.paused,
    }


# ── Reset endpoints ────────────────────────────────────────────────────────────

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


@parameters_router.post("/{bot_id}/reset")
async def reset_bot_params(bot_id: str) -> dict:
    """Unified reset endpoint for oracle | navigator | kraken bot IDs."""
    bot_id = bot_id.lower().strip()

    if bot_id == "oracle":
        ok = reset_oracle_params(source="operator_ui_reset")
        if not ok:
            raise HTTPException(500, "Failed to reset Oracle parameters")
        return {"status": "ok", "bot_id": "oracle", "current": get_oracle_params()}

    if bot_id == "navigator":
        ok = reset_navigator_params(source="operator_ui_reset")
        if not ok:
            raise HTTPException(500, "Failed to reset Navigator parameters")
        return {"status": "ok", "bot_id": "navigator", "current": get_navigator_params()}

    # Kraken bots
    bot_key = _kraken_bot_id_to_key(bot_id)
    if not bot_key:
        raise HTTPException(404, f"Unknown bot_id: {bot_id}. Valid: oracle, navigator, davy-jones, blackbeard, calypso")

    try:
        from analysis.fleet_enforcer import BOT_ID_TO_DB_ID, _revert_kraken_to_defaults, KRAKEN_DEFAULTS
        db_id = BOT_ID_TO_DB_ID.get(bot_key)
        if not db_id:
            raise HTTPException(404, f"No DB ID for bot: {bot_key}")
        _revert_kraken_to_defaults(db_id)
        # Also unpause via control.json
        _write_kraken_control_json(bot_key, False)
        return {"status": "ok", "bot_id": bot_id, "applied_defaults": KRAKEN_DEFAULTS}
    except ImportError as exc:
        raise HTTPException(500, f"Internal error: {exc}")
