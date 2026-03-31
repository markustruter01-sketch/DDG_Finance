"""
Trading Platform — FastAPI Application
----------------------------------------
Serves as both the HTTP API and the host for the APScheduler background jobs.

Endpoints:
  GET  /health              — Liveness probe + system health status
  GET  /status              — Full platform state (scheduler, kill switch, last run)
  GET  /portfolio           — Live Alpaca account + open positions
  GET  /positions/live      — Live positions enriched with allocation entry conditions
  GET  /journal             — Trade journal summary
  GET  /journal/losses      — Recent losses (the RAG loss feedback window)
  GET  /journal/wins        — Recent wins (the RAG win feedback window)
  GET  /performance         — Full daily performance snapshot history
  GET  /performance/summary — Aggregate performance statistics
  POST /run                 — Manually trigger a full pipeline cycle
  POST /run/postmortem      — Manually trigger the post-mortem reconciliation
  POST /kill                — Manually trip the kill switch
  POST /kill/reset          — Reset the kill switch for a new day
  GET  /auditor/report      — Latest HITL audit report (JSON)
  POST /auditor/run         — Manually trigger a full audit cycle
  POST /rebalance           — Force close sellable positions + run fresh pipeline
  GET  /docs                — Auto-generated Swagger UI (FastAPI default)
"""

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, APIRouter
from pydantic import BaseModel
from loguru import logger

# ── Shared core library ────────────────────────────────────────────────────────
# Both bots (Alpaca + Kraken) share RiskProfile, ExitBracket, CircuitBreaker
# from the repo-root shared/ package.
_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config.settings import settings
from core.pipeline import get_last_run, run_pipeline, run_postmortem, reset_error_state
from core.scheduler import get_job_status, get_scheduler, is_auto_trading_enabled, set_auto_trading
from execution.broker import get_account, get_positions, get_open_orders, close_position, close_position_gtc, cancel_all_orders
from execution.kill_switch import (
    get_state as ks_get_state,
    is_tripped,
    reset as ks_reset,
    check as ks_check,
    manual_trip as ks_manual_trip,
    set_pending_liquidation,
    is_pending_liquidation,
)
from analysis.trade_journal import (
    get_journal_summary,
    get_recent_losses,
    get_recent_wins,
    get_all_trades,
    get_performance_snapshots,
    get_performance_summary,
    get_recent_trades_combined,
    init_db,
)
from core.market_clock import is_market_open, get_next_open
from data.cache import get_cache_stats
from analysis.auditor import run_full_audit, get_last_audit, run_performance_analysis, get_last_performance_report
from analysis.schemas import is_crypto_pair
from execution.ratchet_stop import delete_stop
from data.sentiment import get_sentiment, get_sentiment_prompt_block
from data.onchain import get_onchain_data, get_onchain_prompt_block
from data.economic_calendar import is_blackout_active, get_upcoming_events
from analysis.attribution import compute_attribution
from analysis.backtester import run_backtest

EXPECTED_JOB_COUNT = 8  # 5 trading jobs (scheduler.py) + 3 startup jobs (auto_heal, learning_snapshot, equity_heartbeat)
COMMENTARY_TTL_SECONDS = 1800  # 30-minute cache

_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}
_kraken_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}

# ── Commentary Cache Persistence ──────────────────────────────────────────────
# Both commentary caches are file-backed so they survive server restarts.
# Without this, every restart immediately burns Groq tokens to regenerate.
import json as _json
import threading as _ct_lock
from pathlib import Path as _Path

_COMMENTARY_CACHE_FILE = _Path("data/commentary_cache.json")
_commentary_file_lock = _ct_lock.Lock()


def _load_commentary_caches() -> None:
    """Load both commentary caches from disk on startup."""
    global _commentary_cache, _kraken_commentary_cache
    if not _COMMENTARY_CACHE_FILE.exists():
        return
    try:
        data = _json.loads(_COMMENTARY_CACHE_FILE.read_text())
        alpaca = data.get("alpaca", {})
        kraken = data.get("kraken", {})
        if alpaca.get("text") and alpaca.get("ts", 0) > 0:
            _commentary_cache = alpaca
            age_min = (time.time() - alpaca["ts"]) / 60
            logger.info(f"Commentary cache | Alpaca: loaded from disk ({age_min:.0f}min old)")
        if kraken.get("text") and kraken.get("ts", 0) > 0:
            _kraken_commentary_cache = kraken
            age_min = (time.time() - kraken["ts"]) / 60
            logger.info(f"Commentary cache | Kraken: loaded from disk ({age_min:.0f}min old)")
    except Exception as exc:
        logger.warning(f"Commentary cache | Failed to load from disk: {exc}")


def _persist_commentary_caches() -> None:
    """Atomically write both commentary caches to disk (thread-safe)."""
    try:
        _COMMENTARY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "alpaca": _commentary_cache,
            "kraken": _kraken_commentary_cache,
        }
        tmp = str(_COMMENTARY_CACHE_FILE) + ".tmp"
        with _commentary_file_lock:
            with open(tmp, "w") as f:
                _json.dump(payload, f, indent=2)
            os.replace(tmp, str(_COMMENTARY_CACHE_FILE))
    except Exception as exc:
        logger.warning(f"Commentary cache | Failed to persist to disk: {exc}")


# ── Self-Healing Remediation Log ──────────────────────────────────────────────
import threading as _threading

_heal_log: list[dict] = []
_heal_lock = _threading.Lock()


