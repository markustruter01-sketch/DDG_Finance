"""Admin routes: learning-snapshot, token-usage, LLM cache, risk-profile,
gemini-audit, fleet-commander."""

from __future__ import annotations

import asyncio
import os
import sys

from fastapi import APIRouter, HTTPException, BackgroundTasks
from loguru import logger

from execution.broker import get_account, get_positions
from core.scheduler import get_job_status, get_scheduler

from routes._deps import KRAKEN_BOT_PROFILES

admin_router = APIRouter()


@admin_router.get("/admin/learning-snapshot", tags=["Admin"])
async def get_learning_snapshot_info() -> dict:
    from analysis.learning_snapshot import get_snapshot_info
    return get_snapshot_info()


@admin_router.post("/admin/learning-snapshot/export", tags=["Admin"])
async def export_learning_snapshot(background_tasks: BackgroundTasks) -> dict:
    async def _bg_export():
        try:
            from analysis.learning_snapshot import export_snapshot
            export_snapshot()
        except Exception as exc:
            logger.error(f"Learning Snapshot | Background export failed: {exc}")

    background_tasks.add_task(_bg_export)
    return {
        "status":  "export_started",
        "message": "Snapshot export running — check GET /admin/learning-snapshot in a few seconds",
    }


@admin_router.post("/admin/learning-snapshot/seed", tags=["Admin"])
async def seed_learning_from_snapshot() -> dict:
    from analysis.learning_snapshot import seed_from_snapshot
    return seed_from_snapshot()


@admin_router.get("/admin/token-usage", tags=["Admin"])
async def get_token_usage() -> dict:
    from analysis.groq_budget import budget as _gb
    from analysis.llm_response_cache import llm_cache as _lc
    breakdown = _gb.token_usage_breakdown()
    breakdown["cache_stats"] = _lc.stats()
    return breakdown


@admin_router.post("/admin/llm-cache/invalidate", tags=["Admin"])
async def invalidate_llm_cache() -> dict:
    from analysis.llm_response_cache import llm_cache as _lc
    _lc.invalidate()
    return {"status": "cleared", "message": "LLM response cache invalidated — next cycle will call Groq API"}


@admin_router.get("/admin/risk-profile", tags=["Admin"])
async def get_risk_profile() -> dict:
    _repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from shared.risk_profile import RiskProfile

    SAFE_TICKERS = frozenset({"SGOV", "JEPQ"})

    try:
        account   = get_account()
        equity    = float(account.get("equity", 0.0))
        positions = get_positions()
        deployed  = sum(
            float(p.get("market_value", 0.0))
            for p in (positions or [])
            if p.get("symbol") not in SAFE_TICKERS
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch Alpaca account: {exc}")

    rp = RiskProfile(
        total_equity=equity,
        deployed_usd=max(deployed, 0.0),
        ring_fenced_pct=0.60,
        deployable_pct=0.40,
        max_position_pct=0.15,
        daily_loss_limit_pct=0.05,
        reserve_pct=0.18,
        name="alpaca",
    )
    return rp.to_dict()


@admin_router.get("/admin/gemini-audit-status", tags=["Admin"])
async def get_gemini_audit_status() -> dict:
    from analysis.gemini_auditor import get_last_gemini_audit
    from core.veto_enforcer import get_veto_status

    result = get_last_gemini_audit()
    veto_status = get_veto_status()
    result["veto_status"] = veto_status
    result["veto_count"]  = veto_status.get("active_veto_count", 0)
    result["last_run"]    = result.get("generated_at")
    return result


@admin_router.post("/admin/gemini-audit/run", tags=["Admin"])
async def trigger_gemini_audit(background_tasks: BackgroundTasks) -> dict:
    from analysis.gemini_auditor import run_daily_self_critic

    async def _bg():
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_daily_self_critic)
        logger.info(f"Manual Gemini audit complete: {result}")

    background_tasks.add_task(_bg)
    return {
        "status":  "triggered",
        "message": "Gemini self-critic auditor started — poll GET /admin/gemini-audit-status for results",
    }


