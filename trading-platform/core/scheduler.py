"""
APScheduler — Job Definitions
-------------------------------------
Recurring jobs include:

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
import ipaddress
import json
import os
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from config.settings import settings
from core.pipeline import run_postmortem
from analysis.auditor import run_full_audit
from core.market_clock import is_market_open, is_early_close_day, is_alpaca_maintenance_window
from execution.broker import get_account
from execution.kill_switch import reset as ks_reset, check as ks_check, is_tripped


_scheduler: AsyncIOScheduler | None = None
_auto_trading_enabled: bool = True
_last_reset_date: date | None = None
_runner_liveness_failures: int = 0
_runner_liveness_alerted: bool = False
_trading_api_liveness_failures: int = 0
_trading_api_liveness_alerted: bool = False
_trading_api_liveness_checks: int = 0
TRUSTED_LOCAL_RUNNER_HEALTH_URL = "http://127.0.0.1:8085/health"
RUNNER_HEALTH_URL = os.environ.get(
    "RUNNER_HEALTH_URL",
    TRUSTED_LOCAL_RUNNER_HEALTH_URL,
)
RUNNER_HEALTH_ALLOWED_HOST = os.environ.get(
    "RUNNER_HEALTH_ALLOWED_HOST",
    "",
).strip().lower()
TRADING_API_HEALTH_URL = os.environ.get(
    "TRADING_API_HEALTH_URL",
    "http://127.0.0.1:8000/trading-api/fleet/equity",
)
TRADING_API_SECRET_HEADER = "X-Trading-API-Secret"
RUNNER_HEALTH_TIMEOUT_SECONDS = float(
    os.environ.get("RUNNER_HEALTH_TIMEOUT_SECONDS", "5")
)
RUNNER_HEALTH_FAILURE_THRESHOLD = int(
    os.environ.get("RUNNER_HEALTH_FAILURE_THRESHOLD", "3")
)

def _is_published_deployment() -> bool:
    """True only in a Replit published deployment, never in a dev workflow."""
    return os.environ.get("REPLIT_DEPLOYMENT") == "1"


def _trading_api_liveness_enabled() -> bool:
    """Allow the published artifact to opt in even if its platform flag is absent."""
    return _is_published_deployment() or os.environ.get(
        "TRADING_API_LIVENESS_ENABLED", ""
    ).strip() == "1"


def _runner_health_url() -> str | None:
    """Return the trusted local URL or an explicitly allowlisted public URL."""
    url = os.environ.get("RUNNER_HEALTH_URL", RUNNER_HEALTH_URL).strip()
    if url == TRUSTED_LOCAL_RUNNER_HEALTH_URL:
        return url
    try:
        allowed_host = os.environ.get(
            "RUNNER_HEALTH_ALLOWED_HOST",
            RUNNER_HEALTH_ALLOWED_HOST,
        ).strip().lower()
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not hostname
        or not allowed_host
        or hostname != allowed_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path.rstrip("/") != "/health"
        or parsed.query
        or parsed.fragment
    ):
        return None
    try:
        ipaddress.ip_address(hostname)
        return None
    except ValueError:
        pass
    return url


def _runner_liveness_enabled() -> bool:
    """Use the same explicit published-monitor opt-in as the API probe."""
    return _trading_api_liveness_enabled() and _runner_health_url() is not None


def _record_runner_liveness_audit(
    result: str,
    *,
    endpoint_url: str | None = None,
    error_class: str | None = None,
    reason: str | None = None,
    consecutive_failures: int = 0,
    alert_transition: str = "none",
) -> None:
    """Write monitoring evidence without allowing the audit to affect probes."""
    try:
        from db.postgres import record_runner_liveness_probe

        record_runner_liveness_probe(
            result,
            endpoint_url=endpoint_url,
            error_class=error_class,
            reason=reason,
            consecutive_failures=consecutive_failures,
            alert_transition=alert_transition,
        )
    except Exception as exc:
        logger.warning(f"Scheduler | runner liveness audit failed: {type(exc).__name__}")


def _kill_switch_enforced() -> bool:
    """Enforcement requires both production and explicit operator arming."""
    return _is_published_deployment() and settings.kill_switch_armed

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
#      kill switch does NOT stop Kraken bots. Use /emergency/liquidate
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

    # Safety monitors are read-only in DEV; published deployments enforce the
    # same checks without ever liquidating.  Both schedules are replaceable and
    # independent from strategy execution.
    scheduler.add_job(
        func=_automated_kill_switch,
        trigger=__import__("apscheduler.triggers.interval", fromlist=["IntervalTrigger"]).IntervalTrigger(
            minutes=settings.kill_switch_check_interval_minutes
        ),
        id="automated_kill_switch",
        name="Automated Kill Switch (5-minute safety check)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        func=_scheduled_reconciliation,
        trigger=__import__("apscheduler.triggers.interval", fromlist=["IntervalTrigger"]).IntervalTrigger(hours=1),
        id="scheduled_reconciliation",
        name="Hourly Broker/Ledger Reconciliation",
        replace_existing=True,
        misfire_grace_time=600,
        # First run 3 minutes after start, not an hour: otherwise every
        # publish leaves the last reconciliation older than the 90-minute
        # freshness check and raises a false critical alert.
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=3),
    )
    scheduler.add_job(
        func=_standing_invariants_job,
        trigger=__import__("apscheduler.triggers.interval", fromlist=["IntervalTrigger"]).IntervalTrigger(
            minutes=15
        ),
        id="standing_invariants",
        name="Standing Invariants (alerting)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        func=_degradation_resolver_job,
        trigger=__import__("apscheduler.triggers.interval", fromlist=["IntervalTrigger"]).IntervalTrigger(
            minutes=15
        ),
        id="degradation_resolver",
        name="Condition-based degradation resolver",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    logger.info(
        "Scheduler | Registered: automated_kill_switch (5 min) + "
        "scheduled_reconciliation (hourly) + standing_invariants (15 min, alerting) + "
        "degradation_resolver (15 min)"
    )

    scheduler.add_job(
        func=_live_vs_research_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=40, timezone="America/New_York"),
        id="live_vs_research_daily",
        name="Live vs research check (daily, read-only)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=_live_vs_research_monthly,
        trigger=CronTrigger(day=1, hour=9, minute=10, timezone="Australia/Brisbane"),
        id="live_vs_research_monthly",
        name="Live vs research monthly report (Discord)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=6 * 3600,
    )
    logger.info("Scheduler | Registered: live_vs_research daily (Mon–Fri 17:40 ET) and monthly (1st, 09:10 Brisbane)")

    if _runner_liveness_enabled():
        scheduler.add_job(
            func=_probe_runner_liveness,
            trigger=__import__("apscheduler.triggers.interval", fromlist=["IntervalTrigger"]).IntervalTrigger(
                minutes=1
            ),
            id="published_runner_liveness",
            name="Published Runner Liveness Probe",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
        logger.info(
            f"Scheduler | Registered: published_runner_liveness (1 min, "
            f"url={_runner_health_url()})"
        )
    elif _trading_api_liveness_enabled():
        _record_runner_liveness_audit(
            "invalid_endpoint",
            endpoint_url=None,
            error_class="InvalidRunnerHealthEndpoint",
            reason="runner liveness monitoring skipped because endpoint configuration is invalid",
            consecutive_failures=0,
            alert_transition="none",
        )
        logger.warning(
            "Scheduler | Published runner liveness probe skipped: "
            "RUNNER_HEALTH_URL must be the trusted local runner endpoint or "
            "an HTTPS /health URL matching RUNNER_HEALTH_ALLOWED_HOST"
        )
    else:
        _record_runner_liveness_audit(
            "skipped",
            endpoint_url=None,
            error_class="MonitoringDisabled",
            reason="published runner liveness monitoring is not enabled",
            consecutive_failures=0,
            alert_transition="none",
        )
    if _trading_api_liveness_enabled():
        scheduler.add_job(
            func=_probe_trading_api_liveness,
            trigger=__import__("apscheduler.triggers.interval", fromlist=["IntervalTrigger"]).IntervalTrigger(
                minutes=1
            ),
            id="published_trading_api_liveness",
            name="Published Trading API Authenticated Liveness Probe",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
        logger.info(
            f"Scheduler | Registered: published_trading_api_liveness (1 min, "
            f"url={TRADING_API_HEALTH_URL}, "
            f"auth_header={TRADING_API_SECRET_HEADER})"
        )
    else:
        logger.info(
            "Scheduler | Published Trading API liveness probe skipped "
            "(not enabled outside published deployment)"
        )

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
        func=_daily_health_check,
        trigger=CronTrigger(hour=8, minute=40, timezone="Australia/Brisbane"),
        id="daily_health_check",
        name="Daily health check (Discord)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
    )
    logger.info("Scheduler | Registered: daily_health_check (08:40 Brisbane, every day)")

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

    scheduler.add_job(
        func=_daily_bot_returns_snapshot,
        trigger=CronTrigger(
            hour=20,
            minute=15,
            timezone="UTC",
        ),
        id="daily_bot_returns_snapshot",
        name="Daily Per-Bot Return Series (20:15 UTC)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Scheduler | Registered: daily_bot_returns_snapshot (daily 20:15 UTC)")

    # Per-bot vault jobs are fail-closed by PER_BOT_VAULT_ENABLED. They are
    # registered in development so the schedule is visible, but do nothing
    # while the vault remains inactive.
    scheduler.add_job(
        func=_per_bot_vault_deployment,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/15",
            timezone="America/New_York",
        ),
        id="per_bot_vault_deployment",
        name="Per-Bot Vault Deployment (market hours)",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Scheduler | Registered: per_bot_vault_deployment (15 min, fail-closed)")

    scheduler.add_job(
        func=_order_watchdog,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-16",
            minute="5,35",
            timezone="America/New_York",
        ),
        id="order_watchdog",
        name="Order-rate watchdog (read-only, market hours)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    logger.info("Scheduler | Registered: order_watchdog (09:05-16:35 NY, every 30 min)")

    scheduler.add_job(
        func=_gear_shadow,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=40, timezone="America/New_York"),
        id="gear_v1_g4_shadow",
        name="GEAR-V1-G4 shadow replay (no orders, after the close)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler | Registered: gear_v1_g4_shadow (16:40 NY weekdays, no orders)")

    scheduler.add_job(
        func=_per_bot_vault_monthly_skim,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=45, timezone="America/New_York"),
        id="per_bot_vault_monthly_skim",
        name="Per-Bot Vault: daily mark, monthly 10% high-water skim (before the open)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )
    logger.info("Scheduler | Registered: per_bot_vault_monthly_skim (08:45 NY weekdays; skims on the month's first run)")

    logger.info("Scheduler | daily_audit runs via postmortem chain (no fixed cron)")
    logger.info("Scheduler | crypto_cycle retired — Oracle only trades NYSE market hours")
    logger.info("Scheduler | gemini_self_critic retired — Oracle uses pure deterministic momentum")


async def _automated_kill_switch() -> None:
    try:
        from execution.reconciliation import run_kill_switch_check
        result = await asyncio.to_thread(
            run_kill_switch_check,
            report_only=not _kill_switch_enforced(),
        )
        logger.info(
            f"Scheduler | automated_kill_switch: "
            f"mode={result.get('mode', 'enforced')} "
            f"would_trip={result.get('would_trip', result.get('tripped', False))}"
        )
    except Exception as exc:
        logger.critical(f"Scheduler | automated_kill_switch FAILED: {exc}")


async def _scheduled_reconciliation() -> None:
    try:
        from execution.reconciliation import reconcile
        cycle_id = (
            f"reconciliation:"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        )
        result = await asyncio.to_thread(
            reconcile,
            report_only=not _kill_switch_enforced(),
            cycle_id=cycle_id,
        )
        logger.info(
            f"Scheduler | scheduled_reconciliation: "
            f"clean={result.get('clean')} flags={len(result.get('flags', []))}"
        )
    except Exception as exc:
        logger.critical(f"Scheduler | scheduled_reconciliation FAILED: {exc}")


async def _standing_invariants_job() -> None:
    """Run read-only invariants and alert failures through the shared policy."""
    logger.info("Scheduler | JOB STARTING: standing_invariants")
    try:
        from core.degradation_tracker import has_recent_open, mark_resolved, record_degradation
        from core.invariants import format_report, run_all_invariants

        report = await asyncio.to_thread(run_all_invariants)
        from core.outside_heartbeat import ping as outside_ping
        outside_ping("API")   # the API and its scheduler are alive (monitor outside Replit)
        log_method = logger.info if report["overall"] == "PASS" else logger.warning
        for line in format_report(report).splitlines():
            log_method(f"Scheduler | standing_invariants | {line}")
        for result in report["results"]:
            name = str(result["name"])
            status = str(result["status"])
            if status in {"FAIL", "UNKNOWN"}:
                # A failing invariant keeps one open row (renewed daily) instead
                # of a new row every 15 minutes; it is resolved when it passes.
                if has_recent_open("invariant", name):
                    continue
                record_degradation(
                    component="invariant",
                    severity="critical" if status == "FAIL" else "error",
                    error_type=name,
                    message=f"{status}: {result['message']}",
                    detail=json.dumps(
                        {
                            "actual": result.get("actual"),
                            "expected": result.get("expected"),
                            "difference": result.get("difference"),
                        },
                        default=str,
                        sort_keys=True,
                    ),
                )
            else:
                mark_resolved(
                    "invariant",
                    name,
                    f"standing invariant returned {status}",
                )
        logger.info(
            "Scheduler | standing_invariants complete: "
            f"overall={report['overall']} alerting=ENABLED"
        )
    except Exception as exc:
        logger.critical(f"Scheduler | standing_invariants CRASHED: {exc}")


async def _degradation_resolver_job() -> None:
    """Resolve only degradation rows whose live condition has cleared."""
    logger.info("Scheduler | JOB STARTING: degradation_resolver")
    try:
        from core.degradation_resolver import run_degradation_resolver

        result = await asyncio.to_thread(run_degradation_resolver)
        logger.info(
            "Scheduler | degradation_resolver complete: "
            f"dry_run={result['dry_run']} checked={result['checked']} "
            f"would_resolve={result['would_resolve']} resolved={result['resolved']}"
        )
    except Exception as exc:
        logger.critical(f"Scheduler | degradation_resolver FAILED: {exc}")


async def _probe_runner_liveness() -> None:
    """Independent API-process probe for the separately hosted runner."""
    global _runner_liveness_failures, _runner_liveness_alerted
    runner_url = _runner_health_url()
    alert_transition = "none"
    result = "healthy"
    error_class = None
    reason = None

    # Invalid configuration is not an unreachable runner and must not poison
    # the consecutive-failure counter or trigger an outage alert.
    if runner_url is None:
        _record_runner_liveness_audit(
            "invalid_endpoint",
            endpoint_url=None,
            error_class="InvalidRunnerHealthEndpoint",
            reason="runner health URL is not trusted or allowlisted",
            consecutive_failures=0,
            alert_transition="none",
        )
        logger.warning(
            "Scheduler | published runner liveness skipped: invalid endpoint configuration"
        )
        return

    try:
        async with httpx.AsyncClient(timeout=RUNNER_HEALTH_TIMEOUT_SECONDS) as client:
            response = await client.get(
                runner_url,
                headers={"User-Agent": "trading-api-runner-liveness"},
            )
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            payload = response.json()
            if payload.get("service") != "kraken-bot-runner":
                raise RuntimeError("unexpected runner health payload")
        was_alerted = _runner_liveness_alerted
        recovered = _runner_liveness_failures > 0
        _runner_liveness_failures = 0
        if recovered:
            logger.warning(
                f"Scheduler | published runner liveness recovered: {runner_url}"
            )
        if was_alerted:
            alert_transition = "recovered"
        _runner_liveness_alerted = False
    except Exception as exc:
        result = "unreachable"
        error_class = type(exc).__name__
        _runner_liveness_failures += 1
        logger.error(
            f"Scheduler | published runner liveness failure "
            f"{_runner_liveness_failures}/{RUNNER_HEALTH_FAILURE_THRESHOLD}: {exc}"
        )
        if (
            _runner_liveness_failures >= RUNNER_HEALTH_FAILURE_THRESHOLD
            and not _runner_liveness_alerted
        ):
            _runner_liveness_alerted = True
            alert_transition = "raised"
            message = (
                f"Published trading runner has failed "
                f"{_runner_liveness_failures} consecutive health checks. "
                f"URL: {runner_url or 'not configured'}. Latest error: {exc}"
            )
            logger.critical(f"Scheduler | RUNNER LIVENESS ALERT | {message}")
            try:
                from notifications.discord import alert_critical
                alert_critical(
                    "Published trading runner unresponsive",
                    message,
                    fields=[
                        {
                            "name": "Consecutive failures",
                            "value": str(_runner_liveness_failures),
                            "inline": True,
                        },
                        {
                            "name": "Probe timeout",
                            "value": f"{RUNNER_HEALTH_TIMEOUT_SECONDS}s",
                            "inline": True,
                        },
                    ],
                )
            except Exception as alert_exc:
                logger.error(
                    f"Scheduler | runner liveness alert failed: {alert_exc}"
                )
    finally:
        _record_runner_liveness_audit(
            result,
            endpoint_url=runner_url,
            error_class=error_class,
            reason=reason,
            consecutive_failures=_runner_liveness_failures,
            alert_transition=alert_transition,
        )


async def _probe_trading_api_liveness() -> None:
    """Probe a protected API endpoint so auth failures cannot look healthy."""
    global _trading_api_liveness_failures
    global _trading_api_liveness_alerted
    global _trading_api_liveness_checks
    try:
        secret = os.environ.get("TRADING_API_SECRET", "").strip()
        if not secret:
            raise RuntimeError("TRADING_API_SECRET is not configured")
        headers = {TRADING_API_SECRET_HEADER: secret}
        async with httpx.AsyncClient(timeout=RUNNER_HEALTH_TIMEOUT_SECONDS) as client:
            response = await client.get(
                TRADING_API_HEALTH_URL,
                headers={
                    **headers,
                    "User-Agent": "trading-api-authenticated-liveness",
                },
            )
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            if not isinstance(response.json(), dict):
                raise RuntimeError("unexpected trading API response payload")
        _trading_api_liveness_checks += 1
        recovered = _trading_api_liveness_failures > 0
        _trading_api_liveness_failures = 0
        logger.info(
            "Scheduler | protected trading API liveness result=healthy "
            f"check={_trading_api_liveness_checks} status=200 "
            f"auth_header={TRADING_API_SECRET_HEADER}"
        )
        if recovered:
            logger.warning(
                "Scheduler | protected trading API liveness recovered: "
                f"{TRADING_API_HEALTH_URL}"
            )
        _trading_api_liveness_alerted = False
    except Exception as exc:
        _trading_api_liveness_checks += 1
        _trading_api_liveness_failures += 1
        logger.error(
            "Scheduler | protected trading API liveness failure "
            f"{_trading_api_liveness_failures}/{RUNNER_HEALTH_FAILURE_THRESHOLD} "
            f"check={_trading_api_liveness_checks} "
            f"auth_header={TRADING_API_SECRET_HEADER}: {exc}"
        )
        if (
            _trading_api_liveness_failures >= RUNNER_HEALTH_FAILURE_THRESHOLD
            and not _trading_api_liveness_alerted
        ):
            _trading_api_liveness_alerted = True
            message = (
                "Published trading API protected endpoint has failed "
                f"{_trading_api_liveness_failures} consecutive checks. "
                f"URL: {TRADING_API_HEALTH_URL}. Latest error: {exc}"
            )
            logger.critical(
                f"Scheduler | TRADING API LIVENESS ALERT | {message}"
            )
            try:
                from notifications.discord import alert_critical
                alert_critical(
                    "Published trading API protected endpoint unhealthy",
                    message,
                    fields=[
                        {
                            "name": "Consecutive failures",
                            "value": str(_trading_api_liveness_failures),
                            "inline": True,
                        },
                        {
                            "name": "Probe timeout",
                            "value": f"{RUNNER_HEALTH_TIMEOUT_SECONDS}s",
                            "inline": True,
                        },
                    ],
                )
            except Exception as alert_exc:
                logger.error(
                    f"Scheduler | trading API liveness alert failed: {alert_exc}"
                )


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
        from core.build_info import current_commit
        latest = current_commit()

        # Lazy import to avoid circular dependency (main imports scheduler)
        try:
            from main import _RUNNING_HASH as _running
        except Exception:
            _running = "unknown"

        if "unknown" in (_running, latest):
            logger.info("Scheduler | deploy_hash_check: cannot verify (no commit stamp or git here)")
        elif latest != _running:
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
            # A job added before the scheduler starts has no next_run_time yet.
            "next_fire_utc": (
                str(job.next_run_time)
                if getattr(job, "next_run_time", None)
                else "paused"
            ),
        })
    return jobs


def is_auto_trading_enabled() -> bool:
    return _auto_trading_enabled


# Jobs the auto-trading toggle never pauses: none of them places orders, and
# monitoring matters most while trading is paused.
_ALWAYS_ACTIVE_JOBS = {
    "daily_discord_pnl_report",
    "daily_health_check",
    "nightly_walk_forward",
    "standing_invariants",
    "degradation_resolver",
    "order_watchdog",
    "gear_v1_g4_shadow",
    "daily_benchmark_snapshot",
    "nightly_fleet_equity_snapshot",
    "daily_bot_returns_snapshot",
    "live_vs_research_daily",
    "live_vs_research_monthly",
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


async def _daily_health_check() -> None:
    """Every day 08:40 Brisbane: one Discord line per safety check (core/daily_health.py)."""
    if not _is_published_deployment():
        logger.debug("Scheduler | daily_health_check skipped outside published deployment")
        return
    try:
        import asyncio
        from core.daily_health import run_and_send
        await asyncio.to_thread(run_and_send)
    except Exception as exc:
        logger.error(f"Scheduler | daily_health_check FAILED: {exc}")


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


async def _gear_shadow() -> None:
    """Replay the GEAR-V1-G4 rules on live bars and store the day's result. No orders."""
    try:
        from core.gear_shadow_job import run_and_store
        result = await asyncio.to_thread(run_and_store)
        logger.info(f"Scheduler | gear_v1_g4_shadow: {result.get('status')} as_of={result.get('as_of')}")
    except Exception as exc:
        logger.error(f"Scheduler | gear_v1_g4_shadow FAILED: {type(exc).__name__}: {exc}")


