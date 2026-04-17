"""
Oracle Pure Momentum Scanner v3.1 — Deterministic, No LLM
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
  3. Long candidates : top 3 where score ≥ 5.0, RSI 30–70, price > EMA-20,
                       not already in an open position.
  4. Short candidates: bottom 1 where score < 0, RSI 30–70, price < EMA-20,
                       not already in an open position.

Position Sizing
---------------
  • Fixed 10% of equity per position (kelly_fraction = 0.10) until
    Oracle has 30+ closed trades.
  • After 30 closed trades: half-Kelly capped at 15%.

Stop / Take-Profit (volatility-scaled)
---------------------------------------
  vol_factor  = annualized_vol_20d / 100
  stop_loss   = -clamp(vol_factor × 1.5, 0.06, 0.10)   # floor raised 4% → 6%
  take_profit =  clamp(vol_factor × 2.5, 0.09, 0.20)   # floor raised 6% → 9%

Oracle Profit Reserve
---------------------
  After every closed winning trade the post-mortem calls
  add_oracle_profit_contribution(profit_usd * 0.15).
  This reserve is NOT invested — it is tracked as a separate ledger
  item in the diagnostic report.

Kill Switch
-----------
  5% daily drawdown trips the kill switch — handled upstream.

v3.1 changes
------------
  • Per-filter-stage verbose logging: universe_loaded → with_data →
    passed_score → passed_rsi → passed_ema → final signals.
  • Each scan run persists a diagnostic row to oracle_scan_log in
    PostgreSQL so operators can audit zero-signal cycles without
    trawling server logs.
"""

from __future__ import annotations

import json
from typing import Optional

from loguru import logger

from data.yfinance_client import get_cached_momentum_data


MAX_LONG_SLOTS  = 3    # reduced from 6 — concentrated portfolio, 3 high-conviction longs
MAX_SHORT_SLOTS = 1    # reduced from 3 — single highest-conviction short only

RSI_LOWER       = 30.0
RSI_UPPER       = 70.0

MIN_MOMENTUM_SCORE = 5.0  # minimum composite score for long entry — filters weak/borderline signals

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
    # Minimum stop raised from 4% to 6% to avoid normal price noise stop-outs on
    # volatile momentum stocks. Tight 4% stops were being triggered by routine
    # intraday swings, generating massive churn with near-zero P&L.
    stop = -round(min(max(vol_factor * 1.5, 0.06), 0.10), 4)
    take =  round(min(max(vol_factor * 2.5, 0.09), 0.20), 4)
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


def _persist_scan_log(
    universe_loaded: int,
    with_data: int,
    passed_score: int,
    passed_rsi: int,
    passed_ema: int,
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
                        universe_loaded, with_data, passed_score, passed_rsi,
                        passed_ema, long_signals, short_signals,
                        json.dumps(top5_long), json.dumps(top5_short),
                        scan_note,
                    ),
                )
        logger.debug(
            f"Oracle | scan_log persisted: loaded={universe_loaded} "
            f"with_data={with_data} score={passed_score} rsi={passed_rsi} "
            f"ema={passed_ema} longs={long_signals} shorts={short_signals}"
        )
    except Exception as exc:
        logger.warning(f"Oracle | Failed to persist scan_log (non-fatal): {exc}")


