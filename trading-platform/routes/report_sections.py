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
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (ORACLE #1 — PURE MOMENTUM v3.0)")
    lines += [
        "  MOMENTUM SCORE FORMULA (deterministic — no LLM):",
        "    composite_score = (5d_return * 0.20) + (20d_return * 0.50) + (60d_return * 0.30)",
        "",
        "  LONG ENTRY FILTERS (ALL must be True):",
        "    1. composite_score > 0  (net positive momentum)",
        "    2. RSI(14) between 30 and 70  (not oversold or overbought)",
        "    3. Price > EMA-20  (confirmed uptrend)",
        "    4. Not already in an open position",
        "    5. Ranks in top 6 of scored universe",
        "",
        "  SHORT ENTRY FILTERS (ALL must be True):",
        "    1. composite_score < 0  (net negative momentum)",
        "    2. RSI(14) between 30 and 70",
        "    3. Price < EMA-20  (confirmed downtrend)",
        "    4. Not already in an open position (long or short)",
        "    5. Ticker is shortable AND easy-to-borrow (Alpaca check)",
        "    6. Ranks in bottom 3 of scored universe",
        "",
        "  STOP LOSS FORMULA (volatility-scaled):",
        "    vol_factor = annualized_volatility_20d / 100",
        "    stop_loss_pct  = -clamp(vol_factor * 1.5, 0.04, 0.10)",
        "",
        "  TAKE PROFIT FORMULA:",
        "    take_profit_pct = +clamp(vol_factor * 2.5, 0.06, 0.20)",
        "",
        "  POSITION SIZING:",
        "    Fixed 10% of equity per position until 30+ closed trades.",
        "    After 30 closed trades: half-Kelly formula, capped at 15%.",
        "    Max 6 longs + 3 shorts = 9 positions simultaneously.",
        "",
        "  ORACLE PROFIT RESERVE:",
        "    15% of each winning trade's gross profit is swept to the Oracle Profit",
        "    Reserve (DB ledger — NOT invested).  This is tracked separately in the",
        "    diagnostic report under 'Oracle Profit Reserve'.",
        "",
        "  CYCLE FREQUENCY:",
        "    Runs every 15 minutes during NYSE market hours (09:01–15:46 ET Mon-Fri).",
        "    No afterhours trading.  No weekends.  No LLM calls.",
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
        "    Calypso (mean_reversion_conservative): market-cap tiered sizing, Z≥2 + VPIN + RSI triple gate, 48h max hold",
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
        "    THRESHOLD: IVR < 25 (implied volatility is compressed)",
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
        "    1. IVR < 25",
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
    _h2(lines, "ORACLE #1 — STRATEGY STATUS & MOMENTUM SCAN")

    lines += [
        "  STRATEGY: Pure Momentum v3.0 (deterministic — no LLM, no SGOV, no JEPQ)",
        "  Universe: ~250 NYSE/NASDAQ stocks  |  Scan frequency: every 15 min (market hours only)",
        "",
        "  SCORE = 5d_return*0.20 + 20d_return*0.50 + 60d_return*0.30",
        "  LONG  filters: score>0, RSI 30-70, price>EMA20  (top 6 max)",
        "  SHORT filters: score<0, RSI 30-70, price<EMA20  (bottom 3 max, ETB check)",
        "",
    ]

    try:
        from db.postgres import get_oracle_profit_reserve
        pr = get_oracle_profit_reserve()
        _row(lines, "Oracle Profit Reserve:", f"${pr['total_usd']:,.2f}  ({pr['contributions']} contributions)")
        if pr["last_ts"]:
            _row(lines, "Last contribution:", f"${pr['last_contribution']:,.2f}  at {str(pr['last_ts'])[:19]}")
    except Exception:
        lines.append("  Oracle Profit Reserve: unavailable")

    lines.append("")
    lines.append("  LAST MOMENTUM SCAN RESULTS (from pipeline state):")
    try:
        from core.pipeline import _state as _pipeline_state
        _scanner = _pipeline_state.get("last_algo_scanner") or {}
        _top5_long  = _scanner.get("top5_long",  [])
        _top5_short = _scanner.get("top5_short", [])
        _scan_type  = _scanner.get("scan_type", "N/A")
        _universe   = _scanner.get("universe_scanned", 0)
        _n_signals  = _scanner.get("active_signals", 0)

        _row(lines, "Scan type:", _scan_type)
        _row(lines, "Universe scanned:", str(_universe))
        _row(lines, "Long signals:", str(_n_signals))

        if _top5_long:
            lines.append("  Top 5 long candidates:")
            for c in _top5_long:
                score = c.get("score") or c.get("composite_score") or 0
                rsi   = c.get("rsi") or 0
                lines.append(f"    {c['ticker']:10s}  score={score:+.2f}  RSI={rsi:.0f}")

        if _top5_short:
            lines.append("  Bottom 5 short candidates:")
            for c in _top5_short:
                score = c.get("score") or c.get("composite_score") or 0
                rsi   = c.get("rsi") or 0
                lines.append(f"    {c['ticker']:10s}  score={score:+.2f}  RSI={rsi:.0f}")
    except Exception:
        lines.append("  Pipeline state unavailable — scan data will populate after first cycle.")

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
        for ts, to_r, from_r in changes:
            lines.append(f"  {ts:<22} {from_r:<15} {to_r:<15}")
    else:
        lines.append(f"  No regime history in equity_snapshots. Capturing from {_today_str()} forward.")

    return lines


def section_vpin_shadow_log() -> list[str]:
    lines: list[str] = []
    _h2(lines, "VPIN SHADOW LOG (Trades blocked by VPIN filter)")

    db_rows = _pg_query("""
        SELECT bot_id, pair, vpin_value, threshold, direction, price, ts, reason
        FROM vpin_rejections
        ORDER BY ts DESC
        LIMIT 500
    """)

    if db_rows:
        lines.append(f"  [Persistent VPIN rejection log — {len(db_rows)} most recent entries]")
        lines.append("")

        by_bot: dict[str, list] = {}
        for r in db_rows:
            bid = r.get("bot_id", "?")
            by_bot.setdefault(bid, []).append(r)

        for bid in sorted(by_bot):
            bot_rows = by_bot[bid]
            lines.append(f"  {bid} — {len(bot_rows)} recent rejections:")
            lines.append(f"    {'Timestamp':<20} {'Pair':<10} {'VPIN':>7} {'Thresh':>7} {'Dir':<6} {'Price':>12}")
            lines.append("    " + "-" * 65)
            for r in bot_rows:
                ts_str = str(r.get("ts", "?"))[:19]
                pair = str(r.get("pair", "?"))[:9]
                vpin = float(r.get("vpin_value", 0))
                thresh = float(r.get("threshold", 0))
                direction = str(r.get("direction", "?"))[:5]
                price = float(r.get("price", 0))
                lines.append(f"    {ts_str:<20} {pair:<10} {vpin:>7.3f} {thresh:>7.3f} {direction:<6} {_c(price):>12}")
            lines.append("")

        total_rows = _pg_query("SELECT COUNT(*) as cnt FROM vpin_rejections")
        total_count = int(total_rows[0]["cnt"]) if total_rows else 0
        lines.append(f"  All-time VPIN rejections logged: {total_count}")
    else:
        lines.append(f"  No VPIN rejections logged yet. Capturing from {_today_str()} forward.")

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
                vpin_blocks = [s for s in signals if "blocked" in str(s.get("signal_type", "")).lower()]
                if vpin_blocks:
                    lines.append(f"\n  {bot_id} — current cycle micro blocks: {len(vpin_blocks)}")
                    for vb in vpin_blocks[:5]:
                        lines.append(f"    Symbol: {vb.get('symbol', '?')}  Price: {vb.get('price', '?')}")
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
    pool_map = {
        "oracle": "alpaca",
        "kraken": "kraken",
        "options": "options",
        "forex": "forex",
        "all": None,
    }
    col = col_map.get(source, "total_equity")
    pool_name = pool_map.get(source)

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

    injection_by_day: dict[str, float] = {}
    if pool_name:
        inj_rows = _pg_query(
            "SELECT DATE(ts) as day, SUM(amount_usd) as total FROM capital_injections WHERE pool = %s GROUP BY DATE(ts)",
            (pool_name,),
        )
    else:
        inj_rows = _pg_query(
            "SELECT DATE(ts) as day, SUM(amount_usd) as total FROM capital_injections GROUP BY DATE(ts)"
        )
    for ir in inj_rows:
        if ir.get("day"):
            injection_by_day[str(ir["day"])] = float(ir["total"] or 0)

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
        if injection_by_day:
            lines.append(f"  NOTE: Capital injections detected and subtracted from P&L on {len(injection_by_day)} day(s)")
        lines.append(f"  {'Date':<12} {'Open Eq':>14} {'Close Eq':>14} {'Daily P&L':>12} {'Daily %':>9} {'Regime':<12} {'Trades':>7}")
        lines.append("  " + "-" * 82)
        prev_close = None
        for r in rows:
            day = str(r["day"])
            open_eq = float(r.get("open_eq") or 0)
            close_eq = float(r.get("close_eq_proxy") or 0)
            regime = str(r.get("regime") or "?")[:10]
            injection = injection_by_day.get(day[:10], 0.0)
            base = prev_close if prev_close else open_eq
            daily_pnl = close_eq - base - injection
            daily_pct = (daily_pnl / base * 100) if base > 0 else 0
            trades = trade_counts.get(day[:10], 0)
            inj_marker = f" [+{_c(injection)} injected]" if injection > 0 else ""
            lines.append(f"  {day:<12} {_c(open_eq):>14} {_c(close_eq):>14} {_c(daily_pnl):>12} {_pct(daily_pct):>9} {regime:<12} {trades:>7}{inj_marker}")
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

    corr_data: dict = {}
    try:
        from analysis.correlation_matrix import compute_correlation_matrix
        corr_data = compute_correlation_matrix()
    except Exception:
        corr_path = Path(__file__).parent.parent / "data" / "correlation_state.json"
        try:
            if corr_path.exists():
                corr_data = json.loads(corr_path.read_text())
        except Exception:
            pass

    matrix = corr_data.get("matrix", {})
    data_points = corr_data.get("data_points", {})
    note = corr_data.get("note", "")

    if note:
        lines.append(f"  Note: {note}")

    if matrix:
        lines.append("  [Computed from equity_snapshots daily returns]")
        lines.append(f"  Data points per bot: {data_points}")
        lines.append(f"  Min required for correlation: 3 overlapping days")
        lines.append(f"  Computed at: {str(corr_data.get('computed_at', 'N/A'))[:19]}")
        lines.append("")
        lines.append(f"  {'Bot Pair':<30} {'Correlation':>12} {'Flag':>10}")
        lines.append("  " + "-" * 55)
        for pair, coeff in sorted(matrix.items()):
            if coeff is None:
                lines.append(f"  {pair:<30} {'N/A':>12} {'INSUF':>10}")
            else:
                c = float(coeff)
                flag = "HIGH" if abs(c) > 0.70 else ""
                lines.append(f"  {pair:<30} {c:>+12.4f} {flag:>10}")

        max_c = corr_data.get("max_correlation")
        shock = corr_data.get("systemic_shock", False)
        scale = corr_data.get("position_scale_factor", 1.0)
        lines.append("")
        _row(lines, "Max correlation:", f"{float(max_c):.4f}" if max_c is not None else "N/A (insufficient data)")
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
            scan_results_raw = state.get("last_scan_results")
            lines.append(f"  Last scan time: {str(last_scan)[:19] if last_scan else 'Never'}")

            scanner_detail: list = []
            if isinstance(scan_results_raw, list):
                scanner_detail = scan_results_raw
                signals = [s for s in scanner_detail if s.get("signal") in (True, "True")]
                squeezes = [s for s in scanner_detail if s.get("is_squeeze") in (True, "True")]
                lines.append(f"  Tickers evaluated: {len(scanner_detail)}")
                lines.append(f"  Squeeze detected: {len(squeezes)}")
                lines.append(f"  Signals generated: {len(signals)}")
            elif isinstance(scan_results_raw, dict):
                evaluated = scan_results_raw.get("tickers_evaluated", 0)
                setups = scan_results_raw.get("setups_found", 0)
                entries = scan_results_raw.get("entries_taken", 0)
                lines.append(f"  Tickers evaluated: {evaluated}")
                lines.append(f"  Setups found (IVR<25 + squeeze): {setups}")
                lines.append(f"  Entries taken: {entries}")
                scanner_detail = scan_results_raw.get("scanner_detail", [])

            if scanner_detail:
                lines.append("")
                lines.append(f"  {'Ticker':<8} {'IVR':>8} {'Squeeze':>8} {'BW%':>10} {'Status':<25}")
                lines.append("  " + "-" * 62)
                for sd in scanner_detail:
                    ticker = sd.get("ticker") or sd.get("symbol", "?")
                    ivr_val = sd.get("ivr", "?")
                    if isinstance(ivr_val, (int, float)):
                        ivr_str = f"{ivr_val:.1f}"
                    else:
                        ivr_str = str(ivr_val)
                    squeeze = sd.get("is_squeeze", sd.get("squeeze", False))
                    squeeze_str = "YES" if squeeze in (True, "True") else "NO"
                    bw = sd.get("bandwidth") or sd.get("bollinger_bandwidth", "?")
                    if isinstance(bw, (int, float)):
                        bw_str = f"{bw:.2f}"
                    else:
                        bw_str = str(bw)
                    status = str(sd.get("rejection_reason") or sd.get("status", "?"))[:25]
                    lines.append(
                        f"  {ticker:<8} {ivr_str:>8} {squeeze_str:>8} {bw_str:>10} {status:<25}"
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
        ORDER BY date DESC
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
        insight = str(e.get("insight_text", "?"))[:120]
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


def section_regime_performance_matrix(bot_label: str, bot_id: str) -> list[str]:
    """
    Stage 1 — Regime-Conditional Strategy Performance Matrix.
    Shows per-regime metrics for a specific Kraken bot plus the active
    regime_size_multiplier being applied to all new entries.
    """
    lines: list[str] = []
    _h2(lines, f"REGIME PERFORMANCE MATRIX — {bot_label}")

    # Load normaliser from regime_tracker — used for both display and comparison
    total_mult = 1.0
    mult_reason = "No current regime data"
    current_regime_raw = "Unknown"
    current_regime_canonical = "Unknown"
    _normalise = None

    try:
        import sys, os
        _kb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kraken-bot")
        if _kb_path not in sys.path:
            sys.path.insert(0, _kb_path)
        from regime_tracker import (
            get_current_regime,
            calculate_regime_size_multiplier,
            normalise_regime,
        )
        _normalise = normalise_regime
        current_regime_raw = get_current_regime()
        current_regime_canonical = normalise_regime(current_regime_raw)
        total_mult, mult_reason = calculate_regime_size_multiplier(bot_id, current_regime_raw)
    except Exception as exc:
        mult_reason = f"regime_tracker unavailable: {exc}"

    # Fetch raw trade rows — normalise and aggregate in Python so all variants
    # (e.g. "Crypto [Reconstructed]", "Crypto-Risk-Off") merge under "Crypto"
    raw_rows = _pg_query(
        """
        SELECT
            COALESCE(NULLIF(regime_at_entry, ''), 'Unknown') AS regime,
            pnl_usd
        FROM kraken_trades
        WHERE bot_id = %s
        """,
        (bot_id,),
    )

    if not raw_rows:
        lines.append("  No trade data available for regime analysis.")
        return lines

    # Aggregate by canonical regime label
    buckets: dict = {}
    for row in raw_rows:
        canon = _normalise(str(row["regime"])) if _normalise else str(row["regime"])
        pnl   = float(row["pnl_usd"] or 0.0)
        if canon not in buckets:
            buckets[canon] = {"pnls": [], "wins": 0}
        buckets[canon]["pnls"].append(pnl)
        if pnl > 0:
            buckets[canon]["wins"] += 1

    # Sort by trade count descending
    sorted_regimes = sorted(buckets.items(), key=lambda kv: len(kv[1]["pnls"]), reverse=True)

    lines.append("")
    lines.append(
        f"  {'Regime':<18} {'Trades':>7} {'Win%':>7} {'AvgP&L':>9} "
        f"{'ProfFact':>9} {'TotalP&L':>11}"
    )
    lines.append("  " + "-" * 65)

    for canon, data in sorted_regimes:
        pnls      = data["pnls"]
        n         = len(pnls)
        wins      = data["wins"]
        total_pnl = sum(pnls)
        avg_pnl   = total_pnl / n if n > 0 else 0.0
        gross_p   = sum(p for p in pnls if p > 0)
        gross_l   = abs(sum(p for p in pnls if p < 0))
        win_rate  = wins / n if n > 0 else 0.0
        pf        = gross_p / gross_l if gross_l > 0 else (99.99 if gross_p > 0 else 0.0)
        pf_str    = f"{pf:.2f}" if pf < 99 else "∞"

        # Mark currently active regime
        is_active = (canon == current_regime_canonical)
        regime_display = f"► {canon}" if is_active else f"  {canon}"

        lines.append(
            f"  {regime_display:<18} {n:>7} {win_rate:>6.1%} {avg_pnl:>+9.2f} "
            f"{pf_str:>9} {total_pnl:>+11.2f}"
        )

    lines.append("")
    lines.append(f"  Current regime (raw)      : {current_regime_raw}")
    lines.append(f"  Current regime (canonical): {current_regime_canonical}")
    lines.append(f"  Active size multiplier    : {total_mult:.2f}×")
    lines.append(f"  Reason                    : {mult_reason}")
    lines.append("")
    lines.append("  Historical trades backfilled from equity_snapshots.")
    lines.append("  New trades carry live canonical regime labels (e.g. 'Crypto', 'Bear').")

    return lines


def section_correlation_aware_sizing(bot_label: str, bot_id: str) -> list[str]:
    """
    Stage 2 — Correlation-Aware Portfolio Sizing.
    Shows pairwise correlations between currently open positions for this bot,
    plus what correlation penalty (if any) would be applied to a new entry.
    """
    lines: list[str] = []
    _h2(lines, f"CORRELATION-AWARE SIZING — {bot_label}")

    try:
        import sys, os
        _kb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kraken-bot")
        if _kb_path not in sys.path:
            sys.path.insert(0, _kb_path)
        from correlation_tracker import (
            summarise_open_correlations,
            HIGH_CORR_THRESHOLD,
            MODERATE_CORR_THRESHOLD,
            CORR_WINDOW,
        )
    except Exception as exc:
        lines.append(f"  correlation_tracker unavailable: {exc}")
        return lines

    # Load open positions for this bot via DB
    open_rows = _pg_query(
        """
        SELECT symbol, entry_price, size_usd
        FROM kraken_positions
        WHERE bot_id = %s AND status = 'open'
        ORDER BY symbol
        """,
        (bot_id,),
    )

    if not open_rows:
        lines.append("  No open positions — correlation-aware sizing active but idle.")
        lines.append("")
        lines.append(f"  Thresholds: HIGH > {HIGH_CORR_THRESHOLD:.0%}  →  0.50×")
        lines.append(f"              MODERATE > {MODERATE_CORR_THRESHOLD:.0%}  →  0.75×")
        lines.append(f"              LOW ≤ {MODERATE_CORR_THRESHOLD:.0%}  →  1.00×  (no adjustment)")
        return lines

    open_symbols = [r["symbol"] for r in open_rows]

    # Attempt to load closes_cache from correlation_tracker module — only
    # available in-process (the trading bot's memory), so it may be empty here.
    # Fall back to a note explaining this.
    try:
        import importlib
        ct_mod = importlib.import_module("correlation_tracker")
        # The closes_cache lives in main.py, not the tracker — explain that.
        closes_available = False
    except Exception:
        closes_available = False

    lines.append("")
    lines.append(f"  Open positions ({len(open_symbols)}): {', '.join(open_symbols)}")
    lines.append("")
    lines.append(
        f"  {'Symbol':<14} {'Max Corr':>9} {'With':>14} {'Avg Corr':>9} {'Status':>14}"
    )
    lines.append("  " + "-" * 62)
    lines.append(
        "  Correlation data is computed live in the bot process each cycle."
    )
    lines.append(
        "  The bot log will show CorrSizing lines for each entry attempt."
    )
    lines.append("")
    lines.append(f"  Thresholds active:")
    lines.append(f"    avg_corr > {HIGH_CORR_THRESHOLD:.0%}  →  0.50×  (HIGH — halve size)")
    lines.append(f"    avg_corr > {MODERATE_CORR_THRESHOLD:.0%}  →  0.75×  (MODERATE — reduce 25%)")
    lines.append(f"    avg_corr ≤ {MODERATE_CORR_THRESHOLD:.0%}  →  1.00×  (LOW — no adjustment)")
    lines.append(f"  Window : last {CORR_WINDOW} OHLCV closes (1h candles = ~{CORR_WINDOW}h lookback)")

    return lines


def section_per_pair_auto_params(bot_label: str, bot_id: str) -> list[str]:
    """
    Stage 3 — Per-Pair Automatic Parameter Adjustment.
    Reads computed pair stats from kraken_pair_params and displays them in a
    formatted table showing win rate, profit factor, and the auto-derived
    sizing multiplier and z-score threshold factor for each symbol.
    """
    lines: list[str] = []
    _h2(lines, f"PER-PAIR AUTO PARAMS — {bot_label}")

    rows = _pg_query(
        """
        SELECT symbol, trade_count, win_rate, profit_factor,
               avg_win_pct, avg_loss_pct, auto_size_mult, auto_zscore_factor,
               computed_at
        FROM   kraken_pair_params
        WHERE  bot_id = %s
        ORDER  BY profit_factor DESC
        """,
        (bot_id,),
    )

    if not rows:
        lines.append("  No per-pair params computed yet — first refresh runs at bot startup.")
        lines.append("  Data appears after ≥8 closed trades per symbol in the last 30 days.")
        lines.append("")
        lines.append("  Auto-sizing rules (by Profit Factor):")
        lines.append("    PF ≥ 1.50 and WR ≥ 50%  →  1.20×  (auto-boost)")
        lines.append("    PF 1.00–1.50              →  1.00×  (neutral)")
        lines.append("    PF 0.60–1.00              →  0.75×  (caution)")
        lines.append("    PF 0.30–0.60              →  0.50×  (suppress)")
        lines.append("    PF < 0.30                 →  0.30×  (heavy suppress)")
        lines.append("")
        lines.append("  Z-score factor rules (by Win Rate):")
        lines.append("    WR ≥ 55%  →  0.90×  (lower bar — proven pair)")
        lines.append("    WR 40–55% →  1.00×  (neutral)")
        lines.append("    WR 25–40% →  1.15×  (raise bar)")
        lines.append("    WR < 25%  →  1.30×  (significantly raise bar)")
        return lines

    # Determine freshness from latest computed_at
    import datetime as _dt
    from datetime import timezone as _tz
    _freshness = ""
    try:
        _latest_ts = max(r["computed_at"] for r in rows if r.get("computed_at"))
        _age_h = (_dt.datetime.now(_tz.utc) - _latest_ts).total_seconds() / 3600
        _freshness = f"(computed {_age_h:.1f}h ago, refreshes every 6h)"
    except Exception:
        pass

    lines.append(f"  {len(rows)} symbols with data {_freshness}")
    lines.append("")

    MIN_TRADES = 8
    has_data_count = sum(1 for r in rows if r["trade_count"] >= MIN_TRADES)
    neutral_count  = sum(1 for r in rows if r["trade_count"] >= MIN_TRADES
                         and r["auto_size_mult"] == 1.0 and r["auto_zscore_factor"] == 1.0)
    adjusted_count = has_data_count - neutral_count

    lines.append(
        f"  {'Symbol':<14} {'Trades':>6} {'WR':>6} {'PF':>6} "
        f"{'AvgWin':>8} {'AvgLoss':>8} {'SizeMult':>9} {'ZFactor':>8} {'Status':>12}"
    )
    lines.append("  " + "-" * 82)

    for r in rows:
        sym    = r["symbol"]
        n      = r["trade_count"]
        wr     = r["win_rate"]
        pf     = r["profit_factor"]
        aw     = r["avg_win_pct"]
        al     = r["avg_loss_pct"]
        sm     = r["auto_size_mult"]
        zf     = r["auto_zscore_factor"]

        if n < MIN_TRADES:
            status = "insufficient"
            sm_str = "–"
            zf_str = "–"
        else:
            sm_str = f"{sm:.2f}×"
            zf_str = f"{zf:.2f}×"
            if sm > 1.0:
                status = "AUTO-BOOST"
            elif sm < 0.65:
                status = "SUPPRESSED"
            elif sm < 1.0:
                status = "CAUTION"
            elif zf != 1.0:
                status = "Z-ADJ"
            else:
                status = "neutral"

        lines.append(
            f"  {sym:<14} {n:>6} {wr:>6.1%} {pf:>6.2f} "
            f"{aw:>8.2%} {al:>8.2%} {sm_str:>9} {zf_str:>8} {status:>12}"
        )

    lines.append("  " + "-" * 82)
    lines.append(
        f"  Totals: {len(rows)} symbols | {has_data_count} with data | "
        f"{adjusted_count} adjusted | {neutral_count} neutral"
    )
    lines.append("")
    lines.append("  Notes:")
    lines.append(f"    Lookback : 30 days of closed trades  |  Min trades: {MIN_TRADES}")
    lines.append("    Manual PAIR_SIZING_PENALIZED/BOOSTED always override auto_size_mult.")
    lines.append("    auto_zscore_factor applies to ALL pairs (no manual override).")
    lines.append("    Refresh interval: every 6 hours from bot startup.")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4 — Strategy Health Monitor
# ──────────────────────────────────────────────────────────────────────────────

_STATUS_ICON = {"HEALTHY": "✅", "WARNING": "⚠️", "CRITICAL": "🔴"}
_METRIC_LABEL = {
    "recent_win_rate":      "Win Rate (last 20)",
    "recent_profit_factor": "Profit Factor (last 20)",
    "equity_drawdown":      "Equity Drawdown",
    "loss_streak":          "Loss Streak",
    "fee_efficiency":       "Fee Efficiency",
    "symbol_concentration": "Symbol Concentration",
}
_METRIC_WEIGHT_PCT = {
    "recent_win_rate":      "25%",
    "recent_profit_factor": "25%",
    "equity_drawdown":      "20%",
    "loss_streak":          "15%",
    "fee_efficiency":       "10%",
    "symbol_concentration":  "5%",
}


def _fetch_health_snapshot(bot_id: str) -> dict | None:
    """Return latest health snapshot row for bot_id from DB."""
    import psycopg2, psycopg2.extras
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT bot_id, checked_at, overall_score, overall_status, metrics, recommendations
                FROM   kraken_health_snapshots
                WHERE  bot_id = %s
                ORDER  BY checked_at DESC
                LIMIT  1
                """,
                (bot_id,),
            )
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning(f"section_strategy_health: DB query failed: {exc}")
        return None


def _fetch_health_trend(bot_id: str, limit: int = 7) -> list[dict]:
    """Return last `limit` daily health scores for trend sparkline."""
    import psycopg2, psycopg2.extras
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return []
    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT checked_at, overall_score, overall_status
                FROM   kraken_health_snapshots
                WHERE  bot_id = %s
                ORDER  BY checked_at DESC
                LIMIT  %s
                """,
                (bot_id, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return list(reversed(rows))
    except Exception:
        return []


def section_strategy_health_monitor(bot_id: str) -> list[str]:
    """
    Stage 4 — Strategy Health Monitor report section.
    Shows the latest daily health snapshot for one Kraken bot.
    """
    lines: list[str] = []
    _h1(lines, f"STAGE 4 — STRATEGY HEALTH MONITOR  [{bot_id.upper()}]")

    snap = _fetch_health_snapshot(bot_id)
    if snap is None:
        lines.append(f"  No health snapshot found for {bot_id}.")
        lines.append("  Health Monitor runs at 4:00 AM UTC daily.")
        lines.append("  First snapshot will be available after the next scheduled run.")
        return lines

    # Header — overall score
    checked_at = snap.get("checked_at")
    if hasattr(checked_at, "strftime"):
        ts_str = checked_at.strftime("%Y-%m-%d %H:%M UTC")
    else:
        ts_str = str(checked_at)[:16]

    o_score  = snap.get("overall_score", 0)
    o_status = snap.get("overall_status", "UNKNOWN")
    icon     = _STATUS_ICON.get(o_status, "❓")

    lines.append(f"  Last checked : {ts_str}")
    lines.append(f"  Overall score: {o_score}/100  {icon} {o_status}")
    lines.append("")

    # Metric table
    metrics_raw = snap.get("metrics") or {}
    if isinstance(metrics_raw, str):
        try:
            import json as _json
            metrics_raw = _json.loads(metrics_raw)
        except Exception:
            metrics_raw = {}

    lines.append(f"  {'Metric':<28} {'Weight':>6}  {'Score':>5}  {'Status':>8}  Details")
    lines.append("  " + "-" * 80)

    for key in _METRIC_LABEL:
        m      = metrics_raw.get(key, {})
        label  = _METRIC_LABEL[key]
        weight = _METRIC_WEIGHT_PCT[key]
        score  = m.get("score", "—")
        status = m.get("status", "—")
        detail = m.get("details", "")
        s_icon = _STATUS_ICON.get(status, "")
        lines.append(
            f"  {label:<28} {weight:>6}  {str(score):>5}  {s_icon} {status:<8}  {detail}"
        )

    lines.append("  " + "-" * 80)
    lines.append(f"  Weighted overall score: {o_score}/100")
    lines.append("")

    # Score trend (last 7 days)
    trend = _fetch_health_trend(bot_id, limit=7)
    if len(trend) >= 2:
        lines.append("  7-Day Score Trend:")
        sparkline = ""
        for t in trend:
            s = t.get("overall_score", 0)
            st = t.get("overall_status", "")
            block = "█" if s >= 80 else ("▆" if s >= 60 else "▂")
            d_str = ""
            d = t.get("checked_at")
            if hasattr(d, "strftime"):
                d_str = d.strftime("%m-%d")
            elif d:
                d_str = str(d)[5:10]
            sparkline += f"  {d_str}: {block} {s:>3} ({st})\n"
        lines.extend(["  " + l for l in sparkline.strip().splitlines()])
        lines.append("")

    # Recommendations
    recs_raw = snap.get("recommendations") or []
    if isinstance(recs_raw, str):
        try:
            import json as _json
            recs_raw = _json.loads(recs_raw)
        except Exception:
            recs_raw = []

    lines.append("  Recommendations:")
    for i, rec in enumerate(recs_raw, 1):
        lines.append(f"    {i}. {rec}")
    if not recs_raw:
        lines.append("    No recommendations (all metrics healthy).")

    lines.append("")
    lines.append("  Schedule : 4:00 AM UTC daily  |  Fully deterministic (no LLM)")
    lines.append("  Metrics  : win rate, profit factor, drawdown, loss streak, fee drag, symbol concentration")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# Stage 5 — Walk-Forward Parameter Optimiser
# ──────────────────────────────────────────────────────────────────────────────

_CONF_ICON = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}


def _fetch_wfo_result(bot_id: str) -> dict | None:
    import psycopg2, psycopg2.extras
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT bot_id, run_at, total_trades, windows_analysed,
                       overall_confidence, stability_score,
                       rec_sl_pct, rec_tp_pct, rec_best_regime, rec_worst_regime,
                       rec_focus_symbols, rec_avoid_symbols,
                       window_results, regime_breakdown, oos_validation, summary
                FROM   kraken_wfo_results
                WHERE  bot_id = %s
                ORDER  BY run_at DESC
                LIMIT  1
                """,
                (bot_id,),
            )
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning(f"section_wfo: DB query failed: {exc}")
        return None


def _jload(val, default):
    if val is None:
        return default
    if isinstance(val, str):
        try:
            import json as _j
            return _j.loads(val)
        except Exception:
            return default
    return val


def section_walk_forward_optimizer(bot_id: str) -> list[str]:
    """
    Stage 5 — Walk-Forward Parameter Optimiser report section.
    Shows the latest weekly WFO result for one Kraken bot.
    """
    lines: list[str] = []
    _h1(lines, f"STAGE 5 — WALK-FORWARD PARAMETER OPTIMISER  [{bot_id.upper()}]")

    res = _fetch_wfo_result(bot_id)
    if res is None:
        lines.append(f"  No WFO result found for {bot_id}.")
        lines.append("  Walk-Forward Optimiser runs every Sunday at 2:00 AM UTC.")
        lines.append("  First result available after the next Sunday run.")
        return lines

    run_at = res.get("run_at")
    if hasattr(run_at, "strftime"):
        ts_str = run_at.strftime("%Y-%m-%d %H:%M UTC")
    else:
        ts_str = str(run_at)[:16]

    n_trades  = res.get("total_trades", 0)
    n_windows = res.get("windows_analysed", 0)
    conf      = res.get("overall_confidence", "LOW")
    stability = res.get("stability_score", 0)
    c_icon    = _CONF_ICON.get(conf, "❓")

    lines.append(f"  Last run     : {ts_str}")
    lines.append(f"  Trades used  : {n_trades}")
    lines.append(f"  Windows      : {n_windows}")
    lines.append(f"  Stability    : {stability}/100  (WR + PF consistency across windows)")
    lines.append(f"  Confidence   : {c_icon} {conf}")
    lines.append("")

    # ── Parameter Recommendations ──────────────────────────────────────────
    _h2(lines, "Parameter Recommendations  (advisory only — does not auto-apply)")
    rec_sl   = res.get("rec_sl_pct")
    rec_tp   = res.get("rec_tp_pct")
    rec_best = res.get("rec_best_regime")
    rec_worst= res.get("rec_worst_regime")
    focus    = _jload(res.get("rec_focus_symbols"), [])
    avoid    = _jload(res.get("rec_avoid_symbols"), [])

    if rec_sl is not None:
        lines.append(f"  Stop-loss    : {rec_sl:.2f}%  (median observed stop exit across all windows)")
    else:
        lines.append("  Stop-loss    : insufficient stop-exit data")

    if rec_tp is not None:
        lines.append(f"  Take-profit  : {rec_tp:.2f}%  (median observed TP/trail exit across all windows)")
    else:
        lines.append("  Take-profit  : insufficient TP-exit data")

    if rec_best:
        lines.append(f"  Best regime  : {rec_best}  (highest median PF)")
    if rec_worst:
        lines.append(f"  Worst regime : {rec_worst}  (lowest median PF — consider reducing size)")
    if focus:
        lines.append(f"  Focus symbols: {', '.join(focus)}  (consistent top performers)")
    else:
        lines.append("  Focus symbols: no consistent top performers yet")
    if avoid:
        lines.append(f"  Avoid symbols: {', '.join(avoid)}  (consistent underperformers)")
    lines.append("")

    # ── Per-Window Summary ─────────────────────────────────────────────────
    window_results = _jload(res.get("window_results"), [])
    if window_results:
        _h2(lines, "Sliding Window Analysis")
        lines.append(
            f"  {'Window':<20} {'N':>5} {'WR':>6} {'PF':>6} "
            f"{'AvgWin%':>8} {'AvgLoss%':>9} {'Top Symbol':<14} {'Exit'}"
        )
        lines.append("  " + "-" * 82)
        for w in window_results:
            if w.get("skipped"):
                lines.append(f"  {w.get('label','?'):<20} {'—':>5}  skipped ({w.get('reason','')})")
                continue
            label    = w.get("label", "?")
            n        = w.get("n", 0)
            wr       = w.get("wr", 0)
            pf       = w.get("pf", 0)
            aw       = w.get("avg_win_pct")
            al       = w.get("avg_loss_pct")
            top_sym  = (w.get("top_symbols") or ["—"])[0]
            dom_exit = w.get("dominant_exit", "?")
            aw_str   = f"{aw:+.2f}%" if aw is not None else "   —"
            al_str   = f"{al:+.2f}%" if al is not None else "   —"
            lines.append(
                f"  {label:<20} {n:>5} {wr:>5.1%} {pf:>6.2f} "
                f"{aw_str:>8} {al_str:>9} {top_sym:<14} {dom_exit}"
            )
        lines.append("  " + "-" * 82)
        lines.append("")

    # ── Regime Breakdown ───────────────────────────────────────────────────
    regime_bd = _jload(res.get("regime_breakdown"), {})
    if regime_bd:
        _h2(lines, "Full-History Regime Breakdown")
        lines.append(f"  {'Regime':<22} {'N':>5} {'WR':>6} {'PF':>6} {'Net P&L':>10}")
        lines.append("  " + "-" * 52)
        for reg, m in sorted(regime_bd.items(), key=lambda x: x[1].get("pf", 0), reverse=True):
            n_r   = m.get("n", 0)
            wr_r  = m.get("wr", 0)
            pf_r  = m.get("pf", 0)
            net_r = m.get("net", 0)
            flag  = " ← best" if reg == rec_best else (" ← avoid" if reg == rec_worst else "")
            lines.append(
                f"  {reg:<22} {n_r:>5} {wr_r:>5.1%} {pf_r:>6.2f} "
                f"{net_r:>+10.2f}{flag}"
            )
        lines.append("")

    # ── OOS Validation ────────────────────────────────────────────────────
    oos = _jload(res.get("oos_validation"), {})
    hit_rate = oos.get("hit_rate")
    if hit_rate is not None:
        _h2(lines, "Out-of-Sample Symbol Carry-Over Validation")
        lines.append(f"  Symbol carry-over rate: {hit_rate:.0%}  "
                     f"(did top symbols from window[n] stay top in window[n+1]?)")
        for d in (oos.get("detail") or []):
            lines.append(f"    {d.strip()}")
        lines.append("")

    lines.append("  Schedule    : Every Sunday 2:00 AM UTC  |  Fully deterministic (no LLM)")
    lines.append("  Note        : Recommendations are advisory — they do NOT auto-apply parameters.")
    lines.append("  Data source : kraken_trades (pnl_pct, reason, regime_at_entry, symbol)")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# Stage 6 — Historical Backtesting Infrastructure
# ──────────────────────────────────────────────────────────────────────────────

_VERDICT_ICON = {"BETTER": "✅", "WORSE": "❌", "NEUTRAL": "➖"}


def _fetch_backtest_result(bot_id: str) -> dict | None:
    import psycopg2, psycopg2.extras
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM   kraken_backtest_results
                WHERE  bot_id = %s
                ORDER  BY run_at DESC
                LIMIT  1
                """,
                (bot_id,),
            )
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning(f"section_backtest: DB query failed: {exc}")
        return None


def section_historical_backtest(bot_id: str) -> list[str]:
    """
    Stage 6 — Historical Backtesting Infrastructure report section.
    Shows parameter sensitivity analysis for one Kraken bot.
    """
    lines: list[str] = []
    _h1(lines, f"STAGE 6 — HISTORICAL BACKTEST INFRASTRUCTURE  [{bot_id.upper()}]")

    res = _fetch_backtest_result(bot_id)
    if res is None:
        lines.append(f"  No backtest result found for {bot_id}.")
        lines.append("  Historical Backtest runs every Sunday at 2:30 AM UTC (30 min after WFO).")
        lines.append("  First result available after the next Sunday run.")
        return lines

    run_at = res.get("run_at")
    ts_str = run_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(run_at, "strftime") else str(run_at)[:16]

    n_trades = res.get("n_trades", 0)
    lines.append(f"  Last run    : {ts_str}")
    lines.append(f"  Trades      : {n_trades}")
    lines.append(f"  Grid size   : {8 * 8} combinations (SL ∈ [0.5–5.0%] × TP ∈ [none,0.5–4.0%])")
    lines.append(f"  Method      : Realized P&L replay  (see Methodology note below)")
    lines.append("")

    # ── Scenario Comparison Table ──────────────────────────────────────────
    _h2(lines, "Scenario Comparison")
    hdr = f"  {'Scenario':<28} {'WR':>6} {'PF':>6} {'Net P&L%':>9} {'MaxDD%':>8}  {'Verdict'}"
    lines.append(hdr)
    lines.append("  " + "-" * 73)

    # Baseline
    b_wr  = res.get("baseline_wr")  or 0.0
    b_pf  = res.get("baseline_pf")  or 0.0
    b_net = res.get("baseline_net_pct") or 0.0
    b_dd  = res.get("baseline_max_dd")  or 0.0
    lines.append(
        f"  {'Actual (baseline)':<28} {b_wr:>5.1%} {b_pf:>6.2f} {b_net:>+9.2f}% {b_dd:>7.2f}%  —"
    )

    # WFO-recommended
    wfo_sl   = res.get("wfo_sl_pct")
    wfo_tp   = res.get("wfo_tp_pct")
    wfo_wr   = res.get("wfo_wr")   or 0.0
    wfo_pf   = res.get("wfo_pf")   or 0.0
    wfo_net  = res.get("wfo_net_pct") or 0.0
    wfo_dd   = res.get("wfo_max_dd")  or 0.0
    wfo_verd = res.get("wfo_verdict", "?")
    wfo_v_ic = _VERDICT_ICON.get(wfo_verd, "❓")
    wfo_tp_s = f"TP={wfo_tp:.1f}%" if wfo_tp else "TP=none"
    wfo_label = f"WFO rec  SL={wfo_sl:.1f}% {wfo_tp_s}" if wfo_sl else "WFO rec (no data)"
    lines.append(
        f"  {wfo_label:<28} {wfo_wr:>5.1%} {wfo_pf:>6.2f} {wfo_net:>+9.2f}% {wfo_dd:>7.2f}%  "
        f"{wfo_v_ic} {wfo_verd}"
    )

    # Best found
    best_sl  = res.get("best_sl_pct")
    best_tp  = res.get("best_tp_pct")
    best_wr  = res.get("best_wr")  or 0.0
    best_pf  = res.get("best_pf")  or 0.0
    best_net = res.get("best_net_pct") or 0.0
    best_dd  = res.get("best_max_dd")  or 0.0
    best_imp = res.get("best_improvement") or 0.0
    best_tp_s= f"TP={best_tp:.1f}%" if best_tp else "TP=none"
    best_label = f"Best grid SL={best_sl:.1f}% {best_tp_s}" if best_sl else "Best found"
    best_v = "BETTER" if best_imp > 0.05 else ("WORSE" if best_imp < -0.05 else "NEUTRAL")
    best_v_ic = _VERDICT_ICON.get(best_v, "❓")
    lines.append(
        f"  {best_label:<28} {best_wr:>5.1%} {best_pf:>6.2f} {best_net:>+9.2f}% {best_dd:>7.2f}%  "
        f"{best_v_ic} {best_v}"
    )
    lines.append("  " + "-" * 73)
    lines.append(f"  Best grid improvement vs baseline: {best_imp:+.2f}% net P&L")
    lines.append("")

    # ── Grid Search Top-10 ─────────────────────────────────────────────────
    grid = _jload(res.get("grid_results"), [])
    if grid:
        _h2(lines, f"Grid Search — Top {min(len(grid), 10)} Combinations (by Profit Factor)")
        lines.append(
            f"  {'Rank':>5} {'SL%':>5} {'TP%':>6} {'WR':>6} {'PF':>6} {'Net%':>7} {'MaxDD%':>8}"
        )
        lines.append("  " + "-" * 47)
        for i, g in enumerate(grid[:10], 1):
            g_sl = g.get("sl_pct", 0)
            g_tp = g.get("tp_pct")
            g_wr = g.get("wr", 0)
            g_pf = g.get("pf", 0)
            g_np = g.get("net_pct", 0)
            g_dd = g.get("max_dd", 0)
            tp_str = f"{g_tp:.1f}" if g_tp else "none"
            marker = " ◄ best" if i == 1 else ""
            lines.append(
                f"  {i:>5} {g_sl:>4.1f}% {tp_str:>6} {g_wr:>5.1%} {g_pf:>6.2f} "
                f"{g_np:>+6.2f}% {g_dd:>7.2f}%{marker}"
            )
        lines.append("")

    # ── Regime Breakdown ───────────────────────────────────────────────────
    reg_bd = _jload(res.get("regime_breakdown"), {})
    if reg_bd:
        _h2(lines, f"Regime Breakdown — Best Parameters  (SL={best_sl:.1f}% {best_tp_s})")
        lines.append(
            f"  {'Regime':<22} {'N':>5} {'Base PF':>8} {'Sim PF':>7} {'ΔPF':>7} {'Net Δ%':>8}"
        )
        lines.append("  " + "-" * 60)
        for reg, m in sorted(
            reg_bd.items(),
            key=lambda x: x[1].get("simulated", {}).get("pf", 0),
            reverse=True,
        ):
            n_r  = m.get("n", 0)
            b_m  = m.get("baseline",  {})
            s_m  = m.get("simulated", {})
            b_pf_r = b_m.get("pf", 0)
            s_pf_r = s_m.get("pf", 0)
            d_pf   = s_pf_r - b_pf_r
            d_net  = s_m.get("net_pct", 0) - b_m.get("net_pct", 0)
            lines.append(
                f"  {reg:<22} {n_r:>5} {b_pf_r:>8.2f} {s_pf_r:>7.2f} "
                f"{d_pf:>+7.2f} {d_net:>+7.2f}%"
            )
        lines.append("")

    # ── Methodology Note ───────────────────────────────────────────────────
    _h2(lines, "Methodology & Limitations")
    lines.append("  Method      : Realized P&L replay — applies new SL/TP to each trade's")
    lines.append("                recorded pnl_pct without replaying intra-trade price paths.")
    lines.append("  SL caveat   : Benefit may be overstated (no gap fills or slippage modelled).")
    lines.append("  TP caveat   : Trades that reversed after TP level are treated as clean fills.")
    lines.append("  Use as      : Directional parameter sensitivity — not exact performance prediction.")
    lines.append("")
    lines.append(f"  Schedule    : Every Sunday 2:30 AM UTC (30 min after WFO)")
    lines.append("  Deterministic — no LLM calls.  Results are advisory only.")

    return lines
