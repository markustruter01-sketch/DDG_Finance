"""
APScheduler — Job Definitions
-------------------------------------
Seven recurring jobs:

  Job 1 | Every 15 min ET (09:01–15:46 Mon-Fri) — Pure momentum scan + execution
  Job 2 | 16:10 ET daily (Mon-Fri)              — Post-mortem P&L reconciliation
  Job 3 | 16:30 ET daily (Mon-Fri)              — HITL Auditor Agent daily report
  Job 4 | 05:00 AEST daily (Brisbane, 7 days)   — Discord fleet P&L digest
  Job 5 | 17:30 ET daily (Mon-Fri)              — Walk-forward validation (ARC 2)
  Job 6 | 18:30 ET daily                        — Deploy hash verification
  Job 7 | 19:00 ET daily                        — Fleet equity snapshot (sparkline)

Oracle only trades during NYSE market hours (no afterhours crypto).
The Gemini Self-Critic pre-market veto and crypto-only cycles have been retired.

The first cycle of each day resets the kill switch and captures opening equity.

The Auditor Agent (Job 3) runs 20 minutes after market close — after the
post-mortem has finished — so its findings reflect the day's complete trade data.

The scheduler is started inside FastAPI's lifespan context manager in main.py
so it is torn down cleanly on shutdown.
"""

import asyncio
import os
from datetime import date, datetime, timedelta

import httpx
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
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

