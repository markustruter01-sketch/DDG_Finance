"""Fail-safe publisher for database-backed fleet-equity snapshots."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from routes.fleet_equity import ACTIVE_BOT_IDS, _fetch_fleet_equity


_DETAIL_ALPACA_BOT_IDS = ("oracle", "spy_qqq_trend", "jerome_macro")
_DETAIL_LEDGER_TABLES = {
    "oracle": ("alpaca_etf_positions",),
    "spy_qqq_trend": ("bot2_momentum_positions", "bot2_spy_qqq"),
    "jerome_macro": ("bot3_positions",),
}
_DETAIL_INSTRUMENTS = {
    "oracle": [
        "SPY", "QQQ", "EWY", "EWT", "INDA", "EWJ", "EWM", "VNM",
        "EWZ", "EWW", "ECH", "EEM", "EZA", "EPOL", "GREK", "TUR",
    ],
    # Bot 2's runner screens a dynamic equity universe; this token identifies
    # that screen while the fixed sleeve and cash-park instruments stay explicit.
    "spy_qqq_trend": [
        "SCREENED_EQUITIES",
        "SPY",
        "SGOV",
    ],
    "jerome_macro": ["BTC/USD", "ETH/USD", "GLD", "SLV"],
    # Forex AI is paused and has no executable trading universe.
    "forex_ai": [],
}
_DETAIL_BROKER_TIMEOUT_SECONDS = 10.0


class _ModeUnavailable(RuntimeError):
    """The portfolio mode cannot be determined from the database."""


def _as_iso_timestamp(value: Any, field: str, *, default_now: bool = False) -> str | None:
    if value is None:
        if default_now:
            return datetime.now(timezone.utc).isoformat()
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} is not an ISO timestamp") from exc
    else:
        raise ValueError(f"{field} is not an ISO timestamp")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} is not finite")
    return number


def _portfolio_mode(bot_ids: list[str]) -> str:
    try:
        from db.postgres import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bot_id, is_live_broker
                    FROM bot_portfolio
                    WHERE bot_id = ANY(%s)
                    """,
                    (bot_ids,),
                )
                rows = cur.fetchall()
    except Exception:
        raise _ModeUnavailable from None

    if not rows:
        raise _ModeUnavailable

    live_by_bot: dict[str, bool] = {}
    for bot_id, is_live_broker in rows:
        if not isinstance(bot_id, str) or type(is_live_broker) is not bool:
            raise _ModeUnavailable
        live_by_bot[bot_id] = is_live_broker

    if set(live_by_bot) != set(bot_ids):
        raise _ModeUnavailable

    live_flags = list(live_by_bot.values())
    if all(live_flags):
        return "live"
    if not any(live_flags):
        return "paper"
    return "mixed"


def build_payload() -> dict[str, Any]:
    """Build the receiver's exact payload from the existing fleet calculation."""
    result = _fetch_fleet_equity()
    bot_ids = sorted(ACTIVE_BOT_IDS)
    if not bot_ids or len(bot_ids) > 20:
        raise ValueError("fleet bot count is outside the receiver limit")

    bots: list[dict[str, Any]] = []
    for bot_id in bot_ids:
        row = result.get(bot_id)
        if not isinstance(row, dict):
            raise ValueError("fleet-equity result is missing a bot")

        required_fields = (
            "equity",
            "starting",
            "cash",
            "pnl",
            "positions",
            "last_updated",
            "stale",
            "paused",
        )
        if any(field not in row for field in required_fields):
            raise ValueError("fleet-equity result is missing a required bot field")

        open_positions = row["positions"]
        if (
            isinstance(open_positions, bool)
            or not isinstance(open_positions, int)
            or open_positions < 0
        ):
            raise ValueError("open_positions is not a non-negative integer")
        if not isinstance(row["stale"], bool) or not isinstance(row["paused"], bool):
            raise ValueError("stale and paused must be booleans")

        cash_usd = (
            None
            if row["cash"] is None
            else _finite_number(row["cash"], "cash_usd")
        )
        bots.append(
            {
                "bot_id": bot_id,
                "equity_usd": _finite_number(row["equity"], "equity_usd"),
                "starting_usd": _finite_number(row["starting"], "starting_usd"),
                "cash_usd": cash_usd,
                "pnl_usd": _finite_number(row["pnl"], "pnl_usd"),
                "open_positions": open_positions,
                "last_updated": _as_iso_timestamp(
                    row["last_updated"], "last_updated"
                ),
                "stale": row["stale"],
                "paused": row["paused"],
            }
        )

    errors = result.get("errors")
    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
        raise ValueError("fleet-equity result has invalid errors")

    return {
        "generated_at": _as_iso_timestamp(
            result.get("generated_at"), "generated_at", default_now=True
        ),
        "mode": _portfolio_mode(bot_ids),
        "bots": bots,
        "errors": [error[:300] for error in errors[:20]],
    }


