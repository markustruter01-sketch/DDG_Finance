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
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, APIRouter
from pydantic import BaseModel
from loguru import logger

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
    init_db,
)
from core.market_clock import is_market_open, get_next_open
from data.cache import get_cache_stats
from analysis.auditor import run_full_audit, get_last_audit
from analysis.schemas import is_crypto_pair
from execution.ratchet_stop import delete_stop
from data.sentiment import get_sentiment, get_sentiment_prompt_block
from data.onchain import get_onchain_data, get_onchain_prompt_block
from data.economic_calendar import is_blackout_active, get_upcoming_events
from analysis.attribution import compute_attribution
from analysis.backtester import run_backtest

EXPECTED_JOB_COUNT = 4
COMMENTARY_TTL_SECONDS = 1800  # 30-minute cache

_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}
_kraken_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}

# ── Commentary Cache Persistence ──────────────────────────────────────────────
# Both commentary caches are file-backed so they survive server restarts.
# Without this, every restart immediately burns Groq tokens to regenerate.
import json as _json
import threading as _ct_lock
from pathlib import Path as _Path

_COMMENTARY_CACHE_FILE = _Path("data/commentary_cache.json")
_commentary_file_lock = _ct_lock.Lock()


def _load_commentary_caches() -> None:
    """Load both commentary caches from disk on startup."""
    global _commentary_cache, _kraken_commentary_cache
    if not _COMMENTARY_CACHE_FILE.exists():
        return
    try:
        data = _json.loads(_COMMENTARY_CACHE_FILE.read_text())
        alpaca = data.get("alpaca", {})
        kraken = data.get("kraken", {})
        if alpaca.get("text") and alpaca.get("ts", 0) > 0:
            _commentary_cache = alpaca
            age_min = (time.time() - alpaca["ts"]) / 60
            logger.info(f"Commentary cache | Alpaca: loaded from disk ({age_min:.0f}min old)")
        if kraken.get("text") and kraken.get("ts", 0) > 0:
            _kraken_commentary_cache = kraken
            age_min = (time.time() - kraken["ts"]) / 60
            logger.info(f"Commentary cache | Kraken: loaded from disk ({age_min:.0f}min old)")
    except Exception as exc:
        logger.warning(f"Commentary cache | Failed to load from disk: {exc}")


