"""
routes/reports.py — Bot performance report endpoints.
Replaces the legacy /export/report and /export/report-parts endpoints.
"""
from __future__ import annotations

from typing import Any
import logging

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from reports.performance_report import generate_performance_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trading-api", tags=["Reports"])


@router.get("/reports/performance", response_class=PlainTextResponse)
def get_performance_report():
    """Generate and return the full bot performance report as plain text."""
    try:
        return generate_performance_report()
    except Exception as exc:
        logger.exception("Performance report generation failed")
        return PlainTextResponse(
            content=f"[Report generation failed]\nError: {exc}\n",
            status_code=500,
        )


@router.get("/reports/performance-parts")
def get_performance_report_parts() -> dict[str, Any]:
    """Generate report and split into named parts for dashboard download.
    Splits on section headers — keeps each section coherent."""
    try:
        text = generate_performance_report()
        parts: dict[str, dict] = {}
        current_section = "header"
        current_lines: list[str] = []
        section_idx = 0

        for line in text.split("\n"):
            if line.startswith("=== SECTION") or (line.startswith("===") and "END OF REPORT" in line):
                if current_lines:
                    content = "\n".join(current_lines)
                    parts[current_section] = {
                        "filename": f"report_{current_section.replace(' ', '_').lower()}.txt",
                        "text": content,
                        "lines": len(current_lines),
                        "chars": len(content),
                    }
                section_idx += 1
                current_section = f"part{section_idx}"
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            content = "\n".join(current_lines)
            parts[current_section] = {
                "filename": f"report_{current_section}.txt",
                "text": content,
                "lines": len(current_lines),
                "chars": len(content),
            }

        return {"parts": parts, "total_chars": len(text), "approx_tokens": len(text) // 4}
    except Exception as exc:
        logger.exception("Performance report parts generation failed")
        return {"error": str(exc)}


@router.get("/reports/performance-summary", response_class=PlainTextResponse)
def get_performance_summary():
    """Return just sections 1, 3.5, and 8 — the concise executive view.
    For Discord notifications or quick checks."""
    try:
        from reports.performance_report import (
            section_1_executive_summary,
            section_3_5_bot_comparison,
            section_8_anomalies,
        )
        lines = ["=" * 78, "BOT PERFORMANCE SUMMARY — QUANT TERMINAL", "=" * 78]
        lines.extend(section_1_executive_summary())
        lines.extend(section_3_5_bot_comparison())
        lines.extend(section_8_anomalies())
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("Performance summary failed")
        return PlainTextResponse(f"[Summary failed] {exc}", status_code=500)
