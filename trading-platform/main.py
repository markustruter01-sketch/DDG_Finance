"""
Trading Platform — FastAPI Application
----------------------------------------
Serves as both the HTTP API and the host for the APScheduler background jobs.

All endpoint handlers live in ``routes/`` sub-modules.  This file keeps only:
  • lifespan (scheduler bootstrap, DB init, commentary cache load)
  • DegradationCaptureMiddleware
  • app / router creation
  • router wire-up (include_router for trading-api routers)
"""

import asyncio
import hashlib
import hmac
import os
import subprocess as _subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone as _tz
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, APIRouter
from loguru import logger

# ── Running-process git hash (captured once at startup) ──────────────────────
def _read_git_hash() -> str:
    try:
        return _subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=_subprocess.DEVNULL,
            timeout=3,
        ).decode().strip()
    except Exception:
        return "unknown"

_RUNNING_HASH: str = _read_git_hash()
_STARTED_AT: str   = datetime.now(_tz.utc).isoformat()

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config.settings import settings
from core.scheduler import get_scheduler
from execution.broker import get_account
from analysis.trade_journal import init_db

from routes._deps import (
    _load_commentary_caches,
    _get_forex_engine,
)
from routes import ALL_ROUTERS
from routes.bot_registry_route import router as bot_registry_router
from routes.reports import router as reports_router
from routes.strategy_bench import router as strategy_bench_router


def _database_host_fingerprint(dsn: str | None) -> str:
    if not dsn:
        return "none"
    try:
        hostname = urlparse(dsn).hostname
        if hostname is None:
            return "none"
        return hashlib.sha256(hostname.encode()).hexdigest()[:12]
    except Exception:
        return "unavailable"


def _log_database_identity() -> None:
    try:
        from db.postgres import _get_dsn
        from core import database_authority

        try:
            postgres_fingerprint = _database_host_fingerprint(_get_dsn())
        except Exception:
            postgres_fingerprint = "unavailable"

        try:
            invariants_dsn = (
                os.environ.get("INVARIANTS_DATABASE_URL")
                or os.environ.get("DATABASE_URL")
            )
            invariants_fingerprint = _database_host_fingerprint(invariants_dsn)
        except Exception:
            invariants_fingerprint = "unavailable"

        try:
            authoritative_fingerprint = _database_host_fingerprint(
                database_authority.get_authoritative_dsn()
            )
        except Exception:
            authoritative_fingerprint = "unavailable"

        deployment = os.environ.get("REPLIT_DEPLOYMENT") or "unset"
        logger.info(
            "DB identity | "
            f"postgres_dsn={postgres_fingerprint} "
            f"invariants_dsn={invariants_fingerprint} "
            f"authoritative_dsn={authoritative_fingerprint} "
            f"deployment={deployment}"
        )
    except Exception:
        logger.info(
            "DB identity | "
            "postgres_dsn=unavailable "
            "invariants_dsn=unavailable "
            "authoritative_dsn=unavailable "
            f"deployment={os.environ.get('REPLIT_DEPLOYMENT') or 'unset'}"
        )


def _record_yahoo_refresh_failure(error_type: str, message: str, exc: Exception) -> None:
    try:
        from core.degradation_tracker import record_degradation

        record_degradation(
            component="data_pipeline",
            severity="error",
            error_type=error_type,
            message=message[:480],
            detail=repr(exc),
        )
    except Exception as _degradation_error:
        logger.error(
            f"Yahoo refresh | Failed to record degradation for {error_type}: "
            f"{_degradation_error}"
        )


def _refresh_crypto_yahoo_history() -> None:
    try:
        from analysis import crypto_data_pipeline

        counts = crypto_data_pipeline.ingest_yahoo_history()
        for symbol, count in counts.items():
            logger.info(f"Yahoo refresh | crypto | {symbol}: {count} bars stored")
        from core.degradation_tracker import mark_resolved

        mark_resolved(
            component="data_pipeline",
            error_type="crypto_yahoo_history_refresh_failed",
            reason="refresh succeeded",
        )
    except Exception as _exc:
        logger.error(f"Yahoo refresh | crypto history failed: {_exc}")
        _record_yahoo_refresh_failure(
            "crypto_yahoo_history_refresh_failed",
            f"Crypto Yahoo history refresh failed: {_exc!s}",
            _exc,
        )