def _add_heal_entry(component: str, action: str, result: str, success: bool, triggered_by: str = "manual") -> dict:
    entry = {
        "ts": time.time(),
        "component": component,
        "action": action,
        "result": result,
        "success": success,
        "triggered_by": triggered_by,
    }
    with _heal_lock:
        _heal_log.insert(0, entry)
        while len(_heal_log) > 50:
            _heal_log.pop()
    return entry


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.add(
        settings.log_file,
        level=settings.log_level,
        rotation="1 day",
        retention="30 days",
        compression="gz",
        enqueue=True,
    )
    logger.info("=" * 60)
    logger.info("TRADING PLATFORM STARTING")
    logger.info("=" * 60)

    init_db()
    logger.info("Trade journal database initialised")

    # ── Seed learning from snapshot if this is a fresh/empty database ─────────
    try:
        from analysis.learning_snapshot import seed_from_snapshot
        seed_result = seed_from_snapshot()
        if seed_result["seeded"]:
            logger.success(
                f"Learning Snapshot | Seeded DB with {seed_result['rows_inserted']} "
                "llm_learnings rows from committed snapshot"
            )
        elif seed_result.get("rows_inserted", 0) == 0:
            logger.debug(f"Learning Snapshot | Seed skipped: {seed_result.get('reason', 'unknown')}")
    except Exception as _se:
        logger.warning(f"Learning Snapshot | Startup seed failed (non-fatal): {_se}")

    _load_commentary_caches()
    logger.info("Commentary caches loaded from disk")

    scheduler = get_scheduler()
    scheduler.start()
    logger.info(f"Scheduler started — {len(scheduler.get_jobs())} trading jobs registered (auto-trading ON by default)")
    logger.info("Disable auto-trading via dashboard toggle or POST /auto-trading")
    logger.info("24/7 crypto trading enabled — crypto cycles fire when stock market is closed")

    # Register the auto-heal monitor — always active regardless of auto-trading toggle
    from apscheduler.triggers.interval import IntervalTrigger as _ITrigger
    scheduler.add_job(
        func=_auto_heal_check,
        trigger=_ITrigger(minutes=2),
        id="auto_heal",
        name="Auto Self-Heal Monitor",
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info("Auto-heal monitor registered (2-min interval, always active — not paused by auto-trading toggle)")

    # ── Auto-export learning snapshot every 6 hours ───────────────────────────
    def _scheduled_snapshot_export():
        try:
            from analysis.learning_snapshot import export_snapshot
            export_snapshot()
        except Exception as _ex:
            logger.warning(f"Learning Snapshot | Scheduled export failed: {_ex}")

    scheduler.add_job(
        func=_scheduled_snapshot_export,
        trigger=_ITrigger(hours=6),
        id="learning_snapshot_export",
        name="Learning Snapshot Auto-Export",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Learning snapshot auto-export registered (6-hour interval)")

    # ── Equity Curve: seed on startup + record every hour ─────────────────────
    async def _record_equity_snapshot_now():
        """Record the current Alpaca + Kraken equity into the equity_snapshots table."""
        from db.postgres import insert_equity_snapshot
        try:
            acct = get_account()
            alpaca_eq = float(acct.get("equity", 0))
        except Exception:
            alpaca_eq = 0.0
        try:
            import json as _json
            from pathlib import Path as _Path
            _status_file = _Path("../kraken-bot/status.json")
            if _status_file.exists():
                _ks = _json.loads(_status_file.read_text())
                kraken_eq = float(_ks.get("total_equity_usd", 0))
            else:
                kraken_eq = 0.0
        except Exception:
            kraken_eq = 0.0
        insert_equity_snapshot(alpaca_eq, kraken_eq, "LIVE", "hourly_heartbeat")

    def _equity_heartbeat_sync():
        import asyncio as _aio
        try:
            loop = _aio.get_event_loop()
            if loop.is_running():
                loop.create_task(_record_equity_snapshot_now())
            else:
                loop.run_until_complete(_record_equity_snapshot_now())
        except Exception as _e:
            logger.warning(f"Equity Heartbeat | Failed: {_e}")

    # Seed on startup only if the table is empty (avoids duplicate on every reload)
    try:
        from db.postgres import get_equity_curve as _gec
        if not _gec(limit=1):
            await _record_equity_snapshot_now()
            logger.info("Equity Curve | Startup snapshot seeded (table was empty)")
        else:
            logger.debug("Equity Curve | Table already has data — skipping startup seed")
    except Exception as _ese:
        logger.warning(f"Equity Curve | Startup seed failed (non-fatal): {_ese}")

    scheduler.add_job(
        func=_equity_heartbeat_sync,
        trigger=_ITrigger(hours=1),
        id="equity_curve_heartbeat",
        name="Equity Curve Hourly Heartbeat",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Equity curve heartbeat registered (1-hour interval)")

    yield

    logger.info("Shutting down scheduler...")
    scheduler.shutdown(wait=False)
    logger.info("Trading platform stopped.")


# ── App ────────────────────────────────────────────────────────────────────────

API_PREFIX = os.getenv("API_PREFIX", "")

app = FastAPI(
    title="AI Quantitative Trading Platform",
    description=(
        "AI-driven macro quant trading system. "
        "FRED macro + Alpaca market data + NewsAPI → "
        "Groq LLM (Llama 3.3 70B) → Kelly-sized 10-slot allocation → "
        "Alpaca paper trading execution."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

router = APIRouter(prefix=API_PREFIX)


# ── Degradation capture middleware ────────────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

_DEGRADATION_ENDPOINTS = {
    "/ai/commentary", "/kraken/commentary", "/kraken/status",
    "/kraken/performance", "/kraken/trades",
    "/run", "/run/postmortem", "/status", "/health",
    "/positions/live", "/portfolio",
}


class DegradationCaptureMiddleware(BaseHTTPMiddleware):
    """Silently records HTTP 500/503 responses to the degradation log."""

    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        response = await call_next(request)
        if response.status_code in (500, 503):
            path = request.url.path
            # Only track our own trading-api routes
            if API_PREFIX in path:
                short_path = path.replace(API_PREFIX, "")
                relevant = any(short_path.startswith(ep) for ep in _DEGRADATION_ENDPOINTS)
                if relevant:
                    try:
                        from core.degradation_tracker import record_degradation
                        record_degradation(
                            component="http",
                            severity="error",
                            error_type=str(response.status_code),
                            message=f"HTTP {response.status_code} on {short_path}",
                            detail=f"method={request.method} full_path={path}",
                        )
                    except Exception:
                        pass
        return response


app.add_middleware(DegradationCaptureMiddleware)


# ── Request / Response models ─────────────────────────────────────────────────

class RunRequest(BaseModel):
    dry_run: bool = False
    force: bool = False
    crypto_only: bool = False


class KillResetRequest(BaseModel):
    opening_equity: float | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health", tags=["System"])
async def health() -> dict:
    """
    Liveness probe + structured system health.

    system_status:
      'online'   — scheduler has all expected jobs, last run did not error
      'degraded' — scheduler missing jobs OR last run errored
      'offline'  — server just started (no runs yet) but jobs are present
    """
    jobs = get_job_status()
    last = get_last_run()

    job_count = len(jobs)
    last_status = last.get("last_run_status", "never")
    error_count = last.get("error_count", 0)

    if job_count < EXPECTED_JOB_COUNT:
        system_status = "degraded"
        status_reason = f"Only {job_count}/{EXPECTED_JOB_COUNT} scheduler jobs registered"
    elif last_status in ("error", "analysis_failed", "execution_failed", "kill_switch_tripped"):
        system_status = "degraded"
        status_reason = f"Last run failed ({error_count} total errors)"
    elif last_status in ("never", "never_run"):
        system_status = "online"
        status_reason = "Scheduler running — no analysis run yet today"
    else:
        system_status = "online"
        status_reason = "All systems operational"

    return {
        "status": "ok",
        "version": "3.0.0",
        "system_status": system_status,
        "status_reason": status_reason,
        "scheduler_job_count": job_count,
        "last_run_status": last_status,
        "error_count": error_count,
    }


def _get_signal_guard_status() -> dict | None:
    try:
        from analysis.signal_guard import get_last_guard_result
        return get_last_guard_result()
    except Exception:
        return None


@router.get("/status", tags=["System"])
async def status() -> dict:
    """
    Full platform status snapshot:
    market clock, kill switch, scheduler jobs, last pipeline run, cache stats,
    and Groq regime cache status.
    """
    from analysis.analyzer import get_groq_status as _get_groq_status
    from analysis.groq_budget import budget as _groq_budget
    market_open = is_market_open()
    last_run = get_last_run()
    if not is_auto_trading_enabled():
        trading_mode = "idle"
    elif market_open:
        trading_mode = "full_market"
    else:
        trading_mode = "crypto_only"
    groq_status = _get_groq_status()
    groq_status["using_fallback"] = last_run.get("groq_using_fallback", False)
    groq_status.update(_groq_budget.budget_status())
    return {
        "market": {
            "is_open":   market_open,
            "next_open": get_next_open() if not market_open else None,
        },
        "kill_switch":    ks_get_state(),
        "scheduler_jobs": get_job_status(),
        "last_run":       last_run,
        "auto_trading":   is_auto_trading_enabled(),
        "cycle_interval": last_run.get("cycle_interval", "15min"),
        "trading_mode":   trading_mode,
        "data_cache":     get_cache_stats(),
        "blackout":       is_blackout_active(),
        "groq":           groq_status,
        "signal_guard":   _get_signal_guard_status(),
    }


@router.get("/system/health-architecture", tags=["System"])
async def system_health_architecture() -> dict:
    """
    Real-time health metrics for all platform subsystems.
    Powers the System Health Architecture diagram on the dashboard.

    Checks: platform core, Alpaca API, Kraken bot, data pipeline, equity manager.
    """
    import json as _json, time as _time
    from pathlib import Path as _Path

    now = _time.time()
    nodes: dict[str, dict] = {}

    # ── 1. Platform Core ────────────────────────────────────────────────
    try:
        jobs = get_job_status()
        last = get_last_run()
        job_count = len(jobs)
        last_status = last.get("last_run_status", "never")
        last_ts = last.get("last_run_timestamp")
        age_s = (now - last_ts) if last_ts else None
        latency_ms = 0
        _mkt_open_h = False
        try:
            _mkt_open_h = is_market_open()
        except Exception:
            pass
        _groq_exhausted_h = False
        try:
            from analysis.groq_budget import budget as _gb_h
            _groq_exhausted_h = _gb_h.budget_exhausted()
        except Exception:
            pass
        if job_count < EXPECTED_JOB_COUNT:
            level = "red"          # Missing jobs = always critical
        elif last_status in ("error", "execution_failed"):
            level = "red"          # Hard failures = always critical
        elif last_status == "analysis_failed":
            # If Groq budget is exhausted, analysis_failed is expected even during market hours
            if _groq_exhausted_h:
                level = "yellow"   # Budget exhausted — will auto-recover at midnight UTC
            else:
                level = "red" if _mkt_open_h else "yellow"
        else:
            level = "green"
        nodes["platform_core"] = {
            "label": "Main Platform Core",
            "level": level,
            "latency_ms": latency_ms,
            "data_age_s": round(age_s, 1) if age_s else None,
            "detail": f"{job_count}/{EXPECTED_JOB_COUNT} jobs · last: {last_status}",
        }
    except Exception as exc:
        nodes["platform_core"] = {"label": "Main Platform Core", "level": "red", "latency_ms": None, "data_age_s": None, "detail": str(exc)}

    # ── 2. Alpaca API ───────────────────────────────────────────────────
    _acct_cache: dict | None = None
    try:
        t0 = _time.time()
        _acct_cache = get_account()  # returns dict: {"equity": float, "cash": float, ...}
        latency = round((_time.time() - t0) * 1000)
        if latency > 1000:
            level = "red"
        elif latency > 200:
            level = "yellow"
        else:
            level = "green"
        nodes["alpaca_api"] = {
            "label": "Alpaca API (US Equities)",
            "level": level,
            "latency_ms": latency,
            "data_age_s": 0,
            "detail": f"Equity ${_acct_cache['equity']:,.2f}",
        }
    except Exception as exc:
        nodes["alpaca_api"] = {"label": "Alpaca API (US Equities)", "level": "red", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # ── 3. Kraken Bot ───────────────────────────────────────────────────
    try:
        sf = _Path("../kraken-bot/status.json")  # server cwd = trading-platform/
        if sf.exists():
            kst = _json.loads(sf.read_text())
            last_upd = kst.get("last_updated")
            if last_upd:
                from datetime import datetime as _dt, timezone as _tz
                kage = now - _dt.fromisoformat(last_upd).timestamp()
            else:
                kage = None
            kstatus = kst.get("status", "unknown")
            _mkt_open_kr = False
            try:
                _mkt_open_kr = is_market_open()
            except Exception:
                pass
            # After hours: stale bot is expected (Replit slows overnight).
            # Cap at yellow after hours — only escalate to red during market hours.
            if kstatus in ("error",):
                level = "red"
            elif kage and kage > 1800:
                level = "red" if _mkt_open_kr else "yellow"
            elif kstatus == "paused_circuit_breaker" or kstatus == "paused_dashboard" or (kage and kage > 600):
                level = "yellow"
            else:
                level = "green"
            nodes["kraken_api"] = {
                "label": "Kraken API (Crypto Bot)",
                "level": level,
                "latency_ms": None,
                "data_age_s": round(kage, 1) if kage else None,
                "detail": f"Status: {kstatus} · Cycle #{kst.get('cycle_count', 0)}",
            }
        else:
            nodes["kraken_api"] = {"label": "Kraken API (Crypto Bot)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": "Bot not started"}
    except Exception as exc:
        nodes["kraken_api"] = {"label": "Kraken API (Crypto Bot)", "level": "red", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # ── 4. Data Pipeline ────────────────────────────────────────────────
    try:
        caches = get_cache_stats()
        cached_count = sum(1 for c in caches if c.get("cached"))
        ages = [c["age_seconds"] for c in caches if c.get("cached") and c["age_seconds"] >= 0]
        oldest = max(ages) if ages else None
        # Thresholds account for the 15-min (900s) intraday cycle:
        # red  = >1800s (missed 2 full cycles — something is broken)
        # yellow = >900s (one full cycle stale — expected off-hours or between cycles)
        # During off-hours the pipeline is always stale; cap at yellow, not red.
        _mkt_open_dp = False
        try:
            _mkt_open_dp = is_market_open()
        except Exception:
            pass
        if oldest is not None and oldest > 1800 and _mkt_open_dp:
            level = "red"
        elif oldest is not None and oldest > 900:
            level = "yellow"
        elif cached_count == 0:
            level = "yellow"
        else:
            level = "green"
        nodes["data_pipeline"] = {
            "label": "Data Pipeline (fetch_data)",
            "level": level,
            "latency_ms": None,
            "data_age_s": round(oldest, 1) if oldest else None,
            "detail": f"{cached_count}/{len(caches)} feeds cached" if cached_count else "No data cached yet",
        }
    except Exception as exc:
        nodes["data_pipeline"] = {"label": "Data Pipeline (fetch_data)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # ── 5. Equity Manager ───────────────────────────────────────────────
    try:
        positions = get_positions()  # list of dicts
        # reuse cached account from the Alpaca check to avoid a second round-trip
        acct_dict = _acct_cache if _acct_cache is not None else get_account()
        equity_val = float(acct_dict["equity"])
        total_market = sum(float(p["market_value"]) for p in positions) if positions else 0
        # SGOV = AI-designated cash-equivalent / safe-haven (can be 100% of portfolio by design)
        # JEPQ = profit-sweep DRIP vault (exempt from position-size limits)
        # Neither counts toward the 15% active-position cap.
        _EXEMPT_SYMBOLS = {"SGOV", "JEPQ"}
        active_positions = [p for p in positions if p.get("symbol", "") not in _EXEMPT_SYMBOLS]
        max_single = max((float(p["market_value"]) for p in active_positions), default=0)
        # Guard: if equity is trivially small (<$100) or there are no active positions,
        # percentage math is meaningless — report green and skip the check.
        if len(active_positions) == 0 or equity_val < 100:
            level = "green"
            max_pct = 0.0
        else:
            max_pct = (max_single / equity_val * 100) if equity_val > 0 else 0
            if max_pct > 15.0:
                level = "red"
            elif max_pct > 12.0:
                level = "yellow"
            else:
                level = "green"
        _exempt_count = len(positions) - len(active_positions)
        _detail_parts = [f"Max active position: {max_pct:.1f}%", f"{len(active_positions)} active holding(s)"]
        if _exempt_count:
            _detail_parts.append(f"{_exempt_count} exempt (SGOV/JEPQ vault)")
        nodes["equity_manager"] = {
            "label": "Equity Manager (15% Enforcer)",
            "level": level,
            "latency_ms": None,
            "data_age_s": 0,
            "detail": " · ".join(_detail_parts),
        }
    except Exception as exc:
        nodes["equity_manager"] = {"label": "Equity Manager (15% Enforcer)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # ── 6. RAG Learning Engine ───────────────────────────────────────────
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Count post-mortems (Phase 2 lessons)
                cur.execute("SELECT COUNT(*) FROM execution_post_mortems")
                pm_count = cur.fetchone()[0]
                # Count active permanent rules (Phase 4)
                cur.execute("SELECT COUNT(*) FROM hardcoded_rules WHERE active = TRUE")
                rule_count = cur.fetchone()[0]
                # Count pending patterns (losses that haven't hit threshold yet)
                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT ticker, regime, exit_reason
                        FROM execution_post_mortems
                        WHERE pnl_pct < 0
                        GROUP BY ticker, regime, exit_reason
                        HAVING COUNT(*) BETWEEN 1 AND 2
                    ) sub
                """)
                pending_count = cur.fetchone()[0]
        if pm_count == 0:
            level = "yellow"
            detail = f"No post-mortems yet · {rule_count} rules · awaiting first loss cycle"
        else:
            level = "green"
            detail = f"{pm_count} post-mortems · {rule_count} permanent rules · {pending_count} patterns pending"
        nodes["rag_engine"] = {
            "label": "RAG Learning Engine (4-Phase)",
            "level": level,
            "latency_ms": None,
            "data_age_s": None,
            "detail": detail,
        }
    except Exception as exc:
        nodes["rag_engine"] = {
            "label": "RAG Learning Engine (4-Phase)",
            "level": "red",
            "latency_ms": None,
            "data_age_s": None,
            "detail": f"DB error: {str(exc)[:70]}",
        }

    return {
        "timestamp": now,
        "nodes": nodes,
    }


# ── Self-Healing Remediation Engine ──────────────────────────────────────────

async def _remediate_component(component: str, triggered_by: str = "manual") -> dict:
    """Execute targeted remediation for a platform component and log the result."""
    import json as _json
    from pathlib import Path as _Path

    steps: list[str] = []
    success = True

    try:
        if component == "platform_core":
            new_state = reset_error_state()
            steps.append(f"Error state reset → {new_state.get('last_run_status', '?')}")
            try:
                import data.yfinance_client as _yf
                _yf._cached_market_data = None
                steps.append("Market data cache cleared")
            except Exception as exc:
                steps.append(f"Cache clear warning: {exc}")
            _commentary_cache.update({"text": None, "generated_at": None, "ts": 0})
            steps.append("AI commentary cache cleared")
            jobs = get_job_status()
            steps.append(f"Scheduler active with {len(jobs)} job(s)")

        elif component == "data_pipeline":
            from data.cache import invalidate_all
            invalidate_all()
            steps.append("FRED macro + NewsAPI caches invalidated")
            try:
                import data.yfinance_client as _yf
                _yf._cached_market_data = None
                steps.append("yfinance market data cache cleared")
            except Exception as exc:
                steps.append(f"yfinance warning: {exc}")
            steps.append("Fresh data will load on next cycle")

        elif component == "kraken_api":
            sf = _Path("../kraken-bot/status.json")
            if sf.exists():
                import os as _os
                _raw = sf.read_text()
                try:
                    kst = _json.loads(_raw)
                    kst["heal_requested"] = True
                    kst["heal_requested_at"] = time.time()
                    # Atomic write: use a distinct .heal.tmp path so we never
                    # race with the bot's own status.json.tmp write.
                    _tmp = str(sf) + ".heal.tmp"
                    _Path(_tmp).write_text(_json.dumps(kst, indent=2))
                    _os.replace(_tmp, str(sf))
                    steps.append(f"Heal flag written to status.json (cycle #{kst.get('cycle_count', 0)})")
                except _json.JSONDecodeError as exc:
                    # status.json is corrupt — delete it so the bot regenerates
                    # a fresh copy on its very next write_status() call.
                    try:
                        sf.unlink()
                        steps.append(f"Corrupt status.json deleted — bot will regenerate ({exc})")
                    except Exception as del_exc:
                        steps.append(f"Corrupt file could not be removed: {del_exc}")
                    success = False
            else:
                steps.append("status.json not found — start Davy Jones bot first")
            _kraken_commentary_cache.update({"text": None, "generated_at": None, "ts": 0})
            steps.append("Kraken commentary cache cleared")

        elif component == "alpaca_api":
            try:
                t0 = time.time()
                acct = get_account()
                latency = round((time.time() - t0) * 1000)
                steps.append(f"API reachable — {latency}ms, equity ${float(acct['equity']):,.0f}")
            except Exception as exc:
                steps.append(f"Reconnect failed: {str(exc)[:80]}")
                success = False

        elif component == "equity_manager":
            try:
                positions = get_positions()
                acct = get_account()
                equity_val = float(acct["equity"])
                max_pct = max(
                    (float(p["market_value"]) / equity_val * 100 for p in positions),
                    default=0.0,
                )
                steps.append(f"Max position at {max_pct:.1f}% — rebalance queued for next cycle")
                steps.append(f"{len(positions)} position(s) reviewed")
            except Exception as exc:
                steps.append(f"Review failed: {str(exc)[:80]}")
                success = False

        else:
            result_str = f"Unknown component: {component}"
            entry = _add_heal_entry(component, "remediate", result_str, False, triggered_by)
            return {"component": component, "success": False, "result": result_str, "ts": entry["ts"]}

    except Exception as exc:
        steps.append(f"Unexpected error: {str(exc)[:100]}")
        success = False

    result_str = " · ".join(steps) if steps else "No action taken"
    logger.info(f"[HEAL] component={component} by={triggered_by} ok={success} | {result_str}")
    entry = _add_heal_entry(component, f"remediate_{component}", result_str, success, triggered_by)
    return {"component": component, "success": success, "result": result_str, "ts": entry["ts"]}


async def _auto_heal_check() -> None:
    """
    Background monitor — runs every 2 minutes.
    Auto-heals critical trading faults when they are detected.
    NOT paused by the auto-trading toggle — always active.
    """
    import json as _json
    from pathlib import Path as _Path

    now = time.time()
    logger.debug("[AUTO-HEAL] Running health check…")

    from core.degradation_tracker import record_degradation, mark_resolved

    # ── 1. Platform core ────────────────────────────────────────────────────
    try:
        jobs = get_job_status()
        last = get_last_run()
        last_status = last.get("last_run_status", "never")
        _mkt_open = False
        try:
            _mkt_open = is_market_open()
        except Exception:
            pass

        _degraded = False
        _severity = "warning"
        if len(jobs) < EXPECTED_JOB_COUNT:
            # Missing scheduler jobs is always CRITICAL regardless of market hours
            _degraded = True
            _severity = "critical"
        elif last_status in ("error", "execution_failed"):
            # Hard errors / execution failures are always CRITICAL at any hour
            _degraded = True
            _severity = "critical"
        elif last_status == "analysis_failed":
            # analysis_failed off-hours is expected (Alpaca/yfinance unavailable);
            # only escalate to CRITICAL when the market is open AND Groq budget is not exhausted.
            # If the budget is exhausted, analysis_failed is expected — treat as warning.
            _groq_exhausted_ah = False
            try:
                from analysis.groq_budget import budget as _gb_ah
                _groq_exhausted_ah = _gb_ah.budget_exhausted()
            except Exception:
                pass
            _degraded = True
            if _groq_exhausted_ah or not _mkt_open:
                _severity = "warning"   # expected: budget exhausted or market closed
            else:
                _severity = "critical"  # genuine failure during market hours

        if _degraded:
            logger.warning(f"[AUTO-HEAL] platform_core {_severity}: {len(jobs)} jobs, last_status={last_status}, market_open={_mkt_open}")
            record_degradation(
                component="platform_core",
                severity=_severity,
                error_type=last_status if last_status != "never" else "missing_jobs",
                message=f"Platform core degraded: {len(jobs)}/{EXPECTED_JOB_COUNT} scheduler jobs, last_status={last_status}",
            )
            await _remediate_component("platform_core", triggered_by="auto_heal")
        else:
            mark_resolved("platform_core", "analysis_failed")
            mark_resolved("platform_core", "execution_failed")
    except Exception as exc:
        logger.debug(f"[AUTO-HEAL] platform_core check skipped: {exc}")

    # ── 2. Data pipeline — stale feeds > 20 min (1200s) ─────────────────────
    # Threshold is 1200s (2x the 15-min intraday cycle) so normal between-cycle
    # staleness doesn't generate noise.  Off-hours staleness is expected and
    # is only flagged if the market is open and data is >20 min stale.
    try:
        from data.cache import get_cache_stats as _gcs
        caches = _gcs()
        ages = [c["age_seconds"] for c in caches if c.get("cached") and c["age_seconds"] >= 0]
        max_age = max(ages) if ages else 0
        _mkt_open_dp2 = False
        try:
            _mkt_open_dp2 = is_market_open()
        except Exception:
            pass
        if ages and max_age > 1200 and _mkt_open_dp2:
            logger.warning(f"[AUTO-HEAL] data_pipeline stale: max_age={max_age:.0f}s")
            record_degradation(
                component="data_pipeline",
                severity="warning",
                error_type="stale",
                message=f"Data pipeline cache stale: oldest feed is {max_age:.0f}s old (threshold 1200s)",
            )
            await _remediate_component("data_pipeline", triggered_by="auto_heal")
        else:
            mark_resolved("data_pipeline", "stale")
    except Exception as exc:
        logger.debug(f"[AUTO-HEAL] data_pipeline check skipped: {exc}")

    # ── 3. Kraken bot — status file older than 30 min (1800s) or error state ──
    try:
        sf = _Path("../kraken-bot/status.json")
        if sf.exists():
            kst = _json.loads(sf.read_text())
            last_upd = kst.get("last_updated")
            if last_upd:
                from datetime import datetime as _dt
                kage = now - _dt.fromisoformat(last_upd).timestamp()
                kstatus = kst.get("status", "unknown")
                if kstatus == "error" or kage > 1800:
                    logger.warning(f"[AUTO-HEAL] kraken_api stale/error: status={kstatus}, age={kage:.0f}s")
                    record_degradation(
                        component="kraken_api",
                        severity="critical" if kstatus == "error" else "warning",
                        error_type="error_state" if kstatus == "error" else "stale",
                        message=f"Kraken bot {kstatus}: status file is {kage:.0f}s old (threshold 1800s)",
                        detail=f"status.json last_updated={last_upd}, bot_status={kstatus}",
                    )
                    await _remediate_component("kraken_api", triggered_by="auto_heal")
                else:
                    mark_resolved("kraken_api", "stale")
                    mark_resolved("kraken_api", "error_state")
    except Exception as exc:
        logger.debug(f"[AUTO-HEAL] kraken_api check skipped: {exc}")


@router.post("/system/remediate/{component}", tags=["System"])
async def remediate_component(component: str) -> dict:
    """
    Self-heal a specific platform component.

    Components: platform_core | data_pipeline | kraken_api | alpaca_api | equity_manager
    """
    valid = {"platform_core", "data_pipeline", "kraken_api", "alpaca_api", "equity_manager"}
    if component not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown component. Valid: {', '.join(sorted(valid))}")
    return await _remediate_component(component, triggered_by="manual")


@router.post("/system/remediate/all", tags=["System"])
async def remediate_all() -> dict:
    """Run remediation across all components in sequence."""
    components = ["platform_core", "data_pipeline", "kraken_api", "alpaca_api", "equity_manager"]
    results = []
    for comp in components:
        r = await _remediate_component(comp, triggered_by="heal_all")
        results.append(r)
    all_ok = all(r["success"] for r in results)
    return {"success": all_ok, "results": results, "healed_count": sum(1 for r in results if r["success"])}


@router.get("/system/remediate/log", tags=["System"])
async def get_remediation_log() -> dict:
    """Return the recent remediation history (newest first)."""
    with _heal_lock:
        log_copy = list(_heal_log)
    return {"log": log_copy, "count": len(log_copy)}


@router.get("/portfolio", tags=["Portfolio"])
async def portfolio() -> dict:
    """Live Alpaca paper account — equity, cash, all open positions and orders."""
    try:
        acct      = get_account()
        positions = get_positions()
        orders    = get_open_orders()
        return {
            "account":   acct,
            "positions": positions,
            "open_orders": orders,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {exc}")


def _compute_position_health(
    pos: dict, alloc: dict, by_ticker_data: dict, saved_stops: dict,
) -> dict:
    symbol = pos.get("symbol", "")
    entry_price = pos.get("avg_entry_price", 0) or 0
    current_price = pos.get("current_price", 0) or 0
    pnl_pct = pos.get("unrealized_plpc", 0) or 0

    score = 50.0

    ticker_data = by_ticker_data.get(symbol, by_ticker_data.get(symbol.replace("USD", "/USD"), {}))
    mom_3 = ticker_data.get("momentum_3mo", "insufficient_data")
    mom_6 = ticker_data.get("momentum_6mo", "insufficient_data")
    if mom_3 == "positive":
        score += 12
    elif mom_3 == "negative":
        score -= 12
    if mom_6 == "positive":
        score += 8
    elif mom_6 == "negative":
        score -= 8

    conviction = alloc.get("conviction_score")
    if conviction is not None:
        if conviction >= 0.90:
            score += 10
        elif conviction >= 0.80:
            score += 5
        elif conviction < 0.75:
            score -= 5

    if pnl_pct > 0.05:
        score += 10
    elif pnl_pct > 0.02:
        score += 5
    elif pnl_pct < -0.05:
        score -= 15
    elif pnl_pct < -0.02:
        score -= 8

    stop_data = saved_stops.get(symbol)
    if stop_data and current_price > 0:
        stop_price = stop_data.get("stop_price", 0)
        distance_pct = (current_price - stop_price) / current_price if current_price > 0 else 0
        if distance_pct > 0.10:
            score += 5
        elif distance_pct < 0.02:
            score -= 10

    score = max(0, min(100, score))
    value = int(score)

    if value >= 80:
        label = "Excellent"
        color = "green"
    elif value >= 60:
        label = "Good"
        color = "emerald"
    elif value >= 40:
        label = "Fair"
        color = "amber"
    elif value >= 20:
        label = "Poor"
        color = "orange"
    else:
        label = "Critical"
        color = "red"

    return {"score": value, "label": label, "color": color}


@router.get("/positions/live", tags=["Portfolio"])
async def live_positions() -> dict:
    """
    Live Alpaca positions enriched with allocation plan entry conditions.

    Each position is joined with the latest allocation plan (by ticker) to
    include: stop_loss_pct, take_profit_pct, conviction_score, kelly_fraction,
    thesis, stop_loss_price ($), take_profit_price ($).
    """
    try:
        positions = get_positions()
        last_run  = get_last_run()
        allocation = last_run.get("last_allocation") or []

        alloc_by_ticker: dict[str, Any] = {}
        for slot in allocation:
            ticker = slot.get("ticker", "")
            if ticker and ticker not in alloc_by_ticker:
                alloc_by_ticker[ticker] = slot
                normalized = ticker.replace("/", "")
                if normalized != ticker:
                    alloc_by_ticker[normalized] = slot

        from data.yfinance_client import get_cached_market_data
        from execution.ratchet_stop import load_all_stops
        market_data = get_cached_market_data()
        by_ticker_data = market_data.get("by_ticker", {}) if market_data else {}
        saved_stops = load_all_stops()

        enriched = []
        for pos in positions:
            symbol = pos.get("symbol", "")
            alloc = alloc_by_ticker.get(symbol, {})
            entry_price = pos.get("avg_entry_price", 0) or 0
            stop_loss_pct   = alloc.get("stop_loss_pct")
            take_profit_pct = alloc.get("take_profit_pct")

            health_score = _compute_position_health(
                pos, alloc, by_ticker_data, saved_stops
            )

            # Determine asset class: short positions are labelled "direct_short"
            pos_side = str(pos.get("side", "long")).lower()
            raw_asset_class = alloc.get("asset_class", "unknown")
            if pos_side == "short" and raw_asset_class == "unknown":
                raw_asset_class = "direct_short"

            enriched.append({
                **pos,
                "asset_class":      raw_asset_class,
                "conviction_score": alloc.get("conviction_score"),
                "kelly_fraction":   alloc.get("kelly_fraction"),
                "stop_loss_pct":    stop_loss_pct,
                "take_profit_pct":  take_profit_pct,
                "stop_loss_price":  round(entry_price * (1 + stop_loss_pct), 4)
                                    if entry_price and stop_loss_pct is not None else None,
                "take_profit_price": round(entry_price * (1 + take_profit_pct), 4)
                                     if entry_price and take_profit_pct is not None else None,
                "original_thesis":  alloc.get("thesis"),
                "health_score":     health_score,
            })

        return {"count": len(enriched), "positions": enriched}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {exc}")


@router.get("/journal", tags=["Journal"])
async def journal() -> dict:
    """Trade journal summary + full trade history (Alpaca + Kraken)."""
    summary = get_journal_summary()
    alpaca_trades = get_all_trades()
    kraken_trades = _load_kraken_journal_trades()
    # Merge and sort by date descending (newest first)
    all_trades = alpaca_trades + kraken_trades
    try:
        all_trades.sort(key=lambda t: (t.get("date") or ""), reverse=True)
    except Exception:
        pass
    # Update summary totals to include Kraken
    k_wins  = sum(1 for t in kraken_trades if t.get("pnl_percentage", 0) > 0)
    k_total = len(kraken_trades)
    combined_wins  = (summary.get("wins", 0)  or 0) + k_wins
    combined_total = (summary.get("total", 0) or 0) + k_total
    combined_losses = combined_total - combined_wins
    # Recalculate avg_pnl across all trades
    all_pnl = [
        t.get("pnl_percentage")
        for t in all_trades
        if t.get("pnl_percentage") is not None
    ]
    avg_pnl = round(sum(all_pnl) / len(all_pnl), 3) if all_pnl else None
    combined_summary = {
        **summary,
        "total":        combined_total,
        "wins":         combined_wins,
        "losses":       combined_losses,
        "avg_pnl":      avg_pnl,
        "win_rate_pct": round(combined_wins / combined_total * 100, 1) if combined_total > 0 else 0,
    }
    return {"summary": combined_summary, "trades": all_trades}


def _load_kraken_journal_trades() -> list[dict]:
    """Load and normalise Kraken all_trades from paper_portfolio.json into the
    same dict shape used by the Alpaca trades table so they can be merged into
    journal endpoints."""
    try:
        import json as _j
        from pathlib import Path as _P
        _pf_path = _P("../kraken-bot/paper_portfolio.json")
        if not _pf_path.exists():
            return []
        _pf = _j.loads(_pf_path.read_text())
        trades = []
        for idx, t in enumerate(_pf.get("all_trades", [])):
            if t.get("pnl_pct") is None:
                continue
            _pnl = float(t["pnl_pct"])
            trades.append({
                "trade_id": f"kraken-{idx}",
                "date": (t.get("closed_at") or "")[:10],
                "ticker": t.get("symbol", "?"),
                "asset_class": "crypto",
                "conviction_score": None,
                "original_thesis": f"Kraken {t.get('side','?')} {t.get('symbol','?')} — exit: {t.get('reason','?')}",
                "pnl_percentage": _pnl,
                "status": "Closed_Win" if _pnl > 0 else "Closed_Loss",
                "intended_price": None,
                "actual_fill_price": None,
                "slippage_pct": None,
                "source": "kraken",
            })
        return trades
    except Exception as _e:
        logger.warning(f"Kraken journal load failed: {_e}")
        return []


@router.get("/journal/losses", tags=["Journal"])
async def journal_losses(n: int = 5) -> dict:
    """
    The N most recent losing trades — what the RAG loop feeds into the
    next Groq system prompt as failure examples. Includes both Alpaca and Kraken.
    """
    alpaca_losses = get_recent_losses(limit=n * 4)
    kraken_all = _load_kraken_journal_trades()
    kraken_losses = [t for t in kraken_all if t["pnl_percentage"] < 0]
    combined = sorted(alpaca_losses + kraken_losses, key=lambda x: x["pnl_percentage"])
    losses = combined[:n]
    return {"count": len(losses), "losses": losses}


@router.get("/journal/wins", tags=["Journal"])
async def journal_wins(n: int = 5) -> dict:
    """
    The N most recent winning trades — what the RAG loop feeds into the
    next Groq system prompt as positive reinforcement examples. Includes both Alpaca and Kraken.
    """
    alpaca_wins = get_recent_wins(limit=n * 4)
    kraken_all = _load_kraken_journal_trades()
    kraken_wins = [t for t in kraken_all if t["pnl_percentage"] > 0]
    combined = sorted(alpaca_wins + kraken_wins, key=lambda x: x["pnl_percentage"], reverse=True)
    wins = combined[:n]
    return {"count": len(wins), "wins": wins}


@router.get("/journal/recent", tags=["Journal"])
async def journal_recent(n: int = 20) -> dict:
    """Last N closed trades (wins + losses combined), newest first.
    Used by the dashboard for Alpaca streak computation."""
    trades = get_recent_trades_combined(limit=n)
    return {"count": len(trades), "trades": trades}


@router.get("/learning-journal", tags=["Journal"])
async def learning_journal_endpoint(
    regime: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> dict:
    """
    LLM Learning Journal — consolidated insights extracted from every Groq analysis cycle.
    Entries with higher confirmed_count have been observed across multiple independent cycles.
    Sorted by confidence_score DESC.
    Optional filters: regime (Bull|Bear|Sideways|Crypto), category (macro|momentum|risk|position|crypto).
    """
    from analysis.learning_journal import get_journal_entries
    entries = get_journal_entries(regime=regime, category=category, limit=limit)
    return {"count": len(entries), "entries": entries}


# ── System Degradation Log endpoints ─────────────────────────────────────────

@router.get("/system/degradations", tags=["System"])
async def system_degradations_endpoint(
    hours: int = 48,
    component: str | None = None,
    unresolved_only: bool = False,
    limit: int = 100,
) -> dict:
    """
    Persistent log of every detected system failure or degradation event.
    Captured from the auto-heal monitor, HTTP 500/503 middleware, and manual records.
    Optional: component filter, unresolved_only=true to see open issues, hours window.
    """
    from core.degradation_tracker import get_recent_events, get_stats
    events = get_recent_events(limit=limit, hours=hours, component=component, unresolved_only=unresolved_only)
    stats = get_stats(hours=hours)
    return {
        "window_hours": hours,
        "total": len(events),
        "stats": stats,
        "events": events,
    }


@router.get("/system/degradations/report", tags=["System"])
async def system_degradations_report(hours: int = 48) -> dict:
    """
    Generate a rich plain-text bug report formatted for copy-paste to the AI.

    Includes:
    - Live system snapshot (green/yellow/red per node, right now)
    - Market context: open/closed, Groq budget state, Kraken positions/VPIN
    - Active (unresolved) issues with first-seen / last-seen duration
    - Auto-heal success rate (last 20 attempts)
    - Component summary with total counts
    - Full event timeline with MARKET OPEN / AFTER HOURS annotations
    - 8-line detail excerpts (enough for full tracebacks)
    """
    import json as _json
    from pathlib import Path as _Path
    from core.degradation_tracker import build_bug_report

    # ── Gather live context ───────────────────────────────────────────────
    live_health: dict | None = None
    groq_budget: dict | None = None
    kraken_status: dict | None = None
    market_open_flag: bool | None = None
    market_next_open: str | None = None
    heal_log_data: list[dict] | None = None

    try:
        # Live health snapshot (same function powering the dashboard diagram)
        live_health = await system_health_architecture()
    except Exception:
        pass

    try:
        from analysis.groq_budget import budget as _gb
        groq_budget = _gb.budget_status()
        groq_budget["budget_exhausted"] = _gb.budget_exhausted()
        groq_budget["daily_limit"] = groq_budget.get("token_budget_total", 100000)
    except Exception:
        pass

    try:
        sf = _Path("../kraken-bot/status.json")
        if sf.exists():
            kraken_status = _json.loads(sf.read_text())
    except Exception:
        pass

    try:
        market_open_flag = is_market_open()
        if not market_open_flag:
            nxt = get_next_open()
            market_next_open = str(nxt)[:19].replace("T", " ") + " UTC" if nxt else None
    except Exception:
        pass

    try:
        with _heal_lock:
            heal_log_data = list(_heal_log[:20])  # newest-first, first 20
    except Exception:
        pass

    report = build_bug_report(
        hours=hours,
        live_health=live_health,
        groq_budget=groq_budget,
        kraken_status=kraken_status,
        market_open=market_open_flag,
        market_next_open=market_next_open,
        heal_log=heal_log_data,
    )
    return {"hours": hours, "report": report}


@router.post("/system/degradations/record", tags=["System"])
async def record_manual_degradation(
    component: str,
    severity: str,
    error_type: str,
    message: str,
    detail: str | None = None,
) -> dict:
    """
    Manually record a degradation event (e.g. from operator observation).
    Severity: critical | error | warning
    """
    from core.degradation_tracker import record_degradation
    ok = record_degradation(
        component=component,
        severity=severity,
        error_type=error_type,
        message=message,
        detail=detail,
    )
    return {"recorded": ok}


@router.get("/performance", tags=["Performance"])
async def performance_history(limit: int = 90) -> dict:
    """
    Full daily performance snapshot history (up to 90 days by default).
    Each row: date, equity, daily_pnl_pct, cumulative_pnl_pct, win_rate, trades_placed.
    """
    snapshots = get_performance_snapshots(limit=limit)
    return {"count": len(snapshots), "snapshots": snapshots}


@router.get("/performance/summary", tags=["Performance"])
async def performance_summary_endpoint() -> dict:
    """
    Aggregate performance statistics across all recorded snapshots.
    Returns total_return_pct, best/worst day, overall win rate, total trades.
    """
    summary = get_performance_summary()
    return summary


@router.post("/run", tags=["Control"])
async def manual_run(request: RunRequest, background_tasks: BackgroundTasks) -> dict:
    """
    Manually trigger a full analysis + execution pipeline cycle.

    - dry_run=true  → analysis runs, no real orders placed
    - force=true    → bypasses the market-closed guard
    """
    if is_tripped() and not request.force:
        raise HTTPException(
            status_code=409,
            detail="Kill switch is tripped. Pass force=true to override, or POST /kill/reset first.",
        )

    logger.info(f"Manual run requested: dry_run={request.dry_run} force={request.force}")
    result = await run_pipeline(force=request.force, dry_run=request.dry_run, crypto_only=request.crypto_only)
    return result


@router.post("/run/postmortem", tags=["Control"])
async def manual_postmortem() -> dict:
    """Manually trigger the post-mortem P&L reconciliation."""
    logger.info("Manual post-mortem requested")
    postmortem_result = await run_postmortem()

    # ── Kraken journal sync ──────────────────────────────────────────────────
    # Sync closed Kraken paper trades into the PostgreSQL trade journal so the
    # HITL auditor has a complete view of all trading activity.
    try:
        kraken_sync = _sync_kraken_trades_to_journal()
        postmortem_result["kraken_journal_sync"] = kraken_sync
    except Exception as _ksync_exc:
        logger.error(f"Kraken journal sync failed: {_ksync_exc}")
        postmortem_result["kraken_journal_sync"] = {"error": str(_ksync_exc), "imported": 0}

    # ── Equity snapshot at postmortem ────────────────────────────────────────
    try:
        from db.postgres import insert_equity_snapshot as _ins_snap, is_pg_available as _pg_ok
        if _pg_ok():
            import json as _j2, pathlib as _pl2
            _sp2 = _pl2.Path("../kraken-bot/status.json")
            _k_equity = 0.0
            if _sp2.exists():
                _bs2 = _j2.loads(_sp2.read_text())
                _k_equity = float((_bs2.get("paper_summary") or {}).get("total_equity_usd", 0) or 0)
            try:
                from execution.broker import get_account as _ga2
                _a_equity = float(_ga2().get("equity", 0) or 0)
            except Exception:
                _a_equity = 0.0
            _ins_snap(alpaca_equity=_a_equity, kraken_equity=_k_equity, source="postmortem")
            logger.info(f"Postmortem equity snapshot: alpaca={_a_equity:.2f} kraken={_k_equity:.2f}")
    except Exception as _snap2_exc:
        logger.warning(f"Postmortem equity snapshot failed (non-fatal): {_snap2_exc}")

    return postmortem_result


# ── Kraken paper-trade journal sync ───────────────────────────────────────────
_KRAKEN_IMPORTED_SIDECAR = os.path.join(os.path.dirname(__file__), "data", "kraken_imported_trades.json")
_kraken_imported_lock = __import__("threading").Lock()


def _load_kraken_imported() -> set[str]:
    """Load the set of already-imported Kraken trade keys from the sidecar file."""
    try:
        if os.path.exists(_KRAKEN_IMPORTED_SIDECAR):
            with open(_KRAKEN_IMPORTED_SIDECAR) as f:
                return set(__import__("json").load(f))
    except Exception as exc:
        logger.warning(f"Kraken sync | Failed to load import sidecar: {exc}")
    return set()


def _save_kraken_imported(keys: set[str]) -> None:
    """Atomically persist the imported-key set to the sidecar file."""
    tmp = _KRAKEN_IMPORTED_SIDECAR + ".tmp"
    try:
        with open(tmp, "w") as f:
            __import__("json").dump(list(keys), f)
        os.replace(tmp, _KRAKEN_IMPORTED_SIDECAR)
    except Exception as exc:
        logger.warning(f"Kraken sync | Failed to save import sidecar: {exc}")


def _sync_kraken_trades_to_journal() -> dict:
    """
    Read all closed trades from kraken-bot/paper_portfolio.json and insert any
    new ones into the PostgreSQL trade journal (source='kraken_paper').
    Uses a sidecar JSON file to track already-imported trades by a composite key
    (symbol|closed_at) to prevent duplicates across postmortem runs.
    """
    import json as _jk
    from db.postgres import is_pg_available, get_conn

    if not is_pg_available():
        return {"imported": 0, "skipped": 0, "reason": "PostgreSQL unavailable"}

    _portfolio_path = os.path.join(os.path.dirname(__file__), "..", "kraken-bot", "paper_portfolio.json")
    if not os.path.exists(_portfolio_path):
        return {"imported": 0, "skipped": 0, "reason": "paper_portfolio.json not found"}

    try:
        with open(_portfolio_path) as f:
            portfolio = _jk.load(f)
    except Exception as exc:
        return {"imported": 0, "skipped": 0, "error": f"Could not read portfolio: {exc}"}

    all_trades = portfolio.get("all_trades", [])
    if not all_trades:
        return {"imported": 0, "skipped": 0, "reason": "No trades in paper portfolio"}

    with _kraken_imported_lock:
        imported_keys = _load_kraken_imported()
        new_keys = set()
        imported = 0
        skipped = 0
        errors = 0

        for trade in all_trades:
            symbol = trade.get("symbol", "UNKNOWN")
            closed_at = trade.get("closed_at", "")
            key = f"{symbol}|{closed_at}"
            if key in imported_keys:
                skipped += 1
                continue

            # Derive a stable trade_id from the key
            import hashlib
            trade_id = "KRK-" + hashlib.md5(key.encode()).hexdigest()[:16]

            # Parse date from closed_at
            try:
                from datetime import datetime, timezone
                _dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                trade_date = _dt.date().isoformat()
            except Exception:
                trade_date = date.today().isoformat()

            pnl_pct = trade.get("pnl_pct")
            entry_price = trade.get("entry_price")
            exit_price = trade.get("exit_price")
            reason = trade.get("reason", "kraken_paper")

            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        # Insert as a closed trade directly
                        cur.execute(
                            """
                            INSERT INTO trades
                                (trade_id, date, ticker, asset_class, conviction_score,
                                 original_thesis, pnl_percentage, status,
                                 intended_price, actual_fill_price)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (trade_id) DO NOTHING
                            """,
                            (
                                trade_id,
                                trade_date,
                                symbol.replace("/", ""),   # LINK/USD → LINKUSD
                                "Crypto",
                                5.0,                       # default conviction for Kraken trades
                                f"Kraken paper trade ({reason})",
                                pnl_pct,
                                "Closed",
                                entry_price,
                                exit_price,
                            ),
                        )
                new_keys.add(key)
                imported += 1
                logger.info(f"Kraken sync | Imported {symbol} {trade_date} pnl={pnl_pct}%")
            except Exception as exc:
                logger.error(f"Kraken sync | Failed to insert {key}: {exc}")
                errors += 1

        imported_keys.update(new_keys)
        if new_keys:
            _save_kraken_imported(imported_keys)

    logger.info(f"Kraken journal sync | imported={imported} skipped={skipped} errors={errors}")
    return {"imported": imported, "skipped": skipped, "errors": errors}


VAULT_TICKER = "JEPQ"
KNOWN_CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD"}

@router.post("/rebalance", tags=["Control"])
async def force_rebalance() -> dict:
    """
    Force-close all sellable positions then trigger a fresh pipeline run.

    Rules:
      - Crypto positions (BTCUSD, ETHUSD) can always be closed (24/7 market).
      - Stock/ETF positions can only be closed when the stock market is open.
        If the market is closed, those positions are HELD until next market open.
      - JEPQ (vault) is never closed — it is protected.
      - After closing what it can, the system runs a fresh analysis + execution
        pipeline to open new trades based on current learnings.
    """
    market_open = is_market_open()
    positions = get_positions()
    cancel_all_orders()

    closed = []
    held = []
    errors = []

    for pos in positions:
        sym = pos["symbol"]
        if sym == VAULT_TICKER:
            held.append({"symbol": sym, "reason": "vault_protected"})
            continue
        is_crypto = sym in KNOWN_CRYPTO_SYMBOLS
        if not is_crypto and not market_open:
            held.append({"symbol": sym, "reason": "market_closed"})
            continue
        try:
            order = close_position(sym)
            closed.append({"symbol": sym, "order": order})
            try:
                delete_stop(sym)
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"Rebalance | Failed to close {sym}: {exc}")
            errors.append({"symbol": sym, "error": str(exc)})

    logger.info(
        f"Rebalance | Closed {len(closed)} positions, "
        f"held {len(held)}, errors {len(errors)}"
    )

    crypto_only = not market_open
    pipeline_result = await run_pipeline(force=True, dry_run=False, crypto_only=crypto_only)

    return {
        "status": "ok",
        "closed": closed,
        "held": held,
        "errors": errors,
        "market_open": market_open,
        "pipeline": pipeline_result,
    }


@router.post("/rebalance/{symbol}", tags=["Control"])
async def force_close_single(symbol: str) -> dict:
    """
    Force-close a single position by symbol, then trigger a fresh pipeline run
    so the freed capital is immediately reallocated using the latest learning data.

    Rules (same as full rebalance):
      - JEPQ (vault) is never closeable.
      - Crypto symbols (BTCUSD, ETHUSD) can be closed 24/7.
      - Stock/ETF positions require market to be open.
    """
    sym = symbol.upper()

    if sym == VAULT_TICKER:
        raise HTTPException(status_code=400, detail="JEPQ vault position is protected and cannot be force-closed.")

    market_open = is_market_open()
    is_crypto = sym in KNOWN_CRYPTO_SYMBOLS

    if not is_crypto and not market_open:
        raise HTTPException(
            status_code=409,
            detail=f"{sym} is a stock/ETF position. Market is currently closed — cannot close until next session.",
        )

    try:
        order = close_position(sym)
    except Exception as exc:
        logger.error(f"Force-close {sym} | Failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to close {sym}: {str(exc)}")

    try:
        delete_stop(sym)
    except Exception:
        pass

    logger.info(f"Force-close {sym} | Closed. Running fresh pipeline to reallocate capital.")

    crypto_only = not market_open
    pipeline_result = await run_pipeline(force=True, dry_run=False, crypto_only=crypto_only)

    return {
        "status": "ok",
        "closed": sym,
        "order": order,
        "pipeline": pipeline_result,
    }


@router.post("/kill", tags=["Risk"])
async def trip_kill_switch() -> dict:
    """
    Manually trip the kill switch — immediately liquidates all positions
    and blocks further trading for the rest of the day.
    """
    logger.warning("Kill switch MANUALLY tripped via API")
    ks_manual_trip(reason="manual_api_trip")
    return {"status": "tripped", "kill_switch": ks_get_state()}


@router.post("/kill/reset", tags=["Risk"])
async def reset_kill_switch(request: KillResetRequest) -> dict:
    """
    Reset the kill switch for a new trading day.
    Optionally pass opening_equity to override the Alpaca-fetched baseline.
    """
    logger.info(f"Kill switch reset via API | opening_equity={request.opening_equity}")
    ks_reset(opening_equity=request.opening_equity)
    return {"status": "reset", "kill_switch": ks_get_state()}


# ── Emergency Controls ────────────────────────────────────────────────────────

VAULT_TICKER_PROTECTED = {"JEPQ"}


@router.post("/emergency/liquidate", tags=["Emergency"])
async def emergency_liquidate() -> dict:
    """
    Emergency liquidation:
      1. Cancel all open orders immediately.
      2. Market-close every open position EXCEPT the JEPQ vault.
      3. Trip the kill switch so no new trades are placed until manually reset.

    This action is irreversible without a /kill/reset call.
    """
    logger.critical("EMERGENCY LIQUIDATE triggered via API — closing all positions")

    # 1. Cancel pending orders first
    try:
        cancel_all_orders()
        logger.info("Emergency | All open orders cancelled")
    except Exception as exc:
        logger.error(f"Emergency | cancel_all_orders failed: {exc}")

    # 2. Close every non-vault position regardless of market hours
    positions = []
    try:
        positions = get_positions()
    except Exception as exc:
        logger.error(f"Emergency | Could not fetch positions: {exc}")

    closed: list[dict] = []
    held: list[dict] = []
    errors: list[dict] = []

    for pos in positions:
        sym = pos["symbol"]
        if sym in VAULT_TICKER_PROTECTED:
            held.append({"symbol": sym, "reason": "vault_protected"})
            continue
        try:
            order = close_position(sym)   # DAY market order — fills immediately if market open
            closed.append({"symbol": sym, "order_id": order.get("id")})
            # Remove any ratchet stop record
            try:
                from execution.ratchet_stop import delete_stop
                delete_stop(sym)
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"Emergency | Failed to close {sym}: {exc}")
            errors.append({"symbol": sym, "error": str(exc)})

    # 3. Trip the kill switch — blocks all new position opens
    ks_manual_trip(reason="emergency_liquidate_api")

    market_open = is_market_open()
    next_open   = get_next_open() or "next market session"

    # 4. Set pending_liquidation if market is closed or any close order failed.
    #    The pipeline will force-close remaining positions at the next market open.
    needs_deferred = (not market_open) or bool(errors)
    set_pending_liquidation(needs_deferred)

    if market_open and not errors:
        fill_note = (
            f"Market is OPEN — {len(closed)} market order(s) submitted and will fill shortly."
        )
    elif market_open and errors:
        fill_note = (
            f"Market is OPEN — {len(closed)} order(s) submitted; {len(errors)} failed. "
            f"Failed positions will be force-closed at next pipeline run. "
            f"Pending liquidation flag is SET."
        )
    else:
        fill_note = (
            f"Market is CLOSED — close orders cannot execute until market opens. "
            f"A pending liquidation flag is now SET: positions will be force-closed "
            f"automatically the moment the market opens ({next_open} ET). "
            f"No action required — the system handles this automatically."
        )

    logger.critical(
        f"Emergency | Liquidation complete: "
        f"closed={len(closed)}, held={len(held)}, errors={len(errors)} | "
        f"market_open={market_open} | pending_liquidation={needs_deferred} — kill switch tripped"
    )

    return {
        "status":            "liquidated",
        "positions_closed":  closed,
        "positions_held":    held,
        "errors":            errors,
        "kill_switch":       "tripped",
        "market_open":       market_open,
        "pending_liquidation": needs_deferred,
        "fill_note":         fill_note,
        "message":           fill_note + " Use POST /kill/reset to resume trading after positions clear.",
    }


@router.post("/system/restart", tags=["Emergency"])
async def system_restart() -> dict:
    """
    System restart / error-state clear:
      1. Reset pipeline error state (last_run_status → 'restarted', error_count → 0).
      2. Invalidate the market-data cache so the next cycle fetches fresh data.
      3. The kill switch is NOT reset here — use POST /kill/reset for that.

    After calling this, the system status will show 'online' and the next
    scheduled cycle will run normally (or trigger POST /run to force immediately).
    """
    logger.info("SYSTEM RESTART triggered via API — clearing error state and cache")

    # 1. Reset pipeline error state
    new_state = reset_error_state()

    # 2. Clear market-data cache
    try:
        import data.yfinance_client as _yf
        _yf._cached_market_data = None
        logger.info("System restart | Market-data cache cleared")
    except Exception as exc:
        logger.warning(f"System restart | Could not clear market-data cache: {exc}")

    # 3. Clear AI commentary cache
    _commentary_cache.update({"text": None, "generated_at": None, "ts": 0})

    jobs = get_job_status()
    logger.info(f"System restart | Complete — scheduler has {len(jobs)} job(s)")

    return {
        "status": "restarted",
        "pipeline_state": new_state,
        "scheduler_jobs": len(jobs),
        "kill_switch": ks_get_state(),
        "message": (
            "Error state cleared and cache invalidated. "
            "System will resume on next scheduled cycle. "
            "NOTE: Kill switch state is unchanged — use POST /kill/reset if it was tripped."
        ),
    }


class AutoTradingRequest(BaseModel):
    enabled: bool


@router.get("/auto-trading", tags=["Control"])
async def auto_trading_status() -> dict:
    """Return whether the automatic trading system is currently enabled."""
    return {
        "auto_trading_enabled": is_auto_trading_enabled(),
        "jobs": get_job_status(),
    }


@router.post("/auto-trading", tags=["Control"])
async def toggle_auto_trading(request: AutoTradingRequest) -> dict:
    """Enable or disable the automatic trading scheduler."""
    logger.info(f"Auto-trading toggle requested: enabled={request.enabled}")
    result = set_auto_trading(request.enabled)
    return result


@router.get("/allocation/latest", tags=["Portfolio"])
async def latest_allocation() -> dict:
    """Return the most recent LLM allocation plan (from last pipeline run)."""
    last = get_last_run()
    allocation = last.get("last_allocation")
    if not allocation:
        return {"status": "no_allocation_yet", "allocation": None}
    return {
        "status": "ok",
        "run_utc": last.get("last_run_utc"),
        "regime": last.get("last_regime"),
        "allocation": allocation,
    }


# ── AI Brain Commentary ────────────────────────────────────────────────────────

@router.get("/ai/commentary", tags=["AI"])
async def ai_commentary(force: bool = False) -> dict:
    """
    Generate a natural-language 'AI brain' commentary summarising:
      - What the system learned from recent wins/losses
      - How it plans to adjust strategy going forward
      - Its take on current open positions

    Results are cached for 30 minutes. Pass ?force=true to regenerate immediately.
    """
    global _commentary_cache

    now = time.time()
    cache_age = now - _commentary_cache["ts"]

    if not force and _commentary_cache["text"] and cache_age < COMMENTARY_TTL_SECONDS:
        return {
            "commentary": _commentary_cache["text"],
            "generated_at": _commentary_cache["generated_at"],
            "cached": True,
            "cache_age_seconds": int(cache_age),
        }

    from analysis.groq_budget import budget as _groq_budget
    if not _groq_budget.can_call_commentary("alpaca", force=force):
        if _commentary_cache["text"]:
            return {
                "commentary": _commentary_cache["text"],
                "generated_at": _commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "throttled": True,
                "budget_exhausted": _groq_budget.budget_exhausted(),
            }
        _exhausted = _groq_budget.budget_exhausted()
        return {
            "commentary": (
                "The Oracle is resting — daily AI token budget exhausted. Commentary will resume tomorrow at midnight UTC."
                if _exhausted else
                "The Oracle is resting — daily call limit reached. Commentary will resume tomorrow at midnight UTC."
            ),
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "throttled": True,
            "budget_exhausted": _exhausted,
        }

    wins    = get_recent_wins(limit=3)
    losses  = get_recent_losses(limit=5)
    summary = get_journal_summary()

    try:
        positions = get_positions()
    except Exception:
        positions = []

    wins_text = "\n".join(
        f"  WIN: {w['ticker']} +{w['pnl_percentage']:.1f}% — {w['original_thesis'][:80]}"
        for w in wins
    ) or "  (none recorded yet)"

    losses_text = "\n".join(
        f"  LOSS: {l['ticker']} {l['pnl_percentage']:.1f}% — {l['original_thesis'][:80]}"
        for l in losses
    ) or "  (none recorded yet)"

    pos_lines = []
    for p in positions:
        pnl_pct = p.get("unrealized_plpc", 0)
        pnl_dollar = p.get("unrealized_pl", 0)
        emoji = "📈" if pnl_pct >= 0 else "📉"
        pos_lines.append(
            f"  {emoji} {p['symbol']}: {pnl_pct*100:+.1f}% (${pnl_dollar:+.0f})"
        )
    positions_text = "\n".join(pos_lines) or "  (no open positions — fully in cash)"

    extra_context_parts = []

    try:
        from data.sentiment import get_sentiment
        sentiment = get_sentiment()
        cfg = sentiment.get("crypto_fear_greed", {})
        mfg = sentiment.get("market_fear_greed", {})
        extra_context_parts.append(
            f"Sentiment: Crypto Fear&Greed={cfg.get('value', '?')} ({cfg.get('label', '?')}), "
            f"Market Fear&Greed={mfg.get('value', '?')} ({mfg.get('label', '?')})"
        )
    except Exception:
        pass

    try:
        from data.economic_calendar import get_blackout_state, get_upcoming_events
        blackout = get_blackout_state()
        if blackout.get("active"):
            extra_context_parts.append(
                f"BLACKOUT ACTIVE: {blackout.get('event', 'economic release')} — trading paused"
            )
        upcoming = get_upcoming_events(days_ahead=3)
        if upcoming:
            evts = ", ".join(f"{e['name']} in {e['days_away']}d" for e in upcoming[:3])
            extra_context_parts.append(f"Upcoming events: {evts}")
    except Exception:
        pass

    try:
        from analysis.attribution import compute_attribution
        attr = compute_attribution()
        if attr.get("closed_trades", 0) > 0:
            ov = attr["overall"]
            best_regime = max(attr.get("regime_attribution", {}).items(), key=lambda x: x[1]["total_pnl_pct"], default=None)
            regime_note = f", best regime: {best_regime[0]} ({best_regime[1]['total_pnl_pct']:+.1f}%)" if best_regime else ""
            extra_context_parts.append(
                f"Attribution: {ov['wins']}W/{ov['losses']}L, win rate {ov['win_rate']:.0f}%, "
                f"avg P&L {ov['avg_pnl_pct']:+.2f}%{regime_note}"
            )
    except Exception:
        pass

    try:
        snapshots = get_performance_snapshots(limit=30)
        if snapshots and len(snapshots) >= 2:
            import numpy as np
            daily_rets = [s["daily_pnl_pct"] / 100.0 for s in snapshots if s.get("daily_pnl_pct") is not None]
            if len(daily_rets) >= 2:
                arr = np.array(daily_rets)
                std_r = float(np.std(arr, ddof=1))
                if std_r > 0:
                    sharpe = float((np.mean(arr) - 0.05/252) / std_r * np.sqrt(252))
                    extra_context_parts.append(f"Risk: Sharpe={sharpe:.2f}, Volatility={std_r*np.sqrt(252)*100:.1f}%")
    except Exception:
        pass

    try:
        from data.yfinance_client import get_cached_data
        cached = get_cached_data()
        if cached:
            tickers_with_closes = [t for t, d in cached.items() if d.get("closes") and len(d["closes"]) >= 20]
            if len(tickers_with_closes) >= 2:
                import numpy as np
                close_arrays = {}
                min_len = min(len(cached[t]["closes"]) for t in tickers_with_closes)
                for t in tickers_with_closes:
                    close_arrays[t] = cached[t]["closes"][-min_len:]
                high_corr = []
                for i, t1 in enumerate(tickers_with_closes):
                    for t2 in tickers_with_closes[i+1:]:
                        corr = float(np.corrcoef(close_arrays[t1], close_arrays[t2])[0, 1])
                        if abs(corr) > 0.85:
                            high_corr.append(f"{t1}/{t2} r={corr:.2f}")
                if high_corr:
                    extra_context_parts.append(f"Correlation warnings: {', '.join(high_corr[:3])}")
    except Exception:
        pass

    extra_context_text = ""
    if extra_context_parts:
        extra_context_text = "\n\nMarket intelligence:\n" + "\n".join(f"  {p}" for p in extra_context_parts)

    user_prompt = f"""
Recent Wins (reinforcing behaviour):
{wins_text}

Recent Losses (behavioural corrections needed):
{losses_text}

Journal summary: {summary.get('wins', 0)} wins / {summary.get('losses', 0)} losses total, avg P&L {summary.get('avg_pnl') or 0:.2f}%

Current open positions:
{positions_text}
{extra_context_text}
"""

    system_prompt = (
        "You are 'The Degen Oracle' — a quant trading AI with swagger and sharp wit. "
        "In exactly 2 punchy sentences: your sharpest market read right now, and one concrete portfolio observation. "
        "Reference specific tickers or data when available. Direct, no filler. Plain text only."
    )

    def _blocking_call() -> tuple[str, int]:
        from groq import Groq
        from config.settings import settings as _settings
        client = Groq(api_key=_settings.groq_api_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.72,
            max_tokens=150,
        )
        tokens = resp.usage.total_tokens if resp.usage else 0
        return resp.choices[0].message.content.strip(), tokens

    try:
        loop = asyncio.get_event_loop()
        commentary, tokens_used = await loop.run_in_executor(None, _blocking_call)
        _groq_budget.consume(tokens_used, call_type="commentary")
        if not force:
            _groq_budget.record_commentary_call("alpaca")
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        _commentary_cache = {"text": commentary, "generated_at": generated_at, "ts": now}
        _persist_commentary_caches()
        logger.info(f"AI commentary regenerated successfully (force={force}, tokens={tokens_used})")
        return {"commentary": commentary, "generated_at": generated_at, "cached": False, "cache_age_seconds": 0}
    except Exception as exc:
        logger.error(f"AI commentary generation failed: {exc}")
        # Back off 5 min so the next auto-refresh does not immediately retry Groq
        _commentary_cache["ts"] = now - COMMENTARY_TTL_SECONDS + 300
        if _commentary_cache["text"]:
            return {
                "commentary": _commentary_cache["text"],
                "generated_at": _commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "error": str(exc),
            }
        return {
            "commentary": "The Oracle is resting — daily AI token limit reached. Check back tomorrow for fresh market insight.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "error": str(exc),
            "unavailable": True,
        }


# ── High-Yield Growth Vault endpoints ─────────────────────────────────────────

@router.get("/vault", tags=["Vault"])
async def vault_state() -> dict:
    """Return current High-Yield Growth Vault state (HWM, total vaulted, sweeps)."""
    from execution.profit_sweep import get_vault_state
    state = get_vault_state()
    if state is None:
        return {
            "initialised": False,
            "message": "Vault not yet initialised — run a pipeline cycle to set the High Water Mark.",
        }
    return {"initialised": True, **state}


@router.post("/vault/sweep", tags=["Vault"])
async def manual_vault_sweep(dry_run: bool = False) -> dict:
    """Manually trigger a profit-sweep check against the current equity."""
    from execution.profit_sweep import run_profit_sweep
    from execution.broker import get_account
    try:
        acct = get_account()
        equity = acct["equity"]
        result = run_profit_sweep(current_equity=equity, dry_run=dry_run)
        return {"status": "ok", "dry_run": dry_run, "current_equity": equity, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vault sweep failed: {exc}")


# ── Phase 1 compatibility endpoint ────────────────────────────────────────────

# ── Auditor Agent (HITL Supervisor) ───────────────────────────────────────────

@router.get("/auditor/report", tags=["Auditor"])
async def auditor_report() -> dict:
    """
    Return the most recent HITL audit report.
    If no audit has been run yet in this process session, returns an empty
    placeholder.  The daily scheduled audit runs at 4:30 PM ET Mon–Fri.
    Use POST /auditor/run to trigger one immediately.
    """
    result = get_last_audit()
    if result["overall"] == "never_run":
        return {
            "status": "no_audit_yet",
            "message": "No audit has been run yet. POST /auditor/run to trigger one.",
            "report":  None,
        }
    return {"status": "ok", "report": result}


@router.post("/auditor/run", tags=["Auditor"])
async def trigger_audit(background_tasks: BackgroundTasks) -> dict:
    """
    Manually trigger a full HITL audit cycle in the background.
    The audit runs the five checks (regime integrity, compliance, RAG bias,
    phantom drawdown, ratchet integrity) and writes a Markdown report to
    trading-platform/logs/daily_audit_report_YYYY-MM-DD.md.
    """
    logger.info("Auditor | Manual trigger via POST /auditor/run")

    async def _bg_audit() -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, run_full_audit)
        except Exception as exc:
            logger.error(f"Auditor | Background audit failed: {exc}")

    background_tasks.add_task(_bg_audit)
    return {
        "status": "audit_started",
        "message": "Audit running in background — check GET /auditor/report in ~30 seconds",
    }


@router.get("/auditor/performance", tags=["Auditor"])
async def auditor_performance_report() -> dict:
    """
    Return the most recent performance narrative analysis for both bots.
    Returns status='not_run' if no analysis has been triggered yet.
    POST /auditor/performance/run to trigger one.
    """
    return get_last_performance_report()


@router.post("/auditor/performance/run", tags=["Auditor"])
async def trigger_performance_analysis(
    background_tasks: BackgroundTasks,
    days: int = 10,
) -> dict:
    """
    Trigger a performance narrative analysis for the last N days.
    Uses Groq to generate a plain-English comparison of both bots.
    Check GET /auditor/performance in ~15 seconds.
    """
    logger.info(f"PerfAnalysis | Manual trigger via POST /auditor/performance/run (days={days})")

    async def _bg_perf() -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: run_performance_analysis(days=days))
        except Exception as exc:
            logger.error(f"PerfAnalysis | Background analysis failed: {exc}")

    background_tasks.add_task(_bg_perf)
    return {
        "status":  "analysis_started",
        "message": f"Performance analysis running — check GET /auditor/performance in ~15 seconds",
        "days":    days,
    }


# ── Learning Snapshot — cross-deploy knowledge persistence ────────────────────

@router.get("/admin/learning-snapshot", tags=["Admin"])
async def get_learning_snapshot_info() -> dict:
    """
    Return metadata about the current learning snapshot file.
    The snapshot is committed to the repo so it travels to production on every deploy.
    """
    from analysis.learning_snapshot import get_snapshot_info
    return get_snapshot_info()


@router.post("/admin/learning-snapshot/export", tags=["Admin"])
async def export_learning_snapshot(background_tasks: BackgroundTasks) -> dict:
    """
    Export all llm_learnings rows + Kraken adaptive_params to
    data/learning_snapshot.json.  Run this before deploying to ensure
    production starts with all accumulated knowledge.
    """
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


@router.post("/admin/learning-snapshot/seed", tags=["Admin"])
async def seed_learning_from_snapshot() -> dict:
    """
    Manually seed llm_learnings from the snapshot file.
    Normally runs automatically at startup on a fresh database.
    Only inserts if the table is currently empty.
    """
    from analysis.learning_snapshot import seed_from_snapshot
    return seed_from_snapshot()


@router.get("/admin/token-usage", tags=["Admin"])
async def get_token_usage() -> dict:
    """
    Per-call-type Groq token usage breakdown for today.

    Returns:
      - tokens_used_today: total tokens consumed since midnight UTC
      - tokens_remaining: tokens left in the daily budget
      - pct_used: % of budget consumed
      - by_call_type: tokens broken down by regime / crypto / commentary / unknown
      - cache_stats: LLM response cache hit/miss rates and live entries
    """
    from analysis.groq_budget import budget as _gb
    from analysis.llm_response_cache import llm_cache as _lc
    breakdown = _gb.token_usage_breakdown()
    breakdown["cache_stats"] = _lc.stats()
    return breakdown


@router.post("/admin/llm-cache/invalidate", tags=["Admin"])
async def invalidate_llm_cache() -> dict:
    """
    Manually clear the LLM response cache (forces a fresh Groq call on the next cycle).
    Useful after major market events or when you want to guarantee fresh analysis.
    """
    from analysis.llm_response_cache import llm_cache as _lc
    _lc.invalidate()
    return {"status": "cleared", "message": "LLM response cache invalidated — next cycle will call Groq API"}


@router.get("/admin/risk-profile", tags=["Admin"])
async def get_risk_profile() -> dict:
    """
    Live Alpaca risk profile state.

    Returns the current ring-fenced %, deployed %, reserve buffer, and
    single-position cap computed from the live Alpaca account balance and
    open positions.

    Fields:
      - name                    : "alpaca"
      - total_equity_usd        : Current account equity in USD
      - deployed_usd            : Total USD tied up in open positions
      - ring_fenced_pct         : % of equity always held in safe assets (60%)
      - ring_fenced_usd         : USD value of the ring-fenced portion
      - deployable_ceiling_pct  : % available for active deployment (40%)
      - deployable_ceiling_usd  : USD ceiling for active positions
      - reserve_pct             : Additional cash buffer within deployable (18%)
      - active_ceiling_usd      : Effective deployment ceiling (after reserve)
      - reserve_buffer_usd      : Remaining headroom — positive = room to deploy
      - deployed_pct_of_ceiling : deployed_usd / active_ceiling_usd × 100
      - max_single_position_usd : Hard cap per individual position (15% of equity)
      - daily_loss_limit_usd    : USD drawdown that would trip the kill-switch (5%)
      - is_breached             : True if deployed > active_ceiling (risk breach)
    """
    import sys as _sys, os as _os
    _repo_root = _os.path.join(_os.path.dirname(__file__), "..")
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    from shared.risk_profile import RiskProfile

    # Tickers that are treated as ring-fenced / safe-harbour assets.
    # SGOV = cash proxy (short-term treasuries, used for 0-Kelly slots)
    # JEPQ = vault / profit-sweep target — never counted as risk capital
    # These are excluded from deployed_usd so the profile correctly reflects
    # only actively risk-on capital.
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


@router.get("/admin/gemini-audit-status", tags=["Admin"])
async def get_gemini_audit_status() -> dict:
    """
    Return the most recent Gemini self-critic audit result from
    logs/veto_conditions.json.

    Fields when the auditor has run (status = "ok"):
      - generated_at    : ISO-8601 UTC timestamp of when the audit ran
      - valid_until     : ISO-8601 UTC expiry (generated_at + 24 h)
      - vetoed_tickers  : list of ticker symbols blocked today
      - conditions      : list of structured risk-rule overrides
      - critique_summary: 2–4 sentence prose summary
      - critique_flags  : list of specific issues found
      - overall_verdict : "CLEAN" | "CAUTION" | "HOLD"
      - veto_status     : live veto cache state from the enforcer

    Fields when the auditor has not yet run (status = "not_run"):
      - message         : human-readable explanation

    The auditor job runs at 04:15 AM ET Monday–Friday.
    Use POST /admin/gemini-audit/run to trigger it manually.
    """
    from analysis.gemini_auditor import get_last_gemini_audit
    from core.veto_enforcer import get_veto_status

    result = get_last_gemini_audit()
    veto_status = get_veto_status()
    result["veto_status"] = veto_status
    result["veto_count"]  = veto_status.get("active_veto_count", 0)
    result["last_run"]    = result.get("generated_at")
    return result


@router.post("/admin/gemini-audit/run", tags=["Admin"])
async def trigger_gemini_audit(background_tasks: BackgroundTasks) -> dict:
    """
    Manually trigger the Gemini self-critic auditor in the background.

    The job writes logs/veto_conditions.json when complete.
    Poll GET /admin/gemini-audit-status to see the result.
    """
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


@router.get("/correlation", tags=["Analytics"])
async def correlation_matrix() -> dict:
    from data.yfinance_client import get_cached_market_data, fetch_market_data
    market_data = get_cached_market_data()
    if not market_data:
        try:
            logger.info("Correlation | Cache empty — fetching market data on demand")
            market_data = await fetch_market_data(period="3mo", crypto_only=False)
        except Exception as _fe:
            logger.warning(f"Correlation | On-demand fetch failed: {_fe}")
            return {"error": "Unable to fetch market data for correlation", "matrix": {}, "tickers": []}

    by_ticker = market_data.get("by_ticker", {})
    positions = []
    try:
        positions = get_positions()
    except Exception:
        pass

    held_symbols = [p["symbol"] for p in positions] if positions else []
    tickers_to_compare = held_symbols if len(held_symbols) >= 2 else list(by_ticker.keys())[:10]

    returns_map: dict[str, list[float]] = {}
    for ticker in tickers_to_compare:
        lookup = ticker.replace("/", "")
        data = by_ticker.get(ticker, by_ticker.get(lookup, {}))
        closes = data.get("closes")
        if closes and len(closes) >= 20:
            rets = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes))]
            returns_map[ticker] = rets[-30:]

    valid_tickers = list(returns_map.keys())
    if len(valid_tickers) < 2:
        return {"error": "Need at least 2 tickers with data", "matrix": {}, "tickers": valid_tickers}

    min_len = min(len(returns_map[t]) for t in valid_tickers)
    trimmed = {t: returns_map[t][-min_len:] for t in valid_tickers}

    import numpy as np
    matrix: dict[str, dict[str, float]] = {}
    warnings_list: list[dict] = []
    for i, t1 in enumerate(valid_tickers):
        matrix[t1] = {}
        for j, t2 in enumerate(valid_tickers):
            if i == j:
                matrix[t1][t2] = 1.0
            else:
                corr = float(np.corrcoef(trimmed[t1], trimmed[t2])[0, 1])
                matrix[t1][t2] = round(corr, 3)
                if abs(corr) > 0.85 and i < j:
                    warnings_list.append({
                        "pair": [t1, t2],
                        "correlation": round(corr, 3),
                        "risk": "HIGH" if abs(corr) > 0.95 else "ELEVATED",
                    })

    return {
        "tickers": valid_tickers,
        "matrix": matrix,
        "warnings": warnings_list,
        "held_positions": held_symbols,
    }


@router.get("/calendar", tags=["Analytics"])
async def economic_calendar(days_ahead: int = 7) -> dict:
    blackout = is_blackout_active()
    upcoming = get_upcoming_events(days_ahead=days_ahead)
    return {
        "blackout": blackout,
        "upcoming_events": upcoming,
        "event_count": len(upcoming),
    }


@router.get("/sentiment", tags=["Analytics"])
async def sentiment_endpoint(force: bool = False) -> dict:
    return get_sentiment(force=force)


@router.get("/onchain", tags=["Analytics"])
async def onchain_endpoint(force: bool = False) -> dict:
    return get_onchain_data(force=force)


@router.get("/performance/attribution", tags=["Performance"])
async def performance_attribution() -> dict:
    return compute_attribution()


@router.get("/performance/risk-metrics", tags=["Performance"])
async def risk_metrics() -> dict:
    snapshots = get_performance_snapshots(limit=90)
    if not snapshots:
        # Fallback: compute approximate metrics from closed trades in the DB
        try:
            import numpy as np
            from db.postgres import get_conn as _gc
            with _gc() as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute(
                        "SELECT pnl_percentage FROM trades WHERE status LIKE 'Closed_%' ORDER BY date ASC"
                    )
                    _rows = _cur.fetchall()
            trade_returns = [float(r[0]) / 100.0 for r in _rows if r[0] is not None]
            # Also add Kraken trade returns so risk metrics combine both bots
            for _kt in _load_kraken_journal_trades():
                if _kt.get("pnl_percentage") is not None:
                    trade_returns.append(float(_kt["pnl_percentage"]) / 100.0)
            if len(trade_returns) >= 2:
                arr = np.array(trade_returns)
                mean_ret = float(np.mean(arr))
                std_ret = float(np.std(arr, ddof=1))
                # Treat each trade as ~30-day hold; scale to annualised
                periods_per_year = 252 / 30
                rf_per_period = 0.05 / periods_per_year
                sharpe = float((mean_ret - rf_per_period) / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else None
                downside = arr[arr < 0]
                downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else None
                sortino = float((mean_ret - rf_per_period) / downside_std * np.sqrt(periods_per_year)) if downside_std and downside_std > 0 else None
                max_dd = round(abs(float(np.min(arr))) * 100, 2)
                ann_return = round(mean_ret * periods_per_year * 100, 2)
                calmar = round(ann_return / max_dd, 3) if max_dd > 0 else None
                vol_annual = round(std_ret * np.sqrt(periods_per_year) * 100, 2) if std_ret > 0 else None
                return {
                    "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
                    "sortino_ratio": round(sortino, 3) if sortino is not None else None,
                    "max_drawdown_pct": max_dd,
                    "calmar_ratio": calmar,
                    "volatility_annual_pct": vol_annual,
                    "annualised_return_pct": ann_return,
                    "data_points": len(trade_returns),
                    "period_days": len(trade_returns) * 30,
                    "source": "trade_journal",
                    "message": f"Estimated from {len(trade_returns)} closed trades (30-day hold assumption)",
                }
        except Exception as _te:
            logger.warning(f"Risk Metrics | Trade journal fallback failed: {_te}")
        # Last resort: single data point from account state
        try:
            account = get_account()
            equity = float(account["equity"])
            last_equity = float(account.get("last_equity", account["equity"]))
            if last_equity > 0:
                dd = max(0, (last_equity - equity) / last_equity * 100)
                return {
                    "sharpe_ratio": None,
                    "sortino_ratio": None,
                    "max_drawdown_pct": round(dd, 2),
                    "calmar_ratio": None,
                    "volatility_annual_pct": None,
                    "annualised_return_pct": None,
                    "data_points": 1,
                    "period_days": 1,
                    "message": "Awaiting post-mortem snapshots — run a post-mortem to populate full risk metrics",
                }
        except Exception:
            pass
        return {
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown_pct": None,
            "calmar_ratio": None,
            "volatility_annual_pct": None,
            "annualised_return_pct": None,
            "data_points": 0,
            "period_days": 0,
            "message": "No performance data yet — run a post-mortem cycle to start tracking",
        }

    import numpy as np
    daily_returns = [s["daily_pnl_pct"] / 100.0 for s in snapshots if s.get("daily_pnl_pct") is not None]

    if len(daily_returns) < 2:
        return {
            "sharpe_ratio": None, "sortino_ratio": None,
            "max_drawdown_pct": None, "calmar_ratio": None,
            "volatility_annual_pct": None, "data_points": len(daily_returns),
        }

    arr = np.array(daily_returns)
    mean_ret = float(np.mean(arr))
    std_ret = float(np.std(arr, ddof=1))
    rf_daily = 0.05 / 252

    sharpe = float((mean_ret - rf_daily) / std_ret * np.sqrt(252)) if std_ret > 0 else None

    downside = arr[arr < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else None
    sortino = float((mean_ret - rf_daily) / downside_std * np.sqrt(252)) if downside_std and downside_std > 0 else None

    equities = [s["equity"] for s in snapshots if s.get("equity")]
    max_dd = 0.0
    peak = equities[0] if equities else 0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    ann_return = mean_ret * 252 * 100
    calmar = round(ann_return / max_dd, 3) if max_dd > 0 else None
    vol_annual = round(std_ret * np.sqrt(252) * 100, 2)

    return {
        "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
        "sortino_ratio": round(sortino, 3) if sortino is not None else None,
        "max_drawdown_pct": round(max_dd, 2),
        "calmar_ratio": calmar,
        "volatility_annual_pct": vol_annual,
        "annualised_return_pct": round(ann_return, 2),
        "data_points": len(daily_returns),
        "period_days": len(snapshots),
    }


def _build_synthetic_equity_curve() -> list[dict]:
    """Build a synthetic equity curve from trade history when DB has insufficient real snapshots."""
    import json as _j
    from pathlib import Path as _P
    from collections import defaultdict
    from datetime import datetime, timedelta

    alpaca_start = 100_000.0
    kraken_start = 100_000.0

    # --- Kraken trades (have exact pnl_usd) ---
    kraken_daily_pnl: dict = defaultdict(float)
    try:
        _pf_path = _P("../kraken-bot/paper_portfolio.json")
        if _pf_path.exists():
            _pf = _j.loads(_pf_path.read_text())
            kraken_start = float(_pf.get("starting_balance_usd", 100_000.0))
            for _t in _pf.get("all_trades", []):
                _d = (_t.get("closed_at") or "")[:10]
                if _d and _t.get("pnl_usd") is not None:
                    kraken_daily_pnl[_d] += float(_t["pnl_usd"])
    except Exception:
        pass

    # --- Alpaca trades: use pnl_percentage with 5% position sizing estimate ---
    alpaca_daily_pnl: dict = defaultdict(float)
    try:
        from db.postgres import get_conn as _gc2
        with _gc2() as _conn2:
            with _conn2.cursor() as _cur2:
                _cur2.execute(
                    "SELECT date, pnl_percentage FROM trades WHERE status LIKE 'Closed_%' ORDER BY date ASC"
                )
                for _row in _cur2.fetchall():
                    if _row[0] and _row[1] is not None:
                        _d = str(_row[0])
                        alpaca_daily_pnl[_d] += (alpaca_start * 0.05) * (float(_row[1]) / 100.0)
    except Exception:
        pass

    all_dates = sorted(set(list(kraken_daily_pnl.keys()) + list(alpaca_daily_pnl.keys())))
    if not all_dates:
        return []

    first_dt = datetime.strptime(all_dates[0], "%Y-%m-%d")
    start_ts = (first_dt - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")

    rows: list[dict] = [{
        "id": 0, "ts": start_ts,
        "alpaca_equity": alpaca_start, "kraken_equity": kraken_start,
        "total_equity": alpaca_start + kraken_start,
        "regime": None, "source": "synthetic_start",
    }]

    a_eq = alpaca_start
    k_eq = kraken_start
    for _d in all_dates:
        a_eq = round(a_eq + alpaca_daily_pnl.get(_d, 0.0), 2)
        k_eq = round(k_eq + kraken_daily_pnl.get(_d, 0.0), 2)
        rows.append({
            "id": 0, "ts": f"{_d}T12:00:00",
            "alpaca_equity": a_eq, "kraken_equity": k_eq,
            "total_equity": round(a_eq + k_eq, 2),
            "regime": None, "source": "synthetic",
        })

    return rows


@router.get("/performance/equity-curve", tags=["Analytics"])
async def equity_curve_endpoint(limit: int = 500) -> dict:
    """
    Return the last `limit` equity snapshots (oldest-first) for the equity curve chart.
    Falls back to a synthetic curve built from trade history when DB has < 5 real snapshots.
    Each row: {id, ts, alpaca_equity, kraken_equity, total_equity, regime, source}
    """
    from db.postgres import get_equity_curve
    rows = get_equity_curve(limit=min(limit, 2000))
    if len(rows) < 5:
        synthetic = _build_synthetic_equity_curve()
        if synthetic:
            # Append any real snapshots that aren't already represented by synthetic dates
            real_dates = {r["ts"][:10] for r in rows}
            synthetic_dates = {r["ts"][:10] for r in synthetic}
            extra_real = [r for r in rows if r["ts"][:10] not in synthetic_dates]
            rows = synthetic + extra_real
            rows.sort(key=lambda r: r["ts"])
    return {"count": len(rows), "snapshots": rows}


@router.post("/backtest", tags=["Analytics"])
async def run_backtest_endpoint(lookback_days: int = 90) -> dict:
    from data.yfinance_client import get_cached_market_data, fetch_market_data
    market_data = get_cached_market_data()
    if not market_data:
        try:
            logger.info("Backtest | Cache empty — fetching 1y market data on demand (backtester needs 200-day warmup)")
            market_data = await fetch_market_data(period="1y", crypto_only=False)
        except Exception as _fe:
            raise HTTPException(status_code=503, detail=f"Unable to fetch market data for backtesting: {_fe}")

    bars_by_ticker: dict[str, list[dict]] = {}
    for ticker, data in market_data.get("by_ticker", {}).items():
        if "bars" in data:
            bars_by_ticker[ticker] = data["bars"]

    try:
        acct = get_account()
        initial_eq = acct["equity"]
    except Exception:
        initial_eq = 100000.0

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: run_backtest(bars_by_ticker, initial_equity=initial_eq, lookback_days=lookback_days)
    )
    return result


@router.get("/data/snapshot", tags=["Debug"])
async def data_snapshot() -> dict:
    """
    Debug endpoint: fetches macro, market, and news data concurrently.
    Returns raw ingestion client output.
    """
    from data.fred_client import fetch_macro_data
    from data.yfinance_client import fetch_market_data
    from data.news_client import fetch_news

    macro_data, market_data, news_data = await asyncio.gather(
        fetch_macro_data(lookback_days=14),
        fetch_market_data(period="1mo"),
        fetch_news(lookback_days=2),
    )
    return {
        "macro": macro_data,
        "market_summary": {
            ticker: {
                "price": v.get("latest_price"),
                "return_1d_pct": v.get("return_1d_pct"),
            }
            for ticker, v in market_data["by_ticker"].items()
            if "error" not in v
        },
        "news_headlines_count": len(news_data["all_headlines"]),
        "news_sample": news_data["all_headlines"][:5],
    }



# ── Kraken Bot Status ─────────────────────────────────────────────────────────

@router.get("/kraken/status", tags=["Kraken Bot"])
async def kraken_status() -> dict:
    """
    Read and return the Kraken bot's status.json file.
    Written by kraken-bot/main.py after every trading cycle.
    Returns a safe empty-state if the bot hasn't run yet.
    """
    import json as _json
    from pathlib import Path as _Path

    status_file = _Path("../kraken-bot/status.json")  # server cwd = trading-platform/
    if not status_file.exists():
        return {
            "bot_name":         "Davy Jones' Portfolio",
            "status":           "not_started",
            "last_updated":     None,
            "cycle_count":      0,
            "total_equity_usd": 0,
            "deployed_usd":     0,
            "deployed_pct":     0,
            "deployable_ceiling_pct": 80,
            "cash_reserve_pct": 20,
            "open_positions":   [],
            "position_count":   0,
            "max_positions":    3,
            "circuit_breaker":  {"active": False, "paused_until": None},
            "recent_trades":    [],
            "error":            None,
        }
    try:
        return _json.loads(status_file.read_text())
    except Exception as exc:
        logger.warning(f"[kraken/status] Could not parse status.json ({exc}) — returning empty state")
        return {
            "bot_name":         "Davy Jones' Portfolio",
            "status":           "not_started",
            "last_updated":     None,
            "cycle_count":      0,
            "total_equity_usd": 0,
            "deployed_usd":     0,
            "deployed_pct":     0,
            "deployable_ceiling_pct": 80,
            "cash_reserve_pct": 20,
            "open_positions":   [],
            "position_count":   0,
            "max_positions":    3,
            "circuit_breaker":  {"active": False, "paused_until": None},
            "recent_trades":    [],
            "error":            f"status.json parse error: {exc}",
        }


# ── Kraken Bot — AI Narrative Commentary ──────────────────────────────────────

@router.get("/kraken/commentary", tags=["Kraken Bot"])
async def kraken_commentary(force: bool = False) -> dict:
    """
    Generate Davy Jones' AI narrative: thought process, learnings, and future
    behavioural adjustments.  Cached for 30 minutes.
    """
    global _kraken_commentary_cache
    import json as _json
    from pathlib import Path as _Path

    now = time.time()
    cache_age = now - _kraken_commentary_cache["ts"]

    if not force and _kraken_commentary_cache["text"] and cache_age < COMMENTARY_TTL_SECONDS:
        return {
            "commentary": _kraken_commentary_cache["text"],
            "generated_at": _kraken_commentary_cache["generated_at"],
            "cached": True,
            "cache_age_seconds": int(cache_age),
        }

    from analysis.groq_budget import budget as _groq_budget
    if not _groq_budget.can_call_commentary("kraken", force=force):
        if _kraken_commentary_cache["text"]:
            return {
                "commentary": _kraken_commentary_cache["text"],
                "generated_at": _kraken_commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "throttled": True,
                "budget_exhausted": _groq_budget.budget_exhausted(),
            }
        _exhausted = _groq_budget.budget_exhausted()
        return {
            "commentary": (
                "AI narrative paused — daily token budget reached. Trades are running normally; all entry/exit decisions are purely algorithmic (Z-score, RSI, VPIN) and never depend on this commentary. Narrative resumes tomorrow at midnight UTC."
                if _exhausted else
                "AI narrative paused — daily call limit reached. Trades are running normally; all entry/exit decisions are purely algorithmic (Z-score, RSI, VPIN) and never depend on this commentary. Narrative resumes tomorrow at midnight UTC."
            ),
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "throttled": True,
            "budget_exhausted": _exhausted,
        }

    status_file = _Path("../kraken-bot/status.json")
    if not status_file.exists():
        return {
            "commentary": "Davy Jones is still getting his sea legs — bot hasn't run yet. Check back shortly.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "unavailable": True,
        }

    try:
        kdata = _json.loads(status_file.read_text())
    except Exception as exc:
        logger.warning(f"Kraken commentary: could not read status file: {exc}")
        return {
            "commentary": "Charts are foggy — status file temporarily unreadable. Davy Jones sails on.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "error": str(exc),
            "unavailable": True,
        }

    positions     = kdata.get("open_positions", [])
    recent_trades = kdata.get("recent_trades", [])
    signals       = kdata.get("signals", [])
    wins          = [t for t in recent_trades if t.get("pnl_pct", 0) > 0]
    losses        = [t for t in recent_trades if t.get("pnl_pct", 0) <= 0]
    win_rate      = (len(wins) / len(recent_trades) * 100) if recent_trades else None

    pos_text = "\n".join(
        f"  {p.get('side','').upper()} {p['symbol']}: "
        f"entry ${p.get('entry_price', 0):.4f}, now ${p.get('current_price', 0):.4f}, "
        f"P&L {p.get('pnl_pct', 0):+.2f}%"
        for p in positions
    ) or "  (no open positions)"

    wins_text = "\n".join(
        f"  WIN: {t['symbol']} {t.get('pnl_pct', 0):+.2f}% ({t.get('side', '')})"
        for t in wins[-3:]
    ) or "  (none yet)"

    losses_text = "\n".join(
        f"  LOSS: {t['symbol']} {t.get('pnl_pct', 0):+.2f}% ({t.get('side', '')})"
        for t in losses[-3:]
    ) or "  (none yet)"

    signal_text = "\n".join(
        f"  {s['symbol']}: RSI={s.get('rsi', 0):.1f} Z={s.get('z_score', 0):+.2f} → {s.get('signal_type', 'watching')}"
        for s in signals[:6]
    ) or "  (scanning markets)"

    try:
        from data.sentiment import get_sentiment
        sent = get_sentiment()
        cfg  = sent.get("crypto_fear_greed", {})
        sentiment_line = f"Crypto Fear&Greed: {cfg.get('value','?')} ({cfg.get('label','?')})"
    except Exception:
        sentiment_line = ""

    user_prompt = f"""
Davy Jones' current open positions (Kraken 24/7 mean-reversion crypto bot):
{pos_text}

Recent wins (reinforcing behaviour):
{wins_text}

Recent losses (behavioural corrections needed):
{losses_text}

Signal scanner snapshot:
{signal_text}

Statistics: {len(recent_trades)} total trades{f', win rate {win_rate:.0f}%' if win_rate is not None else ''}
Equity: ${kdata.get('total_equity_usd', 0):,.2f} | Deployed: {kdata.get('deployed_pct', 0):.0f}% of {kdata.get('deployable_ceiling_pct', 80)}% ceiling
Cycle #{kdata.get('cycle_count', 0)} | Cash reserve: {kdata.get('cash_reserve_pct', 20)}%
{sentiment_line}
"""

    system_prompt = (
        "You are 'Davy Jones' — a relentless 24/7 crypto mean-reversion trading AI with the soul of a seasoned "
        "sailor who reads market currents like ocean tides. In exactly 3 punchy sentences: "
        "(1) your sharpest read on the current crypto signals and any open positions, "
        "(2) one concrete learning from your recent wins or losses, "
        "(3) one specific behavioural adjustment you're making going forward. "
        "Reference specific coin names, RSI levels, or Z-scores when available. "
        "Direct, confident, nautical flair optional. Plain text only, no markdown."
    )

    def _blocking_call() -> tuple[str, int]:
        from groq import Groq
        from config.settings import settings as _settings
        client = Groq(api_key=_settings.groq_api_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.72,
            max_tokens=180,
        )
        tokens = resp.usage.total_tokens if resp.usage else 0
        return resp.choices[0].message.content.strip(), tokens

    try:
        loop = asyncio.get_event_loop()
        commentary, tokens_used = await loop.run_in_executor(None, _blocking_call)
        _groq_budget.consume(tokens_used, call_type="commentary")
        if not force:
            _groq_budget.record_commentary_call("kraken")
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        _kraken_commentary_cache = {"text": commentary, "generated_at": generated_at, "ts": now}
        _persist_commentary_caches()
        logger.info(f"Kraken AI commentary regenerated successfully (force={force}, tokens={tokens_used})")
        return {"commentary": commentary, "generated_at": generated_at, "cached": False, "cache_age_seconds": 0}
    except Exception as exc:
        logger.error(f"Kraken AI commentary generation failed: {exc}")
        # Back off 5 min so the next auto-refresh does not immediately retry Groq
        _kraken_commentary_cache["ts"] = now - COMMENTARY_TTL_SECONDS + 300
        if _kraken_commentary_cache["text"]:
            return {
                "commentary": _kraken_commentary_cache["text"],
                "generated_at": _kraken_commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "error": str(exc),
            }
        return {
            "commentary": "Davy Jones' AI is resting — daily token limit reached. The seas will clear by tomorrow.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "error": str(exc),
            "unavailable": True,
        }


# ── Kraken Bot — Performance Metrics ──────────────────────────────────────────
# Separate from the Alpaca performance endpoints (/performance/history,
# /performance/summary). This reads exclusively from kraken-bot/status.json
# which is written only by kraken-bot/main.py.
# The Alpaca trading system never touches this file.

@router.get("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_auto_trading_status() -> dict:
    """Return the current Kraken bot pause state from control.json."""
    import json as _json
    from pathlib import Path as _Path
    ctrl = _Path("../kraken-bot/control.json")  # server cwd = trading-platform/
    if not ctrl.exists():
        return {"bot_paused": False}
    try:
        return {"bot_paused": bool(_json.loads(ctrl.read_text()).get("bot_paused", False))}
    except Exception:
        return {"bot_paused": False}


class KrakenControlRequest(BaseModel):
    bot_paused: bool


@router.post("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_toggle_auto_trading(request: KrakenControlRequest) -> dict:
    """
    Pause or resume the Kraken bot by writing control.json.
    The bot reads this file at the start of each cycle.
    The workflow keeps running — only signal processing is paused.
    """
    import json as _json
    from pathlib import Path as _Path
    ctrl = _Path("../kraken-bot/control.json")  # server cwd = trading-platform/
    ctrl.write_text(_json.dumps({"bot_paused": request.bot_paused}, indent=2))
    logger.info(f"Kraken bot {'PAUSED' if request.bot_paused else 'RESUMED'} via dashboard toggle")
    return {"bot_paused": request.bot_paused, "message": "Kraken bot paused" if request.bot_paused else "Kraken bot resumed"}


@router.get("/kraken/performance", tags=["Kraken Bot"])
async def kraken_performance() -> dict:
    """
    Derive performance statistics from the Kraken bot's status.json.

    DATA SOURCE: kraken-bot/status.json (Kraken exchange, separate capital pool)
    NOT RELATED TO: /performance/history or /performance/summary (Alpaca data)

    Returns computed metrics over the recent_trades history:
      - trade count, win rate, total/best/worst/avg P&L
      - per-symbol breakdown
      - the full recent trade list
    """
    import json as _json
    from pathlib import Path as _Path

    status_file = _Path("../kraken-bot/status.json")  # server cwd = trading-platform/

    # Empty state — bot hasn't run yet
    empty: dict = {
        "data_source":     "kraken-bot/status.json",
        "exchange":        "Kraken (crypto, independent from Alpaca)",
        "has_data":        False,
        "total_trades":    0,
        "win_count":       0,
        "loss_count":      0,
        "win_rate_pct":    None,
        "total_pnl_pct":   None,
        "total_pnl_usd":   None,
        "best_trade_pct":  None,
        "worst_trade_pct": None,
        "avg_trade_pct":   None,
        "by_symbol":       {},
        "recent_trades":   [],
        "current_equity":  0,
        "cycle_count":     0,
        "bot_status":      "not_started",
    }

    if not status_file.exists():
        return empty

    try:
        status = _json.loads(status_file.read_text())
    except Exception as exc:
        logger.warning(f"[kraken/performance] Could not parse status.json ({exc}) — returning empty state")
        return empty

    trades: list[dict] = status.get("recent_trades", [])

    if not trades:
        empty["bot_status"]    = status.get("status", "not_started")
        empty["current_equity"] = status.get("total_equity_usd", 0)
        empty["cycle_count"]   = status.get("cycle_count", 0)
        return empty

    pnl_list   = [t["pnl_pct"] for t in trades]
    pnl_usd    = [t["pnl_usd"] for t in trades]
    wins       = [p for p in pnl_list if p > 0]
    losses     = [p for p in pnl_list if p <= 0]
    win_rate   = (len(wins) / len(trades)) * 100 if trades else 0

    # Per-symbol aggregation
    by_symbol: dict[str, dict] = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "wins": 0, "total_pnl_pct": 0.0, "total_pnl_usd": 0.0}
        by_symbol[sym]["trades"]        += 1
        by_symbol[sym]["total_pnl_pct"] += t["pnl_pct"]
        by_symbol[sym]["total_pnl_usd"] += t["pnl_usd"]
        if t["pnl_pct"] > 0:
            by_symbol[sym]["wins"] += 1

    for sym in by_symbol:
        n = by_symbol[sym]["trades"]
        by_symbol[sym]["win_rate_pct"]  = round((by_symbol[sym]["wins"] / n) * 100, 1) if n else 0
        by_symbol[sym]["total_pnl_pct"] = round(by_symbol[sym]["total_pnl_pct"], 2)
        by_symbol[sym]["total_pnl_usd"] = round(by_symbol[sym]["total_pnl_usd"], 2)

    return {
        "data_source":     "kraken-bot/status.json",
        "exchange":        "Kraken (crypto, independent from Alpaca)",
        "has_data":        True,
        "total_trades":    len(trades),
        "win_count":       len(wins),
        "loss_count":      len(losses),
        "win_rate_pct":    round(win_rate, 1),
        "total_pnl_pct":   round(sum(pnl_list), 2),
        "total_pnl_usd":   round(sum(pnl_usd), 2),
        "best_trade_pct":  round(max(pnl_list), 2),
        "worst_trade_pct": round(min(pnl_list), 2),
        "avg_trade_pct":   round(sum(pnl_list) / len(pnl_list), 2),
        "by_symbol":       by_symbol,
        "recent_trades":   trades,
        "current_equity":  status.get("total_equity_usd", 0),
        "cycle_count":     status.get("cycle_count", 0),
        "bot_status":      status.get("status", "unknown"),
    }


# ── Diagnostic Export Report ────────────────────────────────────────────────────

@router.get("/export/report", tags=["Export"])
async def export_diagnostic_report() -> dict:
    """
    Generate a comprehensive plain-text diagnostic report covering both trading bots.
    Intended to be pasted into an LLM (Claude / Gemini / GPT) for strategy analysis.
    Returns: { report: str, generated_at: str, char_count: int }
    """
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime as _dt, timezone as _tz
    from analysis.attribution import compute_attribution as _attr
    from analysis.learning_journal import get_journal_entries as _lj
    from analysis.groq_budget import budget as _groq_budget

    now_utc = _dt.now(_tz.utc)
    ts = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

    def _c(v, decimals=2, prefix="$"):
        """Format a number as currency or plain float."""
        if v is None:
            return "N/A"
        if prefix == "$":
            return f"${v:,.{decimals}f}"
        return f"{v:.{decimals}f}"

    def _pct(v, decimals=2):
        if v is None:
            return "N/A"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.{decimals}f}%"

    def _safe(d, *keys, default="N/A"):
        for k in keys:
            if not isinstance(d, dict):
                return default
            d = d.get(k, None)
            if d is None:
                return default
        return d if d is not None else default

    lines: list[str] = []
    W = "═" * 80

    def h1(title: str):
        lines.append(W)
        lines.append(f"  {title}")
        lines.append(W)

    def h2(title: str):
        lines.append("")
        lines.append(f"── {title} {'─' * max(0, 74 - len(title))}")

    def row(label: str, value: str, indent: int = 2):
        lines.append(f"{'  ' * indent}{label:<32}{value}")

    # ─────────────────────────────────────────────────────────────────────────
    # HEADER
    # ─────────────────────────────────────────────────────────────────────────
    lines.append(W)
    lines.append("  QUANTITATIVE TRADING PLATFORM — AI DIAGNOSTIC REPORT")
    lines.append(f"  Generated: {ts}")
    lines.append("  PURPOSE: Paste into Claude / Gemini / ChatGPT for strategy analysis.")
    lines.append("           Contains all trade history, AI reasoning, risk parameters,")
    lines.append("           entry/exit conditions, and performance data for both bots.")
    lines.append(W)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1: SYSTEM STATUS
    # ─────────────────────────────────────────────────────────────────────────
    try:
        ks_state   = ks_get_state()
        mkt_open   = is_market_open()
        sched_jobs = get_job_status()
        last_run   = get_last_run()
        groq_tok   = _groq_budget.remaining if hasattr(_groq_budget, "remaining") else None
        groq_max   = getattr(_groq_budget, "daily_limit", 100_000)
        groq_used  = (groq_max - groq_tok) if groq_tok is not None else None
    except Exception:
        ks_state = {}; mkt_open = False; sched_jobs = []; last_run = {}; groq_tok = None; groq_used = None; groq_max = 100_000

    h1("SECTION 1: SYSTEM STATUS & RISK ENVIRONMENT")
    row("Report timestamp:", ts)
    row("Market status:", "OPEN (US Equities)" if mkt_open else "CLOSED (After Hours / Weekend)")
    row("Kill switch:", "TRIPPED — ALL TRADING HALTED" if ks_state.get("tripped") else "ARMED (not tripped — normal)")
    row("Daily drawdown:", f"{_pct(ks_state.get('drawdown_pct', 0), 3)} / {_pct(ks_state.get('threshold_pct', 5.0), 1)} threshold")
    row("Opening equity baseline:", _c(ks_state.get("opening_equity")))
    row("Pending liquidation:", "YES — deferred close queued for market open" if ks_state.get("pending_liquidation") else "NO")
    if groq_tok is not None:
        row("Groq token budget:", f"{groq_tok:,} remaining / {groq_max:,} daily ({groq_used:,} used)")
    else:
        row("Groq token budget:", "Unknown")

    last_regime = last_run.get("last_regime") or "Unknown"
    last_status = last_run.get("last_run_status") or "Unknown"
    last_run_ts = last_run.get("last_run_utc") or "Never"
    row("Last analysis cycle:", f"{last_run_ts} | status={last_status}")
    row("Current market regime:", last_regime)

    if sched_jobs:
        lines.append("")
        lines.append("  Scheduler (8 jobs):")
        for job in sched_jobs:
            lines.append(f"    • {job.get('name','?'):<45} next: {str(job.get('next_fire_utc','?'))[:19]}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2: ALPACA BOT — QUANTITATIVE EQUITY PLATFORM
    # ─────────────────────────────────────────────────────────────────────────
    try:
        acct      = get_account()
        positions = get_positions()
    except Exception:
        acct = {}; positions = []

    equity      = acct.get("equity", 0) or 0
    cash        = acct.get("cash", 0) or 0
    buying_pwr  = acct.get("buying_power", 0) or 0
    start_cap   = 100_000.0
    pnl_usd     = equity - start_cap
    pnl_pct     = (pnl_usd / start_cap) * 100

    h1("SECTION 2: ALPACA BOT — QUANTITATIVE EQUITY PLATFORM (US Equities)")
    h2("PORTFOLIO OVERVIEW")
    row("Capital pool:", "US Equity — Paper Trading via Alpaca")
    row("Starting capital:", _c(start_cap))
    row("Current equity:", _c(equity))
    row("Total P&L:", f"{_c(pnl_usd)} ({_pct(pnl_pct)})")
    row("Available cash:", _c(cash))
    row("Buying power:", _c(buying_pwr))
    row("Open positions:", str(len(positions)))

    # ── Current positions ──
    h2("CURRENT OPEN POSITIONS (ALPACA)")
    if not positions:
        lines.append("  No open positions.")
    for p in positions:
        sym         = p.get("symbol", "?")
        qty         = p.get("qty", 0)
        entry       = p.get("avg_entry_price")
        current     = p.get("current_price")
        mval        = p.get("market_value")
        upl         = p.get("unrealized_pl")
        uplpc       = (p.get("unrealized_plpc") or 0) * 100
        ac          = p.get("asset_class", "unknown")
        conv        = p.get("conviction_score")
        kelly       = p.get("kelly_fraction")
        sl_pct      = p.get("stop_loss_pct")
        tp_pct      = p.get("take_profit_pct")
        sl_px       = p.get("stop_loss_price")
        tp_px       = p.get("take_profit_price")
        thesis      = p.get("original_thesis") or "N/A"
        is_vault    = sym in ("JEPQ",)

        lines.append(f"\n  {sym}{' [PROFIT VAULT — protected from liquidation]' if is_vault else ''}")
        row("Qty:", f"{qty:.6f} shares" if qty else "N/A", indent=2)
        row("Avg entry price:", _c(entry), indent=2)
        row("Current price:", _c(current), indent=2)
        row("Market value:", _c(mval), indent=2)
        row("Unrealized P&L:", f"{_c(upl)} ({_pct(uplpc)})", indent=2)
        row("Asset class:", ac, indent=2)
        row("Conviction score:", f"{conv:.2f} / 1.0" if conv else "N/A", indent=2)
        row("Kelly fraction:", f"{(kelly or 0)*100:.2f}%" if kelly else "N/A", indent=2)
        if sl_pct:
            row("Stop loss:", f"{_pct(sl_pct)} from entry | price: {_c(sl_px)}", indent=2)
        else:
            row("Stop loss:", "N/A", indent=2)
        if tp_pct:
            row("Take profit:", f"{_pct(tp_pct)} from entry | price: {_c(tp_px)}", indent=2)
        else:
            row("Take profit:", "N/A", indent=2)
        row("Original thesis:", thesis[:120] if len(thesis) > 120 else thesis, indent=2)

    # ── Short positions summary ──────────────────────────────────────────────
    long_positions  = [p for p in positions if str(p.get("side", "long")).lower() != "short"]
    short_positions = [p for p in positions if str(p.get("side", "long")).lower() == "short"]
    bear_hedge_syms = {"SH", "PSQ", "SPXS", "SQQQ", "SRTY", "DOG"}

    h2("SHORT & BEAR-HEDGE POSITIONS (ALGO SHORT SCANNER)")
    if not short_positions:
        lines.append("  No direct short positions open.")
    else:
        total_short_exposure = sum(abs(p.get("market_value") or 0) for p in short_positions)
        total_short_pnl      = sum(p.get("unrealized_pl") or 0 for p in short_positions)
        short_exposure_pct   = (total_short_exposure / equity * 100) if equity > 0 else 0
        row("Open short positions:", str(len(short_positions)))
        row("Total short exposure:", f"{_c(total_short_exposure)} ({_pct(short_exposure_pct)} of equity)")
        row("Aggregate short P&L:", f"{_c(total_short_pnl)} (profit = positive when price falls)")
        lines.append("")
        lines.append(
            f"  {'TICKER':<8} {'QTY':>8} {'ENTRY':>10} {'CURRENT':>10} "
            f"{'MARKET VAL':>12} {'UNREAL P&L':>12}"
        )
        lines.append("  " + "-" * 66)
        for sp in short_positions:
            sym     = sp.get("symbol", "?")
            qty     = sp.get("qty", 0)
            entry   = sp.get("avg_entry_price") or 0
            curr    = sp.get("current_price") or 0
            mv      = sp.get("market_value") or 0
            upl     = sp.get("unrealized_pl") or 0
            lines.append(
                f"  {sym:<8} {qty:>8.2f} {_c(entry):>10} {_c(curr):>10} "
                f"{_c(mv):>12} {_c(upl):>12}"
            )
        lines.append("")

    # ── Bear-hedge long positions (SPXS / SQQQ / SRTY / SH / PSQ / DOG) ────
    bear_hedge_longs = [p for p in long_positions if p.get("symbol", "") in bear_hedge_syms]
    if bear_hedge_longs:
        total_bh_exposure = sum(abs(p.get("market_value") or 0) for p in bear_hedge_longs)
        total_bh_pnl      = sum(p.get("unrealized_pl") or 0 for p in bear_hedge_longs)
        bh_exposure_pct   = (total_bh_exposure / equity * 100) if equity > 0 else 0
        row("Bear-hedge ETF positions:", str(len(bear_hedge_longs)))
        row("Bear-hedge exposure:", f"{_c(total_bh_exposure)} ({_pct(bh_exposure_pct)} of equity)")
        row("Bear-hedge P&L:", _c(total_bh_pnl))
        lines.append("")
        lines.append(
            f"  {'TICKER':<8} {'QTY':>8} {'ENTRY':>10} {'CURRENT':>10} "
            f"{'MARKET VAL':>12} {'UNREAL P&L':>12} {'ENTRY_TIME'}"
        )
        lines.append("  " + "-" * 80)
        for bp in bear_hedge_longs:
            sym    = bp.get("symbol", "?")
            qty    = bp.get("qty", 0)
            entry  = bp.get("avg_entry_price") or 0
            curr   = bp.get("current_price") or 0
            mv     = bp.get("market_value") or 0
            upl    = bp.get("unrealized_pl") or 0
            et     = bp.get("entry_time") or "N/A"
            lines.append(
                f"  {sym:<8} {qty:>8.2f} {_c(entry):>10} {_c(curr):>10} "
                f"{_c(mv):>12} {_c(upl):>12} {str(et)[:19]}"
            )
        lines.append("")
    else:
        lines.append("  No bear-hedge ETF positions open.")

    # ── Latest AI allocation ──
    h2("LATEST AI ALLOCATION DECISION (GROQ LLAMA 3.3 70B)")
    last_alloc = last_run.get("last_allocation") or []
    if not last_alloc:
        lines.append("  No allocation has been generated yet. Run an analysis cycle to populate.")
    else:
        lines.append(f"  Market Regime:  {last_regime}")
        lines.append(f"  Generated:      {last_run_ts}")
        lines.append("")
        for slot in last_alloc:
            slot_n  = slot.get("slot", "?")
            ticker  = slot.get("ticker", "?")
            ac      = slot.get("asset_class", "?")
            conv    = slot.get("conviction_score")
            kelly   = slot.get("kelly_fraction")
            sl      = slot.get("stop_loss_pct")
            tp      = slot.get("take_profit_pct")
            thesis  = slot.get("thesis", "N/A")
            lines.append(f"  Slot {slot_n} — {ticker} ({ac})")
            row("Conviction:", f"{conv:.2f} / 1.0" if conv else "N/A", indent=3)
            row("Kelly fraction:", f"{(kelly or 0)*100:.2f}%" if kelly else "N/A", indent=3)
            row("Stop loss:", _pct(sl) if sl else "N/A", indent=3)
            row("Take profit:", _pct(tp) if tp else "N/A", indent=3)
            # Word-wrap thesis at 80 chars
            words = thesis.split()
            thesis_line = "      "
            for w in words:
                if len(thesis_line) + len(w) + 1 > 80:
                    lines.append(f"    AI Thesis:    {thesis_line.strip()}")
                    thesis_line = "      " + w + " "
                else:
                    thesis_line += w + " "
            if thesis_line.strip():
                lines.append(f"    AI Thesis:    {thesis_line.strip()}")
            lines.append("")

    # ── Alpaca performance metrics ──
    h2("ALPACA PERFORMANCE METRICS")
    try:
        perf_summary = get_performance_summary()
    except Exception:
        perf_summary = {"total_days": 0, "total_trades": 0, "latest_equity": equity, "total_return_pct": pnl_pct}

    # Compute risk metrics inline from snapshots
    risk_metrics: dict = {}
    try:
        import numpy as _np
        snapshots = get_performance_snapshots(limit=90)
        equities = [s.get("total_equity", 0) for s in snapshots if s.get("total_equity")]
        if len(equities) >= 2:
            returns = _np.diff(equities) / _np.array(equities[:-1])
            mean_r = float(_np.mean(returns))
            std_r  = float(_np.std(returns))
            rf     = 0.05 / 252
            min_e  = min(equities)
            max_e  = max(equities[:equities.index(min_e)+1]) if min_e in equities else equities[0]
            max_dd = round(((max_e - min_e) / max_e) * 100, 2) if max_e > 0 else 0
            ann_r  = mean_r * 252
            sharpe = float((mean_r - rf) / std_r * _np.sqrt(252)) if std_r > 0 else None
            neg_r  = returns[returns < 0]
            ds     = float(_np.std(neg_r)) if len(neg_r) > 0 else None
            sortino = float((mean_r - rf) / ds * _np.sqrt(252)) if ds and ds > 0 else None
            calmar  = round(ann_r / (max_dd / 100), 3) if max_dd > 0 else None
            risk_metrics = {
                "sharpe_ratio": round(sharpe, 3) if sharpe else None,
                "sortino_ratio": round(sortino, 3) if sortino else None,
                "max_drawdown_pct": max_dd,
                "calmar_ratio": calmar,
                "volatility_annual_pct": round(std_r * _np.sqrt(252) * 100, 2),
                "data_points": len(equities),
            }
        elif equities:
            risk_metrics = {"data_points": len(equities)}
    except Exception:
        risk_metrics = {}

    row("Trading days tracked:", str(perf_summary.get("total_days", "N/A")))
    row("Total closed trades:", str(perf_summary.get("total_trades", "N/A")))
    wr = perf_summary.get("avg_win_rate")
    row("Win rate:", f"{wr*100:.1f}%" if wr else "N/A")
    row("Best day:", _pct(perf_summary.get("best_day_pct", None), 3) if perf_summary.get("best_day_pct") else "N/A")
    row("Worst day:", _pct(perf_summary.get("worst_day_pct", None), 3) if perf_summary.get("worst_day_pct") else "N/A")
    row("Total return:", _pct(perf_summary.get("total_return_pct", None), 3))
    conv_avg = perf_summary.get("avg_conviction")
    row("Avg AI conviction:", f"{conv_avg:.4f}" if conv_avg else "N/A")

    h2("ALPACA RISK METRICS (requires 30+ days of equity snapshots)")
    sharpe  = risk_metrics.get("sharpe_ratio")
    sortino = risk_metrics.get("sortino_ratio")
    mdd     = risk_metrics.get("max_drawdown_pct")
    calmar  = risk_metrics.get("calmar_ratio")
    vol     = risk_metrics.get("volatility_annual_pct")
    dpts    = risk_metrics.get("data_points", 0)
    row("Data points (days):", str(dpts))
    row("Sharpe ratio:", f"{sharpe:.4f}" if sharpe is not None else f"N/A ({dpts} day(s) — need 30+)")
    row("Sortino ratio:", f"{sortino:.4f}" if sortino is not None else f"N/A ({dpts} day(s) — need 30+)")
    row("Max drawdown:", _pct(mdd) if mdd is not None else f"N/A ({dpts} day(s) — need 30+)")
    row("Calmar ratio:", f"{calmar:.4f}" if calmar is not None else "N/A")
    row("Annual volatility:", _pct(vol) if vol is not None else "N/A")

    # ── Alpaca trade history ──
    h2("ALPACA TRADE HISTORY (all trades, chronological oldest-first)")
    try:
        alpaca_trades = list(reversed(get_all_trades()))  # oldest first
    except Exception:
        alpaca_trades = []

    if not alpaca_trades:
        lines.append("  No Alpaca trades recorded yet.")
    else:
        lines.append(f"  Total Alpaca trades: {len(alpaca_trades)}")
        lines.append(f"  {'#':<4} {'Date':<12} {'Symbol':<10} {'Status':<16} {'PnL%':>8} {'PnL$':>12}  Thesis / Exit Reason")
        lines.append("  " + "-" * 78)
        for i, t in enumerate(alpaca_trades, 1):
            sym     = str(t.get("ticker") or t.get("symbol") or "?")[:8]
            date    = str(t.get("date") or t.get("closed_at") or "?")[:10]
            status  = str(t.get("status") or "?")[:14]
            pnl_p   = t.get("pnl_percentage") or t.get("pnl_pct")
            pnl_d   = t.get("pnl_usd") or t.get("pnl_usd")
            pnl_p_s = _pct(pnl_p) if pnl_p is not None else "N/A"
            pnl_d_s = _c(pnl_d) if pnl_d is not None else "N/A"
            thesis  = str(t.get("original_thesis") or t.get("exit_reason") or "N/A")[:55]
            lines.append(f"  {i:<4} {date:<12} {sym:<10} {status:<16} {pnl_p_s:>8} {pnl_d_s:>12}  {thesis}")
            # Entry/exit details
            entry_px    = t.get("intended_price") or t.get("avg_entry_price")
            fill_px     = t.get("actual_fill_price")
            slippage    = t.get("slippage_pct")
            conv_score  = t.get("conviction_score")
            asset_cls   = t.get("asset_class", "")
            if any(v is not None for v in [entry_px, fill_px, slippage, conv_score]):
                detail = []
                if entry_px:   detail.append(f"entry={_c(entry_px)}")
                if fill_px:    detail.append(f"fill={_c(fill_px)}")
                if slippage:   detail.append(f"slippage={_pct(slippage, 3)}")
                if conv_score: detail.append(f"conviction={conv_score:.2f}")
                if asset_cls:  detail.append(f"class={asset_cls}")
                lines.append(f"       └─ {' | '.join(detail)}")

    # ── Attribution ──
    h2("ATTRIBUTION ANALYSIS (What worked and what didn't)")
    try:
        attr = _attr()
        by_class = attr.get("asset_class_attribution", {})
        by_conv  = attr.get("conviction_attribution", {})
        by_regime = attr.get("regime_attribution", {})
    except Exception:
        by_class = {}; by_conv = {}; by_regime = {}

    if by_class:
        lines.append("  By Asset Class:")
        lines.append(f"    {'Asset Class':<14} {'Trades':>7} {'Win Rate':>10} {'Total PnL':>11} {'Avg PnL':>9}")
        lines.append("    " + "-" * 55)
        for cls, v in sorted(by_class.items(), key=lambda x: x[1].get("total_pnl_pct", 0)):
            lines.append(f"    {cls:<14} {v.get('count',0):>7} {_pct(v.get('win_rate',0)):>10} {_pct(v.get('total_pnl_pct')):>11} {_pct(v.get('avg_pnl_pct')):>9}")

    if by_conv:
        lines.append("")
        lines.append("  By AI Conviction Level:")
        lines.append(f"    {'Level':<10} {'Trades':>7} {'Win Rate':>10} {'Total PnL':>11} {'Avg PnL':>9}")
        lines.append("    " + "-" * 51)
        for lvl, v in sorted(by_conv.items()):
            lines.append(f"    {lvl:<10} {v.get('count',0):>7} {_pct(v.get('win_rate',0)):>10} {_pct(v.get('total_pnl_pct')):>11} {_pct(v.get('avg_pnl_pct')):>9}")

    if by_regime:
        lines.append("")
        lines.append("  By Market Regime:")
        for regime, v in sorted(by_regime.items()):
            lines.append(f"    {regime:<12} {v.get('count',0)} trades | {_pct(v.get('win_rate',0))} win | avg {_pct(v.get('avg_pnl_pct'))}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: KRAKEN BOT — DAVY JONES' PORTFOLIO
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 3: KRAKEN BOT — DAVY JONES' PORTFOLIO (24/7 Crypto)")

    try:
        _kraken_status_file = _Path("../kraken-bot/status.json")
        _ks = _json.loads(_kraken_status_file.read_text()) if _kraken_status_file.exists() else {}
    except Exception:
        _ks = {}

    try:
        _pf_path = _Path("../kraken-bot/paper_portfolio.json")
        _pf = _json.loads(_pf_path.read_text()) if _pf_path.exists() else {}
    except Exception:
        _pf = {}

    k_status     = _ks.get("status", "not_started")
    k_equity     = _ks.get("total_equity_usd", 0) or 0
    k_deployed   = _ks.get("deployed_usd", 0) or 0
    k_deploy_pct = _ks.get("deployed_pct", 0) or 0
    k_cycles     = _ks.get("cycle_count", 0) or 0
    k_paused     = _ks.get("bot_paused", False)
    k_paper      = _ks.get("paper_trading", True)
    k_updated    = _ks.get("last_updated", "N/A")
    k_positions  = _ks.get("open_positions", []) or []
    k_signals    = _ks.get("signals", []) or []
    k_cb         = _ks.get("circuit_breaker", {}) or {}
    k_adaptive   = _ks.get("adaptive_params", {}) or {}
    k_micro      = _ks.get("microstructure", {}) or {}
    k_thinking   = _ks.get("thinking_text", "") or ""
    k_recent_trd = _ks.get("recent_trades", []) or []
    k_paper_summ = _ks.get("paper_summary", {}) or {}

    # From paper_portfolio.json
    _pf_trades   = _pf.get("all_trades", []) or []
    k_start_bal  = _pf.get("starting_balance", 100_000)
    k_pnl_usd_all = k_equity - k_start_bal

    h2("OVERVIEW")
    row("Capital pool:", "Crypto — Paper Trading via Kraken")
    row("Bot status:", f"{'PAUSED' if k_paused else 'RUNNING'} ({k_status})")
    row("Paper trading:", "YES" if k_paper else "NO — LIVE FUNDS")
    row("Cycles completed:", str(k_cycles))
    row("Last updated:", str(k_updated)[:19])
    row("Starting capital:", _c(k_start_bal))
    row("Current equity:", _c(k_equity))
    row("Total P&L (paper):", f"{_c(k_pnl_usd_all)} ({_pct((k_pnl_usd_all/k_start_bal)*100 if k_start_bal else 0)})")
    row("Deployed capital:", f"{_c(k_deployed)} ({_pct(k_deploy_pct, 1)} of equity)")
    row("Max positions:", str(_ks.get("max_positions", 5)))
    row("Open positions:", str(len(k_positions)))

    # ── Kraken paper summary ──
    if k_paper_summ:
        ps_trades = k_paper_summ.get("total_trades", 0)
        ps_wins   = k_paper_summ.get("win_count", 0)
        ps_losses = k_paper_summ.get("loss_count", 0)
        ps_pnl_u  = k_paper_summ.get("all_time_pnl_usd", 0)
        ps_pnl_p  = k_paper_summ.get("all_time_pnl_pct", 0)
        ps_wr     = (ps_wins / ps_trades * 100) if ps_trades else 0
        lines.append("")
        row("All-time trades:", str(ps_trades))
        row("Win / Loss:", f"{ps_wins}W / {ps_losses}L ({_pct(ps_wr, 1)} win rate)")
        row("All-time P&L:", f"{_c(ps_pnl_u)} ({_pct(ps_pnl_p)})")

    # ── Kraken current positions ──
    h2("CURRENT OPEN POSITIONS (KRAKEN CRYPTO)")
    if not k_positions:
        lines.append("  No open positions (VPIN or reserve ceiling may be blocking entries).")
    for pos in k_positions:
        sym       = pos.get("symbol", "?")
        side      = str(pos.get("side", "?")).upper()
        qty       = pos.get("qty", 0)
        entry     = pos.get("entry_price")
        curr      = pos.get("current_price")
        sz_usd    = pos.get("size_usd", 0)
        upl_usd   = pos.get("unrealized_pnl_usd", 0)
        upl_pct   = pos.get("unrealized_pnl_pct", 0)
        sl        = pos.get("stop_loss_price")
        tp        = pos.get("take_profit_price")
        entry_t   = str(pos.get("entry_time", "?"))[:16]
        best_px   = pos.get("best_price")

        lines.append(f"\n  {sym}  {side}")
        row("Qty:", f"{qty:,.4f}", indent=2)
        row("Entry price:", _c(entry, 4), indent=2)
        row("Current price:", _c(curr, 4), indent=2)
        row("Position size:", _c(sz_usd), indent=2)
        row("Unrealized P&L:", f"{_c(upl_usd)} ({_pct(upl_pct)})", indent=2)
        if sl:
            sl_pct_from_entry = ((sl - entry) / entry * 100) if entry else 0
            row("Stop loss:", f"{_c(sl, 4)} ({_pct(sl_pct_from_entry, 2)} from entry)", indent=2)
        if tp:
            tp_pct_from_entry = ((tp - entry) / entry * 100) if entry else 0
            row("Take profit:", f"{_c(tp, 4)} ({_pct(tp_pct_from_entry, 2)} from entry)", indent=2)
        row("Entry time:", entry_t + " UTC", indent=2)
        if best_px:
            row("Best price seen:", _c(best_px, 4), indent=2)

    # ── Kraken signals ──
    h2("KRAKEN SIGNAL DASHBOARD (current pair signals)")
    if not k_signals:
        lines.append("  No signal data available.")
    else:
        lines.append(f"  {'Pair':<12} {'VPIN':>6} {'Signal':<10} {'Momentum':<12} {'Spread':>8}  Notes")
        lines.append("  " + "-" * 70)
        for sig in (k_signals if isinstance(k_signals, list) else []):
            pair  = str(sig.get("symbol") or sig.get("pair", "?"))[:11]
            vpin  = sig.get("vpin", sig.get("vpin_score"))
            vpin_s = f"{vpin:.3f}" if vpin is not None else "N/A"
            stype = str(sig.get("signal_type") or sig.get("signal", "none"))[:9]
            mom   = str(sig.get("momentum_signal") or sig.get("momentum", "?"))[:11]
            sprd  = sig.get("spread_pct")
            sprd_s = _pct(sprd, 3) if sprd is not None else "N/A"
            note  = "BLOCKED (VPIN>0.70)" if (vpin or 0) > 0.70 else ""
            lines.append(f"  {pair:<12} {vpin_s:>6} {stype:<10} {mom:<12} {sprd_s:>8}  {note}")

    # ── Kraken microstructure ──
    if k_micro:
        h2("ORDER BOOK MICROSTRUCTURE")
        for pair, m in (k_micro.items() if isinstance(k_micro, dict) else []):
            vpin = m.get("vpin")
            sprd = m.get("spread_pct")
            imb  = m.get("order_imbalance")
            lines.append(f"  {pair:<12} VPIN={f'{vpin:.3f}' if vpin else 'N/A'}  Spread={_pct(sprd, 3) if sprd else 'N/A'}  Imbalance={f'{imb:.3f}' if imb else 'N/A'}")

    # ── Kraken per-symbol performance ──
    h2("KRAKEN PER-SYMBOL PERFORMANCE (all-time from paper_portfolio.json)")
    if _pf_trades:
        sym_stats: dict = {}
        for t in _pf_trades:
            s = t.get("symbol", "UNKNOWN")
            if s not in sym_stats:
                sym_stats[s] = {"trades": 0, "wins": 0, "pnl_pct": 0.0, "pnl_usd": 0.0}
            sym_stats[s]["trades"] += 1
            ppct = t.get("pnl_pct", 0) or 0
            pusd = t.get("pnl_usd", 0) or 0
            sym_stats[s]["pnl_pct"] += ppct
            sym_stats[s]["pnl_usd"] += pusd
            if ppct > 0:
                sym_stats[s]["wins"] += 1

        lines.append(f"  {'Symbol':<12} {'Trades':>7} {'Win Rate':>10} {'Total PnL%':>12} {'Total PnL$':>12} {'Avg PnL%':>9}")
        lines.append("  " + "-" * 68)
        for sym, v in sorted(sym_stats.items(), key=lambda x: x[1]["pnl_usd"]):
            n   = v["trades"]
            wr  = (v["wins"] / n * 100) if n else 0
            avg = (v["pnl_pct"] / n) if n else 0
            lines.append(f"  {sym:<12} {n:>7} {_pct(wr, 1):>10} {_pct(v['pnl_pct']):>12} {_c(v['pnl_usd']):>12} {_pct(avg):>9}")
    else:
        lines.append("  No trade data in paper_portfolio.json yet.")

    # ── Kraken recent trade history ──
    h2("KRAKEN TRADE HISTORY (all trades from paper_portfolio.json, oldest-first)")
    pf_trades_sorted = list(reversed(_pf_trades))  # oldest first
    if not pf_trades_sorted and k_recent_trd:
        pf_trades_sorted = list(reversed(k_recent_trd))

    if not pf_trades_sorted:
        lines.append("  No Kraken trade history available yet.")
    else:
        lines.append(f"  Total trades: {len(pf_trades_sorted)}")
        lines.append(f"  {'#':<4} {'Date/Time':<18} {'Symbol':<12} {'Side':<6} {'Entry':>10} {'Exit':>10} {'PnL%':>7} {'PnL$':>10}  Exit Reason")
        lines.append("  " + "-" * 88)
        for i, t in enumerate(pf_trades_sorted, 1):
            sym    = str(t.get("symbol", "?"))[:11]
            dt     = str(t.get("entry_time") or t.get("timestamp") or t.get("date") or "?")[:16]
            side   = str(t.get("side", "?")).upper()[:5]
            entry  = t.get("entry_price") or t.get("intended_price")
            exit_p = t.get("exit_price") or t.get("actual_fill_price")
            ppct   = t.get("pnl_pct") or t.get("pnl_percentage", 0)
            pusd   = t.get("pnl_usd")
            reason = str(t.get("exit_reason") or t.get("original_thesis") or t.get("reason") or "?")[:40]
            entry_s = _c(entry, 4) if entry else "N/A"
            exit_s  = _c(exit_p, 4) if exit_p else "N/A"
            ppct_s  = _pct(ppct) if ppct is not None else "N/A"
            pusd_s  = _c(pusd) if pusd is not None else "N/A"
            lines.append(f"  {i:<4} {dt:<18} {sym:<12} {side:<6} {entry_s:>10} {exit_s:>10} {ppct_s:>7} {pusd_s:>10}  {reason}")

    # ── Kraken circuit breaker ──
    h2("CIRCUIT BREAKER STATUS")
    if k_cb:
        cb_trip = k_cb.get("triggered") or k_cb.get("tripped", False)
        cb_reason = k_cb.get("reason") or k_cb.get("trigger_reason", "N/A")
        cb_consec = k_cb.get("consecutive_losses") or k_cb.get("losses_in_a_row", 0)
        cb_thresh = k_cb.get("threshold") or k_cb.get("max_consecutive_losses", 3)
        row("Triggered:", "YES — bot paused" if cb_trip else "NO")
        row("Consecutive losses:", f"{cb_consec} / {cb_thresh} threshold")
        if cb_reason != "N/A":
            row("Trigger reason:", str(cb_reason))
    else:
        lines.append("  Circuit breaker state not available.")

    # ── Kraken adaptive params ──
    if k_adaptive:
        h2("ADAPTIVE RISK PARAMETERS (current auto-tuned values)")
        for k, v in k_adaptive.items():
            row(f"{k}:", str(v)[:60], indent=2)

    # ── Kraken AI thinking ──
    if k_thinking and len(k_thinking) > 20:
        h2("LAST AI THINKING / REASONING (Kraken bot)")
        thinking_lines = k_thinking.strip().split("\n")
        for tl in thinking_lines[:40]:  # cap at 40 lines
            lines.append(f"  {tl}")
        if len(thinking_lines) > 40:
            lines.append(f"  ... [{len(thinking_lines) - 40} more lines truncated]")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: COMBINED PORTFOLIO
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 4: COMBINED PORTFOLIO OVERVIEW")
    grand_start = 200_000.0
    grand_now   = equity + k_equity
    grand_pnl   = grand_now - grand_start
    grand_pct   = (grand_pnl / grand_start) * 100 if grand_start else 0

    row("Starting capital (both bots):", _c(grand_start))
    row("Alpaca current equity:", f"{_c(equity)}  ({_pct((equity - 100_000) / 100_000 * 100)} from $100k)")
    row("Kraken current equity:", f"{_c(k_equity)}  ({_pct((k_equity - k_start_bal) / k_start_bal * 100 if k_start_bal else 0)} from ${k_start_bal:,.0f})")
    row("Grand total:", _c(grand_now))
    row("Combined P&L:", f"{_c(grand_pnl)} ({_pct(grand_pct)})")

    # Separate analysis of each bot
    lines.append("")
    lines.append("  OBSERVATION: These are two completely separate capital pools:")
    lines.append("    • Alpaca:  US equities strategy — regime-driven, long-only, Kelly-sized,")
    lines.append("               AI allocation via Groq Llama 3.3 70B, 15-min cycles.")
    lines.append("    • Kraken:  Crypto mean-reversion + momentum, VPIN microstructure filter,")
    lines.append("               24/7, 10% position sizing, trailing stops, circuit breaker.")
    lines.append("  They cannot be directly compared — different asset classes and strategies.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5: AI LEARNING JOURNAL
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 5: AI LEARNING JOURNAL (Persistent insights across cycles)")
    try:
        lj_entries = _lj(limit=50)
    except Exception:
        lj_entries = []

    if not lj_entries:
        lines.append("  No learning journal entries yet.")
    else:
        lines.append(f"  {len(lj_entries)} insights stored:")
        lines.append("")
        for e in lj_entries:
            insight   = e.get("insight_text", "?")
            regime    = e.get("regime", "?")
            cat       = e.get("category", "?")
            conf      = e.get("confidence_score", 0)
            confirmed = e.get("confirmed_count", 1)
            first_s   = str(e.get("first_seen", "?"))[:10]
            lines.append(f"  [{regime.upper()} / {cat}]  confidence={conf:.2f}  confirmed×{confirmed}  first_seen={first_s}")
            lines.append(f"    \"{insight}\"")
            lines.append("")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6: STRATEGY PARAMETERS
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 6: STRATEGY PARAMETERS (for LLM context)")

    h2("ALPACA BOT — HOW IT WORKS")
    lines += [
        "  AI Engine:         Groq Llama 3.3 70B (100,000 tokens/day budget)",
        "  Execution:         Alpaca paper trading (simulated US equities)",
        "  Cycle frequency:   Every 15 minutes during market hours",
        "                     24/7 crypto-only cycle for crypto ETFs",
        "  Market regimes:    Bear | Bull | Neutral | Risk-Off",
        "                     Regime changes the entire allocation strategy",
        "  Position sizing:   Kelly Criterion × conviction score (0.0–1.0)",
        "                     Max 15% per position (except SGOV)",
        "  Risk controls:",
        "    - Kill switch:   Trips at 5% daily drawdown — liquidates all",
        "    - Stop losses:   Per-trade, set by AI in allocation decision",
        "    - Take profits:  Per-trade, set by AI in allocation decision",
        "    - Ratchet stops: Trailing stop that locks in gains",
        "  Special positions:",
        "    - SGOV:          AI cash-equivalent — absorbs overflow when all",
        "                     normal slots are capped. Exempt from 15% cap.",
        "    - JEPQ:          Profit vault. 20% of every profit event swept here",
        "                     as a DRIP position. Protected from all liquidations.",
        "  Auditing:          Gemini self-critic runs daily pre-market,",
        "                     HITL auditor agent runs post-close.",
        "  Learning:          AI insights persist in a learning journal and are",
        "                     injected as context into future allocation calls.",
    ]

    h2("KRAKEN BOT — HOW IT WORKS")
    lines += [
        "  Name:              Davy Jones' Portfolio",
        "  Execution:         Kraken exchange (paper trading simulation)",
        "  Strategy:          Mean reversion + momentum with VPIN microstructure filter",
        "  Pairs:             BTC/USD, ETH/USD, XRP/USD, ADA/USD, SOL/USD,",
        "                     DOT/USD, ATOM/USD, AVAX/USD, LINK/USD, MATIC/USD",
        "  Position sizing:   10% of equity per position",
        "  Max positions:     5 simultaneous",
        "  VPIN filter:       Volume-synchronized Probability of Informed Trading.",
        "                     VPIN > 0.70 on a pair blocks new entries — indicates",
        "                     too much informed flow (insider-like activity)",
        "  Entry conditions:  VPIN < 0.70 AND momentum signal AND spread ok",
        "  Stop loss:         Trailing — adapts to best price seen",
        "  Take profit:       Fixed target from entry",
        "  Circuit breaker:   Pauses bot after N consecutive losses",
        "  Capital reserve:   Cannot deploy beyond ceiling % of equity",
        "  Cycle:             Runs 24/7 (crypto never closes)",
        "  Sides:             Both LONG and SHORT allowed",
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # FOOTER
    # ─────────────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append(W)
    lines.append("  END OF REPORT")
    lines.append(f"  Generated: {ts}")
    lines.append("  Suggested LLM prompt:")
    lines.append("    \"Review this trading report. Identify (1) what's working and why,")
    lines.append("     (2) what's losing and the likely root cause, (3) specific parameter")
    lines.append("     changes to improve performance (stop loss %, position sizing, VPIN")
    lines.append("     threshold, conviction cutoffs), and (4) any regime-specific patterns")
    lines.append("     you can see in the trade history. Be specific with numbers.\"")
    lines.append(W)

    report_text = "\n".join(lines)
    return {
        "report":       report_text,
        "generated_at": ts,
        "char_count":   len(report_text),
        "line_count":   len(lines),
    }


app.include_router(router)

# ── System B: Public SaaS Platform routes ─────────────────────────────────────
# Registered separately under /saas-api — no overlap with /trading-api above.
from saas_router import saas_router                          # noqa: E402
from saas_stripe_router import stripe_bp                     # noqa: E402
app.include_router(saas_router)
app.include_router(stripe_bp, prefix="/saas-api")
