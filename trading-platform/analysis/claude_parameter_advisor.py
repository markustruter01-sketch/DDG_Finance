"""Claude Parameter Advisor — AI-driven lever recommendations for Oracle and Navigator bots.

Called by fleet_commander.py during each audit cycle to produce parameter adjustment
suggestions.  The operator must explicitly approve all changes before they are persisted.

Oracle parameters:
  conviction_threshold  [0.60, 0.95]  step=0.05
  max_positions         [1,    10]    step=1
  cash_reserve_pct      [0.30, 0.80]  step=0.05
  paused                bool          kill-switch

Navigator parameters:
  position_size_usd     [5000, 25000] step=1000
  paused                bool          kill-switch

All operator overrides expire after OVERRIDE_TTL_HOURS (default 24 h).
At expiry the system auto-reverts to factory defaults.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from analysis.claude_client import call_claude
from db.postgres import is_pg_available, get_conn

# ── Override TTL ──────────────────────────────────────────────────────────────

OVERRIDE_TTL_HOURS: int = 24

# ── Bounds & steps ────────────────────────────────────────────────────────────

ORACLE_BOUNDS: dict[str, tuple[float, float]] = {
    "conviction_threshold": (0.60, 0.95),
    "max_positions":        (1.0,  10.0),
    "cash_reserve_pct":     (0.30, 0.80),
}

ORACLE_STEPS: dict[str, float] = {
    "conviction_threshold": 0.05,
    "max_positions":        1.0,
    "cash_reserve_pct":     0.05,
}

ORACLE_DEFAULTS: dict[str, float] = {
    "conviction_threshold": 0.75,
    "max_positions":        10.0,
    "cash_reserve_pct":     0.60,
}

NAVIGATOR_BOUNDS: dict[str, tuple[float, float]] = {
    "position_size_usd": (5000.0, 25000.0),
}

NAVIGATOR_STEPS: dict[str, float] = {
    "position_size_usd": 1000.0,
}

NAVIGATOR_DEFAULTS: dict[str, float] = {
    "position_size_usd": 10000.0,
}


# ── Pydantic output models ────────────────────────────────────────────────────

class OracleParamAdjustment(BaseModel):
    conviction_threshold: float | None = Field(None, description="Minimum conviction [0.60-0.95] step 0.05")
    max_positions: int | None = Field(None, description="Max concurrent positions [1-10] step 1")
    cash_reserve_pct: float | None = Field(None, description="Cash reserve fraction [0.30-0.80] step 0.05")
    reasoning: str = Field("", description="Why these changes are recommended")
    no_change: bool = Field(False, description="True if no parameter changes are recommended")


class NavigatorParamAdjustment(BaseModel):
    position_size_usd: float | None = Field(None, description="Per-trade size USD [5000-25000] step 1000")
    reasoning: str = Field("", description="Why these changes are recommended")
    no_change: bool = Field(False, description="True if no parameter changes are recommended")


# ── Expiry helpers ────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _expiry_ts() -> datetime:
    return _now_utc() + timedelta(hours=OVERRIDE_TTL_HOURS)


# ── DB read helpers (expiry-aware) ────────────────────────────────────────────

def get_oracle_params() -> dict[str, Any]:
    """Load current Oracle parameters from DB, auto-reverting expired overrides."""
    defaults: dict[str, Any] = {**ORACLE_DEFAULTS, "paused": False,
                                 "override_set_at": None, "override_expires_at": None}
    if not is_pg_available():
        return defaults
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT conviction_threshold, max_positions, cash_reserve_pct,
                              paused, override_set_at, override_expires_at
                       FROM oracle_parameters WHERE id = 1"""
                )
                row = cur.fetchone()
        if not row:
            return defaults

        expires_at = row[5]
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at and _now_utc() > expires_at:
            logger.info("ParameterAdvisor | Oracle override expired — auto-reverting to defaults")
            _revert_oracle_to_defaults()
            return {**ORACLE_DEFAULTS, "paused": False, "override_set_at": None, "override_expires_at": None}

        return {
            "conviction_threshold": float(row[0]),
            "max_positions":        int(row[1]),
            "cash_reserve_pct":     float(row[2]),
            "paused":               bool(row[3]) if row[3] is not None else False,
            "override_set_at":      row[4].isoformat() if row[4] else None,
            "override_expires_at":  expires_at.isoformat() if expires_at else None,
        }
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | get_oracle_params failed: {exc}")
    return defaults


