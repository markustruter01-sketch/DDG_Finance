"""
Alpaca Broker — Order Execution Layer  (v2 — Rate-Limit Resilient)
-------------------------------------------------------------------
Wraps the Alpaca Trading API for all order operations.

v2 changes
----------
  • Every Alpaca SDK call is decorated with @alpaca_retry (resilience.py).
    This catches HTTP 429 Too Many Requests and retries with full-jitter
    exponential backoff (max 5 attempts, cap 60 s).
  • A singleton TradingClient is reused across calls (one TLS handshake
    per process rather than one per call).
  • Minimum call-spacing of 300 ms is enforced automatically (≈ 200
    req/min retail limit).

Supports ETF/stock (TimeInForce.DAY) and crypto spot (TimeInForce.GTC).
Crypto pairs are detected by "/" in the ticker (e.g. BTC/USD).
Paper trading only — paper=True is hardcoded.
"""

from decimal import Decimal

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
from alpaca.trading.models import Order, Position, TradeAccount
from loguru import logger

from config.settings import settings
from analysis.schemas import is_crypto_pair
from execution.resilience import alpaca_retry

# ── Singleton client ────────────────────────────────────────────────────────
_trading_client: TradingClient | None = None


def _client() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        _trading_client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,
        )
        logger.debug("Broker | TradingClient singleton created")
    return _trading_client


# ── Account + positions ────────────────────────────────────────────────────

@alpaca_retry
def get_account() -> dict:
    acct: TradeAccount = _client().get_account()
    return {
        "equity":             float(acct.equity),
        "cash":               float(acct.cash),
        "buying_power":       float(acct.buying_power),
        "trading_blocked":    acct.trading_blocked,
        "pattern_day_trader": acct.pattern_day_trader,
    }


@alpaca_retry
def get_positions() -> list[dict]:
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


@alpaca_retry
def get_open_orders() -> list[dict]:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    orders = _client().get_orders(filter=req)
    return [
        {
            "id":         str(o.id),
            "symbol":     o.symbol,
            "side":       o.side.value,
            "qty":        float(o.qty) if o.qty else None,
            "notional":   float(o.notional) if o.notional else None,
            "status":     o.status.value,
            "created_at": str(o.created_at),
        }
        for o in orders
    ]


@alpaca_retry
def get_order(order_id: str) -> dict:
    order: Order = _client().get_order_by_id(order_id)
    return {
        "id":               str(order.id),
        "symbol":           order.symbol,
        "side":             order.side.value,
        "qty":              float(order.qty) if order.qty else None,
        "notional":         float(order.notional) if order.notional else None,
        "filled_qty":       float(order.filled_qty) if order.filled_qty else 0.0,
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "status":           order.status.value,
        "created_at":       str(order.created_at),
        "filled_at":        str(order.filled_at) if order.filled_at else None,
    }


# ── Order placement ────────────────────────────────────────────────────────

@alpaca_retry
def place_order(
    ticker: str,
    notional_usd: float,
    side: str = "buy",
) -> dict:
    if notional_usd < 1.0:
        raise ValueError(f"Cannot place order for ${notional_usd:.2f} — below $1 minimum")

    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    is_crypto  = is_crypto_pair(ticker)
    tif        = TimeInForce.GTC if is_crypto else TimeInForce.DAY
    symbol     = ticker.replace("/", "") if is_crypto else ticker

    req = MarketOrderRequest(
        symbol=symbol,
        notional=round(notional_usd, 2),
        side=order_side,
        time_in_force=tif,
    )

    logger.info(
        f"Broker | Placing {side.upper()} {ticker} ${notional_usd:,.2f} "
        f"(notional, market, TIF={tif.value})"
    )

    try:
        order: Order = _client().submit_order(req)
        result = {
            "id":         str(order.id),
            "symbol":     order.symbol,
            "side":       order.side.value,
            "notional":   float(order.notional) if order.notional else notional_usd,
            "status":     order.status.value,
            "created_at": str(order.created_at),
        }
        logger.info(f"Broker | Order submitted: {result['id']} {ticker} status={result['status']}")
        return result
    except Exception as exc:
        logger.error(f"Broker | Order failed for {ticker}: {exc}")
        raise RuntimeError(f"Order placement failed for {ticker}: {exc}") from exc


@alpaca_retry
def place_stop_order(ticker: str, qty: float, stop_price: float) -> dict:
    """
    Place a GTC stop-sell order for an existing position.
    Used by the ratchet stop module.
    """
    is_crypto = is_crypto_pair(ticker)
    symbol    = ticker.replace("/", "") if is_crypto else ticker
    tif       = TimeInForce.GTC

    req = StopOrderRequest(
        symbol=symbol,
        qty=round(qty, 8),
        side=OrderSide.SELL,
        time_in_force=tif,
        stop_price=round(stop_price, 4),
    )

    logger.info(f"Broker | Stop-sell {ticker} qty={qty:.6f} stop=${stop_price:.4f} (GTC)")
    try:
        order: Order = _client().submit_order(req)
        result = {
            "id":         str(order.id),
            "symbol":     order.symbol,
            "side":       order.side.value,
            "stop_price": stop_price,
            "qty":        qty,
            "status":     order.status.value,
        }
        logger.info(f"Broker | Stop order placed: {result['id']} status={result['status']}")
        return result
    except Exception as exc:
        logger.warning(f"Broker | Stop order failed for {ticker}: {exc}")
        raise RuntimeError(f"Stop order failed for {ticker}: {exc}") from exc


# ── Price fetching ─────────────────────────────────────────────────────────

def get_latest_price(ticker: str) -> float | None:
    try:
        if is_crypto_pair(ticker):
            return _get_latest_crypto_price(ticker)
        return _get_latest_stock_price(ticker)
    except Exception as exc:
        logger.warning(f"Broker | Could not fetch latest price for {ticker}: {exc}")
    return None


@alpaca_retry
def _get_latest_stock_price(ticker: str) -> float | None:
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
    return None


@alpaca_retry
def _get_latest_crypto_price(ticker: str) -> float | None:
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoLatestTradeRequest
    data_client = CryptoHistoricalDataClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )
    req = CryptoLatestTradeRequest(symbol_or_symbols=ticker)
    trades = data_client.get_crypto_latest_trade(req)
    if ticker in trades:
        price = float(trades[ticker].price)
        logger.debug(f"Broker | Latest crypto price {ticker}: ${price:.4f}")
        return price
    return None


# ── Position management ────────────────────────────────────────────────────

@alpaca_retry
def close_position(ticker: str) -> dict:
    symbol = ticker.replace("/", "") if is_crypto_pair(ticker) else ticker
    logger.warning(f"Broker | Closing position: {ticker} (symbol={symbol})")
    try:
        order: Order = _client().close_position(symbol)
        return {
            "id":     str(order.id),
            "symbol": order.symbol,
            "side":   order.side.value,
            "status": order.status.value,
        }
    except Exception as exc:
        logger.error(f"Broker | Failed to close {ticker}: {exc}")
        raise RuntimeError(f"Failed to close position {ticker}: {exc}") from exc


@alpaca_retry
def cancel_all_orders() -> int:
    logger.warning("Broker | Cancelling ALL open orders")
    cancelled = _client().cancel_orders()
    n = len(cancelled) if cancelled else 0
    logger.warning(f"Broker | {n} orders cancelled")
    return n


@alpaca_retry
def close_all_positions() -> int:
    logger.warning("Broker | Closing ALL positions (kill switch)")
    closed = _client().close_all_positions(cancel_orders=True)
    n = len(closed) if closed else 0
    logger.warning(f"Broker | {n} positions closed")
    return n
