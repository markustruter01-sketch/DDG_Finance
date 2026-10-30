"""GEAR-V2: G4's gearbox with a different safe gear, plus an optional
always-on slice (plan: research_harness/explore/GEAR-V2-PLAN.md).

G4's signal, aggressive and normal mixes, and rebalance timing are unchanged
(sleeves/gear.py). Only what the safe gear holds changes:
  A0  T-bills (G4 as registered; the control)
  A1  50% GLD + 50% IEF
  A2  100% DBMF (information only: its data starts in May 2019)
  A3  long/short cross-asset trend (TREND-V1-B's rule, short when off)
The slice for Part B is A3's long/short trend run on its own, always on.
Every value here is fixed by the plan.
"""

from __future__ import annotations

from datetime import date

from research_harness.explore.trend_v1 import UNIVERSE as TREND_UNIVERSE
from research_harness.harness.portfolio import HistoryView
from research_harness.sleeves.gear import make_strategy as gear_strategy
from research_harness.sleeves.trend import TrendParams, make_strategy as trend_strategy, target_weights

CORE = "G4"
ENGINES = ("A0", "A1", "A2", "A3")
SELECTABLE = ("A1", "A3")            # simplicity order for ties; A0 = control, A2 = data rule
LS_TREND = TrendParams(rule="sma_210", short_when_off=True)
SAFE_A1 = {"GLD": 0.5, "IEF": 0.5}
DBMF = "DBMF"
SLICE_WEIGHT = 0.25                  # Part B: one quarter, fixed design value


def engine_weights(engine: str, view: HistoryView) -> dict[str, float]:
    """What the safe gear holds today for each engine."""
    if engine == "A0":
        return {}
    if engine == "A1":
        return dict(SAFE_A1)
    if engine == "A2":                # T-bills until DBMF has a bar today
        if DBMF not in view.symbols():
            return {}
        bars = view.window(DBMF, 1)
        return {DBMF: 1.0} if bars and bars[-1]["day"] == view.today else {}
    if engine == "A3":
        return target_weights(view, TREND_UNIVERSE, LS_TREND)
    raise ValueError(f"unknown engine {engine}; declared: {ENGINES}")


def make_strategy(engine: str, log: list[tuple[date, str]] | None = None):
    """G4 with ``engine`` in the safe gear."""
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine}; declared: {ENGINES}")
    return gear_strategy(CORE, log, safe=lambda view: engine_weights(engine, view))


def make_slice_strategy():
    """Part B's always-on slice: the long/short trend, monthly."""
    return trend_strategy(TREND_UNIVERSE, LS_TREND)
