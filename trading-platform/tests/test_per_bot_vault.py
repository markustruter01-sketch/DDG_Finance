from __future__ import annotations

import pathlib
import sys
from enum import Enum
from types import ModuleType, SimpleNamespace

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "trading-platform"))

from execution import per_bot_vault as vault


class _BrokerStatus(Enum):
    FILLED = "filled"


class _FakeCursor:
    def __init__(
        self,
        *,
        queue_rows=None,
        report_rows=None,
        inspection_rows=None,
        skim_rows=None,
        read_only=False,
    ):
        self.queue_rows = queue_rows or []
        self.report_rows = report_rows or []
        self.inspection_rows = inspection_rows or []
        self.skim_rows = skim_rows or []
        self.read_only = read_only
        self.description = []
        self.rowcount = -1
        self._result = []
        self._fetchone_result = None
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
        if self.read_only and not normalized.startswith("select"):
            raise AssertionError(f"read-only fake rejected mutation SQL: {sql}")
        self.executed.append((normalized, params))
        self._fetchone_result = None

        if normalized.startswith("select bot_id, bil_order_id"):
            self._result = [
                (
                    row["bot_id"],
                    row["bil_order_id"],
                    row["voo_order_id"],
                    row["bil_filled_usd"],
                    row["voo_filled_usd"],
                    row["pending_cash_usd"],
                    row["pending_bil_usd"],
                    row["pending_voo_usd"],
                )
                for row in self.queue_rows
                if row["status"] == "submitted"
                and (row["bil_order_id"] or row["voo_order_id"])
            ]
            return

        if normalized.startswith("select q.bot_id, q.pending_cash_usd"):
            self._result = [
                (
                    row["bot_id"],
                    row["pending_cash_usd"],
                    row["pending_bil_usd"],
                    row["pending_voo_usd"],
                    row["bil_order_id"],
                    row["voo_order_id"],
                    row["bil_filled_usd"],
                    row["voo_filled_usd"],
                    row["attempts"],
                    row["status"],
                )
                for row in self.queue_rows
            ]
            return

        if normalized.startswith("select a.bot_id, a.activation_enabled, q.pending_cash_usd"):
            names = [
                "bot_id",
                "activation_enabled",
                "pending_cash_usd",
                "pending_bil_usd",
                "pending_voo_usd",
                "bil_order_id",
                "voo_order_id",
                "bil_filled_usd",
                "voo_filled_usd",
                "status",
                "attempts",
                "last_error",
                "updated_at",
            ]
            self.description = [(name,) for name in names]
            self._result = list(self.inspection_rows)
            return

        if normalized.startswith("select bot_id, source_trade_id"):
            names = [
                "bot_id",
                "source_trade_id",
                "realized_profit",
                "skim_amount",
                "bil_allocated",
                "voo_allocated",
                "cash_accrued",
                "created_at",
            ]
            self.description = [(name,) for name in names]
            self._result = list(self.skim_rows)
            return

        if normalized.startswith("select a.bot_id, a.activation_enabled"):
            names = [
                "bot_id",
                "activation_enabled",
                "activation_equity",
                "seed_amount",
                "bil_qty",
                "voo_qty",
                "cash_usd",
                "cumulative_contributions",
                "last_rebalance_date",
                "trading_capital",
            ]
            self.description = [(name,) for name in names]
            self._result = list(self.report_rows)
            return

        if normalized.startswith("update per_bot_vault_deployment_queue"):
            row = next(row for row in self.queue_rows if row["bot_id"] == params[-1])
            applied_col = (
                "bil_filled_usd"
                if "set bil_filled_usd" in normalized
                else "voo_filled_usd"
            )
            pending_col = (
                "pending_bil_usd"
                if applied_col == "bil_filled_usd"
                else "pending_voo_usd"
            )
            order_col = (
                "bil_order_id"
                if applied_col == "bil_filled_usd"
                else "voo_order_id"
            )
            filled_value, delta, queue_order_id, status, _bot_id = params
            row[applied_col] = filled_value
            row[pending_col] = max(0.0, float(row[pending_col]) - float(delta))
            row[order_col] = queue_order_id
            row["status"] = status
            self.rowcount = 1
            return

        if normalized.startswith("update per_bot_vault_holdings"):
            self.rowcount = 1
            return

        if normalized.startswith("update per_bot_vault_accounts"):
            self.rowcount = 1
            return

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._fetchone_result


class _FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_count += 1


def _install_db_fake(monkeypatch, connection):
    db_package = ModuleType("db")
    db_package.__path__ = []
    postgres = ModuleType("db.postgres")
    postgres.get_conn = lambda: connection
    postgres.is_pg_available = lambda: True
    db_package.postgres = postgres
    monkeypatch.setitem(sys.modules, "db", db_package)
    monkeypatch.setitem(sys.modules, "db.postgres", postgres)


