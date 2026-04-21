"""
Stock Trend Follower v1.0 — Oracle Strategy Replacement
---------------------------------------------------------
Replaces Oracle Pure Momentum Scanner v3.1 entirely.

Strategy: EMA20/EMA50 crossover + ADX(14) strength filter + 10-day momentum
confirmation.  No composite scoring.  No stale rotation.  Trend following only.

Signal — LONG (all must be true):
  • EMA20 > EMA50          — uptrend confirmed
  • ADX(14) ≥ 25           — strong trend, not choppy noise
  • 10-day return positive  — momentum confirms direction
  • RSI(14) 40–75           — not overbought, not a bottom pick
  • Price > EMA20           — price is in the trend, not lagging
  • Not already in a position

Signal — SHORT (all must be true):
  • EMA20 < EMA50
  • ADX(14) ≥ 25
  • 10-day return negative
  • RSI(14) 25–60
  • Price < EMA20
  • Shortable + easy-to-borrow via Alpaca
  • Not already in a position

Position Sizing (ATR-based):
  risk_amount    = equity × 1.5%
  stop_distance  = ATR(14) × 2.0
  shares         = risk_amount / stop_distance
  position_value = shares × price
  kelly_fraction = min(position_value / equity, 20%)

Trailing Stop:
  Activates after profit ≥ ATR × 1.5.
  Trails at ATR × 2.0 from best price.
  Managed each cycle by oracle_exit_manager.py.

Exit Conditions (oracle_exit_manager.py):
  1. Trailing stop hit (immediate — overrides min hold)
  2. EMA20 crosses back through EMA50 (trend reversal)
  3. ADX < 20 (trend dying)
  4. Position held ≥ 15 trading days (max hold)
  Minimum hold: 4 hours before signal-based exits fire.

Maximum simultaneous: 5 longs + 2 shorts = 7 total.
"""

from __future__ import annotations

import json
from typing import Optional

from loguru import logger

from data.yfinance_client import get_cached_momentum_data


# ── Strategy constants ────────────────────────────────────────────────────────
STRATEGY_NAME    = "Stock Trend Follower v1.0"

MAX_LONG_SLOTS   = 5
MAX_SHORT_SLOTS  = 2

EMA_FAST         = 20     # EMA20
EMA_SLOW         = 50     # EMA50

ADX_PERIOD       = 14
ADX_ENTRY_MIN    = 25.0   # must be above this to enter
ADX_EXIT_MIN     = 20.0   # exit when ADX falls below this (used by exit manager)

ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.0    # stop = ATR × 2.0 below/above entry

TRAIL_TRIGGER    = 1.5    # trailing stop activates after profit ≥ ATR × 1.5

RISK_PER_TRADE   = 0.015  # 1.5% of equity per trade
MAX_POSITION_PCT = 0.20   # hard cap 20% per position

LONG_RSI_LOW     = 40.0
LONG_RSI_HIGH    = 75.0
SHORT_RSI_LOW    = 25.0
SHORT_RSI_HIGH   = 60.0

MOMENTUM_DAYS    = 10     # n-day return for momentum confirmation


# ── Technical indicator helpers (self-contained, no external import) ──────────

def _ema(closes: list[float], period: int) -> float | None:
    """EMA seeded by SMA, returns current value or None if insufficient data."""
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
    return ema


def _adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    """Average Directional Index — returns 0.0 on insufficient data."""
    if len(highs) < period * 2 + 1:
        return 0.0
    try:
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        trs: list[float] = []
        for i in range(1, len(highs)):
            up   = highs[i] - highs[i - 1]
            down = lows[i - 1] - lows[i]
            plus_dm.append(up   if (up > down   and up   > 0) else 0.0)
            minus_dm.append(down if (down > up   and down > 0) else 0.0)
            hl  = highs[i] - lows[i]
            hpc = abs(highs[i] - closes[i - 1])
            lpc = abs(lows[i]  - closes[i - 1])
            trs.append(max(hl, hpc, lpc))

        def _smooth(series: list[float], p: int) -> list[float]:
            r = [sum(series[:p]) / p]
            for v in series[p:]:
                r.append(r[-1] - r[-1] / p + v)
            return r

        sm_tr  = _smooth(trs,      period)
        sm_pdm = _smooth(plus_dm,  period)
        sm_mdm = _smooth(minus_dm, period)

        di_plus  = [(sm_pdm[i] / sm_tr[i] * 100) if sm_tr[i] > 0 else 0.0 for i in range(len(sm_tr))]
        di_minus = [(sm_mdm[i] / sm_tr[i] * 100) if sm_tr[i] > 0 else 0.0 for i in range(len(sm_tr))]

        dx_list: list[float] = []
        for i in range(len(di_plus)):
            denom = di_plus[i] + di_minus[i]
            dx_list.append(abs(di_plus[i] - di_minus[i]) / denom * 100 if denom > 0 else 0.0)

        if len(dx_list) < period:
            return 0.0
        return min(100.0, max(0.0, sum(dx_list[-period:]) / period))
    except Exception:
        return 0.0


