"""
Algorithmic Short Scanner — Bear Market Profit Engine
------------------------------------------------------
v1.0 — Standalone mean-reversion short scanner for equity ETFs.

Activated ONLY when the Alpaca platform's current regime is Bear/RISK-OFF.
Mirrors the Kraken bot's mean-reversion signal logic on hourly equity data.

Signal Logic
------------
  Universe: SPY, QQQ, XLK, XLF, XLE, IWM (hardcoded — no LLM)
  Entry: Z-score > 2.0 AND RSI(14) > 68 on last 20 hourly bars
  Sizing: 1% equity risk / ATR stop-distance; hard cap 15% equity per position
  Borrow: check_shortable() must return (True, True)
  Margin: buying_power >= notional required; no debt allowed
  Double-dip: no QQQ short if SQQQ held; no SPY short if SPXS held; no IWM if SRTY held
  Max exposure: sum of algo short market values ≤ 35% of equity

Exit Logic
----------
  Mean-reversion: Z-score < 0.3 (price returned to mean)
  Trailing 5%: if price rises 5% above best (lowest) price since entry → cover
  Hard stop: ATR-based stop-buy order placed at fill (via ratchet_stop.initialise_ratchet_stop)

Integration
-----------
  Called from pipeline.py after execute_allocations(), passing:
    - regime str
    - allocation RegimeAnalysisOutput (for double-dip check)
    - dry_run bool
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from loguru import logger

# ── Constants ────────────────────────────────────────────────────────────────

SHORT_UNIVERSE: list[str] = ["SPY", "QQQ", "XLK", "XLF", "XLE", "IWM"]

# Regime labels that activate the scanner
_BEAR_REGIMES: frozenset[str] = frozenset(
    {"Bear", "RISK-OFF", "Risk-Off", "bear", "risk-off"}
)

ZSCORE_ENTRY_THRESHOLD: float = 1.5    # Z-score above this signals over-extension
RSI_ENTRY_THRESHOLD:    float = 62.0   # RSI above this confirms overbought
ZSCORE_EXIT_THRESHOLD:  float = 0.3    # Z-score below this → mean reversion complete
TRAILING_EXIT_PCT:      float = 0.05   # Exit if price rises 5% above best entry low
MAX_SHORT_EXPOSURE_PCT: float = 0.35   # Max 35% of equity in algo shorts combined
RISK_PER_TRADE_PCT:     float = 0.01   # 1% of equity at risk per short trade
MAX_POSITION_PCT:       float = 0.15   # 15% of equity max per short position
LOOKBACK_HOURS:         int   = 20     # Hourly bars for signal calculation
ATR_PERIOD:             int   = 14     # ATR lookback for stop placement

# Double-dip prevention: if LLM holds inverse ETF, skip shorting its underlying
_DOUBLE_DIP_MAP: dict[str, str] = {
    "QQQ": "SQQQ",
    "SPY": "SPXS",
    "IWM": "SRTY",
}


# ── State tracking for open algo shorts ─────────────────────────────────────
# In-memory tracking of algo short positions; survives individual scan calls
# but resets on process restart. The Alpaca positions list is the authoritative
# source of truth — we use this dict for best-price tracking (trailing exit).

_algo_short_state: dict[str, dict] = {}
# Format: { "SPY": { "entry_price": float, "qty": int, "best_price": float, "entered_at": str } }


def _load_short_state() -> None:
    """Load persisted algo short positions from DB on startup."""
    global _algo_short_state
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS algo_short_positions (
                        symbol TEXT PRIMARY KEY,
                        entry_price DOUBLE PRECISION NOT NULL,
                        qty INTEGER NOT NULL,
                        best_price DOUBLE PRECISION NOT NULL,
                        entered_at TEXT NOT NULL,
                        order_id TEXT
                    )
                """)
                cur.execute("SELECT symbol, entry_price, qty, best_price, entered_at, order_id FROM algo_short_positions")
                rows = cur.fetchall()
                for row in rows:
                    _algo_short_state[row[0]] = {
                        "entry_price": row[1], "qty": row[2],
                        "best_price": row[3], "entered_at": row[4], "order_id": row[5],
                    }
            conn.commit()
        if _algo_short_state:
            logger.info(f"ShortScanner | Loaded {len(_algo_short_state)} persisted short position(s) from DB")
    except Exception as exc:
        logger.warning(f"ShortScanner | Failed to load short state from DB: {exc}")


