"""Vault BIL/VOO are checked against the vault ledger, not the hourly mirror."""

from __future__ import annotations

from execution import reconciliation as rec

VAULT = {"BIL", "VOO"}


def _pos(symbol, qty, price):
    return {"symbol": symbol, "qty": qty, "market_value": qty * price, "side": "long"}


def _ledger(monkeypatch, qty, pending=None):
    monkeypatch.setattr(rec, "_vault_ledger", lambda _b: (qty, pending or {"BIL": 0.0, "VOO": 0.0}))


def test_matching_vault_has_no_finding(monkeypatch):
    _ledger(monkeypatch, {"BIL": 30.8745907, "VOO": 4.015715502})
    broker = [_pos("BIL", 30.8745907, 91.6), _pos("VOO", 4.015715502, 706.65)]
    assert rec._vault_mismatches("spy_qqq_trend", broker, VAULT) == []


def test_cent_rounding_drift_is_tolerated(monkeypatch):
    _ledger(monkeypatch, {"BIL": 25.25, "VOO": 3.284})
    broker = [_pos("BIL", 25.25 + 0.03, 91.6), _pos("VOO", 3.284 + 0.004, 706.65)]   # ~$2.75 each
    assert rec._vault_mismatches("oracle", broker, VAULT) == []


def test_an_order_in_flight_is_allowed_for_its_pending_amount(monkeypatch):
    _ledger(monkeypatch, {"BIL": 25.25, "VOO": 3.284}, {"BIL": 10.0, "VOO": 10.0})
    broker = [_pos("BIL", 25.25 + 10 / 91.6, 91.6), _pos("VOO", 3.284 + 10 / 706.65, 706.65)]
    assert rec._vault_mismatches("oracle", broker, VAULT) == []


def test_the_re_buy_loop_gap_is_flagged_with_stable_fields(monkeypatch):
    # Production oracle, 22 Oct 2026: pending stuck at $5.22, ~$610 gap each.
    _ledger(monkeypatch, {"BIL": 25.250485556, "VOO": 3.28414826}, {"BIL": 5.22, "VOO": 5.21})
    broker = [_pos("BIL", 31.907226319, 91.6), _pos("VOO", 4.144558243, 706.65)]
    first = rec._vault_mismatches("oracle", broker, VAULT)
    assert [f["symbol"] for f in first] == ["BIL", "VOO"]
    assert all(f["kind"] == "vault_quantity_mismatch" for f in first)
    # Same quantities at a different price -> identical findings (kill-switch repeat count).
    broker2 = [_pos("BIL", 31.907226319, 91.7), _pos("VOO", 4.144558243, 700.0)]
    assert rec._vault_mismatches("oracle", broker2, VAULT) == first


def test_ledger_says_held_but_broker_has_none(monkeypatch):
    _ledger(monkeypatch, {"BIL": 5.0, "VOO": 0.0})
    out = rec._vault_mismatches("oracle", [], VAULT)
    assert out == [{"bot_id": "oracle", "symbol": "BIL", "kind": "vault_quantity_mismatch",
                    "table": "per_bot_vault_holdings", "broker_qty": 0.0, "vault_qty": 5.0}]


def test_unreadable_vault_ledger_is_a_check_failure(monkeypatch):
    def boom(_b):
        raise RuntimeError("db down")
    monkeypatch.setattr(rec, "_vault_ledger", boom)
    out = rec._vault_mismatches("oracle", [_pos("BIL", 1, 91.6)], VAULT)
    assert out and out[0]["kind"] == "reconciliation_check_failed"