def get_navigator_params() -> dict[str, Any]:
    """Load current Navigator parameters from DB, auto-reverting expired overrides."""
    defaults: dict[str, Any] = {**NAVIGATOR_DEFAULTS, "paused": False,
                                 "override_set_at": None, "override_expires_at": None}
    if not is_pg_available():
        return defaults
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT position_size_usd, paused, override_set_at, override_expires_at
                       FROM navigator_parameters WHERE id = 1"""
                )
                row = cur.fetchone()
        if not row:
            return defaults

        expires_at = row[3]
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at and _now_utc() > expires_at:
            logger.info("ParameterAdvisor | Navigator override expired — auto-reverting to defaults")
            _revert_navigator_to_defaults()
            return {**NAVIGATOR_DEFAULTS, "paused": False, "override_set_at": None, "override_expires_at": None}

        return {
            "position_size_usd": float(row[0]),
            "paused":            bool(row[1]) if row[1] is not None else False,
            "override_set_at":   row[2].isoformat() if row[2] else None,
            "override_expires_at": expires_at.isoformat() if expires_at else None,
        }
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | get_navigator_params failed: {exc}")
    return defaults


def _revert_oracle_to_defaults() -> None:
    """Auto-revert Oracle to factory defaults after expiry (no audit entry needed)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE oracle_parameters SET
                         conviction_threshold = 0.75, max_positions = 10,
                         cash_reserve_pct = 0.60, paused = FALSE,
                         override_set_at = NULL, override_expires_at = NULL,
                         updated_at = NOW(), updated_by = 'expiry_revert'
                       WHERE id = 1"""
                )
    except Exception as exc:
        logger.error(f"ParameterAdvisor | Oracle expiry revert failed: {exc}")


def _revert_navigator_to_defaults() -> None:
    """Auto-revert Navigator to factory defaults after expiry."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE navigator_parameters SET
                         position_size_usd = 10000, paused = FALSE,
                         override_set_at = NULL, override_expires_at = NULL,
                         updated_at = NOW(), updated_by = 'expiry_revert'
                       WHERE id = 1"""
                )
    except Exception as exc:
        logger.error(f"ParameterAdvisor | Navigator expiry revert failed: {exc}")


# ── DB write helpers ──────────────────────────────────────────────────────────

def _write_audit(
    bot_id: str,
    param_name: str,
    old_val: Any,
    new_val: Any,
    reasoning: str,
    source: str,
    expires_at: datetime | None,
) -> None:
    """Write a single row to ai_parameter_audit with enriched columns."""
    try:
        old_num = float(old_val) if old_val is not None else None
        new_num = float(new_val) if new_val is not None else None
    except (TypeError, ValueError):
        old_num = new_num = None

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ai_parameter_audit
                           (bot_id, param_name, parameter_name, old_value, new_value,
                            old_value_num, new_value_num, reasoning, approved_by, source, expires_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        bot_id, param_name, param_name,
                        str(old_val), str(new_val),
                        old_num, new_num,
                        reasoning, "operator", source,
                        expires_at,
                    ),
                )
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | audit write failed for {bot_id}/{param_name}: {exc}")


def apply_oracle_params(
    params: dict[str, Any],
    reasoning: str,
    source: str = "fleet_commander",
    ttl_hours: int = OVERRIDE_TTL_HOURS,
) -> bool:
    """Clamp-and-step then persist Oracle params with 24h expiry. Writes enriched audit trail."""
    if not is_pg_available():
        logger.warning("ParameterAdvisor | DB unavailable — cannot apply Oracle params")
        return False
    try:
        current = get_oracle_params()
        updates: dict[str, Any] = {}
        audit_entries: list[tuple] = []

        # Handle paused toggle
        if "paused" in params:
            new_paused = bool(params["paused"])
            if new_paused != current.get("paused", False):
                updates["paused"] = new_paused
                audit_entries.append(("paused", current.get("paused"), new_paused))

        # Handle numeric params
        for key, val in params.items():
            if key == "paused" or key not in ORACLE_BOUNDS:
                continue
            lo, hi = ORACLE_BOUNDS[key]
            step = ORACLE_STEPS[key]
            cur_val = float(current.get(key, lo))
            new_val = _clamp_step(cur_val, float(val), lo, hi, step)
            if key == "max_positions":
                new_val = int(round(new_val))
            if new_val != cur_val:
                updates[key] = new_val
                audit_entries.append((key, cur_val, new_val))

        if not updates:
            logger.info("ParameterAdvisor | Oracle params: no effective changes after clamping")
            return True

        now = _now_utc()
        expires = now + timedelta(hours=ttl_hours)

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + ["fleet_commander"]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""UPDATE oracle_parameters SET {set_clause},
                        updated_at = NOW(), updated_by = %s,
                        override_set_at = NOW(), override_expires_at = %s
                       WHERE id = 1""",
                    values + [expires],
                )

        for param_name, old_v, new_v in audit_entries:
            _write_audit("oracle", param_name, old_v, new_v, reasoning, source, expires)

        logger.info(f"ParameterAdvisor | Oracle params applied: {updates} (expires {expires.isoformat()})")
        return True
    except Exception as exc:
        logger.error(f"ParameterAdvisor | apply_oracle_params failed: {exc}")
        return False