def _is_published_deployment() -> bool:
    """True only in a Replit published deployment, never in a dev workflow."""
    return os.environ.get("REPLIT_DEPLOYMENT") == "1"

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
#      The degradation_tracker will alert on stale heartbeat within 5 min.
#      There is no auto-remediation layer — stale detection surfaces alerts
#      only; manual restart of the Replit workflow is required.
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

    # ── ONE-TIME: oracle residual cleanup (2026-08-17 09:31 ET) ──────────────
    # Stage 3B left EMR/LMT/PRU in the oracle paper account. GTC stops were
    # cancelled manually but stuck in pending_cancel over the weekend. This job
    # fires once at Monday open, cancels any remaining orders, market-sells all
    # positions, logs the result, and is automatically removed by DateTrigger.
    _et = pytz.timezone("America/New_York")
    _cleanup_dt = _et.localize(datetime(2026, 8, 17, 9, 31, 0))
    if datetime.now(_et) < _cleanup_dt:
        scheduler.add_job(
            func=_oracle_residual_cleanup,
            trigger=DateTrigger(run_date=_cleanup_dt),
            id="oracle_residual_cleanup_20260817",
            name="ONE-TIME: Close oracle residual EMR/LMT/PRU at Monday open",
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Scheduler | Registered ONE-TIME: oracle_residual_cleanup at 2026-08-17 09:31 ET")
    # ── END one-time cleanup ──────────────────────────────────────────────────

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

    scheduler.add_job(
        func=_nightly_walk_forward,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=17,
            minute=30,
            timezone="America/New_York",
        ),
        id="nightly_walk_forward",
        name="Walk-Forward Validation (ARC 2)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Scheduler | Registered: nightly_walk_forward (Mon–Fri 17:30 ET)")

    # ARC 4: 90-day retention sweep for shadow_signals (runs daily at 18:00 ET)
    scheduler.add_job(
        func=_shadow_signal_retention_sweep,
        trigger=CronTrigger(
            hour=18,
            minute=0,
            timezone="America/New_York",
        ),
        id="shadow_signal_retention",
        name="Shadow Signal 90-Day Retention Sweep",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler | Registered: shadow_signal_retention (daily 18:00 ET)")

    # ── Deploy hash check: published deployments only ──────────────────────
    # Development workflows run against a mutable Git checkout. Replit can
    # checkpoint edits after a process starts, making a Git-HEAD comparison
    # produce a false stale-code alert even though Uvicorn has reloaded code.
    if _is_published_deployment():
        scheduler.add_job(
            func=_deploy_hash_check,
            trigger=CronTrigger(
                hour=18,
                minute=30,
                timezone="America/New_York",
            ),
            id="deploy_hash_check_nightly",
            name="Nightly Deploy Hash Verification",
            replace_existing=True,
            misfire_grace_time=600,
        )
        logger.info("Scheduler | Registered: deploy_hash_check_nightly (daily 18:30 ET)")

        _startup_check_dt = datetime.now(_et) + timedelta(seconds=60)
        scheduler.add_job(
            func=_deploy_hash_check,
            trigger=DateTrigger(run_date=_startup_check_dt),
            id="deploy_hash_check_startup",
            name="60s Post-Startup Deploy Hash Check",
            replace_existing=True,
            misfire_grace_time=120,
        )
        logger.info(f"Scheduler | Registered: deploy_hash_check_startup (one-shot at {_startup_check_dt.isoformat()})")
    else:
        logger.info("Scheduler | Deploy hash checks skipped outside published deployment")

    # ── Job 7: fleet equity snapshot — nightly at 19:00 ET ───────────────────
    scheduler.add_job(
        func=_snapshot_fleet_equity,
        trigger=CronTrigger(
            hour=19,
            minute=0,
            timezone="America/New_York",
        ),
        id="nightly_fleet_equity_snapshot",
        name="Nightly Fleet Equity Snapshot (Sparkline)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler | Registered: nightly_fleet_equity_snapshot (daily 19:00 ET)")

    logger.info("Scheduler | daily_audit runs via postmortem chain (no fixed cron)")
    logger.info("Scheduler | crypto_cycle retired — Oracle only trades NYSE market hours")
    logger.info("Scheduler | gemini_self_critic retired — Oracle uses pure deterministic momentum")


async def _deploy_hash_check() -> None:
    """
    Compare the running-process git hash (captured at startup) against the
    current repo HEAD. Alert via Discord if they differ — the service is
    running stale code and needs a restart.
    """
    if not _is_published_deployment():
        logger.debug("Scheduler | deploy_hash_check skipped outside published deployment")
        return

    try:
        import subprocess as _sp
        latest = _sp.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=_sp.DEVNULL,
            timeout=3,
        ).decode().strip()

        # Lazy import to avoid circular dependency (main imports scheduler)
        try:
            from main import _RUNNING_HASH as _running
        except Exception:
            _running = "unknown"

        if _running == "unknown" or latest != _running:
            from notifications.discord import alert_critical
            alert_critical(
                title="⚠️ Deploy Hash Mismatch",
                description=(
                    f"Running process: `{_running}`\n"
                    f"Repo HEAD: `{latest}`\n\n"
                    f"The trading-api is serving stale code. "
                    f"Restart the workflow to pick up the latest commit."
                ),
            )
            logger.warning(
                f"Scheduler | deploy_hash_check: MISMATCH "
                f"running={_running} latest={latest}"
            )
        else:
            logger.info(f"Scheduler | deploy_hash_check: OK — both {latest}")
    except Exception as exc:
        logger.debug(f"Scheduler | deploy_hash_check: failed (non-fatal): {exc}")


async def _shadow_signal_retention_sweep() -> None:
    """
    ARC 4: delete shadow_signals rows older than 90 days.
    Runs daily at 18:00 ET.  Fire-and-forget — logs result but never raises.
    """
    logger.info("Scheduler | JOB STARTING: shadow_signal_retention_sweep")
    try:
        loop = asyncio.get_event_loop()

        def _sweep() -> int:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return 0
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM shadow_signals "
                        "WHERE signal_ts < NOW() - INTERVAL '90 days'"
                    )
                    return cur.rowcount

        deleted = await loop.run_in_executor(None, _sweep)
        logger.info(
            f"Scheduler | shadow_signal_retention_sweep complete: "
            f"deleted {deleted} row(s) older than 90 days"
        )
    except Exception as exc:
        logger.warning(f"Scheduler | shadow_signal_retention_sweep failed (non-fatal): {exc}")


