"""Shared mechanical US-equity universe screening.

The live Bot 2 process supplies the unfiltered Alpaca asset response and
adjusted daily bars.  Development research supplies the same asset response
and its persisted adjusted-bar panel.  Keeping the screening boundary here
prevents the two callers from quietly growing different universes.

``screen_universe`` intentionally has a small, stable public contract:

    set_screen_data(assets, bars_by_symbol)
    symbols, funnel = screen_universe(as_of_date, universe_size, min_sessions, min_price)

The input setter is an adapter boundary, not a second implementation of the
screen.  It also lets tests use small in-memory Alpaca-shaped fixtures.
"""

from __future__ import annotations

import os
import re
import statistics
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

import requests


APPROVED_EXCHANGES = frozenset(
    {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA", "NYSEAMERICAN"}
)
LIQUIDITY_SESSIONS = 60
MAX_ADJUSTED_CLOSE_RATIO = 10.0
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

_EXCLUDED_NAME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("etf", re.compile(r"\betf\b", re.IGNORECASE)),
    ("etn", re.compile(r"\betn\b", re.IGNORECASE)),
    ("fund", re.compile(r"\bfund\b", re.IGNORECASE)),
    ("trust", re.compile(r"\btrust\b", re.IGNORECASE)),
    ("index", re.compile(r"\bindex\b", re.IGNORECASE)),
    ("warrant", re.compile(r"\bwarrant", re.IGNORECASE)),
    ("right", re.compile(r"\brights?\b", re.IGNORECASE)),
    ("unit", re.compile(r"\bunit", re.IGNORECASE)),
    ("preferred", re.compile(r"\bpreferred\b", re.IGNORECASE)),
    ("note", re.compile(r"\bnotes?\b", re.IGNORECASE)),
    ("bond", re.compile(r"\bbonds?\b", re.IGNORECASE)),
    ("shares_of_beneficial_interest", re.compile(
        r"\bshares?\s+of\s+beneficial\s+interest\b", re.IGNORECASE
    )),
    ("depositary_units", re.compile(r"\bdepositary\s+units?\b", re.IGNORECASE)),
    ("leveraged_marker", re.compile(
        r"(?:\b2x\b|\b3x\b|\bbull\b|\bbear\b|\bultra\b|\bdaily\b|\binverse\b|\bshort\b|\bleveraged\b)",
        re.IGNORECASE,
    )),
)
_EXCLUDED_SYMBOL_PATTERN = re.compile(r"\.(?:WS|U|R|P)", re.IGNORECASE)


@dataclass(frozen=True)
class _ScreenData:
    assets: tuple[Mapping[str, Any], ...]
    bars_by_symbol: Mapping[str, Any]


_SCREEN_DATA: ContextVar[_ScreenData | None] = ContextVar(
    "equity_universe_screen_data", default=None
)
_LAST_OBSERVATIONS: ContextVar[dict[str, dict[str, Any]]] = ContextVar(
    "equity_universe_last_observations", default={}
)


