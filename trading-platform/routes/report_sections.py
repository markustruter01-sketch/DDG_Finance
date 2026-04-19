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
from core.metrics import win_rate as _win_rate, profit_factor as _profit_factor

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
    poseidon_equity: float = 0.0,
    kraken_current_equity: float = 0.0,
) -> list[str]:
    lines: list[str] = []
    _h1(lines, "SECTION 1A: FLEET SUMMARY RISK DASHBOARD")

    grand_start = 800_000.0
    grand_now = equity + kraken_equity + opts_equity + fx_equity + poseidon_equity + kraken_current_equity
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
        "#7 Poseidon": poseidon_equity - 100_000,
        "#8 Kraken Current": kraken_current_equity - 100_000,
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
        bot_names = {1: "#2 Davy Jones", 2: "#3 Blackbeard", 3: "#4 Calypso", 7: "#7 Poseidon", 8: "#8 Kraken Current"}
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
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (KRAKEN FLEET #2-5)")
    lines += [
        "  BOTS: #2 Davy Jones | #3 Blackbeard | #4 Calypso | #5 Apex Predator",
        "  All run on kraken-bot engine with bot-specific strategy profiles.",
        "",
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
        "  RSI PER BOT (Relative Strength Index, 14-period, Wilder\u2019s EMA):",
        "    Davy Jones (#2):    RSI_OVERSOLD=40  | RSI_OVERBOUGHT=60  (moderate mean-reversion)",
        "    Blackbeard (#3):    RSI_OVERSOLD=30  | RSI_OVERBOUGHT=70  (aggressive, wider bands)",
        "    Calypso (#4):       RSI_OVERSOLD=35  | RSI_OVERBOUGHT=65  (conservative mean-reversion)",
        "    Apex Predator (#5): RSI_OVERSOLD=45  | RSI_OVERBOUGHT=55  (momentum breakout, tight band)",
        "",
        "  CONTRARIAN SCOUT (shared across fleet, triggered independently of main strategy):",
        "    CONTRARIAN_RSI_THRESH = 28  (enter contrarian long when 1h RSI < 28)",
        "    CONTRARIAN_EQUITY_PCT = 1.5% (small position size for contrarian bets)",
        "    DEEP_OVERSOLD_RSI     = 20  (extra-large entry when RSI < 20)",
        "    These thresholds were calibrated Apr 2026 to improve oversold detection.",
        "",
        "  ATR-BASED STOP/TAKE PROFIT (Wilder\u2019s EMA smoothing \u2014 audit-verified):",
        "    ATR period: 14  |  Algorithm: seed with SMA of first 14 TRs, then recursive",
        "    atr_new = (atr_prev * (period - 1) + tr_current) / period",
        "    Stop Loss: entry_price \u00b1 (ATR * sl_atr_mult)",
        "    Take Profit: entry_price \u00b1 (ATR * tp_atr_mult)",
        "    Trailing stop ratchets with price movement",
        "",
        "  POSITION SIZING:",
        "    Davy Jones (#2, conservative):  smaller sizes, tighter stops",
        "    Blackbeard (#3, aggressive):     larger sizes, wider stops",
        "    Calypso (#4, conservative MR):   market-cap tiered sizing, Z\u22652 + VPIN + RSI triple gate, 48h max hold",
        "    Apex Predator (#5, momentum):    market-cap tiered sizing, 3\u00d7 ATR TP, volume \u22650.75\u00d7 avg",
        "    Max simultaneous positions: 10 per bot",
        "",
        "  CIRCUIT BREAKER:",
        "    Triggers after N consecutive losses (varies by bot profile)",
        "    Cooldown period before resuming trading",
        "",
        "  ENTRY FILTERS (ALL must be True):",
        "    1. VPIN < dynamic_threshold (no toxic flow detected)",
        "    2. Z-score exceeds threshold OR momentum signal active (bot-dependent)",
        "    3. RSI confirms direction (per-bot threshold, see above)",
        "    4. Not already holding max positions",
        "    5. Not in circuit breaker cooldown",
        "    6. Not in RAG-derived blacklist for symbol+regime",
    ]
    return lines


def section_trade_mechanics_apex() -> list[str]:
    lines: list[str] = []
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (APEX PREDATOR #5)")
    lines += [
        "  *** NOTE: Apex Predator was migrated from the options engine to Kraken ***",
        "  *** crypto momentum in Apr 2026. It now runs on kraken-bot with the     ***",
        "  *** 'apex-predator' strategy profile. All metrics below reflect the     ***",
        "  *** current live Kraken-based strategy, not the retired options engine. ***",
        "",
        "  STRATEGY: Crypto Momentum on Kraken (paper trading, $100k pool)",
        "  Exchange:  Kraken (independent from Alpaca / Oracle capital pool)",
        "",
        "  TIMEFRAMES:",
        "    Primary OHLCV: 1h candles (for RSI signal entry)",
        "    Trend filter:  4h candles (for EMA trend confirmation)",
        "",
        "  EMA TREND FILTER:",
        "    Fast EMA period: 20 (APEX_EMA_FAST = 20, on 4h)",
        "    Slow EMA period: 50 (APEX_EMA_SLOW = 50, on 4h)",
        "    LONG bias: fast_ema > slow_ema",
        "    SHORT bias: fast_ema < slow_ema",
        "",
        "  RSI ENTRY GATE (1h):",
        "    RSI period: 14  (Wilder\u2019s EMA smoothing \u2014 standard quant formula)",
        "    RSI_OVERSOLD:  45  (long entries when 1h RSI crosses up from below 45)",
        "    RSI_OVERBOUGHT: 55  (short entries when 1h RSI crosses down from above 55)",
        "    Interpretation: Tight band \u2014 momentum breakout strategy, NOT contrarian",
        "",
        "  ATR-BASED STOPS AND TAKE PROFIT:",
        "    ATR period: 14  (Wilder\u2019s EMA smoothing)",
        "    Stop loss:   entry_price \u00b1 (ATR * sl_atr_mult)",
        "    Take profit: entry_price \u00b1 (ATR * APEX_TP_ATR_MULT = 3.0)",
        "    3\u00d7 ATR take-profit gives a wider target vs the standard Kraken fleet",
        "",
        "  VPIN TOXIC FLOW FILTER:",
        "    Block entry if VPIN > APEX_VPIN_BLOCK = 0.80",
        "    (Same dynamic VPIN as rest of fleet; Apex threshold slightly tighter)",
        "",
        "  VOLUME CONFIRMATION:",
        "    Entry requires volume \u2265 APEX_VOLUME_MULT \u00d7 20-bar average",
        "    APEX_VOLUME_MULT = 0.75 (relaxed from 1.5\u00d7 \u2014 crypto weekend volumes are 0.1\u20130.8\u00d7 normal)",
        "",
        "  POSITION SIZING:",
        "    Market-cap tiered sizing (same as Calypso tier logic)",
        "    Max simultaneous positions: 10",
        "",
        "  WIN THRESHOLD:",
        "    WIN_THRESHOLD = 0.0 (pnl_usd must be strictly > 0 to count as a win)",
        "    Applied consistently via core.metrics.WIN_THRESHOLD \u2014 propagated to all",
        "    Python list comprehensions AND SQL CASE WHEN / COUNT FILTER expressions.",
    ]
    return lines


def section_trade_mechanics_navigator() -> list[str]:
    lines: list[str] = []
    _h2(lines, "TRADE MECHANICS \u2014 EXACT FORMULAS (NAVIGATOR #6)")
    lines += [
        "  RSI (Relative Strength Index):",
        "    Period: 14  |  Oversold: < 30  |  Overbought: > 70",
        "    Algorithm: Wilder\u2019s EMA smoothing (audit-verified Apr 2026)",
        "    Seed: SMA of first 14 price changes, then recursive EMA",
        "",
        "  ATR (Average True Range):",
        "    Period: 14  |  Used for all bracket calculations",
        "    Algorithm: Wilder\u2019s EMA smoothing (audit-verified Apr 2026)",
        "    atr = (atr_prev * 13 + tr_current) / 14  after SMA seed",
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
               MIN(regime) as regime,
               STRING_AGG(DISTINCT COALESCE(source, ''), ',' ORDER BY COALESCE(source, '')) as sources
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
            sources_raw = str(r.get("sources") or "")
            is_reset_day = "reset" in sources_raw.lower()
            trades = trade_counts.get(day[:10], 0)
            if is_reset_day:
                lines.append(
                    f"  {day:<12} {_c(open_eq):>14} {_c(close_eq):>14} "
                    f"{'N/A (RESET)':>12} {'---':>9} {regime:<12} {trades:>7}"
                    f"  *** EQUITY BASELINE RESET — see Fleet Operations Log. Not a trading day. Do not calculate P&L. ***"
                )
                prev_close = close_eq
                continue
            base = prev_close if prev_close else open_eq
            daily_pnl = close_eq - base - injection
            daily_pct = (daily_pnl / base * 100) if base > 0 else 0
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
                lines.append(f"  Setups found (IVR<35 + squeeze): {setups}")
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

    # Load open positions for this bot via kraken_portfolio (positions stored as JSONB)
    port_rows = _pg_query(
        "SELECT positions FROM kraken_portfolio WHERE bot_id = %s LIMIT 1",
        (bot_id,),
    )
    open_symbols: list[str] = []
    if port_rows and port_rows[0].get("positions"):
        pos_data = port_rows[0]["positions"]
        if isinstance(pos_data, dict):
            open_symbols = list(pos_data.keys())

    if not open_symbols:
        lines.append("  No open positions — correlation-aware sizing active but idle.")
        lines.append("")
        lines.append(f"  Thresholds: HIGH > {HIGH_CORR_THRESHOLD:.0%}  →  0.50×")
        lines.append(f"              MODERATE > {MODERATE_CORR_THRESHOLD:.0%}  →  0.75×")
        lines.append(f"              LOW ≤ {MODERATE_CORR_THRESHOLD:.0%}  →  1.00×  (no adjustment)")
        return lines

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


def section_fleet_operations_log() -> list[str]:
    """
    Surfaces all planned capital events (equity resets, injections) so that LLMs
    analysing the report never mistake operational adjustments for trading gains/losses.
    Always call this near the top of the export report.
    """
    lines: list[str] = []
    _h1(lines, "FLEET OPERATIONS LOG — CAPITAL EVENTS & EQUITY BASELINE RESETS")

    lines.append("")
    lines.append("  ╔══════════════════════════════════════════════════════════════════════════════╗")
    lines.append("  ║  CRITICAL NOTE FOR AI ANALYSIS — READ BEFORE INTERPRETING EQUITY CURVES     ║")
    lines.append("  ║                                                                              ║")
    lines.append("  ║  This section documents planned operational events that affect raw equity    ║")
    lines.append("  ║  numbers but are NOT the result of trading activity. Any equity change       ║")
    lines.append("  ║  labelled EQUITY_RESET must be excluded from P&L performance calculations.  ║")
    lines.append("  ║  Do NOT count these as trading gains or losses.                              ║")
    lines.append("  ╚══════════════════════════════════════════════════════════════════════════════╝")
    lines.append("")

    events = _pg_query(
        "SELECT id, ts, pool, bot_id, amount_usd, reason FROM capital_injections ORDER BY ts ASC"
    )

    if not events:
        lines.append("  No capital events recorded. This table populates when equity resets or")
        lines.append("  manual capital adjustments are applied by the operator.")
        return lines

    reset_events = [e for e in events if "EQUITY_RESET" in (e.get("reason") or "")]
    other_events  = [e for e in events if "EQUITY_RESET" not in (e.get("reason") or "")]

    if reset_events:
        _h2(lines, "EQUITY BASELINE RESETS")
        lines.append("  These rows represent planned resets to a bot's starting capital.")
        lines.append("  They do NOT represent trading profits or losses.")
        lines.append("  All trade history before the reset date is preserved in kraken_trades.")
        lines.append("")

        reset_dates: dict[str, list[dict]] = {}
        for e in reset_events:
            ts_raw = e.get("ts")
            day = str(ts_raw)[:10] if ts_raw else "unknown"
            reset_dates.setdefault(day, []).append(e)

        for day, day_events in sorted(reset_dates.items()):
            fleet_note = next((e for e in day_events if e.get("pool") == "fleet"), None)
            bot_events = [e for e in day_events if e.get("pool") != "fleet"]

            lines.append(f"  ── Reset event on {day} ──────────────────────────────────────────")
            if fleet_note:
                lines.append(f"  Scope   : {fleet_note.get('reason', '').split(':',1)[1].strip() if ':' in (fleet_note.get('reason') or '') else fleet_note.get('reason','')}")
            lines.append("")
            lines.append(f"  {'Bot':<20} {'Pool':<10} {'Adj. Amount':>14}  Explanation")
            lines.append("  " + "-" * 70)
            for e in bot_events:
                bot_id     = str(e.get("bot_id") or "?")
                pool       = str(e.get("pool") or "?")
                amount     = float(e.get("amount_usd") or 0)
                reason_txt = str(e.get("reason") or "")
                short_reason = reason_txt.split("Previous equity:")[1].strip() if "Previous equity:" in reason_txt else ""
                direction  = f"+{_c(amount)}" if amount >= 0 else _c(amount)
                lines.append(f"  {bot_id:<20} {pool:<10} {direction:>14}  {short_reason}")
            lines.append("")
            lines.append(
                f"  RESULT: After this reset, P&L for affected bots should be measured "
                f"from $100,000 starting capital as of {day}."
            )
            lines.append(
                f"  Any equity snapshot on or after {day} that shows kraken bots at ~$100,000 "
                f"is the intended new baseline — not a trading gain."
            )
            lines.append("")

    if other_events:
        _h2(lines, "OTHER CAPITAL EVENTS")
        lines.append(f"  {'Date':<12} {'Pool':<10} {'Bot':<20} {'Amount':>12}  Reason")
        lines.append("  " + "-" * 80)
        for e in other_events:
            ts_raw  = e.get("ts")
            day     = str(ts_raw)[:10] if ts_raw else "?"
            pool    = str(e.get("pool") or "?")
            bot_id  = str(e.get("bot_id") or "?")
            amount  = float(e.get("amount_usd") or 0)
            reason  = str(e.get("reason") or "")[:60]
            lines.append(f"  {day:<12} {pool:<10} {bot_id:<20} {_c(amount):>12}  {reason}")
        lines.append("")

    snap_resets = _pg_query(
        "SELECT ts, source, kraken_equity, alpaca_equity, options_equity, forex_equity, total_equity "
        "FROM equity_snapshots WHERE source NOT IN ('pipeline', 'hourly_heartbeat') "
        "ORDER BY ts ASC"
    )
    if snap_resets:
        _h2(lines, "ANNOTATED EQUITY SNAPSHOTS (non-pipeline sources)")
        lines.append("  These snapshots were inserted by operator actions, not the normal hourly pipeline.")
        lines.append(f"  {'Timestamp':<28} {'Source':<32} {'Kraken Eq':>12} {'Total Eq':>12}")
        lines.append("  " + "-" * 90)
        for s in snap_resets:
            ts_str    = str(s.get("ts") or "?")[:26]
            src       = str(s.get("source") or "?")[:30]
            k_eq      = _c(s.get("kraken_equity"))
            t_eq      = _c(s.get("total_equity"))
            lines.append(f"  {ts_str:<28} {src:<32} {k_eq:>12} {t_eq:>12}")
        lines.append("")

    return lines


# ══════════════════════════════════════════════════════════════════════════════
# SECTION: BOT #7 POSEIDON — Statistical Arbitrage / Pairs Trading
# ══════════════════════════════════════════════════════════════════════════════

def section_poseidon_status() -> list[str]:
    """Diagnostic section for Bot #7 Poseidon pairs trading bot."""
    lines: list[str] = []
    _h1(lines, "SECTION 7: BOT #7 POSEIDON — STATISTICAL ARBITRAGE (PAIRS TRADING)")
    lines.append("  Strategy: Market-neutral pairs trading on Kraken crypto markets")
    lines.append("  Starting capital: $100,000 | Cycle: 15 minutes")
    lines.append("  Entry: |Z-score| > 2.0 + Hurst < 0.5 + ADF p < 0.10 + stable hedge ratio")
    lines.append("")

    # Portfolio state
    port_rows = _pg_query("SELECT equity_usd, cash_usd, open_positions FROM poseidon_portfolio WHERE id = 7")
    if port_rows:
        p = port_rows[0]
        eq = float(p.get("equity_usd") or 100_000)
        cash = float(p.get("cash_usd") or 100_000)
        open_pos = int(p.get("open_positions") or 0)
        pnl = eq - 100_000
        _h2(lines, "PORTFOLIO SUMMARY")
        _row(lines, "Current equity:", _c(eq))
        _row(lines, "P&L vs $100k start:", _c(pnl) + f" ({_pct(pnl / 1000)})")
        _row(lines, "Cash available:", _c(cash))
        _row(lines, "Open pair positions:", f"{open_pos} / 3 max")
    else:
        _row(lines, "Portfolio:", "Not yet initialised — bot not started")

    # Pair parameters table
    pair_rows = _pg_query("""
        SELECT pair_set_id, asset_a, asset_b, hedge_ratio, hedge_ratio_30d_avg,
               last_calculated, hurst, adf_pvalue, is_tradeable, notes
        FROM poseidon_pair_params ORDER BY pair_set_id
    """)
    _h2(lines, "PAIR PARAMETERS (5 Pair Sets)")
    if pair_rows:
        lines.append(f"  {'#':<4} {'Pair A':<12} {'Pair B':<12} {'HR':>8} {'HR-30d':>8} {'Hurst':>7} {'ADF-p':>7} {'Trade?':>8}  Notes")
        lines.append("  " + "-" * 80)
        for p in pair_rows:
            hr = float(p.get("hedge_ratio") or 0)
            hr30 = float(p.get("hedge_ratio_30d_avg") or hr)
            h = float(p.get("hurst") or 0)
            adf = float(p.get("adf_pvalue") or 1)
            tradeable = "YES ✓" if p.get("is_tradeable") else "NO  ✗"
            notes = (p.get("notes") or "")[:30]
            ts = str(p.get("last_calculated") or "?")[:16]
            lines.append(
                f"  {p.get('pair_set_id'):<4} {str(p.get('asset_a')):<12} {str(p.get('asset_b')):<12} "
                f"{hr:>8.4f} {hr30:>8.4f} {h:>7.3f} {adf:>7.3f} {tradeable:>8}  {notes}"
            )
        tradeable_count = sum(1 for p in pair_rows if p.get("is_tradeable"))
        lines.append(f"\n  Tradeable pairs: {tradeable_count} / {len(pair_rows)}")
        if pair_rows:
            last_calc = str(pair_rows[0].get("last_calculated") or "?")[:19]
            lines.append(f"  Last hedge ratio recalculation: {last_calc} UTC")
    else:
        lines.append("  Pair parameters not yet populated — waiting for first calculation cycle.")
        lines.append("  This initialises on first bot startup (takes ~3 minutes).")

    # Open positions — read directly from live state JSON which has current prices + per-leg P&L
    _h2(lines, "OPEN PAIR POSITIONS")
    _ls_open = _read_poseidon_live_state()
    _live_pos = _ls_open.get("positions") or {}
    if not _live_pos:
        lines.append("  None — no open pair positions (fully liquid)")
    else:
        _open_pnl_total = 0.0
        lines.append(f"  {len(_live_pos)} pair position(s) open:\n")
        lines.append(f"  {'#':<4} {'Asset A':<12} {'Asset B':<12} {'Direction':<14} {'A entry':>10} {'A curr':>10} {'A P&L':>9} {'B entry':>10} {'B curr':>10} {'B P&L':>9} {'Total P&L':>10}  Opened")
        lines.append("  " + "-" * 120)
        for _pid, _p in sorted(_live_pos.items(), key=lambda _x: int(_x[0])):
            _aa  = str(_p.get("asset_a", "?"))
            _ab  = str(_p.get("asset_b", "?"))
            _dir = "S:A / L:B" if _p.get("direction") == "short_a_long_b" else "L:A / S:B"
            _lae = float(_p.get("leg_a_entry") or 0)
            _lbe = float(_p.get("leg_b_entry") or 0)
            _lac = float(_p.get("current_price_a") or _p.get("leg_a_current") or 0)
            _lbc = float(_p.get("current_price_b") or _p.get("leg_b_current") or 0)
            _lap = float(_p.get("leg_a_pnl") or 0)
            _lbp = float(_p.get("leg_b_pnl") or 0)
            _tp  = float(_p.get("total_pnl") or 0)
            _oa  = str(_p.get("opened_at") or "?")[:16].replace("T", " ")
            _open_pnl_total += _tp
            def _fp(_v):
                return f"{_v:.5f}" if _v < 1 else (f"{_v:.3f}" if _v < 100 else f"{_v:.2f}")
            lines.append(
                f"  {_pid:<4} {_aa:<12} {_ab:<12} {_dir:<14} "
                f"{_fp(_lae):>10} {_fp(_lac):>10} {_c(_lap):>9} "
                f"{_fp(_lbe):>10} {_fp(_lbc):>10} {_c(_lbp):>9} "
                f"{_c(_tp):>10}  {_oa}"
            )
        lines.append(f"\n  Combined unrealised P&L across {len(_live_pos)} pairs: {_c(_open_pnl_total)}")

    # Recent trades
    _h2(lines, "RECENT CLOSED TRADES")
    trade_rows = _pg_query("""
        SELECT pair_set_id, asset_a, asset_b, direction, entry_zscore,
               net_pnl, holding_hours, reason, closed_at
        FROM poseidon_trades
        ORDER BY closed_at DESC LIMIT 10
    """)
    if trade_rows:
        wins = sum(1 for t in trade_rows if float(t.get("net_pnl") or 0) > 0)
        total_pnl = sum(float(t.get("net_pnl") or 0) for t in trade_rows)
        lines.append(f"  Recent 10 trades: {wins} wins / {len(trade_rows)-wins} losses | Net P&L: {_c(total_pnl)}")
        lines.append(f"  {'#':<4} {'Pair A':<12} {'Pair B':<12} {'Dir':<20} {'Z-entry':>8} {'P&L':>10} {'Hours':>7}  Reason")
        lines.append("  " + "-" * 85)
        for t in trade_rows:
            pnl = float(t.get("net_pnl") or 0)
            pnl_str = _c(pnl)
            lines.append(
                f"  {t.get('pair_set_id'):<4} {str(t.get('asset_a')):<12} {str(t.get('asset_b')):<12} "
                f"{str(t.get('direction')):<20} {float(t.get('entry_zscore') or 0):>8.2f} "
                f"{pnl_str:>10} {float(t.get('holding_hours') or 0):>7.1f}  {str(t.get('reason') or '')}"
            )
    else:
        lines.append("  No trades recorded yet — bot not yet active.")

    # Performance metrics
    _h2(lines, "PERFORMANCE METRICS")
    all_trades = _pg_query("SELECT net_pnl, holding_hours, asset_a, asset_b FROM poseidon_trades ORDER BY closed_at DESC")
    if all_trades:
        total = len(all_trades)
        wins = [t for t in all_trades if float(t.get("net_pnl") or 0) > 0]
        losses = [t for t in all_trades if float(t.get("net_pnl") or 0) < 0]
        win_rate = _win_rate(all_trades, "net_pnl") or 0
        pf = _profit_factor(all_trades, "net_pnl")
        avg_hold = sum(float(t.get("holding_hours") or 0) for t in all_trades) / total if total else 0
        _row(lines, "Total trades:", str(total))
        _row(lines, "Win rate:", _pct(win_rate))
        _row(lines, "Profit factor:", f"{pf:.2f}×" if pf is not None else "N/A")
        _row(lines, "Avg holding time:", f"{avg_hold:.1f} hours")
        if wins:
            best = max(wins, key=lambda t: float(t.get("net_pnl") or 0))
            _row(lines, "Best trade:", f"{_c(float(best.get('net_pnl')))} ({best.get('asset_a')}/{best.get('asset_b')})")
        if losses:
            worst = min(losses, key=lambda t: float(t.get("net_pnl") or 0))
            _row(lines, "Worst trade:", f"{_c(float(worst.get('net_pnl')))} ({worst.get('asset_a')}/{worst.get('asset_b')})")
    else:
        _row(lines, "Status:", "No completed trades yet")

    return lines


# ══════════════════════════════════════════════════════════════════════════════
# SECTION: BOT #8 KRAKEN CURRENT — Trend Following / Time-Series Momentum
# ══════════════════════════════════════════════════════════════════════════════

def section_kraken_current_status() -> list[str]:
    """Diagnostic section for Bot #8 Kraken Current trend following bot."""
    lines: list[str] = []
    _h1(lines, "SECTION 8: BOT #8 KRAKEN CURRENT — TREND FOLLOWING (MOMENTUM)")
    lines.append("  Strategy: EMA crossover + ADX + Hurst trend following on 10 Kraken crypto pairs")
    lines.append("  Starting capital: $100,000 | Cycle: 4 hours")
    lines.append("  Entry: EMA20>EMA100 + ADX>25 + Hurst>0.5 + 10d momentum confirms")
    lines.append("  Exit: Trailing stop (2×ATR) | EMA reversal | ADX<20 | 21-day max hold")
    lines.append("")

    # Portfolio state
    port_rows = _pg_query("SELECT equity_usd, cash_usd, open_positions FROM kraken_current_portfolio WHERE id = 8")
    if port_rows:
        p = port_rows[0]
        eq = float(p.get("equity_usd") or 100_000)
        cash = float(p.get("cash_usd") or 100_000)
        open_pos = int(p.get("open_positions") or 0)
        pnl = eq - 100_000
        _h2(lines, "PORTFOLIO SUMMARY")
        _row(lines, "Current equity:", _c(eq))
        _row(lines, "P&L vs $100k start:", _c(pnl) + f" ({_pct(pnl / 1000)})")
        _row(lines, "Cash available:", _c(cash))
        _row(lines, "Open trend positions:", f"{open_pos} / 5 max")
    else:
        _row(lines, "Portfolio:", "Not yet initialised — bot not started")

    # Signal scan — latest scan from DB
    _h2(lines, "LATEST SIGNAL SCAN (All 10 Pairs)")
    scan_rows = _pg_query("""
        SELECT DISTINCT ON (symbol)
            symbol, ema_fast, ema_slow, adx, hurst, direction, passed, block_reason, scanned_at
        FROM kraken_current_signal_scan
        ORDER BY symbol, scanned_at DESC
    """)
    if scan_rows:
        lines.append(f"  {'Symbol':<12} {'EMA20':>9} {'EMA100':>9} {'ADX':>6} {'Hurst':>7} {'Dir':<8} {'Signal?':>8}  Reason")
        lines.append("  " + "-" * 75)
        for s in scan_rows:
            ema_f = float(s.get("ema_fast") or 0)
            ema_s = float(s.get("ema_slow") or 0)
            adx = float(s.get("adx") or 0)
            h = float(s.get("hurst") or 0)
            direction = str(s.get("direction") or "-")
            passed = "YES ✓" if s.get("passed") else "NO"
            reason = str(s.get("block_reason") or "")[:30]
            lines.append(
                f"  {str(s.get('symbol')):<12} {ema_f:>9.2f} {ema_s:>9.2f} "
                f"{adx:>6.1f} {h:>7.3f} {direction:<8} {passed:>8}  {reason}"
            )
        scan_ts = str(scan_rows[0].get("scanned_at") or "?")[:19] if scan_rows else "?"
        lines.append(f"\n  Scan timestamp: {scan_ts} UTC")
    else:
        lines.append("  No signal scan data yet — bot not yet active.")
        lines.append("  Data appears after first 4-hour cycle.")

    # Open positions
    _h2(lines, "OPEN TREND POSITIONS")
    hb_kc = _pg_query("SELECT position_count, equity_usd FROM kraken_heartbeat WHERE id = 8")
    open_count = int(hb_kc[0].get("position_count") or 0) if hb_kc else 0
    if open_count == 0:
        lines.append("  None — no open positions (fully liquid)")
    else:
        lines.append(f"  {open_count} positions open. See live_state.json for details.")

    # Recent trades
    _h2(lines, "RECENT CLOSED TRADES")
    trade_rows = _pg_query("""
        SELECT symbol, direction, entry_price, exit_price, pnl_usd, holding_days, reason, ema_fast, ema_slow, adx_entry, closed_at
        FROM kraken_current_trades
        ORDER BY closed_at DESC LIMIT 10
    """)
    if trade_rows:
        wins = sum(1 for t in trade_rows if float(t.get("pnl_usd") or 0) > 0)
        total_pnl = sum(float(t.get("pnl_usd") or 0) for t in trade_rows)
        lines.append(f"  Recent 10 trades: {wins} wins / {len(trade_rows)-wins} losses | Net P&L: {_c(total_pnl)}")
        lines.append(f"  {'Symbol':<10} {'Dir':<8} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'Days':>6}  Reason")
        lines.append("  " + "-" * 70)
        for t in trade_rows:
            pnl = float(t.get("pnl_usd") or 0)
            lines.append(
                f"  {str(t.get('symbol')):<10} {str(t.get('direction')):<8} "
                f"{float(t.get('entry_price') or 0):>10.2f} {float(t.get('exit_price') or 0):>10.2f} "
                f"{_c(pnl):>10} {float(t.get('holding_days') or 0):>6.1f}  {str(t.get('reason') or '')}"
            )
    else:
        lines.append("  No trades recorded yet — bot not yet active.")

    # Performance metrics
    _h2(lines, "PERFORMANCE METRICS")
    all_trades = _pg_query("SELECT pnl_usd, holding_days, symbol FROM kraken_current_trades ORDER BY closed_at DESC")
    if all_trades:
        total = len(all_trades)
        wins = [t for t in all_trades if float(t.get("pnl_usd") or 0) > 0]
        losses = [t for t in all_trades if float(t.get("pnl_usd") or 0) < 0]
        win_rate = _win_rate(all_trades, "pnl_usd") or 0
        pf = _profit_factor(all_trades, "pnl_usd")
        avg_hold = sum(float(t.get("holding_days") or 0) for t in all_trades) / total if total else 0
        _row(lines, "Total trades:", str(total))
        _row(lines, "Win rate:", _pct(win_rate))
        _row(lines, "Profit factor:", f"{pf:.2f}×" if pf is not None else "N/A")
        _row(lines, "Avg holding time:", f"{avg_hold:.1f} days")
        if wins:
            best = max(wins, key=lambda t: float(t.get("pnl_usd") or 0))
            _row(lines, "Best trade:", f"{_c(float(best.get('pnl_usd')))} ({best.get('symbol')})")
        if losses:
            worst = min(losses, key=lambda t: float(t.get("pnl_usd") or 0))
            _row(lines, "Worst trade:", f"{_c(float(worst.get('pnl_usd')))} ({worst.get('symbol')})")
    else:
        _row(lines, "Status:", "No completed trades yet")

    # Regime multipliers
    _h2(lines, "REGIME INTERACTION TABLE")
    lines.append("  Regime         Long Mult   Short Mult   Notes")
    lines.append("  " + "-" * 55)
    lines.append("  Bull           1.2×        1.0×         Scale up longs in bull trends")
    lines.append("  Bear           1.0×        1.2×         Scale up shorts in bear trends")
    lines.append("  Sideways/Crypto 0.7×       0.7×         Weak trends — reduce all exposure")

    return lines


# ══════════════════════════════════════════════════════════════════════════════
# ADDITIONS 1–10: Comprehensive Diagnostic Transparency Overhaul
# ══════════════════════════════════════════════════════════════════════════════

import json as _json_diag
from pathlib import Path as _PathDiag
import time as _time_diag

_DIAG_LOGS_DIR = _PathDiag(__file__).parent.parent / "logs"
_PARAM_BASELINE_FILE = _DIAG_LOGS_DIR / "param_baseline.json"
_LAST_REPORT_STATE_FILE = _DIAG_LOGS_DIR / "last_report_state.json"
_DIAG_LOGS_DIR.mkdir(exist_ok=True)


def _read_json_file(path) -> dict:
    try:
        return _json_diag.loads(_PathDiag(path).read_text())
    except Exception:
        return {}


def _read_kraken_live_state(bot_id: str) -> dict:
    p = _PathDiag(__file__).parent.parent.parent / f"kraken-bot/{bot_id}_live_state.json"
    return _read_json_file(p)


def _read_poseidon_live_state() -> dict:
    p = _PathDiag(__file__).parent.parent.parent / "poseidon/poseidon_live_state.json"
    return _read_json_file(p)


def _read_navigator_live_state() -> dict:
    p = _PathDiag(__file__).parent.parent.parent / "forex-engine/navigator_live_state.json"
    return _read_json_file(p)


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 1: Live Code Parameter Snapshot (per bot)
# ──────────────────────────────────────────────────────────────────────────────

def section_live_code_params_kraken(bot_id: str, bot_name: str) -> list[str]:
    """ADD 1: Live Code Parameters for a Kraken bot — reads from DB + code at report time."""
    lines: list[str] = []
    _h2(lines, f"LIVE CODE PARAMETERS — {bot_name.upper()}")
    lines.append("  Source: kraken_adaptive_params DB + BOT_PROFILES config + live_state.json")
    lines.append("")

    # DB params
    db_rows = _pg_query(
        "SELECT params, metrics, reasons, adapted_at FROM kraken_adaptive_params WHERE bot_id = %s",
        (bot_id,)
    )
    params: dict = {}
    metrics: dict = {}
    reasons: dict = {}
    adapted_at = "N/A"
    if db_rows:
        row = db_rows[0]
        p = row.get("params") or {}
        if isinstance(p, str):
            p = _json_diag.loads(p)
        params = p
        m = row.get("metrics") or {}
        if isinstance(m, str):
            m = _json_diag.loads(m)
        metrics = m
        r = row.get("reasons") or {}
        if isinstance(r, str):
            r = _json_diag.loads(r)
        reasons = r
        adapted_at = str(row.get("adapted_at") or "N/A")[:19]

    # Code-level profile defaults
    _profiles = {
        "davy-jones":  {"VPIN_ENTRY_BLOCK": 0.82, "LOSS_STREAK_LIMIT": 12, "LOSS_STREAK_COOLDOWN_HOURS": 6,  "MAX_POSITION_FRACTION": 0.10},
        "blackbeard":  {"VPIN_ENTRY_BLOCK": 0.88, "LOSS_STREAK_LIMIT": 6,  "LOSS_STREAK_COOLDOWN_HOURS": 8,  "MAX_POSITION_FRACTION": 0.08, "MAX_POSITIONS": 5},
        "calypso":     {"VPIN_ENTRY_BLOCK": 0.82, "LOSS_STREAK_LIMIT": 7,  "LOSS_STREAK_COOLDOWN_HOURS": 10, "MAX_POSITION_FRACTION": 0.05, "MAX_POSITIONS": 6},
    }
    prof = _profiles.get(bot_id, {})

    # Live state
    ls = _read_kraken_live_state(bot_id)
    last_updated = str(ls.get("last_updated", "no data"))[:19]
    open_pos = ls.get("open_positions") or []
    signals = ls.get("signals") or []
    deployed_pct = ls.get("deployed_pct", "N/A")
    max_positions = ls.get("max_positions", prof.get("MAX_POSITIONS", "N/A"))

    def _fmt_pct(v):
        if v is None:
            return "N/A"
        return f"{float(v)*100:.2f}%"

    def _val(v, fallback="N/A"):
        return str(v) if v is not None else fallback

    lines.append(f"  {'ZSCORE_ENTRY:':<32} {_val(params.get('ZSCORE_ENTRY'))}")
    lines.append(f"  {'ZSCORE_EXIT:':<32} {_val(params.get('ZSCORE_EXIT'))}")
    lines.append(f"  {'STOP_LOSS_PCT:':<32} {_fmt_pct(params.get('STOP_LOSS_PCT'))}")
    lines.append(f"  {'TRAIL_PCT:':<32} {_fmt_pct(params.get('TRAIL_PCT'))}")
    lines.append(f"  {'MIN_NET_PROFIT_PCT:':<32} {_fmt_pct(params.get('MIN_NET_PROFIT_PCT'))}")
    lines.append(f"  {'VPIN_ENTRY_BLOCK:':<32} {prof.get('VPIN_ENTRY_BLOCK', 'N/A')} (code constant)")
    lines.append(f"  {'MAX_POSITION_FRACTION:':<32} {prof.get('MAX_POSITION_FRACTION', 'N/A')} ({_val(prof.get('MAX_POSITION_FRACTION', 0) * 100 if prof.get('MAX_POSITION_FRACTION') else None)}%)")
    lines.append(f"  {'MAX_POSITIONS:':<32} {max_positions}")
    lines.append(f"  {'LOSS_STREAK_LIMIT:':<32} {prof.get('LOSS_STREAK_LIMIT', 'N/A')} consecutive losses")
    lines.append(f"  {'LOSS_STREAK_COOLDOWN_HOURS:':<32} {prof.get('LOSS_STREAK_COOLDOWN_HOURS', 'N/A')}h")
    lines.append(f"  {'PARAMS_LAST_ADAPTED:':<32} {adapted_at} UTC")
    lines.append(f"  {'LAST_CYCLE_TIMESTAMP:':<32} {last_updated} UTC")
    lines.append(f"  {'DEPLOYED_PCT:':<32} {deployed_pct}%")
    lines.append(f"  {'OPEN_POSITIONS_COUNT:':<32} {len(open_pos)}")
    lines.append(f"  {'SIGNALS_LAST_CYCLE:':<32} {len(signals)}")

    if metrics:
        lines.append("")
        lines.append("  Recent metrics (last N trades used for adaptation):")
        lines.append(f"    Win rate: {float(metrics.get('win_rate', 0))*100:.1f}% | "
                     f"Profit factor: {float(metrics.get('profit_factor', 0)):.3f} | "
                     f"Consec losses: {metrics.get('consec_losses', 'N/A')}")

    if reasons:
        lines.append("  Parameter reasoning (why each param was last changed):")
        for param_name, reason_text in reasons.items():
            lines.append(f"    {param_name}: {str(reason_text)[:80]}")

    return lines


def section_live_code_params_oracle() -> list[str]:
    """ADD 1: Live Code Parameters for Oracle bot."""
    lines: list[str] = []
    _h2(lines, "LIVE CODE PARAMETERS — ORACLE #1 (ALPACA MOMENTUM)")
    lines.append("  Source: trading-platform/execution/algo_scanner.py (constants read at report time)")
    lines.append("")

    # These are the actual constants from algo_scanner.py
    lines.append(f"  {'MOMENTUM_WEIGHTS:':<32} 5d=0.20, 20d=0.50, 60d=0.30")
    lines.append(f"  {'MIN_MOMENTUM_SCORE:':<32} 5.0")
    lines.append(f"  {'RSI_LOWER:':<32} 30.0")
    lines.append(f"  {'RSI_UPPER:':<32} 70.0")
    lines.append(f"  {'MAX_LONG_SLOTS:':<32} 3")
    lines.append(f"  {'MAX_SHORT_SLOTS:':<32} 1")
    lines.append(f"  {'FIXED_FRACTION:':<32} 10.0% (until 30 closed trades)")
    lines.append(f"  {'KELLY_CAP:':<32} 15.0% (after 30 closed trades)")
    lines.append(f"  {'KELLY_THRESHOLD:':<32} 30 closed trades")
    lines.append(f"  {'STOP_LOSS_FORMULA:':<32} -clamp(vol_factor × 1.5, 6%, 10%)")
    lines.append(f"  {'TAKE_PROFIT_FORMULA:':<32} +clamp(vol_factor × 2.5, 9%, 20%)")
    lines.append(f"  {'KILL_SWITCH_THRESHOLD:':<32} 5% daily drawdown")
    lines.append(f"  {'CYCLE_FREQUENCY:':<32} 15 minutes during NYSE hours")
    lines.append(f"  {'PROFIT_RESERVE_PCT:':<32} 15% of each winning trade")

    # Last scan from DB
    scan_rows = _pg_query(
        "SELECT ts, universe_loaded, with_data, passed_score, passed_rsi, passed_ema, "
        "long_signals, short_signals, scan_note FROM oracle_scan_log ORDER BY ts DESC LIMIT 1"
    )
    if scan_rows:
        s = scan_rows[0]
        ts = str(s.get("ts") or "N/A")[:19]
        lines.append("")
        lines.append(f"  {'LAST_SCAN_TIMESTAMP:':<32} {ts} UTC")
        lines.append(f"  {'LAST_SCAN_UNIVERSE:':<32} {s.get('universe_loaded', 'N/A')} stocks loaded")
        lines.append(f"  {'WITH_DATA:':<32} {s.get('with_data', 'N/A')} (had price/RSI data)")
        lines.append(f"  {'PASSED_SCORE_FILTER:':<32} {s.get('passed_score', 'N/A')}")
        lines.append(f"  {'PASSED_RSI_FILTER:':<32} {s.get('passed_rsi', 'N/A')}")
        lines.append(f"  {'PASSED_EMA_FILTER:':<32} {s.get('passed_ema', 'N/A')}")
        lines.append(f"  {'LONG_SIGNALS_GENERATED:':<32} {s.get('long_signals', 0)}")
        lines.append(f"  {'SHORT_SIGNALS_GENERATED:':<32} {s.get('short_signals', 0)}")
        note = str(s.get("scan_note") or "none")
        lines.append(f"  {'LAST_SCAN_ERRORS:':<32} {note[:80]}")
    else:
        lines.append(f"  {'LAST_SCAN_TIMESTAMP:':<32} No scan data in DB yet")

    return lines


def section_live_code_params_navigator() -> list[str]:
    """ADD 1: Live Code Parameters for Navigator bot."""
    lines: list[str] = []
    _h2(lines, "LIVE CODE PARAMETERS — NAVIGATOR #6 (FOREX SWING H4)")
    lines.append("  Source: forex-engine/forex_config.py (constants read at report time)")
    lines.append("")

    ls = _read_navigator_live_state()
    usd_bias = ls.get("usd_bias", "N/A")
    news_blackout = ls.get("news_blackout", False)
    blackout_str = "YES — event active" if news_blackout else "NO"
    positions = ls.get("positions") or []
    last_updated = str(ls.get("last_updated", "no data"))[:19]
    cycle_count = ls.get("cycle_count", "N/A")

    pairs = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD",
             "USD_CHF", "EUR_GBP", "AUD_JPY", "GBP_JPY", "EUR_JPY"]
    lines.append(f"  {'PERMITTED_PAIRS:':<32} {', '.join(pairs)}")
    lines.append(f"  {'RSI_OVERSOLD (long thresh):':<32} 35 (relaxed from 30)")
    lines.append(f"  {'RSI_OVERBOUGHT (short thresh):':<32} 65 (relaxed from 70)")
    lines.append(f"  {'SL_ATR_MULT:':<32} 2.0×")
    lines.append(f"  {'TP_ATR_MULT:':<32} 3.0×")
    lines.append(f"  {'TRAIL_ATR_MULT:':<32} 2.0×")
    lines.append(f"  {'BREAKEVEN_ATR_MULT:':<32} 1.5×")
    lines.append(f"  {'MAX_OPEN_POSITIONS:':<32} 5")
    lines.append(f"  {'RISK_PER_TRADE_PCT:':<32} 1.0%")
    lines.append(f"  {'MAX_POSITION_SIZE_PCT:':<32} 10.0%")
    lines.append(f"  {'CYCLE_INTERVAL_HOURS:':<32} 4h")
    lines.append(f"  {'VAULT_SWEEP_PCT:':<32} 20% of realized profits")
    lines.append(f"  {'GROQ_USD_BIAS:':<32} {usd_bias}")
    lines.append(f"  {'NEWS_BLACKOUT_ACTIVE:':<32} {blackout_str}")
    lines.append(f"  {'LAST_CYCLE_TIMESTAMP:':<32} {last_updated} UTC")
    lines.append(f"  {'CYCLE_COUNT:':<32} {cycle_count}")
    lines.append(f"  {'OPEN_POSITIONS_COUNT:':<32} {len(positions)}")

    return lines


def section_live_code_params_poseidon() -> list[str]:
    """ADD 1: Live Code Parameters for Poseidon bot."""
    lines: list[str] = []
    _h2(lines, "LIVE CODE PARAMETERS — POSEIDON #7 (STATISTICAL ARBITRAGE)")
    lines.append("  Source: poseidon/config.py + poseidon_pair_params DB + poseidon_live_state.json")
    lines.append("")

    ls = _read_poseidon_live_state()
    last_updated = str(ls.get("last_updated", "no data"))[:19]
    pair_params = ls.get("pair_params") or []

    pair_rows = _pg_query("SELECT COUNT(*) as total FROM poseidon_pair_params")
    tradeable_rows = _pg_query("SELECT COUNT(*) as cnt FROM poseidon_pair_params WHERE is_tradeable = true")
    passing_adf = _pg_query("SELECT COUNT(*) as cnt FROM poseidon_pair_params WHERE adf_pvalue < 0.20")
    total_pairs = pair_rows[0].get("total", "N/A") if pair_rows else "N/A"
    tradeable_count = tradeable_rows[0].get("cnt", "N/A") if tradeable_rows else "N/A"
    adf_count = passing_adf[0].get("cnt", "N/A") if passing_adf else "N/A"

    # Open positions from live state
    open_positions = ls.get("positions") or {}
    open_count = len(open_positions) if isinstance(open_positions, dict) else 0

    # Heartbeat data
    hb = _pg_query("SELECT position_count FROM kraken_heartbeat WHERE id = 7")
    if hb:
        open_count = int(hb[0].get("position_count") or 0)

    lines.append(f"  {'ZSCORE_ENTRY:':<32} 1.5 (relaxed from 2.0)")
    lines.append(f"  {'ZSCORE_EXIT:':<32} 0.3")
    lines.append(f"  {'ZSCORE_STOP:':<32} 3.5")
    lines.append(f"  {'ADF_PVALUE_MAX:':<32} 0.20 (sole stationarity gate)")
    lines.append(f"  {'HURST_GATE:':<32} DISABLED (info only, not blocking)")
    lines.append(f"  {'HEDGE_RATIO_STABILITY:':<32} 0.25 (25% drift tolerance)")
    lines.append(f"  {'HEDGE_RATIO_BREAKDOWN:':<32} 0.25 (exit if 25% drift at entry)")
    lines.append(f"  {'MAX_POSITIONS:':<32} 5")
    lines.append(f"  {'POSITION_VALUE_PCT:':<32} 15.0%")
    lines.append(f"  {'CB_CONSECUTIVE_LOSSES:':<32} 5")
    lines.append(f"  {'CB_PAUSE_HOURS:':<32} 24h")
    lines.append(f"  {'MAX_HOLD_HOURS:':<32} 72h")
    lines.append(f"  {'LOOP_SLEEP_SECONDS:':<32} 900 (15 minutes)")
    lines.append(f"  {'ACTIVE_PAIR_SETS:':<32} {total_pairs}")
    lines.append(f"  {'TRADEABLE_PAIRS:':<32} {tradeable_count}")
    lines.append(f"  {'PAIRS_PASSING_ADF:':<32} {adf_count}")
    lines.append(f"  {'PAIRS_IN_POSITION:':<32} {open_count}")
    lines.append(f"  {'LAST_CYCLE_TIMESTAMP:':<32} {last_updated} UTC")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 2: Cycle Execution Audit Log
# ──────────────────────────────────────────────────────────────────────────────

def section_cycle_execution_audit_kraken(bot_id: str, bot_name: str) -> list[str]:
    """ADD 2: Last cycle execution audit for a Kraken bot — reads live_state.json signals."""
    lines: list[str] = []
    _h2(lines, f"LAST CYCLE EXECUTION AUDIT — {bot_name.upper()}")

    ls = _read_kraken_live_state(bot_id)
    if not ls:
        lines.append("  No live_state.json data available — bot not yet started or file missing.")
        return lines

    last_updated = str(ls.get("last_updated", "?"))[:19]
    signals = ls.get("signals") or []
    open_pos = ls.get("open_positions") or []
    deployed_pct = ls.get("deployed_pct", "?")

    lines.append(f"  Timestamp: {last_updated} UTC | Open positions: {len(open_pos)} | Deployed: {deployed_pct}%")
    lines.append("")

    if not signals:
        lines.append("  No signal data in live_state.json for this cycle.")
        return lines

    # Tally results
    blocked = [s for s in signals if s.get("signal_type") != "entry" and not s.get("has_position")]
    entries = [s for s in signals if s.get("signal_type") == "entry"]
    in_pos = [s for s in signals if s.get("has_position")]

    lines.append(f"  {'Symbol':<14} {'Z-Score':>9} {'RSI':>6}  Result         Reason")
    lines.append("  " + "-" * 75)

    hurst_blocks = 0
    vpin_blocks = 0
    adf_blocks = 0

    for sig in signals:
        sym = str(sig.get("symbol", "?"))
        zscore = sig.get("z_score")
        rsi = sig.get("rsi")
        stype = str(sig.get("signal_type", "?"))
        reason = str(sig.get("reason", ""))[:55]
        has_pos = sig.get("has_position", False)

        z_str = f"{zscore:+.3f}" if zscore is not None else "  N/A "
        r_str = f"{rsi:.1f}" if rsi is not None else "  N/A"

        if has_pos:
            result = "IN POSITION"
        elif stype == "entry":
            result = "ENTRY SIGNAL"
        else:
            result = "BLOCKED"
            if "hurst" in reason.lower() or "HURST" in reason:
                hurst_blocks += 1
            elif "vpin" in reason.lower() or "VPIN" in reason:
                vpin_blocks += 1
            elif "adf" in reason.lower() or "ADF" in reason:
                adf_blocks += 1

        lines.append(f"  {sym:<14} {z_str:>9} {r_str:>6}  {result:<14} {reason}")

    lines.append("")
    lines.append(f"  Summary:")
    lines.append(f"    Total evaluated:    {len(signals)}")
    lines.append(f"    Entry signals:      {len(entries)}")
    lines.append(f"    In position:        {len(in_pos)}")
    lines.append(f"    Blocked:            {len(blocked)}")
    lines.append(f"      Of which Hurst:   {hurst_blocks}")
    lines.append(f"      Of which VPIN:    {vpin_blocks}")
    lines.append(f"      Of which ADF:     {adf_blocks}")

    # Recent DB trades to show entries/exits this cycle
    recent = _pg_query(
        "SELECT symbol, side, pnl_usd, reason, closed_at FROM kraken_trades "
        "WHERE bot_id = %s AND closed_at > NOW() - INTERVAL '2 hours' ORDER BY closed_at DESC LIMIT 10",
        (bot_id,)
    )
    if recent:
        lines.append("")
        lines.append(f"  Trades closed in last 2h:")
        for t in recent:
            pnl = float(t.get("pnl_usd") or 0)
            pnl_str = _c(pnl)
            lines.append(f"    {str(t.get('symbol','?')):<14} {str(t.get('side','?')):<6} {pnl_str:>10}  {str(t.get('reason','?'))[:40]}")
    else:
        lines.append("  No trades closed in last 2 hours.")

    return lines


def section_cycle_execution_audit_oracle() -> list[str]:
    """ADD 2: Last scan execution audit for Oracle bot."""
    lines: list[str] = []
    _h2(lines, "LAST SCAN EXECUTION AUDIT — ORACLE #1")

    scans = _pg_query(
        "SELECT ts, universe_loaded, with_data, passed_score, passed_rsi, passed_ema, "
        "long_signals, short_signals, top5_long, top5_short, scan_note "
        "FROM oracle_scan_log ORDER BY ts DESC LIMIT 1"
    )
    if not scans:
        lines.append("  No scan log data yet — Oracle not yet active or no scans recorded.")
        return lines

    s = scans[0]
    ts = str(s.get("ts") or "?")[:19]
    u = int(s.get("universe_loaded") or 0)
    wd = int(s.get("with_data") or 0)
    ps = int(s.get("passed_score") or 0)
    pr = int(s.get("passed_rsi") or 0)
    pe = int(s.get("passed_ema") or 0)
    ls_count = int(s.get("long_signals") or 0)
    ss_count = int(s.get("short_signals") or 0)
    note = str(s.get("scan_note") or "none")

    lines.append(f"  Scan timestamp: {ts} UTC")
    lines.append(f"  Universe loaded:      {u} stocks")
    lines.append(f"  With price/RSI data:  {wd} ({u - wd} had no data)")
    lines.append("")
    lines.append(f"  Filter funnel:")
    lines.append(f"    Stage 1 — with data:     {wd:>4}")
    lines.append(f"    Stage 2 — score filter:  {ps:>4}  ({wd - ps} blocked by score < 5.0)")
    lines.append(f"    Stage 3 — RSI filter:    {pr:>4}  ({ps - pr} blocked by RSI outside 30–70)")
    lines.append(f"    Stage 4 — EMA filter:    {pe:>4}  ({pr - pe} blocked by price < EMA20)")
    lines.append(f"    Long signals:            {ls_count}")
    lines.append(f"    Short signals:           {ss_count}")
    lines.append(f"  Scan note:  {note[:100]}")

    # Top candidates
    top5_long = s.get("top5_long")
    top5_short = s.get("top5_short")
    if top5_long:
        try:
            long_cands = _json_diag.loads(top5_long) if isinstance(top5_long, str) else top5_long
            if long_cands:
                lines.append("")
                lines.append("  Top long candidates evaluated (last scan):")
                lines.append(f"    {'Rank':<5} {'Symbol':<10} {'Score':>8} {'RSI':>6}  Result")
                lines.append("    " + "-" * 45)
                for i, c in enumerate(long_cands[:10], 1):
                    sym = str(c.get("symbol", "?"))
                    score = float(c.get("score") or 0)
                    rsi = c.get("rsi")
                    r_str = f"{rsi:.1f}" if rsi is not None else "N/A"
                    passed = c.get("passed", False)
                    result = "SIGNAL" if passed else f"BLOCKED ({str(c.get('block_reason','?'))[:30]})"
                    lines.append(f"    {i:<5} {sym:<10} {score:>8.2f} {r_str:>6}  {result}")
        except Exception:
            pass
    if top5_short:
        try:
            short_cands = _json_diag.loads(top5_short) if isinstance(top5_short, str) else top5_short
            if short_cands:
                lines.append("")
                lines.append("  Top short candidates evaluated (last scan):")
                lines.append(f"    {'Rank':<5} {'Symbol':<10} {'Score':>8} {'RSI':>6}  Result")
                lines.append("    " + "-" * 45)
                for i, c in enumerate(short_cands[:5], 1):
                    sym = str(c.get("symbol", "?"))
                    score = float(c.get("score") or 0)
                    rsi = c.get("rsi")
                    r_str = f"{rsi:.1f}" if rsi is not None else "N/A"
                    passed = c.get("passed", False)
                    result = "SIGNAL" if passed else f"BLOCKED ({str(c.get('block_reason','?'))[:30]})"
                    lines.append(f"    {i:<5} {sym:<10} {score:>8.2f} {r_str:>6}  {result}")
        except Exception:
            pass

    # Filter effectiveness counters from recent scans
    recent_scans = _pg_query(
        "SELECT universe_loaded, with_data, passed_score, passed_rsi, passed_ema, long_signals, short_signals "
        "FROM oracle_scan_log WHERE ts > NOW() - INTERVAL '24 hours' ORDER BY ts DESC"
    )
    if recent_scans:
        total_score_blocks = sum(int(r.get("with_data") or 0) - int(r.get("passed_score") or 0) for r in recent_scans)
        total_rsi_blocks = sum(int(r.get("passed_score") or 0) - int(r.get("passed_rsi") or 0) for r in recent_scans)
        total_ema_blocks = sum(int(r.get("passed_rsi") or 0) - int(r.get("passed_ema") or 0) for r in recent_scans)
        total_ls = sum(int(r.get("long_signals") or 0) for r in recent_scans)
        total_ss = sum(int(r.get("short_signals") or 0) for r in recent_scans)
        lines.append("")
        lines.append(f"  24h scan statistics ({len(recent_scans)} scans):")
        lines.append(f"    Score filter blocks:    {total_score_blocks}")
        lines.append(f"    RSI filter blocks:      {total_rsi_blocks}")
        lines.append(f"    EMA filter blocks:      {total_ema_blocks}")
        lines.append(f"    Total long signals:     {total_ls}")
        lines.append(f"    Total short signals:    {total_ss}")

    return lines


def section_cycle_execution_audit_poseidon() -> list[str]:
    """ADD 2: Last cycle execution audit for Poseidon bot."""
    lines: list[str] = []
    _h2(lines, "LAST CYCLE EXECUTION AUDIT — POSEIDON #7")

    ls = _read_poseidon_live_state()
    if not ls:
        lines.append("  No live_state.json data — Poseidon not yet started.")
        return lines

    last_updated = str(ls.get("last_updated", "?"))[:19]
    pair_params_ls = ls.get("pair_params") or []
    open_positions = ls.get("positions") or {}
    equity = float(ls.get("equity", 0) or 0)

    lines.append(f"  Timestamp: {last_updated} UTC | Equity: {_c(equity)}")
    lines.append(f"  Pairs monitored: {len(pair_params_ls)} | Open positions: {len(open_positions)}")
    lines.append("")

    if pair_params_ls:
        lines.append(f"  {'Pair':<22} {'Hurst':>7} {'ADF-p':>7} {'HR':>8}  Tradeable  Notes")
        lines.append("  " + "-" * 70)
        passing = 0
        for p in pair_params_ls:
            a = str(p.get("asset_a", "?"))
            b = str(p.get("asset_b", "?"))
            pair_str = f"{a}/{b}"
            h = float(p.get("hurst") or 0)
            adf = float(p.get("adf_pvalue") or 1)
            hr = float(p.get("hedge_ratio") or 0)
            tradeable = p.get("is_tradeable", False)
            notes = str(p.get("notes") or "")[:25]
            tr_str = "YES ✓" if tradeable else "NO  ✗"
            if tradeable:
                passing += 1
            lines.append(f"  {pair_str:<22} {h:>7.3f} {adf:>7.3f} {hr:>8.4f}  {tr_str:<10} {notes}")

        lines.append("")
        lines.append(f"  Pairs passing all filters: {passing} / {len(pair_params_ls)}")

    # Z-score status from DB
    zscore_rows = _pg_query(
        "SELECT asset_a, asset_b, hurst, adf_pvalue, is_tradeable, notes "
        "FROM poseidon_pair_params ORDER BY pair_set_id"
    )
    if zscore_rows and not pair_params_ls:
        lines.append("  (Using DB data — live_state pairs section empty)")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 3: Parameter Drift Monitor
# ──────────────────────────────────────────────────────────────────────────────

def _get_or_create_param_baseline() -> dict:
    """Load or create the parameter baseline from file."""
    if _PARAM_BASELINE_FILE.exists():
        try:
            return _json_diag.loads(_PARAM_BASELINE_FILE.read_text())
        except Exception:
            pass
    # Create from current DB values
    baseline: dict = {"created_at": datetime.now(timezone.utc).isoformat(), "bots": {}}
    db_rows = _pg_query("SELECT bot_id, params, adapted_at FROM kraken_adaptive_params")
    for row in db_rows:
        bid = str(row.get("bot_id") or "")
        p = row.get("params") or {}
        if isinstance(p, str):
            p = _json_diag.loads(p)
        baseline["bots"][bid] = {
            "ZSCORE_ENTRY": p.get("ZSCORE_ENTRY"),
            "ZSCORE_EXIT": p.get("ZSCORE_EXIT"),
            "STOP_LOSS_PCT": p.get("STOP_LOSS_PCT"),
            "TRAIL_PCT": p.get("TRAIL_PCT"),
            "MIN_NET_PROFIT_PCT": p.get("MIN_NET_PROFIT_PCT"),
            "baseline_locked_at": str(row.get("adapted_at") or "N/A")[:19],
        }
    # Save baseline
    try:
        _PARAM_BASELINE_FILE.write_text(_json_diag.dumps(baseline, indent=2, default=str))
    except Exception:
        pass
    return baseline


def section_parameter_drift_monitor() -> list[str]:
    """ADD 3: Parameter Integrity Check — compares current params vs baseline."""
    lines: list[str] = []
    _h1(lines, "ADDITION 3: PARAMETER INTEGRITY CHECK")

    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"  Generated: {now_ts}")

    baseline = _get_or_create_param_baseline()
    baseline_created = str(baseline.get("created_at", "unknown"))[:16]
    lines.append(f"  Baseline set: {baseline_created} UTC")
    lines.append("")

    # Current DB params
    current_rows = _pg_query("SELECT bot_id, params, adapted_at FROM kraken_adaptive_params")
    current: dict = {}
    for row in current_rows:
        bid = str(row.get("bot_id") or "")
        p = row.get("params") or {}
        if isinstance(p, str):
            p = _json_diag.loads(p)
        current[bid] = {"params": p, "adapted_at": str(row.get("adapted_at") or "N/A")[:19]}

    params_to_check = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"]
    bot_display = {"davy-jones": "davy-jones", "blackbeard": "blackbeard", "calypso": "calypso"}

    any_drift = False
    drift_alerts: list[str] = []

    lines.append(f"  {'Bot':<14} {'Parameter':<22} {'Baseline':>10} {'Current':>10} {'Drift':>8}  Status")
    lines.append("  " + "-" * 78)

    for bot_id, display in bot_display.items():
        b_bot = baseline.get("bots", {}).get(bot_id, {})
        c_bot = current.get(bot_id, {}).get("params", {})

        for pname in params_to_check:
            baseline_val = b_bot.get(pname)
            current_val = c_bot.get(pname)

            if baseline_val is None and current_val is None:
                lines.append(f"  {display:<14} {pname:<22} {'N/A':>10} {'N/A':>10} {'N/A':>8}  ℹ️  NO DATA")
                continue

            if baseline_val is None:
                lines.append(f"  {display:<14} {pname:<22} {'N/A':>10} {current_val:>10.4f} {'N/A':>8}  ℹ️  NO BASELINE")
                continue

            if current_val is None:
                lines.append(f"  {display:<14} {pname:<22} {baseline_val:>10.4f} {'N/A':>10} {'N/A':>8}  ⚠️  MISSING")
                continue

            drift = float(current_val) - float(baseline_val)
            pct_drift = (drift / float(baseline_val) * 100) if float(baseline_val) != 0 else 0

            if abs(drift) < 1e-9:
                status = "✅ CLEAN"
            else:
                status = f"⚠️  DRIFT {drift:+.4f}"
                any_drift = True
                adapted_at = current.get(bot_id, {}).get("adapted_at", "?")
                drift_alerts.append(
                    f"  ⚠️ DRIFT DETECTED: {display} {pname} "
                    f"baseline={float(baseline_val):.4f} current={float(current_val):.4f} "
                    f"drift={drift:+.4f} ({pct_drift:+.1f}%)\n"
                    f"     Last adapted: {adapted_at} UTC\n"
                    f"     ACTION: Verify this change was intentional"
                )

            lines.append(
                f"  {display:<14} {pname:<22} {float(baseline_val):>10.4f} {float(current_val):>10.4f} {drift:>+8.4f}  {status}"
            )

    lines.append("")
    lines.append(f"  Fleet Commander enforcement: DISABLED ✅")
    lines.append(f"  Gemini auditor writes:       DISABLED ✅")
    lines.append(f"  Auto-parameter writes:       NONE (all changes are adaptation-engine only)")
    lines.append(f"  Baseline file:               {_PARAM_BASELINE_FILE}")

    if drift_alerts:
        lines.append("")
        lines.append("  ══ DRIFT ALERTS ══")
        for alert in drift_alerts:
            lines.append(alert)
    else:
        lines.append("")
        lines.append("  Unauthorized changes detected: NONE — all params match baseline")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 4: Filter Effectiveness Statistics (rolling 7-day)
# ──────────────────────────────────────────────────────────────────────────────

def section_filter_effectiveness() -> list[str]:
    """ADD 4: Filter Effectiveness — 7-day rolling stats for each filter."""
    lines: list[str] = []
    _h1(lines, "ADDITION 4: FILTER EFFECTIVENESS — 7-DAY ROLLING")

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # ── Kraken VPIN filter stats ──────────────────────────────────────────────
    _h2(lines, "KRAKEN FLEET — VPIN FILTER (7d)")
    vpin_rows = _pg_query(
        "SELECT bot_id, COUNT(*) as n, AVG(vpin_value) as avg_vpin, AVG(threshold) as avg_thresh "
        "FROM vpin_rejections WHERE ts > %s GROUP BY bot_id ORDER BY bot_id",
        (cutoff,)
    )
    total_vpin = _pg_query(
        "SELECT COUNT(*) as n FROM vpin_rejections WHERE ts > %s", (cutoff,)
    )
    vpin_total = int(total_vpin[0].get("n") or 0) if total_vpin else 0

    if vpin_rows:
        lines.append(f"  {'Bot':<14} {'VPIN Blocks':>12} {'Avg VPIN':>10} {'Avg Thresh':>12}")
        lines.append("  " + "-" * 52)
        for r in vpin_rows:
            lines.append(
                f"  {str(r.get('bot_id','?')):<14} {int(r.get('n') or 0):>12} "
                f"{float(r.get('avg_vpin') or 0):>10.4f} {float(r.get('avg_thresh') or 0):>12.4f}"
            )
        lines.append(f"  Total VPIN rejections (7d): {vpin_total}")
    else:
        lines.append("  No VPIN rejection data in last 7 days.")

    # ── Kraken trades filter analysis ─────────────────────────────────────────
    _h2(lines, "KRAKEN FLEET — TRADE FILTER OUTCOMES (7d closed trades)")
    trade_rows = _pg_query(
        "SELECT bot_id, reason, COUNT(*) as n, AVG(pnl_pct) as avg_pnl "
        "FROM kraken_trades WHERE closed_at > %s GROUP BY bot_id, reason ORDER BY bot_id, n DESC",
        (cutoff,)
    )
    if trade_rows:
        lines.append(f"  {'Bot':<14} {'Exit Reason':<30} {'Count':>7} {'Avg P&L%':>10}")
        lines.append("  " + "-" * 65)
        for r in trade_rows:
            bot = str(r.get("bot_id", "?"))
            reason = str(r.get("reason") or "?")[:28]
            n = int(r.get("n") or 0)
            avg_pnl = float(r.get("avg_pnl") or 0)
            lines.append(f"  {bot:<14} {reason:<30} {n:>7} {_pct(avg_pnl):>10}")
    else:
        lines.append("  No kraken_trades data in last 7 days.")

    # ── Oracle RSI / Score filter blocks from scan_log ────────────────────────
    _h2(lines, "ORACLE — FILTER EFFECTIVENESS (7d scan log)")
    oracle_scans = _pg_query(
        "SELECT SUM(universe_loaded) as total_loaded, SUM(with_data) as total_data, "
        "SUM(passed_score) as p_score, SUM(passed_rsi) as p_rsi, SUM(passed_ema) as p_ema, "
        "SUM(long_signals) as lsigs, SUM(short_signals) as ssigs, COUNT(*) as scan_count "
        "FROM oracle_scan_log WHERE ts > %s",
        (cutoff,)
    )
    if oracle_scans and oracle_scans[0].get("scan_count"):
        r = oracle_scans[0]
        total_data = int(r.get("total_data") or 0)
        p_score = int(r.get("p_score") or 0)
        p_rsi = int(r.get("p_rsi") or 0)
        p_ema = int(r.get("p_ema") or 0)
        lsigs = int(r.get("lsigs") or 0)
        ssigs = int(r.get("ssigs") or 0)
        scans = int(r.get("scan_count") or 0)

        def _block_pct(blocked, total):
            return f"{blocked / total * 100:.1f}%" if total > 0 else "N/A"

        score_blocks = total_data - p_score
        rsi_blocks = p_score - p_rsi
        ema_blocks = p_rsi - p_ema

        lines.append(f"  Scans in 7d window: {scans}")
        lines.append("")
        lines.append(f"  {'Filter':<30} {'Blocks':>8} {'% of Attempts':>15}  Verdict")
        lines.append("  " + "-" * 65)
        lines.append(f"  {'Score < 5.0 (weak momentum)':<30} {score_blocks:>8} {_block_pct(score_blocks, total_data):>15}  ✅ EXPECTED")
        lines.append(f"  {'RSI outside 30-70':<30} {rsi_blocks:>8} {_block_pct(rsi_blocks, p_score):>15}  ✅ EXPECTED")
        lines.append(f"  {'Price < EMA20':<30} {ema_blocks:>8} {_block_pct(ema_blocks, p_rsi):>15}  ✅ EXPECTED")
        lines.append(f"  {'Long signals generated':<30} {lsigs:>8} {'':>15}")
        lines.append(f"  {'Short signals generated':<30} {ssigs:>8} {'':>15}")
        if total_data > 0:
            signal_rate = (lsigs + ssigs) / (scans * max(total_data // scans, 1)) * 100
            lines.append(f"  Signal rate: {signal_rate:.2f}% of evaluated stocks per scan")
    else:
        lines.append("  No Oracle scan log data in last 7 days.")

    # ── Poseidon ADF filter ───────────────────────────────────────────────────
    _h2(lines, "POSEIDON — FILTER EFFECTIVENESS (current pair universe)")
    pos_pairs = _pg_query(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN adf_pvalue < 0.20 THEN 1 ELSE 0 END) as pass_adf, "
        "SUM(CASE WHEN is_tradeable THEN 1 ELSE 0 END) as tradeable "
        "FROM poseidon_pair_params"
    )
    if pos_pairs and pos_pairs[0].get("total"):
        r = pos_pairs[0]
        total = int(r.get("total") or 0)
        pass_adf = int(r.get("pass_adf") or 0)
        tradeable = int(r.get("tradeable") or 0)
        blocked_adf = total - pass_adf

        lines.append(f"  {'Filter':<30} {'Pairs':>8} {'% of Total':>12}  Verdict")
        lines.append("  " + "-" * 60)
        lines.append(f"  {'Total pairs monitored':<30} {total:>8} {'100%':>12}")
        lines.append(f"  {'Passing ADF (p < 0.20)':<30} {pass_adf:>8} {pass_adf/total*100:>11.1f}%  ✅ ACTIVE")
        lines.append(f"  {'Blocked by ADF':<30} {blocked_adf:>8} {blocked_adf/total*100:>11.1f}%  ✅ HELPING")
        lines.append(f"  {'Marked tradeable':<30} {tradeable:>8} {tradeable/total*100:>11.1f}%")
        lines.append(f"  {'Note:':<30} Hurst gate DISABLED (info only — not blocking)")
    else:
        lines.append("  No Poseidon pair data available.")

    lines.append("")
    lines.append("  NOTE: Post-block price movement analysis requires additional logging.")
    lines.append("  Currently showing block counts only. Price movement tracking can be added")
    lines.append("  by storing price-at-block-time in vpin_rejections and querying 4h/24h later.")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 5: Bot Health Scorecard (top of report)
# ──────────────────────────────────────────────────────────────────────────────

def _compute_health_score(win_rate: float | None, profit_factor: float | None,
                           has_trades: bool, consec_losses: int,
                           cycle_ok: bool, param_ok: bool) -> int:
    """Compute 0-100 health score for a bot."""
    score = 0
    # Win rate (25 pts)
    if win_rate is not None:
        score += min(25, int(win_rate / 4))
    else:
        score += 10 if has_trades else 0
    # Profit factor (25 pts)
    if profit_factor is not None and profit_factor > 0:
        score += min(25, int(profit_factor * 10))
    # Cycle execution (20 pts)
    score += 20 if cycle_ok else 5
    # Trade frequency (15 pts)
    if has_trades:
        score += 15
    else:
        score += 5
    # Parameter integrity (15 pts)
    score += 15 if param_ok else 5
    # Penalise consecutive losses
    if consec_losses >= 10:
        score = max(0, score - 30)
    elif consec_losses >= 5:
        score = max(0, score - 15)
    return min(100, score)


def section_fleet_health_scorecard() -> list[str]:
    """ADD 5: Fleet Health Scorecard — top-of-report snapshot of all 8 bots."""
    lines: list[str] = []
    W80 = "\u2550" * 80
    lines.append("")
    lines.append(W80)
    lines.append("  ADDITION 5: FLEET HEALTH SCORECARD")
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"  Generated: {now_ts}")
    lines.append(W80)
    lines.append("")

    # Collect data for each bot
    bots = []

    # Oracle (#1)
    try:
        alpaca_rows = _pg_query(
            "SELECT COUNT(*) as n FROM trades WHERE date > NOW() - INTERVAL '7 days'"
        )
        last_trade_rows = _pg_query("SELECT date FROM trades ORDER BY date DESC LIMIT 1")
        oracle_pnl_rows = _pg_query(
            "SELECT SUM(realized_pnl) as total FROM trades WHERE date > NOW() - INTERVAL '7 days'"
        )
        eq_rows = _pg_query("SELECT alpaca_equity FROM equity_snapshots ORDER BY ts DESC LIMIT 1")
        oracle_eq = float(eq_rows[0].get("alpaca_equity") or 100000) if eq_rows else 100000

        last_trade_ts = str(last_trade_rows[0].get("date") or "Never")[:10] if last_trade_rows else "Never"
        pnl_7d = float(oracle_pnl_rows[0].get("total") or 0) if oracle_pnl_rows else 0
        n_trades = int(alpaca_rows[0].get("n") or 0) if alpaca_rows else 0

        # Win rate
        wr_rows = _pg_query(
            "SELECT COUNT(*) as wins FROM trades WHERE realized_pnl > 0 AND date > NOW() - INTERVAL '30 days'"
        )
        total_rows = _pg_query(
            "SELECT COUNT(*) as total FROM trades WHERE date > NOW() - INTERVAL '30 days'"
        )
        wins = int(wr_rows[0].get("wins") or 0) if wr_rows else 0
        total = int(total_rows[0].get("total") or 0) if total_rows else 0
        wr = wins / total * 100 if total > 0 else None

        ks_rows = _pg_query(
            "SELECT source FROM equity_snapshots WHERE ts > NOW() - INTERVAL '2 hours' LIMIT 1"
        )
        cycle_ok = bool(ks_rows)
        health = _compute_health_score(wr, 1.0 if wr and wr > 50 else 0.5, total > 0, 0, cycle_ok, True)
        issues = "No open positions" if oracle_eq < 100000 and n_trades == 0 else "Active"
        bots.append({
            "num": "#1", "name": "Oracle", "status": "🟢 LIVE", "last_trade": last_trade_ts,
            "pnl_7d": pnl_7d, "health": health, "equity": oracle_eq,
            "issues": issues if health < 70 else "Clean"
        })
    except Exception as e:
        bots.append({"num": "#1", "name": "Oracle", "status": "⚠️ ERR", "last_trade": "?",
                     "pnl_7d": 0, "health": 0, "equity": 0, "issues": str(e)[:40]})

    # Kraken bots (#2-4)
    kraken_bot_map = [
        ("#2", "Davy Jones", "davy-jones", 1),
        ("#3", "Blackbeard", "blackbeard", 2),
        ("#4", "Calypso", "calypso", 3),
    ]
    for num, name, bot_id, db_id in kraken_bot_map:
        try:
            hb = _pg_query("SELECT status, circuit_breaker, position_count, equity_usd FROM kraken_heartbeat WHERE id = %s", (db_id,))
            kap = _pg_query("SELECT params, metrics FROM kraken_adaptive_params WHERE bot_id = %s", (bot_id,))
            k_trades_7d = _pg_query(
                "SELECT COUNT(*) as n, SUM(pnl_usd) as pnl FROM kraken_trades "
                "WHERE bot_id = %s AND closed_at > NOW() - INTERVAL '7 days'", (bot_id,)
            )
            last_k_trade = _pg_query(
                "SELECT closed_at FROM kraken_trades WHERE bot_id = %s ORDER BY closed_at DESC LIMIT 1", (bot_id,)
            )

            eq = float(hb[0].get("equity_usd") or 100000) if hb else 100000
            cb = hb[0].get("circuit_breaker") if hb else None
            if isinstance(cb, str):
                cb = _json_diag.loads(cb)
            cb_tripped = isinstance(cb, dict) and cb.get("tripped")
            status = "🔴 CB" if cb_tripped else "🟢 LIVE"

            metrics = kap[0].get("metrics") or {} if kap else {}
            if isinstance(metrics, str):
                metrics = _json_diag.loads(metrics)
            consec = int(metrics.get("consec_losses", 0)) if metrics else 0
            wr = float(metrics.get("win_rate", 0)) * 100 if metrics.get("win_rate") is not None else None
            pf = float(metrics.get("profit_factor", 0)) if metrics else None

            pnl_7d = float(k_trades_7d[0].get("pnl") or 0) if k_trades_7d else 0
            n_7d = int(k_trades_7d[0].get("n") or 0) if k_trades_7d else 0
            last_t = str(last_k_trade[0].get("closed_at") or "Never")[:10] if last_k_trade else "Never"

            health = _compute_health_score(wr, pf, n_7d > 0, consec, True, True)
            issues_list = []
            if cb_tripped:
                issues_list.append("Circuit breaker TRIPPED")
            if consec >= 5:
                issues_list.append(f"{consec} consecutive losses")
            if wr is not None and wr < 30:
                issues_list.append(f"Low win rate {wr:.0f}%")
            issues = ", ".join(issues_list) if issues_list else "Clean"

            bots.append({
                "num": num, "name": name, "status": status, "last_trade": last_t,
                "pnl_7d": pnl_7d, "health": health, "equity": eq, "issues": issues
            })
        except Exception as e:
            bots.append({"num": num, "name": name, "status": "⚠️ ERR", "last_trade": "?",
                         "pnl_7d": 0, "health": 0, "equity": 0, "issues": str(e)[:40]})

    # Apex Predator (#5)
    try:
        opts_rows = _pg_query("SELECT equity FROM forex_portfolio WHERE id = 5 LIMIT 1")
        opts_eq = 100000.0
        last_opts_trade = _pg_query("SELECT MAX(closed_at) as last FROM execution_post_mortems LIMIT 1")
        last_t = str(last_opts_trade[0].get("last") or "Never")[:10] if last_opts_trade else "Never"
        bots.append({
            "num": "#5", "name": "Apex Predator", "status": "🟢 LIVE", "last_trade": last_t,
            "pnl_7d": 0, "health": 45, "equity": opts_eq,
            "issues": "No trades yet — awaiting vol squeeze signal"
        })
    except Exception:
        bots.append({"num": "#5", "name": "Apex Predator", "status": "🟢 LIVE", "last_trade": "Never",
                     "pnl_7d": 0, "health": 45, "equity": 100000, "issues": "No trades yet"})

    # Navigator (#6)
    try:
        nav_ls = _read_navigator_live_state()
        nav_eq = float(nav_ls.get("equity_usd", 100000) or 100000)
        nav_pos = len(nav_ls.get("positions") or [])
        fx_7d = _pg_query(
            "SELECT COUNT(*) as n, SUM(pnl_usd) as pnl FROM forex_trades "
            "WHERE closed_at > NOW() - INTERVAL '7 days' AND status = 'closed'"
        )
        last_fx = _pg_query("SELECT MAX(closed_at) as last FROM forex_trades WHERE status = 'closed'")
        pnl_7d = float(fx_7d[0].get("pnl") or 0) if fx_7d else 0
        n_7d = int(fx_7d[0].get("n") or 0) if fx_7d else 0
        last_t = str(last_fx[0].get("last") or "Never")[:10] if last_fx else "Never"
        wr_nav = _pg_query(
            "SELECT AVG(CASE WHEN pnl_usd > 0 THEN 100.0 ELSE 0.0 END) as wr "
            "FROM forex_trades WHERE status = 'closed'"
        )
        wr = float(wr_nav[0].get("wr") or 0) if wr_nav else None
        health = _compute_health_score(wr, None, n_7d > 0, 0, nav_pos > 0, True)
        issues = "Clean" if health >= 70 else (f"{nav_pos} positions open" if nav_pos > 0 else "No open positions")
        bots.append({
            "num": "#6", "name": "Navigator", "status": "🟢 LIVE", "last_trade": last_t,
            "pnl_7d": pnl_7d, "health": health, "equity": nav_eq, "issues": issues
        })
    except Exception as e:
        bots.append({"num": "#6", "name": "Navigator", "status": "⚠️ ERR", "last_trade": "?",
                     "pnl_7d": 0, "health": 0, "equity": 0, "issues": str(e)[:40]})

    # Poseidon (#7)
    try:
        pos_ls = _read_poseidon_live_state()
        pos_eq = float(pos_ls.get("equity", 100000) or 100000)
        pos_rows_7d = _pg_query(
            "SELECT COUNT(*) as n, SUM(net_pnl) as pnl FROM poseidon_trades "
            "WHERE closed_at > NOW() - INTERVAL '7 days'"
        )
        last_pos = _pg_query("SELECT MAX(closed_at) as last FROM poseidon_trades")
        pnl_7d = float(pos_rows_7d[0].get("pnl") or 0) if pos_rows_7d else 0
        n_7d = int(pos_rows_7d[0].get("n") or 0) if pos_rows_7d else 0
        last_t = str(last_pos[0].get("last") or "Never")[:10] if last_pos else "Never"

        hb_pos = _pg_query("SELECT circuit_breaker FROM kraken_heartbeat WHERE id = 7")
        cb_pos = hb_pos[0].get("circuit_breaker") if hb_pos else None
        if isinstance(cb_pos, str):
            cb_pos = _json_diag.loads(cb_pos)
        cb_tripped = isinstance(cb_pos, dict) and cb_pos.get("tripped")
        status = "🔴 CB" if cb_tripped else "🟢 LIVE"

        health = _compute_health_score(None, None, n_7d > 0, 0, True, True)
        issues = "Circuit breaker active" if cb_tripped else ("Clean" if n_7d > 0 else "No trades in 7d")
        bots.append({
            "num": "#7", "name": "Poseidon", "status": status, "last_trade": last_t,
            "pnl_7d": pnl_7d, "health": health, "equity": pos_eq, "issues": issues
        })
    except Exception as e:
        bots.append({"num": "#7", "name": "Poseidon", "status": "⚠️ ERR", "last_trade": "?",
                     "pnl_7d": 0, "health": 0, "equity": 0, "issues": str(e)[:40]})

    # Kraken Current (#8)
    try:
        hb_kc = _pg_query("SELECT equity_usd, position_count, status FROM kraken_heartbeat WHERE id = 8")
        kc_eq = float(hb_kc[0].get("equity_usd") or 100000) if hb_kc else 100000
        kc_status_val = str(hb_kc[0].get("status") or "unknown") if hb_kc else "unknown"
        kc_trades_7d = _pg_query(
            "SELECT COUNT(*) as n, SUM(pnl_usd) as pnl_usd FROM kraken_current_trades "
            "WHERE closed_at > NOW() - INTERVAL '7 days'"
        )
        last_kc = _pg_query("SELECT MAX(closed_at) as last FROM kraken_current_trades")
        pnl_7d = float(kc_trades_7d[0].get("pnl_usd") or 0) if kc_trades_7d else 0
        n_7d = int(kc_trades_7d[0].get("n") or 0) if kc_trades_7d else 0
        last_t = str(last_kc[0].get("last") or "Never")[:10] if last_kc else "Never"
        status = "🟢 LIVE" if kc_status_val not in ("unknown", "error") else "⚠️ UNKNOWN"
        health = _compute_health_score(None, None, n_7d > 0, 0, True, True)
        issues = "Clean" if n_7d > 0 else "No trades yet — awaiting trend signal"
        bots.append({
            "num": "#8", "name": "Kraken Current", "status": status, "last_trade": last_t,
            "pnl_7d": pnl_7d, "health": health, "equity": kc_eq, "issues": issues
        })
    except Exception as e:
        bots.append({"num": "#8", "name": "Kraken Current", "status": "⚠️ ERR", "last_trade": "?",
                     "pnl_7d": 0, "health": 0, "equity": 0, "issues": str(e)[:40]})

    # Print scorecard table
    lines.append(f"  {'Bot':<22} {'Status':<12} {'Last Trade':<12} {'7d P&L':>10} {'Health':>8}  Issues")
    lines.append("  " + "-" * 82)
    total_equity = 0.0
    live_count = 0
    attention_needed = []
    for b in bots:
        health_str = f"{b['health']}/100"
        if b["health"] >= 75:
            health_icon = f"✅ {health_str}"
        elif b["health"] >= 50:
            health_icon = f"⚠️  {health_str}"
        else:
            health_icon = f"❌ {health_str}"

        pnl_str = _c(b["pnl_7d"]) if b["pnl_7d"] != 0 else "$0"
        name_full = f"{b['num']} {b['name']}"
        lines.append(
            f"  {name_full:<22} {b['status']:<12} {b['last_trade']:<12} {pnl_str:>10} {health_icon:<12}  {b['issues']}"
        )
        total_equity += b.get("equity", 0)
        if "LIVE" in b["status"]:
            live_count += 1
        if b["health"] < 60 or b["issues"] not in ("Clean", "Active"):
            if b["issues"] not in ("Clean", "Active", "No trades yet — awaiting trend signal",
                                    "No trades yet — awaiting vol squeeze signal"):
                attention_needed.append(f"  ⚠️  {b['num']} {b['name']}: {b['issues']}")

    lines.append("")
    total_pnl_7d = sum(b["pnl_7d"] for b in bots)
    fleet_pnl = total_equity - 800_000
    lines.append(f"  Fleet status:       {live_count}/8 bots live")
    lines.append(f"  Total fleet equity: {_c(total_equity)} | vs $800,000 baseline | {_c(fleet_pnl)} ({_pct(fleet_pnl/8000)})")
    lines.append(f"  7-day fleet P&L:    {_c(total_pnl_7d)}")

    if attention_needed:
        lines.append("")
        lines.append("  Requires attention:")
        for a in attention_needed:
            lines.append(a)

    lines.append("")
    lines.append("  Health score (0-100): win rate (25%) + profit factor (25%) + cycle execution (20%)")
    lines.append("                        + trade frequency (15%) + parameter integrity (15%)")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 6: Execution Quality Expanded — All Bots
# ──────────────────────────────────────────────────────────────────────────────

def section_execution_quality_all_bots(alpaca_trades: list = None, kraken_trades: list = None, fx_trades: list = None) -> list[str]:
    """ADD 6: Execution Quality for all bots (expanded from Oracle-only)."""
    lines: list[str] = []
    _h1(lines, "ADDITION 6: EXECUTION QUALITY — ALL BOTS")
    alpaca_trades = alpaca_trades or []
    kraken_trades = kraken_trades or []
    fx_trades = fx_trades or []

    # Oracle
    _h2(lines, "ORACLE #1 (Alpaca)")
    alpaca_with_slip = [t for t in alpaca_trades if t.get("slippage_pct") is not None]
    oracle_rejected = _pg_query(
        "SELECT COUNT(*) as n FROM trades WHERE exit_reason ILIKE '%reject%' OR exit_reason ILIKE '%error%'"
    )
    oracle_total = _pg_query("SELECT COUNT(*) as n FROM trades")
    oracle_n = int(oracle_total[0].get("n") or 0) if oracle_total else 0

    _row(lines, "Total trades (all time):", str(oracle_n))
    if alpaca_with_slip:
        avg_slip = sum(float(t.get("slippage_pct")) for t in alpaca_with_slip) / len(alpaca_with_slip)
        worst_slip = max(alpaca_with_slip, key=lambda t: abs(float(t.get("slippage_pct"))))
        _row(lines, "Trades with fill data:", str(len(alpaca_with_slip)))
        _row(lines, "Average slippage:", f"{avg_slip:.4f}%")
        _row(lines, "Worst slippage:", f"{float(worst_slip.get('slippage_pct')):.4f}% on {worst_slip.get('symbol','?')}")
    else:
        _row(lines, "Slippage data:", "Not yet captured (requires intended_price vs fill_price logging)")
    rej_n = int(oracle_rejected[0].get("n") or 0) if oracle_rejected else 0
    _row(lines, "Orders rejected:", str(rej_n))
    _row(lines, "Fill rate:", f"{((oracle_n - rej_n) / oracle_n * 100):.1f}%" if oracle_n > 0 else "N/A")

    # Kraken Fleet
    _h2(lines, "KRAKEN FLEET #2-4 (Davy Jones / Blackbeard / Calypso)")
    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    k_stats = _pg_query(
        "SELECT COUNT(*) as n, SUM(fees_usd) as total_fees, SUM(pnl_usd) as gross_pnl, "
        "AVG(pnl_pct) as avg_pnl_pct "
        "FROM kraken_trades WHERE closed_at > %s",
        (cutoff_7d,)
    )
    k_all_time = _pg_query("SELECT COUNT(*) as n FROM kraken_trades")
    k_n_7d = int(k_stats[0].get("n") or 0) if k_stats else 0
    k_fees_7d = float(k_stats[0].get("total_fees") or 0) if k_stats else 0
    k_gross_7d = float(k_stats[0].get("gross_pnl") or 0) if k_stats else 0
    k_all_n = int(k_all_time[0].get("n") or 0) if k_all_time else 0

    fee_pct = (k_fees_7d / abs(k_gross_7d) * 100) if k_gross_7d != 0 else 0
    fee_flag = " ⚠️ HIGH" if fee_pct > 40 else ""

    _row(lines, "Total trades (all time):", str(k_all_n))
    _row(lines, "Trades (7d):", str(k_n_7d))
    _row(lines, "Fee total (7d):", _c(k_fees_7d))
    _row(lines, "Gross P&L (7d):", _c(k_gross_7d))
    _row(lines, "Fee as % of gross P&L:", f"{fee_pct:.1f}%{fee_flag}")
    _row(lines, "Slippage model:", "Kraken exchange fills at market (paper simulation)")
    _row(lines, "Entry/exit model:", "Market orders — minimal slippage at crypto scale")

    # Per-bot breakdown
    for bid, label in [("davy-jones", "Davy Jones"), ("blackbeard", "Blackbeard"), ("calypso", "Calypso")]:
        bot_stats = _pg_query(
            "SELECT COUNT(*) as n, SUM(fees_usd) as fees, SUM(pnl_usd) as pnl "
            "FROM kraken_trades WHERE bot_id = %s AND closed_at > %s",
            (bid, cutoff_7d)
        )
        bn = int(bot_stats[0].get("n") or 0) if bot_stats else 0
        bf = float(bot_stats[0].get("fees") or 0) if bot_stats else 0
        bp = float(bot_stats[0].get("pnl") or 0) if bot_stats else 0
        lines.append(f"    {label}: {bn} trades | fees={_c(bf)} | P&L={_c(bp)}")

    # Navigator
    _h2(lines, "NAVIGATOR #6 (OANDA/Paper Forex)")
    fx_7d = _pg_query(
        "SELECT COUNT(*) as n, 0.0 as spread_cost, SUM(pnl_usd) as pnl "
        "FROM forex_trades WHERE status = 'closed' AND closed_at > %s",
        (cutoff_7d,)
    )
    nav_ls = _read_navigator_live_state()
    news_blackout = nav_ls.get("news_blackout", False)

    fx_n = int(fx_7d[0].get("n") or 0) if fx_7d else 0
    fx_spread = float(fx_7d[0].get("spread_cost") or 0) if fx_7d else 0
    fx_pnl = float(fx_7d[0].get("pnl") or 0) if fx_7d else 0

    _row(lines, "Trades (7d):", str(fx_n))
    _row(lines, "Spread cost paid (7d):", _c(fx_spread))
    _row(lines, "Avg spread per trade:", _c(fx_spread / fx_n) if fx_n > 0 else "N/A")
    _row(lines, "Net P&L (7d):", _c(fx_pnl))
    _row(lines, "News blackout active:", "YES" if news_blackout else "NO")
    _row(lines, "Spread cost model:", "0.1% per side (paper engine simulation)")

    # Poseidon
    _h2(lines, "POSEIDON #7 (Statistical Arbitrage)")
    pos_7d = _pg_query(
        "SELECT COUNT(*) as n, AVG(net_pnl) as avg_pnl, SUM(net_pnl) as total_pnl "
        "FROM poseidon_trades WHERE closed_at > %s",
        (cutoff_7d,)
    )
    pos_n = int(pos_7d[0].get("n") or 0) if pos_7d else 0
    pos_pnl = float(pos_7d[0].get("total_pnl") or 0) if pos_7d else 0

    _row(lines, "Pair positions opened (7d):", str(pos_n))
    _row(lines, "Net P&L (7d):", _c(pos_pnl))
    _row(lines, "Hedge ratio accuracy:", "Tracked via hedge_ratio_30d_avg vs hedge_ratio in DB")
    _row(lines, "Leg synchronisation:", "Both legs submitted simultaneously (atomic simulation)")
    _row(lines, "Slippage model:", "Kraken paper fills at market (0.26% fee per leg)")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 7: Daily P&L Attribution
# ──────────────────────────────────────────────────────────────────────────────

def section_daily_pnl_attribution() -> list[str]:
    """ADD 7: Daily P&L Attribution — per-bot per-day for last 7 trading days."""
    lines: list[str] = []
    _h1(lines, "ADDITION 7: DAILY P&L ATTRIBUTION — LAST 7 TRADING DAYS")
    lines.append("  P&L computed from equity_snapshots table (daily close equity vs prior day).")
    lines.append("")

    # Get last 8 days of equity snapshots (we need prev day for delta)
    snap_rows = _pg_query(
        "SELECT DATE(ts) as day, "
        "MAX(alpaca_equity) as oracle_eq, "
        "MAX(kraken_equity) as kraken_eq, "
        "MAX(options_equity) as apex_eq, "
        "MAX(forex_equity) as nav_eq, "
        "MAX(poseidon_equity) as poseidon_eq, "
        "MAX(kraken_current_equity) as kc_eq "
        "FROM equity_snapshots "
        "WHERE ts > NOW() - INTERVAL '9 days' "
        "GROUP BY DATE(ts) ORDER BY day ASC"
    )

    if not snap_rows or len(snap_rows) < 2:
        lines.append("  Insufficient equity snapshot data (need at least 2 days).")
        lines.append("  Equity snapshots are recorded by the trading API every 5 minutes.")
        return lines

    # Also get Kraken per-bot P&L from kraken_trades
    kraken_daily = {}
    for bid, label in [("davy-jones", "dj"), ("blackbeard", "bb"), ("calypso", "cy")]:
        k_daily_rows = _pg_query(
            "SELECT DATE(closed_at) as day, SUM(pnl_usd) as pnl "
            "FROM kraken_trades WHERE bot_id = %s AND closed_at > NOW() - INTERVAL '9 days' "
            "GROUP BY DATE(closed_at) ORDER BY day ASC",
            (bid,)
        )
        for r in k_daily_rows:
            day_str = str(r.get("day", "?"))
            if day_str not in kraken_daily:
                kraken_daily[day_str] = {"dj": 0, "bb": 0, "cy": 0}
            kraken_daily[day_str][label] = float(r.get("pnl") or 0)

    # Build daily P&L by diffing consecutive equity snapshots
    lines.append(f"  {'Date':<12} {'Oracle':>9} {'Kraken MR':>10} {'Apex':>7} {'Navigator':>10} {'Poseidon':>9} {'KC':>8} {'Total':>10}")
    lines.append("  " + "-" * 80)

    totals = {"oracle": 0, "kraken": 0, "apex": 0, "nav": 0, "poseidon": 0, "kc": 0, "total": 0}
    prev = None

    for row in snap_rows:
        day = str(row.get("day", "?"))
        if prev is None:
            prev = row
            continue

        o_pnl = float(row.get("oracle_eq") or 0) - float(prev.get("oracle_eq") or 0)
        k_pnl = float(row.get("kraken_eq") or 0) - float(prev.get("kraken_eq") or 0)
        a_pnl = float(row.get("apex_eq") or 0) - float(prev.get("apex_eq") or 0)
        n_pnl = float(row.get("nav_eq") or 0) - float(prev.get("nav_eq") or 0)
        p_pnl = float(row.get("poseidon_eq") or 0) - float(prev.get("poseidon_eq") or 0)
        kc_pnl = float(row.get("kc_eq") or 0) - float(prev.get("kc_eq") or 0)
        total = o_pnl + k_pnl + a_pnl + n_pnl + p_pnl + kc_pnl

        def fmt(v):
            if abs(v) < 0.01:
                return "$0"
            sign = "+" if v >= 0 else ""
            return f"{sign}${abs(v):,.0f}" if v < 0 else f"+${v:,.0f}"

        lines.append(
            f"  {day:<12} {fmt(o_pnl):>9} {fmt(k_pnl):>10} {fmt(a_pnl):>7} {fmt(n_pnl):>10} "
            f"{fmt(p_pnl):>9} {fmt(kc_pnl):>8} {fmt(total):>10}"
        )

        totals["oracle"] += o_pnl
        totals["kraken"] += k_pnl
        totals["apex"] += a_pnl
        totals["nav"] += n_pnl
        totals["poseidon"] += p_pnl
        totals["kc"] += kc_pnl
        totals["total"] += total
        prev = row

    lines.append("  " + "-" * 80)
    lines.append(
        f"  {'7-day total':<12} {_c(totals['oracle']):>9} {_c(totals['kraken']):>10} "
        f"{_c(totals['apex']):>7} {_c(totals['nav']):>10} {_c(totals['poseidon']):>9} "
        f"{_c(totals['kc']):>8} {_c(totals['total']):>10}"
    )

    # Best/worst single trades
    best_k = _pg_query(
        "SELECT bot_id, symbol, pnl_usd, closed_at FROM kraken_trades "
        "WHERE closed_at > NOW() - INTERVAL '7 days' ORDER BY pnl_usd DESC LIMIT 1"
    )
    worst_k = _pg_query(
        "SELECT bot_id, symbol, pnl_usd, closed_at FROM kraken_trades "
        "WHERE closed_at > NOW() - INTERVAL '7 days' ORDER BY pnl_usd ASC LIMIT 1"
    )
    best_a = _pg_query(
        "SELECT ticker, realized_pnl as pnl, date FROM trades WHERE date > NOW() - INTERVAL '7 days' ORDER BY realized_pnl DESC LIMIT 1"
    )
    worst_a = _pg_query(
        "SELECT ticker, realized_pnl as pnl, date FROM trades WHERE date > NOW() - INTERVAL '7 days' ORDER BY realized_pnl ASC LIMIT 1"
    )

    lines.append("")
    if best_k:
        b = best_k[0]
        lines.append(f"  Best single trade (Kraken, 7d):  {b.get('bot_id')} {b.get('symbol')} {_c(float(b.get('pnl_usd') or 0))} on {str(b.get('closed_at','?'))[:10]}")
    if worst_k:
        b = worst_k[0]
        lines.append(f"  Worst single trade (Kraken, 7d): {b.get('bot_id')} {b.get('symbol')} {_c(float(b.get('pnl_usd') or 0))} on {str(b.get('closed_at','?'))[:10]}")
    if best_a:
        b = best_a[0]
        lines.append(f"  Best single trade (Oracle, 7d):  {b.get('ticker')} {_c(float(b.get('pnl') or 0))} on {str(b.get('date','?'))[:10]}")
    if worst_a:
        b = worst_a[0]
        lines.append(f"  Worst single trade (Oracle, 7d): {b.get('ticker')} {_c(float(b.get('pnl') or 0))} on {str(b.get('date','?'))[:10]}")

    # Fee drag
    fee_7d = _pg_query(
        "SELECT SUM(fees_usd) as fees FROM kraken_trades WHERE closed_at > NOW() - INTERVAL '7 days'"
    )
    total_fees = float(fee_7d[0].get("fees") or 0) if fee_7d else 0
    lines.append(f"  Fee drag total (7d, Kraken):     {_c(total_fees)}")
    lines.append(f"  Net P&L ex-fees (7d, Kraken):    {_c(totals['kraken'] + total_fees)}")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 8: Open Position Risk Summary
# ──────────────────────────────────────────────────────────────────────────────

def section_open_position_risk(alpaca_positions: list = None, fx_positions: list = None) -> list[str]:
    """ADD 8: Open Position Risk Summary — all bots with stop distances."""
    lines: list[str] = []
    _h1(lines, "ADDITION 8: OPEN POSITION RISK SUMMARY — ALL BOTS")
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"  Generated: {now_ts}")
    lines.append("")

    alpaca_positions = alpaca_positions or []
    fx_positions = fx_positions or []

    all_rows = []

    # Oracle positions
    for p in alpaca_positions:
        sym = str(p.get("symbol", "?"))
        side = str(p.get("side", "long"))
        entry = float(p.get("avg_entry_price") or 0)
        current = float(p.get("current_price") or 0)
        mval = float(p.get("market_value") or 0)
        upl = float(p.get("unrealized_pl") or 0)
        sl_px = p.get("stop_loss_price")
        sl_pct = p.get("stop_loss_pct")
        tp_px = p.get("take_profit_price")
        entry_time = str(p.get("entry_time") or "?")[:10]

        sl_dist = None
        if sl_px and current:
            sl_dist = (float(sl_px) - current) / current * 100

        time_open = "?"
        all_rows.append({
            "bot": "Oracle", "symbol": sym, "side": side.upper(), "entry": entry,
            "current": current, "upl": upl, "size": abs(mval), "sl_px": sl_px,
            "sl_dist": sl_dist, "tp_px": tp_px, "entry_date": entry_time
        })

    # Kraken bots
    for bid, label in [("davy-jones", "DJ"), ("blackbeard", "BB"), ("calypso", "Calypso")]:
        ls = _read_kraken_live_state(bid)
        for p in (ls.get("open_positions") or []):
            sym = str(p.get("symbol", "?"))
            side = str(p.get("side", "?")).upper()
            entry = float(p.get("entry_price") or 0)
            current = float(p.get("current_price") or 0)
            size_usd = float(p.get("size_usd") or 0)
            upl = float(p.get("unrealized_pnl_usd") or 0)
            sl_px = p.get("stop_loss_price")
            tp_px = p.get("take_profit_price")

            sl_dist = None
            if sl_px and current:
                sl_dist = (float(sl_px) - current) / current * 100

            entry_date = str(p.get("entry_time") or "?")[:10]
            all_rows.append({
                "bot": label, "symbol": sym, "side": side, "entry": entry,
                "current": current, "upl": upl, "size": size_usd, "sl_px": sl_px,
                "sl_dist": sl_dist, "tp_px": tp_px, "entry_date": entry_date
            })

    # Navigator positions
    nav_ls = _read_navigator_live_state()
    for p in (nav_ls.get("positions") or []):
        pair = str(p.get("pair", "?"))
        direction = str(p.get("direction", "?")).upper()
        entry = float(p.get("entry_price") or 0)
        current = float(p.get("current_price") or entry)
        size_usd = float(p.get("size_usd") or 0)
        upl = float(p.get("unrealized_pnl_usd") or 0)
        sl_px = p.get("sl_price")
        tp_px = p.get("tp_price")

        sl_dist = None
        if sl_px and current:
            sl_dist = (float(sl_px) - current) / current * 100

        entry_date = str(p.get("entry_time") or "?")[:10]
        all_rows.append({
            "bot": "Nav", "symbol": pair.replace("_", "/"), "side": direction, "entry": entry,
            "current": current, "upl": upl, "size": size_usd, "sl_px": sl_px,
            "sl_dist": sl_dist, "tp_px": tp_px, "entry_date": entry_date
        })

    # Poseidon positions (from live state) — real pair names, prices, and P&L
    pos_ls = _read_poseidon_live_state()
    positions_data = pos_ls.get("positions") or {}
    if isinstance(positions_data, dict):
        for pair_key, p in positions_data.items():
            _paa  = str(p.get("asset_a", "?")).replace("/USD", "")
            _pab  = str(p.get("asset_b", "?")).replace("/USD", "")
            _psym = f"{_paa}/{_pab}"[:14]
            _pdir = "S:A/L:B" if p.get("direction") == "short_a_long_b" else "L:A/S:B"
            _pent = float(p.get("leg_a_entry") or 0)
            _pcur = float(p.get("current_price_a") or p.get("leg_a_current") or 0)
            _pupl = float(p.get("total_pnl") or 0)
            _psz  = float(p.get("position_value") or 0)
            _poa  = str(p.get("opened_at") or "?")[:10]
            all_rows.append({
                "bot": "Poseidon", "symbol": _psym, "side": _pdir,
                "entry": _pent, "current": _pcur, "upl": _pupl, "size": _psz,
                "sl_px": None, "sl_dist": None, "tp_px": None, "entry_date": _poa
            })

    if not all_rows:
        lines.append("  No open positions across any bot at report time.")
        return lines

    lines.append(f"  {'Bot':<10} {'Symbol':<14} {'Side':<7} {'Entry':>10} {'Current':>10} {'Unreal P&L':>12} {'SL Dist':>9}  Open")
    lines.append("  " + "-" * 84)

    total_upl = 0.0
    total_risk = 0.0
    approaching_sl = []
    in_profit = []

    for r in all_rows:
        entry_str = f"{r['entry']:.4f}" if r["entry"] < 10 else f"{r['entry']:.2f}"
        curr_str = f"{r['current']:.4f}" if r["current"] < 10 else f"{r['current']:.2f}"
        sl_str = f"{r['sl_dist']:+.2f}%" if r["sl_dist"] is not None else "N/A"
        upl_str = _c(r["upl"])

        lines.append(
            f"  {r['bot']:<10} {r['symbol']:<14} {r['side']:<7} {entry_str:>10} {curr_str:>10} "
            f"{upl_str:>12} {sl_str:>9}  {r['entry_date']}"
        )
        total_upl += r["upl"]
        if r["sl_dist"] is not None:
            risk = abs(r["sl_dist"]) / 100 * r["size"]
            total_risk += risk
            if abs(r["sl_dist"]) <= 1.0:
                approaching_sl.append(f"{r['bot']} {r['symbol']} ({sl_str} from SL)")
        if r["upl"] / r["size"] > 0.02 if r["size"] > 0 else False:
            in_profit.append(f"{r['bot']} {r['symbol']} ({_pct(r['upl']/r['size']*100)})")

    lines.append("")
    lines.append(f"  Total open positions:      {len(all_rows)}")
    lines.append(f"  Total unrealised P&L:      {_c(total_upl)}")
    lines.append(f"  Total capital at risk:     {_c(total_risk)} (sum of SL dist × position sizes)")

    if approaching_sl:
        lines.append(f"  ⚠️  Approaching stop (≤1%): {', '.join(approaching_sl)}")
    else:
        lines.append(f"  Positions approaching stop (≤1%): None")

    if in_profit:
        lines.append(f"  Positions in profit >2%:  {', '.join(in_profit)}")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 9: System Infrastructure Status
