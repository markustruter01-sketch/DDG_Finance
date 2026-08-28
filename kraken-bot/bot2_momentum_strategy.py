"""Bot 2 single-stock momentum strategy.

This module is intentionally separate from the legacy SPY/QQQ ETF strategy.
It implements the Experiment 17 live-shaped execution boundary.  Activation
remains controlled by the module, profile, database, and universe gate.

The research signal is deliberately mechanical:
  * Alpaca-tradable US equities only (no index-membership data)
  * 252 prior sessions, trailing 60-session median dollar volume >= $59.724M
  * trailing 60-session median close > $5
  * 12-1 momentum, with the most recent 21 sessions skipped
  * top 20, equal weight, monthly first-trading-day rebalance
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import requests

_ROOT = Path(__file__).resolve().parents[1]
_TRADING_PLATFORM = str(_ROOT / "trading-platform")
if _TRADING_PLATFORM in sys.path:
    sys.path.remove(_TRADING_PLATFORM)
sys.path.insert(0, _TRADING_PLATFORM)

from db.postgres import get_conn  # noqa: E402

try:
    from core.order_ids import submit_with_unique_client_order_id
    from core.order_ids import client_order_id_matches_prefix
except Exception:  # pragma: no cover - only relevant to a broken deployment
    submit_with_unique_client_order_id = None
    client_order_id_matches_prefix = None


logger = logging.getLogger("bot2.momentum")

BOT_ID = "spy_qqq_trend"
BOT_PAUSED = True
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
MAX_POSITIONS = 20
SLIPPAGE_BPS = 10
MIN_PRIOR_SESSIONS = 252
SKIP_RECENT_SESSIONS = 21
SCREEN_SESSIONS = 60
MIN_MEDIAN_DOLLAR_VOLUME = 59_724_166.23
MIN_MEDIAN_CLOSE = 5.0
MAX_DEPLOYMENT = 1.00
STOP_LOSS_PCT = 0.20
MOMENTUM_ARTEFACT_THRESHOLD = float(
    os.environ.get("BOT2_MOMENTUM_ARTEFACT_THRESHOLD", "3.0")
)
MAX_ADJUSTED_CLOSE_RATIO = 10.0
PARK_SYMBOL = "SGOV"
SECTOR_CACHE_FILE = _ROOT / "trading-platform" / ".local" / "bot2_fullmarket_sector_cache.json"
STRATEGY_TABLE = "bot2_momentum_positions"
US_EQUITY_EXCHANGES = frozenset(
    {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA", "NYSEAMERICAN"}
)
EQUITY_SESSION_OPEN = dt_time(9, 30)
EQUITY_SESSION_CLOSE = dt_time(16, 0)
ORDINARY_SHARE_NAME_PATTERNS = (
    re.compile(r"\bcommon stock\b", re.IGNORECASE),
    re.compile(r"\bcommon shares?\b", re.IGNORECASE),
    re.compile(r"\bordinary shares?\b", re.IGNORECASE),
    re.compile(r"\bamerican depositary shares?\b", re.IGNORECASE),
)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {STRATEGY_TABLE} (
    id              BIGSERIAL PRIMARY KEY,
    bot_id          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    entry_price     NUMERIC NOT NULL,
    notional_usd    NUMERIC NOT NULL,
    stop_price      NUMERIC NOT NULL,
    stop_order_id   TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    exit_reason     TEXT,
    realised_pnl    NUMERIC
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot2_momentum_open_symbol
    ON {STRATEGY_TABLE} (bot_id, symbol) WHERE status = 'open';
"""


def canonical_symbol(symbol: Any) -> str:
    """Return a stable equity identity without changing Alpaca's order symbol."""
    return str(symbol or "").strip().upper()


def _bar_date(bar: dict[str, Any]) -> date:
    value = bar.get("t") or bar.get("date")
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _prior_bars(bars: list[dict[str, Any]], as_of: date) -> list[dict[str, Any]]:
    """Only retain observations strictly before the rebalance date."""
    return sorted(
        [bar for bar in bars if _bar_date(bar) < as_of],
        key=_bar_date,
    )


def has_adjusted_price_artifact(bars: list[dict[str, Any]]) -> bool:
    """Flag impossible-looking adjusted-price discontinuities for review."""
    ordered = sorted(bars, key=_bar_date)
    for previous, current in zip(ordered, ordered[1:]):
        previous_close = float(previous.get("c", 0) or 0)
        current_close = float(current.get("c", 0) or 0)
        if previous_close <= 0 or current_close <= 0:
            continue
        ratio = current_close / previous_close
        if ratio > MAX_ADJUSTED_CLOSE_RATIO or ratio < 1 / MAX_ADJUSTED_CLOSE_RATIO:
            return True
    return False


