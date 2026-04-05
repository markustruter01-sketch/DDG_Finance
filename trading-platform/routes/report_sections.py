"""
report_sections.py — Additional diagnostic report sections (14 new sections)
=============================================================================
Each function returns list[str] lines to be appended to the main report.
Data is reconstructed from historical records where possible.
"""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("report_sections")

_DB_URL = os.environ.get("DATABASE_URL")
W = "\u2550" * 80


def _h1(lines: list[str], title: str):
    lines.append("")
    lines.append(W)
    lines.append(f"  {title}")
    lines.append(W)


def _h2(lines: list[str], title: str):
    lines.append("")
    sep = "\u2500" * max(0, 74 - len(title))
    lines.append(f"\u2500\u2500 {title} {sep}")


def _row(lines: list[str], label: str, value: str, indent: int = 2):
    lines.append(f"{'  ' * indent}{label:<36}{value}")


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


def _pg_query(sql: str, params: tuple = ()) -> list[dict]:
    if not _DB_URL:
        return []
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(_DB_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"report_sections DB query failed: {e}")
        return []


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def section_fleet_risk_dashboard(
    equity: float,
    kraken_equity: float,
    kraken_starting: float,
    opts_equity: float,
    fx_equity: float,
    positions: list,
    kraken_per_bot_equity: dict,
    fx_positions: list,
    opts_positions: list,
    ks_state: dict,
) -> list[str]:
    lines: list[str] = []
    _h1(lines, "SECTION 1A: FLEET SUMMARY RISK DASHBOARD")

    grand_start = 600_000.0
    grand_now = equity + kraken_equity + opts_equity + fx_equity
    grand_peak = grand_now
    peak_rows = _pg_query(
        "SELECT MAX(total_equity) as peak FROM equity_snapshots WHERE total_equity > 0"
    )
    if peak_rows and peak_rows[0].get("peak"):
        grand_peak = max(float(peak_rows[0]["peak"]), grand_now)
    drawdown_from_peak = ((grand_peak - grand_now) / grand_peak * 100) if grand_peak > 0 else 0

    _row(lines, "Combined fleet equity:", _c(grand_now))
    _row(lines, "Fleet all-time peak:", _c(grand_peak))
    _row(lines, "Fleet drawdown from peak:", _pct(-drawdown_from_peak, 3))

    bot_pnls = {
        "#1 Oracle": equity - 100_000,
        "#5 Apex Predator": opts_equity - 100_000,
        "#6 Navigator": fx_equity - 100_000,
    }
    for kbid, keq in kraken_per_bot_equity.items():
        label = {"davy-jones": "#2 Davy Jones", "blackbeard": "#3 Blackbeard", "calypso": "#4 Calypso"}.get(kbid, kbid)
        bot_pnls[label] = keq - 100_000

    best_bot = max(bot_pnls, key=bot_pnls.get) if bot_pnls else "N/A"
    worst_bot = min(bot_pnls, key=bot_pnls.get) if bot_pnls else "N/A"
    _row(lines, "Best performing bot:", f"{best_bot} ({_c(bot_pnls.get(best_bot, 0))})")
    _row(lines, "Biggest drag on performance:", f"{worst_bot} ({_c(bot_pnls.get(worst_bot, 0))})")

    alpaca_exposure = sum(abs(float(p.get("market_value") or 0)) for p in positions)
    fx_exposure = sum(abs(float(p.get("size_usd") or p.get("units") or 0)) for p in fx_positions)
    opts_exposure = sum(abs(float(p.get("total_cost") or 0)) for p in opts_positions)
    kraken_pos_rows = _pg_query(
        "SELECT positions FROM kraken_portfolio"
    )
    kraken_exposure = 0.0
    for pr in kraken_pos_rows:
        pos_data = pr.get("positions")
        if isinstance(pos_data, str):
            pos_data = json.loads(pos_data)
        if isinstance(pos_data, dict):
            for sym, pd in pos_data.items():
                kraken_exposure += abs(float(pd.get("size_usd", 0) if isinstance(pd, dict) else 0))
        elif isinstance(pos_data, list):
            for pd in pos_data:
                kraken_exposure += abs(float(pd.get("size_usd", 0) if isinstance(pd, dict) else 0))

    total_exposure = alpaca_exposure + kraken_exposure + opts_exposure + fx_exposure
    _row(lines, "Total open exposure (all bots):", _c(total_exposure))
    _row(lines, "  Alpaca (Oracle):", _c(alpaca_exposure))
    _row(lines, "  Kraken fleet:", _c(kraken_exposure))
    _row(lines, "  Options (Apex):", _c(opts_exposure))
    _row(lines, "  Forex (Navigator):", _c(fx_exposure))

    _row(lines, "Kill switch status:", "TRIPPED" if ks_state.get("tripped") else "ARMED (normal)")

    hb_rows = _pg_query(
        "SELECT id, bot_paused, circuit_breaker, position_count, status FROM kraken_heartbeat"
    )
    cb_bots = []
    idle_bots = []
    for hb in hb_rows:
        bot_names = {1: "#2 Davy Jones", 2: "#3 Blackbeard", 3: "#4 Calypso"}
        bname = bot_names.get(hb.get("id"), f"Bot {hb.get('id')}")
        cb = hb.get("circuit_breaker")
        if isinstance(cb, str):
            cb = json.loads(cb)
        if isinstance(cb, dict) and cb.get("tripped"):
            cb_bots.append(bname)
        if hb.get("position_count", 0) == 0:
            idle_bots.append(f"{bname} ({hb.get('status', 'unknown')})")

    if not positions:
        idle_bots.append("#1 Oracle (0 positions)")
    if not fx_positions:
        idle_bots.append("#6 Navigator (0 positions)")
    if not opts_positions:
        idle_bots.append("#5 Apex Predator (0 positions)")

    _row(lines, "Bots in circuit breaker:", ", ".join(cb_bots) if cb_bots else "None")
    _row(lines, "Idle bots (0 positions):", ", ".join(idle_bots) if idle_bots else "None")

    return lines


