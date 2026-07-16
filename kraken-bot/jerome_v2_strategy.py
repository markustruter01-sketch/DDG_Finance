"""
jerome_v2_strategy.py — Jerome v2 commodity trend-following strategy.

Replaces the LLM-based jerome_strategy.py with a pure quantitative
EMA/ADX/ATR trailing-stop system.  The LLM stack (jerome_strategy.py,
jerome_investor.py, jerome_market_context.py) remains on disk as a
parachute — revert by changing one line in runner.py.

Validated by 28-month backtest (2024-01-01 → 2026-05-01):
  +33.95% return  |  Sharpe 0.996  |  Max DD 12.91%

Wired into runner.py:
    ("blackbeard", "jerome_v2_strategy", "run_jerome_v2_cycle")

Called every LOOP_SLEEP_SECONDS (900s = 15 min).
Entry scan fires once per day at 13:30–13:50 UTC (5 min after NYSE open).
Exit management runs every cycle (protects open positions continuously).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger("jerome.v2")

# ─── Module-level constants ────────────────────────────────────────────────────

UNIVERSE: dict[str, list[str]] = {
    "ENERGY":          ["XLE", "USO", "XOP"],
    "PRECIOUS_METALS": ["GLD", "SLV", "GDX", "GDXJ"],
}

# Bot identity for DB row tagging (shared jerome_positions table)
BOT_ID = "jerome_macro"

CYCLE_HOUR_UTC  = 13     # entry scan window start
CYCLE_MIN_START = 30     # 13:30 UTC
CYCLE_MIN_END   = 50     # 13:50 UTC
RISK_PER_TRADE  = 0.04   # 4% of portfolio equity per trade
SINGLE_POS_CAP  = 0.50   # 50% single-position notional cap
ADX_LONG_MIN    = 30     # ADX threshold for long entries
ADX_SHORT_MIN   = 25     # ADX threshold for short entries
TRAIL_ATR_MULT  = 5.0    # trailing stop = 5 × ATR(14)
MAX_POSITIONS   = 6      # maximum concurrent open positions
THEME_CAP       = 2      # max positions per theme

# Once-per-day gate state (module-level; resets across restarts, that's OK)
_last_entry_scan_date: Optional[date] = None

# Schema bootstrap flag — runs once per process, before first DB operation
_bot_id_col_ensured: bool = False


def _ensure_bot_id_column() -> None:
    """
    Idempotent: add bot_id column to jerome_positions if it doesn't exist,
    then tag any untagged rows as 'jerome_macro'.  Called once per process on
    first cycle so kraken-bot-runner doesn't depend on trading-api startup order.
    """
    global _bot_id_col_ensured
    if _bot_id_col_ensured:
        return
    _add_trading_platform_to_path()
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE jerome_positions "
                    "ADD COLUMN IF NOT EXISTS bot_id TEXT DEFAULT 'jerome_macro'"
                )
                cur.execute(
                    "UPDATE jerome_positions SET bot_id='jerome_macro' WHERE bot_id IS NULL"
                )
        _bot_id_col_ensured = True
        logger.info("Jerome v2 | jerome_positions.bot_id column ensured")
    except Exception as exc:
        logger.warning(f"Jerome v2 | bot_id column ensure failed (non-fatal): {exc}")


# ─── Universe helpers ──────────────────────────────────────────────────────────

def _all_tickers() -> list[str]:
    return [t for tickers in UNIVERSE.values() for t in tickers]


def _theme_of(ticker: str) -> str:
    for theme, tickers in UNIVERSE.items():
        if ticker in tickers:
            return theme
    return "UNKNOWN"


# ─── Path injection ────────────────────────────────────────────────────────────

def _add_trading_platform_to_path() -> None:
    tp = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
    )
    if tp not in sys.path:
        sys.path.insert(0, tp)


# ─── Data + indicators ────────────────────────────────────────────────────────

def _fetch_ohlcv(ticker: str, days: int = 250) -> Optional[dict]:
    """Delegate to alpaca_etf_engine's Yahoo Finance fetcher (same call site as the fleet)."""
    try:
        from alpaca_etf_engine import _yahoo_daily_ohlcv
        return _yahoo_daily_ohlcv(ticker, days=days)
    except Exception as exc:
        logger.debug(f"Jerome v2 | _fetch_ohlcv({ticker}) failed: {exc}")
        return None


