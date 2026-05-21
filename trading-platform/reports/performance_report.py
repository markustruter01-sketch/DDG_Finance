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
    "oracle":             {"table": "trades",                     "pnl_col": "realized_pnl",  "time_col": "date",      "bot_filter": None,
                          "extra_where": "status IN ('Closed_Win','Closed_Loss') AND realized_pnl IS NOT NULL"},
    "spy_qqq_trend":      {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "davy-jones"},
    "jerome_macro":       {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "blackbeard"},
    "sector_rotation":    {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "calypso"},
    "defensive_guardian": {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "apex-predator"},
    "macro_bond":         {"table": "kraken_trades",              "pnl_col": "pnl_usd",       "time_col": "closed_at", "bot_filter": "bot7_macro_bond"},
    "forex_gump":         {"table": "forex_trades",               "pnl_col": "pnl_usd",       "time_col": "exit_time", "bot_filter": "navigator"},
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
}


def _trade_metrics(bot_id: str, days: int | None = None) -> dict:
    """Aggregate trade metrics for a canonical bot_id from the bot_trades view.
    days=None → all-time. Replaces per-table TRADE_SOURCES dispatch (R5).
    """
    where_parts = ["bot_id = %s"]
    params: list = [bot_id]
    if days is not None:
        where_parts.append("closed_at >= NOW() - INTERVAL %s")
        params.append(f"{days} days")
    where_clause = " WHERE " + " AND ".join(where_parts)

    sql = f"""
        SELECT
            COUNT(*)                                                 AS trades,
            COUNT(*) FILTER (WHERE pnl_usd > 0)                     AS wins,
            COUNT(*) FILTER (WHERE pnl_usd < 0)                     AS losses,
            COALESCE(SUM(pnl_usd), 0)                               AS total_pnl,
            AVG(pnl_usd) FILTER (WHERE pnl_usd > 0)                 AS avg_win,
            AVG(pnl_usd) FILTER (WHERE pnl_usd < 0)                 AS avg_loss,
            MAX(pnl_usd)                                             AS best,
            MIN(pnl_usd)                                             AS worst,
            AVG(pnl_usd)                                             AS expectancy,
            SUM(pnl_usd) FILTER (WHERE pnl_usd > 0)                 AS gross_win,
            ABS(SUM(pnl_usd) FILTER (WHERE pnl_usd < 0))            AS gross_loss,
            MAX(closed_at)                                           AS last_trade
        FROM bot_trades
        {where_clause};
    """
    rows = _query(sql, tuple(params))
    if not rows:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": None,
                "total_pnl": 0.0, "avg_win": None, "avg_loss": None,
                "best": None, "worst": None, "expectancy": None,
                "profit_factor": None, "last_trade": None}
    r = rows[0]
    trades = r.get("trades") or 0
    wins = r.get("wins") or 0
    losses = r.get("losses") or 0
    gross_win = r.get("gross_win") or 0
    gross_loss = r.get("gross_loss") or 0

    win_rate = (100.0 * wins / trades) if trades > 0 else None
    profit_factor = (
        (gross_win / gross_loss) if gross_loss > 0
        else (None if gross_win == 0 else float("inf"))
    )
    last_trade = r.get("last_trade")
    if last_trade and not isinstance(last_trade, str):
        last_trade = last_trade.isoformat()

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": float(r.get("total_pnl") or 0),
        "avg_win": float(r["avg_win"]) if r.get("avg_win") is not None else None,
        "avg_loss": float(r["avg_loss"]) if r.get("avg_loss") is not None else None,
        "best": float(r["best"]) if r.get("best") is not None else None,
        "worst": float(r["worst"]) if r.get("worst") is not None else None,
        "expectancy": float(r["expectancy"]) if r.get("expectancy") is not None else None,
        "profit_factor": profit_factor,
        "last_trade": last_trade,
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

    paused_ids = {s["bot_id"] for s in states if s.get("paused")}
    active_ids = {s["bot_id"] for s in states if not s.get("paused")}

    active_equity   = sum(float(p.get("equity_usd")  or 0) for p in portfolios if p["bot_id"] in active_ids)
    active_starting = sum(float(p.get("starting_usd") or 0) for p in portfolios if p["bot_id"] in active_ids)
    paused_equity   = sum(float(p.get("equity_usd")  or 0) for p in portfolios if p["bot_id"] in paused_ids)
    paused_starting = sum(float(p.get("starting_usd") or 0) for p in portfolios if p["bot_id"] in paused_ids)
    total_equity   = active_equity  + paused_equity
    total_starting = active_starting + paused_starting

    active_pnl = active_equity - active_starting
    paused_pnl = paused_equity - paused_starting

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
    lines.append("FLEET EQUITY:")
    lines.append(f"  Total equity:           {_fmt_money(total_equity)}")
    lines.append(f"  Total starting:         {_fmt_money(total_starting)}")
    lines.append(f"  Total P&L:              {_fmt_money(total_equity - total_starting)}  ({_fmt_pct(((total_equity - total_starting) / total_starting) * 100 if total_starting else 0, 2)})")
    lines.append("")
    lines.append("ACTIVE BOTS (where current trading happens):")
    lines.append(f"  Equity:                 {_fmt_money(active_equity)}")
    lines.append(f"  Starting:               {_fmt_money(active_starting)}")
    lines.append(f"  Current P&L:            {_fmt_money(active_pnl)}  ({_fmt_pct((active_pnl / active_starting) * 100 if active_starting else 0, 2)})")
    lines.append("")
    lines.append("PAUSED BOTS (legacy P&L, not current):")
    lines.append(f"  Equity:                 {_fmt_money(paused_equity)}")
    lines.append(f"  Starting:               {_fmt_money(paused_starting)}")
    lines.append(f"  Legacy P&L:             {_fmt_money(paused_pnl)}  ({_fmt_pct((paused_pnl / paused_starting) * 100 if paused_starting else 0, 2)})")
    lines.append("")
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

        # Reconciliation: does bot_portfolio equity match sum of closed P&L?
        trade_pnl_sum = m_all.get("total_pnl", 0) or 0
        portfolio_pnl = equity - starting
        reconciliation_delta = portfolio_pnl - trade_pnl_sum

        if abs(reconciliation_delta) > 50 and m_all.get("trades", 0) > 0:
            lines.append("RECONCILIATION:")
            lines.append(f"  Portfolio P&L:     {_fmt_money(portfolio_pnl)}")
            lines.append(f"  Sum of trade P&L:  {_fmt_money(trade_pnl_sum)}")
            lines.append(f"  Δ Discrepancy:     {_fmt_money(reconciliation_delta)}")
            if abs(reconciliation_delta) > 500:
                lines.append(f"  🔴 LARGE DISCREPANCY — portfolio and trade history disagree by ${abs(reconciliation_delta):.0f}")
                lines.append(f"      → portfolio likely not being updated, OR closed P&L not flowing to portfolio")
            else:
                lines.append(f"  ⚠ Minor discrepancy — open position unrealised P&L can explain small gaps")
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
        trades = m_all.get("trades", 0)
        wr = m_all.get("win_rate") or 0
        pf = m_all.get("profit_factor")
        if trades == 0:
            lines.append("  No closed trades yet — nothing to verify.")
        elif pf is None:
            lines.append(f"  🔴 NO WINNERS — {trades} trades, {wr:.1f}% win rate. Strategy producing zero profitable trades.")
        elif pf < 0.7:
            lines.append(f"  🔴 SEVERELY LOSING — profit factor {pf:.2f}. Losing $1.40+ for every $1 won.")
        elif pf < 1.0:
            lines.append(f"  ⚠ LOSING — profit factor {pf:.2f} below 1.0. Losses outpacing wins.")
        elif pf < 1.2 and wr < 40:
            lines.append(f"  ⚠ MARGINAL — profit factor {pf:.2f} barely positive. Watch closely.")
        elif wr < 30 and pf >= 1.5:
            lines.append(f"  ✓ Low WR ({wr:.1f}%) high PF ({pf:.2f}) — typical trend-follower signature.")
        elif wr >= 50 and pf >= 1.5:
            lines.append(f"  ✓ Strong — WR {wr:.1f}%, PF {pf:.2f}. Wins consistent and meaningful.")
        else:
            lines.append(f"  ✓ Profitable — WR {wr:.1f}%, PF {pf:.2f}. Above breakeven.")
        lines.append("")

    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 3.5 — Bot Comparison Matrix
