"""The engine against a recorded real day: three paper accounts after the
Fri 13 Nov 2026 close and real Alpaca bars (tests/fixtures/twins_recorded_2026-11-13.json)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from twins import engine
from twins.config import DAILY, MIRROR_MAX_GROSS, SHARE_COSTS

FIX = json.loads((Path(__file__).parent / "fixtures" / "twins_recorded_2026-11-13.json").read_text())
BARS = {s: [{"day": date.fromisoformat(d), "open": o, "high": h, "low": lo, "close": c} for d, o, h, lo, c in rows]
        for s, rows in FIX["bars"].items()}
D11, D12, D13 = date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 13)
# The owner-kept list as it was for this recorded day (BTC was sold on 17 Nov; the live list is now empty).
OWNER_KEPT = {"jerome_macro": frozenset({"BTCUSD"})}


@pytest.mark.parametrize("bot", sorted(FIX["portfolios"]))
def test_the_engine_values_a_real_account_exactly_as_the_broker_did(bot):
    p = FIX["portfolios"][bot]
    snap = engine.share_snapshot(p["positions"], p["cash_usd"], engine.closes_on(BARS, D13),
                                 OWNER_KEPT.get(bot, frozenset()))
    assert snap["equity"] == pytest.approx(p["equity_usd"] - p.get("owner_kept_value_usd", 0.0), abs=0.01)


@pytest.mark.parametrize("bot", sorted(FIX["portfolios"]))
def test_the_mirror_tracks_a_real_day(bot):
    # Nothing traded on 13 Nov, so the 13 Nov holdings were also the 12 Nov closing holdings.
    p = FIX["portfolios"][bot]
    kept = OWNER_KEPT.get(bot, frozenset())
    at12 = engine.share_snapshot(p["positions"], p["cash_usd"], engine.closes_on(BARS, D12), kept)
    real13 = p["equity_usd"] - p.get("owner_kept_value_usd", 0.0)
    res = engine.replay(bars_kind=DAILY, mirror=True, start=D11, start_equity=at12["equity"],
                        decisions=[{"id": 1, "step": D12, "weights": at12["weights"]}], bars=BARS,
                        costs=SHARE_COSTS, max_gross=MIRROR_MAX_GROSS, allow_short=True)
    m = {step: eq for step, eq, _ in res.curve}
    gap_pp = (m[D13] / m[D12] - real13 / at12["equity"]) * 100
    # Measured 15 Nov: |gap| under 0.002 points on all three accounts (the mirror bought at
    # the 12 Nov open, so its mix at that close differs slightly from the real one).
    assert abs(gap_pp) < 0.01, gap_pp