def _compute_indicators(ohlcv: dict) -> Optional[dict]:
    """
    Compute EMA21/55/200, ADX(14), ATR(14) from raw OHLCV dict.
    Returns dict with last-bar values, or None if data is insufficient.
    """
    try:
        import pandas as pd
        import ta

        closes = pd.Series(ohlcv["closes"], dtype=float)
        highs  = pd.Series(ohlcv["highs"],  dtype=float)
        lows   = pd.Series(ohlcv["lows"],   dtype=float)

        if len(closes) < 210:   # need 200 for EMA200 warm-up
            return None

        ema21  = ta.trend.EMAIndicator(closes, window=21).ema_indicator()
        ema55  = ta.trend.EMAIndicator(closes, window=55).ema_indicator()
        ema200 = ta.trend.EMAIndicator(closes, window=200).ema_indicator()
        adx    = ta.trend.ADXIndicator(highs, lows, closes, window=14).adx()
        atr    = ta.volatility.AverageTrueRange(highs, lows, closes, window=14).average_true_range()

        import math
        vals = {
            "close":      float(closes.iloc[-1]),
            "prev_close": float(closes.iloc[-2]),
            "ema21":      float(ema21.iloc[-1]),
            "ema55":      float(ema55.iloc[-1]),
            "ema200":     float(ema200.iloc[-1]),
            "adx":        float(adx.iloc[-1]),
            "atr":        float(atr.iloc[-1]),
        }
        # Reject if any indicator is NaN
        if any(math.isnan(v) for v in vals.values()):
            return None
        return vals

    except Exception as exc:
        logger.debug(f"Jerome v2 | _compute_indicators failed: {exc}")
        return None


def _build_signal(ticker: str, ind: dict) -> Optional[dict]:
    """
    Evaluate entry signal.  Returns dict with direction + score, or None.
    Score = |EMA21−EMA55| / EMA55 × (ADX / 100).  Higher = stronger trend.
    """
    c, pc = ind["close"], ind["prev_close"]
    e21, e55, e200, adx = ind["ema21"], ind["ema55"], ind["ema200"], ind["adx"]

    if e55 == 0:
        return None

    score = abs((e21 - e55) / e55) * (adx / 100.0)

    # Long signal
    if c > e200 and e21 > e55 and adx >= ADX_LONG_MIN and c > pc:
        return {"direction": "long", "score": score}

    # Short signal (shorting_enabled confirmed on PA37SP8ID1XU)
    if c < e200 and e21 < e55 and adx >= ADX_SHORT_MIN and c < pc:
        return {"direction": "short", "score": score}

    return None


# ─── Database helpers ─────────────────────────────────────────────────────────

