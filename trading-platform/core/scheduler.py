"""
APScheduler — 24/7 Job Definitions
-------------------------------------
Five recurring jobs:

  Job 1 | Every 15 min ET (09:01–15:46 Mon-Fri) — Full analysis + execution cycle
  Job 2 | 16:10 ET daily (Mon-Fri)              — Post-mortem P&L reconciliation
  Job 3 | Every 15 min (24/7)                   — Crypto-only cycle (only fires
          when stock market is CLOSED)
  Job 4 | 16:30 ET daily (Mon-Fri)              — HITL Auditor Agent daily report
  Job 5 | 04:15 ET daily (Mon-Fri)              — Claude Self-Critic Auditor

During market hours, Job 1 handles the full universe (ETFs + crypto).
Outside market hours (nights, weekends, holidays), Job 3 handles crypto-only
trading using raw crypto pairs (BTC/USD, ETH/USD, etc.) via Alpaca.

The first cycle of each day (market-hours or crypto) resets the kill switch
and captures opening equity.

The Auditor Agent (Job 4) runs 20 minutes after market close — after the
post-mortem has finished — so its findings reflect the day's complete trade data.

The scheduler is started inside FastAPI's lifespan context manager in main.py
so it is torn down cleanly on shutdown.
"""

import asyncio
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from config.settings import settings
from core.pipeline import run_pipeline, run_postmortem
from analysis.auditor import run_full_audit
from analysis.gemini_auditor import run_daily_self_critic
from core.market_clock import is_market_open, is_early_close_day, is_alpaca_maintenance_window
from execution.broker import get_account
from execution.kill_switch import reset as ks_reset, check as ks_check, is_tripped


_scheduler: AsyncIOScheduler | None = None
_auto_trading_enabled: bool = True
_last_reset_date: date | None = None


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
        func=_crypto_cycle,
        trigger=IntervalTrigger(minutes=15),
        id="crypto_cycle",
        name="Crypto-Only 24/7 Cycle",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Scheduler | Registered: crypto_cycle (every 15 min, 24/7, fires when market closed)")

    logger.info("Scheduler | daily_audit runs via postmortem chain (no fixed cron)")

    scheduler.add_job(
        func=_claude_self_critic_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=4,
            minute=15,
            timezone="America/New_York",
        ),
        id="claude_self_critic",
        name="Claude Self-Critic Auditor (Pre-Market)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Scheduler | Registered: claude_self_critic (Mon–Fri 04:15 ET — pre-market veto run)")


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
        result = await run_pipeline(force=True, dry_run=False)
        logger.info(f"Scheduler | intraday_cycle complete: status={result['status']}")
    except Exception as exc:
        logger.error(f"Scheduler | intraday_cycle CRASHED: {exc}")

    await _run_micro_audit()


async def _crypto_cycle() -> None:
    global _last_reset_date

    if is_market_open():
        logger.debug("Scheduler | Market open — skipping crypto-only cycle (intraday handles it)")
        return

    if is_alpaca_maintenance_window():
        logger.warning("Scheduler | Alpaca monthly maintenance window — skipping crypto cycle (Alpaca API may be unavailable)")
        return

    logger.info("Scheduler | JOB STARTING: crypto_cycle (market closed, crypto-only mode)")

    today = date.today()
    if _last_reset_date != today:
        try:
            acct = get_account()
            ks_reset(opening_equity=acct["equity"])
            _last_reset_date = today
            logger.info(f"Scheduler | Crypto cycle reset kill switch for {today} — equity: ${acct['equity']:,.2f}")
        except Exception as exc:
            logger.error(f"Scheduler | Failed to reset kill switch (crypto): {exc}")

    try:
        result = await run_pipeline(force=True, dry_run=False, crypto_only=True)
        logger.info(f"Scheduler | crypto_cycle complete: status={result['status']}")
    except Exception as exc:
        logger.error(f"Scheduler | crypto_cycle CRASHED: {exc}")

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


async def _claude_self_critic_job() -> None:
    """
    Run the Claude self-critic auditor pre-market (04:15 ET).
    Writes logs/veto_conditions.json so the executor can block vetoed tickers
    for the entire trading day.
    Runs in a thread executor to avoid blocking the asyncio event loop.
    """
    logger.info("Scheduler | JOB STARTING: claude_self_critic (Claude Self-Critic Auditor)")
    try:
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_daily_self_critic)
        logger.info(
            f"Scheduler | claude_self_critic complete: "
            f"status={result.get('status')} "
            f"verdict={result.get('overall_verdict')} "
            f"vetoed={result.get('vetoed_tickers', [])}"
        )
    except Exception as exc:
        logger.error(f"Scheduler | claude_self_critic CRASHED: {exc}")


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


_ALWAYS_ACTIVE_JOBS = {"auto_heal"}  # jobs that must never be paused by auto-trading toggle


def set_auto_trading(enabled: bool) -> dict:
    global _auto_trading_enabled
    scheduler = get_scheduler()

    if enabled:
        for job in scheduler.get_jobs():
            if job.id not in _ALWAYS_ACTIVE_JOBS:
                job.resume()
        _auto_trading_enabled = True
        logger.info("AUTO-TRADING ENABLED — trading scheduler jobs resumed (24/7 crypto + market hours ETFs)")
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
