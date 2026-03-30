"""
shared/var_circuit_breaker.py  —  Parametric VaR Circuit Breaker
=================================================================
Estimates the portfolio's 1-day 99% Value-at-Risk (VaR) from a rolling
window of return observations and trips a circuit breaker when the
estimated loss exceeds a configurable threshold.

Theory
------
Parametric (normal) VaR at confidence level α:

    VaR(α) = −(μ − z_α × σ) × portfolio_usd

where:
  μ      = mean of rolling daily returns (typically ≈ 0 for short windows)
  σ      = standard deviation of rolling daily returns
  z_α    = normal quantile for confidence level α
           (99% → 2.326, 95% → 1.645)
  portfolio_usd = total equity to protect

If VaR(99%) > var_limit_pct × total_equity, the breaker trips.

Usage
-----
    from shared.var_circuit_breaker import VaRCircuitBreaker

    vcb = VaRCircuitBreaker(
        var_limit_pct = 0.08,    # trip if 1-day 99% VaR > 8% of equity
        confidence    = 0.99,
        window        = 20,
        pause_hours   = 6.0,
    )

    vcb.record_return(daily_pct_return)   # call once per day (or per cycle)
    triggered, var_pct = vcb.check_and_trip(total_equity_usd)
    if triggered:
        logger.warning(f"VaR CB active — estimated 1d loss > {var_pct:.1%}")

    vcb.to_dict()   # → dict for status.json / admin endpoint

Design Notes
------------
- Minimum 5 observations are required before the breaker can trip.
- Uses population std-dev (divides by N) to match practitioner convention
  for short intraday windows.
- Fail-open: if VaR cannot be computed (e.g. zero variance), the breaker
  does not trip.
- Thread-safe for single-threaded bots; not designed for concurrent access.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional


# Normal quantile look-up table (pre-computed to avoid scipy dependency)
_NORMAL_QUANTILES: dict[float, float] = {
    0.90: 1.2816,
    0.95: 1.6449,
    0.99: 2.3263,
    0.999: 3.0902,
}


def _normal_quantile(confidence: float) -> float:
    """
    Return the one-tailed normal quantile z such that P(X ≤ z) = confidence.
    Looks up the pre-computed table; falls back to a linear approximation.
    """
    if confidence in _NORMAL_QUANTILES:
        return _NORMAL_QUANTILES[confidence]
    # Fallback: Abramowitz & Stegun approximation for confidence ∈ (0.5, 1)
    p = confidence
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    num = c0 + c1 * t + c2 * t * t
    den = 1.0 + d1 * t + d2 * t * t + d3 * t * t * t
    return round(t - num / den, 6)


def compute_parametric_var(
    returns: list[float],
    portfolio_usd: float,
    confidence: float = 0.99,
) -> tuple[float, float]:
    """
    Compute parametric 1-period VaR for a portfolio.

    Parameters
    ----------
    returns       : List of fractional period returns (e.g. [0.01, -0.02, 0.005]).
    portfolio_usd : Total equity in USD.
    confidence    : Confidence level (default 0.99 = 99%).

    Returns
    -------
    (var_usd, var_pct)
        var_usd  : Estimated maximum loss in USD at the given confidence level.
        var_pct  : var_usd as a fraction of portfolio_usd.
        Both are positive numbers representing a loss magnitude.

    Raises
    ------
    ValueError if len(returns) < 2 or portfolio_usd <= 0.
    """
    if len(returns) < 2:
        raise ValueError("Need at least 2 return observations to compute VaR")
    if portfolio_usd <= 0:
        raise ValueError("portfolio_usd must be > 0")

    n    = len(returns)
    mean = sum(returns) / n
    var_sum = sum((r - mean) ** 2 for r in returns)
    # Population std (divides by N, not N-1) — practitioner convention
    std  = math.sqrt(var_sum / n)

    z    = _normal_quantile(confidence)
    # VaR = -(μ - z×σ) expressed as a loss magnitude
    var_pct = max(0.0, -(mean - z * std))
    var_usd = round(var_pct * portfolio_usd, 2)
    var_pct = round(var_pct, 8)
    return var_usd, var_pct


class VaRCircuitBreaker:
    """
    Stateful 1-period parametric VaR circuit breaker.

    The caller feeds daily (or per-cycle) return observations via
    record_return().  Each cycle, check_and_trip(equity) tests whether the
    estimated tail loss exceeds var_limit_pct × equity.

    Parameters
    ----------
    var_limit_pct : float
        Maximum tolerable 1-period VaR as a fraction of total equity.
        Default: 0.08 (8%).  If the 99%-VaR estimate exceeds this, the
        breaker trips and trading is paused.

    confidence : float
        VaR confidence level.  Default: 0.99 (99%).

    window : int
        Rolling window of return observations (default 20).

    min_obs : int
        Minimum observations before the breaker can trip (default 5).

    pause_hours : float
        Trading pause duration after the breaker fires (default 6 hours).
    """

    def __init__(
        self,
        var_limit_pct: float = 0.08,
        confidence:    float = 0.99,
        window:        int   = 20,
        min_obs:       int   = 5,
        pause_hours:   float = 6.0,
    ) -> None:
        self.var_limit_pct = var_limit_pct
        self.confidence    = confidence
        self.window        = window
        self.min_obs       = min_obs
        self.pause_hours   = pause_hours

        self._returns: deque = deque(maxlen=window)
        self._paused_until: Optional[datetime] = None
        self._last_var_pct: float = 0.0
        self._last_var_usd: float = 0.0

    # ── Data ingestion ─────────────────────────────────────────────────────────

    def record_return(self, r: float) -> None:
        """
        Add a fractional return observation.

        Parameters
        ----------
        r : float
            Period return as a decimal fraction (e.g. 0.02 for +2%, -0.015 for -1.5%).
        """
        self._returns.append(float(r))

    # ── VaR computation ───────────────────────────────────────────────────────

    def current_var(self, portfolio_usd: float) -> tuple[float, float]:
        """
        Compute the current estimated VaR.

        Returns
        -------
        (var_usd, var_pct) or (0.0, 0.0) if insufficient data.
        """
        if len(self._returns) < self.min_obs or portfolio_usd <= 0:
            return 0.0, 0.0
        try:
            return compute_parametric_var(
                list(self._returns),
                portfolio_usd,
                self.confidence,
            )
        except Exception:
            return 0.0, 0.0

    # ── Trigger logic ─────────────────────────────────────────────────────────

    def check_and_trip(
        self,
        portfolio_usd: float,
    ) -> tuple[bool, float]:
        """
        Evaluate VaR and trip the breaker if the threshold is exceeded.
        Idempotent while the pause is still active.

        Parameters
        ----------
        portfolio_usd : float
            Current total account equity in USD.

        Returns
        -------
        (triggered: bool, var_pct: float)
            triggered = True  → breaker is active (just fired or already paused).
            var_pct           → estimated 1-period VaR as a fraction of equity.
        """
        if self.is_triggered():
            return True, self._last_var_pct

        var_usd, var_pct = self.current_var(portfolio_usd)
        self._last_var_usd = var_usd
        self._last_var_pct = var_pct

        if var_pct > self.var_limit_pct and len(self._returns) >= self.min_obs:
            self._paused_until = datetime.now(tz=timezone.utc) + timedelta(hours=self.pause_hours)
            return True, var_pct

        return False, var_pct

    def is_triggered(self) -> bool:
        """Return True if the breaker is currently in its pause window."""
        if self._paused_until is None:
            return False
        return datetime.now(tz=timezone.utc) < self._paused_until

    def reset(self) -> None:
        """Clear the pause immediately (e.g. manual override)."""
        self._paused_until = None

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def paused_until(self) -> Optional[datetime]:
        """The UTC datetime when the pause expires, or None if not paused."""
        return self._paused_until if self.is_triggered() else None

    def minutes_remaining(self) -> float:
        """Return minutes left in the current pause, or 0.0 if inactive."""
        if not self.is_triggered():
            return 0.0
        delta = (self._paused_until - datetime.now(tz=timezone.utc)).total_seconds()
        return round(max(delta / 60.0, 0.0), 1)

    def observation_count(self) -> int:
        """Number of return observations currently buffered."""
        return len(self._returns)

    def to_dict(self) -> dict:
        """Serialise current state for status.json / admin endpoint."""
        active = self.is_triggered()
        return {
            "active":             active,
            "paused_until":       self._paused_until.isoformat() if active else None,
            "minutes_remaining":  self.minutes_remaining(),
            "last_var_pct":       round(self._last_var_pct * 100, 3),
            "last_var_usd":       round(self._last_var_usd, 2),
            "var_limit_pct":      round(self.var_limit_pct * 100, 1),
            "confidence_pct":     round(self.confidence * 100, 1),
            "window":             self.window,
            "observation_count":  self.observation_count(),
            "pause_hours":        self.pause_hours,
        }

    def __repr__(self) -> str:
        state = f"paused until {self._paused_until.isoformat()}" if self.is_triggered() else "inactive"
        return (
            f"VaRCircuitBreaker(limit={self.var_limit_pct:.0%}, "
            f"conf={self.confidence:.0%}, window={self.window}, "
            f"state={state})"
        )
