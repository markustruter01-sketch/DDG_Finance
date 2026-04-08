"""Claude Parameter Advisor — AI-driven lever recommendations for Oracle and Navigator bots.

Called by fleet_commander.py during each audit cycle to produce parameter adjustment
suggestions.  The operator must explicitly approve all changes before they are persisted.

Oracle parameters:
  conviction_threshold  [0.60, 0.95]  step=0.05
  max_positions         [1,    10]    step=1
  cash_reserve_pct      [0.30, 0.80]  step=0.05

Navigator parameters:
  position_size_usd     [5000, 25000] step=1000
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from analysis.claude_client import call_claude
from db.postgres import is_pg_available, get_conn

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

NAVIGATOR_BOUNDS: dict[str, tuple[float, float]] = {
    "position_size_usd": (5000.0, 25000.0),
}

NAVIGATOR_STEPS: dict[str, float] = {
    "position_size_usd": 1000.0,
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


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_oracle_params() -> dict[str, float]:
    """Load current Oracle parameters from DB, falling back to defaults."""
    defaults = {"conviction_threshold": 0.75, "max_positions": 10, "cash_reserve_pct": 0.60}
    if not is_pg_available():
        return defaults
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT conviction_threshold, max_positions, cash_reserve_pct FROM oracle_parameters WHERE id = 1"
                )
                row = cur.fetchone()
        if row:
            return {
                "conviction_threshold": float(row[0]),
                "max_positions":        int(row[1]),
                "cash_reserve_pct":     float(row[2]),
            }
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | get_oracle_params failed: {exc}")
    return defaults


def get_navigator_params() -> dict[str, float]:
    """Load current Navigator parameters from DB, falling back to defaults."""
    defaults = {"position_size_usd": 10000.0}
    if not is_pg_available():
        return defaults
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT position_size_usd FROM navigator_parameters WHERE id = 1")
                row = cur.fetchone()
        if row:
            return {"position_size_usd": float(row[0])}
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | get_navigator_params failed: {exc}")
    return defaults


def apply_oracle_params(
    params: dict[str, Any],
    reasoning: str,
    source: str = "fleet_commander",
) -> bool:
    """Clamp-and-step then persist Oracle params.  Writes audit trail.  Returns success."""
    if not is_pg_available():
        logger.warning("ParameterAdvisor | DB unavailable — cannot apply Oracle params")
        return False
    try:
        current = get_oracle_params()
        updates: dict[str, Any] = {}
        audit_rows: list[tuple] = []

        for key, val in params.items():
            if key not in ORACLE_BOUNDS:
                continue
            lo, hi = ORACLE_BOUNDS[key]
            step = ORACLE_STEPS[key]
            cur_val = current.get(key, lo)
            new_val = _clamp_step(cur_val, float(val), lo, hi, step)
            if key == "max_positions":
                new_val = int(round(new_val))
            if new_val != cur_val:
                updates[key] = new_val
                audit_rows.append((
                    "oracle", key, str(cur_val), str(new_val), reasoning, "operator", source,
                ))

        if not updates:
            logger.info("ParameterAdvisor | Oracle params: no effective changes after clamping")
            return True

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + ["fleet_commander"]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE oracle_parameters SET {set_clause}, updated_at = NOW(), updated_by = %s WHERE id = 1",
                    values,
                )
                for row in audit_rows:
                    cur.execute(
                        """INSERT INTO ai_parameter_audit
                               (bot_id, param_name, old_value, new_value, reasoning, approved_by, source)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        row,
                    )
        logger.info(f"ParameterAdvisor | Oracle params applied: {updates}")
        return True
    except Exception as exc:
        logger.error(f"ParameterAdvisor | apply_oracle_params failed: {exc}")
        return False


def apply_navigator_params(
    params: dict[str, Any],
    reasoning: str,
    source: str = "fleet_commander",
) -> bool:
    """Clamp-and-step then persist Navigator params.  Writes audit trail.  Returns success."""
    if not is_pg_available():
        logger.warning("ParameterAdvisor | DB unavailable — cannot apply Navigator params")
        return False
    try:
        current = get_navigator_params()
        updates: dict[str, Any] = {}
        audit_rows: list[tuple] = []

        for key, val in params.items():
            if key not in NAVIGATOR_BOUNDS:
                continue
            lo, hi = NAVIGATOR_BOUNDS[key]
            step = NAVIGATOR_STEPS[key]
            cur_val = current.get(key, lo)
            new_val = _clamp_step(cur_val, float(val), lo, hi, step)
            if new_val != cur_val:
                updates[key] = new_val
                audit_rows.append((
                    "navigator", key, str(cur_val), str(new_val), reasoning, "operator", source,
                ))

        if not updates:
            logger.info("ParameterAdvisor | Navigator params: no effective changes after clamping")
            return True

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + ["fleet_commander"]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE navigator_parameters SET {set_clause}, updated_at = NOW(), updated_by = %s WHERE id = 1",
                    values,
                )
                for row in audit_rows:
                    cur.execute(
                        """INSERT INTO ai_parameter_audit
                               (bot_id, param_name, old_value, new_value, reasoning, approved_by, source)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        row,
                    )
        logger.info(f"ParameterAdvisor | Navigator params applied: {updates}")
        return True
    except Exception as exc:
        logger.error(f"ParameterAdvisor | apply_navigator_params failed: {exc}")
        return False


def reset_oracle_params(source: str = "operator_reset") -> bool:
    """Reset Oracle parameters to factory defaults."""
    return apply_oracle_params(
        {"conviction_threshold": 0.75, "max_positions": 10, "cash_reserve_pct": 0.60},
        reasoning="Reset to factory defaults",
        source=source,
    )


def reset_navigator_params(source: str = "operator_reset") -> bool:
    """Reset Navigator parameters to factory defaults."""
    return apply_navigator_params(
        {"position_size_usd": 10000.0},
        reasoning="Reset to factory defaults",
        source=source,
    )


def get_parameter_audit_history(limit: int = 50) -> list[dict]:
    """Fetch recent parameter audit log entries across all bots."""
    if not is_pg_available():
        return []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ts, bot_id, param_name, old_value, new_value, reasoning, approved_by, source
                       FROM ai_parameter_audit ORDER BY ts DESC LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
        return [
            {
                "ts":          r[0].isoformat(),
                "bot_id":      r[1],
                "param_name":  r[2],
                "old_value":   r[3],
                "new_value":   r[4],
                "reasoning":   r[5],
                "approved_by": r[6],
                "source":      r[7],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning(f"ParameterAdvisor | get_parameter_audit_history failed: {exc}")
        return []


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
        f"  cash_reserve_pct: {current['cash_reserve_pct']}\n\n"
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
        f"  position_size_usd: {current['position_size_usd']}\n\n"
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