# ──────────────────────────────────────────────────────────────────────

def section_3_5_bot_comparison() -> list[str]:
    lines = _h1("SECTION 3.5 — BOT COMPARISON MATRIX")
    lines.append("Normalized metrics for cross-bot strategy ranking.")
    lines.append(f"Data as of: {_now_utc_str()}")
    lines.append("")

    portfolios = {p["bot_id"]: p for p in get_all_portfolios()}
    states = {s["bot_id"]: s for s in get_all_states()}

    rows = []
    for bot in _registry_all_bots():
        p = portfolios.get(bot.id, {})
        m = _trade_metrics(bot.id)
        equity = float(p.get("equity_usd") or 0)
        starting = float(p.get("starting_usd") or 100000)
        pct_return = ((equity - starting) / starting * 100) if starting else 0

        rows.append({
            "name": bot.display_name,
            "id": bot.id,
            "status": "PAUSED" if states.get(bot.id, {}).get("paused") else "ACTIVE",
            "trades": m.get("trades", 0),
            "wr": m.get("win_rate"),
            "pf": m.get("profit_factor"),
            "expectancy": m.get("expectancy"),
            "pct_return": pct_return,
            "avg_win": m.get("avg_win"),
            "avg_loss": m.get("avg_loss"),
        })

    h = (f"{'BOT':<22} {'STATUS':<7} {'%RET':>7} {'TRADES':>7} {'WR':>7} "
         f"{'PF':>6} {'EXPECT':>9} {'AVG_W':>8} {'AVG_L':>8}")
    lines.append(h)
    lines.append("-" * len(h))
    for r in rows:
        pf_str = f"{r['pf']:.2f}" if r["pf"] else "n/a"
        lines.append(
            f"{r['name']:<22} {r['status']:<7} "
            f"{_fmt_pct(r['pct_return'], 2):>7} "
            f"{r['trades']:>7,} "
            f"{_fmt_pct(r['wr']):>7} "
            f"{pf_str:>6} "
            f"{_fmt_money(r['expectancy']):>9} "
            f"{_fmt_money(r['avg_win']):>8} "
            f"{_fmt_money(r['avg_loss']):>8}"
        )
    lines.append("")

    profitable = [r for r in rows if r["expectancy"] and r["expectancy"] > 0]
    profitable.sort(key=lambda r: r["expectancy"], reverse=True)
    losing = [r for r in rows if r["expectancy"] and r["expectancy"] <= 0]
    losing.sort(key=lambda r: r["expectancy"])

    if profitable:
        lines.append("RANKED BY EXPECTANCY (best to worst, profitable only):")
        for i, r in enumerate(profitable, 1):
            lines.append(f"  {i}. {r['name']:<22} expectancy/trade {_fmt_money(r['expectancy'])}")
        lines.append("")
    if losing:
        lines.append("LOSING BOTS (worst to least bad):")
        for r in losing:
            lines.append(f"  • {r['name']:<22} expectancy/trade {_fmt_money(r['expectancy'])}")
        lines.append("")

    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 4 — Math Audit Summary
