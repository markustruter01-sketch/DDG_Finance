"""A fake Alpaca paper broker that can misbehave, for broker-quirk and replay tests.

The real AlpacaEtfEngine and the real trend executor run against it. It keeps
Alpaca's own rules that our order code depends on:

- shares held by an open sell order (a stop) cannot be sold again
  ("insufficient qty available");
- a buy is rejected while a sell stop for the same symbol is open
  (Alpaca's wash-trade protection);
- GTC stops must be whole shares; replacing an order that is no longer open
  fails with "order is not open";
- a client_order_id can be used once.

Faults that can be switched on (each modelled on something seen live):

- ``cancel_lag_s``: a cancelled order keeps showing as open in the open-orders
  LIST for this many seconds, while get_order already says "canceled"
  (9 Nov 2026, Atlas SPY/QQQ).
- ``fail_next(method, n, error)``: the next n calls of a method raise
  (e.g. 429 rate limit, connection reset).
- ``partial_fill_next(ratio)``: the next market order fills only part and
  stays "partially_filled" until cancelled.
- ``reject_next(type)``: the next submit of that order type is rejected.
- ``empty_positions_next(n)``: list_positions returns [] n times (the known
  transient empty reply).
- ``gap_to(symbol, price)``: the price moves straight to ``price``; any sell
  stop at or above it fills at ``price`` (a gap through the stop).
- ``lose_reply_next(n, resend, method, order_type)``: the next n calls of
  ``method`` (submit_order or replace_order; optionally only for one order
  type) are carried out, then the reply is lost. ``resend=True``: what the
  Alpaca library does after an HTTP 504 (sends again; a resent submit is
  refused as a duplicate client_order_id, a resent replace finds the old
  order no longer open); ``resend=False``: a read time-out
  (16 Nov 2026 order-path audit, F1).

Time is virtual: FakeClock.sleep advances it, so 30-second broker waits run
instantly and lag is measured in the engine's own waiting.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from types import SimpleNamespace

_TIMED_OUT = "HTTPSConnectionPool(host='paper-api.alpaca.markets'): Read timed out."
OPEN_STATUSES = {"new", "accepted", "pending_new", "partially_filled", "held"}


class FakeClock:
    """Stands in for the engine's ``time`` module."""

    def __init__(self, start: float = 1_000.0):
        self.now = start

    def sleep(self, seconds: float) -> None:
        self.now += max(float(seconds), 0.01)

    def monotonic(self) -> float:
        self.now += 0.01      # every check costs a little time, so deadline loops end
        return self.now

    def time(self) -> float:
        return self.now


class APIError(Exception):
    pass


@dataclass
class _Order:
    id: str
    client_order_id: str
    symbol: str
    side: str
    type: str
    qty: float
    time_in_force: str
    stop_price: float | None = None
    status: str = "new"
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    asset_class: str = "us_equity"
    cancelled_at: float | None = None
    replaced_by: str | None = None

    def view(self, **override) -> SimpleNamespace:
        d = dict(self.__dict__, **override)
        d["qty"] = str(int(d["qty"]) if float(d["qty"]).is_integer() else d["qty"])
        d["filled_qty"] = str(d["filled_qty"])
        d["stop_price"] = None if d["stop_price"] is None else str(d["stop_price"])
        d["filled_avg_price"] = None if d["filled_avg_price"] is None else str(d["filled_avg_price"])
        return SimpleNamespace(**d)