def _atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    """Wilder-smoothed ATR. Returns 0.0 on insufficient data."""
    if len(highs) < period + 1:
        return (highs[-1] - lows[-1]) if len(highs) > 1 else 0.0
    trs: list[float] = []
    for i in range(1, len(highs)):
        hl  = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i]  - closes[i - 1])
        trs.append(max(hl, hpc, lpc))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _kelly_from_atr(equity: float, atr: float, price: float) -> float:
    """
    Compute kelly_fraction (position / equity) from ATR-based risk sizing.
    risk_amount = equity × 1.5% → shares = risk_amount / (ATR × 2.0)
    position_value = shares × price → fraction = min(pv / equity, 20%)
    """
    if atr <= 0 or price <= 0 or equity <= 0:
        if atr <= 0:
            logger.warning(
                f"AlgoScanner | kelly_from_atr: ATR={atr} for price={price:.4f} — "
                f"signal will be silently skipped by executor (zero kelly). "
                f"Check yfinance data quality for this ticker."
            )
        return 0.0
    risk_amount    = equity * RISK_PER_TRADE
    stop_distance  = atr * ATR_MULTIPLIER
    shares         = risk_amount / stop_distance
    position_value = shares * price
    return min(position_value / equity, MAX_POSITION_PCT)


# ── Scan log persistence ──────────────────────────────────────────────────────