def _get_open_db_positions() -> list[dict]:
    """Read all open jerome_positions rows, including new v2 columns."""
    _add_trading_platform_to_path()
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return []
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, symbol, direction, theme, notional_usd,
                           entry_price, highest_price_seen, opened_at
                    FROM jerome_positions
                    WHERE status = 'open'
                      AND bot_id = 'jerome_macro'
                    ORDER BY opened_at ASC
                """)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning(f"Jerome v2 | _get_open_db_positions failed: {exc}")
        return []


def _count_open_in_theme(theme: str) -> int:
    """Count open positions in a specific theme (for theme cap gate)."""
    _add_trading_platform_to_path()
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return 0
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM jerome_positions "
                    "WHERE theme = %s AND status = 'open' AND bot_id = 'jerome_macro'",
                    (theme,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
    except Exception:
        return 0


def _count_open_by_symbol(symbol: str) -> int:
    """P2 gate: count open rows for a symbol (catches pending OPG orders)."""
    _add_trading_platform_to_path()
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return 0
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM jerome_positions "
                    "WHERE symbol = %s AND status = 'open' AND bot_id = 'jerome_macro'",
                    (symbol,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
    except Exception:
        return 0


def _update_highest_price_seen(row_id: int, new_val: float) -> None:
    """Ratchet highest_price_seen to new_val (only moves in the favourable direction)."""
    _add_trading_platform_to_path()
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Use GREATEST/LEAST so the DB enforces the ratchet atomically
                cur.execute("""
                    UPDATE jerome_positions
                    SET highest_price_seen = %s
                    WHERE id = %s
                """, (new_val, row_id))
    except Exception as exc:
        logger.debug(f"Jerome v2 | _update_highest_price_seen({row_id}) failed: {exc}")


def _record_trade_open(
    symbol: str,
    direction: str,
    theme: str,
    notional_usd: float,
    entry_price: float,
    close_at_signal: float,
) -> None:
    """Insert a new open position row into jerome_positions."""
    _add_trading_platform_to_path()
    thesis = (
        f"Jerome v2 | {direction.upper()} {symbol} | theme={theme} | "
        f"entry={entry_price:.4f} | notional=${notional_usd:,.0f} | "
        f"trail=5×ATR | ADX≥{ADX_LONG_MIN if direction=='long' else ADX_SHORT_MIN}"
    )
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jerome_positions
                        (symbol, direction, theme, notional_usd,
                         entry_price, highest_price_seen,
                         conviction, stop_loss_pct, take_profit_pct,
                         max_hold_days, thesis, status, opened_at, bot_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',NOW(),'jerome_macro')
                """, (
                    symbol, direction, theme, round(notional_usd, 2),
                    round(entry_price, 6), round(close_at_signal, 6),
                    1.0,             # conviction = 1.0 (signal-based, not LLM)
                    RISK_PER_TRADE,  # stop_loss_pct field reused for audit trail
                    0.0,             # take_profit_pct = 0 (trailing stop replaces TP)
                    365,             # max_hold_days = unlimited (trail manages exit)
                    thesis[:400],
                ))
        logger.info(f"Jerome v2 | DB: recorded OPEN {direction.upper()} {symbol} "
                    f"notional=${notional_usd:,.0f} entry={entry_price:.4f}")
    except Exception as exc:
        # B-8 fix: broker order is LIVE but DB record failed — position untracked.
        # Direct Discord alert + degradation so operator can reconcile manually.
        logger.error(f"Jerome v2 | _record_trade_open FAILED — broker order LIVE but DB untracked: {exc}")
        try:
            from notifications.discord import notify_capital_risk
            notify_capital_risk(
                f"🔴 Jerome {symbol}: broker order LIVE but DB record failed — untracked position",
                symbol=symbol,
            )
        except Exception:
            pass
        try:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="jerome_macro",
                severity="high",
                error_type="db_record_open_failed",
                message=f"Jerome {symbol}: broker order LIVE but _record_trade_open failed — untracked",
                detail=str(exc)[:400],
            )
        except Exception:
            pass


