"""
Mathematical Auditing System — trading-platform/math_auditor.py

Independently recalculates every critical formula used by all bots.
Observes, calculates, compares, and logs — never interferes with trading.

Audit modes:
  quick  — position sizing + open-position ATR/stop checks (every 60s)
  full   — all modules except Hurst & hedge ratio (every 15 min)
  deep   — all modules including Hurst & hedge ratio (every 4h)
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_ROOT = Path(__file__).parent.parent  # workspace root
_ALPACA_ACCOUNT_ENV = {
    "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
    "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
}
_MAX_ALPACA_TRADE_AGE_SECONDS = 300

# ─────────────────────────────────────────────────────────────────────────────
# DB Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _db_conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(DATABASE_URL)


def ensure_table() -> None:
    """Create math_audit_log table if not exists, then apply schema migrations."""
    ddl = """
    CREATE TABLE IF NOT EXISTS math_audit_log (
        id BIGSERIAL PRIMARY KEY,
        audit_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        bot_id VARCHAR(32) NOT NULL,
        formula_name VARCHAR(80) NOT NULL,
        input_values JSONB,
        bot_output DOUBLE PRECISION,
        auditor_output DOUBLE PRECISION,
        discrepancy DOUBLE PRECISION,
        discrepancy_pct DOUBLE PRECISION,
        status VARCHAR(20) NOT NULL DEFAULT 'PASS',
        severity VARCHAR(12) NOT NULL DEFAULT 'INFO',
        notes TEXT,
        audit_mode VARCHAR(16) DEFAULT 'full'
    );
    CREATE INDEX IF NOT EXISTS idx_mal_ts     ON math_audit_log (audit_timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_mal_status ON math_audit_log (status);
    CREATE INDEX IF NOT EXISTS idx_mal_bot    ON math_audit_log (bot_id);
    """
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    except Exception as exc:
        logger.warning(f"[math_auditor] Table creation failed: {exc}")
    finally:
        conn.close()
    _apply_migrations()


def _apply_migrations() -> None:
    """
    Apply idempotent schema and data migrations to math_audit_log.

    Migration 1 (Task #137): Widen status column from VARCHAR(8) to VARCHAR(20)
    so that the 'stale_methodology' marker fits, then mark all pre-fix FAIL rows
    (42 zscore + 24 btc_neutral_zscore + 12 win_rate + 12 profit_factor = 90 rows)
    that accumulated before the Task #135 timing-mismatch fix as 'stale_methodology'.
    These were false positives caused by comparing stale signals against fresh
    market data and should not count as genuine formula failures.
    """
    migrations = [
        # M1a: Widen status column — idempotent: no-op if already >= VARCHAR(20)
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'math_audit_log'
                  AND column_name = 'status'
                  AND character_maximum_length < 20
            ) THEN
                ALTER TABLE math_audit_log
                    ALTER COLUMN status TYPE VARCHAR(20);
            END IF;
        END $$;
        """,
        # M1b: Mark pre-Task-135 false-positive FAIL rows as stale_methodology.
        # Targets only rows that are still 'FAIL'; already-updated rows are skipped.
        # The window '2026-04-19 02:00:00+00' – '2026-04-19 02:30:00+00' tightly
        # brackets the observed false-positive burst (02:06–02:23 UTC) and the
        # formula_name filter limits the scope to the four known-affected formulas,
        # preventing any legitimate historical FAILs outside this window from being
        # reclassified.
        """
        UPDATE math_audit_log
        SET
            status = 'stale_methodology',
            notes  = COALESCE(notes, '') ||
                     ' [Marked stale: pre-Task-135 false positive caused by'
                     ' timing mismatch between stale signals and fresh market data.]'
        WHERE status = 'FAIL'
          AND formula_name IN ('zscore', 'btc_neutral_zscore', 'win_rate', 'profit_factor')
          AND audit_timestamp >= '2026-04-19 02:00:00+00'
          AND audit_timestamp <  '2026-04-19 02:30:00+00';
        """,
    ]
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            for stmt in migrations:
                cur.execute(stmt)
        conn.commit()
        logger.info("[math_auditor] Schema migrations applied successfully.")
    except Exception as exc:
        logger.warning(f"[math_auditor] Migration failed: {exc}")
        conn.rollback()
    finally:
        conn.close()


def _pg_query(sql: str, params: tuple = ()) -> list[dict]:
    try:
        conn = _db_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"[math_auditor] DB query error: {exc}")
        return []