def _persist_scan_log(
    universe_loaded: int,
    with_data: int,
    passed_adx: int,
    passed_rsi: int,
    passed_ema_cross: int,
    long_signals: int,
    short_signals: int,
    top5_long: list,
    top5_short: list,
    scan_note: str | None = None,
) -> None:
    """Write one diagnostic row to oracle_scan_log (non-fatal if DB unavailable)."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO oracle_scan_log
                        (universe_loaded, with_data, passed_score, passed_rsi,
                         passed_ema, long_signals, short_signals,
                         top5_long, top5_short, scan_note)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        universe_loaded, with_data,
                        passed_adx,       # reuse passed_score slot for ADX pass count
                        passed_rsi,       # RSI + momentum + price filter count
                        passed_ema_cross, # EMA crossover count
                        long_signals, short_signals,
                        json.dumps(top5_long), json.dumps(top5_short),
                        scan_note,
                    ),
                )
        logger.debug(
            f"Oracle STF | scan_log: universe={universe_loaded} data={with_data} "
            f"ema_cross={passed_ema_cross} adx={passed_adx} rsi={passed_rsi} "
            f"longs={long_signals} shorts={short_signals}"
        )
    except Exception as exc:
        logger.warning(f"Oracle STF | scan_log persist failed (non-fatal): {exc}")


# ── Core scan ─────────────────────────────────────────────────────────────────

def scan_trend_signals(
    momentum_data: dict,
    open_symbols: set[str] | None = None,
    equity: float = 100_000.0,
) -> dict:
    """
    Stock Trend Follower v1.0 scan.

    Returns
    -------
    dict with:
        long_signals   : list[dict]  — up to 5 long entry candidates
        short_signals  : list[dict]  — up to 2 short entry candidates
        top5_long      : list[dict]  — top 5 qualifying longs for reporting
        top5_short     : list[dict]  — top 5 qualifying shorts for reporting
        universe_size  : int
        filter_stages  : dict        — per-stage counts for diagnostics
    """
    open_symbols = open_symbols or set()
    by_ticker    = momentum_data.get("by_ticker", {})
    universe_loaded = len(by_ticker)

    # ── Stage 1: compute indicators for every ticker ──────────────────────────
    candidates: list[dict] = []
    skipped_no_data = 0

    for ticker, d in by_ticker.items():
        if "error" in d:
            skipped_no_data += 1
            continue

        closes = d.get("closes") or []
        bars   = d.get("bars")   or []
        price  = d.get("latest_price")
        rsi    = d.get("rsi_14d")

        # Need at least EMA_SLOW + 5 bars for reliable EMA50
        if len(closes) < EMA_SLOW + 5 or price is None:
            skipped_no_data += 1
            continue

        highs = [float(b["h"]) for b in bars] if bars else []
        lows  = [float(b["l"]) for b in bars] if bars else []

        ema20 = _ema(closes, EMA_FAST)
        ema50 = _ema(closes, EMA_SLOW)
        adx   = _adx(highs, lows, closes, ADX_PERIOD) if (highs and lows) else 0.0
        atr   = _atr(highs, lows, closes, ATR_PERIOD)  if (highs and lows) else 0.0

        if ema20 is None or ema50 is None or atr <= 0:
            skipped_no_data += 1
            continue

        # EMA crossover direction
        if ema20 > ema50:
            ema_dir = "long"
        elif ema20 < ema50:
            ema_dir = "short"
        else:
            continue  # flat crossover — skip

        # 10-day momentum return
        ret10d = (
            (closes[-1] / closes[-MOMENTUM_DAYS] - 1)
            if len(closes) >= MOMENTUM_DAYS + 1
            else None
        )

        ema_spread_pct = (ema20 - ema50) / ema50 * 100.0

        candidates.append({
            "ticker":     ticker,
            "ema_dir":    ema_dir,
            "ema20":      ema20,
            "ema50":      ema50,
            "ema_spread": ema_spread_pct,
            "adx":        adx,
            "atr":        atr,
            "rsi":        rsi,
            "price":      price,
            "ret10d":     ret10d,
        })

    with_data = len(candidates)
    logger.info(
        f"Oracle STF | Stage 1/4 — universe={universe_loaded} "
        f"with_data={with_data} skipped_errors={skipped_no_data}"
    )

    # ── Stage 2: ADX ≥ 25 (strong confirmed trend) ────────────────────────────
    after_adx   = [c for c in candidates if c["adx"] >= ADX_ENTRY_MIN]
    passed_adx  = len(after_adx)
    logger.info(
        f"Oracle STF | Stage 2/4 — ADX≥{ADX_ENTRY_MIN}: "
        f"passed={passed_adx} dropped={with_data - passed_adx}"
    )

    # ── Stage 3: EMA crossover direction + RSI + 10d momentum + price vs EMA20 ─
    long_cands:  list[dict] = []
    short_cands: list[dict] = []

    for c in after_adx:
        rsi    = c["rsi"]
        ret10d = c["ret10d"]
        price  = c["price"]
        ema20  = c["ema20"]

        if rsi is None or ret10d is None:
            continue

        if c["ema_dir"] == "long":
            if (LONG_RSI_LOW <= rsi <= LONG_RSI_HIGH
                    and ret10d > 0
                    and price > ema20):
                long_cands.append(c)
        else:
            if (SHORT_RSI_LOW <= rsi <= SHORT_RSI_HIGH
                    and ret10d < 0
                    and price < ema20):
                short_cands.append(c)

    passed_rsi = len(long_cands) + len(short_cands)
    logger.info(
        f"Oracle STF | Stage 3/4 — RSI+momentum+price: "
        f"longs={len(long_cands)} shorts={len(short_cands)}"
    )

    # ── Stage 4: exclude already-held positions ───────────────────────────────
    long_fresh  = [c for c in long_cands  if c["ticker"] not in open_symbols]
    short_fresh = [c for c in short_cands if c["ticker"] not in open_symbols]
    logger.info(
        f"Oracle STF | Stage 4/4 — exclude_held({len(open_symbols)}): "
        f"eligible longs={len(long_fresh)} shorts={len(short_fresh)}"
    )

    # Sort by strongest ADX first, then widest EMA spread as tiebreaker
    long_fresh.sort(key=lambda x: (x["adx"], abs(x["ema_spread"])), reverse=True)
    short_fresh.sort(key=lambda x: (x["adx"], abs(x["ema_spread"])), reverse=True)

    # Top-5 for reporting (pre-slot-cap, after all filters)
    top5_long = [
        {
            "ticker":     c["ticker"],
            "ema_spread": round(c["ema_spread"], 3),
            "adx":        round(c["adx"], 1),
            "ret10d_pct": round((c["ret10d"] or 0) * 100, 2),
            "rsi":        round(c["rsi"] or 0, 1),
            "atr":        round(c["atr"], 3),
        }
        for c in long_fresh[:5]
    ]
    top5_short = [
        {
            "ticker":     c["ticker"],
            "ema_spread": round(c["ema_spread"], 3),
            "adx":        round(c["adx"], 1),
            "ret10d_pct": round((c["ret10d"] or 0) * 100, 2),
            "rsi":        round(c["rsi"] or 0, 1),
            "atr":        round(c["atr"], 3),
        }
        for c in short_fresh[:5]
    ]

    # ── Build final signal lists ──────────────────────────────────────────────
    long_signals:  list[dict] = []
    short_signals: list[dict] = []

    for i, c in enumerate(long_fresh[:MAX_LONG_SLOTS]):
        kelly = _kelly_from_atr(equity, c["atr"], c["price"])
        if kelly <= 0:
            logger.warning(
                f"AlgoScanner | Dropping {c['ticker']} from long signals — kelly=0 (ATR={c['atr']:.4f}). "
                f"Signal generated but would be silently skipped by executor."
            )
            continue
        stop_pct = -round(c["atr"] * ATR_MULTIPLIER / c["price"], 4)
        long_signals.append({
            "slot":             i + 1,
            "ticker":           c["ticker"],
            "side":             "long",
            "asset_class":      "momentum_equity",
            "conviction_score": min(round(c["adx"] / 100.0, 2), 0.99),
            "kelly_fraction":   round(kelly, 4),
            "stop_loss_pct":    stop_pct,
            "take_profit_pct":  0.999,   # No fixed TP — trend following exit
            "thesis": (
                f"STF Long #{i+1}: EMA20/EMA50 spread={c['ema_spread']:+.2f}% "
                f"ADX={c['adx']:.1f} 10d={c['ret10d']*100:+.1f}% "
                f"RSI={c['rsi']:.0f} price={c['price']:.2f} ATR={c['atr']:.3f} "
                f"stop_dist={c['atr']*ATR_MULTIPLIER:.3f} ({abs(stop_pct):.1%})"
            ),
            "atr":           round(c["atr"], 4),
            "stop_distance": round(c["atr"] * ATR_MULTIPLIER, 4),
        })
        logger.info(
            f"  LONG  → {c['ticker']:10s} | kelly={kelly:.1%} "
            f"ATR={c['atr']:.2f} stop={abs(stop_pct):.1%} "
            f"ADX={c['adx']:.1f} spread={c['ema_spread']:+.2f}%"
        )

    for i, c in enumerate(short_fresh[:MAX_SHORT_SLOTS]):
        kelly = _kelly_from_atr(equity, c["atr"], c["price"])
        if kelly <= 0:
            logger.warning(
                f"AlgoScanner | Dropping {c['ticker']} from short signals — kelly=0 (ATR={c['atr']:.4f}). "
                f"Signal generated but would be silently skipped by executor."
            )
            continue
        stop_pct = round(c["atr"] * ATR_MULTIPLIER / c["price"], 4)
        short_signals.append({
            "slot":             i + 1,
            "ticker":           c["ticker"],
            "side":             "short",
            "asset_class":      "momentum_short",
            "conviction_score": min(round(c["adx"] / 100.0, 2), 0.99),
            "kelly_fraction":   round(kelly, 4),
            "stop_loss_pct":    -stop_pct,   # negative for short means above entry
            "take_profit_pct":  0.999,
            "thesis": (
                f"STF Short #{i+1}: EMA20/EMA50 spread={c['ema_spread']:+.2f}% "
                f"ADX={c['adx']:.1f} 10d={c['ret10d']*100:+.1f}% "
                f"RSI={c['rsi']:.0f} price={c['price']:.2f} ATR={c['atr']:.3f} "
                f"stop_dist={c['atr']*ATR_MULTIPLIER:.3f} ({stop_pct:.1%})"
            ),
            "atr":           round(c["atr"], 4),
            "stop_distance": round(c["atr"] * ATR_MULTIPLIER, 4),
        })
        logger.info(
            f"  SHORT → {c['ticker']:10s} | kelly={kelly:.1%} "
            f"ATR={c['atr']:.2f} stop={stop_pct:.1%} "
            f"ADX={c['adx']:.1f} spread={c['ema_spread']:+.2f}%"
        )

    scan_note = None if (long_signals or short_signals) else "no_signals_after_all_filters"
    _persist_scan_log(
        universe_loaded=universe_loaded,
        with_data=with_data,
        passed_adx=passed_adx,
        passed_rsi=passed_rsi,
        passed_ema_cross=with_data,   # all with_data tickers were checked for crossover
        long_signals=len(long_signals),
        short_signals=len(short_signals),
        top5_long=top5_long,
        top5_short=top5_short,
        scan_note=scan_note,
    )

    logger.info(
        f"Oracle STF | Scan complete: universe={universe_loaded} → "
        f"data={with_data} → adx={passed_adx} → rsi+mom={passed_rsi} → "
        f"longs={len(long_signals)} shorts={len(short_signals)}"
    )

    return {
        "long_signals":  long_signals,
        "short_signals": short_signals,
        "top5_long":     top5_long,
        "top5_short":    top5_short,
        "universe_size": universe_loaded,
        "filter_stages": {
            "universe_loaded": universe_loaded,
            "with_data":       with_data,
            "passed_adx":      passed_adx,
            "passed_rsi":      passed_rsi,
        },
    }


def run_algo_scan(
    regime: str = "trend",
    vix: Optional[float] = None,
    veto_tickers: Optional[set[str]] = None,
    open_symbols: Optional[set[str]] = None,
    equity: float = 100_000.0,
) -> dict:
    """
    Main entry point — called from pipeline.py every 15-min market cycle.

    Parameters
    ----------
    regime       : ignored (kept for API compat)
    vix          : informational only
    veto_tickers : ignored — trend strategy doesn't use veto
    open_symbols : currently held tickers to exclude from new signals
    equity       : current portfolio equity for ATR sizing

    Returns
    -------
    dict compatible with existing pipeline/executor interface:
        regime, signals, short_signals, top5_long, top5_short,
        activated, scan_type, active_signals, universe_scanned, filter_stages
    """
    momentum_data = get_cached_momentum_data()

    if momentum_data is None or not momentum_data.get("by_ticker"):
        logger.warning(
            "AlgoScanner STF | No momentum data in cache — "
            "fetch_momentum_universe() must be called before run_algo_scan()."
        )
        _persist_scan_log(
            universe_loaded=0, with_data=0, passed_adx=0, passed_rsi=0,
            passed_ema_cross=0, long_signals=0, short_signals=0,
            top5_long=[], top5_short=[],
            scan_note="no_cache: fetch_momentum_universe() not called",
        )
        return {
            "regime":           "trend",
            "signals":          [],
            "short_signals":    [],
            "top5_long":        [],
            "top5_short":       [],
            "activated":        False,
            "scan_type":        "no_data",
            "active_signals":   0,
            "universe_scanned": 0,
            "filter_stages":    {},
        }

    result       = scan_trend_signals(momentum_data, open_symbols=open_symbols or set(), equity=equity)
    long_signals = result["long_signals"]
    short_signals = result["short_signals"]
    stages       = result["filter_stages"]

    fetched  = momentum_data.get("fetched",       stages.get("universe_loaded", 0))
    universe = momentum_data.get("universe_size", fetched)

    logger.info(
        f"Oracle STF | run_algo_scan: universe={universe} fetched={fetched} "
        f"longs={len(long_signals)} shorts={len(short_signals)}"
    )

    return {
        "regime":           "trend",
        "signals":          long_signals,
        "short_signals":    short_signals,
        "top5_long":        result["top5_long"],
        "top5_short":       result["top5_short"],
        "activated":        bool(long_signals or short_signals),
        "scan_type":        "stock_trend_follower_v1",
        "active_signals":   len(long_signals),
        "universe_scanned": fetched,
        "filter_stages":    stages,
    }
