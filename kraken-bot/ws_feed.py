"""
ws_feed.py — Kraken WebSocket Real-Time Feed (Stage 2)
=======================================================
Provides sub-second price/trade data via Kraken's public WebSocket API,
eliminating the 60-second REST polling bottleneck.

Architecture:
  - Connects to wss://ws.kraken.com/v2 for real-time ticker data
  - Maintains a thread-safe price cache updated on every tick
  - Falls back to REST polling (ccxt) if WebSocket disconnects
  - The main loop queries the cache instead of making REST calls

Usage:
    from ws_feed import WebSocketFeed
    feed = WebSocketFeed(symbols=["BTC/USD", "ETH/USD"])
    feed.start()
    price = feed.get_price("BTC/USD")  # sub-millisecond
    feed.stop()
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Callable

from loguru import logger

KRAKEN_WS_URL = "wss://ws.kraken.com/v2"

SYMBOL_TO_KRAKEN = {
    "BTC/USD": "XBT/USD",
    "ETH/USD": "ETH/USD",
    "XRP/USD": "XRP/USD",
    "SOL/USD": "SOL/USD",
    "DOGE/USD": "DOGE/USD",
    "ADA/USD": "ADA/USD",
    "AVAX/USD": "AVAX/USD",
    "LINK/USD": "LINK/USD",
    "DOT/USD": "DOT/USD",
    "UNI/USD": "UNI/USD",
    "BCH/USD": "BCH/USD",
    "LTC/USD": "LTC/USD",
    "ATOM/USD": "ATOM/USD",
    "SHIB/USD": "SHIB/USD",
    "NEAR/USD": "NEAR/USD",
    "BNB/USD": "BNB/USD",
    "TRX/USD": "TRX/USD",
    "TON/USD": "TON/USD",
    "APT/USD": "APT/USD",
    "ICP/USD": "ICP/USD",
    "FIL/USD": "FIL/USD",
    "ARB/USD": "ARB/USD",
    "OP/USD": "OP/USD",
    "SUI/USD": "SUI/USD",
    "INJ/USD": "INJ/USD",
    "RENDER/USD": "RENDER/USD",
    "STX/USD": "STX/USD",
    "TAO/USD": "TAO/USD",
    "PEPE/USD": "PEPE/USD",
    "POL/USD": "POL/USD",
    "IMX/USD": "IMX/USD",
    "GRT/USD": "GRT/USD",
    "VET/USD": "VET/USD",
    "HBAR/USD": "HBAR/USD",
    "RUNE/USD": "RUNE/USD",
    "SNX/USD": "SNX/USD",
    "ENS/USD": "ENS/USD",
    "WLD/USD": "WLD/USD",
    "JUP/USD": "JUP/USD",
    "TIA/USD": "TIA/USD",
    "ONDO/USD": "ONDO/USD",
    "SEI/USD": "SEI/USD",
    "PYTH/USD": "PYTH/USD",
    "W/USD": "W/USD",
    "DYM/USD": "DYM/USD",
    "STRK/USD": "STRK/USD",
    "ENA/USD": "ENA/USD",
    "AAVE/USD": "AAVE/USD",
    "CRV/USD": "CRV/USD",
}

KRAKEN_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_KRAKEN.items()}


class TickerSnapshot:
    __slots__ = ("price", "bid", "ask", "volume_24h", "updated_at")

    def __init__(self, price: float, bid: float, ask: float, volume_24h: float):
        self.price = price
        self.bid = bid
        self.ask = ask
        self.volume_24h = volume_24h
        self.updated_at = time.time()

    @property
    def age_ms(self) -> float:
        return (time.time() - self.updated_at) * 1000

    @property
    def spread_pct(self) -> float:
        if self.bid <= 0:
            return 0.0
        return (self.ask - self.bid) / self.bid

    def is_fresh(self, max_age_seconds: float = 10.0) -> bool:
        return self.age_ms < max_age_seconds * 1000


class WebSocketFeed:
    """
    Real-time Kraken WebSocket feed with thread-safe price cache.
    Falls back gracefully if websocket-client is not installed.
    """

    def __init__(
        self,
        symbols: list[str],
        on_tick: Optional[Callable[[str, TickerSnapshot], None]] = None,
    ):
        self._symbols = symbols
        self._kraken_pairs = []
        for s in symbols:
            k = SYMBOL_TO_KRAKEN.get(s)
            if k:
                self._kraken_pairs.append(k)

        self._on_tick = on_tick
        self._cache: dict[str, TickerSnapshot] = {}
        self._lock = threading.Lock()
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._reconnect_count = 0
        self._max_reconnects = 10
        self._stats = {
            "ticks_received": 0,
            "last_tick_at": None,
            "connect_time": None,
            "disconnects": 0,
        }

    def get_price(self, symbol: str) -> Optional[float]:
        with self._lock:
            snap = self._cache.get(symbol)
            if snap and snap.is_fresh():
                return snap.price
        return None

    def get_last_price(self, symbol: str) -> Optional[float]:
        """Return the last cached price regardless of staleness (for P&L display)."""
        with self._lock:
            snap = self._cache.get(symbol)
            if snap and snap.price > 0:
                return snap.price
        return None

    def get_snapshot(self, symbol: str) -> Optional[TickerSnapshot]:
        with self._lock:
            snap = self._cache.get(symbol)
            if snap and snap.is_fresh():
                return snap
        return None

    def get_all_prices(self) -> dict[str, float]:
        result = {}
        with self._lock:
            for sym, snap in self._cache.items():
                if snap.is_fresh():
                    result[sym] = snap.price
        return result

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="kraken-ws-feed")
        self._thread.start()
        logger.info(f"WebSocketFeed | Started for {len(self._kraken_pairs)} pairs")

    def stop(self) -> None:
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("WebSocketFeed | Stopped")

    def _run_loop(self) -> None:
        # Reliability fix (audit M10): never permanently give up on the WebSocket
        # feed.  Falling back to REST polling burns API quota and increases latency.
        # Use capped exponential backoff (max 60s) on every iteration -- including
        # the common path where ``run_forever`` returns normally on close (no
        # exception), which previously hot-spun the loop.  Only treat the session
        # as "stable" (and reset backoff) if it lasted >=30s.
        STABILITY_THRESHOLD_S = 30.0
        while self._running:
            session_start = time.time()
            exc_repr = None
            try:
                self._connect_and_listen()
            except Exception as exc:
                exc_repr = repr(exc)
            self._connected = False
            session_dur = time.time() - session_start

            if not self._running:
                break

            if session_dur >= STABILITY_THRESHOLD_S and exc_repr is None:
                # Stable session that closed cleanly -- reset backoff and reconnect promptly.
                self._reconnect_count = 0
                wait = 1.0
            else:
                self._reconnect_count += 1
                self._stats["disconnects"] += 1
                wait = min(2 ** min(self._reconnect_count, 6), 60)

            reason = exc_repr or f"closed after {session_dur:.1f}s"
            logger.warning(
                f"WebSocketFeed | Disconnected ({reason}), "
                f"reconnecting in {wait}s (attempt {self._reconnect_count})"
            )
            time.sleep(wait)

    def _connect_and_listen(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.warning(
                "WebSocketFeed | websocket-client not installed. "
                "Install with: pip install websocket-client. Falling back to REST."
            )
            self._running = False
            return

        def on_open(ws):
            self._connected = True
            # Note: _reconnect_count is reset by _run_loop only after the
            # session proves stable (>=30s).  Resetting here causes a hot
            # reconnect loop on the "connect-then-immediate-drop" failure mode.
            self._stats["connect_time"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"WebSocketFeed | Connected to {KRAKEN_WS_URL}")

            batch_size = 25
            for i in range(0, len(self._kraken_pairs), batch_size):
                batch = self._kraken_pairs[i:i + batch_size]
                sub_msg = {
                    "method": "subscribe",
                    "params": {
                        "channel": "ticker",
                        "symbol": batch,
                    },
                }
                ws.send(json.dumps(sub_msg))
                logger.debug(f"WebSocketFeed | Subscribed batch {i // batch_size + 1}: {len(batch)} pairs")

        def on_message(ws, message):
            try:
                data = json.loads(message)
                self._handle_message(data)
            except Exception as exc:
                logger.debug(f"WebSocketFeed | Message parse error: {exc}")

        def on_error(ws, error):
            logger.debug(f"WebSocketFeed | Error: {error}")

        def on_close(ws, close_status_code, close_msg):
            self._connected = False
            logger.info(f"WebSocketFeed | Connection closed ({close_status_code})")

        self._ws = websocket.WebSocketApp(
            KRAKEN_WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10)

    def _handle_message(self, data: dict) -> None:
        if data.get("channel") != "ticker":
            return

        ticker_data = data.get("data", [])
        for tick in ticker_data:
            kraken_sym = tick.get("symbol", "")
            our_sym = KRAKEN_TO_SYMBOL.get(kraken_sym)
            if not our_sym:
                continue

            try:
                price = float(tick.get("last", 0))
                bid = float(tick.get("bid", 0))
                ask = float(tick.get("ask", 0))
                vol = float(tick.get("volume", 0))

                if price <= 0:
                    continue

                snap = TickerSnapshot(price=price, bid=bid, ask=ask, volume_24h=vol)

                with self._lock:
                    self._cache[our_sym] = snap

                self._stats["ticks_received"] += 1
                self._stats["last_tick_at"] = time.time()

                if self._on_tick:
                    try:
                        self._on_tick(our_sym, snap)
                    except Exception:
                        pass

            except (ValueError, TypeError):
                continue