# ──────────────────────────────────────────────────────────────────────

def section_4_math_audit_summary() -> list[str]:
    lines = _h1("SECTION 4 — MATH AUDIT SUMMARY")
    lines.append(f"Data as of: {_now_utc_str()}")
    lines.append("")

    # Resolve legacy audit bot IDs (apex-predator, davy-jones, etc.) to display names
    from core.bot_state import LEGACY_TO_CANONICAL
    def _resolve_audit_bot(audit_bot_id: str) -> str:
        canonical = LEGACY_TO_CANONICAL.get(audit_bot_id, audit_bot_id)
        for bot in _registry_all_bots():
            if bot.id == canonical:
                return bot.display_name
        return audit_bot_id

    # Query 1 — 24h overall
    overall = _query("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'PASS') AS pass,
            COUNT(*) FILTER (WHERE status = 'WARN') AS warn,
            COUNT(*) FILTER (WHERE status = 'FAIL') AS fail
        FROM math_audit_log
        WHERE audit_timestamp >= NOW() - INTERVAL '24 hours';
    """)

    if overall and overall[0].get("total"):
        r = overall[0]
        total = r["total"] or 0
        passed = r["pass"] or 0
        warned = r["warn"] or 0
        failed = r["fail"] or 0
        pass_rate = (100.0 * passed / total) if total else 0
        lines.append("LAST 24 HOURS:")
        lines.append(f"  Total checks:    {total:,}")
        lines.append(f"  PASS:            {passed:,}  ({pass_rate:.1f}%)")
        lines.append(f"  WARN:            {warned:,}")
        lines.append(f"  FAIL:            {failed:,}")
        lines.append("")
    else:
        lines.append("No math audit data in last 24 hours.")
        lines.append("")

    # Query 2 — 7-day trend
    daily = _query("""
        SELECT
            DATE_TRUNC('day', audit_timestamp) AS day,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'FAIL') AS fail,
            ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'PASS') / NULLIF(COUNT(*), 0), 1) AS pass_pct
        FROM math_audit_log
        WHERE audit_timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY DATE_TRUNC('day', audit_timestamp)
        ORDER BY day DESC;
    """)
    if daily:
        lines.append("7-DAY TREND:")
        h = f"  {'DAY':<12} {'TOTAL':>8} {'FAIL':>6} {'PASS%':>7}"
        lines.append(h)
        for d in daily:
            day_str = d["day"].strftime("%Y-%m-%d") if d.get("day") else "?"
            pass_pct_str = (str(d["pass_pct"]) + "%") if d.get("pass_pct") is not None else "n/a"
            lines.append(f"  {day_str:<12} {d['total']:>8,} {d['fail']:>6,} {pass_pct_str:>7}")
        lines.append("")

    # Query 3 — per-bot fail rate
    by_bot = _query("""
        SELECT
            bot_id,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'FAIL') AS fail,
            ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'FAIL') / NULLIF(COUNT(*), 0), 1) AS fail_pct
        FROM math_audit_log
        WHERE audit_timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY bot_id
        ORDER BY fail_pct DESC NULLS LAST;
    """)
    if by_bot:
        lines.append("PER-BOT FAIL RATE (24h):")
        for b in by_bot:
            display = _resolve_audit_bot(b["bot_id"])
            fail_pct_str = (str(b["fail_pct"]) + "%") if b.get("fail_pct") is not None else "n/a"
            lines.append(f"  {display:<22} {b['total']:>6,} checks, {b['fail']:>4,} fails ({fail_pct_str:>6})")
        lines.append("")

    # Query 4 — top failing formulas
    top_fails = _query("""
        SELECT formula_name AS formula, COUNT(*) AS fails
        FROM math_audit_log
        WHERE status = 'FAIL' AND audit_timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY formula_name
        ORDER BY fails DESC
        LIMIT 5;
    """)
    if top_fails:
        lines.append("TOP FAILING FORMULAS (24h):")
        for f in top_fails:
            lines.append(f"  {f['formula']:<40} {f['fails']:>4,} fails")
        lines.append("")

    # Query 5 — recent fail examples
    fail_examples = _query("""
        SELECT bot_id, formula_name AS formula, status, notes, audit_timestamp AS ts
        FROM math_audit_log
        WHERE status = 'FAIL' AND audit_timestamp >= NOW() - INTERVAL '24 hours'
        ORDER BY audit_timestamp DESC
        LIMIT 5;
    """)
    if fail_examples:
        lines.append("RECENT FAILURE EXAMPLES:")
        for ex in fail_examples:
            display = _resolve_audit_bot(ex["bot_id"])
            note = (ex.get("notes") or "")[:100]
            ts_str = ex["ts"].strftime("%H:%M:%S") if ex.get("ts") else "?"
            lines.append(f"  [{ts_str}] {display:<20} {ex['formula']:<30} {note}")
        lines.append("")

    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 5 — Trade Quality + Regime Fitness
# ──────────────────────────────────────────────────────────────────────

def section_5_trade_quality() -> list[str]:
    lines = _h1("SECTION 5 — TRADE QUALITY + REGIME FITNESS")
    lines.append(f"Data as of: {_now_utc_str()}")
    lines.append("")

    lines.append("SLIPPAGE CHECK (last 7d, trades > 1% slippage):")
    high_slip = _query("""
        SELECT trade_id, ticker, slippage_pct, realized_pnl, date
        FROM trades
        WHERE slippage_pct IS NOT NULL AND ABS(slippage_pct) > 1.0
          AND date >= CURRENT_DATE - INTERVAL '7 days'
        ORDER BY ABS(slippage_pct) DESC LIMIT 10;
    """)
    if high_slip:
        for t in high_slip:
            lines.append(f"  {t['ticker']:<8} slip={t['slippage_pct']:>5.2f}%  pnl={_fmt_money(t['realized_pnl'])}  ({t['date']})")
    else:
        lines.append("  No high-slippage trades found.")
    lines.append("")

    lines.append("EXIT REASON DISTRIBUTION (last 30d):")
    for bot in _registry_all_bots():
        src = TRADE_SOURCES.get(bot.id)
        if not src:
            continue
        # kraken_trades, poseidon_momentum_trades, kraken_current_trades all use "reason"
        # only the alpaca "trades" table (oracle) uses "exit_reason"
        reason_col = "exit_reason" if bot.id == "oracle" else "reason"

        where_parts = [f"{src['time_col']} IS NOT NULL"]
        params: list[Any] = []
        if src.get("bot_filter"):
            where_parts.append("bot_id = %s")
            params.append(src["bot_filter"])
        if src.get("extra_where"):
            where_parts.append(src["extra_where"])
        where_parts.append(f"{src['time_col']} >= NOW() - INTERVAL '30 days'")
        where = " WHERE " + " AND ".join(where_parts)

        try:
            sql = (f"SELECT {reason_col} AS reason, COUNT(*) AS n "
                   f"FROM {src['table']}{where} "
                   f"GROUP BY {reason_col} ORDER BY n DESC;")
            results = _query(sql, tuple(params))
            if results:
                lines.append(f"  {bot.display_name}:")
                for r in results[:5]:
                    lines.append(f"    {(r['reason'] or 'unspecified'):<30} {r['n']:>4,} trades")
        except Exception:
            pass
    lines.append("")

    lines.append("PAUSED-STATE TRADE CHECK:")
    states = {s["bot_id"]: s for s in get_all_states()}
    paused_with_recent_trades = []
    for bot in _registry_all_bots():
        s = states.get(bot.id, {})
        if not s.get("paused"):
            continue
        m = _trade_metrics(bot.id, days=1)
        if m.get("trades", 0) > 0:
            paused_with_recent_trades.append((bot.display_name, m["trades"]))
    if paused_with_recent_trades:
        lines.append("  ⚠ Paused bots with trades in last 24h:")
        for name, count in paused_with_recent_trades:
            lines.append(f"    {name}: {count} trades — pause may not be enforcing")
    else:
        lines.append("  ✓ No paused bots have traded recently.")
    lines.append("")

    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 6 — Infrastructure Health
# ──────────────────────────────────────────────────────────────────────

def section_6_infrastructure() -> list[str]:
    lines = _h1("SECTION 6 — INFRASTRUCTURE HEALTH")
    lines.append(f"Data as of: {_now_utc_str()}")
    lines.append("")

    lines.append("BOT HEARTBEATS:")
    states = get_all_states()
    for s in states:
        hb = s.get("last_heartbeat")
        if hb:
            try:
                if isinstance(hb, str):
                    hb_dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
                else:
                    hb_dt = hb
                if hb_dt.tzinfo is None:
                    hb_dt = hb_dt.replace(tzinfo=timezone.utc)
                mins = (_now_utc() - hb_dt).total_seconds() / 60
                flag = "✓" if mins < 5 else ("⚠" if mins < 60 else "🔴")
                lines.append(f"  {flag} {s['bot_id']:<22} {mins:>6.1f} min ago")
            except Exception:
                lines.append(f"  ? {s['bot_id']:<22} (unparseable heartbeat)")
        else:
            lines.append(f"  ⚠ {s['bot_id']:<22} no heartbeat recorded")
    lines.append("")

    lines.append("DEGRADATION EVENTS (last 24h):")
    try:
        degs = _query("""
            SELECT component, severity, COUNT(*) AS n, MAX(occurred_at) AS last_seen
            FROM degradation_events
            WHERE occurred_at >= NOW() - INTERVAL '24 hours'
            GROUP BY component, severity
            ORDER BY n DESC LIMIT 10;
        """)
        if degs:
            for d in degs:
                lines.append(f"  {d['severity']:<8} {d['component']:<30} {d['n']:>4,} events (last: {d['last_seen']})")
        else:
            lines.append("  ✓ No degradation events in last 24h.")
    except Exception as exc:
        lines.append(f"  (degradation_events table not available: {exc})")
    lines.append("")

    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 7 — Parameter Drift (conditional)
# ──────────────────────────────────────────────────────────────────────

def section_7_param_drift() -> list[str]:
    """Only renders if any bot has adaptive param changes in last 24h."""
    drift_data = _query("""
        SELECT bot_id, param_name, old_value, new_value, reason, changed_at
        FROM kraken_adaptive_params
        WHERE changed_at >= NOW() - INTERVAL '24 hours'
        ORDER BY changed_at DESC LIMIT 20;
    """)
    if not drift_data:
        return []

    lines = _h1("SECTION 7 — PARAMETER DRIFT (24h)")
    for d in drift_data:
        ts = d["changed_at"].strftime("%Y-%m-%d %H:%M:%S") if d.get("changed_at") else "?"
        lines.append(
            f"  [{ts}] {d['bot_id']:<20} {d['param_name']:<20} "
            f"{d['old_value']} → {d['new_value']}  ({d.get('reason', '')})"
        )
    lines.append("")
    return lines


# ──────────────────────────────────────────────────────────────────────
# Section 5B — Open Position Audit
# ──────────────────────────────────────────────────────────────────────

def section_5b_open_position_audit() -> list[str]:
    """Cross-check open positions in bot_portfolio against legacy trade tables.
    Surfaces bots with orphaned open trades that the portfolio doesn't know about."""
    lines: list[str] = []
    portfolios = {p["bot_id"]: p for p in get_all_portfolios()}

    # Forex Gump: check forex_trades for status='open' vs bot_portfolio positions
    fx_open = _query("""
        SELECT COUNT(*) AS open_count,
               MIN(entry_time) AS oldest_entry
        FROM forex_trades
        WHERE status = 'open';
    """)
    if fx_open and fx_open[0]["open_count"]:
        n = fx_open[0]["open_count"]
        portfolio_positions = len(portfolios.get("forex_gump", {}).get("positions", []) or [])
        oldest = fx_open[0]["oldest_entry"]
        if n != portfolio_positions:
            if not lines:
                lines = _h1("SECTION 5B — OPEN POSITION AUDIT")
                lines.append("Checks for orphaned open trades not reflected in bot_portfolio.")
                lines.append("")
            lines.append("🔴 Forex Gump:")
            lines.append(f"  forex_trades rows with status='open':  {n}")
            lines.append(f"  bot_portfolio.positions count:          {portfolio_positions}")
            lines.append(f"  Discrepancy:                            {abs(n - portfolio_positions)} stuck rows")
            lines.append(f"  Oldest stuck position opened:           {oldest}")
            lines.append("")

    return lines  # returns [] if no discrepancies — section auto-skipped


