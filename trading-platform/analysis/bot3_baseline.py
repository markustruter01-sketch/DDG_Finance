"""In-sample Bot 3 hard-assets baseline using the shared backtest harness.

Importing this module does not load prices or connect to a database. The
default CLI is also inert; ``--run`` is the only path that loads Helium prices
and appends the two explicitly requested exploration runs.
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
    append_exploration_run,
    load_adjusted_close,
    run_backtest,
)

START_DATE = date(2008, 1, 1)
END_DATE = date(2022, 12, 31)
WARMUP_START = date(2000, 1, 1)

# The baseline trades Bot 3's four assets. SPY is loaded into the shared
# calendar solely as a benchmark and is never targeted.
ASSETS = ("BTC-USD", "ETH-USD", "GLD", "SLV")
CRYPTO = frozenset({"BTC-USD", "ETH-USD"})
METALS = frozenset({"GLD", "SLV"})
BENCHMARK = "SPY"
REQUESTED_SYMBOLS = (*ASSETS, BENCHMARK)
DISPLAY_SYMBOLS = {
    "BTC-USD": "BTC/USD",
    "ETH-USD": "ETH/USD",
    "GLD": "GLD",
    "SLV": "SLV",
    "SPY": "SPY",
}

STRATEGY_FAMILY = "bot3_baseline_v1"
COST_SCENARIOS_BPS = (5, 10)
STARTING_EQUITY = 100_000.0
WHOLE_SHARES = False
RISK_FREE_RATE = 0.0
BORROW_FEE_RATE = 0.0
MAX_GROSS = 1.0
VOL_LOOKBACK = 60
WEIGHT_FLOOR = 0.10
WEIGHT_CAP = 0.40
CRYPTO_FLEET_CAP_PCT = 0.05
FLEET_EQUITY_PROXY_MULTIPLIER = 3.0
DRIFT_BAND = 0.05
CASH_BUFFER_PCT = 0.01
CRYPTO_STOP_PCT = 0.25
METAL_STOP_PCT = 0.10
TRADING_DAYS_PER_YEAR = 252
EVALUATION_WINDOWS = (
    ("2008-09-01", "2009-03-31"),
    ("2009-04-01", "2013-06-30"),
    ("2015-06-01", "2016-02-29"),
    ("2020-02-15", "2020-04-30"),
    ("2022-01-01", "2022-12-31"),
)

SIMPLIFICATIONS = (
    "The standalone fleet-equity proxy is exactly 3 x current Bot3 equity; "
    "the 5% fleet crypto ceiling therefore moves dynamically with Bot3 equity "
    "and equals 15% of current Bot3 equity.",
    "Close-only fixed stops trigger when a close breaches the entry-relative "
    "threshold and are filled at the next common close. This is not live "
    "stop-limit or intraday behavior. The strict NYSE-session panel also misses "
    "weekend-only crypto stop breaches.",
    "Sells-before-buys ordering, broker state, protective-stop order mechanics, "
    "partial fills, and exact intraday execution are not represented.",
    "The stateful signal callback estimates current holdings from its prior "
    "targets, fractional-share quantities, and close prices; actual harness equity "
    "and transaction-cost marks can differ slightly from that internal model.",
    "No margin, shorting, cash interest, or synthetic pre-listing bars are used. "
    "The 1% cash buffer is left as cash by targeting no more than 99% invested.",
    "The strict shared calendar is the intersection of all four assets and SPY. "
    "ETH/USD history begins in 2017, so the actual common first session is "
    "reported from the loaded data rather than represented with earlier bars.",
)

SPEC: dict[str, Any] = {
    "family": STRATEGY_FAMILY,
    "requested_dates": {
        "start": START_DATE.isoformat(),
        "end": END_DATE.isoformat(),
        "price_load_start": WARMUP_START.isoformat(),
        "price_load_end": END_DATE.isoformat(),
    },
    "universe": {
        "BTC/USD": "BTC-USD",
        "ETH/USD": "ETH-USD",
        "GLD": "GLD",
        "SLV": "SLV",
        "benchmark_only": BENCHMARK,
    },
    "harness": {
        "function": "analysis.backtest_harness.run_backtest",
        "cost_bps_scenarios": list(COST_SCENARIOS_BPS),
        "starting_equity": STARTING_EQUITY,
        "whole_shares": WHOLE_SHARES,
        "risk_free_rate": RISK_FREE_RATE,
        "borrow_fee_rate": BORROW_FEE_RATE,
        "max_gross": MAX_GROSS,
        "margin_rate": 0.0,
    },
    "calendar_and_eligibility": {
        "strict_calendar": "intersection of unflagged adjusted-close dates for all four traded assets and SPY",
        "quarterly_rebalance": (
            "the first common NYSE session on or before calendar day 7 in "
            "January, April, July, and October"
        ),
        "individual_asset_minimum": "61 own adjusted closes before targeting",
        "no_synthetic_prelisting_bars": True,
        "actual_common_first_session": (
            "computed and reported from the loaded price panel; ETH history "
            "begins in 2017, limiting the strict shared panel"
        ),
    },
    "allocation": {
        "method": "inverse-volatility with iterative bounded renormalization",
        "volatility_lookback": f"{VOL_LOOKBACK} prior daily returns",
        "annualization": f"sample standard deviation x sqrt({TRADING_DAYS_PER_YEAR})",
        "individual_weight_bounds": [WEIGHT_FLOOR, WEIGHT_CAP],
        "crypto_cap": {
            "live_cap": f"{CRYPTO_FLEET_CAP_PCT:.0%} of fleet equity",
            "standalone_proxy": (
                f"fleet_equity = {FLEET_EQUITY_PROXY_MULTIPLIER:g} x current "
                "Bot3 equity"
            ),
            "effective_dynamic_cap": "15% of current Bot3 equity",
            "reallocation": (
                "scale crypto targets pro-rata to the cap; redistribute freed "
                "weight pro-rata to the metals following the live implementation"
            ),
        },
        "drift_band": (
            "rebalance only when any absolute current-versus-target weight "
            "difference is greater than 5 percentage points; crypto cap "
            "exceedance forces a trim regardless of drift"
        ),
        "cash_buffer": f"{CASH_BUFFER_PCT:.0%}; invest at most 99% of equity",
    },
    "stops": {
        "BTC-USD": f"{CRYPTO_STOP_PCT:.0%} fixed entry-relative stop",
        "ETH-USD": f"{CRYPTO_STOP_PCT:.0%} fixed entry-relative stop",
        "GLD": f"{METAL_STOP_PCT:.0%} fixed entry-relative stop",
        "SLV": f"{METAL_STOP_PCT:.0%} fixed entry-relative stop",
        "execution": (
            "close breach, then fill at next common close; not live "
            "stop-limit/intraday behavior"
        ),
    },
    "reporting": {
        "metrics": "all harness metrics per run",
        "evaluation_windows": [list(window) for window in EVALUATION_WINDOWS],
        "spy_correlation": "daily strategy equity returns versus SPY buy-and-hold daily returns",
        "additional": ["margin_call_count", "first_held_date", "actual_common_first_session"],
    },
    "persistence": {
        "destination": "append_exploration_run only",
        "strategy_family": STRATEGY_FAMILY,
        "parameters_include": ["family", "cost_bps", "spec", "spec_hash"],
        "research_ledger_writes": False,
    },
    "live_source_citations": [
        "kraken-bot/bot3_hard_assets_strategy.py:49-67 (universe and allocation/stop constants)",
        "kraken-bot/bot3_hard_assets_strategy.py:188-200 (quarterly date rule)",
        "kraken-bot/bot3_hard_assets_strategy.py:242-283 (60-return annualized sample volatility and bounded inverse-vol targets)",
        "kraken-bot/bot3_hard_assets_strategy.py:286-331 (fleet crypto cap and pro-rata metal redistribution)",
        "kraken-bot/bot3_hard_assets_strategy.py:663-681 (entry-relative protective-stop prices and live order types)",
        "kraken-bot/bot3_hard_assets_strategy.py:1224-1256 (crypto-cap override to the drift band)",
        "kraken-bot/bot3_hard_assets_strategy.py:1325-1326 (cash buffer)",
        "trading-platform/analysis/backtest_harness.py:942-972 (harness API, as-of callback, and next-common-close execution)",
        "trading-platform/analysis/backtest_harness.py:1312-1372 (append-only exploration_runs persistence)",
    ],
    "simplifications": list(SIMPLIFICATIONS),
}


def canonical_spec_json(spec: Mapping[str, Any] = SPEC) -> str:
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
    """Print the frozen rules, exact source citations, and simplifications."""
    payload = {"spec": SPEC, "spec_hash": spec_hash()}
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False), flush=True)
    return payload


def common_dates(
    history: Mapping[str, Mapping[date, float]],
    symbols: Sequence[str] = REQUESTED_SYMBOLS,
) -> list[date]:
    """Return the strict date intersection without filling any missing rows."""
    if not symbols:
        return []
    missing = [symbol for symbol in symbols if symbol not in history]
    if missing:
        raise ValueError(f"History is missing required symbols: {missing}")
    return sorted(set.intersection(*(set(history[symbol]) for symbol in symbols)))


def quarterly_rebalance_sessions(sessions: Sequence[date]) -> set[date]:
    """First available common NYSE session no later than day 7 of each quarter."""
    candidates: dict[tuple[int, int], date] = {}
    for day in sorted(sessions):
        if day.month not in (1, 4, 7, 10) or day.day > 7:
            continue
        candidates.setdefault((day.year, day.month), day)
    return set(candidates.values())


def bounded_inverse_vol_weights(
    volatilities: Mapping[str, float],
) -> dict[str, float]:
    """Normalize inverse vols with the live Bot3 iterative 10%-40% bounds."""
    if len(volatilities) < 3:
        raise ValueError("At least three eligible assets are required for bounded full investment")
    if len(volatilities) * WEIGHT_FLOOR > 1.0 or len(volatilities) * WEIGHT_CAP < 1.0:
        raise ValueError("Asset count is incompatible with the configured weight bounds")
    inverse: dict[str, float] = {}
    for symbol, raw_vol in volatilities.items():
        volatility = float(raw_vol)
        if not math.isfinite(volatility) or volatility < 0:
            raise ValueError(f"Invalid annualized volatility for {symbol}")
        inverse[symbol] = 1.0 / max(volatility, 1e-12)
    fixed: dict[str, float] = {}
    free = sorted(inverse)
    remaining = 1.0
    while free:
        free_total = math.fsum(inverse[symbol] for symbol in free)
        candidates = {
            symbol: remaining * inverse[symbol] / free_total
            for symbol in free
        }
        below = [
            symbol for symbol in free
            if candidates[symbol] < WEIGHT_FLOOR
        ]
        above = [
            symbol for symbol in free
            if candidates[symbol] > WEIGHT_CAP
        ]
        if not below and not above:
            break
        for symbol in below:
            fixed[symbol] = WEIGHT_FLOOR
            remaining -= WEIGHT_FLOOR
        for symbol in above:
            fixed[symbol] = WEIGHT_CAP
            remaining -= WEIGHT_CAP
        fixed_symbols = set(below) | set(above)
        free = [symbol for symbol in free if symbol not in fixed_symbols]
    free_total = math.fsum(inverse[symbol] for symbol in free)
    for symbol in free:
        fixed[symbol] = remaining * inverse[symbol] / free_total
    return fixed


def apply_dynamic_crypto_cap(
    target_weights: Mapping[str, float],
    current_equity: float,
    *,
    fleet_equity_multiplier: float = FLEET_EQUITY_PROXY_MULTIPLIER,
) -> dict[str, float]:
    """Apply the live 5%-of-fleet cap using the 3x standalone fleet proxy."""
    equity = float(current_equity)
    multiplier = float(fleet_equity_multiplier)
    if (
        not math.isfinite(equity)
        or equity <= 0
        or not math.isfinite(multiplier)
        or multiplier <= 0
    ):
        raise ValueError("current equity and fleet-equity multiplier must be finite and positive")
    if not all(symbol in target_weights for symbol in ASSETS):
        raise ValueError("Target weights must include all four Bot3 assets")
    adjusted = {symbol: float(target_weights[symbol]) for symbol in ASSETS}
    if any(not math.isfinite(weight) or weight < 0 for weight in adjusted.values()):
        raise ValueError("Target weights must be finite and non-negative")
    if not math.isclose(math.fsum(adjusted.values()), 1.0, rel_tol=0.0, abs_tol=1e-10):
        raise ValueError("Target weights must sum to 1.0")

    # Exact proxy required for this standalone baseline:
    # fleet_equity = 3 x current Bot3 equity.
    fleet_equity = fleet_equity_multiplier * equity
    crypto_weight = math.fsum(
        adjusted[symbol] for symbol in ASSETS if symbol in CRYPTO
    )
    metal_weight = math.fsum(
        adjusted[symbol] for symbol in ASSETS if symbol in METALS
    )
    crypto_cap_dollars = CRYPTO_FLEET_CAP_PCT * fleet_equity
    crypto_target_dollars = crypto_weight * equity
    if crypto_target_dollars <= crypto_cap_dollars:
        return adjusted
    if metal_weight <= 0:
        raise ValueError("Metal target weights must have a positive total")

    capped_crypto_weight = crypto_cap_dollars / equity
    scale = capped_crypto_weight / crypto_weight
    freed_weight = crypto_weight - capped_crypto_weight
    for symbol in ASSETS:
        if symbol in CRYPTO:
            adjusted[symbol] *= scale
        elif symbol in METALS:
            adjusted[symbol] += freed_weight * target_weights[symbol] / metal_weight
    adjusted["SLV"] = 1.0 - math.fsum(
        adjusted[symbol] for symbol in ("BTC-USD", "ETH-USD", "GLD")
    )
    return adjusted


def should_rebalance(
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    current_equity: float,
) -> bool:
    """Enforce the 5pp drift band, with unconditional crypto-cap trimming."""
    crypto_weight = math.fsum(
        float(current_weights.get(symbol, 0.0))
        for symbol in ASSETS
        if symbol in CRYPTO
    )
    dynamic_crypto_cap = CRYPTO_FLEET_CAP_PCT * FLEET_EQUITY_PROXY_MULTIPLIER
    if crypto_weight > dynamic_crypto_cap + 1e-12:
        return True
    return any(
        abs(
            float(current_weights.get(symbol, 0.0))
            - float(target_weights.get(symbol, 0.0))
        ) > DRIFT_BAND + 1e-12
        for symbol in ASSETS
    )


def fixed_stop_breaches(
    entry_prices: Mapping[str, float],
    current_prices: Mapping[str, float],
) -> set[str]:
    """Return assets whose close is at or below their fixed entry-relative stop."""
    breached: set[str] = set()
    for symbol, entry_price in entry_prices.items():
        if symbol not in current_prices:
            continue
        stop_fraction = CRYPTO_STOP_PCT if symbol in CRYPTO else METAL_STOP_PCT
        if float(current_prices[symbol]) <= float(entry_price) * (1.0 - stop_fraction):
            breached.add(symbol)
    return breached


class Bot3BaselineSignal:
    """Stateful harness callback that returns ``None`` except on action days."""

    def __init__(
        self,
        sessions: Sequence[date],
        *,
        cost_bps: float,
    ) -> None:
        self.sessions = tuple(sessions)
        self.rebalance_days = quarterly_rebalance_sessions(self.sessions)
        self.cost_rate = float(cost_bps) / 10_000.0
        self.quantities = {symbol: 0.0 for symbol in ASSETS}
        self.cash = STARTING_EQUITY
        self.entry_prices: dict[str, float] = {}
        self.pending_target: dict[str, float] | None = None
        self.stop_locked: set[str] = set()
        self._last_day: date | None = None

    def _apply_pending_target(self, prices: Mapping[str, float]) -> None:
        if self.pending_target is None:
            return
        equity = self.cash + math.fsum(
            self.quantities[symbol] * prices[symbol] for symbol in ASSETS
        )
        for symbol in ASSETS:
            old_quantity = self.quantities[symbol]
            target_quantity = (
                self.pending_target.get(symbol, 0.0) * equity / prices[symbol]
            )
            change = target_quantity - old_quantity
            self.cash -= change * prices[symbol]
            self.cash -= abs(change * prices[symbol]) * self.cost_rate
            if old_quantity <= 0 < target_quantity:
                self.entry_prices[symbol] = prices[symbol]
            elif target_quantity <= 0:
                self.entry_prices.pop(symbol, None)
            self.quantities[symbol] = float(target_quantity)
        self.pending_target = None

    def _current_weights(self, prices: Mapping[str, float]) -> tuple[float, dict[str, float]]:
        equity = self.cash + math.fsum(
            self.quantities[symbol] * prices[symbol] for symbol in ASSETS
        )
        weights = {
            symbol: (
                self.quantities[symbol] * prices[symbol] / equity
                if equity > 0
                else 0.0
            )
            for symbol in ASSETS
        }
        return equity, weights

    def _target_weights(
        self,
        history: Mapping[str, Mapping[date, float]],
        day: date,
        equity: float,
    ) -> dict[str, float] | None:
        volatilities: dict[str, float] = {}
        for symbol in ASSETS:
            prior_dates = sorted(
                session for session in history[symbol]
                if session < day
            )
            if len(prior_dates) < VOL_LOOKBACK + 1:
                continue
            closes = [float(history[symbol][prior]) for prior in prior_dates[-(VOL_LOOKBACK + 1):]]
            returns = [
                closes[index] / closes[index - 1] - 1.0
                for index in range(1, len(closes))
            ]
            volatility = stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR)
            if math.isfinite(volatility):
                volatilities[symbol] = volatility
        # Fewer than three eligible instruments cannot satisfy the live weight
        # bounds while also investing a full target portfolio.
        if len(volatilities) < 3 or len(volatilities) != len(ASSETS):
            return None
        raw_weights = bounded_inverse_vol_weights(volatilities)
        capped = apply_dynamic_crypto_cap(raw_weights, equity)
        investable_scale = 1.0 - CASH_BUFFER_PCT
        return {
            symbol: capped[symbol] * investable_scale
            for symbol in ASSETS
        }

    def __call__(
        self,
        history: Mapping[str, Mapping[date, float]],
        day: date,
    ) -> Mapping[str, float] | None:
        prices = {symbol: float(history[symbol][day]) for symbol in ASSETS}
        self._apply_pending_target(prices)
        self._last_day = day
        equity, current_weights = self._current_weights(prices)

        # No harness target can be executed beyond its final common close.
        if not self.sessions or day == self.sessions[-1]:
            return None

        if day in self.rebalance_days:
            self.stop_locked.clear()

        breaches = fixed_stop_breaches(self.entry_prices, prices) - self.stop_locked
        if breaches:
            self.stop_locked.update(breaches)
            target = dict(current_weights)
            for symbol in breaches:
                target[symbol] = 0.0
            self.pending_target = target
            return {**target, BENCHMARK: 0.0}

        if day not in self.rebalance_days:
            return None

        desired = self._target_weights(history, day, equity)
        if desired is None:
            return None
        if not should_rebalance(current_weights, desired, equity):
            return None
        self.pending_target = desired
        return {**desired, BENCHMARK: 0.0}


@dataclass(frozen=True)
class BaselineRun:
    cost_bps: int
    result: BacktestResult
    diagnostics: dict[str, Any]


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    left_var = math.fsum((value - left_mean) ** 2 for value in left)
    right_var = math.fsum((value - right_mean) ** 2 for value in right)
    if left_var <= 0 or right_var <= 0:
        return None
    covariance = math.fsum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right, strict=True)
    )
    return covariance / math.sqrt(left_var * right_var)


def correlation_with_spy(result: BacktestResult, panel: PricePanel) -> float | None:
    """Correlate daily harness equity returns with SPY close-to-close returns."""
    strategy_returns: list[float] = []
    spy_returns: list[float] = []
    spy = panel.closes[BENCHMARK]
    for previous, current in zip(result.equity_curve, result.equity_curve[1:]):
        previous_day = previous["date"]
        current_day = current["date"]
        if previous_day not in spy or current_day not in spy:
            continue
        prior_equity = float(previous["equity"])
        if prior_equity <= 0:
            continue
        strategy_returns.append(float(current["equity"]) / prior_equity - 1.0)
        spy_returns.append(spy[current_day] / spy[previous_day] - 1.0)
    return _pearson(strategy_returns, spy_returns)


def _window_return(
    curve: Sequence[Mapping[str, Any]],
    start: date,
    end: date,
) -> float | None:
    before = [point for point in curve if point["date"] <= start]
    through = [point for point in curve if point["date"] <= end]
    if not before or not through:
        return None
    initial = float(before[-1]["equity"])
    final = float(through[-1]["equity"])
    return final / initial - 1.0 if initial > 0 else None


def _diagnostics(result: BacktestResult, panel: PricePanel) -> dict[str, Any]:
    curve = result.equity_curve
    windows = {
        f"{start}..{end}": _window_return(
            curve,
            date.fromisoformat(start),
            date.fromisoformat(end),
        )
        for start, end in EVALUATION_WINDOWS
    }
    first_held_date = next(
        (
            event["date"]
            for event in result.events
            if event.get("type") == "trade"
            and event.get("quantity_after", 0) > 0
        ),
        None,
    )
    return {
        "window_returns": windows,
        "spy_buy_and_hold_daily_return_correlation": correlation_with_spy(result, panel),
        "margin_call_count": sum(event.get("type") == "margin_call" for event in result.events),
        "first_held_date": first_held_date,
        "actual_common_first_session": result.data_window["first_session"],
        "data_limitation": (
            "Strict all-series intersection begins on "
            f"{result.data_window['first_session']}; ETH/USD listing history prevents "
            "evaluation on earlier requested dates."
        ),
    }


def run_scenarios(panel: PricePanel) -> list[BaselineRun]:
    """Run exactly the 5bps and 10bps in-sample scenarios on a supplied panel."""
    if set(panel.closes) != set(REQUESTED_SYMBOLS):
        raise ValueError(
            "Price panel must contain exactly the four traded assets and SPY benchmark; "
            f"missing={sorted(set(REQUESTED_SYMBOLS) - set(panel.closes))}, "
            f"extra={sorted(set(panel.closes) - set(REQUESTED_SYMBOLS))}"
        )
    if any(day > END_DATE for series in panel.closes.values() for day in series):
        raise ValueError(f"Price panel contains rows after {END_DATE.isoformat()}")
    sessions = [
        day for day in common_dates(panel.closes)
        if START_DATE <= day <= END_DATE
    ]
    if len(sessions) < 2:
        raise ValueError("At least two common in-sample sessions are required")
    records: list[BaselineRun] = []
    for cost_bps in COST_SCENARIOS_BPS:
        signal = Bot3BaselineSignal(sessions, cost_bps=cost_bps)
        result = run_backtest(
            panel,
            signal,
            START_DATE,
            END_DATE,
            cost_bps=cost_bps,
            borrow_fee_rate=BORROW_FEE_RATE,
            risk_free_rate=RISK_FREE_RATE,
            margin_rate=0.0,
            max_gross=MAX_GROSS,
            starting_equity=STARTING_EQUITY,
            whole_shares=WHOLE_SHARES,
        )
        result.parameters.update(
            {
                "family": STRATEGY_FAMILY,
                "cost_bps": cost_bps,
                "spec": SPEC,
                "spec_hash": spec_hash(),
                "fleet_equity_proxy": (
                    f"{FLEET_EQUITY_PROXY_MULTIPLIER:g} x current Bot3 equity"
                ),
            }
        )
        records.append(BaselineRun(cost_bps, result, _diagnostics(result, panel)))
    return records


def load_price_panel() -> PricePanel:
    """Load only the requested symbols and bounded warmup/evaluation interval."""
    panel = load_adjusted_close(
        REQUESTED_SYMBOLS,
        start_date=WARMUP_START,
        end_date=END_DATE,
    )
    if set(panel.closes) != set(REQUESTED_SYMBOLS):
        raise ValueError("Loaded price panel does not contain exactly the requested symbols")
    if any(day > END_DATE for series in panel.closes.values() for day in series):
        raise ValueError("Loaded price panel contains data beyond 2022-12-31")
    return panel


def _json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def run_and_persist() -> dict[str, Any]:
    """Load, run, report, and append the two exploration_runs records."""
    print_spec()
    panel = load_price_panel()
    records = run_scenarios(panel)
    run_ids = [
        append_exploration_run(
            record.result,
            strategy_family=STRATEGY_FAMILY,
            notes=json.dumps(
                {
                    "cost_bps": record.cost_bps,
                    "spec_hash": spec_hash(),
                    "diagnostics": record.diagnostics,
                },
                sort_keys=True,
                allow_nan=False,
            ),
        )
        for record in records
    ]
    return {
        "strategy_family": STRATEGY_FAMILY,
        "spec_hash": spec_hash(),
        "actual_common_first_session": common_dates(panel.closes)[0].isoformat(),
        "runs": [
            {
                "run_id": run_id,
                "cost_bps": record.cost_bps,
                "metrics": record.result.metrics,
                "diagnostics": record.diagnostics,
            }
            for run_id, record in zip(run_ids, records, strict=True)
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--print-spec", action="store_true", help="print the frozen baseline spec")
    actions.add_argument("--run", action="store_true", help="run two scenarios and append exploration rows")
    args = parser.parse_args(argv)
    if args.print_spec:
        print_spec()
    elif args.run:
        print(json.dumps(_json_safe(run_and_persist()), sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())