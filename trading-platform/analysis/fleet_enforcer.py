"""
analysis/fleet_enforcer.py — Safe enforcement of Fleet Commander recommendations
=================================================================================
Takes Gemini's FleetCommanderResponse and applies Alpaca veto conditions.
The retired Kraken parameter adjustment payload is recorded as skipped.

Safety guarantees:
  - All values clamped to BOUNDS from adaptive_params config
  - Maximum ±1 step change per parameter per audit cycle
  - Every change logged with before/after values and reasoning
  - Fail-open: if enforcement fails, bots continue with existing params
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

BOUNDS = {
    "ZSCORE_ENTRY":       (0.70, 1.50),
    "ZSCORE_EXIT":        (0.10, 0.55),
    "STOP_LOSS_PCT":      (0.008, 0.040),
    "TRAIL_PCT":          (0.030, 0.100),
    "MIN_NET_PROFIT_PCT": (0.006, 0.020),
}

STEPS = {
    "ZSCORE_ENTRY":       0.05,
    "ZSCORE_EXIT":        0.02,
    "STOP_LOSS_PCT":      0.002,
    "TRAIL_PCT":          0.005,
    "MIN_NET_PROFIT_PCT": 0.001,
}

FEE_PCT = 0.0026
FEE_FLOOR = FEE_PCT * 2 + 0.001

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
        changes_skipped.append({
            "bot_id": bot_id,
            "reason": "retired_kraken_parameter_store",
            "reasoning": adj.reasoning,
        })

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
        "veto_conditions_written": veto_written,
        "total_param_changes": sum(len(c["changes"]) for c in changes_applied),
    }
