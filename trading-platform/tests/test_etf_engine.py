from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "trading-platform"))
sys.path.insert(1, str(_ROOT / "kraken-bot"))

# Other Kraken tests can load kraken-bot/db.py as the top-level "db" module.
# Remove that non-package alias so this test uses trading-platform/db.
loaded_db = sys.modules.get("db")
if loaded_db is not None and not hasattr(loaded_db, "__path__"):
    del sys.modules["db"]

from alpaca_etf_engine import AlpacaEtfEngine
import alpaca_etf_engine as etf_engine_module
from db import postgres


def test_cash_park_symbol_variants_skip_engine_stop_management():
    engine = object.__new__(AlpacaEtfEngine)

    assert engine.ensure_protective_stop("oracle", "s/gov", 10.0) is None
    engine.reconcile_protective_stops(
        "oracle",
        [
            {"direction": "long", "symbol": "s-gov", "qty": 10, "stop_price": None},
        ],
    )


class _FakeCursor:
    def __init__(self, rows, trade_row=None):
        self.rows = rows
        self.trade_row = trade_row
        self._result = []
        self._fetchone_result = None
        self.rowcount = -1
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split()).lower()
        placeholder_count = sql.count("%s")
        parameter_count = 0 if params is None else len(params)
        if placeholder_count != parameter_count:
            raise TypeError(
                f"placeholder/parameter mismatch: {placeholder_count} placeholders "
                f"for {parameter_count} parameters"
            )
        self.executed.append((normalized, params))
        if normalized.startswith("select id, bot_id, symbol, status"):
            self._result = [
                (row["id"], row["bot_id"], row["symbol"], row["status"])
                for row in self.rows
                if row["current_qty"] is None
                and row["status"] in {"open", "closed"}
            ]
            self.rowcount = len(self._result)
            return

        if normalized.startswith("select id, bot_id, symbol, qty, current_qty"):
            self._result = [
                (
                    row["id"],
                    row["bot_id"],
                    row["symbol"],
                    row["qty"],
                    row["current_qty"],
                )
                for row in self.rows
                if row["status"] == "open"
                and (row.get("scaled_out_tp1") or row.get("scaled_out_tp2"))
                and row["current_qty"] == row.get("qty")
            ]
            self.rowcount = len(self._result)
            return

        if normalized.startswith("select id, symbol"):
            bot_id = params[0]
            self._result = [
                (row["id"], row["symbol"])
                for row in self.rows
                if row["bot_id"] == bot_id and row["status"] == "open"
            ]
            self.rowcount = len(self._result)
            return

        if "set current_qty = 0" in normalized:
            changed = 0
            for row in self.rows:
                if row["status"] == "closed" and row["current_qty"] != 0:
                    row["current_qty"] = 0
                    changed += 1
            self.rowcount = changed
            return

        if "set current_qty = %s" in normalized:
            broker_qty, row_id = params[0], params[1]
            expected_qty = params[2] if len(params) > 2 else None
            bot_id = params[2] if "bot_id = %s" in normalized and len(params) > 2 else None
            changed = 0
            for row in self.rows:
                if (
                    row["id"] == row_id
                    and (bot_id is None or row["bot_id"] == bot_id)
                    and (
                        "current_qty = qty" not in normalized
                        or row["current_qty"] == row.get("qty") == expected_qty
                    )
                ):
                    row["current_qty"] = broker_qty
                    changed = 1
                    break
            self.rowcount = changed
            return

        if normalized.startswith("insert into alpaca_etf_positions"):
            self._fetchone_result = None
            self.rowcount = 1
            return

        if normalized.startswith("update alpaca_etf_positions") and "set status" in normalized:
            exit_reason, realised_pnl, bot_id, symbol = params
            self._fetchone_result = None
            self.rowcount = 0
            for row in self.rows:
                if (
                    row["bot_id"] == bot_id
                    and row["symbol"] == symbol
                    and row["status"] == "open"
                ):
                    row["status"] = "closed"
                    row["current_qty"] = 0
                    row["exit_reason"] = exit_reason
                    row["realised_pnl"] = realised_pnl
                    self._fetchone_result = (row["id"],)
                    self.rowcount = 1
                    break
            return

        if normalized.startswith("select trade_id, intended_price"):
            self._fetchone_result = self.trade_row
            self.rowcount = 1 if self.trade_row else 0
            return

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._fetchone_result


class _FakeConnection:
    def __init__(self, rows, trade_row=None):
        self.cursor_obj = _FakeCursor(rows, trade_row)
        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_count += 1


