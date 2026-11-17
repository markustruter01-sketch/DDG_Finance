"""
Alpaca Broker — Order Execution Layer  (v2.1 — Short Order Primitives)
-----------------------------------------------------------------------
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

v2.1 additions (Bear Engine)
-----------------------------
  • buy_to_cover()            — BUY market order to close a short (GTC)
  • place_short_stop_order()  — BUY stop order (stop-buy above price) to cap loss on short
  • get_positions() now includes `side` field ("long" or "short")
  • get_account() now exposes `initial_margin` (used for short exposure cap)

Supports ETF/stock (TimeInForce.DAY) and crypto spot (TimeInForce.GTC).
Crypto pairs are detected by "/" in the ticker (e.g. BTC/USD).
Paper trading only — paper=True is hardcoded.
"""

import math
from decimal import Decimal

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
from alpaca.trading.models import Order, Position, TradeAccount
from loguru import logger

from config.settings import settings
from analysis.schemas import is_crypto_pair
from execution.resilience import alpaca_retry
from core.order_ids import submit_with_unique_client_order_id
from core.broker_http import with_time_limit

# ── Singleton client ────────────────────────────────────────────────────────
_trading_client: TradingClient | None = None


def _client() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        # Every call has a time limit (16 Nov 2026 audit, F5).
        _trading_client = with_time_limit(TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,
        ))
        logger.debug("Broker | TradingClient singleton created")
    return _trading_client


def _lookup_order(client_order_id: str):
    """Read an order back by its client ID (used when a send raised)."""
    return _client().get_order_by_client_id(client_order_id)


# ── Account + positions ────────────────────────────────────────────────────

@alpaca_retry
def get_account() -> dict:
    acct: TradeAccount = _client().get_account()
    return {
        "equity":             float(acct.equity),
        "last_equity":        float(acct.last_equity),
        "cash":               float(acct.cash),
        "buying_power":       float(acct.buying_power),
        "initial_margin":     float(acct.initial_margin) if acct.initial_margin else 0.0,
        "trading_blocked":    acct.trading_blocked,
        "pattern_day_trader": acct.pattern_day_trader,
    }


