"""
jerome_alpaca.py — Alpaca execution engine for Jerome commodity bot.
Uses Jerome's dedicated paper trading account (separate from other bots).
"""
from __future__ import annotations
import logging
from datetime import datetime, time as dtime, timezone
from typing import Optional

import pytz

logger = logging.getLogger("jerome.alpaca")


def _nyse_is_open(now_utc: datetime | None = None) -> bool:
    """Return True if NYSE regular session is currently open (9:30–16:00 ET, Mon–Fri)."""
    now = now_utc or datetime.now(pytz.UTC)
    et = now.astimezone(pytz.timezone("America/New_York"))
    if et.weekday() >= 5:
        return False
    return dtime(9, 30) <= et.time() < dtime(16, 0)


class JeromeAlpaca:
    """Handles all Alpaca interactions for Jerome's commodity account."""

    def __init__(self, api_key: str, secret_key: str,
                 base_url: str = "https://paper-api.alpaca.markets"):
        import alpaca_trade_api as tradeapi
        self.api = tradeapi.REST(api_key, secret_key, base_url=base_url)
        logger.info("JeromeAlpaca | Connected to Alpaca paper account")

    def get_account(self) -> dict:
        acc = self.api.get_account()
        return {
            "equity":       float(acc.equity),
            "cash":         float(acc.cash),
            "buying_power": float(acc.buying_power),
        }

    def get_open_positions(self) -> list[dict]:
        positions = self.api.list_positions()
        result = []
        for p in positions:
            entry   = float(p.avg_entry_price)
            current = float(p.current_price)
            side    = p.side
            unrealised_pct = (
                (current - entry) / entry * 100
                if side == "long"
                else (entry - current) / entry * 100
            )
            result.append({
                "symbol":             p.symbol,
                "direction":          side,
                "qty":                float(p.qty),
                "entry_price":        entry,
                "current_price":      current,
                "unrealised_pnl_usd": float(p.unrealized_pl),
                "unrealised_pct":     round(unrealised_pct, 3),
                "market_value":       float(p.market_value),
            })
        return result

    def place_order(
        self,
        symbol: str,
        side: str,
        notional: float,
    ) -> Optional[dict]:
        """Place a fractional notional market order.
        Uses time_in_force="day" when NYSE is open; "opg" (at-the-open) when closed
        so off-hours orders queue for next open instead of being rejected.
        """
        # Translate strategy-layer side ("long"/"short") to Alpaca side ("buy"/"sell").
        # Jerome's LLM returns long/short. Alpaca REST requires buy/sell.
        _side_map = {"long": "buy", "short": "sell", "buy": "buy", "sell": "sell"}
        alpaca_side = _side_map.get(side.lower().strip())
        if alpaca_side is None:
            logger.error(f"JeromeAlpaca | Unknown side '{side}' — cannot translate")
            return None
        # Fractional/notional orders only support time_in_force="day" on Alpaca.
        # Off-hours "day" orders queue until next market open automatically.
        tif = "day"
        logger.info(f"JeromeAlpaca | Submitting {alpaca_side.upper()} {symbol} notional=${notional:,.2f} tif={tif}")
        try:
            from core.order_ids import submit_with_unique_client_order_id
            order, client_order_id = submit_with_unique_client_order_id(
                lambda generated_id: self.api.submit_order(
                    symbol=symbol,
                    notional=round(notional, 2),
                    side=alpaca_side,
                    type="market",
                    time_in_force=tif,
                    client_order_id=generated_id,
                ),
                f"jerome-entry-{symbol}",
                lookup=lambda client_order_id: self.api.get_order_by_client_order_id(client_order_id),
            )
            logger.info(
                f"JeromeAlpaca | ORDER PLACED: {side.upper()} {symbol} "
                f"notional=${notional:,.2f} order_id={order.id} "
                f"client_order_id={client_order_id}"
            )
            return {"order_id": order.id, "symbol": symbol,
                    "side": side, "notional": notional,
                    "client_order_id": client_order_id}
        except Exception as exc:
            logger.error(f"JeromeAlpaca | Order failed {side} {symbol}: {exc}")
            return None

    def close_position(self, symbol: str) -> bool:
        """Close entire position with an explicitly tagged market order."""
        try:
            from core.order_ids import submit_with_unique_client_order_id
            position = self.api.get_position(symbol)
            position_side = str(getattr(position, "side", "long")).lower()
            close_side = "buy" if "short" in position_side else "sell"
            qty = abs(float(position.qty))
            _, client_order_id = submit_with_unique_client_order_id(
                lambda generated_id: self.api.submit_order(
                    symbol=symbol,
                    qty=round(qty, 8),
                    side=close_side,
                    type="market",
                    time_in_force="day",
                    client_order_id=generated_id,
                ),
                f"jerome-exit-{symbol}",
                lookup=lambda client_order_id: self.api.get_order_by_client_order_id(client_order_id),
            )
            logger.info(
                f"JeromeAlpaca | CLOSED position: {symbol} "
                f"client_order_id={client_order_id}"
            )
            return True
        except Exception as exc:
            logger.error(f"JeromeAlpaca | Close failed {symbol}: {exc}")
            return False

    def get_orders(
        self,
        symbol: str,
        side: str = "sell",
        status: str = "filled",
        limit: int = 20,
    ) -> list[dict]:
        """Return orders for a symbol filtered by side and status."""
        try:
            orders = self.api.list_orders(
                status=status,
                side=side,
                limit=limit,
                direction="desc",
            )
            return [
                {
                    "id":               o.id,
                    "symbol":           o.symbol,
                    "side":             o.side,
                    "status":           o.status,
                    "filled_avg_price": getattr(o, "filled_avg_price", None),
                    "filled_qty":       getattr(o, "filled_qty", None),
                    "filled_at":        str(getattr(o, "filled_at", "") or ""),
                    "submitted_at":     str(getattr(o, "submitted_at", "") or ""),
                }
                for o in orders
                if o.symbol == symbol
            ]
        except Exception as exc:
            logger.warning(f"JeromeAlpaca | get_orders({symbol}, {side}): {exc}")
            return []

    def is_market_open(self) -> bool:
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception as exc:
            logger.warning(f"JeromeAlpaca | Clock check failed: {exc} — assuming closed")
            return False