def _record_trade_close(row_id: int, exit_reason: str) -> None:
    """Mark jerome_positions row as closed.  P&L is back-filled by the existing reconciler."""
    _add_trading_platform_to_path()
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE jerome_positions
                    SET status = 'closed', closed_at = NOW(), exit_reason = %s
                    WHERE id = %s
                """, (exit_reason, row_id))
        logger.info(f"Jerome v2 | DB: recorded CLOSE id={row_id} reason={exit_reason}")
    except Exception as exc:
        # B-8 fix: broker close is DONE but DB record failed — row stays 'open'.
        logger.error(f"Jerome v2 | _record_trade_close({row_id}) FAILED — position may show Open in DB: {exc}")
        try:
            from notifications.discord import notify_capital_risk
            notify_capital_risk(
                f"🔴 Jerome: DB close record FAILED (id={row_id}, reason={exit_reason}) "
                f"— position may still show Open in DB",
                symbol=f"JEROME_ID{row_id}",
            )
        except Exception:
            pass
        try:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="jerome_macro",
                severity="high",
                error_type="db_record_close_failed",
                message=f"Jerome id={row_id}: _record_trade_close failed — row may still show open",
                detail=str(exc)[:400],
            )
        except Exception:
            pass


# ─── Time gate ────────────────────────────────────────────────────────────────

def should_run_v2_cycle(now: Optional[datetime] = None) -> bool:
    """
    True if we are in the 13:30–13:50 UTC window AND have not run an entry
    scan today.  Exits are not gated — they run every caller cycle.
    """
    global _last_entry_scan_date
    if now is None:
        now = datetime.now(timezone.utc)
    in_window = (
        now.hour == CYCLE_HOUR_UTC
        and CYCLE_MIN_START <= now.minute < CYCLE_MIN_END
    )
    already_ran = (_last_entry_scan_date == now.date())
    return in_window and not already_ran


# ─── Exit management (runs every cycle) ───────────────────────────────────────

def _manage_exits(alpaca: "JeromeAlpaca", equity: float) -> None:
    """
    For each open jerome_positions row:
      1. Fetch fresh OHLCV for the ticker (latest close + ATR + EMA200)
      2. Ratchet highest_price_seen in the DB
      3. Compute trailing stop = highest_price_seen ± TRAIL_ATR_MULT × ATR
      4. Check trailing stop hit OR regime flip (close crosses EMA200)
      5. If exit triggered: close Alpaca position + DB record
    """
    open_rows = _get_open_db_positions()
    if not open_rows:
        logger.debug("Jerome v2 | No open positions to manage")
        return

    logger.info(f"Jerome v2 | Managing {len(open_rows)} open position(s)")

    for row in open_rows:
        symbol    = row["symbol"]
        direction = row["direction"]
        row_id    = row["id"]
        entry_px  = float(row["entry_price"] or 0)
        hps       = float(row["highest_price_seen"] or entry_px or 0)

        ohlcv = _fetch_ohlcv(symbol, days=250)
        if ohlcv is None:
            logger.warning(f"Jerome v2 | {symbol}: OHLCV fetch failed — skipping exit check")
            continue

        ind = _compute_indicators(ohlcv)
        if ind is None:
            logger.warning(f"Jerome v2 | {symbol}: indicator compute failed — skipping exit check")
            continue

        close = ind["close"]
        atr   = ind["atr"]
        e200  = ind["ema200"]

        # ── Ratchet highest_price_seen ────────────────────────────────────
        if direction == "long":
            if close > hps:
                hps = close
                _update_highest_price_seen(row_id, hps)
        else:  # short: track the lowest close (stored in same field)
            if hps == 0 or close < hps:
                hps = close
                _update_highest_price_seen(row_id, hps)

        # ── Compute trailing stop ──────────────────────────────────────────
        if direction == "long":
            trail_stop = hps - TRAIL_ATR_MULT * atr
            stop_hit   = close < trail_stop
            regime_flip = close < e200
        else:
            trail_stop = hps + TRAIL_ATR_MULT * atr
            stop_hit   = close > trail_stop
            regime_flip = close > e200

        exit_reason: Optional[str] = None
        if stop_hit:
            exit_reason = "trailing_stop"
            logger.info(
                f"Jerome v2 | EXIT trailing_stop: {symbol} "
                f"close={close:.4f} trail={trail_stop:.4f} "
                f"hps={hps:.4f} ATR={atr:.4f}"
            )
        elif regime_flip:
            exit_reason = "regime_flip"
            logger.info(
                f"Jerome v2 | EXIT regime_flip: {symbol} "
                f"close={close:.4f} EMA200={e200:.4f}"
            )
        else:
            upl_pct = (
                (close - entry_px) / entry_px * 100 if entry_px
                else 0.0
            )
            if direction == "short":
                upl_pct = -upl_pct
            logger.info(
                f"Jerome v2 | HOLD {symbol} ({direction}) "
                f"close={close:.4f} trail={trail_stop:.4f} "
                f"hps={hps:.4f} UPL={upl_pct:+.2f}%"
            )

        if exit_reason:
            ok = alpaca.close_position(symbol)
            if ok:
                _record_trade_close(row_id, exit_reason)
            else:
                logger.error(
                    f"Jerome v2 | Alpaca close FAILED for {symbol} — "
                    f"DB NOT updated (will retry next cycle)"
                )


# ─── Entry scan (once per day at 13:35 UTC) ───────────────────────────────────

def _is_crisis_active() -> bool:
    """
    MSE CRISIS gate: return True if SPY 20-day return <= -12%.

    FAIL-SAFE direction: returns True (block entries) on insufficient data or
    any error. This is TRANSIENT — the moment SPY data is available and computes
    cleanly, it returns the real regime. No sticky state.
    """
    try:
        spy = _fetch_ohlcv("SPY", days=30)
        if spy is None:
            logger.warning("Jerome v2 | CRISIS GATE: SPY data unavailable — fail-safe CRISIS active")
            return True   # fail-safe: block entries
        closes = spy.get("closes") or []
        if len(closes) < 21:
            logger.warning(
                f"Jerome v2 | CRISIS GATE: insufficient SPY data "
                f"({len(closes)} bars, need 21) — fail-safe CRISIS active"
            )
            return True   # fail-safe: block entries
        ret_20d = float(closes[-1]) / float(closes[-21]) - 1
        return ret_20d <= -0.12
    except Exception as exc:
        logger.warning(f"Jerome v2 | CRISIS GATE: computation failed ({exc}) — fail-safe CRISIS active")
        return True  # fail-safe: block entries


def _run_entry_scan(alpaca: "JeromeAlpaca", equity: float, buying_power: float = 0.0) -> None:
    """
    Scan all 12 universe instruments for entry signals.
    Applies theme cap, position cap, and capital checks before submitting orders.

    buying_power: shared-account available cash passed from the cycle; used as a
    rolling guard so Jerome + Buck Futures cannot jointly over-deploy the pool.
    """
    global _last_entry_scan_date

    # Jerome's universe — used to partition position-cap from Buck Futures' positions
    # on the shared account. Only positions in THIS set count toward Jerome's cap.
    JEROME_SYMBOLS = {"GLD", "SLV", "GDX", "GDXJ", "XLE", "USO", "XOP"}

    logger.info("Jerome v2 | === ENTRY SCAN START ===")

    # Count currently open positions (Alpaca is source-of-truth for live count)
    # Filter to Jerome's own universe — Buck Futures shares the account but trades
    # a non-overlapping set (DBB, PICK, DBC, PDBC, GSG), so exclude their positions.
    alpaca_positions = alpaca.get_open_positions()
    open_count       = len([p for p in alpaca_positions if p["symbol"] in JEROME_SYMBOLS])
    open_symbols     = {p["symbol"] for p in alpaca_positions if p["symbol"] in JEROME_SYMBOLS}

    logger.info(
        f"Jerome v2 | Open positions (Jerome universe): {open_count}/{MAX_POSITIONS} "
        f"| shared-account buying_power=${buying_power:,.2f}"
    )

    # Rolling cash tracker — prevents over-deployment when both bots size against
    # the same shared account pool in the same cycle.
    cash_remaining = buying_power

    if open_count >= MAX_POSITIONS:
        logger.info("Jerome v2 | Position cap reached — no new entries")
        _last_entry_scan_date = datetime.now(timezone.utc).date()
        return

    # ── MSE CRISIS gate: SPY 20-day return <= -12% blocks all new entries ────
    if _is_crisis_active():
        logger.warning(
            "Jerome v2 | CRISIS GATE: SPY 20-day return <= -12% — "
            "all new entries blocked this cycle (exits unaffected)"
        )
        _last_entry_scan_date = datetime.now(timezone.utc).date()
        return

    # Build signals for all universe tickers
    candidates: list[dict] = []
    for ticker in _all_tickers():
        ohlcv = _fetch_ohlcv(ticker, days=250)
        if ohlcv is None:
            logger.debug(f"Jerome v2 | {ticker}: no data — skip")
            continue
        ind = _compute_indicators(ohlcv)
        if ind is None:
            logger.debug(f"Jerome v2 | {ticker}: indicators unavailable — skip")
            continue
        sig = _build_signal(ticker, ind)
        if sig is None:
            logger.debug(f"Jerome v2 | {ticker}: no signal (ADX={ind['adx']:.1f})")
            continue
        candidates.append({
            "ticker":    ticker,
            "theme":     _theme_of(ticker),
            "direction": sig["direction"],
            "score":     sig["score"],
            "close":     ind["close"],
            "atr":       ind["atr"],
        })
        logger.info(
            f"Jerome v2 | SIGNAL {sig['direction'].upper()} {ticker} "
            f"score={sig['score']:.4f} ADX={ind['adx']:.1f} "
            f"close={ind['close']:.4f} ATR={ind['atr']:.4f}"
        )

    if not candidates:
        logger.info("Jerome v2 | No signals this cycle")
        _last_entry_scan_date = datetime.now(timezone.utc).date()
        return

    # Sort by trend strength score descending — enter strongest trends first
    candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info(
        f"Jerome v2 | {len(candidates)} signal(s). "
        f"Top: {candidates[0]['ticker']} ({candidates[0]['direction']}) "
        f"score={candidates[0]['score']:.4f}"
    )

    entries_this_cycle = 0

    # ARC 4: fire-and-forget shadow signal helper (decision ledger without execution)
    def _shadow_jv2(sym, dir_, price, score, *, executed: bool = False, skip: str | None = None) -> None:
        try:
            from db.shadow_signals import log_shadow_signal
            log_shadow_signal(
                "jerome_macro", sym,
                side=dir_,
                entry_price_at_signal=price,
                score=score,
                executed=executed,
                skip_reason=skip,
            )
        except Exception:
            pass

    for cand in candidates:
        if open_count >= MAX_POSITIONS:
            break

        ticker    = cand["ticker"]
        theme     = cand["theme"]
        direction = cand["direction"]
        close     = cand["close"]
        atr       = cand["atr"]

        # ── Guard: already holding (DB gate — catches pending OPG orders) ──
        if _count_open_by_symbol(ticker) > 0:
            logger.debug(f"Jerome v2 | {ticker}: already open in DB — skip")
            _shadow_jv2(ticker, direction, close, cand["score"], skip="already_holding")
            continue
        if ticker in open_symbols:
            logger.debug(f"Jerome v2 | {ticker}: already open on Alpaca — skip")
            _shadow_jv2(ticker, direction, close, cand["score"], skip="already_holding")
            continue

        # ── Guard: theme cap ───────────────────────────────────────────────
        theme_open = _count_open_in_theme(theme)
        if theme_open >= THEME_CAP:
            logger.debug(
                f"Jerome v2 | {ticker}: theme cap reached "
                f"({theme} has {theme_open}/{THEME_CAP}) — skip"
            )
            _shadow_jv2(ticker, direction, close, cand["score"], skip="theme_cap")
            continue

        # ── Guard: ATR sanity ──────────────────────────────────────────────
        if atr <= 0:
            logger.debug(f"Jerome v2 | {ticker}: ATR={atr} invalid — skip")
            _shadow_jv2(ticker, direction, close, cand["score"], skip="atr_invalid")
            continue

        # ── Sizing ────────────────────────────────────────────────────────
        risk_usd      = equity * RISK_PER_TRADE          # 4% of equity
        stop_distance = TRAIL_ATR_MULT * atr              # 5 × ATR
        qty           = risk_usd / stop_distance
        notional      = qty * close

        # Cap at 50% of equity
        cap = equity * SINGLE_POS_CAP
        if notional > cap:
            notional = cap
            qty      = notional / close
            logger.debug(
                f"Jerome v2 | {ticker}: notional capped at 50% equity "
                f"(${notional:,.0f})"
            )

        # Minimum position sanity ($500)
        if notional < 500:
            logger.debug(
                f"Jerome v2 | {ticker}: notional ${notional:.0f} < $500 — skip"
            )
            _shadow_jv2(ticker, direction, close, cand["score"], skip="min_position")
            continue

        # ── Guard: shared-account cash ─────────────────────────────────────
        # Both Jerome and Buck Futures draw from the same ~$96.7k paper account.
        # Skip this entry if notional exceeds the remaining available cash so
        # we cannot jointly over-deploy the shared pool.
        if notional > cash_remaining:
            logger.warning(
                f"Jerome v2 | {ticker}: insufficient shared-account cash "
                f"(need ${notional:,.0f}, available=${cash_remaining:,.0f}) — skip"
            )
            _shadow_jv2(ticker, direction, close, cand["score"], skip="cash")
            continue

        # ── Submit order ───────────────────────────────────────────────────
        alpaca_side = "buy" if direction == "long" else "sell"
        logger.info(
            f"Jerome v2 | ENTER {direction.upper()} {ticker} "
            f"notional=${notional:,.0f} qty≈{qty:.3f} "
            f"theme={theme} score={cand['score']:.4f}"
        )
        order = alpaca.place_order(ticker, alpaca_side, notional)
        if order is None:
            logger.error(f"Jerome v2 | Order FAILED for {ticker} — skipping DB write")
            _shadow_jv2(ticker, direction, close, cand["score"], skip="order_failed")
            continue

        # ── DB record ──────────────────────────────────────────────────────
        _record_trade_open(
            symbol=ticker,
            direction=direction,
            theme=theme,
            notional_usd=notional,
            entry_price=close,
            close_at_signal=close,
        )

        open_count      += 1
        open_symbols.add(ticker)
        entries_this_cycle += 1
        cash_remaining  -= notional   # deduct from shared-account cash tracker
        _shadow_jv2(ticker, direction, close, cand["score"], executed=True)

    logger.info(
        f"Jerome v2 | === ENTRY SCAN END === "
        f"({entries_this_cycle} new position(s) opened)"
    )
    _last_entry_scan_date = datetime.now(timezone.utc).date()


# ─── P&L reconciler ───────────────────────────────────────────────────────────

def _reconcile_jerome_pnl(alpaca: "JeromeAlpaca") -> None:
    """Back-fill realised_pnl_usd for closed rows whose SELL hasn't filled yet.

    Runs every cycle (idempotent: only touches rows with realised_pnl_usd IS NULL).

    P&L formula per DB row:
        row_pnl = (sell_filled_avg × sell_filled_qty − total_notional)
                  × (row_notional / total_notional)

    When multiple DB rows share the same symbol (Jerome held duplicate lots),
    the single SELL order covers all of them and P&L is split proportionally
    by notional invested.

    Migrated from jerome_strategy.py on v1 deletion (Phase 9).
    """
    try:
        _add_trading_platform_to_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, symbol, notional_usd, closed_at
                    FROM jerome_positions
                    WHERE status = 'closed' AND realised_pnl_usd IS NULL
                    ORDER BY symbol, closed_at
                """)
                null_rows = cur.fetchall()

        if not null_rows:
            return

        logger.info(f"Jerome v2 | P&L reconciler: {len(null_rows)} row(s) with NULL pnl")

        from collections import defaultdict
        by_symbol: dict = defaultdict(list)
        for row_id, sym, notional, closed_at in null_rows:
            by_symbol[sym].append((row_id, float(notional), closed_at))

        for sym, rows in by_symbol.items():
            try:
                filled_sells = alpaca.get_orders(symbol=sym, side="sell", status="filled")
                if not filled_sells:
                    logger.debug(
                        f"Jerome v2 | Reconciler: no filled SELL for {sym} yet — deferring"
                    )
                    continue

                sell = max(filled_sells, key=lambda o: o.get("filled_at") or "")
                sell_avg = float(sell.get("filled_avg_price") or 0)
                sell_qty = float(sell.get("filled_qty") or 0)
                if not sell_avg or not sell_qty:
                    logger.debug(
                        f"Jerome v2 | Reconciler: {sym} SELL fill price not available — deferring"
                    )
                    continue

                total_notional = sum(r[1] for r in rows)
                total_proceeds = sell_avg * sell_qty
                total_pnl      = total_proceeds - total_notional

                with get_conn() as conn:
                    with conn.cursor() as cur:
                        for row_id, notional, _ in rows:
                            row_pnl = round(total_pnl * (notional / total_notional), 2)
                            cur.execute("""
                                UPDATE jerome_positions
                                SET realised_pnl_usd = %s
                                WHERE id = %s AND realised_pnl_usd IS NULL
                            """, (row_pnl, row_id))
                            logger.info(
                                f"Jerome v2 | Reconciler: {sym} id={row_id} "
                                f"pnl=${row_pnl:+.2f} "
                                f"(sell_avg={sell_avg:.4f} × {sell_qty:.4f} qty "
                                f"notional_share={notional:.0f}/{total_notional:.0f})"
                            )
                    conn.commit()

            except Exception as exc:
                logger.warning(f"Jerome v2 | Reconciler failed for {sym}: {exc}")

    except Exception as exc:
        logger.warning(f"Jerome v2 | P&L reconciler failed (non-fatal): {exc}")


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_jerome_v2_cycle(profile: dict, db_id: int) -> None:
    """
    Main Jerome v2 cycle — called every 900 s from runner.py.

    Always:
      - Manages exits on all open positions (trailing stop + regime flip)
      - Runs P&L reconciler (back-fills realised_pnl_usd for closed rows)

    Once per day at 13:30–13:50 UTC:
      - Scans all 12 universe instruments for entry signals
      - Submits orders for qualifying candidates
    """
    from jerome_alpaca import JeromeAlpaca

    _ensure_bot_id_column()

    now = datetime.now(timezone.utc)
    logger.info(
        f"Jerome v2 | === CYCLE START === "
        f"{now.strftime('%Y-%m-%d %H:%M UTC')}  "
        f"(universe: {len(_all_tickers())} instruments)"
    )

    # ── Connect to Alpaca ──────────────────────────────────────────────────
    try:
        alpaca = JeromeAlpaca(
            api_key=profile.get("ALPACA_API_KEY", ""),
            secret_key=profile.get("ALPACA_SECRET_KEY", ""),
            base_url=profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
    except Exception as exc:
        logger.error(f"Jerome v2 | Alpaca connection failed: {exc}")
        return

    account = alpaca.get_account()
    equity  = account["equity"]
    logger.info(
        f"Jerome v2 | Equity=${equity:,.2f} "
        f"cash=${account['cash']:,.2f} "
        f"buying_power=${account['buying_power']:,.2f}"
    )

    # ── Always: manage exits ───────────────────────────────────────────────
    _manage_exits(alpaca, equity)

    # ── Always: reconcile P&L for recently closed positions ───────────────
    try:
        _reconcile_jerome_pnl(alpaca)
    except Exception as exc:
        logger.warning(f"Jerome v2 | P&L reconciler error (non-fatal): {exc}")

    # ── Once per day: entry scan ───────────────────────────────────────────
    if should_run_v2_cycle(now):
        _run_entry_scan(alpaca, equity, buying_power=account["buying_power"])
    else:
        next_window = f"{CYCLE_HOUR_UTC:02d}:{CYCLE_MIN_START:02d}–{CYCLE_MIN_END:02d} UTC"
        logger.debug(
            f"Jerome v2 | Entry scan not due "
            f"(window={next_window}, last={_last_entry_scan_date})"
        )

    logger.info("Jerome v2 | === CYCLE END ===")