def _save_short_position(symbol: str, state: dict) -> None:
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO algo_short_positions (symbol, entry_price, qty, best_price, entered_at, order_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol) DO UPDATE SET
                        best_price = EXCLUDED.best_price,
                        entered_at = EXCLUDED.entered_at
                """, (symbol, state["entry_price"], state["qty"],
                      state["best_price"], state["entered_at"], state.get("order_id")))
            conn.commit()
    except Exception as exc:
        logger.debug(f"ShortScanner | State save failed for {symbol}: {exc}")


def _delete_short_position(symbol: str) -> None:
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM algo_short_positions WHERE symbol = %s", (symbol,))
            conn.commit()
    except Exception as exc:
        logger.debug(f"ShortScanner | State delete failed for {symbol}: {exc}")


# Load persisted state on module import
_load_short_state()


# ── Signal computation ───────────────────────────────────────────────────────

def _fetch_hourly_bars(ticker: str, n_bars: int = LOOKBACK_HOURS) -> Optional[list[float]]:
    """
    Fetch the last n_bars of hourly close prices from Alpaca's data API.
    Returns a list of floats (oldest first), or None on failure.
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from datetime import timedelta
        from config.settings import settings

        client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=n_bars * 3)  # extra buffer for market closed hours

        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Hour,
            start=start,
            end=end,
        )
        bars = client.get_stock_bars(req)
        if not bars or ticker not in bars:
            return None

        closes = [float(b.close) for b in bars[ticker]]
        if len(closes) < n_bars:
            logger.debug(f"ShortScanner | {ticker}: only {len(closes)} hourly bars (need {n_bars})")
            return None
        return closes[-n_bars:]   # last n_bars only
    except Exception as exc:
        logger.warning(f"ShortScanner | Hourly bar fetch failed for {ticker}: {exc}")
        return None


def _compute_zscore(closes: list[float]) -> float:
    """Z-score of the last close relative to the window."""
    arr = np.array(closes, dtype=float)
    mean = np.mean(arr)
    std  = np.std(arr)
    if std < 1e-8:
        return 0.0
    return float((arr[-1] - mean) / std)


def _compute_rsi(closes: list[float], period: int = ATR_PERIOD) -> float:
    """Wilder's RSI with recursive smoothing — consistent with algo_scanner.py and Kraken bots."""
    if len(closes) < period + 1:
        return 50.0

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes]
    losses = [abs(min(c, 0.0)) for c in changes]

    # Seed with simple average of first `period` bars
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's recursive smoothing for remaining bars
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _compute_atr(closes: list[float]) -> float:
    """Simple ATR approximation using daily closes (hourly here)."""
    if len(closes) < 2:
        return 0.0
    tr_list = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    if not tr_list:
        return 0.0
    period = min(ATR_PERIOD, len(tr_list))
    return float(np.mean(tr_list[-period:]))


def _compute_signals(ticker: str) -> Optional[dict]:
    """
    Compute Z-score, RSI, and ATR for a ticker using the last 20 hourly bars.
    Returns None if data is unavailable.
    """
    closes = _fetch_hourly_bars(ticker, LOOKBACK_HOURS)
    if closes is None:
        return None

    zscore = _compute_zscore(closes)
    rsi    = _compute_rsi(closes, ATR_PERIOD)
    atr    = _compute_atr(closes)

    return {
        "ticker":        ticker,
        "close":         closes[-1],
        "zscore":        round(zscore, 3),
        "rsi":           round(rsi, 2),
        "atr":           round(atr, 4),
        "entry_signal":  zscore > ZSCORE_ENTRY_THRESHOLD and rsi > RSI_ENTRY_THRESHOLD,
        "exit_signal":   zscore < ZSCORE_EXIT_THRESHOLD,
    }


# ── Position sizing ──────────────────────────────────────────────────────────