@admin_router.get("/admin/fleet-commander/status", tags=["Admin"])
async def get_fleet_commander_status() -> dict:
    from analysis.fleet_commander import get_last_fleet_audit, get_token_usage
    from core.veto_enforcer import get_veto_status

    result = get_last_fleet_audit()
    result["token_usage_today"] = get_token_usage()
    result["veto_status"] = get_veto_status()

    scheduler = get_scheduler()
    fc_jobs = [j for j in scheduler.get_jobs() if j.id.startswith("fleet_commander_")]
    next_runs = []
    for j in fc_jobs:
        next_runs.append({
            "id": j.id,
            "name": j.name,
            "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
        })
    result["scheduled_runs"] = sorted(next_runs, key=lambda x: x.get("next_run") or "")
    return result


@admin_router.get("/admin/fleet-commander/history", tags=["Admin"])
async def get_fleet_commander_history() -> dict:
    from analysis.fleet_commander import get_fleet_audit_history
    history = get_fleet_audit_history()
    return {"history": history, "count": len(history)}


@admin_router.post("/admin/fleet-commander/run", tags=["Admin"])
async def trigger_fleet_commander(background_tasks: BackgroundTasks) -> dict:
    from analysis.fleet_commander import run_fleet_commander

    async def _bg():
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_fleet_commander)
        logger.info(f"Manual Fleet Commander run complete: {result.get('overall_verdict', 'N/A')}")

    background_tasks.add_task(_bg)
    return {
        "status": "triggered",
        "message": "Fleet Commander audit started — poll GET /admin/fleet-commander/status for results",
    }


@admin_router.get("/admin/micro-auditor/status", tags=["Admin"])
async def get_micro_auditor_status() -> dict:
    import json
    from pathlib import Path
    audit_file = Path(__file__).parent.parent / "logs" / "micro_audit.json"
    if audit_file.exists():
        try:
            return json.loads(audit_file.read_text())
        except Exception:
            pass
    return {"status": "no_data", "alerts": [], "alert_count": 0}


@admin_router.get("/admin/micro-auditor/history", tags=["Admin"])
async def get_micro_auditor_history() -> dict:
    import json
    from pathlib import Path
    history_file = Path(__file__).parent.parent / "logs" / "micro_audit_history.json"
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
            return {"history": history, "count": len(history)}
        except Exception:
            pass
    return {"history": [], "count": 0}



@admin_router.get("/admin/oracle/scan-log", tags=["Admin"])
async def get_oracle_scan_log(limit: int = 20) -> dict:
    """
    Return the last N oracle_scan_log rows — one row per momentum scan cycle.
    Shows per-filter-stage counts to diagnose zero-signal cycles.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return {"status": "unavailable", "rows": [], "count": 0}
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, ts AT TIME ZONE 'UTC' AS ts,
                        universe_loaded, with_data, passed_score,
                        passed_rsi, passed_ema, long_signals, short_signals,
                        top5_long, top5_short, scan_note
                    FROM oracle_scan_log
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    (min(limit, 200),),
                )
                cols = [desc[0] for desc in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                for row in rows:
                    if row.get("ts"):
                        row["ts"] = str(row["ts"])
        return {"status": "ok", "rows": rows, "count": len(rows)}
    except Exception as exc:
        logger.error(f"Admin | oracle scan-log query failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@admin_router.post("/admin/micro-auditor/run", tags=["Admin"])
async def trigger_micro_auditor(background_tasks: BackgroundTasks) -> dict:
    from analysis.micro_auditor import run_micro_audit

    async def _bg():
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_micro_audit)
        logger.info(f"Manual MicroAuditor run complete: {result.get('alert_count', 0)} alerts")

    background_tasks.add_task(_bg)
    return {
        "status": "triggered",
        "message": "Micro-Auditor check started — poll GET /admin/micro-auditor/status for results",
    }
