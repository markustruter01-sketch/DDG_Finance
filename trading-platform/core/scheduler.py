"""
APScheduler — Intraday Job Definitions
-----------------------------------------
Two recurring jobs run every trading day:

  Job 1 | Every 15 min ET (09:31–15:45) — Full analysis + execution cycle
  Job 2 | 16:10 ET daily               — Post-mortem P&L reconciliation

The first cycle of each day (09:31) also resets the kill switch and
captures opening equity. Subsequent cycles reuse cached FRED (1hr TTL)
and NewsAPI (30min TTL) data while fetching fresh market prices.

We use APScheduler's AsyncIOScheduler (non-blocking, compatible with FastAPI)
with the US/Eastern timezone. Jobs only run on weekdays — the market clock
guard inside run_pipeline() handles holidays.

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
from core.market_clock import is_market_open
from execution.broker import get_account
from execution.kill_switch import reset as ks_reset, check as ks_check, is_tripped


_scheduler: AsyncIOScheduler | None = None
_auto_trading_enabled: bool = False
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


async def _intraday_cycle() -> None:
    global _last_reset_date

    logger.info("Scheduler | JOB STARTING: intraday_cycle")

    if not is_market_open():
        logger.info("Scheduler | Market closed — skipping intraday cycle")
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


async def _evening_postmortem() -> None:
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