def _persist_commentary_caches() -> None:
    """Atomically write both commentary caches to disk (thread-safe)."""
    try:
        _COMMENTARY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "alpaca": _commentary_cache,
            "kraken": _kraken_commentary_cache,
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

    _load_commentary_caches()
    logger.info("Commentary caches loaded from disk")

    scheduler = get_scheduler()
    scheduler.start()
    for job in scheduler.get_jobs():
        job.pause()
    logger.info(f"Scheduler started — {len(scheduler.get_jobs())} trading jobs registered (paused — auto-trading OFF)")
    logger.info("Enable auto-trading via dashboard toggle or POST /auto-trading")
    logger.info("24/7 crypto trading enabled — crypto cycles fire when stock market is closed")

    # Register the auto-heal monitor AFTER the pause loop so it stays active
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
        if job_count < EXPECTED_JOB_COUNT:
            level = "yellow"
        elif last_status in ("error", "analysis_failed", "execution_failed"):
            level = "red"
        else:
            level = "green"
        nodes["platform_core"] = {
            "label": "Main Platform Core",
            "level": level,
            "latency_ms": latency_ms,
            "data_age_s": round(age_s, 1) if age_s else None,
            "detail": f"{job_count} jobs · last: {last_status}",
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
        sf = _Path("../kraken-bot/status.json")  # server cwd = trading-platform/
        if sf.exists():
            kst = _json.loads(sf.read_text())
            last_upd = kst.get("last_updated")
            if last_upd:
                from datetime import datetime as _dt, timezone as _tz
                kage = now - _dt.fromisoformat(last_upd).timestamp()
            else:
                kage = None
            kstatus = kst.get("status", "unknown")
            if kstatus in ("error",) or (kage and kage > 300):
                level = "red"
            elif kstatus == "paused_circuit_breaker" or kstatus == "paused_dashboard" or (kage and kage > 60):
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
            nodes["kraken_api"] = {"label": "Kraken API (Crypto Bot)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": "Bot not started"}
    except Exception as exc:
        nodes["kraken_api"] = {"label": "Kraken API (Crypto Bot)", "level": "red", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # ── 4. Data Pipeline ────────────────────────────────────────────────
    try:
        caches = get_cache_stats()
        cached_count = sum(1 for c in caches if c.get("cached"))
        ages = [c["age_seconds"] for c in caches if c.get("cached") and c["age_seconds"] >= 0]
        oldest = max(ages) if ages else None
        if oldest is not None and oldest > 300:
            level = "red"
        elif oldest is not None and oldest > 60:
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
        max_single = max((float(p["market_value"]) for p in positions), default=0)
        max_pct = (max_single / equity_val * 100) if equity_val > 0 else 0
        if max_pct > 15.0:
            level = "red"
        elif max_pct > 12.0:
            level = "yellow"
        else:
            level = "green"
        nodes["equity_manager"] = {
            "label": "Equity Manager (15% Enforcer)",
            "level": level,
            "latency_ms": None,
            "data_age_s": 0,
            "detail": f"Max position: {max_pct:.1f}% · {len(positions)} holdings",
        }
    except Exception as exc:
        nodes["equity_manager"] = {"label": "Equity Manager (15% Enforcer)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

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
            sf = _Path("../kraken-bot/status.json")
            if sf.exists():
                try:
                    kst = _json.loads(sf.read_text())
                    kst["heal_requested"] = True
                    kst["heal_requested_at"] = time.time()
                    sf.write_text(_json.dumps(kst, indent=2))
                    steps.append(f"Heal flag written to status.json (cycle #{kst.get('cycle_count', 0)})")
                except Exception as exc:
                    steps.append(f"Status write warning: {exc}")
            else:
                steps.append("status.json not found — start Davy Jones bot first")
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

    # ── 1. Platform core ────────────────────────────────────────────────────
    try:
        jobs = get_job_status()
        last = get_last_run()
        last_status = last.get("last_run_status", "never")
        if len(jobs) < EXPECTED_JOB_COUNT or last_status in ("error", "analysis_failed", "execution_failed"):
            logger.warning(f"[AUTO-HEAL] platform_core critical: {len(jobs)} jobs, last_status={last_status}")
            await _remediate_component("platform_core", triggered_by="auto_heal")
    except Exception as exc:
        logger.debug(f"[AUTO-HEAL] platform_core check skipped: {exc}")

    # ── 2. Data pipeline — stale feeds > 5 min ──────────────────────────────
    try:
        from data.cache import get_cache_stats as _gcs
        caches = _gcs()
        ages = [c["age_seconds"] for c in caches if c.get("cached") and c["age_seconds"] >= 0]
        if ages and max(ages) > 300:
            logger.warning(f"[AUTO-HEAL] data_pipeline stale: max_age={max(ages):.0f}s")
            await _remediate_component("data_pipeline", triggered_by="auto_heal")
    except Exception as exc:
        logger.debug(f"[AUTO-HEAL] data_pipeline check skipped: {exc}")

    # ── 3. Kraken bot — status file older than 10 min or error state ─────────
    try:
        sf = _Path("../kraken-bot/status.json")
        if sf.exists():
            kst = _json.loads(sf.read_text())
            last_upd = kst.get("last_updated")
            if last_upd:
                from datetime import datetime as _dt
                kage = now - _dt.fromisoformat(last_upd).timestamp()
                kstatus = kst.get("status", "unknown")
                if kstatus == "error" or kage > 600:
                    logger.warning(f"[AUTO-HEAL] kraken_api critical: status={kstatus}, age={kage:.0f}s")
                    await _remediate_component("kraken_api", triggered_by="auto_heal")
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

            enriched.append({
                **pos,
                "asset_class":      alloc.get("asset_class", "unknown"),
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
    """Trade journal summary + full trade history."""
    summary = get_journal_summary()
    trades  = get_all_trades()
    return {"summary": summary, "trades": trades}


@router.get("/journal/losses", tags=["Journal"])
async def journal_losses(n: int = 5) -> dict:
    """
    The N most recent losing trades — what the RAG loop feeds into the
    next Groq system prompt as failure examples.
    """
    losses = get_recent_losses(limit=n)
    return {"count": len(losses), "losses": losses}


@router.get("/journal/wins", tags=["Journal"])
async def journal_wins(n: int = 5) -> dict:
    """
    The N most recent winning trades — what the RAG loop feeds into the
    next Groq system prompt as positive reinforcement examples.
    """
    wins = get_recent_wins(limit=n)
    return {"count": len(wins), "wins": wins}


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
            import json as _j2, pathlib as _pl2
            _sp2 = _pl2.Path("../kraken-bot/status.json")
            _k_equity = 0.0
            if _sp2.exists():
                _bs2 = _j2.loads(_sp2.read_text())
                _k_equity = float((_bs2.get("paper_summary") or {}).get("total_equity_usd", 0) or 0)
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
    Read all closed trades from kraken-bot/paper_portfolio.json and insert any
    new ones into the PostgreSQL trade journal (source='kraken_paper').
    Uses a sidecar JSON file to track already-imported trades by a composite key
    (symbol|closed_at) to prevent duplicates across postmortem runs.
    """
    import json as _jk
    from db.postgres import is_pg_available, get_conn

    if not is_pg_available():
        return {"imported": 0, "skipped": 0, "reason": "PostgreSQL unavailable"}

    _portfolio_path = os.path.join(os.path.dirname(__file__), "..", "kraken-bot", "paper_portfolio.json")
    if not os.path.exists(_portfolio_path):
        return {"imported": 0, "skipped": 0, "reason": "paper_portfolio.json not found"}

    try:
        with open(_portfolio_path) as f:
            portfolio = _jk.load(f)
    except Exception as exc:
        return {"imported": 0, "skipped": 0, "error": f"Could not read portfolio: {exc}"}

    all_trades = portfolio.get("all_trades", [])
    if not all_trades:
        return {"imported": 0, "skipped": 0, "reason": "No trades in paper portfolio"}

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
    ks_check(current_equity=0.0)
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
            }
        raise HTTPException(status_code=429, detail="Commentary daily limit reached — try again tomorrow or use ?force=true")

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
        _groq_budget.consume(tokens_used)
        _groq_budget.record_commentary_call("alpaca")
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        _commentary_cache = {"text": commentary, "generated_at": generated_at, "ts": now}
        _persist_commentary_caches()
        logger.info("AI commentary regenerated successfully")
        return {"commentary": commentary, "generated_at": generated_at, "cached": False, "cache_age_seconds": 0}
    except Exception as exc:
        logger.error(f"AI commentary generation failed: {exc}")
        if _commentary_cache["text"]:
            return {
                "commentary": _commentary_cache["text"],
                "generated_at": _commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "error": str(exc),
            }
        raise HTTPException(status_code=503, detail=f"AI commentary unavailable: {exc}")


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


@router.get("/correlation", tags=["Analytics"])
async def correlation_matrix() -> dict:
    from data.yfinance_client import get_cached_market_data
    market_data = get_cached_market_data()
    if not market_data:
        return {"error": "No market data cached yet", "matrix": {}, "tickers": []}

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
        try:
            account = get_account()
            equity = float(account["equity"])
            last_equity = float(account.get("last_equity", account["equity"]))
            if last_equity > 0:
                daily_pnl = (equity - last_equity) / last_equity * 100
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


@router.get("/performance/equity-curve", tags=["Analytics"])
async def equity_curve_endpoint(limit: int = 500) -> dict:
    """
    Return the last `limit` equity snapshots (oldest-first) for the equity curve chart.
    Each row: {id, ts, alpaca_equity, kraken_equity, total_equity, regime, source}
    """
    from db.postgres import get_equity_curve
    rows = get_equity_curve(limit=min(limit, 2000))
    return {"count": len(rows), "snapshots": rows}


@router.post("/backtest", tags=["Analytics"])
async def run_backtest_endpoint(lookback_days: int = 90) -> dict:
    from data.yfinance_client import get_cached_market_data
    market_data = get_cached_market_data()
    if not market_data:
        raise HTTPException(status_code=503, detail="No market data cached yet — run a pipeline cycle first")

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

@router.get("/kraken/status", tags=["Kraken Bot"])
async def kraken_status() -> dict:
    """
    Read and return the Kraken bot's status.json file.
    Written by kraken-bot/main.py after every trading cycle.
    Returns a safe empty-state if the bot hasn't run yet.
    """
    import json as _json
    from pathlib import Path as _Path

    status_file = _Path("../kraken-bot/status.json")  # server cwd = trading-platform/
    if not status_file.exists():
        return {
            "bot_name":         "Davy Jones' Portfolio",
            "status":           "not_started",
            "last_updated":     None,
            "cycle_count":      0,
            "total_equity_usd": 0,
            "deployed_usd":     0,
            "deployed_pct":     0,
            "deployable_ceiling_pct": 80,
            "cash_reserve_pct": 20,
            "open_positions":   [],
            "position_count":   0,
            "max_positions":    3,
            "circuit_breaker":  {"active": False, "paused_until": None},
            "recent_trades":    [],
            "error":            None,
        }
    try:
        return _json.loads(status_file.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not parse kraken status: {exc}")


# ── Kraken Bot — AI Narrative Commentary ──────────────────────────────────────

@router.get("/kraken/commentary", tags=["Kraken Bot"])
async def kraken_commentary(force: bool = False) -> dict:
    """
    Generate Davy Jones' AI narrative: thought process, learnings, and future
    behavioural adjustments.  Cached for 30 minutes.
    """
    global _kraken_commentary_cache
    import json as _json
    from pathlib import Path as _Path

    now = time.time()
    cache_age = now - _kraken_commentary_cache["ts"]

    if not force and _kraken_commentary_cache["text"] and cache_age < COMMENTARY_TTL_SECONDS:
        return {
            "commentary": _kraken_commentary_cache["text"],
            "generated_at": _kraken_commentary_cache["generated_at"],
            "cached": True,
            "cache_age_seconds": int(cache_age),
        }

    from analysis.groq_budget import budget as _groq_budget
    if not _groq_budget.can_call_commentary("kraken", force=force):
        if _kraken_commentary_cache["text"]:
            return {
                "commentary": _kraken_commentary_cache["text"],
                "generated_at": _kraken_commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "throttled": True,
            }
        raise HTTPException(status_code=429, detail="Kraken commentary daily limit reached — try again tomorrow or use ?force=true")

    status_file = _Path("../kraken-bot/status.json")
    if not status_file.exists():
        raise HTTPException(status_code=503, detail="Kraken bot has not run yet — no status file")

    try:
        kdata = _json.loads(status_file.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read kraken status: {exc}")

    positions     = kdata.get("open_positions", [])
    recent_trades = kdata.get("recent_trades", [])
    signals       = kdata.get("signals", [])
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

    user_prompt = f"""
Davy Jones' current open positions (Kraken 24/7 mean-reversion crypto bot):
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
        "You are 'Davy Jones' — a relentless 24/7 crypto mean-reversion trading AI with the soul of a seasoned "
        "sailor who reads market currents like ocean tides. In exactly 3 punchy sentences: "
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
        _groq_budget.consume(tokens_used)
        _groq_budget.record_commentary_call("kraken")
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        _kraken_commentary_cache = {"text": commentary, "generated_at": generated_at, "ts": now}
        _persist_commentary_caches()
        logger.info("Kraken AI commentary regenerated successfully")
        return {"commentary": commentary, "generated_at": generated_at, "cached": False, "cache_age_seconds": 0}
    except Exception as exc:
        logger.error(f"Kraken AI commentary generation failed: {exc}")
        if _kraken_commentary_cache["text"]:
            return {
                "commentary": _kraken_commentary_cache["text"],
                "generated_at": _kraken_commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "error": str(exc),
            }
        raise HTTPException(status_code=503, detail=f"Kraken commentary unavailable: {exc}")


# ── Kraken Bot — Performance Metrics ──────────────────────────────────────────
# Separate from the Alpaca performance endpoints (/performance/history,
# /performance/summary). This reads exclusively from kraken-bot/status.json
# which is written only by kraken-bot/main.py.
# The Alpaca trading system never touches this file.

@router.get("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_auto_trading_status() -> dict:
    """Return the current Kraken bot pause state from control.json."""
    import json as _json
    from pathlib import Path as _Path
    ctrl = _Path("../kraken-bot/control.json")  # server cwd = trading-platform/
    if not ctrl.exists():
        return {"bot_paused": False}
    try:
        return {"bot_paused": bool(_json.loads(ctrl.read_text()).get("bot_paused", False))}
    except Exception:
        return {"bot_paused": False}


class KrakenControlRequest(BaseModel):
    bot_paused: bool


@router.post("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_toggle_auto_trading(request: KrakenControlRequest) -> dict:
    """
    Pause or resume the Kraken bot by writing control.json.
    The bot reads this file at the start of each cycle.
    The workflow keeps running — only signal processing is paused.
    """
    import json as _json
    from pathlib import Path as _Path
    ctrl = _Path("../kraken-bot/control.json")  # server cwd = trading-platform/
    ctrl.write_text(_json.dumps({"bot_paused": request.bot_paused}, indent=2))
    logger.info(f"Kraken bot {'PAUSED' if request.bot_paused else 'RESUMED'} via dashboard toggle")
    return {"bot_paused": request.bot_paused, "message": "Kraken bot paused" if request.bot_paused else "Kraken bot resumed"}


@router.get("/kraken/performance", tags=["Kraken Bot"])
async def kraken_performance() -> dict:
    """
    Derive performance statistics from the Kraken bot's status.json.

    DATA SOURCE: kraken-bot/status.json (Kraken exchange, separate capital pool)
    NOT RELATED TO: /performance/history or /performance/summary (Alpaca data)

    Returns computed metrics over the recent_trades history:
      - trade count, win rate, total/best/worst/avg P&L
      - per-symbol breakdown
      - the full recent trade list
    """
    import json as _json
    from pathlib import Path as _Path

    status_file = _Path("../kraken-bot/status.json")  # server cwd = trading-platform/

    # Empty state — bot hasn't run yet
    empty: dict = {
        "data_source":     "kraken-bot/status.json",
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

    if not status_file.exists():
        return empty

    try:
        status = _json.loads(status_file.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not parse kraken status: {exc}")

    trades: list[dict] = status.get("recent_trades", [])

    if not trades:
        empty["bot_status"]    = status.get("status", "not_started")
        empty["current_equity"] = status.get("total_equity_usd", 0)
        empty["cycle_count"]   = status.get("cycle_count", 0)
        return empty

    pnl_list   = [t["pnl_pct"] for t in trades]
    pnl_usd    = [t["pnl_usd"] for t in trades]
    wins       = [p for p in pnl_list if p > 0]
    losses     = [p for p in pnl_list if p <= 0]
    win_rate   = (len(wins) / len(trades)) * 100 if trades else 0

    # Per-symbol aggregation
    by_symbol: dict[str, dict] = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "wins": 0, "total_pnl_pct": 0.0, "total_pnl_usd": 0.0}
        by_symbol[sym]["trades"]        += 1
        by_symbol[sym]["total_pnl_pct"] += t["pnl_pct"]
        by_symbol[sym]["total_pnl_usd"] += t["pnl_usd"]
        if t["pnl_pct"] > 0:
            by_symbol[sym]["wins"] += 1

    for sym in by_symbol:
        n = by_symbol[sym]["trades"]
        by_symbol[sym]["win_rate_pct"]  = round((by_symbol[sym]["wins"] / n) * 100, 1) if n else 0
        by_symbol[sym]["total_pnl_pct"] = round(by_symbol[sym]["total_pnl_pct"], 2)
        by_symbol[sym]["total_pnl_usd"] = round(by_symbol[sym]["total_pnl_usd"], 2)

    return {
        "data_source":     "kraken-bot/status.json",
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
        "current_equity":  status.get("total_equity_usd", 0),
        "cycle_count":     status.get("cycle_count", 0),
        "bot_status":      status.get("status", "unknown"),
    }


app.include_router(router)

# ── System B: Public SaaS Platform routes ─────────────────────────────────────
# Registered separately under /saas-api — no overlap with /trading-api above.
from saas_router import saas_router                          # noqa: E402
from saas_stripe_router import stripe_bp                     # noqa: E402
app.include_router(saas_router)
app.include_router(stripe_bp, prefix="/saas-api")
