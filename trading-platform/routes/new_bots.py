"""API routes for Bot #7 Poseidon and Bot #8 Kraken Current."""
from __future__ import annotations

import os
from fastapi import APIRouter

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


@new_bots_router.get("/poseidon/state")
async def poseidon_state():
    """Return current state of Bot #7 Poseidon (pairs trading)."""
    port = _pg_query("SELECT equity_usd, cash_usd, open_positions FROM poseidon_portfolio WHERE id = 7")
    hb = _pg_query("SELECT bot_paused, position_count, status, circuit_breaker FROM kraken_heartbeat WHERE id = 7")
    trade_rows = _pg_query("SELECT net_pnl FROM poseidon_trades")
    pair_params = _pg_query("""
        SELECT pair_set_id, asset_a, asset_b, hedge_ratio, hurst, adf_pvalue, is_tradeable
        FROM poseidon_pair_params ORDER BY pair_set_id
    """)
    open_trades = _pg_query("""
        SELECT pair_set_id, asset_a, asset_b, direction, entry_zscore, opened_at
        FROM poseidon_trades WHERE closed_at IS NULL
    """)

    eq = float(port[0]["equity_usd"]) if port else 100_000.0
    cash = float(port[0]["cash_usd"]) if port else 100_000.0
    open_pos = int(port[0]["open_positions"]) if port else 0

    wins = sum(1 for t in trade_rows if float(t.get("net_pnl") or 0) > 0)
    total_trades = len(trade_rows)
    total_pnl = sum(float(t.get("net_pnl") or 0) for t in trade_rows)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else None

    paused = bool(hb[0].get("bot_paused")) if hb else False
    status = str(hb[0].get("status") or "INITIALISING") if hb else "INITIALISING"

    return {
        "total_equity": eq,
        "paper_equity": eq,
        "cash_usd": cash,
        "open_positions": open_pos,
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "total_wins": wins,
        "win_rate": win_rate,
        "paused": paused,
        "status": status,
        "pair_params": pair_params,
        "open_trades": open_trades,
        "starting_capital": 100_000.0,
        "strategy": "Statistical Arbitrage / Pairs Trading",
        "cycle_minutes": 15,
        "max_pairs": 3,
        "zscore_entry": 2.0,
        "zscore_exit": 0.3,
        "zscore_stop": 3.5,
        "hurst_threshold": 0.5,
        "adf_pvalue_threshold": 0.10,
    }


@new_bots_router.get("/kraken-current/state")
async def kraken_current_state():
    """Return current state of Bot #8 Kraken Current (trend following)."""
    port = _pg_query("SELECT equity_usd, cash_usd, open_positions FROM kraken_current_portfolio WHERE id = 8")
    hb = _pg_query("SELECT bot_paused, position_count, status FROM kraken_heartbeat WHERE id = 8")
    trade_rows = _pg_query("SELECT pnl FROM kraken_current_trades")
    scan_rows = _pg_query("""
        SELECT DISTINCT ON (symbol) symbol, ema_fast, ema_slow, adx, hurst, direction, passed, block_reason
        FROM kraken_current_signal_scan ORDER BY symbol, scanned_at DESC
    """)
    open_count = int(hb[0].get("position_count") or 0) if hb else 0

    eq = float(port[0]["equity_usd"]) if port else 100_000.0
    cash = float(port[0]["cash_usd"]) if port else 100_000.0

    wins = sum(1 for t in trade_rows if float(t.get("pnl") or 0) > 0)
    total_trades = len(trade_rows)
    total_pnl = sum(float(t.get("pnl") or 0) for t in trade_rows)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else None

    paused = bool(hb[0].get("bot_paused")) if hb else False
    status = str(hb[0].get("status") or "INITIALISING") if hb else "INITIALISING"

    return {
        "total_equity": eq,
        "paper_equity": eq,
        "cash_usd": cash,
        "open_positions": open_count,
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "total_wins": wins,
        "win_rate": win_rate,
        "paused": paused,
        "status": status,
        "signal_scan": scan_rows,
        "starting_capital": 100_000.0,
        "strategy": "Trend Following / EMA Crossover + ADX",
        "cycle_hours": 4,
        "universe_size": 10,
        "ema_fast": 20,
        "ema_slow": 100,
        "adx_threshold": 25,
        "hurst_threshold": 0.5,
        "max_positions": 5,
        "max_hold_days": 21,
        "atr_stop_mult": 2.0,
    }
