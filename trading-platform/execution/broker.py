"""
Alpaca Broker — Order Execution Layer
---------------------------------------
Wraps the Alpaca Trading API for all order operations used by this platform:

  - place_order():        Submit a fractional market buy order for a slot
  - close_position():     Liquidate an entire position immediately
  - get_account():        Return account equity, cash, buying power
  - get_positions():      Return all current open positions
  - get_open_orders():    Return all pending orders
  - cancel_all_orders():  Cancel every open order (used by kill switch)
  - close_all_positions():Liquidate everything (used by kill switch)
  - get_order():          Fetch a single order by ID

All functions raise on Alpaca API errors — callers must handle exceptions.
Paper trading only — paper=True is hardcoded.
"""

from decimal import Decimal

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.models import Order, Position, TradeAccount
from loguru import logger

from config.settings import settings


def _client() -> TradingClient:
    return TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        paper=True,
    )


def get_account() -> dict:
    """
    Return a simplified dict of account metrics.

    Returns:
        {equity, cash, buying_power, trading_blocked, pattern_day_trader}
    """
    acct: TradeAccount = _client().get_account()
    return {
        "equity":             float(acct.equity),
        "cash":               float(acct.cash),
        "buying_power":       float(acct.buying_power),
        "trading_blocked":    acct.trading_blocked,
        "pattern_day_trader": acct.pattern_day_trader,
    }


def get_positions() -> list[dict]:
    """
    Return all open positions as simplified dicts.
    """
    positions: list[Position] = _client().get_all_positions()
    return [
        {
            "symbol":          p.symbol,
            "qty":             float(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "market_value":    float(p.market_value),
            "unrealized_pl":   float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
            "current_price":   float(p.current_price),
        }
        for p in positions
    ]


def get_open_orders() -> list[dict]:
    """Return all open/pending orders."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    orders = _client().get_orders(filter=req)
    return [
        {
            "id":        str(o.id),
            "symbol":    o.symbol,
            "side":      o.side.value,
            "qty":       float(o.qty) if o.qty else None,
            "notional":  float(o.notional) if o.notional else None,
            "status":    o.status.value,
            "created_at": str(o.created_at),
        }
        for o in orders
    ]


def get_order(order_id: str) -> dict:
    """Fetch a single order by its Alpaca order UUID."""
    order: Order = _client().get_order_by_id(order_id)
    return {
        "id":              str(order.id),
        "symbol":          order.symbol,
        "side":            order.side.value,
        "qty":             float(order.qty) if order.qty else None,
        "notional":        float(order.notional) if order.notional else None,
        "filled_qty":      float(order.filled_qty) if order.filled_qty else 0.0,
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "status":          order.status.value,
        "created_at":      str(order.created_at),
        "filled_at":       str(order.filled_at) if order.filled_at else None,
    }


def place_order(
    ticker: str,
    notional_usd: float,
    side: str = "buy",
) -> dict:
    """
    Place a fractional market order by notional dollar amount.

    Args:
        ticker:       Stock/ETF symbol.
        notional_usd: Dollar amount to deploy (e.g. 1500.00).
        side:         "buy" or "sell" (default "buy").

    Returns:
        Dict with order id, symbol, notional, status.

    Raises:
        ValueError:  If notional_usd < $1.
        RuntimeError: On Alpaca API error.
    """
    if notional_usd < 1.0:
        raise ValueError(f"Cannot place order for ${notional_usd:.2f} — below $1 minimum")

    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    req = MarketOrderRequest(
        symbol=ticker,
        notional=round(notional_usd, 2),
        side=order_side,
        time_in_force=TimeInForce.DAY,
    )

    logger.info(f"Broker | Placing {side.upper()} {ticker} ${notional_usd:,.2f} (notional, market order)")

    try:
        order: Order = _client().submit_order(req)
        result = {
            "id":        str(order.id),
            "symbol":    order.symbol,
            "side":      order.side.value,
            "notional":  float(order.notional) if order.notional else notional_usd,
            "status":    order.status.value,
            "created_at": str(order.created_at),
        }
        logger.info(f"Broker | Order submitted: {result['id']} {ticker} status={result['status']}")
        return result
    except Exception as exc:
        logger.error(f"Broker | Order failed for {ticker}: {exc}")
        raise RuntimeError(f"Order placement failed for {ticker}: {exc}") from exc


def get_latest_price(ticker: str) -> float | None:
    """
    Fetch the latest trade price for a ticker from Alpaca Data API.
    Used to record intended_price before order placement for slippage tracking.
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest
        data_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        req = StockLatestTradeRequest(symbol_or_symbols=ticker)
        trades = data_client.get_stock_latest_trade(req)
        if ticker in trades:
            price = float(trades[ticker].price)
            logger.debug(f"Broker | Latest price {ticker}: ${price:.4f}")
            return price
    except Exception as exc:
        logger.warning(f"Broker | Could not fetch latest price for {ticker}: {exc}")
    return None


def close_position(ticker: str) -> dict:
    """
    Close an entire open position in a ticker.

    Args:
        ticker: Symbol to liquidate.

    Returns:
        Dict with order details from the close.
    """
    logger.warning(f"Broker | Closing position: {ticker}")
    try:
        order: Order = _client().close_position(ticker)
        return {
            "id":     str(order.id),
            "symbol": order.symbol,
            "side":   order.side.value,
            "status": order.status.value,
        }
    except Exception as exc:
        logger.error(f"Broker | Failed to close {ticker}: {exc}")
        raise RuntimeError(f"Failed to close position {ticker}: {exc}") from exc


def cancel_all_orders() -> int:
    """
    Cancel all open orders. Returns number of orders cancelled.
    Used by the kill switch.
    """
    logger.warning("Broker | Cancelling ALL open orders")
    cancelled = _client().cancel_orders()
    n = len(cancelled) if cancelled else 0
    logger.warning(f"Broker | {n} orders cancelled")
    return n


def close_all_positions() -> int:
    """
    Liquidate all open positions. Returns number of positions closed.
    Used by the kill switch.
    """
    logger.warning("Broker | Closing ALL positions (kill switch)")
    closed = _client().close_all_positions(cancel_orders=True)
    n = len(closed) if closed else 0
    logger.warning(f"Broker | {n} positions closed")
    return n
