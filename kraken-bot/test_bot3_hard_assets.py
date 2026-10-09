"""Focused Bot 3 stop-ledger regressions."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import time
from datetime import datetime, timezone

import pytest


_MODULE_PATH = pathlib.Path(__file__).with_name("bot3_hard_assets_strategy.py")
_SPEC = importlib.util.spec_from_file_location(
    "bot3_hard_assets_strategy_test", _MODULE_PATH
)
assert _SPEC and _SPEC.loader
bot3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot3
_SPEC.loader.exec_module(bot3)


class _EntryClient:
    def __init__(self) -> None:
        self.qty = 0.0

    def submit(self, symbol, side, qty, order_type, **_extra):
        if side == "buy":
            self.qty = float(qty)
            return {"id": "entry-order"}
        return {"id": "replacement-stop-order"}

    def wait_for_fill(self, order_id):
        return {
            "status": "filled",
            "filled_qty": self.qty,
            "filled_avg_price": 100.0,
        }

    def positions(self):
        return [{"symbol": "BTC/USD", "qty": self.qty}]


def test_confirmed_entry_explicitly_remembers_stop_order_id(monkeypatch) -> None:
    client = _EntryClient()
    recorded = []
    remembered = []

    monkeypatch.setattr(
        bot3,
        "_record_open",
        lambda fill, qty, stop_price, stop_order_id: recorded.append(
            (fill, qty, stop_price, stop_order_id)
        ),
    )
    monkeypatch.setattr(bot3, "_strategy_positions", lambda: [])
    monkeypatch.setattr(
        bot3,
        "_remember_stop",
        lambda symbol, stop_order_id: remembered.append((symbol, stop_order_id)),
    )
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    result = bot3._place_confirmed_entry(client, "BTC/USD", 0.5, "cycle")

    assert result["status"] == "filled"
    assert recorded[0][3] == "replacement-stop-order"
    assert remembered == [("BTC/USD", "replacement-stop-order")]


class _PartialEntryClient:
    def __init__(self) -> None:
        self.qty = 2.0
        self.events = []
        self.submitted = []

    def submit(self, symbol, side, qty, order_type, **extra):
        self.events.append(("submit", side, order_type, float(qty)))
        self.submitted.append((symbol, side, float(qty), order_type, extra))
        if side == "buy":
            return {"id": "entry-order"}
        return {
            "id": "entry-stop",
            "status": "new",
            "stop_price": str(extra["stop_price"]),
        }

    def wait_for_fill(self, _order_id):
        return {
            "status": "partially_filled",
            "filled_qty": "2",
            "filled_avg_price": "100",
        }

    def _request(self, method, path, **_kwargs):
        self.events.append((method.upper(), path))
        if method.upper() == "DELETE":
            return {}
        return {
            "id": "entry-order",
            "status": "canceled",
            "filled_qty": "2",
            "filled_avg_price": "100",
        }

    def positions(self):
        return [{"symbol": "GLD", "qty": self.qty}]


def test_partial_entry_cancels_remainder_before_stop_for_filled_quantity(
    monkeypatch,
) -> None:
    client = _PartialEntryClient()
    recorded = []
    monkeypatch.setattr(bot3, "_strategy_positions", lambda: [])
    monkeypatch.setattr(
        bot3,
        "_record_open",
        lambda fill, qty, stop_price, stop_order_id: recorded.append(
            (fill, qty, stop_price, stop_order_id)
        ),
    )
    monkeypatch.setattr(bot3, "_remember_stop", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    result = bot3._place_confirmed_entry(client, "GLD", 5, "cycle")

    assert result["status"] == "canceled"
    assert client.events[1][0] == "DELETE"
    assert client.events[2][0] == "GET"
    assert client.events[3] == ("submit", "sell", "stop", 2.0)
    assert client.submitted[-1][2] == 2.0
    assert recorded[0][1] == 2.0
    assert recorded[0][3] == "entry-stop"


def test_entry_refuses_to_buy_when_an_open_row_already_exists(monkeypatch) -> None:
    row = _open_position_row("GLD")

    class NoOrderClient:
        submitted = False

        def submit(self, *args, **kwargs):
            self.submitted = True
            raise AssertionError("duplicate entry must not submit an order")

    client = NoOrderClient()
    critical = []
    monkeypatch.setattr(bot3, "_strategy_positions", lambda: [row])
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot3.logger, "critical", lambda message: critical.append(message))

    result = bot3._place_confirmed_entry(client, "GLD", 5, "cycle")

    assert result["status"] == "blocked_open_row"
    assert not client.submitted
    assert any("open ledger row exists" in message for message in critical)


def test_wait_for_fill_keeps_polling_after_partial_fill(monkeypatch) -> None:
    client = object.__new__(bot3.AlpacaBot3)
    statuses = iter(["partially_filled", "filled"])
    requests = []

    def get_order(method, path, **_kwargs):
        requests.append((method, path))
        return {"status": next(statuses)}

    monkeypatch.setattr(client, "_request", get_order)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    result = client.wait_for_fill("entry-order", attempts=3)

    assert result["status"] == "filled"
    assert len(requests) == 2


class _RemainderOrderClient:
    def __init__(self, statuses) -> None:
        self.statuses = list(statuses)
        self.events = []

    def wait_for_fill(self, _order_id):
        return {"status": "partially_filled", "filled_qty": "2"}

    def _request(self, method, path, **_kwargs):
        self.events.append((method.upper(), path))
        if method.upper() == "DELETE":
            return {}
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"status": status, "filled_qty": "2"}


def test_wait_helper_cancels_and_confirms_a_working_remainder(monkeypatch) -> None:
    client = _RemainderOrderClient(["cancel_pending", "canceled"])
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    result = bot3._wait_for_final_order(client, "entry-order")

    assert result["status"] == "canceled"
    assert [event[0] for event in client.events] == ["DELETE", "GET", "GET"]


def test_wait_helper_raises_when_cancel_cannot_be_confirmed(monkeypatch) -> None:
    client = _RemainderOrderClient(["new"])
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="cancellation was not confirmed"):
        bot3._wait_for_final_order(client, "entry-order", cancel_attempts=2)


class _MemoryLedger:
    def __init__(self, row: dict) -> None:
        self.rows = (
            [dict(item) for item in row]
            if isinstance(row, list)
            else [dict(row)]
        )
        self.statements = []
        self.insert_count = 0


class _MemoryCursor:
    def __init__(self, ledger: _MemoryLedger) -> None:
        self.ledger = ledger
        self.rowcount = -1
        self.results = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, query: str, params=()) -> None:
        params = tuple(params or ())
        placeholder_count = query.count("%s")
        if placeholder_count != len(params):
            raise AssertionError(
                f"SQL placeholder mismatch: {placeholder_count} placeholders "
                f"for {len(params)} parameters: {query!r}"
            )
        self.ledger.statements.append((query, params))
        normalized = " ".join(query.lower().split())
        if normalized.startswith("insert into bot3_positions"):
            self.ledger.insert_count += 1
            raise AssertionError("an existing position must never be inserted again")

        if normalized.startswith("select symbol from bot3_positions"):
            bot_id, quarter_start, now = params

            def timestamp(value):
                return value.isoformat() if hasattr(value, "isoformat") else str(value)

            start_text, end_text = timestamp(quarter_start), timestamp(now)
            self.results = [
                (row["symbol"],)
                for row in self.ledger.rows
                if row["bot_id"] == bot_id
                and row["status"] == "closed"
                and row.get("exit_reason") == "stop_filled"
                and row.get("closed_at") is not None
                and start_text <= timestamp(row["closed_at"]) <= end_text
            ]
            return

        if "set status='closed'" in normalized:
            if len(params) == 4:
                closed_at, exit_reason, bot_id, symbol = params
            else:
                exit_reason, bot_id, symbol = params
                closed_at = "fake-now"
            matches = [
                row for row in self.ledger.rows
                if row["bot_id"] == bot_id
                and row["symbol"] == symbol
                and row["status"] == "open"
            ]
            self.rowcount = len(matches)
            for row in matches:
                row.update(
                    status="closed",
                    exit_reason=exit_reason,
                    closed_at=closed_at,
                )
            return

        if normalized.startswith("update bot3_positions"):
            qty, entry_price, notional_usd, stop_price, stop_order_id, bot_id, symbol = params
            matches = [
                row for row in self.ledger.rows
                if row["bot_id"] == bot_id
                and row["symbol"] == symbol
                and row["status"] == "open"
            ]
            self.rowcount = len(matches)
            for row in matches:
                row.update(
                    qty=qty,
                    entry_price=entry_price,
                    notional_usd=notional_usd,
                    stop_price=stop_price,
                    stop_order_id=stop_order_id,
                )
            return

        raise AssertionError(f"unexpected SQL in fake ledger: {query}")

    def fetchall(self):
        return list(self.results)


class _MemoryConnection:
    def __init__(self, ledger: _MemoryLedger) -> None:
        self.ledger = ledger

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self):
        return _MemoryCursor(self.ledger)


class _ReservedShareBroker:
    """Fake Alpaca broker: open sell orders reserve their position quantity."""

    def __init__(
        self,
        qty: float = 10.0,
        entry_price: float = 100.0,
        current_price: float = 105.0,
        *,
        cancel_confirms: bool = True,
        stop_failures: int = 0,
        symbol: str = "GLD",
        asset_class: str = "us_equity",
    ) -> None:
        self.symbol = symbol
        self.qty = qty
        self.entry_price = entry_price
        self.current_price = current_price
        self.asset_class = asset_class
        self.cancel_confirms = cancel_confirms
        self.stop_failures = stop_failures
        self.events = []
        self.submitted = []
        self.orders = {
            "old-stop": {
                "id": "old-stop",
                "symbol": symbol,
                "qty": str(qty),
                "side": "sell",
                "type": "stop",
                "status": "new",
                "stop_price": "90",
            },
            "old-limit": {
                "id": "old-limit",
                "symbol": symbol,
                "qty": "1",
                "side": "buy",
                "type": "limit",
                "status": "new",
            }
        }
        self.fills = {}
        self._next_id = 0

    def positions(self):
        if self.qty <= 1e-12:
            return []
        return [{
            "symbol": self.symbol,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "market_value": self.qty * self.current_price,
            "asset_class": self.asset_class,
        }]

    def open_orders(self):
        active = {"new", "accepted", "pending_new", "partially_filled", "cancel_pending"}
        return [
            dict(order) for order in self.orders.values()
            if order["status"].lower() in active
        ]

    def _request(self, method, path, **_kwargs):
        self.events.append(("request", method.upper(), path))
        order_id = path.rsplit("/", 1)[-1]
        if method.upper() == "DELETE":
            order = self.orders[order_id]
            order["status"] = "canceled" if self.cancel_confirms else "cancel_pending"
            return {}
        if method.upper() == "GET":
            return dict(self.orders[order_id])
        raise AssertionError(f"unexpected fake broker request: {method} {path}")

    def submit(self, symbol, side, qty, order_type, **extra):
        qty = float(qty)
        self.events.append(("submit", side, order_type, qty))
        self.submitted.append((symbol, side, order_type, qty, dict(extra)))
        if side == "sell":
            reserved_qty = sum(
                float(order["qty"])
                for order in self.open_orders()
                if order["symbol"] == symbol and order["side"] == "sell"
            )
            available_qty = max(0.0, self.qty - reserved_qty)
            if qty > available_qty + 1e-9:
                raise RuntimeError(
                    f"insufficient unreserved shares: requested={qty}, "
                    f"available={available_qty}"
                )

        if order_type in {"stop", "stop_limit"}:
            if self.stop_failures:
                self.stop_failures -= 1
                raise RuntimeError("fake protective stop rejection")
            order_id = f"stop-{self._next_id}"
            self._next_id += 1
            order = {
                "id": order_id,
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": order_type,
                "status": "new",
                **{key: str(value) for key, value in extra.items()},
            }
            self.orders[order_id] = order
            return dict(order)

        if order_type != "market":
            raise AssertionError(f"unexpected order type: {order_type}")

        order_id = f"market-{self._next_id}"
        self._next_id += 1
        if side == "sell":
            self.qty = max(0.0, self.qty - qty)
            fill_price = self.current_price
        else:
            old_notional = self.qty * self.entry_price
            new_qty = self.qty + qty
            fill_price = self.current_price
            self.entry_price = (
                (old_notional + qty * fill_price) / new_qty
                if new_qty > 0
                else 0.0
            )
            self.qty = new_qty
        fill = {
            "id": order_id,
            "status": "filled",
            "filled_qty": str(qty),
            "filled_avg_price": str(fill_price),
        }
        self.fills[order_id] = fill
        self.orders[order_id] = {
            "id": order_id,
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "status": "filled",
        }
        return dict(self.orders[order_id])

    def wait_for_fill(self, order_id):
        return dict(self.fills[order_id])


class _LaggingOpenOrdersBroker(_ReservedShareBroker):
    """Return one stale collection snapshot after individual cancel confirms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.confirmed_cancelled_ids = set()
        self.stale_snapshot_returned = False

    def _request(self, method, path, **kwargs):
        response = super()._request(method, path, **kwargs)
        order_id = path.rsplit("/", 1)[-1]
        if (
            method.upper() == "GET"
            and self.orders[order_id]["status"].lower() == "canceled"
        ):
            self.confirmed_cancelled_ids.add(order_id)
        return response

    def open_orders(self):
        active = super().open_orders()
        if self.confirmed_cancelled_ids and not self.stale_snapshot_returned:
            self.stale_snapshot_returned = True
            return active + [
                dict(self.orders[order_id])
                for order_id in sorted(self.confirmed_cancelled_ids)
            ]
        return active


