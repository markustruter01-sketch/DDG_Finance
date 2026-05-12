"""
performance_report.py — Unified bot performance report.
Replaces the legacy report_sections.py (4,434 lines).
Pulls from bot_registry, bot_portfolio, bots_state, and unified trade tables.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any
import logging
import psycopg2
import psycopg2.extras
import os

from core.bot_registry import all_bots as _registry_all_bots
from core.bot_state import get_all_states, get_all_portfolios

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _now_brisbane_str() -> str:
    from zoneinfo import ZoneInfo
    return _now_utc().astimezone(ZoneInfo("Australia/Brisbane")).strftime("%Y-%m-%d %H:%M:%S %Z")

def _now_utc_str() -> str:
    return _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")

def _h1(title: str) -> list[str]:
    return ["", "=" * 78, f"=== {title}", "=" * 78, ""]

def _h2(title: str) -> list[str]:
    return ["", f"--- {title} ---", ""]

def _fmt_money(value: float | None) -> str:
    if value is None: return "    n/a"
    return f"${value:>11,.2f}"

def _fmt_pct(value: float | None, decimals: int = 1) -> str:
    if value is None: return "  n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:>5.{decimals}f}%"

def _fmt_count(value: int | None, width: int = 5) -> str:
    if value is None: return "  n/a"
    return f"{value:>{width},}"

def _pg_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])

def _query(sql: str, params: tuple = ()) -> list[dict]:
    """Run SELECT, return list of dict rows."""
    try:
        with _pg_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error(f"Report query failed: {exc}")
        return []

# Map canonical bot_id → which trade table to query
TRADE_SOURCES = {
    "oracle":             {"table": "trades",                     "pnl_col": "realized_pnl",  "time_col": "closed_at", "bot_filter": None,
                          "extra_where": "status IN ('Closed_Win','Closed_Loss') AND realized_pnl IS NOT NULL"},
    "spy_qqq_trend":      {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "davy-jones"},
    "jerome_macro":       {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "blackbeard"},
    "sector_rotation":    {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "calypso"},
    "defensive_guardian": {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "apex-predator"},
    "macro_bond":         {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "bot7_macro_bond"},
    "forex_gump":         {"table": "forex_trades",               "pnl_col": "pnl_usd",       "time_col": "exit_time", "bot_filter": "navigator"},
    "poseidon_momentum":  {"table": "poseidon_momentum_trades",   "pnl_col": "net_pnl",       "time_col": "closed_at", "bot_filter": None},
    "kraken_trend":       {"table": "kraken_current_trades",      "pnl_col": "pnl",           "time_col": "closed_at", "bot_filter": None},
}

# Benchmark mapping for return comparison
BENCHMARKS = {
    "oracle": "SPY",
    "spy_qqq_trend": "SPY",
    "jerome_macro": "SPY",
    "sector_rotation": "SPY",
    "defensive_guardian": "SPY",
    "macro_bond": "SPY",
    "forex_gump": "DXY",
    "poseidon_momentum": "BTC",
    "kraken_trend": "BTC",
}


def _trade_metrics(canonical_id: str, days: int | None = None) -> dict:
    """Aggregate trade metrics for a bot. days=None → all-time."""
    src = TRADE_SOURCES.get(canonical_id)
    if not src: return {}

    where_parts = []
    params = []
    if src["bot_filter"]:
        where_parts.append("bot_id = %s")
        params.append(src["bot_filter"])
    where_parts.append(f"{src['time_col']} IS NOT NULL")
    if src.get("extra_where"):
        where_parts.append(src["extra_where"])
    if days is not None:
        where_parts.append(f"{src['time_col']} >= NOW() - INTERVAL %s")
        params.append(f"{days} days")
    where = " WHERE " + " AND ".join(where_parts) if where_parts else ""

    sql = f"""
        SELECT
            COUNT(*) AS trades,
            COUNT(*) FILTER (WHERE {src['pnl_col']} > 0) AS wins,
            COUNT(*) FILTER (WHERE {src['pnl_col']} <= 0) AS losses,
            SUM({src['pnl_col']}) AS total_pnl,
            AVG({src['pnl_col']}) AS avg_pnl,
            AVG({src['pnl_col']}) FILTER (WHERE {src['pnl_col']} > 0) AS avg_win,
            AVG({src['pnl_col']}) FILTER (WHERE {src['pnl_col']} <= 0) AS avg_loss,
            MAX({src['pnl_col']}) AS best,
            MIN({src['pnl_col']}) AS worst,
            MAX({src['time_col']}) AS last_trade
        FROM {src['table']}{where};
    """
    rows = _query(sql, tuple(params))
    if not rows: return {}
    r = rows[0]
    trades = r.get("trades") or 0
    wins = r.get("wins") or 0
    return {
        "trades": trades,
        "wins": wins,
        "losses": r.get("losses") or 0,
        "win_rate": (100.0 * wins / trades) if trades > 0 else None,
        "total_pnl": float(r.get("total_pnl") or 0),
        "avg_pnl": float(r.get("avg_pnl")) if r.get("avg_pnl") is not None else None,
        "avg_win": float(r.get("avg_win")) if r.get("avg_win") is not None else None,
        "avg_loss": float(r.get("avg_loss")) if r.get("avg_loss") is not None else None,
        "best": float(r.get("best")) if r.get("best") is not None else None,
        "worst": float(r.get("worst")) if r.get("worst") is not None else None,
        "expectancy": (float(r.get("avg_pnl")) if r.get("avg_pnl") is not None else None),
        "profit_factor": (
            abs(float(r["avg_win"]) * wins) / abs(float(r["avg_loss"]) * r["losses"])
            if r.get("avg_win") and r.get("avg_loss") and r.get("losses") and float(r["avg_loss"]) < 0
            else None
        ),
        "last_trade": r.get("last_trade").isoformat() if r.get("last_trade") else None,
    }


# ──────────────────────────────────────────────────────────────────────
# Section 1 — Executive Summary
# ──────────────────────────────────────────────────────────────────────

def section_1_executive_summary() -> list[str]:
    lines = _h1("SECTION 1 — EXECUTIVE SUMMARY")

    states = get_all_states()
    portfolios = get_all_portfolios()
    pf_by_id = {p["bot_id"]: p for p in portfolios}

    active = [s for s in states if not s.get("paused", False)]
    paused = [s for s in states if s.get("paused", False)]

    total_equity = sum(float(p.get("equity_usd") or 0) for p in portfolios)
    total_starting = sum(float(p.get("starting_usd") or 0) for p in portfolios)
    total_pnl = total_equity - total_starting

    # Fleet win rate over all-time
    fleet_trades = 0
    fleet_wins = 0
    for bot in _registry_all_bots():
        m = _trade_metrics(bot.id)
        fleet_trades += m.get("trades", 0)
        fleet_wins += m.get("wins", 0)
    fleet_wr = (100.0 * fleet_wins / fleet_trades) if fleet_trades > 0 else None

    lines.append(f"Report generated:  {_now_utc_str()}  /  {_now_brisbane_str()}")
    lines.append(f"Active bots:       {len(active)} / {len(states)}")
    lines.append(f"Paused bots:       {len(paused)}")
    lines.append("")
    lines.append(f"Fleet equity:      {_fmt_money(total_equity)}")
    lines.append(f"Starting capital:  {_fmt_money(total_starting)}")
    lines.append(f"Total P&L:         {_fmt_money(total_pnl)}  ({_fmt_pct((total_pnl/total_starting)*100 if total_starting else 0, 2)})")
    lines.append(f"Fleet win rate:    {_fmt_pct(fleet_wr) if fleet_wr is not None else 'n/a'}  ({fleet_wins:,}W / {fleet_trades - fleet_wins:,}L)")
    lines.append("")

    # Paused bot listing
    if paused:
        lines.append("PAUSED BOTS:")
        for s in paused:
            reason = s.get("pause_reason") or "(no reason recorded)"
            lines.append(f"  - {s['bot_id']:<22} {reason}")
        lines.append("")

    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 2 — Fleet Status Dashboard
# ──────────────────────────────────────────────────────────────────────

def section_2_fleet_dashboard() -> list[str]:
    lines = _h1("SECTION 2 — FLEET STATUS DASHBOARD")
    lines.append(f"Data as of: {_now_utc_str()}")
    lines.append("")

    states = {s["bot_id"]: s for s in get_all_states()}
    portfolios = {p["bot_id"]: p for p in get_all_portfolios()}

    # Header row
    header = f"{'BOT':<22} {'STATUS':<8} {'HB':>6} {'EQUITY':>13} {'P&L':>13} {'PNL%':>7} {'TRADES':>7} {'W/R':>7} {'POS':>4}"
    lines.append(header)
    lines.append("-" * len(header))

    for bot in _registry_all_bots():
        s = states.get(bot.id, {})
        p = portfolios.get(bot.id, {})
        m = _trade_metrics(bot.id)

        status = "PAUSED" if s.get("paused") else "ACTIVE"
        hb = s.get("last_heartbeat")
        if hb:
            if isinstance(hb, str):
                try:
                    from datetime import datetime as _dt
                    hb = _dt.fromisoformat(hb)
                except Exception:
                    hb = None
            if hb:
                mins = (_now_utc() - hb.replace(tzinfo=timezone.utc) if hb.tzinfo is None else _now_utc() - hb).total_seconds() / 60
                hb_str = f"{mins:>4.0f}m"
            else:
                hb_str = "  n/a"
        else:
            hb_str = "  n/a"

        equity = float(p.get("equity_usd") or 0)
        starting = float(p.get("starting_usd") or 100000)
        pnl = equity - starting
        pnl_pct = (pnl / starting * 100) if starting else 0

        positions_count = len(p.get("positions", [])) if isinstance(p.get("positions"), list) else 0

        lines.append(
            f"{bot.display_name:<22} {status:<8} {hb_str:>6} "
            f"{_fmt_money(equity)} {_fmt_money(pnl)} {_fmt_pct(pnl_pct):>7} "
            f"{_fmt_count(m.get('trades'), 7)} "
            f"{_fmt_pct(m.get('win_rate')):>7} "
            f"{positions_count:>4}"
        )

    lines.append("")
    lines.append("Legend: HB=heartbeat age, EQUITY=current, P&L=since starting, POS=open positions")
    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 3 — Per-Bot Deep Dive
# ──────────────────────────────────────────────────────────────────────

def section_3_per_bot_deep_dive() -> list[str]:
    lines = _h1("SECTION 3 — PER-BOT DEEP DIVE")
    lines.append(f"Data as of: {_now_utc_str()}")

    states = {s["bot_id"]: s for s in get_all_states()}
    portfolios = {p["bot_id"]: p for p in get_all_portfolios()}

    for bot in _registry_all_bots():
        lines.extend(_h2(f"{bot.display_name}  ({bot.id})"))

        s = states.get(bot.id, {})
        p = portfolios.get(bot.id, {})
        m_all = _trade_metrics(bot.id)
        m_24h = _trade_metrics(bot.id, days=1)
        m_7d  = _trade_metrics(bot.id, days=7)
        m_30d = _trade_metrics(bot.id, days=30)

        # Strategy + status
        lines.append(f"Strategy:   {bot.strategy_label or 'unspecified'}")
        lines.append(f"Exchange:   {bot.exchange} ({bot.asset_class})")
        lines.append(f"Status:     {'PAUSED — ' + (s.get('pause_reason') or '') if s.get('paused') else 'ACTIVE'}")
        lines.append("")

        # Equity
        equity = float(p.get("equity_usd") or 0)
        cash = float(p.get("cash_usd") or 0)
        starting = float(p.get("starting_usd") or 100000)
        pnl = equity - starting
        lines.append("EQUITY:")
        lines.append(f"  Starting capital:  {_fmt_money(starting)}")
        lines.append(f"  Current equity:    {_fmt_money(equity)}")
        lines.append(f"  Cash:              {_fmt_money(cash)}")
        lines.append(f"  Total P&L:         {_fmt_money(pnl)}  ({_fmt_pct((pnl/starting)*100 if starting else 0, 2)})")
        lines.append("")

        # Performance metrics
        lines.append("PERFORMANCE (all-time):")
        lines.append(f"  Trades:            {m_all.get('trades', 0):,}")
        lines.append(f"  Wins / Losses:     {m_all.get('wins', 0):,} / {m_all.get('losses', 0):,}")
        lines.append(f"  Win rate:          {_fmt_pct(m_all.get('win_rate'))}")
        lines.append(f"  Avg win:           {_fmt_money(m_all.get('avg_win'))}")
        lines.append(f"  Avg loss:          {_fmt_money(m_all.get('avg_loss'))}")
        lines.append(f"  Best trade:        {_fmt_money(m_all.get('best'))}")
        lines.append(f"  Worst trade:       {_fmt_money(m_all.get('worst'))}")
        lines.append(f"  Expectancy/trade:  {_fmt_money(m_all.get('expectancy'))}")
        lines.append(f"  Profit factor:     {m_all.get('profit_factor', 0):.2f}" if m_all.get('profit_factor') else "  Profit factor:     n/a")
        lines.append("")

        # Recent activity
        lines.append("RECENT ACTIVITY:")
        lines.append(f"  Last 24h:          {m_24h.get('trades', 0):,} trades, P&L {_fmt_money(m_24h.get('total_pnl', 0))}")
        lines.append(f"  Last 7d:           {m_7d.get('trades', 0):,} trades, P&L {_fmt_money(m_7d.get('total_pnl', 0))}")
        lines.append(f"  Last 30d:          {m_30d.get('trades', 0):,} trades, P&L {_fmt_money(m_30d.get('total_pnl', 0))}")
        lines.append(f"  Last trade at:     {m_all.get('last_trade') or 'never'}")
        lines.append("")

        # Open positions
        positions = p.get("positions", [])
        if isinstance(positions, list) and positions:
            lines.append(f"OPEN POSITIONS ({len(positions)}):")
            for pos in positions[:10]:
                sym = pos.get("symbol", "?")
                side = pos.get("side", pos.get("direction", "?"))
                entry = (pos.get("entry_price")
                         or pos.get("entry")
                         or pos.get("entry_usd")
                         or 0)
                val = (pos.get("size_usd")
                       or pos.get("value_usd")
                       or pos.get("position_usd")
                       or pos.get("position_value")
                       or 0)
                units = (pos.get("size_units")
                         or pos.get("units")
                         or pos.get("size")
                         or 0)
                lines.append(
                    f"  {sym:<14} {side:<6} entry={entry:<14} "
                    f"size={units:<14} value=${val:,.2f}"
                )
            if len(positions) > 10:
                lines.append(f"  ... +{len(positions) - 10} more")
        else:
            lines.append("OPEN POSITIONS: none")
        lines.append("")

        # Behavior check
        lines.append("BEHAVIOR CHECK:")
        if m_all.get("trades", 0) == 0:
            lines.append("  No closed trades yet — nothing to verify.")
        else:
            wr = m_all.get("win_rate") or 0
            pf = m_all.get("profit_factor") or 0
            if wr < 30 and pf < 1.0:
                lines.append("  ⚠ LOW WIN RATE + LOW PROFIT FACTOR — strategy may be unsuited to current conditions.")
            elif wr < 30 and pf >= 1.5:
                lines.append("  ✓ Low win rate but high profit factor — consistent with trend-following design.")
            elif wr >= 50 and pf < 1.0:
                lines.append("  ⚠ High win rate but losing money — losses larger than wins. Check stop placement.")
            else:
                lines.append(f"  ✓ Win rate {wr:.1f}% / profit factor {pf:.2f} — within expected ranges.")
        lines.append("")

    return lines


# ──────────────────────────────────────────────────────────────────────
# Master generator (sections 1-3 only for now; 4-9 in subsequent prompts)
# ──────────────────────────────────────────────────────────────────────

def generate_performance_report() -> str:
    """Generate full bot performance report. Returns plain text."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("BOT PERFORMANCE REPORT  —  QUANT TERMINAL")
    lines.append("=" * 78)

    try:
        lines.extend(section_1_executive_summary())
    except Exception as exc:
        lines.extend(["", "[Section 1 failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_2_fleet_dashboard())
    except Exception as exc:
        lines.extend(["", "[Section 2 failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_3_per_bot_deep_dive())
    except Exception as exc:
        lines.extend(["", "[Section 3 failed]", f"Error: {exc}", ""])

    lines.append("")
    lines.append("=" * 78)
    lines.append("END OF REPORT (sections 1-3 of 9 — sections 4-9 pending build)")
    lines.append("=" * 78)

    return "\n".join(lines)
