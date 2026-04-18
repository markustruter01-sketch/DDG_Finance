"""API routes for Bot #7 Poseidon and Bot #8 Kraken Current."""
from __future__ import annotations

import json
import os
from fastapi import APIRouter
from core.metrics import win_rate as _win_rate, win_rate_from_counts as _win_rate_from_counts, profit_factor as _profit_factor, WIN_THRESHOLD as _WIN_THRESHOLD

new_bots_router = APIRouter()

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_POSEIDON_LIVE_STATE = os.path.join(_REPO_ROOT, "poseidon", "poseidon_live_state.json")
_KC_LIVE_STATE = os.path.join(_REPO_ROOT, "kraken-current", "kc_live_state.json")


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


def _read_live_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


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

    eq = float(port[0]["equity_usd"]) if port else 100_000.0
    cash = float(port[0]["cash_usd"]) if port else 100_000.0
    open_pos = int(port[0]["open_positions"]) if port else 0

    total_trades = len(trade_rows)
    total_pnl = sum(float(t.get("net_pnl") or 0) for t in trade_rows)
    wins = sum(1 for t in trade_rows if float(t.get("net_pnl") or 0) > _WIN_THRESHOLD)
    win_rate = _win_rate(trade_rows, "net_pnl")

    paused = bool(hb[0].get("bot_paused")) if hb else False
    status = str(hb[0].get("status") or "INITIALISING") if hb else "INITIALISING"

    # Read live positions from the bot's JSON state file
    live_state = _read_live_state(_POSEIDON_LIVE_STATE)
    live_positions_raw = live_state.get("positions", {})

    # Normalise into a list for the frontend
    open_trades = []
    for ps_id, pos in live_positions_raw.items():
        open_trades.append({
            "pair_set_id": pos.get("pair_set_id"),
            "asset_a": pos.get("asset_a"),
            "asset_b": pos.get("asset_b"),
            "direction": pos.get("direction"),
            "leg_a_side": pos.get("leg_a_side"),
            "leg_b_side": pos.get("leg_b_side"),
            "entry_zscore": pos.get("entry_zscore"),
            "position_value": pos.get("position_value"),
            "total_pnl": pos.get("total_pnl"),
            "leg_a_entry": pos.get("leg_a_entry"),
            "leg_b_entry": pos.get("leg_b_entry"),
            "current_price_a": pos.get("current_price_a"),
            "current_price_b": pos.get("current_price_b"),
            "opened_at": pos.get("opened_at"),
            "fees_paid": pos.get("fees_paid"),
        })

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

    # Poseidon pair stats
    poseidon_pairs = _pg_query("""
        SELECT pair_set_id, asset_a, asset_b, hedge_ratio, hurst, adf_pvalue, is_tradeable
        FROM poseidon_pair_params ORDER BY pair_set_id LIMIT 20
    """)

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
        "poseidon_pairs": poseidon_pairs,
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


@new_bots_router.get("/kraken-current/state")
async def kraken_current_state():
    """Return current state of Bot #8 Kraken Current (trend following)."""
    port = _pg_query("SELECT equity_usd, cash_usd, open_positions FROM kraken_current_portfolio WHERE id = 8")
    hb = _pg_query("SELECT bot_paused, position_count, status FROM kraken_heartbeat WHERE id = 8")
    trade_rows = _pg_query("SELECT pnl_usd FROM kraken_current_trades")
    scan_rows = _pg_query("""
        SELECT DISTINCT ON (symbol) symbol, ema_fast, ema_slow, adx, hurst, direction, passed, block_reason
        FROM kraken_current_signal_scan ORDER BY symbol, scanned_at DESC
    """)
    open_count = int(hb[0].get("position_count") or 0) if hb else 0

    eq = float(port[0]["equity_usd"]) if port else 100_000.0
    cash = float(port[0]["cash_usd"]) if port else 100_000.0

    total_trades = len(trade_rows)
    total_pnl = sum(float(t.get("pnl_usd") or 0) for t in trade_rows)
    wins = sum(1 for t in trade_rows if float(t.get("pnl_usd") or 0) > _WIN_THRESHOLD)
    win_rate = _win_rate(trade_rows, "pnl_usd")

    paused = bool(hb[0].get("bot_paused")) if hb else False
    status = str(hb[0].get("status") or "INITIALISING") if hb else "INITIALISING"

    # Read live positions from the bot's JSON state file
    live_state = _read_live_state(_KC_LIVE_STATE)
    live_positions_raw = live_state.get("positions", {})

    open_positions_list = []
    for sym, pos in live_positions_raw.items():
        open_positions_list.append({
            "symbol": pos.get("symbol", sym),
            "direction": pos.get("direction", "long"),
            "entry_price": pos.get("entry_price"),
            "current_price": pos.get("current_price"),
            "units": pos.get("units"),
            "position_value": pos.get("position_value"),
            "unrealised_pnl": pos.get("unrealised_pnl"),
            "stop_level": pos.get("stop_level"),
            "trailing_active": pos.get("trailing_active"),
            "opened_at": pos.get("opened_at"),
            "fees_paid": pos.get("fees_paid"),
        })

    return {
        "total_equity": eq,
        "paper_equity": eq,
        "cash_usd": cash,
        "open_positions": open_count,
        "open_positions_list": open_positions_list,
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
        "universe_size": 156,
        "ema_fast": 20,
        "ema_slow": 100,
        "adx_threshold": 25,
        "hurst_threshold": 0.5,
        "max_positions": 5,
        "max_hold_days": 21,
        "atr_stop_mult": 2.0,
    }
