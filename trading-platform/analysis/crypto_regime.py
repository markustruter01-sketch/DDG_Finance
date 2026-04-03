"""
crypto_regime.py — Independent Crypto Regime Classifier (Stage 3)
=================================================================
Decouples crypto trading from equity-driven market_regime.json.

Instead of blindly inheriting the Alpaca pipeline's Bear/Bull regime
(which is driven by SPY, VIX, Yield Curve), this module produces an
independent crypto-native regime using:

  1. Crypto Fear & Greed Index  (alternative.me API)
  2. BTC 24h price change       (proxy for crypto-native risk appetite)
  3. BTC dominance trend        (from CoinGecko)
  4. Equity regime contagion    (only applied when correlation is high)

Output: crypto_regime.json with fields:
  - crypto_regime: "Crypto-Bull" | "Crypto-Bear" | "Crypto-Sideways" | "Crypto-Risk-Off"
  - equity_contagion: bool  (True if equity Bear AND crypto correlation > 0.6)
  - crypto_fear_greed: int  (0-100)
  - btc_24h_change_pct: float
  - confidence: float (0-1)

The Kraken bots read this file instead of market_regime.json for entry gating.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

_DATA_DIR = Path(__file__).parent.parent / "data"
_CRYPTO_REGIME_FILE = _DATA_DIR / "crypto_regime.json"
_EQUITY_REGIME_FILE = _DATA_DIR / "market_regime.json"

_CACHE_TTL = 1800

_cache: dict[str, Any] = {"data": None, "ts": 0}


def _fetch_crypto_fear_greed() -> int | None:
    try:
        r = httpx.get(
            "https://api.alternative.me/fng/?limit=1&format=json",
            timeout=10,
        )
        r.raise_for_status()
        return int(r.json()["data"][0]["value"])
    except Exception as exc:
        logger.warning(f"CryptoRegime | Fear & Greed fetch failed: {exc}")
        return None


def _fetch_btc_24h_change() -> float | None:
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin&vs_currencies=usd&include_24hr_change=true",
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["bitcoin"]["usd_24h_change"]
    except Exception as exc:
        logger.warning(f"CryptoRegime | BTC 24h change fetch failed: {exc}")
        return None


def _fetch_btc_dominance() -> float | None:
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["data"]["market_cap_percentage"]["btc"]
    except Exception as exc:
        logger.debug(f"CryptoRegime | BTC dominance fetch failed: {exc}")
        return None


def _read_equity_regime() -> dict:
    try:
        if _EQUITY_REGIME_FILE.exists():
            return json.loads(_EQUITY_REGIME_FILE.read_text())
    except Exception:
        pass
    return {}


def classify_crypto_regime(
    correlation_with_equity: float = 0.0,
) -> dict:
    """
    Produce an independent crypto regime classification.

    Parameters
    ----------
    correlation_with_equity : float
        Rolling 60-day Pearson correlation between equity and crypto returns.
        If > 0.6 AND equity is Bear, the crypto regime inherits contagion.

    Returns
    -------
    dict with crypto_regime, confidence, and supporting data.
    """
    fg = _fetch_crypto_fear_greed()
    btc_change = _fetch_btc_24h_change()
    btc_dom = _fetch_btc_dominance()
    eq_regime = _read_equity_regime()

    score = 50.0
    signals_available = 0

    if fg is not None:
        signals_available += 1
        if fg >= 75:
            score += 25
        elif fg >= 55:
            score += 10
        elif fg <= 25:
            score -= 25
        elif fg <= 40:
            score -= 10

    if btc_change is not None:
        signals_available += 1
        if btc_change > 5:
            score += 15
        elif btc_change > 2:
            score += 8
        elif btc_change < -5:
            score -= 20
        elif btc_change < -2:
            score -= 10

    eq_is_bear = eq_regime.get("regime", "") in {
        "Bear", "RISK-OFF", "Risk-Off", "bear", "risk-off",
    }
    equity_contagion = eq_is_bear and correlation_with_equity > 0.6

    if equity_contagion:
        signals_available += 1
        contagion_penalty = min(20, correlation_with_equity * 25)
        score -= contagion_penalty
        logger.info(
            f"CryptoRegime | Equity contagion active — "
            f"corr={correlation_with_equity:.2f}, penalty={contagion_penalty:.1f}"
        )

    score = max(0, min(100, score))

    if score >= 65:
        regime = "Crypto-Bull"
    elif score <= 20:
        regime = "Crypto-Risk-Off"
    elif score <= 35:
        regime = "Crypto-Bear"
    else:
        regime = "Crypto-Sideways"

    confidence = min(1.0, signals_available / 3.0)

    result = {
        "crypto_regime": regime,
        "score": round(score, 1),
        "confidence": round(confidence, 2),
        "equity_contagion": equity_contagion,
        "equity_regime": eq_regime.get("regime", "unknown"),
        "correlation_with_equity": round(correlation_with_equity, 3),
        "crypto_fear_greed": fg,
        "btc_24h_change_pct": round(btc_change, 2) if btc_change else None,
        "btc_dominance": round(btc_dom, 1) if btc_dom else None,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CRYPTO_REGIME_FILE.write_text(json.dumps(result, indent=2))
        logger.debug(f"CryptoRegime | Written: {regime} (score={score:.1f})")
    except Exception as exc:
        logger.warning(f"CryptoRegime | File write failed: {exc}")

    _cache["data"] = result
    _cache["ts"] = time.time()

    return result


def get_cached_crypto_regime() -> dict | None:
    if _cache["data"] and (time.time() - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        if _CRYPTO_REGIME_FILE.exists():
            data = json.loads(_CRYPTO_REGIME_FILE.read_text())
            written = data.get("written_at", "")
            if written:
                from datetime import datetime as _dt
                age = (datetime.now(timezone.utc) - _dt.fromisoformat(written)).total_seconds()
                if age < _CACHE_TTL:
                    _cache["data"] = data
                    _cache["ts"] = time.time()
                    return data
    except Exception:
        pass

    return None


CRYPTO_BEAR_REGIMES = frozenset({"Crypto-Bear", "Crypto-Risk-Off"})
