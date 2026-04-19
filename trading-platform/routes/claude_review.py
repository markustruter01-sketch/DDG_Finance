"""
routes/claude_review.py — Claude Multi-Stage Audit API
========================================================
Manual-only endpoints for the 8-stage Claude deep audit system.

  GET  /trading-api/claude-review/stages             — all stages with status/cooldown/last result
  GET  /trading-api/claude-review/stage/{stage_id}   — full result for a specific stage
  POST /trading-api/claude-review/trigger/{stage_id} — trigger a specific stage in background
  GET  /trading-api/claude-review/history            — combined history across all stages

Never wired to APScheduler — manual trigger only.
"""

from __future__ import annotations

import threading
import uuid

from fastapi import APIRouter, HTTPException
from loguru import logger

claude_review_router = APIRouter()


@claude_review_router.get("/claude-review/stages", tags=["Claude Review"])
async def get_claude_stages() -> dict:
    """Returns all 8 audit stages with their current status, cooldown, and last result summary."""
    from analysis.claude_reviewer import get_all_stages_status
    stages = get_all_stages_status()
    return {"stages": stages, "count": len(stages)}


@claude_review_router.get("/claude-review/stage/{stage_id}", tags=["Claude Review"])
async def get_claude_stage_result(stage_id: str) -> dict:
    """Returns the full stored result for a specific audit stage."""
    from analysis.claude_reviewer import get_stage_full_result, AUDIT_STAGES
    if stage_id not in AUDIT_STAGES:
        raise HTTPException(status_code=404, detail=f"Unknown stage_id: {stage_id}")
    return get_stage_full_result(stage_id)


@claude_review_router.post("/claude-review/trigger/{stage_id}", tags=["Claude Review"])
async def trigger_claude_stage(stage_id: str) -> dict:
    """
    Triggers a specific audit stage in a background thread.
    Returns immediately with a run ID.

    Blocked if:
    - Another stage is already running (one stage at a time)
    - This stage's 23-hour cooldown has not expired
    """
    import os
    from analysis.claude_reviewer import (
        AUDIT_STAGES,
        _stage_run_states,
        _get_stage_cooldown,
        _run_lock,
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured — set it in Replit Secrets to use Claude Audit",
        )

    if stage_id not in AUDIT_STAGES:
        raise HTTPException(status_code=404, detail=f"Unknown stage_id: {stage_id}")

    any_running = next(
        (sid for sid, state in _stage_run_states.items() if state["in_progress"]), None
    )
    if any_running:
        running_meta = AUDIT_STAGES[any_running]
        raise HTTPException(
            status_code=409,
            detail=f"Another audit is already running: {running_meta['name']}. Wait for it to finish.",
        )

    cooldown = _get_stage_cooldown(stage_id)
    if cooldown["locked"]:
        remaining_h = cooldown["seconds_remaining"] // 3600
        remaining_m = (cooldown["seconds_remaining"] % 3600) // 60
        raise HTTPException(
            status_code=429,
            detail=(
                f"{AUDIT_STAGES[stage_id]['name']} is in cooldown — "
                f"available in {remaining_h}h {remaining_m}m. "
                f"Next available: {cooldown['next_available']}"
            ),
        )

    run_id = str(uuid.uuid4())[:8]
    meta = AUDIT_STAGES[stage_id]

    # Atomically mark in_progress in the request path to close the race window
    # between the check above and the thread acquiring _run_lock.
    _stage_run_states[stage_id].update({
        "in_progress": True,
        "run_id": run_id,
        "started_at": None,
        "error": None,
    })

    logger.info(f"ClaudeReview | Manual trigger: stage={stage_id} run_id={run_id}")

    def _bg_run():
        from analysis.claude_reviewer import trigger_stage
        trigger_stage(stage_id, run_id)

    thread = threading.Thread(target=_bg_run, daemon=True, name=f"claude-{stage_id}-{run_id}")
    thread.start()

    return {
        "status": "triggered",
        "stage_id": stage_id,
        "stage_name": meta["name"],
        "run_id": run_id,
        "message": f"{meta['name']} audit started — poll GET /trading-api/claude-review/stages for progress",
        "model": "claude-3-5-sonnet-20241022",
    }


@claude_review_router.get("/claude-review/history", tags=["Claude Review"])
async def get_claude_review_history() -> dict:
    """Returns the combined audit history across all stages (last 50 entries)."""
    from analysis.claude_reviewer import get_review_history
    history = get_review_history()
    return {"history": history, "count": len(history)}