@dataclass
class FakeAlpaca:
    prices: dict[str, float]
    positions: dict[str, float] = field(default_factory=dict)       # symbol -> qty
    cash: float = 100_000.0
    clock: FakeClock = field(default_factory=FakeClock)
    market_open: bool = True
    cancel_lag_s: float = 0.0
    orders: dict[str, _Order] = field(default_factory=dict)
    log: list[tuple] = field(default_factory=list)                    # every call, for assertions
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _fail: dict[str, list[Exception]] = field(default_factory=dict)
    _partial: list[float] = field(default_factory=list)
    _reject: dict[str, int] = field(default_factory=dict)
    _empty_positions: int = 0
    _lost_replies: list[dict] = field(default_factory=list)
    _entry: dict[str, float] = field(default_factory=dict)

    # ── fault switches ────────────────────────────────────────────────────
    def fail_next(self, method: str, n: int = 1, error: str = "429 Client Error: Too Many Requests"):
        self._fail.setdefault(method, []).extend(APIError(error) for _ in range(n))

    def partial_fill_next(self, ratio: float) -> None:
        self._partial.append(ratio)

    def reject_next(self, order_type: str, n: int = 1) -> None:
        self._reject[order_type] = self._reject.get(order_type, 0) + n

    def lose_reply_next(self, n: int = 1, resend: bool = True, method: str = "submit_order",
                        order_type: str | None = None) -> None:
        self._lost_replies.extend({"resend": resend, "method": method, "type": order_type}
                                  for _ in range(n))

    def _reply_lost(self, method: str, order_type: str) -> bool | None:
        """None: reply arrives. True/False: lost (resend or time-out)."""
        for i, fault in enumerate(self._lost_replies):
            if fault["method"] == method and fault["type"] in (None, order_type):
                return self._lost_replies.pop(i)["resend"]
        return None

    def empty_positions_next(self, n: int = 1) -> None:
        self._empty_positions += n

    def gap_to(self, symbol: str, price: float) -> None:
        self.prices[symbol] = price
        for o in list(self.orders.values()):
            if (o.symbol == symbol and o.side == "sell" and o.status in OPEN_STATUSES
                    and o.type in {"stop", "stop_limit"} and price <= float(o.stop_price)):
                self._fill(o, o.qty, price)

    # ── helpers for tests ─────────────────────────────────────────────────
    def open_stops(self, symbol: str) -> list[_Order]:
        return [o for o in self.orders.values()
                if o.symbol == symbol and o.side == "sell" and o.type in {"stop", "stop_limit"}
                and o.status in OPEN_STATUSES]

    def held_for_orders(self, symbol: str) -> float:
        return sum(o.qty - o.filled_qty for o in self.orders.values()
                   if o.symbol == symbol and o.side == "sell" and o.status in OPEN_STATUSES)

    # ── internals ─────────────────────────────────────────────────────────
    def _call(self, method: str, *args, **kwargs) -> None:
        self.log.append((method, args, kwargs))
        queued = self._fail.get(method)
        if queued:
            raise queued.pop(0)

    def _fill(self, o: _Order, qty: float, price: float) -> None:
        qty = min(qty, o.qty - o.filled_qty)
        if o.side == "buy":
            held = self.positions.get(o.symbol, 0.0)
            self._entry[o.symbol] = ((self._entry.get(o.symbol, price) * held + price * qty) / (held + qty))
            self.positions[o.symbol] = held + qty
            self.cash -= qty * price
        else:
            self.positions[o.symbol] = self.positions.get(o.symbol, 0.0) - qty
            if self.positions[o.symbol] <= 1e-9:
                self.positions.pop(o.symbol)
                self._entry.pop(o.symbol, None)
            self.cash += qty * price
        prev = o.filled_qty
        o.filled_qty = prev + qty
        o.filled_avg_price = price if not prev else (
            (float(o.filled_avg_price) * prev + price * qty) / o.filled_qty)
        o.status = "filled" if o.filled_qty >= o.qty - 1e-9 else "partially_filled"

    # ── Alpaca REST surface used by the engine ────────────────────────────
    def get_clock(self):
        self._call("get_clock")
        return SimpleNamespace(is_open=self.market_open)

    def get_account(self):
        self._call("get_account")
        lmv = sum(q * self.prices[s] for s, q in self.positions.items())
        equity = self.cash + lmv
        return SimpleNamespace(equity=str(equity), cash=str(self.cash), buying_power=str(self.cash),
                               long_market_value=str(lmv), last_equity=str(equity))

    def _position_view(self, symbol: str, qty: float):
        px = self.prices[symbol]
        entry = self._entry.get(symbol, px)
        return SimpleNamespace(
            symbol=symbol, qty=str(int(qty) if float(qty).is_integer() else qty), side="long",
            qty_available=str(qty - self.held_for_orders(symbol)),
            avg_entry_price=str(entry), current_price=str(px), market_value=str(qty * px),
            unrealized_pl=str((px - entry) * qty), asset_class="us_equity")

    def list_positions(self):
        self._call("list_positions")
        if self._empty_positions:
            self._empty_positions -= 1
            return []
        return [self._position_view(s, q) for s, q in sorted(self.positions.items())]

    def get_position(self, symbol: str):
        self._call("get_position", symbol)
        if symbol not in self.positions:
            raise APIError("position does not exist")
        return self._position_view(symbol, self.positions[symbol])

    def list_orders(self, status: str = "open", limit: int = 100, nested: bool = True, **_):
        self._call("list_orders", status=status)
        out = []
        for o in self.orders.values():
            if o.status in OPEN_STATUSES:
                out.append(o.view())
            elif (o.status == "canceled" and o.cancelled_at is not None
                  and self.clock.now - o.cancelled_at < self.cancel_lag_s):
                out.append(o.view(status="new"))     # stale list entry: the 9 Nov quirk
        return out[:limit]

    def get_order(self, order_id: str):
        self._call("get_order", order_id)
        if order_id not in self.orders:
            raise APIError("order not found")
        return self.orders[order_id].view()

    def get_order_by_client_order_id(self, client_order_id: str):
        self._call("get_order_by_client_order_id", client_order_id)
        for o in self.orders.values():
            if o.client_order_id == client_order_id:
                return o.view()
        raise APIError("order not found")

    def submit_order(self, *, symbol: str, side: str, type: str, time_in_force: str,
                     client_order_id: str, qty=None, notional=None, stop_price=None, **_):
        self._call("submit_order", symbol=symbol, side=side, type=type, qty=qty, stop_price=stop_price)
        if any(o.client_order_id == client_order_id for o in self.orders.values()):
            raise APIError("client_order_id must be unique")
        if self._reject.get(type):
            self._reject[type] -= 1
            raise APIError(f"order rejected by broker ({type})")
        qty = float(qty) if qty is not None else float(notional) / self.prices[symbol]
        if qty <= 0:
            raise APIError("qty must be > 0")
        if type in {"stop", "stop_limit"} and time_in_force == "gtc" and not qty.is_integer():
            raise APIError("fractional orders must be DAY orders")
        if side == "sell":
            available = self.positions.get(symbol, 0.0) - self.held_for_orders(symbol)
            if qty > available + 1e-9:
                raise APIError(f"insufficient qty available for order (requested: {qty}, available: {available})")
        if side == "buy" and self.open_stops(symbol):
            raise APIError("potential wash trade detected. use complex orders")
        o = _Order(id=f"ord-{next(self._ids)}", client_order_id=client_order_id, symbol=symbol,
                   side=side, type=type, qty=qty, time_in_force=time_in_force,
                   stop_price=None if stop_price is None else float(stop_price))
        self.orders[o.id] = o
        if type == "market" and self.market_open:
            ratio = self._partial.pop(0) if self._partial else 1.0
            fill_qty = qty if ratio >= 1 else max(1.0, float(int(qty * ratio)))
            self._fill(o, fill_qty, self.prices[symbol])
        lost = self._reply_lost("submit_order", type)
        if lost is not None:
            raise APIError("client_order_id must be unique" if lost else _TIMED_OUT)
        return o.view()

    def cancel_order(self, order_id: str) -> None:
        self._call("cancel_order", order_id)
        o = self.orders.get(order_id)
        if o is None:
            raise APIError("order not found")
        if o.status not in OPEN_STATUSES:
            raise APIError("order is not cancelable")
        o.status = "canceled"
        o.cancelled_at = self.clock.now

    def replace_order(self, order_id: str, *, qty=None, stop_price=None, time_in_force=None, **_):
        self._call("replace_order", order_id, qty=qty, stop_price=stop_price)
        old = self.orders.get(order_id)
        if old is None or old.status not in OPEN_STATUSES:
            raise APIError("order is not open")
        old.status = "replaced"
        new_qty = float(qty) if qty is not None else old.qty
        available = self.positions.get(old.symbol, 0.0) - self.held_for_orders(old.symbol)
        if old.side == "sell" and new_qty > available + 1e-9:
            old.status = "new"
            raise APIError("insufficient qty available for order")
        o = _Order(id=f"ord-{next(self._ids)}", client_order_id=f"{old.client_order_id[:40]}-r",
                   symbol=old.symbol, side=old.side, type=old.type, qty=new_qty,
                   time_in_force=time_in_force or old.time_in_force,
                   stop_price=float(stop_price) if stop_price is not None else old.stop_price)
        self.orders[o.id] = o
        old.replaced_by = o.id
        lost = self._reply_lost("replace_order", old.type)
        if lost is not None:
            raise APIError("order is not open" if lost else _TIMED_OUT)
        return o.view()

    def get_latest_trade(self, symbol: str):
        self._call("get_latest_trade", symbol)
        return SimpleNamespace(price=self.prices[symbol])

    def get_asset(self, symbol: str):
        self._call("get_asset", symbol)
        tradable = symbol in self.prices
        return SimpleNamespace(symbol=symbol, tradable=tradable, status="active" if tradable else "inactive")

    # ── set-up helper ─────────────────────────────────────────────────────
    def seed_stop(self, symbol: str, qty: float, stop_price: float, client_order_id: str) -> str:
        o = _Order(id=f"ord-{next(self._ids)}", client_order_id=client_order_id, symbol=symbol,
                   side="sell", type="stop", qty=float(qty), time_in_force="gtc",
                   stop_price=float(stop_price))
        self.orders[o.id] = o
        return o.id