class _OrderGetOutcomeBroker(_ReservedShareBroker):
    def __init__(self, *, get_failure=False, get_status=None):
        super().__init__()
        self.get_failure = get_failure
        self.get_status = get_status

    def _request(self, method, path, **kwargs):
        if method.upper() == "GET" and path.rsplit("/", 1)[-1] in self.orders:
            if self.get_failure:
                self.events.append(("request", method.upper(), path))
                raise RuntimeError("fake per-order GET failed")
            response = super()._request(method, path, **kwargs)
            if self.get_status is not None:
                response["status"] = self.get_status
            return response
        return super()._request(method, path, **kwargs)


def _open_position_row(symbol: str = "GLD", qty: float = 10.0) -> dict:
    return {
        "bot_id": "jerome_macro",
        "symbol": symbol,
        "qty": qty,
        "entry_price": 100.0,
        "notional_usd": qty * 100.0,
        "stop_price": 90.0,
        "stop_order_id": "old-stop",
        "status": "open",
    }


def _install_fake_ledger(monkeypatch, row: dict) -> _MemoryLedger:
    from contextlib import contextmanager

    ledger = _MemoryLedger(row)

    @contextmanager
    def fake_get_conn():
        yield _MemoryConnection(ledger)

    monkeypatch.setattr(bot3, "get_conn", fake_get_conn)
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    return ledger


