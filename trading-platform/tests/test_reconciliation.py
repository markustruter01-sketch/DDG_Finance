from __future__ import annotations

from contextlib import contextmanager

import pytest

from execution import reconciliation


def test_ledger_orphan_findings_scan_all_ledgers_and_normalise_symbols(monkeypatch):
    monkeypatch.setattr(
        reconciliation,
        "_active_ledger_rows",
        lambda: [
            {
                "table": "trades",
                "bot_id": None,
                "symbol": "PYPL",
                "qty": 159,
                "notional_usd": None,
                "status": "Active",
                "opened_at": "2026-08-06",
            },
            {
                "table": "jerome_positions",
                "bot_id": "buck_futures",
                "symbol": "DBC",
                "qty": None,
                "notional_usd": 46165.23,
                "status": "open",
                "opened_at": "2026-07-23",
            },
            {
                "table": "bot3_positions",
                "bot_id": "jerome_macro",
                "symbol": "BTC/USD",
                "qty": 0.3,
                "notional_usd": 10000,
                "status": "open",
                "opened_at": "2026-08-24",
            },
            {
                "table": "bot_portfolio.positions",
                "bot_id": "oracle",
                "symbol": "SGOV",
                "qty": 0.000000004,
                "notional_usd": None,
                "status": "Active",
                "opened_at": None,
            },
        ],
    )

    findings = reconciliation._ledger_orphan_findings(
        {
            "oracle": [{"symbol": "BTC/USD", "qty": 1}],
            "spy_qqq_trend": [],
            "jerome_macro": [{"symbol": "BTCUSD", "qty": 0.3}],
        }
    )

    assert [(finding["table"], finding["symbol"]) for finding in findings] == [
        ("trades", "PYPL"),
        ("jerome_positions", "DBC"),
    ]
    assert findings[1]["bot_id"] == "oracle"
    assert findings[1]["ledger_bot_id"] == "buck_futures"
    assert findings[0]["kind"] == "ledger_orphan"
    assert all("opened_at" in finding for finding in findings)


class _Cursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.calls.append((query, params))


class _Connection:
    def __init__(self):
        self.cursor_instance = _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def test_reconcile_persists_non_clean_orphan_run_without_trip(monkeypatch):
    connection = _Connection()
    snapshot = {
        "accounts": [
            {
                "bot_id": "oracle",
                "positions": [],
                "orders": [],
                "_client": object(),
            }
        ],
        "mismatches": [
            {
                "bot_id": "oracle",
                "table": "trades",
                "symbol": "PYPL",
                "kind": "ledger_orphan",
            }
        ],
        "account_summaries": [
            {
                "bot_id": "oracle",
                "broker_finding_count": 0,
                "orphan_finding_count": 1,
                "status": "MISMATCH",
            }
        ],
        "account_findings": [],
        "pause_state_disagreements": [],
        "liveness_findings": [],
        "fleet_equity": 100,
        "fleet_hwm": 100,
        "captured_at": "2026-08-31T00:00:00+00:00",
    }
    monkeypatch.setattr(reconciliation, "collect_live_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        "core.kill_switch._load_acknowledgements",
        lambda: {},
    )
    monkeypatch.setattr("core.kill_switch.evaluate_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        "core.kill_switch.trip",
        lambda *_args: (_ for _ in ()).throw(AssertionError("trip called")),
    )

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)

    result = reconciliation.reconcile(report_only=True, cycle_id="test-cycle")

    assert result["clean"] is False

    assert result["mode"] == "report_only"
    assert result["snapshot"]["mismatches"][0]["kind"] == "ledger_orphan"
    assert connection.cursor_instance.calls
    query, params = connection.cursor_instance.calls[0]
    assert "INSERT INTO reconciliation_log" in query
    assert params[0] is False


def test_reconcile_persists_clean_run(monkeypatch):
    connection = _Connection()
    snapshot = {
        "accounts": [],
        "mismatches": [],
        "account_summaries": [],
        "account_findings": [],
        "pause_state_disagreements": [],
        "liveness_findings": [],
        "fleet_equity": 100,
        "fleet_hwm": 100,
        "captured_at": "2026-08-31T00:00:00+00:00",
    }
    monkeypatch.setattr(reconciliation, "collect_live_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        "core.kill_switch._load_acknowledgements",
        lambda: {},
    )
    monkeypatch.setattr("core.kill_switch.evaluate_snapshot", lambda snapshot: [])

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)

    result = reconciliation.reconcile(report_only=True, cycle_id="clean-cycle")

    assert result["clean"] is True
    query, params = connection.cursor_instance.calls[0]
    assert "INSERT INTO reconciliation_log" in query
    assert params[0] is True


