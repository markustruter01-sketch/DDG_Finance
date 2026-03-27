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
  GET  /docs                — Auto-generated Swagger UI (FastAPI default)
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from loguru import logger

from config.settings import settings
from core.pipeline import get_last_run, run_pipeline, run_postmortem
from core.scheduler import get_job_status, get_scheduler
from execution.broker import get_account, get_positions, get_open_orders
from execution.kill_switch import (
    get_state as ks_get_state,
    is_tripped,
    reset as ks_reset,
    check as ks_check,
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

EXPECTED_JOB_COUNT = 3


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

    scheduler = get_scheduler()
    scheduler.start()
    logger.info(f"Scheduler started — {len(scheduler.get_jobs())} jobs registered")
    for job in get_job_status():
        logger.info(f"  {job['id']}: next={job['next_fire_utc']}")

    yield

    logger.info("Shutting down scheduler...")
    scheduler.shutdown(wait=False)
    logger.info("Trading platform stopped.")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Quantitative Trading Platform",
    description=(
        "AI-driven macro quant trading system. "
        "FRED macro + Alpaca market data + NewsAPI → "
        "Groq LLM (Llama 3.3 70B) → Kelly-sized 10-slot allocation → "
        "Alpaca paper trading execution."
    ),
    version="1.1.0",
    lifespan=lifespan,
)


# ── Request / Response models ─────────────────────────────────────────────────

class RunRequest(BaseModel):
    dry_run: bool = False
    force: bool = False


class KillResetRequest(BaseModel):
    opening_equity: float | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
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
    elif last_status == "error":
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
        "version": "1.1.0",
        "system_status": system_status,
        "status_reason": status_reason,
        "scheduler_job_count": job_count,
        "last_run_status": last_status,
        "error_count": error_count,
    }


@app.get("/status", tags=["System"])
async def status() -> dict:
    """
    Full platform status snapshot:
    market clock, kill switch, scheduler jobs, last pipeline run.
    """
    market_open = is_market_open()
    return {
        "market": {
            "is_open":   market_open,
            "next_open": get_next_open() if not market_open else None,
        },
        "kill_switch":   ks_get_state(),
        "scheduler_jobs": get_job_status(),
        "last_run":      get_last_run(),
    }


@app.get("/portfolio", tags=["Portfolio"])
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


@app.get("/positions/live", tags=["Portfolio"])
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

        enriched = []
        for pos in positions:
            symbol = pos.get("symbol", "")
            alloc = alloc_by_ticker.get(symbol, {})
            entry_price = pos.get("avg_entry_price", 0) or 0
            stop_loss_pct   = alloc.get("stop_loss_pct")
            take_profit_pct = alloc.get("take_profit_pct")

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
            })

        return {"count": len(enriched), "positions": enriched}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {exc}")


@app.get("/journal", tags=["Journal"])
async def journal() -> dict:
    """Trade journal summary + full trade history."""
    summary = get_journal_summary()
    trades  = get_all_trades()
    return {"summary": summary, "trades": trades}


@app.get("/journal/losses", tags=["Journal"])
async def journal_losses(n: int = 5) -> dict:
    """
    The N most recent losing trades — what the RAG loop feeds into the
    next Groq system prompt as failure examples.
    """
    losses = get_recent_losses(limit=n)
    return {"count": len(losses), "losses": losses}


@app.get("/journal/wins", tags=["Journal"])
async def journal_wins(n: int = 5) -> dict:
    """
    The N most recent winning trades — what the RAG loop feeds into the
    next Groq system prompt as positive reinforcement examples.
    """
    wins = get_recent_wins(limit=n)
    return {"count": len(wins), "wins": wins}


@app.get("/performance", tags=["Performance"])
async def performance_history(limit: int = 90) -> dict:
    """
    Full daily performance snapshot history (up to 90 days by default).
    Each row: date, equity, daily_pnl_pct, cumulative_pnl_pct, win_rate, trades_placed.
    """
    snapshots = get_performance_snapshots(limit=limit)
    return {"count": len(snapshots), "snapshots": snapshots}


@app.get("/performance/summary", tags=["Performance"])
async def performance_summary_endpoint() -> dict:
    """
    Aggregate performance statistics across all recorded snapshots.
    Returns total_return_pct, best/worst day, overall win rate, total trades.
    """
    summary = get_performance_summary()
    return summary


@app.post("/run", tags=["Control"])
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
    result = await run_pipeline(force=request.force, dry_run=request.dry_run)
    return result


@app.post("/run/postmortem", tags=["Control"])
async def manual_postmortem() -> dict:
    """Manually trigger the post-mortem P&L reconciliation."""
    logger.info("Manual post-mortem requested")
    return await run_postmortem()


@app.post("/kill", tags=["Risk"])
async def trip_kill_switch() -> dict:
    """
    Manually trip the kill switch — immediately liquidates all positions
    and blocks further trading for the rest of the day.
    """
    logger.warning("Kill switch MANUALLY tripped via API")
    ks_check(current_equity=0.0)
    return {"status": "tripped", "kill_switch": ks_get_state()}


@app.post("/kill/reset", tags=["Risk"])
async def reset_kill_switch(request: KillResetRequest) -> dict:
    """
    Reset the kill switch for a new trading day.
    Optionally pass opening_equity to override the Alpaca-fetched baseline.
    """
    logger.info(f"Kill switch reset via API | opening_equity={request.opening_equity}")
    ks_reset(opening_equity=request.opening_equity)
    return {"status": "reset", "kill_switch": ks_get_state()}


@app.get("/allocation/latest", tags=["Portfolio"])
async def latest_allocation() -> dict:
    """Return the most recent LLM allocation plan (from last pipeline run)."""
    last = get_last_run()
    allocation = last.get("last_allocation")
    if not allocation:
        return {"status": "no_allocation_yet", "allocation": None}
    return {
        "status": "ok",
        "run_utc": last.get("last_run_utc"),
        "allocation": allocation,
    }


# ── Phase 1 compatibility endpoint ────────────────────────────────────────────

@app.get("/data/snapshot", tags=["Debug"])
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
