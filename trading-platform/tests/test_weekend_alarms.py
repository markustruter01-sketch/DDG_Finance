"""Weekend alarms of 14-15 Nov 2026: one alarm per open mismatch, one OANDA
retry on a 401, and an owner-kept sale in the twins' mirror check."""

from __future__ import annotations

import json
from datetime import date

import pytest

from core import daily_health, oanda_client
from execution import reconciliation
from twins import engine, job

ETH_FLAGS = [
    {"trigger": "broker_ledger_mismatch", "bot_id": "jerome_macro", "table": "bot3_positions",
     "symbol": "ETH/USD", "stop_order_id": "4e844e8b", "kind": "ledger_stop_without_broker"},
    {"trigger": "broker_ledger_mismatch", "bot_id": "jerome_macro", "table": "bot3_positions",
     "symbol": "ETHUSD", "qty": 2.222351339, "notional_usd": 5492.49, "kind": "ledger_orphan"},
]


# ── 3. one alarm per open mismatch ────────────────────────────────────────────
def test_the_same_mismatch_has_the_same_key_whatever_its_numbers():
    moved = [dict(f, notional_usd=1.0, qty=9.0) for f in ETH_FLAGS]
    assert reconciliation._mismatch_key("alpaca", "jerome_macro", json.dumps(ETH_FLAGS)) == \
        reconciliation._mismatch_key("alpaca", "jerome_macro", moved)
    other = [dict(ETH_FLAGS[1], symbol="BTC/USD")]
    assert reconciliation._mismatch_key("alpaca", "jerome_macro", other) != \
        reconciliation._mismatch_key("alpaca", "jerome_macro", ETH_FLAGS)
    assert reconciliation._mismatch_key("alpaca", "jerome_macro", "not json{") is None


def _reconcile_with(monkeypatch, open_keys):
    snapshot = {"accounts": [], "mismatches": [], "account_summaries": [], "account_findings": [],
                "pause_state_disagreements": [], "liveness_findings": [], "fleet_equity": 1, "fleet_hwm": 1}
    monkeypatch.setattr(reconciliation, "collect_live_snapshot", lambda: snapshot)
    monkeypatch.setattr("core.kill_switch._load_acknowledgements", lambda: {})
    monkeypatch.setattr("core.kill_switch.evaluate_snapshot", lambda s: list(ETH_FLAGS))
    monkeypatch.setattr(reconciliation, "_open_mismatch_keys", lambda: open_keys)
    recorded = []
    monkeypatch.setattr("core.degradation_tracker.record_degradation", lambda **kw: recorded.append(kw))

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): pass

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _Cur()

    monkeypatch.setattr("db.postgres.get_conn", lambda: _Conn())
    reconciliation.reconcile(report_only=True, cycle_id="reconciliation:test")
    return recorded


def test_an_open_mismatch_is_not_recorded_again(monkeypatch):
    first = _reconcile_with(monkeypatch, set())
    assert [r["bot_id"] for r in first] == ["jerome_macro"]
    key = reconciliation._mismatch_key("alpaca", "jerome_macro", first[0]["detail"])
    assert _reconcile_with(monkeypatch, {key}) == []


# ── 4. OANDA: one retry on a 401 ──────────────────────────────────────────────
class _Resp:
    def __init__(self, status):
        self.status_code = status

    def json(self):
        return {"ok": True}


class _Http:
    def __init__(self, statuses):
        self.statuses, self.calls = list(statuses), 0

    def get(self, *a, **kw):
        self.calls += 1
        return _Resp(self.statuses.pop(0))


@pytest.fixture
def client_for(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "test-account")
    monkeypatch.setattr(oanda_client, "RETRY_PAUSE_SECONDS", 0)
    monkeypatch.setattr("core.link_health.record_link", lambda *a, **kw: None)
    warnings = []
    monkeypatch.setattr(oanda_client.logger, "warning", lambda msg: warnings.append(msg))

    def make(statuses):
        http = _Http(statuses)
        return oanda_client.OandaClient(http_client=http), http, warnings
    return make


def test_a_401_is_retried_once_and_counted(client_for):
    client, http, warnings = client_for([401, 200])
    assert client._get("/x") == {"ok": True} and http.calls == 2
    assert warnings == [f"{oanda_client.RETRY_LOG_PREFIX} | recovered"]


def test_a_second_401_fails_and_is_counted(client_for):
    client, http, warnings = client_for([401, 401])
    with pytest.raises(oanda_client.OandaHTTPError):
        client._get("/x")
    assert http.calls == 2 and warnings[0].startswith(f"{oanda_client.RETRY_LOG_PREFIX} | failed again")


def test_other_errors_are_not_retried(client_for):
    client, http, warnings = client_for([503])
    with pytest.raises(oanda_client.OandaClientError):
        client._get("/x")
    assert http.calls == 1 and warnings == []


def test_daily_health_shows_the_retry_count_as_a_note():
    ok, lines = daily_health.summarize({"results": []}, pause_states={}, unresolved=[],
                                       kill_switch_tripped=False, oanda_retries=(5, 1))
    assert ok and lines[-1] == "ℹ️ OANDA answered 401 6× in 24 h: 5 fixed by one retry, 1 failed again"
    assert daily_health.summarize({"results": []}, pause_states={}, unresolved=[],
                                  kill_switch_tripped=False, oanda_retries=(0, 0))[1] == ["0/0 safety checks pass"]


# ── 5. an owner-kept sale is money arriving, not engine error ─────────────────
D1, D2, D3, D4 = (date(2026, 11, d) for d in (23, 24, 25, 26))


def test_owner_kept_quantities_are_recorded_beside_the_strategy():
    snap = engine.share_snapshot([{"symbol": "SPY", "qty": 10}, {"symbol": "BTC/USD", "qty": "0.0977"}],
                                 1_000, {"SPY": 100.0}, frozenset({"BTCUSD"}))
    assert snap["kept"] == {"BTCUSD": 0.0977} and snap["equity"] == 2_000


def test_a_stop_sale_of_btc_does_not_look_like_engine_error():
    # Strategy flat at 70,000 throughout; BTC (owner-kept) sold on D3 for 6,000, which lands as cash.
    rows = [{"day": D1, "equity": 70_000.0, "ref_equity": 70_000.0, "ref_holdings": {"kept": {"BTCUSD": 0.1}}},
            {"day": D2, "equity": 70_700.0, "ref_equity": 70_700.0, "ref_holdings": {"kept": {"BTCUSD": 0.1}}},
            {"day": D3, "equity": 71_400.0, "ref_equity": 77_400.0, "ref_holdings": {"kept": {}}},
            {"day": D4, "equity": 72_114.0, "ref_equity": 78_174.0, "ref_holdings": {"kept": {}}}]
    flows = job.flow_days(rows)
    assert flows == {D3}
    pts = [(r["day"], r["equity"], r["ref_equity"]) for r in rows]
    gaps = engine.mirror_gaps(pts, flows)
    assert gaps[D2] == 0.0 and gaps[D3] == 0.0 and abs(gaps[D4]) < 0.01
    assert engine.mirror_gaps(pts)[D3] < -8                 # without it: an 8-point false alarm