def test_stopped_out_rows_are_limited_to_the_current_calendar_quarter(
    monkeypatch,
) -> None:
    rows = [
        {
            **_open_position_row("SLV"),
            "status": "closed",
            "exit_reason": "stop_filled",
            "closed_at": datetime(2026, 10, 8, tzinfo=timezone.utc),
        },
        {
            **_open_position_row("GLD"),
            "status": "closed",
            "exit_reason": "stop_filled",
            "closed_at": datetime(2026, 9, 30, tzinfo=timezone.utc),
        },
    ]
    _install_fake_ledger(monkeypatch, rows)

    assert bot3._stopped_out_symbols(
        datetime(2026, 10, 10, tzinfo=timezone.utc)
    ) == {"SLV"}


def test_missing_broker_position_closes_ledger_when_recorded_stop_filled(
    monkeypatch,
) -> None:
    row = _open_position_row()
    ledger = _install_fake_ledger(monkeypatch, row)
    client = _OrderGetOutcomeBroker(get_status="filled")
    client.qty = 0
    client.orders["old-stop"]["filled_at"] = "2026-10-08T13:42:00Z"

    closed = bot3._reconcile_missing_stop_fills(client, [row], [])

    assert closed == {"GLD"}
    assert ledger.rows[0]["status"] == "closed"
    assert ledger.rows[0]["closed_at"] == datetime(
        2026, 10, 8, 13, 42, tzinfo=timezone.utc
    )
    assert ledger.rows[0]["exit_reason"] == "stop_filled"


