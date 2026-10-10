"""Forex quant desk (Phase 3): daily signal sheet and the registered baseline call.

Read-only. Uses only OANDA practice data already exposed by OandaClient.
No orders, no AI, no database writes. The baseline rule below is registered in
businesses/finance/forex-registered-plan-2026-10-10.md; changing it after the
first logged decision is a new plan.
"""

from __future__ import annotations

import math
from typing import Any

# Registered pairs (plan item 2).
FOREX_PAIRS = (
    "EUR_USD",
    "USD_JPY",
    "GBP_USD",
    "AUD_USD",
    "USD_CAD",
    "USD_CHF",
    "NZD_USD",
)

# Registered baseline rule (time-series trend + momentum). Chosen before any
# test was run on it; no variants explored.
TREND_SMA_DAYS = 100
MOMENTUM_DAYS = 63
ATR_DAYS = 14
STOP_ATR_MULTIPLE = 2.0

SHORT_MOMENTUM_DAYS = 20
VOL_DAYS = 20
CANDLES_NEEDED = TREND_SMA_DAYS + 1  # also covers MOMENTUM_DAYS + 1 and ATR_DAYS + 1
CANDLES_REQUESTED = 130

UNAVAILABLE = "unavailable"


def _mid(candle: dict[str, Any], key: str) -> float:
    value = float(candle["mid"][key])
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"candle mid {key} must be positive and finite")
    return value


def _ohlc(candles: list[dict[str, Any]]) -> tuple[list[float], list[float], list[float]]:
    highs = [_mid(c, "h") for c in candles]
    lows = [_mid(c, "l") for c in candles]
    closes = [_mid(c, "c") for c in candles]
    return highs, lows, closes


def _atr(highs: list[float], lows: list[float], closes: list[float], days: int) -> float:
    true_ranges = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(len(closes) - days, len(closes))
    ]
    return sum(true_ranges) / days


def _annualised_vol(closes: list[float], days: int) -> float:
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - days, len(closes))]
    mean = sum(returns) / days
    variance = sum((r - mean) ** 2 for r in returns) / (days - 1)
    return math.sqrt(variance) * math.sqrt(252)


def _carry(financing: dict[str, Any] | None) -> dict[str, Any]:
    """Annual financing rates from OANDA instrument details, if present."""
    if not isinstance(financing, dict):
        return {"long_rate": None, "short_rate": None, "status": UNAVAILABLE}
    try:
        long_rate = float(financing["longRate"])
        short_rate = float(financing["shortRate"])
    except (KeyError, TypeError, ValueError):
        return {"long_rate": None, "short_rate": None, "status": UNAVAILABLE}
    return {"long_rate": long_rate, "short_rate": short_rate, "status": "ok"}


def signal_row(
    pair: str,
    candles: list[dict[str, Any]],
    *,
    financing: dict[str, Any] | None = None,
    spread: float | None = None,
) -> dict[str, Any]:
    """Build one pair's signal row from complete daily mid candles (oldest first)."""
    if len(candles) < CANDLES_NEEDED:
        raise ValueError(
            f"{pair}: need {CANDLES_NEEDED} complete daily candles, got {len(candles)}"
        )
    highs, lows, closes = _ohlc(candles)
    close = closes[-1]
    sma = sum(closes[-TREND_SMA_DAYS:]) / TREND_SMA_DAYS
    atr = _atr(highs, lows, closes, ATR_DAYS)
    return {
        "pair": pair,
        "as_of": candles[-1].get("time"),
        "close": close,
        "sma_trend": sma,
        "trend": "up" if close > sma else "down" if close < sma else "flat",
        "momentum_return": close / closes[-1 - MOMENTUM_DAYS] - 1,
        "short_momentum_return": close / closes[-1 - SHORT_MOMENTUM_DAYS] - 1,
        "atr": atr,
        "atr_pct": atr / close,
        "realised_vol": _annualised_vol(closes, VOL_DAYS),
        "spread": spread,
        "spread_to_atr": (spread / atr) if spread is not None and atr > 0 else None,
        "carry": _carry(financing),
        "calendar": UNAVAILABLE,
        "positioning": UNAVAILABLE,
    }


def baseline_call(row: dict[str, Any]) -> dict[str, Any]:
    """Registered baseline: long if above trend and momentum positive; short if
    below trend and momentum negative; otherwise flat. Stop = 2 x ATR(14)."""
    momentum = row["momentum_return"]
    if row["trend"] == "up" and momentum > 0:
        direction = "long"
    elif row["trend"] == "down" and momentum < 0:
        direction = "short"
    else:
        direction = "flat"
    stop_distance = STOP_ATR_MULTIPLE * row["atr"]
    stop_price = None
    if direction == "long":
        stop_price = row["close"] - stop_distance
    elif direction == "short":
        stop_price = row["close"] + stop_distance
    return {
        "direction": direction,
        "stop_distance": stop_distance,
        "stop_price": stop_price,
        "rule": (
            f"close vs SMA{TREND_SMA_DAYS} and {MOMENTUM_DAYS}-day return agree; "
            f"stop {STOP_ATR_MULTIPLE:g} x ATR{ATR_DAYS}"
        ),
    }


def build_signal_sheet(client: Any) -> dict[str, Any]:
    """Read OANDA data for every registered pair and return the day's sheet.

    A pair that cannot be read is reported with its error and a flat baseline;
    it never stops the other pairs.
    """
    financing_by_pair: dict[str, Any] = {}
    sheet_errors: list[str] = []
    try:
        for instrument in client.tradeable_instruments():
            name = instrument.get("name")
            if name in FOREX_PAIRS:
                financing_by_pair[name] = instrument.get("financing")
    except Exception as exc:  # carry is optional; the sheet still runs
        sheet_errors.append(f"instruments: {exc}")

    rows: list[dict[str, Any]] = []
    for pair in FOREX_PAIRS:
        try:
            candles = client.daily_candles(pair, count=CANDLES_REQUESTED)
            quote = client.current_bid_ask(pair)
            row = signal_row(
                pair,
                candles,
                financing=financing_by_pair.get(pair),
                spread=float(quote["spread"]),
            )
            row["baseline"] = baseline_call(row)
        except Exception as exc:
            row = {
                "pair": pair,
                "error": str(exc),
                "baseline": {"direction": "flat", "stop_distance": None, "stop_price": None,
                             "rule": "no data"},
            }
        rows.append(row)
    return {"rows": rows, "errors": sheet_errors}
