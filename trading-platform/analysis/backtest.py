"""
backtest.py — Stage 6: True Price-Based Historical Backtesting
==============================================================
Runs every Sunday at 2:30 AM UTC (30 min after the Walk-Forward Optimiser).
Fully deterministic — no LLM calls.

This replaces the previous P&L replay simulator with a genuine price-based
backtester that replays OHLCV candles through the actual strategy logic.

Approach
--------
For each bot, load historical daily (1d) candles from the `historical_prices`
table and replay them chronologically. At each candle:
  1. Calculate Z-score, RSI, ATR from the rolling price window
  2. Apply the bot's entry signal logic
  3. Track open simulated positions and apply exit logic
  4. Record simulated trade outcomes

Strategy types
--------------
  mean_reversion (davy-jones):      Z-score entry @ ±1.0, exit @ |z| < 0.3,
                                    ATR × 2.5 stop, 24-candle timeout.
  mean_reversion_conservative (calypso): Z-score entry @ ±2.0, exit @ |z| < 0.3,
                                    ATR × 2.0 stop, 24-candle timeout.
  flow_sentiment (blackbeard):      EMA12/26 crossover + Z-score pullback ± 0.8,
                                    ATR × 3.0 TP, ATR × 2.0 SL, 14-candle timeout.

Fee model: 0.26% taker per side (0.52% round-trip) — Kraken Pro rate.

Pairs tested: BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD
Timeframe:    1d (daily candles — ~2 years of history from April 2024)
Warmup:       50 candles (to seed ATR/EMA/Z-score correctly)

Performance metrics
-------------------
  WR        — Win rate
  PF        — Profit factor (gross profit / gross loss)
  net_pct   — Net P&L% (summed across all simulated trades)
  max_dd    — Maximum drawdown (equity curve)
  sharpe    — Annualised Sharpe ratio (√252 × mean/std of per-trade returns)
  n_trades  — Total simulated trades

Results stored in kraken_backtest_results (PostgreSQL).
The old P&L replay result format is preserved in the table alongside new columns.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any

from loguru import logger

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── constants ─────────────────────────────────────────────────────────────────

KRAKEN_BOT_IDS = ["davy-jones", "blackbeard", "calypso"]

BACKTEST_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "AVAX/USD"]
TIMEFRAME      = "1d"
WARMUP_BARS    = 50        # candles needed before signals are valid
FEE_PER_SIDE   = 0.0026   # 0.26% Kraken Pro taker rate
ROUND_TRIP_FEE = FEE_PER_SIDE * 2

# Strategy parameters (mirror config.py per-bot profiles)
BOT_CONFIGS = {
    "davy-jones": {
        "strategy":       "mean_reversion",
        "zscore_entry":   1.0,
        "zscore_exit":    0.3,
        "atr_sl_mult":    2.5,
        "timeout_bars":   24,
        "rsi_period":     14,
        "zscore_window":  20,
        "atr_period":     14,
        "ema_fast":       None,
        "ema_slow":       None,
        "atr_tp_mult":    None,
    },
    "calypso": {
        "strategy":       "mean_reversion_conservative",
        "zscore_entry":   2.0,
        "zscore_exit":    0.3,
        "atr_sl_mult":    2.0,
        "timeout_bars":   24,
        "rsi_period":     14,
        "zscore_window":  20,
        "atr_period":     14,
        "ema_fast":       None,
        "ema_slow":       None,
        "atr_tp_mult":    None,
    },
    "blackbeard": {
        "strategy":       "flow_sentiment",
        "zscore_entry":   0.8,
        "zscore_exit":    0.0,
        "atr_sl_mult":    2.0,
        "timeout_bars":   14,
        "rsi_period":     14,
        "zscore_window":  20,
        "atr_period":     14,
        "ema_fast":       12,
        "ema_slow":       26,
        "atr_tp_mult":    3.0,
    },
}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _pg_conn():
    from db.postgres import get_conn
    return get_conn()


def _query(sql: str, params: tuple = ()) -> list[dict]:
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning(f"Backtest | DB query failed: {exc}")
        return []


def _ensure_table() -> None:
    """Create/migrate kraken_backtest_results with new true-backtest columns."""
    ddl = """
    CREATE TABLE IF NOT EXISTS kraken_backtest_results (
        id                BIGSERIAL PRIMARY KEY,
        bot_id            TEXT NOT NULL,
        run_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        n_trades          INTEGER NOT NULL DEFAULT 0,

        baseline_wr       DOUBLE PRECISION,
        baseline_pf       DOUBLE PRECISION,
        baseline_net_pct  DOUBLE PRECISION,
        baseline_max_dd   DOUBLE PRECISION,
        baseline_avg_hold DOUBLE PRECISION,

        wfo_sl_pct        DOUBLE PRECISION,
        wfo_tp_pct        DOUBLE PRECISION,
        wfo_wr            DOUBLE PRECISION,
        wfo_pf            DOUBLE PRECISION,
        wfo_net_pct       DOUBLE PRECISION,
        wfo_max_dd        DOUBLE PRECISION,
        wfo_verdict       TEXT,

        best_sl_pct       DOUBLE PRECISION,
        best_tp_pct       DOUBLE PRECISION,
        best_wr           DOUBLE PRECISION,
        best_pf           DOUBLE PRECISION,
        best_net_pct      DOUBLE PRECISION,
        best_max_dd       DOUBLE PRECISION,
        best_improvement  DOUBLE PRECISION,

        grid_results      JSONB NOT NULL DEFAULT '[]',
        regime_breakdown  JSONB NOT NULL DEFAULT '{}',
        summary           TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_backtest_bot_run
        ON kraken_backtest_results (bot_id, run_at DESC);
    """
    migrations = [
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS backtest_type TEXT DEFAULT 'pnl_replay'",
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS data_from TIMESTAMPTZ",
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS data_to TIMESTAMPTZ",
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS timeframe_used TEXT",
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS candles_used INTEGER",
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS sim_trades INTEGER",
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS sharpe_ratio DOUBLE PRECISION",
        "ALTER TABLE kraken_backtest_results ADD COLUMN IF NOT EXISTS per_pair_results JSONB DEFAULT '{}'",
    ]
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
        for stmt in migrations:
            try:
                with _pg_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(stmt)
            except Exception:
                pass
        logger.debug("Backtest | Table ensured: kraken_backtest_results")
    except Exception as exc:
        logger.error(f"Backtest | Table creation failed: {exc}")


def _persist(bot_id: str, result: dict) -> None:
    sql = """
    INSERT INTO kraken_backtest_results (
        bot_id, run_at, n_trades,
        baseline_wr, baseline_pf, baseline_net_pct, baseline_max_dd, baseline_avg_hold,
        wfo_sl_pct, wfo_tp_pct, wfo_wr, wfo_pf, wfo_net_pct, wfo_max_dd, wfo_verdict,
        best_sl_pct, best_tp_pct, best_wr, best_pf, best_net_pct, best_max_dd, best_improvement,
        grid_results, regime_breakdown, summary,
        backtest_type, data_from, data_to, timeframe_used, candles_used, sim_trades,
        sharpe_ratio, per_pair_results
    ) VALUES (
        %(bot_id)s, %(run_at)s, %(n_trades)s,
        %(baseline_wr)s, %(baseline_pf)s, %(baseline_net_pct)s, %(baseline_max_dd)s, %(baseline_avg_hold)s,
        %(wfo_sl_pct)s, %(wfo_tp_pct)s, %(wfo_wr)s, %(wfo_pf)s, %(wfo_net_pct)s, %(wfo_max_dd)s, %(wfo_verdict)s,
        %(best_sl_pct)s, %(best_tp_pct)s, %(best_wr)s, %(best_pf)s, %(best_net_pct)s, %(best_max_dd)s, %(best_improvement)s,
        %(grid_results)s, %(regime_breakdown)s, %(summary)s,
        %(backtest_type)s, %(data_from)s, %(data_to)s, %(timeframe_used)s, %(candles_used)s, %(sim_trades)s,
        %(sharpe_ratio)s, %(per_pair_results)s
    )
    """
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                row = {**result, "bot_id": bot_id, "run_at": datetime.now(timezone.utc)}
                row["grid_results"]     = json.dumps(row.get("grid_results", []))
                row["regime_breakdown"] = json.dumps(row.get("regime_breakdown", {}))
                row["per_pair_results"] = json.dumps(row.get("per_pair_results", {}))
                cur.execute(sql, row)
        logger.debug(f"Backtest | Persisted result for {bot_id}")
    except Exception as exc:
        logger.error(f"Backtest | Persist failed for {bot_id}: {exc}")


# ── candle loading ────────────────────────────────────────────────────────────

def _load_candles(pair: str, timeframe: str = "1d") -> list[dict]:
    """Load OHLCV candles for a pair from historical_prices, oldest first."""
    rows = _query(
        """
        SELECT ts, open, high, low, close, volume
        FROM   historical_prices
        WHERE  pair = %s AND timeframe = %s
        ORDER  BY ts ASC
        """,
        (pair, timeframe),
    )
    return rows


# ── indicator math ────────────────────────────────────────────────────────────

def _calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains   = [max(c, 0.0) for c in changes]
    losses  = [abs(min(c, 0.0)) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + avg_gain / avg_loss)), 2)


def _calc_zscore(closes: list[float], window: int = 20) -> float:
    if len(closes) < window + 1:
        return 0.0
    recent  = closes[-window:]
    mean    = sum(recent) / len(recent)
    var     = sum((p - mean) ** 2 for p in recent) / len(recent)
    std_dev = math.sqrt(var)
    if std_dev == 0.0:
        return 0.0
    return round((closes[-1] - mean) / std_dev, 4)


def _calc_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 8)


def _calc_ema(closes: list[float], period: int) -> float:
    """Compute EMA of the entire closes list, return last value."""
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    k   = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


# ── trade metrics ─────────────────────────────────────────────────────────────

def _compute_metrics(pnl_pcts: list[float]) -> dict:
    if not pnl_pcts:
        return {"wr": 0.0, "pf": 0.0, "net_pct": 0.0, "max_dd": 0.0, "sharpe": 0.0, "n": 0}

    wins   = [p for p in pnl_pcts if p > 0]
    losses = [p for p in pnl_pcts if p < 0]

    wr  = len(wins) / len(pnl_pcts)
    pf  = (
        sum(wins) / abs(sum(losses)) if losses else (99.99 if wins else 0.0)
    )
    pf  = round(min(pf, 99.99), 4)
    net = round(sum(pnl_pcts), 4)

    # Max drawdown via equity curve
    peak, equity, max_dd = 0.0, 0.0, 0.0
    for p in pnl_pcts:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio (annualised using daily data → sqrt(252))
    sharpe = 0.0
    if len(pnl_pcts) >= 2:
        mean_r = sum(pnl_pcts) / len(pnl_pcts)
        var_r  = sum((r - mean_r) ** 2 for r in pnl_pcts) / len(pnl_pcts)
        std_r  = math.sqrt(var_r)
        if std_r > 0:
            sharpe = round(mean_r / std_r * math.sqrt(252), 4)

    return {
        "wr":      round(wr, 4),
        "pf":      pf,
        "net_pct": net,
        "max_dd":  round(max_dd, 4),
        "sharpe":  sharpe,
        "n":       len(pnl_pcts),
    }


# ── strategy simulators ───────────────────────────────────────────────────────

def _sim_mean_reversion(
    candles: list[dict],
    zscore_entry:   float,
    zscore_exit:    float,
    atr_sl_mult:    float,
    timeout_bars:   int,
    rsi_period:     int,
    zscore_window:  int,
    atr_period:     int,
) -> list[dict]:
    """
    Simulate a mean-reversion strategy on daily candles.
    One position at a time. Returns list of simulated trade dicts.
    """
    if len(candles) < WARMUP_BARS + 1:
        return []

    opens  = [c["open"]  for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]

    trades = []
    pos = None  # None or dict with: side, entry_price, atr_stop, bars_held

    for i in range(WARMUP_BARS, len(candles)):
        close = closes[i]
        high  = highs[i]
        low   = lows[i]

        # Pass all price data up to and including the current candle.
        # Each indicator function handles its own internal windowing.
        win_closes = closes[: i + 1]
        win_highs  = highs[: i + 1]
        win_lows   = lows[: i + 1]

        z   = _calc_zscore(win_closes, zscore_window)
        atr = _calc_atr(win_highs, win_lows, win_closes, atr_period)

        if pos is not None:
            pos["bars_held"] += 1
            side  = pos["side"]
            ep    = pos["entry_price"]
            stop  = pos["atr_stop"]
            exit_reason = None
            exit_price  = close

            # ATR stop check (use high/low to see if stop was hit intraday)
            if side == "long":
                if low <= stop:
                    exit_price  = stop
                    exit_reason = "atr_stop"
                elif abs(z) < zscore_exit:
                    exit_reason = "mean_reversion"
            else:  # short
                if high >= stop:
                    exit_price  = stop
                    exit_reason = "atr_stop"
                elif abs(z) < zscore_exit:
                    exit_reason = "mean_reversion"

            if exit_reason is None and pos["bars_held"] >= timeout_bars:
                exit_reason = "timeout"

            if exit_reason:
                if side == "long":
                    raw_pnl = (exit_price - ep) / ep
                else:
                    raw_pnl = (ep - exit_price) / ep
                net_pnl = raw_pnl - ROUND_TRIP_FEE
                trades.append({
                    "pair":        pos["pair"],
                    "side":        side,
                    "entry_price": ep,
                    "exit_price":  exit_price,
                    "pnl_pct":     round(net_pnl * 100, 4),
                    "bars_held":   pos["bars_held"],
                    "reason":      exit_reason,
                    "entry_ts":    pos["entry_ts"],
                    "exit_ts":     candles[i]["ts"].isoformat() if hasattr(candles[i]["ts"], "isoformat") else str(candles[i]["ts"]),
                })
                pos = None

        # Entry logic (only when flat)
        if pos is None and atr > 0:
            if z < -zscore_entry:
                stop = close - atr * atr_sl_mult
                pos  = {
                    "pair":        "combined",
                    "side":        "long",
                    "entry_price": close,
                    "atr_stop":    stop,
                    "bars_held":   0,
                    "entry_ts":    candles[i]["ts"].isoformat() if hasattr(candles[i]["ts"], "isoformat") else str(candles[i]["ts"]),
                }
            elif z > zscore_entry:
                stop = close + atr * atr_sl_mult
                pos  = {
                    "pair":        "combined",
                    "side":        "short",
                    "entry_price": close,
                    "atr_stop":    stop,
                    "bars_held":   0,
                    "entry_ts":    candles[i]["ts"].isoformat() if hasattr(candles[i]["ts"], "isoformat") else str(candles[i]["ts"]),
                }

    return trades


def _sim_flow_sentiment(
    candles: list[dict],
    zscore_filter:  float,
    atr_sl_mult:    float,
    atr_tp_mult:    float,
    timeout_bars:   int,
    rsi_period:     int,
    zscore_window:  int,
    atr_period:     int,
    ema_fast:       int,
    ema_slow:       int,
) -> list[dict]:
    """
    Simulate a flow-sentiment / swing strategy on daily candles.
    Entry: EMA crossover (trend direction) + Z-score pullback (timing).
    Exit:  ATR TP or ATR SL or timeout.
    """
    if len(candles) < WARMUP_BARS + 1:
        return []

    opens  = [c["open"]  for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]

    trades = []
    pos = None

    for i in range(WARMUP_BARS, len(candles)):
        close = closes[i]
        high  = highs[i]
        low   = lows[i]

        win_closes = closes[: i + 1]
        win_highs  = highs[: i + 1]
        win_lows   = lows[: i + 1]

        ema_f = _calc_ema(win_closes, ema_fast)
        ema_s = _calc_ema(win_closes, ema_slow)
        z     = _calc_zscore(win_closes, zscore_window)
        atr   = _calc_atr(win_highs, win_lows, win_closes, atr_period)

        if pos is not None:
            pos["bars_held"] += 1
            side  = pos["side"]
            ep    = pos["entry_price"]
            tp    = pos["atr_tp"]
            sl    = pos["atr_sl"]
            exit_reason = None
            exit_price  = close

            if side == "long":
                if low <= sl:
                    exit_price  = sl
                    exit_reason = "atr_stop"
                elif high >= tp:
                    exit_price  = tp
                    exit_reason = "atr_tp"
            else:
                if high >= sl:
                    exit_price  = sl
                    exit_reason = "atr_stop"
                elif low <= tp:
                    exit_price  = tp
                    exit_reason = "atr_tp"

            if exit_reason is None and pos["bars_held"] >= timeout_bars:
                exit_reason = "timeout"

            if exit_reason:
                if side == "long":
                    raw_pnl = (exit_price - ep) / ep
                else:
                    raw_pnl = (ep - exit_price) / ep
                net_pnl = raw_pnl - ROUND_TRIP_FEE
                trades.append({
                    "pair":        pos["pair"],
                    "side":        side,
                    "entry_price": ep,
                    "exit_price":  exit_price,
                    "pnl_pct":     round(net_pnl * 100, 4),
                    "bars_held":   pos["bars_held"],
                    "reason":      exit_reason,
                    "entry_ts":    pos["entry_ts"],
                    "exit_ts":     candles[i]["ts"].isoformat() if hasattr(candles[i]["ts"], "isoformat") else str(candles[i]["ts"]),
                })
                pos = None

        if pos is None and atr > 0:
            bullish_trend = ema_f > ema_s
            bearish_trend = ema_f < ema_s

            if bullish_trend and z < -zscore_filter:
                tp_price = close + atr * atr_tp_mult
                sl_price = close - atr * atr_sl_mult
                pos = {
                    "pair":        "combined",
                    "side":        "long",
                    "entry_price": close,
                    "atr_tp":      tp_price,
                    "atr_sl":      sl_price,
                    "bars_held":   0,
                    "entry_ts":    candles[i]["ts"].isoformat() if hasattr(candles[i]["ts"], "isoformat") else str(candles[i]["ts"]),
                }
            elif bearish_trend and z > zscore_filter:
                tp_price = close - atr * atr_tp_mult
                sl_price = close + atr * atr_sl_mult
                pos = {
                    "pair":        "combined",
                    "side":        "short",
                    "entry_price": close,
                    "atr_tp":      tp_price,
                    "atr_sl":      sl_price,
                    "bars_held":   0,
                    "entry_ts":    candles[i]["ts"].isoformat() if hasattr(candles[i]["ts"], "isoformat") else str(candles[i]["ts"]),
                }

    return trades


# ── per-pair backtest ─────────────────────────────────────────────────────────

def _backtest_pair(pair: str, cfg: dict) -> dict:
    """Run the backtester for one pair and return metrics."""
    candles = _load_candles(pair, TIMEFRAME)
    if len(candles) < WARMUP_BARS + 10:
        return {"pair": pair, "error": f"insufficient candles ({len(candles)})"}

    strategy = cfg["strategy"]

    if strategy in ("mean_reversion", "mean_reversion_conservative"):
        trades = _sim_mean_reversion(
            candles,
            zscore_entry  = cfg["zscore_entry"],
            zscore_exit   = cfg["zscore_exit"],
            atr_sl_mult   = cfg["atr_sl_mult"],
            timeout_bars  = cfg["timeout_bars"],
            rsi_period    = cfg["rsi_period"],
            zscore_window = cfg["zscore_window"],
            atr_period    = cfg["atr_period"],
        )
    elif strategy == "flow_sentiment":
        trades = _sim_flow_sentiment(
            candles,
            zscore_filter = cfg["zscore_entry"],
            atr_sl_mult   = cfg["atr_sl_mult"],
            atr_tp_mult   = cfg["atr_tp_mult"],
            timeout_bars  = cfg["timeout_bars"],
            rsi_period    = cfg["rsi_period"],
            zscore_window = cfg["zscore_window"],
            atr_period    = cfg["atr_period"],
            ema_fast      = cfg["ema_fast"],
            ema_slow      = cfg["ema_slow"],
        )
    else:
        trades = []

    pnl_pcts = [t["pnl_pct"] for t in trades]
    metrics  = _compute_metrics(pnl_pcts)
    metrics["pair"] = pair
    metrics["candles"] = len(candles)

    # Date range from loaded candles
    if candles:
        first_ts = candles[0]["ts"]
        last_ts  = candles[-1]["ts"]
        metrics["data_from"] = first_ts.isoformat() if hasattr(first_ts, "isoformat") else str(first_ts)
        metrics["data_to"]   = last_ts.isoformat() if hasattr(last_ts, "isoformat") else str(last_ts)

    return metrics


# ── WFO integration ───────────────────────────────────────────────────────────

def _fetch_wfo_recommendation(bot_id: str) -> tuple[float | None, float | None]:
    rows = _query(
        "SELECT rec_sl_pct, rec_tp_pct FROM kraken_wfo_results "
        "WHERE bot_id = %s ORDER BY run_at DESC LIMIT 1",
        (bot_id,),
    )
    if not rows:
        return None, None
    return rows[0]["rec_sl_pct"], rows[0]["rec_tp_pct"]


# ── main backtest run ─────────────────────────────────────────────────────────

def run_backtest(bot_id: str) -> dict:
    """
    Full true price-based backtest for one bot across all 5 pairs.
    Aggregates results across all pairs and stores in DB.
    """
    _ensure_table()

    cfg = BOT_CONFIGS.get(bot_id)
    if not cfg:
        return {"error": f"Unknown bot: {bot_id}"}

    # Ensure OHLCV data is available
    try:
        from analysis.ingest_kraken_ohlcv import needs_ingest, run_ingest
        if needs_ingest():
            logger.info(f"Backtest | {bot_id}: historical_prices empty — running ingest first …")
            run_ingest()
    except Exception as exc:
        logger.warning(f"Backtest | {bot_id}: Ingest check failed (non-fatal): {exc}")

    logger.info(f"Backtest | Starting TRUE price-based backtest for {bot_id} "
                f"(strategy={cfg['strategy']}, pairs={BACKTEST_PAIRS}, timeframe={TIMEFRAME})")

    all_trades   : list[float] = []
    per_pair     : dict        = {}
    total_candles: int         = 0
    data_from    : str | None  = None
    data_to      : str | None  = None

    for pair in BACKTEST_PAIRS:
        try:
            result = _backtest_pair(pair, cfg)
            per_pair[pair] = result

            if "error" not in result:
                # Reconstruct per-trade pnl_pcts from the pair metrics (aggregated)
                # We need the raw trades — re-run to get them
                candles = _load_candles(pair, TIMEFRAME)
                strategy = cfg["strategy"]
                if strategy in ("mean_reversion", "mean_reversion_conservative"):
                    raw_trades = _sim_mean_reversion(
                        candles,
                        zscore_entry  = cfg["zscore_entry"],
                        zscore_exit   = cfg["zscore_exit"],
                        atr_sl_mult   = cfg["atr_sl_mult"],
                        timeout_bars  = cfg["timeout_bars"],
                        rsi_period    = cfg["rsi_period"],
                        zscore_window = cfg["zscore_window"],
                        atr_period    = cfg["atr_period"],
                    )
                else:
                    raw_trades = _sim_flow_sentiment(
                        candles,
                        zscore_filter = cfg["zscore_entry"],
                        atr_sl_mult   = cfg["atr_sl_mult"],
                        atr_tp_mult   = cfg["atr_tp_mult"],
                        timeout_bars  = cfg["timeout_bars"],
                        rsi_period    = cfg["rsi_period"],
                        zscore_window = cfg["zscore_window"],
                        atr_period    = cfg["atr_period"],
                        ema_fast      = cfg["ema_fast"],
                        ema_slow      = cfg["ema_slow"],
                    )

                pair_pnls = [t["pnl_pct"] for t in raw_trades]
                all_trades.extend(pair_pnls)

                total_candles += result.get("candles", 0)
                if data_from is None or result.get("data_from", "") < data_from:
                    data_from = result.get("data_from")
                if data_to is None or result.get("data_to", "") > data_to:
                    data_to = result.get("data_to")

                logger.info(
                    f"Backtest | {bot_id} — {pair}: {result['n']} simulated trades | "
                    f"WR={result['wr']*100:.1f}% PF={result['pf']:.2f} "
                    f"net={result['net_pct']:+.2f}% DD={result['max_dd']:.2f}%"
                )
            else:
                logger.warning(f"Backtest | {bot_id} — {pair}: {result['error']}")

        except Exception as exc:
            logger.error(f"Backtest | {bot_id} — {pair}: exception: {exc}")
            per_pair[pair] = {"error": str(exc)}

    if not all_trades:
        logger.warning(f"Backtest | {bot_id}: no simulated trades generated")
        return {"error": "no simulated trades — check historical_prices table"}

    # Aggregate metrics across all pairs
    agg = _compute_metrics(all_trades)

    # WFO recommendation
    wfo_sl, wfo_tp = _fetch_wfo_recommendation(bot_id)

    # Build summary
    summary = (
        f"{bot_id} TRUE PRICE BACKTEST | strategy={cfg['strategy']} | "
        f"timeframe={TIMEFRAME} | pairs={len(BACKTEST_PAIRS)} | "
        f"period={data_from or '?'} → {data_to or '?'} | "
        f"simulated trades={len(all_trades)} | "
        f"WR={agg['wr']*100:.1f}% PF={agg['pf']:.2f} "
        f"net={agg['net_pct']:+.2f}% maxDD={agg['max_dd']:.2f}% "
        f"Sharpe={agg['sharpe']:.2f}"
    )
    logger.info(f"Backtest | {summary}")

    result = {
        "n_trades":         len(all_trades),
        "baseline_wr":      agg["wr"],
        "baseline_pf":      agg["pf"],
        "baseline_net_pct": agg["net_pct"],
        "baseline_max_dd":  agg["max_dd"],
        "baseline_avg_hold": None,
        "wfo_sl_pct":  wfo_sl,
        "wfo_tp_pct":  wfo_tp,
        "wfo_wr":      None,
        "wfo_pf":      None,
        "wfo_net_pct": None,
        "wfo_max_dd":  None,
        "wfo_verdict": "N/A (WFO recs apply to live params, not price-based simulation)",
        "best_sl_pct":    None,
        "best_tp_pct":    None,
        "best_wr":        None,
        "best_pf":        None,
        "best_net_pct":   None,
        "best_max_dd":    None,
        "best_improvement": None,
        "grid_results":   [],
        "regime_breakdown": {},
        "summary":        summary,
        "backtest_type":  "price_replay",
        "data_from":      data_from,
        "data_to":        data_to,
        "timeframe_used": TIMEFRAME,
        "candles_used":   total_candles,
        "sim_trades":     len(all_trades),
        "sharpe_ratio":   agg["sharpe"],
        "per_pair_results": per_pair,
    }
    return result


def run_all_bots() -> dict[str, dict]:
    """Run the full true price-based backtest for all three Kraken bots."""
    results: dict[str, dict] = {}
    for bot_id in KRAKEN_BOT_IDS:
        try:
            r = run_backtest(bot_id)
            results[bot_id] = r
            if "error" not in r:
                _persist(bot_id, r)
        except Exception as exc:
            logger.error(f"Backtest | {bot_id} failed: {exc}")
            results[bot_id] = {"error": str(exc)}
    return results


def get_latest_result(bot_id: str) -> dict | None:
    """Fetch the most recent backtest result for one bot."""
    rows = _query(
        """
        SELECT *
        FROM   kraken_backtest_results
        WHERE  bot_id = %s
        ORDER  BY run_at DESC
        LIMIT  1
        """,
        (bot_id,),
    )
    return rows[0] if rows else None