async def _order_watchdog() -> None:
    """Alert (never act) when any account keeps placing orders."""
    try:
        from core.order_watchdog import run_watchdog
        report = await asyncio.to_thread(run_watchdog)
        summary = {b: r["status"] for b, r in report.items()}
        logger.info(f"Scheduler | order_watchdog: {summary}")
    except Exception as exc:
        logger.error(f"Scheduler | order_watchdog FAILED: {exc}")


async def _per_bot_vault_deployment() -> None:
    """Deploy only tagged vault cash; inactive mode performs no DB/order work."""
    try:
        from execution.per_bot_vault import run_deployment_cycle
        result = await asyncio.to_thread(run_deployment_cycle, market_open=is_market_open())
        logger.info(f"Scheduler | per_bot_vault_deployment: {result.get('status')}")
    except Exception as exc:
        logger.error(f"Scheduler | per_bot_vault_deployment FAILED: {exc}")


async def _daily_bot_returns_snapshot() -> None:
    """Record all active bots without ever writing a partial fleet."""
    try:
        from analysis.research_ledger import (
            ensure_research_tables,
            snapshot_daily_returns,
        )
        await asyncio.to_thread(ensure_research_tables)
        result = await asyncio.to_thread(snapshot_daily_returns)
        stale_count = int(result.get("stale_count", 0))
        skipped_count = int(result.get("skipped_count", 0))
        if stale_count or skipped_count:
            logger.error(
                "Scheduler | daily_bot_returns_snapshot: "
                f"status={result.get('status')} "
                f"stale_count={stale_count} skipped_count={skipped_count}"
            )
        else:
            logger.info(
                "Scheduler | daily_bot_returns_snapshot: "
                f"status={result.get('status')} "
                f"stale_count={stale_count} skipped_count={skipped_count}"
            )
    except Exception as exc:
        logger.error(f"Scheduler | daily_bot_returns_snapshot FAILED: {exc}")