def _compute_short_size(equity: float, price: float, atr: float) -> int:
    """
    Risk-based position sizing for a short entry.
    Risk per trade = 1% of equity.
    Stop distance = 2× ATR (the buy-to-cover stop is placed 2× ATR above fill).
    Returns whole number of shares (math.floor).
    Returns 0 if floor(notional/price) < 1 — caller must skip the entry.
    """
    stop_distance = max(2.0 * atr, price * 0.01)   # guard: at least 1% of price
    risk_dollars = equity * RISK_PER_TRADE_PCT
    notional = risk_dollars / (stop_distance / price)  # notional = risk / (stop_pct)
    max_notional = equity * MAX_POSITION_PCT
    notional = min(notional, max_notional)
    return math.floor(notional / price)  # returns 0 if floor < 1 — caller skips


# ── Double-dip prevention ────────────────────────────────────────────────────

def _check_double_dip(
    ticker: str,
    llm_tickers: set[str],
    held_symbols: set[str] | None = None,
) -> bool:
    """
    Returns True if shorting *ticker* would double-dip with an inverse ETF
    held in EITHER the current LLM allocation OR the live Alpaca account.

    Parameters
    ----------
    ticker       : Symbol the scanner wants to short (e.g. QQQ)
    llm_tickers  : Tickers from the current LLM cycle allocation
    held_symbols : All symbols currently held in Alpaca (from get_positions())
                   — checked in addition to llm_tickers to handle portfolio drift
                   (partial fills, manual trades, latency between cycles)
    """
    inverse = _DOUBLE_DIP_MAP.get(ticker)
    if not inverse:
        return False

    if inverse in llm_tickers:
        logger.info(
            f"ShortScanner | Skipping SHORT {ticker} — LLM allocated {inverse} "
            f"(double-dip prevention)"
        )
        return True

    if held_symbols and inverse in held_symbols:
        logger.info(
            f"ShortScanner | Skipping SHORT {ticker} — {inverse} currently held "
            f"in Alpaca account (double-dip prevention; portfolio may have drifted from LLM allocation)"
        )
        return True

    return False


# ── Exposure check ───────────────────────────────────────────────────────────

def _get_short_exposure(positions: list[dict], equity: float) -> tuple[float, float]:
    """
    Returns (total_short_usd, short_pct) for currently open short positions.
    Includes ALL short positions in the Alpaca account (algo + any others).
    """
    short_positions = [
        p for p in positions
        if str(p.get("side", "long")).lower() == "short"
    ]
    total_short_usd = sum(abs(float(p.get("market_value", 0.0))) for p in short_positions)
    short_pct = total_short_usd / max(equity, 1.0)
    return total_short_usd, short_pct


# ── Entry logic ──────────────────────────────────────────────────────────────

