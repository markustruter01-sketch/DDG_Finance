"""Bot 2 single-stock momentum strategy.

This module is intentionally separate from the legacy SPY/QQQ ETF strategy.
It implements the Experiment 17 live-shaped execution boundary.  Activation
remains controlled by the module, profile, database, and universe gate.

The research signal is deliberately mechanical:
  * Alpaca-tradable US equities only (no index-membership data)
   * 252 prior sessions, top 500 by trailing 60-session median dollar volume
  * trailing 60-session median close > $5
  * 12-1 momentum, with the most recent 21 sessions skipped
  * top 50, equal weight, monthly first-trading-day rebalance
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import math
import os
import statistics
import sys
import time
import uuid
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import requests

_ROOT = Path(__file__).resolve().parents[1]
_TRADING_PLATFORM = str(_ROOT / "trading-platform")
if _TRADING_PLATFORM in sys.path:
    sys.path.remove(_TRADING_PLATFORM)
sys.path.insert(0, _TRADING_PLATFORM)

from db.postgres import get_conn  # noqa: E402
from core.equity_universe import (  # noqa: E402
    eligible_asset_records,
    last_screen_observations,
    screen_universe as shared_screen_universe,
    set_screen_data,
)
from core.cash_park import CASH_PARK_SYMBOLS, is_cash_park  # noqa: E402

try:
    from core.order_ids import submit_with_unique_client_order_id
    from core.order_ids import client_order_id_matches_prefix
except Exception:  # pragma: no cover - only relevant to a broken deployment
    submit_with_unique_client_order_id = None
    client_order_id_matches_prefix = None


logger = logging.getLogger("bot2.momentum")


def _load_bot2_profile() -> dict[str, Any]:
    """Load Bot 2's profile without confusing it with trading-platform/config."""
    config_path = _ROOT / "kraken-bot" / "config.py"
    spec = importlib.util.spec_from_file_location("_bot2_profile_config", config_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Bot 2 profile could not be loaded from {config_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.BOT_PROFILES["bot2_spy_qqq"]
    except (AttributeError, KeyError) as exc:
        raise RuntimeError("Bot 2 profile is missing from kraken-bot/config.py") from exc


BOT2_PROFILE = _load_bot2_profile()
BOT_ID = "spy_qqq_trend"
BOT_PAUSED = True
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
MAX_POSITIONS = int(BOT2_PROFILE["MAX_POSITIONS"])
SLIPPAGE_BPS = 10
MIN_PRIOR_SESSIONS = 252
SKIP_RECENT_SESSIONS = 21
UNIVERSE_SIZE = 500
MIN_MEDIAN_CLOSE = 5.0
MAX_DEPLOYMENT = 1.00
STOP_LOSS_PCT = 0.20
MOMENTUM_ARTEFACT_THRESHOLD = float(
    os.environ.get("BOT2_MOMENTUM_ARTEFACT_THRESHOLD", "3.0")
)
PARK_SYMBOL = next(iter(CASH_PARK_SYMBOLS))
SECTOR_CACHE_FILE = _ROOT / "trading-platform" / ".local" / "bot2_fullmarket_sector_cache.json"
STRATEGY_TABLE = "bot2_momentum_positions"
EQUITY_SESSION_OPEN = dt_time(9, 30)
EQUITY_SESSION_CLOSE = dt_time(16, 0)
SIP_DELAY_MINUTES = 20
VOLATILITY_TARGET_ANNUAL = 0.12
VOLATILITY_LOOKBACK_SESSIONS = 126
VOLATILITY_ANNUALIZATION_SESSIONS = 252
COOLDOWN_SESSIONS = 63
STOP_FILLED_EXIT_REASONS = frozenset({"stop_filled"})
SGOV_QTY_DUST = 1e-6
_NYSE_HOLIDAY_CACHE: dict[int, set[date]] = {}

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
    screened: set[str],
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    as_of: date,
    top_n: int = MAX_POSITIONS,
) -> list[dict[str, float | str]]:
    observations = last_screen_observations()
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
                "asset_class": observations[symbol].get("asset_class", "us_equity"),
                "median_dollar_volume": observations[symbol]["median_dollar_volume_60"],
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
        if (
            is_cash_park(position.get("symbol"))
            or canonical_symbol(position.get("symbol")) in excluded_symbols
        )
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
        # The shared screener needs the full catalogue so its funnel can
        # audit inactive, non-equity, OTC, and excluded-product records.
        return self._request("GET", "/v2/assets") or []

    def daily_bars(
        self, symbols: list[str], as_of: date, batch_size: int = 100
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        start = as_of - timedelta(days=540)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        end_time = now - timedelta(minutes=SIP_DELAY_MINUTES)
        end = end_time.isoformat().replace("+00:00", "Z")
        unfinished_session = (
            end_time.astimezone(_eastern()).date()
            if us_equity_session_open(end_time)
            else None
        )
        for offset in range(0, len(symbols), batch_size):
            batch = symbols[offset:offset + batch_size]
            token = None
            while True:
                params = {
                    "symbols": ",".join(batch),
                    "timeframe": "1Day",
                    "start": start.isoformat(),
                    "end": end,
                    "limit": 10000,
                    "adjustment": "all",
                    "feed": os.environ.get("BOT2_ALPACA_DATA_FEED", "sip"),
                    "sort": "asc",
                }
                if token:
                    params["page_token"] = token
                payload = self._data_request("GET", "/v2/stocks/bars", params=params) or {}
                for symbol, bars in (payload.get("bars") or {}).items():
                    eligible_bars = [
                        bar for bar in (bars or [])
                        if unfinished_session is None
                        or _bar_date(bar) != unfinished_session
                    ]
                    if eligible_bars:
                        result.setdefault(canonical_symbol(symbol), []).extend(
                            eligible_bars
                        )
                token = payload.get("next_page_token")
                if not token:
                    break
        return result

    def latest_price(self, symbol: str) -> float:
        symbol = canonical_symbol(symbol)
        path = f"/v2/stocks/{symbol}/quotes/latest"
        quote_feed = "sip"
        fallback_reason = "sip_request_succeeded"
        try:
            payload = self._data_request(
                "GET", path, params={"feed": quote_feed}
            )
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is None or response.status_code != 403:
                raise
            quote_feed = "iex"
            fallback_reason = "sip_http_403"
            payload = self._data_request(
                "GET", path, params={"feed": quote_feed}
            )
        quote = (payload or {}).get("quote", {})
        bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
        if bid <= 0 and ask <= 0:
            raise RuntimeError(f"missing Alpaca quote for {symbol}")
        print(
            f"BOT2_LATEST_QUOTE | symbol={symbol} feed={quote_feed} "
            f"reason={fallback_reason}"
        )
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

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2/orders/{order_id}") or {}

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


def load_closed_position_history(
    bot_id: str = BOT_ID,
) -> tuple[list[tuple[Any, Any, Any]], bool]:
    """Read closed strategy rows for stop cooldowns; never create the table here."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT symbol, closed_at, exit_reason
                    FROM {STRATEGY_TABLE}
                    WHERE bot_id=%s AND status='closed' AND closed_at IS NOT NULL
                    ORDER BY closed_at DESC
                    """,
                    (bot_id,),
                )
                return list(cur.fetchall()), True
    except Exception as exc:
        if getattr(exc, "pgcode", None) == "42P01":
            logger.warning(
                "Bot 2 | cooldown history table is not initialized; "
                "no closed strategy rows are available"
            )
            return [], False
        raise


def load_bot2_daily_equity_points(as_of: date) -> list[tuple[date, float]]:
    """Read Bot 2's latest per-session equity marks strictly before as_of."""
    cutoff = datetime.combine(as_of, dt_time.min, tzinfo=_eastern())
    start = cutoff - timedelta(days=500)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_date, equity_usd
                    FROM (
                        SELECT
                            (snapshot_ts AT TIME ZONE 'America/New_York')::date AS session_date,
                            equity_usd,
                            ROW_NUMBER() OVER (
                                PARTITION BY (snapshot_ts AT TIME ZONE 'America/New_York')::date
                                ORDER BY snapshot_ts DESC
                            ) AS session_rank
                        FROM fleet_equity_snapshots
                        WHERE bot_id=%s AND snapshot_ts >= %s AND snapshot_ts < %s
                    ) daily
                    WHERE session_rank=1
                    ORDER BY session_date DESC
                    """,
                    (BOT_ID, start, cutoff),
                )
                return [
                    (row[0], float(row[1]))
                    for row in cur.fetchall()
                ]
    except Exception as exc:
        if getattr(exc, "pgcode", None) == "42P01":
            logger.warning("Bot 2 | equity snapshot history is unavailable")
            return []
        raise


def _nyse_holidays(year: int) -> set[date]:
    cached = _NYSE_HOLIDAY_CACHE.get(year)
    if cached is not None:
        return cached
    try:
        import holidays

        result = set(holidays.NYSE(years=year).keys())
    except Exception as exc:
        raise RuntimeError(
            f"Bot 2 requires the NYSE holiday calendar for {year}"
        ) from exc
    _NYSE_HOLIDAY_CACHE[year] = result
    return result


def _is_nyse_session(day: date) -> bool:
    return day.weekday() < 5 and day not in _nyse_holidays(day.year)


def _nyse_sessions_before(as_of: date, count: int) -> list[date]:
    """Return the latest count NYSE sessions before as_of, oldest first."""
    if count <= 0:
        return []
    sessions: list[date] = []
    day = as_of - timedelta(days=1)
    while len(sessions) < count:
        if _is_nyse_session(day):
            sessions.append(day)
        day -= timedelta(days=1)
    sessions.reverse()
    return sessions


def nyse_sessions_after(close_date: date, count: int) -> list[date]:
    """Return the first count NYSE sessions strictly after a close date."""
    if count <= 0:
        return []
    sessions: list[date] = []
    day = close_date + timedelta(days=1)
    while len(sessions) < count:
        if _is_nyse_session(day):
            sessions.append(day)
        day += timedelta(days=1)
    return sessions


def _closed_at_session_date(closed_at: Any) -> date:
    if isinstance(closed_at, datetime):
        value = closed_at
    else:
        value = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_eastern()).date()


def _is_stop_filled_exit_reason(exit_reason: Any) -> bool:
    normalized = str(exit_reason or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in STOP_FILLED_EXIT_REASONS


def build_stop_cooldowns(
    closed_rows: Sequence[tuple[Any, Any, Any]],
    as_of: date,
) -> dict[str, dict[str, Any]]:
    """Keep only stop-filled exits through session 63; session 64 is eligible."""
    cooldowns: dict[str, dict[str, Any]] = {}
    release_session = COOLDOWN_SESSIONS + 1
    for symbol, closed_at, exit_reason in closed_rows:
        normalized_symbol = canonical_symbol(symbol)
        if (
            not normalized_symbol
            or closed_at is None
            or not _is_stop_filled_exit_reason(exit_reason)
        ):
            continue
        close_date = _closed_at_session_date(closed_at)
        release_date = nyse_sessions_after(close_date, release_session)[-1]
        if as_of >= release_date:
            continue
        current = cooldowns.get(normalized_symbol)
        if current is None or release_date > current["release_date"]:
            cooldowns[normalized_symbol] = {
                "closed_at": closed_at,
                "exit_reason": str(exit_reason),
                "release_date": release_date,
            }
    return cooldowns


def daily_returns_from_equity_points(
    points: Sequence[tuple[date, float]],
    as_of: date,
) -> list[float]:
    """Return only consecutive NYSE-session returns within the 126-session window."""
    sessions = _nyse_sessions_before(as_of, VOLATILITY_LOOKBACK_SESSIONS + 1)
    expected = set(sessions)
    equity_by_session: dict[date, float] = {}
    for session_date, equity in points:
        value = float(equity)
        if session_date in expected and math.isfinite(value) and value > 0:
            equity_by_session[session_date] = value
    returns = []
    for previous, current in zip(sessions, sessions[1:]):
        if previous in equity_by_session and current in equity_by_session:
            returns.append(equity_by_session[current] / equity_by_session[previous] - 1.0)
    return returns


def calculate_volatility_multiplier(daily_returns: Sequence[float]) -> dict[str, Any]:
    """Apply run-106's annualized-volatility sizing rule to 126 daily returns."""
    values = [float(value) for value in daily_returns]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Bot 2 daily returns must be finite")
    if len(values) < VOLATILITY_LOOKBACK_SESSIONS:
        return {
            "multiplier": 1.0,
            "annualized_volatility": None,
            "return_count": len(values),
            "reason": "insufficient_returns",
        }
    annualized_volatility = (
        statistics.stdev(values[-VOLATILITY_LOOKBACK_SESSIONS:])
        * math.sqrt(VOLATILITY_ANNUALIZATION_SESSIONS)
    )
    if not math.isfinite(annualized_volatility) or annualized_volatility <= 0:
        return {
            "multiplier": 1.0,
            "annualized_volatility": annualized_volatility,
            "return_count": VOLATILITY_LOOKBACK_SESSIONS,
            "reason": "zero_volatility",
        }
    return {
        "multiplier": min(1.0, VOLATILITY_TARGET_ANNUAL / annualized_volatility),
        "annualized_volatility": annualized_volatility,
        "return_count": VOLATILITY_LOOKBACK_SESSIONS,
        "reason": "calculated",
    }


def load_bot2_volatility(as_of: date) -> dict[str, Any]:
    points = load_bot2_daily_equity_points(as_of)
    return calculate_volatility_multiplier(
        daily_returns_from_equity_points(points, as_of)
    )


def build_target_allocation_plan(
    equity: float,
    vault_market_value: float,
    ranked: Sequence[dict[str, Any]],
    multiplier: float,
    benched_symbols: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Keep original rank slots fixed; benched/unused allocation remains in SGOV."""
    if not math.isfinite(float(multiplier)) or not 0.0 <= float(multiplier) <= 1.0:
        raise ValueError("Bot 2 volatility multiplier must be between zero and one")
    base = allocation_plan(equity, vault_market_value, len(ranked))
    slot_notional = base["equal_weight_notional"]
    scaled_notional = slot_notional * float(multiplier)
    targets: dict[str, float] = {}
    for item in ranked:
        symbol = canonical_symbol(item["symbol"])
        targets[symbol] = 0.0 if symbol in benched_symbols else scaled_notional
    stock_target = sum(targets.values())
    sgov_target = max(0.0, base["target_base"] - stock_target)
    return {
        **base,
        "slot_notional": slot_notional,
        "scaled_position_notional": scaled_notional,
        "target_allocations": targets,
        "stock_target": stock_target,
        "sgov_target": sgov_target,
    }


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


def _prepare_symbol_for_sell(
    client: AlpacaMomentumClient,
    symbol: str,
    sell_qty: int,
    recorded_stop_id: str | None = None,
) -> bool:
    """Cancel and confirm symbol orders, then verify shares are free to sell."""
    symbol = canonical_symbol(symbol)
    if sell_qty < 1:
        return False

    final_statuses = {
        "canceled",
        "cancelled",
        "expired",
        "filled",
        "rejected",
        "done_for_day",
    }
    confirmed_order_ids: set[str] = set()

    def confirm_order_final(order_id: str) -> bool:
        try:
            order = client.get_order(order_id)
        except Exception as exc:
            logger.critical(
                "Bot 2 | sell blocked: order GET failed symbol=%s id=%s error=%s",
                symbol,
                order_id,
                exc,
            )
            return False
        if (
            not isinstance(order, dict)
            or str(order.get("id") or "") != order_id
            or canonical_symbol(order.get("symbol", "")) != symbol
        ):
            logger.critical(
                "Bot 2 | sell blocked: order GET did not confirm symbol/id "
                "symbol=%s id=%s",
                symbol,
                order_id,
            )
            return False

        status = str(order.get("status", "")).lower()
        if status not in final_statuses:
            if not client.cancel_confirm(order_id):
                logger.critical(
                    "Bot 2 | sell blocked: order cancellation unconfirmed "
                    "symbol=%s id=%s status=%s",
                    symbol,
                    order_id,
                    status,
                )
                return False
            try:
                order = client.get_order(order_id)
            except Exception as exc:
                logger.critical(
                    "Bot 2 | sell blocked: post-cancel GET failed "
                    "symbol=%s id=%s error=%s",
                    symbol,
                    order_id,
                    exc,
                )
                return False
            if (
                not isinstance(order, dict)
                or str(order.get("id") or "") != order_id
                or canonical_symbol(order.get("symbol", "")) != symbol
            ):
                logger.critical(
                    "Bot 2 | sell blocked: post-cancel GET did not confirm "
                    "symbol/id symbol=%s id=%s",
                    symbol,
                    order_id,
                )
                return False
            status = str(order.get("status", "")).lower()

        if status not in final_statuses:
            logger.critical(
                "Bot 2 | sell blocked: order is not final symbol=%s id=%s status=%s",
                symbol,
                order_id,
                status or "missing",
            )
            return False
        confirmed_order_ids.add(order_id)
        return True

    if recorded_stop_id:
        if not confirm_order_final(str(recorded_stop_id)):
            return False

    def confirm_listed_symbol_orders() -> bool:
        try:
            open_orders = client.open_orders()
        except Exception as exc:
            logger.critical(
                "Bot 2 | sell blocked: open-order listing failed symbol=%s error=%s",
                symbol,
                exc,
            )
            return False
        if not isinstance(open_orders, list):
            logger.critical(
                "Bot 2 | sell blocked: invalid open-order listing symbol=%s",
                symbol,
            )
            return False
        for order in open_orders:
            if not isinstance(order, dict) or not order.get("symbol"):
                logger.critical(
                    "Bot 2 | sell blocked: open order lacks a usable symbol symbol=%s",
                    symbol,
                )
                return False
            if canonical_symbol(order["symbol"]) != symbol:
                continue
            order_id = str(order.get("id") or "")
            if not order_id:
                logger.critical(
                    "Bot 2 | sell blocked: matching open order lacks an id symbol=%s",
                    symbol,
                )
                return False
            if order_id in confirmed_order_ids:
                continue
            if not confirm_order_final(order_id):
                return False
        return True

    # Re-read after cancellations. A stale collection response is harmless
    # only for IDs whose order-specific GET already proved a final status.
    if not confirm_listed_symbol_orders():
        return False
    if not confirm_listed_symbol_orders():
        return False

    try:
        matching_positions = [
            position
            for position in client.positions()
            if canonical_symbol(position.get("symbol", "")) == symbol
        ]
    except Exception as exc:
        logger.critical(
            "Bot 2 | sell blocked: position read failed symbol=%s error=%s",
            symbol,
            exc,
        )
        return False
    if len(matching_positions) != 1:
        logger.critical(
            "Bot 2 | sell blocked: expected one broker position symbol=%s count=%d",
            symbol,
            len(matching_positions),
        )
        return False

    broker_position = matching_positions[0]
    if "qty_available" not in broker_position:
        logger.critical(
            "Bot 2 | sell blocked: Alpaca position lacks qty_available "
            "symbol=%s available_fields=%s",
            symbol,
            sorted(broker_position),
        )
        return False
    try:
        available_qty = float(broker_position["qty_available"])
    except (TypeError, ValueError):
        logger.critical(
            "Bot 2 | sell blocked: invalid qty_available symbol=%s value=%r",
            symbol,
            broker_position["qty_available"],
        )
        return False
    if (
        not math.isfinite(available_qty)
        or available_qty < 0
        or available_qty + 1e-9 < sell_qty
    ):
        logger.critical(
            "Bot 2 | sell blocked: qty_available=%s is below sell_qty=%s symbol=%s",
            available_qty,
            sell_qty,
            symbol,
        )
        return False
    logger.info(
        "Bot 2 | sell precheck passed symbol=%s sell_qty=%s "
        "qty_available=%s confirmed_orders=%d",
        symbol,
        sell_qty,
        available_qty,
        len(confirmed_order_ids),
    )
    return True


def _arm_stop(client: AlpacaMomentumClient, symbol: str, qty: int, entry_price: float) -> dict[str, Any]:
    whole_qty = math.floor(abs(float(qty)))
    if whole_qty < 1:
        raise RuntimeError(f"{symbol}: no whole share available for GTC stop")
    stop_price = round(float(entry_price) * (1.0 - STOP_LOSS_PCT), 2)
    return client.submit(
        symbol, "sell", whole_qty, "stop", stop_price=stop_price,
    )


def _flatten_after_stop_failure(
    client: AlpacaMomentumClient,
    symbol: str,
    recorded_stop_id: str | None = None,
) -> None:
    for attempt in range(2):
        qty = _broker_qty(client, symbol)
        if qty < 1:
            return
        if not _prepare_symbol_for_sell(client, symbol, qty, recorded_stop_id):
            raise RuntimeError(
                f"{symbol}: sell precheck failed before emergency flatten"
            )
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


def _filled_stop_exit(
    order: dict[str, Any], position: dict[str, Any]
) -> tuple[int, float | None] | None:
    if (
        str(order.get("status", "")).lower() != "filled"
        or str(order.get("side", "")).lower() != "sell"
        or str(order.get("type", "")).lower() not in {"stop", "stop_limit"}
    ):
        return None
    try:
        quantity = min(
            int(position["qty"]),
            math.floor(float(order.get("filled_qty") or position["qty"])),
        )
        fill_price = float(order.get("filled_avg_price") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if quantity < 1:
        return None
    realised_pnl = (
        (fill_price - float(position["entry_price"])) * quantity
        if fill_price > 0
        else None
    )
    return quantity, realised_pnl


def _reconcile_protective_stops(
    client: AlpacaMomentumClient,
    db_positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Re-arm only this strategy's missing stops before rebalance sells."""
    stop_closed_symbols: set[str] = set()
    for position in db_positions:
        symbol = canonical_symbol(position["symbol"])
        if _broker_qty(client, symbol) < 1:
            stop_order_id = position.get("stop_order_id")
            if stop_order_id:
                try:
                    stop_order = client.get_order(str(stop_order_id))
                except Exception as exc:
                    logger.warning(
                        "Bot 2 | could not verify stop order for flat position "
                        "symbol=%s order_id=%s error=%s",
                        symbol, stop_order_id, exc,
                    )
                    continue
                filled_exit = _filled_stop_exit(stop_order, position)
                if filled_exit is not None:
                    _, realised_pnl = filled_exit
                    record_close(symbol, "stop_filled", realised_pnl)
                    stop_closed_symbols.add(symbol)
                    logger.info(
                        "Bot 2 | stop fill recorded symbol=%s exit_reason=stop_filled "
                        "realised_pnl=%s",
                        symbol, realised_pnl,
                    )
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
            _flatten_after_stop_failure(
                client, symbol, position.get("stop_order_id")
            )
            record_close(symbol, "stop_arm_failed_flattened", None)
            raise RuntimeError(
                f"{symbol}: restart stop reconciliation failed: {first_error}"
            )
        record_stop_order(symbol, str(stop["id"]))
    return [
        position for position in db_positions
        if canonical_symbol(position["symbol"]) not in stop_closed_symbols
    ]


def _sell_confirmed(
    client: AlpacaMomentumClient, position: dict[str, Any], reason: str
) -> bool:
    symbol = canonical_symbol(position["symbol"])
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
    if not _prepare_symbol_for_sell(
        client, symbol, qty, position.get("stop_order_id")
    ):
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
) -> tuple[list[dict[str, float | str]], set[str], dict[str, list[dict[str, Any]]]]:
    assets = client.assets()
    candidate_assets, asset_report = eligible_asset_records(assets)
    logger.info(
        "Bot 2 | shared asset filter total=%d asset_eligible=%d "
        "excluded_name=%d excluded_symbol_structure=%d",
        asset_report["total_assets"],
        asset_report["asset_eligible_records"],
        asset_report["excluded_name"],
        asset_report["excluded_symbol_structure"],
    )
    symbols = [
        canonical_symbol(asset["symbol"])
        for asset in candidate_assets
    ]
    bars = client.daily_bars(symbols, as_of)
    set_screen_data(assets, bars)
    screened, funnel = shared_screen_universe(
        as_of,
        UNIVERSE_SIZE,
        MIN_PRIOR_SESSIONS,
        MIN_MEDIAN_CLOSE,
    )
    ranked = rank_momentum(screened, bars, as_of)
    logger.info(
        "Bot 2 | LIVE_FUNNEL %s ranked_top50=%d",
        " ".join(f"{key}={value}" for key, value in sorted(funnel.items())),
        len(ranked),
    )
    print(
        "LIVE_FUNNEL | "
        + " | ".join(f"{key}={value}" for key, value in sorted(funnel.items()))
        + f" | ranked_top50={len(ranked)}"
    )
    return ranked, screened, bars


def _park_idle_cash(
    client: AlpacaMomentumClient, vault_symbols: set[str]
) -> dict[str, float]:
    """Park residual cash in SGOV only after stock work is complete."""
    positions = client.positions()
    account = client.account()
    price = client.latest_price(PARK_SYMBOL)
    if not math.isfinite(price) or price <= 0:
        raise RuntimeError("Bot 2 cannot park idle cash without a valid SGOV price")
    held_qty = sum(
        max(0.0, float(position.get("qty", 0) or 0))
        for position in positions
        if is_cash_park(position.get("symbol"))
    )
    if held_qty < SGOV_QTY_DUST:
        held_qty = 0.0
    idle_cash = max(0.0, float(account["cash"]))
    target_qty = math.floor((held_qty * price + idle_cash) / price)
    qty = min(
        max(0, target_qty - math.floor(held_qty)),
        math.floor(idle_cash / price),
    )
    if qty < 1:
        return {
            "held_qty": held_qty,
            "target_qty": float(target_qty),
            "buy_qty": 0.0,
            "idle_cash": idle_cash,
        }
    allowed, projection = fresh_buy_guard(
        account, positions, qty * price,
        excluded_symbols=set(vault_symbols) | {PARK_SYMBOL},
    )
    if allowed:
        client.submit(PARK_SYMBOL, "buy", qty, "market")
        return {
            "held_qty": held_qty,
            "target_qty": float(target_qty),
            "buy_qty": float(qty),
            "idle_cash": idle_cash,
        }
    logger.warning(
        "Bot 2 | SGOV parking blocked qty=%s projected_cash=%.2f deployment=%.2f",
        qty, projection["projected_cash"], projection["projected_deployment"],
    )
    return {
        "held_qty": held_qty,
        "target_qty": float(target_qty),
        "buy_qty": 0.0,
        "idle_cash": idle_cash,
    }


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
    db_positions = _reconcile_protective_stops(client, db_positions)
    strategy_symbols = {row["symbol"] for row in db_positions}
    live_strategy = [
        position for position in broker_positions
        if position["symbol"] in strategy_symbols and position["symbol"] not in vault_symbols
    ]
    initial_entry = not db_positions and not live_strategy
    if not initial_entry and not is_first_trading_day(now):
        _park_idle_cash(client, vault_symbols)
        return {"status": "complete", "orders": 0, "reason": "not_first_trading_day"}
    as_of = now.astimezone(_eastern()).date()
    ranked, screened, bars = _build_book(client, as_of)
    closed_rows, history_available = load_closed_position_history()
    cooldowns = build_stop_cooldowns(closed_rows, as_of)
    eligible_ranked = [
        item for item in ranked
        if canonical_symbol(item["symbol"]) not in cooldowns
    ]
    volatility = load_bot2_volatility(as_of)
    desired = {str(item["symbol"]) for item in eligible_ranked}
    orders = 0
    for position in db_positions:
        if position["symbol"] not in desired:
            if _sell_confirmed(client, position, "fell_out_of_top_50"):
                orders += 1
    account = client.account()
    broker_positions = client.positions()
    vault_market_value = sum(
        float(p["market_value"])
        for p in broker_positions
        if canonical_symbol(p["symbol"]) in vault_symbols
    )
    plan = build_target_allocation_plan(
        account["equity"],
        vault_market_value,
        ranked,
        volatility["multiplier"],
        set(cooldowns),
    )
    logger.info(
        "Bot 2 | VOL_SCALE as_of=%s multiplier=%.6f annualized_volatility=%s "
        "returns=%s/%s reason=%s stop_exit_reasons=%s",
        as_of,
        volatility["multiplier"],
        (
            f"{volatility['annualized_volatility']:.6f}"
            if volatility["annualized_volatility"] is not None
            else "unavailable"
        ),
        volatility["return_count"],
        VOLATILITY_LOOKBACK_SESSIONS,
        volatility["reason"],
        sorted(STOP_FILLED_EXIT_REASONS),
    )
    for symbol, details in sorted(cooldowns.items()):
        logger.info(
            "Bot 2 | COOLDOWN symbol=%s exit_reason=%s release_date=%s",
            symbol, details["exit_reason"], details["release_date"],
        )
    held = {
        canonical_symbol(p["symbol"])
        for p in broker_positions
        if canonical_symbol(p["symbol"]) in desired
    }
    for item in eligible_ranked:
        symbol = str(item["symbol"])
        if symbol in held:
            continue
        close = float(_prior_bars(bars[symbol], now.astimezone(_eastern()).date())[-1]["c"])
        target_notional = plan["target_allocations"][symbol]
        qty = math.floor(target_notional / close)
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
        "top_50": ranked,
        "eligible": eligible_ranked,
        "benched": cooldowns,
        "cooldown_history_available": history_available,
        "volatility": volatility,
        "allocation_plan": plan,
    }