async def _per_bot_vault_monthly_skim() -> None:
    """VAULT-V2: record vault value and trading equity; skim on the month's first run."""
    try:
        from execution.per_bot_vault import run_monthly_skim
        result = await asyncio.to_thread(run_monthly_skim)
        logger.info(f"Scheduler | per_bot_vault_monthly_skim: {result.get('status')} "
                    f"{[(b.get('bot_id'), b.get('action')) for b in result.get('bots', [])]}")
    except Exception as exc:
        logger.error(f"Scheduler | per_bot_vault_monthly_skim FAILED: {exc}")


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


async def _snapshot_fleet_equity(*, dry_run: bool = False) -> dict[str, object]:
    """
    Job 7 — fires daily at 19:00 ET.
    Writes one fleet_equity_history row (date, total_equity) for the sparkline.
    Uses every non-retired bot_portfolio row as the source of truth (same as
    /fleet/equity route). Stale rows remain valid last-known equity.
    ON CONFLICT DO UPDATE keeps the latest value for each calendar date.
    """
    logger.info("Scheduler | JOB STARTING: nightly_fleet_equity_snapshot")
    from core.bot_registry import active_bot_ids as registry_active_bot_ids
    active_ids = registry_active_bot_ids()
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            logger.warning("Scheduler | fleet_equity_snapshot: PG unavailable — skip")
            return {"status": "skipped", "reason": "database_unavailable"}

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT bot_id, equity_usd, last_updated
                    FROM bot_portfolio
                    WHERE bot_id = ANY(%s)
                """, (active_ids,))
                portfolio_rows = cur.fetchall()

            contributed = len(portfolio_rows)
            if contributed < len(active_ids):
                missing = sorted(set(active_ids) - {row[0] for row in portfolio_rows})
                logger.error(
                    "Scheduler | fleet_equity_snapshot: refusing partial total — "
                    f"found {contributed}/{len(active_ids)} active bots; missing={missing}"
                )
                return {
                    "status": "skipped",
                    "reason": "incomplete_active_bot_rows",
                    "bot_count": contributed,
                    "missing": missing,
                }

            total = sum(float(row[1] or 0.0) for row in portfolio_rows)
            stale_bots = [
                row[0] for row in portfolio_rows
                if row[2] is None or (datetime.now(row[2].tzinfo) - row[2]).total_seconds() > 25 * 60
            ]

            # Compare against the canonical route before writing. A divergence
            # this large means the history row would poison the chart.
            try:
                from routes.fleet_equity import _fetch_fleet_equity
                canonical = _fetch_fleet_equity()["fleet_total"]["equity"]
            except Exception as exc:
                logger.critical(
                    f"Scheduler | fleet_equity_snapshot: canonical comparison failed — {exc}; refusing write"
                )
                return {"status": "skipped", "reason": "canonical_comparison_failed", "bot_count": contributed}

            divergence_pct = abs(total - float(canonical)) / float(canonical) * 100 if canonical else 0.0
            if divergence_pct > 5:
                logger.critical(
                    "Scheduler | fleet_equity_snapshot: refusing write — "
                    f"computed=${total:,.2f}, canonical=${float(canonical):,.2f}, "
                    f"divergence={divergence_pct:.2f}%"
                )
                return {
                    "status": "skipped",
                    "reason": "canonical_divergence",
                    "bot_count": contributed,
                    "computed_total": round(total, 2),
                    "canonical_total": round(float(canonical), 2),
                    "divergence_pct": round(divergence_pct, 4),
                }

            result = {
                "status": "dry_run" if dry_run else "written",
                "bot_count": contributed,
                "total_equity": round(total, 2),
                "canonical_total": round(float(canonical), 2),
                "stale_bots": stale_bots,
                "snapshot_date": str(date.today()),
            }
            logger.info(
                "Scheduler | fleet_equity_snapshot: "
                f"{'would write' if dry_run else 'writing'} ${total:,.2f} "
                f"from {contributed}/{len(active_ids)} bots; stale={stale_bots or 'none'}"
            )

            if dry_run:
                return result

            if total <= 0:
                logger.warning(f"Scheduler | fleet_equity_snapshot: total=${total:,.2f} — skip (zero equity)")
                return {"status": "skipped", "reason": "zero_equity", "bot_count": contributed}

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
        return result
    except Exception as exc:
        logger.error(f"Scheduler | fleet_equity_snapshot FAILED: {exc}")
        return {"status": "error", "reason": str(exc)}


def _fetch_fleet_equity_total() -> float:
    """Legacy heartbeat equity is retired; fleet equity has its own SSoT."""
    return 0.0


# Make _json importable inside the module-level function
import json as _json


async def _live_vs_research_daily() -> None:
    """Plan item 12: the same rules on the live feed and on research data (core/live_check_job.py)."""
    if not _is_published_deployment():
        return
    try:
        import asyncio
        from core.live_check_job import run_daily
        await asyncio.to_thread(run_daily)
    except Exception as exc:
        logger.error(f"Scheduler | live_vs_research_daily FAILED: {exc}")


async def _live_vs_research_monthly() -> None:
    if not _is_published_deployment():
        return
    try:
        import asyncio
        from core.live_check_job import send_monthly
        await asyncio.to_thread(send_monthly)
    except Exception as exc:
        logger.error(f"Scheduler | live_vs_research_monthly FAILED: {exc}")