class _FakeApi:
    def __init__(self, positions=None, error=None, order_status="filled", filled_qty="10"):
        self.positions = positions or []
        self.error = error
        self.list_positions_calls = 0
        self.order_status = order_status
        self.filled_qty = filled_qty

    def list_positions(self):
        self.list_positions_calls += 1
        if self.error is not None:
            raise self.error
        return self.positions

    def submit_order(self, **_kwargs):
        return SimpleNamespace(id="sale-1")

    def get_order(self, _order_id):
        return SimpleNamespace(
            id="sale-1",
            status=self.order_status,
            filled_qty=self.filled_qty,
        )


def _rows():
    return [
        {"id": 1, "bot_id": "oracle", "symbol": "SPY", "status": "closed", "current_qty": None},
        {"id": 2, "bot_id": "oracle", "symbol": "E/WY", "status": "open", "current_qty": None},
        {"id": 3, "bot_id": "oracle", "symbol": "QQQ", "status": "canceled", "current_qty": None},
        {"id": 4, "bot_id": "oracle", "symbol": "GREK", "status": "open", "current_qty": 7},
    ]


def _engine(monkeypatch, rows, api, degradation_records=None, trade_row=None):
    connection = _FakeConnection(rows, trade_row)
    monkeypatch.setattr(postgres, "get_conn", lambda: connection)
    monkeypatch.setattr(postgres, "is_pg_available", lambda: True)
    if degradation_records is not None:
        monkeypatch.setattr(
            "core.degradation_tracker.record_degradation",
            lambda **kwargs: degradation_records.append(kwargs),
        )
    engine = object.__new__(AlpacaEtfEngine)
    engine.api = api
    return engine, connection


def test_current_qty_backfill_sets_closed_rows_to_zero(monkeypatch):
    rows = _rows()
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="E/WY", qty="43.355")]),
    )

    engine._backfill_current_qty()

    assert rows[0]["current_qty"] == 0


def test_current_qty_backfill_sets_open_rows_by_canonical_symbol(monkeypatch):
    rows = _rows()
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="EWY", qty="43.355")]),
    )

    engine._backfill_current_qty()

    assert rows[1]["current_qty"] == "43.355"


def test_current_qty_backfill_uses_rest_list_positions_method(monkeypatch):
    rows = _rows()
    api = _FakeApi([SimpleNamespace(symbol="E/WY", qty="43.355")])
    engine, _connection = _engine(monkeypatch, rows, api)

    engine._backfill_current_qty()

    assert api.list_positions_calls == 1


def test_current_qty_backfill_leaves_cancelled_rows_untouched(monkeypatch):
    rows = _rows()
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="E/WY", qty="43.355")]),
    )

    engine._backfill_current_qty()

    assert rows[2]["current_qty"] is None


def test_current_qty_backfill_leaves_populated_rows_untouched(monkeypatch):
    rows = _rows()
    rows[1]["current_qty"] = "43.355"
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="GREK", qty="99")]),
    )

    engine._backfill_current_qty()

    assert rows[3]["current_qty"] == 7
    assert engine.api.list_positions_calls == 0


def test_current_qty_backfill_broker_failure_updates_closed_and_records_degradation(
    monkeypatch,
):
    rows = _rows()
    degradation_records = []
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi(error=RuntimeError("broker unavailable")),
        degradation_records,
    )

    engine._backfill_current_qty()

    assert rows[0]["current_qty"] == 0
    assert rows[1]["current_qty"] is None
    assert rows[2]["current_qty"] is None
    assert len(degradation_records) == 1
    assert degradation_records[0]["error_type"] == "etf_current_qty_broker_read_failed"


def test_current_qty_backfill_is_idempotent(monkeypatch):
    rows = _rows()
    api = _FakeApi([SimpleNamespace(symbol="EWY", qty="43.355")])
    engine, _connection = _engine(monkeypatch, rows, api)

    engine._backfill_current_qty()
    after_first = [dict(row) for row in rows]
    engine._backfill_current_qty()

    assert rows == after_first
    assert api.list_positions_calls == 1


def test_fake_cursor_rejects_placeholder_parameter_mismatch():
    cursor = _FakeCursor([])

    with pytest.raises(TypeError, match="placeholder/parameter mismatch"):
        cursor.execute("SELECT %s", (1, 2))


