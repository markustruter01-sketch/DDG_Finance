"""Momentum's account handed to G4 + DBMF (GEAR-V2 engine A2, forward test)."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_MODULE_PATH = pathlib.Path(__file__).with_name("bot2_momentum_strategy.py")
_SPEC = importlib.util.spec_from_file_location("bot2_gear_handover_test", _MODULE_PATH)
bot2 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot2
_SPEC.loader.exec_module(bot2)

import alpaca_etf_engine  # noqa: E402
import core.degradation_tracker as degradation_tracker  # noqa: E402
import core.kill_switch as kill_switch  # noqa: E402
import gear_account  # noqa: E402
from sleeve_runtime.gear_live import G4, G4_DBMF  # noqa: E402

PROFILE = {"GEAR_SLEEVE_LIVE": True, "ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"}
ROWS = [{"symbol": "AMD", "qty": 2, "entry_price": 500.0, "stop_order_id": "st-amd"},
        {"symbol": "SPY", "qty": 27, "entry_price": 650.0, "stop_order_id": "st-spy"}]


class _Engine:
    market_open = True

    def __init__(self, **_kw):
        pass

    def is_market_open(self):
        return self.market_open

    def get_positions(self):
        return [{"symbol": "SGOV", "qty": 434}]


@pytest.fixture
def wired(monkeypatch):
    seen = {"sold": [], "gear": [], "alerts": [], "clients": 0}
    _Engine.market_open = True
    monkeypatch.setattr(alpaca_etf_engine, "AlpacaEtfEngine", _Engine)
    monkeypatch.setattr(kill_switch, "latch_tripped", lambda: False)
    monkeypatch.setattr(degradation_tracker, "record_degradation",
                        lambda **kw: seen["alerts"].append(kw))
    monkeypatch.setattr(gear_account, "run_gear_account",
                        lambda engine, **kw: seen["gear"].append(kw) or {"status": "rebalanced to safe"})
    monkeypatch.setattr(bot2, "ensure_schema", lambda: None)
    monkeypatch.setattr(bot2, "load_open_positions", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(bot2, "_reconcile_protective_stops", lambda client, rows: rows)

    class _Client:
        def __init__(self, *_a):
            seen["clients"] += 1
    monkeypatch.setattr(bot2, "AlpacaMomentumClient", _Client)
    monkeypatch.setattr(bot2, "_sell_confirmed",
                        lambda client, row, reason: seen["sold"].append((row["symbol"], reason)) or True)
    return seen


def test_switch_off_keeps_momentums_own_cycle(monkeypatch):
    monkeypatch.setattr(bot2, "_run_gear_handover",
                        lambda *_a: pytest.fail("handover must not run with the switch off"))
    monkeypatch.setattr(bot2, "us_equity_session_open", lambda _now: False)
    assert bot2.run_bot2_cycle({"GEAR_SLEEVE_LIVE": False})["reason"] == "US_equity_market_closed"
    assert bot2.run_bot2_cycle()["reason"] == "US_equity_market_closed"


def test_handover_sells_the_whole_momentum_book_then_starts_g4_dbmf(wired):
    out = bot2.run_bot2_cycle(PROFILE)
    assert wired["sold"] == [("AMD", "gear_v2_a2_handover"), ("SPY", "gear_v2_a2_handover")]
    assert len(wired["gear"]) == 1
    call = wired["gear"][0]
    assert call["variant"] is G4_DBMF and call["variant"] is not G4
    assert call["bot_id"] == "spy_qqq_trend" and call["label"] == "GearDBMF"
    assert out == {"status": "rebalanced to safe"}
    assert wired["alerts"] == []


def test_a_failed_sell_buys_nothing_and_alerts(wired, monkeypatch):
    monkeypatch.setattr(bot2, "_sell_confirmed",
                        lambda client, row, reason: wired["sold"].append(row["symbol"]) or row["symbol"] != "AMD")
    out = bot2.run_bot2_cycle(PROFILE)
    assert out == {"status": "handover incomplete", "failed": ["AMD"]}
    assert wired["sold"] == ["AMD", "SPY"]                 # every row is tried
    assert wired["gear"] == []                              # nothing bought
    assert wired["alerts"][0]["error_type"] == "gear_v2_a2_handover"
    assert wired["alerts"][0]["bot_id"] == "spy_qqq_trend"


def test_no_sells_while_market_closed_or_kill_switch_tripped(wired, monkeypatch):
    _Engine.market_open = False
    assert bot2.run_bot2_cycle(PROFILE)["status"] == "market closed"
    _Engine.market_open = True
    monkeypatch.setattr(kill_switch, "latch_tripped", lambda: True)
    assert bot2.run_bot2_cycle(PROFILE)["status"] == "kill switch tripped: no trading"
    assert wired["sold"] == [] and wired["gear"] == [] and wired["clients"] == 0


def test_after_the_handover_g4_dbmf_runs_alone(wired, monkeypatch):
    monkeypatch.setattr(bot2, "load_open_positions", lambda: [])
    bot2.run_bot2_cycle(PROFILE)
    assert wired["sold"] == [] and wired["clients"] == 0
    assert len(wired["gear"]) == 1 and wired["gear"][0]["variant"] is G4_DBMF


def test_gear_wiring_uses_the_variants_own_state_key_and_alert_type(monkeypatch):
    import core.bot_state as bot_state
    import sleeve_runtime.gear_live as gl

    monkeypatch.setattr(gear_account, "sleeve_exclusions", lambda bot_id, live: ({"BIL", "VOO"}, {"SGOV"}))
    meta = {"gear_v1_g4": {"key": "atlas"}, "gear_v2_a2": {"key": "momentum"}}
    writes, alerts = [], []
    monkeypatch.setattr(bot_state, "read_metadata", lambda bot_id: meta)
    monkeypatch.setattr(bot_state, "merge_metadata", lambda bot_id, patch: writes.append((bot_id, patch)))
    monkeypatch.setattr(degradation_tracker, "record_degradation", lambda **kw: alerts.append(kw))
    captured = {}

    def fake_cycle(engine, **kw):
        captured.update(kw)
        kw["write_state"]({"key": "x"})
        kw["alert"]("error", "msg")
        return {"status": "ok", "state": kw["read_state"]()}
    monkeypatch.setattr(gl, "run_gear_cycle", fake_cycle)

    class _E:
        api = object()
    out = gear_account.run_gear_account(_E(), bot_id="spy_qqq_trend", variant=G4_DBMF,
                                        label="GearDBMF", live_positions=[])
    assert out["state"] == {"key": "momentum"}
    assert writes == [("spy_qqq_trend", {"gear_v2_a2": {"key": "x"}})]
    assert alerts[0]["error_type"] == "gear_v2_a2_rebalance" and alerts[0]["bot_id"] == "spy_qqq_trend"
    assert captured["variant"] is G4_DBMF and captured["vault"] == {"BIL", "VOO"}


def test_config_ships_momentums_account_on_g4_dbmf_and_atlas_on_g4():
    spec = importlib.util.spec_from_file_location("_cfg_handover_test", _MODULE_PATH.with_name("config.py"))
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    assert cfg.BOT_PROFILES["bot2_spy_qqq"]["GEAR_SLEEVE_LIVE"] is True
    assert cfg.BOT_PROFILES["bot2_spy_qqq"]["MAX_DEPLOYMENT"] == 1.00
    assert cfg.BOT_PROFILES["oracle"]["GEAR_SLEEVE_LIVE"] is True
