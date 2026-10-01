"""Exploratory Bot 2 trend candidates built on the shared backtest harness.

This module only creates target weights and reports; all cash, holdings,
execution, financing, stops, and portfolio accounting are delegated to
``analysis.backtest_harness``. The executable path is deliberately explicit:
``--print-spec`` only prints the frozen JSON/hash, while ``--run`` runs the
eight in-sample cost scenarios and appends them to Helium ``exploration_runs``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import stdev
from typing import Any

from analysis.backtest_harness import (
    BacktestResult,
    PricePanel,
    load_adjusted_close,
    run_backtest,
)
from db.research_postgres import get_research_conn

START_DATE = date(2008, 1, 1)
END_DATE = date(2022, 12, 31)
WARMUP_START = date(2000, 1, 1)
UNIVERSE = (
    "TLT",
    "IEF",
    "TIP",
    "BWX",
    "DBC",
    "DBE",
    "DBA",
    "DBB",
    "UUP",
    "FXY",
    "FXF",
    "FXA",
)
CASH_ASSET = "BIL"
BENCHMARK = "SPY"
VOLATILITY_LOOKBACK = 60
MINIMUM_HISTORY = 200
REBALANCE_EVERY = 5
FAST_EMA = 50
SLOW_EMA = 200
TREND_BAND = 0.001
TRAILING_STOP = 0.08
TARGET_ANNUAL_VOLATILITY = 0.10
TRADING_DAYS_PER_YEAR = 252
STARTING_EQUITY = 100_000.0
BORROW_FEE_RATE = 0.01
MARGIN_RATE = 0.0625
RISK_FREE_RATE = 0.0
GROSS_CAP = 1.5
CASH_GROSS_CAP = 1.0
SOURCE = "backtest_harness f7ff08e8"
STRATEGY_FAMILY = "bot2_trend_v1.1"
EVALUATION_WINDOWS = (
    ("2008-09-01", "2009-03-31"),
    ("2009-04-01", "2013-06-30"),
    ("2015-06-01", "2016-02-29"),
    ("2020-02-15", "2020-04-30"),
    ("2022-01-01", "2022-12-31"),
)
RUN_PLAN = tuple(
    [(candidate, 5) for candidate in ("A", "B", "C", "D")]
    + [(candidate, 10) for candidate in ("A", "B", "C", "D")]
)

# Interpretation details are part of the hash so future comparisons can use
# the same allocation, rebalancing, and volatility-targeting conventions.
SPEC: dict[str, Any] = {
    "universe": list(UNIVERSE),
    "cash_asset": CASH_ASSET,
    "benchmark_only": BENCHMARK,
    "evaluation_window": {
        "start": START_DATE.isoformat(),
        "end": END_DATE.isoformat(),
    },
    "warmup": {
        "load_start": WARMUP_START.isoformat(),
        "eligibility": f"{MINIMUM_HISTORY} unflagged closes per symbol",
        "ema_initialization": "recursive EMA seeded from first loaded close",
    },
    "signal": {
        "fast_ema": FAST_EMA,
        "slow_ema": SLOW_EMA,
        "long_if_fast_exceeds_slow_by": TREND_BAND,
        "short_if_fast_below_slow_by": -TREND_BAND,
        "otherwise": "flat",
    },
    "sizing": {
        "method": "inverse trailing volatility, equal risk per active position",
        "lookback_daily_returns": VOLATILITY_LOOKBACK,
        "return_calendar": "common unflagged adjusted-close sessions",
        "annualization_trading_days": TRADING_DAYS_PER_YEAR,
        "A_B_risk_budget": "active position count divided by 12",
        "C_risk_budget": "gross 1.0 across all 12 eligible instruments",
        "cash_weight": (
            "BIL residual weight is max(0, 1 minus signed risky weights); "
            "excess leverage is funded by negative cash"
        ),
    },
    "rebalance": {
        "A_B_D": f"every {REBALANCE_EVERY} common trading sessions",
        "C": (
            f"after all 12 instruments are eligible, rebalance every "
            f"{REBALANCE_EVERY} common trading sessions to inverse-volatility "
            f"equal-risk weights scaled to {TARGET_ANNUAL_VOLATILITY:.0%}; "
            f"gross <= {GROSS_CAP}"
        ),
        "execution": "next common valid close, by backtest_harness",
    },
    "trailing_stop": {
        "fraction": TRAILING_STOP,
        "applies_to": (
            "A and B ETF holdings; C has no stops; D's 8% stop applies only "
            "to its trend sleeve, retaining the passive risk-parity sleeve"
        ),
        "cash_asset": (
            "BIL is a non-negative residual cash leg, never part of a "
            "stop-managed sleeve; preflight checks its loaded history"
        ),
    },
    "portfolio_constraints": {
        "gross_cap_A": CASH_GROSS_CAP,
        "gross_cap_B_C_D": GROSS_CAP,
        "whole_shares": True,
        "starting_equity": STARTING_EQUITY,
        "borrow_fee_rate": BORROW_FEE_RATE,
        "margin_rate": MARGIN_RATE,
        "risk_free_rate": RISK_FREE_RATE,
        "cost_model": "cost_bps is charged per side on absolute traded notional",
        "financing_model": (
            "negative cash is charged margin_rate; borrow fees apply only "
            "to short ETF positions; BIL weight is floored at zero"
        ),
    },
    "volatility_targeting": {
        "annual_target": TARGET_ANNUAL_VOLATILITY,
        "estimator": "sample covariance of the trailing 60 common daily returns",
        "cash_treatment": (
            "BIL is a non-negative residual weight; leverage beyond net "
            "cash is negative cash, not a short BIL position"
        ),
        "gross_limit": GROSS_CAP,
        "D": (
            "blend half of B and half of C risky target weights; recalculate "
            "the C sleeve every 5 common sessions, then retarget the blend"
        ),
    },
    "cost_bps_scenarios": [5, 10],
    "reporting": {
        "window_returns": [list(window) for window in EVALUATION_WINDOWS],
        "spy_correlation": "daily strategy equity returns versus SPY buy-and-hold",
        "correlation_matrix_symbols": list(UNIVERSE),
        "metrics": [
            "total_return",
            "cagr",
            "annualised_volatility",
            "sharpe",
            "sortino",
            "max_drawdown",
            "calmar",
            "turnover",
            "average_gross_exposure",
            "average_net_exposure",
            "number_of_trades",
            "total_costs",
            "total_interest",
            "total_borrow_fees",
            "total_traded_notional",
        ],
    },
    "candidates": {
        "A": (
            "long uptrends only; non-negative residual allocation in BIL; "
            "gross <= 1.0"
        ),
        "B": (
            "long uptrends and short downtrends; 10% annual volatility "
            "target; BIL weight >= 0; gross <= 1.5"
        ),
        "C": (
            "no timing signal; inverse-volatility long-only risk parity "
            "rebalanced every 5 common sessions to a 10% volatility target; "
            "gross <= 1.5"
        ),
        "D": (
            "50/50 blend of B and C risky target weights; C sleeve recalculated "
            "every 5 common sessions; retarget blend to 10%; gross <= 1.5; "
            "8% stop applies only to trend sleeve"
        ),
    },
    "quality_and_calendar": {
        "flagged_rows": "drop; never fill",
        "session_calendar": "intersection of unflagged adjusted-close dates",
        "no_dates_after": END_DATE.isoformat(),
    },
    "persistence": {
        "destination": "exploration_runs only",
        "strategy_family": STRATEGY_FAMILY,
        "source": SOURCE,
        "never_write_research_ledger_results": True,
    },
}

SPEC_CHANGES = [
    {
        "item": "1a",
        "change": (
            "Floor BIL weight at zero; fund excess leverage with negative "
            "cash charged at margin_rate; assess borrow fees only on short ETFs."
        ),
        "why": "The memo requires margin interest on borrowed money.",
    },
    {
        "item": "1b",
        "change": (
            "Rebalance C every five common trading sessions to equal-risk "
            "weights scaled to 10% volatility with a 1.5 gross cap; D recalculates "
            "its C sleeve on the same schedule."
        ),
        "why": "C's volatility target requires rebalancing.",
    },
    {
        "item": "1c",
        "change": "Describe D's 8% stop as applying only to its trend sleeve.",
        "why": "This makes the text match the code.",
    },
]


@dataclass(frozen=True)
class CandidateRun:
    candidate: str
    cost_bps: int
    result: BacktestResult
    diagnostics: dict[str, Any]


def canonical_spec_json(spec: Mapping[str, Any] = SPEC) -> str:
    """Return the deterministic JSON representation covered by the hash."""
    return json.dumps(
        spec,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def spec_hash(spec: Mapping[str, Any] = SPEC) -> str:
    return hashlib.sha256(canonical_spec_json(spec).encode("utf-8")).hexdigest()


def print_spec() -> dict[str, Any]:
    """Print the corrected spec, its SHA-256, and the precise corrections."""
    payload = {
        "spec": SPEC,
        "spec_hash": spec_hash(),
        "changes_from_dd977b3c": SPEC_CHANGES,
    }
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False), flush=True)
    return payload


def classify_ema_trend(
    fast: float,
    slow: float,
    *,
    band: float = TREND_BAND,
) -> int:
    """Return +1, -1, or 0 using the specified strict 0.1% flat band."""
    if not all(math.isfinite(value) for value in (fast, slow, band)):
        raise ValueError("EMA inputs and band must be finite")
    if slow <= 0 or band < 0:
        raise ValueError("slow EMA must be positive and band non-negative")
    relative_difference = fast / slow - 1.0
    if relative_difference > band:
        return 1
    if relative_difference < -band:
        return -1
    return 0


def ema_last(values: Sequence[float], span: int) -> float:
    """Compute adjust=False EMA, seeded from the first supplied observation."""
    if span <= 0:
        raise ValueError("EMA span must be positive")
    if not values:
        raise ValueError("EMA requires at least one observation")
    alpha = 2.0 / (span + 1.0)
    current = float(values[0])
    if not math.isfinite(current) or current <= 0:
        raise ValueError("EMA prices must be finite and positive")
    for raw_value in values[1:]:
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("EMA prices must be finite and positive")
        current += alpha * (value - current)
    return current


def _common_dates(
    history: Mapping[str, Mapping[date, float]],
    symbols: Sequence[str],
) -> list[date]:
    if not symbols:
        return []
    try:
        date_sets = [set(history[symbol]) for symbol in symbols]
    except KeyError as exc:
        raise ValueError(f"History is missing required symbol {exc.args[0]}") from exc
    return sorted(set.intersection(*date_sets))


def _returns_by_symbol(
    history: Mapping[str, Mapping[date, float]],
    symbols: Sequence[str],
    *,
    lookback: int = VOLATILITY_LOOKBACK,
) -> dict[str, list[float]]:
    """Get aligned trailing returns without filling missing price rows."""
    if lookback <= 1:
        raise ValueError("lookback must be at least two returns")
    dates = _common_dates(history, symbols)
    if len(dates) < lookback + 1:
        return {}
    dates = dates[-(lookback + 1) :]
    returns: dict[str, list[float]] = {}
    for symbol in symbols:
        prices = [float(history[symbol][day]) for day in dates]
        symbol_returns = [
            prices[index] / prices[index - 1] - 1.0
            for index in range(1, len(prices))
        ]
        if any(not math.isfinite(value) for value in symbol_returns):
            raise ValueError(f"Non-finite return in {symbol} history")
        returns[symbol] = symbol_returns
    return returns


def _volatilities(
    history: Mapping[str, Mapping[date, float]],
    symbols: Sequence[str],
) -> dict[str, float]:
    aligned = _returns_by_symbol(
        history,
        symbols,
        lookback=VOLATILITY_LOOKBACK,
    )
    if not aligned:
        return {}
    result: dict[str, float] = {}
    for symbol, values in aligned.items():
        volatility = stdev(values)
        if math.isfinite(volatility) and volatility > 0:
            result[symbol] = volatility
    return result


def equal_risk_weights(
    volatilities: Mapping[str, float],
    directions: Mapping[str, int],
    *,
    total_gross_budget: float,
) -> dict[str, float]:
    """Allocate an equal volatility-risk budget using inverse-vol weights."""
    if not math.isfinite(total_gross_budget) or total_gross_budget < 0:
        raise ValueError("total_gross_budget must be finite and non-negative")
    active = [
        symbol
        for symbol, direction in directions.items()
        if direction in (-1, 1)
        and symbol in volatilities
        and math.isfinite(volatilities[symbol])
        and volatilities[symbol] > 0
    ]
    if not active or total_gross_budget == 0:
        return {}
    inverse_vol = {symbol: 1.0 / volatilities[symbol] for symbol in active}
    denominator = math.fsum(inverse_vol.values())
    if denominator <= 0 or not math.isfinite(denominator):
        raise ValueError("Could not normalize equal-risk weights")
    return {
        symbol: directions[symbol] * total_gross_budget * inverse_vol[symbol] / denominator
        for symbol in active
    }


def _sample_variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = math.fsum(values) / len(values)
    return math.fsum((value - average) ** 2 for value in values) / (len(values) - 1)


def _sample_covariance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    return math.fsum(
        (x - left_mean) * (y - right_mean)
        for x, y in zip(left, right, strict=True)
    ) / (len(left) - 1)


def _gross_at_scale(risky_weights: Mapping[str, float], scale: float) -> float:
    risky_gross = math.fsum(abs(scale * weight) for weight in risky_weights.values())
    cash_weight = max(0.0, 1.0 - scale * math.fsum(risky_weights.values()))
    return risky_gross + cash_weight


def _portfolio_volatility_at_scale(
    risky_weights: Mapping[str, float],
    aligned_returns: Mapping[str, Sequence[float]],
    scale: float,
    cash_asset: str,
) -> float:
    cash_returns = aligned_returns[cash_asset]
    risky_net = math.fsum(risky_weights.values())
    cash_weight = max(0.0, 1.0 - scale * risky_net)
    portfolio_returns = [
        scale
        * math.fsum(
            risky_weights[symbol] * aligned_returns[symbol][index]
            for symbol in risky_weights
        )
        + cash_weight * cash_returns[index]
        for index in range(len(cash_returns))
    ]
    return math.sqrt(
        max(0.0, _sample_variance(portfolio_returns))
        * TRADING_DAYS_PER_YEAR
    )


def _scale_to_target_volatility_with_factor(
    history: Mapping[str, Mapping[date, float]],
    risky_weights: Mapping[str, float],
    *,
    cash_asset: str = CASH_ASSET,
    target_annual_volatility: float = TARGET_ANNUAL_VOLATILITY,
    max_gross: float = GROSS_CAP,
) -> tuple[dict[str, float], float]:
    """Scale a signed risky sleeve; BIL is floored at zero when leveraged.

    The scalar is solved against the trailing 60-session covariance of the
    risky sleeve and any non-negative BIL balance. Excess leverage is negative
    cash in the harness, not a short BIL holding. The feasible scalar is capped
    by the gross limit.
    """
    if not math.isfinite(target_annual_volatility) or target_annual_volatility <= 0:
        raise ValueError("target_annual_volatility must be finite and positive")
    if not math.isfinite(max_gross) or max_gross < 1.0:
        raise ValueError("max_gross must be finite and at least 1.0")
    nonzero = {
        symbol: float(weight)
        for symbol, weight in risky_weights.items()
        if abs(float(weight)) > 1e-14
    }
    if cash_asset in nonzero:
        raise ValueError("risky_weights must not include the cash asset")
    if not nonzero:
        return {cash_asset: 1.0}, 0.0

    symbols = tuple(dict.fromkeys((cash_asset, *sorted(nonzero))))
    aligned = _returns_by_symbol(history, symbols)
    if not aligned:
        raise ValueError(
            f"At least {VOLATILITY_LOOKBACK} aligned returns are required "
            "for volatility scaling"
        )

    low = 0.0
    high = 1.0
    while _gross_at_scale(nonzero, high) <= max_gross and high < 1_000_000:
        high *= 2.0
    for _ in range(80):
        midpoint = (low + high) / 2.0
        if _gross_at_scale(nonzero, midpoint) <= max_gross:
            low = midpoint
        else:
            high = midpoint
    max_scale = low

    risky_net = math.fsum(nonzero.values())
    cash_returns = aligned[cash_asset]
    differential = [
        math.fsum(
            nonzero[symbol] * aligned[symbol][index]
            for symbol in nonzero
        )
        - risky_net * cash_returns[index]
        for index in range(len(cash_returns))
    ]
    variance_cash = _sample_variance(cash_returns)
    variance_diff = _sample_variance(differential)
    twice_covariance = 2.0 * _sample_covariance(cash_returns, differential)
    target_variance = (
        target_annual_volatility / math.sqrt(TRADING_DAYS_PER_YEAR)
    ) ** 2
    quadratic_a = variance_diff
    quadratic_b = twice_covariance
    quadratic_c = variance_cash - target_variance

    cash_segment_max = max_scale
    if risky_net > 0:
        cash_segment_max = min(max_scale, 1.0 / risky_net)

    # While BIL remains positive, variance is a quadratic in the scale.
    # Include its target crossings and vertex so the closest attainable
    # volatility is selected even when the target lies outside the range.
    candidates = [0.0, max_scale, cash_segment_max]
    if cash_segment_max > 0:
        cash_segment_candidates: list[float] = []
        if abs(quadratic_a) <= 1e-18:
            if abs(quadratic_b) > 1e-18:
                cash_segment_candidates.append(-quadratic_c / quadratic_b)
        else:
            discriminant = quadratic_b**2 - 4.0 * quadratic_a * quadratic_c
            if discriminant >= 0:
                root = math.sqrt(discriminant)
                cash_segment_candidates.extend(
                    (
                        (-quadratic_b - root) / (2.0 * quadratic_a),
                        (-quadratic_b + root) / (2.0 * quadratic_a),
                    )
                )
            cash_segment_candidates.append(-quadratic_b / (2.0 * quadratic_a))
        candidates.extend(
            value
            for value in cash_segment_candidates
            if math.isfinite(value) and 0.0 <= value <= cash_segment_max
        )

    # Once BIL reaches zero, leverage is funded by negative cash. With
    # constant target weights, the risky-sleeve variance scales quadratically.
    if max_scale > cash_segment_max:
        risky_portfolio_returns = [
            math.fsum(
                nonzero[symbol] * aligned[symbol][index]
                for symbol in nonzero
            )
            for index in range(len(cash_returns))
        ]
        risky_variance = _sample_variance(risky_portfolio_returns)
        if risky_variance > 0:
            leveraged_target_scale = math.sqrt(target_variance / risky_variance)
            if cash_segment_max <= leveraged_target_scale <= max_scale:
                candidates.append(leveraged_target_scale)

    candidates = [
        value
        for value in candidates
        if math.isfinite(value) and 0.0 <= value <= max_scale
    ]
    scale = min(
        candidates,
        key=lambda value: (
            abs(
                _portfolio_volatility_at_scale(
                    nonzero,
                    aligned,
                    value,
                    cash_asset,
                )
                - target_annual_volatility
            ),
            abs(value - 1.0),
        ),
    )

    result = {symbol: scale * weight for symbol, weight in nonzero.items()}
    result[cash_asset] = max(0.0, 1.0 - scale * risky_net)
    if _gross_at_scale(nonzero, scale) > max_gross + 1e-9:
        raise RuntimeError("Volatility scaling exceeded the gross cap")
    return (
        {
            symbol: weight
            for symbol, weight in result.items()
            if abs(weight) > 1e-14
        },
        scale,
    )


def scale_to_target_volatility(
    history: Mapping[str, Mapping[date, float]],
    risky_weights: Mapping[str, float],
    *,
    cash_asset: str = CASH_ASSET,
    target_annual_volatility: float = TARGET_ANNUAL_VOLATILITY,
    max_gross: float = GROSS_CAP,
) -> dict[str, float]:
    """Scale a signed risky sleeve to target volatility, balancing with BIL."""
    result, _ = _scale_to_target_volatility_with_factor(
        history,
        risky_weights,
        cash_asset=cash_asset,
        target_annual_volatility=target_annual_volatility,
        max_gross=max_gross,
    )
    return result


def _base_weights_for_directions(
    history: Mapping[str, Mapping[date, float]],
    directions: Mapping[str, int],
    *,
    universe: Sequence[str],
) -> dict[str, float]:
    eligible = [
        symbol
        for symbol in universe
        if len(history[symbol]) >= MINIMUM_HISTORY
        and directions.get(symbol, 0) in (-1, 1)
    ]
    if not eligible:
        return {}
    volatilities = _volatilities(history, (*universe, CASH_ASSET))
    if not volatilities:
        return {}
    budget = len(eligible) / len(universe)
    return equal_risk_weights(
        volatilities,
        {symbol: directions[symbol] for symbol in eligible},
        total_gross_budget=budget,
    )


def _base_risk_parity_weights(
    history: Mapping[str, Mapping[date, float]],
    *,
    universe: Sequence[str],
) -> dict[str, float]:
    eligible = [
        symbol for symbol in universe if len(history[symbol]) >= MINIMUM_HISTORY
    ]
    if not eligible:
        return {}
    volatilities = _volatilities(history, (*universe, CASH_ASSET))
    if not volatilities:
        return {}
    budget = len(eligible) / len(universe)
    return equal_risk_weights(
        volatilities,
        {symbol: 1 for symbol in eligible},
        total_gross_budget=budget,
    )


def blend_half_weights(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> dict[str, float]:
    """Return the 50/50 target-weight blend, retaining signed exposures."""
    symbols = set(left) | set(right)
    return {
        symbol: 0.5 * float(left.get(symbol, 0.0))
        + 0.5 * float(right.get(symbol, 0.0))
        for symbol in sorted(symbols)
        if abs(
            0.5 * float(left.get(symbol, 0.0))
            + 0.5 * float(right.get(symbol, 0.0))
        )
        > 1e-14
    }


def _build_candidate_targets_and_stop_weights(
    candidate: str,
    history: Mapping[str, Mapping[date, float]],
    trend_directions: Mapping[str, int],
    *,
    universe: Sequence[str] = UNIVERSE,
    cash_asset: str = CASH_ASSET,
) -> tuple[dict[str, float], dict[str, float]]:
    """Build portfolio weights and the separately stopped trend sleeve."""
    if candidate not in {"A", "B", "C", "D"}:
        raise ValueError(f"Unknown candidate: {candidate!r}")
    if not universe or len(set(universe)) != len(universe):
        raise ValueError("universe must contain unique symbols")
    if cash_asset in universe:
        raise ValueError("cash asset must be outside the risk universe")

    if candidate == "C":
        if not all(len(history[symbol]) >= MINIMUM_HISTORY for symbol in universe):
            return {cash_asset: 1.0}, {}
        c_base = _base_risk_parity_weights(history, universe=universe)
        target = scale_to_target_volatility(
            history,
            c_base,
            cash_asset=cash_asset,
            max_gross=GROSS_CAP,
        )
        return target, {}

    if candidate == "A":
        long_directions = {
            symbol: 1
            for symbol in universe
            if trend_directions.get(symbol, 0) == 1
        }
        b_base = _base_weights_for_directions(
            history,
            long_directions,
            universe=universe,
        )
        long_symbols = {
            symbol: weight for symbol, weight in b_base.items() if weight > 0
        }
        cash_weight = max(0.0, 1.0 - math.fsum(long_symbols.values()))
        result = {**long_symbols, cash_asset: cash_weight}
        target = {
            symbol: weight
            for symbol, weight in result.items()
            if abs(weight) > 1e-14
        }
        return target, long_symbols

    b_base = _base_weights_for_directions(
        history,
        trend_directions,
        universe=universe,
    )
    if candidate == "B":
        if not b_base:
            return {cash_asset: 1.0}, {}
        target = scale_to_target_volatility(
            history,
            b_base,
            cash_asset=cash_asset,
            max_gross=GROSS_CAP,
        )
        stop_weights = {
            symbol: weight
            for symbol, weight in target.items()
            if symbol != cash_asset
        }
        return target, stop_weights

    # Candidate D blends B's current trend sleeve with C's current risk-parity
    # sleeve. The blended target is then independently volatility-scaled.
    b_target = (
        scale_to_target_volatility(
            history,
            b_base,
            cash_asset=cash_asset,
            max_gross=GROSS_CAP,
        )
        if b_base
        else {cash_asset: 1.0}
    )
    c_base = _base_risk_parity_weights(history, universe=universe)
    c_target = (
        scale_to_target_volatility(
            history,
            c_base,
            cash_asset=cash_asset,
            max_gross=GROSS_CAP,
        )
        if c_base
        else {cash_asset: 1.0}
    )
    blend = blend_half_weights(b_target, c_target)
    blended_risky = {
        symbol: weight for symbol, weight in blend.items() if symbol != cash_asset
    }
    target, retarget_scale = _scale_to_target_volatility_with_factor(
        history,
        blended_risky,
        cash_asset=cash_asset,
        max_gross=GROSS_CAP,
    )
    stop_weights = {
        symbol: 0.5 * weight * retarget_scale
        for symbol, weight in b_target.items()
        if symbol != cash_asset and abs(0.5 * weight * retarget_scale) > 1e-14
    }
    return target, stop_weights


def build_candidate_targets(
    candidate: str,
    history: Mapping[str, Mapping[date, float]],
    trend_directions: Mapping[str, int],
    *,
    universe: Sequence[str] = UNIVERSE,
    cash_asset: str = CASH_ASSET,
) -> dict[str, float]:
    """Build one candidate's target weights; C deliberately ignores trend state."""
    target, _ = _build_candidate_targets_and_stop_weights(
        candidate,
        history,
        trend_directions,
        universe=universe,
        cash_asset=cash_asset,
    )
    return target


