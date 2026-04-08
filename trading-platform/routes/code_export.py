"""
code_export.py — Code export endpoints for Claude / AI review
=============================================================
/export/code-parts  — bundles all core source files into byte-exact text parts
/export/code-audit  — SHA-256 integrity check: live file vs last-exported snapshot
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter
from starlette.responses import JSONResponse

logger = logging.getLogger("code_export")

code_export_router = APIRouter()

_REPO_ROOT = Path(__file__).parent.parent.parent

_HASH_SNAPSHOT_PATH = _REPO_ROOT / "trading-platform" / "_code_export_hashes.json"

_SOURCE_FILES: list[str] = [
    # ── Trading platform core ──────────────────────────────────────────────
    "trading-platform/main.py",
    "trading-platform/config/settings.py",
    "trading-platform/core/pipeline.py",
    "trading-platform/core/scheduler.py",
    "trading-platform/core/market_clock.py",
    "trading-platform/core/degradation_tracker.py",
    "trading-platform/core/veto_enforcer.py",
    "trading-platform/core/cycle_state.py",
    # ── Execution layer ────────────────────────────────────────────────────
    "trading-platform/execution/broker.py",
    "trading-platform/execution/executor.py",
    "trading-platform/execution/algo_scanner.py",
    "trading-platform/execution/short_scanner.py",
    "trading-platform/execution/kill_switch.py",
    "trading-platform/execution/momentum_universe.py",
    "trading-platform/execution/profit_sweep.py",
    "trading-platform/execution/ratchet_stop.py",
    "trading-platform/execution/resilience.py",
    "trading-platform/execution/compliance.py",
    # ── Portfolio engine ───────────────────────────────────────────────────
    "trading-platform/portfolio/allocator.py",
    "trading-platform/portfolio/kelly.py",
    "trading-platform/portfolio/var_calculator.py",
    # ── Analysis & AI ──────────────────────────────────────────────────────
    "trading-platform/analysis/analyzer.py",
    "trading-platform/analysis/auditor.py",
    "trading-platform/analysis/attribution.py",
    "trading-platform/analysis/backtester.py",
    "trading-platform/analysis/correlation_matrix.py",
    "trading-platform/analysis/crypto_regime.py",
    "trading-platform/analysis/fleet_commander.py",
    "trading-platform/analysis/fleet_enforcer.py",
    "trading-platform/analysis/groq_budget.py",
    "trading-platform/analysis/groq_client.py",
    "trading-platform/analysis/learning_journal.py",
    "trading-platform/analysis/learning_snapshot.py",
    "trading-platform/analysis/micro_auditor.py",
    "trading-platform/analysis/post_mortem.py",
    "trading-platform/analysis/rule_engine.py",
    "trading-platform/analysis/schemas.py",
    "trading-platform/analysis/signal_guard.py",
    "trading-platform/analysis/trade_journal.py",
    "trading-platform/analysis/feedback_injection.py",
    "trading-platform/analysis/regime_bias_manager.py",
    # ── Data ingestion ─────────────────────────────────────────────────────
    "trading-platform/data/cache.py",
    "trading-platform/data/economic_calendar.py",
    "trading-platform/data/fred_client.py",
    "trading-platform/data/news_client.py",
    "trading-platform/data/onchain.py",
    "trading-platform/data/sentiment.py",
    "trading-platform/data/yfinance_client.py",
    # ── Database ───────────────────────────────────────────────────────────
    "trading-platform/db/postgres.py",
    # ── Notifications ──────────────────────────────────────────────────────
    "trading-platform/notifications/alert_manager.py",
    "trading-platform/notifications/telegram.py",
    "trading-platform/notifications/discord.py",
    # ── Options engine ─────────────────────────────────────────────────────
    "trading-platform/options_engine.py",
    # ── API routes ─────────────────────────────────────────────────────────
    "trading-platform/routes/__init__.py",
    "trading-platform/routes/_deps.py",
    "trading-platform/routes/system.py",
    "trading-platform/routes/portfolio.py",
    "trading-platform/routes/report_sections.py",
    "trading-platform/routes/control.py",
    "trading-platform/routes/admin.py",
    "trading-platform/routes/kraken.py",
    "trading-platform/routes/options.py",
    "trading-platform/routes/forex.py",
    "trading-platform/routes/alerts.py",
    "trading-platform/routes/fleet_chat.py",
    "trading-platform/routes/ai_impact.py",
    "trading-platform/routes/code_export.py",
    # ── Kraken crypto bot engines (#2 Davy Jones / #3 Blackbeard / #4 Calypso)
    "kraken-bot/main.py",
    "kraken-bot/logic.py",
    "kraken-bot/microstructure.py",
    "kraken-bot/vpin_adaptive.py",
    "kraken-bot/adaptive_params.py",
    "kraken-bot/paper_engine.py",
    "kraken-bot/scalp_strategies.py",
    "kraken-bot/swing_strategies.py",
    "kraken-bot/scalp_exits.py",
    "kraken-bot/swing_exits.py",
    "kraken-bot/flow_sentiment.py",
    "kraken-bot/fetch_data.py",
    "kraken-bot/db.py",
    "kraken-bot/config.py",
    "kraken-bot/penalty_tracker.py",
    "kraken-bot/ws_feed.py",
    # ── Forex Navigator engine (#6 Navigator) ──────────────────────────────
    "forex-engine/forex_engine.py",
    "forex-engine/forex_nav_db.py",
    "forex-engine/forex_config.py",
    "forex-engine/paper_engine.py",
    "forex-engine/indicators.py",
    "forex-engine/journal.py",
    # ── Shared utilities (workspace-level risk/exit/circuit-breaker logic) ──
    "shared/__init__.py",
    "shared/circuit_breaker.py",
    "shared/exit_bracket.py",
    "shared/market_snapshot_validator.py",
    "shared/risk_profile.py",
    "shared/var_circuit_breaker.py",
    # ── Dashboard frontend ─────────────────────────────────────────────────
    "artifacts/dashboard/src/pages/Dashboard.tsx",
    "artifacts/dashboard/src/hooks/use-trading.ts",
    "artifacts/dashboard/src/App.tsx",
    "artifacts/dashboard/src/components/BotCard.tsx",
    "artifacts/dashboard/src/components/ControlPanel.tsx",
    "artifacts/dashboard/src/components/EmergencyControls.tsx",
    "artifacts/dashboard/src/components/FleetPerformanceHero.tsx",
    "artifacts/dashboard/src/components/LivePositionsSection.tsx",
    "artifacts/dashboard/src/components/PortfolioSummary.tsx",
    "artifacts/dashboard/src/components/FleetCommanderPanel.tsx",
]

_PART_LIMIT = 80_000


def _file_header_bytes(rel_path: str) -> bytes:
    return f"===== FILE: {rel_path} =====\n".encode("utf-8")


def _read_file_raw(abs_path: Path) -> bytes:
    with open(abs_path, "rb") as fh:
        return fh.read()


def _build_export_block(rel_path: str, raw_content: bytes) -> bytes:
    """Return the exact bytes that represent this file in the export: header + raw content + trailing newlines."""
    return _file_header_bytes(rel_path) + raw_content + b"\n\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect_file_data() -> list[tuple[str, bytes, bytes]]:
    """Returns list of (rel_path, raw_content, export_block_bytes)."""
    result: list[tuple[str, bytes, bytes]] = []
    for rel in _SOURCE_FILES:
        abs_path = _REPO_ROOT / rel
        if not abs_path.exists():
            continue
        raw = _read_file_raw(abs_path)
        block = _build_export_block(rel, raw)
        result.append((rel, raw, block))
    return result


def _block_char_count(block: bytes) -> int:
    """Return the character count of an export block after UTF-8 / latin-1 decoding."""
    try:
        return len(block.decode("utf-8"))
    except UnicodeDecodeError:
        return len(block.decode("latin-1"))


def _split_into_parts(file_data: list[tuple[str, bytes, bytes]]) -> list[bytes]:
    """Split export blocks into parts at file boundaries only, each part ≤ PART_LIMIT characters."""
    parts: list[bytes] = []
    current = b""
    current_chars = 0
    for _rel, _raw, block in file_data:
        block_chars = _block_char_count(block)
        if current and current_chars + block_chars > _PART_LIMIT:
            parts.append(current)
            current = block
            current_chars = block_chars
        else:
            current += block
            current_chars += block_chars
    if current:
        parts.append(current)
    return parts


def _load_hash_snapshot() -> dict[str, str]:
    """Load the persisted per-file export hashes from the last export run."""
    try:
        if _HASH_SNAPSHOT_PATH.exists():
            return json.loads(_HASH_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Code export | Failed to load hash snapshot (audit will show 'not_exported'): %s", exc)
    return {}


def _save_hash_snapshot(snapshot: dict[str, str]) -> None:
    """Persist the per-file hashes from the current export to disk."""
    try:
        _HASH_SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Code export | Failed to save hash snapshot (audit will be unavailable): %s", exc)


@code_export_router.get("/export/code-parts", tags=["Export"])
async def export_code_parts():
    file_data = _collect_file_data()
    parts = _split_into_parts(file_data)

    export_snapshot: dict[str, str] = {}
    for rel, _raw, block in file_data:
        export_snapshot[rel] = _sha256(block)
    _save_hash_snapshot(export_snapshot)

    result: dict[str, dict] = {}
    for i, part_bytes in enumerate(parts, start=1):
        key = f"p{i}"
        try:
            text = part_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = part_bytes.decode("latin-1")
        result[key] = {
            "filename": f"code-p{i}.txt",
            "text": text,
            "chars": len(text),
            "part": i,
            "total_parts": len(parts),
        }

    return JSONResponse(content=result)


@code_export_router.get("/export/code-audit", tags=["Export"])
async def audit_code_export():
    """
    Compares the SHA-256 of each live file's export representation against the
    SHA-256 stored when /export/code-parts was last called.

    Both live_hash and export_hash are SHA-256 of the full export block for that
    file: `===== FILE: <path> =====\\n` + raw file bytes + `\\n\\n`.  Using the
    same representation for both sides means any change to the file content (or
    its path header) after the last export run will cause a detectable mismatch.

    live_hash   — SHA-256 of the current export block for this file (recomputed now)
    export_hash — SHA-256 of the export block as persisted during the last export

    status values:
      "ok"           — file is unchanged since last export (hashes match)
      "mismatch"     — file has changed since last export (hashes differ)
      "missing"      — file does not exist on disk
      "not_exported" — no export snapshot exists yet; run /export/code-parts first
    """
    saved_snapshot = _load_hash_snapshot()

    findings: list[dict] = []

    for rel in _SOURCE_FILES:
        abs_path = _REPO_ROOT / rel

        if not abs_path.exists():
            findings.append({
                "path": rel,
                "status": "missing",
                "live_hash": None,
                "export_hash": saved_snapshot.get(rel),
            })
            continue

        raw = _read_file_raw(abs_path)
        live_block = _build_export_block(rel, raw)
        live_hash = _sha256(live_block)

        export_hash = saved_snapshot.get(rel)

        if export_hash is None:
            status = "not_exported"
        elif live_hash == export_hash:
            status = "ok"
        else:
            status = "mismatch"

        findings.append({
            "path": rel,
            "status": status,
            "live_hash": live_hash,
            "export_hash": export_hash,
        })

    total = len(findings)
    ok_count = sum(1 for f in findings if f["status"] == "ok")
    missing_count = sum(1 for f in findings if f["status"] == "missing")
    mismatch_count = sum(1 for f in findings if f["status"] == "mismatch")
    not_exported_count = sum(1 for f in findings if f["status"] == "not_exported")

    all_verified = mismatch_count == 0 and missing_count == 0 and not_exported_count == 0

    return JSONResponse(content={
        "summary": {
            "total": total,
            "ok": ok_count,
            "missing": missing_count,
            "mismatches": mismatch_count,
            "not_exported": not_exported_count,
            "all_verified": all_verified,
        },
        "findings": findings,
    })
