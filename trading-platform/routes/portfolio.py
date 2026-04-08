"""Portfolio routes: portfolio, positions/live, journal, learning-journal,
performance, allocation, AI commentary, vault, auditor, correlation,
calendar, sentiment, onchain, backtest, equity-curve, data/snapshot, export/report."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date

from fastapi import APIRouter, HTTPException, BackgroundTasks
from loguru import logger

from core.pipeline import get_last_run
from core.market_clock import is_market_open
from execution.broker import get_account, get_positions, get_open_orders
from analysis.trade_journal import (
    get_journal_summary, get_recent_losses, get_recent_wins,
    get_all_trades, get_performance_snapshots, get_performance_summary,
    get_recent_trades_combined,
)
from analysis.auditor import run_full_audit, get_last_audit, run_performance_analysis, get_last_performance_report
from analysis.schemas import is_crypto_pair
from data.sentiment import get_sentiment
from data.onchain import get_onchain_data
from data.economic_calendar import is_blackout_active, get_upcoming_events
from analysis.attribution import compute_attribution
from analysis.backtester import run_backtest
from data.cache import get_cache_stats
from execution.kill_switch import get_state as ks_get_state
from core.scheduler import get_job_status, is_auto_trading_enabled

from routes._deps import (
    COMMENTARY_TTL_SECONDS,
    KRAKEN_BOT_PROFILES,
    _commentary_cache,
    _persist_commentary_caches,
    _load_kraken_journal_trades,
    _get_forex_engine,
    _get_forex_db,
)

portfolio_router = APIRouter()


@portfolio_router.get("/portfolio", tags=["Portfolio"])
async def portfolio() -> dict:
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
    if stop_data:
        stop_price = stop_data.get("stop_price", 0)
        if stop_price and current_price:
            buffer_pct = ((current_price - stop_price) / current_price) * 100
            if buffer_pct < 1.0:
                score -= 10
            elif buffer_pct < 2.0:
                score -= 5
        if stop_data.get("ratcheted"):
            score += 5

    score = max(0, min(100, score))

    if score >= 70:
        label = "strong"
    elif score >= 40:
        label = "moderate"
    else:
        label = "weak"

    return {
        "health_score": round(score, 1),
        "health_label": label,
        "momentum_3mo": mom_3,
        "momentum_6mo": mom_6,
        "conviction": conviction,
        "stop_buffer_pct": round(((current_price - (stop_data or {}).get("stop_price", 0)) / current_price * 100), 2) if current_price and stop_data and stop_data.get("stop_price") else None,
        "ratcheted": (stop_data or {}).get("ratcheted", False),
    }


@portfolio_router.get("/positions/live", tags=["Portfolio"])
async def live_positions() -> dict:
    try:
        positions = get_positions()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {exc}")

    last_run = get_last_run()
    allocation = last_run.get("last_allocation") or []

    alloc_by_ticker = {}
    for slot in allocation:
        ticker = slot.get("ticker") or slot.get("symbol")
        if ticker:
            alloc_by_ticker[ticker] = slot

    by_ticker_data: dict = {}
    try:
        from data.yfinance_client import get_cached_market_data
        mkt = get_cached_market_data()
        if mkt:
            by_ticker_data = mkt.get("by_ticker", {})
    except Exception:
        pass

    saved_stops: dict = {}
    try:
        from execution.ratchet_stop import get_all_stops
        saved_stops = get_all_stops()
    except Exception:
        pass

    enriched = []
    for pos in positions:
        symbol = pos.get("symbol", "")
        alloc_info = alloc_by_ticker.get(symbol, {})
        health = _compute_position_health(pos, alloc_info, by_ticker_data, saved_stops)

        enriched.append({
            **pos,
            "allocation_entry": {
                "conviction_score": alloc_info.get("conviction_score"),
                "kelly_fraction":   alloc_info.get("kelly_fraction"),
                "thesis":           alloc_info.get("thesis"),
                "regime":           last_run.get("last_regime"),
                "stop_loss":        alloc_info.get("stop_loss"),
                "take_profit":      alloc_info.get("take_profit"),
            },
            "health": health,
        })

    return {
        "positions": enriched,
        "count": len(enriched),
        "allocation_run_utc": last_run.get("last_run_utc"),
    }


@portfolio_router.get("/journal", tags=["Journal"])
async def journal(limit: int = 100) -> dict:
    alpaca_trades = get_all_trades(limit=limit)
    kraken_trades = _load_kraken_journal_trades()
    combined = alpaca_trades + kraken_trades
    combined.sort(key=lambda x: str(x.get("date", "")), reverse=True)
    combined = combined[:limit]
    summary = get_journal_summary()
    return {
        "summary": summary,
        "trades": combined,
        "total_count": len(combined),
    }


@portfolio_router.get("/journal/losses", tags=["Journal"])
async def journal_losses(n: int = 5) -> dict:
    alpaca_losses = get_recent_losses(limit=n * 4)
    kraken_all = _load_kraken_journal_trades()
    kraken_losses = [t for t in kraken_all if t["pnl_percentage"] < 0]
    combined = sorted(alpaca_losses + kraken_losses, key=lambda x: x["pnl_percentage"])
    losses = combined[:n]
    return {"count": len(losses), "losses": losses}


@portfolio_router.get("/journal/wins", tags=["Journal"])
async def journal_wins(n: int = 5) -> dict:
    alpaca_wins = get_recent_wins(limit=n * 4)
    kraken_all = _load_kraken_journal_trades()
    kraken_wins = [t for t in kraken_all if t["pnl_percentage"] > 0]
    combined = sorted(alpaca_wins + kraken_wins, key=lambda x: x["pnl_percentage"], reverse=True)
    wins = combined[:n]
    return {"count": len(wins), "wins": wins}


@portfolio_router.get("/journal/recent", tags=["Journal"])
async def journal_recent(n: int = 20) -> dict:
    trades = get_recent_trades_combined(limit=n)
    return {"count": len(trades), "trades": trades}


@portfolio_router.get("/learning-journal", tags=["Journal"])
async def learning_journal_endpoint(
    regime: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> dict:
    from analysis.learning_journal import get_journal_entries
    entries = get_journal_entries(regime=regime, category=category, limit=limit)
    return {"count": len(entries), "entries": entries}


@portfolio_router.get("/performance", tags=["Performance"])
async def performance_history(limit: int = 90) -> dict:
    snapshots = get_performance_snapshots(limit=limit)
    return {"count": len(snapshots), "snapshots": snapshots}


@portfolio_router.get("/performance/summary", tags=["Performance"])
async def performance_summary_endpoint() -> dict:
    summary = get_performance_summary()
    return summary


@portfolio_router.get("/allocation/latest", tags=["Portfolio"])
async def latest_allocation() -> dict:
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


@portfolio_router.get("/ai/commentary", tags=["AI"])
async def ai_commentary(force: bool = False) -> dict:
    import routes._deps as _deps

    now = time.time()
    cache_age = now - _deps._commentary_cache["ts"]

    if not force and _deps._commentary_cache["text"] and cache_age < COMMENTARY_TTL_SECONDS:
        return {
            "commentary": _deps._commentary_cache["text"],
            "generated_at": _deps._commentary_cache["generated_at"],
            "cached": True,
            "cache_age_seconds": int(cache_age),
        }

    from analysis.groq_budget import budget as _groq_budget
    if not _groq_budget.can_call_commentary("alpaca", force=force):
        if _deps._commentary_cache["text"]:
            return {
                "commentary": _deps._commentary_cache["text"],
                "generated_at": _deps._commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "throttled": True,
                "budget_exhausted": _groq_budget.budget_exhausted(),
            }
        _exhausted = _groq_budget.budget_exhausted()
        return {
            "commentary": (
                "The Oracle is resting — daily AI token budget exhausted. Commentary will resume tomorrow at midnight UTC."
                if _exhausted else
                "The Oracle is resting — daily call limit reached. Commentary will resume tomorrow at midnight UTC."
            ),
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "throttled": True,
            "budget_exhausted": _exhausted,
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
        _groq_budget.consume(tokens_used, call_type="commentary")
        if not force:
            _groq_budget.record_commentary_call("alpaca")
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        _deps._commentary_cache.update({"text": commentary, "generated_at": generated_at, "ts": now})
        _persist_commentary_caches()
        logger.info(f"AI commentary regenerated successfully (force={force}, tokens={tokens_used})")
        return {"commentary": commentary, "generated_at": generated_at, "cached": False, "cache_age_seconds": 0}
    except Exception as exc:
        logger.error(f"AI commentary generation failed: {exc}")
        _deps._commentary_cache["ts"] = now - COMMENTARY_TTL_SECONDS + 300
        if _deps._commentary_cache["text"]:
            return {
                "commentary": _deps._commentary_cache["text"],
                "generated_at": _deps._commentary_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "error": str(exc),
            }
        return {
            "commentary": "The Oracle is resting — daily AI token limit reached. Check back tomorrow for fresh market insight.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "error": str(exc),
            "unavailable": True,
        }


@portfolio_router.get("/vault", tags=["Vault"])
async def vault_state() -> dict:
    from execution.profit_sweep import get_vault_state, _use_pg, _pg_conn
    from datetime import datetime, timedelta
    state = get_vault_state()
    if state is None:
        return {
            "initialised": False,
            "message": "Vault not yet initialised — run a pipeline cycle to set the High Water Mark.",
        }
    vaulted_24h = 0.0
    try:
        if _use_pg():
            # Use today's UTC midnight as cutoff so contributions only drop off
            # at the daily reset — not gradually throughout the day as with a
            # rolling 24h window. This makes the figure monotonically increasing
            # within a calendar day.
            today_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            with _pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COALESCE(SUM(pnl_usd * 0.20), 0.0) FROM kraken_trades "
                        "WHERE pnl_usd > 0 AND closed_at >= %s",
                        (today_utc,),
                    )
                    row = cur.fetchone()
                    vaulted_24h += float(row[0] or 0)
                    try:
                        cur.execute(
                            "SELECT COALESCE(SUM(pnl_usd * 0.20), 0.0) FROM forex_trades "
                            "WHERE pnl_usd > 0 AND exit_time >= %s",
                            (today_utc,),
                        )
                        row2 = cur.fetchone()
                        vaulted_24h += float(row2[0] or 0)
                    except Exception:
                        pass
    except Exception:
        pass
    return {"initialised": True, "vaulted_24h": round(vaulted_24h, 2), **state}


@portfolio_router.post("/vault/sweep", tags=["Vault"])
async def manual_vault_sweep(dry_run: bool = False) -> dict:
    from execution.profit_sweep import run_profit_sweep
    from execution.broker import get_account
    try:
        acct = get_account()
        equity = acct["equity"]
        result = run_profit_sweep(current_equity=equity, dry_run=dry_run)
        return {"status": "ok", "dry_run": dry_run, "current_equity": equity, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vault sweep failed: {exc}")


@portfolio_router.get("/auditor/report", tags=["Auditor"])
async def auditor_report() -> dict:
    result = get_last_audit()
    if result["overall"] == "never_run":
        return {
            "status": "no_audit_yet",
            "message": "No audit has been run yet. POST /auditor/run to trigger one.",
            "report":  None,
        }
    return {"status": "ok", "report": result}


@portfolio_router.post("/auditor/run", tags=["Auditor"])
async def trigger_audit(background_tasks: BackgroundTasks) -> dict:
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


@portfolio_router.get("/auditor/performance", tags=["Auditor"])
async def auditor_performance_report() -> dict:
    return get_last_performance_report()


@portfolio_router.post("/auditor/performance/run", tags=["Auditor"])
async def trigger_performance_analysis(
    background_tasks: BackgroundTasks,
    days: int = 10,
) -> dict:
    logger.info(f"PerfAnalysis | Manual trigger via POST /auditor/performance/run (days={days})")

    async def _bg_perf() -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: run_performance_analysis(days=days))
        except Exception as exc:
            logger.error(f"PerfAnalysis | Background analysis failed: {exc}")

    background_tasks.add_task(_bg_perf)
    return {
        "status":  "analysis_started",
        "message": f"Performance analysis running — check GET /auditor/performance in ~15 seconds",
        "days":    days,
    }


@portfolio_router.get("/correlation", tags=["Analytics"])
async def correlation_matrix() -> dict:
    from data.yfinance_client import get_cached_market_data, fetch_market_data
    market_data = get_cached_market_data()
    if not market_data:
        try:
            logger.info("Correlation | Cache empty — fetching market data on demand")
            market_data = await fetch_market_data(period="3mo", crypto_only=False)
        except Exception as _fe:
            logger.warning(f"Correlation | On-demand fetch failed: {_fe}")
            return {"error": "Unable to fetch market data for correlation", "matrix": {}, "tickers": []}

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


@portfolio_router.get("/calendar", tags=["Analytics"])
async def economic_calendar(days_ahead: int = 7) -> dict:
    blackout = is_blackout_active()
    upcoming = get_upcoming_events(days_ahead=days_ahead)
    return {
        "blackout": blackout,
        "upcoming_events": upcoming,
        "event_count": len(upcoming),
    }


@portfolio_router.get("/sentiment", tags=["Analytics"])
async def sentiment_endpoint(force: bool = False) -> dict:
    return get_sentiment(force=force)


@portfolio_router.get("/onchain", tags=["Analytics"])
async def onchain_endpoint(force: bool = False) -> dict:
    return get_onchain_data(force=force)


@portfolio_router.get("/performance/attribution", tags=["Performance"])
async def performance_attribution() -> dict:
    return compute_attribution()


@portfolio_router.get("/performance/risk-metrics", tags=["Performance"])
async def risk_metrics() -> dict:
    snapshots = get_performance_snapshots(limit=90)
    if not snapshots:
        try:
            import numpy as np
            from db.postgres import get_conn as _gc
            with _gc() as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute(
                        "SELECT pnl_percentage FROM trades WHERE status LIKE 'Closed_%' ORDER BY date ASC"
                    )
                    _rows = _cur.fetchall()
            trade_returns = [float(r[0]) / 100.0 for r in _rows if r[0] is not None]
            for _kt in _load_kraken_journal_trades():
                if _kt.get("pnl_percentage") is not None:
                    trade_returns.append(float(_kt["pnl_percentage"]) / 100.0)
            if len(trade_returns) >= 2:
                arr = np.array(trade_returns)
                mean_ret = float(np.mean(arr))
                std_ret = float(np.std(arr, ddof=1))
                periods_per_year = 252 / 30
                rf_per_period = 0.05 / periods_per_year
                sharpe = float((mean_ret - rf_per_period) / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else None
                downside = arr[arr < 0]
                downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else None
                sortino = float((mean_ret - rf_per_period) / downside_std * np.sqrt(periods_per_year)) if downside_std and downside_std > 0 else None
                max_dd = round(abs(float(np.min(arr))) * 100, 2)
                ann_return = round(mean_ret * periods_per_year * 100, 2)
                calmar = round(ann_return / max_dd, 3) if max_dd > 0 else None
                vol_annual = round(std_ret * np.sqrt(periods_per_year) * 100, 2) if std_ret > 0 else None
                return {
                    "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
                    "sortino_ratio": round(sortino, 3) if sortino is not None else None,
                    "max_drawdown_pct": max_dd,
                    "calmar_ratio": calmar,
                    "volatility_annual_pct": vol_annual,
                    "annualised_return_pct": ann_return,
                    "data_points": len(trade_returns),
                    "period_days": len(trade_returns) * 30,
                    "source": "trade_journal",
                    "message": f"Estimated from {len(trade_returns)} closed trades (30-day hold assumption)",
                }
        except Exception as _te:
            logger.warning(f"Risk Metrics | Trade journal fallback failed: {_te}")
        try:
            account = get_account()
            equity = float(account["equity"])
            last_equity = float(account.get("last_equity", account["equity"]))
            if last_equity > 0:
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


def _build_synthetic_equity_curve() -> list[dict]:
    import json as _j
    from pathlib import Path as _P
    from collections import defaultdict
    from datetime import datetime, timedelta

    alpaca_start = 100_000.0
    kraken_start = 0.0

    kraken_daily_pnl: dict = defaultdict(float)
    try:
        import psycopg2 as _pg2sc, os as _ossc
        _dburlsc = _ossc.environ.get("DATABASE_URL")
        if _dburlsc:
            _scconn = _pg2sc.connect(_dburlsc)
            try:
                with _scconn.cursor() as _scc:
                    _scc.execute("SELECT COALESCE(SUM(starting_balance_usd), 0) FROM kraken_portfolio")
                    _scr = _scc.fetchone()
                    if _scr:
                        kraken_start = float(_scr[0] or 300_000.0)
                    _scc.execute("SELECT pnl_usd, closed_at FROM kraken_trades WHERE pnl_usd IS NOT NULL ORDER BY closed_at ASC")
                    for _tr in _scc.fetchall():
                        _d = (_tr[1].isoformat() if _tr[1] else "")[:10]
                        if _d:
                            kraken_daily_pnl[_d] += float(_tr[0])
            finally:
                _scconn.close()
    except Exception:
        kraken_start = 300_000.0

    alpaca_daily_pnl: dict = defaultdict(float)
    try:
        from db.postgres import get_conn as _gc2
        with _gc2() as _conn2:
            with _conn2.cursor() as _cur2:
                _cur2.execute(
                    "SELECT date, pnl_percentage FROM trades WHERE status LIKE 'Closed_%' ORDER BY date ASC"
                )
                for _row2 in _cur2.fetchall():
                    _d2 = str(_row2[0])[:10]
                    _ppct = float(_row2[1] or 0) / 100.0
                    _position_size = alpaca_start * 0.05
                    alpaca_daily_pnl[_d2] += _position_size * _ppct
    except Exception:
        pass

    all_dates = sorted(set(list(alpaca_daily_pnl.keys()) + list(kraken_daily_pnl.keys())))
    if not all_dates:
        return []

    curve = []
    a_eq = alpaca_start
    k_eq = kraken_start
    for d in all_dates:
        a_eq += alpaca_daily_pnl.get(d, 0)
        k_eq += kraken_daily_pnl.get(d, 0)
        curve.append({
            "ts": f"{d}T12:00:00",
            "alpaca_equity": round(a_eq, 2),
            "kraken_equity": round(k_eq, 2),
            "options_equity": 0,
            "forex_equity": 0,
            "total_equity": round(a_eq + k_eq, 2),
            "regime": None,
            "source": "synthetic",
        })
    return curve


@portfolio_router.get("/performance/equity-curve", tags=["Analytics"])
async def equity_curve(limit: int = 90) -> dict:
    from db.postgres import get_equity_curve as _get_eq_curve
    rows = _get_eq_curve(limit=limit)
    if rows and len(rows) >= 2:
        return {"curve": rows, "count": len(rows), "source": "equity_snapshots"}
    synthetic = _build_synthetic_equity_curve()
    if synthetic:
        return {"curve": synthetic[-limit:], "count": len(synthetic[-limit:]), "source": "synthetic_from_trades"}
    return {"curve": [], "count": 0, "source": "no_data"}


@portfolio_router.post("/backtest", tags=["Analytics"])
async def backtest_endpoint(
    ticker: str = "SPY",
    period: str = "6mo",
    stop_loss: float = 5.0,
    take_profit: float = 10.0,
) -> dict:
    try:
        result = run_backtest(
            ticker=ticker,
            period=period,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}")


@portfolio_router.get("/data/snapshot", tags=["Debug"])
async def data_snapshot() -> dict:
    from data.yfinance_client import get_cached_market_data
    from data.fred_macro import get_latest_macro
    from data.news_api import get_news_data

    market_data = get_cached_market_data() or {}
    macro_data  = get_latest_macro() or {}
    news_data   = get_news_data() or {"all_headlines": []}

    return {
        "market_data_keys": list(market_data.get("by_ticker", {}).keys()) if market_data else [],
        "market_data_stale": market_data.get("stale", True) if market_data else True,
        "macro_keys": list(macro_data.keys()) if isinstance(macro_data, dict) else [],
        "news_headlines_count": len(news_data["all_headlines"]),
        "news_sample": news_data["all_headlines"][:5],
    }


@portfolio_router.get("/export/report", tags=["Export"])
async def export_diagnostic_report():
    from starlette.responses import PlainTextResponse
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime as _dt, timezone as _tz
    from analysis.attribution import compute_attribution as _attr
    from analysis.learning_journal import get_journal_entries as _lj
    from analysis.groq_budget import budget as _groq_budget
    import options_engine as _opts
    from routes import report_sections as _rs

    now_utc = _dt.now(_tz.utc)
    ts = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

    def _c(v, decimals=2, prefix="$"):
        if v is None:
            return "N/A"
        if prefix == "$":
            return f"${v:,.{decimals}f}"
        return f"{v:.{decimals}f}"

    def _pct(v, decimals=2):
        if v is None:
            return "N/A"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.{decimals}f}%"

    def _safe(d, *keys, default="N/A"):
        for k in keys:
            if not isinstance(d, dict):
                return default
            d = d.get(k, None)
            if d is None:
                return default
        return d if d is not None else default

    lines: list[str] = []
    W = "\u2550" * 80

    def h1(title: str):
        lines.append(W)
        lines.append(f"  {title}")
        lines.append(W)

    def h2(title: str):
        lines.append("")
        sep = "\u2500" * max(0, 74 - len(title))
        lines.append(f"\u2500\u2500 {title} {sep}")

    def row(label: str, value: str, indent: int = 2):
        lines.append(f"{'  ' * indent}{label:<32}{value}")

    lines.append(W)
    lines.append("  QUANTITATIVE TRADING PLATFORM \u2014 AI DIAGNOSTIC REPORT")
    lines.append(f"  Generated: {ts}")
    lines.append("  PURPOSE: Paste into Claude / Gemini / ChatGPT for strategy analysis.")
    lines.append("           Contains all trade history, AI reasoning, risk parameters,")
    lines.append("           entry/exit conditions, and performance data for ALL 6 BOTS.")
    lines.append("  FLEET:   #1 Oracle (Alpaca), #2 Davy Jones, #3 Blackbeard, #4 Calypso (Kraken),")
    lines.append("           #5 Apex Predator (Options), #6 Navigator (Forex)")
    lines.append("  CAPITAL: $600,000 total across 4 capital pools")
    lines.append(W)

    try:
        ks_state   = ks_get_state()
        mkt_open   = is_market_open()
        sched_jobs = get_job_status()
        last_run   = get_last_run()
        groq_tok   = _groq_budget.remaining if hasattr(_groq_budget, "remaining") else None
        groq_max   = getattr(_groq_budget, "daily_limit", 100_000)
        groq_used  = (groq_max - groq_tok) if groq_tok is not None else None
    except Exception:
        ks_state = {}; mkt_open = False; sched_jobs = []; last_run = {}; groq_tok = None; groq_used = None; groq_max = 100_000

    lines.append("@@PART1@@")
    h1("SECTION 1: SYSTEM STATUS & RISK ENVIRONMENT")
    row("Report timestamp:", ts)
    row("Market status:", "OPEN (US Equities)" if mkt_open else "CLOSED (After Hours / Weekend)")
    row("Kill switch:", "TRIPPED \u2014 ALL TRADING HALTED" if ks_state.get("tripped") else "ARMED (not tripped \u2014 normal)")
    row("Daily drawdown:", f"{_pct(ks_state.get('drawdown_pct', 0), 3)} / {_pct(ks_state.get('threshold_pct', 5.0), 1)} threshold")
    row("Opening equity baseline:", _c(ks_state.get("opening_equity")))
    row("Pending liquidation:", "YES \u2014 deferred close queued for market open" if ks_state.get("pending_liquidation") else "NO")
    if groq_tok is not None:
        row("Groq token budget:", f"{groq_tok:,} remaining / {groq_max:,} daily ({groq_used:,} used)")
    else:
        row("Groq token budget:", "Unknown")

    last_regime = last_run.get("last_regime") or "Unknown"
    last_status = last_run.get("last_run_status") or "Unknown"
    last_run_ts = last_run.get("last_run_utc") or "Never"
    row("Last analysis cycle:", f"{last_run_ts} | status={last_status}")
    row("Current market regime:", last_regime)

    if sched_jobs:
        lines.append("")
        lines.append("  Scheduler (8 jobs):")
        for job in sched_jobs:
            lines.append(f"    \u2022 {job.get('name','?'):<45} next: {str(job.get('next_fire_utc','?'))[:19]}")

    _report_ks_state = ks_state

    try:
        acct      = get_account()
        positions = get_positions()
    except Exception:
        acct = {}; positions = []

    equity      = acct.get("equity", 0) or 0
    cash        = acct.get("cash", 0) or 0
    buying_pwr  = acct.get("buying_power", 0) or 0
    start_cap   = 100_000.0
    pnl_usd     = equity - start_cap
    pnl_pct     = (pnl_usd / start_cap) * 100

    h1("SECTION 2: ALPACA BOT \u2014 QUANTITATIVE EQUITY PLATFORM (US Equities)")
    h2("PORTFOLIO OVERVIEW")
    row("Capital pool:", "US Equity \u2014 Paper Trading via Alpaca")
    row("Starting capital:", _c(start_cap))
    row("Current equity:", _c(equity))
    row("Total P&L:", f"{_c(pnl_usd)} ({_pct(pnl_pct)})")
    row("Available cash:", _c(cash))
    row("Buying power:", _c(buying_pwr))
    row("Open positions:", str(len(positions)))

    h2("CURRENT OPEN POSITIONS (ALPACA)")
    if not positions:
        lines.append("  No open positions.")
    for p in positions:
        sym         = p.get("symbol", "?")
        qty         = p.get("qty", 0)
        entry       = p.get("avg_entry_price")
        current     = p.get("current_price")
        mval        = p.get("market_value")
        upl         = p.get("unrealized_pl")
        uplpc       = (p.get("unrealized_plpc") or 0) * 100
        ac          = p.get("asset_class", "unknown")
        conv        = p.get("conviction_score")
        kelly       = p.get("kelly_fraction")
        sl_pct      = p.get("stop_loss_pct")
        tp_pct      = p.get("take_profit_pct")
        sl_px       = p.get("stop_loss_price")
        tp_px       = p.get("take_profit_price")
        thesis      = p.get("original_thesis") or "N/A"
        is_vault    = sym in ("JEPQ",)

        vault_tag = " [PROFIT VAULT \u2014 protected from liquidation]" if is_vault else ""
        lines.append(f"\n  {sym}{vault_tag}")
        row("Qty:", f"{qty:.6f} shares" if qty else "N/A", indent=2)
        row("Avg entry price:", _c(entry), indent=2)
        row("Current price:", _c(current), indent=2)
        row("Market value:", _c(mval), indent=2)
        row("Unrealized P&L:", f"{_c(upl)} ({_pct(uplpc)})", indent=2)
        row("Asset class:", ac, indent=2)
        row("Conviction score:", f"{conv:.2f} / 1.0" if conv else "N/A", indent=2)
        row("Kelly fraction:", f"{(kelly or 0)*100:.2f}%" if kelly else "N/A", indent=2)
        if sl_pct:
            row("Stop loss:", f"{_pct(sl_pct)} from entry | price: {_c(sl_px)}", indent=2)
        else:
            row("Stop loss:", "N/A", indent=2)
        if tp_pct:
            row("Take profit:", f"{_pct(tp_pct)} from entry | price: {_c(tp_px)}", indent=2)
        else:
            row("Take profit:", "N/A", indent=2)
        row("Original thesis:", thesis[:120] if len(thesis) > 120 else thesis, indent=2)

    long_positions  = [p for p in positions if str(p.get("side", "long")).lower() != "short"]
    short_positions = [p for p in positions if str(p.get("side", "long")).lower() == "short"]
    bear_hedge_syms = {"SH", "PSQ", "SPXS", "SQQQ", "SRTY", "DOG"}

    h2("SHORT & BEAR-HEDGE POSITIONS (ALGO SHORT SCANNER)")
    if not short_positions:
        lines.append("  No direct short positions open.")
    else:
        total_short_exposure = sum(abs(p.get("market_value") or 0) for p in short_positions)
        total_short_pnl      = sum(p.get("unrealized_pl") or 0 for p in short_positions)
        short_exposure_pct   = (total_short_exposure / equity * 100) if equity > 0 else 0
        row("Open short positions:", str(len(short_positions)))
        row("Total short exposure:", f"{_c(total_short_exposure)} ({_pct(short_exposure_pct)} of equity)")
        row("Aggregate short P&L:", f"{_c(total_short_pnl)} (profit = positive when price falls)")
        lines.append("")
        lines.append(
            f"  {'TICKER':<8} {'QTY':>8} {'ENTRY':>10} {'CURRENT':>10} "
            f"{'MARKET VAL':>12} {'UNREAL P&L':>12}"
        )
        lines.append("  " + "-" * 66)
        for sp in short_positions:
            sym     = sp.get("symbol", "?")
            qty     = sp.get("qty", 0)
            entry   = sp.get("avg_entry_price") or 0
            curr    = sp.get("current_price") or 0
            mv      = sp.get("market_value") or 0
            upl     = sp.get("unrealized_pl") or 0
            lines.append(
                f"  {sym:<8} {qty:>8.2f} {_c(entry):>10} {_c(curr):>10} "
                f"{_c(mv):>12} {_c(upl):>12}"
            )
        lines.append("")

    bear_hedge_longs = [p for p in long_positions if p.get("symbol", "") in bear_hedge_syms]
    if bear_hedge_longs:
        total_bh_exposure = sum(abs(p.get("market_value") or 0) for p in bear_hedge_longs)
        total_bh_pnl      = sum(p.get("unrealized_pl") or 0 for p in bear_hedge_longs)
        bh_exposure_pct   = (total_bh_exposure / equity * 100) if equity > 0 else 0
        row("Bear-hedge ETF positions:", str(len(bear_hedge_longs)))
        row("Bear-hedge exposure:", f"{_c(total_bh_exposure)} ({_pct(bh_exposure_pct)} of equity)")
        row("Bear-hedge P&L:", _c(total_bh_pnl))
        lines.append("")
        lines.append(
            f"  {'TICKER':<8} {'QTY':>8} {'ENTRY':>10} {'CURRENT':>10} "
            f"{'MARKET VAL':>12} {'UNREAL P&L':>12} {'ENTRY_TIME'}"
        )
        lines.append("  " + "-" * 80)
        for bp in bear_hedge_longs:
            sym    = bp.get("symbol", "?")
            qty    = bp.get("qty", 0)
            entry  = bp.get("avg_entry_price") or 0
            curr   = bp.get("current_price") or 0
            mv     = bp.get("market_value") or 0
            upl    = bp.get("unrealized_pl") or 0
            et     = bp.get("entry_time") or "N/A"
            lines.append(
                f"  {sym:<8} {qty:>8.2f} {_c(entry):>10} {_c(curr):>10} "
                f"{_c(mv):>12} {_c(upl):>12} {str(et)[:19]}"
            )
        lines.append("")
    else:
        lines.append("  No bear-hedge ETF positions open.")

    h2("LATEST AI ALLOCATION DECISION (GROQ LLAMA 3.3 70B)")
    last_alloc = last_run.get("last_allocation") or []
    if not last_alloc:
        lines.append("  No allocation has been generated yet. Run an analysis cycle to populate.")
    else:
        lines.append(f"  Market Regime:  {last_regime}")
        lines.append(f"  Generated:      {last_run_ts}")
        lines.append("")
        for slot in last_alloc:
            slot_n  = slot.get("slot", "?")
            ticker  = slot.get("ticker", "?")
            ac      = slot.get("asset_class", "?")
            conv    = slot.get("conviction_score")
            kelly   = slot.get("kelly_fraction")
            sl      = slot.get("stop_loss_pct")
            tp      = slot.get("take_profit_pct")
            thesis  = slot.get("thesis", "N/A")
            lines.append(f"  Slot {slot_n} \u2014 {ticker} ({ac})")
            row("Conviction:", f"{conv:.2f} / 1.0" if conv else "N/A", indent=3)
            row("Kelly fraction:", f"{(kelly or 0)*100:.2f}%" if kelly else "N/A", indent=3)
            row("Stop loss:", _pct(sl) if sl else "N/A", indent=3)
            row("Take profit:", _pct(tp) if tp else "N/A", indent=3)
            words = thesis.split()
            thesis_line = "      "
            for w in words:
                if len(thesis_line) + len(w) + 1 > 80:
                    lines.append(f"    AI Thesis:    {thesis_line.strip()}")
                    thesis_line = "      " + w + " "
                else:
                    thesis_line += w + " "
            if thesis_line.strip():
                lines.append(f"    AI Thesis:    {thesis_line.strip()}")
            lines.append("")

    h2("ALPACA PERFORMANCE METRICS")
    try:
        perf_summary = get_performance_summary()
    except Exception:
        perf_summary = {"total_days": 0, "total_trades": 0, "latest_equity": equity, "total_return_pct": pnl_pct}

    risk_metrics: dict = {}
    try:
        import numpy as _np
        snapshots = get_performance_snapshots(limit=90)
        equities = [s.get("total_equity", 0) for s in snapshots if s.get("total_equity")]
        if len(equities) >= 2:
            returns = _np.diff(equities) / _np.array(equities[:-1])
            mean_r = float(_np.mean(returns))
            std_r  = float(_np.std(returns))
            rf     = 0.05 / 252
            min_e  = min(equities)
            max_e  = max(equities[:equities.index(min_e)+1]) if min_e in equities else equities[0]
            max_dd = round(((max_e - min_e) / max_e) * 100, 2) if max_e > 0 else 0
            ann_r  = mean_r * 252
            sharpe = float((mean_r - rf) / std_r * _np.sqrt(252)) if std_r > 0 else None
            neg_r  = returns[returns < 0]
            ds     = float(_np.std(neg_r)) if len(neg_r) > 0 else None
            sortino = float((mean_r - rf) / ds * _np.sqrt(252)) if ds and ds > 0 else None
            calmar  = round(ann_r / (max_dd / 100), 3) if max_dd > 0 else None
            risk_metrics = {
                "sharpe_ratio": round(sharpe, 3) if sharpe else None,
                "sortino_ratio": round(sortino, 3) if sortino else None,
                "max_drawdown_pct": max_dd,
                "calmar_ratio": calmar,
                "volatility_annual_pct": round(std_r * _np.sqrt(252) * 100, 2),
                "data_points": len(equities),
            }
        elif equities:
            risk_metrics = {"data_points": len(equities)}
    except Exception:
        risk_metrics = {}

    row("Trading days tracked:", str(perf_summary.get("total_days", "N/A")))
    row("Total closed trades:", str(perf_summary.get("total_trades", "N/A")))
    wr = perf_summary.get("avg_win_rate")
    row("Win rate:", f"{wr*100:.1f}%" if wr else "N/A")
    row("Best day:", _pct(perf_summary.get("best_day_pct", None), 3) if perf_summary.get("best_day_pct") else "N/A")
    row("Worst day:", _pct(perf_summary.get("worst_day_pct", None), 3) if perf_summary.get("worst_day_pct") else "N/A")
    row("Total return:", _pct(perf_summary.get("total_return_pct", None), 3))
    conv_avg = perf_summary.get("avg_conviction")
    row("Avg AI conviction:", f"{conv_avg:.4f}" if conv_avg else "N/A")

    h2("ALPACA RISK METRICS (requires 30+ days of equity snapshots)")
    sharpe  = risk_metrics.get("sharpe_ratio")
    sortino = risk_metrics.get("sortino_ratio")
    mdd     = risk_metrics.get("max_drawdown_pct")
    calmar  = risk_metrics.get("calmar_ratio")
    vol     = risk_metrics.get("volatility_annual_pct")
    dpts    = risk_metrics.get("data_points", 0)
    row("Data points (days):", str(dpts))
    row("Sharpe ratio:", f"{sharpe:.4f}" if sharpe is not None else f"N/A ({dpts} day(s) \u2014 need 30+)")
    row("Sortino ratio:", f"{sortino:.4f}" if sortino is not None else f"N/A ({dpts} day(s) \u2014 need 30+)")
    row("Max drawdown:", _pct(mdd) if mdd is not None else f"N/A ({dpts} day(s) \u2014 need 30+)")
    row("Calmar ratio:", f"{calmar:.4f}" if calmar is not None else "N/A")
    row("Annual volatility:", _pct(vol) if vol is not None else "N/A")

    h2("ALPACA TRADE HISTORY (sorted by PnL ascending \u2014 worst losses first)")
    try:
        _all_alpaca = get_all_trades()
        alpaca_trades = sorted(
            _all_alpaca,
            key=lambda t: float(t.get("pnl_usd") or t.get("pnl_dollar") or 0),
        )
    except Exception:
        alpaca_trades = []

    if not alpaca_trades:
        lines.append("  No Alpaca trades recorded yet.")
    else:
        lines.append(f"  Total Alpaca trades: {len(alpaca_trades)} (showing worst losses first)")
        lines.append(f"  {'#':<4} {'Date':<12} {'Symbol':<10} {'Status':<16} {'PnL%':>8} {'PnL$':>12}  Thesis / Exit Reason")
        lines.append("  " + "-" * 78)
        for i, t in enumerate(alpaca_trades, 1):
            sym     = str(t.get("ticker") or t.get("symbol") or "?")[:8]
            date    = str(t.get("date") or t.get("closed_at") or "?")[:10]
            status  = str(t.get("status") or "?")[:14]
            pnl_p   = t.get("pnl_percentage") or t.get("pnl_pct")
            pnl_d   = t.get("pnl_usd") or t.get("pnl_usd")
            pnl_p_s = _pct(pnl_p) if pnl_p is not None else "N/A"
            pnl_d_s = _c(pnl_d) if pnl_d is not None else "N/A"
            thesis  = str(t.get("original_thesis") or t.get("exit_reason") or "N/A")
            lines.append(f"  {i:<4} {date:<12} {sym:<10} {status:<16} {pnl_p_s:>8} {pnl_d_s:>12}  {thesis}")
            entry_px    = t.get("intended_price") or t.get("avg_entry_price")
            fill_px     = t.get("actual_fill_price")
            slippage    = t.get("slippage_pct")
            conv_score  = t.get("conviction_score")
            asset_cls   = t.get("asset_class", "")
            regime_tag  = t.get("regime_at_entry", "")
            detail = []
            if entry_px:   detail.append(f"entry={_c(entry_px)}")
            if fill_px:    detail.append(f"fill={_c(fill_px)}")
            if slippage:   detail.append(f"slippage={_pct(slippage, 3)}")
            if conv_score: detail.append(f"conviction={conv_score:.2f}")
            if asset_cls:  detail.append(f"class={asset_cls}")
            if regime_tag: detail.append(f"regime={regime_tag}")
            if detail:
                lines.append(f"       \u2514\u2500 {' | '.join(detail)}")

    h2("ATTRIBUTION ANALYSIS (What worked and what didn't)")
    try:
        attr = _attr()
        by_class = attr.get("asset_class_attribution", {})
        by_conv  = attr.get("conviction_attribution", {})
        by_regime = attr.get("regime_attribution", {})
    except Exception:
        by_class = {}; by_conv = {}; by_regime = {}

    if by_class:
        lines.append("  By Asset Class:")
        lines.append(f"    {'Asset Class':<14} {'Trades':>7} {'Win Rate':>10} {'Total PnL':>11} {'Avg PnL':>9}")
        lines.append("    " + "-" * 55)
        for cls, v in sorted(by_class.items(), key=lambda x: x[1].get("total_pnl_pct", 0)):
            lines.append(f"    {cls:<14} {v.get('count',0):>7} {_pct(v.get('win_rate',0)):>10} {_pct(v.get('total_pnl_pct')):>11} {_pct(v.get('avg_pnl_pct')):>9}")

    if by_conv:
        lines.append("")
        lines.append("  By AI Conviction Level:")
        lines.append(f"    {'Level':<10} {'Trades':>7} {'Win Rate':>10} {'Total PnL':>11} {'Avg PnL':>9}")
        lines.append("    " + "-" * 51)
        for lvl, v in sorted(by_conv.items()):
            lines.append(f"    {lvl:<10} {v.get('count',0):>7} {_pct(v.get('win_rate',0)):>10} {_pct(v.get('total_pnl_pct')):>11} {_pct(v.get('avg_pnl_pct')):>9}")

    if by_regime:
        lines.append("")
        lines.append("  By Market Regime:")
        for regime, v in sorted(by_regime.items()):
            lines.append(f"    {regime:<12} {v.get('count',0)} trades | {_pct(v.get('win_rate',0))} win | avg {_pct(v.get('avg_pnl_pct'))}")

    lines += _rs.section_trade_mechanics_oracle()
    lines += _rs.section_oracle_regime_transparency()
    lines += _rs.section_daily_equity_history("Oracle #1", source="oracle")
    lines += _rs.section_regime_performance("Oracle #1", source="oracle")
    lines += _rs.section_consecutive_streaks("Oracle #1", alpaca_trades)
    lines += _rs.section_rolling_metrics("Oracle #1", alpaca_trades, equity_source="oracle")

    lines.append("@@PART2@@")
    h1("SECTION 3: KRAKEN FLEET \u2014 ALL 3 CRYPTO BOTS (24/7)")

    import psycopg2 as _pg2rpt, psycopg2.extras as _pg2xrpt, os as _osrpt
    _dburlrpt = _osrpt.environ.get("DATABASE_URL")

    _all_kraken_equity = 0.0
    _all_kraken_starting = 0.0
    _all_kraken_trades_all: list = []
    _kraken_per_bot_equity: dict = {}

    for _kbid, _kprof in KRAKEN_BOT_PROFILES.items():
        _kdbid = _kprof["db_id"]
        _kname = _kprof["display_name"]
        _kstrat = _kprof["strategy_label"]

        h2(f"BOT #{_kdbid+1}: {_kname.upper()} (bot_id={_kbid}, strategy={_kstrat})")

        _ks: dict = {}
        _pf: dict = {}
        _pf_trades: list = []

        if _dburlrpt:
            try:
                _rptconn = _pg2rpt.connect(_dburlrpt)
                try:
                    with _rptconn.cursor(cursor_factory=_pg2xrpt.RealDictCursor) as _rhc:
                        _rhc.execute("SELECT * FROM kraken_heartbeat WHERE id = %s", (_kdbid,))
                        _rhr = _rhc.fetchone()
                        if _rhr:
                            _ks = {
                                "status":         _rhr["status"],
                                "equity_usd":     _rhr["equity_usd"],
                                "cycle_count":    _rhr["cycle_count"],
                                "bot_paused":     _rhr["bot_paused"],
                                "paper_trading":  _rhr["paper_trading"],
                                "last_updated":   _rhr["last_updated"].isoformat() if _rhr["last_updated"] else "N/A",
                                "position_count": _rhr["position_count"],
                            }
                    with _rptconn.cursor() as _rpc:
                        _rpc.execute(
                            "SELECT starting_balance_usd, cash_usd, positions FROM kraken_portfolio WHERE id = %s",
                            (_kdbid,)
                        )
                        _rpr = _rpc.fetchone()
                        if _rpr:
                            _pos_raw = _rpr[2]
                            if isinstance(_pos_raw, str):
                                _pos_raw = _json.loads(_pos_raw)
                            _db_pos_list = []
                            if isinstance(_pos_raw, dict):
                                for _s, _pd in _pos_raw.items():
                                    _ep = dict(_pd)
                                    _ep.setdefault("symbol", _s)
                                    _db_pos_list.append(_ep)
                            elif isinstance(_pos_raw, list):
                                _db_pos_list = _pos_raw
                            _pf = {
                                "starting_balance_usd": float(_rpr[0] or 100_000),
                                "cash_usd":             float(_rpr[1] or 0),
                                "open_positions": _db_pos_list,
                            }
                    with _rptconn.cursor(cursor_factory=_pg2xrpt.RealDictCursor) as _rtc:
                        _rtc.execute(
                            """
                            SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                                   fees_usd, reason, closed_at, paper, order_id
                            FROM   kraken_trades WHERE bot_id = %s ORDER BY closed_at ASC
                            """,
                            (_kbid,)
                        )
                        for _rtr in _rtc.fetchall():
                            _rtd = dict(_rtr)
                            if _rtd.get("closed_at"):
                                _rtd["closed_at"] = _rtd["closed_at"].isoformat()
                            _pf_trades.append(_rtd)
                finally:
                    _rptconn.close()
            except Exception as _rpte:
                logger.warning(f"[report] Kraken DB read failed for {_kbid}: {_rpte}")

        _live_rpt: dict = {}
        try:
            _lsf_rpt = _Path(f"../kraken-bot/{_kbid}_live_state.json")
            if _lsf_rpt.exists():
                _live_rpt = _json.loads(_lsf_rpt.read_text())
            elif _kbid == "davy-jones":
                _lsf_rpt2 = _Path("../kraken-bot/live_state.json")
                if _lsf_rpt2.exists():
                    _live_rpt = _json.loads(_lsf_rpt2.read_text())
        except Exception:
            pass

        k_status   = _ks.get("status", "not_started")
        k_equity   = _ks.get("equity_usd", 0) or 0
        k_cycles   = _ks.get("cycle_count", 0) or 0
        k_paused   = _ks.get("bot_paused", False)
        k_paper    = _ks.get("paper_trading", True)
        k_updated  = _ks.get("last_updated", "N/A")
        _live_rpt_positions = _live_rpt.get("open_positions", [])
        k_positions = _live_rpt_positions if _live_rpt_positions else (_pf.get("open_positions", []) or [])
        k_start_bal = _pf.get("starting_balance_usd", 100_000)
        k_cash_usd  = _pf.get("cash_usd", 0)
        k_deployed  = k_equity - k_cash_usd if k_equity > k_cash_usd else 0.0
        k_deploy_pct = round((k_deployed / k_equity) * 100, 1) if k_equity > 0 else 0.0
        k_pnl_usd   = k_equity - k_start_bal
        _k_has_data  = bool(_ks)

        if _k_has_data:
            _all_kraken_equity += k_equity
            _all_kraken_starting += k_start_bal
        else:
            _all_kraken_starting += 100_000
            k_equity = 0
        _all_kraken_trades_all.extend(_pf_trades)
        _kraken_per_bot_equity[_kbid] = k_equity

        if not _k_has_data:
            row("Bot status:", "DB UNAVAILABLE \u2014 no heartbeat data")
        else:
            row("Bot status:", f"{'PAUSED' if k_paused else 'RUNNING'} ({k_status})")
        row("Paper trading:", "YES" if k_paper else "NO \u2014 LIVE FUNDS")
        row("Strategy:", _kstrat)
        row("Cycles completed:", str(k_cycles))
        row("Last updated:", str(k_updated)[:19])
        row("Starting capital:", _c(k_start_bal))
        row("Current equity:", _c(k_equity))
        row("Total P&L:", f"{_c(k_pnl_usd)} ({_pct((k_pnl_usd/k_start_bal)*100 if k_start_bal else 0)})")
        row("Deployed capital:", f"{_c(k_deployed)} ({_pct(k_deploy_pct, 1)} of equity)")
        row("Open positions:", str(len(k_positions)))

        _pf_wins = [t for t in _pf_trades if (t.get("pnl_usd", 0) or 0) >= 0]
        if _pf_trades:
            ps_trades = len(_pf_trades)
            ps_wins   = len(_pf_wins)
            ps_losses = ps_trades - ps_wins
            ps_pnl_u  = round(sum(t.get("pnl_usd", 0) or 0 for t in _pf_trades), 2)
            ps_wr     = (ps_wins / ps_trades * 100) if ps_trades else 0
            row("All-time trades:", str(ps_trades))
            row("Win / Loss:", f"{ps_wins}W / {ps_losses}L ({_pct(ps_wr, 1)} win rate)")
            row("All-time P&L:", _c(ps_pnl_u))

        if k_positions:
            lines.append("")
            lines.append(f"    Open Positions:")
            for pos in k_positions:
                sym     = pos.get("symbol", "?")
                side    = str(pos.get("side", "?")).upper()
                entry   = pos.get("entry_price")
                curr    = pos.get("current_price")
                upl_usd = pos.get("unrealized_pnl_usd", 0)
                upl_pct = pos.get("unrealized_pnl_pct", 0)
                lines.append(f"      {sym:<12} {side:<6} entry={_c(entry, 4)}  now={_c(curr, 4)}  P&L={_c(upl_usd)} ({_pct(upl_pct)})")

        if _pf_trades:
            lines.append("")
            lines.append(f"    Full Trade History ({len(_pf_trades)} trades):")
            lines.append(f"      {'#':<4} {'Date':<16} {'Symbol':<12} {'Side':<5} {'PnL%':>7} {'PnL$':>10}  {'Entry':>10} {'Exit':>10} {'Fees':>8}  Reason")
            lines.append("      " + "-" * 110)
            for _ti, t in enumerate(_pf_trades, 1):
                sym    = str(t.get("symbol", "?"))[:11]
                dt     = str(t.get("closed_at") or "?")[:16]
                side   = str(t.get("side", "?")).upper()[:5]
                ppct   = t.get("pnl_pct") or 0
                pusd   = t.get("pnl_usd") or 0
                entry  = t.get("entry_price") or 0
                exit_p = t.get("exit_price") or 0
                fees   = t.get("fees_usd") or 0
                reason = str(t.get("reason") or "?")
                lines.append(f"      {_ti:<4} {dt:<16} {sym:<12} {side:<5} {_pct(ppct):>7} {_c(pusd):>10}  {_c(entry, 4):>10} {_c(exit_p, 4):>10} {_c(fees):>8}  {reason}")

    h2("KRAKEN FLEET TOTALS")
    _k_fleet_pnl = _all_kraken_equity - _all_kraken_starting
    row("Fleet starting capital:", _c(_all_kraken_starting))
    row("Fleet current equity:", _c(_all_kraken_equity))
    row("Fleet P&L:", f"{_c(_k_fleet_pnl)} ({_pct((_k_fleet_pnl/_all_kraken_starting)*100 if _all_kraken_starting else 0)})")
    row("Fleet total trades:", str(len(_all_kraken_trades_all)))

    h2("KRAKEN PER-SYMBOL PERFORMANCE (all bots combined)")
    if _all_kraken_trades_all:
        sym_stats: dict = {}
        for t in _all_kraken_trades_all:
            s = t.get("symbol", "UNKNOWN")
            if s not in sym_stats:
                sym_stats[s] = {"trades": 0, "wins": 0, "pnl_pct": 0.0, "pnl_usd": 0.0}
            sym_stats[s]["trades"] += 1
            ppct = t.get("pnl_pct", 0) or 0
            pusd = t.get("pnl_usd", 0) or 0
            sym_stats[s]["pnl_pct"] += ppct
            sym_stats[s]["pnl_usd"] += pusd
            if pusd >= 0:
                sym_stats[s]["wins"] += 1
        lines.append(f"  {'Symbol':<12} {'Trades':>7} {'Win Rate':>10} {'Total PnL%':>12} {'Total PnL$':>12} {'Avg PnL%':>9}")
        lines.append("  " + "-" * 68)
        for sym, v in sorted(sym_stats.items(), key=lambda x: x[1]["pnl_usd"]):
            n   = v["trades"]
            wr  = (v["wins"] / n * 100) if n else 0
            avg = (v["pnl_pct"] / n) if n else 0
            lines.append(f"  {sym:<12} {n:>7} {_pct(wr, 1):>10} {_pct(v['pnl_pct']):>12} {_c(v['pnl_usd']):>12} {_pct(avg):>9}")
    else:
        lines.append("  No trade data in kraken_trades DB yet.")

    lines.append("@@KRAKEN_SUPP@@")
    lines += _rs.section_trade_mechanics_kraken()
    lines += _rs.section_vpin_shadow_log()
    lines += _rs.section_vpin_calibration()
    lines += _rs.section_daily_equity_history("Kraken Fleet", source="kraken")
    lines += _rs.section_regime_performance("Kraken Fleet", source="kraken")
    for _streak_bid, _streak_prof in KRAKEN_BOT_PROFILES.items():
        _streak_name = _streak_prof["display_name"]
        lines += _rs.section_consecutive_streaks_kraken(_streak_name, _streak_bid)
    lines += _rs.section_rolling_metrics("Kraken Fleet", _all_kraken_trades_all, equity_source="kraken")

    lines.append("@@PART3@@")
    h1("SECTION 4: APEX PREDATOR \u2014 OPTIONS ENGINE (Bot #5)")

    try:
        _opts_state = _opts.get_full_state()
        _opts_positions = _opts._get_positions()
    except Exception:
        _opts_state = {}
        _opts_positions = []

    _opts_equity   = _opts_state.get("paper_equity", _opts_state.get("total_equity", 100_000))
    _opts_deployed = _opts_state.get("deployed_capital", 0)
    _opts_unrealized = _opts_state.get("unrealized_pnl", 0)
    _opts_trades   = _opts_state.get("total_trades", 0)
    _opts_wins     = _opts_state.get("total_wins", 0)
    _opts_paused   = _opts_state.get("paused", False)
    _opts_paper    = _opts_state.get("paper_mode", True)
    _opts_start    = 100_000.0
    _opts_pnl      = _opts_equity - _opts_start

    h2("OVERVIEW")
    row("Capital pool:", "Options \u2014 Paper Trading (Volatility Squeeze Strategy)")
    row("Bot status:", "PAUSED" if _opts_paused else "RUNNING")
    row("Paper trading:", "YES" if _opts_paper else "NO \u2014 LIVE FUNDS")
    row("Starting capital:", _c(_opts_start))
    row("Current equity:", _c(_opts_equity))
    row("Total P&L:", f"{_c(_opts_pnl)} ({_pct((_opts_pnl/_opts_start)*100)})")
    row("Deployed capital:", _c(_opts_deployed))
    row("Unrealized P&L:", _c(_opts_unrealized))
    row("Total trades:", str(_opts_trades))
    row("Wins:", str(_opts_wins))
    _opts_wr = (_opts_wins / _opts_trades * 100) if _opts_trades > 0 else 0
    row("Win rate:", _pct(_opts_wr, 1))

    h2("CURRENT OPTIONS POSITIONS")
    if not _opts_positions:
        lines.append("  No open options positions.")
    else:
        for op in _opts_positions:
            sym      = op.get("symbol", "?")
            strategy = op.get("strategy", "?")
            status   = op.get("status", "?")
            cost     = op.get("total_cost", 0)
            cur_val  = op.get("current_value", 0)
            pnl_op   = cur_val - cost
            entry_t  = str(op.get("entry_time") or op.get("opened_at") or "?")[:16]
            lines.append(f"\n  {sym} \u2014 {strategy}")
            row("Status:", status, indent=2)
            row("Total cost:", _c(cost), indent=2)
            row("Current value:", _c(cur_val), indent=2)
            row("Unrealized P&L:", _c(pnl_op), indent=2)
            row("Entry time:", entry_t, indent=2)
            legs = op.get("legs", [])
            if legs:
                for leg in legs:
                    leg_type = leg.get("type", "?")
                    strike   = leg.get("strike", "?")
                    exp      = str(leg.get("expiration", "?"))[:10]
                    qty_l    = leg.get("quantity", 0)
                    lines.append(f"      Leg: {leg_type} strike={strike} exp={exp} qty={qty_l}")

    h2("OPTIONS STRATEGY PARAMETERS")
    lines += [
        "  Strategy:          Volatility Squeeze \u2192 Long Straddle (100% quant, LLM-free)",
        "  Scan schedule:     Daily at 3:30 PM ET (Mon\u2013Fri)",
        "  Capital fence:     20% of equity max deployed at any time",
        "  Entry:             Bollinger Band squeeze + low IV rank \u2192 buy ATM straddle",
        "  Exit:              Profit target or time decay threshold",
        "  Paper mode:        Simulated fills with real option chain data",
    ]

    lines += _rs.section_trade_mechanics_apex()
    lines += _rs.section_apex_scan_log()

    _opts_all_trades: list = []
    _opts_trades_db = _Path(__file__).parent.parent / "_options_state" / "trades.db"
    if _opts_trades_db.exists():
        try:
            import sqlite3 as _sq3
            _sq_conn = _sq3.connect(str(_opts_trades_db))
            _sq_conn.row_factory = _sq3.Row
            _sq_cur = _sq_conn.execute("SELECT * FROM options_trades ORDER BY closed_at ASC")
            _opts_all_trades = [dict(r) for r in _sq_cur.fetchall()]
            _sq_conn.close()
        except Exception:
            pass

    lines += _rs.section_daily_equity_history("Apex Predator #5", source="options")
    lines += _rs.section_consecutive_streaks("Apex Predator #5", _opts_all_trades)
    lines += _rs.section_rolling_metrics("Apex Predator #5", _opts_all_trades, equity_source="options")

    h1("SECTION 5: THE NAVIGATOR \u2014 FOREX SWING ENGINE (Bot #6)")

    _fx_engine = _get_forex_engine()
    _fx_db = _get_forex_db()

    _fx_state: dict = {}
    _fx_positions: list = []
    _fx_trades: list = []
    try:
        if _fx_engine:
            _fx_state = _fx_engine.get_state()
            _fx_positions = _fx_engine.get_positions()
    except Exception:
        pass
    try:
        if _fx_db:
            _fx_trades = _fx_db.load_recent_trades(limit=10_000)
    except Exception:
        pass

    _fx_equity   = _fx_state.get("total_equity", _fx_state.get("paper_equity", 100_000))
    _fx_cycles   = _fx_state.get("cycle_count", 0)
    _fx_paused   = _fx_state.get("paused", False)
    _fx_usd_bias = _fx_state.get("usd_bias", "NEUTRAL")
    _fx_blackout = _fx_state.get("news_blackout", False)
    _fx_trades_n = _fx_state.get("total_trades", 0)
    _fx_wins     = _fx_state.get("total_wins", 0)
    _fx_pnl_all  = _fx_state.get("total_pnl", 0)
    _fx_hwm      = _fx_state.get("hwm_usd", 100_000)
    _fx_vault    = _fx_state.get("vault_total_usd", 0)
    _fx_start    = 100_000.0
    _fx_pnl_from_start = _fx_equity - _fx_start

    h2("OVERVIEW")
    row("Capital pool:", "Forex \u2014 Paper Trading (H4 Swing Strategy)")
    row("Bot status:", "PAUSED" if _fx_paused else ("RUNNING" if _fx_state.get("status") == "running" else _fx_state.get("status", "not_started")))
    row("USD bias (Groq macro):", _fx_usd_bias)
    row("News blackout:", "YES \u2014 trading paused" if _fx_blackout else "NO")
    row("Cycles completed:", str(_fx_cycles))
    row("Starting capital:", _c(_fx_start))
    row("Current equity:", _c(_fx_equity))
    row("Total P&L:", f"{_c(_fx_pnl_from_start)} ({_pct((_fx_pnl_from_start/_fx_start)*100)})")
    row("High water mark:", _c(_fx_hwm))
    row("Vault (profit lock):", _c(_fx_vault))
    row("Total trades:", str(_fx_trades_n))
    row("Wins:", str(_fx_wins))
    _fx_wr = (_fx_wins / _fx_trades_n * 100) if _fx_trades_n > 0 else 0
    row("Win rate:", _pct(_fx_wr, 1))
    row("Open positions:", str(len(_fx_positions)))

    h2("CURRENT FOREX POSITIONS")
    if not _fx_positions:
        lines.append("  No open forex positions.")
    else:
        for fp in _fx_positions:
            pair    = fp.get("pair", "?")
            dirn    = fp.get("direction", "?").upper()
            entry   = fp.get("entry_price", 0)
            curr    = fp.get("current_price", 0)
            pnl_p   = fp.get("unrealized_pnl_pips", fp.get("pnl_pips", 0))
            pnl_u   = fp.get("unrealized_pnl_usd", fp.get("pnl_usd", 0))
            sl      = fp.get("sl_price", fp.get("stop_loss", 0))
            tp      = fp.get("tp_price", fp.get("take_profit", 0))
            units   = fp.get("units", 0)
            lines.append(f"\n  {pair}  {dirn}")
            row("Units:", f"{units:,.0f}", indent=2)
            row("Entry:", f"{entry:.5f}", indent=2)
            row("Current:", f"{curr:.5f}", indent=2)
            row("P&L:", f"{_c(pnl_u)} ({pnl_p:+.1f} pips)", indent=2)
            row("Stop loss:", f"{sl:.5f}", indent=2)
            row("Take profit:", f"{tp:.5f}", indent=2)

    h2("FOREX TRADE HISTORY (all trades)")
    if not _fx_trades:
        lines.append("  No forex trade history yet.")
    else:
        lines.append(f"  Total recorded: {len(_fx_trades)}")
        lines.append(f"  {'#':<4} {'Date':<18} {'Pair':<12} {'Dir':<6} {'Entry':>10} {'Exit':>10} {'PnL$':>10} {'Pips':>7}  Reason")
        lines.append("  " + "-" * 85)
        for i, ft in enumerate(_fx_trades, 1):
            pair   = str(ft.get("pair", "?"))[:11]
            dt     = str(ft.get("closed_at") or ft.get("exit_time") or "?")[:16]
            dirn   = str(ft.get("direction", "?")).upper()[:5]
            entry  = ft.get("entry_price") or 0
            exit_p = ft.get("exit_price") or 0
            pusd   = ft.get("pnl_usd") or 0
            pips   = ft.get("pnl_pips") or 0
            reason = str(ft.get("exit_reason") or ft.get("reason") or "?")
            try:
                lines.append(f"  {i:<4} {dt:<18} {pair:<12} {dirn:<6} {float(entry):>10.5f} {float(exit_p):>10.5f} {_c(pusd):>10} {float(pips):>+7.1f}  {reason}")
            except (TypeError, ValueError):
                lines.append(f"  {i:<4} {dt:<18} {pair:<12} {dirn:<6} {'N/A':>10} {'N/A':>10} {_c(pusd):>10} {'N/A':>7}  {reason}")

    h2("FOREX STRATEGY PARAMETERS")
    lines += [
        "  Strategy:          H4 swing \u2014 5 major pairs (EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD)",
        "  AI engine:         Groq Llama 3.3 70B \u2014 USD directional bias only (BULLISH/BEARISH/NEUTRAL)",
        "  Cycle frequency:   Every 4 hours (24/7)",
        "  Position sizing:   3% risk per trade, ATR-based stop loss",
        "  Max positions:     5 simultaneous",
        "  Entry:             EMA crossover + RSI + MACD confluence, filtered by USD bias",
        "  Stop loss:         1.5\u00d7 ATR from entry",
        "  Take profit:       2.0\u00d7 risk (R:R = 1:2)",
        "  Profit vault:      10% of realized profits locked in vault",
        "  News blackout:     Groq detects high-impact events \u2192 pauses trading",
    ]

    lines += _rs.section_trade_mechanics_navigator()
    lines += _rs.section_navigator_pair_breakdown(_fx_trades)
    lines += _rs.section_daily_equity_history("Navigator #6", source="forex")
    lines += _rs.section_consecutive_streaks("Navigator #6", _fx_trades)
    lines += _rs.section_rolling_metrics("Navigator #6", _fx_trades, equity_source="forex")

    lines.append("@@SEC6@@")
    h1("SECTION 6: COMBINED FLEET PORTFOLIO \u2014 ALL 6 BOTS")

    grand_start = 600_000.0
    grand_now   = equity + _all_kraken_equity + _opts_equity + _fx_equity
    grand_pnl   = grand_now - grand_start
    grand_pct   = (grand_pnl / grand_start) * 100 if grand_start else 0

    row("Total starting capital:", f"{_c(grand_start)} across 4 capital pools, 6 bots")
    lines.append("")
    row("Bot #1 Oracle (Alpaca):", f"{_c(equity)}  ({_pct((equity - 100_000) / 100_000 * 100)} from $100k)")
    _k_fleet_pnl_s = _all_kraken_equity - _all_kraken_starting
    row("Bots #2-4 Kraken Fleet:", f"{_c(_all_kraken_equity)}  ({_pct((_k_fleet_pnl_s/_all_kraken_starting)*100 if _all_kraken_starting else 0)} from {_c(_all_kraken_starting)})")
    for _kbid2, _kprof2 in KRAKEN_BOT_PROFILES.items():
        _kdbid2 = _kprof2["db_id"]
        _keq2 = _kraken_per_bot_equity.get(_kbid2, 0)
        row(f"  - {_kprof2['display_name']} (#{_kdbid2+1}):", _c(_keq2))
    row("Bot #5 Apex Predator:", f"{_c(_opts_equity)}  ({_pct((_opts_pnl/_opts_start)*100)} from $100k)")
    row("Bot #6 Navigator:", f"{_c(_fx_equity)}  ({_pct((_fx_pnl_from_start/_fx_start)*100)} from $100k)")
    lines.append("")
    row("GRAND TOTAL EQUITY:", _c(grand_now))
    row("COMBINED P&L:", f"{_c(grand_pnl)} ({_pct(grand_pct)})")

    lines.append("")
    lines.append("  CAPITAL POOLS:")
    lines.append("    Pool 1: Alpaca US Equities     $100k  (Bot #1 Oracle)")
    lines.append("    Pool 2: Kraken Crypto Fleet    $300k  (Bots #2 Davy Jones, #3 Blackbeard, #4 Calypso)")
    lines.append("    Pool 3: Options (Apex Predator) $100k (Bot #5)")
    lines.append("    Pool 4: Forex (Navigator)       $100k (Bot #6)")
    lines.append("  Each pool is independent \u2014 different asset classes, strategies, and risk profiles.")

    lines.append("@@SEC1A@@")
    lines += _rs.section_fleet_risk_dashboard(
        equity=equity,
        kraken_equity=_all_kraken_equity,
        kraken_starting=_all_kraken_starting,
        opts_equity=_opts_equity,
        fx_equity=_fx_equity,
        positions=positions,
        kraken_per_bot_equity=_kraken_per_bot_equity,
        fx_positions=_fx_positions,
        opts_positions=_opts_positions,
        ks_state=_report_ks_state,
    )

    lines.append("@@CORR@@")
    lines += _rs.section_cross_bot_correlation()

    lines.append("@@EXEC@@")
    lines += _rs.section_slippage_execution_quality(
        alpaca_trades=alpaca_trades,
        kraken_trades=_all_kraken_trades_all,
        fx_trades=_fx_trades,
    )

    lines.append("@@SEC7@@")
    h1("SECTION 7: AI LEARNING JOURNAL (Persistent insights across cycles)")
    try:
        lj_entries = _lj(limit=50)
    except Exception:
        lj_entries = []

    if not lj_entries:
        lines.append("  No learning journal entries yet.")
    else:
        lines.append(f"  {len(lj_entries)} insights stored:")
        lines.append("")
        for e in lj_entries:
            insight   = e.get("insight_text", "?")
            regime    = e.get("regime", "?")
            cat       = e.get("category", "?")
            conf      = e.get("confidence_score", 0)
            confirmed = e.get("confirmed_count", 1)
            first_s   = str(e.get("first_seen", "?"))[:10]
            lines.append(f"  [{regime.upper()} / {cat}]  confidence={conf:.2f}  confirmed\u00d7{confirmed}  first_seen={first_s}")
            lines.append(f"    \"{insight}\"")
            lines.append("")

    lines += _rs.section_learning_journal_metadata(lj_entries)

    lines.append("@@SEC_AI@@")
    h1("SECTION 8: AI IMPACT TIMELINE \u2014 INTERVENTIONS & PERFORMANCE EFFECT")
    try:
        from routes.ai_impact import _get_conn as _ai_conn
        _aic = _ai_conn()
        try:
            with _aic.cursor() as _aicur:
                _aicur.execute("""
                    SELECT id, ts, source, overall_verdict, critique_summary,
                           vetoed_tickers, param_changes, equity_at_time
                    FROM ai_interventions
                    ORDER BY ts DESC
                    LIMIT 50
                """)
                _ai_cols = [d[0] for d in _aicur.description]
                _ai_rows = [dict(zip(_ai_cols, r)) for r in _aicur.fetchall()]
        finally:
            _aic.close()

        if not _ai_rows:
            lines.append("  No AI interventions recorded yet.")
        else:
            lines.append(f"  Total interventions in DB: {len(_ai_rows)} (showing most recent 50)")
            lines.append("")

            helped = 0
            hurt = 0
            neutral = 0

            for iv in _ai_rows:
                iv_ts = iv["ts"].strftime("%Y-%m-%d %H:%M UTC") if iv["ts"] else "Unknown"
                source = iv.get("source") or "unknown"
                verdict = iv.get("overall_verdict") or "N/A"
                summary = iv.get("critique_summary") or "N/A"
                eq = iv.get("equity_at_time")
                vetoed = iv.get("vetoed_tickers")
                params = iv.get("param_changes")

                if isinstance(vetoed, str):
                    try:
                        import json as _jj
                        vetoed = _jj.loads(vetoed)
                    except Exception:
                        pass
                if isinstance(params, str):
                    try:
                        import json as _jj
                        params = _jj.loads(params)
                    except Exception:
                        pass

                lines.append(f"  [{iv_ts}] Source: {source} | Verdict: {verdict}")
                if eq is not None:
                    lines.append(f"    Equity at time: ${float(eq):,.2f}")
                if summary and summary != "N/A":
                    summary_short = summary[:300] + ("..." if len(summary) > 300 else "")
                    lines.append(f"    Summary: {summary_short}")
                if vetoed and isinstance(vetoed, list) and len(vetoed) > 0:
                    lines.append(f"    Vetoed tickers: {', '.join(str(v) for v in vetoed)}")
                if params and isinstance(params, dict) and len(params) > 0:
                    param_str = ", ".join(f"{k}={v}" for k, v in list(params.items())[:10])
                    lines.append(f"    Param changes: {param_str}")
                lines.append("")

            for iv in _ai_rows:
                v = iv.get("overall_verdict", "")
                if v and "helped" in str(v).lower():
                    helped += 1
                elif v and ("hurt" in str(v).lower() or "negative" in str(v).lower()):
                    hurt += 1
                else:
                    neutral += 1

            h2("AI IMPACT SUMMARY")
            row("Total interventions:", str(len(_ai_rows)))
            row("Helped:", str(helped))
            row("Hurt:", str(hurt))
            row("Neutral/Unknown:", str(neutral))
    except Exception as _ai_exc:
        lines.append(f"  [AI Impact Timeline unavailable: {_ai_exc}]")

    lines.append("@@SEC9@@")
    h1("SECTION 9: STRATEGY PARAMETERS \u2014 ALL 6 BOTS (for LLM context)")

    h2("BOT #1: ORACLE (ALPACA) \u2014 HOW IT WORKS")
    lines += [
        "  AI Engine:         Groq Llama 3.3 70B (100,000 tokens/day budget)",
        "  Execution:         Alpaca paper trading (simulated US equities)",
        "  Cycle frequency:   Every 15 minutes during market hours",
        "                     24/7 crypto-only cycle for crypto ETFs",
        "  Market regimes:    Bear | Bull | Neutral | Risk-Off",
        "                     Regime changes the entire allocation strategy",
        "  Position sizing:   Kelly Criterion \u00d7 conviction score (0.0\u20131.0)",
        "                     Max 15% per position (except SGOV)",
        "  Risk controls:",
        "    - Kill switch:   Trips at 5% daily drawdown \u2014 liquidates all",
        "    - Stop losses:   Per-trade, set by AI in allocation decision",
        "    - Take profits:  Per-trade, set by AI in allocation decision",
        "    - Ratchet stops: Trailing stop that locks in gains",
        "  Special positions:",
        "    - SGOV:          AI cash-equivalent \u2014 absorbs overflow when all",
        "                     normal slots are capped. Exempt from 15% cap.",
        "    - JEPQ:          Profit vault. 20% of every profit event swept here",
        "                     as a DRIP position. Protected from all liquidations.",
        "  Auditing:          Gemini self-critic runs daily pre-market,",
        "                     HITL auditor agent runs post-close.",
        "  Learning:          AI insights persist in a learning journal and are",
        "                     injected as context into future allocation calls.",
    ]

    h2("BOTS #2-4: KRAKEN FLEET \u2014 HOW THEY WORK")
    lines += [
        "  Bots:              #2 Davy Jones (Conservative), #3 Blackbeard (Aggressive), #4 Calypso (Most Aggressive)",
        "  Execution:         Kraken exchange (paper trading simulation, $100k each)",
        "  Strategy:          Mean reversion + momentum with VPIN microstructure filter",
        "  Pairs:             35+ crypto pairs (BTC, ETH, XRP, SOL, BNB, ADA, DOT, AVAX, etc.)",
        "  Position sizing:   10-15% of equity per position (varies by bot aggression)",
        "  Max positions:     10 simultaneous per bot",
        "  VPIN filter:       Volume-synchronized Probability of Informed Trading.",
        "                     VPIN > 0.65-0.75 blocks entries (varies by bot)",
        "  Stop loss:         Trailing \u2014 adapts to best price seen",
        "  Take profit:       Fixed target from entry",
        "  Circuit breaker:   Pauses bot after N consecutive losses",
        "  Cycle:             Runs 24/7 every 60s (crypto never closes)",
        "  Sides:             Both LONG and SHORT allowed",
    ]

    h2("BOT #5: APEX PREDATOR \u2014 HOW IT WORKS")
    lines += [
        "  Strategy:          Volatility Squeeze \u2192 Long Straddle (100% quant, LLM-free)",
        "  Execution:         Paper trading with real options chain data",
        "  Scan schedule:     Daily at 3:30 PM ET (Mon\u2013Fri)",
        "  Capital fence:     20% of equity max deployed",
        "  Entry:             Bollinger Band squeeze + low IV rank \u2192 ATM straddle",
        "  Exit:              Profit target or time decay threshold",
    ]

    h2("BOT #6: THE NAVIGATOR \u2014 HOW IT WORKS")
    lines += [
        "  Strategy:          H4 swing \u2014 5 major forex pairs",
        "  Pairs:             EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD",
        "  AI engine:         Groq Llama 3.3 70B \u2014 USD directional bias only",
        "  Cycle frequency:   Every 4 hours (24/7)",
        "  Position sizing:   3% risk per trade, ATR-based stop loss",
        "  Max positions:     5 simultaneous",
        "  Stop loss:         1.5\u00d7 ATR from entry",
        "  Take profit:       2.0\u00d7 risk (R:R = 1:2)",
        "  Profit vault:      10% of realized profits locked in vault",
        "  News blackout:     Groq detects high-impact events \u2192 pauses trading",
    ]

    lines.append("")
    lines.append(W)
    lines.append("  END OF REPORT")
    lines.append(f"  Generated: {ts}")
    lines.append("  Suggested LLM prompt:")
    lines.append("    \"Review this trading report. Identify (1) what's working and why,")
    lines.append("     (2) what's losing and the likely root cause, (3) specific parameter")
    lines.append("     changes to improve performance (stop loss %, position sizing, VPIN")
    lines.append("     threshold, conviction cutoffs), and (4) any regime-specific patterns")
    lines.append("     you can see in the trade history. Be specific with numbers.\"")
    lines.append(W)

    clean_lines = [l for l in lines if not l.startswith("@@")]
    report_text = "\n".join(clean_lines)
    filename = f"trading-report-{now_utc.strftime('%Y-%m-%d_%H%M%S')}.txt"

    global _last_report_lines_with_markers
    _last_report_lines_with_markers = lines[:]

    return PlainTextResponse(
        content=report_text,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Lines": str(len(clean_lines)),
            "X-Report-Chars": str(len(report_text)),
        },
    )

_last_report_lines_with_markers: list[str] = []


@portfolio_router.get("/export/report-parts", tags=["Export"])
async def export_report_parts():
    from starlette.responses import JSONResponse

    await export_diagnostic_report()

    lines = _last_report_lines_with_markers
    if not lines:
        return JSONResponse(content={"error": "No report generated"}, status_code=500)

    idx: dict[str, int] = {}
    for i, l in enumerate(lines):
        if l.startswith("@@"):
            idx[l.strip()] = i

    def _grab(start_m: str, end_m: str | None) -> list[str]:
        s = idx.get(start_m, 0)
        e = idx.get(end_m, len(lines)) if end_m else len(lines)
        return [l for l in lines[s:e] if not l.startswith("@@")]

    header = [l for l in lines[:idx.get("@@PART1@@", 0)] if not l.startswith("@@")]

    p1 = header + _grab("@@PART1@@", "@@PART2@@")
    p2 = _grab("@@PART2@@", "@@KRAKEN_SUPP@@") + _grab("@@CORR@@", "@@EXEC@@")
    p3 = _grab("@@PART3@@", "@@SEC6@@") + _grab("@@EXEC@@", "@@SEC7@@")
    p4 = (_grab("@@SEC1A@@", "@@CORR@@")
          + _grab("@@SEC6@@", "@@SEC1A@@")
          + _grab("@@KRAKEN_SUPP@@", "@@PART3@@")
          + _grab("@@SEC7@@", "@@SEC_AI@@")
          + _grab("@@SEC_AI@@", "@@SEC9@@")
          + _grab("@@SEC9@@", None))

    result = {}
    for name, part_lines in [("p1", p1), ("p2", p2), ("p3", p3), ("p4", p4)]:
        text = "\n".join(part_lines)
        result[name] = {
            "filename": f"report-{name}.txt",
            "text": text,
            "lines": len(part_lines),
            "chars": len(text),
        }
    return JSONResponse(content=result)


@portfolio_router.get("/portfolio/news-feed", tags=["Portfolio"])
async def news_feed() -> dict:
    import asyncio as _asyncio
    from data.news_client import fetch_news
    from data.cache import news_cache

    try:
        raw = await _asyncio.wait_for(
            news_cache.get_or_fetch(fetch_news, lookback_days=3),
            timeout=12.0,
        )
        articles = []
        for cat, cat_data in raw.get("by_category", {}).items():
            for article in cat_data.get("articles", []):
                articles.append({
                    "title": article.get("title", ""),
                    "source": article.get("source", "Unknown"),
                    "category": cat,
                    "published_at": article.get("published_at", ""),
                    "url": article.get("url", ""),
                })
        articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)
        if not articles:
            news_cache.invalidate()
        return {"articles": articles[:25]}
    except _asyncio.TimeoutError:
        logger.warning("News feed fetch timed out (12s)")
        news_cache.invalidate()
        return {"articles": [], "error": "timeout"}
    except Exception as exc:
        logger.warning(f"News feed fetch failed: {exc}")
        news_cache.invalidate()
        return {"articles": [], "error": str(exc)}


@portfolio_router.get("/crypto-regime")
async def get_crypto_regime():
    """
    Stage 3 — Independent crypto regime classification.
    Returns the current crypto-native regime (decoupled from equity).
    """
    try:
        from analysis.crypto_regime import get_cached_crypto_regime, classify_crypto_regime
        cached = get_cached_crypto_regime()
        if cached:
            return cached
        return classify_crypto_regime(correlation_with_equity=0.0)
    except Exception as exc:
        logger.warning(f"API | crypto-regime failed: {exc}")
        return {"crypto_regime": "unknown", "error": str(exc)}


@portfolio_router.get("/correlation-matrix")
async def get_correlation_matrix():
    """
    Stage 3 — Rolling 60-day Pearson correlation matrix between all bots.
    Includes systemic-shock detection and position-scaling factor.
    """
    try:
        from analysis.correlation_matrix import get_cached_state, compute_correlation_matrix
        cached = get_cached_state()
        if cached:
            return cached
        return compute_correlation_matrix()
    except Exception as exc:
        logger.warning(f"API | correlation-matrix failed: {exc}")
        return {"matrix": {}, "systemic_shock": False, "error": str(exc)}
