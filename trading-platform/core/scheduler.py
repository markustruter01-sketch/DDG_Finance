"""
APScheduler — Daily Job Definitions
--------------------------------------
Three recurring jobs run every trading day:

  Job 1 | 09:31 ET daily     — Full analysis + execution cycle
  Job 2 | Every 30 min ET    — Kill switch drawdown check (10:00–15:30)
  Job 3 | 16:10 ET daily     — Post-mortem P&L reconciliation

We use APScheduler's AsyncIOScheduler (non-blocking, compatible with FastAPI)
with the US/Eastern timezone.  Jobs only run on weekdays — the market clock
guard inside run_pipeline() handles holidays.

The scheduler is started inside FastAPI's lifespan context manager in main.py
so it is torn down cleanly on shutdown.
"""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config.settings import settings
from core.pipeline import run_pipeline, run_postmortem
from execution.broker import get_account
from execution.kill_switch import reset as ks_reset, check as ks_check, is_tripped


_scheduler: AsyncIOScheduler | None = None
_auto_trading_enabled: bool = False


def get_scheduler() -> AsyncIOScheduler:
    """Return the singleton scheduler instance (creates it if needed).
    Jobs are registered but paused — auto-trading starts OFF by default.
    Enable via set_auto_trading(True) or POST /auto-trading."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="America/New_York")
        _register_jobs(_scheduler)
    return _scheduler


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all three recurring jobs on the scheduler."""

    # ── Job 1: Daily analysis + execution at 09:31 ET ───────────────────────
    scheduler.add_job(
        func=_morning_cycle,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=31,
            timezone="America/New_York",
        ),
        id="morning_cycle",
        name="Daily Analysis & Execution",
        replace_existing=True,
        misfire_grace_time=300,   # If delayed up to 5 min, still run
    )
    logger.info("Scheduler | Registered: morning_cycle (Mon–Fri 09:31 ET)")

    # ── Job 2: Kill switch intraday check every 30 min ──────────────────────
    scheduler.add_job(
        func=_intraday_check,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="10-15",
            minute="0,30",
            timezone="America/New_York",
        ),
        id="intraday_kill_switch",
        name="Intraday Kill Switch Check",
        replace_existing=True,
        misfire_grace_time=120,
    )
    logger.info("Scheduler | Registered: intraday_kill_switch (Mon–Fri every 30 min, 10:00–15:30 ET)")

    # ── Job 3: Post-mortem at 16:10 ET ──────────────────────────────────────
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


# ── Job implementations ───────────────────────────────────────────────────────

async def _morning_cycle() -> None:
    """
    09:31 ET — Reset kill switch, capture opening equity, run full pipeline.
    """
    logger.info("Scheduler | JOB STARTING: morning_cycle")
    try:
        acct = get_account()
        ks_reset(opening_equity=acct["equity"])
        logger.info(f"Scheduler | Opening equity: ${acct['equity']:,.2f}")
    except Exception as exc:
        logger.error(f"Scheduler | Failed to reset kill switch: {exc}")

    try:
        result = await run_pipeline(force=False, dry_run=False)
        logger.info(f"Scheduler | morning_cycle complete: status={result['status']}")
    except Exception as exc:
        logger.error(f"Scheduler | morning_cycle CRASHED: {exc}")


async def _intraday_check() -> None:
    """
    Every 30 min — Check portfolio drawdown and trip kill switch if needed.
    """
    if is_tripped():
        return  # Already tripped, nothing to do

    logger.info("Scheduler | JOB: intraday_kill_switch check")
    try:
        tripped = ks_check()
        if tripped:
            logger.critical("Scheduler | KILL SWITCH TRIPPED — all positions liquidated")
    except Exception as exc:
        logger.error(f"Scheduler | Kill switch check failed: {exc}")


async def _evening_postmortem() -> None:
    """
    16:10 ET — Reconcile today's closed orders with the trade journal.
    """
    logger.info("Scheduler | JOB STARTING: evening_postmortem")
    try:
        result = await run_postmortem()
        logger.info(
            f"Scheduler | evening_postmortem complete: "
            f"status={result['status']} updated={result.get('updated_count', 0)}"
        )
    except Exception as exc:
        logger.error(f"Scheduler | evening_postmortem CRASHED: {exc}")


def get_job_status() -> list[dict]:
    """Return next-fire-time for all registered jobs."""
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


def set_auto_trading(enabled: bool) -> dict:
    global _auto_trading_enabled
    scheduler = get_scheduler()

    if enabled:
        for job in scheduler.get_jobs():
            job.resume()
        _auto_trading_enabled = True
        logger.info("AUTO-TRADING ENABLED — all scheduler jobs resumed")
    else:
        for job in scheduler.get_jobs():
            job.pause()
        _auto_trading_enabled = False
        logger.warning("AUTO-TRADING DISABLED — all scheduler jobs paused")

    return {
        "auto_trading_enabled": _auto_trading_enabled,
        "jobs": get_job_status(),
    }
