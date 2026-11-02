"""Overfitting checks for FLEET-V1 (plan: research_harness/explore/FLEET-V1-PLAN.md).

- Deflated Sharpe ratio (Bailey & Lopez de Prado 2014): the probability that
  the true Sharpe exceeds the best Sharpe expected from N unskilled trials,
  given the sample's length, skew and kurtosis.
- Monthly block shuffle and percentiles for the random-gear null (N2).

Sharpe ratios here are per period (daily), not annualised, unless stated.
"""

from __future__ import annotations

import math
import random
from datetime import date
from statistics import NormalDist
from typing import Sequence, TypeVar

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()
T = TypeVar("T")


def skew_kurt(r: Sequence[float]) -> tuple[float, float]:
    """Sample skewness and (non-excess) kurtosis; a normal sample gives (0, 3)."""
    n = len(r)
    if n < 3:
        raise ValueError("need at least 3 returns")
    m = sum(r) / n
    m2 = sum((x - m) ** 2 for x in r) / n
    if m2 == 0:
        return 0.0, 3.0
    m3 = sum((x - m) ** 3 for x in r) / n
    m4 = sum((x - m) ** 4 for x in r) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def sharpe_per_period(r: Sequence[float], rf: Sequence[float] | None = None) -> float:
    ex = [x - (rf[i] if rf else 0.0) for i, x in enumerate(r)]
    m = sum(ex) / len(ex)
    sd = math.sqrt(sum((x - m) ** 2 for x in ex) / (len(ex) - 1))
    return m / sd if sd > 0 else 0.0


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """E[max Sharpe] of N unskilled trials whose Sharpe ratios have variance var_sharpe."""
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_trials == 1 or var_sharpe <= 0:
        return 0.0
    z1 = _N.inv_cdf(1 - 1 / n_trials)
    z2 = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(var_sharpe) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def probabilistic_sharpe(sr: float, benchmark: float, n_obs: int, skew: float, kurt: float) -> float:
    """P(true Sharpe > benchmark) for an observed per-period Sharpe sr over n_obs returns."""
    if n_obs < 2:
        raise ValueError("need at least 2 observations")
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        raise ValueError("non-positive variance term; check skew/kurtosis inputs")
    return _N.cdf((sr - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def deflated_sharpe(r: Sequence[float], rf: Sequence[float] | None, n_trials: int,
                    var_sharpe: float) -> dict[str, float]:
    """Deflated Sharpe ratio of a return series (excess of rf when given).
    var_sharpe: variance of the per-period Sharpe ratios across the trials."""
    ex = [x - (rf[i] if rf else 0.0) for i, x in enumerate(r)]
    sr = sharpe_per_period(ex)
    sk, ku = skew_kurt(ex)
    sr0 = expected_max_sharpe(n_trials, var_sharpe)
    return {"sharpe_per_period": sr, "sharpe_annual": sr * math.sqrt(252), "skew": sk,
            "kurtosis": ku, "n_obs": len(ex), "n_trials": n_trials, "var_sharpe": var_sharpe,
            "expected_max_sharpe": sr0, "dsr": probabilistic_sharpe(sr, sr0, len(ex), sk, ku)}


def variance(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def month_blocks(days: Sequence[date], labels: Sequence[T]) -> list[list[T]]:
    """Labels grouped into consecutive calendar-month blocks."""
    blocks: list[list[T]] = []
    key = None
    for d, x in zip(days, labels):
        if (d.year, d.month) != key:
            blocks.append([])
            key = (d.year, d.month)
        blocks[-1].append(x)
    return blocks


def block_shuffle(days: Sequence[date], labels: Sequence[T], rng: random.Random) -> list[T]:
    """The label sequence with its monthly blocks in random order. Same length
    and same share of each label; positions are re-attached to the original days."""
    blocks = month_blocks(days, labels)
    rng.shuffle(blocks)
    return [x for b in blocks for x in b]


def percentile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile, q in [0, 100]."""
    if not xs:
        raise ValueError("empty")
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
