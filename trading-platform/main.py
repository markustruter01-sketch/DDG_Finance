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

from fastapi import FastAPI, HTTPException, BackgroundTasks, APIRouter, Request
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

EXPECTED_JOB_COUNT = 10  # 5 trading jobs (scheduler.py) + 5 startup jobs (auto_heal, learning_snapshot, equity_heartbeat, options_apex_predator, forex_navigator)
COMMENTARY_TTL_SECONDS = 1800  # 30-minute cache

_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}
_kraken_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}

KRAKEN_BOT_PROFILES = {
    "davy-jones": {"display_name": "Davy Jones' Portfolio", "db_id": 1, "strategy_label": "Conservative", "port": 8085},
    "blackbeard": {"display_name": "Blackbeard's Fleet", "db_id": 2, "strategy_label": "Aggressive", "port": 8086},
    "calypso":    {"display_name": "Calypso's Tide", "db_id": 3, "strategy_label": "Most Aggressive", "port": 8087},
}

_kraken_commentary_caches: dict[str, dict[str, Any]] = {
    bot_id: {"text": None, "generated_at": None, "ts": 0}
    for bot_id in KRAKEN_BOT_PROFILES
}

_kraken_commentary_round_robin_idx = 0

# ── Commentary Cache Persistence ──────────────────────────────────────────────
# Both commentary caches are file-backed so they survive server restarts.
# Without this, every restart immediately burns Groq tokens to regenerate.
import json as _json
import threading as _ct_lock
from pathlib import Path as _Path

_COMMENTARY_CACHE_FILE = _Path("data/commentary_cache.json")
_commentary_file_lock = _ct_lock.Lock()


def _load_commentary_caches() -> None:
    """Load all commentary caches from disk on startup."""
    global _commentary_cache, _kraken_commentary_cache, _kraken_commentary_caches
    if not _COMMENTARY_CACHE_FILE.exists():
        return
    try:
        data = _json.loads(_COMMENTARY_CACHE_FILE.read_text())
        alpaca = data.get("alpaca", {})
        if alpaca.get("text") and alpaca.get("ts", 0) > 0:
            _commentary_cache = alpaca
            age_min = (time.time() - alpaca["ts"]) / 60
            logger.info(f"Commentary cache | Alpaca: loaded from disk ({age_min:.0f}min old)")
        kraken = data.get("kraken", {})
        if kraken.get("text") and kraken.get("ts", 0) > 0:
            _kraken_commentary_cache = kraken
            _kraken_commentary_caches["davy-jones"] = dict(kraken)
            age_min = (time.time() - kraken["ts"]) / 60
            logger.info(f"Commentary cache | Kraken (davy-jones): loaded from disk ({age_min:.0f}min old)")
        kraken_bots = data.get("kraken_bots", {})
        for bot_id, cache_data in kraken_bots.items():
            if bot_id in _kraken_commentary_caches and cache_data.get("text") and cache_data.get("ts", 0) > 0:
                _kraken_commentary_caches[bot_id] = cache_data
                age_min = (time.time() - cache_data["ts"]) / 60
                logger.info(f"Commentary cache | Kraken ({bot_id}): loaded from disk ({age_min:.0f}min old)")
    except Exception as exc:
        logger.warning(f"Commentary cache | Failed to load from disk: {exc}")


