"""
APScheduler — Job Definitions
-------------------------------------
Three recurring jobs:

  Job 1 | Every 15 min ET (09:01–15:46 Mon-Fri) — Pure momentum scan + execution
  Job 2 | 16:10 ET daily (Mon-Fri)              — Post-mortem P&L reconciliation
  Job 3 | 16:30 ET daily (Mon-Fri)              — HITL Auditor Agent daily report
  Job 4 | 05:00 AEST daily (Brisbane, 7 days)   — Discord fleet P&L digest

Oracle only trades during NYSE market hours (no afterhours crypto).
The Gemini Self-Critic pre-market veto and crypto-only cycles have been retired.

The first cycle of each day resets the kill switch and captures opening equity.

The Auditor Agent (Job 3) runs 20 minutes after market close — after the
post-mortem has finished — so its findings reflect the day's complete trade data.

The scheduler is started inside FastAPI's lifespan context manager in main.py
so it is torn down cleanly on shutdown.
"""

import asyncio
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config.settings import settings
from core.pipeline import run_pipeline, run_postmortem
from analysis.auditor import run_full_audit
from core.market_clock import is_market_open, is_early_close_day, is_alpaca_maintenance_window
from execution.broker import get_account
from execution.kill_switch import reset as ks_reset, check as ks_check, is_tripped


_scheduler: AsyncIOScheduler | None = None
_auto_trading_enabled: bool = True
_last_reset_date: date | None = None

# ══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURAL NOTE — KRAKEN BOT PROCESS ISOLATION
# ══════════════════════════════════════════════════════════════════════════════
#
# The Kraken crypto bots (Davy Jones, Jerome, Calypso, Apex Predator,
# FOMO Fred, Kraken Current, Forex Gump) run in a SEPARATE PROCESS from this trading-platform
# FastAPI/APScheduler process.
#
# Consequences:
#   1. If this process crashes, the Kraken bots continue trading unattended.
#      The math auditor, kill switch, and health monitor all stop — but Kraken
#      bots keep running their own internal circuit breakers independently.
#
#   2. If the Kraken bot process crashes, this scheduler has no visibility.
#      The kraken_heartbeat table going stale (>30 min) is the only signal.
#      The degradation_tracker will alert on stale heartbeat within 5 min
#      (TTL fixed from 1800s to 300s in audit fix F11).
#
#   3. There is no cross-process kill switch. A manual trip of the Alpaca
#      kill switch does NOT stop Kraken bots. Use the /rebalance endpoint
#      or directly pause each Kraken bot via its control file.
#
#   4. The math auditor runs in THIS process and cannot reach the Kraken bot
#      process directly — it reads Kraken results from the DB only.
#
# Monitoring: kraken_heartbeat.last_updated must be < 30 min old per bot.
# Alert threshold: 5 min stale (degradation_tracker _EVENT_TTL["kraken_api"]["stale"]).
# ══════════════════════════════════════════════════════════════════════════════


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="America/New_York")
        _register_jobs(_scheduler)
    return _scheduler


def _register_jobs(scheduler: AsyncIOScheduler) -> None:

    scheduler.add_job(
        func=_intraday_cycle,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="1,16,31,46",
            timezone="America/New_York",
        ),
        id="intraday_cycle",
        name="15-Min Analysis & Execution Cycle",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Scheduler | Registered: intraday_cycle (Mon–Fri every 15 min, 09:01–15:46 ET)")

    scheduler.add_job(
        func=_evening_postmortem,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=10,
            timezone="America/New_York",
        ),
        id="evening_postmortem",
        name="Post-Mortem Reconciliation",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Scheduler | Registered: evening_postmortem (Mon–Fri 16:10 ET)")

    scheduler.add_job(
        func=_daily_discord_pnl_report,
        trigger=CronTrigger(
            hour=5,
            minute=0,
            timezone="Australia/Brisbane",
        ),
        id="daily_discord_pnl_report",
        name="Discord Daily Fleet P&L Digest (05:00 AEST)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Scheduler | Registered: daily_discord_pnl_report (daily 05:00 AEST Brisbane)")

    scheduler.add_job(
        func=_daily_benchmark_snapshot,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=17,
            minute=10,
            timezone="America/New_York",
        ),
        id="daily_benchmark_snapshot",
        name="SPY/QQQ/AGG Daily Benchmark Snapshot (17:10 ET)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Scheduler | Registered: daily_benchmark_snapshot (Mon–Fri 17:10 ET)")

    logger.info("Scheduler | daily_audit runs via postmortem chain (no fixed cron)")
    logger.info("Scheduler | crypto_cycle retired — Oracle only trades NYSE market hours")
    logger.info("Scheduler | gemini_self_critic retired — Oracle uses pure deterministic momentum")