def _set_alpaca_read_timeout(client: Any) -> None:
    """Apply a 10-second timeout to the SDK's HTTP requests for this client."""
    session = getattr(client, "_session", None)
    request = getattr(session, "request", None)
    if not callable(request):
        raise RuntimeError("Alpaca client has no request session")

    def request_with_timeout(method: str, url: str, *args: Any, **kwargs: Any):
        kwargs["timeout"] = _DETAIL_BROKER_TIMEOUT_SECONDS
        return request(method, url, *args, **kwargs)

    session.request = request_with_timeout
    # The SDK retries rate-limit responses; disabling retries here keeps each
    # read bounded to one HTTP request while leaving other client behavior alone.
    if hasattr(client, "_retry"):
        client._retry = 0


def _fresh_read_client(bot_id: str) -> Any:
    """Create a dedicated paper client for this snapshot's read-only calls."""
    from alpaca.trading.client import TradingClient
    from core.bot_registry import resolve_bot_id
    from core.kill_switch import ACCOUNT_ENV

    canonical_bot_id = resolve_bot_id(bot_id)
    credentials = ACCOUNT_ENV.get(canonical_bot_id)
    if credentials is None:
        raise RuntimeError(f"missing credentials for {canonical_bot_id}")
    key_name, secret_name = credentials
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"missing credentials for {canonical_bot_id}")
    return TradingClient(key, secret, paper=True)


def _optional_ledger_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} is not finite")
    return number


def _flag_text(flag: Any) -> str:
    if isinstance(flag, str):
        return flag[:300]
    return json.dumps(flag, sort_keys=True, default=str, separators=(",", ":"))[:300]