def _close_engine(monkeypatch, rows, api, degradation_records=None):
    engine, connection = _engine(
        monkeypatch,
        rows,
        api,
        degradation_records,
    )
    engine.is_market_open = lambda: True
    engine._has_pending_owned_exit = lambda *_args: False
    engine._cancel_owned_stop = lambda *_args: True
    engine._cancel_and_confirm_order = lambda *_args: True
    engine.ensure_protective_stop = lambda *_args, **_kwargs: None
    engine._exit_client_order_prefix = lambda *_args: "test-exit"
    monkeypatch.setattr(
        etf_engine_module,
        "submit_with_unique_client_order_id",
        lambda submitter, _prefix: (submitter("client-order-1"), "client-order-1"),
    )
    return engine, connection


def test_record_open_initializes_current_qty_to_entry_qty(monkeypatch):
    rows = []
    engine, connection = _engine(monkeypatch, rows, _FakeApi())
    monkeypatch.setattr("analysis.trade_journal.log_trade", lambda **_kwargs: None)

    assert engine.record_open(
        "oracle", "SPY", "long", 12.5, 500.0, None, 6250.0,
        450.0, 525.0, 560.0, 5,
    )

    insert_sql, insert_params = connection.cursor_obj.executed[0]
    assert "current_qty" in insert_sql
    assert insert_params[3] == 12.5
    assert insert_params[4] == 12.5


def test_close_partial_filled_syncs_current_qty_from_broker(monkeypatch):
    rows = [{
        "id": 10, "bot_id": "oracle", "symbol": "E/WY", "status": "open",
        "qty": 65.0, "current_qty": 65.0,
    }]
    engine, _connection = _close_engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="EWY", qty="43.355")]),
    )

    assert engine.close_partial(
        "EWY", 21.645, bot_id="oracle", stop_price=70.0,
    )
    assert rows[0]["current_qty"] == "43.355"


def test_close_partial_partial_fill_syncs_residual_and_returns_true(monkeypatch):
    rows = [{
        "id": 11, "bot_id": "oracle", "symbol": "SPY", "status": "open",
        "qty": 100.0, "current_qty": 100.0,
    }]
    engine, _connection = _close_engine(
        monkeypatch,
        rows,
        _FakeApi(
            [SimpleNamespace(symbol="SPY", qty="97.5")],
            order_status="new",
            filled_qty="2.5",
        ),
    )
    monkeypatch.setattr(etf_engine_module.time, "sleep", lambda _seconds: None)
    clock = iter((0.0, 0.0, 21.0))
    monkeypatch.setattr(etf_engine_module.time, "monotonic", lambda: next(clock))

    assert engine.close_partial(
        "SPY", 10.0, bot_id="oracle", stop_price=450.0,
    )
    assert rows[0]["current_qty"] == "97.5"


def test_close_partial_sync_failure_preserves_success_and_records_degradation(monkeypatch):
    rows = [{
        "id": 12, "bot_id": "oracle", "symbol": "SPY", "status": "open",
        "qty": 100.0, "current_qty": 100.0,
    }]
    degradation_records = []
    engine, _connection = _close_engine(
        monkeypatch,
        rows,
        _FakeApi(error=RuntimeError("broker unavailable")),
        degradation_records,
    )

    assert engine.close_partial(
        "SPY", 10.0, bot_id="oracle", stop_price=450.0,
    )
    assert rows[0]["current_qty"] == 100.0
    assert degradation_records[-1]["error_type"] == "etf_current_qty_sync_failed"


def test_record_close_sets_current_qty_to_zero(monkeypatch):
    rows = [{
        "id": 13, "bot_id": "oracle", "symbol": "SPY", "status": "open",
        "qty": 100.0, "current_qty": 97.5,
    }]
    engine, _connection = _engine(monkeypatch, rows, _FakeApi())
    monkeypatch.setattr("analysis.trade_journal.close_trade", lambda **_kwargs: None)

    engine.record_close("oracle", "SPY", "trailing_stop", realised_pnl=25.0)

    assert rows[0]["status"] == "closed"
    assert rows[0]["current_qty"] == 0


