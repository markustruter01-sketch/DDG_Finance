"""Paper-only migration guard for consolidating the three ETF accounts.

The default command is read-only inventory.  Destructive flattening requires
both ``--execute`` and the exact ``--confirm`` phrase, and refuses to run while
the market is closed.  This keeps a workflow restart from ever selling paper
positions implicitly.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest, StopOrderRequest


CONFIRMATION = "CONSOLIDATE-PAPER-ETF-ACCOUNTS"
IGNORED_SYMBOLS = {"SGOV"}
TARGET_SYMBOLS = {
    "SPY", "QQQ", "EWY", "EWT", "INDA", "EWJ", "EWM", "VNM",
    "EWZ", "EWW", "ECH", "EEM", "EZA", "EPOL", "GREK", "TUR",
}


@dataclass(frozen=True)
class AccountSpec:
    label: str
    key_env: str
    secret_env: str


ACCOUNT_SPECS = (
    AccountSpec("bot1_global", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    AccountSpec("bot2_reserved", "ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
    AccountSpec("bot3_reserved", "ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
)

LEDGER_BOTS = {
    "bot1_global": "oracle",
    "bot2_reserved": "spy_qqq_trend",
    "bot3_reserved": "jerome_macro",
}


class MigrationError(RuntimeError):
    """Raised when the migration cannot prove a safe next action."""


def _value(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


def _is_stop(order: Any) -> bool:
    return _value(getattr(order, "side", "")) == "sell" and _value(
        getattr(order, "type", "")
    ) in {"stop", "stop_limit", "trailing_stop"}


def _is_target_position(position: Any) -> bool:
    return (
        str(getattr(position, "symbol", "")) in TARGET_SYMBOLS
        and abs(float(getattr(position, "qty", 0) or 0)) > 1e-6
    )


def inventory(client: TradingClient) -> dict[str, Any]:
    """Return a serialisable broker snapshot without credentials."""
    account = client.get_account()
    positions = client.get_all_positions()
    orders = client.get_orders(
        filter=GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            nested=True,
            limit=100,
        )
    )
    return {
        "equity": round(float(account.equity), 2),
        "cash": round(float(account.cash), 2),
        "positions": [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": round(float(p.market_value or 0), 2),
            }
            for p in positions
            if _is_target_position(p) or str(p.symbol) in IGNORED_SYMBOLS
        ],
        "open_orders": [
            {
                "id": str(o.id),
                "symbol": str(o.symbol),
                "side": _value(o.side),
                "type": _value(o.type),
                "client_order_id": str(getattr(o, "client_order_id", "") or ""),
                "qty": float(o.qty),
                "stop_price": (
                    float(o.stop_price)
                    if getattr(o, "stop_price", None) is not None
                    else None
                ),
            }
            for o in orders
        ],
    }


def _wait_cancelled(client: TradingClient, order_id: str, timeout: float = 10) -> None:
    client.cancel_order_by_id(order_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _value(client.get_order_by_id(order_id).status)
        if status in {"canceled", "cancelled", "expired", "rejected"}:
            return
        time.sleep(0.25)
    raise MigrationError(f"order cancellation unconfirmed: {order_id}")


def _wait_flat(client: TradingClient, symbol: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            position = client.get_open_position(symbol)
        except Exception as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code == 404:
                return
            raise MigrationError(
                f"position lookup failed while flattening {symbol}: {exc}"
            ) from exc
        if abs(float(getattr(position, "qty", 0) or 0)) <= 1e-6:
            return
        time.sleep(1)
    raise MigrationError(f"position did not become flat: {symbol}")


def _wait_sell_filled(
    client: TradingClient,
    order_id: str,
    symbol: str,
    timeout: float = 30,
) -> Any:
    """Require a broker-confirmed filled sell before proceeding."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.get_order_by_id(order_id)
        status = _value(last.status)
        if status == "filled":
            _wait_flat(client, symbol, timeout=max(1.0, deadline - time.monotonic()))
            return last
        if status in {"canceled", "cancelled", "rejected", "expired"}:
            raise MigrationError(
                f"sell not filled for {symbol}: broker status={status}"
            )
        time.sleep(1)
    raise MigrationError(
        f"sell fill not confirmed for {symbol}: broker status="
        f"{_value(getattr(last, 'status', 'unknown'))}"
    )


def _restore_stop(
    client: TradingClient,
    symbol: str,
    qty: float,
    stop_price: float | None,
) -> None:
    """Restore coverage if an exit submission/fill cannot be confirmed."""
    if stop_price is None:
        raise MigrationError(f"cannot restore stop for {symbol}: no stop price")
    whole_qty = int(abs(qty))
    if whole_qty <= 0:
        raise MigrationError(f"cannot restore stop for {symbol}: no whole shares")
    client.submit_order(
        order_data=StopOrderRequest(
            symbol=symbol,
            qty=whole_qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=stop_price,
            client_order_id=f"etf-migration-protect-{symbol.lower()}-{uuid.uuid4().hex[:10]}",
        )
    )


