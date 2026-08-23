"""Bot 3 hard-assets sleeve.

This module is deliberately built paused.  It is not imported by runner.py and
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
from datetime import date, datetime, time, timezone
from pathlib import Path
from statistics import stdev
from typing import Any

import requests

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402

logger = logging.getLogger("bot3.hard_assets")

BOT_ID = "jerome_macro"
BOT_PAUSED = True
ASSETS = ("BTC/USD", "ETH/USD", "GLD", "SLV")
CRYPTO = frozenset({"BTC/USD", "ETH/USD"})
METALS = frozenset({"GLD", "SLV"})
VAULT_SYMBOLS = frozenset({"BIL", "VOO"})
TARGET_WEIGHT = 0.25
VOL_LOOKBACK = 60
WEIGHT_FLOOR = 0.10
WEIGHT_CAP = 0.40
DRIFT_BAND = 0.05
CRYPTO_STOP_PCT = 0.25
METAL_STOP_PCT = 0.10
EQUITY_SESSION_OPEN = time(9, 30)
EQUITY_SESSION_CLOSE = time(16, 0)
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
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
    return eastern.month in (1, 4, 7, 10) and eastern.day <= 7 and eastern.weekday() < 5


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


def _client_id(prefix: str, symbol: str) -> str:
    return f"bot3-{prefix}-{symbol.replace('/', '')}-{uuid.uuid4().hex[:10]}"[:48]


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
        response.raise_for_status()
        return response.json() if response.content else None

    def account(self) -> dict[str, float]:
        raw = self._request("GET", "/v2/account")
        return {key: float(raw[key]) for key in ("equity", "cash", "buying_power")}

    def positions(self) -> list[dict[str, Any]]:
        raw = self._request("GET", "/v2/positions")
        result = []
        for position in raw:
            result.append({
                "symbol": position["symbol"],
                "qty": float(position["qty"]),
                "entry_price": float(position["avg_entry_price"]),
                "current_price": float(position["current_price"]),
                "market_value": float(position["market_value"]),
            })
        return result

    def open_orders(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v2/orders", params={"status": "open", "limit": 500}) or []

    def latest_prices(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        for symbol in METALS:
            quote = self._request("GET", f"/v2/stocks/{symbol}/quotes/latest").get("quote", {})
            bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
            if bid <= 0 and ask <= 0:
                raise RuntimeError(f"Bot 3 missing Alpaca quote for {symbol}")
            prices[symbol] = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
        crypto_quotes = self._request(
            "GET",
            "/v1beta3/crypto/us/latest/quotes",
            params={"symbols": ",".join(sorted(CRYPTO))},
        )
        for symbol, quote in (crypto_quotes or {}).items():
            bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
            if bid <= 0 and ask <= 0:
                raise RuntimeError(f"Bot 3 missing Alpaca quote for {symbol}")
            prices[symbol] = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
        if set(prices) != set(ASSETS):
            raise RuntimeError(f"Bot 3 incomplete Alpaca quotes: {sorted(prices)}")
        return prices

    def submit(self, symbol: str, side: str, qty: float, order_type: str, **extra: Any) -> dict[str, Any]:
        payload = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "qty": str(qty),
            "time_in_force": "gtc" if order_type in ("stop", "stop_limit") else "day",
            "client_order_id": _client_id("order", symbol),
            **extra,
        }
        return self._request("POST", "/v2/orders", json=payload)

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
                    "symbol": row[0], "qty": row[1], "entry_price": row[2],
                    "notional_usd": row[3], "stop_price": row[4], "stop_order_id": row[5],
                }
                for row in cur.fetchall()
            ]


def _record_open(fill: dict[str, Any], stop_price: float, stop_order_id: str | None) -> None:
    qty = float(fill.get("filled_qty") or 0)
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


def _software_backstop(
    client: AlpacaBot3,
    positions: list[dict[str, Any]],
    cycle_id: str,
    equity_session_open: bool,
) -> None:
    """Submit a market sell if a protective stop is breached but not filled."""
    open_orders = client.open_orders()
    open_symbols = {order.get("symbol") for order in open_orders if order.get("side") == "sell"}
    for position in positions:
        symbol = position["symbol"]
        if symbol in VAULT_SYMBOLS or symbol in open_symbols:
            continue
        if position["current_price"] > position["stop_price"]:
            continue
        if symbol in METALS and not equity_session_open:
            _log_decision(
                cycle_id, "SOFTWARE_BACKSTOP_DEFERRED", symbol=symbol,
                reason="US equity market closed",
            )
            continue
        order = client.submit(
            symbol, "sell",
            math.floor(position["qty"]) if symbol in METALS else position["qty"],
            "market",
        )
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
    stop_order = _arm_stop(client, symbol, filled_qty, filled_price)
    stop_price = filled_price * (
        1.0 - CRYPTO_STOP_PCT if symbol in CRYPTO else 1.0 - METAL_STOP_PCT
    )
    _record_open(fill, stop_price, stop_order.get("id"))
    _log_decision(
        cycle_id, "ENTRY_FILLED", symbol=symbol, planned_qty=qty,
        current_price=filled_price, order_id=order["id"], outcome="FILLED",
        context={"stop_order_id": stop_order.get("id")},
    )
    return fill


def _plan_orders(
    account: dict[str, float],
    positions: list[dict[str, Any]],
    targets: dict[str, float],
    cycle_id: str,
    current_prices: dict[str, float],
) -> list[dict[str, Any]]:
    equity = account["equity"]
    position_by_symbol = {position["symbol"]: position for position in positions}
    plan = []
    for symbol in ASSETS:
        position = position_by_symbol.get(symbol)
        current_value = position["market_value"] if position else 0.0
        current_weight = current_value / equity if equity > 0 else 0.0
        target_value = equity * targets[symbol]
        delta = target_value - current_value
        if abs(current_weight - targets[symbol]) <= DRIFT_BAND and position:
            decision = "HOLD_WITHIN_DRIFT_BAND"
        elif delta > 0:
            price = position["current_price"] if position else current_prices[symbol]
            qty = delta / price if price > 0 else 0.0
            decision = "BUY_TO_TARGET"
            plan.append({"symbol": symbol, "side": "buy", "qty": qty})
        else:
            price = position["current_price"] if position else current_prices[symbol]
            qty = min(position["qty"], abs(delta) / price) if position and price > 0 else 0.0
            decision = "SELL_TO_TARGET"
            plan.append({"symbol": symbol, "side": "sell", "qty": qty})
        _log_decision(
            cycle_id, decision, symbol=symbol, current_weight=current_weight,
            target_weight=targets[symbol],
            current_price=position["current_price"] if position else None,
            planned_qty=plan[-1]["qty"] if plan and plan[-1]["symbol"] == symbol else None,
            reason="quarterly target comparison",
        )
    return plan


def run_bot3_cycle(profile: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Live cycle. The first executable branch is the permanent build pause."""
    if BOT_PAUSED:
        logger.info("Bot 3 | BOT_PAUSED=True — no client, account read, or order activity")
        return {"status": "paused", "orders": 0}

    profile = profile or {}
    now = now or datetime.now(timezone.utc)
    cycle_id = uuid.uuid4().hex
    ensure_bot3_tables()
    client = AlpacaBot3(
        profile.get("ALPACA_JEROME_API_KEY") or os.environ.get("ALPACA_JEROME_API_KEY", ""),
        profile.get("ALPACA_JEROME_SECRET_KEY") or os.environ.get("ALPACA_JEROME_SECRET_KEY", ""),
        profile.get("ALPACA_BASE_URL", ALPACA_BASE_URL),
    )
    account = client.account()
    raw_positions = client.positions()
    live_positions = [
        position for position in raw_positions
        if position["symbol"] in ASSETS and position["symbol"] not in VAULT_SYMBOLS
    ]
    db_positions = {position["symbol"]: position for position in _strategy_positions()}
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
    _software_backstop(client, positions, cycle_id, _nyse_session_open(now))
    if not _quarterly_rebalance_date(now):
        _log_decision(cycle_id, "NO_REBALANCE", reason="not first trading week of quarter")
        return {"status": "complete", "orders": 0, "reason": "not_quarterly_date"}
    if not _nyse_session_open(now):
        _log_decision(cycle_id, "REBALANCE_DEFERRED", reason="US equity market closed")
        return {"status": "deferred", "orders": 0, "reason": "US_equity_market_closed"}
    closes = _load_recent_closes()
    targets, volatility = inverse_vol_targets(closes)
    plan = _plan_orders(account, positions, targets, cycle_id, client.latest_prices())
    orders = 0
    for item in plan:
        if item["side"] == "buy":
            _place_confirmed_entry(client, item["symbol"], item["qty"], cycle_id)
        else:
            client.submit(
                item["symbol"], "sell",
                math.floor(item["qty"]) if item["symbol"] in METALS else item["qty"],
                "market",
            )
        orders += 1
    return {
        "status": "complete",
        "orders": orders,
        "targets": targets,
        "volatility": volatility,
    }