async def _oracle_residual_cleanup() -> None:
    """
    ONE-TIME job — 2026-08-17 09:31 ET.
    Closes the Stage 3B residual (EMR/LMT/PRU) left in the oracle paper account
    after the stock scanner was retired.  GTC stops were stuck in pending_cancel
    over the weekend; they will have cleared by 09:31.  DateTrigger fires this
    job once and then auto-removes it.
    """
    logger.info("Scheduler | oracle_residual_cleanup: STARTING — cancelling stops + closing EMR/LMT/PRU")

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    }
    base = "https://paper-api.alpaca.markets/v2"

    try:
        async with httpx.AsyncClient(timeout=30) as client:

            # Step 1 — cancel all open orders (belt-and-suspenders for stops)
            cancel_resp = await client.delete(f"{base}/orders", headers=headers)
            logger.info(f"Scheduler | oracle_residual_cleanup: cancel all orders → HTTP {cancel_resp.status_code}")
            await asyncio.sleep(3)

            # Step 2 — close all positions (cancel_orders=true as extra safety)
            close_resp = await client.delete(
                f"{base}/positions", headers=headers,
                params={"cancel_orders": "true"},
            )
            logger.info(f"Scheduler | oracle_residual_cleanup: delete all positions → HTTP {close_resp.status_code}")
            try:
                items = close_resp.json()
                if isinstance(items, list):
                    for item in items:
                        sym = item.get("symbol", "?")
                        status = item.get("status", "?")
                        msg = item.get("body", {}).get("message", "submitted")
                        logger.info(f"Scheduler | oracle_residual_cleanup: {sym} → {status} ({msg})")
            except Exception:
                pass

            # Step 3 — wait for fills then verify flat
            await asyncio.sleep(8)
            pos_resp = await client.get(f"{base}/positions", headers=headers)
            positions = pos_resp.json() if pos_resp.status_code == 200 else []
            ord_resp = await client.get(f"{base}/orders", headers=headers, params={"status": "open", "limit": 20})
            orders = ord_resp.json() if ord_resp.status_code == 200 else []
            acct_resp = await client.get(f"{base}/account", headers=headers)
            acct = acct_resp.json() if acct_resp.status_code == 200 else {}

            cash = float(acct.get("cash", 0))
            equity = float(acct.get("equity", 0))

            if not positions and not orders:
                logger.info(
                    f"Scheduler | oracle_residual_cleanup: ORACLE FLAT ✓ — "
                    f"0 positions, 0 orders, cash=${cash:,.2f}, equity=${equity:,.2f}"
                )
            else:
                logger.warning(
                    f"Scheduler | oracle_residual_cleanup: NOT FLAT — "
                    f"{len(positions)} position(s), {len(orders)} order(s) remaining"
                )
                for p in positions:
                    logger.warning(
                        f"Scheduler | oracle_residual_cleanup: RESIDUAL {p['symbol']} "
                        f"qty={p['qty']} mktval=${float(p['market_value']):,.2f}"
                    )

    except Exception as exc:
        logger.error(f"Scheduler | oracle_residual_cleanup: FAILED — {exc}")


async def _intraday_cycle() -> None:
    global _last_reset_date

    logger.info("Scheduler | JOB STARTING: intraday_cycle")

    # Stage 3B (2026-08-11): oracle stock-scanner retired — slot repurposed to
    # Asia-Pacific ETF trend (asia_trend_strategy via kraken-bot/runner.py).
    # Hard-stop this job so it cannot open new stock positions after publish.
    # Belt-and-suspenders: also reads bots_state.paused from DB.
    try:
        from core.bot_state import is_paused as _is_bot_paused
        if _is_bot_paused("oracle"):
            logger.info("Scheduler | oracle paused in DB — intraday_cycle skipped (Stage 3B retirement)")
            return
    except Exception as _pause_chk_err:
        logger.warning(f"Scheduler | oracle pause-check failed ({_pause_chk_err}) — continuing")
    # Hard-exit: oracle stock pipeline is permanently retired as of Stage 3B publish.
    logger.info("Scheduler | intraday_cycle DISABLED — oracle stock scanner retired (Stage 3B). ETF bots run via runner.py.")
    return

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
        try:
            from core.bot_state import touch_heartbeat as _bs_touch
            _bs_touch("oracle", status="error", error=str(exc)[:200])
        except Exception as _hb_exc:
            logger.debug(f"Pipeline | Oracle error heartbeat failed: {_hb_exc}")

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