def test_missing_broker_position_with_unfilled_stop_keeps_row_open(
    monkeypatch,
) -> None:
    row = _open_position_row()
    ledger = _install_fake_ledger(monkeypatch, row)
    client = _OrderGetOutcomeBroker()
    client.qty = 0
    critical = []
    monkeypatch.setattr(bot3.logger, "critical", lambda message: critical.append(message))

    assert bot3._reconcile_missing_stop_fills(client, [row], []) == set()
    assert ledger.rows[0]["status"] == "open"
    assert any("leaving ledger row open" in message for message in critical)


def test_stop_fill_close_requires_exactly_one_open_row(monkeypatch) -> None:
    row = _open_position_row()
    ledger = _install_fake_ledger(monkeypatch, [row, dict(row)])

    with pytest.raises(RuntimeError, match="updated 2"):
        bot3._close_stop_filled_position(
            "GLD", "2026-10-08T13:42:00Z"
        )


def _run_existing_rebalance(monkeypatch, client, ledger, side, qty):
    return bot3._rebalance_existing_holding(
        client,
        {"symbol": client.symbol, "side": side, "qty": qty, "price": client.current_price},
        ledger.rows[0],
        "cycle",
    )


def test_old_sell_loop_is_rejected_when_existing_stop_reserves_shares() -> None:
    client = _ReservedShareBroker(qty=10)

    with pytest.raises(RuntimeError, match="insufficient unreserved shares"):
        client.submit("GLD", "sell", 2, "market")