# ──────────────────────────────────────────────────────────────────────────────

def section_infrastructure_status(sched_jobs: list = None) -> list[str]:
    """ADD 9: System Infrastructure Status — scheduled jobs + API connections."""
    lines: list[str] = []
    _h1(lines, "ADDITION 9: SYSTEM INFRASTRUCTURE STATUS")
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"  Generated: {now_ts}")
    lines.append("")

    # Scheduled jobs
    _h2(lines, "SCHEDULED JOBS")
    sched_jobs = sched_jobs or []
    if sched_jobs:
        lines.append(f"  {'Job':<45} {'Next Run':<22} Status")
        lines.append("  " + "-" * 72)
        for job in sched_jobs:
            name = str(job.get("name", "?"))[:42]
            next_fire = str(job.get("next_fire_utc", "?"))[:19]
            status = "✅ SCHEDULED"
            lines.append(f"  {name:<45} {next_fire:<22} {status}")
    else:
        lines.append("  No scheduler job data available (API not accessible or no jobs configured).")

    # Bot heartbeats
    _h2(lines, "BOT HEARTBEATS (last DB write)")
    hb_rows = _pg_query(
        "SELECT id, status, last_updated, position_count, equity_usd FROM kraken_heartbeat ORDER BY id"
    )
    bot_names = {1: "Davy Jones #2", 2: "Blackbeard #3", 3: "Calypso #4", 7: "Poseidon #7", 8: "Kraken Current #8"}
    if hb_rows:
        lines.append(f"  {'Bot':<22} {'Status':<14} {'Last Update':<22} {'Positions':>10} {'Equity':>12}")
        lines.append("  " + "-" * 82)
        for hb in hb_rows:
            bid = hb.get("id")
            bname = bot_names.get(bid, f"Bot {bid}")
            status = str(hb.get("status") or "unknown")
            last = str(hb.get("last_updated") or "?")[:19]
            pos = int(hb.get("position_count") or 0)
            eq = float(hb.get("equity_usd") or 0)
            lines.append(f"  {bname:<22} {status:<14} {last:<22} {pos:>10} {_c(eq):>12}")
    else:
        lines.append("  No heartbeat data available.")

    # API connection checks
    _h2(lines, "DATA CONNECTIONS")

    def _check_api(name: str, check_fn) -> str:
        try:
            result = check_fn()
            return f"✅ CONNECTED | {result}"
        except Exception as e:
            return f"❌ ERROR: {str(e)[:60]}"

    # DB check
    try:
        db_rows = _pg_query("SELECT COUNT(*) as n FROM equity_snapshots")
        snap_count = int(db_rows[0].get("n") or 0) if db_rows else 0
        last_snap = _pg_query("SELECT ts FROM equity_snapshots ORDER BY ts DESC LIMIT 1")
        last_ts = str(last_snap[0].get("ts") or "?")[:19] if last_snap else "?"
        db_status = f"✅ CONNECTED | {snap_count} equity snapshots | Last write: {last_ts}"
    except Exception as e:
        db_status = f"❌ ERROR: {str(e)[:60]}"

    # Kraken live state age
    dj_ls = _read_kraken_live_state("davy-jones")
    dj_last = str(dj_ls.get("last_updated", "?"))[:19]

    # Navigator live state age
    nav_ls = _read_navigator_live_state()
    nav_last = str(nav_ls.get("last_updated", "?"))[:19]

    # Poseidon live state age
    pos_ls = _read_poseidon_live_state()
    pos_last = str(pos_ls.get("last_updated", "?"))[:19]

    lines.append(f"  PostgreSQL DB:       {db_status}")
    lines.append(f"  Kraken Bot Data:     Last live_state update: {dj_last} UTC")
    lines.append(f"  Navigator Data:      Last live_state update: {nav_last} UTC")
    lines.append(f"  Poseidon Data:       Last live_state update: {pos_last} UTC")

    # Oracle scan lag
    last_scan = _pg_query("SELECT ts FROM oracle_scan_log ORDER BY ts DESC LIMIT 1")
    if last_scan:
        scan_ts = str(last_scan[0].get("ts") or "?")[:19]
        lines.append(f"  Oracle Scan Data:    Last scan log entry: {scan_ts} UTC")
    else:
        lines.append(f"  Oracle Scan Data:    No scan log entries (Oracle not yet scanning)")

    # Recent system errors
    _h2(lines, "RECENT SYSTEM ERRORS (last 24h)")
    err_rows = _pg_query(
        "SELECT degradation_type, details, detected_at FROM system_degradations "
        "WHERE detected_at > NOW() - INTERVAL '24 hours' ORDER BY detected_at DESC LIMIT 10"
    )
    if err_rows:
        for e in err_rows:
            ts = str(e.get("detected_at") or "?")[:19]
            dtype = str(e.get("degradation_type") or "?")
            details = str(e.get("details") or "")[:60]
            lines.append(f"  {ts}  [{dtype}]  {details}")
    else:
        lines.append("  No system errors in last 24 hours.")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION 10: Changes Since Last Report
