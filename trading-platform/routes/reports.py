"""
routes/reports.py — Bot performance report endpoints.
Backed by the claude-report JSON + text-formatter pipeline.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trading-api", tags=["Reports"])


async def _generate_text(days: int = 1) -> str:
    """Build the plain-text report using claude_report helpers."""
    from routes.claude_report import (
        _build_live_pos_cache, _build_errors_window, _build_open_positions,
        _build_fleet, _build_bots, _build_trades_window, _build_metrics_30d,
        _build_reconciliation_flags, _build_decisions_pending,
        _build_exit_attribution_30d, _build_walk_forward_status,
        _format_text, _DAYS_CAP, _now,
    )
    from datetime import timedelta

    days         = min(max(days, 1), _DAYS_CAP)
    window_start = _now() - timedelta(days=days)
    errors: list[dict] = []

    live_pos_cache      = await _build_live_pos_cache()
    log_events          = _build_errors_window(window_start, errors)
    open_positions      = _build_open_positions(live_pos_cache, errors)
    fleet               = _build_fleet(open_positions, errors)
    bots                = _build_bots(log_events, open_positions, errors)
    trades_window       = _build_trades_window(window_start, errors)
    metrics_30d         = _build_metrics_30d(errors)
    recon_flags         = _build_reconciliation_flags(live_pos_cache, errors)
    decisions           = _build_decisions_pending(window_start, errors)
    exit_attr           = _build_exit_attribution_30d(errors)
    walk_forward_status = _build_walk_forward_status(errors)

    from routes.claude_report import _iso
    report_dict = {
        "generated_at":          _iso(_now()),
        "window_days":           days,
        "fleet":                 fleet,
        "bots":                  bots,
        "open_positions":        open_positions,
        "trades_window":         trades_window,
        "metrics_30d":           metrics_30d,
        "reconciliation_flags":  recon_flags,
        "errors_window":         log_events,
        "decisions_pending":     decisions,
        "exit_attribution_30d":  exit_attr,
        "walk_forward_status":   walk_forward_status,
    }
    return _format_text(report_dict)


@router.get("/reports/performance", response_class=PlainTextResponse)
async def get_performance_report():
    """Generate and return the full bot performance report as plain text."""
    try:
        return await _generate_text(days=1)
    except Exception as exc:
        logger.exception("Performance report generation failed")
        return PlainTextResponse(
            content=f"[Report generation failed]\nError: {exc}\n",
            status_code=500,
        )


@router.get("/reports/performance-parts")
async def get_performance_report_parts() -> dict:
    """Return report as a single named part for dashboard download."""
    try:
        text = await _generate_text(days=1)
        return {
            "parts": {
                "part1": {
                    "filename": "quant-terminal-report.txt",
                    "text":     text,
                    "lines":    text.count("\n"),
                    "chars":    len(text),
                }
            },
            "total_chars":    len(text),
            "approx_tokens":  len(text) // 4,
        }
    except Exception as exc:
        logger.exception("Performance report parts generation failed")
        return {"error": str(exc)}


@router.get("/reports/performance-summary", response_class=PlainTextResponse)
async def get_performance_summary():
    """Concise executive view — first section of the claude-report text."""
    try:
        text = await _generate_text(days=1)
        lines = text.split("\n")
        summary = [l for l in lines if l.strip()][:40]
        return "\n".join(summary)
    except Exception as exc:
        logger.exception("Performance summary failed")
        return PlainTextResponse(f"[Summary failed] {exc}", status_code=500)
