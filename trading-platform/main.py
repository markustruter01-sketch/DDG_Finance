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
from core.pipeline import get_last_run, run_pipeline, run_postmortem
from core.scheduler import get_job_status, get_scheduler, is_auto_trading_enabled, set_auto_trading
from execution.broker import get_account, get_positions, get_open_orders, close_position, cancel_all_orders
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
    for job in scheduler.get_jobs():
        job.pause()
    logger.info(f"Scheduler started — {len(scheduler.get_jobs())} jobs registered (paused — auto-trading OFF)")
    logger.info("Enable auto-trading via dashboard toggle or POST /auto-trading")
    logger.info("24/7 crypto trading enabled — crypto cycles fire when stock market is closed")

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
    market clock, kill switch, scheduler jobs, last pipeline run, cache stats.
    """
    market_open = is_market_open()
    last_run = get_last_run()
    if not is_auto_trading_enabled():
        trading_mode = "idle"
    elif market_open:
        trading_mode = "full_market"
    else:
        trading_mode = "crypto_only"
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
    }


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
    return await run_postmortem()


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

    user_prompt = f"""
Recent Wins (reinforcing behaviour):
{wins_text}

Recent Losses (behavioural corrections needed):
{losses_text}

Journal summary: {summary.get('wins', 0)} wins / {summary.get('losses', 0)} losses total, avg P&L {summary.get('avg_pnl') or 0:.2f}%

Current open positions:
{positions_text}
"""

    system_prompt = (
        "You are an AI quantitative trading assistant with a distinct, confident personality. "
        "In 3–4 short, punchy sentences maximum, share: "
        "(1) the single most important thing you have learned from your recent wins and losses "
        "and exactly how you are adjusting your strategy; "
        "(2) a candid one-line take on how the current open positions are looking right now. "
        "Be direct, specific, and avoid generic statements. "
        "Write in first person, casual but intelligent. No bullet points. Plain paragraph only."
    )

    def _blocking_call() -> str:
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
            max_tokens=220,
        )
        return resp.choices[0].message.content.strip()

    try:
        loop = asyncio.get_event_loop()
        commentary = await loop.run_in_executor(None, _blocking_call)
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        _commentary_cache = {"text": commentary, "generated_at": generated_at, "ts": now}
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
        return {
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown_pct": None,
            "calmar_ratio": None,
            "volatility_annual_pct": None,
            "data_points": 0,
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


app.include_router(router)