def _canonical_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _asset_value(asset: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if asset.get(key) is not None:
            return asset[key]
    return default


def _bar_date(bar: Any) -> date:
    if isinstance(bar, Mapping):
        value = bar.get("t") or bar.get("date")
    else:
        value = getattr(bar, "day", None) or getattr(bar, "date", None)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _bar_number(bar: Any, mapping_key: str, attribute: str) -> float | None:
    value = bar.get(mapping_key) if isinstance(bar, Mapping) else getattr(bar, attribute, None)
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _bars_for(value: Any) -> list[Any]:
    if value is None:
        return []
    bars = getattr(value, "bars", value)
    try:
        return sorted(list(bars), key=_bar_date)
    except TypeError:
        return []


def _excluded_name_reason(asset: Mapping[str, Any]) -> str | None:
    name = str(_asset_value(asset, "name", default="") or "")
    for reason, pattern in _EXCLUDED_NAME_PATTERNS:
        if pattern.search(name):
            return reason
    symbol = _canonical_symbol(_asset_value(asset, "symbol"))
    if _EXCLUDED_SYMBOL_PATTERN.search(symbol):
        return "symbol_structure"
    return None


def _static_eligibility_reason(asset: Mapping[str, Any]) -> str | None:
    if str(_asset_value(asset, "status", default="") or "").lower() != "active":
        return "inactive"
    asset_class = str(
        _asset_value(asset, "asset_class", "class", default="") or ""
    ).lower()
    if asset_class != "us_equity":
        return "asset_class"
    if not bool(_asset_value(asset, "tradable", default=False)):
        return "not_tradable"
    exchange = str(_asset_value(asset, "exchange", default="") or "").upper()
    if exchange not in APPROVED_EXCHANGES:
        return "exchange"
    return _excluded_name_reason(asset)


def asset_is_eligible(asset: Mapping[str, Any]) -> bool:
    """Return whether an Alpaca asset passes the shared static asset gates."""
    return bool(_canonical_symbol(_asset_value(asset, "symbol"))) and (
        _static_eligibility_reason(asset) is None
    )


def eligible_asset_records(
    assets: Iterable[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    """Return static candidates plus an auditable asset-only funnel."""
    records = list(assets)
    counts: dict[str, int] = {
        "total_assets": len(records),
        "inactive": 0,
        "non_us_equity": 0,
        "not_tradable": 0,
        "unapproved_exchange": 0,
        "excluded_name": 0,
        "excluded_symbol_structure": 0,
        "asset_eligible_records": 0,
        "duplicate_symbol_records": 0,
    }
    chosen: dict[str, Mapping[str, Any]] = {}
    for asset in records:
        reason = _static_eligibility_reason(asset)
        if reason is None:
            counts["asset_eligible_records"] += 1
            symbol = _canonical_symbol(_asset_value(asset, "symbol"))
            if symbol in chosen:
                counts["duplicate_symbol_records"] += 1
            else:
                chosen[symbol] = asset
            continue
        if reason == "inactive":
            counts["inactive"] += 1
        elif reason == "asset_class":
            counts["non_us_equity"] += 1
        elif reason == "not_tradable":
            counts["not_tradable"] += 1
        elif reason == "exchange":
            counts["unapproved_exchange"] += 1
        elif reason == "symbol_structure":
            counts["excluded_symbol_structure"] += 1
        else:
            counts["excluded_name"] += 1
    return list(chosen.values()), counts


def set_screen_data(
    assets: Iterable[Mapping[str, Any]],
    bars_by_symbol: Mapping[str, Any],
) -> None:
    """Set the normalized input boundary used by the four-argument screen."""
    _SCREEN_DATA.set(_ScreenData(tuple(assets), bars_by_symbol))


def last_screen_observations() -> dict[str, dict[str, Any]]:
    """Return metrics from the most recent screen for ranking/reporting."""
    return {symbol: dict(value) for symbol, value in _LAST_OBSERVATIONS.get().items()}


def screen_universe(
    as_of_date: date,
    universe_size: int = 500,
    min_sessions: int = 252,
    min_price: float = 5.0,
    *,
    require_current_bar: bool = False,
) -> tuple[set[str], dict[str, Any]]:
    """Apply one point-in-time screen to the configured asset/bar data.

    All bars used for history, price, liquidity, and artifact checks are
    strictly earlier than ``as_of_date``.  The result is a deterministic
    top-ranked set, ordered by trailing median dollar volume and then symbol.
    ``require_current_bar`` is available to callers whose execution day must
    also be present in the supplied panel; it never permits current-day data
    into the screening observations.
    """
    data = _SCREEN_DATA.get()
    if data is None:
        raise RuntimeError("set_screen_data must be called before screen_universe")
    if universe_size < 1:
        raise ValueError("universe_size must be positive")
    if min_sessions < LIQUIDITY_SESSIONS:
        raise ValueError("min_sessions must be at least the liquidity window")
    if min_price < 0:
        raise ValueError("min_price must be non-negative")

    asset_records, asset_counts = eligible_asset_records(data.assets)
    funnel = dict(asset_counts)
    funnel.update({
        "history_eligible": 0,
        "no_price_data": 0,
        "fewer_than_min_sessions": 0,
        "missing_current_bar": 0,
        "adjusted_price_artifacts": 0,
        "below_min_price": 0,
        "ranked_candidates": 0,
        "rank_cutoff_dollar_volume": None,
        "qualifying_symbols": 0,
    })
    observations: dict[str, dict[str, Any]] = {}
    ranked_candidates: list[tuple[str, float]] = []

    for asset in asset_records:
        symbol = _canonical_symbol(_asset_value(asset, "symbol"))
        bars = _bars_for(data.bars_by_symbol.get(symbol))
        if not bars:
            funnel["no_price_data"] += 1
            continue
        if require_current_bar and not any(_bar_date(bar) == as_of_date for bar in bars):
            funnel["missing_current_bar"] += 1
            continue
        prior = [bar for bar in bars if _bar_date(bar) < as_of_date]
        if len(prior) < min_sessions:
            funnel["fewer_than_min_sessions"] += 1
            continue
        funnel["history_eligible"] += 1
        # Live screening only requests a bounded recent history window.  A
        # research panel may contain older split artifacts that the live
        # caller cannot observe; artifact detection must therefore be
        # point-in-time over the same lookback used for eligibility.
        artifact_window = prior[-min_sessions:]
        valid_closes = [
            close for bar in prior
            if bar in artifact_window
            if (close := _bar_number(bar, "c", "close")) is not None and close > 0
        ]
        artifact = any(
            previous > 0 and current > 0 and (
                current / previous > MAX_ADJUSTED_CLOSE_RATIO
                or current / previous < 1 / MAX_ADJUSTED_CLOSE_RATIO
            )
            for previous, current in zip(valid_closes, valid_closes[1:])
        )
        if artifact:
            funnel["adjusted_price_artifacts"] += 1
            continue
        trailing = prior[-LIQUIDITY_SESSIONS:]
        closes: list[float] = []
        dollar_volumes: list[float] = []
        for bar in trailing:
            close = _bar_number(bar, "c", "close")
            volume = _bar_number(bar, "v", "volume")
            if close is None or volume is None or close <= 0 or volume < 0:
                continue
            closes.append(close)
            dollar_volumes.append(close * volume)
        if len(closes) < LIQUIDITY_SESSIONS:
            continue
        median_close = float(statistics.median(closes))
        median_dollar_volume = float(statistics.median(dollar_volumes))
        observation = {
            "last_data_day": _bar_date(prior[-1]),
            "sessions_available": len(prior),
            "median_close_60": median_close,
            "median_dollar_volume_60": median_dollar_volume,
            "asset_class": "us_equity",
            "name": str(_asset_value(asset, "name", default="") or ""),
            "exchange": str(_asset_value(asset, "exchange", default="") or ""),
            "uses_future_data": False,
        }
        observations[symbol] = observation
        if median_close <= min_price:
            funnel["below_min_price"] += 1
            continue
        ranked_candidates.append((symbol, median_dollar_volume))

    ranked_candidates.sort(key=lambda item: (-item[1], item[0]))
    funnel["ranked_candidates"] = len(ranked_candidates)
    if ranked_candidates:
        selected = ranked_candidates[:universe_size]
        funnel["rank_cutoff_dollar_volume"] = selected[-1][1]
    else:
        selected = []
    qualifying = {symbol for symbol, _ in selected}
    funnel["qualifying_symbols"] = len(qualifying)
    _LAST_OBSERVATIONS.set(observations)
    return qualifying, funnel


def fetch_alpaca_assets(
    api_key: str | None = None,
    secret_key: str | None = None,
    base_url: str = ALPACA_BASE_URL,
) -> list[dict[str, Any]]:
    """Read the unfiltered Alpaca asset catalogue for development research."""
    api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
    secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required for asset discovery")
    response = requests.get(
        base_url.rstrip("/") + "/v2/assets",
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Alpaca asset endpoint returned a non-list payload")
    return payload