def section_trade_mechanics_oracle() -> list[str]:
    lines: list[str] = []
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (ORACLE #1)")
    lines += [
        "  MOMENTUM SCORE FORMULA:",
        "    composite_score = (20d_return * 0.50) + (60d_return * 0.30)",
        "    Trend bonus: +5.0 if Price > SMA-63 AND Price > SMA-126",
        "",
        "  ENTRY FILTERS (ALL must be True):",
        "    1. Composite momentum score ranks in top N for regime (Bull=9, Sideways=6, Bear=4)",
        "    2. RSI(14) between 30 and regime_upper (Bull=75, Bear=70)",
        "    3. 3-month momentum must be 'positive'",
        "    4. Sector diversification: max 3 per sector (Bull), max 2 per sector (Bear/Sideways)",
        "    5. Bear regime: only DEFENSIVE sectors (healthcare, utilities, staples, energy, safe-haven ETFs, commodity ETFs)",
        "    6. Not in existing open positions",
        "",
        "  STOP LOSS FORMULA:",
        "    vol_factor = annualized_volatility_20d / 100",
        "    stop_loss_pct = -min(max(vol_factor * stop_mult, 0.03), 0.08)",
        "    Bull: stop_mult=1.5  |  Sideways: stop_mult=1.2  |  Bear: stop_mult=1.0",
        "",
        "  TAKE PROFIT FORMULA:",
        "    take_profit_pct = min(max(vol_factor * take_mult, 0.05), 0.20)",
        "    Bull: take_mult=2.0  |  Sideways: take_mult=1.6  |  Bear: take_mult=1.3",
        "",
        "  KELLY CRITERION FORMULA:",
        "    kelly = (win_rate * (avg_win / avg_loss + 1) - 1) / (avg_win / avg_loss)",
        "    Final sizing = min(kelly * conviction_score, kelly_cap)",
        "    Bull: kelly_cap=12%  |  Sideways: kelly_cap=8%  |  Bear: kelly_cap=6%",
        "    Fallback: 2% fixed fractional if insufficient trade history",
        "",
        "  REGIME-SPECIFIC PARAMETERS:",
        "    Bull:     max_active=9  kelly_cap=12%  stop_mult=1.5x  take_mult=2.0x  full_universe",
        "    Sideways: max_active=6  kelly_cap=8%   stop_mult=1.2x  take_mult=1.6x  full_universe",
        "    Bear:     max_active=4  kelly_cap=6%   stop_mult=1.0x  take_mult=1.3x  defensive_only",
    ]
    return lines


def section_trade_mechanics_kraken() -> list[str]:
    lines: list[str] = []
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (KRAKEN FLEET #2-4)")
    lines += [
        "  VPIN (Volume-Synchronized Probability of Informed Trading):",
        "    bucket_size = volume / num_buckets (50 buckets default)",
        "    vpin = abs(buy_volume - sell_volume) / total_volume per bucket",
        "    Dynamic threshold = rolling_30d_mean + 1.5 * rolling_30d_stddev",
        "    Threshold floor: 0.60  |  Threshold ceiling: 0.95",
        "    Legacy fallback threshold: 0.82 (if < 100 observations)",
        "",
        "  Z-SCORE (Mean Reversion Entry):",
        "    z_score = (current_price - SMA_20) / rolling_stddev_20",
        "    Entry LONG:  z_score < -2.0  |  Entry SHORT: z_score > +2.0",
        "",
        "  ATR-BASED STOP/TAKE PROFIT:",
        "    ATR = 14-period Average True Range",
        "    Stop Loss: entry_price +/- (ATR * sl_atr_mult)",
        "    Take Profit: entry_price +/- (ATR * tp_atr_mult)",
        "    Trailing stop ratchets with price movement",
        "",
        "  POSITION SIZING:",
        "    Base: 10-15% of equity per position (varies by bot aggression profile)",
        "    Davy Jones (Conservative): smaller sizes, tighter stops",
        "    Blackbeard (Aggressive): larger sizes, wider stops",
        "    Calypso (Most Aggressive): largest sizes, widest stops",
        "    Max simultaneous positions: 10 per bot",
        "",
        "  CIRCUIT BREAKER:",
        "    Triggers after N consecutive losses (varies by bot profile)",
        "    Cooldown period before resuming trading",
        "",
        "  ENTRY FILTERS (ALL must be True):",
        "    1. VPIN < dynamic_threshold (no toxic flow detected)",
        "    2. Z-score exceeds threshold OR momentum signal active",
        "    3. Not already holding max positions",
        "    4. Not in circuit breaker cooldown",
        "    5. Not in RAG-derived blacklist for symbol+regime",
    ]
    return lines


def section_trade_mechanics_apex() -> list[str]:
    lines: list[str] = []
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (APEX PREDATOR #5)")
    lines += [
        "  IV RANK (IVR) FORMULA:",
        "    current_iv = median(all option IVs in chain)",
        "    iv_min = 5th percentile of chain IVs",
        "    iv_max = 95th percentile of chain IVs",
        "    ivr = ((current_iv - iv_min) / (iv_max - iv_min)) * 100",
        "    THRESHOLD: IVR < 20 (implied volatility is compressed)",
        "",
        "  BOLLINGER BAND SQUEEZE FORMULA:",
        "    SMA = 20-day Simple Moving Average",
        "    Upper Band = SMA + (2.0 * 20d_stddev)",
        "    Lower Band = SMA - (2.0 * 20d_stddev)",
        "    Bandwidth = ((Upper - Lower) / SMA) * 100",
        "    Lookback: 126 trading days (6 months)",
        "    SQUEEZE = True when current_bandwidth <= 1.05 * min_bandwidth_126d",
        "",
        "  ENTRY CONDITIONS (ALL must be True):",
        "    1. IVR < 20",
        "    2. Bollinger Band squeeze detected",
        "    3. Option chain has valid ATM strikes with 30-45 DTE",
        "    4. Deployed capital < capital fence (5% of equity)",
        "",
        "  TRADE CONSTRUCTION:",
        "    Strategy: Long Straddle (ATM Call + ATM Put, same strike, same expiration)",
        "    DTE target: 30-45 days to expiration",
        "    Strike: At-The-Money (closest to current stock price)",
        "",
        "  QUARTER-KELLY POSITION SIZING:",
        "    p = historical win rate  |  b = avg_win / avg_loss ratio",
        "    kelly = (p * (b + 1) - 1) / b",
        "    final_size = min(kelly / 4, 0.10)  (capped at 10% of fenced capital)",
        "    Fallback: 1% fixed fractional risk if < 10 historical trades",
        "",
        "  EXIT CONDITIONS:",
        "    Max loss: 50% of entry cost (MAX_LOSS_PCT = 0.50)",
        "    Time decay: exit before significant theta burn",
        "    Profit target: based on expected vol expansion",
    ]
    return lines


def section_trade_mechanics_navigator() -> list[str]:
    lines: list[str] = []
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (NAVIGATOR #6)")
    lines += [
        "  RSI (Relative Strength Index):",
        "    Period: 14  |  Oversold: < 30  |  Overbought: > 70",
        "",
        "  ATR (Average True Range):",
        "    Period: 14  |  Used for all bracket calculations",
        "",
        "  STOP LOSS FORMULA:",
        "    Initial SL = 2.5 * ATR(14) from entry  (SL_ATR_MULT = 2.5)",
        "    Breakeven trigger: when price moves 1.5 * ATR in favor, SL moves to entry + 2 pips",
        "",
        "  TAKE PROFIT FORMULA:",
        "    TP = 5.0 * ATR(14) from entry  (TP_ATR_MULT = 5.0)",
        "",
        "  TRAILING STOP FORMULA:",
        "    Trailing offset = 2.0 * ATR(14) from best price seen  (TRAIL_ATR_MULT = 2.0)",
        "    Ratchets up (longs) / down (shorts) as price moves favorably",
        "",
        "  POSITION SIZING FORMULA:",
        "    risk_per_trade = equity * MAX_RISK_PER_TRADE_PCT  (1%)",
        "    units = risk_per_trade / (SL_distance_in_price * pip_value)",
        "    Max position size: 10% of equity  (MAX_POSITION_SIZE_PCT = 0.10)",
        "",
        "  ENTRY FILTERS (ALL must be True):",
        "    1. RSI confirms direction (< 30 for long, > 70 for short)",
        "    2. USD bias from Groq LLM aligns with trade direction",
        "    3. Not in news blackout (high-impact event within 4 hours)",
        "    4. Open positions < MAX_OPEN_POSITIONS (10)",
        "    5. Not in circuit breaker cooldown (3% drawdown triggers 8hr pause)",
        "",
        "  SPREAD COST MODEL (Paper Trading):",
        "    PAPER_SPREAD_COST_PCT = 0.001 (0.1% per side)",
        "    Total round-trip cost = entry_size * 0.001 + exit_size * 0.001",
        "",
        "  VAULT SWEEP:",
        "    20% of profits above High Water Mark swept weekly",
    ]
    return lines


def section_oracle_regime_transparency() -> list[str]:
    lines: list[str] = []
    _h2(lines, "ORACLE REGIME LOGIC TRANSPARENCY")

    lines += [
        "  REGIME DEFINITIONS:",
        "    Bull:     LLM (Groq) classifies based on: SPY trend, VIX level, breadth indicators,",
        "              economic data (FRED), news sentiment. Characterized by broad risk-on conditions.",
        "    Sideways: Mixed signals, no clear directional bias. Moderate risk parameters.",
        "    Bear:     Risk-off conditions: elevated VIX, declining breadth, negative macro data.",
        "              Triggers defensive-only universe (healthcare, utilities, staples, energy,",
        "              safe-haven ETFs, commodity ETFs).",
        "",
        "    The LLM provides the regime label. The algo scanner adjusts RISK PARAMETERS not strategy.",
        "",
        "  SGOV DEFAULT LOGIC:",
        "    SGOV (T-Bill ETF) is the cash-equivalent parking position.",
        "    Used when: all active slots are filled OR no momentum signals pass filters.",
        "    One slot always reserved for SGOV to prevent full capital deployment.",
        "    SGOV is exempt from position size cap and treated as a cash proxy.",
    ]

    regime_json_path = Path(__file__).parent.parent / "data" / "market_regime.json"
    try:
        if regime_json_path.exists():
            rd = json.loads(regime_json_path.read_text())
            _row(lines, "Current regime:", str(rd.get("regime", "Unknown")))
            _row(lines, "Regime set at:", str(rd.get("written_at", "Unknown"))[:19])
            _row(lines, "Rationale:", str(rd.get("rationale", "N/A"))[:120])
    except Exception:
        pass

    _h2(lines, "REGIME CHANGE LOG (Reconstructed from equity_snapshots)")
    regime_rows = _pg_query("""
        SELECT ts, regime FROM equity_snapshots
        WHERE regime IS NOT NULL
        ORDER BY ts ASC
    """)
    if regime_rows:
        changes = []
        prev_regime = None
        for r in regime_rows:
            regime = r.get("regime")
            if regime and regime != prev_regime:
                changes.append((str(r["ts"])[:19], regime, prev_regime or "N/A"))
                prev_regime = regime
        lines.append(f"  Total regime transitions detected: {len(changes)}")
        lines.append(f"  [Reconstructed from historical data]")
        lines.append(f"  {'Timestamp':<22} {'From':<15} {'To':<15}")
        lines.append("  " + "-" * 52)
        for ts, to_r, from_r in changes[-30:]:
            lines.append(f"  {ts:<22} {from_r:<15} {to_r:<15}")
        if len(changes) > 30:
            lines.append(f"  ... ({len(changes) - 30} earlier transitions omitted)")
    else:
        lines.append(f"  No regime history in equity_snapshots. Capturing from {_today_str()} forward.")

    return lines


def section_vpin_shadow_log() -> list[str]:
    lines: list[str] = []
    _h2(lines, "VPIN SHADOW LOG (Trades blocked by VPIN filter)")
    lines += [
        f"  Historical VPIN rejections were not persisted to database prior to this report.",
        f"  VPIN blocked-entry events were logged to console only and overwritten each cycle.",
        f"  Status: Capturing from {_today_str()} forward.",
        "",
        "  VPIN rejection tracking requires kraken-bot code changes (out of scope per user rules).",
        "  Current cycle rejections can be seen in each bot's live_state.json under cycle_signals.",
    ]

    for bot_id in ["davy-jones", "blackbeard", "calypso"]:
        ls_path = Path(__file__).parent.parent.parent / "kraken-bot" / f"{bot_id}_live_state.json"
        if bot_id == "davy-jones":
            alt_path = Path(__file__).parent.parent.parent / "kraken-bot" / "live_state.json"
            if not ls_path.exists() and alt_path.exists():
                ls_path = alt_path
        try:
            if ls_path.exists():
                ls = json.loads(ls_path.read_text())
                signals = ls.get("cycle_signals", [])
                vpin_blocks = [s for s in signals if "vpin" in str(s.get("signal_type", "")).lower()]
                if vpin_blocks:
                    lines.append(f"\n  {bot_id} — current cycle VPIN blocks: {len(vpin_blocks)}")
                    for vb in vpin_blocks[:5]:
                        lines.append(f"    Symbol: {vb.get('symbol', '?')}  VPIN: {vb.get('vpin', '?')}  "
                                     f"Threshold: {vb.get('threshold', '?')}")
        except Exception:
            pass

    return lines


def section_vpin_calibration() -> list[str]:
    lines: list[str] = []
    _h2(lines, "VPIN CALIBRATION METRICS (Kraken Fleet)")

    lines += [
        "  EXACT VPIN FORMULA:",
        "    1. Divide volume stream into N buckets (50 default)",
        "    2. Classify each trade as buy/sell using tick rule",
        "    3. VPIN = |buy_vol - sell_vol| / total_vol per bucket",
        "    4. Rolling window: last 50 buckets",
        "",
        "  DYNAMIC THRESHOLD FORMULA:",
        "    threshold = mean(30d_readings) + 1.5 * stddev(30d_readings)",
        "    Floor: 0.60  |  Ceiling: 0.95",
        "    Fallback: 0.82 (if < 100 historical observations)",
    ]

    vpin_history_path = Path(__file__).parent.parent.parent / "kraken-bot" / "_vpin_history.json"
    try:
        if vpin_history_path.exists():
            vh = json.loads(vpin_history_path.read_text())
            if isinstance(vh, list) and vh:
                lines.append(f"\n  Total VPIN observations stored: {len(vh)}")
                readings = [float(v.get("vpin", 0)) for v in vh if v.get("vpin")]
                if readings:
                    import statistics
                    mean_v = statistics.mean(readings)
                    std_v = statistics.stdev(readings) if len(readings) > 1 else 0
                    current_threshold = min(max(mean_v + 1.5 * std_v, 0.60), 0.95)
                    lines.append(f"  Current dynamic threshold: {current_threshold:.4f}")
                    lines.append(f"  Rolling mean: {mean_v:.4f}  |  Rolling stddev: {std_v:.4f}")

                    recent_24h = [
                        float(v["vpin"]) for v in vh
                        if v.get("ts") and (datetime.now(timezone.utc).timestamp() - float(v["ts"])) < 86400
                    ]
                    if recent_24h:
                        lines.append(f"  24hr average VPIN: {statistics.mean(recent_24h):.4f} ({len(recent_24h)} readings)")
                    else:
                        lines.append("  24hr average VPIN: No readings in last 24 hours")
                    lines.append("  [Reconstructed from historical data]")
            else:
                lines.append(f"  No VPIN history data available. Capturing from {_today_str()} forward.")
        else:
            lines.append(f"  VPIN history file not found. Capturing from {_today_str()} forward.")
    except Exception as e:
        lines.append(f"  Error reading VPIN history: {e}")

    kraken_trades = _pg_query(
        "SELECT COUNT(*) as total FROM kraken_trades"
    )
    total_trades = kraken_trades[0].get("total", 0) if kraken_trades else 0
    lines.append(f"\n  Total Kraken trades executed (VPIN allowed): {total_trades}")
    lines.append("  Total VPIN-blocked entries: Not historically tracked — console logs only")
    lines.append(f"  Note: VPIN blocking statistics require kraken-bot code changes to persist")

    return lines


def section_daily_equity_history(bot_label: str, source: str = "all") -> list[str]:
    lines: list[str] = []
    _h2(lines, f"DAILY EQUITY HISTORY ({bot_label})")

    col_map = {
        "oracle": "alpaca_equity",
        "kraken": "kraken_equity",
        "options": "options_equity",
        "forex": "forex_equity",
        "all": "total_equity",
    }
    col = col_map.get(source, "total_equity")

    rows = _pg_query(f"""
        SELECT DATE(ts) as day,
               MIN({col}) as open_eq,
               MAX({col}) as close_eq_proxy,
               MIN(regime) as regime
        FROM equity_snapshots
        WHERE {col} IS NOT NULL AND {col} > 0
        GROUP BY DATE(ts)
        ORDER BY DATE(ts) ASC
    """)

    trade_counts: dict = {}
    if source == "oracle":
        tc_rows = _pg_query("SELECT date, COUNT(*) as cnt FROM trades GROUP BY date")
        for r in tc_rows:
            trade_counts[str(r["date"])] = r["cnt"]
    elif source == "kraken":
        tc_rows = _pg_query("SELECT DATE(closed_at) as day, COUNT(*) as cnt FROM kraken_trades GROUP BY DATE(closed_at)")
        for r in tc_rows:
            if r["day"]:
                trade_counts[str(r["day"])] = r["cnt"]

    if rows:
        lines.append(f"  [Reconstructed from historical data — {len(rows)} days]")
        lines.append(f"  {'Date':<12} {'Open Eq':>14} {'Close Eq':>14} {'Daily P&L':>12} {'Daily %':>9} {'Regime':<12} {'Trades':>7}")
        lines.append("  " + "-" * 82)
        prev_close = None
        for r in rows[-60:]:
            day = str(r["day"])
            open_eq = float(r.get("open_eq") or 0)
            close_eq = float(r.get("close_eq_proxy") or 0)
            regime = str(r.get("regime") or "?")[:10]
            daily_pnl = close_eq - (prev_close if prev_close else open_eq)
            daily_pct = (daily_pnl / (prev_close if prev_close else open_eq) * 100) if (prev_close or open_eq) > 0 else 0
            trades = trade_counts.get(day[:10], 0)
            lines.append(f"  {day:<12} {_c(open_eq):>14} {_c(close_eq):>14} {_c(daily_pnl):>12} {_pct(daily_pct):>9} {regime:<12} {trades:>7}")
            prev_close = close_eq
        if len(rows) > 60:
            lines.append(f"  ... ({len(rows) - 60} earlier days omitted)")
    else:
        lines.append(f"  No equity history available. Capturing from {_today_str()} forward.")

    return lines


def section_regime_performance(bot_label: str, source: str = "oracle") -> list[str]:
    lines: list[str] = []
    _h2(lines, f"REGIME PERFORMANCE TABLE ({bot_label})")

    if source == "oracle":
        rows = _pg_query("""
            SELECT regime_at_entry as regime,
                   COUNT(*) as trades,
                   SUM(CASE WHEN (realized_pnl >= 0 OR pnl_percentage >= 0) THEN 1 ELSE 0 END) as wins,
                   AVG(COALESCE(pnl_percentage, 0)) as avg_pnl,
                   SUM(COALESCE(realized_pnl, 0)) as total_pnl_usd
            FROM trades
            WHERE regime_at_entry IS NOT NULL AND status != 'Active'
            GROUP BY regime_at_entry
        """)
    elif source == "kraken":
        rows = _pg_query("""
            SELECT 'Crypto' as regime,
                   COUNT(*) as trades,
                   SUM(CASE WHEN pnl_usd >= 0 THEN 1 ELSE 0 END) as wins,
                   AVG(COALESCE(pnl_pct, 0)) as avg_pnl,
                   SUM(COALESCE(pnl_usd, 0)) as total_pnl_usd
            FROM kraken_trades
        """)
    else:
        rows = []

    if rows and any(r.get("trades", 0) > 0 for r in rows):
        lines.append("  [Reconstructed from historical data]")
        lines.append(f"  {'Regime':<16} {'Trades':>7} {'Wins':>6} {'Win Rate':>10} {'Avg PnL':>10} {'Total PnL$':>14}")
        lines.append("  " + "-" * 68)
        for r in rows:
            n = int(r.get("trades", 0))
            wins = int(r.get("wins", 0))
            wr = (wins / n * 100) if n > 0 else 0
            avg = float(r.get("avg_pnl") or 0)
            total = float(r.get("total_pnl_usd") or 0)
            regime = str(r.get("regime") or "Unknown")
            lines.append(f"  {regime:<16} {n:>7} {wins:>6} {_pct(wr, 1):>10} {_pct(avg):>10} {_c(total):>14}")
    else:
        lines.append(f"  No regime-tagged trades available for {bot_label}. Capturing from {_today_str()} forward.")

    return lines


def section_cross_bot_correlation() -> list[str]:
    lines: list[str] = []
    _h1(lines, "CROSS-BOT CORRELATION MATRIX")

    corr_path = Path(__file__).parent.parent / "data" / "correlation_state.json"
    corr_data: dict = {}
    try:
        if corr_path.exists():
            corr_data = json.loads(corr_path.read_text())
    except Exception:
        pass

    if not corr_data:
        try:
            from analysis.correlation_matrix import compute_correlation_matrix
            corr_data = compute_correlation_matrix()
        except Exception:
            pass

    matrix = corr_data.get("matrix", {})
    if matrix:
        lines.append("  [Reconstructed from historical data]")
        lines.append(f"  Data points: {corr_data.get('data_points', 'N/A')}")
        lines.append(f"  Computed at: {str(corr_data.get('computed_at', 'N/A'))[:19]}")
        lines.append("")
        lines.append(f"  {'Bot Pair':<30} {'Correlation':>12} {'Flag':>10}")
        lines.append("  " + "-" * 55)
        for pair, coeff in sorted(matrix.items()):
            c = float(coeff) if coeff is not None else 0
            flag = "HIGH" if abs(c) > 0.70 else ""
            lines.append(f"  {pair:<30} {c:>+12.4f} {flag:>10}")

        max_c = corr_data.get("max_correlation")
        shock = corr_data.get("systemic_shock", False)
        scale = corr_data.get("position_scale_factor", 1.0)
        lines.append("")
        _row(lines, "Max correlation:", f"{float(max_c):.4f}" if max_c is not None else "N/A")
        _row(lines, "Systemic shock detected:", "YES" if shock else "NO")
        _row(lines, "Position scale factor:", f"{float(scale or 1.0):.2f}x")
    else:
        lines.append(f"  Correlation matrix not yet computed (requires equity_snapshots data).")
        lines.append(f"  Capturing from {_today_str()} forward.")

    eq_rows = _pg_query("""
        SELECT
            COALESCE(SUM(alpaca_equity), 0) +
            COALESCE(SUM(kraken_equity), 0) +
            COALESCE(SUM(options_equity), 0) +
            COALESCE(SUM(forex_equity), 0) as total
        FROM (
            SELECT DISTINCT ON (1)
                DATE(ts) as d, alpaca_equity, kraken_equity, options_equity, forex_equity
            FROM equity_snapshots
            ORDER BY 1 DESC, ts DESC
            LIMIT 1
        ) latest
    """)

    return lines


def section_navigator_pair_breakdown(fx_trades: list) -> list[str]:
    lines: list[str] = []
    _h2(lines, "NAVIGATOR PAIR-BY-PAIR BREAKDOWN")

    db_trades = _pg_query("""
        SELECT pair, direction, entry_price, exit_price, pnl_usd, pnl_pips,
               entry_time, exit_time, sl_price, tp_price, llm_thesis
        FROM forex_trades
        WHERE status = 'closed'
        ORDER BY exit_time ASC
    """)

    all_trades = db_trades if db_trades else fx_trades

    if not all_trades:
        lines.append(f"  No closed forex trades to analyze. Capturing from {_today_str()} forward.")
        return lines

    lines.append("  [Reconstructed from historical data]")
    pair_stats: dict = {}
    for t in all_trades:
        pair = t.get("pair", "Unknown")
        if pair not in pair_stats:
            pair_stats[pair] = {
                "trades": 0, "wins": 0, "total_pnl": 0.0,
                "holding_hours": [], "rr_achieved": [],
                "bias_overrides": 0, "bias_override_wins": 0,
            }
        ps = pair_stats[pair]
        ps["trades"] += 1
        pnl = float(t.get("pnl_usd") or 0)
        ps["total_pnl"] += pnl
        if pnl >= 0:
            ps["wins"] += 1

        entry_t = t.get("entry_time")
        exit_t = t.get("exit_time") or t.get("closed_at")
        if entry_t and exit_t:
            try:
                if isinstance(entry_t, str):
                    entry_t = datetime.fromisoformat(entry_t.replace("Z", "+00:00"))
                if isinstance(exit_t, str):
                    exit_t = datetime.fromisoformat(exit_t.replace("Z", "+00:00"))
                hold_hrs = (exit_t - entry_t).total_seconds() / 3600
                if 0 < hold_hrs < 10000:
                    ps["holding_hours"].append(hold_hrs)
            except Exception:
                pass

        entry_px = float(t.get("entry_price") or 0)
        exit_px = float(t.get("exit_price") or 0)
        sl_px = float(t.get("sl_price") or 0)
        if entry_px and exit_px and sl_px and sl_px != entry_px:
            risk = abs(entry_px - sl_px)
            reward = abs(exit_px - entry_px)
            if risk > 0:
                ps["rr_achieved"].append(reward / risk)

        thesis = str(t.get("llm_thesis") or "")
        if "override" in thesis.lower() or "bias" in thesis.lower():
            ps["bias_overrides"] += 1
            if pnl >= 0:
                ps["bias_override_wins"] += 1

    lines.append(f"  {'Pair':<14} {'Trades':>7} {'Win%':>7} {'Total PnL':>12} {'Avg Hold':>10} {'Avg R:R':>8} {'Bias Ovr':>9}")
    lines.append("  " + "-" * 72)
    for pair, ps in sorted(pair_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
        n = ps["trades"]
        wr = (ps["wins"] / n * 100) if n > 0 else 0
        avg_hold = f"{sum(ps['holding_hours']) / len(ps['holding_hours']):.1f}h" if ps["holding_hours"] else "N/A"
        avg_rr = f"{sum(ps['rr_achieved']) / len(ps['rr_achieved']):.2f}" if ps["rr_achieved"] else "N/A"
        bias_info = f"{ps['bias_overrides']}" if ps["bias_overrides"] else "0"
        lines.append(f"  {pair:<14} {n:>7} {_pct(wr, 1):>7} {_c(ps['total_pnl']):>12} {avg_hold:>10} {avg_rr:>8} {bias_info:>9}")

    return lines


def section_apex_scan_log() -> list[str]:
    lines: list[str] = []
    _h2(lines, "APEX PREDATOR SCAN LOG")

    state_path = Path(__file__).parent.parent / "_options_state" / "state.json"
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text())
            last_scan = state.get("last_scan")
            scan_results = state.get("last_scan_results", {})
            lines.append(f"  Last scan time: {str(last_scan)[:19] if last_scan else 'Never'}")

            if scan_results:
                evaluated = scan_results.get("tickers_evaluated", 0)
                setups = scan_results.get("setups_found", 0)
                entries = scan_results.get("entries_taken", 0)
                lines.append(f"  Tickers evaluated: {evaluated}")
                lines.append(f"  Setups found (IVR<20 + squeeze): {setups}")
                lines.append(f"  Entries taken: {entries}")

                scanner_detail = scan_results.get("scanner_detail", [])
                if scanner_detail:
                    lines.append("")
                    lines.append(f"  {'Ticker':<8} {'IVR':>6} {'Squeeze':>8} {'BW%':>8} {'Status':<25}")
                    lines.append("  " + "-" * 58)
                    for sd in scanner_detail[:40]:
                        lines.append(
                            f"  {sd.get('ticker','?'):<8} "
                            f"{sd.get('ivr','?'):>6} "
                            f"{'YES' if sd.get('squeeze') else 'NO':>8} "
                            f"{sd.get('bandwidth','?'):>8} "
                            f"{str(sd.get('rejection_reason', sd.get('status', '?')))[:25]:<25}"
                        )
                    if len(scanner_detail) > 40:
                        lines.append(f"  ... ({len(scanner_detail) - 40} more omitted)")
        else:
            lines.append("  No scan state file found.")
    except Exception as e:
        lines.append(f"  Error reading scan state: {e}")

    trades_db = Path(__file__).parent.parent / "_options_state" / "trades.db"
    if trades_db.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(trades_db))
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT COUNT(*) as total FROM options_trades")
            total = cur.fetchone()["total"]
            cur2 = conn.execute("SELECT COUNT(*) as wins FROM options_trades WHERE pnl_usd >= 0")
            wins = cur2.fetchone()["wins"]
            lines.append(f"\n  All-time options trades: {total}  |  Wins: {wins}  |  Win rate: {_pct((wins/total*100) if total else 0, 1)}")
            lines.append("  [Reconstructed from historical data]")
            conn.close()
        except Exception:
            pass
    else:
        lines.append(f"  Options trades database not found. Capturing from {_today_str()} forward.")

    return lines


def section_slippage_execution_quality(alpaca_trades: list, kraken_trades: list, fx_trades: list) -> list[str]:
    lines: list[str] = []
    _h1(lines, "EXECUTION QUALITY \u2014 SLIPPAGE & FILL ANALYSIS")

    all_slip = []
    bot_slip: dict = {"Oracle": [], "Kraken": [], "Navigator": []}

    for t in alpaca_trades:
        s = t.get("slippage_pct")
        if s is not None:
            val = float(s)
            all_slip.append(val)
            bot_slip["Oracle"].append(val)

    for t in kraken_trades:
        ep = t.get("entry_price")
        exp = t.get("exit_price")
        if ep and exp:
            pass

    fx_db_trades = _pg_query("""
        SELECT pair, entry_price, exit_price, pnl_usd FROM forex_trades WHERE status = 'closed'
    """)

    if all_slip:
        total_slippage_cost = 0.0
        for t in alpaca_trades:
            s = t.get("slippage_pct")
            ep = float(t.get("intended_price") or t.get("actual_fill_price") or 0)
            fp = float(t.get("actual_fill_price") or 0)
            if s is not None and ep > 0 and fp > 0:
                total_slippage_cost += abs(ep - fp)

        lines.append("  [Reconstructed from historical data]")
        _row(lines, "Total slippage cost (Oracle):", _c(total_slippage_cost))
        _row(lines, "Average slippage per trade:", _pct(sum(all_slip) / len(all_slip), 4) if all_slip else "N/A")
        _row(lines, "Best slippage (smallest):", _pct(min(all_slip), 4) if all_slip else "N/A")
        _row(lines, "Worst slippage (largest):", _pct(max(all_slip), 4) if all_slip else "N/A")
        _row(lines, "Trades with slippage data:", str(len(all_slip)))
    else:
        lines.append(f"  No slippage data recorded in historical trades.")
        lines.append(f"  Oracle slippage tracking requires intended_price and actual_fill_price fields.")
        lines.append(f"  Capturing from {_today_str()} forward.")

    lines.append("")
    _row(lines, "Navigator spread cost model:", "0.1% per side (simulated, not real slippage)")
    _row(lines, "Kraken slippage model:", "Dynamic based on order size and ATR volatility")

    failed_rows = _pg_query("""
        SELECT ticker, date, exit_reason FROM trades
        WHERE exit_reason ILIKE '%fail%' OR exit_reason ILIKE '%error%' OR exit_reason ILIKE '%reject%'
        ORDER BY date DESC LIMIT 10
    """)
    if failed_rows:
        lines.append("")
        lines.append("  Failed/Rejected executions (Oracle):")
        for fr in failed_rows:
            lines.append(f"    {str(fr.get('date','?')):<12} {str(fr.get('ticker','?')):<10} {str(fr.get('exit_reason','?'))[:50]}")

    return lines


def section_consecutive_streaks(bot_label: str, trades: list) -> list[str]:
    lines: list[str] = []
    _h2(lines, f"CONSECUTIVE STREAK TRACKER ({bot_label})")

    if not trades:
        lines.append(f"  No trade history for {bot_label}. Capturing from {_today_str()} forward.")
        return lines

    lines.append("  [Reconstructed from historical data]")

    current_streak = 0
    current_type = None
    max_win_streak = 0
    max_loss_streak = 0
    temp_streak = 0
    temp_type = None

    for t in trades:
        pnl = float(t.get("pnl_usd") or t.get("realized_pnl") or t.get("pnl_dollar") or 0)
        is_win = pnl >= 0
        new_type = "W" if is_win else "L"
        if new_type == temp_type:
            temp_streak += 1
        else:
            temp_type = new_type
            temp_streak = 1
        if new_type == "W":
            max_win_streak = max(max_win_streak, temp_streak)
        else:
            max_loss_streak = max(max_loss_streak, temp_streak)
        current_streak = temp_streak
        current_type = temp_type

    _row(lines, "Current streak:", f"{current_streak} {'WIN' if current_type == 'W' else 'LOSS'}{'S' if current_streak > 1 else ''}")
    _row(lines, "Max win streak (all-time):", str(max_win_streak))
    _row(lines, "Max loss streak (all-time):", str(max_loss_streak))

    return lines


def section_consecutive_streaks_kraken(bot_label: str, bot_id: str) -> list[str]:
    trades = _pg_query(
        "SELECT pnl_usd FROM kraken_trades WHERE bot_id = %s ORDER BY closed_at ASC",
        (bot_id,)
    )
    return section_consecutive_streaks(bot_label, trades)


def section_rolling_metrics(bot_label: str, trades: list, equity_source: str = "all") -> list[str]:
    lines: list[str] = []
    _h2(lines, f"ROLLING PERFORMANCE METRICS ({bot_label})")

    if not trades:
        lines.append(f"  No trade data for {bot_label}. Capturing from {_today_str()} forward.")
        return lines

    col_map = {
        "oracle": "alpaca_equity",
        "kraken": "kraken_equity",
        "options": "options_equity",
        "forex": "forex_equity",
        "all": "total_equity",
    }
    col = col_map.get(equity_source, "total_equity")

    eq_rows = _pg_query(f"""
        SELECT DATE(ts) as day, AVG({col}) as avg_eq
        FROM equity_snapshots
        WHERE {col} IS NOT NULL AND {col} > 0
        GROUP BY DATE(ts)
        ORDER BY DATE(ts) DESC
        LIMIT 30
    """)

    sharpe_label = "N/A"
    if len(eq_rows) >= 2:
        try:
            import numpy as np
            equities = [float(r["avg_eq"]) for r in reversed(eq_rows)]
            returns = np.diff(equities) / np.array(equities[:-1])
            last7 = returns[-7:] if len(returns) >= 7 else returns
            if len(last7) >= 2:
                mean_r = float(np.mean(last7))
                std_r = float(np.std(last7))
                rf = 0.05 / 252
                if std_r > 0:
                    sharpe_7d = (mean_r - rf) / std_r * np.sqrt(252)
                    qualifier = " (preliminary — under 30 days)" if len(eq_rows) < 30 else ""
                    sharpe_label = f"{sharpe_7d:.4f}{qualifier}"
        except Exception:
            pass

    _row(lines, "7-day rolling Sharpe ratio:", sharpe_label)

    recent_7d_trades = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for t in trades:
        dt_str = str(t.get("closed_at") or t.get("date") or t.get("exit_time") or "")
        try:
            if dt_str and dt_str[:10] >= cutoff.strftime("%Y-%m-%d"):
                recent_7d_trades.append(t)
        except Exception:
            pass

    if recent_7d_trades:
        wins_7d = sum(1 for t in recent_7d_trades if float(t.get("pnl_usd") or t.get("realized_pnl") or 0) >= 0)
        wr_7d = (wins_7d / len(recent_7d_trades) * 100)
        avg_pnl_7d = sum(float(t.get("pnl_usd") or t.get("realized_pnl") or 0) for t in recent_7d_trades) / len(recent_7d_trades)
        _row(lines, "7-day rolling win rate:", _pct(wr_7d, 1))
        _row(lines, "7-day rolling avg P&L/trade:", _c(avg_pnl_7d))
    else:
        _row(lines, "7-day rolling win rate:", "No trades in last 7 days")
        _row(lines, "7-day rolling avg P&L/trade:", "N/A")

    gross_profit = sum(float(t.get("pnl_usd") or t.get("realized_pnl") or 0)
                       for t in trades if float(t.get("pnl_usd") or t.get("realized_pnl") or 0) > 0)
    gross_loss = abs(sum(float(t.get("pnl_usd") or t.get("realized_pnl") or 0)
                        for t in trades if float(t.get("pnl_usd") or t.get("realized_pnl") or 0) < 0))
    pf = f"{gross_profit / gross_loss:.3f}" if gross_loss > 0 else "Infinite (no losses)"
    _row(lines, "Profit factor (all-time):", pf)
    _row(lines, "  Gross profit:", _c(gross_profit))
    _row(lines, "  Gross loss:", _c(gross_loss))

    lines.append("  [Reconstructed from historical data]")
    return lines


def section_learning_journal_metadata(entries: list) -> list[str]:
    lines: list[str] = []
    _h2(lines, "LEARNING JOURNAL METADATA")

    if not entries:
        lines.append("  No learning journal entries to analyze.")
        return lines

    now = datetime.now(timezone.utc)
    lines.append(f"  {'#':<4} {'Age(d)':>7} {'Confidence':>11} {'Confirmed':>10} {'Stale?':>7} {'Regime':<12} Insight (truncated)")
    lines.append("  " + "-" * 90)
    for i, e in enumerate(entries, 1):
        first_seen = e.get("first_seen", "")
        age_days = "?"
        stale = "N/A"
        try:
            if first_seen:
                fs = first_seen
                if isinstance(fs, str):
                    fs = datetime.fromisoformat(fs.replace("Z", "+00:00"))
                    if fs.tzinfo is None:
                        from datetime import timezone as _tz
                        fs = fs.replace(tzinfo=_tz.utc)
                age = (now - fs).days
                age_days = str(age)
                stale = "STALE" if age > 14 else "Fresh"
        except Exception:
            pass

        conf = e.get("confidence_score", 0)
        confirmed = e.get("confirmed_count", 0)
        regime = str(e.get("regime", "?"))[:10]
        insight = str(e.get("insight_text", "?"))[:55]
        lines.append(
            f"  {i:<4} {age_days:>7} {conf:>11.2f} {confirmed:>10} {stale:>7} {regime:<12} {insight}"
        )

    stale_count = 0
    for e in entries:
        try:
            fs = e.get("first_seen", "")
            if isinstance(fs, str):
                fs = datetime.fromisoformat(fs.replace("Z", "+00:00"))
                if fs.tzinfo is None:
                    fs = fs.replace(tzinfo=timezone.utc)
                if (now - fs).days > 14:
                    stale_count += 1
        except Exception:
            pass

    lines.append("")
    _row(lines, "Total insights:", str(len(entries)))
    _row(lines, "Stale insights (>14 days):", str(stale_count))
    _row(lines, "Injection count tracking:", f"Not currently tracked. Capturing from {_today_str()} forward.")
    _row(lines, "Contradiction detection:", f"Not currently tracked. Capturing from {_today_str()} forward.")

    return lines


def section_circuit_breaker_history(bot_label: str, bot_id: str = None) -> list[str]:
    lines: list[str] = []

    if bot_id:
        hb = _pg_query("SELECT circuit_breaker FROM kraken_heartbeat WHERE id = %s", (int(bot_id),))
        if hb:
            cb = hb[0].get("circuit_breaker")
            if isinstance(cb, str):
                cb = json.loads(cb)
            if isinstance(cb, dict):
                tripped = cb.get("tripped", False)
                count = cb.get("trip_count", 0)
                last_trip = cb.get("last_tripped_at", "Never")
                _row(lines, "Circuit breaker tripped:", "YES" if tripped else "NO")
                _row(lines, "Times tripped:", str(count) if count else "0")
                _row(lines, "Last tripped:", str(last_trip)[:19] if last_trip else "Never")

    return lines