def apply_navigator_params(
    params: dict[str, Any],
    reasoning: str,
    source: str = "fleet_commander",
    ttl_hours: int = OVERRIDE_TTL_HOURS,
) -> bool:
    """Clamp-and-step then persist Navigator params with 24h expiry. Writes enriched audit trail."""
    if not is_pg_available():
        logger.warning("ParameterAdvisor | DB unavailable — cannot apply Navigator params")
        return False
    try:
        current = get_navigator_params()
        updates: dict[str, Any] = {}
        audit_entries: list[tuple] = []

        if "paused" in params:
            new_paused = bool(params["paused"])
            if new_paused != current.get("paused", False):
                updates["paused"] = new_paused
                audit_entries.append(("paused", current.get("paused"), new_paused))

        for key, val in params.items():
            if key == "paused" or key not in NAVIGATOR_BOUNDS:
                continue
            lo, hi = NAVIGATOR_BOUNDS[key]
            step = NAVIGATOR_STEPS[key]
            cur_val = float(current.get(key, lo))
            new_val = _clamp_step(cur_val, float(val), lo, hi, step)
            if new_val != cur_val:
                updates[key] = new_val
                audit_entries.append((key, cur_val, new_val))

        if not updates:
            logger.info("ParameterAdvisor | Navigator params: no effective changes after clamping")
            return True

        now = _now_utc()
        expires = now + timedelta(hours=ttl_hours)

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + ["fleet_commander"]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""UPDATE navigator_parameters SET {set_clause},
                        updated_at = NOW(), updated_by = %s,
                        override_set_at = NOW(), override_expires_at = %s
                       WHERE id = 1""",
                    values + [expires],
                )

        for param_name, old_v, new_v in audit_entries:
            _write_audit("navigator", param_name, old_v, new_v, reasoning, source, expires)

        logger.info(f"ParameterAdvisor | Navigator params applied: {updates} (expires {expires.isoformat()})")
        return True
    except Exception as exc:
        logger.error(f"ParameterAdvisor | apply_navigator_params failed: {exc}")
        return False


def set_oracle_paused(paused: bool, reasoning: str = "Operator pause toggle") -> bool:
    """Convenience: toggle Oracle paused state."""
    return apply_oracle_params({"paused": paused}, reasoning=reasoning, source="operator_ui")


def set_navigator_paused(paused: bool, reasoning: str = "Operator pause toggle") -> bool:
    """Convenience: toggle Navigator paused state."""
    return apply_navigator_params({"paused": paused}, reasoning=reasoning, source="operator_ui")


def reset_oracle_params(source: str = "operator_reset") -> bool:
    """Reset Oracle parameters to factory defaults (clears expiry)."""
    if not is_pg_available():
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE oracle_parameters SET
                         conviction_threshold = 0.75, max_positions = 10,
                         cash_reserve_pct = 0.60, paused = FALSE,
                         override_set_at = NULL, override_expires_at = NULL,
                         updated_at = NOW(), updated_by = %s
                       WHERE id = 1""",
                    (source,),
                )
        _write_audit("oracle", "reset", "all", "factory_defaults", "Reset to factory defaults", source, None)
        logger.info("ParameterAdvisor | Oracle params reset to defaults")
        return True
    except Exception as exc:
        logger.error(f"ParameterAdvisor | reset_oracle_params failed: {exc}")
        return False


