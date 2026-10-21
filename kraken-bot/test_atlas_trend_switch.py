"""oracle's cycle: TREND_SLEEVE_LIVE decides who trades the account."""
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


def _cycle(monkeypatch, live: bool):
    seen = []
    monkeypatch.setattr(atlas, "AlpacaEtfEngine", _Engine)
    monkeypatch.setattr(atlas, "_run_trend_sleeve", lambda e, live_pos: seen.append("sleeve"))
    monkeypatch.setattr(atlas, "_maybe_run_trend_shadow", lambda *a: seen.append("shadow"))
    monkeypatch.setattr(atlas, "_in_entry_window", lambda *a: seen.append("legacy") or False)
    monkeypatch.setattr("sgov_parking.park_idle_cash", lambda *a, **k: None)
    atlas.run_asia_cycle({"TREND_SLEEVE_LIVE": live}, 5)
    return seen


def test_switch_off_runs_legacy_and_shadow_only(monkeypatch):
    assert _cycle(monkeypatch, False) == ["shadow", "legacy"]


def test_switch_on_runs_only_the_sleeve(monkeypatch):
    assert _cycle(monkeypatch, True) == ["sleeve"]


def test_switch_ships_off():
    assert load_bot_profiles()["oracle"]["TREND_SLEEVE_LIVE"] is False