def asset_instrument_class(asset: dict[str, Any]) -> str:
    """Classify from provider metadata, never from a symbol blocklist.

    Alpaca's asset endpoint exposes a descriptive security name but no
    dedicated ETF/common-stock type.  The positive ordinary-share patterns are
    intentionally conservative; unknown instruments are excluded and reported.
    """
    explicit_type = str(
        asset.get("instrument_type")
        or asset.get("security_type")
        or asset.get("asset_type")
        or ""
    ).strip().lower()
    if explicit_type in {"common_stock", "ordinary_share", "stock", "equity"}:
        return "ordinary_equity"
    if explicit_type in {
        "etf", "etn", "fund", "mutual_fund", "preferred", "warrant",
        "right", "unit", "closed_end_fund",
    }:
        return "non_ordinary"
    name = str(asset.get("name") or "").strip()
    if name and any(pattern.search(name) for pattern in ORDINARY_SHARE_NAME_PATTERNS):
        return "ordinary_equity"
    return "unknown"


def filter_ordinary_equity_assets(
    assets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return only ordinary operating-company shares and an audit report."""
    base_candidates = [
        asset for asset in assets
        if (
            str(asset.get("status", "active")).lower() == "active"
            and str(asset.get("asset_class", asset.get("class", "us_equity"))).lower()
            == "us_equity"
            and bool(asset.get("tradable"))
            and str(asset.get("exchange", "")).upper() in US_EQUITY_EXCHANGES
        )
    ]
    ordinary = [asset for asset in base_candidates if asset_instrument_class(asset) == "ordinary_equity"]
    non_ordinary = [
        asset for asset in base_candidates if asset_instrument_class(asset) == "non_ordinary"
    ]
    unknown = [
        asset for asset in base_candidates if asset_instrument_class(asset) == "unknown"
    ]
    report = {
        "total_assets": len(assets),
        "tradable_us_equity_assets": len(base_candidates),
        "ordinary_equity_assets": len(ordinary),
        "excluded_non_ordinary": len(non_ordinary),
        "excluded_unknown_metadata": len(unknown),
        "metadata_complete": not unknown,
        "provider_limitation": (
            "Alpaca does not expose a dedicated ETF/common-stock type; "
            "unknown instruments are excluded until Polygon/Massive reference "
            "tickers or a licensed security master supplies a security type."
            if unknown else None
        ),
        "excluded_symbols": sorted(
            canonical_symbol(asset.get("symbol")) for asset in non_ordinary + unknown
        ),
    }
    return ordinary, report


UNIVERSE_GATE_FILE = (
    _ROOT / "trading-platform" / ".local" / "bot2_universe_gate.json"
)


def universe_gate_is_passed() -> bool:
    """Require a development parity artifact before any future activation."""
    try:
        payload = json.loads(UNIVERSE_GATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload.get("status") == "PASS" and bool(
        payload.get("historical_parity_required")
    )


def _asset_is_tradable_us_equity(asset: dict[str, Any]) -> bool:
    return (
        str(asset.get("status", "active")).lower() == "active"
        and str(asset.get("asset_class", asset.get("class", "us_equity"))).lower()
        == "us_equity"
        and bool(asset.get("tradable"))
        and str(asset.get("exchange", "")).upper() in US_EQUITY_EXCHANGES
        and asset_instrument_class(asset) == "ordinary_equity"
    )


def screen_universe(
    assets: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    as_of: date,
) -> dict[str, dict[str, float]]:
    """Apply the mechanical, point-in-time universe gates."""
    screened: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not _asset_is_tradable_us_equity(asset):
            continue
        symbol = canonical_symbol(asset.get("symbol"))
        bars = _prior_bars(bars_by_symbol.get(symbol, []), as_of)
        if len(bars) < MIN_PRIOR_SESSIONS:
            continue
        if has_adjusted_price_artifact(bars):
            logger.warning(
                "Bot 2 | adjusted-price artefact excluded symbol=%s", symbol
            )
            continue
        trailing = bars[-SCREEN_SESSIONS:]
        closes = [float(bar.get("c", 0) or 0) for bar in trailing]
        dollar_volumes = [
            float(bar.get("v", 0) or 0) * float(bar.get("c", 0) or 0)
            for bar in trailing
        ]
        if (
            median(dollar_volumes) < MIN_MEDIAN_DOLLAR_VOLUME
            or median(closes) <= MIN_MEDIAN_CLOSE
        ):
            continue
        screened[symbol] = {
            "median_dollar_volume": float(median(dollar_volumes)),
            "median_close": float(median(closes)),
            "asset_class": "ordinary_equity",
        }
    return screened


def momentum_12_1(bars: list[dict[str, Any]], as_of: date) -> float | None:
    """Return 12-1 momentum: price 21 sessions ago / price 252 sessions ago."""
    prior = _prior_bars(bars, as_of)
    if len(prior) < MIN_PRIOR_SESSIONS:
        return None
    old_price = float(prior[-MIN_PRIOR_SESSIONS].get("c", 0) or 0)
    skip_end_price = float(prior[-SKIP_RECENT_SESSIONS - 1].get("c", 0) or 0)
    if old_price <= 0 or skip_end_price <= 0:
        return None
    return skip_end_price / old_price - 1.0


def rank_momentum(
    screened: dict[str, dict[str, Any]],
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    as_of: date,
    top_n: int = MAX_POSITIONS,
) -> list[dict[str, float | str]]:
    ranked = []
    for symbol in screened:
        score = momentum_12_1(bars_by_symbol.get(symbol, []), as_of)
        if score is not None and math.isfinite(score):
            if score > MOMENTUM_ARTEFACT_THRESHOLD:
                logger.warning(
                    "Bot 2 | momentum artefact flagged and excluded symbol=%s score=%.4f threshold=%.4f",
                    symbol, score, MOMENTUM_ARTEFACT_THRESHOLD,
                )
                continue
            ranked.append({
                "symbol": symbol,
                "momentum": score,
                "asset_class": screened[symbol].get("asset_class", "ordinary_equity"),
                "median_dollar_volume": screened[symbol]["median_dollar_volume"],
                "price": float(_prior_bars(bars_by_symbol.get(symbol, []), as_of)[-1]["c"]),
            })
    return sorted(ranked, key=lambda item: (-float(item["momentum"]), str(item["symbol"])))[:top_n]


def _sector_map() -> dict[str, str]:
    """Load descriptive sector labels without making them a selection gate."""
    try:
        payload = json.loads(SECTOR_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {canonical_symbol(key): str(value) for key, value in payload.items()}
    except (OSError, ValueError):
        pass
    try:
        from execution.momentum_universe import TICKER_TO_SECTOR
        return {canonical_symbol(key): str(value) for key, value in TICKER_TO_SECTOR.items()}
    except Exception:
        return {}


def is_first_trading_day(now: datetime) -> bool:
    """Use NYSE holidays when available; otherwise fail safely to weekdays."""
    eastern = now.astimezone(_eastern())
    if eastern.weekday() >= 5:
        return False
    try:
        import holidays
        holiday_dates = set(holidays.NYSE(years=eastern.year).keys())
    except Exception:
        holiday_dates = set()
    if eastern.date() in holiday_dates:
        return False
    for day_number in range(1, eastern.day):
        candidate = eastern.date().replace(day=day_number)
        if candidate.weekday() < 5 and candidate not in holiday_dates:
            return False
    return True


def _eastern():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # pragma: no cover
        return timezone.utc


def us_equity_session_open(now: datetime) -> bool:
    eastern = now.astimezone(_eastern())
    return (
        eastern.weekday() < 5
        and EQUITY_SESSION_OPEN <= eastern.time().replace(tzinfo=None) < EQUITY_SESSION_CLOSE
    )


def allocation_plan(
    equity: float,
    vault_market_value: float,
    selected_count: int,
    max_deployment: float = MAX_DEPLOYMENT,
) -> dict[str, Any]:
    """Return the vault-excluded equal-weight sizing base."""
    equity = max(0.0, float(equity))
    vault_market_value = max(0.0, float(vault_market_value))
    investable_base = max(0.0, equity - vault_market_value)
    strategy_cap = max(0.0, equity * float(max_deployment) - vault_market_value)
    target_base = min(investable_base, strategy_cap)
    count = max(0, int(selected_count))
    equal_weight_notional = target_base / count if count else 0.0
    return {
        "equity": equity,
        "vault_market_value": vault_market_value,
        "investable_base": investable_base,
        "target_base": target_base,
        "selected_count": count,
        "equal_weight_notional": equal_weight_notional,
        "projected_deployment": (
            (vault_market_value + target_base) / equity if equity > 0 else 0.0
        ),
    }


def fresh_buy_guard(
    account: dict[str, float],
    positions: list[dict[str, Any]],
    notional: float,
    *,
    max_deployment: float = MAX_DEPLOYMENT,
    excluded_symbols: set[str] | frozenset[str] = frozenset(),
) -> tuple[bool, dict[str, float]]:
    """Project one buy from a freshly fetched whole-account snapshot."""
    equity = float(account.get("equity", 0) or 0)
    cash = float(account.get("cash", 0) or 0)
    long_market_value = account.get("long_market_value")
    if long_market_value is None:
        long_market_value = sum(
            max(0.0, float(position.get("market_value", 0) or 0))
            for position in positions
        )
    long_market_value = float(long_market_value or 0)
    excluded_value = sum(
        max(0.0, float(position.get("market_value", 0) or 0))
        for position in positions
        if canonical_symbol(position.get("symbol")) in excluded_symbols
    )
    projected_cash = cash - float(notional)
    projected_long = long_market_value + float(notional)
    projected_strategy = projected_long - excluded_value
    projected_deployment = projected_strategy / equity if equity > 0 else float("inf")
    projection = {
        "fresh_equity": equity,
        "fresh_cash": cash,
        "fresh_long_market_value": long_market_value,
        "estimated_notional": float(notional),
        "projected_cash": projected_cash,
        "projected_long_market_value": projected_long,
        "projected_strategy_market_value": projected_strategy,
        "projected_deployment": projected_deployment,
        "max_deployment": float(max_deployment),
    }
    return (
        equity > 0
        and projected_cash >= 0
        and projected_long <= equity
        and projected_deployment <= float(max_deployment)
    ), projection


class AlpacaMomentumClient:
    """Small direct adapter with no ETF-engine schema or order side effects."""

    def __init__(self, api_key: str, secret_key: str, base_url: str = ALPACA_BASE_URL):
        if not api_key or not secret_key:
            raise RuntimeError("Bot 2 requires Alpaca credentials")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(method, self.base_url + path, timeout=30, **kwargs)
        if not response.ok:
            raise requests.HTTPError(
                f"{response.status_code} {response.reason}: {response.text}",
                response=response,
            )
        return response.json() if response.content else None

    def _data_request(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in range(6):
            response = self.session.request(
                method, ALPACA_DATA_BASE_URL + path, timeout=30, **kwargs
            )
            if response.status_code != 429:
                response.raise_for_status()
                return response.json() if response.content else None
            if attempt == 5:
                response.raise_for_status()
            wait_seconds = min(16, 2 ** attempt)
            logger.warning(
                "Bot 2 | Alpaca data rate limit path=%s retry_in=%ss",
                path, wait_seconds,
            )
            time.sleep(wait_seconds)
        raise RuntimeError(f"Alpaca data request exhausted retries: {path}")

    def account(self) -> dict[str, float]:
        raw = self._request("GET", "/v2/account")
        result = {key: float(raw[key]) for key in ("equity", "cash", "buying_power")}
        if raw.get("long_market_value") is not None:
            result["long_market_value"] = float(raw["long_market_value"])
        return result

    def positions(self) -> list[dict[str, Any]]:
        result = []
        for position in self._request("GET", "/v2/positions") or []:
            result.append({
                "symbol": canonical_symbol(position["symbol"]),
                "qty": float(position["qty"]),
                "entry_price": float(position["avg_entry_price"]),
                "current_price": float(position["current_price"]),
                "market_value": float(position["market_value"]),
            })
        return result

    def assets(self) -> list[dict[str, Any]]:
        return self._request(
            "GET", "/v2/assets",
            params={"status": "active", "asset_class": "us_equity"},
        ) or []

    def daily_bars(
        self, symbols: list[str], as_of: date, batch_size: int = 100
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        start = as_of - timedelta(days=540)
        for offset in range(0, len(symbols), batch_size):
            batch = symbols[offset:offset + batch_size]
            token = None
            while True:
                params = {
                    "symbols": ",".join(batch),
                    "timeframe": "1Day",
                    "start": start.isoformat(),
                    "end": as_of.isoformat(),
                    "limit": 10000,
                    "adjustment": "all",
                    "feed": os.environ.get("BOT2_ALPACA_DATA_FEED", "iex"),
                    "sort": "asc",
                }
                if token:
                    params["page_token"] = token
                payload = self._data_request("GET", "/v2/stocks/bars", params=params) or {}
                for symbol, bars in (payload.get("bars") or {}).items():
                    result.setdefault(canonical_symbol(symbol), []).extend(bars or [])
                token = payload.get("next_page_token")
                if not token:
                    break
        return result

    def latest_price(self, symbol: str) -> float:
        payload = self._data_request(
            "GET", f"/v2/stocks/{canonical_symbol(symbol)}/quotes/latest"
        )
        quote = (payload or {}).get("quote", {})
        bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
        if bid <= 0 and ask <= 0:
            raise RuntimeError(f"missing Alpaca quote for {symbol}")
        return (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)

    def submit(self, symbol: str, side: str, qty: int, order_type: str, **extra: Any) -> dict[str, Any]:
        if submit_with_unique_client_order_id is None:
            raise RuntimeError("unique Alpaca order-id helper unavailable")
        payload = {
            "symbol": canonical_symbol(symbol),
            "side": side,
            "type": order_type,
            "qty": str(int(qty)),
            "time_in_force": "gtc" if order_type == "stop" else "day",
            **extra,
        }
        response, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: self._request(
                "POST", "/v2/orders",
                json={**payload, "client_order_id": generated_id},
            ),
            f"bot2-momentum-{side}-{canonical_symbol(symbol)}",
        )
        response.setdefault("client_order_id", client_order_id)
        return response

    def wait_for_fill(self, order_id: str, attempts: int = 30) -> dict[str, Any]:
        terminal = {"filled", "partially_filled", "canceled", "rejected", "expired", "done_for_day"}
        latest: dict[str, Any] = {}
        for attempt in range(attempts):
            latest = self._request("GET", f"/v2/orders/{order_id}") or {}
            if str(latest.get("status", "")).lower() in terminal:
                return latest
            if attempt < attempts - 1:
                time.sleep(1)
        return latest

    def open_orders(self) -> list[dict[str, Any]]:
        return self._request(
            "GET", "/v2/orders",
            params={"status": "open", "limit": 500, "nested": "true"},
        ) or []

    def cancel_confirm(self, order_id: str, timeout_seconds: int = 5) -> bool:
        try:
            self._request("DELETE", f"/v2/orders/{order_id}")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                order = self._request("GET", f"/v2/orders/{order_id}") or {}
                if str(order.get("status", "")).lower() in {"canceled", "expired", "rejected"}:
                    return True
                time.sleep(0.25)
        except Exception as exc:
            logger.error("Bot 2 | order cancellation failed id=%s: %s", order_id, exc)
        return False


def ensure_schema() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)


def load_vault_symbols(bot_id: str = BOT_ID) -> set[str]:
    """Read vault identity from the database source of truth, never a constant."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM per_bot_vault_holdings WHERE bot_id=%s AND qty > 0",
                (bot_id,),
            )
            return {canonical_symbol(row[0]) for row in cur.fetchall()}