def dry_run_cycle() -> dict[str, Any]:
    """Read the current account and signal inputs; never submits an order."""
    profile = {
        "ALPACA_API_KEY": os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL": ALPACA_BASE_URL,
    }
    now = datetime.now(timezone.utc)
    as_of = now.astimezone(_eastern()).date()
    data_feed = os.environ.get("BOT2_ALPACA_DATA_FEED", "sip").strip().lower()
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
    ranked, screened, bars = _build_book(client, as_of)
    closed_rows, history_available = load_closed_position_history()
    cooldowns = build_stop_cooldowns(closed_rows, as_of)
    eligible_ranked = [
        item for item in ranked
        if canonical_symbol(item["symbol"]) not in cooldowns
    ]
    volatility = load_bot2_volatility(as_of)
    plan = build_target_allocation_plan(
        account["equity"],
        vault_market_value,
        ranked,
        volatility["multiplier"],
        set(cooldowns),
    )
    current_sgov_value = sum(
        max(0.0, float(position.get("market_value", 0) or 0))
        for position in positions
        if is_cash_park(position.get("symbol"))
    )
    planned_stock_notional = 0.0
    for item in ranked:
        symbol = canonical_symbol(item["symbol"])
        target_notional = plan["target_allocations"][symbol]
        close = float(item["price"])
        qty = math.floor(target_notional / close) if target_notional > 0 and close > 0 else 0
        planned_stock_notional += qty * close
    sgov_target = max(0.0, plan["target_base"] - planned_stock_notional)
    total_planned = vault_market_value + planned_stock_notional + sgov_target
    observed_exit_reasons = sorted({
        str(row[2]) for row in closed_rows if row[2] is not None
    })
    print(
        f"DRY_RUN_ACCOUNT | equity=${account['equity']:,.2f} "
        f"| cash=${account['cash']:,.2f} | as_of={as_of.isoformat()}"
    )
    print(f"DRY_RUN_DATA_FEED | {data_feed}")
    print(f"DRY_RUN_PAUSE | module={BOT_PAUSED} | orders_submitted=0")
    print(f"DRY_RUN_VAULT | symbols={sorted(vault_symbols)} | market_value=${vault_market_value:,.2f}")
    print(f"DRY_RUN_INVESTABLE_BASE | ${plan['investable_base']:,.2f}")
    print(f"DRY_RUN_UNIVERSE_SIZE | {len(screened)}")
    print(
        "DRY_RUN_VOLATILITY | "
        f"multiplier={volatility['multiplier']:.6f} "
        f"| annualized_volatility={volatility['annualized_volatility']} "
        f"| returns={volatility['return_count']}/{VOLATILITY_LOOKBACK_SESSIONS} "
        f"| reason={volatility['reason']}"
    )
    print(
        "DRY_RUN_STOP_EXIT_REASONS | "
        f"recognized={sorted(STOP_FILLED_EXIT_REASONS)} "
        f"| observed={observed_exit_reasons} "
        f"| history_table_available={history_available}"
    )
    if cooldowns:
        for symbol, details in sorted(cooldowns.items()):
            print(
                f"DRY_RUN_BENCHED | symbol={symbol} "
                f"| exit_reason={details['exit_reason']} "
                f"| closed_at={details['closed_at']} "
                f"| release_date={details['release_date'].isoformat()}"
            )
    else:
        print("DRY_RUN_BENCHED | none")
    sectors = _sector_map()
    for index, item in enumerate(ranked, start=1):
        symbol = canonical_symbol(item["symbol"])
        target_notional = plan["target_allocations"][symbol]
        close = float(item["price"])
        qty = math.floor(target_notional / close) if target_notional > 0 and close > 0 else 0
        planned_notional = qty * close
        print(
            f"LIVE_TOP50 | rank={index} | symbol={item['symbol']} "
            f"| momentum={float(item['momentum']):+.4%} "
            f"| dollar_volume=${float(item['median_dollar_volume']):,.2f} "
            f"| price=${close:,.2f} "
            f"| slot_notional=${plan['slot_notional']:,.2f} "
            f"| target_notional=${target_notional:,.2f} "
            f"| shares={qty} | planned_notional=${planned_notional:,.2f} "
            f"| release_date={cooldowns[symbol]['release_date'] if symbol in cooldowns else 'eligible'} "
            f"| sector={sectors.get(str(item['symbol']), 'unknown')} "
                f"| asset_class={item.get('asset_class', 'us_equity')}"
        )
    print(
        f"LIVE_SCREEN_SANITY | qualifying={len(screened)} | top50={len(ranked)} "
        f"| zero_etfs=true | above_artifact_threshold=0 "
        f"| max_momentum={max((float(item['momentum']) for item in ranked), default=0.0):+.4%}"
    )
    print(
        "DRY_RUN_TOP_50 | "
        + json.dumps(
            [
                {
                    "symbol": item["symbol"],
                    "momentum": item["momentum"],
                    "asset_class": item.get("asset_class", "us_equity"),
                    "target_notional": plan["target_allocations"][
                        canonical_symbol(item["symbol"])
                    ],
                }
                for item in ranked
            ],
            sort_keys=True,
        )
    )
    print(f"DRY_RUN_SLOT_NOTIONAL | ${plan['slot_notional']:,.2f}")
    print(f"DRY_RUN_SCALED_POSITION_NOTIONAL | ${plan['scaled_position_notional']:,.2f}")
    print(f"DRY_RUN_STOCK_TARGET | ${planned_stock_notional:,.2f}")
    print(
        f"DRY_RUN_SGOV | target=${sgov_target:,.2f} "
        f"| held=${current_sgov_value:,.2f} "
        f"| additional_target=${max(0.0, sgov_target - current_sgov_value):,.2f}"
    )
    print(
        f"DRY_RUN_TOTAL | planned=${total_planned:,.2f} "
        f"| account_equity=${account['equity']:,.2f} "
        f"| projected_deployment={plan['projected_deployment']:.2%}"
    )
    print("DRY_RUN_ORDERS_SUBMITTED | 0")
    return {
        "equity": account["equity"], "cash": account["cash"],
        "investable_base": plan["investable_base"], "universe_size": len(screened),
        "top_50": ranked,
        "eligible": eligible_ranked,
        "benched": cooldowns,
        "volatility": volatility,
        "stock_target": planned_stock_notional,
        "sgov_target": sgov_target,
        "total_planned": total_planned,
        "orders_submitted": 0,
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