def test_record_close_passes_closing_bot_and_selects_its_trade(monkeypatch):
    rows = [{
        "id": 14, "bot_id": "oracle", "symbol": "SPY", "status": "open",
        "qty": 10.0, "current_qty": 10.0,
    }]
    trade_id = "ETF-oracle-SPY-20261002"
    engine, connection = _engine(
        monkeypatch,
        rows,
        _FakeApi(),
        trade_row=(trade_id, 100.0),
    )
    closed_trades = []
    monkeypatch.setattr(
        "analysis.trade_journal.close_trade",
        lambda **kwargs: closed_trades.append(kwargs),
    )

    engine.record_close("oracle", "SPY", "take_profit", realised_pnl=25.0)

    assert closed_trades == [{
        "trade_id": trade_id,
        "pnl_percentage": 1.0,
        "realized_pnl": 25.0,
        "exit_reason": "take_profit",
        "bot_id": "oracle",
    }]
    trade_select = next(
        entry for entry in connection.cursor_obj.executed
        if entry[0].startswith("select trade_id, intended_price")
    )
    assert trade_select[1] == (
        "SPY",
        "ETF-oracle-SPY-",
        "ETF-oracle-SPY-",
    )


def test_backfill_repairs_stale_closed_and_scaled_out_rows(monkeypatch):
    rows = [
        {
            "id": 20, "bot_id": "oracle", "symbol": "SPY", "status": "closed",
            "qty": 15.0, "current_qty": 15.0,
        },
        {
            "id": 21, "bot_id": "oracle", "symbol": "E/WY", "status": "open",
            "qty": 65.0, "current_qty": 65.0,
            "scaled_out_tp1": True, "scaled_out_tp2": False,
        },
    ]
    api = _FakeApi([SimpleNamespace(symbol="EWY", qty="43.355")])
    engine, connection = _engine(
        monkeypatch,
        rows,
        api,
    )

    engine._backfill_current_qty()

    assert rows[0]["current_qty"] == 0
    assert rows[1]["current_qty"] == "43.355"
    scaled_update = next(
        (
            (sql, params)
            for sql, params in connection.cursor_obj.executed
            if "current_qty = qty" in sql and "qty = %s" in sql
        ),
        None,
    )
    assert scaled_update is not None and len(scaled_update[1]) == 3
    after_first = [dict(row) for row in rows]

    engine._backfill_current_qty()

    assert rows == after_first
    assert api.list_positions_calls == 1


def test_backfill_scaled_out_missing_broker_position_fails_closed(monkeypatch):
    rows = [{
        "id": 22, "bot_id": "oracle", "symbol": "SPY", "status": "open",
        "qty": 100.0, "current_qty": 100.0,
        "scaled_out_tp1": True, "scaled_out_tp2": False,
    }]
    degradation_records = []
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([]),
        degradation_records,
    )

    engine._backfill_current_qty()

    assert rows[0]["current_qty"] == 100.0
    assert degradation_records[-1]["error_type"] == (
        "etf_current_qty_broker_position_missing"
    )


def test_backfill_scaled_out_broker_failure_fails_closed(monkeypatch):
    rows = [{
        "id": 23, "bot_id": "oracle", "symbol": "SPY", "status": "open",
        "qty": 100.0, "current_qty": 100.0,
        "scaled_out_tp1": True, "scaled_out_tp2": False,
    }]
    degradation_records = []
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi(error=RuntimeError("broker unavailable")),
        degradation_records,
    )

    engine._backfill_current_qty()

    assert rows[0]["current_qty"] == 100.0
    assert degradation_records[-1]["error_type"] == "etf_current_qty_broker_read_failed"


def test_run_exit_checks_uses_immutable_qty_for_scale_out(monkeypatch):
    engine = object.__new__(AlpacaEtfEngine)
    captured = []
    db_position = {
        "symbol": "SPY",
        "qty": 100.0,
        "current_qty": 20.0,
        "entry_price": 500.0,
        "stop_price": 450.0,
    }
    fresh_position = dict(db_position)

    engine.update_trailing_stop = lambda *_args: None
    engine.get_db_positions = lambda _bot_id: [fresh_position]
    engine.ensure_protective_stop = lambda *_args: None
    engine.check_stop_hit = lambda *_args: False
    engine.check_min_hold = lambda *_args: True
    engine.check_tp2_hit = lambda *_args: True
    engine.close_partial = (
        lambda _symbol, scale_qty, **_kwargs: captured.append(scale_qty) or True
    )
    engine.mark_scaled_out = lambda *_args, **_kwargs: None

    engine.run_exit_checks(
        "oracle",
        db_position,
        [{"symbol": "SPY", "current_price": 550.0}],
        trail_pct=0.08,
    )

    assert captured == pytest.approx([33.3])