def test_trim_cancels_stop_before_sell_then_arms_one_stop_at_old_price(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _ReservedShareBroker(qty=10)

    assert _run_existing_rebalance(monkeypatch, client, ledger, "sell", 3) == 1

    submissions = [event for event in client.events if event[0] == "submit"]
    assert [event[1:3] for event in submissions] == [
        ("sell", "market"),
        ("sell", "stop"),
    ]
    cancel_events = [
        (i, event) for i, event in enumerate(client.events)
        if event[:2] == ("request", "DELETE")
    ]
    market_index = next(i for i, event in enumerate(client.events) if event[:3] == ("submit", "sell", "market"))
    assert [event[2].rsplit("/", 1)[-1] for _, event in cancel_events] == [
        "old-stop", "old-limit",
    ]
    assert all(index < market_index for index, _ in cancel_events)
    stops = [order for order in client.open_orders() if order["type"] == "stop"]
    assert len(stops) == 1
    assert float(stops[0]["qty"]) == 7
    assert float(stops[0]["stop_price"]) == 90
    assert len(ledger.rows) == 1
    assert ledger.rows[0]["qty"] == 7
    assert ledger.rows[0]["entry_price"] == 100
    assert ledger.rows[0]["notional_usd"] == 700
    assert ledger.rows[0]["stop_price"] == 90
    assert ledger.rows[0]["stop_order_id"] == stops[0]["id"]
    assert ledger.insert_count == 0


def test_rearmed_stop_uses_recorded_price_and_updates_ledger_fields(monkeypatch) -> None:
    row = _open_position_row()
    row["qty"] = 9
    row["stop_price"] = 90.005
    _install_fake_ledger(monkeypatch, row)
    client = _ReservedShareBroker(qty=10, current_price=95)
    client.orders.pop("old-stop")
    remembered = []
    monkeypatch.setattr(
        bot3,
        "_remember_stop",
        lambda *args, **kwargs: remembered.append((args, kwargs)),
    )

    bot3._maintain_protective_stops(
        client,
        [{
            "symbol": "GLD",
            "qty": 10,
            "entry_price": 100,
            "current_price": 95,
            "stop_price": 90.005,
        }],
        "cycle",
        True,
    )

    stops = [order for order in client.open_orders() if order["type"] == "stop"]
    assert len(stops) == 1
    assert float(stops[0]["stop_price"]) == 90.01
    assert remembered[0][0] == ("GLD", stops[0]["id"])
    assert remembered[0][1] == {"qty": 10, "stop_price": 90.01}


def test_missing_stop_at_or_below_recorded_price_is_left_for_backstop(monkeypatch) -> None:
    client = _ReservedShareBroker(qty=10, current_price=90)
    client.orders.pop("old-stop")
    remembered = []
    critical = []
    monkeypatch.setattr(
        bot3,
        "_remember_stop",
        lambda *args, **kwargs: remembered.append((args, kwargs)),
    )
    monkeypatch.setattr(bot3.logger, "critical", lambda message: critical.append(message))

    bot3._maintain_protective_stops(
        client,
        [{
            "symbol": "GLD",
            "qty": 10,
            "entry_price": 100,
            "current_price": 90,
            "stop_price": 90,
        }],
        "cycle",
        True,
    )

    assert not [item for item in client.submitted if item[3] == "stop"]
    assert remembered == []
    assert any("deferring re-arm to software backstop" in message for message in critical)


class _BackstopFillBroker(_ReservedShareBroker):
    def wait_for_fill(self, order_id):
        return {
            **super().wait_for_fill(order_id),
            "filled_at": "2026-10-08T13:42:00Z",
        }


def test_full_software_backstop_fill_closes_row_as_stop_filled(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _BackstopFillBroker(qty=10, current_price=80)
    client.orders.pop("old-stop")

    closed = bot3._software_backstop(
        client,
        [{
            "symbol": "GLD",
            "qty": 10,
            "current_price": 80,
            "stop_price": 90,
        }],
        "cycle",
        True,
    )

    assert closed == {"GLD"}
    assert ledger.rows[0]["status"] == "closed"
    assert ledger.rows[0]["closed_at"] == datetime(
        2026, 10, 8, 13, 42, tzinfo=timezone.utc
    )
    assert ledger.rows[0]["exit_reason"] == "stop_filled"


def test_top_up_arms_one_stop_for_new_total_and_updates_existing_row(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _ReservedShareBroker(qty=10, current_price=110)

    assert _run_existing_rebalance(monkeypatch, client, ledger, "buy", 2) == 1

    stops = [order for order in client.open_orders() if order["type"] == "stop"]
    assert len(stops) == 1
    assert float(stops[0]["qty"]) == 12
    assert float(stops[0]["stop_price"]) == pytest.approx(91.5)
    assert len(ledger.rows) == 1
    assert ledger.rows[0]["qty"] == 12
    assert ledger.rows[0]["entry_price"] == pytest.approx(101.6666666667)
    assert ledger.rows[0]["notional_usd"] == pytest.approx(1220)
    assert ledger.rows[0]["stop_price"] == pytest.approx(91.5)
    assert ledger.rows[0]["stop_order_id"] == stops[0]["id"]
    assert ledger.insert_count == 0


def test_top_up_stop_never_falls_below_recorded_stop(monkeypatch) -> None:
    row = _open_position_row()
    row["stop_price"] = 95
    ledger = _install_fake_ledger(monkeypatch, row)
    client = _ReservedShareBroker(qty=10, current_price=110)

    assert _run_existing_rebalance(monkeypatch, client, ledger, "buy", 2) == 1

    stops = [order for order in client.open_orders() if order["type"] == "stop"]
    assert len(stops) == 1
    assert float(stops[0]["stop_price"]) == 95
    assert ledger.rows[0]["stop_price"] == 95


def test_full_exit_closes_row_without_arming_a_stop(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _ReservedShareBroker(qty=10)

    assert _run_existing_rebalance(monkeypatch, client, ledger, "sell", 10) == 1

    assert client.qty == 0
    assert not [order for order in client.open_orders() if order["type"] in {"stop", "stop_limit"}]
    assert ledger.rows[0]["status"] == "closed"
    assert ledger.rows[0]["exit_reason"] == "rebalance_full_exit"
    assert ledger.insert_count == 0


def test_confirmed_cancelled_order_in_stale_open_list_allows_rebalance(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _LaggingOpenOrdersBroker(qty=10)

    assert _run_existing_rebalance(monkeypatch, client, ledger, "sell", 3) == 1

    assert any(order[2] == "market" for order in client.submitted)
    assert ledger.rows[0]["qty"] == 7
    assert client.stale_snapshot_returned


def test_unconfirmed_cancel_refuses_to_place_market_order(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _ReservedShareBroker(qty=10, cancel_confirms=False)

    with pytest.raises(RuntimeError, match="cancellation was not confirmed"):
        _run_existing_rebalance(monkeypatch, client, ledger, "sell", 3)

    assert not client.submitted
    assert client.qty == 10
    assert ledger.rows[0]["status"] == "open"
    assert ledger.insert_count == 0


@pytest.mark.parametrize(
    ("get_failure", "get_status"),
    [(True, None), (False, "filled")],
    ids=["GET-fails", "GET-not-canceled"],
)
def test_per_order_get_failure_or_other_status_refuses_rebalance(
    monkeypatch, get_failure, get_status
) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _OrderGetOutcomeBroker(
        get_failure=get_failure,
        get_status=get_status,
    )

    with pytest.raises(RuntimeError, match="cancellation was not confirmed"):
        _run_existing_rebalance(monkeypatch, client, ledger, "sell", 3)

    assert not client.submitted
    assert client.qty == 10
    assert ledger.rows[0]["status"] == "open"
    assert ledger.insert_count == 0


def test_transient_position_read_failure_retries_before_rearming_stop(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _ReservedShareBroker(qty=10)
    original_positions = client.positions
    failed_once = False

    def flaky_positions():
        nonlocal failed_once
        if client.qty == 7 and not failed_once:
            failed_once = True
            raise RuntimeError("temporary broker position-read failure")
        return original_positions()

    client.positions = flaky_positions

    assert _run_existing_rebalance(monkeypatch, client, ledger, "sell", 3) == 1

    stops = [order for order in client.open_orders() if order["type"] == "stop"]
    assert failed_once
    assert len(stops) == 1
    assert float(stops[0]["qty"]) == 7
    assert ledger.rows[0]["qty"] == 7
    assert ledger.rows[0]["stop_order_id"] == stops[0]["id"]
    assert ledger.insert_count == 0


def test_two_stop_failures_flatten_and_close_the_position_row(monkeypatch) -> None:
    ledger = _install_fake_ledger(monkeypatch, _open_position_row())
    client = _ReservedShareBroker(qty=10, stop_failures=2)

    with pytest.raises(RuntimeError, match="position was flattened"):
        _run_existing_rebalance(monkeypatch, client, ledger, "sell", 3)

    assert client.qty == 0
    assert [item[2] for item in client.submitted].count("stop") == 2
    assert [item[2] for item in client.submitted].count("market") == 2
    assert ledger.rows[0]["status"] == "closed"
    assert ledger.rows[0]["exit_reason"] == "rebalance_stop_arm_failed"
    assert ledger.insert_count == 0


def test_broker_position_carries_crypto_class_for_stop_coverage(monkeypatch) -> None:
    client = object.__new__(bot3.AlpacaBot3)
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **kwargs: [{
            "symbol": "BTCUSD",
            "qty": "0.5",
            "avg_entry_price": "60000",
            "current_price": "61000",
            "market_value": "30500",
            "asset_class": "crypto",
        }],
    )

    position = client.positions()[0]
    undersized_stop = {
        "symbol": position["symbol"],
        "qty": "0.1",
        "side": "sell",
        "type": "stop_limit",
    }

    assert position["asset_class"] == "crypto"
    assert not bot3._covers(position, undersized_stop)


@pytest.mark.parametrize(
    ("side", "held", "stopped_out", "quarterly", "expected_orders", "expected_entries"),
    [
        ("sell", True, frozenset(), True, 1, 0),
        ("buy", True, frozenset(), True, 1, 0),
        ("buy", False, frozenset(), True, 1, 1),
        ("buy", False, frozenset({"GLD"}), False, 0, 0),
        ("buy", False, frozenset({"GLD"}), True, 1, 1),
        (
            "buy",
            True,
            frozenset(set(bot3.ASSETS) - {"GLD"}),
            False,
            0,
            0,
        ),
        ("buy", False, frozenset(bot3.ASSETS), False, 0, 0),
    ],
)
def test_cycle_routes_held_symbols_through_existing_position_rebalance(
    monkeypatch,
    side,
    held,
    stopped_out,
    quarterly,
    expected_orders,
    expected_entries,
) -> None:
    row = _open_position_row() if held else None
    client = _ReservedShareBroker(qty=10 if held else 0)
    client.account = lambda: {"equity": 1_000, "cash": 500, "buying_power": 500}
    client.latest_prices = lambda: {"GLD": 105}
    plan_item = {"symbol": "GLD", "side": side, "qty": 2, "price": 105, "notional": 210}
    targets = {symbol: 0.25 for symbol in bot3.ASSETS}
    routed = []
    new_entries = []
    guard_calls = []
    plan_calls = []

    monkeypatch.setattr(bot3, "ensure_bot3_tables", lambda: None)
    monkeypatch.setattr(bot3, "AlpacaBot3", lambda *args, **kwargs: client)
    monkeypatch.setattr(bot3, "_reconcile_missing_stop_fills", lambda *args: set())
    monkeypatch.setattr(
        bot3, "_stopped_out_symbols", lambda _now: set(stopped_out)
    )
    monkeypatch.setattr(
        bot3, "_strategy_positions", lambda: [row] if row is not None else []
    )
    monkeypatch.setattr(bot3, "_maintain_protective_stops", lambda *args: None)
    monkeypatch.setattr(bot3, "_software_backstop", lambda *args: set())
    monkeypatch.setattr(bot3, "_nyse_session_open", lambda _now: True)
    monkeypatch.setattr(
        bot3, "_quarterly_rebalance_date", lambda _now: quarterly
    )
    monkeypatch.setattr(bot3, "_load_recent_closes", lambda: {})
    monkeypatch.setattr(
        bot3, "inverse_vol_targets", lambda _closes: (targets, {})
    )
    monkeypatch.setattr(
        bot3,
        "_apply_live_crypto_cap",
        lambda _cycle_id, weights, _base: (weights, 1_000, {}, 50, 50),
    )
    monkeypatch.setattr(
        bot3,
        "_plan_orders",
        lambda *args, **kwargs: (plan_calls.append(args) or [plan_item]),
    )
    monkeypatch.setattr(
        bot3,
        "_fresh_buy_guard",
        lambda *args: (guard_calls.append(args) or True, {}),
    )
    monkeypatch.setattr(
        bot3,
        "_rebalance_existing_holding",
        lambda broker, item, existing, cycle_id: (
            routed.append((broker, item, existing, cycle_id)) or 1
        ),
    )
    monkeypatch.setattr(
        bot3,
        "_place_confirmed_entry",
        lambda *args: (new_entries.append(args) or {"status": "filled"}),
    )
    monkeypatch.setattr(bot3, "_log_decision", lambda *args, **kwargs: None)

    result = bot3.run_bot3_cycle(
        profile={
            "ALPACA_JEROME_API_KEY": "test-key",
            "ALPACA_JEROME_SECRET_KEY": "test-secret",
        }
    )

    assert result["orders"] == expected_orders
    eligible = (
        set(bot3.ASSETS)
        if quarterly
        else set(bot3.ASSETS) - set(stopped_out)
    )
    held_eligible = ({"GLD"} if held else set()) & eligible
    should_plan = (
        quarterly
        or (not held and bool(eligible))
        or (held and held_eligible != eligible)
    )
    assert len(routed) == int(
        held and should_plan and (side != "buy" or "GLD" in eligible)
    )
    assert len(new_entries) == expected_entries
    if stopped_out == frozenset(bot3.ASSETS) and not quarterly:
        assert plan_calls == []
    if held:
        if routed:
            assert routed[0][1] == plan_item
            assert routed[0][2]["stop_price"] == row["stop_price"]
    assert len(guard_calls) == int(
        side == "buy" and should_plan and "GLD" in eligible
    )