def _persist_commentary_caches() -> None:
    """Atomically write all commentary caches to disk (thread-safe)."""
    try:
        _COMMENTARY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "alpaca": _commentary_cache,
            "kraken": _kraken_commentary_cache,
            "kraken_bots": _kraken_commentary_caches,
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
            import psycopg2 as _pg2eq, os as _oseq
            _dburlq = _oseq.environ.get("DATABASE_URL")
            kraken_eq = 0.0
            if _dburlq:
                _eqconn = _pg2eq.connect(_dburlq)
                try:
                    with _eqconn.cursor() as _eqcur:
                        _eqcur.execute("SELECT COALESCE(SUM(equity_usd), 0) FROM kraken_heartbeat")
                        _eqrow = _eqcur.fetchone()
                        if _eqrow:
                            kraken_eq = float(_eqrow[0] or 0)
                finally:
                    _eqconn.close()
        except Exception:
            kraken_eq = 0.0
        forex_eq = 0.0
        try:
            fx = _get_forex_engine()
            if fx:
                fx_state = fx.get_state()
                forex_eq = float(fx_state.get("paper_equity", 0))
        except Exception:
            forex_eq = 0.0
        insert_equity_snapshot(alpaca_eq, kraken_eq + forex_eq, "LIVE", "hourly_heartbeat")

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

    from apscheduler.triggers.cron import CronTrigger as _CronTrigger
    from options_engine import run_scheduled_scan as _options_scan
    scheduler.add_job(
        func=_options_scan,
        trigger=_CronTrigger(hour=15, minute=30, timezone="US/Eastern"),
        id="options_apex_predator",
        name="Apex Predator Options Scan (3:30 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Apex Predator options scanner registered (3:30 PM ET daily)")

    def _forex_navigator_cycle():
        try:
            fx = _get_forex_engine()
            if fx:
                fx.run_cycle()
            else:
                logger.warning("Forex Navigator | Engine not loaded — skipping cycle")
        except Exception as _fxe:
            logger.warning(f"Forex Navigator | Scheduled cycle failed: {_fxe}")

    _FOREX_ENGINE_DIR = os.path.join(_REPO_ROOT, "forex-engine")
    if _FOREX_ENGINE_DIR not in sys.path:
        sys.path.append(_FOREX_ENGINE_DIR)

    try:
        import importlib.util as _ilu
        _fx_db_spec = _ilu.spec_from_file_location("forex_db", os.path.join(_FOREX_ENGINE_DIR, "forex_nav_db.py"))
        _fx_db_mod = _ilu.module_from_spec(_fx_db_spec)
        _fx_db_spec.loader.exec_module(_fx_db_mod)
        _fx_db_mod.ensure_schema()
        _fx_db_mod.ensure_vault_table()
        logger.info("Forex DB | Schema bootstrapped from trading-api lifespan")
    except Exception as _fxdb_err:
        logger.warning(f"Forex DB | Bootstrap failed (non-fatal): {_fxdb_err}")

    import pytz as _pytz
    _et_tz = _pytz.timezone("America/New_York")
    scheduler.add_job(
        func=_forex_navigator_cycle,
        trigger=_ITrigger(hours=4),
        id="forex_navigator",
        name="Forex Navigator 4h Cycle",
        replace_existing=True,
        misfire_grace_time=600,
        next_run_time=__import__("datetime").datetime.now(_et_tz),
    )
    logger.info("Forex Navigator registered (4-hour interval, first run immediate)")

    try:
        from notifications.alert_manager import start_alert_scheduler
        start_alert_scheduler()
        logger.info("Alert manager started (batched Telegram/Discord notifications)")
    except Exception as _alert_err:
        logger.warning(f"Alert manager startup failed (non-fatal): {_alert_err}")

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
        from datetime import datetime as _dt, timezone as _tz
        kst: dict | None = None

        # ── Try PostgreSQL kraken_heartbeat first (no file-parse risk) ────────
        try:
            import psycopg2 as _pg2, psycopg2.extras as _pg2x, os as _kos
            _kdburl = _kos.environ.get("DATABASE_URL")
            if _kdburl:
                _kpgconn = _pg2.connect(_kdburl)
                try:
                    with _kpgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _kc:
                        _kc.execute(
                            "SELECT status, cycle_count, last_updated, error "
                            "FROM kraken_heartbeat WHERE id = 1"
                        )
                        _kr = _kc.fetchone()
                    if _kr:
                        kst = {
                            "last_updated": _kr["last_updated"].isoformat() if _kr["last_updated"] else None,
                            "status":       _kr["status"],
                            "cycle_count":  _kr["cycle_count"],
                        }
                finally:
                    _kpgconn.close()
        except Exception:
            pass

        if kst is not None:
            last_upd = kst.get("last_updated")
            kage = now - _dt.fromisoformat(last_upd).timestamp() if last_upd else None
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
            nodes["kraken_api"] = {
                "label": "Kraken API (Crypto Bot)", "level": "yellow",
                "latency_ms": None, "data_age_s": None, "detail": "Bot not started",
            }
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

    # ── 7. Options Bot (Apex Predator) ──────────────────────────────────
    try:
        import options_engine as _opts_h
        _opts_state = _opts_h._get_state()
        _opts_enabled = not _opts_state.get("paused", False)
        _opts_equity = _opts_state.get("paper_equity", _opts_h.PAPER_CAPITAL)
        _opts_positions = _opts_h._load_json(_opts_h.POSITIONS_FILE, [])
        _opts_open = len([p for p in _opts_positions if p.get("status") == "open"]) if _opts_positions else 0
        nodes["options_bot"] = {
            "label": "Apex Predator (Options Bot #5)",
            "level": "green",
            "latency_ms": None,
            "data_age_s": None,
            "detail": f"{'Enabled' if _opts_enabled else 'Standby'} · ${_opts_equity:,.0f} · {_opts_open} open",
        }
    except Exception as exc:
        nodes["options_bot"] = {"label": "Apex Predator (Options Bot #5)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # ── 8. Forex Bot (The Navigator) ──────────────────────────────────
    try:
        _fx_h = _get_forex_engine()
        if _fx_h:
            _fx_state = _fx_h.get_state()
            _fx_equity = _fx_state.get("paper_equity", 0)
            _fx_positions = _fx_state.get("position_count", 0)
            _fx_paused = _fx_state.get("paused", False)
            _fx_level = "yellow" if _fx_paused else "green"
            nodes["forex_bot"] = {
                "label": "The Navigator (Forex Bot #6)",
                "level": _fx_level,
                "latency_ms": None,
                "data_age_s": None,
                "detail": f"{'Paused' if _fx_paused else 'Active'} · ${_fx_equity:,.0f} · {_fx_positions} positions",
            }
        else:
            nodes["forex_bot"] = {"label": "The Navigator (Forex Bot #6)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": "Engine not loaded"}
    except Exception as exc:
        nodes["forex_bot"] = {"label": "The Navigator (Forex Bot #6)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # ── 9. Alert System ──────────────────────────────────────────────
    try:
        from notifications.telegram import is_configured as _tg_ok
        from notifications.discord import is_configured as _dc_ok
        from notifications.alert_manager import get_queue_status as _aq_status
        _alert_st = _aq_status()
        _tg = _alert_st.get("telegram_configured", False)
        _dc = _alert_st.get("discord_configured", False)
        _q_size = _alert_st.get("queue_size", 0)
        _channels = []
        if _tg: _channels.append("TG")
        if _dc: _channels.append("DC")
        _ch_str = "+".join(_channels) if _channels else "No channels"
        nodes["alert_system"] = {
            "label": "Alert System (Telegram/Discord)",
            "level": "green" if _channels else "yellow",
            "latency_ms": None,
            "data_age_s": None,
            "detail": f"{_ch_str} · {_q_size} queued · {_alert_st['config'].get('interval_minutes', 60)}min interval",
        }
    except Exception as exc:
        nodes["alert_system"] = {"label": "Alert System", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

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
            # Bot state is in PostgreSQL (kraken_heartbeat / kraken_portfolio / kraken_trades).
            # No file-based heal flag needed — the DB is the authoritative state store.
            try:
                import psycopg2 as _pg2r, os as _osr
                _dburlr = _osr.environ.get("DATABASE_URL")
                if _dburlr:
                    _rconn = _pg2r.connect(_dburlr)
                    try:
                        with _rconn.cursor() as _rc:
                            _rc.execute("SELECT status, cycle_count FROM kraken_heartbeat WHERE id = 1")
                            _rrow = _rc.fetchone()
                        if _rrow:
                            steps.append(
                                f"DB heartbeat reachable — status={_rrow[0]}, cycle #{_rrow[1]}"
                            )
                        else:
                            steps.append("DB reachable but bot has not run yet (no heartbeat row)")
                    finally:
                        _rconn.close()
                else:
                    steps.append("DATABASE_URL not set — cannot verify bot state")
                    success = False
            except Exception as exc:
                steps.append(f"DB health check failed: {str(exc)[:120]}")
                success = False
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

    # ── 3. Kraken bot — heartbeat older than 30 min (1800s) or error state ──
    # Source: kraken_heartbeat PostgreSQL table (DB-only — no file parsing, no JSONDecodeError).
    try:
        from datetime import datetime as _dt
        kst: dict | None = None

        import psycopg2, psycopg2.extras, os as _os
        _dburl = _os.environ.get("DATABASE_URL")
        if _dburl:
            _pgconn = psycopg2.connect(_dburl)
            try:
                with _pgconn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as _cur:
                    _cur.execute("SELECT status, last_updated, error FROM kraken_heartbeat WHERE id = 1")
                    _row = _cur.fetchone()
                if _row:
                    kst = {
                        "last_updated": _row["last_updated"].isoformat() if _row["last_updated"] else None,
                        "status":       _row["status"],
                        "error":        _row["error"],
                    }
            finally:
                _pgconn.close()

        if kst is not None:
            last_upd = kst.get("last_updated")
            if last_upd:
                kage    = now - _dt.fromisoformat(last_upd).timestamp()
                kstatus = kst.get("status", "unknown")
                if kstatus == "error" or kage > 1800:
                    logger.warning(f"[AUTO-HEAL] kraken_api stale/error: status={kstatus}, age={kage:.0f}s")
                    record_degradation(
                        component="kraken_api",
                        severity="critical" if kstatus == "error" else "warning",
                        error_type="error_state" if kstatus == "error" else "stale",
                        message=f"Kraken bot {kstatus}: heartbeat is {kage:.0f}s old (threshold 1800s)",
                        detail=f"last_updated={last_upd}, bot_status={kstatus}",
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
    alpaca_only = [t for t in alpaca_trades if not t.get("trade_id", "").startswith("KRK-")]
    all_trades = alpaca_only + kraken_trades
    try:
        all_trades.sort(key=lambda t: (t.get("date") or ""), reverse=True)
    except Exception:
        pass
    closed_alpaca = [t for t in alpaca_only if t.get("status", "").startswith("Closed")]
    a_wins  = sum(1 for t in closed_alpaca if t.get("status") == "Closed_Win" or (t.get("status") == "Closed" and (t.get("pnl_percentage") or 0) > 0))
    a_losses = sum(1 for t in closed_alpaca if t.get("status") == "Closed_Loss" or (t.get("status") == "Closed" and (t.get("pnl_percentage") or 0) <= 0 and t.get("pnl_percentage") is not None))
    k_wins  = sum(1 for t in kraken_trades if (t.get("pnl_percentage") or 0) > 0)
    k_losses = sum(1 for t in kraken_trades if t.get("pnl_percentage") is not None and (t.get("pnl_percentage") or 0) <= 0)
    combined_wins  = a_wins + k_wins
    combined_losses = a_losses + k_losses
    combined_total = combined_wins + combined_losses
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
    """Load and normalise Kraken closed trades from kraken_trades (PostgreSQL) into the
    same dict shape used by the Alpaca trades table so they can be merged into
    journal endpoints."""
    try:
        import psycopg2 as _pg2j, psycopg2.extras as _pg2xj, os as _osj
        _dburlj = _osj.environ.get("DATABASE_URL")
        if not _dburlj:
            return []
        _jconn = _pg2j.connect(_dburlj)
        try:
            with _jconn.cursor(cursor_factory=_pg2xj.RealDictCursor) as _jc:
                _jc.execute(
                    """
                    SELECT symbol, side, pnl_pct, pnl_usd, reason, closed_at
                    FROM   kraken_trades ORDER BY closed_at ASC
                    """
                )
                _jrows = _jc.fetchall()
        finally:
            _jconn.close()
        trades = []
        for idx, t in enumerate(_jrows):
            if t.get("pnl_pct") is None:
                continue
            _pnl = float(t["pnl_pct"])
            trades.append({
                "trade_id": f"kraken-{idx}",
                "date": (t["closed_at"].isoformat() if t.get("closed_at") else "")[:10],
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
        import psycopg2 as _pg2dr, psycopg2.extras as _pg2xdr, os as _osdr
        _dburldr = _osdr.environ.get("DATABASE_URL")
        if _dburldr:
            _drconn = _pg2dr.connect(_dburldr)
            try:
                with _drconn.cursor(cursor_factory=_pg2xdr.RealDictCursor) as _drc:
                    _drc.execute("SELECT status, equity_usd, cycle_count, last_updated FROM kraken_heartbeat WHERE id = 1")
                    _drrow = _drc.fetchone()
                    if _drrow:
                        kraken_status = {
                            "status":           _drrow["status"],
                            "total_equity_usd": _drrow["equity_usd"],
                            "cycle_count":      _drrow["cycle_count"],
                            "last_updated":     _drrow["last_updated"].isoformat() if _drrow["last_updated"] else None,
                        }
            finally:
                _drconn.close()
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
            _k_equity = 0.0
            try:
                import psycopg2 as _pg2pm, os as _ospm
                _dburlpm = _ospm.environ.get("DATABASE_URL")
                if _dburlpm:
                    _pmconn = _pg2pm.connect(_dburlpm)
                    try:
                        with _pmconn.cursor() as _pmc:
                            _pmc.execute("SELECT COALESCE(SUM(equity_usd), 0) FROM kraken_heartbeat")
                            _pmrow = _pmc.fetchone()
                            if _pmrow:
                                _k_equity = float(_pmrow[0] or 0)
                    finally:
                        _pmconn.close()
            except Exception:
                pass
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
    Read all closed trades from the kraken_trades PostgreSQL table and insert any
    new ones into the PostgreSQL trade journal (source='kraken_paper').
    Uses a sidecar JSON file to track already-imported trades by a composite key
    (symbol|closed_at) to prevent duplicates across postmortem runs.
    """
    import json as _jk
    from db.postgres import is_pg_available, get_conn

    if not is_pg_available():
        return {"imported": 0, "skipped": 0, "reason": "PostgreSQL unavailable"}

    # Read all_trades from kraken_trades DB table (no JSON file fallback)
    all_trades = []
    try:
        with get_conn() as _kconn:
            with _kconn.cursor() as _kc:
                _kc.execute(
                    """
                    SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                           fees_usd, reason, closed_at
                    FROM   kraken_trades ORDER BY closed_at ASC
                    """
                )
                for row in _kc.fetchall():
                    sym, side, ep, xp, pct, pusd, fees, reason, cat = row
                    all_trades.append({
                        "symbol":      sym,
                        "side":        side,
                        "entry_price": float(ep) if ep is not None else None,
                        "exit_price":  float(xp) if xp is not None else None,
                        "pnl_pct":     float(pct) if pct is not None else None,
                        "pnl_usd":     float(pusd) if pusd is not None else None,
                        "fees_usd":    float(fees) if fees is not None else None,
                        "reason":      reason,
                        "closed_at":   cat.isoformat() if hasattr(cat, "isoformat") else str(cat) if cat else "",
                    })
    except Exception as exc:
        return {"imported": 0, "skipped": 0, "error": f"Could not read kraken_trades DB: {exc}"}

    if not all_trades:
        return {"imported": 0, "skipped": 0, "reason": "No trades in kraken_trades table"}

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
    kraken_start = 0.0

    # --- Kraken trades (from kraken_trades + kraken_portfolio PostgreSQL tables) ---
    # Sum starting balances across ALL bots
    kraken_daily_pnl: dict = defaultdict(float)
    try:
        import psycopg2 as _pg2sc, os as _ossc
        _dburlsc = _ossc.environ.get("DATABASE_URL")
        if _dburlsc:
            _scconn = _pg2sc.connect(_dburlsc)
            try:
                with _scconn.cursor() as _scc:
                    _scc.execute("SELECT COALESCE(SUM(starting_balance_usd), 0) FROM kraken_portfolio")
                    _scr = _scc.fetchone()
                    if _scr:
                        kraken_start = float(_scr[0] or 300_000.0)
                    _scc.execute("SELECT pnl_usd, closed_at FROM kraken_trades WHERE pnl_usd IS NOT NULL ORDER BY closed_at ASC")
                    for _tr in _scc.fetchall():
                        _d = (_tr[1].isoformat() if _tr[1] else "")[:10]
                        if _d:
                            kraken_daily_pnl[_d] += float(_tr[0])
            finally:
                _scconn.close()
    except Exception:
        kraken_start = 300_000.0

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

@router.get("/kraken/bots", tags=["Kraken Bot"])
async def kraken_bots_list() -> dict:
    """Return metadata for all configured Kraken bots."""
    return {"bots": KRAKEN_BOT_PROFILES}


def _resolve_bot(bot_id: str | None) -> tuple[str, dict]:
    """Resolve bot_id to a valid (bot_id, profile) tuple. Defaults to davy-jones."""
    bid = bot_id or "davy-jones"
    profile = KRAKEN_BOT_PROFILES.get(bid)
    if not profile:
        bid = "davy-jones"
        profile = KRAKEN_BOT_PROFILES["davy-jones"]
    return bid, profile


@router.get("/kraken/status", tags=["Kraken Bot"])
async def kraken_status(bot_id: str | None = None) -> dict:
    """
    Read and return a Kraken bot's full runtime state for the dashboard.
    Accepts optional bot_id query param (defaults to davy-jones).
    """
    import json as _json
    from pathlib import Path as _Path
    import psycopg2 as _pg2, psycopg2.extras as _pg2x
    import os as _os

    bid, profile = _resolve_bot(bot_id)
    db_id = profile["db_id"]
    display_name = profile["display_name"]
    strategy_label = profile["strategy_label"]

    live_state_file = _Path(f"../kraken-bot/{bid}_live_state.json")
    if not live_state_file.exists() and bid == "davy-jones":
        live_state_file = _Path("../kraken-bot/live_state.json")

    # ── Live telemetry (non-persistent) — always from live_state.json ──────────
    # live_state.json is ALLOWED for: signals, microstructure, adaptive_params,
    # thinking_text, AND open_positions (enriched with current_price / unrealized
    # P&L / stop/tp prices — fields that only exist while the bot is running).
    _live_telemetry: dict = {
        "signals":        [],
        "microstructure": {},
        "thinking_text":  "",
        "adaptive_params": {},
    }
    _live_open_positions: list = []
    try:
        if live_state_file.exists():
            _ls = _json.loads(live_state_file.read_text())
            _live_telemetry["signals"]         = _ls.get("signals", [])
            _live_telemetry["microstructure"]  = _ls.get("microstructure", {})
            _live_telemetry["thinking_text"]   = _ls.get("thinking_text", "")
            _live_telemetry["adaptive_params"] = _ls.get("adaptive_params", {})
            # open_positions from live_state: enriched with current_price, P&L, stop/tp
            _live_open_positions = _ls.get("open_positions", [])
    except Exception:
        pass

    # ── All persistent state from PostgreSQL (DB-only, no file fallback) ───────
    _not_started = {
        "bot_id": bid, "bot_name": display_name, "strategy_label": strategy_label,
        "status": "not_started",
        "last_updated": None, "cycle_count": 0, "total_equity_usd": 0,
        "circuit_breaker": {"active": False, "paused_until": None},
        "position_count": 0, "open_positions": [], "deployed_usd": 0,
        "deployed_pct": 0, "cash_usd": 0, "error": None,
        "recent_trades": [], "paper_summary": None, **_live_telemetry,
    }

    _dburl = _os.environ.get("DATABASE_URL")
    if not _dburl:
        return _not_started

    try:
        _pgconn = _pg2.connect(_dburl)
        try:
            with _pgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _hc:
                _hc.execute("SELECT * FROM kraken_heartbeat WHERE id = %s", (db_id,))
                _hrow = _hc.fetchone()

            if not _hrow:
                return _not_started

            hb = dict(_hrow)
            if hb.get("last_updated"):
                hb["last_updated"] = hb["last_updated"].isoformat()
            if isinstance(hb.get("circuit_breaker"), str):
                hb["circuit_breaker"] = _json.loads(hb["circuit_breaker"])

            # ── 2. Portfolio (cash + open positions) ────────────────────────
            cash_usd      = 0.0
            starting      = 100_000.0
            _db_positions: list = []
            with _pgconn.cursor() as _pc:
                _pc.execute(
                    "SELECT starting_balance_usd, cash_usd, positions FROM kraken_portfolio WHERE id = %s",
                    (db_id,)
                )
                _pr = _pc.fetchone()
                if _pr:
                    starting, cash_usd, _pos_raw = _pr
                    if isinstance(_pos_raw, str):
                        _pos_raw = _json.loads(_pos_raw)
                    # positions is a JSONB dict {symbol: {...}} — inject symbol key and convert to list
                    if isinstance(_pos_raw, dict):
                        for _sym, _pdata in _pos_raw.items():
                            _entry = dict(_pdata)
                            _entry.setdefault("symbol", _sym)
                            _db_positions.append(_entry)
                    elif isinstance(_pos_raw, list):
                        _db_positions = _pos_raw

            # Prefer live_state positions (enriched: current_price, P&L, stop/tp)
            # Fall back to DB positions (which include symbol from key, but lack live fields)
            open_positions: list = _live_open_positions if _live_open_positions else _db_positions

            # ── 3. Trades + paper_summary ────────────────────────────────────
            with _pgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _tc:
                _tc.execute(
                    """
                    SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                           fees_usd, reason, closed_at, paper
                    FROM   kraken_trades WHERE bot_id = %s ORDER BY closed_at ASC
                    """,
                    (bid,)
                )
                _all_rows = _tc.fetchall()

            all_trades = []
            for r in _all_rows:
                d = dict(r)
                if d.get("closed_at"):
                    d["closed_at"] = d["closed_at"].isoformat()
                all_trades.append(d)

            wins = [t for t in all_trades if (t.get("pnl_pct") or 0) > 0]
            paper_summary = {
                "starting_balance_usd": starting,
                "cash_usd":             round(cash_usd, 2),
                "total_trades":         len(all_trades),
                "win_count":            len(wins),
                "loss_count":           len(all_trades) - len(wins),
                "all_time_pnl_usd":     round(sum((t.get("pnl_usd") or 0) for t in all_trades), 2),
                "all_time_pnl_pct":     round(sum((t.get("pnl_pct") or 0) for t in all_trades), 2),
            }

            equity       = round(hb.get("equity_usd", 0), 2)
            deployed_usd = equity - cash_usd if equity > cash_usd else 0.0
            deployed_pct = round((deployed_usd / equity) * 100, 1) if equity > 0 else 0.0

            return {
                "bot_id":               bid,
                "bot_name":             display_name,
                "strategy_label":       strategy_label,
                "paper_trading":        hb.get("paper_trading", True),
                "bot_paused":           hb.get("bot_paused", False),
                "status":               hb.get("status", "not_started"),
                "last_updated":         hb.get("last_updated"),
                "cycle_count":          hb.get("cycle_count", 0),
                "total_equity_usd":     equity,
                "position_count":       hb.get("position_count", 0),
                "circuit_breaker":      hb.get("circuit_breaker") or {"active": False, "paused_until": None},
                "error":                hb.get("error"),
                "cash_usd":             round(cash_usd, 2),
                "open_positions":       open_positions,
                "deployed_usd":         round(deployed_usd, 2),
                "deployed_pct":         deployed_pct,
                "deployable_ceiling_pct": 80,
                "cash_reserve_pct":     20,
                "max_positions":        10,
                "recent_trades":        all_trades[-50:],
                "paper_summary":        paper_summary,
                **_live_telemetry,
            }
        finally:
            _pgconn.close()
    except Exception as exc:
        logger.warning(f"[kraken/status] DB read failed: {exc}")
        return {
            "bot_id": bid, "bot_name": display_name, "strategy_label": strategy_label,
            "status": "db_unavailable",
            "last_updated": None, "cycle_count": 0, "total_equity_usd": 0,
            "circuit_breaker": {"active": False, "paused_until": None},
            "position_count": 0, "open_positions": [], "deployed_usd": 0,
            "deployed_pct": 0, "cash_usd": 0, "error": str(exc),
            "recent_trades": [], "paper_summary": None, **_live_telemetry,
        }


# ── Kraken Bot — Fleet Summary (combined equity across all bots) ──────────────

@router.get("/kraken/fleet-summary", tags=["Kraken Bot"])
async def kraken_fleet_summary() -> dict:
    """
    Return combined equity, cash, trade stats across ALL Kraken bots.
    Used by the dashboard to show accurate fleet-wide totals.
    """
    import psycopg2 as _pg2fs, psycopg2.extras as _pg2fsx, os as _osfs, json as _jsonfs

    _dburlfs = _osfs.environ.get("DATABASE_URL")
    if not _dburlfs:
        return {"total_equity_usd": 0, "total_cash_usd": 0, "total_starting_usd": 0,
                "total_trades": 0, "total_wins": 0, "total_pnl_usd": 0, "bot_count": 0, "bots": []}

    try:
        _fsconn = _pg2fs.connect(_dburlfs)
        try:
            bots_out = []
            total_equity = 0.0
            total_cash = 0.0
            total_starting = 0.0
            total_trades = 0
            total_wins = 0
            total_pnl_usd = 0.0

            for _bid, _prof in KRAKEN_BOT_PROFILES.items():
                _dbid = _prof["db_id"]
                eq = 0.0
                cash = 0.0
                starting = 100_000.0
                trades_count = 0
                wins_count = 0
                pnl = 0.0

                with _fsconn.cursor() as _fsc:
                    _fsc.execute("SELECT equity_usd FROM kraken_heartbeat WHERE id = %s", (_dbid,))
                    _hr = _fsc.fetchone()
                    if _hr:
                        eq = float(_hr[0] or 0)

                    _fsc.execute("SELECT starting_balance_usd, cash_usd FROM kraken_portfolio WHERE id = %s", (_dbid,))
                    _pr = _fsc.fetchone()
                    if _pr:
                        starting = float(_pr[0] or 100_000)
                        cash = float(_pr[1] or 0)

                    _fsc.execute(
                        "SELECT COUNT(*), "
                        "SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END), "
                        "COALESCE(SUM(pnl_usd), 0) "
                        "FROM kraken_trades WHERE bot_id = %s",
                        (_bid,)
                    )
                    _tr = _fsc.fetchone()
                    if _tr:
                        trades_count = int(_tr[0] or 0)
                        wins_count = int(_tr[1] or 0)
                        pnl = float(_tr[2] or 0)

                total_equity += eq
                total_cash += cash
                total_starting += starting
                total_trades += trades_count
                total_wins += wins_count
                total_pnl_usd += pnl

                bots_out.append({
                    "bot_id": _bid,
                    "display_name": _prof["display_name"],
                    "equity_usd": round(eq, 2),
                    "cash_usd": round(cash, 2),
                    "starting_balance_usd": round(starting, 2),
                    "trades": trades_count,
                    "wins": wins_count,
                    "pnl_usd": round(pnl, 2),
                })

            return {
                "total_equity_usd": round(total_equity, 2),
                "total_cash_usd": round(total_cash, 2),
                "total_starting_usd": round(total_starting, 2),
                "total_trades": total_trades,
                "total_wins": total_wins,
                "total_pnl_usd": round(total_pnl_usd, 2),
                "bot_count": len(KRAKEN_BOT_PROFILES),
                "bots": bots_out,
            }
        finally:
            _fsconn.close()
    except Exception as exc:
        logger.warning(f"[kraken/fleet-summary] DB read failed: {exc}")
        return {"total_equity_usd": 0, "total_cash_usd": 0, "total_starting_usd": 0,
                "total_trades": 0, "total_wins": 0, "total_pnl_usd": 0,
                "bot_count": 0, "bots": [], "error": str(exc)}


# ── Kraken Bot — AI Narrative Commentary ──────────────────────────────────────

@router.get("/kraken/commentary", tags=["Kraken Bot"])
async def kraken_commentary(force: bool = False, bot_id: str | None = None) -> dict:
    """
    Generate a Kraken bot's AI narrative. Cached for 30 minutes per bot.
    Round-robin: only one bot gets fresh Groq generation per request cycle.
    """
    global _kraken_commentary_cache, _kraken_commentary_round_robin_idx
    import json as _json, os as _os
    from pathlib import Path as _Path

    bid, profile = _resolve_bot(bot_id)
    db_id = profile["db_id"]
    display_name = profile["display_name"]

    bot_cache = _kraken_commentary_caches.get(bid, {"text": None, "generated_at": None, "ts": 0})

    now = time.time()
    cache_age = now - bot_cache["ts"]

    if not force and bot_cache["text"] and cache_age < COMMENTARY_TTL_SECONDS:
        return {
            "bot_id": bid,
            "commentary": bot_cache["text"],
            "generated_at": bot_cache["generated_at"],
            "cached": True,
            "cache_age_seconds": int(cache_age),
        }

    from analysis.groq_budget import budget as _groq_budget
    if not _groq_budget.can_call_commentary("kraken", force=force):
        if bot_cache["text"]:
            return {
                "bot_id": bid,
                "commentary": bot_cache["text"],
                "generated_at": bot_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "throttled": True,
                "budget_exhausted": _groq_budget.budget_exhausted(),
            }
        _exhausted = _groq_budget.budget_exhausted()
        return {
            "bot_id": bid,
            "commentary": "AI narrative paused — daily token budget reached. Trades are running normally; all entry/exit decisions are purely algorithmic (Z-score, RSI, VPIN) and never depend on this commentary. Narrative resumes tomorrow at midnight UTC.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "throttled": True,
            "budget_exhausted": _exhausted,
        }

    bot_ids_list = list(KRAKEN_BOT_PROFILES.keys())
    if not force:
        rr_bot = bot_ids_list[_kraken_commentary_round_robin_idx % len(bot_ids_list)]
        if bid != rr_bot and bot_cache["text"]:
            return {
                "bot_id": bid,
                "commentary": bot_cache["text"],
                "generated_at": bot_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "round_robin_skip": True,
            }

    import psycopg2 as _pg2c, psycopg2.extras as _pg2cx
    kdata: dict = {}
    recent_trades: list[dict] = []

    _dburl = _os.environ.get("DATABASE_URL")
    if _dburl:
        try:
            _kcpgconn = _pg2c.connect(_dburl)
            try:
                with _kcpgconn.cursor(cursor_factory=_pg2cx.RealDictCursor) as _kcc:
                    _kcc.execute("SELECT * FROM kraken_heartbeat WHERE id = %s", (db_id,))
                    _khr = _kcc.fetchone()
                    if _khr:
                        kdata = {
                            "status":           _khr["status"],
                            "cycle_count":      _khr["cycle_count"],
                            "total_equity_usd": _khr["equity_usd"],
                            "open_positions":   [],
                        }

                with _kcpgconn.cursor(cursor_factory=_pg2cx.RealDictCursor) as _kct:
                    _kct.execute(
                        """
                        SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                               fees_usd, reason, closed_at, paper
                        FROM   kraken_trades WHERE bot_id = %s ORDER BY closed_at ASC
                        """,
                        (bid,)
                    )
                    for _r in _kct.fetchall():
                        _d = dict(_r)
                        if _d.get("closed_at"):
                            _d["closed_at"] = _d["closed_at"].isoformat()
                        recent_trades.append(_d)
            finally:
                _kcpgconn.close()
        except Exception as exc:
            logger.debug(f"Kraken commentary: DB read failed: {exc}")

    if not kdata:
        return {
            "bot_id": bid,
            "commentary": f"{display_name} is still getting started — bot hasn't run yet. Check back shortly.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "unavailable": True,
        }

    _lsf = _Path(f"../kraken-bot/{bid}_live_state.json")
    if not _lsf.exists() and bid == "davy-jones":
        _lsf = _Path("../kraken-bot/live_state.json")
    _live: dict = {}
    try:
        if _lsf.exists():
            _live = _json.loads(_lsf.read_text())
    except Exception:
        pass

    positions     = _live.get("open_positions", kdata.get("open_positions", []))
    signals       = _live.get("signals", kdata.get("signals", []))
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

    _persona_map = {
        "davy-jones": ("Davy Jones", "a relentless 24/7 crypto mean-reversion trading AI with the soul of a seasoned sailor who reads market currents like ocean tides"),
        "blackbeard": ("Blackbeard", "an aggressive 24/7 crypto mean-reversion trading AI who attacks weak signals like a pirate raiding merchant ships — tight entry thresholds, higher risk tolerance, bigger positions"),
        "calypso": ("Calypso", "the most aggressive 24/7 crypto mean-reversion trading AI — a mythical sea goddess who bends markets to her will with the tightest entry thresholds, smallest cash reserves, and maximum position sizing"),
    }
    persona_name, persona_desc = _persona_map.get(bid, ("Kraken Bot", "a 24/7 crypto mean-reversion trading AI"))

    user_prompt = f"""
{persona_name}'s current open positions (Kraken 24/7 mean-reversion crypto bot, {profile.get('strategy_label', '')} strategy):
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
        f"You are '{persona_name}' — {persona_desc}. In exactly 3 punchy sentences: "
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
            _kraken_commentary_round_robin_idx += 1
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        new_cache = {"text": commentary, "generated_at": generated_at, "ts": now}
        _kraken_commentary_caches[bid] = new_cache
        if bid == "davy-jones":
            _kraken_commentary_cache = new_cache
        _persist_commentary_caches()
        logger.info(f"Kraken AI commentary regenerated for {bid} (force={force}, tokens={tokens_used})")
        return {"bot_id": bid, "commentary": commentary, "generated_at": generated_at, "cached": False, "cache_age_seconds": 0}
    except Exception as exc:
        logger.error(f"Kraken AI commentary generation failed for {bid}: {exc}")
        bot_cache["ts"] = now - COMMENTARY_TTL_SECONDS + 300
        _kraken_commentary_caches[bid] = bot_cache
        if bot_cache["text"]:
            return {
                "bot_id": bid,
                "commentary": bot_cache["text"],
                "generated_at": bot_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "error": str(exc),
            }
        return {
            "bot_id": bid,
            "commentary": f"{persona_name}'s AI is resting — daily token limit reached. The seas will clear by tomorrow.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "error": str(exc),
            "unavailable": True,
        }


# ── Kraken Bot — Performance Metrics ──────────────────────────────────────────
# Separate from the Alpaca performance endpoints (/performance/history,
# /performance/summary). This reads exclusively from the kraken_trades,
# kraken_heartbeat, and kraken_portfolio PostgreSQL tables.
# The Alpaca trading system never touches these tables.

@router.get("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_auto_trading_status(bot_id: str | None = None) -> dict:
    """Return the current Kraken bot pause state from control.json."""
    import json as _json
    from pathlib import Path as _Path
    bid, _ = _resolve_bot(bot_id)
    ctrl = _Path(f"../kraken-bot/{bid}_control.json")
    if not ctrl.exists() and bid == "davy-jones":
        ctrl = _Path("../kraken-bot/control.json")
    if not ctrl.exists():
        return {"bot_id": bid, "bot_paused": False}
    try:
        return {"bot_id": bid, "bot_paused": bool(_json.loads(ctrl.read_text()).get("bot_paused", False))}
    except Exception:
        return {"bot_id": bid, "bot_paused": False}


class KrakenControlRequest(BaseModel):
    bot_paused: bool


@router.post("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_toggle_auto_trading(request: KrakenControlRequest, bot_id: str | None = None) -> dict:
    """Pause or resume a Kraken bot by writing its control.json."""
    import json as _json
    from pathlib import Path as _Path
    bid, _ = _resolve_bot(bot_id)
    ctrl = _Path(f"../kraken-bot/{bid}_control.json")
    ctrl.write_text(_json.dumps({"bot_paused": request.bot_paused}, indent=2))
    logger.info(f"Kraken bot {bid} {'PAUSED' if request.bot_paused else 'RESUMED'} via dashboard toggle")
    return {"bot_id": bid, "bot_paused": request.bot_paused, "message": f"Kraken bot {bid} paused" if request.bot_paused else f"Kraken bot {bid} resumed"}


@router.get("/kraken/performance", tags=["Kraken Bot"])
async def kraken_performance(bot_id: str | None = None) -> dict:
    """Derive performance statistics from a Kraken bot."""
    import json as _json
    from pathlib import Path as _Path
    import psycopg2 as _pg2, psycopg2.extras as _pg2x
    import os as _os

    bid, profile = _resolve_bot(bot_id)
    db_id = profile["db_id"]

    empty: dict = {
        "bot_id":          bid,
        "data_source":     "postgresql:kraken_trades",
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

    trades: list[dict] = []
    current_equity = 0
    cycle_count    = 0
    bot_status     = "not_started"

    _dburl = _os.environ.get("DATABASE_URL")
    if _dburl:
        try:
            _pgconn = _pg2.connect(_dburl)
            try:
                with _pgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _tc:
                    _tc.execute(
                        """
                        SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                               fees_usd, reason, closed_at, paper
                        FROM   kraken_trades WHERE bot_id = %s
                        ORDER  BY closed_at ASC
                        """,
                        (bid,)
                    )
                    for r in _tc.fetchall():
                        d = dict(r)
                        if d.get("closed_at"):
                            d["closed_at"] = d["closed_at"].isoformat()
                        trades.append(d)

                with _pgconn.cursor() as _hc:
                    _hc.execute(
                        "SELECT equity_usd, cycle_count, status FROM kraken_heartbeat WHERE id = %s",
                        (db_id,)
                    )
                    _hr = _hc.fetchone()
                    if _hr:
                        current_equity = _hr[0] or 0
                        cycle_count    = _hr[1] or 0
                        bot_status     = _hr[2] or "not_started"
            finally:
                _pgconn.close()
        except Exception as exc:
            logger.warning(f"[kraken/performance] DB read failed: {exc}")
            empty["bot_status"]     = bot_status
            empty["current_equity"] = current_equity
            empty["cycle_count"]    = cycle_count
            return empty

    if not trades:
        empty["bot_status"]     = bot_status
        empty["current_equity"] = current_equity
        empty["cycle_count"]    = cycle_count
        return empty

    pnl_list = [t.get("pnl_pct", 0) for t in trades]
    pnl_usd  = [t.get("pnl_usd", 0) for t in trades]
    wins     = [p for p in pnl_list if p > 0]
    losses   = [p for p in pnl_list if p <= 0]
    win_rate = (len(wins) / len(trades)) * 100 if trades else 0

    by_symbol: dict[str, dict] = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "wins": 0, "total_pnl_pct": 0.0, "total_pnl_usd": 0.0}
        by_symbol[sym]["trades"]        += 1
        by_symbol[sym]["total_pnl_pct"] += t.get("pnl_pct", 0)
        by_symbol[sym]["total_pnl_usd"] += t.get("pnl_usd", 0)
        if (t.get("pnl_pct") or 0) > 0:
            by_symbol[sym]["wins"] += 1

    for sym in by_symbol:
        n = by_symbol[sym]["trades"]
        by_symbol[sym]["win_rate_pct"]  = round((by_symbol[sym]["wins"] / n) * 100, 1) if n else 0
        by_symbol[sym]["total_pnl_pct"] = round(by_symbol[sym]["total_pnl_pct"], 2)
        by_symbol[sym]["total_pnl_usd"] = round(by_symbol[sym]["total_pnl_usd"], 2)

    return {
        "bot_id":          bid,
        "data_source":     "postgresql:kraken_trades",
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
        "current_equity":  current_equity,
        "cycle_count":     cycle_count,
        "bot_status":      bot_status,
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
    lines.append("           entry/exit conditions, and performance data for ALL 6 BOTS.")
    lines.append("  FLEET:   #1 Oracle (Alpaca), #2 Davy Jones, #3 Blackbeard, #4 Calypso (Kraken),")
    lines.append("           #5 Apex Predator (Options), #6 Navigator (Forex)")
    lines.append("  CAPITAL: $600,000 total across 4 capital pools")
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
    h2("ALPACA TRADE HISTORY (sorted by PnL ascending — worst losses first)")
    try:
        _all_alpaca = get_all_trades()
        alpaca_trades = sorted(
            _all_alpaca,
            key=lambda t: float(t.get("pnl_usd") or t.get("pnl_dollar") or 0),
        )
    except Exception:
        alpaca_trades = []

    if not alpaca_trades:
        lines.append("  No Alpaca trades recorded yet.")
    else:
        lines.append(f"  Total Alpaca trades: {len(alpaca_trades)} (showing worst losses first)")
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
    # SECTION 3: KRAKEN FLEET — ALL 3 CRYPTO BOTS
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 3: KRAKEN FLEET — ALL 3 CRYPTO BOTS (24/7)")

    import psycopg2 as _pg2rpt, psycopg2.extras as _pg2xrpt, os as _osrpt
    _dburlrpt = _osrpt.environ.get("DATABASE_URL")

    _all_kraken_equity = 0.0
    _all_kraken_starting = 0.0
    _all_kraken_trades_all: list = []
    _kraken_per_bot_equity: dict = {}

    for _kbid, _kprof in KRAKEN_BOT_PROFILES.items():
        _kdbid = _kprof["db_id"]
        _kname = _kprof["display_name"]
        _kstrat = _kprof["strategy_label"]

        h2(f"BOT #{_kdbid+1}: {_kname.upper()} (bot_id={_kbid}, strategy={_kstrat})")

        _ks: dict = {}
        _pf: dict = {}
        _pf_trades: list = []

        if _dburlrpt:
            try:
                _rptconn = _pg2rpt.connect(_dburlrpt)
                try:
                    with _rptconn.cursor(cursor_factory=_pg2xrpt.RealDictCursor) as _rhc:
                        _rhc.execute("SELECT * FROM kraken_heartbeat WHERE id = %s", (_kdbid,))
                        _rhr = _rhc.fetchone()
                        if _rhr:
                            _ks = {
                                "status":         _rhr["status"],
                                "equity_usd":     _rhr["equity_usd"],
                                "cycle_count":    _rhr["cycle_count"],
                                "bot_paused":     _rhr["bot_paused"],
                                "paper_trading":  _rhr["paper_trading"],
                                "last_updated":   _rhr["last_updated"].isoformat() if _rhr["last_updated"] else "N/A",
                                "position_count": _rhr["position_count"],
                            }
                    with _rptconn.cursor() as _rpc:
                        _rpc.execute(
                            "SELECT starting_balance_usd, cash_usd, positions FROM kraken_portfolio WHERE id = %s",
                            (_kdbid,)
                        )
                        _rpr = _rpc.fetchone()
                        if _rpr:
                            _pos_raw = _rpr[2]
                            if isinstance(_pos_raw, str):
                                _pos_raw = _json.loads(_pos_raw)
                            _db_pos_list = []
                            if isinstance(_pos_raw, dict):
                                for _s, _pd in _pos_raw.items():
                                    _ep = dict(_pd)
                                    _ep.setdefault("symbol", _s)
                                    _db_pos_list.append(_ep)
                            elif isinstance(_pos_raw, list):
                                _db_pos_list = _pos_raw
                            _pf = {
                                "starting_balance_usd": float(_rpr[0] or 100_000),
                                "cash_usd":             float(_rpr[1] or 0),
                                "open_positions": _db_pos_list,
                            }
                    with _rptconn.cursor(cursor_factory=_pg2xrpt.RealDictCursor) as _rtc:
                        _rtc.execute(
                            """
                            SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                                   fees_usd, reason, closed_at, paper
                            FROM   kraken_trades WHERE bot_id = %s ORDER BY closed_at ASC
                            """,
                            (_kbid,)
                        )
                        for _rtr in _rtc.fetchall():
                            _rtd = dict(_rtr)
                            if _rtd.get("closed_at"):
                                _rtd["closed_at"] = _rtd["closed_at"].isoformat()
                            _pf_trades.append(_rtd)
                finally:
                    _rptconn.close()
            except Exception as _rpte:
                logger.warning(f"[report] Kraken DB read failed for {_kbid}: {_rpte}")

        _live_rpt: dict = {}
        try:
            _lsf_rpt = _Path(f"../kraken-bot/{_kbid}_live_state.json")
            if _lsf_rpt.exists():
                _live_rpt = _json.loads(_lsf_rpt.read_text())
            elif _kbid == "davy-jones":
                _lsf_rpt2 = _Path("../kraken-bot/live_state.json")
                if _lsf_rpt2.exists():
                    _live_rpt = _json.loads(_lsf_rpt2.read_text())
        except Exception:
            pass

        k_status   = _ks.get("status", "not_started")
        k_equity   = _ks.get("equity_usd", 0) or 0
        k_cycles   = _ks.get("cycle_count", 0) or 0
        k_paused   = _ks.get("bot_paused", False)
        k_paper    = _ks.get("paper_trading", True)
        k_updated  = _ks.get("last_updated", "N/A")
        _live_rpt_positions = _live_rpt.get("open_positions", [])
        k_positions = _live_rpt_positions if _live_rpt_positions else (_pf.get("open_positions", []) or [])
        k_start_bal = _pf.get("starting_balance_usd", 100_000)
        k_cash_usd  = _pf.get("cash_usd", 0)
        k_deployed  = k_equity - k_cash_usd if k_equity > k_cash_usd else 0.0
        k_deploy_pct = round((k_deployed / k_equity) * 100, 1) if k_equity > 0 else 0.0
        k_pnl_usd   = k_equity - k_start_bal
        _k_has_data  = bool(_ks)

        if _k_has_data:
            _all_kraken_equity += k_equity
            _all_kraken_starting += k_start_bal
        else:
            _all_kraken_starting += 100_000
            k_equity = 0
        _all_kraken_trades_all.extend(_pf_trades)
        _kraken_per_bot_equity[_kbid] = k_equity

        if not _k_has_data:
            row("Bot status:", "DB UNAVAILABLE — no heartbeat data")
        else:
            row("Bot status:", f"{'PAUSED' if k_paused else 'RUNNING'} ({k_status})")
        row("Paper trading:", "YES" if k_paper else "NO — LIVE FUNDS")
        row("Strategy:", _kstrat)
        row("Cycles completed:", str(k_cycles))
        row("Last updated:", str(k_updated)[:19])
        row("Starting capital:", _c(k_start_bal))
        row("Current equity:", _c(k_equity))
        row("Total P&L:", f"{_c(k_pnl_usd)} ({_pct((k_pnl_usd/k_start_bal)*100 if k_start_bal else 0)})")
        row("Deployed capital:", f"{_c(k_deployed)} ({_pct(k_deploy_pct, 1)} of equity)")
        row("Open positions:", str(len(k_positions)))

        _pf_wins = [t for t in _pf_trades if (t.get("pnl_pct", 0) or 0) > 0]
        if _pf_trades:
            ps_trades = len(_pf_trades)
            ps_wins   = len(_pf_wins)
            ps_losses = ps_trades - ps_wins
            ps_pnl_u  = round(sum(t.get("pnl_usd", 0) or 0 for t in _pf_trades), 2)
            ps_wr     = (ps_wins / ps_trades * 100) if ps_trades else 0
            row("All-time trades:", str(ps_trades))
            row("Win / Loss:", f"{ps_wins}W / {ps_losses}L ({_pct(ps_wr, 1)} win rate)")
            row("All-time P&L:", _c(ps_pnl_u))

        if k_positions:
            lines.append("")
            lines.append(f"    Open Positions:")
            for pos in k_positions:
                sym     = pos.get("symbol", "?")
                side    = str(pos.get("side", "?")).upper()
                entry   = pos.get("entry_price")
                curr    = pos.get("current_price")
                upl_usd = pos.get("unrealized_pnl_usd", 0)
                upl_pct = pos.get("unrealized_pnl_pct", 0)
                lines.append(f"      {sym:<12} {side:<6} entry={_c(entry, 4)}  now={_c(curr, 4)}  P&L={_c(upl_usd)} ({_pct(upl_pct)})")

        if _pf_trades:
            lines.append("")
            lines.append(f"    Recent Trades (last 15):")
            for t in _pf_trades[-15:]:
                sym    = str(t.get("symbol", "?"))[:11]
                dt     = str(t.get("closed_at") or "?")[:16]
                side   = str(t.get("side", "?")).upper()[:5]
                ppct   = t.get("pnl_pct") or 0
                pusd   = t.get("pnl_usd") or 0
                reason = str(t.get("reason") or "?")[:35]
                lines.append(f"      {dt:<16} {sym:<12} {side:<5} {_pct(ppct):>7} {_c(pusd):>10}  {reason}")

    h2("KRAKEN FLEET TOTALS")
    _k_fleet_pnl = _all_kraken_equity - _all_kraken_starting
    row("Fleet starting capital:", _c(_all_kraken_starting))
    row("Fleet current equity:", _c(_all_kraken_equity))
    row("Fleet P&L:", f"{_c(_k_fleet_pnl)} ({_pct((_k_fleet_pnl/_all_kraken_starting)*100 if _all_kraken_starting else 0)})")
    row("Fleet total trades:", str(len(_all_kraken_trades_all)))

    h2("KRAKEN PER-SYMBOL PERFORMANCE (all bots combined)")
    if _all_kraken_trades_all:
        sym_stats: dict = {}
        for t in _all_kraken_trades_all:
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
        lines.append("  No trade data in kraken_trades DB yet.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: APEX PREDATOR — OPTIONS ENGINE (Bot #5)
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 4: APEX PREDATOR — OPTIONS ENGINE (Bot #5)")

    try:
        _opts_state = _opts.get_full_state()
        _opts_positions = _opts._get_positions()
    except Exception:
        _opts_state = {}
        _opts_positions = []

    _opts_equity   = _opts_state.get("paper_equity", _opts_state.get("total_equity", 100_000))
    _opts_deployed = _opts_state.get("deployed_capital", 0)
    _opts_unrealized = _opts_state.get("unrealized_pnl", 0)
    _opts_trades   = _opts_state.get("total_trades", 0)
    _opts_wins     = _opts_state.get("total_wins", 0)
    _opts_paused   = _opts_state.get("paused", False)
    _opts_paper    = _opts_state.get("paper_mode", True)
    _opts_start    = 100_000.0
    _opts_pnl      = _opts_equity - _opts_start

    h2("OVERVIEW")
    row("Capital pool:", "Options — Paper Trading (Volatility Squeeze Strategy)")
    row("Bot status:", "PAUSED" if _opts_paused else "RUNNING")
    row("Paper trading:", "YES" if _opts_paper else "NO — LIVE FUNDS")
    row("Starting capital:", _c(_opts_start))
    row("Current equity:", _c(_opts_equity))
    row("Total P&L:", f"{_c(_opts_pnl)} ({_pct((_opts_pnl/_opts_start)*100)})")
    row("Deployed capital:", _c(_opts_deployed))
    row("Unrealized P&L:", _c(_opts_unrealized))
    row("Total trades:", str(_opts_trades))
    row("Wins:", str(_opts_wins))
    _opts_wr = (_opts_wins / _opts_trades * 100) if _opts_trades > 0 else 0
    row("Win rate:", _pct(_opts_wr, 1))

    h2("CURRENT OPTIONS POSITIONS")
    if not _opts_positions:
        lines.append("  No open options positions.")
    else:
        for op in _opts_positions:
            sym      = op.get("symbol", "?")
            strategy = op.get("strategy", "?")
            status   = op.get("status", "?")
            cost     = op.get("total_cost", 0)
            cur_val  = op.get("current_value", 0)
            pnl_op   = cur_val - cost
            entry_t  = str(op.get("entry_time") or op.get("opened_at") or "?")[:16]
            lines.append(f"\n  {sym} — {strategy}")
            row("Status:", status, indent=2)
            row("Total cost:", _c(cost), indent=2)
            row("Current value:", _c(cur_val), indent=2)
            row("Unrealized P&L:", _c(pnl_op), indent=2)
            row("Entry time:", entry_t, indent=2)
            legs = op.get("legs", [])
            if legs:
                for leg in legs:
                    leg_type = leg.get("type", "?")
                    strike   = leg.get("strike", "?")
                    exp      = str(leg.get("expiration", "?"))[:10]
                    qty_l    = leg.get("quantity", 0)
                    lines.append(f"      Leg: {leg_type} strike={strike} exp={exp} qty={qty_l}")

    h2("OPTIONS STRATEGY PARAMETERS")
    lines += [
        "  Strategy:          Volatility Squeeze → Long Straddle (100% quant, LLM-free)",
        "  Scan schedule:     Daily at 3:30 PM ET (Mon–Fri)",
        "  Capital fence:     20% of equity max deployed at any time",
        "  Entry:             Bollinger Band squeeze + low IV rank → buy ATM straddle",
        "  Exit:              Profit target or time decay threshold",
        "  Paper mode:        Simulated fills with real option chain data",
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5: THE NAVIGATOR — FOREX ENGINE (Bot #6)
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 5: THE NAVIGATOR — FOREX SWING ENGINE (Bot #6)")

    _fx_engine = _get_forex_engine()
    _fx_db = _get_forex_db()

    _fx_state: dict = {}
    _fx_positions: list = []
    _fx_trades: list = []
    try:
        if _fx_engine:
            _fx_state = _fx_engine.get_state()
            _fx_positions = _fx_engine.get_positions()
    except Exception:
        pass
    try:
        if _fx_db:
            _fx_trades = _fx_db.load_recent_trades(limit=100)
    except Exception:
        pass

    _fx_equity   = _fx_state.get("total_equity", _fx_state.get("paper_equity", 100_000))
    _fx_cycles   = _fx_state.get("cycle_count", 0)
    _fx_paused   = _fx_state.get("paused", False)
    _fx_usd_bias = _fx_state.get("usd_bias", "NEUTRAL")
    _fx_blackout = _fx_state.get("news_blackout", False)
    _fx_trades_n = _fx_state.get("total_trades", 0)
    _fx_wins     = _fx_state.get("total_wins", 0)
    _fx_pnl_all  = _fx_state.get("total_pnl", 0)
    _fx_hwm      = _fx_state.get("hwm_usd", 100_000)
    _fx_vault    = _fx_state.get("vault_total_usd", 0)
    _fx_start    = 100_000.0
    _fx_pnl_from_start = _fx_equity - _fx_start

    h2("OVERVIEW")
    row("Capital pool:", "Forex — Paper Trading (H4 Swing Strategy)")
    row("Bot status:", "PAUSED" if _fx_paused else ("RUNNING" if _fx_state.get("status") == "running" else _fx_state.get("status", "not_started")))
    row("USD bias (Groq macro):", _fx_usd_bias)
    row("News blackout:", "YES — trading paused" if _fx_blackout else "NO")
    row("Cycles completed:", str(_fx_cycles))
    row("Starting capital:", _c(_fx_start))
    row("Current equity:", _c(_fx_equity))
    row("Total P&L:", f"{_c(_fx_pnl_from_start)} ({_pct((_fx_pnl_from_start/_fx_start)*100)})")
    row("High water mark:", _c(_fx_hwm))
    row("Vault (profit lock):", _c(_fx_vault))
    row("Total trades:", str(_fx_trades_n))
    row("Wins:", str(_fx_wins))
    _fx_wr = (_fx_wins / _fx_trades_n * 100) if _fx_trades_n > 0 else 0
    row("Win rate:", _pct(_fx_wr, 1))
    row("Open positions:", str(len(_fx_positions)))

    h2("CURRENT FOREX POSITIONS")
    if not _fx_positions:
        lines.append("  No open forex positions.")
    else:
        for fp in _fx_positions:
            pair    = fp.get("pair", "?")
            dirn    = fp.get("direction", "?").upper()
            entry   = fp.get("entry_price", 0)
            curr    = fp.get("current_price", 0)
            pnl_p   = fp.get("unrealized_pnl_pips", fp.get("pnl_pips", 0))
            pnl_u   = fp.get("unrealized_pnl_usd", fp.get("pnl_usd", 0))
            sl      = fp.get("sl_price", fp.get("stop_loss", 0))
            tp      = fp.get("tp_price", fp.get("take_profit", 0))
            units   = fp.get("units", 0)
            lines.append(f"\n  {pair}  {dirn}")
            row("Units:", f"{units:,.0f}", indent=2)
            row("Entry:", f"{entry:.5f}", indent=2)
            row("Current:", f"{curr:.5f}", indent=2)
            row("P&L:", f"{_c(pnl_u)} ({pnl_p:+.1f} pips)", indent=2)
            row("Stop loss:", f"{sl:.5f}", indent=2)
            row("Take profit:", f"{tp:.5f}", indent=2)

    h2("FOREX TRADE HISTORY (recent trades)")
    if not _fx_trades:
        lines.append("  No forex trade history yet.")
    else:
        lines.append(f"  Total recorded: {len(_fx_trades)}")
        lines.append(f"  {'#':<4} {'Date':<18} {'Pair':<12} {'Dir':<6} {'Entry':>10} {'Exit':>10} {'PnL$':>10} {'Pips':>7}  Reason")
        lines.append("  " + "-" * 85)
        for i, ft in enumerate(_fx_trades[-30:], 1):
            pair   = str(ft.get("pair", "?"))[:11]
            dt     = str(ft.get("closed_at") or ft.get("exit_time") or "?")[:16]
            dirn   = str(ft.get("direction", "?")).upper()[:5]
            entry  = ft.get("entry_price", 0)
            exit_p = ft.get("exit_price", 0)
            pusd   = ft.get("pnl_usd", 0)
            pips   = ft.get("pnl_pips", 0)
            reason = str(ft.get("exit_reason") or ft.get("reason") or "?")[:30]
            lines.append(f"  {i:<4} {dt:<18} {pair:<12} {dirn:<6} {entry:>10.5f} {exit_p:>10.5f} {_c(pusd):>10} {pips:>+7.1f}  {reason}")

    h2("FOREX STRATEGY PARAMETERS")
    lines += [
        "  Strategy:          H4 swing — 5 major pairs (EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD)",
        "  AI engine:         Groq Llama 3.3 70B — USD directional bias only (BULLISH/BEARISH/NEUTRAL)",
        "  Cycle frequency:   Every 4 hours (24/7)",
        "  Position sizing:   3% risk per trade, ATR-based stop loss",
        "  Max positions:     5 simultaneous",
        "  Entry:             EMA crossover + RSI + MACD confluence, filtered by USD bias",
        "  Stop loss:         1.5× ATR from entry",
        "  Take profit:       2.0× risk (R:R = 1:2)",
        "  Profit vault:      10% of realized profits locked in vault",
        "  News blackout:     Groq detects high-impact events → pauses trading",
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6: COMBINED FLEET PORTFOLIO (ALL 6 BOTS)
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 6: COMBINED FLEET PORTFOLIO — ALL 6 BOTS")

    grand_start = 600_000.0
    grand_now   = equity + _all_kraken_equity + _opts_equity + _fx_equity
    grand_pnl   = grand_now - grand_start
    grand_pct   = (grand_pnl / grand_start) * 100 if grand_start else 0

    row("Total starting capital:", f"{_c(grand_start)} across 4 capital pools, 6 bots")
    lines.append("")
    row("Bot #1 Oracle (Alpaca):", f"{_c(equity)}  ({_pct((equity - 100_000) / 100_000 * 100)} from $100k)")
    _k_fleet_pnl_s = _all_kraken_equity - _all_kraken_starting
    row("Bots #2-4 Kraken Fleet:", f"{_c(_all_kraken_equity)}  ({_pct((_k_fleet_pnl_s/_all_kraken_starting)*100 if _all_kraken_starting else 0)} from {_c(_all_kraken_starting)})")
    for _kbid2, _kprof2 in KRAKEN_BOT_PROFILES.items():
        _kdbid2 = _kprof2["db_id"]
        _keq2 = _kraken_per_bot_equity.get(_kbid2, 0)
        row(f"  - {_kprof2['display_name']} (#{_kdbid2+1}):", _c(_keq2))
    row("Bot #5 Apex Predator:", f"{_c(_opts_equity)}  ({_pct((_opts_pnl/_opts_start)*100)} from $100k)")
    row("Bot #6 Navigator:", f"{_c(_fx_equity)}  ({_pct((_fx_pnl_from_start/_fx_start)*100)} from $100k)")
    lines.append("")
    row("GRAND TOTAL EQUITY:", _c(grand_now))
    row("COMBINED P&L:", f"{_c(grand_pnl)} ({_pct(grand_pct)})")

    lines.append("")
    lines.append("  CAPITAL POOLS:")
    lines.append("    Pool 1: Alpaca US Equities     $100k  (Bot #1 Oracle)")
    lines.append("    Pool 2: Kraken Crypto Fleet    $300k  (Bots #2 Davy Jones, #3 Blackbeard, #4 Calypso)")
    lines.append("    Pool 3: Options (Apex Predator) $100k (Bot #5)")
    lines.append("    Pool 4: Forex (Navigator)       $100k (Bot #6)")
    lines.append("  Each pool is independent — different asset classes, strategies, and risk profiles.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 7: AI LEARNING JOURNAL
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 7: AI LEARNING JOURNAL (Persistent insights across cycles)")
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
    # SECTION 8: STRATEGY PARAMETERS
    # ─────────────────────────────────────────────────────────────────────────
    h1("SECTION 8: STRATEGY PARAMETERS — ALL 6 BOTS (for LLM context)")

    h2("BOT #1: ORACLE (ALPACA) — HOW IT WORKS")
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

    h2("BOTS #2-4: KRAKEN FLEET — HOW THEY WORK")
    lines += [
        "  Bots:              #2 Davy Jones (Conservative), #3 Blackbeard (Aggressive), #4 Calypso (Most Aggressive)",
        "  Execution:         Kraken exchange (paper trading simulation, $100k each)",
        "  Strategy:          Mean reversion + momentum with VPIN microstructure filter",
        "  Pairs:             35+ crypto pairs (BTC, ETH, XRP, SOL, BNB, ADA, DOT, AVAX, etc.)",
        "  Position sizing:   10-15% of equity per position (varies by bot aggression)",
        "  Max positions:     10 simultaneous per bot",
        "  VPIN filter:       Volume-synchronized Probability of Informed Trading.",
        "                     VPIN > 0.65-0.75 blocks entries (varies by bot)",
        "  Stop loss:         Trailing — adapts to best price seen",
        "  Take profit:       Fixed target from entry",
        "  Circuit breaker:   Pauses bot after N consecutive losses",
        "  Cycle:             Runs 24/7 every 60s (crypto never closes)",
        "  Sides:             Both LONG and SHORT allowed",
    ]

    h2("BOT #5: APEX PREDATOR — HOW IT WORKS")
    lines += [
        "  Strategy:          Volatility Squeeze → Long Straddle (100% quant, LLM-free)",
        "  Execution:         Paper trading with real options chain data",
        "  Scan schedule:     Daily at 3:30 PM ET (Mon–Fri)",
        "  Capital fence:     20% of equity max deployed",
        "  Entry:             Bollinger Band squeeze + low IV rank → ATM straddle",
        "  Exit:              Profit target or time decay threshold",
    ]

    h2("BOT #6: THE NAVIGATOR — HOW IT WORKS")
    lines += [
        "  Strategy:          H4 swing — 5 major forex pairs",
        "  Pairs:             EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD",
        "  AI engine:         Groq Llama 3.3 70B — USD directional bias only",
        "  Cycle frequency:   Every 4 hours (24/7)",
        "  Position sizing:   3% risk per trade, ATR-based stop loss",
        "  Max positions:     5 simultaneous",
        "  Stop loss:         1.5× ATR from entry",
        "  Take profit:       2.0× risk (R:R = 1:2)",
        "  Profit vault:      10% of realized profits locked in vault",
        "  News blackout:     Groq detects high-impact events → pauses trading",
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


# ── Bot #5: Apex Predator — Options Engine ────────────────────────────────────
# Pure quant, 100% LLM-free. Volatility Squeeze → Long Straddle.
import options_engine as _opts

@router.get("/options/state")
async def options_state():
    return _opts.get_full_state()

@router.get("/options/positions")
async def options_positions():
    positions = _opts._get_positions()
    return {"positions": positions, "count": len(positions)}

@router.get("/options/pending")
async def options_pending():
    pending = _opts._get_pending()
    return {"pending": pending, "count": len(pending)}

class _OptionsApproveReq(BaseModel):
    trade_id: str

@router.post("/options/approve")
async def options_approve(req: _OptionsApproveReq):
    result = _opts.approve_trade(req.trade_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/options/reject")
async def options_reject(req: _OptionsApproveReq):
    result = _opts.reject_trade(req.trade_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/options/toggle")
async def options_toggle():
    return _opts.toggle_pause()

@router.post("/options/scan")
async def options_manual_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(_opts.scan_for_setups)
    return {"status": "scan_queued"}

@router.post("/options/close")
async def options_close_position(req: _OptionsApproveReq):
    result = _opts.close_position_by_id(req.trade_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

# ── Bot #6: The Navigator — Forex Swing Engine ──────────────────────────────────
# H4 cycle, 5 major pairs, Groq Macro Compass for USD bias only.
_FOREX_ENGINE_PATH = os.path.join(_REPO_ROOT, "forex-engine")
if _FOREX_ENGINE_PATH not in sys.path:
    sys.path.append(_FOREX_ENGINE_PATH)

_forex_engine_module = None
def _get_forex_engine():
    global _forex_engine_module
    if _forex_engine_module is not None:
        return _forex_engine_module
    try:
        import importlib.util as _ilu3
        _fx_path = os.path.join(_REPO_ROOT, "forex-engine")
        if _fx_path not in sys.path:
            sys.path.insert(0, _fx_path)

        spec = _ilu3.spec_from_file_location("forex_engine", os.path.join(_fx_path, "forex_engine.py"))
        mod = _ilu3.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _forex_engine_module = mod
        return mod
    except Exception as exc:
        logger.warning(f"Forex engine import failed: {exc}")
        return None

_forex_db_module = None
def _get_forex_db():
    global _forex_db_module
    if _forex_db_module is not None:
        return _forex_db_module
    try:
        import importlib.util as _ilu2
        _fx_path = os.path.join(_REPO_ROOT, "forex-engine")
        spec = _ilu2.spec_from_file_location("forex_db", os.path.join(_fx_path, "forex_nav_db.py"))
        mod = _ilu2.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _forex_db_module = mod
        return mod
    except Exception as exc:
        logger.warning(f"Forex DB import failed: {exc}")
        return None


@router.get("/forex/state")
async def forex_state():
    fx = _get_forex_engine()
    if fx is None:
        return {
            "status": "not_started",
            "paused": False,
            "cycle_count": 0,
            "usd_bias": "NEUTRAL",
            "news_blackout": False,
            "paper_mode": True,
            "paper_equity": 100000.0,
            "total_equity": 100000.0,
            "position_count": 0,
            "total_trades": 0,
            "total_wins": 0,
            "total_pnl": 0.0,
            "hwm_usd": 100000.0,
            "vault_total_usd": 0.0,
            "error": None,
        }
    return fx.get_state()

@router.get("/forex/positions")
async def forex_positions():
    fx = _get_forex_engine()
    if fx is None:
        return {"positions": [], "count": 0}
    positions = fx.get_positions()
    return {"positions": positions, "count": len(positions)}

@router.get("/forex/trades")
async def forex_trades():
    fxdb = _get_forex_db()
    if fxdb is None:
        return {"trades": [], "count": 0}
    trades = fxdb.load_recent_trades(limit=50)
    return {"trades": trades, "count": len(trades)}

@router.get("/forex/journal")
async def forex_journal():
    try:
        import importlib.util as _ilu_j
        _fx_path = os.path.join(_REPO_ROOT, "forex-engine")
        spec = _ilu_j.spec_from_file_location("forex_journal", os.path.join(_fx_path, "journal.py"))
        mod = _ilu_j.module_from_spec(spec)
        spec.loader.exec_module(mod)
        entries = mod.get_journal_entries(limit=50)
        stats = mod.get_journal_stats()
        return {"entries": entries, "stats": stats, "count": len(entries)}
    except Exception:
        return {"entries": [], "stats": {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0, "avg_pips": 0}, "count": 0}

@router.get("/forex/vault")
async def forex_vault():
    fxdb = _get_forex_db()
    if fxdb is None:
        return {"vault_total_usd": 0, "sweeps": []}
    try:
        sweeps = fxdb.load_vault_history()
    except Exception:
        sweeps = []
    fx = _get_forex_engine()
    vault_total = 0
    if fx:
        state = fx.get_state()
        vault_total = state.get("vault_total_usd", 0)
    return {"vault_total_usd": vault_total, "sweeps": sweeps}

@router.post("/forex/toggle")
async def forex_toggle():
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    state = fx.get_state()
    if state.get("paused"):
        fx.resume_bot()
        return {"paused": False, "message": "Navigator resumed"}
    else:
        fx.pause_bot()
        return {"paused": True, "message": "Navigator paused"}

@router.post("/forex/pause")
async def forex_pause():
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    fx.pause_bot()
    return {"paused": True, "message": "Navigator paused"}

@router.post("/forex/resume")
async def forex_resume():
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    fx.resume_bot()
    return {"paused": False, "message": "Navigator resumed"}

@router.post("/forex/scan")
async def forex_manual_scan(background_tasks: BackgroundTasks):
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    background_tasks.add_task(fx.run_cycle)
    return {"status": "forex_scan_queued"}

# ── Alert Notification System ──────────────────────────────────────────────────
from notifications import alert_manager as _alert_mgr

@router.get("/alerts/config")
async def alerts_config():
    return _alert_mgr.get_config()

@router.post("/alerts/config")
async def alerts_config_update(request: Request):
    body = await request.json()
    return _alert_mgr.save_config(body)

@router.get("/alerts/status")
async def alerts_status():
    return _alert_mgr.get_queue_status()

@router.post("/alerts/test")
async def alerts_test():
    from notifications.telegram import send_test_message, is_configured as tg_ok
    from notifications.discord import is_configured as dc_ok, _send_async, _embed, COLOR_PURPLE
    tg_result = False
    dc_result = False
    if tg_ok():
        tg_result = send_test_message()
    if dc_ok():
        try:
            _send_async({"embeds": [_embed("\U0001f514 Alert Test", "This is a test notification from AlgoEdge.", COLOR_PURPLE)]})
            dc_result = True
        except Exception:
            dc_result = False
    return {
        "telegram_configured": tg_ok(),
        "telegram_sent": tg_result,
        "discord_configured": dc_ok(),
        "discord_sent": dc_result,
        "detail": f"TG={'sent' if tg_result else 'skip'} DC={'sent' if dc_result else 'skip'}",
    }

@router.post("/alerts/flush")
async def alerts_flush():
    count = _alert_mgr.flush_alerts()
    return {"flushed": count}

app.include_router(router)

# ── System B: Public SaaS Platform routes ─────────────────────────────────────
# Registered separately under /saas-api — no overlap with /trading-api above.
from saas_router import saas_router                          # noqa: E402
from saas_stripe_router import stripe_bp                     # noqa: E402
app.include_router(saas_router)
app.include_router(stripe_bp, prefix="/saas-api")