def build_detail() -> dict[str, Any]:
    """Build optional broker-backed detail using read-only DB and Alpaca reads."""
    from core.bot_registry import BOT_REGISTRY
    from core.cash_park import CASH_PARK_SYMBOLS
    from core.degradation_resolver import _latest_reconciliation
    from core.kill_switch import _covers
    from core.runner_heartbeat import get_runner_status
    from core.symbols import canonical_symbol
    from execution.per_bot_vault import VAULT_BIL_SYMBOL, VAULT_VOO_SYMBOL
    from execution.reconciliation import _orders, _positions
    from db.postgres import get_conn

    bot_ids = sorted(ACTIVE_BOT_IDS)
    if not bot_ids or len(bot_ids) > 20:
        raise ValueError("fleet bot count is outside the detail limit")

    bot_modes: dict[str, str] = {}
    ledgers: dict[str, dict[str, dict[str, float | None]]] = {
        bot_id: {} for bot_id in _DETAIL_ALPACA_BOT_IDS
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bot_id, is_live_broker
                FROM bot_portfolio
                WHERE bot_id = ANY(%s)
                """,
                (bot_ids,),
            )
            for bot_id, is_live_broker in cur.fetchall():
                if bot_id not in bot_ids or type(is_live_broker) is not bool:
                    raise ValueError("portfolio broker mode is invalid")
                bot_modes[bot_id] = "live" if is_live_broker else "paper"

            if set(bot_modes) != set(bot_ids):
                raise ValueError("portfolio broker mode is unavailable")

            for bot_id, (table, *aliases) in _DETAIL_LEDGER_TABLES.items():
                ledger_ids = [bot_id, *aliases]
                if bot_id == "oracle":
                    ledger_ids.extend(
                        alias
                        for alias in BOT_REGISTRY[bot_id].legacy_aliases
                        if alias not in ledger_ids
                    )
                cur.execute(
                    f"""
                    SELECT symbol, entry_price, stop_price
                    FROM {table}
                    WHERE status = 'open'
                      AND bot_id = ANY(%s)
                    ORDER BY opened_at DESC NULLS LAST
                    """,
                    (ledger_ids,),
                )
                for symbol, entry_price, stop_price in cur.fetchall():
                    key = canonical_symbol(symbol)
                    ledgers[bot_id].setdefault(
                        key,
                        {
                            "entry_price": _optional_ledger_number(
                                entry_price, "entry_price"
                            ),
                            "stop_price": _optional_ledger_number(
                                stop_price, "stop_price"
                            ),
                        },
                    )

            cur.execute(
                """
                SELECT ts AT TIME ZONE 'UTC', component, severity,
                       message, bot_id, resolved_at
                FROM system_degradations
                WHERE ts >= NOW() - INTERVAL '48 hours'
                ORDER BY ts DESC
                LIMIT 50
                """
            )
            incidents = [
                {
                    "ts": _as_iso_timestamp(row[0], "incident.ts"),
                    "component": row[1],
                    "severity": row[2],
                    "message": str(row[3] or "")[:300],
                    "bot_id": row[4],
                    "resolved": row[5] is not None,
                }
                for row in cur.fetchall()
            ]
            reconciliation_row = _latest_reconciliation(conn)

    reconciliation = None
    if reconciliation_row is not None:
        raw_flags = reconciliation_row.get("flags") or []
        if not isinstance(raw_flags, list):
            raise ValueError("reconciliation flags are invalid")
        clean = reconciliation_row.get("clean")
        if type(clean) is not bool:
            raise ValueError("reconciliation clean flag is invalid")
        reconciliation = {
            "last_run": _as_iso_timestamp(
                reconciliation_row.get("run_ts"), "reconciliation.last_run"
            ),
            "clean": clean,
            "flags": [_flag_text(flag) for flag in raw_flags[:50]],
        }

    runner_read = get_runner_status()
    runner_row = runner_read.get("row")
    runner = None
    if runner_row:
        runner = {
            "status": runner_read.get("verdict"),
            "last_heartbeat": _as_iso_timestamp(
                runner_row.get("last_beat_at"), "runner.last_heartbeat"
            ),
        }

    positions: list[dict[str, Any]] = []
    special_symbols = {
        canonical_symbol(symbol)
        for symbol in (
            VAULT_BIL_SYMBOL,
            VAULT_VOO_SYMBOL,
            *CASH_PARK_SYMBOLS,
        )
    }
    for bot_id in _DETAIL_ALPACA_BOT_IDS:
        client = _fresh_read_client(bot_id)
        _set_alpaca_read_timeout(client)
        broker_positions = _positions(client)
        open_orders = _orders(client)
        for position in broker_positions:
            symbol = str(position["symbol"])
            symbol_key = canonical_symbol(symbol)
            ledger = ledgers[bot_id].get(symbol_key, {})
            if symbol_key in special_symbols:
                has_broker_stop: bool | None = None
            else:
                has_broker_stop = any(
                    str(order.get("side", "")).lower() == "sell"
                    and str(order.get("type", "")).lower().replace("-", "_")
                    in {"stop", "stop_limit"}
                    and _covers(position, order)
                    for order in open_orders
                )
            positions.append(
                {
                    "bot_id": bot_id,
                    "symbol": symbol,
                    "qty": _finite_number(position["qty"], "position.qty"),
                    "entry_price": ledger.get("entry_price"),
                    "stop_price": ledger.get("stop_price"),
                    "has_broker_stop": has_broker_stop,
                    "source": "broker",
                }
            )

    bots_meta: list[dict[str, Any]] = []
    for bot_id in bot_ids:
        entry = BOT_REGISTRY.get(bot_id)
        if entry is None:
            raise ValueError(f"bot registry entry is missing for {bot_id}")
        if entry.exchange not in {"alpaca", "oanda"}:
            raise ValueError(f"unsupported broker for {bot_id}")
        instruments = _DETAIL_INSTRUMENTS.get(bot_id)
        if instruments is None or len(instruments) > 60:
            raise ValueError(f"strategy instruments unavailable for {bot_id}")
        bots_meta.append(
            {
                "bot_id": bot_id,
                "strategy": entry.short_name[:100],
                "broker": entry.exchange,
                "account_mode": bot_modes[bot_id],
                "registry_status": entry.status,
                "instruments": list(instruments),
            }
        )
    positions.sort(key=lambda position: (position["bot_id"], position["symbol"]))
    return {
        "bots_meta": bots_meta,
        "positions": positions[:200],
        "incidents": incidents,
        "kill_switch": None,
        "reconciliation": reconciliation,
        "runner": runner,
        "version": None,
    }


def _fit_detail_limits(detail: dict[str, Any]) -> dict[str, Any]:
    """Copy and truncate optional detail to the receiver's field and list limits."""
    if not isinstance(detail, dict):
        raise ValueError("detail payload must be an object")

    string_limits = {
        "instruments": 20,
        "strategy": 100,
        "registry_status": 20,
        "component": 60,
        "severity": 20,
        "message": 300,
        "flags": 300,
        "status": 30,
        "bot_id": 64,
        "symbol": 20,
    }
    list_limits = {
        "bots_meta": 20,
        "instruments": 60,
        "positions": 200,
        "incidents": 50,
        "flags": 50,
        "triggers": 50,
    }

    def fit_value(value: Any, field: str | None = None) -> Any:
        if isinstance(value, str):
            return value[: string_limits.get(field, 300)]
        if isinstance(value, list):
            limit = list_limits.get(field)
            items = value if limit is None else value[:limit]
            return [fit_value(item, field) for item in items]
        if isinstance(value, dict):
            return {
                key: fit_value(item, key if isinstance(key, str) else None)
                for key, item in value.items()
            }
        return value

    return fit_value(detail)


def push_fleet_snapshot() -> None:
    """Send one snapshot when enabled; never let a push failure escape."""
    key = ""
    try:
        if os.environ.get("FLEET_PUSH_ENABLED") != "true":
            return

        url = os.environ.get("DDG_FLEET_PUSH_URL")
        key = os.environ.get("FLEET_INBOUND_KEY")
        if not url or not key:
            raise RuntimeError("push configuration unavailable")

        payload = build_payload()
        try:
            payload["detail"] = _fit_detail_limits(build_detail())
        except Exception as exc:
            logger.warning(f"ddg-push detail-skipped {type(exc).__name__}")
        detail_included = "detail" in payload
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0,
        )
        status = response.status_code
        if 400 <= status < 500 and detail_included:
            error_text = ""
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("error") is not None:
                    error_text = str(body["error"])
            except Exception:
                pass
            if key and key in error_text:
                error_text = error_text.replace(key, "[REDACTED]")
            error_text = error_text[:200]
            reason = f" {error_text}" if error_text else ""
            logger.warning(f"ddg-push detail-rejected {status}{reason}")

            payload_without_detail = dict(payload)
            payload_without_detail.pop("detail", None)
            response = httpx.post(
                url,
                json=payload_without_detail,
                headers={"Authorization": f"Bearer {key}"},
                timeout=10.0,
            )
            status = response.status_code
            if 200 <= status < 300:
                logger.info(f"ddg-push ok {status} (without detail)")
            else:
                error_text = ""
                try:
                    body = response.json()
                    if isinstance(body, dict) and body.get("error") is not None:
                        error_text = str(body["error"])
                except Exception:
                    pass
                if key and key in error_text:
                    error_text = error_text.replace(key, "[REDACTED]")
                error_text = error_text[:200]
                reason = f" {error_text}" if error_text else ""
                logger.error(f"ddg-push failed {status}{reason}")
            return

        if not 200 <= status < 300:
            error_text = ""
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("error") is not None:
                    error_text = str(body["error"])
            except Exception:
                pass
            if key and key in error_text:
                error_text = error_text.replace(key, "[REDACTED]")
            error_text = error_text[:200]
            reason = f" {error_text}" if error_text else ""
            logger.error(f"ddg-push failed {status}{reason}")
            return

        logger.info(f"ddg-push ok {status}")
    except _ModeUnavailable:
        logger.error("ddg-push failed _ModeUnavailable mode-unavailable")
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        error_text = ""
        if response is not None:
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("error") is not None:
                    error_text = str(body["error"])
            except Exception:
                pass
        if not error_text:
            error_text = str(exc)
        if key and key in error_text:
            error_text = error_text.replace(key, "[REDACTED]")
        error_text = error_text[:200]
        reason = f" {error_text}" if error_text else ""
        failure = status if status is not None else type(exc).__name__
        logger.error(f"ddg-push failed {failure}{reason}")
