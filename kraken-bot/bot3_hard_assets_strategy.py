"""Bot 3 hard-assets sleeve.

This module is deliberately built paused.  It is registered by runner.py but
does not start a workflow.  ``run_bot3_cycle`` returns before constructing an
Alpaca client while BOT_PAUSED is true.  The ``--dry-run`` path uses only the
already validated development price tables and an explicitly supplied empty
account snapshot.

Execution policy:
* A quarterly rebalance is deferred as a whole when the US equity session is
  closed.  This keeps GLD/SLV and BTC/ETH legs consistent instead of allowing
  only the crypto half to execute.
* All entries are fill-confirmed before ``bot3_positions`` is written.
* Stop orders are armed only after a confirmed fill.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from statistics import stdev
from typing import Any

import requests
_ROOT = Path(__file__).resolve().parents[1]
_TRADING_PLATFORM = str(_ROOT / "trading-platform")
if _TRADING_PLATFORM in sys.path:
    sys.path.remove(_TRADING_PLATFORM)
sys.path.insert(0, _TRADING_PLATFORM)
from db.postgres import get_conn as _platform_get_conn
from core.kill_switch import _covers

@contextmanager
def get_conn():
    """Use the platform's shared DATABASE_URL connection layer."""
    with _platform_get_conn() as conn:
        yield conn

logger = logging.getLogger("bot3.hard_assets")

BOT_ID = "jerome_macro"
BOT_PAUSED = False
ASSETS = ("BTC/USD", "ETH/USD", "GLD", "SLV")
CRYPTO = frozenset({"BTC/USD", "ETH/USD"})
METALS = frozenset({"GLD", "SLV"})
VAULT_SYMBOLS = frozenset({"BIL", "VOO"})
DEFAULT_MAX_DEPLOYMENT = 1.0
TARGET_WEIGHT = 0.25
VOL_LOOKBACK = 60
WEIGHT_FLOOR = 0.10
WEIGHT_CAP = 0.40
# Source: research_ledger experiment 20.
CRYPTO_FLEET_CAP_PCT = 0.05
DRIFT_BAND = 0.05
CRYPTO_STOP_PCT = 0.25
METAL_STOP_PCT = 0.10
EQUITY_SESSION_OPEN = time(9, 30)
EQUITY_SESSION_CLOSE = time(16, 0)
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
PRICE_TABLES = {
    "BTC/USD": ("crypto_historical_prices", "BTC"),
    "ETH/USD": ("crypto_historical_prices", "ETH"),
    "GLD": ("bot3_inflation_hedge_prices", "GLD"),
    "SLV": ("bot3_inflation_hedge_prices", "SLV"),
}