async def _intraday_cycle() -> None:
    global _last_reset_date

    logger.info("Scheduler | JOB STARTING: intraday_cycle")

    if not is_market_open():
        logger.info("Scheduler | Market closed — skipping intraday cycle")
        return

    if is_alpaca_maintenance_window():
        logger.warning("Scheduler | Alpaca monthly maintenance window (2nd Saturday 09:00–11:00 ET) — skipping intraday cycle")
        return

    # ── Early-close guard ─────────────────────────────────────────────────
    # NYSE early-close days (Black Friday, Christmas Eve, NYE) end at 1 PM ET.
    # The CronTrigger fires at :01, :16, :31, :46 through hour 15, but we
    # must stop at 13:00 on half-days.  is_market_open() (Alpaca clock) is
    # authoritative; this guard is a belt-and-suspenders safety net.
    from datetime import datetime
    import pytz
    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)
    if is_early_close_day() and now_et.hour >= 13:
        logger.info(
            f"Scheduler | Early-close day — market closed at 13:00 ET "
            f"(now {now_et.strftime('%H:%M')} ET). Skipping cycle."
        )
        return

    today = date.today()
    if _last_reset_date != today:
        try:
            acct = get_account()
            ks_reset(opening_equity=acct["equity"])
            _last_reset_date = today
            logger.info(f"Scheduler | First cycle of {today} — opening equity: ${acct['equity']:,.2f}")
        except Exception as exc:
            logger.error(f"Scheduler | Failed to reset kill switch: {exc}")

    try:
        result = await run_pipeline(force=False, dry_run=False)
        logger.info(f"Scheduler | intraday_cycle complete: status={result['status']}")
    except Exception as exc:
        logger.error(f"Scheduler | intraday_cycle CRASHED: {exc}")

    await _run_micro_audit()




async def _run_micro_audit() -> None:
    try:
        loop = asyncio.get_event_loop()
        from analysis.micro_auditor import run_micro_audit
        result = await loop.run_in_executor(None, run_micro_audit)
        if result.get("alert_count", 0) > 0:
            logger.warning(
                f"Scheduler | MicroAuditor: {result['alert_count']} alert(s) "
                f"({result['high_count']} HIGH, {result['medium_count']} MED) "
                f"escalated={result['escalated_to_gemini']}"
            )
    except Exception as exc:
        logger.debug(f"Scheduler | MicroAuditor failed (non-fatal): {exc}")


async def _evening_postmortem() -> None:
    logger.info("Scheduler | JOB STARTING: evening_postmortem")
    try:
        result = await run_postmortem()
        logger.info(
            f"Scheduler | evening_postmortem complete: "
            f"status={result['status']} updated={result.get('updated_count', 0)}"
        )
        logger.info("Scheduler | Chaining daily_audit after postmortem completion")
        await _daily_audit_job()
    except Exception as exc:
        logger.error(f"Scheduler | evening_postmortem CRASHED: {exc}")


async def _daily_audit_job() -> None:
    """
    Run the HITL Auditor Agent daily report.
    Chained from evening_postmortem on completion so the audit always sees
    the day's fully reconciled trade outcomes.
    Runs in a thread executor to avoid blocking the asyncio event loop.
    """
    logger.info("Scheduler | JOB STARTING: daily_audit (HITL Auditor Agent)")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_full_audit)
        logger.info(
            f"Scheduler | daily_audit complete: "
            f"overall={result['overall']} "
            f"failed={result['failed_checks']}/{result['total_checks']} checks"
        )
    except Exception as exc:
        logger.error(f"Scheduler | daily_audit CRASHED: {exc}")




def get_job_status() -> list[dict]:
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id":            job.id,
            "name":          job.name,
            "next_fire_utc": str(job.next_run_time) if job.next_run_time else "paused",
        })
    return jobs


