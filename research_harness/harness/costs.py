"""Cost model. No defaults on purpose: every registration states its costs.

Anything a backtest leaves out goes in ``omitted``; the result is then labelled
optimistic in its summary. Rates are in basis points (1 bp = 0.01%).
"""

from __future__ import annotations

from dataclasses import dataclass

KNOWN_COSTS = ("commission", "spread", "slippage", "short_borrow", "financing")


@dataclass(frozen=True)
class CostModel:
    commission_bps: float          # per traded notional
    half_spread_bps: float         # per traded notional (pay half the spread each side)
    slippage_bps: float            # per traded notional
    short_borrow_bps_yr: float     # on short market value, per year
    financing_spread_bps_yr: float  # over the cash rate, on borrowed money, per year
    omitted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("commission_bps", "half_spread_bps", "slippage_bps",
                     "short_borrow_bps_yr", "financing_spread_bps_yr"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        unknown = set(self.omitted) - set(KNOWN_COSTS)
        if unknown:
            raise ValueError(f"unknown omitted costs: {sorted(unknown)}")

    @property
    def per_trade_bps(self) -> float:
        return self.commission_bps + self.half_spread_bps + self.slippage_bps

    def trade_cost(self, traded_notional: float) -> float:
        return abs(traded_notional) * self.per_trade_bps / 1e4

    def label(self) -> str:
        if not self.omitted:
            return "all costs included"
        return "OPTIMISTIC: omits " + ", ".join(self.omitted)
