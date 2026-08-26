"""Portfolio routes: portfolio, positions/live, journal, learning-journal,
performance, allocation, AI commentary, vault, auditor, correlation,
calendar, sentiment, onchain, backtest, equity-curve, data/snapshot, export/report."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, BackgroundTasks
from loguru import logger

from core.pipeline import get_last_run
from core.market_clock import is_market_open
from core.metrics import risk_metrics as _compute_risk_metrics
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
from data.cache import get_cache_stats
from execution.kill_switch import get_state as ks_get_state
from core.scheduler import get_job_status, is_auto_trading_enabled
from core.symbols import canonical_symbol, same_symbol

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

# Home-dashboard canonical live-position routing. Each ETF bot has its own
# Alpaca account, so ticker symbols must never be used to infer ownership.
_LIVE_POSITION_ACCOUNTS: dict[str, tuple[str, str]] = {
    "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
    "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
}
def _fetch_account_positions(api_key: str, secret_key: str, bot_id: str) -> list[dict[str, Any]]:
    """Read one bot's Alpaca account and normalize it for the dashboard."""
    from alpaca.trading.client import TradingClient

    client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
    positions = client.get_all_positions()
    return [
        {
            "bot_id": bot_id,
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": p.side.value if getattr(p, "side", None) else "long",
            "avg_entry_price": float(p.avg_entry_price),
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
            "current_price": float(p.current_price),
        }
        for p in positions
    ]


async def _fetch_positions_by_bot() -> dict[str, dict[str, Any]]:
    """Fetch all three broker accounts concurrently without falling back across accounts."""
    bot_ids = list(_LIVE_POSITION_ACCOUNTS)
    requests = []
    for bot_id in bot_ids:
        key_env, secret_env = _LIVE_POSITION_ACCOUNTS[bot_id]
        api_key = os.environ.get(key_env, "")
        secret_key = os.environ.get(secret_env, "")
        if not api_key or not secret_key:
            raise RuntimeError(f"Missing Alpaca credentials for {bot_id}")
        requests.append(asyncio.to_thread(_fetch_account_positions, api_key, secret_key, bot_id))

    results = await asyncio.gather(*requests, return_exceptions=True)
    by_bot: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for bot_id, result in zip(bot_ids, results):
        if isinstance(result, Exception):
            errors.append(f"{bot_id}: {result}")
            continue
        from core.kill_switch import _vault_symbols
        vault_symbols = _vault_symbols(bot_id)
        by_bot[bot_id] = {
            "positions": result,
            "count": len(result),
            "strategy_count": sum(
                1 for position in result
                if (
                    not same_symbol(position["symbol"], "SGOV")
                    and canonical_symbol(position["symbol"]) not in vault_symbols
                )
            ),
        }

    if errors:
        raise RuntimeError("Unable to read live Alpaca positions: " + "; ".join(errors))
    return by_bot


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

    ticker_data = next(
        (
            data for key, data in by_ticker_data.items()
            if same_symbol(key, symbol)
        ),
        {},
    )
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

    stop_data = next(
        (data for key, data in saved_stops.items() if same_symbol(key, symbol)),
        None,
    )
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
        positions_by_bot = await _fetch_positions_by_bot()
        # Return the complete active fleet in the flat compatibility list.
        # Each normalized position already carries its canonical bot_id; retain
        # positions_by_bot as the attribution-friendly grouped response.
        positions = [
            position
            for bot_data in positions_by_bot.values()
            for position in bot_data["positions"]
        ]
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
        "positions_by_bot": positions_by_bot,
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


@portfolio_router.get("/vault/per-bot", tags=["Vault"])
async def per_bot_vault_report(bot_id: str | None = None) -> dict:
    """Separate per-bot reporting; the legacy /vault contract is unchanged."""
    from execution.per_bot_vault import get_vault_report
    return get_vault_report(bot_id)


@portfolio_router.get("/vault/per-bot/seed-preview", tags=["Vault"])
async def per_bot_vault_seed_preview() -> dict:
    """Preview 5% seeds from current equity without creating accounts."""
    from execution.per_bot_vault import seed_preview
    return {"enabled": False, "seed_rate": 0.05, "bots": seed_preview()}


@portfolio_router.get("/vault/per-bot/verification", tags=["Vault"])
async def per_bot_vault_verification() -> dict:
    """Deterministic accounting checks; no broker or runner interaction."""
    from execution.per_bot_vault import verification_report
    return verification_report()