def load_open_positions(bot_id: str = BOT_ID) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, qty, entry_price, notional_usd, stop_price, stop_order_id
                FROM {STRATEGY_TABLE}
                WHERE bot_id=%s AND status='open'
                ORDER BY opened_at, symbol
                """,
                (bot_id,),
            )
            return [
                {
                    "symbol": canonical_symbol(row[0]),
                    "qty": int(row[1]),
                    "entry_price": float(row[2]),
                    "notional_usd": float(row[3]),
                    "stop_price": float(row[4]),
                    "stop_order_id": row[5],
                }
                for row in cur.fetchall()
            ]


def record_open(
    symbol: str, qty: int, entry_price: float, stop_price: float, stop_order_id: str
) -> None:
    if int(qty) < 1 or float(entry_price) <= 0 or not stop_order_id:
        raise RuntimeError("Bot 2 position recording requires fill and stop confirmation")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {STRATEGY_TABLE}
                    (bot_id, symbol, qty, entry_price, notional_usd, stop_price, stop_order_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    BOT_ID, canonical_symbol(symbol), int(qty), float(entry_price),
                    int(qty) * float(entry_price), float(stop_price), stop_order_id,
                ),
            )


def record_close(symbol: str, reason: str, realised_pnl: float | None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {STRATEGY_TABLE}
                   SET status='closed', closed_at=NOW(), exit_reason=%s, realised_pnl=%s
                 WHERE bot_id=%s AND symbol=%s AND status='open'
                """,
                (reason, realised_pnl, BOT_ID, canonical_symbol(symbol)),
            )