def _queue_row(**overrides):
    row = {
        "bot_id": "oracle",
        "pending_cash_usd": 0.0,
        "pending_bil_usd": 0.01,
        "pending_voo_usd": 0.01,
        "bil_order_id": "bil-order",
        "voo_order_id": "voo-order",
        "bil_filled_usd": 100.0,
        "voo_filled_usd": 100.0,
        "attempts": 2,
        "status": "submitted",
    }
    row.update(overrides)
    return row


def test_order_reader_uses_enum_value(monkeypatch):
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_order_by_id(self, _order_id):
            return SimpleNamespace(
                status=_BrokerStatus.FILLED,
                filled_qty="2",
                filled_avg_price="50",
            )

    from alpaca.trading import client as alpaca_client

    monkeypatch.setattr(alpaca_client, "TradingClient", FakeClient)
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

    assert vault._read_vault_order("oracle", "order-1") == {
        "status": "filled",
        "filled_qty": 2.0,
        "filled_avg_price": 50.0,
        "replaced_by": None,
    }


def test_reconciliation_clears_filled_orders_even_when_fill_delta_is_zero(monkeypatch):
    row = _queue_row()
    cursor = _FakeCursor(queue_rows=[row])
    _install_db_fake(monkeypatch, _FakeConnection(cursor))
    monkeypatch.setattr(vault, "vault_enabled", lambda: True)
    monkeypatch.setattr(
        vault,
        "_read_vault_order",
        lambda _bot, _order: {
            "status": "filled",
            "filled_qty": 1.0,
            "filled_avg_price": 100.0,
        },
    )

    result = vault.reconcile_deployment_orders()

    assert result["updated"] == 2
    assert [item["broker_status"] for item in result["orders"]] == ["filled", "filled"]
    assert row["bil_order_id"] is None
    assert row["voo_order_id"] is None
    assert row["status"] == "complete"
    assert not any("%s" in sql and params is None for sql, params in cursor.executed)


def test_reconciliation_tracks_replacement_without_clearing_queue_order(monkeypatch):
    row = _queue_row(
        pending_bil_usd=50.0,
        pending_voo_usd=0.0,
        voo_order_id=None,
        bil_filled_usd=0.0,
    )
    cursor = _FakeCursor(queue_rows=[row])
    _install_db_fake(monkeypatch, _FakeConnection(cursor))
    monkeypatch.setattr(vault, "vault_enabled", lambda: True)
    monkeypatch.setattr(
        vault,
        "_read_vault_order",
        lambda _bot, _order: {
            "status": "replaced",
            "filled_qty": 0.0,
            "filled_avg_price": 0.0,
            "replaced_by": "replacement-order",
        },
    )

    result = vault.reconcile_deployment_orders()

    assert result["updated"] == 1
    assert row["bil_order_id"] == "replacement-order"
    assert row["status"] == "submitted"
    assert result["orders"][0]["replacement_order_id"] == "replacement-order"


def test_duplicate_submit_adopts_existing_order(monkeypatch):
    class FakeClient:
        submit_calls = 0
        lookup_calls = 0
        submitted_client_order_id = None

        def __init__(self, *_args, **_kwargs):
            pass

        def get_account(self):
            return SimpleNamespace(cash="5000")

        def submit_order(self, request):
            self.__class__.submit_calls += 1
            self.__class__.submitted_client_order_id = request.client_order_id
            raise RuntimeError("duplicate client_order_id already exists")

        def get_order_by_client_id(self, client_order_id):
            self.__class__.lookup_calls += 1
            assert client_order_id == self.__class__.submitted_client_order_id
            return SimpleNamespace(
                id="existing-order",
                status=_BrokerStatus.FILLED,
                filled_qty="1",
                filled_avg_price="100",
            )

    from alpaca.trading import client as alpaca_client

    monkeypatch.setattr(alpaca_client, "TradingClient", FakeClient)
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "dev")
    monkeypatch.setattr(vault, "vault_enabled", lambda: True)

    result = vault._submit_vault_buy("oracle", "BIL", 100.0, "3-bil")

    assert result["order_id"] == "existing-order"
    assert result["status"] == "filled"
    assert result["client_order_id"] == "pbv-dev-oracle-3-bil"
    assert FakeClient.submit_calls == 1
    assert FakeClient.lookup_calls == 1


