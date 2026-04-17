"""
Trading Platform — FastAPI Application
----------------------------------------
Serves as both the HTTP API and the host for the APScheduler background jobs.

All endpoint handlers live in ``routes/`` sub-modules.  This file keeps only:
  • lifespan (scheduler bootstrap, DB init, commentary cache load)
  • DegradationCaptureMiddleware
  • app / router creation
  • router wire-up (include_router for trading-api + SaaS routers)
"""

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, APIRouter
from loguru import logger

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
from routes.system import _auto_heal_check
from routes import ALL_ROUTERS


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
    scheduler.add_job(
        func=_auto_heal_check,
        trigger=_ITrigger(minutes=2),
        id="auto_heal",
        name="Auto Self-Heal Monitor",
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info("Auto-heal monitor registered (2-min interval, always active — not paused by auto-trading toggle)")

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

    async def _record_equity_snapshot_now():
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
                        _eqcur.execute(
                            "SELECT COALESCE(SUM(equity_usd), 0) FROM kraken_heartbeat "
                            "WHERE id IN (1, 2, 3, 4)"
                        )
                        _eqrow = _eqcur.fetchone()
                        if _eqrow:
                            kraken_eq = float(_eqrow[0] or 0)
                finally:
                    _eqconn.close()
        except Exception:
            kraken_eq = 0.0
        # Apex Predator (Bot #5) is included in kraken_eq (id=4 above).
        # The options pool no longer exists; report options_equity as 0.
        options_eq = 0.0
        forex_eq = 0.0
        try:
            fx = _get_forex_engine()
            if fx:
                fx_state = fx.get_state()
                forex_eq = float(fx_state.get("paper_equity", 0))
        except Exception:
            forex_eq = 0.0
        poseidon_eq = 100_000.0
        kc_eq = 100_000.0
        try:
            if _dburlq:
                _ps_conn = _pg2eq.connect(_dburlq)
                try:
                    with _ps_conn.cursor() as _pscur:
                        _pscur.execute("SELECT equity_usd FROM poseidon_portfolio WHERE id = 7")
                        _ps_row = _pscur.fetchone()
                        if _ps_row and _ps_row[0]:
                            poseidon_eq = float(_ps_row[0])
                        _pscur.execute("SELECT equity_usd FROM kraken_current_portfolio WHERE id = 8")
                        _kc_row = _pscur.fetchone()
                        if _kc_row and _kc_row[0]:
                            kc_eq = float(_kc_row[0])
                finally:
                    _ps_conn.close()
        except Exception:
            pass
        insert_equity_snapshot(
            alpaca_eq, kraken_eq, "LIVE", "hourly_heartbeat",
            options_equity=options_eq, forex_equity=forex_eq,
            poseidon_equity=poseidon_eq, kraken_current_equity=kc_eq,
        )

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

    def _fleet_commander_run():
        try:
            from analysis.fleet_commander import run_fleet_commander
            result = run_fleet_commander()
            logger.info(f"Fleet Commander | Scheduled run complete: verdict={result.get('overall_verdict', 'N/A')}")
        except Exception as _fce:
            logger.warning(f"Fleet Commander | Scheduled run failed (fail-open): {_fce}")

    _fc_schedule = [
        (4, 15, "Pre-Market 4:15 AM"),
        (9, 45, "Post-Open 9:45 AM"),
        (12, 0, "Midday 12:00 PM"),
        (15, 0, "Late Session 3:00 PM"),
        (17, 0, "Post-Close 5:00 PM"),
        (22, 0, "Evening Crypto 10:00 PM"),
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

    # ── Stage 4: Strategy Health Monitor — 4:00 AM UTC daily ──────────────────
    def _health_monitor_run():
        try:
            from analysis.health_monitor import run_all_bots
            results = run_all_bots()
            for bid, res in results.items():
                status = res.get("overall_status", "ERROR")
                score  = res.get("overall_score", 0)
                logger.info(f"HealthMonitor | {bid}: status={status} score={score}/100")
        except Exception as _hme:
            logger.warning(f"HealthMonitor | Scheduled run failed (non-fatal): {_hme}")

    scheduler.add_job(
        func=_health_monitor_run,
        trigger=_CronTrigger(hour=4, minute=0, timezone="UTC"),
        id="kraken_health_monitor",
        name="Strategy Health Monitor (4:00 AM UTC)",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    logger.info("HealthMonitor | Registered: kraken_health_monitor (4:00 AM UTC daily)")

    # ── Stage 5: Walk-Forward Optimiser — Sunday 2:00 AM UTC weekly ────────────
    def _walk_forward_run():
        try:
            from analysis.walk_forward import run_all_bots as _wfo_run_all
            results = _wfo_run_all()
            for bid, res in results.items():
                if "error" in res:
                    logger.error(f"WFO | {bid}: {res['error']}")
                else:
                    logger.info(
                        f"WFO | {bid}: {res.get('total_trades',0)} trades | "
                        f"{res.get('windows_analysed',0)} windows | "
                        f"confidence={res.get('overall_confidence','?')} | "
                        f"stability={res.get('stability_score',0)}/100"
                    )
        except Exception as _wfe:
            logger.warning(f"WFO | Scheduled run failed (non-fatal): {_wfe}")

    scheduler.add_job(
        func=_walk_forward_run,
        trigger=_CronTrigger(day_of_week="sun", hour=2, minute=0, timezone="UTC"),
        id="kraken_walk_forward_optimizer",
        name="Walk-Forward Parameter Optimiser (Sun 2:00 AM UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("WFO | Registered: kraken_walk_forward_optimizer (Sunday 2:00 AM UTC)")

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

            import threading as _threading_ohlcv
            _t = _threading_ohlcv.Thread(target=_startup_ingest, daemon=True, name="ohlcv-startup-ingest")
            _t.start()
            logger.info("OHLCV | Startup ingest launched in background thread")
        else:
            logger.info("OHLCV | historical_prices already populated — skipping startup ingest")
    except Exception as _ohlcv_err:
        logger.warning(f"OHLCV | Startup ingest check failed (non-fatal): {_ohlcv_err}")

    # ── Stage 6: True Price-Based Historical Backtest — Sunday 2:30 AM UTC ────
    # Runs 30 minutes after the Walk-Forward Optimiser to use fresh WFO data.
    # Now uses OHLCV-based simulation instead of P&L replay.
    from analysis.backtester_kraken import run_all_bots as _bt_run_all

    async def _backtest_run():
        import asyncio
        try:
            logger.info("Backtest | Scheduled TRUE price-based backtest starting …")
            results = await asyncio.get_event_loop().run_in_executor(None, _bt_run_all)
            for bid, r in results.items():
                if "error" in r:
                    logger.warning(f"Backtest | {bid}: {r['error']}")
                else:
                    logger.info(
                        f"Backtest | {bid}: {r.get('sim_trades', r.get('n_trades', 0))} simulated trades | "
                        f"WR={r.get('baseline_wr', 0)*100:.1f}% "
                        f"PF={r.get('baseline_pf', 0):.2f} "
                        f"net={r.get('baseline_net_pct', 0):+.2f}% "
                        f"Sharpe={r.get('sharpe_ratio', 0):.2f}"
                    )
        except Exception as _bte:
            logger.warning(f"Backtest | Scheduled run failed (non-fatal): {_bte}")

    scheduler.add_job(
        func=_backtest_run,
        trigger=_CronTrigger(day_of_week="sun", hour=2, minute=30, timezone="UTC"),
        id="kraken_historical_backtest",
        name="True Price-Based Backtester (Sun 2:30 AM UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Backtest | Registered: kraken_historical_backtest (Sunday 2:30 AM UTC) — TRUE price-based")

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
            trigger=_ITrigger(seconds=60),
            id="math_audit_quick",
            name="Math Auditor — Quick (ATR + sizing, 60s)",
            replace_existing=True,
            misfire_grace_time=30,
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

_DEGRADATION_ENDPOINTS = {
    "/ai/commentary", "/kraken/commentary", "/kraken/status",
    "/kraken/performance", "/kraken/trades",
    "/run", "/run/postmortem", "/status", "/health",
    "/positions/live", "/portfolio",
}


class DegradationCaptureMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        response = await call_next(request)
        if response.status_code in (500, 503):
            path = request.url.path
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


for sub_router in ALL_ROUTERS:
    router.include_router(sub_router)

app.include_router(router)

from saas_router import saas_router                          # noqa: E402
from saas_stripe_router import stripe_bp                     # noqa: E402
app.include_router(saas_router)
app.include_router(stripe_bp, prefix="/saas-api")