def flatten_account(
    client: TradingClient,
    snapshot: dict[str, Any],
    account_label: str,
) -> None:
    """Flatten target ETF positions with stop cancellation and fill fences."""
    clock = client.get_clock()
    if not bool(clock.is_open):
        raise MigrationError("market is closed; controlled flatten deferred")

    positions = [
        position for position in snapshot["positions"]
        if position["symbol"] != "SGOV" or account_label == "bot1_global"
    ]
    positions.sort(key=lambda position: position["symbol"] == "SGOV")
    for position in positions:
        symbol = position["symbol"]
        if symbol in IGNORED_SYMBOLS and not (
            symbol == "SGOV" and account_label == "bot1_global"
        ):
            continue
        qty = abs(float(position["qty"]))
        floor_qty = math.floor(qty)
        symbol_orders = [o for o in snapshot["open_orders"] if o["symbol"] == symbol]
        stops = [o for o in symbol_orders if o["side"] == "sell" and o["type"] in {
            "stop", "stop_limit", "trailing_stop"
        }]
        covered_stops = [o for o in stops if float(o.get("qty", 0) or 0) >= floor_qty]
        if symbol != "SGOV" and not covered_stops:
            raise MigrationError(
                f"refusing naked flatten: no protective stop covering "
                f"floor(position_qty)={floor_qty} for {symbol}"
            )
        stop_price = next((o["stop_price"] for o in covered_stops if o["stop_price"]), None)
        try:
            sell = client.submit_order(
                order_data=MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=f"etf-migration-exit-{symbol.lower()}-{uuid.uuid4().hex[:12]}",
                )
            )
            sell_id = str(sell.id)
            filled = _wait_sell_filled(client, sell_id, symbol)
            print(
                json.dumps({
                    "event": "FILL_CONFIRMED",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "account": account_label,
                    "symbol": symbol,
                    "order_id": sell_id,
                    "status": _value(filled.status),
                    "filled_qty": float(filled.filled_qty),
                    "filled_avg_price": float(filled.filled_avg_price),
                }),
                flush=True,
            )
            for order in symbol_orders:
                _wait_cancelled(client, order["id"])
        except Exception:
            # The original protective stop is deliberately still live until
            # the sell is confirmed and the position is flat. If the sell
            # failed, retain it; restore only if the broker no longer reports
            # any covered protective order.
            try:
                current = client.get_open_position(symbol)
                active_orders = client.get_orders(
                    filter=GetOrdersRequest(
                        status=QueryOrderStatus.OPEN,
                        nested=True,
                        limit=100,
                    )
                )
                still_covered = any(
                    str(o.symbol) == symbol
                    and _is_stop(o)
                    and float(o.qty or 0) >= math.floor(abs(float(current.qty)))
                    for o in active_orders
                )
                if not still_covered:
                    _restore_stop(client, symbol, float(current.qty), stop_price)
                    print(
                        json.dumps({
                            "event": "PROTECTION_RESTORED",
                            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            "account": account_label,
                            "symbol": symbol,
                        }),
                        flush=True,
                    )
                else:
                    print(
                        json.dumps({
                            "event": "PROTECTION_RETAINED",
                            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            "account": account_label,
                            "symbol": symbol,
                        }),
                        flush=True,
                    )
            except Exception as restore_exc:
                raise MigrationError(
                    f"{symbol} exit failed and stop restoration check failed: {restore_exc}"
                ) from restore_exc
            raise


def _client(spec: AccountSpec) -> TradingClient:
    key = os.environ.get(spec.key_env, "")
    secret = os.environ.get(spec.secret_env, "")
    if not key or not secret:
        raise MigrationError(f"missing paper credentials for {spec.label}")
    return TradingClient(key, secret, paper=True)


def reset_active_ledgers(final_snapshots: dict[str, dict[str, Any]]) -> None:
    """Close pre-migration ETF rows and reset active portfolio positions.

    Historical scan/trade rows are retained.  Realised P&L stays NULL here
    because this safety command does not infer fills from market value; the
    migration operator can reconcile exact fill prices separately.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise MigrationError("DATABASE_URL is required for ledger reset")
    try:
        import psycopg2
    except ImportError as exc:
        raise MigrationError("psycopg2 is required for ledger reset") from exc

    symbols = list(TARGET_SYMBOLS)
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alpaca_etf_positions
                   SET status='closed',
                       closed_at=NOW(),
                       exit_reason='phase3_consolidation_flatten',
                       realised_pnl=NULL
                 WHERE status='open' AND symbol = ANY(%s)
                """,
                (symbols,),
            )
            cur.execute(
                """
                UPDATE trades
                   SET status='Closed'
                 WHERE status='Active'
                   AND ticker = ANY(%s)
                   AND asset_class IN ('momentum_etf', 'momentum_equity')
                """,
                (symbols,),
            )
            for account_label, bot_id in LEDGER_BOTS.items():
                snapshot = final_snapshots[account_label]
                cur.execute(
                    """
                    UPDATE bot_portfolio
                       SET cash_usd=%s,
                           equity_usd=%s,
                           positions='[]'::jsonb,
                           last_updated=NOW(),
                           data_source='alpaca_api',
                           is_live_broker=FALSE
                     WHERE bot_id=%s
                    """,
                    (snapshot["cash"], snapshot["equity"], bot_id),
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument(
        "--reset-ledgers",
        action="store_true",
        help="reset active ETF ledger rows after every account is verified flat",
    )
    args = parser.parse_args()
    if args.execute and args.confirm != CONFIRMATION:
        parser.error(f"--execute requires --confirm {CONFIRMATION}")
    if args.reset_ledgers and not args.execute:
        parser.error("--reset-ledgers requires --execute")

    final_snapshots: dict[str, dict[str, Any]] = {}
    for spec in ACCOUNT_SPECS:
        client = _client(spec)
        snapshot = inventory(client)
        print(json.dumps({"account": spec.label, **snapshot}, sort_keys=True))
        if args.execute:
            flatten_account(client, snapshot, spec.label)
            final = inventory(client)
            residual = [
                p for p in final["positions"] if p["symbol"] not in IGNORED_SYMBOLS
            ]
            if residual or final["open_orders"]:
                raise MigrationError(f"{spec.label} is not clean after flatten")
            final_snapshots[spec.label] = final
            print(json.dumps({"account": spec.label, "status": "flat"}))
    if args.reset_ledgers:
        reset_active_ledgers(final_snapshots)
        print(json.dumps({"status": "active_ledgers_reset"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())