@pytest.mark.parametrize(
    ("bot_id", "table"),
    [
        ("oracle", "alpaca_etf_positions"),
        ("jerome_macro", "bot3_positions"),
    ],
)
def test_authoritative_quantity_mismatch_includes_table(
    monkeypatch, bot_id, table
):
    monkeypatch.setattr(
        reconciliation,
        "_authoritative_ledger_positions",
        lambda _bot_id: [
            {"table": table, "bot_id": bot_id, "symbol": "BTC/USD", "qty": 2.0}
        ],
    )

    findings = reconciliation._authoritative_quantity_mismatches(
        bot_id,
        [{"symbol": "BTCUSD", "qty": 1.0}],
    )

    assert findings == [
        {
            "bot_id": bot_id,
            "table": table,
            "symbol": "BTCUSD",
            "kind": "quantity_mismatch",
            "broker_qty": 1.0,
            "ledger_qty": 2.0,
        }
    ]


def test_authoritative_quantity_check_has_no_bot2_path(monkeypatch):
    def fail_if_read(_bot_id):
        raise AssertionError("Bot 2 must not use an authoritative strategy path")

    monkeypatch.setattr(
        reconciliation,
        "_authoritative_ledger_positions",
        fail_if_read,
    )

    assert reconciliation._authoritative_quantity_mismatches(
        "spy_qqq_trend",
        [{"symbol": "BIL", "qty": 10}],
    ) == []


def test_order_mismatches_matches_per_bot_and_symbol_and_keeps_pending_cancel_live(
    monkeypatch,
):
    monkeypatch.setattr(
        reconciliation,
        "_stop_ledger_rows",
        lambda _bot_id: [
            {
                "bot_id": "oracle",
                "symbol": "ECH",
                "stop_order_id": "oracle-ech",
                "table": "alpaca_etf_positions",
                "reverse_check": True,
            }
        ],
    )

    findings = reconciliation._order_mismatches(
        "oracle",
        [
            {
                "id": "oracle-ech",
                "symbol": "ECH",
                "side": "sell",
                "type": "stop",
                "status": "pending_cancel",
            },
            {
                "id": "unowned",
                "symbol": "EPOL",
                "side": "sell",
                "type": "stop",
                "status": "new",
            },
        ],
    )

    assert findings == [
        {
            "bot_id": "oracle",
            "order_id": "unowned",
            "symbol": "EPOL",
            "kind": "broker_open_order_without_ledger",
        }
    ]


def test_order_mismatches_reports_terminal_ledger_stop_and_wrong_symbol_owner(
    monkeypatch,
):
    monkeypatch.setattr(
        reconciliation,
        "_stop_ledger_rows",
        lambda _bot_id: [
            {
                "bot_id": "oracle",
                "symbol": "ECH",
                "stop_order_id": "stale-stop",
                "table": "alpaca_etf_positions",
                "reverse_check": True,
            }
        ],
    )

    findings = reconciliation._order_mismatches(
        "oracle",
        [
            {
                "id": "stale-stop",
                "symbol": "EPOL",
                "side": "sell",
                "type": "stop",
                "status": "new",
            },
        ],
    )

    assert findings == [
        {
            "bot_id": "oracle",
            "order_id": "stale-stop",
            "symbol": "EPOL",
            "kind": "broker_open_order_without_ledger",
        },
        {
            "bot_id": "oracle",
            "table": "alpaca_etf_positions",
            "symbol": "ECH",
            "stop_order_id": "stale-stop",
            "kind": "ledger_stop_without_broker",
        },
    ]


@pytest.mark.parametrize("status", ["new", "accepted", "held", "pending_cancel"])
def test_required_nonterminal_stop_statuses_are_live(status):
    assert reconciliation._is_live_protective_order(
        {
            "id": "stop",
            "symbol": "ECH",
            "side": "sell",
            "type": "stop",
            "status": status,
        }
    )


@pytest.mark.parametrize("status", ["canceled", "filled", "expired", "rejected"])
def test_terminal_stop_statuses_are_not_live(status):
    assert not reconciliation._is_live_protective_order(
        {
            "id": "stop",
            "symbol": "ECH",
            "side": "sell",
            "type": "stop",
            "status": status,
        }
    )


@pytest.mark.parametrize(
    "finding_kind",
    ["quantity_mismatch", "ledger_stop_without_broker"],
)
def test_new_finding_types_make_reconciliation_non_clean(
    monkeypatch, finding_kind
):
    connection = _Connection()
    snapshot = {
        "accounts": [{"bot_id": "oracle", "positions": [], "orders": []}],
        "mismatches": [{"bot_id": "oracle", "kind": finding_kind}],
        "account_summaries": [],
        "account_findings": [],
        "pause_state_disagreements": [],
        "liveness_findings": [],
        "fleet_equity": 100,
        "fleet_hwm": 100,
        "captured_at": "2026-08-31T00:00:00+00:00",
    }
    monkeypatch.setattr(reconciliation, "collect_live_snapshot", lambda: snapshot)
    monkeypatch.setattr("core.kill_switch._load_acknowledgements", lambda: {})
    monkeypatch.setattr("core.kill_switch.evaluate_snapshot", lambda snapshot: [])

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)

    result = reconciliation.reconcile(report_only=True, cycle_id="finding-cycle")

    assert result["clean"] is False