"""
Algorithmic Momentum Scanner — Oracle's Trade Engine
------------------------------------------------------
v2.0 — Pure Momentum Chaser

Scans ~200 NYSE/NASDAQ stocks and ranks by momentum strength.
The LLM (Groq) classifies the regime and provides oversight/veto.
This module generates all trade entries based on momentum signals.

Strategy (Momentum-First, All Regimes)
---------------------------------------
Core: Rank entire universe by composite momentum score, pick top N.

Regime adjusts RISK, not STRATEGY:
  Bull:     Full momentum, up to 9 active slots, aggressive sizing (kelly cap 12%)
  Sideways: Moderate momentum, up to 6 active slots, moderate sizing (kelly cap 8%)
  Bear:     Defensive momentum (healthcare/utilities/staples/energy sectors only),
            up to 4 active slots, tight stops, conservative sizing (kelly cap 6%)

Momentum Score = weighted composite:
  - 20-day return    × 0.50  (short-term momentum)
  - 60-day return    × 0.30  (medium-term trend)
  - 5-day return     × 0.20  (very short-term signal)
  - Trend alignment  × bonus (price > SMA-63 AND SMA-126 = +5.0)

Filters:
  - Price > SMA-63 (3-month moving average — confirmed uptrend)
  - RSI between 30–75 (not overbought, not crashed)
  - Not overheated (Z-score < 2.0 AND RSI < 75)

Integration
-----------
  Called from pipeline.py AFTER the LLM provides regime classification.
  Fetches its own data for the broad universe (cached 1 hour).
  Returns RegimeAllocationSlot-compatible dicts for the executor.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from data.yfinance_client import get_cached_momentum_data
from execution.momentum_universe import (
    DEFENSIVE_TICKERS,
    TICKER_TO_SECTOR,
)


MAX_SLOTS = 10
MAX_KELLY_SUM = 1.0
RSI_OVERBOUGHT = 75.0
RSI_FLOOR = 30.0
CASH_TICKER = "SGOV"

BEAR_INVERSE_ETFS: list[str] = ["SQQQ", "SH", "PSQ"]
BEAR_INVERSE_MAX_TOTAL: float = 0.20
BEAR_INVERSE_KELLY_CAP: float = 0.06

BEAR_SAFE_UNIVERSE: list[str] = ["GLD", "TLT", "XLU", "XLP", "XLV", "SQQQ", "SH"]
BEAR_SAFE_MAX_ACTIVE: int = 2
BEAR_SAFE_ACTIVE_POOL: float = 0.40
BEAR_SAFE_SGOV_FLOOR: float = 0.60
BEAR_SAFE_RSI_LOWER: float = 35.0
BEAR_SAFE_RSI_UPPER: float = 65.0
BEAR_SAFE_STOP_PCT: float = -0.03
BEAR_SAFE_TAKE_PCT: float = 0.05

REGIME_PARAMS: dict[str, dict] = {
    "bull": {
        "max_active": 9,
        "kelly_cap": 0.12,
        "stop_multiplier": 1.5,
        "take_multiplier": 2.0,
        "sector_filter": None,
        "rsi_upper": 75.0,
        "min_conviction": 0.50,
    },
    "sideways": {
        "max_active": 6,
        "kelly_cap": 0.08,
        "stop_multiplier": 1.2,
        "take_multiplier": 1.6,
        "sector_filter": None,
        "rsi_upper": 72.0,
        "min_conviction": 0.60,
    },
    "bear": {
        "max_active": 4,
        "kelly_cap": 0.06,
        "stop_multiplier": 1.0,
        "take_multiplier": 1.3,
        "sector_filter": DEFENSIVE_TICKERS,
        "rsi_upper": 70.0,
        "min_conviction": 0.65,
    },
}


def _momentum_score(d: dict) -> float:
    ret_20 = d.get("return_20d_pct") or 0.0
    ret_60 = d.get("return_60d_pct") or 0.0
    ret_5 = d.get("return_5d_pct") or 0.0
    score = ret_20 * 0.50 + ret_60 * 0.30 + ret_5 * 0.20
    if d.get("momentum_3mo") == "positive" and d.get("momentum_6mo") == "positive":
        score += 5.0
    return score


def _conviction_from_rsi(rsi: float) -> float:
    if rsi <= 35:
        return 0.95
    if rsi <= 45:
        return 0.85
    if rsi <= 55:
        return 0.75
    if rsi <= 65:
        return 0.65
    return 0.55


def _half_kelly(conviction: float, cap: float) -> float:
    raw = conviction * 0.5
    return round(min(raw, cap), 4)


def _stop_take(
    volatility: Optional[float],
    stop_mult: float,
    take_mult: float,
) -> tuple[float, float]:
    vol = volatility or 20.0
    vol_factor = max(vol / 100.0, 0.01)
    stop = round(-min(max(vol_factor * stop_mult, 0.03), 0.08), 4)
    take = round(min(max(vol_factor * take_mult, 0.05), 0.20), 4)
    return stop, take


def _scan_bear_inverse_etfs(
    by_ticker: dict,
    kelly_cap: float = BEAR_INVERSE_KELLY_CAP,
    max_total: float = BEAR_INVERSE_MAX_TOTAL,
) -> list[dict]:
    """
    Bear-regime active strategy: scan inverse ETFs (SQQQ, SH, PSQ) for
    positive momentum. Only enters if both 20d and 60d returns are positive
    (which they will be in a genuine bear market). Capped at kelly_cap per
    position and max_total across all inverse ETFs.
    """
    slots = []
    kelly_sum = 0.0

    candidates = []
    for ticker in BEAR_INVERSE_ETFS:
        d = by_ticker.get(ticker)
        if not d:
            logger.debug(f"BearInverse | {ticker}: no data available — skip")
            continue

        ret_20 = d.get("return_20d_pct") or 0.0
        ret_60 = d.get("return_60d_pct") or 0.0

        if ret_20 <= 0 or ret_60 <= 0:
            logger.info(
                f"BearInverse | {ticker}: negative momentum "
                f"(20d={ret_20:+.1f}%, 60d={ret_60:+.1f}%) — skip"
            )
            continue

        rsi = d.get("rsi_14d")
        if rsi is not None and rsi > RSI_OVERBOUGHT:
            logger.info(f"BearInverse | {ticker}: RSI {rsi:.0f} > {RSI_OVERBOUGHT} — skip")
            continue

        score = _momentum_score(d)
        conviction = _conviction_from_rsi(rsi) if rsi else 0.70

        candidates.append({
            "ticker": ticker,
            "score": score,
            "conviction": conviction,
            "rsi": rsi or 50.0,
            "volatility": d.get("annualized_volatility_20d_pct"),
            "return_20d": ret_20,
            "return_60d": ret_60,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    for c in candidates:
        kelly = _half_kelly(c["conviction"], kelly_cap)
        if kelly_sum + kelly > max_total:
            kelly = round(max_total - kelly_sum, 4)
        if kelly <= 0:
            break

        vol = c["volatility"] or 40.0
        vol_factor = max(vol / 100.0, 0.02)
        stop = round(-min(max(vol_factor * 1.0, 0.04), 0.10), 4)
        take = round(min(max(vol_factor * 1.5, 0.06), 0.20), 4)

        slots.append({
            "slot": 0,
            "ticker": c["ticker"],
            "asset_class": "bear_hedge",
            "conviction_score": round(c["conviction"], 2),
            "kelly_fraction": kelly,
            "thesis": (
                f"Bear inverse ETF: {c['ticker']} "
                f"20d={c['return_20d']:+.1f}% 60d={c['return_60d']:+.1f}% "
                f"RSI={c['rsi']:.0f} — positive momentum confirms bear trend"
            ),
            "stop_loss_pct": stop,
            "take_profit_pct": take,
        })
        kelly_sum += kelly

    if slots:
        logger.info(
            f"BearInverse | {len(slots)} inverse ETF(s) selected: "
            f"{[s['ticker'] for s in slots]} total_kelly={kelly_sum:.1%}"
        )
    else:
        logger.info("BearInverse | No inverse ETFs qualify (need positive 20d+60d momentum)")

    return slots


def _scan_bear_safe(by_ticker: dict) -> list[dict]:
    """
    Bear-regime partial deployment: scan BEAR_SAFE_UNIVERSE for up to 2
    high-conviction defensive positions, then guarantee a 60% SGOV floor.

    Rules:
      - Universe: GLD, TLT, XLU, XLP, XLV, SQQQ, SH
      - Filter: positive composite momentum score AND RSI in [35, 65]
      - Rank by composite momentum score, take top BEAR_SAFE_MAX_ACTIVE (2)
      - Each position allocated an equal share of the 40% active pool
      - Fixed stop: -3%   fixed take: +5%
      - SGOV floor: 60% (or 100% if no asset qualifies)
    """
    candidates = []
    for ticker in BEAR_SAFE_UNIVERSE:
        d = by_ticker.get(ticker)
        if not d:
            logger.debug(f"BearSafe | {ticker}: no data — skip")
            continue

        rsi = d.get("rsi_14d")
        if rsi is None or not (BEAR_SAFE_RSI_LOWER <= rsi <= BEAR_SAFE_RSI_UPPER):
            logger.debug(
                f"BearSafe | {ticker}: RSI={rsi} outside "
                f"[{BEAR_SAFE_RSI_LOWER:.0f}, {BEAR_SAFE_RSI_UPPER:.0f}] — skip"
            )
            continue

        score = _momentum_score(d)
        if score <= 0:
            logger.info(
                f"BearSafe | {ticker}: composite score {score:.2f} ≤ 0 — skip"
            )
            continue

        candidates.append({
            "ticker": ticker,
            "score": score,
            "rsi": rsi,
            "return_5d":  d.get("return_5d_pct")  or 0.0,
            "return_20d": d.get("return_20d_pct") or 0.0,
            "return_60d": d.get("return_60d_pct") or 0.0,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:BEAR_SAFE_MAX_ACTIVE]

    slots: list[dict] = []

    if top:
        per_position_kelly = round(BEAR_SAFE_ACTIVE_POOL / len(top), 4)
        for i, c in enumerate(top):
            slots.append({
                "slot":             i + 1,
                "ticker":           c["ticker"],
                "asset_class":      "bear_defensive",
                "conviction_score": round(_conviction_from_rsi(c["rsi"]), 2),
                "kelly_fraction":   per_position_kelly,
                "thesis": (
                    f"BearSafe rank #{i + 1}: score={c['score']:.2f} "
                    f"5d={c['return_5d']:+.1f}% 20d={c['return_20d']:+.1f}% "
                    f"60d={c['return_60d']:+.1f}% RSI={c['rsi']:.0f}"
                ),
                "stop_loss_pct":   BEAR_SAFE_STOP_PCT,
                "take_profit_pct": BEAR_SAFE_TAKE_PCT,
            })
        active_kelly = sum(s["kelly_fraction"] for s in slots)
        logger.info(
            f"BearSafe | {len(top)} active: "
            f"{[s['ticker'] for s in slots]} "
            f"kelly={per_position_kelly:.1%} each, total={active_kelly:.1%}"
        )
    else:
        logger.info(
            "BearSafe | No qualifying assets in bear-safe universe "
            "(need positive score + RSI 35–65) — 100% SGOV fallback"
        )
        active_kelly = 0.0

    sgov_kelly = round(max(BEAR_SAFE_SGOV_FLOOR, 1.0 - active_kelly), 4)
    slots.append({
        "slot":             len(slots) + 1,
        "ticker":           CASH_TICKER,
        "asset_class":      "cash",
        "conviction_score": 1.0,
        "kelly_fraction":   sgov_kelly,
        "thesis": (
            "Bear 60% SGOV floor — capital preservation"
            if top else
            "Bear 100% SGOV — no qualifying defensive assets"
        ),
        "stop_loss_pct":   -0.01,
        "take_profit_pct":  0.01,
    })

    return slots


def scan_momentum(
    momentum_data: dict,
    regime: str,
    vix: Optional[float] = None,
) -> list[dict]:
    regime_lower = (regime or "sideways").lower()
    if regime_lower in ("risk-off",):
        regime_lower = "bear"

    if regime_lower == "bear":
        by_ticker = momentum_data.get("by_ticker", {})
        return _scan_bear_safe(by_ticker)

    params = REGIME_PARAMS.get(regime_lower, REGIME_PARAMS["sideways"])

    max_active = params["max_active"]
    kelly_cap = params["kelly_cap"]
    stop_mult = params["stop_multiplier"]
    take_mult = params["take_multiplier"]
    sector_filter: set[str] | None = params["sector_filter"]
    rsi_upper = params["rsi_upper"]
    min_conviction = params["min_conviction"]

    by_ticker = momentum_data.get("by_ticker", {})

    candidates = []
    skipped_sector = 0
    skipped_filter = 0

    for ticker, d in by_ticker.items():
        if sector_filter and ticker not in sector_filter:
            skipped_sector += 1
            continue

        rsi = d.get("rsi_14d")
        if rsi is None:
            skipped_filter += 1
            continue
        if rsi > rsi_upper or rsi < RSI_FLOOR:
            skipped_filter += 1
            continue
        if d.get("is_overheated"):
            skipped_filter += 1
            continue
        if d.get("momentum_3mo") != "positive":
            skipped_filter += 1
            continue

        score = _momentum_score(d)
        conviction = _conviction_from_rsi(rsi)
        if conviction < min_conviction:
            skipped_filter += 1
            continue

        candidates.append({
            "ticker": ticker,
            "score": score,
            "conviction": conviction,
            "rsi": rsi,
            "volatility": d.get("annualized_volatility_20d_pct"),
            "sector": TICKER_TO_SECTOR.get(ticker, "unknown"),
            "return_5d": d.get("return_5d_pct") or 0.0,
            "return_20d": d.get("return_20d_pct") or 0.0,
            "return_60d": d.get("return_60d_pct") or 0.0,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    logger.info(
        f"AlgoScanner | {len(candidates)} momentum candidates from "
        f"{len(by_ticker)} tickers (sector_skip={skipped_sector}, "
        f"filter_skip={skipped_filter})"
    )

    slots = []
    kelly_sum = 0.0

    seen_sectors: dict[str, int] = {}
    max_per_sector = 3 if regime_lower == "bull" else 2

    for c in candidates:
        if len(slots) >= max_active:
            break

        sector = c["sector"]
        if seen_sectors.get(sector, 0) >= max_per_sector:
            continue

        kelly = _half_kelly(c["conviction"], kelly_cap)
        if kelly_sum + kelly > MAX_KELLY_SUM:
            kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
        if kelly <= 0:
            break

        stop, take = _stop_take(c["volatility"], stop_mult, take_mult)

        slots.append({
            "slot": len(slots) + 1,
            "ticker": c["ticker"],
            "asset_class": "momentum_equity",
            "conviction_score": round(c["conviction"], 2),
            "kelly_fraction": kelly,
            "thesis": (
                f"Momentum rank #{len(slots)+1}: "
                f"5d={c['return_5d']:+.1f}% 20d={c['return_20d']:+.1f}% "
                f"60d={c['return_60d']:+.1f}% "
                f"RSI={c['rsi']:.0f} sector={sector}"
            ),
            "stop_loss_pct": stop,
            "take_profit_pct": take,
        })
        kelly_sum += kelly
        seen_sectors[sector] = seen_sectors.get(sector, 0) + 1

    if regime_lower == "bear":
        inverse_slots = _scan_bear_inverse_etfs(by_ticker)
        for inv_slot in inverse_slots:
            if kelly_sum + inv_slot["kelly_fraction"] > MAX_KELLY_SUM:
                inv_slot["kelly_fraction"] = round(MAX_KELLY_SUM - kelly_sum, 4)
            if inv_slot["kelly_fraction"] <= 0:
                break
            inv_slot["slot"] = len(slots) + 1
            slots.append(inv_slot)
            kelly_sum += inv_slot["kelly_fraction"]

    if kelly_sum < MAX_KELLY_SUM:
        sgov_kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
        slots.append({
            "slot": len(slots) + 1,
            "ticker": CASH_TICKER,
            "asset_class": "cash",
            "conviction_score": 1.0,
            "kelly_fraction": sgov_kelly,
            "thesis": "Remainder to cash (SGOV) for capital preservation",
            "stop_loss_pct": -0.01,
            "take_profit_pct": 0.01,
        })

    return slots


def run_algo_scan(
    regime: str,
    vix: Optional[float] = None,
    veto_tickers: Optional[set[str]] = None,
) -> dict:
    """
    Main entry point — called from pipeline.py after LLM regime classification.

    Parameters
    ----------
    regime      : "Bull", "Bear", or "Sideways" from the LLM
    vix         : current VIX value (informational)
    veto_tickers: set of tickers the LLM/Gemini auditor vetoed

    Returns
    -------
    dict with:
        "regime":     str
        "signals":    list[dict]  (RegimeAllocationSlot-compatible)
        "activated":  bool
        "scan_type":  str
    """
    momentum_data = get_cached_momentum_data()

    if momentum_data is None or not momentum_data.get("by_ticker"):
        logger.warning("AlgoScanner | No momentum data available — returning SGOV-only")
        return {
            "regime": regime,
            "signals": [{
                "slot": 1,
                "ticker": CASH_TICKER,
                "asset_class": "cash",
                "conviction_score": 1.0,
                "kelly_fraction": 1.0,
                "thesis": "No market data available — 100% cash",
                "stop_loss_pct": -0.01,
                "take_profit_pct": 0.01,
            }],
            "activated": False,
            "scan_type": "no_data",
        }

    regime_lower = (regime or "sideways").lower()
    scan_type = f"momentum_{regime_lower}"
    signals = scan_momentum(momentum_data, regime, vix)

    if veto_tickers:
        original_count = len(signals)
        signals = [s for s in signals if s["ticker"] not in veto_tickers]
        vetoed = original_count - len(signals)
        if vetoed > 0:
            logger.info(f"AlgoScanner | LLM veto removed {vetoed} signal(s): {veto_tickers}")
            remaining_kelly = sum(s["kelly_fraction"] for s in signals)
            if remaining_kelly < MAX_KELLY_SUM:
                sgov_exists = any(s["ticker"] == CASH_TICKER for s in signals)
                if sgov_exists:
                    for s in signals:
                        if s["ticker"] == CASH_TICKER:
                            s["kelly_fraction"] = round(
                                MAX_KELLY_SUM - remaining_kelly + s["kelly_fraction"], 4
                            )
                            break
                else:
                    signals.append({
                        "slot": len(signals) + 1,
                        "ticker": CASH_TICKER,
                        "asset_class": "cash",
                        "conviction_score": 1.0,
                        "kelly_fraction": round(MAX_KELLY_SUM - remaining_kelly, 4),
                        "thesis": "Vetoed allocation redirected to SGOV",
                        "stop_loss_pct": -0.01,
                        "take_profit_pct": 0.01,
                    })

    for i, s in enumerate(signals):
        s["slot"] = i + 1

    active_count = sum(1 for s in signals if s["ticker"] != CASH_TICKER)
    fetched = momentum_data.get("fetched", 0)
    universe = momentum_data.get("universe_size", 0)

    logger.info(
        f"AlgoScanner | regime={regime} scan={scan_type} "
        f"universe={universe} fetched={fetched} "
        f"signals={active_count} active + SGOV remainder"
    )
    for s in signals:
        if s["ticker"] != CASH_TICKER:
            logger.info(
                f"  → {s['ticker']} | conviction={s['conviction_score']:.2f} "
                f"kelly={s['kelly_fraction']:.4f} | {s['thesis'][:80]}"
            )

    return {
        "regime": regime,
        "signals": signals,
        "activated": active_count > 0,
        "scan_type": scan_type,
        "active_signals": active_count,
        "universe_scanned": fetched,
    }