def is_auto_trading_enabled() -> bool:
    return _auto_trading_enabled


_ALWAYS_ACTIVE_JOBS = {"auto_heal", "daily_discord_pnl_report"}  # always run regardless of trading toggle


def set_auto_trading(enabled: bool) -> dict:
    global _auto_trading_enabled
    scheduler = get_scheduler()

    if enabled:
        for job in scheduler.get_jobs():
            if job.id not in _ALWAYS_ACTIVE_JOBS:
                job.resume()
        _auto_trading_enabled = True
        logger.info("AUTO-TRADING ENABLED — trading scheduler jobs resumed (market hours ETFs + 24/7 Kraken crypto bots)")
    else:
        for job in scheduler.get_jobs():
            if job.id not in _ALWAYS_ACTIVE_JOBS:
                job.pause()
        _auto_trading_enabled = False
        logger.warning("AUTO-TRADING DISABLED — trading jobs paused (auto-heal monitor remains active)")

    return {
        "auto_trading_enabled": _auto_trading_enabled,
        "jobs": get_job_status(),
    }


async def _daily_discord_pnl_report() -> None:
    """
    Fires every day at 05:00 AEST (Brisbane) — sends the 24-hour fleet P&L
    digest to Discord. Runs regardless of whether auto-trading is enabled.
    """
    logger.info("Scheduler | JOB STARTING: daily_discord_pnl_report")
    try:
        import asyncio
        from notifications.discord import notify_daily_pnl_report
        await asyncio.to_thread(notify_daily_pnl_report)
        logger.info("Scheduler | daily_discord_pnl_report: sent successfully")
    except Exception as exc:
        logger.error(f"Scheduler | daily_discord_pnl_report FAILED: {exc}")


async def _daily_benchmark_snapshot() -> None:
    """
    Fires Mon–Fri at 17:10 ET (10 min after market close).
    Fetches SPY, QQQ, AGG closing prices from Yahoo Finance and records
    the current fleet equity into benchmark_snapshots for 30-day comparison.
    """
    import asyncio
    import json as _json
    from datetime import date

    logger.info("Scheduler | JOB STARTING: daily_benchmark_snapshot")
    try:
        closes = await asyncio.to_thread(_fetch_benchmark_closes)
        if not closes:
            logger.warning("Scheduler | daily_benchmark_snapshot: failed to fetch closes")
            return

        fleet_equity = await asyncio.to_thread(_fetch_fleet_equity_total)

        today = date.today()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            logger.warning("Scheduler | daily_benchmark_snapshot: DB unavailable")
            return

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO benchmark_snapshots
                        (snapshot_date, spy_close, qqq_close, agg_close, fleet_equity)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (snapshot_date) DO UPDATE
                        SET spy_close    = EXCLUDED.spy_close,
                            qqq_close    = EXCLUDED.qqq_close,
                            agg_close    = EXCLUDED.agg_close,
                            fleet_equity = EXCLUDED.fleet_equity
                """, (
                    today,
                    closes.get("SPY"),
                    closes.get("QQQ"),
                    closes.get("AGG"),
                    fleet_equity,
                ))
            conn.commit()

        logger.info(
            f"Scheduler | daily_benchmark_snapshot: {today} — "
            f"SPY={closes.get('SPY')} QQQ={closes.get('QQQ')} "
            f"AGG={closes.get('AGG')} fleet=${fleet_equity:,.0f}"
        )

    except Exception as exc:
        logger.error(f"Scheduler | daily_benchmark_snapshot FAILED: {exc}")


def _fetch_benchmark_closes() -> dict:
    """Fetch previous-close prices for SPY, QQQ, AGG from Yahoo Finance."""
    import urllib.request
    results = {}
    for ticker in ("SPY", "QQQ", "AGG"):
        try:
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                f"?interval=1d&range=5d"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if closes:
                results[ticker] = round(closes[-1], 4)
        except Exception as e:
            logger.warning(f"Scheduler | benchmark_closes: {ticker} fetch failed — {e}")
    return results


def _fetch_fleet_equity_total() -> float:
    """Sum all heartbeat equity values as a quick fleet total."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return 0.0
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(SUM(equity_usd), 0) FROM kraken_heartbeat")
                row = cur.fetchone()
        return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


# Make _json importable inside the module-level function
import json as _json
