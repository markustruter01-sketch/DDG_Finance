"""
analysis/fleet_enforcer.py — Safe enforcement of Fleet Commander recommendations
=================================================================================
Takes Gemini's FleetCommanderResponse and applies parameter changes within
hard bounds.  Writes Kraken params to kraken_adaptive_params DB table and
Alpaca veto conditions to veto_conditions.json.

Safety guarantees:
  - All values clamped to BOUNDS from adaptive_params config
  - Maximum ±1 step change per parameter per audit cycle (steps are 4x expanded)
  - Every change logged with before/after values and reasoning
  - Fail-open: if enforcement fails, bots continue with existing params
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

KRAKEN_DEFAULTS: dict[str, float] = {
    "ZSCORE_ENTRY":       1.0,
    "ZSCORE_EXIT":        0.45,
    "STOP_LOSS_PCT":      0.015,
    "TRAIL_PCT":          0.03,
    "MIN_NET_PROFIT_PCT": 0.008,
}

OVERRIDE_TTL_HOURS = 24

BOUNDS = {
    "ZSCORE_ENTRY":       (0.70, 1.50),
    "ZSCORE_EXIT":        (0.10, 0.55),
    "STOP_LOSS_PCT":      (0.008, 0.040),
    "TRAIL_PCT":          (0.030, 0.100),
    "MIN_NET_PROFIT_PCT": (0.006, 0.020),
}

STEPS = {
    "ZSCORE_ENTRY":       0.20,
    "ZSCORE_EXIT":        0.08,
    "STOP_LOSS_PCT":      0.008,
    "TRAIL_PCT":          0.020,
    "MIN_NET_PROFIT_PCT": 0.004,
}

FEE_PCT = 0.0026
FEE_FLOOR = FEE_PCT * 2 + 0.001

BOT_ID_TO_DB_ID = {
    "davy_jones": 1,
    "blackbeard": 2,
    "calypso": 3,
}

_VETO_FILE = Path(__file__).parent.parent / "logs" / "veto_conditions.json"


def _clamp(name: str, value: float) -> float:
    lo, hi = BOUNDS[name]
    return max(lo, min(hi, value))


def _limit_step(current: float, target: float, param_name: str) -> float:
    step = STEPS[param_name]
    diff = target - current
    if abs(diff) <= step:
        return _clamp(param_name, target)
    direction = 1 if diff > 0 else -1
    return _clamp(param_name, round(current + direction * step, 6))


def _load_current_kraken_params(db_id: int) -> dict | None:
    """Load Kraken params from DB, auto-reverting if the override TTL has expired."""
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return None
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT params, paused, override_expires_at, override_set_at
                       FROM kraken_adaptive_params WHERE id = %s""",
                    (db_id,)
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None

        params = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
        paused = bool(row[1]) if row[1] is not None else False
        override_expires_at = row[2]
        override_set_at = row[3]

        # Auto-revert if override has expired
        if override_expires_at is not None:
            now = datetime.now(timezone.utc)
            exp = override_expires_at if override_expires_at.tzinfo else override_expires_at.replace(tzinfo=timezone.utc)
            if now >= exp:
                logger.info(
                    f"FleetEnforcer | Override expired for db_id={db_id} "
                    f"(expired at {exp.isoformat()}) — reverting to defaults"
                )
                _revert_kraken_to_defaults(db_id)
                params = dict(KRAKEN_DEFAULTS)
                paused = False
                override_expires_at = None
                override_set_at = None

        params["paused"] = paused
        if override_expires_at is not None:
            params["override_expires_at"] = override_expires_at.isoformat()
        if override_set_at is not None:
            params["override_set_at"] = override_set_at.isoformat()

        return params
    except Exception as exc:
        logger.warning(f"FleetEnforcer | Failed to load params for db_id={db_id}: {exc}")
        return None


