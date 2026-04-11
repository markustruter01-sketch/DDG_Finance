"""
Oracle Pure Momentum Scanner v3.0 — Deterministic, No LLM
----------------------------------------------------------
Replaces the regime-switching LLM-dependent scanner with a pure
deterministic momentum ranking system.  No Groq/Gemini calls.
No SGOV.  No JEPQ.  No regime classification.

Strategy
--------
Every 15 minutes during NYSE market hours:
  1. Compute composite_score for all ~250 tickers in the universe:
       score = 5d_return × 0.20 + 20d_return × 0.50 + 60d_return × 0.30
  2. Rank all tickers by composite_score (descending).
  3. Long candidates : top 6 where score > 0, RSI 30–70, price > EMA-20,
                       not already in an open position.
  4. Short candidates: bottom 3 where score < 0, RSI 30–70, price < EMA-20,
                       not already in an open position.

Position Sizing
---------------
  • Fixed 10% of equity per position (kelly_fraction = 0.10) until
    Oracle has 30+ closed trades.
  • After 30 closed trades: half-Kelly capped at 15%.

Stop / Take-Profit (volatility-scaled)
---------------------------------------
  vol_factor  = annualized_vol_20d / 100
  stop_loss   = -clamp(vol_factor × 1.5, 0.04, 0.10)
  take_profit =  clamp(vol_factor × 2.5, 0.06, 0.20)

Oracle Profit Reserve
---------------------
  After every closed winning trade the post-mortem calls
  add_oracle_profit_contribution(profit_usd * 0.15).
  This reserve is NOT invested — it is tracked as a separate ledger
  item in the diagnostic report.

Kill Switch
-----------
  5% daily drawdown trips the kill switch — handled upstream.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from data.yfinance_client import get_cached_momentum_data


MAX_LONG_SLOTS  = 6
MAX_SHORT_SLOTS = 3

RSI_LOWER       = 30.0
RSI_UPPER       = 70.0

FIXED_FRACTION  = 0.10
KELLY_CAP       = 0.15
KELLY_THRESHOLD = 30


def _composite_score(d: dict) -> float:
    ret_5  = d.get("return_5d_pct")  or 0.0
    ret_20 = d.get("return_20d_pct") or 0.0
    ret_60 = d.get("return_60d_pct") or 0.0
    return ret_5 * 0.20 + ret_20 * 0.50 + ret_60 * 0.30


def _stop_take(volatility: Optional[float]) -> tuple[float, float]:
    vol = volatility or 20.0
    vol_factor = max(vol / 100.0, 0.01)
    stop = -round(min(max(vol_factor * 1.5, 0.04), 0.10), 4)
    take =  round(min(max(vol_factor * 2.5, 0.06), 0.20), 4)
    return stop, take


def _get_position_fraction() -> float:
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return FIXED_FRACTION
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM trades "
                    "WHERE status = 'closed' AND bot_source = 'oracle'"
                )
                row = cur.fetchone()
                closed_trades = int(row[0]) if row else 0
    except Exception:
        return FIXED_FRACTION

    if closed_trades < KELLY_THRESHOLD:
        return FIXED_FRACTION

    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE pnl_usd > 0) AS wins,
                        COUNT(*)                             AS total
                    FROM (
                        SELECT pnl_usd FROM trades
                        WHERE status = 'closed' AND bot_source = 'oracle'
                        ORDER BY exit_time DESC
                        LIMIT 30
                    ) last30
                """)
                row = cur.fetchone()
                wins  = int(row[0] or 0)
                total = int(row[1] or 1)
    except Exception:
        wins, total = 0, 1

    win_rate   = wins / total if total > 0 else 0.5
    half_kelly = win_rate - (1.0 - win_rate)
    half_kelly = max(0.05, min(half_kelly, KELLY_CAP))

    logger.info(
        f"Oracle | Kelly sizing: win_rate={win_rate:.1%} "
        f"closed_trades={closed_trades} → kelly={half_kelly:.1%}"
    )
    return half_kelly