def record_stop_order(symbol: str, stop_order_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {STRATEGY_TABLE}
                   SET stop_order_id=%s
                 WHERE bot_id=%s AND symbol=%s AND status='open'
                """,
                (stop_order_id, BOT_ID, canonical_symbol(symbol)),
            )


def _broker_qty(client: AlpacaMomentumClient, symbol: str) -> int:
    return math.floor(sum(
        float(position["qty"])
        for position in client.positions()
        if canonical_symbol(position["symbol"]) == canonical_symbol(symbol)
    ))


def _owned_stop(
    client: AlpacaMomentumClient, symbol: str, recorded_id: str | None
) -> dict[str, Any] | None:
    canonical = canonical_symbol(symbol)
    if recorded_id:
        for order in client.open_orders():
            if (
                str(order.get("id")) == str(recorded_id)
                and canonical_symbol(order.get("symbol")) == canonical
                and str(order.get("side", "")).lower() == "sell"
                and str(order.get("type", "")).lower() == "stop"
            ):
                return order
    prefix = f"bot2-momentum-sell-{canonical}"
    for order in client.open_orders():
        client_id = str(order.get("client_order_id", "")).lower()
        if (
            canonical_symbol(order.get("symbol")) == canonical
            and str(order.get("side", "")).lower() == "sell"
            and str(order.get("type", "")).lower() == "stop"
            and client_order_id_matches_prefix
            and client_order_id_matches_prefix(client_id, prefix)
        ):
            return order
    return None


def _cancel_owned_stop(
    client: AlpacaMomentumClient, symbol: str, recorded_id: str | None
) -> bool:
    order = _owned_stop(client, symbol, recorded_id)
    return order is None or client.cancel_confirm(str(order["id"]))


def _arm_stop(client: AlpacaMomentumClient, symbol: str, qty: int, entry_price: float) -> dict[str, Any]:
    whole_qty = math.floor(abs(float(qty)))
    if whole_qty < 1:
        raise RuntimeError(f"{symbol}: no whole share available for GTC stop")
    stop_price = round(float(entry_price) * (1.0 - STOP_LOSS_PCT), 2)
    return client.submit(
        symbol, "sell", whole_qty, "stop", stop_price=stop_price,
    )


def _flatten_after_stop_failure(client: AlpacaMomentumClient, symbol: str) -> None:
    for order in client.open_orders():
        if canonical_symbol(order.get("symbol")) == canonical_symbol(symbol):
            if not client.cancel_confirm(str(order["id"])):
                raise RuntimeError(f"{symbol}: could not cancel order before flatten")
    for attempt in range(2):
        qty = _broker_qty(client, symbol)
        if qty < 1:
            return
        sell = client.submit(symbol, "sell", qty, "market")
        fill = client.wait_for_fill(str(sell["id"]))
        if str(fill.get("status", "")).lower() in {"filled", "partially_filled"} and _broker_qty(client, symbol) < 1:
            return
        logger.critical("Bot 2 | flatten retry after stop failure symbol=%s attempt=%s", symbol, attempt + 1)
    raise RuntimeError(f"{symbol}: stop failure could not be recovered by confirmed flatten")


def _place_confirmed_entry(
    client: AlpacaMomentumClient, symbol: str, qty: int, cycle_id: str
) -> bool:
    order = client.submit(symbol, "buy", qty, "market")
    fill = client.wait_for_fill(str(order["id"]))
    status = str(fill.get("status", "")).lower()
    filled_qty = math.floor(float(fill.get("filled_qty") or 0))
    entry_price = float(fill.get("filled_avg_price") or 0)
    if status not in {"filled", "partially_filled"} or filled_qty < 1 or entry_price <= 0:
        logger.warning("Bot 2 | entry not confirmed symbol=%s cycle=%s status=%s", symbol, cycle_id, status)
        return False
    broker_qty = _broker_qty(client, symbol)
    if broker_qty < 1:
        _flatten_after_stop_failure(client, symbol)
        raise RuntimeError(f"{symbol}: filled entry did not settle at broker")
    stop_price = round(entry_price * (1.0 - STOP_LOSS_PCT), 2)
    stop = None
    first_error: Exception | None = None
    for _ in range(2):
        try:
            stop = _arm_stop(client, symbol, broker_qty, entry_price)
            break
        except Exception as exc:
            first_error = exc
            logger.critical("Bot 2 | stop arm failed; retrying symbol=%s error=%s", symbol, exc)
    if stop is None:
        _flatten_after_stop_failure(client, symbol)
        raise RuntimeError(f"{symbol}: stop arm failed twice: {first_error}")
    record_open(symbol, broker_qty, entry_price, stop_price, str(stop["id"]))
    return True


def _reconcile_protective_stops(
    client: AlpacaMomentumClient,
    db_positions: list[dict[str, Any]],
) -> None:
    """Re-arm only this strategy's missing stops before rebalance sells."""
    for position in db_positions:
        symbol = canonical_symbol(position["symbol"])
        if _broker_qty(client, symbol) < 1:
            continue
        if _owned_stop(client, symbol, position.get("stop_order_id")):
            continue
        stop = None
        first_error: Exception | None = None
        for _ in range(2):
            try:
                stop = _arm_stop(
                    client, symbol, int(position["qty"]), float(position["entry_price"])
                )
                break
            except Exception as exc:
                first_error = exc
                logger.critical(
                    "Bot 2 | missing stop arm failed; retrying symbol=%s error=%s",
                    symbol, exc,
                )
        if stop is None:
            _flatten_after_stop_failure(client, symbol)
            record_close(symbol, "stop_arm_failed_flattened", None)
            raise RuntimeError(
                f"{symbol}: restart stop reconciliation failed: {first_error}"
            )
        record_stop_order(symbol, str(stop["id"]))


def _sell_confirmed(
    client: AlpacaMomentumClient, position: dict[str, Any], reason: str
) -> bool:
    symbol = canonical_symbol(position["symbol"])
    if not _cancel_owned_stop(client, symbol, position.get("stop_order_id")):
        logger.critical("Bot 2 | sell blocked because stop cancellation was unconfirmed symbol=%s", symbol)
        return False
    qty = min(int(position["qty"]), _broker_qty(client, symbol))
    if qty < 1:
        return False
    account = client.account()  # fresh account state between every order
    live_positions = client.positions()
    long_market_value = account.get("long_market_value")
    if long_market_value is None:
        long_market_value = sum(float(p.get("market_value", 0) or 0) for p in live_positions)
    if (
        float(account.get("equity", 0) or 0) <= 0
        or float(account.get("cash", 0) or 0) < 0
        or float(long_market_value or 0) > float(account.get("equity", 0) or 0)
    ):
        logger.critical("Bot 2 | sell blocked by inconsistent fresh account state symbol=%s", symbol)
        return False
    order = client.submit(symbol, "sell", qty, "market")
    fill = client.wait_for_fill(str(order["id"]))
    if str(fill.get("status", "")).lower() not in {"filled", "partially_filled"}:
        return False
    if _broker_qty(client, symbol) > 0:
        logger.warning("Bot 2 | sell not flat; leaving ledger open symbol=%s", symbol)
        return False
    fill_price = float(fill.get("filled_avg_price") or 0)
    record_close(symbol, reason, (fill_price - float(position["entry_price"])) * qty if fill_price else None)
    return True


def _build_book(
    client: AlpacaMomentumClient, as_of: date
) -> tuple[list[dict[str, float | str]], dict[str, dict[str, float]], dict[str, list[dict[str, Any]]]]:
    assets = client.assets()
    ordinary_assets, asset_report = filter_ordinary_equity_assets(assets)
    logger.info(
        "Bot 2 | asset filter total=%d tradable_us_equity=%d ordinary_equity=%d "
        "excluded_non_ordinary=%d excluded_unknown=%d",
        asset_report["total_assets"],
        asset_report["tradable_us_equity_assets"],
        asset_report["ordinary_equity_assets"],
        asset_report["excluded_non_ordinary"],
        asset_report["excluded_unknown_metadata"],
    )
    if asset_report["provider_limitation"]:
        logger.error("Bot 2 | asset metadata limitation: %s", asset_report["provider_limitation"])
    symbols = [
        canonical_symbol(asset["symbol"])
        for asset in ordinary_assets
    ]
    bars = client.daily_bars(symbols, as_of)
    screened = screen_universe(ordinary_assets, bars, as_of)
    ranked = rank_momentum(screened, bars, as_of)
    artifact_exclusions = sum(
        1
        for symbol in screened
        if momentum_12_1(bars.get(symbol, []), as_of) is not None
        and momentum_12_1(bars.get(symbol, []), as_of) > MOMENTUM_ARTEFACT_THRESHOLD
    )
    logger.info(
        "Bot 2 | LIVE_FUNNEL total_assets=%d tradable_us_equity=%d "
        "ordinary_equity=%d history_and_price_qualified=%d ranked_top20=%d "
        "artifact_excluded=%d etf_or_non_ordinary=0",
        len(assets),
        asset_report["tradable_us_equity_assets"],
        asset_report["ordinary_equity_assets"],
        len(screened),
        len(ranked),
        artifact_exclusions,
    )
    print(
        f"LIVE_FUNNEL | total_assets={len(assets)} "
        f"| tradable_us_equity={asset_report['tradable_us_equity_assets']} "
        f"| ordinary_equity={asset_report['ordinary_equity_assets']} "
        f"| history_and_price_qualified={len(screened)} "
        f"| ranked_top20={len(ranked)} | artifact_excluded={artifact_exclusions} "
        "| etf_or_non_ordinary=0"
    )
    return ranked, screened, bars


def _park_idle_cash(client: AlpacaMomentumClient, vault_symbols: set[str]) -> None:
    """Park residual cash in SGOV only after stock work is complete."""
    positions = client.positions()
    if any(canonical_symbol(p["symbol"]) == PARK_SYMBOL for p in positions):
        return
    account = client.account()
    price = client.latest_price(PARK_SYMBOL)
    qty = math.floor(float(account["cash"]) / price)
    if qty < 1:
        return
    allowed, projection = fresh_buy_guard(
        account, positions, qty * price,
        excluded_symbols=set(vault_symbols) | {PARK_SYMBOL},
    )
    if allowed:
        client.submit(PARK_SYMBOL, "buy", qty, "market")


def run_bot2_cycle(
    profile: dict[str, Any] | None = None,
    db_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Live-shaped cycle with the permanent pause as the first executable branch."""
    if BOT_PAUSED:
        logger.info("Bot 2 | BOT_PAUSED=True — no client, account read, or order activity")
        return {"status": "paused", "orders": 0}
    profile = profile or {}
    now = now or datetime.now(timezone.utc)
    if not us_equity_session_open(now):
        return {"status": "deferred", "orders": 0, "reason": "US_equity_market_closed"}
    if not universe_gate_is_passed():
        logger.critical(
            "Bot 2 | historical universe parity gate is not PASS — execution blocked"
        )
        return {"status": "blocked", "orders": 0, "reason": "universe_parity_gate"}
    ensure_schema()
    client = AlpacaMomentumClient(
        profile.get("ALPACA_API_KEY") or os.environ.get("ALPACA_BB_API_KEY", ""),
        profile.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        profile.get("ALPACA_BASE_URL", ALPACA_BASE_URL),
    )
    account = client.account()
    vault_symbols = load_vault_symbols()
    broker_positions = client.positions()
    db_positions = load_open_positions()
    _reconcile_protective_stops(client, db_positions)
    strategy_symbols = {row["symbol"] for row in db_positions}
    live_strategy = [
        position for position in broker_positions
        if position["symbol"] in strategy_symbols and position["symbol"] not in vault_symbols
    ]
    initial_entry = not db_positions and not live_strategy
    if not initial_entry and not is_first_trading_day(now):
        _park_idle_cash(client, vault_symbols)
        return {"status": "complete", "orders": 0, "reason": "not_first_trading_day"}
    ranked, screened, bars = _build_book(client, now.astimezone(_eastern()).date())
    desired = {str(item["symbol"]) for item in ranked}
    orders = 0
    for position in db_positions:
        if position["symbol"] not in desired:
            if _sell_confirmed(client, position, "fell_out_of_top_20"):
                orders += 1
    account = client.account()
    broker_positions = client.positions()
    vault_market_value = sum(
        float(p["market_value"])
        for p in broker_positions
        if canonical_symbol(p["symbol"]) in vault_symbols
    )
    plan = allocation_plan(account["equity"], vault_market_value, len(ranked))
    held = {
        canonical_symbol(p["symbol"])
        for p in broker_positions
        if canonical_symbol(p["symbol"]) in desired
    }
    for item in ranked:
        symbol = str(item["symbol"])
        if symbol in held:
            continue
        close = float(_prior_bars(bars[symbol], now.astimezone(_eastern()).date())[-1]["c"])
        qty = math.floor(plan["equal_weight_notional"] / close)
        if qty < 1:
            continue
        # Fresh state is fetched inside the guard; sell work has already run.
        fresh_account = client.account()
        fresh_positions = client.positions()
        allowed, projection = fresh_buy_guard(
            fresh_account, fresh_positions, qty * close,
            max_deployment=MAX_DEPLOYMENT,
            excluded_symbols=set(vault_symbols) | {PARK_SYMBOL},
        )
        if not allowed:
            logger.critical(
                "Bot 2 | BUY BLOCKED symbol=%s projected_cash=%.2f deployment=%.2f",
                symbol, projection["projected_cash"], projection["projected_deployment"],
            )
            continue
        if _place_confirmed_entry(client, symbol, qty, uuid.uuid4().hex):
            orders += 1
    _park_idle_cash(client, vault_symbols)
    return {
        "status": "complete",
        "orders": orders,
        "reason": "initial_entry" if initial_entry else "monthly_rebalance",
        "universe_size": len(screened),
        "top_20": ranked,
    }


def dry_run_cycle() -> dict[str, Any]:
    """Read the current account and signal inputs; never submits an order."""
    profile = {
        "ALPACA_API_KEY": os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL": ALPACA_BASE_URL,
    }
    now = datetime.now(timezone.utc)
    client = AlpacaMomentumClient(
        profile["ALPACA_API_KEY"], profile["ALPACA_SECRET_KEY"], profile["ALPACA_BASE_URL"]
    )
    account = client.account()
    vault_symbols = load_vault_symbols()
    positions = client.positions()
    vault_market_value = sum(
        float(p["market_value"]) for p in positions
        if canonical_symbol(p["symbol"]) in vault_symbols
    )
    ranked, screened, bars = _build_book(client, now.astimezone(_eastern()).date())
    plan = allocation_plan(account["equity"], vault_market_value, len(ranked))
    print(f"DRY_RUN_ACCOUNT | equity=${account['equity']:,.2f} | cash=${account['cash']:,.2f}")
    print(f"DRY_RUN_VAULT | symbols={sorted(vault_symbols)} | market_value=${vault_market_value:,.2f}")
    print(f"DRY_RUN_INVESTABLE_BASE | ${plan['investable_base']:,.2f}")
    print(f"DRY_RUN_UNIVERSE_SIZE | {len(screened)}")
    sectors = _sector_map()
    for index, item in enumerate(ranked, start=1):
        print(
            f"LIVE_TOP20 | rank={index} | symbol={item['symbol']} "
            f"| momentum={float(item['momentum']):+.4%} "
            f"| dollar_volume=${float(item['median_dollar_volume']):,.2f} "
            f"| price=${float(item['price']):,.2f} "
            f"| target_notional=${plan['equal_weight_notional']:,.2f} "
            f"| sector={sectors.get(str(item['symbol']), 'unknown')} "
            f"| asset_class={item.get('asset_class', 'ordinary_equity')}"
        )
    print(
        f"LIVE_SCREEN_SANITY | qualifying={len(screened)} | top20={len(ranked)} "
        f"| zero_etfs=true | above_artifact_threshold=0 "
        f"| max_momentum={max((float(item['momentum']) for item in ranked), default=0.0):+.4%}"
    )
    print(
        "DRY_RUN_TOP_20 | "
        + json.dumps(
            [
                {
                    "symbol": item["symbol"],
                    "momentum": item["momentum"],
                    "asset_class": item.get("asset_class", "ordinary_equity"),
                }
                for item in ranked
            ],
            sort_keys=True,
        )
    )
    print(f"DRY_RUN_EQUAL_WEIGHT_NOTIONAL | ${plan['equal_weight_notional']:,.2f}")
    projected = plan["target_base"]
    desired_symbols = {str(item["symbol"]) for item in ranked}
    projected_cash = account["cash"] - max(0.0, projected - sum(
        float(p["market_value"]) for p in positions
        if canonical_symbol(p["symbol"]) in desired_symbols
    ))
    print(f"DRY_RUN_PROJECTED_DEPLOYMENT | ${projected:,.2f} ({plan['projected_deployment']:.2%})")
    print(f"DRY_RUN_PROJECTED_CASH | ${projected_cash:,.2f}")
    return {
        "equity": account["equity"], "cash": account["cash"],
        "investable_base": plan["investable_base"], "universe_size": len(screened),
        "top_20": ranked, "equal_weight_notional": plan["equal_weight_notional"],
        "projected_deployment": projected, "projected_cash": projected_cash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        dry_run_cycle()
        return 0
    print("Bot 2 single-stock momentum module is permanently paused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())