def test_trade_journal_routes_skim_to_explicit_closing_bot(monkeypatch):
    class JournalCursor:
        def __init__(self):
            self.rowcount = -1
            self._fetchone_result = None
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            placeholder_count = sql.count("%s")
            parameter_count = 0 if params is None else len(params)
            if placeholder_count != parameter_count:
                raise TypeError("placeholder/parameter mismatch")
            normalized = " ".join(sql.split()).lower()
            self.executed.append((normalized, params))
            if normalized.startswith("select intended_price, asset_class"):
                self._fetchone_result = (100.0, "momentum_etf")
            elif normalized.startswith("update trades"):
                self.rowcount = 1
            else:
                raise AssertionError(f"Unexpected SQL: {sql}")

        def fetchone(self):
            return self._fetchone_result

    cursor = JournalCursor()
    _install_db_fake(monkeypatch, _FakeConnection(cursor))
    from analysis import trade_journal

    credited_bots = []
    monkeypatch.setattr(
        vault,
        "record_profitable_close",
        lambda **kwargs: credited_bots.append(kwargs["bot_id"]),
    )

    trade_journal.close_trade(
        trade_id="ETF-oracle-SPY-20261002",
        pnl_percentage=1.0,
        realized_pnl=25.0,
        bot_id="oracle",
    )

    assert credited_bots == ["oracle"]


def test_vault_report_includes_broker_marked_holdings(monkeypatch):
    row = (
        "oracle",
        True,
        1000.0,
        50.0,
        2.0,
        3.0,
        10.0,
        100.0,
        None,
        950.0,
    )
    cursor = _FakeCursor(report_rows=[row])
    _install_db_fake(monkeypatch, _FakeConnection(cursor))
    monkeypatch.setattr(vault, "vault_enabled", lambda: True)
    monkeypatch.setattr(vault, "ensure_schema", lambda: None)
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="BIL", current_price="91.50"),
                SimpleNamespace(symbol="VOO", current_price="600.00"),
            ]

    from alpaca.trading import client as alpaca_client

    monkeypatch.setattr(alpaca_client, "TradingClient", FakeClient)

    report = vault.get_vault_report("oracle")["bots"][0]

    assert report["bil_market_value"] == 183.0
    assert report["voo_market_value"] == 1800.0
    assert report["vault_value"] == 1993.0
    assert report["combined_total"] == 2943.0


def test_vault_inspection_reads_queue_orders_and_skims_only(monkeypatch):
    cursor = _FakeCursor(
        inspection_rows=[
            (
                "oracle",
                True,
                0.0,
                0.01,
                0.01,
                "bil-order",
                None,
                100.0,
                0.0,
                "submitted",
                2,
                None,
                None,
            )
        ],
        skim_rows=[
            (
                "oracle",
                "ETF-oracle-QQQ-20260831",
                25.0,
                5.0,
                2.5,
                2.5,
                0.0,
                None,
            )
        ],
        read_only=True,
    )
    _install_db_fake(monkeypatch, _FakeConnection(cursor))
    monkeypatch.setattr(
        vault,
        "_read_vault_order",
        lambda _bot, order_id: {
            "status": "filled",
            "filled_qty": 1.0,
            "filled_avg_price": 100.0,
        },
    )

    report = vault.get_vault_inspection()

    assert report["read_only"] is True
    assert report["bots"][0]["status"] == "submitted"
    assert report["orders"] == [{
        "bot_id": "oracle",
        "symbol": "BIL",
        "order_id": "bil-order",
        "status": "filled",
        "filled_qty": 1.0,
        "filled_avg_price": 100.0,
    }]
    assert report["skims"][0]["source_trade_id"] == "ETF-oracle-QQQ-20260831"
    assert report["skims"][0]["skim_amount"] == 5.0
    assert all(sql.startswith("select") for sql, _params in cursor.executed)


def test_deployment_preview_is_read_only_and_does_not_submit(monkeypatch):
    row = _queue_row(pending_cash_usd=0.98)
    cursor = _FakeCursor(queue_rows=[row], read_only=True)
    _install_db_fake(monkeypatch, _FakeConnection(cursor))
    monkeypatch.setattr(vault, "vault_enabled", lambda: True)
    monkeypatch.setattr(
        vault,
        "_read_vault_order",
        lambda _bot, _order: {
            "status": "filled",
            "filled_qty": 1.0,
            "filled_avg_price": 100.0,
        },
    )
    monkeypatch.setattr(
        vault,
        "run_deployment_cycle",
        lambda **_kwargs: pytest.fail("preview called the mutating deployment cycle"),
    )

    preview = vault.preview_deployment_cycle(market_open=True)

    assert preview["read_only"] is True
    assert preview["would_submit"] == []
    assert preview["queues"][0]["projected_status"] == "pending"
    assert preview["queues"][0]["pending_cash_usd"] == 0.0
    assert preview["queues"][0]["pending_bil_usd"] == 0.5
    assert preview["queues"][0]["pending_voo_usd"] == 0.5
    assert row["bil_order_id"] == "bil-order"
    assert row["voo_order_id"] == "voo-order"
    assert all(sql.startswith("select") for sql, _params in cursor.executed)