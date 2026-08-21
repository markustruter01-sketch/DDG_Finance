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
import os
import subprocess as _subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone as _tz
from typing import Any

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

    from apscheduler.triggers.interval import IntervalTrigger as _ITrigger
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
    scheduler.add_job(
        func=_record_fleet_equity_snapshots,
        trigger=_ITrigger(hours=1),
        id="hourly_equity_snapshot",
        name="Hourly Active-Bot Equity Snapshot",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Hourly equity snapshot job registered (active bots, every 1 hour)")

    async def _record_equity_snapshot_now():
        from db.postgres import insert_equity_snapshot
        try:
            acct = get_account()
            alpaca_eq = float(acct.get("equity", 0))
        except Exception:
            alpaca_eq = 0.0
        # Legacy Kraken/Forex pools were retired.  Fleet equity is sourced from
        # the canonical bot portfolio/fleet-equity path.
        kraken_eq = 0.0
        options_eq = 0.0
        forex_eq = 0.0
        try:
            fx = _get_forex_engine()
            if fx:
                fx_state = fx.get_state()
                forex_eq = float(fx_state.get("paper_equity", 0)) or 0.0
        except Exception:
            forex_eq = 0.0
        insert_equity_snapshot(
            alpaca_eq, kraken_eq, "LIVE", "hourly_heartbeat",
            options_equity=options_eq, forex_equity=forex_eq,
        )

    def _equity_heartbeat_sync():
        import asyncio as _aio
        try:
            _aio.run(_record_equity_snapshot_now())
            logger.info("Equity Heartbeat | snapshot written")
        except Exception as _e:
            logger.warning(f"Equity Heartbeat | Failed: {_e}")

    try:
        await _record_equity_snapshot_now()
        logger.info("Equity Curve | Startup snapshot written")
    except Exception as _ese:
        logger.warning(f"Equity Curve | Startup snapshot failed (non-fatal): {_ese}")

    scheduler.add_job(
        func=_equity_heartbeat_sync,
        trigger=_ITrigger(minutes=15),
        id="equity_curve_heartbeat",
        name="Equity Curve 15-min Heartbeat",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Equity curve heartbeat registered (15-min interval)")

    from apscheduler.triggers.cron import CronTrigger as _CronTrigger
    logger.info("Apex Predator options engine removed — Bot #5 now runs as crypto momentum scalper via Kraken pool")

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

    # FOREX NAVIGATOR DISABLED 2026-05-28 — forex shelved (2 backtests, both NO-GO).
    # Navigator slot repurposed as Buck Futures (kraken-bot/buck_futures_strategy.py).
    # Leaving _forex_navigator_cycle and forex-engine code on disk as a parachute.
    # import pytz as _pytz
    # _et_tz = _pytz.timezone("America/New_York")
    # scheduler.add_job(
    #     func=_forex_navigator_cycle,
    #     trigger=_ITrigger(hours=4),
    #     id="forex_navigator",
    #     name="Forex Navigator 4h Cycle",
    #     replace_existing=True,
    #     misfire_grace_time=600,
    #     next_run_time=__import__("datetime").datetime.now(_et_tz),
    # )
    # logger.info("Forex Navigator registered (4-hour interval, first run immediate)")

    try:
        from notifications.alert_manager import start_alert_scheduler
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
        scheduler.add_job(
            func=_fleet_commander_run,
            trigger=_CronTrigger(hour=_fc_h, minute=_fc_m, timezone="US/Eastern"),
            id=f"fleet_commander_{_fc_h:02d}{_fc_m:02d}",
            name=f"Fleet Commander ({_fc_label} ET)",
            replace_existing=True,
            misfire_grace_time=600,
        )
    logger.info(f"Fleet Commander registered — {len(_fc_schedule)} daily audit runs scheduled")

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
            ("equity_snapshots",     "ts",        90),
            ("system_degradations",  "ts",        90),
            ("oracle_scan_log",      "ts",        90),
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

    scheduler.add_job(
        func=_retention_sweep,
        trigger=_CronTrigger(hour=3, minute=15, timezone="UTC"),
        id="nightly_retention_sweep",
        name="Nightly retention sweep (3:15 AM UTC) — M4",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    logger.info("Retention | Registered: nightly_retention_sweep (3:15 AM UTC) — M4")

    # ── Review Flag Scheduler — daily performance checks ─────────────────────
    from core.review_scheduler import run_scheduled_checks as _run_review_checks
    scheduler.add_job(
        func=_run_review_checks,
        trigger=_CronTrigger(hour=17, minute=30, timezone="America/New_York"),
        id="daily_review_flags",
        name="Daily Review Flag Checker (5:30 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )
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

        scheduler.add_job(
            func=_math_audit_quick,
            trigger=_ITrigger(minutes=15),
            id="math_audit_quick",
            name="Math Auditor — Quick (ATR + sizing, 15 min)",
            replace_existing=True,
            misfire_grace_time=120,
        )
        scheduler.add_job(
            func=_math_audit_full,
            trigger=_ITrigger(minutes=15),
            id="math_audit_full",
            name="Math Auditor — Full (all formulas, 15 min)",
            replace_existing=True,
            misfire_grace_time=120,
        )
        scheduler.add_job(
            func=_math_audit_deep,
            trigger=_ITrigger(hours=4),
            id="math_audit_deep",
            name="Math Auditor — Deep (Hurst + hedge ratio, 4h)",
            replace_existing=True,
            misfire_grace_time=600,
        )
        logger.info("MathAuditor | 3 jobs registered: quick (60s), full (15 min), deep (4h)")
    except Exception as _ma_boot_err:
        logger.warning(f"MathAuditor | Boot failed (non-fatal): {_ma_boot_err}")

    yield

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
from starlette.responses import Response as StarletteResponse

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
app.include_router(bot_registry_router, prefix="/trading-api", tags=["bot-registry"])
app.include_router(reports_router)
