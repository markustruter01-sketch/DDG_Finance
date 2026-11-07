"""Fail-closed fleet safety checks and broker/ledger reconciliation.

This module is deliberately separate from strategy and order placement code.
It reads broker state, pauses bots on a confirmed trip, and cancels only
non-protective pending orders.  It never liquidates positions.
"""
from __future__ import annotations

import json
import hmac
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from config.settings import settings
from core.symbols import canonical_symbol, same_symbol
from core.cash_park import is_cash_park
from core.stop_policy import stop_exempt
from core.bot_config import load_bot_profiles
from core.bot_registry import active_bot_ids
from core.risk_limits import HARD_DRAWDOWN

DUST_QTY = 1e-6
# Alpaca only accepts whole-share GTC stops on equities
# (kraken-bot/alpaca_etf_engine.py:631). A fractional remainder below one
# share therefore cannot be covered and is not a naked position. Crypto
# accepts fractional stops, so its tolerance stays at DUST_QTY.
EQUITY_STOP_SHORTFALL_TOLERANCE = 1.0
MISSING_STOP_SECONDS = 60.0
MISMATCH_REQUIRED_CHECKS = 2
RESET_CONFIRMATION_ENV_VAR = "KILL_SWITCH_RESET_CONFIRMATION"
# kill_switch_events doubles as the persisted latch: the switch is tripped
# while the newest event is anything other than a reset.
RESET_EVENT_TRIGGER = "reset"
# Registry list includes paused, non-retired bots so the safety monitor still
# observes Forex while its strategy remains paused.
ACTIVE_BOTS = tuple(active_bot_ids())
ACCOUNT_ENV = {
    "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
    "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
}
_BOT_PROFILE_KEYS = {
    "oracle": "oracle",
    "spy_qqq_trend": "bot2_spy_qqq",
    "jerome_macro": "jerome_macro",
}
_BOT_PROFILES = load_bot_profiles()
ALPACA_BOTS = tuple(bot_id for bot_id in ACTIVE_BOTS if bot_id in ACCOUNT_ENV)
MAX_DEPLOYMENT = {
    bot_id: float(_BOT_PROFILES[_BOT_PROFILE_KEYS[bot_id]]["MAX_DEPLOYMENT"])
    for bot_id in ALPACA_BOTS
}
FOREX_MAX_GROSS = float(_BOT_PROFILES["forex_ai"]["FOREX_MAX_GROSS"])

_state: dict[str, Any] = {
    "tripped": False,
    "last_snapshot": {},
    "missing_stop_since": {},
    "mismatch_counts": {},
}


def _now() -> float:
    return time.time()


def _is_protective(order: dict[str, Any]) -> bool:
    side = str(order.get("side", "")).lower()
    order_type = str(order.get("type", "")).lower()
    return order_type in {"stop", "stop_limit", "trailing_stop"} and side in {"sell", "buy"}


