"""
shared/exit_bracket.py  —  Exit-Level Calculator
=================================================
Computes the three exit prices for any long or short trade:

  1. stop_loss_price        — Hard cut if the trade goes wrong.
  2. take_profit_price      — Initial profit target (ATR-based or fixed %).
  3. trail_activation_price — Price at which the trailing stop kicks in.

The maths delegates to the existing implementations in each bot's own
module but provides a single, consistent interface so the dashboard,
risk reports, and unit tests can reference one canonical formula.

Usage:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from shared.exit_bracket import ExitBracket, compute_exit_levels

    bracket = ExitBracket(
        entry_price=50_000.0,
        direction="long",
        stop_loss_pct=0.02,
        take_profit_pct=0.06,
        trail_pct=0.05,
        atr=None,               # if supplied, ATR-based stops override fixed %
        atr_multiplier=2.0,
    )
    sl, tp, trail = bracket.compute()

    # Or use the module-level convenience function:
    sl, tp, trail = compute_exit_levels(
        entry_price=50_000.0,
        direction="long",
        stop_loss_pct=0.02,
        take_profit_pct=0.06,
    )

ATR-based stop logic
--------------------
When *atr* is provided and > 0:
  long  stop  = entry − (atr_multiplier × atr)
  short stop  = entry + (atr_multiplier × atr)
  The ATR stop replaces the fixed stop_loss_pct stop.

The take-profit and trail-activation prices always use the fixed percentage
parameters regardless of whether ATR is supplied.

Alpaca parameters (executor.py defaults):
  stop_loss_pct    = 0.02  (FALLBACK_STOP_PCT / OVERHEAT_STOP_PCT)
  atr_multiplier   = 2.0   (ATR_MULTIPLIER)   | 1.5 for leveraged ETFs
  trail_pct        = 0.05  (implied by ratchet mechanism)
  take_profit_pct  = 0.06  (implied 3× risk-reward at 2 % stop)

Kraken parameters (config.py defaults):
  stop_loss_pct    = 0.02  (STOP_LOSS_PCT)
  trail_pct        = 0.05  (TRAIL_PCT)
  take_profit_pct  = 0.06  (implied)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple


@dataclass
class ExitBracket:
    """
    Encapsulates the exit parameters for a single trade position.

    Parameters
    ----------
    entry_price : float
        The fill price at which the position was opened.

    direction : "long" | "short"
        Trade direction.

    stop_loss_pct : float
        Distance from entry to the hard stop as a positive decimal
        (e.g. 0.02 = 2 %).  Used as fallback when ATR is unavailable.

    take_profit_pct : float
        Distance from entry to the initial take-profit target as a
        positive decimal (e.g. 0.06 = 6 %).

    trail_pct : float
        Trailing-stop activation distance from the *best price* seen
        since entry (e.g. 0.05 = 5 %).  The trailing stop kicks in
        once the position is profitable by at least this fraction.

    atr : float | None
        Average True Range value (in price units, not percentage).
        When provided and > 0, the stop_loss_price is computed as
        entry ± (atr_multiplier × atr) instead of entry ± stop_loss_pct.

    atr_multiplier : float
        ATR multiplier used for the ATR-based stop.
        Standard: 2.0 (most tickers).
        Leveraged ETFs: 1.5 (TQQQ, SOXL, UPRO).
    """

    entry_price:    float
    direction:      Literal["long", "short"]
    stop_loss_pct:  float  = 0.02
    take_profit_pct: float = 0.06
    trail_pct:      float  = 0.05
    atr:            Optional[float] = None
    atr_multiplier: float  = 2.0

    def __post_init__(self) -> None:
        if self.entry_price <= 0:
            raise ValueError(f"entry_price must be > 0 (got {self.entry_price})")
        if self.direction not in ("long", "short"):
            raise ValueError(f"direction must be 'long' or 'short' (got {self.direction!r})")
        if self.stop_loss_pct <= 0:
            raise ValueError(f"stop_loss_pct must be > 0 (got {self.stop_loss_pct})")
        if self.take_profit_pct <= 0:
            raise ValueError(f"take_profit_pct must be > 0 (got {self.take_profit_pct})")
        if self.trail_pct <= 0:
            raise ValueError(f"trail_pct must be > 0 (got {self.trail_pct})")

    # ── Core calculation ───────────────────────────────────────────────────────

    def compute(self) -> Tuple[float, float, float]:
        """
        Compute the three exit prices.

        Returns
        -------
        (stop_loss_price, take_profit_price, trail_activation_price)

        For a long:
          stop_loss         = entry - (atr × mult)   [ATR]
                            = entry × (1 - stop_loss_pct)  [fixed fallback]
          take_profit       = entry × (1 + take_profit_pct)
          trail_activation  = entry × (1 + trail_pct)
                              (trailing stop fires when price later drops
                               trail_pct below its running peak)

        For a short:
          stop_loss         = entry + (atr × mult)   [ATR]
                            = entry × (1 + stop_loss_pct)  [fixed fallback]
          take_profit       = entry × (1 - take_profit_pct)
          trail_activation  = entry × (1 - trail_pct)
                              (trailing stop fires when price later rises
                               trail_pct above its running trough)
        """
        e = self.entry_price

        # ── Stop-loss price ─────────────────────────────────────────────────
        if self.atr and self.atr > 0:
            atr_distance = self.atr * self.atr_multiplier
            if self.direction == "long":
                stop_loss_price = e - atr_distance
            else:
                stop_loss_price = e + atr_distance
        else:
            if self.direction == "long":
                stop_loss_price = e * (1.0 - self.stop_loss_pct)
            else:
                stop_loss_price = e * (1.0 + self.stop_loss_pct)

        # ── Take-profit price ───────────────────────────────────────────────
        if self.direction == "long":
            take_profit_price = e * (1.0 + self.take_profit_pct)
        else:
            take_profit_price = e * (1.0 - self.take_profit_pct)

        # ── Trail-activation price ──────────────────────────────────────────
        # This is the first price at which the trailing stop becomes active.
        # Once price reaches this level, any subsequent reversal of trail_pct
        # from the best-price triggers an exit.
        if self.direction == "long":
            trail_activation_price = e * (1.0 + self.trail_pct)
        else:
            trail_activation_price = e * (1.0 - self.trail_pct)

        return (
            round(stop_loss_price,        6),
            round(take_profit_price,      6),
            round(trail_activation_price, 6),
        )

    def risk_reward_ratio(self) -> float:
        """
        Return the trade's risk-reward ratio using fixed percentages.

        ratio = take_profit_pct / stop_loss_pct
        A ratio ≥ 2.0 is generally required for positive expected value
        at a 40 %+ win rate.
        """
        return round(self.take_profit_pct / self.stop_loss_pct, 2)

    def to_dict(self) -> dict:
        """Serialise bracket parameters and computed levels for logging."""
        sl, tp, trail = self.compute()
        return {
            "entry_price":          round(self.entry_price, 6),
            "direction":            self.direction,
            "stop_loss_pct":        round(self.stop_loss_pct * 100, 3),
            "take_profit_pct":      round(self.take_profit_pct * 100, 3),
            "trail_pct":            round(self.trail_pct * 100, 3),
            "atr":                  self.atr,
            "atr_multiplier":       self.atr_multiplier,
            "stop_loss_price":      sl,
            "take_profit_price":    tp,
            "trail_activation_price": trail,
            "risk_reward_ratio":    self.risk_reward_ratio(),
        }

    def __repr__(self) -> str:
        sl, tp, trail = self.compute()
        return (
            f"ExitBracket({self.direction} @ {self.entry_price:.4f} | "
            f"SL={sl:.4f}  TP={tp:.4f}  Trail@{trail:.4f})"
        )


# ── Convenience function ───────────────────────────────────────────────────────

def compute_exit_levels(
    entry_price:     float,
    direction:       Literal["long", "short"],
    risk_profile:    Optional[object]  = None,
    atr:             Optional[float]   = None,
    stop_loss_pct:   float = 0.02,
    take_profit_pct: float = 0.06,
    trail_pct:       float = 0.05,
    atr_multiplier:  float = 2.0,
) -> Tuple[float, float, float]:
    """
    Module-level convenience wrapper around ExitBracket.compute().

    Parameters
    ----------
    entry_price : float
        Fill price at which the position was opened.

    direction : "long" | "short"
        Trade direction.

    risk_profile : RiskProfile | None
        Optional shared.risk_profile.RiskProfile instance.  When supplied,
        the stop_loss_pct is derived from the profile's max_position_pct
        (i.e. we risk at most max_position_pct × entry per position).
        Explicit *stop_loss_pct* is used as a fallback / override when
        risk_profile is None.

    atr : float | None
        Average True Range in price units.  When > 0, overrides the fixed
        percentage stop with an ATR-based stop.

    stop_loss_pct : float
        Fixed-percentage stop used when risk_profile is None and atr is None.

    take_profit_pct : float
        Take-profit target distance from entry.

    trail_pct : float
        Trailing-stop activation distance from the best price.

    atr_multiplier : float
        ATR multiplier (2.0 standard, 1.5 for leveraged ETFs).

    Returns
    -------
    (stop_loss_price, take_profit_price, trail_activation_price)
    """
    # When a RiskProfile is provided, derive the stop_loss_pct from the
    # profile's max_position_pct so that stop sizing respects the same
    # risk envelope that governs position sizing.
    if risk_profile is not None and hasattr(risk_profile, "max_position_pct"):
        # The stop is set so that a full stop-out costs at most
        # (max_position_pct / 2) of equity — a conservative derivation
        # that keeps stop distance proportional to the position limit.
        stop_loss_pct = risk_profile.max_position_pct / 2.0

    bracket = ExitBracket(
        entry_price=entry_price,
        direction=direction,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trail_pct=trail_pct,
        atr=atr,
        atr_multiplier=atr_multiplier,
    )
    return bracket.compute()
