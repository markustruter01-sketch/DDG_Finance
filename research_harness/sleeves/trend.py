"""Cross-asset trend sleeve (v1): long or flat in a fixed ETF universe.

Each month (first close of a new month) every ETF with enough history gets a
trend call from one of the declared rules. ETFs that are "on" are held at an
inverse-volatility weight; the share belonging to ETFs that are "off" stays
in cash (earning T-bills). Long only, no leverage: gross weight <= 1.

Inverse-vol base weight for ETF i = (1/vol_i) / sum over ALL eligible ETFs of
(1/vol_j), so the sleeve is fully invested only when every ETF is trending.
Each weight is capped at ``max_weight``; anything cut by the cap stays cash.
With ``short_when_off`` (GEAR-V2 candidate A3), an "off" ETF is held SHORT at
the same size instead of in cash; gross stays <= 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from research_harness.harness.portfolio import HistoryView

TRADING_DAYS = 252


@dataclass(frozen=True)
class TrendParams:
    rule: str                 # "tsmom_252", "sma_210", or "blend_63_126_252"
    vol_lookback: int = 63
    max_weight: float = 0.30
    short_when_off: bool = False  # GEAR-V2 A3: short "off" ETFs instead of holding cash

    def __post_init__(self) -> None:
        if self.rule not in RULES:
            raise ValueError(f"unknown rule {self.rule}; declared rules: {sorted(RULES)}")


def _tsmom(closes: list[float], n: int) -> bool | None:
    if len(closes) <= n:
        return None
    return closes[-1] / closes[-1 - n] - 1 > 0


def _sma(closes: list[float], n: int) -> bool | None:
    if len(closes) < n:
        return None
    return closes[-1] > sum(closes[-n:]) / n


def _blend(closes: list[float]) -> bool | None:
    votes = [_tsmom(closes, n) for n in (63, 126, 252)]
    if any(v is None for v in votes):
        return None
    return sum(votes) >= 2  # majority of the three look-backs


RULES = {
    "tsmom_252": (lambda c: _tsmom(c, 252), 253),
    "sma_210": (lambda c: _sma(c, 210), 210),
    "blend_63_126_252": (_blend, 253),
}


def _ann_vol(closes: list[float]) -> float | None:
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    return sd * math.sqrt(TRADING_DAYS) if sd > 0 else None


def target_weights(view: HistoryView, universe: list[str], p: TrendParams) -> dict[str, float]:
    rule, min_bars = RULES[p.rule]
    need = max(min_bars, p.vol_lookback + 1)
    inv_vol: dict[str, float] = {}
    on: dict[str, bool] = {}
    for sym in universe:
        bars = view.window(sym, need)
        if len(bars) < need or bars[-1]["day"] != view.today:
            continue  # not yet listed, or no fresh bar today: not eligible
        closes = [b["close"] for b in bars]
        vol = _ann_vol(closes[-(p.vol_lookback + 1):])
        call = rule(closes)
        if vol is None or call is None:
            continue
        inv_vol[sym] = 1 / vol
        on[sym] = call
    total = sum(inv_vol.values())
    if total == 0:
        return {}
    return {s: (1.0 if on[s] else -1.0) * min(p.max_weight, iv / total)
            for s, iv in inv_vol.items() if on[s] or p.short_when_off}


def make_strategy(universe: list[str], p: TrendParams):
    """Strategy for portfolio.simulate: rebalances on the first close of each month."""
    state: dict[str, tuple[int, int] | None] = {"month": None}

    def strategy(day: date, view: HistoryView) -> dict[str, float] | None:
        month = (day.year, day.month)
        if month == state["month"]:
            return None
        state["month"] = month
        return target_weights(view, universe, p)

    return strategy