def matching_protective_orders(
    position: dict[str, Any], orders: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return protective orders matching this position's symbol and exit side."""
    if str(position.get("asset_class") or "").lower() == "forex":
        return [order for order in orders if _covers(position, order)]
    position_side = str(position.get("side", "long")).lower()
    expected = "sell" if position_side != "short" else "buy"
    return [
        order for order in orders
        if _is_protective(order)
        and same_symbol(position.get("symbol"), order.get("symbol"))
        and str(order.get("side", "")).lower() == expected
    ]


def _covers(position: dict[str, Any], order: dict[str, Any]) -> bool:
    if str(position.get("asset_class") or "").lower() == "forex":
        trade_id = str(position.get("trade_id") or "")
        order_trade_id = str(order.get("trade_id") or "")
        order_id = order.get("id")
        order_type = str(order.get("type") or "").lower().replace("-", "_")
        status = str(order.get("status") or "").lower()
        if (
            not trade_id
            or not order_trade_id
            or order_trade_id != trade_id
            or order_id in (None, "")
            or status != "pending"
            or order_type not in {"stop_loss", "stop_loss_order"}
        ):
            return False
        try:
            signed_units = float(
                position.get("signed_units", position.get("qty") or 0)
            )
        except (TypeError, ValueError):
            return False
        if signed_units == 0 or not math.isfinite(signed_units):
            return False
        position_side = str(position.get("side") or "").lower()
        if not position_side:
            position_side = "long" if signed_units > 0 else "short"
        if position_side not in {"long", "short"}:
            return False
        expected_side = "sell" if position_side == "long" else "buy"
        raw_order_side = str(order.get("side") or "").lower()
        if raw_order_side and raw_order_side != expected_side:
            return False
        try:
            position_qty = abs(signed_units)
            order_qty = abs(float(order.get("qty") or 0))
        except (TypeError, ValueError):
            return False
        return (
            math.isfinite(order_qty)
            and order_qty > 0
            and order_qty + DUST_QTY >= position_qty
        )

    if not matching_protective_orders(position, [order]):
        return False
    position_side = str(position.get("side", "long")).lower()
    asset_class = str(position.get("asset_class") or "").lower()
    tolerance = DUST_QTY if "crypto" in asset_class else EQUITY_STOP_SHORTFALL_TOLERANCE
    position_qty = abs(float(position.get("qty") or 0))
    order_qty = float(order.get("qty") or 0)
    if "crypto" in asset_class:
        return order_qty + tolerance >= position_qty
    return order_qty + tolerance > position_qty


def _oanda_mid_price(client: Any, instrument: str) -> float:
    quote = client.current_bid_ask(instrument)
    bid = float(quote.get("bid"))
    ask = float(quote.get("ask"))
    if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask < bid:
        raise ValueError(f"invalid OANDA price for {instrument}")
    return (bid + ask) / 2.0


def _oanda_quote_to_usd(client: Any, currency: str, price_cache: dict[str, float]) -> float:
    if currency == "USD":
        return 1.0

    direct = f"{currency}_USD"
    inverse = f"USD_{currency}"
    try:
        rate = price_cache.get(direct)
        if rate is None:
            rate = _oanda_mid_price(client, direct)
            price_cache[direct] = rate
        return rate
    except Exception:
        rate = price_cache.get(inverse)
        if rate is None:
            rate = _oanda_mid_price(client, inverse)
            price_cache[inverse] = rate
        if rate <= 0 or not math.isfinite(rate):
            raise ValueError(f"invalid USD conversion price for {currency}")
        return 1.0 / rate


def read_oanda_account_snapshot(client: Any | None = None) -> dict[str, Any]:
    """Read and normalize the Forex account without exposing any write methods."""
    owns_client = client is None
    if client is None:
        from core.oanda_client import OandaClient

        client = OandaClient()
    try:
        summary = client.account_summary()
        if str(summary.get("currency") or "").upper() != "USD":
            raise ValueError("OANDA account currency must be USD")
        nav = float(summary.get("nav"))
        balance = float(summary.get("balance"))
        if not math.isfinite(nav) or nav <= 0 or not math.isfinite(balance):
            raise ValueError("OANDA account NAV or balance is invalid")

        raw_trades = client.open_trades()
        if not isinstance(raw_trades, list):
            raise ValueError("OANDA open trades are unavailable")

        price_cache: dict[str, float] = {}
        positions: list[dict[str, Any]] = []
        orders: list[dict[str, Any]] = []
        open_trades: list[dict[str, Any]] = []
        gross_exposure_usd = 0.0
        for raw_trade in raw_trades:
            if not isinstance(raw_trade, dict):
                raise ValueError("OANDA returned an invalid open trade")
            trade_id = str(raw_trade.get("id") or "").strip()
            instrument = str(raw_trade.get("instrument") or "").strip().upper()
            try:
                base_currency, quote_currency = instrument.split("_")
                signed_units = float(raw_trade.get("currentUnits"))
                entry_price = float(raw_trade.get("price"))
            except (ValueError, TypeError):
                raise ValueError("OANDA open trade is missing valid identity or units") from None
            if (
                not trade_id
                or not base_currency
                or not quote_currency
                or not math.isfinite(signed_units)
                or signed_units == 0
                or not math.isfinite(entry_price)
                or entry_price <= 0
            ):
                raise ValueError("OANDA open trade is missing valid identity, units, or entry price")

            if base_currency == "USD":
                trade_gross_usd = abs(signed_units)
            else:
                pair_mid = price_cache.get(instrument)
                if pair_mid is None:
                    pair_mid = _oanda_mid_price(client, instrument)
                    price_cache[instrument] = pair_mid
                quote_to_usd = _oanda_quote_to_usd(client, quote_currency, price_cache)
                trade_gross_usd = abs(signed_units) * pair_mid * quote_to_usd
            if not math.isfinite(trade_gross_usd) or trade_gross_usd < 0:
                raise ValueError(f"invalid USD gross exposure for {instrument}")
            gross_exposure_usd += trade_gross_usd

            side = "long" if signed_units > 0 else "short"
            protective_side = "sell" if side == "long" else "buy"
            stop = raw_trade.get("stopLossOrder")
            normalized_stop = None
            stop_order_id = None
            if isinstance(stop, dict):
                raw_stop_units = stop.get("units", signed_units)
                try:
                    stop_qty = abs(float(raw_stop_units))
                except (TypeError, ValueError):
                    stop_qty = 0.0
                stop_order_id = (
                    str(stop.get("id")).strip()
                    if stop.get("id") not in (None, "")
                    else None
                )
                normalized_stop = {
                    "id": stop_order_id,
                    "trade_id": str(
                        stop.get("tradeID") or stop.get("trade_id") or trade_id
                    ),
                    "symbol": instrument,
                    "qty": stop_qty,
                    "side": str(stop.get("side") or protective_side).lower(),
                    "type": str(stop.get("type") or "STOP_LOSS"),
                    "status": str(stop.get("state") or "").lower(),
                }
                orders.append(normalized_stop)

            trade = {
                "trade_id": trade_id,
                "instrument": instrument,
                "signed_units": signed_units,
                "qty": abs(signed_units),
                "side": side,
                "entry_price": entry_price,
                "stop_order_id": stop_order_id,
                "stop_loss_order": normalized_stop,
                "status": "open",
                "opened_at": raw_trade.get("openTime"),
                "asset_class": "forex",
                "market_value": trade_gross_usd,
            }
            open_trades.append(trade)
            positions.append(
                {
                    "symbol": instrument,
                    "qty": abs(signed_units),
                    "signed_units": signed_units,
                    "side": side,
                    "trade_id": trade_id,
                    "asset_class": "forex",
                    "market_value": trade_gross_usd,
                    "stop_order_id": stop_order_id,
                }
            )

        if not math.isfinite(gross_exposure_usd):
            raise ValueError("OANDA gross exposure is invalid")
        return {
            "bot_id": "forex_ai",
            "currency": "USD",
            "cash": balance,
            "equity": nav,
            "nav": nav,
            "gross_exposure_usd": gross_exposure_usd,
            "positions": positions,
            "orders": orders,
            "open_trades": open_trades,
        }
    finally:
        if owns_client:
            client.close()


def _evaluate_forex_account(account: dict[str, Any], now: float) -> list[dict[str, Any]]:
    bot_id = account.get("bot_id", "forex_ai")
    triggers: list[dict[str, Any]] = []
    try:
        nav = float(account.get("nav", account.get("equity")))
        gross = float(account.get("gross_exposure_usd"))
    except (TypeError, ValueError):
        nav = gross = float("nan")
    if not math.isfinite(nav) or nav <= 0 or not math.isfinite(gross) or gross < 0:
        return [{
            "trigger": "forex_account_data_unknown",
            "bot_id": bot_id,
            "detail": "OANDA NAV or USD gross exposure is missing or invalid",
        }]
    positions = account.get("positions")
    orders = account.get("orders")
    if (
        not isinstance(positions, list)
        or not isinstance(orders, list)
        or any(not isinstance(position, dict) for position in positions)
        or any(not isinstance(order, dict) for order in orders)
    ):
        return [{
            "trigger": "forex_account_data_unknown",
            "bot_id": bot_id,
            "detail": "OANDA positions or attached stop data is unavailable",
        }]
    if gross > FOREX_MAX_GROSS * nav:
        triggers.append(
            {
                "trigger": "forex_gross_exposure",
                "bot_id": bot_id,
                "detail": (
                    f"gross_usd={gross:.2f} nav_usd={nav:.2f} "
                    f"cap={FOREX_MAX_GROSS:.4f}x"
                ),
            }
        )

    for position in positions:
        try:
            qty = abs(float(position.get("signed_units", position.get("qty"))))
            trade_id = str(position.get("trade_id") or "")
            symbol = str(position.get("symbol") or "")
            if not trade_id or not symbol:
                raise ValueError
        except (TypeError, ValueError):
            triggers.append(
                {
                    "trigger": "forex_account_data_unknown",
                    "bot_id": bot_id,
                    "detail": f"invalid trade units for {position.get('trade_id', 'unknown')}",
                }
            )
            continue
        if not math.isfinite(qty) or qty < DUST_QTY:
            continue
        key = f"{bot_id}:{trade_id}"
        if any(_covers(position, order) for order in orders):
            _state["missing_stop_since"].pop(key, None)
            continue
        first_seen = _state["missing_stop_since"].setdefault(key, now)
        if now - first_seen > MISSING_STOP_SECONDS:
            triggers.append(
                {
                    "trigger": "missing_protective_stop",
                    "bot_id": bot_id,
                    "trade_id": trade_id or None,
                    "symbol": position.get("symbol"),
                    "detail": (
                        f"{position.get('symbol')} trade {trade_id or 'unknown'} "
                        f"unprotected for {now - first_seen:.1f}s"
                    ),
                }
            )
    return triggers


def forex_trade_mismatches(
    broker_trades: list[dict[str, Any]],
    ledger_trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare open OANDA trades with the read-only Forex ledger."""
    def indexed(rows: list[dict[str, Any]], source: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{source} contains an unreadable trade row")
            trade_id = str(row.get("trade_id") or row.get("id") or "").strip()
            if not trade_id:
                raise ValueError(f"{source} trade is missing trade_id")
            if trade_id in result:
                raise ValueError(f"{source} contains duplicate trade_id {trade_id}")
            instrument = str(row.get("instrument") or "").strip()
            try:
                signed_units = float(row.get("signed_units"))
            except (TypeError, ValueError):
                raise ValueError(f"{source} trade {trade_id} has unreadable signed units") from None
            if (
                not instrument
                or not math.isfinite(signed_units)
                or signed_units == 0
            ):
                raise ValueError(f"{source} trade {trade_id} is incomplete")
            result[trade_id] = row
        return result

    broker = indexed(broker_trades, "OANDA")
    ledger = indexed(ledger_trades, "forex_ai_trades")
    findings: list[dict[str, Any]] = []
    for trade_id in sorted(set(broker) | set(ledger)):
        live = broker.get(trade_id)
        stored = ledger.get(trade_id)
        if live is None:
            findings.append(
                {
                    "bot_id": "forex_ai",
                    "trade_id": trade_id,
                    "kind": "ledger_trade_without_oanda",
                }
            )
            continue
        if stored is None:
            findings.append(
                {
                    "bot_id": "forex_ai",
                    "trade_id": trade_id,
                    "instrument": live.get("instrument"),
                    "kind": "oanda_trade_without_ledger",
                }
            )
            continue
        differences: dict[str, dict[str, Any]] = {}
        live_instrument = str(live.get("instrument") or "").upper()
        ledger_instrument = str(stored.get("instrument") or "").upper()
        if live_instrument != ledger_instrument:
            differences["instrument"] = {
                "oanda": live_instrument,
                "ledger": ledger_instrument,
            }
        try:
            live_units = float(live.get("signed_units"))
            ledger_units = float(stored.get("signed_units"))
            if not math.isfinite(live_units) or not math.isfinite(ledger_units):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"trade {trade_id} has unreadable signed units") from None
        if abs(live_units - ledger_units) > DUST_QTY:
            differences["signed_units"] = {
                "oanda": live_units,
                "ledger": ledger_units,
            }
        live_stop = live.get("stop_order_id")
        ledger_stop = stored.get("stop_order_id")
        live_stop = str(live_stop) if live_stop not in (None, "") else None
        ledger_stop = str(ledger_stop) if ledger_stop not in (None, "") else None
        if live_stop != ledger_stop:
            differences["stop_order_id"] = {
                "oanda": live_stop,
                "ledger": ledger_stop,
            }
        if differences:
            findings.append(
                {
                    "bot_id": "forex_ai",
                    "trade_id": trade_id,
                    "kind": "forex_trade_mismatch",
                    "differences": differences,
                }
            )
    return findings


def _vault_symbols(bot_id: str) -> set[str]:
    """Return vault-owned symbols from the durable vault holdings table."""
    try:
        import os
        import psycopg2
        from core.database_authority import get_authoritative_dsn
        dsn = get_authoritative_dsn()
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol FROM per_bot_vault_holdings WHERE bot_id = %s",
                    (bot_id,),
                )
                return {canonical_symbol(row[0]) for row in cur.fetchall()}
    except Exception as exc:
        logger.critical(f"Kill switch | vault holdings lookup failed for {bot_id}: {exc}")
        raise


def evaluate_account(account: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    """Return trigger records for one normalized account snapshot."""
    now = _now() if now is None else now
    bot_id = account["bot_id"]
    if bot_id == "forex_ai":
        return _evaluate_forex_account(account, now)
    equity = float(account.get("equity") or 0)
    cash = float(account.get("cash") or 0)
    lmv = float(account.get("long_market_value") or 0)
    triggers: list[dict[str, Any]] = []

    if cash < 0:
        triggers.append({"trigger": "negative_cash", "detail": f"cash={cash:.2f}"})
    if equity > 0 and lmv > equity + 1e-6:
        triggers.append({"trigger": "leverage", "detail": f"lmv={lmv:.2f} equity={equity:.2f}"})

    cash_park_value = sum(
        max(0.0, float(position.get("market_value") or 0))
        for position in account.get("positions", [])
        if is_cash_park(position.get("symbol"))
    )
    deployed_lmv = max(0.0, lmv - cash_park_value)
    deployed_pct = deployed_lmv / equity if equity > 0 else 1.0
    max_deployment = float(account.get("max_deployment", MAX_DEPLOYMENT.get(bot_id, 0.80)))
    if deployed_pct > max_deployment + 0.05 and not account.get("deployment_acknowledged", False):
        triggers.append({
            "trigger": "deployment",
            "detail": f"deployed={deployed_pct:.4f} max={max_deployment:.4f} tolerance=0.05",
        })

    raw_vault_symbols = account.get("vault_symbols")
    if raw_vault_symbols is None:
        triggers.append({
            "trigger": "vault_symbols_unknown",
            "detail": f"{bot_id}: vault symbols unavailable; skipping stop coverage",
        })
        return triggers

    vault_symbols = {
        canonical_symbol(symbol)
        for symbol in raw_vault_symbols
    }
    for position in account.get("positions", []):
        qty = abs(float(position.get("qty") or 0))
        if qty < DUST_QTY:
            _state["missing_stop_since"].pop(f"{bot_id}:{position.get('symbol')}", None)
            continue
        if canonical_symbol(position.get("symbol")) in vault_symbols:
            _state["missing_stop_since"].pop(f"{bot_id}:{position.get('symbol')}", None)
            continue
        if is_cash_park(position.get("symbol")):
            _state["missing_stop_since"].pop(f"{bot_id}:{position.get('symbol')}", None)
            continue
        if stop_exempt(bot_id, canonical_symbol(position.get("symbol"))):
            # FLEET-V1 cross-asset line: stop-free by design (core/stop_policy.py).
            _state["missing_stop_since"].pop(f"{bot_id}:{position.get('symbol')}", None)
            continue
        covered = any(_covers(position, order) for order in account.get("orders", []))
        key = f"{bot_id}:{position.get('symbol')}"
        if covered:
            _state["missing_stop_since"].pop(key, None)
        else:
            first_seen = _state["missing_stop_since"].setdefault(key, now)
            if now - first_seen > MISSING_STOP_SECONDS:
                triggers.append({
                    "trigger": "missing_protective_stop",
                    "detail": f"{position.get('symbol')} unprotected for {now - first_seen:.1f}s",
                })

    return triggers


def evaluate_snapshot(snapshot: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    """Evaluate all pure safety rules without side effects."""
    triggers: list[dict[str, Any]] = []
    for account in snapshot.get("accounts", []):
        triggers.extend(evaluate_account(account, now=now))

    raw_fleet_equity = snapshot.get("fleet_equity")
    raw_fleet_hwm = snapshot.get("fleet_hwm")
    try:
        current = float(raw_fleet_equity) if raw_fleet_equity is not None else None
    except (TypeError, ValueError):
        current = None
    if current is None:
        triggers.append({
            "trigger": "fleet_equity_unknown",
            "detail": f"fleet_equity is not a number: {raw_fleet_equity!r}",
        })
    elif not math.isfinite(current) or current <= 0:
        triggers.append({
            "trigger": "fleet_equity_unknown",
            "detail": f"fleet_equity must be finite and greater than zero: {raw_fleet_equity!r}",
        })
    else:
        hwm = float(raw_fleet_hwm or current)
        threshold = HARD_DRAWDOWN
        if hwm > 0 and (hwm - current) / hwm > threshold:
            triggers.append({
                "trigger": "fleet_drawdown",
                "detail": f"fleet={current:.2f} hwm={hwm:.2f} threshold={threshold:.4f}",
            })

    for mismatch in snapshot.get("mismatches", []):
        key = json.dumps(mismatch, sort_keys=True, default=str)
        count = _state["mismatch_counts"].get(key, 0) + 1
        _state["mismatch_counts"][key] = count
        if count >= MISMATCH_REQUIRED_CHECKS:
            triggers.append({"trigger": "broker_ledger_mismatch", **mismatch})

    for disagreement in snapshot.get("pause_state_disagreements", []):
        triggers.append({"trigger": "pause_state_disagreement", **disagreement})

    for finding in snapshot.get("account_findings", []):
        triggers.append({"trigger": "missing_account", **finding})

    # Liveness is collected with the live broker snapshot. Keeping it in the
    # snapshot makes this evaluator pure and prevents synthetic/unit snapshots
    # from silently querying a real database.
    triggers.extend(snapshot.get("liveness_findings", []))

    return triggers


def _db_call(fn: Callable, default: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        logger.warning(f"Kill switch | database read failed: {exc}")
        return default


def _load_acknowledgements() -> dict[str, bool]:
    def query() -> dict[str, bool]:
        from db.postgres import get_conn
        result: dict[str, bool] = {}
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT condition_key FROM kill_switch_acknowledgements "
                    "WHERE acknowledged_until > NOW()"
                )
                result.update({str(row[0]): True for row in cur.fetchall()})
        return result
    return _db_call(query, {})


def _write_event(trigger: str, snapshot: dict[str, Any], action: str) -> None:
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO kill_switch_events "
                    "(trigger, account, snapshot, action_taken) VALUES (%s,%s,%s::jsonb,%s)",
                    (trigger, snapshot.get("account"), json.dumps(snapshot, default=str), action),
                )
    except Exception as exc:
        logger.critical(f"Kill switch | event persistence failed: {exc}")


def _set_all_paused(reason: str) -> list[str]:
    """Pause every bot. Returns the bots that could NOT be paused; a failure
    never stops the other bots being paused or the orders being cancelled."""
    from core.bot_state import set_paused
    failed = []
    for bot_id in ACTIVE_BOTS:
        try:
            set_paused(bot_id, True, reason=reason)
        except Exception as exc:
            failed.append(bot_id)
            logger.critical(f"Kill switch | FAILED to pause {bot_id}: {exc}")
    return failed


def _cancel_non_protective(snapshot: dict[str, Any]) -> int:
    cancelled = 0
    for account in snapshot.get("accounts", []):
        client = account.get("_client")
        if client is None:
            continue
        for order in account.get("orders", []):
            if _is_protective(order):
                continue
            try:
                client.cancel_order_by_id(str(order["id"]))
                cancelled += 1
            except Exception as exc:
                logger.critical(f"Kill switch | failed cancelling pending order {order.get('id')}: {exc}")
    return cancelled


# A broker/ledger mismatch is about ONE account's records, so it pauses that
# bot only and does not latch the fleet (Markus, 7 Nov 2026: a Forex records
# slip had frozen all four bots for four days). Everything else stays fleet-wide.
BOT_SCOPED_TRIGGERS = frozenset({"broker_ledger_mismatch"})


def _bot_scoped(trigger: dict[str, Any]) -> bool:
    return trigger.get("trigger") in BOT_SCOPED_TRIGGERS and trigger.get("bot_id") in ACTIVE_BOTS


def _pause_bots(bots: list[str], triggers: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Pause only the named bots and cancel only their non-stop orders. No latch."""
    from core.bot_state import set_paused
    failed = []
    for bot_id in bots:
        try:
            set_paused(bot_id, True, reason="broker_ledger_mismatch")
        except Exception as exc:
            failed.append(bot_id)
            logger.critical(f"Kill switch | FAILED to pause {bot_id}: {exc}")
    scoped = {**snapshot, "accounts": [a for a in snapshot.get("accounts", []) if a.get("bot_id") in bots]}
    cancelled = _cancel_non_protective(scoped)
    action = f"paused_bots={','.join(bots)};cancelled_non_protective={cancelled};protective_stops_preserved"
    if failed:
        action += f";PAUSE_FAILED={','.join(failed)}"
    for trigger in triggers:
        logger.critical(f"KILL SWITCH (one bot) | {trigger}")
        try:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="kill_switch", severity="critical", error_type="bot_paused_ledger_mismatch",
                message=f"Paused {trigger.get('bot_id')}: broker and ledger disagree"[:300],
                detail=json.dumps({**trigger, "action": action}, default=str)[:2000],
                bot_id=str(trigger.get("bot_id")))
        except Exception as exc:
            logger.critical(f"Kill switch | degradation record failed: {type(exc).__name__}")
        try:
            from notifications.condition_alerts import alert_condition
            alert_condition(
                source="kill_switch", condition="broker_ledger_mismatch", bot_id=str(trigger.get("bot_id")),
                title=f"Bot paused: {trigger.get('bot_id')} broker/ledger mismatch",
                description=("Only this bot was paused; the other bots keep running. "
                             f"Evidence: {json.dumps(trigger, default=str, sort_keys=True)}"),
                fields=[{"name": "Action", "value": action, "inline": False}])
        except Exception as exc:
            logger.critical(f"Kill switch | alert dispatch failed: {type(exc).__name__}")
    return {"tripped": False, "paused_bots": bots, "triggers": triggers, "cancelled": cancelled, "action": action}


def trip(triggers: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Latch the switch, pause all bots, and cancel only non-stop orders.
    If every trigger is a single bot's broker/ledger mismatch, pause just those bots."""
    if triggers and all(_bot_scoped(t) for t in triggers):
        return _pause_bots(sorted({str(t["bot_id"]) for t in triggers}), triggers, snapshot)
    _state["tripped"] = True
    reason = "; ".join(str(t.get("trigger")) for t in triggers)
    pause_failed = _set_all_paused(reason)
    cancelled = _cancel_non_protective(snapshot)
    action = f"paused_all_bots;cancelled_non_protective={cancelled};protective_stops_preserved"
    if pause_failed:
        action += f";PAUSE_FAILED={','.join(pause_failed)}"
    for trigger in triggers:
        logger.critical(f"KILL SWITCH TRIGGERED | {trigger}")
        _write_event(str(trigger.get("trigger")), snapshot, action)
        try:
            from notifications.condition_alerts import alert_condition

            bot_id = trigger.get("bot_id")
            alert_condition(
                source="kill_switch",
                condition=str(trigger.get("trigger") or "unknown"),
                bot_id=str(bot_id) if bot_id else None,
                title=f"Kill switch triggered: {trigger.get('trigger', 'unknown')}",
                description=(
                    "The kill switch latched and paused all bots. "
                    f"Trigger evidence: {json.dumps(trigger, default=str, sort_keys=True)}"
                ),
                fields=[
                    {
                        "name": "Action",
                        "value": action,
                        "inline": False,
                    }
                ],
            )
        except Exception as exc:
            logger.critical(
                f"Kill switch | alert dispatch failed: {type(exc).__name__}"
            )
    return {"tripped": True, "triggers": triggers, "cancelled": cancelled, "action": action}


def reset(opening_equity: float | None = None, confirmation_token: str | None = None) -> None:
    was_tripped = bool(_state["tripped"])
    if was_tripped:
        expected_confirmation = os.getenv(RESET_CONFIRMATION_ENV_VAR, "").strip()
        if not expected_confirmation:
            raise ValueError("Kill-switch reset confirmation is not configured.")
        if not confirmation_token or not hmac.compare_digest(confirmation_token, expected_confirmation):
            raise ValueError("Invalid kill-switch reset confirmation.")
        # Persist the reset before clearing memory. If it cannot be written the
        # switch stays tripped; otherwise a restart would re-latch it silently.
        _write_reset_event()
    _state["tripped"] = False
    _state["last_snapshot"] = {}
    _state["missing_stop_since"] = {}
    _state["mismatch_counts"] = {}
    logger.warning("Kill switch manually reset after explicit confirmation")


def _write_reset_event() -> None:
    from db.postgres import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kill_switch_events (trigger, account, snapshot, action_taken) "
                "VALUES (%s, NULL, '{}'::jsonb, %s)",
                (RESET_EVENT_TRIGGER, "reset_with_confirmation"),
            )


def latch_tripped() -> bool:
    """Read the persisted latch (any process may call this). Tripped when the
    newest kill_switch_events row is not a reset; unreadable = tripped."""
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT trigger FROM kill_switch_events "
                    "ORDER BY event_ts DESC, id DESC LIMIT 1"
                )
                row = cur.fetchone()
        return row is not None and str(row[0]) != RESET_EVENT_TRIGGER
    except Exception as exc:
        logger.critical(f"Kill switch | latch unreadable, treating as TRIPPED: {exc}")
        return True