class _ProtectiveStopApi:
    def __init__(
        self,
        position,
        current_stop,
        *,
        replace_error=None,
        stop_read_error=None,
        position_read_error=None,
    ):
        self.position = position
        self.current_stop = current_stop
        self.replace_error = replace_error or RuntimeError("order chain not fully replaced")
        self.stop_read_error = stop_read_error
        self.position_read_error = position_read_error
        self.list_positions_calls = 0
        self.get_order_calls = 0
        self.replace_order_calls = []
        self.submit_order_calls = []

    def list_positions(self):
        self.list_positions_calls += 1
        if self.position_read_error is not None:
            raise self.position_read_error
        return [self.position]

    def get_order(self, _order_id):
        self.get_order_calls += 1
        if self.stop_read_error is not None:
            raise self.stop_read_error
        return self.current_stop

    def replace_order(self, order_id, **kwargs):
        self.replace_order_calls.append((order_id, kwargs))
        raise self.replace_error

    def submit_order(self, **kwargs):
        self.submit_order_calls.append(kwargs)
        return SimpleNamespace(id="fresh-stop")


def _protective_stop_engine(
    monkeypatch,
    api,
    existing_stop,
    degradation_records=None,
    *,
    wait_result=True,
    wait_calls=None,
):
    engine = object.__new__(AlpacaEtfEngine)
    engine.api = api
    engine._has_pending_owned_exit = lambda *_args: False
    engine.get_positions = lambda: [{"symbol": "SPY", "qty": 10.0}]
    engine._find_owned_stop = lambda *_args: existing_stop
    wait_calls = wait_calls if wait_calls is not None else []

    def _wait_for_shares_free(*args):
        wait_calls.append(args)
        return wait_result

    engine._wait_for_shares_free = _wait_for_shares_free
    stored = []
    engine._store_stop_order_id = (
        lambda *args, **kwargs: stored.append((args, kwargs))
    )
    if degradation_records is not None:
        monkeypatch.setattr(
            "core.degradation_tracker.record_degradation",
            lambda **kwargs: degradation_records.append(kwargs),
        )
    return engine, stored


def _protective_stop_fixtures(
    *,
    current_status="new",
    current_qty="10",
    position_qty="10",
    stop_read_error=None,
    position_read_error=None,
):
    existing_stop = SimpleNamespace(
        id="existing-stop",
        symbol="SPY",
        qty="10",
        stop_price="99",
        status="new",
        side="sell",
        type="stop",
        asset_class="us_equity",
    )
    current_stop = SimpleNamespace(
        id="existing-stop",
        symbol="SPY",
        qty=current_qty,
        stop_price="99",
        status=current_status,
        side="sell",
        type="stop",
        asset_class="us_equity",
    )
    live_position = SimpleNamespace(
        symbol="SPY",
        qty=position_qty,
        side="long",
        asset_class="us_equity",
    )
    api = _ProtectiveStopApi(
        live_position,
        current_stop,
        stop_read_error=stop_read_error,
        position_read_error=position_read_error,
    )
    return api, existing_stop


def _capture_protective_stop_critical_path(monkeypatch):
    critical_inserts = []
    alerts = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            critical_inserts.append((" ".join(sql.split()).lower(), params))

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(postgres, "get_conn", lambda: Connection())
    monkeypatch.setattr(postgres, "is_pg_available", lambda: True)
    from notifications import discord

    monkeypatch.setattr(
        discord,
        "notify_capital_risk",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )
    return critical_inserts, alerts