def _try_enter_short(
    ticker: str,
    signals: dict,
    equity: float,
    positions: list[dict],
    llm_tickers: set[str],
    held_symbols: set[str] | None = None,
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Attempt to open a short position on *ticker*.
    Returns result dict on success, None if skipped.
    """
    price = signals["close"]
    atr   = signals["atr"]

    # Guard: skip if already short this ticker
    current_shorts = {
        p["symbol"] for p in positions
        if str(p.get("side", "long")).lower() == "short"
    }
    if ticker in current_shorts:
        logger.debug(f"ShortScanner | {ticker} already held short — skipping re-entry")
        return None

    # Guard: double-dip (checks both LLM allocation AND actual held positions)
    if _check_double_dip(ticker, llm_tickers, held_symbols=held_symbols):
        return None

    # Guard: max short exposure
    total_short_usd, short_pct = _get_short_exposure(positions, equity)
    if short_pct >= MAX_SHORT_EXPOSURE_PCT:
        logger.warning(
            f"ShortScanner | {ticker} — short exposure cap reached "
            f"({short_pct:.1%} ≥ {MAX_SHORT_EXPOSURE_PCT:.0%}) — skipping"
        )
        return None

    # Borrow check
    from execution.broker import check_shortable, get_account
    shortable, easy_to_borrow = check_shortable(ticker)
    if not shortable or not easy_to_borrow:
        logger.info(
            f"ShortScanner | {ticker} not shortable "
            f"(shortable={shortable}, etb={easy_to_borrow}) — skipping"
        )
        return None

    # Sizing: skip if floor(notional/price) < 1 share
    qty = _compute_short_size(equity, price, atr)
    if qty < 1:
        logger.info(
            f"ShortScanner | {ticker} — qty < 1 share at current sizing "
            f"(equity=${equity:,.0f}, price=${price:.2f}) — skipping"
        )
        return None

    # Margin check
    acct = get_account()
    buying_power = float(acct.get("buying_power", 0.0))
    notional_required = qty * price
    if buying_power < notional_required:
        logger.warning(
            f"ShortScanner | {ticker} — insufficient buying power "
            f"(need ${notional_required:,.0f}, have ${buying_power:,.0f}) — skipping"
        )
        return None

    # Pre-exposure check (would adding this breach the cap?)
    if (total_short_usd + notional_required) / equity > MAX_SHORT_EXPOSURE_PCT:
        logger.warning(
            f"ShortScanner | {ticker} — would breach exposure cap after entry — skipping"
        )
        return None

    logger.info(
        f"ShortScanner | ENTRY {ticker} SHORT qty={qty} price=${price:.2f} "
        f"z={signals['zscore']:.2f} rsi={signals['rsi']:.1f} atr={atr:.4f} "
        f"{'[DRY-RUN]' if dry_run else ''}"
    )

    if dry_run:
        _algo_short_state[ticker] = {
            "entry_price": price,
            "qty":         qty,
            "best_price":  price,
            "entered_at":  datetime.now(timezone.utc).isoformat(),
            "dry_run":     True,
        }
        _save_short_position(ticker, _algo_short_state[ticker])
        return {
            "action":  "short_entry",
            "ticker":  ticker,
            "qty":     qty,
            "price":   price,
            "dry_run": True,
        }

    try:
        from execution.broker import place_short_order
        order = place_short_order(ticker, qty)
        fill_price = float(order.get("fill_price") or price)

        _algo_short_state[ticker] = {
            "entry_price": fill_price,
            "qty":         qty,
            "best_price":  fill_price,
            "entered_at":  datetime.now(timezone.utc).isoformat(),
            "order_id":    order.get("id"),
        }
        _save_short_position(ticker, _algo_short_state[ticker])

        # Place ATR stop-buy above fill
        from execution.ratchet_stop import initialise_ratchet_stop
        stop_result = initialise_ratchet_stop(
            ticker=ticker,
            fill_price=fill_price,
            qty=float(qty),
            dry_run=False,
            side="short",
        )

        # Log to trade journal
        try:
            import uuid
            from analysis.trade_journal import log_trade
            log_trade(
                trade_id=f"short_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                ticker=ticker,
                asset_class="direct_short",
                conviction_score=0.0,
                original_thesis=(
                    f"Algo short ENTRY: Z={signals['zscore']:.2f} "
                    f"RSI={signals['rsi']:.1f} qty={qty} fill=${fill_price:.2f} "
                    f"(thresholds Z>{ZSCORE_ENTRY_THRESHOLD} RSI>{RSI_ENTRY_THRESHOLD})"
                ),
                intended_price=price,
            )
        except Exception as log_exc:
            logger.warning(f"ShortScanner | Journal log failed for {ticker}: {log_exc}")

        logger.info(
            f"ShortScanner | SHORT {ticker} entered: qty={qty} fill=${fill_price:.2f} "
            f"stop=${stop_result.get('stop_price', 'n/a'):.4f}"
        )
        return {
            "action":      "short_entry",
            "ticker":      ticker,
            "qty":         qty,
            "fill_price":  fill_price,
            "stop_result": stop_result,
        }

    except Exception as exc:
        logger.error(f"ShortScanner | Short entry failed for {ticker}: {exc}")
        return None


# ── Exit logic ───────────────────────────────────────────────────────────────

def _try_exit_short(
    ticker: str,
    signals: dict,
    positions: list[dict],
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Check exit conditions for an open algo short on *ticker*.
    Returns result dict if exit was triggered, None if position should be held.
    """
    pos = next(
        (p for p in positions
         if p["symbol"] == ticker and str(p.get("side", "long")).lower() == "short"),
        None,
    )
    if pos is None:
        # Position no longer exists (may have been stopped out by GTC stop order)
        if ticker in _algo_short_state:
            logger.info(f"ShortScanner | {ticker} short position gone — removing state")
            _algo_short_state.pop(ticker, None)
            _delete_short_position(ticker)
        return None

    current_price = float(pos.get("current_price", signals["close"]))
    qty = abs(int(float(pos.get("qty", 1))))

    # Update best (lowest) price seen since entry
    state = _algo_short_state.get(ticker, {})
    best_price = state.get("best_price", current_price)
    if current_price < best_price:
        best_price = current_price
        _algo_short_state.setdefault(ticker, {})["best_price"] = best_price

    # Exit condition 1: Mean-reversion complete (Z-score returned to mean)
    mean_revert = signals["zscore"] < ZSCORE_EXIT_THRESHOLD

    # Exit condition 2: Trailing stop — price rose 5% above best (lowest) price
    trailing_triggered = current_price >= best_price * (1.0 + TRAILING_EXIT_PCT)

    reason = None
    if mean_revert:
        reason = f"mean-reversion (Z={signals['zscore']:.2f} < {ZSCORE_EXIT_THRESHOLD})"
    elif trailing_triggered:
        reason = f"trailing exit (price ${current_price:.2f} ≥ best ${best_price:.2f} + {TRAILING_EXIT_PCT:.0%})"

    if reason is None:
        logger.debug(
            f"ShortScanner | {ticker} SHORT holding — "
            f"Z={signals['zscore']:.2f} price=${current_price:.2f} best=${best_price:.2f}"
        )
        return None

    logger.warning(
        f"ShortScanner | EXIT {ticker} SHORT — {reason} "
        f"{'[DRY-RUN]' if dry_run else ''}"
    )

    if dry_run:
        _algo_short_state.pop(ticker, None)
        _delete_short_position(ticker)
        return {"action": "short_exit", "ticker": ticker, "reason": reason, "dry_run": True}

    # Capture entry timestamp BEFORE deletion (needed for time-in-trade calc)
    _entry_ts_iso: str | None = None
    try:
        from db.postgres import get_position_entry_times as _get_pet
        _entry_ts_iso = _get_pet().get(ticker)
    except Exception:
        pass

    try:
        from execution.broker import buy_to_cover
        from execution.ratchet_stop import delete_stop
        from db.postgres import delete_position_entry
        order = buy_to_cover(ticker, qty)
        delete_stop(ticker)
        delete_position_entry(ticker)   # Remove entry timestamp; fresh ts on next open
        _algo_short_state.pop(ticker, None)
        _delete_short_position(ticker)
        logger.info(f"ShortScanner | {ticker} covered: {reason}")

        # ── RAG Memory Phase 2: generate and persist algo-cover lesson ─────
        try:
            from analysis.post_mortem_lessons import (
                generate_lesson as _gen_lesson,
                _load_regime_from_file,
                compute_hours_since,
            )
            from analysis.trade_journal import log_post_mortem as _log_pm
            entry_price = float(pos.get("avg_entry_price") or current_price)
            _pnl_pct = (entry_price - current_price) / entry_price * 100 if entry_price > 0 else 0.0
            _hours    = compute_hours_since(_entry_ts_iso)
            _regime   = _load_regime_from_file()
            _lesson   = _gen_lesson(
                ticker=ticker,
                regime=_regime,
                pnl_pct=_pnl_pct,
                exit_reason="algo_cover",
                time_in_trade_hours=_hours,
                asset_class="direct_short",
            )
            _log_pm(
                ticker=ticker,
                regime=_regime,
                hardcoded_lesson_text=_lesson,
                asset_class="direct_short",
                exit_reason="algo_cover",
                pnl_pct=_pnl_pct,
                time_in_trade_hours=_hours,
            )
            logger.debug(f"ShortScanner | Post-mortem logged for {ticker}: {_lesson[:80]}")
        except Exception as _pm_exc:
            logger.debug(f"ShortScanner | Post-mortem logging failed for {ticker}: {_pm_exc}")

        # Journal log the exit
        try:
            import uuid
            entry_price = float(pos.get("avg_entry_price") or current_price)
            pl = float(pos.get("unrealized_pl", 0.0))
            from analysis.trade_journal import log_trade
            log_trade(
                trade_id=f"short_exit_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                ticker=ticker,
                asset_class="direct_short",
                conviction_score=0.0,
                original_thesis=f"Algo short EXIT: {reason} | entry=${entry_price:.2f} cover=${current_price:.2f} pl=${pl:+.2f}",
                intended_price=current_price,
            )
        except Exception as _log_exc:
            logger.debug(f"ShortScanner | Exit journal log failed for {ticker}: {_log_exc}")

        return {
            "action":  "short_exit",
            "ticker":  ticker,
            "reason":  reason,
            "order":   order,
        }
    except Exception as exc:
        logger.error(f"ShortScanner | buy_to_cover failed for {ticker}: {exc}")
        return None


# ── Main entry point ─────────────────────────────────────────────────────────

def run_scan(
    regime: Optional[str],
    allocation,   # RegimeAnalysisOutput or None
    dry_run: bool = False,
) -> dict:
    """
    Main scanner entry point, called from pipeline.py after execute_allocations().

    Parameters
    ----------
    regime     : current regime string (e.g. "Bear", "Bull", "Sideways")
    allocation : RegimeAnalysisOutput from the LLM (for double-dip check); may be None
    dry_run    : if True, log but do not place real orders

    Returns
    -------
    dict with scan summary: { regime, activated, entries, exits, skips, errors }
    """
    # Activation gate: read market_regime.json first (the authoritative persisted
    # regime written by the pipeline each cycle), then fall back to the passed
    # `regime` argument if the file is missing or unparseable.
    _file_regime: Optional[str] = None
    try:
        from pathlib import Path as _Path
        import json as _json
        _regime_path = _Path(__file__).parent.parent / "data" / "market_regime.json"
        if _regime_path.exists() and _regime_path.stat().st_size > 0:
            _regime_data = _json.loads(_regime_path.read_text())
            _file_regime = str(_regime_data.get("regime", "") or "").strip() or None
    except Exception as _rj_exc:
        logger.debug(f"ShortScanner | market_regime.json read failed: {_rj_exc} — using passed regime")

    regime_str = _file_regime or (str(regime) if regime else "unknown")
    logger.debug(
        f"ShortScanner | regime resolved to '{regime_str}' "
        f"(source: {'market_regime.json' if _file_regime else 'pipeline arg'})"
    )

    result: dict = {
        "regime":    regime_str,
        "activated": False,
        "entries":   [],
        "exits":     [],
        "skips":     [],
        "errors":    [],
    }

    # Activation gate: scanner ONLY runs in Bear/RISK-OFF
    if regime_str not in _BEAR_REGIMES:
        logger.debug(
            f"ShortScanner | regime='{regime_str}' — scanner inactive "
            f"(only activates in Bear/RISK-OFF)"
        )
        return result

    result["activated"] = True
    logger.info(f"ShortScanner | ACTIVATED — regime='{regime_str}' (Bear/RISK-OFF)")

    # Collect LLM-held tickers for double-dip prevention
    llm_tickers: set[str] = set()
    if allocation is not None:
        try:
            llm_tickers = {a.ticker for a in allocation.allocations}
        except Exception:
            pass

    # Fetch current Alpaca state
    try:
        from execution.broker import get_positions, get_account
        positions = get_positions()
        acct      = get_account()
        equity    = float(acct.get("equity", 0.0))
    except Exception as exc:
        logger.error(f"ShortScanner | Failed to fetch Alpaca state: {exc}")
        result["errors"].append(f"account fetch: {exc}")
        return result

    if equity < 1000.0:
        logger.warning("ShortScanner | Equity too low — scanner skipped")
        return result

    # held_symbols = ALL symbols currently held in Alpaca (long OR short).
    # Used by double-dip guard to catch portfolio drift from current LLM allocation
    # (e.g. partial fills, ratchet-triggered exits, latency between cycles).
    held_symbols: set[str] = {p["symbol"] for p in positions}

    logger.info(
        f"ShortScanner | equity=${equity:,.0f} | "
        f"scanning {len(SHORT_UNIVERSE)} tickers: {SHORT_UNIVERSE}"
    )

    # ── Scan each ticker ──────────────────────────────────────────────────────
    for ticker in SHORT_UNIVERSE:
        try:
            signals = _compute_signals(ticker)
            if signals is None:
                result["skips"].append({"ticker": ticker, "reason": "no data"})
                continue

            logger.debug(
                f"ShortScanner | {ticker}: Z={signals['zscore']:.2f} "
                f"RSI={signals['rsi']:.1f} price=${signals['close']:.2f}"
            )

            # ── Exit check for existing shorts ────────────────────────────────
            exit_result = _try_exit_short(ticker, signals, positions, dry_run=dry_run)
            if exit_result is not None:
                result["exits"].append(exit_result)
                # Refresh positions after exit
                if not dry_run:
                    try:
                        positions = get_positions()
                    except Exception:
                        pass
                continue

            # ── Entry check ───────────────────────────────────────────────────
            if signals["entry_signal"]:
                entry_result = _try_enter_short(
                    ticker, signals, equity, positions, llm_tickers,
                    held_symbols=held_symbols, dry_run=dry_run
                )
                if entry_result is not None:
                    result["entries"].append(entry_result)
                    # Refresh positions and equity after entry
                    if not dry_run:
                        try:
                            positions = get_positions()
                            acct_fresh = get_account()
                            equity = float(acct_fresh.get("equity", equity))
                        except Exception:
                            pass
                else:
                    skip_reason = "entry blocked"
                    result["skips"].append({"ticker": ticker, "reason": skip_reason})
                    # Journal-log entry-signal skips (borrow/margin/exposure blocks)
                    try:
                        import uuid
                        from analysis.trade_journal import log_trade
                        log_trade(
                            trade_id=f"short_skip_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                            ticker=ticker,
                            asset_class="direct_short",
                            conviction_score=0.0,
                            original_thesis=(
                                f"Algo short SKIP ({skip_reason}): "
                                f"Z={signals['zscore']:.2f} RSI={signals['rsi']:.1f} "
                                f"price=${signals['close']:.2f}"
                            ),
                            intended_price=signals["close"],
                        )
                    except Exception:
                        pass
            else:
                result["skips"].append({
                    "ticker": ticker,
                    "reason": "signal not met",
                    "z":      signals["zscore"],
                    "rsi":    signals["rsi"],
                })
                logger.debug(
                    f"ShortScanner | SCAN {ticker}: "
                    f"Z={signals['zscore']:.2f} RSI={signals['rsi']:.1f} — signal not met"
                )
                # Journal all scan outcomes (including signal-not-met) for full audit trail
                try:
                    import uuid
                    from analysis.trade_journal import log_trade
                    log_trade(
                        trade_id=f"short_scan_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                        ticker=ticker,
                        asset_class="direct_short",
                        conviction_score=0.0,
                        original_thesis=(
                            f"Algo short SCAN (signal not met): "
                            f"Z={signals['zscore']:.2f} (need >{ZSCORE_ENTRY_THRESHOLD}) "
                            f"RSI={signals['rsi']:.1f} (need >{RSI_ENTRY_THRESHOLD}) "
                            f"price=${signals['close']:.2f}"
                        ),
                        intended_price=signals["close"],
                    )
                except Exception:
                    pass

        except Exception as exc:
            logger.error(f"ShortScanner | Unexpected error on {ticker}: {exc}")
            result["errors"].append(f"{ticker}: {exc}")

    total_short_usd, short_pct = _get_short_exposure(positions, equity)
    logger.info(
        f"ShortScanner | Scan complete — "
        f"entries={len(result['entries'])} exits={len(result['exits'])} "
        f"skips={len(result['skips'])} errors={len(result['errors'])} "
        f"short_exposure=${total_short_usd:,.0f} ({short_pct:.1%})"
    )
    result["short_exposure_usd"] = round(total_short_usd, 2)
    result["short_exposure_pct"] = round(short_pct * 100, 2)

    return result


def get_algo_short_state() -> dict:
    """Return a copy of the current in-memory algo short state (for API/dashboard)."""
    return dict(_algo_short_state)