@portfolio_router.post("/vault/per-bot/activate", tags=["Vault"])
async def per_bot_vault_activate(
    confirmation: str | None = None,
    dry_run: bool = True,
) -> dict:
    """Explicit activation command; defaults to a no-write simulation."""
    from execution.per_bot_vault import activate_vault
    return activate_vault(confirmation=confirmation, dry_run=dry_run)


@portfolio_router.get("/vault/history", tags=["Vault"])
async def vault_history(days: int = 90) -> dict:
    """Return daily vault growth snapshots derived from trade history."""
    from execution.profit_sweep import _use_pg, _pg_conn, get_vault_state
    from datetime import datetime, timedelta

    days = max(1, min(days, 730))  # clamp to 1–730 days

    snapshots: list[dict] = []
    total_vaulted = 0.0

    try:
        state = get_vault_state()
        if state:
            total_vaulted = float(state.get("total_vaulted_usd") or 0.0)
    except Exception:
        pass

    if not _use_pg():
        return {"count": 0, "snapshots": [], "total_vaulted_usd": total_vaulted}

    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                # Kraken contributions per day
                cur.execute("""
                    SELECT DATE(closed_at) AS day,
                           SUM(pnl_usd * 0.20) AS amount
                    FROM kraken_trades
                    WHERE pnl_usd > 0 AND closed_at >= %s
                    GROUP BY DATE(closed_at)
                """, (cutoff,))
                kraken_rows = cur.fetchall()

                # Forex contributions per day
                forex_rows = []
                try:
                    cur.execute("""
                        SELECT DATE(exit_time) AS day,
                               SUM(pnl_usd * 0.20) AS amount
                        FROM forex_trades
                        WHERE pnl_usd > 0 AND exit_time >= %s
                        GROUP BY DATE(exit_time)
                    """, (cutoff,))
                    forex_rows = cur.fetchall()
                except Exception:
                    pass

        # Merge and aggregate by day
        daily: dict[str, float] = {}
        for row in kraken_rows:
            day_str = str(row[0])
            daily[day_str] = daily.get(day_str, 0.0) + float(row[1] or 0)
        for row in forex_rows:
            day_str = str(row[0])
            daily[day_str] = daily.get(day_str, 0.0) + float(row[1] or 0)

        sorted_days = sorted(daily.keys())

        # Compute cumulative totals from trade history
        trade_total = sum(daily.values())

        # Distribute any remaining vault balance (from Alpaca HWM sweeps)
        # proportionally on the first available day or as a seed entry
        alpaca_remainder = max(0.0, total_vaulted - trade_total)
        if alpaca_remainder > 0.01 and sorted_days:
            # Prepend seed entry one day before earliest trade record
            from datetime import date as _date, timedelta as _td
            first_day = sorted_days[0]
            seed_day = str((_date.fromisoformat(first_day) - _td(days=1)))
            daily[seed_day] = daily.get(seed_day, 0.0) + alpaca_remainder
            sorted_days = sorted(daily.keys())
        elif alpaca_remainder > 0.01:
            # No trade data — single seed entry today
            seed_day = str(datetime.utcnow().date())
            daily[seed_day] = alpaca_remainder
            sorted_days = [seed_day]

        cumulative = 0.0
        for day_str in sorted_days:
            amt = daily[day_str]
            cumulative += amt
            snapshots.append({
                "date": day_str,
                "daily_vaulted": round(amt, 2),
                "cumulative_vaulted": round(cumulative, 2),
            })

    except Exception as exc:
        logger.warning(f"Vault history error: {exc}")
        return {"count": 0, "snapshots": [], "total_vaulted_usd": total_vaulted, "error": str(exc)}

    return {
        "count": len(snapshots),
        "snapshots": snapshots,
        "total_vaulted_usd": total_vaulted,
    }


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
    if len(snapshots) < 2:
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
                _rm = _compute_risk_metrics(trade_returns, periods_per_year=252 / 30)
                return {
                    **_rm,
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

    daily_returns = [s["daily_pnl_pct"] / 100.0 for s in snapshots if s.get("daily_pnl_pct") is not None]

    if len(daily_returns) < 2:
        return {
            "sharpe_ratio": None, "sortino_ratio": None,
            "max_drawdown_pct": None, "calmar_ratio": None,
            "volatility_annual_pct": None, "data_points": len(daily_returns),
        }

    equities = [s["equity"] for s in snapshots if s.get("equity")]
    return {
        **_compute_risk_metrics(daily_returns, equity_curve=equities or None),
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
        return {"curve": rows, "count": len(rows), "source": "fleet_equity_snapshots"}
    return {
        "curve": [],
        "count": len(rows),
        "source": "insufficient_history",
    }



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
