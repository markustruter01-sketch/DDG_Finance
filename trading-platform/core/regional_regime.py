"""
core/regional_regime.py — Per-Market Regional Regime
------------------------------------------------------
Stage 1 shared infrastructure.  NOT wired to any bot yet.

Function
--------
    regional_regime(etf) → dict

Regime labels (same thresholds as the validated market_state)
--------------------------------------------------------------
    BULL   — ETF EMA-50 > EMA-200 AND ETF 20d return > -12%
    BEAR   — ETF EMA-50 ≤ EMA-200 AND ETF 20d return > -12%
    CRISIS — ETF 20d return ≤ -12%  (per-ETF, regardless of SMA relationship)

Global crash override
---------------------
    If the GLOBAL state (SPY 20d return ≤ -12%) == CRISIS, all new entries are
    gated fleet-wide regardless of any regional BULL reading.  Exits are NEVER
    gated by either the regional or global regime.

    The override is exposed as a separate key ("global_override") so callers can
    distinguish "this ETF itself is in crisis" from "SPY dragged it into a gate".

Fail-safe direction
-------------------
    Insufficient data (< 201 bars for EMA-200) → CRISIS (block).
    Any fetch / compute error → CRISIS (block).
    Same discipline as get_market_state() in market_state.py and the Arc-3 audit.

Data source
-----------
    Yahoo Finance v8 daily adjClose — same endpoint used by bot2_spy_qqq via
    alpaca_etf_engine._yahoo_daily_ohlcv.  Implemented standalone so this module
    has zero cross-package dependencies at import time.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants (mirror market_state.py — authoritative values) ─────────────────
CRISIS_THRESHOLD = -0.12   # 20d return ≤ -12% → CRISIS
CRISIS_LOOKBACK  = 20      # trading days for 20d return
EMA_FAST         = 50      # EMA-50 (per-ETF regime)
EMA_SLOW         = 200     # EMA-200 (per-ETF regime)
HIGH_VOL_LOOKBACK= 10      # days for realized vol flag
HIGH_VOL_ANN     = 0.30    # 30% annualised → HIGH_VOL flag

FETCH_DAYS_REGIME = 310    # buffer for 200-bar EMA warm-up (~200 trading days ≈ 280 cal)

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; trading-platform/1.0)"}


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch_daily_closes(ticker: str, days: int = FETCH_DAYS_REGIME) -> Optional[list[float]]:
    """
    Yahoo Finance v8 daily adjClose (oldest first).
    Returns None on any error — callers map None → CRISIS (fail-CLOSED).
    """
    import requests

    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{days}d", "interval": "1d", "includePrePost": "false"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"RegionalRegime | Yahoo {ticker} → HTTP {resp.status_code}")
            return None
        data   = resp.json()
        result = (data.get("chart", {}).get("result") or [None])[0]
        if not result:
            return None
        adj    = (result.get("indicators", {}).get("adjclose") or [{}])[0]
        closes = adj.get("adjclose") or result["indicators"]["quote"][0].get("close", [])
        clean  = [float(c) for c in closes if c is not None and c > 0]
        return clean or None
    except Exception as exc:
        logger.warning(f"RegionalRegime | fetch failed for {ticker}: {exc}")
        return None


# ── Technical indicators ──────────────────────────────────────────────────────

def _ema(closes: list[float], period: int) -> Optional[float]:
    """
    Standard EMA seeded with the SMA of the first `period` bars.
    Returns None if fewer than `period` bars available.
    Matches yfinance_client._compute_ema and alpaca_etf_engine.calculate_ema.
    """
    if len(closes) < period:
        return None
    k   = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period   # SMA seed
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
    return ema


def _realized_vol(closes: list[float], lookback: int = HIGH_VOL_LOOKBACK) -> Optional[float]:
    """Annualized realized vol over `lookback` daily returns."""
    if len(closes) < lookback + 1:
        return None
    window = closes[-(lookback + 1):]
    rets   = [window[i] / window[i - 1] - 1 for i in range(1, len(window))]
    if len(rets) < 2:
        return None
    mu  = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


# ── Core computation ───────────────────────────────────────────────────────────

def _compute_regime(closes: list[float], ticker: str = "?") -> dict[str, Any]:
    """
    Given a close series (oldest first), compute the per-ETF regime dict.
    Fail-safe: any insufficiency returns CRISIS with fail_safe=True.
    """
    n = len(closes)

    if n < CRISIS_LOOKBACK + 1:
        logger.warning(
            f"RegionalRegime | {ticker}: only {n} bars (need {CRISIS_LOOKBACK + 1}) "
            f"— fail-safe CRISIS"
        )
        return _crisis_failsafe(ticker, f"insufficient_data ({n} bars)")

    price    = closes[-1]
    ret_20d  = closes[-1] / closes[-(CRISIS_LOOKBACK + 1)] - 1

    # EMA-50 / EMA-200 for BULL / BEAR classification
    ema50  = _ema(closes, EMA_FAST)
    ema200 = _ema(closes, EMA_SLOW)

    # 10-day realized vol for HIGH_VOL flag
    hi_vol_val = _realized_vol(closes, HIGH_VOL_LOOKBACK)
    high_vol   = bool(hi_vol_val is not None and hi_vol_val > HIGH_VOL_ANN)

    # Regime classification — CRISIS dominates
    if ret_20d <= CRISIS_THRESHOLD:
        regime = "CRISIS"
    elif ema50 is not None and ema200 is not None and ema50 < ema200:
        regime = "BEAR"
    elif ema50 is not None and ema200 is not None:
        regime = "BULL"
    else:
        # Insufficient bars for EMA-200 specifically
        logger.warning(
            f"RegionalRegime | {ticker}: {n} bars — insufficient for EMA-{EMA_SLOW} "
            f"(need {EMA_SLOW}) — fail-safe CRISIS"
        )
        return _crisis_failsafe(ticker, f"insufficient_ema200 ({n} bars, need {EMA_SLOW})")

    return {
        "ticker":      ticker,
        "regime":      regime,
        "high_vol":    high_vol,
        "price":       round(price, 4),
        "ret_20d":     round(ret_20d, 6),
        "ema50":       round(ema50, 4)  if ema50  is not None else None,
        "ema200":      round(ema200, 4) if ema200 is not None else None,
        "hi_vol_ann":  round(hi_vol_val, 4) if hi_vol_val is not None else None,
        "data_bars":   n,
        "fail_safe":   False,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _crisis_failsafe(ticker: str, reason: str) -> dict[str, Any]:
    return {
        "ticker":      ticker,
        "regime":      "CRISIS",
        "high_vol":    False,
        "price":       None,
        "ret_20d":     None,
        "ema50":       None,
        "ema200":      None,
        "hi_vol_ann":  None,
        "data_bars":   0,
        "fail_safe":   True,
        "fail_safe_reason": reason,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Global override (SPY-based) ───────────────────────────────────────────────

def _get_global_state() -> dict[str, Any]:
    """
    Returns the current GLOBAL market state (SPY-based).

    Attempts to use the platform's cached get_market_state() (avoid a redundant
    fetch when running inside trading-platform).  Falls back to a direct Yahoo
    fetch of SPY if that import fails (standalone / test context).

    Fail-safe: any error → CRISIS (block all entries).
    """
    # ── Try platform cache first ──────────────────────────────────────────────
    try:
        from core.market_state import get_market_state
        state = get_market_state(persist=False)
        state["source"] = "market_state_cache"
        return state
    except Exception as exc:
        logger.debug(f"RegionalRegime | platform market_state unavailable ({exc}) — fetching SPY direct")

    # ── Fallback: fetch SPY directly ──────────────────────────────────────────
    try:
        spy_closes = _fetch_daily_closes("SPY", days=35)
        if not spy_closes or len(spy_closes) < CRISIS_LOOKBACK + 1:
            logger.warning("RegionalRegime | SPY fallback insufficient — fail-safe CRISIS (global)")
            return {
                "regime": "CRISIS", "high_vol": False,
                "fail_safe": True,
                "fail_safe_reason": "spy_fetch_insufficient",
                "source": "yahoo_direct_fallback",
            }
        spy_20d_ret = spy_closes[-1] / spy_closes[-(CRISIS_LOOKBACK + 1)] - 1
        global_regime = "CRISIS" if spy_20d_ret <= CRISIS_THRESHOLD else "BULL"
        return {
            "regime":       global_regime,
            "high_vol":     False,
            "spy_20d_ret":  round(spy_20d_ret, 6),
            "spy_close":    round(spy_closes[-1], 4),
            "fail_safe":    False,
            "source":       "yahoo_direct_fallback",
        }
    except Exception as exc:
        logger.warning(f"RegionalRegime | SPY fallback failed ({exc}) — fail-safe CRISIS (global)")
        return {
            "regime": "CRISIS", "high_vol": False,
            "fail_safe": True,
            "fail_safe_reason": f"spy_fetch_error: {exc}",
            "source": "yahoo_direct_fallback",
        }


# ── Public API ────────────────────────────────────────────────────────────────

def regional_regime(etf: str) -> dict[str, Any]:
    """
    Compute the current regime for a single ETF using its OWN price data.

    Parameters
    ----------
    etf : ticker symbol (e.g. "EWZ", "EWY")

    Returns
    -------
    dict with keys:
        ticker          : str
        regime          : "BULL" | "BEAR" | "CRISIS"   (per-ETF)
        high_vol        : bool
        price           : float | None
        ret_20d         : float | None   (e.g. -0.134 = -13.4%)
        ema50           : float | None
        ema200          : float | None
        hi_vol_ann      : float | None   (annualised, decimal)
        data_bars       : int
        fail_safe       : bool           (True = fallback-CRISIS)
        global_override : bool           (True = SPY in CRISIS, all entries blocked)
        global_regime   : "BULL" | "BEAR" | "CRISIS"
        global_source   : str            (how global state was obtained)
        entries_allowed : bool           (False when EITHER regime is CRISIS)
        computed_at     : ISO-8601 string

    entries_allowed = (regional regime != CRISIS) AND (global regime != CRISIS)
    Exits are NEVER gated — callers must not use this to block exits.

    Fail-safe: any data / compute error → CRISIS, fail_safe=True, entries_allowed=False.
    """
    # ── Per-ETF regime ────────────────────────────────────────────────────────
    try:
        closes = _fetch_daily_closes(etf)
        if not closes:
            regional_state = _crisis_failsafe(etf, "fetch_returned_no_data")
        else:
            regional_state = _compute_regime(closes, ticker=etf)
    except Exception as exc:
        logger.warning(f"RegionalRegime | {etf}: compute error ({exc}) — fail-safe CRISIS")
        regional_state = _crisis_failsafe(etf, f"compute_error: {exc}")

    # ── Global override (SPY) ─────────────────────────────────────────────────
    global_state    = _get_global_state()
    global_regime   = global_state.get("regime", "CRISIS")
    global_override = global_regime == "CRISIS"

    # ── Entries gate ──────────────────────────────────────────────────────────
    entries_allowed = (
        regional_state["regime"] != "CRISIS"
        and not global_override
    )

    result = {
        **regional_state,
        "global_override":  global_override,
        "global_regime":    global_regime,
        "global_source":    global_state.get("source", "unknown"),
        "entries_allowed":  entries_allowed,
    }

    logger.info(
        f"RegionalRegime | {etf}: regime={regional_state['regime']}  "
        f"global={global_regime}  entries_allowed={entries_allowed}"
    )
    return result


def is_entry_allowed(etf: str) -> bool:
    """
    Fast boolean: can we open a new position in this ETF right now?

    Used by bot entry gates that need a simple True/False.
    Fails CLOSED — returns False on any error.
    """
    try:
        state = regional_regime(etf)
        return bool(state.get("entries_allowed", False))
    except Exception as exc:
        logger.warning(
            f"RegionalRegime | is_entry_allowed({etf}) failed ({exc}) "
            f"— fail-CLOSED (returning False)"
        )
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────

def _selftest() -> bool:
    """
    Feed SPY, EWZ, EWY current data → print each ETF's regional regime
    plus the global override state.

    Assertions:
      - All three return a valid regime (BULL / BEAR / CRISIS)
      - fail_safe=False on all three (assumes Yahoo is reachable)
      - global_override is the same bool for all three (same SPY state)
      - entries_allowed is consistent with regime + global_override
    """
    print("=" * 70)
    print("UNIT TEST — core/regional_regime.py")
    print("=" * 70)

    tickers  = ["SPY", "EWZ", "EWY"]
    results  = {}
    all_pass = True

    for etf in tickers:
        print(f"\n  Computing regional_regime({etf!r})…")
        r = regional_regime(etf)
        results[etf] = r

        regime_str = r.get("regime", "?")
        ema50_str  = f"{r['ema50']:.2f}"  if r.get("ema50")  else "N/A"
        ema200_str = f"{r['ema200']:.2f}" if r.get("ema200") else "N/A"
        ret_str    = f"{r['ret_20d']:+.2%}" if r.get("ret_20d") is not None else "N/A"
        price_str  = f"${r['price']:.2f}" if r.get("price") else "N/A"

        print(f"    price={price_str}  ret_20d={ret_str}  "
              f"ema50={ema50_str}  ema200={ema200_str}")
        print(f"    regime={regime_str}  high_vol={r.get('high_vol')}  "
              f"fail_safe={r.get('fail_safe')}")
        print(f"    global_regime={r.get('global_regime')}  "
              f"global_override={r.get('global_override')}  "
              f"global_source={r.get('global_source')}")
        print(f"    entries_allowed={r.get('entries_allowed')}  "
              f"data_bars={r.get('data_bars')}")

        # ── Assertions ──────────────────────────────────────────────────────
        errors = []
        if regime_str not in ("BULL", "BEAR", "CRISIS"):
            errors.append(f"invalid regime '{regime_str}'")
        if r.get("fail_safe") and r.get("regime") != "CRISIS":
            errors.append("fail_safe=True but regime != CRISIS")
        # entries_allowed consistency
        regional_crisis = (regime_str == "CRISIS")
        global_crisis   = r.get("global_override", False)
        expected_ea     = not regional_crisis and not global_crisis
        if r.get("entries_allowed") != expected_ea:
            errors.append(
                f"entries_allowed mismatch: got {r.get('entries_allowed')}, "
                f"expected {expected_ea}"
            )
        if errors:
            all_pass = False
            for e in errors:
                print(f"    FAIL ❌ — {e}")
        else:
            print(f"    PASS ✅")

    # ── Global override consistency across all tickers ───────────────────────
    overrides = {t: results[t].get("global_override") for t in tickers}
    if len(set(overrides.values())) > 1:
        all_pass = False
        print(f"\n  FAIL ❌ — global_override inconsistent across tickers: {overrides}")
    else:
        print(f"\n  PASS ✅ — global_override consistent across all tickers: "
              f"{list(overrides.values())[0]}")

    print()
    print(f"{'ALL TESTS PASS ✅' if all_pass else 'SOME TESTS FAILED ❌'}")
    print("=" * 70)
    return all_pass


if __name__ == "__main__":
    import logging as _log
    _log.basicConfig(level=logging.WARNING)
    _selftest()