@alpaca_retry
def get_positions() -> list[dict]:
    positions: list[Position] = _client().get_all_positions()

    # Enrich entry_time from position_entry_times table (immutable TIMESTAMPTZ written
    # once when the position is first opened — never overwritten on ratchet updates).
    # Used by check_time_exits() to enforce the 5-day 3× inverse ETF forced-exit rule.
    _entry_times: dict[str, str] = {}
    try:
        from db.postgres import get_position_entry_times
        _entry_times = get_position_entry_times()
    except Exception:
        pass  # Non-fatal — entry_time defaults to None (time-exit won't fire)

    return [
        {
            "symbol":          p.symbol,
            "qty":             float(p.qty),
            "side":            p.side.value if hasattr(p, "side") and p.side else "long",
            "avg_entry_price": float(p.avg_entry_price),
            "market_value":    float(p.market_value),
            "unrealized_pl":   float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
            "current_price":   float(p.current_price),
            "entry_time":      _entry_times.get(p.symbol),
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

    logger.info(
        f"Broker | Placing {side.upper()} {ticker} ${notional_usd:,.2f} "
        f"(notional, market, TIF={tif.value})"
    )

    try:
        order, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: _client().submit_order(
                MarketOrderRequest(
                    symbol=symbol,
                    notional=round(notional_usd, 2),
                    side=order_side,
                    time_in_force=tif,
                    client_order_id=generated_id,
                )
            ),
            f"broker-entry-{ticker}",
            lookup=_lookup_order,
        )
        result = {
            "id":         str(order.id),
            "symbol":     order.symbol,
            "side":       order.side.value,
            "notional":   float(order.notional) if order.notional else notional_usd,
            "status":     order.status.value,
            "created_at": str(order.created_at),
            "client_order_id": client_order_id,
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

    logger.info(f"Broker | Stop-sell {ticker} qty={qty:.6f} stop=${stop_price:.4f} (GTC)")
    try:
        order, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: _client().submit_order(
                StopOrderRequest(
                    symbol=symbol,
                    qty=round(qty, 8),
                    side=OrderSide.SELL,
                    time_in_force=tif,
                    stop_price=round(stop_price, 2),
                    client_order_id=generated_id,
                )
            ),
            f"broker-stop-{ticker}",
            lookup=_lookup_order,
        )
        result = {
            "id":         str(order.id),
            "symbol":     order.symbol,
            "side":       order.side.value,
            "stop_price": stop_price,
            "qty":        qty,
            "status":     order.status.value,
            "client_order_id": client_order_id,
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


# ── Data client singleton (stock) ───────────────────────────────────────────
# One TLS handshake per process rather than one per price fetch.
_stock_data_client: "StockHistoricalDataClient | None" = None


def _get_stock_data_client():
    """Return cached StockHistoricalDataClient — one TLS handshake per process."""
    global _stock_data_client
    if _stock_data_client is None:
        from alpaca.data.historical import StockHistoricalDataClient
        _stock_data_client = with_time_limit(StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        ))
        logger.debug("Broker | StockHistoricalDataClient singleton created")
    return _stock_data_client


@alpaca_retry
def _get_latest_stock_price(ticker: str) -> float | None:
    from alpaca.data.requests import StockLatestTradeRequest
    data_client = _get_stock_data_client()
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
    data_client = with_time_limit(CryptoHistoricalDataClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    ))
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
    """Close a position with an explicitly tagged market order."""
    symbol = ticker.replace("/", "") if is_crypto_pair(ticker) else ticker
    logger.warning(f"Broker | Closing position (day): {ticker} (symbol={symbol})")
    try:
        position: Position = _client().get_open_position(symbol)
        position_side = getattr(position.side, "value", str(position.side)).lower()
        close_side = OrderSide.BUY if position_side == "short" else OrderSide.SELL
        tif = TimeInForce.GTC if is_crypto_pair(ticker) else TimeInForce.DAY
        qty = round(abs(float(position.qty)), 8)
        order, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: _client().submit_order(
                MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=close_side,
                    time_in_force=tif,
                    client_order_id=generated_id,
                )
            ),
            f"broker-close-{ticker}",
            lookup=_lookup_order,
        )
        return {
            "id":     str(order.id),
            "symbol": order.symbol,
            "side":   order.side.value,
            "status": order.status.value,
            "client_order_id": client_order_id,
        }
    except Exception as exc:
        logger.error(f"Broker | Failed to close {ticker}: {exc}")
        raise RuntimeError(f"Failed to close position {ticker}: {exc}") from exc


@alpaca_retry
def close_position_gtc(ticker: str) -> dict:
    """
    Emergency close: place an explicit GTC market sell order for the full qty.

    Unlike close_position() which uses Alpaca's shortcut (TIF=day and gets
    auto-cancelled on weekends), this submits a qty-based GTC sell that persists
    until the market opens and fills it.
    Crypto positions are already GTC by default; equity positions get forced GTC.
    """
    is_crypto = is_crypto_pair(ticker)
    symbol    = ticker.replace("/", "") if is_crypto else ticker
    # Fetch current qty from Alpaca so we can close the exact fractional amount
    position: Position = _client().get_open_position(symbol)
    qty = abs(float(position.qty))

    tif = TimeInForce.GTC  # persists over weekends / after-hours
    logger.warning(
        f"Broker | Emergency close GTC: {ticker} qty={qty:.6f} TIF={tif.value}"
    )
    try:
        order, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: _client().submit_order(
                MarketOrderRequest(
                    symbol=symbol,
                    qty=round(qty, 8),
                    side=OrderSide.SELL,
                    time_in_force=tif,
                    client_order_id=generated_id,
                )
            ),
            f"broker-close-gtc-{ticker}",
            lookup=_lookup_order,
        )
        return {
            "id":     str(order.id),
            "symbol": order.symbol,
            "side":   order.side.value,
            "qty":    qty,
            "status": order.status.value,
            "tif":    tif.value,
            "client_order_id": client_order_id,
        }
    except Exception as exc:
        logger.error(f"Broker | GTC close failed for {ticker}: {exc}")
        raise RuntimeError(f"GTC close failed for {ticker}: {exc}") from exc


@alpaca_retry
def cancel_all_orders() -> int:
    logger.warning("Broker | Cancelling ALL open orders")
    cancelled = _client().cancel_orders()
    n = len(cancelled) if cancelled else 0
    logger.warning(f"Broker | {n} orders cancelled")
    return n