class CandidateSignal:
    """Stateful, as-of-only candidate signal callable for the harness."""

    def __init__(
        self,
        candidate: str,
        sessions: Sequence[date],
        *,
        universe: Sequence[str] = UNIVERSE,
        cash_asset: str = CASH_ASSET,
    ) -> None:
        if candidate not in {"A", "B", "C", "D"}:
            raise ValueError(f"Unknown candidate: {candidate!r}")
        self.candidate = candidate
        self.sessions = tuple(sessions)
        self.session_index = {day: index for index, day in enumerate(self.sessions)}
        self.universe = tuple(universe)
        self.cash_asset = cash_asset
        self._initialized = False
        self._last_processed_day: date | None = None
        self._ema_fast: dict[str, float | None] = {
            symbol: None for symbol in self.universe
        }
        self._ema_slow: dict[str, float | None] = {
            symbol: None for symbol in self.universe
        }
        self._close_counts = {symbol: 0 for symbol in self.universe}
        self._cash_parked = False
        self._c_entered = False
        self._c_last_rebalance_index: int | None = None
        self._last_signal_day: date | None = None
        self._last_stop_weights: dict[str, float] | None = None

    def _update_ema(self, symbol: str, close: float) -> None:
        if not math.isfinite(close) or close <= 0:
            raise ValueError(f"Invalid adjusted close for {symbol}")
        fast = self._ema_fast[symbol]
        slow = self._ema_slow[symbol]
        self._ema_fast[symbol] = (
            close
            if fast is None
            else fast + (2.0 / (FAST_EMA + 1.0)) * (close - fast)
        )
        self._ema_slow[symbol] = (
            close
            if slow is None
            else slow + (2.0 / (SLOW_EMA + 1.0)) * (close - slow)
        )
        self._close_counts[symbol] += 1

    def _ingest_as_of_history(
        self,
        history: Mapping[str, Mapping[date, float]],
        day: date,
    ) -> None:
        if not self._initialized:
            for symbol in self.universe:
                for _, close in history[symbol].items():
                    self._update_ema(symbol, float(close))
            self._initialized = True
            self._last_processed_day = day
            return
        if self._last_processed_day == day:
            return
        for symbol in self.universe:
            self._update_ema(symbol, float(history[symbol][day]))
        self._last_processed_day = day

    def _trend_directions(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for symbol in self.universe:
            fast = self._ema_fast[symbol]
            slow = self._ema_slow[symbol]
            result[symbol] = (
                classify_ema_trend(fast, slow)
                if self._close_counts[symbol] >= MINIMUM_HISTORY
                and fast is not None
                and slow is not None
                else 0
            )
        return result

    def __call__(
        self,
        history: Mapping[str, Mapping[date, float]],
        day: date,
    ) -> Mapping[str, float] | None:
        if day not in self.session_index:
            raise ValueError(f"Signal date {day} is outside the session calendar")
        self._last_signal_day = None
        self._last_stop_weights = None
        self._ingest_as_of_history(history, day)
        index = self.session_index[day]
        if index == len(self.sessions) - 1:
            return None

        if self.candidate == "C":
            if not self._cash_parked:
                self._cash_parked = True
                return self._record_targets(day, {self.cash_asset: 1.0}, {})
            if (
                self._c_entered
                and self._c_last_rebalance_index is not None
                and index - self._c_last_rebalance_index < REBALANCE_EVERY
            ):
                return None
            if not all(
                self._close_counts[symbol] >= MINIMUM_HISTORY
                for symbol in self.universe
            ):
                return None
            target, stop_weights = _build_candidate_targets_and_stop_weights(
                "C",
                history,
                self._trend_directions(),
                universe=self.universe,
                cash_asset=self.cash_asset,
            )
            self._c_entered = True
            self._c_last_rebalance_index = index
            return self._record_targets(day, target, stop_weights)

        if index % REBALANCE_EVERY:
            return None
        target, stop_weights = _build_candidate_targets_and_stop_weights(
            self.candidate,
            history,
            self._trend_directions(),
            universe=self.universe,
            cash_asset=self.cash_asset,
        )
        return self._record_targets(day, target, stop_weights)

    def _record_targets(
        self,
        day: date,
        target: dict[str, float],
        stop_weights: dict[str, float],
    ) -> dict[str, float]:
        self._last_signal_day = day
        self._last_stop_weights = stop_weights
        return target

    def trailing_stop_signal(
        self,
        _history: Mapping[str, Mapping[date, float]],
        day: date,
    ) -> Mapping[str, float] | None:
        """Return the stop-managed sleeve paired with this day's target."""
        if self._last_signal_day != day:
            return None
        return dict(self._last_stop_weights or {})


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_sd = stdev(left)
    right_sd = stdev(right)
    if left_sd == 0 or right_sd == 0:
        return 0.0
    covariance = _sample_covariance(left, right)
    return covariance / (left_sd * right_sd)


def in_sample_correlation_matrix(
    panel: PricePanel,
    *,
    universe: Sequence[str] = UNIVERSE,
) -> dict[str, dict[str, float]]:
    """Pairwise instrument correlations over common valid in-sample sessions."""
    dates = _common_dates(panel.closes, universe)
    dates = [
        day for day in dates
        if START_DATE <= day <= END_DATE
    ]
    if not dates:
        raise ValueError("No common in-sample prices for correlation matrix")
    # Include the immediately preceding common close to form the first return.
    all_dates = _common_dates(panel.closes, universe)
    prior = [day for day in all_dates if day < START_DATE]
    if prior:
        dates = [prior[-1], *dates]
    returns = {symbol: [] for symbol in universe}
    for index in range(1, len(dates)):
        previous_day, current_day = dates[index - 1], dates[index]
        if current_day < START_DATE:
            continue
        for symbol in universe:
            previous = panel.closes[symbol][previous_day]
            current = panel.closes[symbol][current_day]
            returns[symbol].append(current / previous - 1.0)
    return {
        left: {
            right: _pearson(returns[left], returns[right])
            for right in universe
        }
        for left in universe
    }


def _window_return(
    equity_curve: Sequence[Mapping[str, Any]],
    start: date,
    end: date,
) -> float:
    before = [
        point for point in equity_curve
        if point["date"] <= start
    ]
    through = [
        point for point in equity_curve
        if point["date"] <= end
    ]
    if not before or not through:
        raise ValueError(f"Equity curve does not cover {start} through {end}")
    initial = float(before[-1]["equity"])
    final = float(through[-1]["equity"])
    if initial <= 0:
        raise ValueError("Window return requires positive starting equity")
    return final / initial - 1.0


def window_returns(
    result: BacktestResult,
) -> dict[str, float]:
    curve = result.equity_curve
    return {
        f"{start}..{end}": _window_return(
            curve,
            date.fromisoformat(start),
            date.fromisoformat(end),
        )
        for start, end in EVALUATION_WINDOWS
    }


def correlation_with_spy(
    result: BacktestResult,
    spy_panel: PricePanel,
) -> float:
    spy = spy_panel.closes[BENCHMARK]
    curve = result.equity_curve
    strategy_returns: list[float] = []
    benchmark_returns: list[float] = []
    for index in range(1, len(curve)):
        previous = curve[index - 1]
        current = curve[index]
        previous_day = previous["date"]
        current_day = current["date"]
        if previous_day not in spy or current_day not in spy:
            continue
        previous_equity = float(previous["equity"])
        if previous_equity <= 0:
            continue
        strategy_returns.append(
            float(current["equity"]) / previous_equity - 1.0
        )
        benchmark_returns.append(spy[current_day] / spy[previous_day] - 1.0)
    return _pearson(strategy_returns, benchmark_returns)


def _count_margin_calls(result: BacktestResult) -> int:
    return sum(event.get("type") == "margin_call" for event in result.events)


def _common_sessions(panel: PricePanel) -> list[date]:
    dates = _common_dates(panel.closes, tuple(panel.closes))
    return [
        day for day in dates
        if START_DATE <= day <= END_DATE
    ]


def buy_and_hold_metrics(
    panel: PricePanel,
    symbol: str = CASH_ASSET,
) -> dict[str, Any]:
    """Calculate buy-and-hold return and CAGR on the strategy's shared sessions."""
    if symbol not in panel.closes:
        raise ValueError(f"Price panel is missing buy-and-hold symbol {symbol}")
    sessions = _common_sessions(panel)
    if len(sessions) < 2:
        raise ValueError("At least two common sessions are required for buy-and-hold")
    start_day, end_day = sessions[0], sessions[-1]
    start_price = panel.closes[symbol][start_day]
    end_price = panel.closes[symbol][end_day]
    total_return = end_price / start_price - 1.0
    elapsed_days = (end_day - start_day).days
    if elapsed_days <= 0:
        raise ValueError("Buy-and-hold CAGR requires a positive evaluation period")
    cagr = (end_price / start_price) ** (
        365.0 / elapsed_days
    ) - 1.0
    if not math.isfinite(total_return) or not math.isfinite(cagr):
        raise ValueError("Buy-and-hold metrics must be finite")
    return {
        "symbol": symbol,
        "requested_start": START_DATE.isoformat(),
        "requested_end": END_DATE.isoformat(),
        "actual_start": start_day.isoformat(),
        "actual_end": end_day.isoformat(),
        "total_return": total_return,
        "cagr": cagr,
    }


def _check_cash_asset_stop_compatibility(panel: PricePanel) -> None:
    """Fail before any run if a global harness stop could exit the BIL cash leg."""
    closes = panel.closes[CASH_ASSET]
    high = 0.0
    max_drawdown = 0.0
    for _, price in sorted(closes.items()):
        high = max(high, price)
        if high > 0:
            max_drawdown = max(max_drawdown, (high - price) / high)
    if max_drawdown >= TRAILING_STOP:
        raise RuntimeError(
            "BIL breached the global harness trailing-stop threshold; "
            "stop execution until trend-only stop handling is available"
        )


def _make_result_record(
    candidate: str,
    cost_bps: int,
    panel: PricePanel,
    spy_panel: PricePanel,
) -> CandidateRun:
    sessions = _common_sessions(panel)
    if len(sessions) < 2:
        raise ValueError("At least two common in-sample sessions are required")
    signal = CandidateSignal(candidate, sessions)
    result = run_backtest(
        panel,
        signal,
        START_DATE,
        END_DATE,
        cost_bps=cost_bps,
        borrow_fee_rate=BORROW_FEE_RATE,
        risk_free_rate=RISK_FREE_RATE,
        margin_rate=MARGIN_RATE,
        max_gross=CASH_GROSS_CAP if candidate == "A" else GROSS_CAP,
        starting_equity=STARTING_EQUITY,
        whole_shares=True,
        trail_pct=None if candidate == "C" else TRAILING_STOP,
        trailing_stop_signal=(
            None if candidate == "C" else signal.trailing_stop_signal
        ),
        trailing_stop_cash_asset=None if candidate == "C" else CASH_ASSET,
    )
    diagnostics = {
        "window_returns": window_returns(result),
        "spy_buy_and_hold_daily_return_correlation": correlation_with_spy(
            result,
            spy_panel,
        ),
        "margin_call_count": _count_margin_calls(result),
        "average_gross_exposure": result.metrics["average_gross_exposure"],
    }
    return CandidateRun(candidate, cost_bps, result, diagnostics)


def append_exploration_runs(
    records: Sequence[CandidateRun],
    *,
    frozen_spec_hash: str,
    spec: Mapping[str, Any] = SPEC,
    source: str = SOURCE,
) -> list[int]:
    """Append exactly the eight fixed scenarios in one Helium transaction."""
    expected = set(RUN_PLAN)
    observed = [(record.candidate, record.cost_bps) for record in records]
    if len(records) != 8 or len(set(observed)) != 8 or set(observed) != expected:
        raise ValueError("Exactly one result for each A-D and 5/10 bps is required")
    if frozen_spec_hash != spec_hash(spec):
        raise ValueError("frozen_spec_hash does not match the supplied spec")
    if source != SOURCE:
        raise ValueError(f"source must remain {SOURCE!r}")

    run_ids: list[int] = []
    with get_research_conn() as conn:
        with conn.cursor() as cur:
            for candidate, cost_bps in RUN_PLAN:
                record = next(
                    item
                    for item in records
                    if item.candidate == candidate and item.cost_bps == cost_bps
                )
                result = record.result
                if result.data_window.get("requested_end") != END_DATE.isoformat():
                    raise ValueError("All exploration rows must end on 2022-12-31")
                parameters = {
                    "spec": dict(spec),
                    "spec_hash": frozen_spec_hash,
                    "candidate": candidate,
                    "cost_bps": cost_bps,
                    "harness_parameters": result.parameters,
                }
                note_payload = {
                    "metrics": result.metrics,
                    "supplemental": record.diagnostics,
                    "classification": "in-sample exploration; not research_ledger results",
                }
                cur.execute(
                    """
                    INSERT INTO exploration_runs
                        (strategy_family, parameters, data_window, spec_hash, source,
                         sharpe, return_pct, max_drawdown, notes)
                    VALUES (%s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)
                    RETURNING run_id
                    """,
                    (
                        STRATEGY_FAMILY,
                        json.dumps(parameters, sort_keys=True, allow_nan=False),
                        json.dumps(result.data_window, sort_keys=True, allow_nan=False),
                        frozen_spec_hash,
                        source,
                        float(result.metrics["sharpe"]),
                        float(result.metrics["total_return"]) * 100.0,
                        float(result.metrics["max_drawdown"]),
                        json.dumps(note_payload, sort_keys=True, allow_nan=False),
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError(
                        f"exploration_runs insert returned no run_id for {candidate}/{cost_bps}"
                    )
                run_ids.append(int(row[0]))
    return run_ids


def load_research_panels() -> tuple[PricePanel, PricePanel]:
    """Load the strategy universe and the separate SPY reference series."""
    strategy_panel = load_adjusted_close(
        (*UNIVERSE, CASH_ASSET),
        start_date=WARMUP_START,
        end_date=END_DATE,
    )
    spy_panel = load_adjusted_close(
        (BENCHMARK,),
        start_date=WARMUP_START,
        end_date=END_DATE,
    )
    return strategy_panel, spy_panel


def run_exploratory_candidates(
    strategy_panel: PricePanel | None = None,
    spy_panel: PricePanel | None = None,
) -> dict[str, Any]:
    """Run the corrected in-sample scenarios once, then append all eight rows."""
    print_spec()
    if strategy_panel is None or spy_panel is None:
        loaded_strategy, loaded_spy = load_research_panels()
        strategy_panel = strategy_panel or loaded_strategy
        spy_panel = spy_panel or loaded_spy
    _check_cash_asset_stop_compatibility(strategy_panel)
    matrix = in_sample_correlation_matrix(strategy_panel)
    bil_metrics = buy_and_hold_metrics(strategy_panel)
    records = [
        _make_result_record(candidate, cost_bps, strategy_panel, spy_panel)
        for candidate, cost_bps in RUN_PLAN
    ]
    run_ids = append_exploration_runs(
        records,
        frozen_spec_hash=spec_hash(),
    )
    run_id_map = {
        (candidate, cost_bps): run_id
        for (candidate, cost_bps), run_id in zip(RUN_PLAN, run_ids, strict=True)
    }
    return {
        "spec": SPEC,
        "spec_hash": spec_hash(),
        "source": SOURCE,
        "flagged_rows_dropped": strategy_panel.flagged_rows_dropped,
        "session_count": len(_common_sessions(strategy_panel)),
        "instrument_correlation_matrix": matrix,
        "bil_buy_and_hold": bil_metrics,
        "runs": [
            {
                "candidate": record.candidate,
                "cost_bps": record.cost_bps,
                "run_id": run_id_map[(record.candidate, record.cost_bps)],
                "metrics": record.result.metrics,
                "cagr_minus_bil": (
                    float(record.result.metrics["cagr"]) - bil_metrics["cagr"]
                ),
                **record.diagnostics,
            }
            for record in records
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--print-spec",
        action="store_true",
        help="print the frozen JSON specification and hash; do not run strategies",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="print the frozen specification first, then run and append the eight scenarios",
    )
    args = parser.parse_args()
    if args.print_spec:
        print_spec()
        return
    report = run_exploratory_candidates()
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()