_ALWAYS_ACTIVE_JOBS = {
    "daily_discord_pnl_report",
    "nightly_walk_forward",  # monitoring job — runs even when trading is disabled
}


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
        logger.warning("AUTO-TRADING DISABLED — trading jobs paused (math_auditor, discord_pnl, snapshot_export remain active)")

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


async def _nightly_walk_forward() -> None:
    """
    Job 5 — fires Mon–Fri at 17:30 ET (30 min after benchmark snapshot).
    Computes trailing 30d/90d metrics for all 4 bots, classifies each vs its
    OOS envelope (GREEN/AMBER/RED/INSUFFICIENT_DATA/DISQUALIFIED), and
    persists to bot_evaluation_history.  Runs regardless of trading toggle
    (monitoring job — always active).
    """
    logger.info("Scheduler | JOB STARTING: nightly_walk_forward")
    try:
        import asyncio
        from analysis.arc2_walk_forward import run_walk_forward_job
        results = await asyncio.to_thread(run_walk_forward_job, False)
        summary = ", ".join(f"{b}: {r['status']}" for b, r in results.items())
        logger.info(f"Scheduler | nightly_walk_forward complete — {summary}")
    except Exception as exc:
        logger.error(f"Scheduler | nightly_walk_forward FAILED: {exc}")


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


async def _snapshot_fleet_equity() -> None:
    """
    Job 7 — fires daily at 19:00 ET.
    Writes one fleet_equity_history row (date, total_equity) for the sparkline.
    Uses bot_portfolio as source of truth (same as /fleet/equity route).
    ON CONFLICT DO UPDATE keeps the latest value for each calendar date.
    """
    logger.info("Scheduler | JOB STARTING: nightly_fleet_equity_snapshot")
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            logger.warning("Scheduler | fleet_equity_snapshot: PG unavailable — skip")
            return

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Match /fleet/equity exactly: retired portfolio rows must
                # never contribute a phantom allocation to the sparkline.
                active_bot_ids = ("oracle", "spy_qqq_trend", "jerome_macro")
                cur.execute("""
                    SELECT COALESCE(SUM(equity_usd), 0)
                    FROM bot_portfolio
                    WHERE bot_id IN (%s, %s, %s)
                      AND last_updated > NOW() - INTERVAL '25 minutes'
                """, active_bot_ids)
                row = cur.fetchone()
                total = float(row[0]) if row else 0.0

                # Fall back to the same active set if no recent heartbeat
                # (weekend, market closed).
                if total == 0:
                    cur.execute("""
                        SELECT COALESCE(SUM(equity_usd), 0)
                        FROM bot_portfolio
                        WHERE bot_id IN (%s, %s, %s)
                    """, active_bot_ids)
                    row = cur.fetchone()
                    total = float(row[0]) if row else 0.0

            if total <= 0:
                logger.warning(f"Scheduler | fleet_equity_snapshot: total=${total:,.2f} — skip (zero equity)")
                return

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO fleet_equity_history (snapshot_date, total_equity)
                    VALUES (CURRENT_DATE, %s)
                    ON CONFLICT (snapshot_date)
                    DO UPDATE SET total_equity = EXCLUDED.total_equity,
                                  created_at   = NOW()
                """, (round(total, 2),))
            conn.commit()

        logger.info(f"Scheduler | fleet_equity_snapshot complete — ${total:,.2f} saved for {__import__('datetime').date.today()}")
    except Exception as exc:
        logger.error(f"Scheduler | fleet_equity_snapshot FAILED: {exc}")


def _fetch_fleet_equity_total() -> float:
    """Legacy heartbeat equity is retired; fleet equity has its own SSoT."""
    return 0.0


# Make _json importable inside the module-level function
import json as _json