def dry_run_cycle() -> dict[str, Any]:
    """Simulate an empty post-migration account without touching Alpaca."""
    cycle_id = "dry-run-bot3"
    ensure_bot3_tables()
    closes = _load_recent_closes()
    targets, volatility = inverse_vol_targets(closes)
    account = {"equity": 100_000.0, "cash": 100_000.0, "buying_power": 100_000.0}
    positions: list[dict[str, Any]] = []
    print("DRY_RUN_ACCOUNT | post-migration empty strategy account | equity=$100,000.00 | positions=0")
    print("DRY_RUN_DATE | first quarterly trading day | metal_session=open required")
    print("DRY_RUN_TARGETS | " + " | ".join(f"{symbol}={targets[symbol]:.2%}" for symbol in ASSETS))
    print("DRY_RUN_VOL | " + " | ".join(f"{symbol}={volatility[symbol]:.4f}" for symbol in ASSETS))
    current_prices = {
        symbol: values[-1] for symbol, values in closes.items()
    }
    plan = _plan_orders(account, positions, targets, cycle_id, current_prices)
    for item in plan:
        print(f"WOULD_SUBMIT | {item['side'].upper()} | {item['symbol']} | qty={item['qty']:.8f}")
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
    print("VAULT_POLICY=ignore BIL/VOO vault holdings; neither is in strategy universe")
    print("STOP_POLICY=crypto stop_limit 25%; metals whole-share GTC stop 10%")
    print("FILL_POLICY=record_open only after confirmed fill; stop armed after fill")
    print("STOP_ID_POLICY=unique UUID suffix on every stop submit")
    print("SOFTWARE_BACKSTOP=market sell if breached stop has no active sell order")
    print("UNPAUSE=only after migration confirms Bot 3 account flat/reconciled and EPOL/GREK/TUR untouched; then explicitly edit BOT_PAUSED=False")
    print("RUNNER=not wired by this build; wiring/restart remains a separate authorized step")


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