def _refresh_bot3_metals_history() -> None:
    try:
        from analysis import bot3_data_pipeline

        counts = bot3_data_pipeline.ingest_metals()
        for symbol, count in counts.items():
            logger.info(f"Yahoo refresh | Bot 3 metals | {symbol}: {count} bars stored")
        from core.degradation_tracker import mark_resolved

        mark_resolved(
            component="data_pipeline",
            error_type="bot3_metals_history_refresh_failed",
            reason="refresh succeeded",
        )
    except Exception as _exc:
        logger.error(f"Yahoo refresh | Bot 3 metals history failed: {_exc}")
        _record_yahoo_refresh_failure(
            "bot3_metals_history_refresh_failed",
            f"Bot 3 metals Yahoo history refresh failed: {_exc!s}",
            _exc,
        )


YAHOO_STARTUP_DELAY_SECONDS = 60


def _scheduler_enabled_for_current_environment() -> bool:
    # Match the runner's environment resolution exactly:
    # kraken-bot/runner.py:152-155. REPLIT_DEPLOYMENT is the shared deployment
    # signal, with RUNNER_ENVIRONMENT as the same explicit override.
    environment = os.environ.get(
        "RUNNER_ENVIRONMENT",
        "published" if os.environ.get("REPLIT_DEPLOYMENT") == "1" else "dev",
    )
    if environment == "published":
        return True
    if environment == "dev":
        return False
    raise RuntimeError(
        f"Unknown RUNNER_ENVIRONMENT={environment!r}; "
        "expected 'published' or 'dev'."
    )


def _start_scheduler(scheduler_enabled: bool) -> Any | None:
    if not scheduler_enabled:
        logger.info("scheduler disabled (workspace)")
        return None

    scheduler = get_scheduler()
    scheduler.start()
    logger.info(
        f"Scheduler started — {len(scheduler.get_jobs())} trading jobs registered "
        "(auto-trading ON by default)"
    )
    logger.info("Disable auto-trading via dashboard toggle or POST /auto-trading")
    logger.info("24/7 crypto trading enabled — crypto cycles fire when stock market is closed")
    return scheduler


def _add_scheduler_job(scheduler: Any | None, **job: Any) -> None:
    if scheduler is not None:
        scheduler.add_job(**job)