def restore_latch() -> bool:
    """Re-apply a trip that survived a restart. Call once at startup.
    Fails closed: an unreadable latch counts as tripped, and bots cannot be
    resumed until someone resets it with the confirmation token."""
    tripped = latch_tripped()
    if tripped:
        _state["tripped"] = True
        logger.critical("Kill switch | latched from a previous run; reset with the confirmation token to clear")
    return tripped


def is_tripped() -> bool:
    return bool(_state["tripped"])


def manual_trip(reason: str = "manual_emergency") -> dict[str, Any]:
    """Emergency stop from the dashboard/API.

    Pauses every bot FIRST (fastest protection), then reads the brokers so
    pending non-protective orders can be cancelled. Without that read the
    trip would pause bots but leave pending entry orders live. Protective
    stops are never cancelled. If the broker read fails, bots stay paused and
    the failure is logged critically.
    """
    _set_all_paused(reason)
    snapshot: dict[str, Any] = {"reason": reason}
    try:
        from execution.reconciliation import collect_live_snapshot

        snapshot = {**collect_live_snapshot(), "reason": reason}
    except Exception as exc:
        logger.critical(
            f"Kill switch | manual trip could not read brokers; bots paused but "
            f"pending orders NOT cancelled: {exc}"
        )
    return trip([{"trigger": "manual", "detail": reason}], snapshot)