def _revert_kraken_to_defaults(db_id: int) -> None:
    """Reset a Kraken bot's params to factory defaults and clear override TTL."""
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE kraken_adaptive_params SET
                           params               = %s,
                           paused               = FALSE,
                           override_expires_at  = NULL,
                           override_set_at      = NULL,
                           adapted_at           = NOW()
                       WHERE id = %s""",
                    (json.dumps(KRAKEN_DEFAULTS), db_id)
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(f"FleetEnforcer | Failed to revert defaults for db_id={db_id}: {exc}")


def _write_kraken_params(
    db_id: int,
    bot_id_str: str,
    params: dict,
    reasoning: str,
    ttl_hours: int = OVERRIDE_TTL_HOURS,
    source: str = "fleet_commander",
) -> bool:
    """Write Kraken params with TTL expiry, paused flag, and audit trail."""
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return False

        # Separate trading params from meta-fields
        paused = bool(params.get("paused", False))
        clean_params = {k: v for k, v in params.items()
                        if k in BOUNDS and isinstance(v, (int, float))}

        # Load existing params for audit diff
        existing = _load_current_kraken_params(db_id) or {}

        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_adaptive_params
                        (id, bot_id, params, metrics, reasons, adapted_at, lookback_n,
                         paused, override_set_at, override_expires_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), 0, %s, NOW(),
                            NOW() + (%s * INTERVAL '1 hour'))
                    ON CONFLICT (id) DO UPDATE SET
                        params              = EXCLUDED.params,
                        reasons             = EXCLUDED.reasons,
                        adapted_at          = NOW(),
                        paused              = EXCLUDED.paused,
                        override_set_at     = NOW(),
                        override_expires_at = NOW() + (%s * INTERVAL '1 hour')
                    """,
                    (
                        db_id, bot_id_str,
                        json.dumps(clean_params),
                        json.dumps({}),
                        json.dumps({"fleet_commander": reasoning}),
                        paused,
                        ttl_hours,
                        ttl_hours,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        # Write audit entries for changed params
        try:
            from analysis.claude_parameter_advisor import _write_audit
            expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            for param_name, new_val in clean_params.items():
                old_val = existing.get(param_name)
                if old_val is None or abs(float(old_val) - float(new_val)) > 1e-8:
                    _write_audit(
                        bot_id=bot_id_str,
                        param_name=param_name,
                        old_val=old_val,
                        new_val=new_val,
                        reasoning=reasoning,
                        source=source,
                        expires_at=expires_at,
                    )
            # Audit paused toggle separately
            old_paused = existing.get("paused", False)
            if bool(old_paused) != paused:
                _write_audit(
                    bot_id=bot_id_str,
                    param_name="paused",
                    old_val=old_paused,
                    new_val=paused,
                    reasoning=reasoning,
                    source=source,
                    expires_at=expires_at,
                )
        except Exception as ae:
            logger.debug(f"FleetEnforcer | Audit write failed (non-fatal): {ae}")

        return True
    except Exception as exc:
        logger.warning(f"FleetEnforcer | Failed to write params for {bot_id_str}: {exc}")
        return False


def _write_veto_conditions(vetoed_tickers: list[str], conditions: list[dict],
                            critique_summary: str, critique_flags: list[str],
                            verdict: str) -> bool:
    generated_at = datetime.now(timezone.utc)
    valid_until = generated_at + timedelta(hours=6)

    payload = {
        "generated_at": generated_at.isoformat(),
        "valid_until": valid_until.isoformat(),
        "vetoed_tickers": vetoed_tickers,
        "conditions": conditions,
        "critique_summary": critique_summary,
        "critique_flags": critique_flags,
        "overall_verdict": verdict,
        "source": "fleet_commander",
    }

    try:
        serialised = json.dumps(payload, indent=2, default=str)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=_VETO_FILE.parent, prefix=".veto_conditions_", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                f.write(serialised)
            os.replace(tmp_path, _VETO_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return True
    except Exception as exc:
        logger.warning(f"FleetEnforcer | Failed to write veto file: {exc}")
        return False


def enforce_fleet_recommendations(response) -> dict[str, Any]:
    changes_applied = []
    changes_skipped = []

    for adj in response.kraken_param_adjustments:
        bot_id = adj.bot_id.lower().strip()
        db_id = BOT_ID_TO_DB_ID.get(bot_id)
        if db_id is None:
            logger.warning(f"FleetEnforcer | Unknown bot_id '{bot_id}' — skipping")
            changes_skipped.append({"bot_id": bot_id, "reason": "unknown_bot_id"})
            continue

        current_params = _load_current_kraken_params(db_id)
        if current_params is None:
            logger.warning(f"FleetEnforcer | No existing params for {bot_id} (db_id={db_id}) — skipping")
            changes_skipped.append({"bot_id": bot_id, "reason": "no_existing_params"})
            continue

        updated = dict(current_params)
        param_changes = []

        for param_name in BOUNDS:
            recommended = getattr(adj, param_name, None)
            if recommended is None:
                continue

            current_val = current_params.get(param_name)
            if current_val is None:
                continue

            new_val = _limit_step(current_val, recommended, param_name)

            if param_name == "MIN_NET_PROFIT_PCT" and new_val < FEE_FLOOR:
                new_val = round(FEE_FLOOR, 6)

            if abs(new_val - current_val) > 1e-7:
                updated[param_name] = new_val
                change_info = {
                    "param": param_name,
                    "before": round(current_val, 6),
                    "after": round(new_val, 6),
                    "recommended": round(recommended, 6),
                    "clamped": abs(new_val - recommended) > 1e-7,
                }
                param_changes.append(change_info)
                logger.info(
                    f"FleetEnforcer | {bot_id}.{param_name}: "
                    f"{current_val:.4f} → {new_val:.4f} "
                    f"(recommended={recommended:.4f}, reason={adj.reasoning})"
                )

        if param_changes:
            success = _write_kraken_params(
                db_id, bot_id, updated, adj.reasoning,
                source="fleet_commander",
            )
            changes_applied.append({
                "bot_id": bot_id,
                "db_id": db_id,
                "changes": param_changes,
                "reasoning": adj.reasoning,
                "written": success,
            })
        else:
            changes_skipped.append({
                "bot_id": bot_id,
                "reason": "no_effective_changes",
                "reasoning": adj.reasoning,
            })

    # ── Apply Oracle parameter recommendations ────────────────────────────────
    oracle_applied: dict = {}
    oracle_adj = getattr(response, "oracle_param_adjustment", None)
    if oracle_adj is not None:
        try:
            from analysis.claude_parameter_advisor import apply_oracle_params
            oracle_params: dict = {}
            if oracle_adj.conviction_threshold is not None:
                oracle_params["conviction_threshold"] = oracle_adj.conviction_threshold
            if oracle_adj.max_positions is not None:
                oracle_params["max_positions"] = oracle_adj.max_positions
            if oracle_adj.cash_reserve_pct is not None:
                oracle_params["cash_reserve_pct"] = oracle_adj.cash_reserve_pct
            if oracle_params:
                ok = apply_oracle_params(
                    oracle_params, oracle_adj.reasoning, source="fleet_commander"
                )
                oracle_applied = {"params": oracle_params, "written": ok, "reasoning": oracle_adj.reasoning}
                logger.info(f"FleetEnforcer | Oracle params applied: {oracle_params} ok={ok}")
        except Exception as _oe:
            logger.warning(f"FleetEnforcer | Oracle param enforcement failed: {_oe}")

    # ── Apply Navigator parameter recommendations ─────────────────────────────
    navigator_applied: dict = {}
    nav_adj = getattr(response, "navigator_param_adjustment", None)
    if nav_adj is not None:
        try:
            from analysis.claude_parameter_advisor import apply_navigator_params
            nav_params: dict = {}
            if nav_adj.position_size_usd is not None:
                nav_params["position_size_usd"] = nav_adj.position_size_usd
            if nav_params:
                ok = apply_navigator_params(
                    nav_params, nav_adj.reasoning, source="fleet_commander"
                )
                navigator_applied = {"params": nav_params, "written": ok, "reasoning": nav_adj.reasoning}
                logger.info(f"FleetEnforcer | Navigator params applied: {nav_params} ok={ok}")
        except Exception as _ne:
            logger.warning(f"FleetEnforcer | Navigator param enforcement failed: {_ne}")

    veto_written = False
    should_write_veto = (
        response.vetoed_tickers
        or response.conditions
        or response.overall_verdict == "HOLD"
    )
    if should_write_veto:
        conditions_dicts = [c.model_dump(exclude_none=True) for c in response.conditions]
        if response.overall_verdict == "HOLD" and not conditions_dicts:
            conditions_dicts = [{"type": "fleet_hold", "value": 1.0}]
        veto_written = _write_veto_conditions(
            response.vetoed_tickers,
            conditions_dicts,
            response.critique_summary,
            response.critique_flags,
            response.overall_verdict,
        )

    return {
        "kraken_changes_applied": changes_applied,
        "kraken_changes_skipped": changes_skipped,
        "oracle_applied": oracle_applied,
        "navigator_applied": navigator_applied,
        "veto_conditions_written": veto_written,
        "total_param_changes": sum(len(c["changes"]) for c in changes_applied),
    }