def scan_momentum(
    momentum_data: dict,
    open_symbols: set[str] | None = None,
) -> dict:
    """
    Run the pure momentum scan.

    Returns
    -------
    dict with:
        "long_signals"  : list[dict]  — up to 6 long candidates
        "short_signals" : list[dict]  — up to 3 short candidates
        "top5_long"     : list[dict]  — top 5 ranked (pre-filter, for reporting)
        "top5_short"    : list[dict]  — bottom 5 ranked (pre-filter, for reporting)
        "universe_size" : int
    """
    open_symbols = open_symbols or set()
    by_ticker    = momentum_data.get("by_ticker", {})

    scored: list[dict] = []
    for ticker, d in by_ticker.items():
        if "error" in d:
            continue
        score = _composite_score(d)
        rsi   = d.get("rsi_14d")
        price = d.get("latest_price")
        ema20 = d.get("ema_20d")
        vol   = d.get("annualized_volatility_20d_pct")
        scored.append({
            "ticker":     ticker,
            "score":      score,
            "rsi":        rsi,
            "price":      price,
            "ema_20d":    ema20,
            "vol":        vol,
            "return_5d":  d.get("return_5d_pct")  or 0.0,
            "return_20d": d.get("return_20d_pct") or 0.0,
            "return_60d": d.get("return_60d_pct") or 0.0,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    fraction   = _get_position_fraction()
    top5_long  = [{"ticker": c["ticker"], "score": round(c["score"], 3), "rsi": c["rsi"]} for c in scored[:5]]
    top5_short = [{"ticker": c["ticker"], "score": round(c["score"], 3), "rsi": c["rsi"]} for c in scored[-5:]]

    long_signals: list[dict] = []
    for c in scored:
        if len(long_signals) >= MAX_LONG_SLOTS:
            break
        if c["ticker"] in open_symbols:
            continue
        if c["score"] <= 0:
            break
        rsi = c["rsi"]
        if rsi is None or not (RSI_LOWER <= rsi <= RSI_UPPER):
            continue
        price, ema20 = c["price"], c["ema_20d"]
        if price is None or ema20 is None or price <= ema20:
            continue
        stop, take = _stop_take(c["vol"])
        slot_num   = len(long_signals) + 1
        long_signals.append({
            "slot":             slot_num,
            "ticker":           c["ticker"],
            "side":             "long",
            "asset_class":      "momentum_equity",
            "conviction_score": round(min(abs(c["score"]) / 10.0, 0.99), 2),
            "kelly_fraction":   fraction,
            "thesis": (
                f"Momentum long #{slot_num}: score={c['score']:.2f} "
                f"5d={c['return_5d']:+.1f}% 20d={c['return_20d']:+.1f}% "
                f"60d={c['return_60d']:+.1f}% RSI={rsi:.0f} "
                f"price={price:.2f} EMA20={ema20:.2f}"
            ),
            "stop_loss_pct":   stop,
            "take_profit_pct": take,
        })

    short_signals: list[dict] = []
    for c in reversed(scored):
        if len(short_signals) >= MAX_SHORT_SLOTS:
            break
        if c["ticker"] in open_symbols:
            continue
        if c["score"] >= 0:
            break
        rsi = c["rsi"]
        if rsi is None or not (RSI_LOWER <= rsi <= RSI_UPPER):
            continue
        price, ema20 = c["price"], c["ema_20d"]
        if price is None or ema20 is None or price >= ema20:
            continue
        stop, take = _stop_take(c["vol"])
        slot_num   = len(short_signals) + 1
        short_signals.append({
            "slot":             slot_num,
            "ticker":           c["ticker"],
            "side":             "short",
            "asset_class":      "momentum_short",
            "conviction_score": round(min(abs(c["score"]) / 10.0, 0.99), 2),
            "kelly_fraction":   fraction,
            "thesis": (
                f"Momentum short #{slot_num}: score={c['score']:.2f} "
                f"5d={c['return_5d']:+.1f}% 20d={c['return_20d']:+.1f}% "
                f"60d={c['return_60d']:+.1f}% RSI={rsi:.0f} "
                f"price={price:.2f} EMA20={ema20:.2f}"
            ),
            "stop_loss_pct":   stop,
            "take_profit_pct": take,
        })

    return {
        "long_signals":  long_signals,
        "short_signals": short_signals,
        "top5_long":     top5_long,
        "top5_short":    top5_short,
        "universe_size": len(by_ticker),
    }


def run_algo_scan(
    regime: str = "momentum",
    vix: Optional[float] = None,
    veto_tickers: Optional[set[str]] = None,
    open_symbols: Optional[set[str]] = None,
) -> dict:
    """
    Main entry point — called from pipeline.py every 15-min market cycle.

    Parameters
    ----------
    regime       : ignored (kept for API compatibility with old pipeline code)
    vix          : informational only — no regime switching
    veto_tickers : ignored for Oracle — pure deterministic ranking
    open_symbols : set of ticker symbols currently in open positions
                   (these are excluded from new signal candidates)

    Returns
    -------
    dict with:
        "regime"          : "momentum"
        "signals"         : list[dict]  (RegimeAllocationSlot-compatible — long slots)
        "short_signals"   : list[dict]  (short candidates for separate execution)
        "top5_long"       : list[dict]  (top 5 ranked for reporting)
        "top5_short"      : list[dict]  (bottom 5 ranked for reporting)
        "activated"       : bool
        "scan_type"       : "pure_momentum"
        "active_signals"  : int
        "universe_scanned": int
    """
    momentum_data = get_cached_momentum_data()

    if momentum_data is None or not momentum_data.get("by_ticker"):
        logger.warning("AlgoScanner | No momentum data available — returning empty signals")
        return {
            "regime":           "momentum",
            "signals":          [],
            "short_signals":    [],
            "top5_long":        [],
            "top5_short":       [],
            "activated":        False,
            "scan_type":        "no_data",
            "active_signals":   0,
            "universe_scanned": 0,
        }

    result       = scan_momentum(momentum_data, open_symbols=open_symbols or set())
    long_signals  = result["long_signals"]
    short_signals = result["short_signals"]

    fetched   = momentum_data.get("fetched",        len(momentum_data.get("by_ticker", {})))
    universe  = momentum_data.get("universe_size",  fetched)

    logger.info(
        f"Oracle | Pure momentum scan complete: universe={universe} fetched={fetched} "
        f"longs={len(long_signals)} shorts={len(short_signals)} "
        f"vix={vix:.1f if vix else 'N/A'} regime_param={regime!r} (ignored)"
    )
    for s in long_signals:
        logger.info(
            f"  LONG  → {s['ticker']:10s} | "
            f"stop={s['stop_loss_pct']:.1%} tp={s['take_profit_pct']:.1%} "
            f"kelly={s['kelly_fraction']:.1%}"
        )
    for s in short_signals:
        logger.info(
            f"  SHORT → {s['ticker']:10s} | "
            f"stop={s['stop_loss_pct']:.1%} tp={s['take_profit_pct']:.1%} "
            f"kelly={s['kelly_fraction']:.1%}"
        )

    return {
        "regime":           "momentum",
        "signals":          long_signals,
        "short_signals":    short_signals,
        "top5_long":        result["top5_long"],
        "top5_short":       result["top5_short"],
        "activated":        bool(long_signals or short_signals),
        "scan_type":        "pure_momentum",
        "active_signals":   len(long_signals),
        "universe_scanned": fetched,
    }