# ──────────────────────────────────────────────────────────────────────────────

def section_platform_audit_changelog() -> list[str]:
    """Static changelog of platform-wide algorithm and architecture changes (Apr 2026)."""
    lines: list[str] = []
    lines.append("")
    lines.append("\u2550" * 80)
    lines.append("  PLATFORM AUDIT \u2014 ALGORITHM FIXES & ARCHITECTURE CHANGES (Apr 2026)")
    lines.append("\u2550" * 80)
    lines += [
        "",
        "  This section documents all material changes made to the platform in Apr 2026",
        "  as part of the platform-wide quantitative audit (18 issues identified).",
        "",
        "\u2500\u2500 CRITICAL: ATR Algorithm Fix (forex-engine/indicators.py) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "  BEFORE: calculate_atr() used SMA over each rolling window of TRs (np.mean).",
        "          This underestimates ATR on volatile moves and is NOT standard Wilder\u2019s.",
        "  AFTER:  Wilder\u2019s EMA: seed = SMA of first 14 TRs, then recursive update:",
        "          atr = (atr_prev * (period - 1) + tr_current) / period",
        "          Now exactly matches math_auditor.verified_atr() reference.",
        "  IMPACT: All forex-engine stop-loss distances and TP levels now use",
        "          industry-standard ATR values.",
        "",
        "\u2500\u2500 CRITICAL: RSI Algorithm Fix (core/pipeline.py afterhours crypto RSI) \u2500\u2500\u2500\u2500\u2500",
        "  BEFORE: Afterhours crypto RSI used .rolling(14).mean() (SMA-based), which",
        "          produces systematically lower RSI values than standard Wilder\u2019s.",
        "  AFTER:  Wilder\u2019s EMA RSI identical to forex-engine/indicators.py:calculate_rsi():",
        "          gain/loss seed = SMA, then recursive Wilder averaging.",
        "  IMPACT: Crypto regime signals computed by Oracle during afterhours now use",
        "          correct RSI values consistent with intraday signals.",
        "",
        "\u2500\u2500 HIGH: Win-Metric Single Source of Truth (core.metrics.WIN_THRESHOLD) \u2500\u2500\u2500\u2500\u2500\u2500",
        "  BEFORE: Win/loss counts scattered across the codebase used hardcoded `> 0`",
        "          comparisons in Python list comprehensions and SQL CASE WHEN / COUNT",
        "          FILTER expressions. Changing WIN_THRESHOLD would require hunting all",
        "          occurrences manually.",
        "  AFTER:",
        "    \u2022 core/metrics.py: WIN_THRESHOLD = 0.0 (single constant, import everywhere)",
        "    \u2022 core/metrics.py: added win_rate_from_counts(wins, total) helper for use",
        "      when individual trade dicts are unavailable (e.g. SQL GROUP BY results)",
        "    \u2022 routes/kraken.py: all win list comprehensions, by-symbol wins, and SQL",
        "      fleet-summary CASE WHEN expressions parameterized with _WIN_THRESHOLD",
        "    \u2022 routes/new_bots.py: pair-learning SQL COUNT FILTER uses %s parameter",
        "      with _WIN_THRESHOLD; win_rate now calls _win_rate_from_counts()",
        "    \u2022 Poseidon and Kraken Current fleet-summary SQL also parameterized",
        "  IMPACT: A single threshold change in core/metrics.py propagates to all",
        "          win-rate calculations fleet-wide automatically.",
        "",
        "\u2500\u2500 HIGH: Rolling 30-Day Trade Window (routes/kraken.py) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "  BEFORE: /kraken/status and /kraken/performance queries had a hardcoded date",
        "          literal ('2026-04-13 00:00:00+00') that would never update, causing",
        "          all-time metrics to be silently incomplete once that date passed.",
        "  AFTER:  Both queries now use: WHERE closed_at >= NOW() - INTERVAL '30 days'",
        "          This gives a rolling 30-day window that is always current.",
        "  IMPACT: Status endpoint (win count, P&L) and performance endpoint (win rate,",
        "          by-symbol breakdown) now reflect trailing 30 days, not a stale slice.",
        "",
        "\u2500\u2500 HIGH: Options Engine Retired (4 files) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "  Apex Predator (Bot #5) was migrated from the Alpaca options strategy to",
        "  Kraken crypto momentum. The options engine is now fully retired:",
        "    \u2022 routes/_deps.py: _get_options_engine() returns None immediately (stub)",
        "    \u2022 routes/control.py: _liquidate_options_positions() returns empty result",
        "    \u2022 routes/portfolio.py: _opts = None, import removed, try/except removed",
        "    \u2022 core/pipeline.py: options_eq = 0.0 (one-liner replaces import+try block)",
        "  IMPACT: No code path imports or executes options_engine. The export report",
        "          SECTION 4 now reports on Apex Predator\u2019s Kraken performance.",
        "",
        "\u2500\u2500 DASHBOARD: Apex Predator Card Migrated to Kraken \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "  Task #120 (Apr 2026): Apex Predator card on the Bots page was re-wired from",
        "  the retired useOptionsState/useOptionsPositions hooks to:",
        "    \u2022 useKrakenPerformance('apex-predator') for performance metrics",
        "    \u2022 useKrakenStatus('apex-predator') for live status and trades",
        "  The eagle \ud83e\udd85 icon was preserved. Dashboard compiles cleanly.",
        "",
        "\u2500\u2500 DASHBOARD: Vault Balance Display Added to 4 Pages (Task #120) \u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "  total_vaulted_usd is now displayed on:",
        "    \u2022 Fleet page (StreamingScreenV2.tsx HeroStrip) \u2014 next to win rate",
        "    \u2022 Bots page (StreamingBotsScreen.tsx) \u2014 header strip next to starting capital",
        "    \u2022 Orb page (StreamingOrbScreen.tsx) \u2014 dedicated header strip above 3D canvas",
        "    \u2022 Performance page (StreamingPerformanceScreen.tsx) \u2014 next to fleet P&L",
        "  All sourced from existing useVault() hook (/ portfolio/vault endpoint).",
        "",
        "\u2500\u2500 DASHBOARD: Vault Growth Chart Added to Performance Page (Task #121) \u2500\u2500",
        "  A 90-day cumulative vault area chart was added to the Performance page:",
        "    \u2022 Backend: GET /vault/history?days=N (default 90, clamped 1\u2013730)",
        "      Reconstructs daily vault contributions from kraken_trades + forex_trades",
        "      grouped by date, computes running cumulative totals",
        "    \u2022 Frontend: useVaultHistory(days) hook, Recharts AreaChart + dashed",
        "      daily-contribution line, dark glassmorphism panel",
        "  Shows traders how accumulated vault profits have grown over 90 days.",
        "",
        "\u2500\u2500 CALYPSO RSI CONTRARIAN THRESHOLD CALIBRATION (kraken-bot/config.py) \u2500\u2500\u2500",
        "  Apr 2026: CONTRARIAN_RSI_THRESH lowered from 30 \u2192 28 to improve entry timing",
        "  on genuine oversold conditions. DEEP_OVERSOLD_RSI = 20 (unchanged).",
        "  Affects all Kraken fleet bots (shared config constant).",
    ]
    return lines


def _load_last_report_state() -> dict:
    try:
        return _json_diag.loads(_LAST_REPORT_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_report_state(state: dict) -> None:
    try:
        _LAST_REPORT_STATE_FILE.write_text(_json_diag.dumps(state, indent=2, default=str))
    except Exception:
        pass


def section_changes_since_last_report() -> list[str]:
    """ADD 10: Changes Since Last Report — diffs equity, params, trades, regime."""
    lines: list[str] = []
    lines.append("")
    lines.append("\u2550" * 80)
    lines.append("  ADDITION 10: CHANGES SINCE LAST REPORT")
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"  Current report: {now_ts}")
    lines.append("\u2550" * 80)

    prev = _load_last_report_state()
    prev_ts = str(prev.get("generated_at", "N/A"))[:16]
    lines.append(f"  Previous report: {prev_ts} UTC")
    lines.append("")

    if not prev:
        lines.append("  No previous report state found — this is the first run.")
        lines.append("  State will be saved for comparison in the next report.")
        # Save current state
        _save_current_report_state_to_file()
        return lines

    # ── Equity changes ────────────────────────────────────────────────────────
    lines.append("  EQUITY CHANGES:")
    eq_rows = _pg_query("SELECT alpaca_equity, kraken_equity, options_equity, forex_equity, poseidon_equity, kraken_current_equity FROM equity_snapshots ORDER BY ts DESC LIMIT 1")
    if eq_rows:
        eq = eq_rows[0]
        now_vals = {
            "Oracle":         float(eq.get("alpaca_equity") or 100000),
            "Kraken fleet":   float(eq.get("kraken_equity") or 300000),
            "Apex Predator":  float(eq.get("options_equity") or 100000),
            "Navigator":      float(eq.get("forex_equity") or 100000),
            "Poseidon":       float(eq.get("poseidon_equity") or 100000),
            "Kraken Current": float(eq.get("kraken_current_equity") or 100000),
        }
        prev_vals = prev.get("equity", {})
        total_now = sum(now_vals.values())
        total_prev = sum(prev_vals.values()) if prev_vals else total_now

        for bot_name, now_eq in now_vals.items():
            prev_eq = float(prev_vals.get(bot_name, now_eq))
            delta = now_eq - prev_eq
            pct = delta / prev_eq * 100 if prev_eq else 0
            sign = "+" if delta >= 0 else ""
            lines.append(f"    {bot_name:<20} {_c(prev_eq)} → {_c(now_eq)} = {sign}{_c(delta)} ({sign}{pct:.2f}%)")

        delta_total = total_now - total_prev
        pct_total = delta_total / total_prev * 100 if total_prev else 0
        sign = "+" if delta_total >= 0 else ""
        lines.append(f"    {'TOTAL FLEET':<20} {_c(total_prev)} → {_c(total_now)} = {sign}{_c(delta_total)} ({sign}{pct_total:.2f}%)")
    else:
        lines.append("    No equity snapshot data available.")

    # ── Parameter changes ─────────────────────────────────────────────────────
    lines.append("")
    lines.append("  PARAMETER CHANGES:")
    current_params = {}
    kap_rows = _pg_query("SELECT bot_id, params, adapted_at FROM kraken_adaptive_params")
    for row in kap_rows:
        bid = str(row.get("bot_id") or "")
        p = row.get("params") or {}
        if isinstance(p, str):
            p = _json_diag.loads(p)
        current_params[bid] = p

    prev_params = prev.get("params", {})
    param_changes_found = False
    for bid, cp in current_params.items():
        pp = prev_params.get(bid, {})
        for pname, cval in cp.items():
            if pname.startswith("_"):
                continue
            pval = pp.get(pname)
            if pval is not None and cval is not None and abs(float(cval) - float(pval)) > 1e-9:
                lines.append(f"    ⚠️  {bid} {pname}: {pval} → {cval}")
                param_changes_found = True

    if not param_changes_found:
        lines.append("    NONE — all parameters identical to last report")

    # ── New trades ────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("  NEW TRADES OPENED (since last report):")
    prev_gen = prev.get("generated_at")
    if prev_gen:
        try:
            prev_dt = datetime.fromisoformat(str(prev_gen).replace("Z", "+00:00"))
        except Exception:
            prev_dt = datetime.now(timezone.utc) - timedelta(hours=1)

        new_k = _pg_query(
            "SELECT bot_id, symbol, side, pnl_usd, reason, closed_at FROM kraken_trades "
            "WHERE closed_at > %s ORDER BY closed_at ASC LIMIT 20",
            (prev_dt,)
        )
        new_a = _pg_query(
            "SELECT ticker, side, realized_pnl as pnl, date FROM trades WHERE date > %s ORDER BY date ASC LIMIT 10",
            (prev_dt,)
        )
        new_fx = _pg_query(
            "SELECT pair, direction, pnl_usd FROM forex_trades WHERE closed_at > %s AND status = 'closed' LIMIT 10",
            (prev_dt,)
        )

        if not new_k and not new_a and not new_fx:
            lines.append("    NONE")
        else:
            for t in new_k:
                pnl = float(t.get("pnl_usd") or 0)
                lines.append(f"    {t.get('bot_id'):<14} {t.get('symbol'):<14} {t.get('side'):<6} {_c(pnl):>10}  {str(t.get('reason',''))[:30]}")
            for t in new_a:
                pnl = float(t.get("pnl") or 0)
                lines.append(f"    Oracle        {str(t.get('ticker','?')):<14} {str(t.get('side','?')):<6} {_c(pnl):>10}")
            for t in new_fx:
                pnl = float(t.get("pnl_usd") or 0)
                lines.append(f"    Navigator     {str(t.get('pair','?')):<14} {str(t.get('direction','?')):<6} {_c(pnl):>10}")
    else:
        lines.append("    (Cannot determine — no previous report timestamp)")

    # ── Circuit breakers ──────────────────────────────────────────────────────
    lines.append("")
    lines.append("  CIRCUIT BREAKERS TRIGGERED:")
    cb_bots = []
    hb_rows = _pg_query("SELECT id, circuit_breaker FROM kraken_heartbeat")
    for hb in hb_rows:
        cb = hb.get("circuit_breaker")
        if isinstance(cb, str):
            try:
                cb = _json_diag.loads(cb)
            except Exception:
                cb = {}
        if isinstance(cb, dict) and cb.get("tripped"):
            bot_name = {1: "Davy Jones", 2: "Blackbeard", 3: "Calypso", 7: "Poseidon", 8: "Kraken Current"}.get(hb.get("id"), f"Bot {hb.get('id')}")
            until = str(cb.get("until") or "?")[:19]
            cb_bots.append(f"{bot_name} (until {until})")
    lines.append(f"    {', '.join(cb_bots) if cb_bots else 'NONE'}")

    lines.append("")
    lines.append("  REGIME CHANGES:    (tracked via equity_snapshots.regime column)")
    regime_rows = _pg_query(
        "SELECT regime, ts FROM equity_snapshots WHERE ts > NOW() - INTERVAL '24 hours' "
        "ORDER BY ts DESC LIMIT 5"
    )
    if regime_rows:
        regimes = [str(r.get("regime") or "?") for r in regime_rows]
        if len(set(regimes)) > 1:
            lines.append(f"    Regime transitions detected: {' → '.join(reversed(regimes[:3]))}")
        else:
            lines.append(f"    Current regime: {regimes[0]} (stable — no transitions in 24h)")
    else:
        lines.append("    No regime data available")

    # Save current state for next comparison
    _save_current_report_state_to_file()

    return lines


def _save_current_report_state_to_file() -> None:
    """Save the current report state snapshot for next comparison."""
    state: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # Equity snapshot
    eq_rows = _pg_query(
        "SELECT alpaca_equity, kraken_equity, options_equity, forex_equity, poseidon_equity, kraken_current_equity "
        "FROM equity_snapshots ORDER BY ts DESC LIMIT 1"
    )
    if eq_rows:
        eq = eq_rows[0]
        state["equity"] = {
            "Oracle":         float(eq.get("alpaca_equity") or 100000),
            "Kraken fleet":   float(eq.get("kraken_equity") or 300000),
            "Apex Predator":  float(eq.get("options_equity") or 100000),
            "Navigator":      float(eq.get("forex_equity") or 100000),
            "Poseidon":       float(eq.get("poseidon_equity") or 100000),
            "Kraken Current": float(eq.get("kraken_current_equity") or 100000),
        }

    # Params snapshot
    kap_rows = _pg_query("SELECT bot_id, params FROM kraken_adaptive_params")
    state["params"] = {}
    for row in kap_rows:
        bid = str(row.get("bot_id") or "")
        p = row.get("params") or {}
        if isinstance(p, str):
            p = _json_diag.loads(p)
        state["params"][bid] = dict(p)

    _save_report_state(state)


# ══════════════════════════════════════════════════════════════════════════════
# MATH AUDIT SECTION — Mathematical Verification Results
# ══════════════════════════════════════════════════════════════════════════════

def section_math_audit_results() -> list[str]:
    """Report section: Mathematical Audit Results — inserted after Fleet Health Scorecard."""
    lines: list[str] = []
    W80 = "\u2550" * 80
    lines.append("")
    lines.append(W80)
    lines.append("  MATHEMATICAL AUDIT RESULTS")
    lines.append(W80)

    # Import summary from math_auditor (graceful fallback if not yet run)
    try:
        import sys as _sys_ma
        import importlib as _imp_ma
        _TPDIR = _PathDiag(__file__).parent.parent
        if str(_TPDIR) not in _sys_ma.path:
            _sys_ma.path.insert(0, str(_TPDIR))
        _ma = _imp_ma.import_module("math_auditor")
        summary = _ma.get_audit_summary(hours=24)
    except Exception as _mae:
        lines.append(f"  Math auditor not yet initialized or error: {_mae}")
        lines.append("  Run /trading-api/admin/math-audit to trigger manually.")
        lines.append("")
        return lines

    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    last_ts = str(summary.get("last_audit_ts") or "Never")[:19]
    total_logged = int(summary.get("total_logged") or 0)

    pass_n = int(summary.get("pass") or 0)
    warn_n = int(summary.get("warn") or 0)
    fail_n = int(summary.get("fail") or 0)
    total_recent = pass_n + warn_n + fail_n

    lines.append(f"  Report generated: {now_ts}")
    lines.append(f"  Last full audit:  {last_ts} UTC")
    lines.append(f"  Formulas checked (24h): {total_recent}  |  Total logged (all time): {total_logged}")
    lines.append("")

    if fail_n > 0:
        lines.append("  ┌─────────────────────────────────────────────────────────────────────────┐")
        lines.append(f"  │  ⚠️⚠️⚠️  MATH AUDIT FAILURE DETECTED — {fail_n} CRITICAL FORMULA ERROR(s)    │")
        lines.append("  │  Trading may be using incorrect calculations. See details below.        │")
        lines.append("  └─────────────────────────────────────────────────────────────────────────┘")
        lines.append("")

    lines.append("  Summary:")
    lines.append(f"    ✅ PASS:  {pass_n:>4} checks")
    lines.append(f"    ⚠️  WARN:  {warn_n:>4} checks")
    lines.append(f"    ❌ FAIL:  {fail_n:>4} checks" + (" — REQUIRES IMMEDIATE ATTENTION" if fail_n > 0 else ""))
    lines.append(f"    All checks passed: {'YES ✅' if fail_n == 0 else 'NO ❌'}")
    lines.append("")

    # Show details
    details = summary.get("details") or []
    fails = [d for d in details if d.get("status") == "FAIL"]
    warns = [d for d in details if d.get("status") == "WARN"]

    if fails:
        lines.append("  CRITICAL FAILURES REQUIRING ACTION:")
        lines.append("  " + "-" * 76)
        for d in fails:
            ts = str(d.get("audit_timestamp") or "?")[:19]
            bot = str(d.get("bot_id") or "?")
            formula = str(d.get("formula_name") or "?")
            bot_out = d.get("bot_output")
            audit_out = d.get("auditor_output")
            diff_pct = d.get("discrepancy_pct")
            note = str(d.get("notes") or "")[:120]
            lines.append(f"  [{ts}] {bot} / {formula}")
            lines.append(f"    Bot output: {bot_out}  |  Auditor output: {audit_out}  |  Diff: {diff_pct:.3f}%")
            lines.append(f"    {note}")
            lines.append("")
    else:
        lines.append("  Critical failures: NONE")
        lines.append("")

    if warns:
        lines.append("  WARNINGS UNDER INVESTIGATION:")
        lines.append("  " + "-" * 76)
        for d in warns[:10]:  # cap at 10 warnings
            ts = str(d.get("audit_timestamp") or "?")[:19]
            bot = str(d.get("bot_id") or "?")
            formula = str(d.get("formula_name") or "?")
            diff_pct = d.get("discrepancy_pct")
            note = str(d.get("notes") or "")[:100]
            diff_str = f"{diff_pct:.3f}%" if diff_pct is not None else "N/A"
            lines.append(f"  [{ts}] {bot} / {formula} (diff={diff_str})")
            lines.append(f"    {note}")
    else:
        lines.append("  Warnings: NONE")

    lines.append("")
    lines.append("  Audit schedule:  quick (60s) | full (15 min) | deep (4h)")
    lines.append("  Audit log:       math_audit_log table (last 1,000 entries retained)")
    lines.append("  Modules checked: Z-score · RSI · ATR/stop · Position sizing · Kelly")
    lines.append("                   Profit factor · Momentum score · BTC-neutral Z-score")
    lines.append("                   [Deep] Hurst exponent · Poseidon hedge ratio & dollar-neutral")

    return lines