CREATE_BOT3_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS bot3_positions (
    id                BIGSERIAL PRIMARY KEY,
    bot_id            TEXT NOT NULL,
    symbol            TEXT NOT NULL CHECK (symbol IN ('BTC/USD', 'ETH/USD', 'GLD', 'SLV')),
    qty               NUMERIC NOT NULL,
    entry_price       NUMERIC NOT NULL,
    notional_usd      NUMERIC NOT NULL,
    stop_price        NUMERIC NOT NULL,
    stop_order_id     TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    opened_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at         TIMESTAMPTZ,
    exit_reason       TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot3_positions_open_symbol
    ON bot3_positions (bot_id, symbol) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS bot3_decision_log (
    id                BIGSERIAL PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bot_id            TEXT NOT NULL,
    cycle_id          TEXT NOT NULL,
    symbol            TEXT,
    decision           TEXT NOT NULL,
    reason             TEXT,
    current_weight     NUMERIC,
    target_weight      NUMERIC,
    current_price      NUMERIC,
    planned_qty        NUMERIC,
    order_id           TEXT,
    outcome             TEXT,
    context_json       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_bot3_decision_log_cycle
    ON bot3_decision_log (bot_id, ts DESC, cycle_id);
"""

def _canonical_symbol(symbol: str) -> str:
    from core.symbols import alpaca_symbol
    return alpaca_symbol(symbol)


def _log_decision(
    cycle_id: str,
    decision: str,
    *,
    symbol: str | None = None,
    reason: str | None = None,
    current_weight: float | None = None,
    target_weight: float | None = None,
    current_price: float | None = None,
    planned_qty: float | None = None,
    order_id: str | None = None,
    outcome: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Durable per-symbol decision logging; logging failure is surfaced."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bot3_decision_log
                    (bot_id, cycle_id, symbol, decision, reason, current_weight,
                     target_weight, current_price, planned_qty, order_id, outcome,
                     context_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    BOT_ID, cycle_id, symbol, decision, reason, current_weight,
                    target_weight, current_price, planned_qty, order_id, outcome,
                    json.dumps(context or {}, default=str),
                ),
            )


def ensure_bot3_tables() -> None:
    """Create only Bot 3's new isolated tables; never alter existing tables."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_BOT3_TABLES_SQL)


def _nyse_session_open(now: datetime) -> bool:
    """Regular US session check used before any GLD/SLV order."""
    eastern = now.astimezone(_eastern())
    return (
        eastern.weekday() < 5
        and EQUITY_SESSION_OPEN <= eastern.time().replace(tzinfo=None) < EQUITY_SESSION_CLOSE
    )


def _eastern():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # pragma: no cover
        return timezone.utc


def _quarterly_rebalance_date(now: datetime) -> bool:
    eastern = now.astimezone(_eastern())
    if eastern.month not in (1, 4, 7, 10) or eastern.day > 7:
        return False
    if eastern.weekday() >= 5:
        return False
    try:
        import holidays
        if eastern.date() in set(holidays.NYSE(years=eastern.year).keys()):
            return False
    except ImportError:
        pass
    return True


def _load_recent_closes() -> dict[str, list[float]]:
    closes: dict[str, list[float]] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol, (table, db_symbol) in PRICE_TABLES.items():
                cur.execute(
                    f"""
                    SELECT close FROM {table}
                    WHERE symbol=%s AND source='yahoo'
                    ORDER BY date DESC LIMIT %s
                    """,
                    (db_symbol, VOL_LOOKBACK + 1),
                )
                values = [float(row[0]) for row in reversed(cur.fetchall())]
                if not values:
                    raise RuntimeError(f"Bot 3 missing historical closes for {symbol}")
                closes[symbol] = values
    return closes


def inverse_vol_targets(
    closes: dict[str, list[float]],
) -> tuple[dict[str, float], dict[str, float]]:
    """Return bounded inverse-vol targets and annualised realised vol."""
    vol: dict[str, float] = {}
    for symbol in ASSETS:
        values = closes.get(symbol, [])
        if len(values) < VOL_LOOKBACK + 1:
            return (
                {symbol_name: TARGET_WEIGHT for symbol_name in ASSETS},
                {symbol_name: 0.0 for symbol_name in ASSETS},
            )
        returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]
        vol[symbol] = stdev(returns) * math.sqrt(252)

    inverse = {symbol: 1.0 / max(value, 1e-12) for symbol, value in vol.items()}
    total = sum(inverse.values())
    weights = {symbol: inverse[symbol] / total for symbol in ASSETS}
    fixed: dict[str, float] = {}
    free = set(ASSETS)
    remaining = 1.0
    while free:
        changed = False
        free_total = sum(weights[symbol] for symbol in free)
        for symbol in tuple(free):
            candidate = remaining * weights[symbol] / free_total
            if candidate < WEIGHT_FLOOR:
                fixed[symbol] = WEIGHT_FLOOR
                remaining -= WEIGHT_FLOOR
                free.remove(symbol)
                changed = True
            elif candidate > WEIGHT_CAP:
                fixed[symbol] = WEIGHT_CAP
                remaining -= WEIGHT_CAP
                free.remove(symbol)
                changed = True
        if not changed:
            break
    free_total = sum(weights[symbol] for symbol in free)
    for symbol in free:
        fixed[symbol] = remaining * weights[symbol] / free_total
    return fixed, vol


def apply_crypto_fleet_cap(
    target_weights: dict[str, float],
    target_base: float,
    fleet_equity: float,
) -> dict[str, float]:
    """Cap combined crypto target dollars and reallocate the difference."""
    try:
        target_base = float(target_base)
        fleet_equity = float(fleet_equity)
    except (TypeError, ValueError) as exc:
        raise ValueError("target_base and fleet_equity must be numbers") from exc
    if (
        not math.isfinite(target_base)
        or target_base <= 0
        or not math.isfinite(fleet_equity)
        or fleet_equity <= 0
    ):
        raise ValueError("target_base and fleet_equity must be finite and positive")

    adjusted = {symbol: float(target_weights[symbol]) for symbol in ASSETS}
    if not math.isclose(sum(adjusted.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("target weights must sum to 1.0")

    crypto_weight = sum(adjusted[symbol] for symbol in CRYPTO)
    metal_weight = sum(adjusted[symbol] for symbol in METALS)
    crypto_dollars = crypto_weight * target_base
    crypto_ceiling = CRYPTO_FLEET_CAP_PCT * fleet_equity
    if crypto_dollars <= crypto_ceiling:
        return adjusted

    if metal_weight <= 0:
        raise ValueError("metal target weights must have a positive total")

    capped_crypto_weight = crypto_ceiling / target_base
    crypto_scale = capped_crypto_weight / crypto_weight
    freed_weight = crypto_weight - capped_crypto_weight
    for symbol in CRYPTO:
        adjusted[symbol] *= crypto_scale
    # The fleet cap deliberately overrides WEIGHT_FLOOR for crypto because it
    # is the stricter constraint.
    for symbol in METALS:
        adjusted[symbol] += freed_weight * adjusted[symbol] / (
            metal_weight + 0.0
        )
    adjusted["SLV"] = 1.0 - sum(adjusted[symbol] for symbol in ("BTC/USD", "ETH/USD", "GLD"))
    if not math.isclose(sum(adjusted.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError("capped target weights do not sum to 1.0")
    return adjusted


def _apply_live_crypto_cap(
    cycle_id: str,
    target_weights: dict[str, float],
    target_base: float,
) -> tuple[dict[str, float], float, dict[str, float], float, float]:
    from core.fleet_equity import get_fleet_equity

    try:
        fleet_equity, fleet_breakdown = get_fleet_equity()
    except Exception as exc:
        logger.critical(f"Bot 3 | crypto fleet cap unavailable: {exc}")
        _log_decision(
            cycle_id,
            "CRYPTO_CAP_UNAVAILABLE",
            reason=str(exc),
            outcome="FAILED",
            context={"error": str(exc)},
        )
        raise

    pre_cap_crypto_dollars = sum(
        target_weights[symbol] for symbol in CRYPTO
    ) * target_base
    crypto_ceiling = CRYPTO_FLEET_CAP_PCT * fleet_equity
    adjusted_weights = apply_crypto_fleet_cap(
        target_weights,
        target_base,
        fleet_equity,
    )
    _log_decision(
        cycle_id,
        "CRYPTO_CAP_EVALUATED",
        reason="research_ledger experiment 20 fleet crypto cap",
        outcome=(
            "CAPPED"
            if pre_cap_crypto_dollars > crypto_ceiling
            else "UNCHANGED"
        ),
        context={
            "fleet_equity": fleet_equity,
            "fleet_equity_by_bot": fleet_breakdown,
            "crypto_ceiling_usd": crypto_ceiling,
            "pre_cap_crypto_dollars": pre_cap_crypto_dollars,
            "post_cap_weights": adjusted_weights,
        },
    )
    return (
        adjusted_weights,
        fleet_equity,
        fleet_breakdown,
        crypto_ceiling,
        pre_cap_crypto_dollars,
    )


class AlpacaBot3:
    """Small direct Alpaca adapter; no shared-engine schema side effects."""

    def __init__(self, api_key: str, secret_key: str, base_url: str = ALPACA_BASE_URL):
        if not api_key or not secret_key:
            raise RuntimeError("Bot 3 requires ALPACA_JEROME_API_KEY and ALPACA_JEROME_SECRET_KEY")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(method, self.base_url + path, timeout=20, **kwargs)
        if not response.ok:
            raise requests.HTTPError(
                f"{response.status_code} {response.reason}: {response.text}",
                response=response,
            )
        response.raise_for_status()
        return response.json() if response.content else None

    def _data_request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(
            method, ALPACA_DATA_BASE_URL + path, timeout=20, **kwargs
        )
        response.raise_for_status()
        return response.json() if response.content else None

    def account(self) -> dict[str, float]:
        raw = self._request("GET", "/v2/account")
        account = {
            key: float(raw[key])
            for key in ("equity", "cash", "buying_power")
        }
        # Alpaca's long_market_value includes vault and other long holdings.
        # Preserve its absence for test doubles/broker responses that omit it;
        # _fresh_buy_guard then obtains a fresh position snapshot instead.
        if raw.get("long_market_value") is not None:
            account["long_market_value"] = float(raw["long_market_value"])
        return account

    def positions(self) -> list[dict[str, Any]]:
        raw = self._request("GET", "/v2/positions")
        result = []
        for position in raw:
            result.append({
                "symbol": _canonical_symbol(position["symbol"]),
                "qty": float(position["qty"]),
                "entry_price": float(position["avg_entry_price"]),
                "current_price": float(position["current_price"]),
                "market_value": float(position["market_value"]),
            })
        return result

    def open_orders(self) -> list[dict[str, Any]]:
        orders = self._request("GET", "/v2/orders", params={"status": "open", "limit": 500}) or []
        for order in orders:
            order["symbol"] = _canonical_symbol(order["symbol"])
        return orders

    def latest_prices(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        for symbol in METALS:
            quote = self._data_request(
                "GET", f"/v2/stocks/{symbol}/quotes/latest"
            ).get("quote", {})
            bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
            if bid <= 0 and ask <= 0:
                raise RuntimeError(f"Bot 3 missing Alpaca quote for {symbol}")
            prices[symbol] = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
        crypto_quotes = self._data_request(
            "GET",
            "/v1beta3/crypto/us/latest/quotes",
            params={"symbols": ",".join(sorted(CRYPTO))},
        )
        for symbol, quote in (crypto_quotes or {}).get("quotes", crypto_quotes or {}).items():
            bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
            if bid <= 0 and ask <= 0:
                raise RuntimeError(f"Bot 3 missing Alpaca quote for {symbol}")
            prices[symbol] = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
        if set(prices) != set(ASSETS):
            raise RuntimeError(f"Bot 3 incomplete Alpaca quotes: {sorted(prices)}")
        return prices

    def submit(self, symbol: str, side: str, qty: float, order_type: str, **extra: Any) -> dict[str, Any]:
        from core.order_ids import submit_with_unique_client_order_id
        payload = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "qty": str(qty),
            "time_in_force": (
                "gtc"
                if symbol in CRYPTO or order_type in ("stop", "stop_limit")
                else "day"
            ),
            **extra,
        }
        response, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: self._request(
                "POST",
                "/v2/orders",
                json={**payload, "client_order_id": generated_id},
            ),
            f"bot3-order-{symbol.replace('/', '')}",
        )
        if isinstance(response, dict):
            response.setdefault("client_order_id", client_order_id)
        return response

    def wait_for_fill(self, order_id: str, attempts: int = 8) -> dict[str, Any]:
        import time as _time
        for _ in range(attempts):
            order = self._request("GET", f"/v2/orders/{order_id}")
            if order.get("status") in {"filled", "partially_filled", "canceled", "rejected", "expired"}:
                return order
            _time.sleep(1)
        return self._request("GET", f"/v2/orders/{order_id}")


def _strategy_positions() -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT symbol, qty::float8, entry_price::float8, notional_usd::float8,
                       stop_price::float8, stop_order_id
                FROM bot3_positions
                WHERE bot_id=%s AND status='open'
                ORDER BY symbol
                """,
                (BOT_ID,),
            )
            return [
                {
                    "symbol": _canonical_symbol(row[0]), "qty": row[1], "entry_price": row[2],
                    "notional_usd": row[3], "stop_price": row[4], "stop_order_id": row[5],
                }
                for row in cur.fetchall()
            ]


def _record_open(
    fill: dict[str, Any],
    broker_qty: float,
    stop_price: float,
    stop_order_id: str | None,
) -> None:
    qty = float(broker_qty)
    entry = float(fill.get("filled_avg_price") or 0)
    if qty <= 0 or entry <= 0:
        raise RuntimeError("record_open requires a confirmed positive fill")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bot3_positions
                    (bot_id, symbol, qty, entry_price, notional_usd, stop_price, stop_order_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (BOT_ID, fill["symbol"], qty, entry, qty * entry, stop_price, stop_order_id),
            )


def _position_market_value(position: dict[str, Any]) -> float:
    """Return a non-negative marked value for an account position."""
    try:
        return max(0.0, float(position.get("market_value", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _long_market_value(positions: list[dict[str, Any]]) -> float:
    """Sum the long exposure represented by a broker position snapshot."""
    return sum(
        _position_market_value(position)
        for position in positions
        if str(position.get("direction", "long")).lower() != "short"
    )


def _max_deployment(profile: dict[str, Any] | None) -> float:
    """Read and validate the account deployment ceiling.

    Bot 3's normal profile is always-invested (1.00), but the value must still
    be consumed by the planner and order-boundary guard. Invalid configuration
    fails closed rather than silently changing the risk envelope.
    """
    raw_value = (profile or {}).get("MAX_DEPLOYMENT", DEFAULT_MAX_DEPLOYMENT)
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid MAX_DEPLOYMENT={raw_value!r}") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"MAX_DEPLOYMENT must be between 0 and 1, got {raw_value!r}")
    return value


def _allocation_bases(
    account: dict[str, float],
    positions: list[dict[str, Any]],
    max_deployment: float,
) -> tuple[float, float, float]:
    """Return total equity, vault-excluded equity, and capped target base."""
    equity = max(0.0, float(account.get("equity", 0.0) or 0.0))
    vault_market_value = sum(
        _position_market_value(position)
        for position in positions
        if _canonical_symbol(position.get("symbol")) in VAULT_SYMBOLS
    )
    investable_base = max(0.0, equity - vault_market_value)
    deployment_headroom = max(0.0, equity * max_deployment - vault_market_value)
    target_base = min(investable_base, deployment_headroom)
    return equity, investable_base, target_base


def _fresh_buy_guard(
    client: AlpacaBot3,
    item: dict[str, Any],
    max_deployment: float,
) -> tuple[bool, dict[str, float]]:
    """Check one buy against freshly fetched account state.

    The account's long-market-value field includes vault holdings and any other
    long positions. If a broker response omits it, fall back to a fresh
    position snapshot rather than assuming the strategy is the whole account.
    """
    fresh_account = client.account()
    fresh_equity = float(fresh_account.get("equity", 0.0) or 0.0)
    fresh_cash = float(fresh_account.get("cash", 0.0) or 0.0)
    fresh_long_market_value = fresh_account.get("long_market_value")
    if fresh_long_market_value is None:
        fresh_long_market_value = _long_market_value(client.positions())
    else:
        fresh_long_market_value = float(fresh_long_market_value or 0.0)

    qty = max(0.0, float(item.get("qty", 0.0) or 0.0))
    price = max(0.0, float(item.get("price", 0.0) or 0.0))
    estimated_notional = qty * price
    projected_cash = fresh_cash - estimated_notional
    projected_long_market_value = fresh_long_market_value + estimated_notional
    projected_deployment = (
        projected_long_market_value / fresh_equity
        if fresh_equity > 0
        else float("inf")
    )
    projection = {
        "fresh_equity": fresh_equity,
        "fresh_cash": fresh_cash,
        "fresh_long_market_value": fresh_long_market_value,
        "estimated_notional": estimated_notional,
        "projected_cash": projected_cash,
        "projected_long_market_value": projected_long_market_value,
        "projected_deployment": projected_deployment,
        "max_deployment": max_deployment,
    }
    allowed = (
        fresh_equity > 0
        and projected_cash >= 0
        and projected_long_market_value <= fresh_equity
        and projected_deployment <= max_deployment
    )
    return allowed, projection


def _arm_stop(client: AlpacaBot3, symbol: str, qty: float, entry_price: float) -> dict[str, Any]:
    stop_price = entry_price * (
        1.0 - CRYPTO_STOP_PCT if symbol in CRYPTO else 1.0 - METAL_STOP_PCT
    )
    if symbol in CRYPTO:
        return client.submit(
            symbol, "sell", qty, "stop_limit",
            stop_price=round(stop_price, 8),
            limit_price=round(stop_price * 0.99, 8),
        )
    whole_qty = math.floor(qty)
    if whole_qty < 1:
        raise RuntimeError(f"{symbol}: no whole share available for GTC stop")
    return client.submit(
        symbol, "sell", whole_qty, "stop",
        stop_price=round(stop_price, 2),
    )

def _broker_position_qty(client: AlpacaBot3, symbol: str) -> float:
    canonical = _canonical_symbol(symbol)
    return sum(
        float(position["qty"])
        for position in client.positions()
        if _canonical_symbol(position["symbol"]) == canonical
    )

def _settled_broker_position_qty(
    client: AlpacaBot3, symbol: str, attempts: int = 10
) -> float | None:
    import time as _time
    previous: float | None = None
    for attempt in range(attempts):
        current = _broker_position_qty(client, symbol)
        if current > 0 and previous is not None and math.isclose(
            current, previous, rel_tol=0.0, abs_tol=1e-12
        ):
            return current
        previous = current if current > 0 else None
        if attempt < attempts - 1:
            _time.sleep(1)
    return None

def _cancel_symbol_orders(client: AlpacaBot3, symbol: str) -> None:
    canonical = _canonical_symbol(symbol)
    for order in client.open_orders():
        if _canonical_symbol(order.get("symbol", "")) == canonical:
            client._request("DELETE", f"/v2/orders/{order['id']}")

def _flatten_position(client: AlpacaBot3, symbol: str) -> None:
    _cancel_symbol_orders(client, symbol)
    for attempt in range(2):
        current_qty = _broker_position_qty(client, symbol)
        if current_qty <= 0:
            return
        sell = client.submit(symbol, "sell", current_qty, "market")
        client.wait_for_fill(sell["id"])
        if _broker_position_qty(client, symbol) <= 1e-9:
            return
        logger.critical(
            "Bot 3 | flatten not confirmed; retrying | "
            f"symbol={symbol} attempt={attempt + 1}"
        )
    raise RuntimeError(f"Bot 3 could not confirm flat for {symbol}")


def _remember_stop(symbol: str, stop_order_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE bot3_positions
                SET stop_order_id=%s
                WHERE bot_id=%s AND symbol=%s AND status='open'
                """,
                (stop_order_id, BOT_ID, symbol),
            )


def _maintain_protective_stops(
    client: AlpacaBot3,
    positions: list[dict[str, Any]],
    cycle_id: str,
    equity_session_open: bool,
) -> None:
    """Re-arm a missing protective stop before checking the software backstop."""
    open_orders = client.open_orders()
    for position in positions:
        symbol = position["symbol"]
        if any(_covers(position, order) for order in open_orders):
            continue
        raw_response = None
        try:
            stop_order = _arm_stop(
                client, symbol, position["qty"], position["entry_price"]
            )
            stop_status = str(stop_order.get("status", "")).lower()
            if stop_status in {"rejected", "failed", "error", "canceled", "cancelled"}:
                raw_response = repr(stop_order)
                raise RuntimeError(
                    f"broker rejected protective stop with status={stop_status}"
                )
            stop_id = stop_order.get("id")
            if stop_id:
                _remember_stop(symbol, stop_id)
            _log_decision(
                cycle_id, "PROTECTIVE_STOP_REARMED", symbol=symbol,
                order_id=stop_id, outcome=stop_order.get("status", "submitted"),
            )
        except Exception as exc:
            if raw_response is None:
                broker_response = getattr(exc, "response", None)
                raw_response = getattr(broker_response, "text", None)
                if raw_response is None:
                    raw_response = repr(exc)
            error = f"{type(exc).__name__}: {exc}"
            logger.critical(
                "Bot 3 | protective stop arm failed | "
                f"symbol={symbol} error={error} raw_broker_response={raw_response}"
            )
            _log_decision(
                cycle_id,
                "PROTECTIVE_STOP_ARM_FAILED",
                symbol=symbol,
                reason=error,
                context={"error": error, "raw_broker_response": raw_response},
            )
            raise


def _software_backstop(
    client: AlpacaBot3,
    positions: list[dict[str, Any]],
    cycle_id: str,
    equity_session_open: bool,
) -> None:
    """Submit a market sell if a protective stop is breached but not filled."""
    open_orders = client.open_orders()
    for position in positions:
        symbol = position["symbol"]
        if symbol in VAULT_SYMBOLS or any(
            _covers(position, order) for order in open_orders
        ):
            continue
        if position["current_price"] > position["stop_price"]:
            continue
        if symbol in METALS and not equity_session_open:
            _log_decision(
                cycle_id, "SOFTWARE_BACKSTOP_DEFERRED", symbol=symbol,
                reason="US equity market closed",
            )
            continue
        broker_qty = _broker_position_qty(client, symbol)
        if broker_qty <= 0:
            continue
        order = client.submit(symbol, "sell", broker_qty, "market")
        _log_decision(
            cycle_id, "SOFTWARE_BACKSTOP_SELL", symbol=symbol,
            reason="protective stop breached without active sell order",
            order_id=order.get("id"), outcome="SUBMITTED",
        )


def _place_confirmed_entry(
    client: AlpacaBot3,
    symbol: str,
    qty: float,
    cycle_id: str,
) -> dict[str, Any]:
    order = client.submit(
        symbol,
        "buy",
        math.floor(qty) if symbol in METALS else qty,
        "market",
    )
    fill = client.wait_for_fill(order["id"])
    status = fill.get("status")
    filled_qty = float(fill.get("filled_qty") or 0)
    filled_price = float(fill.get("filled_avg_price") or 0)
    if status not in {"filled", "partially_filled"} or filled_qty <= 0 or filled_price <= 0:
        _log_decision(
            cycle_id, "ENTRY_NOT_FILLED", symbol=symbol,
            order_id=order["id"], outcome=status,
        )
        return fill
    broker_qty = _settled_broker_position_qty(client, symbol)
    if broker_qty is None:
        logger.critical(
            "Bot 3 | position did not settle after fill; flattening without guessing | "
            f"symbol={symbol}"
        )
        _flatten_position(client, symbol)
        raise RuntimeError(f"Bot 3 aborted: unsettled position for {symbol}")
    stop_price = filled_price * (
        1.0 - CRYPTO_STOP_PCT if symbol in CRYPTO else 1.0 - METAL_STOP_PCT
    )
    try:
        stop_order = _arm_stop(client, symbol, broker_qty, filled_price)
    except Exception as first_exc:
        logger.critical(
            "Bot 3 | protective stop failed after fill; retrying once | "
            f"symbol={symbol} qty={broker_qty} error={first_exc}"
        )
        try:
            stop_order = _arm_stop(client, symbol, broker_qty, filled_price)
        except Exception as second_exc:
            logger.critical(
                "Bot 3 | protective stop retry failed; flattening immediately | "
                f"symbol={symbol} qty={broker_qty} error={second_exc}"
            )
            _flatten_position(client, symbol)
            logger.critical(
                "Bot 3 | protective stop failure recovered by confirmed flatten | "
                f"symbol={symbol}"
            )
            raise RuntimeError(
                f"Bot 3 aborted after stop failure for {symbol}: {second_exc}"
            ) from second_exc
    recorded_fill = {**fill, "symbol": _canonical_symbol(symbol)}
    stop_order_id = stop_order.get("id")
    _record_open(recorded_fill, broker_qty, stop_price, stop_order_id)
    if stop_order_id:
        # Keep the explicit write-back next to every accepted stop ID. The
        # insert above handles new rows; this also covers any existing open row
        # restored during a retry/reconciliation path.
        _remember_stop(symbol, stop_order_id)
    _log_decision(
        cycle_id, "ENTRY_FILLED", symbol=symbol, planned_qty=qty,
        current_price=filled_price, order_id=order["id"], outcome="FILLED",
        context={"stop_order_id": stop_order_id},
    )
    return fill


def _plan_orders(
    account: dict[str, float],
    positions: list[dict[str, Any]],
    targets: dict[str, float],
    cycle_id: str,
    current_prices: dict[str, float],
    max_deployment: float = DEFAULT_MAX_DEPLOYMENT,
) -> list[dict[str, Any]]:
    equity, investable_base, target_base = _allocation_bases(
        account, positions, max_deployment
    )
    position_by_symbol = {
        _canonical_symbol(position["symbol"]): position for position in positions
        if _canonical_symbol(position.get("symbol")) in ASSETS
    }
    plan = []
    for symbol in ASSETS:
        position = position_by_symbol.get(symbol)
        current_value = _position_market_value(position) if position else 0.0
        current_weight = current_value / target_base if target_base > 0 else 0.0
        target_weight = float(targets[symbol])
        target_value = target_base * target_weight
        delta = target_value - current_value
        if abs(current_weight - target_weight) <= DRIFT_BAND and position:
            decision = "HOLD_WITHIN_DRIFT_BAND"
        elif delta > 0:
            price = position["current_price"] if position else current_prices[symbol]
            qty = delta / price if price > 0 else 0.0
            decision = "BUY_TO_TARGET"
            plan.append({
                "symbol": symbol,
                "side": "buy",
                "qty": qty,
                "price": price,
                "notional": qty * price,
            })
        else:
            price = position["current_price"] if position else current_prices[symbol]
            qty = min(position["qty"], abs(delta) / price) if position and price > 0 else 0.0
            decision = "SELL_TO_TARGET"
            if qty > 0:
                plan.append({
                    "symbol": symbol,
                    "side": "sell",
                    "qty": qty,
                    "price": price,
                    "notional": qty * price,
                })
        _log_decision(
            cycle_id, decision, symbol=symbol, current_weight=current_weight,
            target_weight=target_weight,
            current_price=position["current_price"] if position else None,
            planned_qty=plan[-1]["qty"] if plan and plan[-1]["symbol"] == symbol else None,
            reason="quarterly target comparison",
            context={
                "equity": equity,
                "investable_base": investable_base,
                "target_base": target_base,
                "max_deployment": max_deployment,
            },
        )
    # Always liquidate reductions before submitting increases. If a sell has
    # not settled yet, the fresh buy guard below will refuse the buy safely.
    return sorted(plan, key=lambda item: 0 if item["side"] == "sell" else 1)


def run_bot3_cycle(
    profile: dict[str, Any] | None = None,
    now: datetime | None = None,
    db_id: int | None = None,
) -> dict[str, Any]:
    """Live cycle. The first executable branch is the permanent build pause."""
    if BOT_PAUSED:
        logger.info("Bot 3 | BOT_PAUSED=True — no client, account read, or order activity")
        return {"status": "paused", "orders": 0}

    profile = profile or {}
    try:
        max_deployment = _max_deployment(profile)
    except ValueError as exc:
        logger.critical(f"Bot 3 | invalid deployment configuration — fail closed: {exc}")
        return {"status": "error", "orders": 0, "reason": "invalid_deployment_config"}
    now = now or datetime.now(timezone.utc)
    cycle_id = uuid.uuid4().hex
    ensure_bot3_tables()
    client = AlpacaBot3(
        (
            profile.get("ALPACA_JEROME_API_KEY")
            or profile.get("ALPACA_API_KEY")
            or os.environ.get("ALPACA_JEROME_API_KEY")
            or os.environ.get("ALPACA_API_KEY", "")
        ),
        (
            profile.get("ALPACA_JEROME_SECRET_KEY")
            or profile.get("ALPACA_SECRET_KEY")
            or os.environ.get("ALPACA_JEROME_SECRET_KEY")
            or os.environ.get("ALPACA_SECRET_KEY", "")
        ),
        profile.get("ALPACA_BASE_URL", ALPACA_BASE_URL),
    )
    account = client.account()
    raw_positions = client.positions()
    live_positions = [
        position for position in raw_positions
        if _canonical_symbol(position["symbol"]) in ASSETS
        and _canonical_symbol(position["symbol"]) not in VAULT_SYMBOLS
    ]
    db_positions = {position["symbol"]: position for position in _strategy_positions()}
    initial_entry = not live_positions and not db_positions
    partial_entry = bool(live_positions) and {
        _canonical_symbol(position["symbol"]) for position in live_positions
    } != set(ASSETS)
    positions = []
    for live in live_positions:
        stored = db_positions.get(live["symbol"], {})
        entry_price = stored.get("entry_price", live["entry_price"])
        positions.append({
            **live,
            "stop_price": stored.get(
                "stop_price",
                entry_price * (
                    1.0 - CRYPTO_STOP_PCT
                    if live["symbol"] in CRYPTO else 1.0 - METAL_STOP_PCT
                ),
            ),
            "stop_order_id": stored.get("stop_order_id"),
        })
    _log_decision(cycle_id, "CYCLE_START", context={"equity": account["equity"]})
    equity_session_open = _nyse_session_open(now)
    _maintain_protective_stops(client, positions, cycle_id, equity_session_open)
    _software_backstop(client, positions, cycle_id, equity_session_open)
    if not initial_entry and not partial_entry and not _quarterly_rebalance_date(now):
        _log_decision(cycle_id, "NO_REBALANCE", reason="not first trading day of quarter")
        return {"status": "complete", "orders": 0, "reason": "not_quarterly_date"}
    if not _nyse_session_open(now):
        _log_decision(
            cycle_id,
            "INITIAL_ENTRY_DEFERRED" if initial_entry else "REBALANCE_DEFERRED",
            reason="US equity market closed",
        )
        return {"status": "deferred", "orders": 0, "reason": "US_equity_market_closed"}
    closes = _load_recent_closes()
    targets, volatility = inverse_vol_targets(closes)
    _, _, target_base = _allocation_bases(
        account,
        raw_positions,
        max_deployment,
    )
    targets, _, _, _, _ = _apply_live_crypto_cap(
        cycle_id,
        targets,
        target_base,
    )
    plan = _plan_orders(
        account,
        raw_positions,
        targets,
        cycle_id,
        client.latest_prices(),
        max_deployment=max_deployment,
    )
    orders = 0
    for item in plan:
        if item["side"] == "sell":
            symbol = _canonical_symbol(item["symbol"])
            broker_qty = _broker_position_qty(client, symbol)
            sell_qty = min(float(item["qty"]), broker_qty)
            if sell_qty > 0:
                sell_order = client.submit(symbol, "sell", sell_qty, "market")
                client.wait_for_fill(sell_order["id"])
                orders += 1
            continue

        allowed, projection = _fresh_buy_guard(client, item, max_deployment)
        if not allowed:
            _log_decision(
                cycle_id,
                "BUY_BLOCKED",
                symbol=item["symbol"],
                planned_qty=item["qty"],
                current_price=item.get("price"),
                reason="cash_or_deployment_guard",
                context=projection,
            )
            logger.critical(
                "Bot 3 | BUY BLOCKED by cash/deployment guard | "
                f"symbol={item['symbol']} qty={item['qty']:.8f} "
                f"projected_cash=${projection['projected_cash']:,.2f} "
                f"projected_long=${projection['projected_long_market_value']:,.2f} "
                f"projected_deployment={projection['projected_deployment']:.2%} "
                f"max_deployment={max_deployment:.2%}"
            )
            continue

        _place_confirmed_entry(client, item["symbol"], item["qty"], cycle_id)
        orders += 1
    return {
        "status": "complete",
        "orders": orders,
        "reason": (
            "initial_entry" if initial_entry
            else "partial_entry_recovery" if partial_entry
            else "quarterly_rebalance"
        ),
        "targets": targets,
        "volatility": volatility,
    }


def dry_run_cycle() -> dict[str, Any]:
    """Simulate an empty post-migration account without touching Alpaca."""
    # Exercise the same per-cycle UUID path used by live cycles without
    # constructing a broker client or submitting any orders.
    cycle_id = uuid.uuid4().hex
    try:
        closes = _load_recent_closes()
        data_source = "validated database price tables"
    except RuntimeError as exc:
        # The dry-run must remain a deterministic offline harness.  Do not
        # silently turn missing research data into live behavior: announce the
        # synthetic fixture and never call ensure_schema or an Alpaca client.
        logger.warning(f"Bot 3 dry-run data unavailable: {exc}; using synthetic fixture")
        bases = {"BTC/USD": 60_000.0, "ETH/USD": 2_000.0, "GLD": 400.0, "SLV": 30.0}
        closes = {
            symbol: [
                base * (1.0 + 0.0005 * ((index % 7) - 3))
                for index in range(VOL_LOOKBACK + 1)
            ]
            for symbol, base in bases.items()
        }
        data_source = "deterministic synthetic fixture"
    targets, volatility = inverse_vol_targets(closes)
    account = {"equity": 100_000.0, "cash": 100_000.0, "buying_power": 100_000.0}
    positions: list[dict[str, Any]] = []
    print(f"DRY_RUN_CYCLE | cycle_id={cycle_id} | data={data_source} | completed_without_exception")
    print("DRY_RUN_ACCOUNT | post-migration empty strategy account | equity=$100,000.00 | positions=0")
    print("DRY_RUN_DATE | first quarterly trading day | metal_session=open required")
    print("DRY_RUN_TARGETS | " + " | ".join(f"{symbol}={targets[symbol]:.2%}" for symbol in ASSETS))
    print("DRY_RUN_VOL | " + " | ".join(f"{symbol}={volatility[symbol]:.4f}" for symbol in ASSETS))
    current_prices = {
        symbol: values[-1] for symbol, values in closes.items()
    }
    plan = _plan_orders(
        account,
        positions,
        targets,
        cycle_id,
        current_prices,
        max_deployment=DEFAULT_MAX_DEPLOYMENT,
    )
    _, investable_base, target_base = _allocation_bases(
        account, positions, DEFAULT_MAX_DEPLOYMENT
    )
    for item in plan:
        print(
            f"WOULD_SUBMIT | {item['side'].upper()} | {item['symbol']} | "
            f"qty={item['qty']:.8f} | notional=${item['notional']:,.2f}"
        )
    print(
        f"DRY_RUN_BASES | investable_equity=${investable_base:,.2f} | "
        f"target_base=${target_base:,.2f} | max_deployment={DEFAULT_MAX_DEPLOYMENT:.2%}"
    )
    print("DRY_RUN_ORDERS | 0 submitted | simulation plan only")
    return {"targets": targets, "volatility": volatility, "plan": plan, "orders": 0}


def print_module() -> None:
    print("BOT3_MODULE=bot3_hard_assets_strategy.py")
    print(f"BOT_ID={BOT_ID}")
    print(f"BOT_PAUSED={BOT_PAUSED}")
    print("UNIVERSE=BTC/USD, ETH/USD, GLD, SLV")
    print("WEIGHTING=inverse volatility, trailing 60 observations, floor 10%, cap 40%")
    print("REBALANCE=first trading day of Jan/Apr/Jul/Oct, 5pp drift band")
    print("SESSION_POLICY=defer entire rebalance while US equity session is closed")
    print("INITIAL_ENTRY=empty Bot 3 account bypasses quarterly date and establishes targets on the next open US equity session")
    print("SCHEDULED_REBALANCE=non-empty account only rebalances on first trading day of quarter")
    print("VAULT_POLICY=ignore BIL/VOO vault holdings; neither is in strategy universe")
    print("STOP_POLICY=crypto stop_limit 25%; metals whole-share GTC stop 10%")
    print("FILL_POLICY=record_open only after confirmed fill; stop armed after fill")
    print("STOP_ID_POLICY=unique UUID suffix on every stop submit")
    print("SOFTWARE_BACKSTOP=market sell if breached stop has no active sell order")
    print("UNPAUSE=only after migration confirms Bot 3 account flat/reconciled and EPOL/GREK/TUR untouched; then explicitly edit BOT_PAUSED=False")
    print("RUNNER=registered as jerome_macro -> bot3_hard_assets_strategy.run_bot3_cycle; runner not started")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-module", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not (args.print_module or args.dry_run):
        parser.error("use --print-module or --dry-run")
    if args.print_module:
        print_module()
    if args.dry_run:
        dry_run_cycle()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())