def reset_navigator_params(source: str = "operator_reset") -> bool:
    """Reset Navigator parameters to factory defaults (clears expiry)."""
    if not is_pg_available():
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE navigator_parameters SET
                         position_size_usd = 10000, paused = FALSE,
                         override_set_at = NULL, override_expires_at = NULL,
                         updated_at = NOW(), updated_by = %s
                       WHERE id = 1""",
                    (source,),
                )
        _write_audit("navigator", "reset", "all", "factory_defaults", "Reset to factory defaults", source, None)
        logger.info("ParameterAdvisor | Navigator params reset to defaults")
        return True
    except Exception as exc:
        logger.error(f"ParameterAdvisor | reset_navigator_params failed: {exc}")
        return False


def get_parameter_audit_history(limit: int = 50) -> list[dict]:
    """Fetch recent parameter audit log entries across all bots."""
    if not is_pg_available():
        return []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ts, bot_id,
                              COALESCE(parameter_name, param_name) AS parameter_name,
                              old_value, new_value,
                              old_value_num, new_value_num,
                              reasoning, approved_by, source, expires_at
                       FROM ai_parameter_audit ORDER BY ts DESC LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
        return [
            {
                "ts":             r[0].isoformat(),
                "bot_id":         r[1],
                "parameter_name": r[2],
                "param_name":     r[2],
                "old_value":      r[3],
                "new_value":      r[4],
                "old_value_num":  r[5],
                "new_value_num":  r[6],
                "reasoning":      r[7],
                "approved_by":    r[8],
                "source":         r[9],
                "expires_at":     r[10].isoformat() if r[10] else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | get_parameter_audit_history failed: {exc}")
        return []


def get_all_active_overrides() -> dict[str, Any]:
    """Return all currently active (non-expired) parameter overrides for all bots."""
    oracle = get_oracle_params()
    navigator = get_navigator_params()
    now = _now_utc()

    def _is_active(params: dict) -> bool:
        exp = params.get("override_expires_at")
        if not exp:
            return False
        try:
            exp_dt = datetime.fromisoformat(exp)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            return now < exp_dt
        except Exception:
            return False

    def _seconds_remaining(params: dict) -> int | None:
        exp = params.get("override_expires_at")
        if not exp:
            return None
        try:
            exp_dt = datetime.fromisoformat(exp)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            secs = int((exp_dt - now).total_seconds())
            return max(0, secs)
        except Exception:
            return None

    return {
        "oracle": {
            "params": oracle,
            "defaults": ORACLE_DEFAULTS,
            "bounds": {k: {"min": v[0], "max": v[1], "step": ORACLE_STEPS[k]} for k, v in ORACLE_BOUNDS.items()},
            "has_active_override": _is_active(oracle),
            "seconds_remaining": _seconds_remaining(oracle),
        },
        "navigator": {
            "params": navigator,
            "defaults": NAVIGATOR_DEFAULTS,
            "bounds": {k: {"min": v[0], "max": v[1], "step": NAVIGATOR_STEPS[k]} for k, v in NAVIGATOR_BOUNDS.items()},
            "has_active_override": _is_active(navigator),
            "seconds_remaining": _seconds_remaining(navigator),
        },
    }


# ── Claude advisory calls ─────────────────────────────────────────────────────

def get_oracle_adjustment(fleet_context: str) -> OracleParamAdjustment:
    """Ask Claude whether Oracle parameters should be adjusted based on current fleet data."""
    current = get_oracle_params()
    system = (
        "You are an AI parameter advisor for Oracle Bot #1, an Alpaca paper-trading equity bot. "
        "Review the fleet context and current Oracle parameters, then decide if any adjustments "
        "are warranted.  Output ONLY a JSON object with these fields:\n"
        '  "conviction_threshold": <float or null>,\n'
        '  "max_positions": <int or null>,\n'
        '  "cash_reserve_pct": <float or null>,\n'
        '  "reasoning": "<brief explanation>",\n'
        '  "no_change": <true if no changes recommended>\n\n'
        "RULES:\n"
        "- conviction_threshold: [0.60, 0.95] step=0.05. Lower = more trades, higher = selective.\n"
        "- max_positions: [1, 10] step=1. Concurrent equity positions allowed.\n"
        "- cash_reserve_pct: [0.30, 0.80] step=0.05. Fraction to keep as cash/SGOV.\n"
        "- Maximum ±1 step change per parameter per cycle.\n"
        "- Only recommend changes if there is clear data-driven justification.\n"
        "- If no changes are needed, set no_change=true and leave params null.\n"
    )
    user = (
        f"Current Oracle parameters:\n"
        f"  conviction_threshold: {current['conviction_threshold']}\n"
        f"  max_positions: {current['max_positions']}\n"
        f"  cash_reserve_pct: {current['cash_reserve_pct']}\n"
        f"  paused: {current.get('paused', False)}\n\n"
        f"Fleet context:\n{fleet_context}\n\n"
        "Should any Oracle parameters be adjusted?  Respond with JSON only."
    )
    try:
        raw = call_claude(
            system_prompt=system,
            user_prompt=user,
            temperature=0.2,
            max_tokens=512,
            call_type="oracle_param_advisor",
            expect_json=True,
            smart=False,
        )
        data = json.loads(raw) if isinstance(raw, str) else raw
        return OracleParamAdjustment.model_validate(data)
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | Oracle adjustment call failed: {exc}")
        return OracleParamAdjustment(no_change=True, reasoning=f"Advisor unavailable: {exc}")


def get_navigator_adjustment(fleet_context: str) -> NavigatorParamAdjustment:
    """Ask Claude whether Navigator parameters should be adjusted based on current fleet data."""
    current = get_navigator_params()
    system = (
        "You are an AI parameter advisor for Navigator Bot #6, a paper forex trading bot. "
        "Review the fleet context and current Navigator parameters, then decide if adjustments "
        "are warranted.  Output ONLY a JSON object with these fields:\n"
        '  "position_size_usd": <float or null>,\n'
        '  "reasoning": "<brief explanation>",\n'
        '  "no_change": <true if no changes recommended>\n\n'
        "RULES:\n"
        "- position_size_usd: [5000, 25000] step=1000. Per-trade notional in USD.\n"
        "- Maximum ±1 step change per cycle.\n"
        "- Only recommend changes with clear data-driven justification.\n"
        "- If no changes are needed, set no_change=true and position_size_usd=null.\n"
    )
    user = (
        f"Current Navigator parameters:\n"
        f"  position_size_usd: {current['position_size_usd']}\n"
        f"  paused: {current.get('paused', False)}\n\n"
        f"Fleet context:\n{fleet_context}\n\n"
        "Should any Navigator parameters be adjusted?  Respond with JSON only."
    )
    try:
        raw = call_claude(
            system_prompt=system,
            user_prompt=user,
            temperature=0.2,
            max_tokens=256,
            call_type="navigator_param_advisor",
            expect_json=True,
            smart=False,
        )
        data = json.loads(raw) if isinstance(raw, str) else raw
        return NavigatorParamAdjustment.model_validate(data)
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | Navigator adjustment call failed: {exc}")
        return NavigatorParamAdjustment(no_change=True, reasoning=f"Advisor unavailable: {exc}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _clamp_step(current: float, target: float, lo: float, hi: float, step: float) -> float:
    """Move current toward target by at most one step, then clamp to [lo, hi]."""
    if target > current:
        new_val = current + step
    elif target < current:
        new_val = current - step
    else:
        new_val = current
    new_val = max(lo, min(hi, new_val))
    precision = max(0, -int(f"{step:.10f}".rstrip("0").find(".") - len(f"{step:.10f}".rstrip("0"))) + 1) if "." in f"{step}" else 0
    return round(new_val, precision if precision > 0 else 6)
