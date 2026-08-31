from __future__ import annotations

from contextlib import contextmanager

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