def _register_yahoo_refresh_jobs(scheduler) -> None:
    """Register Yahoo refreshes with a delayed first run, then every six hours."""

    if scheduler is None:
        return

    from apscheduler.triggers.interval import IntervalTrigger

    first_run = datetime.now(_tz.utc) + timedelta(seconds=YAHOO_STARTUP_DELAY_SECONDS)
    _add_scheduler_job(
        scheduler,
        func=_refresh_crypto_yahoo_history,
        trigger=IntervalTrigger(hours=6),
        id="crypto_yahoo_history_refresh",
        name="Crypto Yahoo History Refresh",
        replace_existing=True,
        misfire_grace_time=300,
        next_run_time=first_run,
    )
    _add_scheduler_job(
        scheduler,
        func=_refresh_bot3_metals_history,
        trigger=IntervalTrigger(hours=6),
        id="bot3_metals_history_refresh",
        name="Bot 3 Metals Yahoo History Refresh",
        replace_existing=True,
        misfire_grace_time=300,
        next_run_time=first_run,
    )
    logger.info("Yahoo refresh | crypto and Bot 3 metals jobs registered (6-hour interval)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_enabled = _scheduler_enabled_for_current_environment()
    logger.add(
        settings.log_file,
        level=settings.log_level,
        rotation="1 day",
        retention="30 days",
        compression="gz",
        enqueue=True,
    )
    _log_database_identity()
    logger.info("=" * 60)
    logger.info("TRADING PLATFORM STARTING")
    logger.info("=" * 60)

    init_db()
    logger.info("Trade journal database initialised")

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
    from core.database_authority import assert_database_authority
    try:
        assert_database_authority()
        logger.info("Database authority assertion: PASS — DATABASE_URL")
    except Exception as _db_authority_exc:
        logger.critical(f"Database authority assertion: FAIL — {_db_authority_exc}")
        raise
    from routes.entry_windows import assert_entry_window_alignment
    assert_entry_window_alignment()

    scheduler = _start_scheduler(scheduler_enabled)

    from apscheduler.triggers.interval import IntervalTrigger as _ITrigger
    def _scheduled_snapshot_export():
        try:
            from analysis.learning_snapshot import export_snapshot
            export_snapshot()
        except Exception as _ex:
            logger.warning(f"Learning Snapshot | Scheduled export failed: {_ex}")

    _add_scheduler_job(
        scheduler,
        func=_scheduled_snapshot_export,
        trigger=_ITrigger(hours=6),
        id="learning_snapshot_export",
        name="Learning Snapshot Auto-Export",
        replace_existing=True,
        misfire_grace_time=300,
    )
    if scheduler is not None:
        logger.info("Learning snapshot auto-export registered (6-hour interval)")

    def _record_fleet_equity_snapshots():
        try:
            from core.bot_state import get_all_portfolios
            from db.postgres import insert_fleet_equity_snapshots
            portfolios = get_all_portfolios()
            rows = [
                (p["bot_id"], float(p.get("equity_usd") or 0.0))
                for p in portfolios
                if p.get("equity_usd") is not None
            ]
            inserted = insert_fleet_equity_snapshots(rows)
            logger.info(
                f"Fleet equity snapshot | wrote {inserted}/{len(rows)} active bot rows"
            )
        except Exception as _e:
            logger.warning(f"Fleet equity snapshot | Failed: {_e}")

    _record_fleet_equity_snapshots()
    _add_scheduler_job(
        scheduler,
        func=_record_fleet_equity_snapshots,
        trigger=_ITrigger(hours=1),
        id="hourly_equity_snapshot",
        name="Hourly Active-Bot Equity Snapshot",
        replace_existing=True,
        misfire_grace_time=600,
    )
    if scheduler is not None:
        logger.info("Hourly equity snapshot job registered (active bots, every 1 hour)")

    from core.ddg_push import push_fleet_snapshot
    _ddg_push_first_run = datetime.fromisoformat(_STARTED_AT) + timedelta(minutes=5)
    _add_scheduler_job(
        scheduler,
        func=push_fleet_snapshot,
        trigger=_ITrigger(hours=1),
        id="ddg_fleet_snapshot_push",
        name="Hourly DDG Fleet Snapshot Push",
        replace_existing=True,
        next_run_time=_ddg_push_first_run,
    )
    if scheduler is not None:
        logger.info("DDG fleet push job registered (hourly, 5-minute startup delay)")

    _register_yahoo_refresh_jobs(scheduler)

    from apscheduler.triggers.cron import CronTrigger as _CronTrigger
    logger.info("Apex Predator options engine removed — Bot #5 now runs as crypto momentum scalper via Kraken pool")

    # FOREX NAVIGATOR is retired. Its engine code remains on disk as a
    # preservation parachute, but trading-api startup must not bootstrap or
    # resurrect its retired PostgreSQL tables.

    try:
        from notifications.alert_manager import start_alert_scheduler
        if scheduler is not None:
            start_alert_scheduler()
            logger.info("Alert manager started (batched Telegram/Discord notifications)")
    except Exception as _alert_err:
        logger.warning(f"Alert manager startup failed (non-fatal): {_alert_err}")

    def _fleet_commander_run():
        try:
            from analysis.fleet_commander import run_fleet_commander
            result = run_fleet_commander()
            logger.info(f"Fleet Commander | Scheduled run complete: verdict={result.get('overall_verdict', 'N/A')}")
        except Exception as _fce:
            logger.warning(f"Fleet Commander | Scheduled run failed (fail-open): {_fce}")

    _fc_schedule = [
        (17, 0, "Post-Close 5:00 PM"),
    ]
    for _fc_h, _fc_m, _fc_label in _fc_schedule:
        _add_scheduler_job(
            scheduler,
            func=_fleet_commander_run,
            trigger=_CronTrigger(hour=_fc_h, minute=_fc_m, timezone="US/Eastern"),
            id=f"fleet_commander_{_fc_h:02d}{_fc_m:02d}",
            name=f"Fleet Commander ({_fc_label} ET)",
            replace_existing=True,
            misfire_grace_time=600,
        )
    if scheduler is not None:
        logger.info(
            f"Fleet Commander registered — {len(_fc_schedule)} daily audit runs scheduled"
        )

    # ── Stage 6: OHLCV Data Ingest — run on startup if historical_prices is empty ──
    try:
        from analysis.ingest_kraken_ohlcv import needs_ingest, run_ingest
        if needs_ingest():
            logger.info("OHLCV | historical_prices table is empty — running startup ingest …")

            def _startup_ingest():
                try:
                    summary = run_ingest()
                    for key, r in summary.items():
                        if "error" not in r:
                            rng = r.get("range")
                            rng_str = f"{rng[0]} → {rng[1]}" if rng else "N/A"
                            logger.info(
                                f"OHLCV | {key}: {r.get('total', 0)} candles stored | "
                                f"range: {rng_str}"
                            )
                        else:
                            logger.warning(f"OHLCV | {key}: {r.get('error')}")
                except Exception as _ie:
                    logger.warning(f"OHLCV | Startup ingest failed (non-fatal): {_ie}")
                    # Audit fix H6: surface silent ingest failures so the
                    # dashboard knows historical_prices is empty.
                    try:
                        from core.degradation_tracker import record_degradation
                        record_degradation(
                            component="data_pipeline",
                            severity="error",
                            error_type="ohlcv_startup_ingest_failed",
                            message=f"OHLCV startup ingest failed: {_ie!s}"[:480],
                            detail=f"historical_prices may be empty; backtester will skip. {_ie!r}",
                        )
                    except Exception:
                        pass

            def _supervised_startup_ingest():
                try:
                    _startup_ingest()
                except Exception as _se:
                    logger.error(f"OHLCV | Background ingest thread crashed: {_se!r}")
                    try:
                        from core.degradation_tracker import record_degradation
                        record_degradation(
                            component="data_pipeline",
                            severity="critical",
                            error_type="ohlcv_thread_crash",
                            message=f"OHLCV background thread crashed: {_se!s}"[:480],
                            detail=f"{_se!r}",
                        )
                    except Exception:
                        pass

            import threading as _threading_ohlcv
            _t = _threading_ohlcv.Thread(target=_supervised_startup_ingest, daemon=True, name="ohlcv-startup-ingest")
            _t.start()
            logger.info("OHLCV | Startup ingest launched in background thread")
        else:
            logger.info("OHLCV | historical_prices already populated — skipping startup ingest")
    except Exception as _ohlcv_err:
        logger.warning(f"OHLCV | Startup ingest check failed (non-fatal): {_ohlcv_err}")

    # ── Audit fix M4: Nightly retention sweep (3:15 AM UTC) ──────────────────
    # Tables grow forever without this. Defaults: 90-day window for high-volume
    # series, longer for low-volume. Logged so the operator can verify counts.
    def _retention_sweep() -> None:
        from db.postgres import is_pg_available, get_conn
        if not is_pg_available():
            return
        # (table, ts_column, retention_days) — kept conservative
        plans = [
            ("system_degradations",  "ts",        90),
            # historical_prices: keep daily candles (1d) ~3y, hourly ~90d via
            # delete-by-timeframe so the backtester still has a long lookback.
            # Hourly bars churn most; daily bars rarely.
        ]
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for table, ts_col, days in plans:
                        try:
                            cur.execute(
                                f'DELETE FROM {table} WHERE "{ts_col}" < NOW() - INTERVAL %s',
                                (f"{days} days",),
                            )
                            logger.info(
                                f"M4 retention | {table}: deleted {cur.rowcount} rows "
                                f"older than {days}d"
                            )
                        except Exception as _te:
                            logger.warning(f"M4 retention | {table} sweep failed: {_te}")
                    # historical_prices: hourly only (1d preserved indefinitely)
                    try:
                        cur.execute(
                            'DELETE FROM historical_prices '
                            'WHERE timeframe = %s AND "timestamp" < NOW() - INTERVAL %s',
                            ("1h", "90 days"),
                        )
                        logger.info(
                            f"M4 retention | historical_prices(1h): deleted {cur.rowcount} rows older than 90d"
                        )
                    except Exception as _te:
                        logger.warning(f"M4 retention | historical_prices sweep failed: {_te}")
        except Exception as _se:
            logger.warning(f"M4 retention | Nightly sweep failed (non-fatal): {_se}")

    _add_scheduler_job(
        scheduler,
        func=_retention_sweep,
        trigger=_CronTrigger(hour=3, minute=15, timezone="UTC"),
        id="nightly_retention_sweep",
        name="Nightly retention sweep (3:15 AM UTC) — M4",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    if scheduler is not None:
        logger.info("Retention | Registered: nightly_retention_sweep (3:15 AM UTC) — M4")

    # ── Review Flag Scheduler — daily performance checks ─────────────────────
    from core.review_scheduler import run_scheduled_checks as _run_review_checks
    _add_scheduler_job(
        scheduler,
        func=_run_review_checks,
        trigger=_CronTrigger(hour=17, minute=30, timezone="America/New_York"),
        id="daily_review_flags",
        name="Daily Review Flag Checker (5:30 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )
    if scheduler is not None:
        logger.info("ReviewScheduler | Registered: daily_review_flags (5:30 PM ET)")

    # ── Seed review flags immediately on startup (ensures production DB is populated) ─
    try:
        _run_review_checks()
        logger.info("ReviewScheduler | Startup seed complete")
    except Exception as _rev_err:
        logger.warning(f"ReviewScheduler | Startup seed failed (non-fatal): {_rev_err}")

    # ── Math Auditor — independent formula verification ─────────────────────
    try:
        from math_auditor import ensure_table as _ma_ensure, run_quick_audit, run_full_audit, run_deep_audit

        _ma_ensure()  # create math_audit_log table if needed
        logger.info("MathAuditor | DB table ensured")

        def _math_audit_quick():
            try:
                run_quick_audit()
            except Exception as _mae:
                logger.warning(f"MathAuditor | quick audit failed: {_mae}")

        def _math_audit_full():
            try:
                run_full_audit()
            except Exception as _mae:
                logger.warning(f"MathAuditor | full audit failed: {_mae}")

        def _math_audit_deep():
            try:
                run_deep_audit()
            except Exception as _mae:
                logger.warning(f"MathAuditor | deep audit failed: {_mae}")

        _add_scheduler_job(
            scheduler,
            func=_math_audit_quick,
            trigger=_ITrigger(minutes=15),
            id="math_audit_quick",
            name="Math Auditor — Quick (ATR + sizing, 15 min)",
            replace_existing=True,
            misfire_grace_time=120,
        )
        _add_scheduler_job(
            scheduler,
            func=_math_audit_full,
            trigger=_ITrigger(minutes=15),
            id="math_audit_full",
            name="Math Auditor — Full (all formulas, 15 min)",
            replace_existing=True,
            misfire_grace_time=120,
        )
        _add_scheduler_job(
            scheduler,
            func=_math_audit_deep,
            trigger=_ITrigger(hours=4),
            id="math_audit_deep",
            name="Math Auditor — Deep (Hurst + hedge ratio, 4h)",
            replace_existing=True,
            misfire_grace_time=600,
        )
        if scheduler is not None:
            logger.info("MathAuditor | 3 jobs registered: quick (60s), full (15 min), deep (4h)")
    except Exception as _ma_boot_err:
        logger.warning(f"MathAuditor | Boot failed (non-fatal): {_ma_boot_err}")

    yield

    if scheduler is not None:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
    logger.info("Trading platform stopped.")


API_PREFIX = os.getenv("API_PREFIX", "")

app = FastAPI(
    title="AI Quantitative Trading Platform",
    description=(
        "AI-driven macro quant trading system. "
        "FRED macro + Alpaca market data + NewsAPI → "
        "Gemini (gemini-3-flash-preview) → Kelly-sized 10-slot allocation → "
        "Alpaca paper trading execution."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

router = APIRouter(prefix=API_PREFIX)


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse, Response as StarletteResponse

# Audit fix H8: degradation tracker now captures ALL 5xx, not a hardcoded
# whitelist.  Tracebacks are captured when the route raises an unhandled
# exception so root-cause is visible without grepping logs.
import traceback as _traceback


class DegradationCaptureMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        path = request.url.path
        try:
            response = await call_next(request)
        except Exception as exc:
            # Unhandled exception bubbled out of a route — record full traceback
            # then re-raise so FastAPI's normal error handling still fires.
            try:
                from core.degradation_tracker import record_degradation
                tb = _traceback.format_exc()[-1800:]
                short_path = path.replace(API_PREFIX, "") if API_PREFIX in path else path
                record_degradation(
                    component="http",
                    severity="critical",
                    error_type=type(exc).__name__,
                    message=f"Unhandled exception on {short_path}: {exc!s}"[:480],
                    detail=f"method={request.method} full_path={path}\n{tb}",
                )
            except Exception:
                pass
            raise

        if response.status_code >= 500:
            try:
                from core.degradation_tracker import record_degradation
                short_path = path.replace(API_PREFIX, "") if API_PREFIX in path else path
                record_degradation(
                    component="http",
                    severity="error" if response.status_code == 500 else "warning",
                    error_type=str(response.status_code),
                    message=f"HTTP {response.status_code} on {short_path}",
                    detail=f"method={request.method} full_path={path}",
                )
            except Exception:
                pass
        return response


app.add_middleware(DegradationCaptureMiddleware)


TRADING_API_SECRET_HEADER = "X-Trading-API-Secret"


def _health_path() -> str:
    prefix = API_PREFIX.rstrip("/")
    return f"{prefix}/health" if prefix else "/health"


def _liveness_path() -> str:
    prefix = API_PREFIX.rstrip("/")
    return f"{prefix}/liveness" if prefix else "/liveness"


class TradingAPIAuthMiddleware(BaseHTTPMiddleware):
    """Require the shared API secret for every route except liveness health."""

    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        public_bench_catalog = (
            request.method == "GET"
            and request.url.path == "/trading-api/research/strategy-bench/catalog"
        )
        if (
            request.url.path in {_health_path(), _liveness_path()}
            or public_bench_catalog
        ):
            return await call_next(request)

        expected_secret = os.getenv("TRADING_API_SECRET", "").strip()
        if not expected_secret:
            logger.error("Trading API authentication is not configured; rejecting protected request")
            return JSONResponse(
                status_code=503,
                content={"detail": "Trading API authentication is not configured."},
            )

        supplied_secret = request.headers.get(TRADING_API_SECRET_HEADER, "")
        if not supplied_secret or not hmac.compare_digest(supplied_secret, expected_secret):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing trading API secret."},
                headers={"WWW-Authenticate": TRADING_API_SECRET_HEADER},
            )

        return await call_next(request)


app.add_middleware(TradingAPIAuthMiddleware)


@app.get("/trading-api/version", tags=["System"])
async def version_info():
    """
    Return the running-process git hash (captured at startup) alongside the
    current HEAD hash.  If they differ, the process has not been restarted
    since the last deploy — restart the deployment to pick up the new code.
    """
    try:
        latest = _subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=_subprocess.DEVNULL,
            timeout=3,
        ).decode().strip()
    except Exception:
        latest = "unknown"
    return {
        "running_hash": _RUNNING_HASH,
        "latest_hash":  latest,
        "match":        _RUNNING_HASH == latest,
        "started_at":   _STARTED_AT,
    }


for sub_router in ALL_ROUTERS:
    router.include_router(sub_router)

app.include_router(router)
# Local development normally supplies API_PREFIX through the deployment
# environment.  Keep the proxied /trading-api path available when running the
# API directly from a shell or from the test suite where API_PREFIX is empty.
if not API_PREFIX:
    app.include_router(strategy_bench_router, prefix="/trading-api")
app.include_router(bot_registry_router, prefix="/trading-api", tags=["bot-registry"])
app.include_router(reports_router)
