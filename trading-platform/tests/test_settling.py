"""Unbooked broker fills are reported as settling, not as critical mismatches."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import settling
from core.invariants import (
    InvariantInputs,
    check_ledger_broker_presence,
    check_ledger_broker_quantities,
)

NOW = datetime(2026, 10, 22, 20, 47, tzinfo=timezone.utc)


class _FillsClient:
    """Fake of alpaca TradingClient.get (the generic REST GET it inherits)."""

    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.calls = rows or [], error, []

    def get(self, path, data=None, **kwargs):
        self.calls.append((path, data))
        if self.error:
            raise self.error
        return self.rows


def test_recent_fill_symbols_uses_fill_time_and_window():
    client = _FillsClient([
        {"transaction_time": "2026-10-22T19:55:24.507998Z", "symbol": "SGOV"},
        {"transaction_time": "2026-10-22T19:45:24.983431Z", "symbol": "ASX"},
        {"transaction_time": "2026-10-22T18:00:00Z", "symbol": "OLD"},     # outside 90 min
        {"transaction_time": "not a time", "symbol": "BAD"},
        {"transaction_time": "2026-10-22T20:00:00Z", "symbol": None},
    ])
    assert settling.recent_fill_symbols(client, NOW) == {"SGOV", "ASX"}
    path, params = client.calls[0]
    assert path == "/account/activities/FILL"
    assert params["after"] == "2026-10-22T19:17:00Z" and params["direction"] == "desc"


def test_unreadable_fills_mean_nothing_is_settling():
    client = _FillsClient(error=RuntimeError("403"))
    assert settling.safe_recent_fill_symbols("spy_qqq_trend", client, NOW) == set()
    with pytest.raises(RuntimeError):
        settling.recent_fill_symbols(client, NOW)


def test_split_settling_holds_only_lag_kinds_for_recently_filled_symbols():
    findings = [
        {"bot_id": "spy_qqq_trend", "symbol": "SGOV", "kind": "quantity_mismatch", "broker_qty": 387, "ledger_qty": 373},
        {"bot_id": "spy_qqq_trend", "symbol": "ASX", "kind": "ledger_without_broker"},
        {"bot_id": "spy_qqq_trend", "symbol": "ASX", "kind": "ledger_stop_without_broker", "stop_order_id": "x"},
        {"bot_id": "spy_qqq_trend", "symbol": "NVDA", "kind": "ledger_without_broker"},         # no recent fill
        {"bot_id": "jerome_macro", "symbol": "SGOV", "kind": "quantity_mismatch"},             # other account
        {"bot_id": "oracle", "symbol": "BIL", "kind": "vault_quantity_mismatch"},              # not a lag kind
        {"bot_id": "oracle", "kind": "reconciliation_check_failed", "check": "vault_symbols_read"},
    ]
    kept, held = settling.split_settling(findings, {"spy_qqq_trend": {"SGOV", "ASX"}, "oracle": {"BIL"}})
    assert [f["symbol"] for f in held] == ["SGOV", "ASX", "ASX"]
    assert [f.get("symbol") for f in kept] == ["NVDA", "SGOV", "BIL", None]


def _inputs(**changes):
    base = InvariantInputs(
        now=NOW,
        broker_positions={"oracle": [], "spy_qqq_trend": [{"symbol": "NOK", "qty": 0.0}], "jerome_macro": []},
        broker_orders={"oracle": [], "spy_qqq_trend": [], "jerome_macro": []},
        oanda_trades=[],
        ledger_positions={"oracle": [], "spy_qqq_trend": [{"symbol": "NOK", "qty": 166.0}], "jerome_macro": []},
        forex_ai_trades=[],
        vault_symbols={"oracle": set(), "spy_qqq_trend": set(), "jerome_macro": set()},
        fleet_equity=100_000.0,
    )
    return replace(base, **changes)


def test_presence_invariant_reports_a_just_sold_position_as_settling():
    assert check_ledger_broker_presence(_inputs())["status"] == "FAIL"
    result = check_ledger_broker_presence(_inputs(settling_symbols={"spy_qqq_trend": {"NOK"}}))
    assert result["status"] == "PASS"
    assert result["actual"]["settling"] == [{"bot_id": "spy_qqq_trend", "symbol": "NOK"}]


def test_quantity_invariant_reports_an_unbooked_partial_fill_as_settling():
    partial = dict(
        broker_positions={"oracle": [], "spy_qqq_trend": [{"symbol": "TER", "qty": 2.0}], "jerome_macro": []},
        ledger_positions={"oracle": [], "spy_qqq_trend": [{"symbol": "TER", "qty": 4.0}], "jerome_macro": []},
    )
    assert check_ledger_broker_quantities(_inputs(**partial))["status"] == "FAIL"
    result = check_ledger_broker_quantities(_inputs(**partial, settling_symbols={"spy_qqq_trend": {"TER"}}))
    assert result["status"] == "PASS"
    assert result["actual"]["settling"] == [{"bot_id": "spy_qqq_trend", "symbol": "TER"}]


def test_collect_live_snapshot_moves_settling_findings_out_of_mismatches(monkeypatch):
    from execution import reconciliation  # imported here, as in the other reconciliation tests

    class _Client(_FillsClient):
        def get_account(self):
            return SimpleNamespace(equity="100", cash="50")

    fill_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    clients = {"spy_qqq_trend": _Client([{"transaction_time": fill_time, "symbol": "SGOV"}])}
    monkeypatch.setattr(reconciliation, "ACTIVE_BOTS", ["oracle", "spy_qqq_trend"])
    monkeypatch.setattr(reconciliation, "_client_for", lambda bot_id: clients.get(bot_id) or _Client())
    monkeypatch.setattr(reconciliation, "_vault_symbols", lambda _bot_id: set())
    monkeypatch.setattr(reconciliation, "_positions", lambda _client: [])
    monkeypatch.setattr(reconciliation, "_orders", lambda _client: [])
    monkeypatch.setattr(reconciliation, "_ledger_positions", lambda _bot_id: [])
    monkeypatch.setattr(
        reconciliation, "_mismatches",
        lambda bot_id, *_a: [{"bot_id": bot_id, "symbol": "SGOV", "kind": "quantity_mismatch"}],
    )
    monkeypatch.setattr(reconciliation, "_authoritative_quantity_mismatches", lambda *_a: [])
    monkeypatch.setattr(reconciliation, "_order_mismatches", lambda *_a: [])
    monkeypatch.setattr(reconciliation, "_stale_portfolio", lambda _bot_id: [])
    monkeypatch.setattr(reconciliation, "_ledger_orphan_findings", lambda _p: [])
    monkeypatch.setattr(reconciliation, "_pause_state_disagreements", lambda: [])
    monkeypatch.setattr("core.fleet_equity.get_fleet_equity", lambda: (None, None))
    monkeypatch.setattr("core.bot_liveness.evaluate_liveness", lambda: [])

    snapshot = reconciliation.collect_live_snapshot()

    assert snapshot["settling"] == [{"bot_id": "spy_qqq_trend", "symbol": "SGOV", "kind": "quantity_mismatch"}]
    assert {"bot_id": "oracle", "symbol": "SGOV", "kind": "quantity_mismatch"} in snapshot["mismatches"]
    assert not any(m.get("bot_id") == "spy_qqq_trend" for m in snapshot["mismatches"])
