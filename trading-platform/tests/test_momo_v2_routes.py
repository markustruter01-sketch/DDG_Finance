"""MOMO-V2 dashboard API: read values only."""

from __future__ import annotations

from routes import momo_v2


def test_state_view_passes_the_runtime_state_through():
    st = {"month": "2026-11", "selection_day": "2026-11-02", "universe_source": "ssga_spy",
          "names": ["AAA", "BBB"], "targets": {"AAA": 0.02, "BBB": 0.02}, "held": "in", "why": "monthly",
          "trend_on": True, "s": 0.8, "index": 101.2, "sma100": 97.0, "vol20": 0.18,
          "stopped": ["CCC"], "skipped_unaffordable": [], "key": "2026-11|in|normal",
          "drawdown": {"mode": "normal", "drawdown": 0.01, "hwm": 101_000.0},
          "cutover": {"day": "2026-11-02", "equity": 100_000.0, "spy": 500.0},
          "mark": {"day": "2026-11-20", "equity": 102_000.0, "spy": 505.0}}
    v = momo_v2.state_view(st)
    assert v["names"] == ["AAA", "BBB"] and v["invested_fraction"] == 0.8 and v["trend_on"] is True
    assert v["stopped"] == ["CCC"] and v["drawdown"]["mode"] == "normal"
    assert round(v["since_cutover"]["account_return"], 4) == 0.02


def test_state_view_of_an_empty_state():
    v = momo_v2.state_view({})
    assert v["names"] == [] and v["since_cutover"] is None and v["drawdown"]["mode"] == "normal"
