"""
claude_report.py — Structured JSON report endpoint for Claude daily analysis.

GET /trading-api/claude-report?days=N&include_logs=bool

Default: days=1, include_logs=true
Cap:     days max 30
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter
from loguru import logger

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

_BOT_TRADE_ALIAS: dict[str, tuple[str, str]] = {
    "forex_gump":    ("forex_trades",        "navigator"),
    "spy_qqq_trend": ("alpaca_etf_positions", "bot2_spy_qqq"),
}
_SINGLETON_BOTS = {"jerome_macro"}
_TRADES_TABLE_ASSET_CLASS = {
    "oracle": "momentum_equity",
}
_LIVE_GATE_WIN_RATE_MIN = 0.40
_LIVE_GATE_TRADES_MIN   = 60
_STALE_MINUTES          = 120
_DAYS_CAP               = 30

_ALPACA_ENV_VARS: dict[str, tuple[str, str]] = {
    "oracle":        ("ALPACA_API_KEY",        "ALPACA_SECRET_KEY"),
    "spy_qqq_trend": ("ALPACA_BB_API_KEY",     "ALPACA_BB_SECRET_KEY"),
    "jerome_macro":  ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
}
_BOT_BROKER_LABEL: dict[str, str] = {
    "oracle":        "alpaca_PA33G6QCIHDS",
    "spy_qqq_trend": "alpaca_PA3X9UBVZ6T8",
    "jerome_macro":  "alpaca_PA37SP8ID1XU",
}

# ── Utilities ─────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        s = dt.isoformat()
        if not (s.endswith("Z") or "+00:00" in s or s.endswith("+0000")):
            s += "Z"
        return s
    return str(dt)

def _tz(dt: Any) -> Optional[datetime]:
    if dt is None:
        return None
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def _pg_rows(sql: str, params: tuple = ()) -> list[dict]:
    import psycopg2.extras
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

def _pg_scalar(sql: str, params: tuple = ()) -> Any:
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None

def _infer_bot_from_component(component: str) -> Optional[str]:
    comp = (component or "").lower()
    _MAP = {
        "oracle": "oracle", "stf": "oracle",
        "jerome": "jerome_macro",
        "spy_qqq": "spy_qqq_trend",
        "bot2":    "spy_qqq_trend",
    }
    for key, bot_id in _MAP.items():
        if key in comp:
            return bot_id
    return None

# ── Alpaca live positions cache ────────────────────────────────────────────────

def _fetch_alpaca_positions_sync(api_key: str, secret_key: str) -> list[dict]:
    from alpaca.trading.client import TradingClient
    client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
    positions = client.get_all_positions()
    return [
        {
            "symbol":          p.symbol,
            "qty":             float(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price":   float(p.current_price),
            "unrealized_pl":   float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
            "market_value":    float(p.market_value),
        }
        for p in positions
    ]

async def _build_live_pos_cache() -> dict[str, list[dict]]:
    # Build list of (bot_id, acct_key, coroutine_or_None) upfront so we can
    # fan out all Alpaca calls in parallel via asyncio.gather instead of
    # awaiting them one-by-one in a for loop (B.1.1 perf fix).
    tasks: list[tuple[str, str, object]] = []
    for bot_id, (api_env, sec_env) in _ALPACA_ENV_VARS.items():
        api_key    = os.environ.get(api_env, "")
        secret_key = os.environ.get(sec_env, "")
        acct_key   = _BOT_BROKER_LABEL[bot_id]
        if not api_key or not secret_key:
            logger.warning(f"claude_report | Missing Alpaca creds for {bot_id} ({api_env})")
            tasks.append((bot_id, acct_key, None))
        else:
            tasks.append((
                bot_id, acct_key,
                asyncio.to_thread(_fetch_alpaca_positions_sync, api_key, secret_key),
            ))

    coroutines = [coro for _, _, coro in tasks if coro is not None]
    settled    = await asyncio.gather(*coroutines, return_exceptions=True)

    cache: dict[str, list[dict]] = {}
    result_iter = iter(settled)
    for bot_id, acct_key, coro in tasks:
        if coro is None:
            cache[acct_key] = []
            continue
        result = next(result_iter)
        if isinstance(result, Exception):
            logger.warning(f"claude_report | Alpaca {bot_id} fetch failed: {result}")
            cache[acct_key] = []
        else:
            cache[acct_key] = result
            logger.debug(f"claude_report | Alpaca {bot_id}: {len(result)} live positions")
    return cache

# ── Section: fleet ─────────────────────────────────────────────────────────────

def _build_fleet(open_positions: list, errors: list) -> dict:
    try:
        rows = _pg_rows(
            "SELECT bot_id, equity_usd, starting_usd, cash_usd FROM bot_portfolio ORDER BY bot_id"
        )
        if not rows:
            return {}
        equity_total   = sum(r["equity_usd"]  or 0 for r in rows)
        starting_total = sum(r["starting_usd"] or 0 for r in rows)
        cash_total     = sum(r["cash_usd"]     or 0 for r in rows)
        pnl_total      = equity_total - starting_total
        pnl_pct        = (pnl_total / starting_total * 100) if starting_total else 0.0
        cash_deployed  = equity_total - cash_total
        bot_pnls = sorted(
            [
                {
                    "id":      r["bot_id"],
                    "pnl_pct": round(
                        ((r["equity_usd"] - r["starting_usd"]) / r["starting_usd"] * 100)
                        if r["starting_usd"] else 0.0, 4
                    ),
                }
                for r in rows
            ],
            key=lambda x: x["pnl_pct"],
        )
        return {
            "equity_total":   round(equity_total, 2),
            "starting_total": round(starting_total, 2),
            "pnl_total":      round(pnl_total, 2),
            "pnl_pct":        round(pnl_pct, 4),
            "cash_deployed":  round(cash_deployed, 2),
            "positions_total": len(open_positions),
            "best_bot":       bot_pnls[-1] if bot_pnls else None,
            "worst_bot":      bot_pnls[0]  if bot_pnls else None,
        }
    except Exception as exc:
        errors.append({"section": "fleet", "error": str(exc)})
        return {}

# ── Section: bots ──────────────────────────────────────────────────────────────

def _get_last_trade_at(bot_id: str) -> Optional[str]:
    try:
        if bot_id == "oracle":
            result = _pg_scalar(
                "SELECT GREATEST(MAX(date::timestamptz), MAX(closed_at)) FROM trades WHERE asset_class = %s",
                ("momentum_equity",),
            )
        elif bot_id == "spy_qqq_trend":
            result = _pg_scalar(
                "SELECT GREATEST(MAX(opened_at), MAX(closed_at)) FROM alpaca_etf_positions WHERE bot_id = %s",
                ("bot2_spy_qqq",),
            )
        elif bot_id == "jerome_macro":
            result = _pg_scalar(
                "SELECT GREATEST(MAX(opened_at), MAX(closed_at)) FROM jerome_positions"
            )
        else:
            return None
        return _iso(result)
    except Exception:
        return None


def _build_bots(log_events: list, open_positions: list, errors: list) -> list[dict]:
    try:
        rows = _pg_rows(
            """SELECT bot_id, equity_usd, starting_usd, cash_usd,
                      last_updated, data_source, is_live_broker
               FROM bot_portfolio ORDER BY bot_id"""
        )
        now  = _now()
        bots = []
        for r in rows:
            bid          = r["bot_id"]
            last_updated = _tz(r["last_updated"])
            stale_mins   = (
                round((now - last_updated).total_seconds() / 60, 1)
                if last_updated else None
            )
            equity   = r["equity_usd"]   or 0
            starting = r["starting_usd"] or 0
            pnl_usd  = equity - starting
            pnl_pct  = (pnl_usd / starting * 100) if starting else 0.0
            positions_count = sum(1 for p in open_positions if p.get("bot_id") == bid)
            last_trade_at   = _get_last_trade_at(bid)

            bot_errors = [
                e for e in log_events
                if e.get("bot_id_hint") == bid and e.get("severity") in ("error", "critical")
            ]
            if bot_errors:
                status = "ERROR"
            elif stale_mins is not None and stale_mins > _STALE_MINUTES:
                status = "STALE"
            else:
                status = "TRADING"

            bots.append({
                "id":              bid,
                "status":          status,
                "equity":          round(equity, 2),
                "starting":        round(starting, 2),
                "pnl_usd":         round(pnl_usd, 2),
                "pnl_pct":         round(pnl_pct, 4),
                "cash":            round(r["cash_usd"] or 0, 2),
                "positions_count": positions_count,
                "last_cycle_at":   _iso(last_updated),
                "last_trade_at":   last_trade_at,
                "stale_minutes":   stale_mins,
                "broker":          _BOT_BROKER_LABEL.get(bid, "unknown"),
                "data_source":     r.get("data_source") or "unknown",
            })
        return bots
    except Exception as exc:
        errors.append({"section": "bots", "error": str(exc)})
        return []

# ── Section: open_positions ────────────────────────────────────────────────────

def _build_open_positions(live_pos_cache: dict, errors: list) -> list[dict]:
    positions = []
    now = _now()

    # Oracle — trades (status=Active, asset_class=momentum_equity)
    try:
        oracle_live = {p["symbol"]: p for p in live_pos_cache.get("alpaca_PA33G6QCIHDS", [])}
        rows = _pg_rows(
            "SELECT ticker, intended_price, date FROM trades WHERE status = 'Active' AND asset_class = %s",
            ("momentum_equity",),
        )
        for r in rows:
            sym  = r["ticker"]
            live = oracle_live.get(sym, {})
            date_held = r["date"]
            days_held = (now.date() - date_held).days if date_held else None
            urpc = live.get("unrealized_plpc")
            positions.append({
                "bot_id": "oracle", "symbol": sym, "direction": "long",
                "qty":           live.get("qty"),
                "entry_price":   float(r["intended_price"]) if r["intended_price"] else live.get("avg_entry_price"),
                "current_price": live.get("current_price"),
                "unrealised_pnl_usd": live.get("unrealized_pl"),
                "unrealised_pnl_pct": round(urpc * 100, 4) if urpc is not None else None,
                "days_held":    days_held,
                "trailing_stop": None,
                "entry_reason":  None,
                "asset_class":   "momentum_equity",
            })
    except Exception as exc:
        errors.append({"section": "open_positions.oracle", "error": str(exc)})

    # SPY/QQQ — alpaca_etf_positions
    # Multiple DB lots of the same symbol are aggregated into one position entry
    # (weighted-avg entry price, summed qty) so the P&L from Alpaca's single
    # merged position is not mirrored across duplicate rows in the report.
    try:
        spy_live = {p["symbol"]: p for p in live_pos_cache.get("alpaca_PA3X9UBVZ6T8", [])}
        rows = _pg_rows(
            "SELECT symbol, direction, qty, entry_price, stop_price, opened_at "
            "FROM alpaca_etf_positions WHERE bot_id = %s AND status = 'open'",
            ("bot2_spy_qqq",),
        )
        _lots_by_sym: dict = {}
        for r in rows:
            _lots_by_sym.setdefault(r["symbol"], []).append(r)
        for sym, lots in _lots_by_sym.items():
            live = spy_live.get(sym, {})
            opened_ats = [_tz(r["opened_at"]) for r in lots if r["opened_at"]]
            opened_at  = min(opened_ats) if opened_ats else None
            days_held  = (now - opened_at).days if opened_at else None
            total_qty  = sum(float(r["qty"] or 0) for r in lots)
            wavg_entry = (
                sum(float(r["qty"] or 0) * float(r["entry_price"] or 0) for r in lots) / total_qty
                if total_qty else 0.0
            )
            urpc = live.get("unrealized_plpc")
            positions.append({
                "bot_id": "spy_qqq_trend", "symbol": sym, "direction": lots[0]["direction"],
                "qty":           round(total_qty, 6),
                "entry_price":   round(wavg_entry, 4),
                "current_price": live.get("current_price"),
                "unrealised_pnl_usd": live.get("unrealized_pl"),
                "unrealised_pnl_pct": round(urpc * 100, 4) if urpc is not None else None,
                "days_held":    days_held,
                "trailing_stop": float(lots[0]["stop_price"]) if lots[0]["stop_price"] else None,
                "entry_reason":  None,
                "asset_class":   "momentum_etf",
            })
    except Exception as exc:
        errors.append({"section": "open_positions.spy_qqq_trend", "error": str(exc)})

    # Jerome — jerome_positions (status=open)
    try:
        jerome_live = {p["symbol"]: p for p in live_pos_cache.get("alpaca_PA37SP8ID1XU", [])}
        rows = _pg_rows(
            "SELECT symbol, direction, notional_usd, stop_loss_pct, thesis, opened_at "
            "FROM jerome_positions WHERE status = 'open'"
        )
        for r in rows:
            sym  = r["symbol"]
            live = jerome_live.get(sym, {})
            opened_at  = _tz(r["opened_at"])
            days_held  = (now - opened_at).days if opened_at else None
            entry_px   = live.get("avg_entry_price")
            stop_price = (
                round(entry_px * (1 - float(r["stop_loss_pct"])), 2)
                if entry_px and r["stop_loss_pct"] else None
            )
            urpc = live.get("unrealized_plpc")
            positions.append({
                "bot_id": "jerome_macro", "symbol": sym, "direction": r["direction"],
                "qty":           live.get("qty"),
                "entry_price":   entry_px,
                "current_price": live.get("current_price"),
                "unrealised_pnl_usd": live.get("unrealized_pl"),
                "unrealised_pnl_pct": round(urpc * 100, 4) if urpc is not None else None,
                "days_held":    days_held,
                "trailing_stop": stop_price,
                "entry_reason":  (r.get("thesis") or "")[:80] or None,
                "asset_class":   "macro_etf",
            })
    except Exception as exc:
        errors.append({"section": "open_positions.jerome_macro", "error": str(exc)})

    return positions

# ── Section: trades_window ─────────────────────────────────────────────────────

def _trade_row(bot_id: str, symbol: str, direction: Any,
               qty: Any, entry_price: Any, exit_price: Any,
               opened_at: Any, closed_at: Any, realised_pnl_usd: Any,
               exit_reason: Any, asset_class: str, status: str) -> dict:
    return {
        "bot_id":          bot_id,
        "symbol":          symbol,
        "direction":       direction,
        "qty":             float(qty)             if qty             is not None else None,
        "entry_price":     float(entry_price)     if entry_price     is not None else None,
        "exit_price":      float(exit_price)      if exit_price      is not None else None,
        "opened_at":       _iso(opened_at),
        "closed_at":       _iso(closed_at),
        "realised_pnl_usd": float(realised_pnl_usd) if realised_pnl_usd is not None else None,
        "exit_reason":     exit_reason,
        "asset_class":     asset_class,
        "status":          status,
    }


def _build_trades_window(window_start: datetime, errors: list) -> list[dict]:
    trades = []

    # Oracle
    try:
        rows = _pg_rows(
            """SELECT ticker, 'long' AS direction, NULL AS qty,
                      intended_price, actual_fill_price,
                      date::timestamptz AS opened_at, closed_at,
                      realized_pnl, exit_reason, asset_class, status
               FROM trades
               WHERE asset_class = %s
                 AND (closed_at >= %s OR (status = 'Active' AND date::timestamptz >= %s))
               ORDER BY COALESCE(closed_at, date::timestamptz) DESC""",
            ("momentum_equity", window_start, window_start),
        )
        for r in rows:
            trades.append(_trade_row(
                "oracle", r["ticker"], "long",
                None, r["intended_price"], r["actual_fill_price"],
                r["opened_at"], r["closed_at"], r["realized_pnl"],
                r["exit_reason"], r["asset_class"], r["status"],
            ))
    except Exception as exc:
        errors.append({"section": "trades_window.oracle", "error": str(exc)})

    # SPY/QQQ
    try:
        rows = _pg_rows(
            """SELECT symbol, direction, qty::float, entry_price::float,
                      NULL AS exit_price, opened_at, closed_at,
                      realised_pnl::float, exit_reason, status
               FROM alpaca_etf_positions
               WHERE bot_id = %s
                 AND (closed_at >= %s OR (status = 'open' AND opened_at >= %s))
               ORDER BY COALESCE(closed_at, opened_at) DESC""",
            ("bot2_spy_qqq", window_start, window_start),
        )
        for r in rows:
            trades.append(_trade_row(
                "spy_qqq_trend", r["symbol"], r["direction"],
                r["qty"], r["entry_price"], r["exit_price"],
                r["opened_at"], r["closed_at"], r["realised_pnl"],
                r["exit_reason"], "momentum_etf", r["status"],
            ))
    except Exception as exc:
        errors.append({"section": "trades_window.spy_qqq_trend", "error": str(exc)})

    # Jerome
    try:
        rows = _pg_rows(
            """SELECT symbol, direction, opened_at, closed_at,
                      realised_pnl_usd, exit_reason, status
               FROM jerome_positions
               WHERE (closed_at >= %s OR (status = 'open' AND opened_at >= %s))
               ORDER BY COALESCE(closed_at, opened_at) DESC""",
            (window_start, window_start),
        )
        for r in rows:
            trades.append(_trade_row(
                "jerome_macro", r["symbol"], r["direction"],
                None, None, None,
                r["opened_at"], r["closed_at"], r["realised_pnl_usd"],
                r["exit_reason"], "macro_etf", r["status"],
            ))
    except Exception as exc:
        errors.append({"section": "trades_window.jerome_macro", "error": str(exc)})

    return trades

# ── Section: metrics_30d ───────────────────────────────────────────────────────

def _build_metrics_30d(errors: list) -> list[dict]:
    import statistics as _stats
    thirty_days_ago = _now() - timedelta(days=30)

    _sources = [
        {
            "bot_id": "oracle",
            # ARC 4: exclude reconciliation tracking rows (is_recon_tracking=TRUE)
            # so WR/expectancy only counts genuine oracle trades, not ghost-repair rows.
            "sql": """SELECT realized_pnl AS pnl FROM trades
                      WHERE asset_class = 'momentum_equity'
                        AND status NOT IN ('Active') AND closed_at >= %s
                        AND NOT COALESCE(is_recon_tracking, FALSE)""",
        },
        {
            "bot_id": "spy_qqq_trend",
            "sql": """SELECT realised_pnl::float AS pnl FROM alpaca_etf_positions
                      WHERE bot_id = 'bot2_spy_qqq' AND status = 'closed' AND closed_at >= %s""",
        },
        {
            "bot_id": "jerome_macro",
            # opened_at filter excludes v1 LLM trades (pre-2026-05-28).
            # v1 used verbose LLM exits; v2 uses EMA/ADX mechanical signals.
            # v1 rows stay in the table as historical record but must not
            # pollute Jerome v2's live-trading scorecard.
            "sql": """SELECT realised_pnl_usd AS pnl FROM jerome_positions
                      WHERE status = 'closed' AND closed_at >= %s
                        AND opened_at >= '2026-05-28 00:00:00+00'""",
        },
    ]

    metrics = []
    for src in _sources:
        try:
            rows  = _pg_rows(src["sql"], (thirty_days_ago,))
            pnls  = [float(r["pnl"]) for r in rows if r.get("pnl") is not None]
            count = len(rows)
            wins  = sum(1 for p in pnls if p > 0)
            losses= sum(1 for p in pnls if p < 0)
            win_rate    = wins / count if count else 0.0
            winners     = [p for p in pnls if p > 0]
            losers      = [p for p in pnls if p < 0]
            avg_winner  = (sum(winners) / len(winners)) if winners else 0.0
            avg_loser   = (sum(losers)  / len(losers))  if losers  else 0.0
            expectancy  = (win_rate * avg_winner) + ((1 - win_rate) * avg_loser)
            pnl_total   = sum(pnls)
            sharpe_proxy = None
            if len(pnls) >= 3:
                mu = _stats.mean(pnls)
                sd = _stats.stdev(pnls)
                sharpe_proxy = round(mu / sd, 3) if sd else None
            metrics.append({
                "bot_id":               src["bot_id"],
                "trades_count":         count,
                "wins":                 wins,
                "losses":               losses,
                "win_rate":             round(win_rate, 4),
                "avg_winner_usd":       round(avg_winner, 2),
                "avg_loser_usd":        round(avg_loser, 2),
                "expectancy_usd":       round(expectancy, 2),
                "pnl_total_usd":        round(pnl_total, 2),
                "sharpe_proxy":         sharpe_proxy,
                "live_capital_gate_met": (
                    win_rate >= _LIVE_GATE_WIN_RATE_MIN
                    and count >= _LIVE_GATE_TRADES_MIN
                ),
            })
        except Exception as exc:
            errors.append({"section": f"metrics_30d.{src['bot_id']}", "error": str(exc)})

    return metrics

# ── Stale-bot thresholds (seconds) ────────────────────────────────────────────
from core.bot_liveness import PORTFOLIO_STALE_THRESHOLDS as _BOT_STALE_THRESHOLDS


def _build_stale_flags(errors: list) -> list[dict]:
    """Check bot_portfolio.last_updated against per-bot thresholds.

    Emits a HIGH severity entry to system_degradations on stale detection
    AND returns the flag for inclusion in the report.  Dual emission means
    stale bots appear in both errors_window AND reconciliation_flags.
    """
    flags: list[dict] = []
    try:
        rows = _pg_rows(
            "SELECT bp.bot_id, bp.last_updated, "
            "EXTRACT(EPOCH FROM (NOW() - last_updated)) AS age_s, "
            "COALESCE(bs.paused, FALSE) AS database_paused "
            "FROM bot_portfolio bp "
            "LEFT JOIN bots_state bs ON bs.bot_id = bp.bot_id "
            "WHERE bp.bot_id = ANY(%s)",
            (list(_BOT_STALE_THRESHOLDS.keys()),),
        )
        for r in rows:
            age_s = r.get("age_s")
            if age_s is None:
                continue
            age_s = float(age_s)
            bot_id = r["bot_id"]
            threshold = _BOT_STALE_THRESHOLDS[bot_id]
            if bool(r.get("database_paused")):
                logger.info(
                    f"claude_report | {bot_id} paused in database — "
                    "portfolio staleness is not a degradation"
                )
                continue
            if age_s > threshold:
                flags.append({
                    "type":      "bot_stale",
                    "bot_id":    bot_id,
                    "detail":    f"last_updated {int(age_s)}s ago (threshold {threshold}s)",
                    "severity":  "high",
                })
                try:
                    from core.degradation_tracker import record_degradation
                    record_degradation(
                        component=f"bot/{bot_id}",
                        severity="high",
                        error_type="bot_stale_workflow",
                        message=(
                            f"{bot_id} stale: last_updated {int(age_s)}s ago "
                            f"(threshold {threshold}s). Manual restart required."
                        ),
                    )
                except Exception as exc:
                    logger.warning(f"claude_report | stale flag degradation write failed: {exc}")
    except Exception as exc:
        errors.append({"section": "recon_flags.bot_stale", "error": str(exc)})
    return flags


# ── Section: reconciliation_flags ─────────────────────────────────────────────

def _build_reconciliation_flags(live_pos_cache: dict, errors: list) -> list[dict]:
    flags = []
    now   = _now()

    # (a)+(d) broker_db_mismatch / orphan_db_active — Alpaca accounts
    _alpaca_checks = [
        ("oracle",        "alpaca_PA33G6QCIHDS",
         "SELECT COUNT(*) FROM trades WHERE asset_class='momentum_equity' AND status='Active'",
         ()),
        ("spy_qqq_trend", "alpaca_PA3X9UBVZ6T8",
         "SELECT COUNT(DISTINCT symbol) FROM alpaca_etf_positions WHERE bot_id='bot2_spy_qqq' AND status='open'",
         ()),
        ("jerome_macro",  "alpaca_PA37SP8ID1XU",
         "SELECT COUNT(*) FROM jerome_positions WHERE status='open'",
         ()),
    ]
    for bot_id, acct_key, sql, params in _alpaca_checks:
        try:
            broker_count = len(live_pos_cache.get(acct_key) or [])
            db_count     = int(_pg_scalar(sql, params) or 0)
            if broker_count != db_count:
                flags.append({
                    "type":     "broker_db_mismatch" if broker_count < db_count else "orphan_db_active",
                    "bot_id":   bot_id,
                    "detail":   f"Broker: {broker_count} | DB Active: {db_count}",
                    "severity": "medium",
                })
        except Exception as exc:
            errors.append({"section": f"recon_flags.broker_mismatch.{bot_id}", "error": str(exc)})

    # (b) stale_portfolio
    try:
        rows = _pg_rows("SELECT bot_id, last_updated FROM bot_portfolio")
        for r in rows:
            lu = _tz(r["last_updated"])
            stale_mins = (now - lu).total_seconds() / 60 if lu else 9999
            if stale_mins > _STALE_MINUTES:
                flags.append({
                    "type":     "stale_portfolio",
                    "bot_id":   r["bot_id"],
                    "detail":   f"last_updated {round(stale_mins):.0f}min ago",
                    "severity": "low",
                })
    except Exception as exc:
        errors.append({"section": "recon_flags.stale_portfolio", "error": str(exc)})

    # (c) null_realised_pnl
    _null_checks = [
        ("oracle",
         "SELECT COUNT(*) FROM trades WHERE asset_class='momentum_equity' AND status NOT IN ('Active') AND realized_pnl IS NULL AND closed_at > NOW() - INTERVAL '60 days'"),
        ("spy_qqq_trend",
         "SELECT COUNT(*) FROM alpaca_etf_positions WHERE bot_id='bot2_spy_qqq' AND status='closed' AND realised_pnl IS NULL"),
        ("jerome_macro",
         "SELECT COUNT(*) FROM jerome_positions WHERE status='closed' AND realised_pnl_usd IS NULL"),
        ("forex_gump",
         "SELECT COUNT(*) FROM forex_trades WHERE bot_id='navigator' AND status!='open' AND pnl_usd IS NULL"),
    ]
    for bot_id, sql in _null_checks:
        try:
            cnt = int(_pg_scalar(sql) or 0)
            if cnt > 0:
                flags.append({
                    "type":     "null_realised_pnl",
                    "bot_id":   bot_id,
                    "detail":   f"{cnt} closed row(s) with realised_pnl IS NULL",
                    "severity": "high",
                })
        except Exception as exc:
            errors.append({"section": f"recon_flags.null_pnl.{bot_id}", "error": str(exc)})

    # (e) decision_unexecuted — Jerome only
    try:
        decisions = _pg_rows(
            "SELECT id, decided_at, entries_count, entries_json "
            "FROM jerome_groq_decisions WHERE entries_count > 0 "
            "AND decided_at >= '2026-05-28 00:00:00+00' "
            "ORDER BY decided_at DESC LIMIT 20"
        )
        for d in decisions:
            entries = d.get("entries_json") or []
            if isinstance(entries, str):
                entries = json.loads(entries)
            syms = [e.get("symbol") for e in entries if e.get("symbol")]
            if not syms:
                continue
            decided_at    = _tz(d["decided_at"])
            ten_min_after = decided_at + timedelta(minutes=10)
            matched = int(_pg_scalar(
                "SELECT COUNT(*) FROM jerome_positions WHERE symbol = ANY(%s) AND opened_at BETWEEN %s AND %s",
                (syms, decided_at, ten_min_after),
            ) or 0)
            if matched < len(syms) * 0.5:
                flags.append({
                    "type":     "decision_unexecuted",
                    "bot_id":   "jerome_macro",
                    "detail":   f"Decision id={d['id']} at {_iso(decided_at)}: {len(syms)} expected, {matched} positions found in +10min",
                    "severity": "high",
                })
    except Exception as exc:
        errors.append({"section": "recon_flags.decision_unexecuted", "error": str(exc)})

    # (f) stale bots — per-bot last_updated thresholds
    flags.extend(_build_stale_flags(errors))

    return flags

# ── Section: errors_window ────────────────────────────────────────────────────

def _build_errors_window(window_start: datetime, errors: list) -> list[dict]:
    try:
        from core.degradation_tracker import get_recent_events
        hours = max(1, int(((_now() - window_start).total_seconds() / 3600) + 1))
        raw   = get_recent_events(hours=hours, limit=500)
        groups: dict[tuple, list] = defaultdict(list)
        for evt in raw:
            key = (evt.get("component", ""), evt.get("error_type", ""))
            groups[key].append(evt)
        _sev_order = {"critical": 3, "error": 2, "warning": 1, "info": 0}
        result = []
        for (component, error_type), evts in groups.items():
            max_sev    = max(evts, key=lambda e: _sev_order.get(e.get("severity", "info"), 0))
            timestamps = [e["ts"] for e in evts if e.get("ts")]
            result.append({
                "first_seen":   min(timestamps) if timestamps else None,
                "last_seen":    max(timestamps) if timestamps else None,
                "count":        len(evts),
                "pattern":      (evts[0].get("message") or "")[:120],
                "bot_id_hint":  _infer_bot_from_component(component),
                "severity":     max_sev.get("severity", "info"),
                "component":    component,
                "error_type":   error_type,
            })
        result.sort(key=lambda x: x["count"], reverse=True)
        return result[:50]
    except Exception as exc:
        errors.append({"section": "errors_window", "error": str(exc)})
        return []

# ── Section: decisions_pending ────────────────────────────────────────────────

def _build_decisions_pending(window_start: datetime, errors: list) -> list[dict]:
    try:
        rows = _pg_rows(
            "SELECT id, decided_at, entries_count, closes_count, entries_json, closes_json "
            "FROM jerome_groq_decisions WHERE decided_at >= %s ORDER BY decided_at DESC",
            (window_start,),
        )
        result = []
        for r in rows:
            entries = r.get("entries_json") or []
            closes  = r.get("closes_json")  or []
            if isinstance(entries, str):
                entries = json.loads(entries)
            if isinstance(closes, str):
                closes  = json.loads(closes)
            decided_at    = _tz(r["decided_at"])
            ten_min_after = decided_at + timedelta(minutes=10) if decided_at else None
            entry_syms = [e.get("symbol") for e in entries if e.get("symbol")]
            close_syms = [c.get("symbol") for c in closes  if c.get("symbol")]
            executed      = True
            fills_pending = False
            if entry_syms and decided_at:
                matched = int(_pg_scalar(
                    "SELECT COUNT(*) FROM jerome_positions WHERE symbol = ANY(%s) AND opened_at BETWEEN %s AND %s",
                    (entry_syms, decided_at, ten_min_after),
                ) or 0)
                executed = matched >= len(entry_syms) * 0.5
            if close_syms:
                still_open = int(_pg_scalar(
                    "SELECT COUNT(*) FROM jerome_positions WHERE symbol = ANY(%s) AND status = 'open'",
                    (close_syms,),
                ) or 0)
                fills_pending = still_open > 0
            result.append({
                "bot_id":        "jerome_macro",
                "decided_at":    _iso(decided_at),
                "decision_type": "entry" if entry_syms else "close",
                "entries_count": r["entries_count"] or 0,
                "closes_count":  r["closes_count"]  or 0,
                "entries":       entry_syms,
                "closes":        close_syms,
                "executed":      executed,
                "fills_pending": fills_pending,
            })
        return result
    except Exception as exc:
        errors.append({"section": "decisions_pending", "error": str(exc)})
        return []

# ── Section: exit_attribution_30d ─────────────────────────────────────────────

def _build_exit_attribution_30d(errors: list) -> dict:
    thirty_days_ago = _now() - timedelta(days=30)
    all_exits: list[tuple[str, Optional[float]]] = []

    def _collect(sql: str, params: tuple = ()) -> None:
        try:
            rows = _pg_rows(sql, params)
            for r in rows:
                reason = r.get("exit_reason") or r.get("reason") or "unknown"
                pnl    = r.get("pnl")
                all_exits.append((str(reason), float(pnl) if pnl is not None else None))
        except Exception as exc:
            errors.append({"section": "exit_attribution_30d.collect", "error": str(exc)})

    _collect(
        "SELECT exit_reason, realized_pnl AS pnl FROM trades "
        "WHERE asset_class='momentum_equity' AND status NOT IN ('Active') AND closed_at >= %s",
        (thirty_days_ago,),
    )
    _collect(
        "SELECT exit_reason, realised_pnl::float AS pnl FROM alpaca_etf_positions "
        "WHERE status='closed' AND closed_at >= %s",
        (thirty_days_ago,),
    )
    _collect(
        # opened_at >= 2026-05-28: exclude v1 LLM exits from attribution buckets
        "SELECT exit_reason, realised_pnl_usd::float AS pnl FROM jerome_positions "
        "WHERE status='closed' AND closed_at >= %s AND opened_at >= '2026-05-28 00:00:00+00'",
        (thirty_days_ago,),
    )
    def _bucket(reason: str) -> str:
        r = reason.lower()
        if any(k in r for k in ("trail", "stop")):       return "trailing_stop"
        if any(k in r for k in ("rank", "dropout")):     return "rank_dropout"
        if any(k in r for k in ("direction", "flip")):   return "direction_flip"
        if any(k in r for k in ("max_hold", "time")):    return "max_hold"
        if any(k in r for k in ("trend", "ema")):        return "trend_exit"
        if any(k in r for k in ("llm", "groq", "ai", "agriculture", "energy", "sector")):
            return "llm_close"
        return "other"

    buckets: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl_usd": 0.0, "_null": False})
    for reason, pnl in all_exits:
        b = _bucket(reason)
        buckets[b]["count"] += 1
        if pnl is None:
            buckets[b]["_null"] = True
        else:
            buckets[b]["pnl_usd"] += pnl

    canonical = ("trailing_stop", "rank_dropout", "direction_flip", "max_hold", "trend_exit", "llm_close", "other")
    result = {}
    for b in canonical:
        if b in buckets:
            d = buckets[b]
            result[b] = {
                "count":   d["count"],
                "pnl_usd": None if (d["_null"] and d["pnl_usd"] == 0.0) else round(d["pnl_usd"], 2),
            }
        else:
            result[b] = {"count": 0, "pnl_usd": 0.0}
    return result

# ── Section: market_state ─────────────────────────────────────────────────────


def _build_market_state(errors: list) -> dict:
    """Fetch current MSE regime. Non-fatal: returns {} on any error."""
    try:
        from core.market_state import get_market_state
        return get_market_state(persist=False)
    except Exception as exc:
        errors.append({"section": "market_state", "error": str(exc)})
        return {}


# ── Section: walk_forward_status ──────────────────────────────────────────────

def _build_walk_forward_status(errors: list) -> list[dict]:
    """
    Read the most-recent walk-forward row per bot from bot_evaluation_history.
    Non-fatal: returns [] if table not yet populated (pre-first-run).
    """
    try:
        from analysis.arc2_walk_forward import get_current_wf_status
        return get_current_wf_status()
    except Exception as exc:
        errors.append({"section": "walk_forward_status", "error": str(exc)})
        return []


# ── Text formatter ─────────────────────────────────────────────────────────────

def _format_text(r: dict) -> str:
    """Convert the claude-report JSON dict into a copy-pasteable plain-text report."""
    SEP  = "═" * 67
    DASH = "─" * 4

    def _c(v) -> str:
        return f"${v:,.2f}" if v is not None else "N/A"

    def _sgn(v) -> str:
        if v is None:
            return "N/A"
        return f"+${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}"

    def _pct(v) -> str:
        if v is None:
            return "N/A"
        return f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"

    lines: list[str] = [
        SEP,
        "QUANT TERMINAL — CLAUDE REPORT",
        f"Generated: {r.get('generated_at', 'N/A')}",
        f"Window:    {r.get('window_days', 1)} day(s)",
        SEP,
        "",
    ]

    # ── Market State ───────────────────────────────────────────────────────────
    _ms        = r.get("market_state") or {}
    _ms_regime = _ms.get("regime", "UNKNOWN")
    _ms_hv     = _ms.get("high_vol", False)
    _ms_20d    = _ms.get("spy_20d_ret")
    _ms_close  = _ms.get("spy_close")
    _ms_200sma = _ms.get("spy_200sma")
    _vol_flag  = "  ⚠ HIGH_VOL" if _ms_hv else ""
    lines += [
        f"{DASH} MARKET STATE {DASH}",
        f"Regime:    {_ms_regime}{_vol_flag}",
    ]
    if _ms_20d is not None:
        lines.append(f"SPY 20d:   {_ms_20d:+.2%}")
    if _ms_close is not None and _ms_200sma is not None:
        lines.append(f"SPY close: {_ms_close:.2f}  200SMA: {_ms_200sma:.2f}")
    if _ms_regime == "CRISIS":
        lines.append(
            "CRISIS GATE ACTIVE — all new entries blocked "
            "(safe-havens TLT/GLD/IEF longs only, max 2, 0.5× size)"
        )
    elif _ms_regime == "BEAR":
        lines.append("BEAR (display only — no trading gate active)")
    lines.append("")

    # ── Fleet ──────────────────────────────────────────────────────────────────
    fleet = r.get("fleet") or {}
    best  = fleet.get("best_bot")  or {}
    worst = fleet.get("worst_bot") or {}
    lines += [
        f"{DASH} FLEET {DASH}",
        f"Equity:      {_c(fleet.get('equity_total'))}",
        f"Starting:    {_c(fleet.get('starting_total'))}",
        f"P&L:         {_sgn(fleet.get('pnl_total'))} ({_pct(fleet.get('pnl_pct'))})",
        f"Cash:        {_c(fleet.get('cash_deployed'))}",
        f"Positions:   {fleet.get('positions_total', 0)}",
        f"Best:        {best.get('id', 'N/A')} ({_pct(best.get('pnl_pct'))})",
        f"Worst:       {worst.get('id', 'N/A')} ({_pct(worst.get('pnl_pct'))})",
        "",
    ]

    # ── Bots ───────────────────────────────────────────────────────────────────
    lines.append(f"{DASH} BOTS {DASH}")
    for b in (r.get("bots") or []):
        sm = b.get("stale_minutes")
        stale_s = f"stale={int(sm)}m" if sm is not None else "stale=?"
        lines.append(
            f"{b.get('id', '?'):<20} {b.get('status', '?'):<16}"
            f"equity={_c(b.get('equity'))}  "
            f"pnl={_sgn(b.get('pnl_usd'))} ({_pct(b.get('pnl_pct'))})  "
            f"pos={b.get('positions_count', 0)}  {stale_s}"
        )
    lines.append("")

    # ── Open positions ─────────────────────────────────────────────────────────
    lines.append(f"{DASH} OPEN POSITIONS {DASH}")
    open_pos = r.get("open_positions") or []
    if not open_pos:
        lines.append("  (none)")
    for p in open_pos:
        unreal_s = _sgn(p.get("unrealised_pnl_usd"))
        unreal_pct = p.get("unrealised_pnl_pct")
        if unreal_pct is not None:
            unreal_s += f" ({_pct(unreal_pct)})"
        lines.append(
            f"{p.get('bot_id', '?'):<20} {p.get('symbol', '?'):<10} "
            f"{str(p.get('direction', '?')):<5}"
            f"qty={p.get('qty', '?')}  entry={_c(p.get('entry_price'))}  "
            f"current={_c(p.get('current_price'))}  unreal={unreal_s}  "
            f"held={p.get('days_held', '?')}d"
        )
    lines.append("")

    # ── Trades in window ───────────────────────────────────────────────────────
    lines.append(f"{DASH} TRADES IN WINDOW {DASH}")
    trades = r.get("trades_window") or []
    if not trades:
        lines.append("  (none)")
    for t in trades:
        reason = str(t.get("exit_reason") or "?")[:30]
        lines.append(
            f"{t.get('bot_id', '?'):<20} {t.get('symbol', '?'):<10} "
            f"{str(t.get('direction', '?')):<5}"
            f"entry={_c(t.get('entry_price'))}  exit={_c(t.get('exit_price'))}  "
            f"pnl={_sgn(t.get('realised_pnl_usd'))}  reason={reason}"
        )
    lines.append("")

    # ── Metrics 30d ────────────────────────────────────────────────────────────
    lines.append(f"{DASH} METRICS (30d) {DASH}")
    for m in (r.get("metrics_30d") or []):
        gate    = "Y" if m.get("live_capital_gate_met") else "N"
        sharpe  = m.get("sharpe_proxy")
        sharpe_s = f"{sharpe:.2f}" if sharpe is not None else "N/A"
        wr       = m.get("win_rate", 0) or 0
        lines.append(
            f"{m.get('bot_id', '?'):<20}"
            f"trades={m.get('trades_count', 0)}  "
            f"WR={wr * 100:.1f}%  "
            f"expectancy={_sgn(m.get('expectancy_usd'))}  "
            f"total={_sgn(m.get('pnl_total_usd'))}  "
            f"sharpe={sharpe_s}  gate={gate}"
        )
    lines.append("")

    # ── Reconciliation flags ───────────────────────────────────────────────────
    lines.append(f"{DASH} RECONCILIATION FLAGS {DASH}")
    flags = r.get("reconciliation_flags") or []
    if not flags:
        lines.append("  (none)")
    for fl in sorted(flags, key=lambda x: (x.get("severity") or ""), reverse=True):
        sev   = (fl.get("severity") or "?").upper()
        ftype = fl.get("type", "?")
        bid   = fl.get("bot_id") or ""
        det   = fl.get("detail") or ""
        bid_s = f" {bid}" if bid else ""
        lines.append(f"  [{sev}] {ftype}{bid_s}: {det}")
    lines.append("")

    # ── Errors window ──────────────────────────────────────────────────────────
    days = r.get("window_days", 1)
    lines.append(f"{DASH} ERRORS (last {days} day(s)) {DASH}")
    errs = r.get("errors_window") or []
    if not errs:
        lines.append("  (none)")
    for e in errs[:50]:
        sev   = (e.get("severity") or "?").upper()
        pat   = str(e.get("pattern") or e.get("error_type") or "?")[:80]
        cnt   = e.get("count", 1)
        first = (e.get("first_seen") or "?")[:19]
        last  = (e.get("last_seen")  or "?")[:19]
        hint  = e.get("bot_id_hint") or ""
        lines.append(f"  [{sev}] {pat} (count={cnt}, first={first}, last={last}, bot={hint})")
    lines.append("")

    # ── Decisions pending ──────────────────────────────────────────────────────
    lines.append(f"{DASH} DECISIONS PENDING {DASH}")
    decisions = r.get("decisions_pending") or []
    if not decisions:
        lines.append("  (none)")
    for d in decisions:
        exec_s = "Y" if d.get("executed") else "N"
        fill_s = "Y" if d.get("fills_pending") else "N"
        lines.append(
            f"{d.get('bot_id', '?')} @ {(d.get('decided_at') or '?')[:19]}: "
            f"{d.get('decision_type', '?')}  "
            f"entries={d.get('entries_count', 0)}  closes={d.get('closes_count', 0)}  "
            f"executed={exec_s}  fills_pending={fill_s}"
        )
    lines.append("")

    # ── Exit attribution ───────────────────────────────────────────────────────
    lines.append(f"{DASH} EXIT ATTRIBUTION (30d) {DASH}")
    attr = r.get("exit_attribution_30d") or {}
    for bucket in ("trailing_stop", "rank_dropout", "direction_flip",
                   "max_hold", "trend_exit", "llm_close", "other"):
        d = attr.get(bucket) or {"count": 0, "pnl_usd": 0.0}
        lines.append(f"  {bucket:<20} count={d.get('count', 0)}, pnl={_sgn(d.get('pnl_usd'))}")

    # ── Walk-Forward Validation ────────────────────────────────────────────────
    _STATUS_ICON = {
        "GREEN":            "✅ GREEN",
        "AMBER":            "🟡 AMBER",
        "RED":              "🔴 RED",
        "INSUFFICIENT_DATA":"⏳ INSUFFICIENT_DATA",
        "DISQUALIFIED":     "⚫ DISQUALIFIED",
    }
    wf = r.get("walk_forward_status") or []
    lines.append(f"{DASH} WALK-FORWARD VALIDATION (ARC 2) {DASH}")
    if not wf:
        lines.append("  (no data — run nightly_walk_forward job or wait for first 17:30 ET cycle)")
    for w in wf:
        bid   = w.get("bot_id", "?")
        st    = w.get("wf_status") or "?"
        icon  = _STATUS_ICON.get(st, st)
        sh90  = w.get("wf_sharpe_90d")
        sh30  = w.get("wf_sharpe_30d")
        floor = w.get("wf_oos_floor_sharpe")
        days  = w.get("wf_consecutive_below_floor") or 0
        cnt   = w.get("wf_trades_90d") or 0
        mdd   = w.get("wf_maxdd_90d")
        snap  = (w.get("snapshot_at") or "?")[:19]
        sh90_s  = f"{sh90:.3f}" if sh90 is not None else "N/A"
        sh30_s  = f"{sh30:.3f}" if sh30 is not None else "N/A"
        floor_s = f"{floor:.3f}" if floor is not None else "N/A"
        mdd_s   = f"{mdd * 100:.1f}%" if mdd is not None else "N/A"
        lines.append(
            f"  {bid:<20} {icon:<25} "
            f"Sharpe90d={sh90_s}  floor={floor_s}  "
            f"Sharpe30d={sh30_s}  trades90d={cnt}  "
            f"maxDD={mdd_s}  below={days}d  snap={snap}"
        )
        if st == "RED":
            _protocol = ""
            if days >= 120:
                _protocol = "  ⛔ PROTOCOL: HALT ENTRIES (human action required)"
            elif days >= 60:
                _protocol = "  ⚠ PROTOCOL: HALVE POSITION SIZE (human action required)"
            if _protocol:
                lines.append(f"  {'':20} {_protocol}")
    lines.append("")

    lines += ["", SEP, "END OF REPORT", SEP, ""]
    return "\n".join(lines)


# ── Main route handler ─────────────────────────────────────────────────────────

@router.get("/claude-report", tags=["Claude Report"])
async def claude_report(days: int = 1, include_logs: bool = True) -> dict:
    """
    Structured JSON snapshot for Claude daily analysis.
    Covers all 8 bots: open positions, trade history, 30-day metrics,
    reconciliation flags, error patterns, and LLM decision tracking.
    """
    t0           = time.perf_counter()
    days         = min(max(days, 1), _DAYS_CAP)
    window_start = _now() - timedelta(days=days)
    errors: list[dict] = []

    # Fetch Alpaca live positions once, share across all helpers
    live_pos_cache = await _build_live_pos_cache()

    # Build errors_window early — used by bots status logic
    log_events: list[dict] = []
    if include_logs:
        log_events = _build_errors_window(window_start, errors)

    # open_positions needed by _build_fleet (positions_total) and _build_bots (positions_count)
    open_positions = _build_open_positions(live_pos_cache, errors)

    fleet         = _build_fleet(open_positions, errors)
    bots          = _build_bots(log_events, open_positions, errors)
    trades_window = _build_trades_window(window_start, errors)
    metrics_30d   = _build_metrics_30d(errors)
    recon_flags   = _build_reconciliation_flags(live_pos_cache, errors)
    decisions     = _build_decisions_pending(window_start, errors)
    exit_attr          = _build_exit_attribution_30d(errors)
    market_state       = _build_market_state(errors)
    walk_forward_status = _build_walk_forward_status(errors)

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    logger.info(f"claude_report | generated in {elapsed_ms}ms | "
                f"bots={len(bots)} open={len(open_positions)} trades={len(trades_window)} "
                f"flags={len(recon_flags)} section_errors={len(errors)}")

    return {
        "generated_at":          _iso(_now()),
        "window_days":           days,
        "response_time_ms":      elapsed_ms,
        "fleet":                 fleet,
        "bots":                  bots,
        "open_positions":        open_positions,
        "trades_window":         trades_window,
        "metrics_30d":           metrics_30d,
        "reconciliation_flags":  recon_flags,
        "errors_window":         log_events if include_logs else None,
        "decisions_pending":     decisions,
        "exit_attribution_30d":  exit_attr,
        "market_state":          market_state,
        "walk_forward_status":   walk_forward_status,
        "_section_errors":       errors,
    }


@router.get("/claude-report.txt", tags=["Claude Report"])
async def claude_report_text(days: int = 1):
    """
    Plain-text version of the Claude report — same data as /claude-report,
    formatted for copy-paste into Claude / Gemini. Triggers file download.
    """
    from starlette.responses import Response as _Resp

    t0           = time.perf_counter()
    days         = min(max(days, 1), _DAYS_CAP)
    window_start = _now() - timedelta(days=days)
    errors: list[dict] = []

    live_pos_cache = await _build_live_pos_cache()
    log_events     = _build_errors_window(window_start, errors)
    open_positions = _build_open_positions(live_pos_cache, errors)
    fleet          = _build_fleet(open_positions, errors)
    bots           = _build_bots(log_events, open_positions, errors)
    trades_window  = _build_trades_window(window_start, errors)
    metrics_30d    = _build_metrics_30d(errors)
    recon_flags    = _build_reconciliation_flags(live_pos_cache, errors)
    decisions      = _build_decisions_pending(window_start, errors)
    exit_attr           = _build_exit_attribution_30d(errors)
    market_state        = _build_market_state(errors)
    walk_forward_status = _build_walk_forward_status(errors)

    report_dict = {
        "generated_at":          _iso(_now()),
        "window_days":           days,
        "fleet":                 fleet,
        "bots":                  bots,
        "open_positions":        open_positions,
        "trades_window":         trades_window,
        "metrics_30d":           metrics_30d,
        "reconciliation_flags":  recon_flags,
        "errors_window":         log_events,
        "decisions_pending":     decisions,
        "exit_attribution_30d":  exit_attr,
        "market_state":          market_state,
        "walk_forward_status":   walk_forward_status,
    }

    body = _format_text(report_dict)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    logger.info(f"claude_report_text | generated in {elapsed_ms}ms | "
                f"lines={body.count(chr(10))} chars={len(body)}")

    return _Resp(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={
            "x-report-lines": str(body.count("\n")),
            "x-report-chars": str(len(body)),
        },
    )