def test_replace_failure_with_active_covering_stop_is_warning_only(monkeypatch, caplog):
    degradation_records = []
    api, existing_stop = _protective_stop_fixtures()
    engine, _stored = _protective_stop_engine(
        monkeypatch, api, existing_stop, degradation_records
    )
    alerts = []
    from notifications import discord

    monkeypatch.setattr(
        discord,
        "notify_capital_risk",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    result = engine.ensure_protective_stop("oracle", "SPY", 100.0)

    assert result == "existing-stop"
    assert api.replace_order_calls[0][0] == "existing-stop"
    assert api.get_order_calls == 1
    assert api.list_positions_calls == 1
    assert len(degradation_records) == 1
    assert degradation_records[0]["severity"] == "warning"
    assert degradation_records[0]["error_type"] == "protective_stop_ratchet_deferred"
    assert "stop ratchet deferred" in caplog.text
    assert "existing_stop_id=existing-stop" in caplog.text
    assert "existing_stop_price=$99.00" in caplog.text
    assert "desired_stop_price=$100.00" in caplog.text
    assert not alerts


def test_replace_failure_with_active_noncovering_stop_keeps_critical_path(monkeypatch):
    api, existing_stop = _protective_stop_fixtures(current_qty="4", position_qty="10")
    engine, _stored = _protective_stop_engine(monkeypatch, api, existing_stop)
    critical_inserts, alerts = _capture_protective_stop_critical_path(monkeypatch)

    result = engine.ensure_protective_stop("oracle", "SPY", 100.0)

    assert result is None
    assert api.list_positions_calls == 1
    assert api.submit_order_calls == []
    assert len(critical_inserts) == 1
    assert "insert into system_degradations" in critical_inserts[0][0]
    assert critical_inserts[0][1][1:3] == (
        "critical",
        "protective_stop_failed",
    )
    assert len(alerts) == 1


def test_replace_failure_with_terminal_stop_keeps_fresh_submit_path(monkeypatch):
    api, existing_stop = _protective_stop_fixtures(current_status="canceled")
    engine, stored = _protective_stop_engine(monkeypatch, api, existing_stop)
    critical_inserts, alerts = _capture_protective_stop_critical_path(monkeypatch)
    monkeypatch.setattr(
        etf_engine_module,
        "submit_with_unique_client_order_id",
        lambda submitter, _prefix: (submitter("test-client-order"), "test-client-order"),
    )

    result = engine.ensure_protective_stop("oracle", "SPY", 100.0)

    assert result == "fresh-stop"
    assert api.list_positions_calls == 0
    assert api.submit_order_calls[0]["symbol"] == "SPY"
    assert api.submit_order_calls[0]["side"] == "sell"
    assert api.submit_order_calls[0]["type"] == "stop"
    assert len(stored) == 1
    assert not critical_inserts
    assert not alerts


def test_replace_failure_when_stop_reread_fails_uses_guarded_fresh_submit(monkeypatch):
    api, existing_stop = _protective_stop_fixtures(
        stop_read_error=RuntimeError("stop reread unavailable")
    )
    wait_calls = []
    engine, stored = _protective_stop_engine(
        monkeypatch,
        api,
        existing_stop,
        wait_calls=wait_calls,
    )
    critical_inserts, alerts = _capture_protective_stop_critical_path(monkeypatch)
    monkeypatch.setattr(
        etf_engine_module,
        "submit_with_unique_client_order_id",
        lambda submitter, _prefix: (submitter("test-client-order"), "test-client-order"),
    )

    result = engine.ensure_protective_stop("oracle", "SPY", 100.0)

    assert result == "fresh-stop"
    assert wait_calls == [("SPY", 10)]
    assert api.submit_order_calls[0]["symbol"] == "SPY"
    assert api.submit_order_calls[0]["side"] == "sell"
    assert api.submit_order_calls[0]["type"] == "stop"
    assert len(stored) == 1
    assert not critical_inserts
    assert not alerts


def test_replace_failure_when_position_reread_fails_keeps_critical_path(monkeypatch):
    api, existing_stop = _protective_stop_fixtures(
        position_read_error=RuntimeError("position reread unavailable")
    )
    wait_calls = []
    engine, _stored = _protective_stop_engine(
        monkeypatch,
        api,
        existing_stop,
        wait_calls=wait_calls,
    )
    critical_inserts, alerts = _capture_protective_stop_critical_path(monkeypatch)

    result = engine.ensure_protective_stop("oracle", "SPY", 100.0)

    assert result is None
    assert api.list_positions_calls == 1
    assert api.submit_order_calls == []
    assert wait_calls == []
    assert len(critical_inserts) == 1
    assert critical_inserts[0][1][1:3] == (
        "critical",
        "protective_stop_failed",
    )
    assert len(alerts) == 1


def test_replace_failure_when_stop_reread_fails_and_shares_stay_reserved(
    monkeypatch,
):
    api, existing_stop = _protective_stop_fixtures(
        stop_read_error=RuntimeError("stop reread unavailable")
    )
    wait_calls = []
    engine, _stored = _protective_stop_engine(
        monkeypatch,
        api,
        existing_stop,
        wait_result=False,
        wait_calls=wait_calls,
    )
    critical_inserts, alerts = _capture_protective_stop_critical_path(monkeypatch)

    result = engine.ensure_protective_stop("oracle", "SPY", 100.0)

    assert result is None
    assert wait_calls == [("SPY", 10)]
    assert api.submit_order_calls == []
    assert len(critical_inserts) == 1
    assert critical_inserts[0][1][1:3] == (
        "critical",
        "protective_stop_failed",
    )
    assert len(alerts) == 1