def get_state() -> dict[str, Any]:
    return {
        "tripped": bool(_state["tripped"]),
        "missing_stop_seconds": MISSING_STOP_SECONDS,
        "last_snapshot": _state.get("last_snapshot", {}),
    }


def acknowledge(
    condition_key: str,
    until: str,
    acknowledged_by: str = "manual",
    reason: str | None = None,
) -> dict[str, Any]:
    """Record an explicit, expiring acknowledgement for a known condition."""
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO kill_switch_acknowledgements "
                    "(condition_key, acknowledged_until, acknowledged_by, reason) "
                    "VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (condition_key) DO UPDATE SET "
                    "acknowledged_until=EXCLUDED.acknowledged_until, "
                    "acknowledged_by=EXCLUDED.acknowledged_by, "
                    "reason=EXCLUDED.reason, acknowledged_at=NOW()",
                    (condition_key, until, acknowledged_by, reason),
                )
        return {
            "condition_key": condition_key,
            "acknowledged_until": until,
            "acknowledged_by": acknowledged_by,
            "reason": reason,
        }
    except Exception as exc:
        raise RuntimeError(f"Could not save acknowledgement: {exc}") from exc


def report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Evaluate without pausing, cancelling, or persisting a trip."""
    triggers = evaluate_snapshot(snapshot)
    public_snapshot = {
        key: [
            {k: v for k, v in item.items() if k != "_client"}
            for item in value
        ] if key == "accounts" else value
        for key, value in snapshot.items()
    }
    result = {"mode": "report_only", "would_trip": bool(triggers), "triggers": triggers, "snapshot": public_snapshot}
    _state["last_snapshot"] = result
    logger.warning(f"Kill switch report-only | would_trip={bool(triggers)} triggers={len(triggers)}")
    if triggers:
        # Durable evidence for the arming decision: how often, and why, the
        # unarmed switch would have tripped. De-duplicated by the tracker.
        try:
            from core.degradation_tracker import record_degradation
            kinds = sorted({str(t.get("kind", t.get("trigger", "unknown"))) for t in triggers})
            record_degradation(
                component="kill_switch", severity="warning", error_type="would_trip",
                message=f"Kill switch (report-only) would trip: {', '.join(kinds)}"[:300],
                detail=json.dumps(triggers, default=str)[:2000],
            )
        except Exception as exc:
            logger.error(f"Kill switch | would-trip record failed: {type(exc).__name__}")
    for trigger in triggers:
        logger.warning(
            "Kill switch report-only trigger | "
            f"bot={trigger.get('bot_id', 'unknown')} "
            f"symbol={trigger.get('symbol', 'unknown')} "
            f"kind={trigger.get('kind', trigger.get('trigger', 'unknown'))} "
            f"detail={trigger.get('detail', '')}"
        )
    return result


def check(current_equity: float | None = None) -> bool:
    """Compatibility check used by existing pipeline guards; never liquidates."""
    if _state["tripped"]:
        return True
    return False


def run_report_only() -> dict[str, Any]:
    """Run a safe live-state report using broker reads only."""
    from execution.reconciliation import collect_live_snapshot
    return report(collect_live_snapshot())