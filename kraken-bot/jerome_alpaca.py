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
        tif = "day" if _nyse_is_open() else "opg"
        logger.info(f"JeromeAlpaca | Submitting {side.upper()} {symbol} notional=${notional:,.2f} tif={tif}")
        try:
            order = self.api.submit_order(
                symbol=symbol,
                notional=round(notional, 2),
                side=side,
                type="market",
                time_in_force=tif,
            )
            logger.info(
                f"JeromeAlpaca | ORDER PLACED: {side.upper()} {symbol} "
                f"notional=${notional:,.2f} order_id={order.id}"
            )
            return {"order_id": order.id, "symbol": symbol,
                    "side": side, "notional": notional}
        except Exception as exc:
            logger.error(f"JeromeAlpaca | Order failed {side} {symbol}: {exc}")
            return None

    def close_position(self, symbol: str) -> bool:
        """Close entire position in a symbol."""
        try:
            self.api.close_position(symbol)
            logger.info(f"JeromeAlpaca | CLOSED position: {symbol}")
            return True
        except Exception as exc:
            logger.error(f"JeromeAlpaca | Close failed {symbol}: {exc}")
            return False

    def is_market_open(self) -> bool:
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception as exc:
            logger.warning(f"JeromeAlpaca | Clock check failed: {exc} — assuming closed")
            return False
