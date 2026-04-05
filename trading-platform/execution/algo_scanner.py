"""
Algorithmic Signal Scanner — Oracle's Trade Engine
----------------------------------------------------
v1.0 — Replaces LLM-driven allocation selection with pure algorithmic signals.

The LLM (Groq) still classifies the market regime and provides oversight/veto.
This module generates the actual trade entries based on technical indicators
and the regime context.

Strategy Matrix by Regime
--------------------------
  Bull:
    - Momentum: Buy equities/ETFs where price > SMA-63 (3mo) AND price > SMA-126 (6mo)
      AND RSI(14) between 30–70 (not overbought). Rank by 20d return, take top N.
    - Leveraged satellite: TQQQ/SOXL/UPRO if SPY > EMA-20 (existing gate).

  Bear:
    - Safe haven rotation: GLD, TLT, IEF, SLV — buy those with positive momentum.
    - Inverse ETF momentum: SH, PSQ, DOG (1×) when equities have negative momentum.
    - 3× inverse (SPXS, SQQQ, SRTY) only if VIX > 25 and equity indices in strong
      downtrend (price < SMA-63 AND < SMA-126).

  Sideways:
    - Mean-reversion: Buy oversold assets (RSI < 35, Z-score < -1.5) with
      6mo momentum still positive (dip-buy, not falling knife).
    - Conservative sizing: half-Kelly, max 3 positions.

All Regimes:
  - Max 10 slots total.
  - Conviction = normalised signal strength (0.0–1.0).
  - Kelly fraction = half-Kelly based on conviction.
  - Stop-loss and take-profit derived from ATR/volatility.

Integration
-----------
  Called from pipeline.py AFTER the LLM provides regime classification.
  Returns a list of RegimeAllocationSlot-compatible dicts that the executor
  can process identically to LLM-generated allocations.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from analysis.schemas import REGIME_UNIVERSE, BEAR_HEDGE_TICKERS, BEAR_HEDGE_3X_TICKERS
from data.yfinance_client import get_cached_market_data, get_spy_ema_anchor


BULL_UNIVERSE: list[str] = REGIME_UNIVERSE["equity"]
SAFE_HAVEN_UNIVERSE: list[str] = REGIME_UNIVERSE["safe_haven"]
BEAR_HEDGE_1X: list[str] = ["SH", "PSQ", "DOG"]
BEAR_HEDGE_3X: list[str] = ["SPXS", "SQQQ", "SRTY"]
LEVERAGED_UNIVERSE: list[str] = REGIME_UNIVERSE["leveraged_risk"]
COMMODITY_UNIVERSE: list[str] = REGIME_UNIVERSE["commodity"]
CASH_TICKER = "SGOV"

MAX_SLOTS = 10
MAX_KELLY_SUM = 1.0
HALF_KELLY_CAP = 0.10
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 35.0
ZSCORE_OVERSOLD = -1.5
VIX_ELEVATED = 25.0


def _get_ticker_data(market_data: dict, ticker: str) -> Optional[dict]:
    by_ticker = market_data.get("by_ticker", {})
    return by_ticker.get(ticker)


def _momentum_score(d: dict) -> float:
    ret_20 = d.get("return_20d_pct") or 0.0
    ret_60 = d.get("return_60d_pct") or 0.0
    return ret_20 * 0.6 + ret_60 * 0.4


def _conviction_from_rsi(rsi: float, direction: str = "long") -> float:
    if direction == "long":
        if rsi <= 30:
            return 0.95
        if rsi <= 40:
            return 0.85
        if rsi <= 50:
            return 0.75
        if rsi <= 60:
            return 0.65
        return 0.55
    else:
        if rsi >= 75:
            return 0.90
        if rsi >= 65:
            return 0.80
        return 0.65


def _half_kelly(conviction: float) -> float:
    raw = conviction * 0.5
    return round(min(raw, HALF_KELLY_CAP), 4)


def _stop_take(volatility: Optional[float], direction: str = "long") -> tuple[float, float]:
    vol = volatility or 20.0
    vol_factor = max(vol / 100.0, 0.01)
    if direction == "long":
        stop = round(-min(max(vol_factor * 1.5, 0.03), 0.08), 4)
        take = round(min(max(vol_factor * 2.0, 0.05), 0.20), 4)
    else:
        stop = round(-min(max(vol_factor * 1.5, 0.03), 0.08), 4)
        take = round(min(max(vol_factor * 2.0, 0.05), 0.15), 4)
    return stop, take


def _classify_asset(ticker: str) -> str:
    for asset_class, tickers in REGIME_UNIVERSE.items():
        if ticker in tickers:
            return asset_class
    return "equity"


def scan_bull(market_data: dict, vix: Optional[float] = None) -> list[dict]:
    spy_anchor = get_spy_ema_anchor()
    spy_above_ema = spy_anchor.get("spy_above_ema_20")

    candidates = []
    for ticker in BULL_UNIVERSE + COMMODITY_UNIVERSE:
        d = _get_ticker_data(market_data, ticker)
        if d is None:
            continue
        mom_3mo = d.get("momentum_3mo")
        mom_6mo = d.get("momentum_6mo")
        rsi = d.get("rsi_14d")
        if rsi is None:
            continue
        if mom_3mo != "positive" or mom_6mo != "positive":
            continue
        if rsi > RSI_OVERBOUGHT:
            continue
        if d.get("is_overheated"):
            continue

        score = _momentum_score(d)
        conviction = _conviction_from_rsi(rsi, "long")
        candidates.append({
            "ticker": ticker,
            "score": score,
            "conviction": conviction,
            "rsi": rsi,
            "volatility": d.get("annualized_volatility_20d_pct"),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    slots = []
    kelly_sum = 0.0
    max_active = MAX_SLOTS - 1

    for i, c in enumerate(candidates[:min(7, max_active)]):
        kelly = _half_kelly(c["conviction"])
        if kelly_sum + kelly > MAX_KELLY_SUM:
            kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
        if kelly <= 0:
            break
        stop, take = _stop_take(c["volatility"], "long")
        slots.append({
            "slot": len(slots) + 1,
            "ticker": c["ticker"],
            "asset_class": _classify_asset(c["ticker"]),
            "conviction_score": round(c["conviction"], 2),
            "kelly_fraction": kelly,
            "thesis": (
                f"Algo momentum signal: positive 3mo+6mo trend, "
                f"RSI={c['rsi']:.0f}, 20d return rank #{i+1}"
            ),
            "stop_loss_pct": stop,
            "take_profit_pct": take,
        })
        kelly_sum += kelly

    if spy_above_ema and len(slots) < max_active:
        for lev_ticker in LEVERAGED_UNIVERSE:
            if kelly_sum >= MAX_KELLY_SUM or len(slots) >= max_active:
                break
            d = _get_ticker_data(market_data, lev_ticker)
            if d is None:
                continue
            rsi = d.get("rsi_14d")
            if rsi is None or rsi > RSI_OVERBOUGHT or d.get("is_overheated"):
                continue
            kelly = min(0.05, round(MAX_KELLY_SUM - kelly_sum, 4))
            if kelly <= 0:
                break
            stop, take = _stop_take(d.get("annualized_volatility_20d_pct"), "long")
            stop = round(max(stop, -0.06), 4)
            slots.append({
                "slot": len(slots) + 1,
                "ticker": lev_ticker,
                "asset_class": "leveraged_risk",
                "conviction_score": 0.60,
                "kelly_fraction": kelly,
                "thesis": (
                    f"Algo leveraged satellite: SPY above EMA-20, "
                    f"RSI={rsi:.0f}, max 5% allocation"
                ),
                "stop_loss_pct": stop,
                "take_profit_pct": take,
            })
            kelly_sum += kelly

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


def scan_bear(market_data: dict, vix: Optional[float] = None) -> list[dict]:
    vix_val = vix or 20.0
    slots = []
    kelly_sum = 0.0

    haven_candidates = []
    for ticker in SAFE_HAVEN_UNIVERSE:
        d = _get_ticker_data(market_data, ticker)
        if d is None:
            continue
        mom_3mo = d.get("momentum_3mo")
        rsi = d.get("rsi_14d")
        if rsi is None:
            continue
        if mom_3mo == "positive":
            score = _momentum_score(d)
            conviction = _conviction_from_rsi(rsi, "long")
            haven_candidates.append({
                "ticker": ticker,
                "score": score,
                "conviction": conviction,
                "rsi": rsi,
                "volatility": d.get("annualized_volatility_20d_pct"),
            })

    haven_candidates.sort(key=lambda x: x["score"], reverse=True)

    for c in haven_candidates[:3]:
        kelly = _half_kelly(c["conviction"])
        if kelly_sum + kelly > MAX_KELLY_SUM:
            kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
        if kelly <= 0:
            break
        stop, take = _stop_take(c["volatility"], "long")
        slots.append({
            "slot": len(slots) + 1,
            "ticker": c["ticker"],
            "asset_class": "safe_haven",
            "conviction_score": round(c["conviction"], 2),
            "kelly_fraction": kelly,
            "thesis": (
                f"Algo bear safe haven: positive momentum in downmarket, "
                f"RSI={c['rsi']:.0f}"
            ),
            "stop_loss_pct": stop,
            "take_profit_pct": take,
        })
        kelly_sum += kelly

    equity_downtrend = 0
    for eq_ticker in ["SPY", "QQQ", "IWM"]:
        d = _get_ticker_data(market_data, eq_ticker)
        if d and d.get("momentum_3mo") == "negative" and d.get("momentum_6mo") == "negative":
            equity_downtrend += 1

    max_active_bear = MAX_SLOTS - 1
    if equity_downtrend >= 2 and len(slots) < max_active_bear:
        for inv_ticker in BEAR_HEDGE_1X:
            if kelly_sum >= MAX_KELLY_SUM or len(slots) >= max_active_bear:
                break
            d = _get_ticker_data(market_data, inv_ticker)
            if d is None:
                continue
            rsi = d.get("rsi_14d")
            if rsi is None:
                continue
            conviction = 0.70
            kelly = _half_kelly(conviction)
            if kelly_sum + kelly > MAX_KELLY_SUM:
                kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
            if kelly <= 0:
                break
            stop, take = _stop_take(d.get("annualized_volatility_20d_pct"), "long")
            slots.append({
                "slot": len(slots) + 1,
                "ticker": inv_ticker,
                "asset_class": "bear_hedge",
                "conviction_score": round(conviction, 2),
                "kelly_fraction": kelly,
                "thesis": (
                    f"Algo 1× inverse ETF: {equity_downtrend}/3 major indices "
                    f"in confirmed downtrend, RSI={rsi:.0f}"
                ),
                "stop_loss_pct": stop,
                "take_profit_pct": take,
            })
            kelly_sum += kelly

    if vix_val > VIX_ELEVATED and equity_downtrend >= 2 and len(slots) < max_active_bear:
        bear3x_kelly_sum = 0.0
        bear3x_cap = 0.20
        for inv3x in BEAR_HEDGE_3X:
            if kelly_sum >= MAX_KELLY_SUM or len(slots) >= max_active_bear:
                break
            if bear3x_kelly_sum >= bear3x_cap:
                break
            d = _get_ticker_data(market_data, inv3x)
            if d is None:
                continue
            rsi = d.get("rsi_14d")
            if rsi is None:
                continue
            conviction = 0.65
            kelly = min(0.05, _half_kelly(conviction))
            kelly = min(kelly, round(bear3x_cap - bear3x_kelly_sum, 4))
            if kelly_sum + kelly > MAX_KELLY_SUM:
                kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
            if kelly <= 0:
                break
            stop, take = _stop_take(d.get("annualized_volatility_20d_pct"), "long")
            stop = round(max(stop, -0.08), 4)
            slots.append({
                "slot": len(slots) + 1,
                "ticker": inv3x,
                "asset_class": "bear_hedge",
                "conviction_score": round(conviction, 2),
                "kelly_fraction": kelly,
                "thesis": (
                    f"Algo 3× inverse: VIX={vix_val:.0f} elevated, "
                    f"{equity_downtrend}/3 indices downtrending, short-term hold"
                ),
                "stop_loss_pct": stop,
                "take_profit_pct": take,
            })
            kelly_sum += kelly
            bear3x_kelly_sum += kelly

    if kelly_sum < MAX_KELLY_SUM:
        sgov_kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
        slots.append({
            "slot": len(slots) + 1,
            "ticker": CASH_TICKER,
            "asset_class": "cash",
            "conviction_score": 1.0,
            "kelly_fraction": sgov_kelly,
            "thesis": "Remainder to cash (SGOV) — capital preservation in bear market",
            "stop_loss_pct": -0.01,
            "take_profit_pct": 0.01,
        })

    return slots


def scan_sideways(market_data: dict, vix: Optional[float] = None) -> list[dict]:
    candidates = []
    for ticker in BULL_UNIVERSE + SAFE_HAVEN_UNIVERSE + COMMODITY_UNIVERSE:
        d = _get_ticker_data(market_data, ticker)
        if d is None:
            continue
        rsi = d.get("rsi_14d")
        z_score = d.get("z_score_200d")
        mom_6mo = d.get("momentum_6mo")
        if rsi is None or z_score is None:
            continue
        if rsi < RSI_OVERSOLD and z_score < ZSCORE_OVERSOLD and mom_6mo == "positive":
            conviction = min(0.95, 0.60 + (RSI_OVERSOLD - rsi) / 100.0 + abs(z_score) * 0.1)
            candidates.append({
                "ticker": ticker,
                "conviction": conviction,
                "rsi": rsi,
                "z_score": z_score,
                "volatility": d.get("annualized_volatility_20d_pct"),
            })

    candidates.sort(key=lambda x: x["conviction"], reverse=True)

    slots = []
    kelly_sum = 0.0

    for c in candidates[:3]:
        if c["conviction"] < 0.80:
            continue
        kelly = _half_kelly(c["conviction"])
        if kelly_sum + kelly > MAX_KELLY_SUM:
            kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
        if kelly <= 0:
            break
        stop, take = _stop_take(c["volatility"], "long")
        slots.append({
            "slot": len(slots) + 1,
            "ticker": c["ticker"],
            "asset_class": _classify_asset(c["ticker"]),
            "conviction_score": round(c["conviction"], 2),
            "kelly_fraction": kelly,
            "thesis": (
                f"Algo mean-reversion: RSI={c['rsi']:.0f} oversold, "
                f"Z={c['z_score']:.2f}, 6mo trend still positive (dip-buy)"
            ),
            "stop_loss_pct": stop,
            "take_profit_pct": take,
        })
        kelly_sum += kelly

    if kelly_sum < MAX_KELLY_SUM:
        sgov_kelly = round(MAX_KELLY_SUM - kelly_sum, 4)
        slots.append({
            "slot": len(slots) + 1,
            "ticker": CASH_TICKER,
            "asset_class": "cash",
            "conviction_score": 1.0,
            "kelly_fraction": sgov_kelly,
            "thesis": "Sideways regime — capital preservation priority, remainder to SGOV",
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
    vix         : current VIX value (for bear 3× gate)
    veto_tickers: set of tickers the LLM/Gemini auditor vetoed

    Returns
    -------
    dict with:
        "regime":     str
        "signals":    list[dict]  (RegimeAllocationSlot-compatible)
        "activated":  bool
        "scan_type":  str
    """
    market_data = get_cached_market_data()
    if market_data is None:
        logger.warning("AlgoScanner | No cached market data — returning SGOV-only")
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

    regime_lower = regime.lower() if regime else "sideways"

    if regime_lower in ("bull",):
        scan_type = "bull_momentum"
        signals = scan_bull(market_data, vix)
    elif regime_lower in ("bear", "risk-off"):
        scan_type = "bear_defensive"
        signals = scan_bear(market_data, vix)
    else:
        scan_type = "sideways_reversion"
        signals = scan_sideways(market_data, vix)

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
                            s["kelly_fraction"] = round(MAX_KELLY_SUM - remaining_kelly + s["kelly_fraction"], 4)
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
    logger.info(
        f"AlgoScanner | regime={regime} scan={scan_type} "
        f"signals={active_count} active + SGOV remainder"
    )
    for s in signals:
        if s["ticker"] != CASH_TICKER:
            logger.info(
                f"  → {s['ticker']} | conviction={s['conviction_score']:.2f} "
                f"kelly={s['kelly_fraction']:.4f} | {s['thesis'][:60]}"
            )

    return {
        "regime": regime,
        "signals": signals,
        "activated": active_count > 0,
        "scan_type": scan_type,
        "active_signals": active_count,
    }
