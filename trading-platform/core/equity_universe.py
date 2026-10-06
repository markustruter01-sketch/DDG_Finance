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
from bisect import bisect_left
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


@dataclass(frozen=True)
class EquitySymbolSummary:
    """Small point-in-time summary of the bars used by screen and rank."""

    as_of_date: date
    min_sessions: int
    momentum_lookback: int | None
    skip_recent_sessions: int
    has_bars: bool
    has_current_bar: bool
    sessions_available: int
    last_data_day: date | None
    adjusted_price_artifact: bool
    median_close_60: float | None
    median_dollar_volume_60: float | None
    momentum: float | None
    prior_close: float | None

    def matches(
        self,
        as_of_date: date,
        min_sessions: int,
        momentum_lookback: int | None,
        skip_recent_sessions: int,
    ) -> bool:
        return (
            self.as_of_date == as_of_date
            and self.min_sessions == min_sessions
            and self.momentum_lookback == momentum_lookback
            and self.skip_recent_sessions == skip_recent_sessions
        )


_SCREEN_DATA: ContextVar[_ScreenData | None] = ContextVar(
    "equity_universe_screen_data", default=None
)
_LAST_OBSERVATIONS: ContextVar[dict[str, dict[str, Any]]] = ContextVar(
    "equity_universe_last_observations", default={}
)
_LAST_SUMMARIES: ContextVar[dict[str, EquitySymbolSummary]] = ContextVar(
    "equity_universe_last_summaries", default={}
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
    if getattr(value, "bars_sorted", False):
        return value.bars
    bars = getattr(value, "bars", value)
    try:
        return sorted(list(bars), key=_bar_date)
    except TypeError:
        return []


def _momentum_close(bar: Any) -> float:
    value = bar.get("c", 0) if isinstance(bar, Mapping) else getattr(bar, "c", 0)
    return float(value or 0)


def summarize_symbol_bars(
    value: Any,
    as_of_date: date,
    min_sessions: int,
    *,
    momentum_lookback: int | None = None,
    skip_recent_sessions: int = 0,
) -> EquitySymbolSummary:
    """Reduce one full bar series to the only values needed by screen and rank.

    The helper deliberately uses the same strictly-prior window and adjusted
    close, liquidity, and momentum rules as the full-bars entry points.
    """
    if min_sessions < 1:
        raise ValueError("min_sessions must be positive")
    if momentum_lookback is not None and momentum_lookback < 1:
        raise ValueError("momentum_lookback must be positive when supplied")
    if skip_recent_sessions < 0:
        raise ValueError("skip_recent_sessions must be non-negative")

    bars = _bars_for(value)
    if not bars:
        return EquitySymbolSummary(
            as_of_date=as_of_date,
            min_sessions=min_sessions,
            momentum_lookback=momentum_lookback,
            skip_recent_sessions=skip_recent_sessions,
            has_bars=False,
            has_current_bar=False,
            sessions_available=0,
            last_data_day=None,
            adjusted_price_artifact=False,
            median_close_60=None,
            median_dollar_volume_60=None,
            momentum=None,
            prior_close=None,
        )

    window_size = max(
        min_sessions,
        LIQUIDITY_SESSIONS,
        momentum_lookback or 0,
    )
    source_days = getattr(value, "days", None)
    if source_days is not None:
        cutoff = bisect_left(source_days, as_of_date)
        has_current_bar = (
            cutoff < len(source_days) and source_days[cutoff] == as_of_date
        )
        sessions_available = cutoff
        prior = bars[max(0, cutoff - window_size):cutoff]
    else:
        has_current_bar = any(_bar_date(bar) == as_of_date for bar in bars)
        all_prior = [bar for bar in bars if _bar_date(bar) < as_of_date]
        sessions_available = len(all_prior)
        prior = all_prior[-window_size:]

    last_data_day = _bar_date(prior[-1]) if prior else None
    artifact_window = prior[-min_sessions:]
    valid_closes = [
        close for bar in artifact_window
        if (close := _bar_number(bar, "c", "close")) is not None and close > 0
    ]
    adjusted_price_artifact = any(
        previous > 0 and current > 0 and (
            current / previous > MAX_ADJUSTED_CLOSE_RATIO
            or current / previous < 1 / MAX_ADJUSTED_CLOSE_RATIO
        )
        for previous, current in zip(valid_closes, valid_closes[1:])
    )

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

    median_close = (
        float(statistics.median(closes))
        if len(closes) >= LIQUIDITY_SESSIONS else None
    )
    median_dollar_volume = (
        float(statistics.median(dollar_volumes))
        if len(dollar_volumes) >= LIQUIDITY_SESSIONS else None
    )

    momentum: float | None = None
    prior_close: float | None = None
    if momentum_lookback is not None and len(prior) >= momentum_lookback:
        skip_index = skip_recent_sessions + 1
        if skip_index <= len(prior):
            old_price = _momentum_close(prior[-momentum_lookback])
            skip_end_price = _momentum_close(prior[-skip_index])
            if old_price > 0 and skip_end_price > 0:
                momentum = skip_end_price / old_price - 1.0
            prior_close = _momentum_close(prior[-1])

    return EquitySymbolSummary(
        as_of_date=as_of_date,
        min_sessions=min_sessions,
        momentum_lookback=momentum_lookback,
        skip_recent_sessions=skip_recent_sessions,
        has_bars=True,
        has_current_bar=has_current_bar,
        sessions_available=sessions_available,
        last_data_day=last_data_day,
        adjusted_price_artifact=adjusted_price_artifact,
        median_close_60=median_close,
        median_dollar_volume_60=median_dollar_volume,
        momentum=momentum,
        prior_close=prior_close,
    )


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


def last_screen_summaries(
    bars_by_symbol: Mapping[str, Any] | None = None,
) -> dict[str, EquitySymbolSummary]:
    """Return compact per-symbol summaries from the most recent screen."""
    data = _SCREEN_DATA.get()
    if (
        bars_by_symbol is not None
        and (data is None or data.bars_by_symbol is not bars_by_symbol)
    ):
        return {}
    return dict(_LAST_SUMMARIES.get())


def screen_universe(
    as_of_date: date,
    universe_size: int = 500,
    min_sessions: int = 252,
    min_price: float = 5.0,
    *,
    require_current_bar: bool = False,
    momentum_lookback: int | None = None,
    skip_recent_sessions: int = 0,
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
    summaries: dict[str, EquitySymbolSummary] = {}
    ranked_candidates: list[tuple[str, float]] = []

    for asset in asset_records:
        symbol = _canonical_symbol(_asset_value(asset, "symbol"))
        source = data.bars_by_symbol.get(symbol)
        if isinstance(source, EquitySymbolSummary):
            if not source.matches(
                as_of_date,
                min_sessions,
                momentum_lookback,
                skip_recent_sessions,
            ):
                raise ValueError(
                    f"summary parameters do not match screen inputs for {symbol}"
                )
            summary = source
        else:
            summary = summarize_symbol_bars(
                source,
                as_of_date,
                min_sessions,
                momentum_lookback=momentum_lookback,
                skip_recent_sessions=skip_recent_sessions,
            )
        summaries[symbol] = summary

        if not summary.has_bars:
            funnel["no_price_data"] += 1
            continue
        if require_current_bar and not summary.has_current_bar:
            funnel["missing_current_bar"] += 1
            continue
        if summary.sessions_available < min_sessions:
            funnel["fewer_than_min_sessions"] += 1
            continue
        funnel["history_eligible"] += 1
        if summary.adjusted_price_artifact:
            funnel["adjusted_price_artifacts"] += 1
            continue
        if (
            summary.median_close_60 is None
            or summary.median_dollar_volume_60 is None
        ):
            continue
        observation = {
            "last_data_day": summary.last_data_day,
            "sessions_available": summary.sessions_available,
            "median_close_60": summary.median_close_60,
            "median_dollar_volume_60": summary.median_dollar_volume_60,
            "asset_class": "us_equity",
            "name": str(_asset_value(asset, "name", default="") or ""),
            "exchange": str(_asset_value(asset, "exchange", default="") or ""),
            "uses_future_data": False,
        }
        observations[symbol] = observation
        if summary.median_close_60 <= min_price:
            funnel["below_min_price"] += 1
            continue
        ranked_candidates.append((symbol, summary.median_dollar_volume_60))

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
    _LAST_SUMMARIES.set(summaries)
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