# ──────────────────────────────────────────────────────────────────────
# Section 8 — Anomalies Detected
# ──────────────────────────────────────────────────────────────────────

def section_8_anomalies() -> list[str]:
    lines = _h1("SECTION 8 — ANOMALIES DETECTED")
    lines.append("Automatically flagged data patterns worth investigating.")
    lines.append("")

    anomalies = []
    portfolios = {p["bot_id"]: p for p in get_all_portfolios()}
    states = {s["bot_id"]: s for s in get_all_states()}

    for bot in _registry_all_bots():
        m = _trade_metrics(bot.id)
        p = portfolios.get(bot.id, {})
        s = states.get(bot.id, {})

        trades = m.get("trades", 0)
        if trades == 0:
            # Anomaly: active bot with zero trades all-time
            if not s.get("paused"):
                anomalies.append(
                    f"⚠ {bot.display_name}: 0 trades all-time but marked ACTIVE. "
                    "Either new bot still warming up, or strategy not firing."
                )
            continue

        wr = m.get("win_rate") or 0
        pf = m.get("profit_factor")
        expectancy = m.get("expectancy") or 0
        last_trade_str = m.get("last_trade")

        # Anomaly: WR = 0 with multiple trades
        if wr == 0 and trades >= 3:
            anomalies.append(
                f"🔴 {bot.display_name}: 0% win rate over {trades} trades. "
                "Strategy fundamentally broken."
            )

        # Anomaly: profit factor < 1.0 (losing money)
        if pf is not None and pf < 1.0 and trades >= 10:
            severity = "🔴" if pf < 0.7 else "⚠"
            anomalies.append(
                f"{severity} {bot.display_name}: Profit factor {pf:.2f} over {trades} trades "
                "— strategy not profitable."
            )

        # Anomaly: marginal profitability (PF 1.0–1.2)
        if pf is not None and 1.0 <= pf < 1.2 and trades >= 10:
            anomalies.append(
                f"⚠ {bot.display_name}: Profit factor {pf:.2f} — barely above breakeven. "
                "Within noise range."
            )

        # Anomaly: single big winner skewing equity
        best = m.get("best") or 0
        worst = abs(m.get("worst") or 0)
        if worst > 0 and best > 5 * worst and trades >= 10:
            anomalies.append(
                f"⚠ {bot.display_name}: Best trade ${best:.0f} is {best/worst:.1f}x worst loss. "
                "Equity heavily dependent on single winner."
            )

        # Anomaly: active bot with stale last trade
        if not s.get("paused") and last_trade_str:
            try:
                lt = (datetime.fromisoformat(last_trade_str.replace("Z", "+00:00"))
                      if isinstance(last_trade_str, str) else last_trade_str)
                if lt.tzinfo is None:
                    lt = lt.replace(tzinfo=timezone.utc)
                days_since = (_now_utc() - lt).days
                if days_since > 7:
                    anomalies.append(
                        f"🔴 {bot.display_name}: Last trade was {days_since} days ago, "
                        "but bot is marked ACTIVE. Either dormant or broken."
                    )
                elif days_since > 2:
                    anomalies.append(
                        f"⚠ {bot.display_name}: No trades in {days_since} days while active."
                    )
            except Exception:
                pass

        # Anomaly: portfolio P&L vs trade-history P&L mismatch
        equity_pnl = float(p.get("equity_usd") or 0) - float(p.get("starting_usd") or 100000)
        trade_pnl = m.get("total_pnl") or 0
        delta = abs(equity_pnl - trade_pnl)
        if delta > 500 and trades > 0:
            anomalies.append(
                f"🔴 {bot.display_name}: Portfolio P&L ${equity_pnl:+.0f} disagrees with "
                f"trade history ${trade_pnl:+.0f} by ${delta:.0f}. Data integrity issue."
            )

    if anomalies:
        for a in anomalies:
            lines.append(f"  {a}")
    else:
        lines.append("  ✓ No anomalies detected.")
    lines.append("")
    return lines


# ──────────────────────────────────────────────────────────────────────
# Master generator — sections 1-8
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

    try:
        lines.extend(section_3_5_bot_comparison())
    except Exception as exc:
        lines.extend(["", "[Section 3.5 failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_4_math_audit_summary())
    except Exception as exc:
        lines.extend(["", "[Section 4 failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_5_trade_quality())
    except Exception as exc:
        lines.extend(["", "[Section 5 failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_5b_open_position_audit())
    except Exception as exc:
        lines.extend(["", "[Section 5B failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_6_infrastructure())
    except Exception as exc:
        lines.extend(["", "[Section 6 failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_7_param_drift())
    except Exception as exc:
        lines.extend(["", "[Section 7 failed]", f"Error: {exc}", ""])

    try:
        lines.extend(section_8_anomalies())
    except Exception as exc:
        lines.extend(["", "[Section 8 failed]", f"Error: {exc}", ""])

    lines.append("")
    lines.append("=" * 78)
    lines.append("END OF REPORT  (sections 1-8 of 9 — section 9 pending build)")
    lines.append("=" * 78)

    return "\n".join(lines)