@alpaca_retry
def cancel_order(order_id: str) -> bool:
    """Cancel a single order by ID. Returns True on success."""
    try:
        _client().cancel_order_by_id(order_id)
        logger.info(f"Broker | Cancelled order {order_id}")
        return True
    except Exception as exc:
        logger.warning(f"Broker | Failed to cancel order {order_id}: {exc}")
        return False


@alpaca_retry
def close_all_positions() -> int:
    """Close every position through the tagged explicit-order path."""
    logger.warning("Broker | Closing ALL positions (kill switch)")
    _client().cancel_orders()
    positions: list[Position] = _client().get_all_positions()
    closed = 0
    for position in positions:
        try:
            close_position(position.symbol)
            closed += 1
        except Exception as exc:
            logger.error(
                f"Broker | Kill-switch close failed for {position.symbol}: {exc}"
            )
    logger.warning(f"Broker | {closed}/{len(positions)} positions closed")
    return closed


# ── Short Selling Primitives (Bear Engine v2.1) ────────────────────────────

@alpaca_retry
# Opening a short (check_shortable, place_short_order) was removed 18 Nov 2026: no strategy shorts.
# buy_to_cover and place_short_stop_order stay, so a short could still be protected and closed.


def buy_to_cover(ticker: str, qty_int: int) -> dict:
    """
    Place a BUY market order to close an existing short position (GTC).

    Parameters
    ----------
    ticker  : str   Equity ticker.
    qty_int : int   Whole shares to cover.

    Returns
    -------
    dict with id, symbol, side, qty, status.
    """
    qty = max(1, math.floor(qty_int))
    logger.info(f"Broker | BUY-TO-COVER {ticker} qty={qty} (GTC)")
    try:
        order, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: _client().submit_order(
                MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.GTC,
                    client_order_id=generated_id,
                )
            ),
            f"broker-cover-{ticker}",
            lookup=_lookup_order,
        )
        result = {
            "id":         str(order.id),
            "symbol":     order.symbol,
            "side":       order.side.value,
            "qty":        qty,
            "status":     order.status.value,
            "created_at": str(order.created_at),
            "client_order_id": client_order_id,
        }
        logger.info(f"Broker | Cover order placed: {result['id']} {ticker} status={result['status']}")
        return result
    except Exception as exc:
        logger.error(f"Broker | buy_to_cover failed for {ticker}: {exc}")
        raise RuntimeError(f"buy_to_cover failed for {ticker}: {exc}") from exc


@alpaca_retry
def place_short_stop_order(ticker: str, qty_int: int, stop_price: float) -> dict:
    """
    Place a GTC stop-BUY order to protect a short position.

    The stop fills if *ticker* price rises to *stop_price* (i.e. the trade
    moves against the short).  This is the inverse of a long stop-loss.

    Parameters
    ----------
    ticker     : str   Equity ticker.
    qty_int    : int   Whole shares to cover at the stop.
    stop_price : float Price at which to trigger the covering buy.

    Returns
    -------
    dict with id, symbol, side, stop_price, qty, status.
    """
    qty = max(1, math.floor(qty_int))
    logger.info(f"Broker | Short-stop BUY {ticker} qty={qty} stop=${stop_price:.4f} (GTC)")
    try:
        order, client_order_id = submit_with_unique_client_order_id(
            lambda generated_id: _client().submit_order(
                StopOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.GTC,
                    stop_price=round(stop_price, 4),
                    client_order_id=generated_id,
                )
            ),
            f"broker-short-stop-{ticker}",
            lookup=_lookup_order,
        )
        result = {
            "id":         str(order.id),
            "symbol":     order.symbol,
            "side":       order.side.value,
            "stop_price": stop_price,
            "qty":        qty,
            "status":     order.status.value,
            "client_order_id": client_order_id,
        }
        logger.info(f"Broker | Short-stop order placed: {result['id']} status={result['status']}")
        return result
    except Exception as exc:
        logger.warning(f"Broker | Short-stop order failed for {ticker}: {exc}")
        raise RuntimeError(f"Short-stop order failed for {ticker}: {exc}") from exc