def scan_momentum(
    momentum_data: dict,
    open_symbols: set[str] | None = None,
) -> dict:
    """
    Run the pure momentum scan.

    Returns
    -------
    dict with:
        "long_signals"   : list[dict]  — up to 6 long candidates
        "short_signals"  : list[dict]  — up to 3 short candidates
        "top5_long"      : list[dict]  — top 5 ranked (pre-filter, for reporting)
        "top5_short"     : list[dict]  — bottom 5 ranked (pre-filter, for reporting)
        "universe_size"  : int
        "filter_stages"  : dict        — per-stage counts for diagnostics
    """
    open_symbols = open_symbols or set()
    by_ticker    = momentum_data.get("by_ticker", {})

    universe_loaded = len(by_ticker)

    # ── Stage 1: parse + score all tickers ───────────────────────────────────
    scored: list[dict] = []
    skipped_no_data = 0
    for ticker, d in by_ticker.items():
        if "error" in d:
            skipped_no_data += 1
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

    with_data = len(scored)
    logger.info(
        f"Oracle | Filter stage 1/5 — universe_loaded={universe_loaded} "
        f"with_valid_data={with_data} skipped_errors={skipped_no_data}"
    )

    scored.sort(key=lambda x: x["score"], reverse=True)

    # ── Stage 2: score threshold — longs need score ≥ MIN_MOMENTUM_SCORE ────
    # Shorts only need score < 0 (no floor — inverted logic for weak momentum)
    long_candidates  = [c for c in scored if c["score"] >= MIN_MOMENTUM_SCORE]
    short_candidates = [c for c in scored if c["score"] < 0]
    passed_score = len(long_candidates) + len(short_candidates)
    logger.info(
        f"Oracle | Filter stage 2/5 — score_threshold(longs≥{MIN_MOMENTUM_SCORE} / shorts<0): "
        f"long_candidates={len(long_candidates)} short_candidates={len(short_candidates)} "
        f"(dropped below_min_score={len([c for c in scored if 0 <= c['score'] < MIN_MOMENTUM_SCORE])})"
    )

    # ── Stage 3: RSI 30–70 ────────────────────────────────────────────────────
    long_rsi  = [c for c in long_candidates  if c["rsi"] is not None and RSI_LOWER <= c["rsi"] <= RSI_UPPER]
    short_rsi = [c for c in short_candidates if c["rsi"] is not None and RSI_LOWER <= c["rsi"] <= RSI_UPPER]
    passed_rsi = len(long_rsi) + len(short_rsi)
    logger.info(
        f"Oracle | Filter stage 3/5 — passed_RSI({RSI_LOWER:.0f}–{RSI_UPPER:.0f}): "
        f"long={len(long_rsi)} short={len(short_rsi)} "
        f"(dropped longs={len(long_candidates)-len(long_rsi)} shorts={len(short_candidates)-len(short_rsi)})"
    )

    # ── Stage 4: price vs EMA-20 ──────────────────────────────────────────────
    long_ema  = [c for c in long_rsi  if c["price"] is not None and c["ema_20d"] is not None and c["price"] > c["ema_20d"]]
    short_ema = [c for c in short_rsi if c["price"] is not None and c["ema_20d"] is not None and c["price"] < c["ema_20d"]]
    passed_ema = len(long_ema) + len(short_ema)
    logger.info(
        f"Oracle | Filter stage 4/5 — passed_EMA20: "
        f"long(price>EMA20)={len(long_ema)} short(price<EMA20)={len(short_ema)} "
        f"(dropped longs={len(long_rsi)-len(long_ema)} shorts={len(short_rsi)-len(short_ema)})"
    )

    # ── Stage 5: exclude open positions ──────────────────────────────────────
    long_fresh  = [c for c in long_ema  if c["ticker"] not in open_symbols]
    short_fresh = [c for c in short_ema if c["ticker"] not in open_symbols]
    logger.info(
        f"Oracle | Filter stage 5/5 — exclude_open_positions({len(open_symbols)} held): "
        f"long_eligible={len(long_fresh)} short_eligible={len(short_fresh)}"
    )

    fraction   = _get_position_fraction()
    top5_long  = [{"ticker": c["ticker"], "score": round(c["score"], 3), "rsi": c["rsi"]} for c in scored[:5]]
    top5_short = [{"ticker": c["ticker"], "score": round(c["score"], 3), "rsi": c["rsi"]} for c in scored[-5:]]

    # ── Build final signal lists ──────────────────────────────────────────────
    long_signals: list[dict] = []
    for c in long_fresh[:MAX_LONG_SLOTS]:
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
                f"60d={c['return_60d']:+.1f}% RSI={c['rsi']:.0f} "
                f"price={c['price']:.2f} EMA20={c['ema_20d']:.2f}"
            ),
            "stop_loss_pct":   stop,
            "take_profit_pct": take,
        })

    short_signals: list[dict] = []
    for c in short_fresh[:MAX_SHORT_SLOTS]:
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
                f"60d={c['return_60d']:+.1f}% RSI={c['rsi']:.0f} "
                f"price={c['price']:.2f} EMA20={c['ema_20d']:.2f}"
            ),
            "stop_loss_pct":   stop,
            "take_profit_pct": take,
        })

    logger.info(
        f"Oracle | Scan complete — "
        f"universe={universe_loaded} → with_data={with_data} → "
        f"score_filter={passed_score} → rsi_filter={passed_rsi} → "
        f"ema_filter={passed_ema} → final: longs={len(long_signals)} shorts={len(short_signals)}"
    )
    if long_signals:
        for s in long_signals:
            logger.info(
                f"  LONG  → {s['ticker']:10s} | "
                f"stop={s['stop_loss_pct']:.1%} tp={s['take_profit_pct']:.1%} "
                f"kelly={s['kelly_fraction']:.1%}"
            )
    else:
        logger.warning("Oracle | No long signals generated — Oracle will hold cash this cycle")
    for s in short_signals:
        logger.info(
            f"  SHORT → {s['ticker']:10s} | "
            f"stop={s['stop_loss_pct']:.1%} tp={s['take_profit_pct']:.1%} "
            f"kelly={s['kelly_fraction']:.1%}"
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
            "passed_score":    passed_score,
            "passed_rsi":      passed_rsi,
            "passed_ema":      passed_ema,
        },
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
        "filter_stages"   : dict       (per-stage counts for diagnostics)
    """
    momentum_data = get_cached_momentum_data()

    if momentum_data is None or not momentum_data.get("by_ticker"):
        logger.warning(
            "AlgoScanner | No momentum data in cache — "
            "fetch_momentum_universe() must be called before run_algo_scan()."
        )
        _persist_scan_log(
            universe_loaded=0, with_data=0, passed_score=0,
            passed_rsi=0, passed_ema=0, long_signals=0, short_signals=0,
            top5_long=[], top5_short=[],
            scan_note="no_cache: fetch_momentum_universe() was not called",
        )
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
            "filter_stages":    {},
        }

    result        = scan_momentum(momentum_data, open_symbols=open_symbols or set())
    long_signals  = result["long_signals"]
    short_signals = result["short_signals"]
    stages        = result["filter_stages"]

    fetched  = momentum_data.get("fetched",       stages.get("universe_loaded", 0))
    universe = momentum_data.get("universe_size", fetched)

    logger.info(
        f"Oracle | run_algo_scan summary: universe={universe} fetched={fetched} "
        f"longs={len(long_signals)} shorts={len(short_signals)} "
        f"vix={'N/A' if not isinstance(vix, float) else f'{vix:.1f}'} "
        f"regime_param={regime!r} (ignored)"
    )

    scan_note = None if (long_signals or short_signals) else "no_signals_after_all_filters"
    _persist_scan_log(
        universe_loaded=stages.get("universe_loaded", 0),
        with_data=stages.get("with_data", 0),
        passed_score=stages.get("passed_score", 0),
        passed_rsi=stages.get("passed_rsi", 0),
        passed_ema=stages.get("passed_ema", 0),
        long_signals=len(long_signals),
        short_signals=len(short_signals),
        top5_long=result["top5_long"],
        top5_short=result["top5_short"],
        scan_note=scan_note,
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
        "filter_stages":    stages,
    }
