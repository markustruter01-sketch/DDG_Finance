"""G4-STRESS-1985 reconstruction (synthetic data only)."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from research_harness.explore import g4_stress_1985 as st
from research_harness.harness.store import BarStore


def _days(n, start=date(1985, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_levered_series_matches_the_formula():
    d = _days(3)
    closes = [(d[0], 100.0), (d[1], 110.0), (d[2], 99.0)]
    rf = {d[0]: 0.0252}                                   # 0.01% a day
    out = st.levered(closes, rf, 2.0, 0.0252, start_value=100.0)
    day = 0.0252 / 252
    v1 = 100 * (1 + 2 * 0.10 - day - day)
    v2 = v1 * (1 + 2 * (-0.10) - day - day)
    assert [v for _, v in out] == pytest.approx([100.0, v1, v2])


def test_close_to_close_bars():
    d = _days(3)
    bars = st.close_to_close([(d[0], 10.0), (d[1], 11.0), (d[2], 9.0)])
    assert [b["open"] for b in bars] == [10.0, 10.0, 11.0]
    assert all(b["high"] == b["low"] == b["close"] for b in bars)


def test_end_to_end_on_synthetic_indices(tmp_path):
    days = [d for d in _days(9200) if d <= date(2020, 12, 31)]
    rng = random.Random(3)

    def walk(drift, vol, start):
        px, out = start, []
        for d in days:
            px *= math.exp(drift + rng.gauss(0, vol))
            out.append({"day": d, "open": px, "high": px, "low": px, "close": px})
        return out

    store = BarStore(tmp_path)
    store.write_dataset(st.INDEX_DATASET, source="t", bars_by_symbol={
        st.SP: walk(0.0003, 0.01, 200.0), st.NDX: [b for b in walk(0.0004, 0.015, 250.0)
                                                   if b["day"] >= date(1985, 10, 1)]})
    store.write_dataset(st.RATES_DATASET, source="t", fields=("day", "rate"), positive_fields=(),
                        bars_by_symbol={"DTB3": [{"day": d, "rate": 0.04} for d in days]})
    out = st.run(store, log_path=None)
    g = out["stress"]["G4_reconstructed"]
    assert out["stress"]["window"][0] >= "1985-10-01"
    assert set(g["sub_windows"]) == {"1987", "2000-2002"}
    assert "cagr_pct" in out["fidelity_2007_2020"]["G4_reconstructed"]
