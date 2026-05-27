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
    "forex_gump":    "oanda_navigator",
    "momentum_alpha": "kucoin",
    "momentum_beta":  "kucoin",
    "momentum_gamma": "kucoin",
    "depeg_hunter":  "stable_monitor",
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
        "momentum_alpha": "momentum_alpha",
        "momentum_beta":  "momentum_beta",
        "momentum_gamma": "momentum_gamma",
        "depeg": "depeg_hunter",
        "forex":  "forex_gump",
        "navigator": "forex_gump",
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
        elif bot_id == "forex_gump":
            result = _pg_scalar(
                "SELECT GREATEST(MAX(entry_time), MAX(exit_time)) FROM forex_trades WHERE bot_id = %s",
                ("navigator",),
            )
        elif bot_id in ("momentum_alpha", "momentum_beta", "momentum_gamma"):
            result = _pg_scalar(
                "SELECT GREATEST(MAX(opened_at), MAX(closed_at)) FROM momentum_bot_trades WHERE bot_id = %s",
                (bot_id,),
            )
        elif bot_id == "depeg_hunter":
            result = _pg_scalar(
                "SELECT GREATEST(MAX(entry_time), MAX(exit_time)) FROM depeg_hunter_trades"
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
            elif stale_mins is not None and stale_mins > _STALE_MINUTES and bid != "depeg_hunter":
                status = "STALE"
            elif bid == "depeg_hunter":
                status = "IDLE_BY_DESIGN"
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
    try:
        spy_live = {p["symbol"]: p for p in live_pos_cache.get("alpaca_PA3X9UBVZ6T8", [])}
        rows = _pg_rows(
            "SELECT symbol, direction, qty, entry_price, stop_price, opened_at "
            "FROM alpaca_etf_positions WHERE bot_id = %s AND status = 'open'",
            ("bot2_spy_qqq",),
        )
        for r in rows:
            sym  = r["symbol"]
            live = spy_live.get(sym, {})
            opened_at = _tz(r["opened_at"])
            days_held = (now - opened_at).days if opened_at else None
            urpc = live.get("unrealized_plpc")
            positions.append({
                "bot_id": "spy_qqq_trend", "symbol": sym, "direction": r["direction"],
                "qty":           float(r["qty"] or 0),
                "entry_price":   float(r["entry_price"] or 0),
                "current_price": live.get("current_price"),
                "unrealised_pnl_usd": live.get("unrealized_pl"),
                "unrealised_pnl_pct": round(urpc * 100, 4) if urpc is not None else None,
                "days_held":    days_held,
                "trailing_stop": float(r["stop_price"]) if r["stop_price"] else None,
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

    # Momentum — momentum_bot_trades (status=open)
    try:
        rows = _pg_rows(
            "SELECT bot_id, symbol, direction, qty, entry_price, entry_reason, opened_at "
            "FROM momentum_bot_trades WHERE status = 'open'"
        )
        for r in rows:
            opened_at = _tz(r["opened_at"])
            days_held = (now - opened_at).days if opened_at else None
            positions.append({
                "bot_id": r["bot_id"], "symbol": r["symbol"], "direction": r["direction"],
                "qty":           float(r["qty"] or 0),
                "entry_price":   float(r["entry_price"] or 0),
                "current_price": None,
                "unrealised_pnl_usd": None,
                "unrealised_pnl_pct": None,
                "days_held":    days_held,
                "trailing_stop": None,
                "entry_reason":  r.get("entry_reason"),
                "asset_class":   "momentum_crypto",
            })
    except Exception as exc:
        errors.append({"section": "open_positions.momentum", "error": str(exc)})

    # Forex — forex_trades (status=open, bot_id=navigator)
    try:
        rows = _pg_rows(
            "SELECT pair, direction, units, entry_price, sl_price, llm_thesis, entry_time "
            "FROM forex_trades WHERE status = 'open' AND bot_id = %s",
            ("navigator",),
        )
        for r in rows:
            entry_time = _tz(r["entry_time"])
            days_held  = (now - entry_time).days if entry_time else None
            positions.append({
                "bot_id": "forex_gump", "symbol": r["pair"], "direction": r["direction"],
                "qty":           float(r["units"] or 0),
                "entry_price":   float(r["entry_price"] or 0),
                "current_price": None,
                "unrealised_pnl_usd": None,
                "unrealised_pnl_pct": None,
                "days_held":    days_held,
                "trailing_stop": float(r["sl_price"]) if r["sl_price"] else None,
                "entry_reason":  (r.get("llm_thesis") or "")[:80] or None,
                "asset_class":   "forex",
            })
    except Exception as exc:
        errors.append({"section": "open_positions.forex_gump", "error": str(exc)})

    # Depeg hunter — depeg_hunter_trades (exit_time IS NULL)
    try:
        rows = _pg_rows(
            "SELECT stable, units, entry_price, severity, entry_time "
            "FROM depeg_hunter_trades WHERE exit_time IS NULL"
        )
        for r in rows:
            entry_time = _tz(r["entry_time"])
            days_held  = (now - entry_time).days if entry_time else None
            positions.append({
                "bot_id": "depeg_hunter", "symbol": r["stable"], "direction": "short",
                "qty":           float(r["units"] or 0),
                "entry_price":   float(r["entry_price"] or 0),
                "current_price": None,
                "unrealised_pnl_usd": None,
                "unrealised_pnl_pct": None,
                "days_held":    days_held,
                "trailing_stop": None,
                "entry_reason":  f"depeg_severity={r.get('severity', '?')}",
                "asset_class":   "stablecoin_arbitrage",
            })
    except Exception as exc:
        errors.append({"section": "open_positions.depeg_hunter", "error": str(exc)})

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

    # Momentum
    try:
        rows = _pg_rows(
            """SELECT bot_id, symbol, direction, qty::float,
                      entry_price::float, exit_price::float,
                      opened_at, closed_at, realised_pnl_usd::float,
                      exit_reason, status
               FROM momentum_bot_trades
               WHERE (closed_at >= %s OR (status = 'open' AND opened_at >= %s))
               ORDER BY COALESCE(closed_at, opened_at) DESC""",
            (window_start, window_start),
        )
        for r in rows:
            trades.append(_trade_row(
                r["bot_id"], r["symbol"], r["direction"],
                r["qty"], r["entry_price"], r["exit_price"],
                r["opened_at"], r["closed_at"], r["realised_pnl_usd"],
                r["exit_reason"], "momentum_crypto", r["status"],
            ))
    except Exception as exc:
        errors.append({"section": "trades_window.momentum", "error": str(exc)})

    # Forex
    try:
        rows = _pg_rows(
            """SELECT pair, direction, units::float AS qty,
                      entry_price::float, exit_price::float,
                      entry_time AS opened_at, exit_time AS closed_at,
                      pnl_usd::float AS realised_pnl_usd, status
               FROM forex_trades
               WHERE bot_id = %s
                 AND (exit_time >= %s OR (status = 'open' AND entry_time >= %s))
               ORDER BY COALESCE(exit_time, entry_time) DESC""",
            ("navigator", window_start, window_start),
        )
        for r in rows:
            trades.append(_trade_row(
                "forex_gump", r["pair"], r["direction"],
                r["qty"], r["entry_price"], r["exit_price"],
                r["opened_at"], r["closed_at"], r["realised_pnl_usd"],
                None, "forex", r["status"],
            ))
    except Exception as exc:
        errors.append({"section": "trades_window.forex_gump", "error": str(exc)})

    # Depeg hunter
    try:
        rows = _pg_rows(
            """SELECT stable AS symbol, units::float AS qty,
                      entry_price::float, exit_price::float,
                      entry_time AS opened_at, exit_time AS closed_at,
                      pnl_usd::float AS realised_pnl_usd, reason AS exit_reason
               FROM depeg_hunter_trades
               WHERE (exit_time >= %s OR (exit_time IS NULL AND entry_time >= %s))
               ORDER BY COALESCE(exit_time, entry_time) DESC""",
            (window_start, window_start),
        )
        for r in rows:
            status = "open" if r["closed_at"] is None else "closed"
            trades.append(_trade_row(
                "depeg_hunter", r["symbol"], None,
                r["qty"], r["entry_price"], r["exit_price"],
                r["opened_at"], r["closed_at"], r["realised_pnl_usd"],
                r["exit_reason"], "stablecoin_arbitrage", status,
            ))
    except Exception as exc:
        errors.append({"section": "trades_window.depeg_hunter", "error": str(exc)})

    return trades

# ── Section: metrics_30d ───────────────────────────────────────────────────────

def _build_metrics_30d(errors: list) -> list[dict]:
    import statistics as _stats
    thirty_days_ago = _now() - timedelta(days=30)

    _sources = [
        {
            "bot_id": "oracle",
            "sql": """SELECT realized_pnl AS pnl FROM trades
                      WHERE asset_class = 'momentum_equity'
                        AND status NOT IN ('Active') AND closed_at >= %s""",
        },
        {
            "bot_id": "spy_qqq_trend",
            "sql": """SELECT realised_pnl::float AS pnl FROM alpaca_etf_positions
                      WHERE bot_id = 'bot2_spy_qqq' AND status = 'closed' AND closed_at >= %s""",
        },
        {
            "bot_id": "jerome_macro",
            "sql": """SELECT realised_pnl_usd AS pnl FROM jerome_positions
                      WHERE status = 'closed' AND closed_at >= %s""",
        },
        {
            "bot_id": "forex_gump",
            "sql": """SELECT pnl_usd AS pnl FROM forex_trades
                      WHERE bot_id = 'navigator' AND status != 'open' AND exit_time >= %s""",
        },
        {
            "bot_id": "depeg_hunter",
            "sql": "SELECT pnl_usd AS pnl FROM depeg_hunter_trades WHERE exit_time >= %s",
        },
        {
            "bot_id": "momentum_alpha",
            "sql": "SELECT realised_pnl_usd::float AS pnl FROM momentum_bot_trades WHERE bot_id='momentum_alpha' AND status='closed' AND closed_at >= %s",
        },
        {
            "bot_id": "momentum_beta",
            "sql": "SELECT realised_pnl_usd::float AS pnl FROM momentum_bot_trades WHERE bot_id='momentum_beta' AND status='closed' AND closed_at >= %s",
        },
        {
            "bot_id": "momentum_gamma",
            "sql": "SELECT realised_pnl_usd::float AS pnl FROM momentum_bot_trades WHERE bot_id='momentum_gamma' AND status='closed' AND closed_at >= %s",
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
# depeg_hunter intentionally excluded — idle is its normal state.
_BOT_STALE_THRESHOLDS: dict[str, int] = {
    "oracle":          108000,  # 30h — covers weekends and market holidays
    "spy_qqq_trend":   108000,  # 30h — same
    "jerome_macro":     50000,  # ~14h, between 09:00 and 21:00 UTC cycles
    "forex_gump":        5400,  # 90 min
    "momentum_alpha":   94000,  # ~26h, daily 00:05 UTC cycle
    "momentum_beta":    94000,  # same
    "momentum_gamma":   94000,  # same
}


def _build_stale_flags(errors: list) -> list[dict]:
    """Check bot_portfolio.last_updated against per-bot thresholds.

    Emits a HIGH severity entry to system_degradations on stale detection
    AND returns the flag for inclusion in the report.  Dual emission means
    stale bots appear in both errors_window AND reconciliation_flags.
    """
    flags: list[dict] = []
    try:
        rows = _pg_rows(
            "SELECT bot_id, last_updated, "
            "EXTRACT(EPOCH FROM (NOW() - last_updated)) AS age_s "
            "FROM bot_portfolio WHERE bot_id = ANY(%s)",
            (list(_BOT_STALE_THRESHOLDS.keys()),),
        )
        for r in rows:
            age_s = r.get("age_s")
            if age_s is None:
                continue
            age_s = float(age_s)
            bot_id = r["bot_id"]
            threshold = _BOT_STALE_THRESHOLDS[bot_id]
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
         "SELECT COUNT(*) FROM alpaca_etf_positions WHERE bot_id='bot2_spy_qqq' AND status='open'",
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
            "FROM jerome_groq_decisions WHERE entries_count > 0 ORDER BY decided_at DESC LIMIT 20"
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
        "SELECT exit_reason, realised_pnl_usd::float AS pnl FROM jerome_positions "
        "WHERE status='closed' AND closed_at >= %s",
        (thirty_days_ago,),
    )
    _collect(
        "SELECT exit_reason, realised_pnl_usd::float AS pnl FROM momentum_bot_trades "
        "WHERE status='closed' AND closed_at >= %s",
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
    exit_attr     = _build_exit_attribution_30d(errors)

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
        "_section_errors":       errors,
    }
