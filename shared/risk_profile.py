"""
shared/risk_profile.py  —  Portfolio-Level Risk Envelope
=========================================================
A single source of truth for the risk parameters that govern how much
capital each bot can deploy, how large any single position can be, and
how to enforce the 60/40 ring-fence rule (60 % of equity is always
reserved for safe/stable assets; only 40 % is available as "risk capital"
that the bot can actively deploy into volatile positions).

Usage (both bots):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from shared.risk_profile import RiskProfile

    rp = RiskProfile(total_equity=100_000)
    rp.validate()            # raises ValueError if envelope is violated
    rp.deployed_pct()        # → float  (% of deployable capital in use)
    rp.reserve_buffer_usd()  # → float  (USD headroom before ceiling is hit)
    rp.to_dict()             # → dict   (admin endpoint serialisation)

Design notes:
  • NO trading logic lives here — only parameter storage and validation.
  • All maths is plain Python floats; no numpy / pandas dependency.
  • The 60/40 ring-fence is the primary invariant:
      ring_fenced_pct  +  deployable_pct  == 1.0  (100 %)
    where ring_fenced_pct defaults to 0.60 and deployable_pct to 0.40.
  • max_position_pct caps any single position as a fraction of total equity
    (not deployable equity) to keep individual bets small.
  • daily_loss_limit_pct expresses the maximum tolerable drawdown in one
    calendar day as a fraction of total equity.  Bots should trip their
    kill-switch when this threshold is breached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RiskProfile:
    """
    Defines the risk envelope for one portfolio (Alpaca or Kraken).

    Parameters
    ----------
    total_equity : float
        Current total account value in USD.  Updated each cycle by the
        calling bot before enforcement checks are run.

    deployed_usd : float
        Total USD currently tied up in open positions.  Updated each cycle.

    ring_fenced_pct : float
        Fraction of equity permanently ring-fenced into safe/stable assets
        (e.g. SGOV for Alpaca, cash reserve for Kraken).
        Default: 0.60 (60 %).

    deployable_pct : float
        Fraction of equity available for active / volatile positions.
        Must equal 1.0 − ring_fenced_pct.  Validated on construction.
        Default: 0.40 (40 %).

    max_position_pct : float
        Hard cap for any single position as a fraction of *total* equity.
        Alpaca default: 0.15 (15 %).
        Kraken default: 0.30 (30 % — fewer symbols, higher concentration ok).

    daily_loss_limit_pct : float
        Maximum tolerable intraday drawdown as a fraction of total equity.
        Default: 0.05 (5 %).

    reserve_pct : float
        Additional cash buffer kept liquid inside the deployable portion.
        Alpaca sets this via TARGET_UTILIZATION (18 % headroom).
        Kraken sets this via CASH_RESERVE (20 % of total equity).
        Default: 0.18.

    name : str
        Human-readable label for logging / serialisation ("alpaca" or "kraken").
    """

    total_equity:         float
    deployed_usd:         float        = 0.0
    ring_fenced_pct:      float        = 0.60
    deployable_pct:       float        = 0.40
    max_position_pct:     float        = 0.15
    daily_loss_limit_pct: float        = 0.05
    reserve_pct:          float        = 0.18
    name:                 str          = "portfolio"

    def __post_init__(self) -> None:
        if self.total_equity < 0:
            raise ValueError(f"RiskProfile.total_equity must be ≥ 0 (got {self.total_equity})")
        if not (0.0 <= self.ring_fenced_pct <= 1.0):
            raise ValueError(f"ring_fenced_pct must be in [0, 1] (got {self.ring_fenced_pct})")
        if not (0.0 <= self.deployable_pct <= 1.0):
            raise ValueError(f"deployable_pct must be in [0, 1] (got {self.deployable_pct})")
        expected = round(1.0 - self.ring_fenced_pct, 6)
        actual   = round(self.deployable_pct, 6)
        if abs(expected - actual) > 1e-4:
            raise ValueError(
                f"ring_fenced_pct + deployable_pct must equal 1.0 "
                f"(got {self.ring_fenced_pct} + {self.deployable_pct} = "
                f"{self.ring_fenced_pct + self.deployable_pct})"
            )
        if not (0.0 < self.max_position_pct <= 1.0):
            raise ValueError(f"max_position_pct must be in (0, 1] (got {self.max_position_pct})")

    # ── Derived quantities ─────────────────────────────────────────────────────

    def ring_fenced_usd(self) -> float:
        """USD value that must remain in safe/ring-fenced assets."""
        return round(self.total_equity * self.ring_fenced_pct, 2)

    def deployable_ceiling_usd(self) -> float:
        """
        Maximum USD that can be actively deployed in volatile positions.
        This is the hard ceiling before the reserve buffer is applied.
        """
        return round(self.total_equity * self.deployable_pct, 2)

    def active_ceiling_usd(self) -> float:
        """
        Effective deployment ceiling after subtracting the reserve buffer.

        For Alpaca this corresponds to TARGET_UTILIZATION × equity;
        for Kraken it corresponds to (1 − CASH_RESERVE) × equity
        within the deployable portion.
        """
        return round(self.deployable_ceiling_usd() * (1.0 - self.reserve_pct), 2)

    def max_single_position_usd(self) -> float:
        """Hard cap for any single position in USD."""
        return round(self.total_equity * self.max_position_pct, 2)

    def daily_loss_limit_usd(self) -> float:
        """USD drawdown that triggers the kill-switch for the day."""
        return round(self.total_equity * self.daily_loss_limit_pct, 2)

    def reserve_buffer_usd(self) -> float:
        """
        Remaining headroom before the active_ceiling is breached.
        Positive = room to deploy more.  Negative = over-deployed (violation).
        """
        return round(self.active_ceiling_usd() - self.deployed_usd, 2)

    def deployed_pct(self) -> float:
        """
        Deployed capital as a percentage of the active_ceiling_usd().
        Returns 0.0 when no capital is active.
        """
        ceiling = self.active_ceiling_usd()
        if ceiling <= 0:
            return 0.0
        return round((self.deployed_usd / ceiling) * 100.0, 2)

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate(self) -> None:
        """
        Raise ValueError if the current deployed_usd exceeds the
        active_ceiling_usd (i.e. the reserve buffer has been breached).

        Callers should catch ValueError and log a risk breach rather than
        halting the bot — the breach is informational but serious.
        """
        if self.deployed_usd > self.active_ceiling_usd() + 0.01:
            raise ValueError(
                f"RiskProfile [{self.name}] | Reserve breach: "
                f"deployed ${self.deployed_usd:,.2f} exceeds ceiling "
                f"${self.active_ceiling_usd():,.2f} "
                f"(buffer = ${self.reserve_buffer_usd():,.2f})"
            )

    def is_breached(self) -> bool:
        """Return True if deployed_usd exceeds active_ceiling_usd."""
        return self.deployed_usd > self.active_ceiling_usd() + 0.01

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """
        Return a dashboard-friendly snapshot suitable for the
        GET /admin/risk-profile endpoint.
        """
        return {
            "name":                    self.name,
            "total_equity_usd":        round(self.total_equity, 2),
            "deployed_usd":            round(self.deployed_usd, 2),
            "ring_fenced_pct":         round(self.ring_fenced_pct * 100, 1),
            "ring_fenced_usd":         self.ring_fenced_usd(),
            "deployable_ceiling_pct":  round(self.deployable_pct * 100, 1),
            "deployable_ceiling_usd":  self.deployable_ceiling_usd(),
            "reserve_pct":             round(self.reserve_pct * 100, 1),
            "active_ceiling_usd":      self.active_ceiling_usd(),
            "reserve_buffer_usd":      self.reserve_buffer_usd(),
            "deployed_pct_of_ceiling": self.deployed_pct(),
            "max_single_position_usd": self.max_single_position_usd(),
            "daily_loss_limit_usd":    self.daily_loss_limit_usd(),
            "is_breached":             self.is_breached(),
        }

    def __repr__(self) -> str:
        return (
            f"RiskProfile(name={self.name!r}, equity=${self.total_equity:,.0f}, "
            f"deployed=${self.deployed_usd:,.0f}, "
            f"ceiling=${self.active_ceiling_usd():,.0f}, "
            f"buffer=${self.reserve_buffer_usd():,.0f})"
        )
