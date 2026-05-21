"""API route for pair-learning data."""
from __future__ import annotations

import os

from fastapi import APIRouter
from loguru import logger
from core.metrics import win_rate_from_counts as _win_rate_from_counts, WIN_THRESHOLD as _WIN_THRESHOLD

new_bots_router = APIRouter()



def _pg_query(sql: str, params: tuple = ()):
    try:
        import psycopg2, psycopg2.extras
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return []
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []



@new_bots_router.get("/pair-learning")
async def pair_learning():
    """Python rule-based learning journal — per-symbol Hurst, ADF, win rates, pauses."""

    # Per-symbol stats from pair performance table
    perf_rows = _pg_query("""
        SELECT bot_id, symbol, hurst_current, adf_pvalue_current,
               status, pause_until, pause_reason, updated_at
        FROM kraken_pair_performance
        ORDER BY bot_id, symbol
    """)

    # Aggregate win rates from kraken_trades per bot+symbol.
    # Threshold matches core.metrics.WIN_THRESHOLD — passed as parameter to stay in sync.
    trade_rows = _pg_query(
        """
        SELECT bot_id, symbol,
               COUNT(*) FILTER (WHERE pnl_usd > %s) AS wins,
               COUNT(*) AS total,
               SUM(pnl_usd) AS total_pnl,
               MAX(closed_at) AS last_trade_at
        FROM kraken_trades
        WHERE closed_at IS NOT NULL
        GROUP BY bot_id, symbol
        ORDER BY bot_id, symbol
        """,
        (_WIN_THRESHOLD,)
    )

    # Build win-rate lookup: (bot_id, symbol) -> stats
    wr_lookup: dict = {}
    for t in trade_rows:
        key = (t["bot_id"], t["symbol"])
        wr_lookup[key] = {
            "wins": int(t["wins"] or 0),
            "total": int(t["total"] or 0),
            "total_pnl": float(t["total_pnl"] or 0),
            "last_trade_at": str(t["last_trade_at"]) if t["last_trade_at"] else None,
        }

    # Merge into symbol records
    symbols = []
    for row in perf_rows:
        bot_id = row["bot_id"]
        symbol = row["symbol"]
        wr = wr_lookup.get((bot_id, symbol), {})
        wins = wr.get("wins", 0)
        total = wr.get("total", 0)
        symbols.append({
            "bot_id": bot_id,
            "symbol": symbol,
            "hurst": float(row["hurst_current"]) if row["hurst_current"] is not None else None,
            "adf_pvalue": float(row["adf_pvalue_current"]) if row["adf_pvalue_current"] is not None else None,
            "status": row["status"],
            "pause_until": str(row["pause_until"]) if row["pause_until"] else None,
            "pause_reason": row["pause_reason"],
            "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
            "wins": wins,
            "losses": total - wins,
            "total_trades": total,
            "win_rate": _win_rate_from_counts(wins, total),
            "total_pnl": wr.get("total_pnl", 0),
            "last_trade_at": wr.get("last_trade_at"),
        })

    # Fleet-wide symbol summary (deduplicated across bots)
    unique_symbols: dict[str, dict] = {}
    for s in symbols:
        sym = s["symbol"]
        if sym not in unique_symbols:
            unique_symbols[sym] = {
                "symbol": sym,
                "avg_hurst": None,
                "avg_adf_pvalue": None,
                "total_wins": 0,
                "total_losses": 0,
                "total_pnl": 0,
                "any_paused": False,
                "pause_reason": None,
                "bot_count": 0,
            }
        u = unique_symbols[sym]
        u["total_wins"] += s["wins"]
        u["total_losses"] += s["losses"]
        u["total_pnl"] += s["total_pnl"]
        u["bot_count"] += 1
        if s["hurst"] is not None:
            u["avg_hurst"] = ((u["avg_hurst"] or 0) + s["hurst"]) / 1 if u["avg_hurst"] is None else (u["avg_hurst"] * (u["bot_count"] - 1) + s["hurst"]) / u["bot_count"]
        if s["adf_pvalue"] is not None:
            u["avg_adf_pvalue"] = s["adf_pvalue"] if u["avg_adf_pvalue"] is None else (u["avg_adf_pvalue"] + s["adf_pvalue"]) / 2
        if s["status"] == "paused":
            u["any_paused"] = True
            u["pause_reason"] = s["pause_reason"]

    fleet_symbols = sorted(unique_symbols.values(), key=lambda x: (not x["any_paused"], -(x.get("avg_hurst") or 0)))

    # Adaptive parameters per bot (self-tuning)
    adaptive_rows = _pg_query("""
        SELECT bot_id, params, metrics, reasons, adapted_at, lookback_n
        FROM kraken_adaptive_params ORDER BY bot_id
    """)
    adaptive_params = []
    for a in adaptive_rows:
        adaptive_params.append({
            "bot_id": a["bot_id"],
            "params": a["params"] or {},
            "metrics": a["metrics"] or {},
            "reasons": a["reasons"] or {},
            "adapted_at": str(a["adapted_at"]) if a["adapted_at"] else None,
            "lookback_n": int(a["lookback_n"] or 0),
        })

    # Recent trades feed (last 20 across all 3 bots)
    recent_trades = _pg_query("""
        SELECT bot_id, symbol, side, pnl_usd, closed_at
        FROM kraken_trades
        WHERE closed_at IS NOT NULL
        ORDER BY closed_at DESC
        LIMIT 20
    """)
    recent_trades_list = []
    for t in recent_trades:
        recent_trades_list.append({
            "bot_id": t["bot_id"],
            "symbol": t["symbol"],
            "side": t["side"],
            "pnl_usd": float(t["pnl_usd"] or 0),
            "closed_at": str(t["closed_at"]) if t["closed_at"] else None,
        })

    # Fleet-level counts (unique symbols)
    paused_syms = set(s["symbol"] for s in symbols if s["status"] == "paused")
    active_syms = set(s["symbol"] for s in symbols if s["status"] == "active") - paused_syms
    total_syms = active_syms | paused_syms

    # Total trade count across ALL bots: Kraken trades + Alpaca journal (Oracle)
    kraken_count_rows = _pg_query("SELECT COUNT(*) AS cnt FROM kraken_trades WHERE closed_at IS NOT NULL")
    alpaca_count_rows = _pg_query(
        "SELECT COUNT(*) AS cnt FROM trade_journal WHERE status IN ('Closed_Win','Closed_Loss','Closed')"
    )
    kraken_total = int(kraken_count_rows[0]["cnt"] or 0) if kraken_count_rows else 0
    alpaca_total = int(alpaca_count_rows[0]["cnt"] or 0) if alpaca_count_rows else 0
    total_trade_count = kraken_total + alpaca_total

    return {
        "symbols": symbols,
        "fleet_symbols": fleet_symbols,
        "adaptive_params": adaptive_params,
        "recent_trades": recent_trades_list,
        "total_symbols": len(total_syms),
        "paused_count": len(paused_syms),
        "active_count": len(active_syms),
        "bot_slot_total": len(symbols),
        "bot_slot_paused": sum(1 for s in symbols if s["status"] == "paused"),
        "bot_slot_active": sum(1 for s in symbols if s["status"] == "active"),
        "total_trade_count": total_trade_count,
        "kraken_trade_count": kraken_total,
        "alpaca_trade_count": alpaca_total,
    }

