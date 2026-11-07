"""oracle's cycle: the *_SLEEVE_LIVE switches decide who trades the account."""
from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "trading-platform"))
sys.path.insert(1, str(_ROOT / "kraken-bot"))
sys.path.insert(2, str(_ROOT))

import asia_trend_strategy as atlas
from core.bot_config import load_bot_profiles


class _Engine:
    def __init__(self, *a, **k):
        self.calls = []

    def get_account(self):
        return {"equity": 100.0, "cash": 100.0, "buying_power": 100.0}

    def get_positions(self):
        return []

    def get_db_positions(self, bot_id):
        self.calls.append("get_db_positions")
        return []

    def reconcile_protective_stops(self, bot_id, rows):
        self.calls.append("reconcile_protective_stops")


def _cycle(monkeypatch, live: bool, gear: bool = False, fleet: bool = False):
    seen = []
    monkeypatch.setattr(atlas, "AlpacaEtfEngine", _Engine)
    monkeypatch.setattr(atlas, "_run_trend_sleeve", lambda e, live_pos: seen.append("sleeve"))
    monkeypatch.setattr(atlas, "_run_gear_sleeve", lambda e, live_pos: seen.append("gear"))
    monkeypatch.setattr(atlas, "_run_fleet_sleeve", lambda e, live_pos: seen.append("fleet"))
    monkeypatch.setattr(atlas, "_maybe_run_trend_shadow", lambda *a: seen.append("shadow"))
    monkeypatch.setattr(atlas, "_in_entry_window", lambda *a: seen.append("legacy") or False)
    monkeypatch.setattr("sgov_parking.park_idle_cash", lambda *a, **k: None)
    atlas.run_asia_cycle({"TREND_SLEEVE_LIVE": live, "GEAR_SLEEVE_LIVE": gear,
                          "FLEET_SLEEVE_LIVE": fleet}, 5)
    return seen


def test_switch_off_runs_legacy_and_shadow_only(monkeypatch):
    assert _cycle(monkeypatch, False) == ["shadow", "legacy"]


def test_switch_on_runs_only_the_sleeve(monkeypatch):
    assert _cycle(monkeypatch, True) == ["sleeve"]


def test_gear_switch_runs_only_g4(monkeypatch):
    assert _cycle(monkeypatch, False, gear=True) == ["gear"]
    assert _cycle(monkeypatch, True, gear=True) == ["gear"]      # G4 wins if both were ever on


def test_fleet_switch_runs_only_fleet_v1(monkeypatch):
    assert _cycle(monkeypatch, False, fleet=True) == ["fleet"]
    assert _cycle(monkeypatch, True, gear=True, fleet=True) == ["fleet"]   # FLEET-V1 wins over G4 and trend


def test_atlas_ships_with_fleet_v1_live_and_g4_off():
    oracle = load_bot_profiles()["oracle"]
    assert oracle["FLEET_SLEEVE_LIVE"] is True
    assert oracle["GEAR_SLEEVE_LIVE"] is False and oracle["TREND_SLEEVE_LIVE"] is False
    assert oracle["MAX_DEPLOYMENT"] == 1.0


def test_jerome_is_paused_in_code_and_forex_council_trades_practice():
    profiles = load_bot_profiles()
    assert profiles["jerome_macro"]["PAUSED_IN_CODE"] is True
    # 7 Nov 2026 (Markus): the Forex council is back on, practice account only.
    assert profiles["forex_ai"]["FOREX_COUNCIL_ENABLED"] is True
    assert profiles["forex_ai"]["FOREX_TRADING_ENABLED"] is True