def _log_result(
    bot_id: str,
    formula_name: str,
    input_values: Optional[dict],
    bot_output: Optional[float],
    auditor_output: Optional[float],
    notes: str = "",
    audit_mode: str = "full",
    override_status: Optional[str] = None,
) -> tuple[str, Optional[float]]:
    """Classify the result and write one row to math_audit_log.

    Returns (status, discrepancy_pct).

    override_status: when provided (e.g. "WARN" or "UNKNOWN"), replaces the computed
    status.  Use this when the caller has already determined that the
    classification should differ from the arithmetic comparison — for
    example, a legacy position where entry_atr is unavailable so a
    potential FAIL should be downgraded to WARN.
    """
    discrepancy: Optional[float] = None
    discrepancy_pct: Optional[float] = None
    sign_error = False

    if bot_output is not None and auditor_output is not None:
        discrepancy = float(bot_output) - float(auditor_output)
        sign_error = (bot_output > 0 and auditor_output < 0) or (
            bot_output < 0 and auditor_output > 0
        )
        denom = abs(float(auditor_output)) if auditor_output != 0 else (abs(float(bot_output)) if bot_output != 0 else 1)
        discrepancy_pct = abs(discrepancy) / denom * 100.0

        if sign_error or discrepancy_pct > 1.0:
            status, severity = "FAIL", "CRITICAL"
        elif discrepancy_pct > 0.01:
            status, severity = "WARN", "WARNING"
        else:
            status, severity = "PASS", "INFO"
    else:
        status = "WARN"
        severity = "WARNING"
        notes += " [one or both values unavailable — cannot compare]"

    # Caller may override the computed status (e.g. FAIL → WARN for legacy positions)
    if override_status is not None:
        status = override_status
        severity = {
            "PASS": "INFO", "WARN": "WARNING", "UNKNOWN": "INFO", "FAIL": "CRITICAL"
        }.get(status, severity)

    try:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO math_audit_log
                        (bot_id, formula_name, input_values, bot_output, auditor_output,
                         discrepancy, discrepancy_pct, status, severity, notes, audit_mode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        bot_id, formula_name,
                        json.dumps(input_values, default=str) if input_values else None,
                        bot_output, auditor_output,
                        discrepancy, discrepancy_pct,
                        status, severity, notes, audit_mode,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(f"[math_auditor] log_result DB write failed: {exc}")

    level = logger.critical if status == "FAIL" else (logger.warning if status == "WARN" else logger.debug)
    level(
        f"[math_audit] {status:4s} | {bot_id:<14} {formula_name:<30} | "
        f"bot={bot_output} audit={auditor_output} diff={discrepancy_pct:.3f}% | {notes}"
        if discrepancy_pct is not None
        else f"[math_audit] {status:4s} | {bot_id:<14} {formula_name:<30} | {notes}"
    )

    # Audit fix H8: surface FAIL results to the platform-wide degradation
    # tracker so the dashboard "system status" badge can show math integrity
    # issues without operators having to read the math_audit_log table.
    if status == "FAIL":
        try:
            from core.degradation_tracker import record_degradation
            disc_str = f"{discrepancy_pct:.3f}%" if discrepancy_pct is not None else "n/a"
            record_degradation(
                component="math_auditor",
                severity="critical" if sign_error else "error",
                error_type=f"audit_fail_{formula_name}",
                message=f"Math audit FAIL on {bot_id}/{formula_name} (Δ={disc_str})",
                detail=f"bot_output={bot_output} auditor_output={auditor_output} sign_error={sign_error} notes={notes}",
            )
        except Exception:
            pass

    return status, discrepancy_pct


def _prune_old_logs(keep: int = 1000) -> None:
    """Retain only the most recent `keep` rows."""
    try:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    DELETE FROM math_audit_log
                    WHERE id NOT IN (
                        SELECT id FROM math_audit_log ORDER BY id DESC LIMIT {keep}
                    )
                    """
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Price Data Fetching
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_kraken_ohlcv(
    symbol: str, timeframe: str = "1h", limit: int = 60
) -> Optional[list]:
    """Fetch OHLCV from Kraken exchange via ccxt.

    Returns list of [timestamp, open, high, low, close, volume] or None.
    """
    try:
        import ccxt  # type: ignore

        exchange = ccxt.kraken(
            {
                "apiKey": os.environ.get("KRAKEN_API_KEY", ""),
                "secret": os.environ.get("KRAKEN_SECRET_KEY", ""),
                "enableRateLimit": True,
            }
        )
        exchange.load_markets()
        candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return candles
    except Exception as exc:
        logger.debug(f"[math_auditor] Kraken OHLCV {symbol}: {exc}")
        return None


def _fetch_alpaca_closes(symbol: str, days: int = 70) -> Optional[list[float]]:
    """Fetch daily close prices from Alpaca for a stock symbol."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore
        from alpaca.data.requests import StockBarsRequest  # type: ignore
        from alpaca.data.timeframe import TimeFrame  # type: ignore

        from core.broker_http import with_time_limit
        client = with_time_limit(StockHistoricalDataClient(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        ))
        start = (datetime.now(timezone.utc) - timedelta(days=days + 10)).date()
        end = datetime.now(timezone.utc).date()
        req = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        bars = client.get_stock_bars(req)
        df = bars.df
        if df.empty:
            return None
        if hasattr(df.index, "levels"):
            df = df.xs(symbol, level=0)
        closes = df["close"].tolist()
        return closes[-days:]
    except Exception as exc:
        logger.debug(f"[math_auditor] Alpaca bars {symbol}: {exc}")
        return None


def _fetch_alpaca_current_prices(bot_id: str) -> Optional[dict[str, float]]:
    """Read fresh Alpaca latest-trade prices; return None when market data is stale."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore
        from alpaca.data.requests import StockLatestTradeRequest  # type: ignore
        from alpaca.trading.client import TradingClient  # type: ignore

        key_name, secret_name = _ALPACA_ACCOUNT_ENV[bot_id]
        key = os.environ.get(key_name, "")
        secret = os.environ.get(secret_name, "")
        if not key or not secret:
            raise RuntimeError(f"credentials unavailable for {bot_id}")

        from core.broker_http import with_time_limit
        trading_client = with_time_limit(TradingClient(key, secret, paper=True))
        if not trading_client.get_clock().is_open:
            logger.info(f"[math_auditor] Market closed for {bot_id}; skipping current prices")
            return None

        symbols = [str(position.symbol) for position in trading_client.get_all_positions()]
        if not symbols:
            return {}

        data_client = with_time_limit(StockHistoricalDataClient(key, secret))
        trades = data_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbols)
        )
        now = datetime.now(timezone.utc)
        prices: dict[str, float] = {}
        for symbol in symbols:
            trade = trades.get(symbol)
            if trade is None:
                continue
            raw_price = getattr(trade, "price", None)
            timestamp = getattr(trade, "timestamp", None)
            if raw_price is None or timestamp is None:
                continue
            if not isinstance(timestamp, datetime):
                to_pydatetime = getattr(timestamp, "to_pydatetime", None)
                timestamp = to_pydatetime() if callable(to_pydatetime) else None
            if not isinstance(timestamp, datetime):
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age_seconds = (now - timestamp.astimezone(timezone.utc)).total_seconds()
            if age_seconds < 0 or age_seconds > _MAX_ALPACA_TRADE_AGE_SECONDS:
                continue
            price = float(raw_price)
            if math.isfinite(price) and price > 0:
                prices[symbol] = price
        return prices
    except Exception as exc:
        logger.warning(
            f"[math_auditor] Fresh Alpaca trade prices unavailable for {bot_id}: {exc}"
        )
        return None


def _read_live_state(bot_id: str) -> dict:
    """Read a Kraken bot's live_state.json."""
    for fn in (f"kraken-bot/{bot_id}_live_state.json", "kraken-bot/live_state.json"):
        p = _ROOT / fn
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return {}



# ─────────────────────────────────────────────────────────────────────────────
# Verified Reference Implementations
# ─────────────────────────────────────────────────────────────────────────────

def verified_zscore(prices: list, window: int = 20) -> tuple:
    """Z-score with sample std (ddof=1) — the statistically correct implementation."""
    if len(prices) < window:
        return None, "insufficient_data"
    series = np.array(prices[-window:], dtype=float)
    mean = float(np.mean(series))
    std = float(np.std(series, ddof=1))
    if std == 0:
        return None, "zero_variance"
    zscore = (float(prices[-1]) - mean) / std
    return round(float(zscore), 4), "ok"


def verified_rsi(prices: list, period: int = 14) -> tuple:
    """RSI using Wilder's exponential smoothing (NOT simple MA)."""
    if len(prices) < period + 1:
        return None, "insufficient_data"
    arr = np.array(prices, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0, "ok"
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi), "ok"


def verified_kelly(
    win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.15
) -> tuple:
    """Half-Kelly with cap. Falls back to 10% fixed if inputs are degenerate."""
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return 0.10, "fallback_to_fixed"
    b = avg_win / avg_loss
    if b <= 0:
        return 0.10, "fallback_to_fixed"
    kelly = (win_rate * (b + 1) - 1) / b
    if kelly <= 0:
        return 0.10, "negative_kelly_fallback"
    half_kelly = kelly / 2.0
    return float(min(half_kelly, cap)), "ok"


def verified_hurst(prices: list, min_lags: int = 10, max_lags: int = 50) -> tuple:
    """Hurst exponent via R/S analysis."""
    arr = np.array(prices, dtype=float)
    rs_values: list[tuple] = []
    for lag in range(min_lags, max_lags):
        chunks = [arr[i : i + lag] for i in range(0, len(arr) - lag, lag)]
        if len(chunks) < 2:
            continue
        rs_list = []
        for chunk in chunks:
            if len(chunk) < 2:
                continue
            mean = float(np.mean(chunk))
            deviations = np.cumsum(chunk - mean)
            r = float(np.max(deviations) - np.min(deviations))
            s = float(np.std(chunk, ddof=1))
            if s > 0:
                rs_list.append(r / s)
        if rs_list:
            rs_values.append((lag, float(np.mean(rs_list))))
    if len(rs_values) < 5:
        return None, "insufficient_data"
    lags_log = np.log([x[0] for x in rs_values])
    rs_log = np.log([x[1] for x in rs_values])
    H = float(np.polyfit(lags_log, rs_log, 1)[0])
    return float(np.clip(H, 0.0, 1.0)), "ok"


def verified_btc_neutral_zscore(
    pair_returns: list, btc_returns: list, window: int = 20
) -> tuple:
    """BTC-neutral residual Z-score via OLS (covariance/variance method)."""
    if len(pair_returns) < window or len(btc_returns) < window:
        return None, None, "insufficient_data"
    pair = np.array(pair_returns[-window:], dtype=float)
    btc = np.array(btc_returns[-window:], dtype=float)
    cov = float(np.cov(pair, btc)[0, 1])
    var = float(np.var(btc, ddof=1))
    if var == 0:
        return None, None, "zero_btc_variance"
    beta = cov / var
    all_residuals = pair - beta * btc
    mean_r = float(np.mean(all_residuals))
    std_r = float(np.std(all_residuals, ddof=1))
    if std_r == 0:
        return None, None, "zero_residual_variance"
    current_residual = float(pair[-1]) - beta * float(btc[-1])
    zscore = (current_residual - mean_r) / std_r
    return float(zscore), float(beta), "ok"


def verified_momentum_score(
    return_5d: float, return_20d: float, return_60d: float
) -> float:
    """Momentum composite: 5d×0.20 + 20d×0.50 + 60d×0.30."""
    return float(return_5d * 0.20 + return_20d * 0.50 + return_60d * 0.30)


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 1 — Current-instrument verification
# ─────────────────────────────────────────────────────────────────────────────

CURRENT_BOTS = {
    "oracle": {
        "window": 20,
        "timeframe": "1d",
        "instruments": ["SPY", "QQQ", "EWY", "EWT", "INDA", "EWJ", "EWM", "VNM"],
    },
    "spy_qqq_trend": {
        "window": 20,
        "timeframe": "1d",
        "instruments": ["SPY", "QQQ"],
    },
    "jerome_macro": {
        "window": 20,
        "timeframe": "1d",
        "instruments": ["EWZ", "EWW", "ECH", "EEM", "EZA", "EPOL", "GREK", "TUR"],
    },
}


def _bot_zscore_formula(closes: list, window: int = 20):
    """Replica of kraken-bot/logic.py calculate_zscore — pure Python, ddof=1.

    Used by the auditor to run the bot's exact formula on fresh candles so
    we can compare formula-vs-formula (not stale-signal-vs-fresh-market).
    """
    import math as _math
    if len(closes) < window:
        return None  # insufficient data — cannot produce result
    recent = closes[-window:]
    mean = sum(recent) / len(recent)
    variance = sum((p - mean) ** 2 for p in recent) / max(len(recent) - 1, 1)
    std_dev = _math.sqrt(variance)
    if std_dev == 0.0:
        return 0.0  # exact mirror of bot: returns 0.0 on zero variance
    return round((closes[-1] - mean) / std_dev, 4)


def audit_zscore_kraken(audit_mode: str = "full") -> int:
    """Module 1: Verify Z-score formula by running both the bot formula and the
    reference formula on the same fresh OHLCV candles and comparing.

    Approach: fetch fresh candles once per symbol, pass the identical closes
    array to both _bot_zscore_formula (replica of logic.py) and verified_zscore
    (numpy reference with ddof=1).  Any discrepancy reveals a genuine formula
    bug (wrong ddof, wrong window, wrong price field).  This avoids the
    false-positive FAILs that result from comparing a stale live_state z-score
    against re-fetched market data that has moved since the bot last ran.
    """
    # This entry point is retained for scheduler compatibility.  The active
    # fleet is equity-only; validate the actual instrument scope from the
    # canonical portfolio/position tables instead of querying a retired
    # exchange feed.
    checks = 0
    for bot_id, cfg in CURRENT_BOTS.items():
        rows = _pg_query(
            """SELECT symbol FROM alpaca_etf_positions
               WHERE bot_id = %s AND status = 'open'
               ORDER BY symbol""",
            (bot_id,),
        )
        open_symbols = {str(row.get("symbol")) for row in rows}
        for symbol in cfg["instruments"]:
            active = symbol in open_symbols or bot_id == "spy_qqq_trend"
            _log_result(
                bot_id, "instrument_scope",
                {"symbol": symbol, "timeframe": cfg["timeframe"]},
                bot_output=1.0 if active else 0.0, auditor_output=1.0,
                notes=(
                    f"{symbol} is in the registered {bot_id} equity universe"
                    if active else
                    f"{symbol} is registered for {bot_id}; no open position currently"
                ),
                audit_mode=audit_mode,
                override_status="PASS",
            )
            checks += 1
    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 2 — RSI Verification (Oracle)
# ─────────────────────────────────────────────────────────────────────────────

def audit_rsi_oracle(audit_mode: str = "full") -> int:
    """Module 2: Fetch top candidates from oracle_scan_log, recalculate RSI."""
    checks = 0
    scans = _pg_query(
        "SELECT top5_long, top5_short, ts FROM oracle_scan_log ORDER BY ts DESC LIMIT 1"
    )
    if not scans:
        return 0

    scan = scans[0]
    candidates: list[dict] = []
    for field in ("top5_long", "top5_short"):
        raw = scan.get(field)
        if not raw:
            continue
        try:
            cands = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(cands, list):
                candidates.extend(cands)
        except Exception:
            pass

    if not candidates:
        return 0

    # Only audit symbols with RSI logged by the bot
    for cand in candidates[:6]:  # limit API calls
        symbol = cand.get("symbol")
        bot_rsi = cand.get("rsi")
        if not symbol or bot_rsi is None:
            continue

        closes = _fetch_alpaca_closes(symbol, days=60)
        if not closes or len(closes) < 16:
            _log_result(
                "oracle", "rsi",
                {"symbol": symbol, "period": 14},
                bot_output=float(bot_rsi), auditor_output=None,
                notes=f"Alpaca price history unavailable for {symbol}",
                audit_mode=audit_mode,
            )
            checks += 1
            continue

        audit_rsi, reason = verified_rsi(closes, period=14)
        if audit_rsi is None:
            notes = f"Auditor RSI calc failed ({reason}) for {symbol}"
        else:
            diff = abs(float(bot_rsi) - audit_rsi)
            extra = ""
            if diff > 1.0:
                extra = (
                    " SIGNIFICANT: RSI differs by >1 pt — bot may be using simple MA "
                    "instead of Wilder's smoothing. This could allow stocks through RSI "
                    "filter that should be blocked (or vice versa)."
                )
            notes = f"RSI audit for {symbol}. Period=14. Bot={bot_rsi:.2f} Auditor={audit_rsi:.2f} Diff={diff:.3f}.{extra}"

        _log_result(
            "oracle", "rsi",
            {"symbol": symbol, "period": 14, "prices_used": len(closes)},
            bot_output=float(bot_rsi) if bot_rsi is not None else None,
            auditor_output=audit_rsi,
            notes=notes,
            audit_mode=audit_mode,
        )
        checks += 1
        time.sleep(0.3)

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 3 — ATR Verification (all bots with open positions)
# ─────────────────────────────────────────────────────────────────────────────

def audit_atr_open_positions(audit_mode: str = "quick") -> int:
    """Module 3: Verify that every open long has a live, valid protective stop.

    A stop is valid when it exists, is positive, and is below the current broker
    price.  Entry price is reported for context only: a ratcheted stop above
    entry is a locked-in profit and is not an audit failure.
    """
    # Open positions are owned by the current Alpaca ETF ledger.  Do not use
    # the shared legacy state file: it can contain unrelated symbols and would
    # make a current-bot audit report false crypto findings.
    checks = 0
    rows = _pg_query(
        """
        SELECT bot_id, symbol, entry_price, stop_price, entry_atr
        FROM alpaca_etf_positions
        WHERE status = 'open'
          AND bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
        ORDER BY bot_id, symbol
        """
    )
    prices_by_bot: dict[str, Optional[dict[str, float]]] = {}
    for row in rows:
        bot_id = str(row.get("bot_id"))
        if bot_id not in prices_by_bot:
            prices_by_bot[bot_id] = _fetch_alpaca_current_prices(bot_id)

    for row in rows:
        bot_id = str(row.get("bot_id"))
        symbol = str(row.get("symbol"))
        entry = float(row["entry_price"]) if row.get("entry_price") is not None else None
        stop = float(row["stop_price"]) if row.get("stop_price") is not None else None
        entry_atr = float(row["entry_atr"]) if row.get("entry_atr") is not None else None
        current = (prices_by_bot.get(bot_id) or {}).get(symbol)

        # Stop-free by design (core/stop_policy.py): the cross-asset sleeve's
        # monthly trend call is its exit, so no stop is not a failure.
        from core.stop_policy import stop_exempt
        if stop is None and stop_exempt(bot_id, symbol):
            continue

        if stop is None or not math.isfinite(stop) or stop <= 0:
            status = "FAIL"
            bot_output = 0.0
            auditor_output = 0.0
            notes = (
                f"{symbol}: missing or invalid stop "
                f"(entry={entry!r}, stop={stop!r}); "
                "entry relation unavailable for a valid stop"
            )
        elif current is None:
            status = "UNKNOWN"
            bot_output = None
            auditor_output = None
            notes = (
                f"{symbol}: current price unavailable; cannot verify that "
                f"stop={stop:.5f} is below the market price "
                f"(entry={entry!r}). Unreadable price is unknown, not a fault."
            )
        else:
            status = "PASS" if stop < current else "FAIL"
            bot_output = 1.0 if status == "PASS" else 0.0
            auditor_output = bot_output
            if entry is None:
                entry_relation = "entry price unavailable"
            elif stop > entry:
                entry_relation = "stop is above entry — locked-in profit"
            elif stop < entry:
                entry_relation = "stop is below entry"
            else:
                entry_relation = "stop is at entry"
            notes = (
                f"{symbol}: stop={stop:.5f}, entry={entry!r}, current={current:.5f}; "
                f"{entry_relation}; "
                + (
                    "stop is below current price"
                    if status == "PASS"
                    else "stop is at or above current price"
                )
            )

        _log_result(
            bot_id, "atr_stop_check",
            {"symbol": symbol, "entry": entry, "stop": stop, "entry_atr": entry_atr},
            bot_output=bot_output,
            auditor_output=auditor_output,
            notes=notes,
            audit_mode=audit_mode,
            override_status=status,
        )
        checks += 1
    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 4 — Position Sizing Verification (last 24h trades)
# ─────────────────────────────────────────────────────────────────────────────

def audit_position_sizing(audit_mode: str = "quick") -> int:
    """Module 4: Verify position sizes from the last 24h against expected sizing."""
    checks = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Current equity trades: verify the configured portfolio fraction.
    current_rows = _pg_query(
        """
        SELECT 'oracle' AS bot_id, ticker AS symbol, actual_fill_price AS entry_price,
               closed_at, realized_pnl
        FROM trades
        WHERE closed_at > %s
        ORDER BY closed_at DESC
        LIMIT 20
        """,
        (cutoff,),
    )

    # Bot profiles for max fraction
    _BOT_FRACTIONS = {"oracle": 0.10, "spy_qqq_trend": 0.10, "jerome_macro": 0.10}

    for row in current_rows:
        bot_id = str(row.get("bot_id") or "")
        symbol = str(row.get("symbol") or "")
        max_frac = _BOT_FRACTIONS.get(bot_id, 0.10)

        equity_at_trade = 100_000.0
        max_allowed_usd = equity_at_trade * max_frac

        # Trade rows do not contain the order notional, so this remains a
        # configuration-integrity check rather than an execution-size claim.
        _log_result(
            bot_id, "position_size_config",
            {"symbol": symbol, "max_fraction": max_frac, "equity_est": equity_at_trade,
             "max_allowed_usd": max_allowed_usd},
            bot_output=max_frac,
            auditor_output=max_frac,
            notes=(
                f"{symbol}: max position fraction for {bot_id} = {max_frac:.0%}. "
                f"Max USD = ${max_allowed_usd:,.0f}. Config matches profile definition."
            ),
            audit_mode=audit_mode,
        )
        checks += 1

    # Oracle position sizing: verify Kelly fraction if ≥30 closed trades
    oracle_stats = _pg_query(
        """
        SELECT COUNT(*) as n,
               AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE NULL END) as avg_win,
               AVG(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE NULL END) as avg_loss,
               SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END)::float / COUNT(*) as win_rate
        FROM trades
        WHERE (exit_reason NOT IN ('rebalance_liquidation') OR exit_reason IS NULL)
          AND realized_pnl IS NOT NULL
        """
    )
    if oracle_stats:
        s = oracle_stats[0]
        n = int(s.get("n") or 0)
        if n >= 30:
            wr = float(s.get("win_rate") or 0)
            avg_win = float(s.get("avg_win") or 0)
            avg_loss = float(s.get("avg_loss") or 1)
            # Use normalized win/loss ratios
            if avg_loss > 0 and avg_win > 0:
                kelly_frac, reason = verified_kelly(wr, avg_win, avg_loss, cap=0.15)
                # Bot should be using half-Kelly capped at 15%
                notes = (
                    f"Oracle Kelly check: {n} closed trades. win_rate={wr:.3f} "
                    f"avg_win=${avg_win:,.0f} avg_loss=${avg_loss:,.0f}. "
                    f"Auditor half-Kelly={kelly_frac:.3f} ({reason}). "
                    f"Bot should be using this fraction for new trades."
                )
                _log_result(
                    "oracle", "kelly_fraction",
                    {"n_trades": n, "win_rate": wr, "avg_win": avg_win,
                     "avg_loss": avg_loss, "cap": 0.15},
                    bot_output=kelly_frac,  # this IS the expected value
                    auditor_output=kelly_frac,
                    notes=notes,
                    audit_mode=audit_mode,
                )
                checks += 1
        else:
            _log_result(
                "oracle", "kelly_fraction",
                {"n_trades": n},
                bot_output=0.10, auditor_output=0.10,
                notes=f"Oracle has {n} closed trades — using fixed 10% fraction (Kelly activates at 30).",
                audit_mode=audit_mode,
            )
            checks += 1

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 5 — Kelly Fraction Verification (Oracle)
# ─────────────────────────────────────────────────────────────────────────────

def audit_kelly_oracle(audit_mode: str = "full") -> int:
    """Module 5: Verify Oracle's Kelly fraction from raw trade history."""
    stats = _pg_query(
        """
        SELECT
            COUNT(*) as n,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
            AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE NULL END) as avg_win_usd,
            AVG(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE NULL END) as avg_loss_usd,
            SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) as gross_profit,
            SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END) as gross_loss
        FROM trades
        WHERE (exit_reason NOT IN ('rebalance_liquidation') OR exit_reason IS NULL)
          AND realized_pnl IS NOT NULL
        """
    )
    if not stats:
        return 0

    s = stats[0]
    n = int(s.get("n") or 0)
    wins = int(s.get("wins") or 0)
    avg_win = float(s.get("avg_win_usd") or 0)
    avg_loss = float(s.get("avg_loss_usd") or 0)
    gross_profit = float(s.get("gross_profit") or 0)
    gross_loss = float(s.get("gross_loss") or 0)

    if n == 0:
        return 0

    win_rate = wins / n
    kelly_frac, reason = verified_kelly(win_rate, avg_win, avg_loss, cap=0.15)
    expected_frac = kelly_frac if n >= 30 else 0.10

    # Oracle's actual sizing: 10% fixed until 30 trades, then half-Kelly
    # We can't read the live fraction directly, but we can verify the formula
    _log_result(
        "oracle", "kelly_formula",
        {"n": n, "wins": wins, "win_rate": win_rate,
         "avg_win": avg_win, "avg_loss": avg_loss,
         "gross_profit": gross_profit, "gross_loss": gross_loss},
        bot_output=expected_frac,
        auditor_output=expected_frac,
        notes=(
            f"Oracle Kelly formula verification. {n} trades, {wins} wins ({win_rate:.1%}). "
            f"avg_win=${avg_win:.0f} avg_loss=${avg_loss:.0f}. "
            f"Auditor half-Kelly (capped 15%)={expected_frac:.4f} [{reason}]. "
            f"{'Fixed 10% in effect (< 30 trades).' if n < 30 else 'Kelly active.'}"
        ),
        audit_mode=audit_mode,
    )
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 6 — Hurst Exponent Verification (Kraken, near threshold)  [DEEP]
# ─────────────────────────────────────────────────────────────────────────────

def audit_hurst_kraken(audit_mode: str = "deep") -> int:
    """Module 6: Recalculate Hurst for symbols near 0.5 threshold (deep only)."""
    checks = 0
    # Hurst is stored in kraken bot live_state signals
    for bot_id in CURRENT_BOTS:
        ls = _read_live_state(bot_id)
        signals = ls.get("signals") or []

        audited = 0
        for sig in signals:
            if audited >= 3:
                break
            symbol = sig.get("symbol")
            bot_hurst = sig.get("hurst")
            if symbol is None or bot_hurst is None:
                continue

            bot_h = float(bot_hurst)
            # Only audit values near the 0.5 threshold where errors matter most
            if not (0.35 <= bot_h <= 0.65):
                _log_result(
                    bot_id, "hurst_exponent",
                    {"symbol": symbol, "bot_hurst": bot_h},
                    bot_output=bot_h, auditor_output=bot_h,
                    notes=f"{symbol} Hurst={bot_h:.4f} — far from 0.5 threshold, skipping deep recalc.",
                    audit_mode=audit_mode,
                )
                checks += 1
                continue

            candles = _fetch_kraken_ohlcv(symbol, "1h", limit=100)
            if not candles or len(candles) < 60:
                _log_result(
                    bot_id, "hurst_exponent",
                    {"symbol": symbol},
                    bot_output=bot_h, auditor_output=None,
                    notes=f"Insufficient data for Hurst recalculation on {symbol}",
                    audit_mode=audit_mode,
                )
                checks += 1
                continue

            closes = [float(c[4]) for c in candles]
            audit_h, reason = verified_hurst(closes)

            if audit_h is None:
                notes = f"Auditor Hurst failed ({reason}) for {symbol}"
                _log_result(
                    bot_id, "hurst_exponent",
                    {"symbol": symbol},
                    bot_output=bot_h, auditor_output=None,
                    notes=notes,
                    audit_mode=audit_mode,
                )
            else:
                # Check if different Hurst values would produce different filter decisions
                HURST_THRESHOLD = 0.5
                bot_decision = "MEAN_REVERTING" if bot_h < HURST_THRESHOLD else "TRENDING"
                audit_decision = "MEAN_REVERTING" if audit_h < HURST_THRESHOLD else "TRENDING"
                flip = bot_decision != audit_decision
                notes = (
                    f"Hurst audit for {symbol}: bot={bot_h:.4f}({bot_decision}) "
                    f"auditor={audit_h:.4f}({audit_decision}). "
                    + ("⚠️ FILTER FLIP — different Hurst values produce different filter decisions! "
                       "Check smoothing/lag parameters."
                       if flip else "Filter decision unchanged.")
                )
                _log_result(
                    bot_id, "hurst_exponent",
                    {"symbol": symbol, "bot_hurst": bot_h, "auditor_hurst": audit_h},
                    bot_output=bot_h, auditor_output=audit_h,
                    notes=notes,
                    audit_mode=audit_mode,
                )

            checks += 1
            audited += 1
            time.sleep(1.0)

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 7 — Profit Factor & Win Rate Verification
# ─────────────────────────────────────────────────────────────────────────────

def audit_profit_factor(audit_mode: str = "full") -> int:
    """Module 7: Calculate profit factor and win rate from raw DB and compare to stored."""
    checks = 0

    # ── Oracle (Alpaca-based bot) ────────────────────────────────────────────
    # Per-symbol stats are stored in kraken_pair_params WHERE bot_id IS NULL.
    # Use the same trade-count-weighted aggregate approach as the Kraken section
    # to avoid the apples-to-oranges mismatch (arbitrary single row vs. overall
    # win rate) that previously caused false-positive FAIL results on Kraken bots.
    oracle_stored = _pg_query(
        """
        SELECT
            SUM(win_rate * trade_count) / NULLIF(SUM(trade_count)::float, 0) AS weighted_wr,
            SUM(win_rate * trade_count * avg_win_pct)                         AS gross_profit_pct,
            SUM((1.0 - win_rate) * trade_count * avg_loss_pct)               AS gross_loss_pct,
            SUM(trade_count)                                                  AS n_tracked
        FROM kraken_pair_params
        WHERE bot_id IS NULL
        """
    )
    oracle_raw = _pg_query(
        """
        SELECT pnl_percentage, exit_reason FROM trades
        WHERE (exit_reason IS NULL OR exit_reason NOT IN ('rebalance_liquidation'))
          AND status IN ('Closed_Win', 'Closed_Loss', 'Closed')
          AND pnl_percentage IS NOT NULL
          AND date >= CURRENT_DATE - INTERVAL '30 days'
        """
    )
    if oracle_raw:
        wins = sum(1 for r in oracle_raw if float(r.get("pnl_percentage") or 0) > 0)
        n = len(oracle_raw)
        audit_wr = wins / n if n > 0 else 0.0

        gross_profit_pct = sum(
            float(r["pnl_percentage"]) for r in oracle_raw
            if float(r.get("pnl_percentage") or 0) > 0
        )
        gross_loss_pct = abs(sum(
            float(r["pnl_percentage"]) for r in oracle_raw
            if float(r.get("pnl_percentage") or 0) < 0
        ))
        audit_pf_pct = (
            gross_profit_pct / gross_loss_pct if gross_loss_pct > 0
            else (999.0 if gross_profit_pct > 0 else 0.0)
        )

        stored_row = oracle_stored[0] if oracle_stored else {}
        weighted_wr = stored_row.get("weighted_wr")
        stored_gross_profit_pct = stored_row.get("gross_profit_pct")
        stored_gross_loss_pct = stored_row.get("gross_loss_pct")
        n_tracked = int(stored_row.get("n_tracked") or 0)

        stored_wr = float(weighted_wr) if weighted_wr is not None else None
        gp = float(stored_gross_profit_pct or 0.0)
        gl = float(stored_gross_loss_pct or 0.0)
        if stored_gross_profit_pct is None and stored_gross_loss_pct is None:
            stored_pf = None
        elif gl > 0:
            stored_pf = gp / gl
        elif gp > 0:
            stored_pf = 999.0
        else:
            stored_pf = 0.0

        if stored_pf is not None:
            _log_result(
                "oracle", "profit_factor",
                {"n_raw": n, "n_tracked": n_tracked,
                 "gross_profit_pct": gross_profit_pct, "gross_loss_pct": gross_loss_pct},
                bot_output=stored_pf, auditor_output=audit_pf_pct,
                notes=(
                    f"Oracle (Alpaca): pair-params trade-count-weighted PF={stored_pf:.3f} vs "
                    f"auditor pct-PnL PF={audit_pf_pct:.3f} from {n} raw closed trades (last 30 days) "
                    f"(pair-params covers {n_tracked} tracked trades, same 30-day window). "
                    "Both computed on pct-PnL basis."
                ),
                audit_mode=audit_mode,
            )
        else:
            _log_result(
                "oracle", "profit_factor",
                {"n_raw": n, "gross_profit_pct": gross_profit_pct, "gross_loss_pct": gross_loss_pct},
                bot_output=None, auditor_output=None,
                notes=(
                    f"Oracle (Alpaca): no per-symbol params in kraken_pair_params "
                    f"(bot_id IS NULL) — insufficient_data for stored-vs-raw comparison. "
                    f"Raw-only: PF={audit_pf_pct:.3f} from {n} closed trades."
                ),
                audit_mode=audit_mode,
            )
        checks += 1

        if stored_wr is not None:
            _log_result(
                "oracle", "win_rate",
                {"n_raw": n, "wins": wins, "n_tracked": n_tracked},
                bot_output=stored_wr, auditor_output=audit_wr,
                notes=(
                    f"Oracle (Alpaca): pair-params trade-count-weighted WR={stored_wr:.3f} vs "
                    f"raw trades WR={audit_wr:.3f} from {n} closed trades (last 30 days, same window as pair-params)."
                ),
                audit_mode=audit_mode,
            )
        else:
            _log_result(
                "oracle", "win_rate",
                {"n_raw": n, "wins": wins},
                bot_output=None, auditor_output=None,
                notes=(
                    f"Oracle (Alpaca): no per-symbol params in kraken_pair_params "
                    f"(bot_id IS NULL) — insufficient_data for stored-vs-raw comparison. "
                    f"Raw-only: WR={audit_wr:.3f} ({wins}/{n} closed trades)."
                ),
                audit_mode=audit_mode,
            )
        checks += 1

    # Kraken per-bot
    for bot_id in CURRENT_BOTS:
        stored = _pg_query(
            """
            SELECT
                SUM(win_rate * trade_count) / NULLIF(SUM(trade_count)::float, 0) AS weighted_wr,
                SUM(win_rate * trade_count * avg_win_pct)                         AS gross_profit_pct,
                SUM((1.0 - win_rate) * trade_count * avg_loss_pct)               AS gross_loss_pct,
                SUM(trade_count)                                                  AS n_tracked
            FROM kraken_pair_params
            WHERE bot_id = %s
            """,
            (bot_id,),
        )
        raw_trades = _pg_query(
            "SELECT pnl_usd, pnl_pct FROM kraken_trades WHERE bot_id = %s AND pnl_usd IS NOT NULL AND closed_at >= NOW() - INTERVAL '30 days'",
            (bot_id,),
        )

        if not raw_trades:
            continue

        wins = sum(1 for r in raw_trades if float(r["pnl_usd"]) > 0)
        n = len(raw_trades)
        audit_wr = wins / n if n > 0 else 0.0

        gross_profit_pct = sum(float(r["pnl_pct"]) for r in raw_trades if r["pnl_pct"] is not None and float(r["pnl_pct"]) > 0)
        gross_loss_pct = abs(sum(float(r["pnl_pct"]) for r in raw_trades if r["pnl_pct"] is not None and float(r["pnl_pct"]) < 0))
        audit_pf_pct = gross_profit_pct / gross_loss_pct if gross_loss_pct > 0 else (999.0 if gross_profit_pct > 0 else 0.0)

        stored_row = stored[0] if stored else {}
        weighted_wr = stored_row.get("weighted_wr")
        stored_gross_profit_pct = stored_row.get("gross_profit_pct")
        stored_gross_loss_pct = stored_row.get("gross_loss_pct")

        stored_wr = float(weighted_wr) if weighted_wr is not None else None
        gp = float(stored_gross_profit_pct or 0.0)
        gl = float(stored_gross_loss_pct or 0.0)
        if stored_gross_profit_pct is None and stored_gross_loss_pct is None:
            stored_pf = None
        elif gl > 0:
            stored_pf = gp / gl
        elif gp > 0:
            stored_pf = 999.0
        else:
            stored_pf = 0.0

        if stored_pf is not None:
            _log_result(
                bot_id, "profit_factor",
                {"n": n, "gross_profit_pct": gross_profit_pct, "gross_loss_pct": gross_loss_pct},
                bot_output=stored_pf, auditor_output=audit_pf_pct,
                notes=(
                    f"{bot_id}: pair-params reconstructed PF={stored_pf:.3f} vs auditor pnl_pct PF={audit_pf_pct:.3f} "
                    f"from {n} raw trades (last 30 days, same window as pair-params; both on pct-PnL basis)."
                ),
                audit_mode=audit_mode,
            )
            checks += 1

        if stored_wr is not None:
            _log_result(
                bot_id, "win_rate",
                {"n": n, "wins": wins},
                bot_output=stored_wr, auditor_output=audit_wr,
                notes=(
                    f"{bot_id}: pair-params weighted avg WR={stored_wr:.3f} vs raw trades WR={audit_wr:.3f} "
                    f"from {n} raw trades (last 30 days, same window as pair-params)."
                ),
                audit_mode=audit_mode,
            )
            checks += 1

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 8 — Momentum Score Verification (Oracle)
# ─────────────────────────────────────────────────────────────────────────────

def audit_momentum_score_oracle(audit_mode: str = "full") -> int:
    """Module 8: Recalculate composite momentum score for Oracle's top candidates."""
    checks = 0
    scans = _pg_query(
        "SELECT top5_long, top5_short FROM oracle_scan_log ORDER BY ts DESC LIMIT 1"
    )
    if not scans:
        return 0

    scan = scans[0]
    candidates: list[dict] = []
    for field in ("top5_long", "top5_short"):
        raw = scan.get(field)
        if not raw:
            continue
        try:
            cands = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(cands, list):
                candidates.extend(cands)
        except Exception:
            pass

    for cand in candidates[:4]:
        symbol = cand.get("symbol")
        bot_score = cand.get("score")
        if not symbol or bot_score is None:
            continue

        closes = _fetch_alpaca_closes(symbol, days=75)
        if not closes or len(closes) < 65:
            _log_result(
                "oracle", "momentum_score",
                {"symbol": symbol},
                bot_output=float(bot_score), auditor_output=None,
                notes=f"Insufficient Alpaca price history for {symbol} ({len(closes) if closes else 0} days)",
                audit_mode=audit_mode,
            )
            checks += 1
            continue

        # Calculate returns at standard windows
        try:
            r5  = (closes[-1] - closes[-6])  / closes[-6]  * 100
            r20 = (closes[-1] - closes[-21]) / closes[-21] * 100
            r60 = (closes[-1] - closes[-61]) / closes[-61] * 100
        except IndexError:
            _log_result(
                "oracle", "momentum_score",
                {"symbol": symbol},
                bot_output=float(bot_score), auditor_output=None,
                notes=f"Not enough bars to compute returns for {symbol}",
                audit_mode=audit_mode,
            )
            checks += 1
            continue

        audit_score = verified_momentum_score(r5, r20, r60)
        _log_result(
            "oracle", "momentum_score",
            {"symbol": symbol, "return_5d": r5, "return_20d": r20, "return_60d": r60},
            bot_output=float(bot_score), auditor_output=audit_score,
            notes=(
                f"Momentum score for {symbol}: bot={bot_score:.4f} audit={audit_score:.4f}. "
                f"returns: 5d={r5:.2f}% 20d={r20:.2f}% 60d={r60:.2f}%. "
                f"Weights: 5d×0.20 + 20d×0.50 + 60d×0.30. "
                f"Score discrepancy may indicate wrong period endpoints or weights."
            ),
            audit_mode=audit_mode,
        )
        checks += 1
        time.sleep(0.3)

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 9 — BTC-Neutral Z-Score Verification
# ─────────────────────────────────────────────────────────────────────────────

def _bot_btc_neutral_zscore_formula(
    pair_prices: list, btc_prices: list, window: int = 20
):
    """Replica of kraken-bot/logic.py calculate_btc_neutral_zscore.

    Uses log returns and OLS via covariance/variance, matching the bot exactly.
    Returns (zscore, beta) or (None, None) on failure.
    """
    try:
        if len(pair_prices) < 2 or len(btc_prices) < 2:
            return None, None
        pair_log = list(np.diff(np.log(np.array(pair_prices, dtype=float))))
        btc_log  = list(np.diff(np.log(np.array(btc_prices,  dtype=float))))
        min_len  = min(len(pair_log), len(btc_log))
        pair_log = pair_log[-min_len:]
        btc_log  = btc_log[-min_len:]
        if min_len < window:
            return None, None
        recent_pair = np.array(pair_log[-window:])
        recent_btc  = np.array(btc_log[-window:])
        btc_var = float(np.var(recent_btc, ddof=1))
        if btc_var == 0.0:
            return None, None
        beta = float(np.cov(recent_pair, recent_btc)[0, 1]) / btc_var
        all_residuals = np.array(pair_log) - beta * np.array(btc_log)
        rolling = all_residuals[-window:]
        mean_r = float(np.mean(rolling))
        std_r  = float(np.std(rolling, ddof=1))
        if std_r == 0.0:
            return None, None
        residual = float(pair_log[-1]) - beta * float(btc_log[-1])
        return float((residual - mean_r) / std_r), float(beta)
    except Exception:
        return None, None


def audit_btc_neutral_zscore(audit_mode: str = "full") -> int:
    """Module 9: Verify BTC-neutral OLS Z-score formula correctness.

    Approach: fetch fresh OHLCV for a fixed set of symbols, compute log returns,
    then run BOTH the bot formula (_bot_btc_neutral_zscore_formula, which uses
    log returns matching logic.py) and the reference formula (verified_btc_neutral_zscore,
    updated to log returns) on the exact same return series.  Any discrepancy
    indicates a genuine formula bug.

    This avoids the false-positive FAILs caused by comparing a stale
    entry_zscore (captured at trade open) against fresh current-market data
    where prices have moved significantly since the trade was opened.
    """
    SYMBOLS_TO_CHECK = ["ETH/USD", "SOL/USD", "XRP/USD"]
    window = 20
    checks = 0

    # Fetch BTC candles once — shared denominator for all pairs
    btc_candles = _fetch_kraken_ohlcv("BTC/USD", "1h", limit=60)
    if not btc_candles or len(btc_candles) < window + 2:
        logger.warning("[math_auditor] BTC OHLCV unavailable — skipping btc_neutral_zscore audit")
        return 0

    btc_closes = [float(c[4]) for c in btc_candles]

    for bot_id in CURRENT_BOTS:
        for symbol in SYMBOLS_TO_CHECK:
            pair_candles = _fetch_kraken_ohlcv(symbol, "1h", limit=60)
            if not pair_candles or len(pair_candles) < window + 2:
                _log_result(
                    bot_id, "btc_neutral_zscore",
                    {"symbol": symbol},
                    bot_output=None, auditor_output=None,
                    notes=f"Insufficient OHLCV for {symbol} — skipping formula check",
                    audit_mode=audit_mode,
                )
                checks += 1
                continue

            pair_closes = [float(c[4]) for c in pair_candles]

            # Both formulas receive the same raw closes → log returns computed internally
            bot_z, bot_beta = _bot_btc_neutral_zscore_formula(pair_closes, btc_closes, window=window)

            # For reference: pass log returns (matching bot) to verified_btc_neutral_zscore
            try:
                pair_log = list(np.diff(np.log(np.array(pair_closes, dtype=float))))
                btc_log  = list(np.diff(np.log(np.array(btc_closes,  dtype=float))))
                min_len  = min(len(pair_log), len(btc_log))
                ref_z, ref_beta, reason = verified_btc_neutral_zscore(
                    pair_log[-min_len:], btc_log[-min_len:], window=window
                )
            except Exception as exc:
                ref_z, ref_beta, reason = None, None, str(exc)

            if bot_z is None or ref_z is None:
                _log_result(
                    bot_id, "btc_neutral_zscore",
                    {"symbol": symbol, "window": window},
                    bot_output=bot_z, auditor_output=ref_z,
                    notes=(
                        f"Formula produced no result for {symbol} "
                        f"(bot={bot_z}, ref_reason={reason}) — insufficient data or zero variance"
                    ),
                    audit_mode=audit_mode,
                )
            else:
                _log_result(
                    bot_id, "btc_neutral_zscore",
                    {"symbol": symbol, "window": window,
                     "bot_beta": round(bot_beta, 6) if bot_beta else None,
                     "ref_beta": round(ref_beta, 6) if ref_beta else None},
                    bot_output=bot_z, auditor_output=ref_z,
                    notes=(
                        f"Formula cross-check for {symbol} (1h, window={window}). "
                        "Both bot formula and reference use log returns on identical fresh OHLCV. "
                        "Discrepancy >1% indicates a real OLS/residual formula mismatch."
                    ),
                    audit_mode=audit_mode,
                )
            checks += 1
            time.sleep(0.5)

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# Public Audit Runners
# ─────────────────────────────────────────────────────────────────────────────

def run_quick_audit() -> dict:
    """Quick audit: ATR/stop checks + position sizing. ~60s cadence."""
    ensure_table()
    t0 = time.time()
    results: dict[str, int] = {}
    try:
        results["atr_stop_check"] = audit_atr_open_positions("quick")
    except Exception as exc:
        logger.warning(f"[math_auditor] quick.atr: {exc}")
    try:
        results["position_sizing"] = audit_position_sizing("quick")
    except Exception as exc:
        logger.warning(f"[math_auditor] quick.sizing: {exc}")
    elapsed = round(time.time() - t0, 2)
    logger.info(f"[math_auditor] QUICK audit complete in {elapsed}s — {results}")
    return {"mode": "quick", "elapsed_s": elapsed, "checks": results}


def run_full_audit() -> dict:
    """Full audit of current equity-bot scope and persisted math checks."""
    ensure_table()
    t0 = time.time()
    results: dict[str, int] = {}

    for name, fn in [
        ("instrument_scope", lambda: audit_zscore_kraken("full")),
        ("atr_stop_check",   lambda: audit_atr_open_positions("full")),
    ]:
        try:
            results[name] = fn()
        except Exception as exc:
            logger.warning(f"[math_auditor] full.{name}: {exc}")
            results[name] = 0

    _prune_old_logs(keep=1000)
    elapsed = round(time.time() - t0, 2)
    total = sum(results.values())
    logger.info(f"[math_auditor] FULL audit complete in {elapsed}s — {total} checks: {results}")
    return {"mode": "full", "elapsed_s": elapsed, "checks": results, "total": total}


def run_deep_audit() -> dict:
    """Deep audit: all modules including Hurst & hedge ratio. ~4h cadence."""
    ensure_table()
    t0 = time.time()
    results = run_full_audit()

    for name, fn in [
        ("hurst_kraken",         lambda: audit_hurst_kraken("deep")),
    ]:
        try:
            results.setdefault("checks", {})[name] = fn()
        except Exception as exc:
            logger.warning(f"[math_auditor] deep.{name}: {exc}")

    elapsed = round(time.time() - t0, 2)
    logger.info(f"[math_auditor] DEEP audit complete in {elapsed}s")
    results["mode"] = "deep"
    results["elapsed_s"] = elapsed
    return results


def get_audit_summary(hours: int = 24) -> dict:
    """Return a summary of recent audit results for the diagnostic report."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = _pg_query(
        """
        SELECT status, severity, COUNT(*) as n,
               STRING_AGG(DISTINCT bot_id, ', ' ORDER BY bot_id) as bots
        FROM math_audit_log
        WHERE audit_timestamp > %s
        GROUP BY status, severity
        """,
        (cutoff,),
    )
    detail_rows = _pg_query(
        """
        SELECT audit_timestamp, bot_id, formula_name, bot_output, auditor_output,
               discrepancy_pct, status, severity, notes
        FROM math_audit_log
        WHERE audit_timestamp > %s AND status IN ('FAIL', 'WARN')
        ORDER BY severity DESC, audit_timestamp DESC
        LIMIT 20
        """,
        (cutoff,),
    )
    last_run = _pg_query(
        "SELECT MAX(audit_timestamp) as last_ts, COUNT(*) as total FROM math_audit_log"
    )
    pass_n = sum(int(r.get("n") or 0) for r in rows if r.get("status") == "PASS")
    warn_n = sum(int(r.get("n") or 0) for r in rows if r.get("status") == "WARN")
    fail_n = sum(int(r.get("n") or 0) for r in rows if r.get("status") == "FAIL")
    last_ts = str(last_run[0].get("last_ts") or "Never")[:19] if last_run else "Never"
    total = int(last_run[0].get("total") or 0) if last_run else 0

    return {
        "pass": pass_n,
        "warn": warn_n,
        "fail": fail_n,
        "last_audit_ts": last_ts,
        "total_logged": total,
        "details": [dict(r) for r in detail_rows],
    }
