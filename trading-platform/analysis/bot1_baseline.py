"""Standalone in-sample Bot 1 baseline using the shared backtest harness.

This module has no database side effects when imported.  Helium reads and
exploration_runs appends are confined to the explicit ``--run`` path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
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
UNIVERSE = (
    "SPY", "QQQ", "EWY", "EWT", "INDA", "EWJ", "EWM", "VNM",
    "EWZ", "EWW", "ECH", "EEM", "EZA", "EPOL", "GREK", "TUR",
)
STRATEGY_FAMILY = "bot1_baseline_v1"
COST_SCENARIOS = (5, 10)
STARTING_EQUITY = 100_000.0
MAX_GROSS = 0.80
MAX_POSITIONS = 6
MAX_NAME_WEIGHT = 0.13
TARGET_ANNUAL_VOL = 0.12
VOL_LOOKBACK = 20
FAST_EMA = 50
SLOW_EMA = 200
MIN_ENTRY_HISTORY = 205
CRISIS_THRESHOLD = -0.12
TRAILING_STOP = 0.08
MIN_HOLD_CALENDAR_DAYS = 5
TP1_RETURN = 0.06
TP2_RETURN = 0.12
TP_ORIGINAL_FRACTION = 0.333
CORR_HISTORY_DAYS = 90
CORR_RETURNS = 60
CORR_THRESHOLD = 0.75
TRADING_DAYS_PER_YEAR = 252
SOURCE = "bot1_baseline.py / analysis.backtest_harness"
EVALUATION_WINDOWS = (
    ("2008-09-01", "2009-03-31"),
    ("2009-04-01", "2013-06-30"),
    ("2015-06-01", "2016-02-29"),
    ("2020-02-15", "2020-04-30"),
    ("2022-01-01", "2022-12-31"),
)

SPEC: dict[str, Any] = {
    "strategy_family": STRATEGY_FAMILY,
    "universe": list(UNIVERSE),
    "requested_dates": {
        "start": START_DATE.isoformat(),
        "end": END_DATE.isoformat(),
        "warmup_load_start": WARMUP_START.isoformat(),
        "no_data_after": END_DATE.isoformat(),
        "calendar": (
            "intersection of unflagged adjusted-close dates across all 16 symbols; "
            "late listings restrict the shared calendar; report actual first common session"
        ),
        "candidate_warmup": (
            "each candidate independently needs at least 205 of its own unflagged "
            "adjusted closes and computable ATR14 before entry"
        ),
    },
    "entry": {
        "scan": "daily close approximation to the live 19:40-19:59 UTC scan",
        "ema_fast": FAST_EMA,
        "ema_slow": SLOW_EMA,
        "entry_ema": (
            "recursive EMA seeded from first observation, computed over the latest "
            "250 available candidate closes to match the live 250d fetch; entry EMA "
            "uses the full fetched history (F18 distinction)"
        ),
        "conditions": [
            "EMA50 > EMA200",
            "EMA50 today > EMA50 five bars ago",
            "close > EMA50",
            "ATR14 computable",
            "candidate regional regime is BULL (BEAR and CRISIS are blocked)",
            "global SPY 20-session return is greater than -12%",
        ],
        "regional_regime": (
            "20-session return <= -12% is CRISIS; otherwise EMA50 < EMA200 is "
            "BEAR, else BULL; uses the latest 310 calendar days to match the live "
            "regime fetch; per-symbol EMA uses SMA(period) seed then recursive EMA; "
            "fewer than 200 bars fails closed to CRISIS"
        ),
        "candidate_order": "(close - EMA50) / EMA50 descending",
        "source_citations": [
            "kraken-bot/asia_trend_strategy.py:69-84, 221-267, 575-605, 693-696",
            "kraken-bot/asia_trend_strategy.py:368-372 (six-position and deployment limits)",
            "kraken-bot/asia_trend_strategy.py:155-190, 648-665 (correlation cap and max_correlated=1)",
            "trading-platform/core/regional_regime.py:47-50, 90-102, 125-158",
            "trading-platform/core/regional_regime.py:214-233, 289-307",
            "trading-platform/core/vol_targeting.py:31-35, 75-88, 145-147",
            "trading-platform/core/correlation_cap.py:124-210",
            "kraken-bot/alpaca_etf_engine.py:105-137",
        ],
    },
    "sizing_and_risk": {
        "volatility": (
            "sample standard deviation of the last 20 own-symbol daily close returns "
            "times sqrt(252)"
        ),
        "weight": f"min({TARGET_ANNUAL_VOL}/annualized_volatility, {MAX_NAME_WEIGHT})",
        "max_positions": MAX_POSITIONS,
        "max_deployment": MAX_GROSS,
        "correlation": {
            "history": (
                f"{CORR_HISTORY_DAYS}-calendar-day fetch with up to "
                f"{CORR_RETURNS} trailing daily returns"
            ),
            "returns": CORR_RETURNS,
            "method": (
                "Pearson correlation of trailing return arrays, tail-aligned to "
                "common length as in the live helper"
            ),
            "threshold": (
                f"round correlation to 4 decimals, then strictly greater than "
                f"{CORR_THRESHOLD}"
            ),
            "maximum_correlated_held_etfs": 0,
            "scope": (
                "standalone strategy holdings only; cross-bot DB/vault holdings "
                "are not present in standalone research"
            ),
        },
    },
    "exits": {
        "trailing_stop": (
            f"{TRAILING_STOP:.0%} below closing high-water; close-only trigger "
            "and next common-close execution (intraday simplification)"
        ),
        "minimum_hold_calendar_days": MIN_HOLD_CALENDAR_DAYS,
        "trend_exit": (
            "after minimum hold: close below EMA50 calculated from only the last "
            "50 closes (F18 behavior; intentionally not full history), or "
            "close[-1]/close[-4]-1 <= -5%"
        ),
        "take_profit_order": [
            f"TP2 first at +{TP2_RETURN:.0%}; sell {TP_ORIGINAL_FRACTION:.1%} of original filled quantity once",
            f"TP1 at +{TP1_RETURN:.0%}; sell {TP_ORIGINAL_FRACTION:.1%} of original filled quantity once",
            "both only after minimum hold; harness whole-share execution applies",
        ],
        "source_citations": [
            "kraken-bot/asia_trend_strategy.py:69-79, 272-297, 441-468",
            "kraken-bot/alpaca_etf_engine.py:105-137",
            "trading-platform/analysis/global_backtest_phase1.py:221-242, 287-339",
        ],
    },
    "data_and_execution": {
        "decision_prices": (
            "adjusted close from public.research_daily_prices via "
            "analysis.backtest_harness.load_adjusted_close"
        ),
        "atr_prices": (
            "high/low/close from public.research_daily_prices where quality_flag IS NULL; "
            "latest 250 as-of daily rows; Wilder ATR14; these OHLC values are not adjusted"
        ),
        "cost_bps_scenarios": list(COST_SCENARIOS),
        "starting_equity": STARTING_EQUITY,
        "whole_shares": True,
        "risk_free_rate": 0,
        "max_gross": MAX_GROSS,
        "borrow_fee_rate": 0,
        "margin_rate": 0,
        "cash": (
            "residual cash earns zero; SGOV parking is not simulated "
            "(SGOV starts in 2020 and is operational parking only)"
        ),
        "signal_protocol": (
            "stateful full target mapping only on changes; None on unchanged days; "
            "harness executes at next common valid close; surviving target weights "
            "are marked from estimated whole-share quantities and current decision closes"
        ),
    },
    "known_simplifications": [
        "daily close scan approximates the live 19:40-19:59 UTC window",
        "stops use closing high-water and close-only trigger, executed at next common close",
        "cross-bot database/vault holdings are absent from standalone correlation screening",
        "the live correlation helper tail-aligns return arrays by length; data gaps can misalign dates",
        "SGOV operational cash parking is not modeled",
        "target maps preserve estimated whole-share quantities for surviving holdings; next-close price moves and harness equity changes can still cause small quantity differences",
    ],
    "reporting": {
        "windows": [list(window) for window in EVALUATION_WINDOWS],
        "per_run": [
            "harness_metrics",
            "five_window_returns",
            "SPY_daily_return_correlation",
            "margin_call_count",
            "first_held_date",
            "actual_common_first_session",
        ],
    },
    "persistence": {
        "destination": "exploration_runs only, append-only",
        "parameters": ["family", "candidate", "cost_bps", "spec", "spec_hash", "harness_parameters"],
        "research_ledger_writes": False,
    },
}


@dataclass(frozen=True)
class BaselineRun:
    cost_bps: int
    result: BacktestResult
    diagnostics: dict[str, Any]


def canonical_spec_json(spec: Mapping[str, Any] = SPEC) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)


def spec_hash(spec: Mapping[str, Any] = SPEC) -> str:
    return hashlib.sha256(canonical_spec_json(spec).encode("utf-8")).hexdigest()


def print_spec() -> dict[str, Any]:
    payload = {"spec": SPEC, "spec_hash": spec_hash()}
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False), flush=True)
    return payload


def ema_last(values: Sequence[float], span: int) -> float:
    """Recursive adjust=False EMA with first observation seed."""
    if span <= 0 or not values:
        raise ValueError("EMA requires a positive span and at least one observation")
    alpha = 2.0 / (span + 1.0)
    value = float(values[0])
    for observation in values[1:]:
        value += alpha * (float(observation) - value)
    return value


def _sma_seed_ema(values: Sequence[float], period: int) -> float | None:
    """regional_regime._ema convention: SMA(period) seed, then recursion."""
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    current = math.fsum(values[:period]) / period
    for value in values[period:]:
        current += alpha * (float(value) - current)
    return current


def _wilder_atr(bars: Sequence[tuple[float, float, float]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for index in range(1, len(bars)):
        high, low, _ = bars[index]
        previous_close = bars[index - 1][2]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if len(true_ranges) < period:
        return None
    atr = math.fsum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        atr = (atr * (period - 1) + true_range) / period
    return atr


def _returns(closes: Sequence[float], count: int | None = None) -> list[float]:
    if count is not None:
        closes = closes[-(count + 1):]
    return [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    size = min(len(left), len(right))
    if size < 20:
        return None
    a, b = list(left[-size:]), list(right[-size:])
    mean_a, mean_b = math.fsum(a) / size, math.fsum(b) / size
    var_a = math.fsum((x - mean_a) ** 2 for x in a)
    var_b = math.fsum((y - mean_b) ** 2 for y in b)
    if var_a <= 0 or var_b <= 0:
        return None
    cov = math.fsum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    return cov / math.sqrt(var_a * var_b)


def _asof_values(series: Mapping[date, float], day: date) -> list[float]:
    return [
        float(value)
        for close_day, value in sorted(series.items())
        if close_day <= day
    ]


def _asof_returns(
    series: Mapping[date, float],
    day: date,
    count: int,
    *,
    calendar_days: int,
) -> list[float]:
    cutoff = day - timedelta(days=calendar_days)
    closes = [
        float(value)
        for close_day, value in sorted(series.items())
        if cutoff < close_day <= day
    ]
    return _returns(closes, count)


class Bot1BaselineSignal:
    """Daily-close, stateful signal callable for ``run_backtest``."""

    def __init__(
        self,
        sessions: Sequence[date],
        atr_history: Mapping[str, Mapping[date, tuple[float, float, float]]],
        *,
        cost_bps: float = 0,
    ) -> None:
        self.sessions = tuple(sessions)
        self.session_index = {day: index for index, day in enumerate(self.sessions)}
        self.atr_history = atr_history
        self.positions: dict[str, dict[str, Any]] = {}
        self.quantities = {symbol: 0.0 for symbol in UNIVERSE}
        self.cash = STARTING_EQUITY
        self.cost_rate = float(cost_bps) / 10_000.0
        self.pending_target: dict[str, float] | None = None
        self.pending: list[tuple[str, str, float | None]] = []
        self.last_targets: dict[str, float] = {}

    def _equity(self, prices: Mapping[str, float]) -> float:
        return self.cash + math.fsum(
            self.quantities[symbol] * prices[symbol] for symbol in UNIVERSE
        )

    def _trade_to_quantities(
        self,
        target_quantities: Mapping[str, float],
        prices: Mapping[str, float],
    ) -> None:
        for symbol in UNIVERSE:
            old_quantity = self.quantities[symbol]
            new_quantity = max(0.0, float(target_quantities.get(symbol, 0.0)))
            change = new_quantity - old_quantity
            if change:
                notional = change * prices[symbol]
                self.cash -= notional + abs(notional) * self.cost_rate
                self.quantities[symbol] = new_quantity

    def _apply_pending(self, history: Mapping[str, Mapping[date, float]], day: date) -> None:
        if self.pending_target is None:
            return
        prices = {symbol: float(history[symbol][day]) for symbol in UNIVERSE}
        equity = self._equity(prices)
        if equity <= 0:
            raise ValueError("Shadow portfolio equity is not positive")
        gross_weight = math.fsum(
            abs(float(self.pending_target.get(symbol, 0.0)))
            for symbol in UNIVERSE
        )
        scale = min(1.0, MAX_GROSS / gross_weight) if gross_weight else 1.0
        target_quantities = {
            symbol: math.trunc(
                float(self.pending_target.get(symbol, 0.0))
                * equity
                * scale
                / prices[symbol]
            )
            for symbol in UNIVERSE
        }
        self._trade_to_quantities(target_quantities, prices)

        # Mirror the harness post-cost gross check so later decisions use its
        # estimated whole-share holdings rather than a fixed starting balance.
        for _ in range(len(UNIVERSE) + 1):
            equity = self._equity(prices)
            gross = math.fsum(
                abs(self.quantities[symbol] * prices[symbol])
                for symbol in UNIVERSE
            )
            if equity <= 0:
                raise ValueError("Shadow portfolio equity is not positive after trading")
            if gross <= MAX_GROSS * equity + 1e-8:
                break
            reduction = MAX_GROSS * equity / gross if gross else 0.0
            reduced = {
                symbol: math.trunc(self.quantities[symbol] * reduction)
                for symbol in UNIVERSE
            }
            if reduced == self.quantities:
                break
            self._trade_to_quantities(reduced, prices)

        for action, symbol, value in self.pending:
            if action == "entry":
                filled_quantity = self.quantities[symbol]
                if filled_quantity <= 0:
                    continue
                self.positions[symbol] = {
                    "entry_date": day,
                    "entry_price": prices[symbol],
                    "high_water": prices[symbol],
                    "original_quantity": float(filled_quantity),
                    "remaining": 1.0,
                    "tp1": False,
                    "tp2": False,
                }
            elif action == "exit":
                self.positions.pop(symbol, None)
            elif action in ("tp1", "tp2"):
                position = self.positions.get(symbol)
                if position is not None:
                    original_quantity = float(position["original_quantity"])
                    position["remaining"] = (
                        self.quantities[symbol] / original_quantity
                        if original_quantity > 0
                        else 0.0
                    )
                    position[action] = True
                    if self.quantities[symbol] <= 0:
                        self.positions.pop(symbol, None)
        self.pending_target = None
        self.pending.clear()

    def _regional_regime(self, closes: Sequence[float]) -> str:
        if len(closes) < SLOW_EMA or len(closes) < 21:
            return "CRISIS"
        if closes[-1] / closes[-21] - 1.0 <= CRISIS_THRESHOLD:
            return "CRISIS"
        fast = _sma_seed_ema(closes, FAST_EMA)
        slow = _sma_seed_ema(closes, SLOW_EMA)
        if fast is None or slow is None:
            return "CRISIS"
        return "BEAR" if fast < slow else "BULL"

    def __call__(
        self,
        history: Mapping[str, Mapping[date, float]],
        day: date,
    ) -> Mapping[str, float] | None:
        if day not in self.session_index:
            raise ValueError(f"Signal date {day} is outside the session calendar")
        self._apply_pending(history, day)
        if self.session_index[day] == len(self.sessions) - 1:
            return None

        prices = {symbol: float(history[symbol][day]) for symbol in UNIVERSE}
        equity = self._equity(prices)
        if equity <= 0:
            raise ValueError("Shadow portfolio equity is not positive")
        proposed = {
            symbol: self.quantities[symbol] * prices[symbol] / equity
            for symbol in UNIVERSE
            if self.quantities[symbol] > 0
        }
        actions: list[tuple[str, str, float | None]] = []
        changed = False

        # Exits are evaluated before entries, matching the live cycle.
        for symbol, position in list(self.positions.items()):
            closes = _asof_values(history[symbol], day)
            if not closes:
                continue
            close = closes[-1]
            position["high_water"] = max(float(position["high_water"]), close)
            if close <= float(position["high_water"]) * (1.0 - TRAILING_STOP):
                proposed.pop(symbol, None)
                actions.append(("exit", symbol, None))
                changed = True
                continue
            held_days = (day - position["entry_date"]).days
            if held_days < MIN_HOLD_CALENDAR_DAYS:
                continue

            remaining = float(position["remaining"])
            if not position["tp2"] and close >= float(position["entry_price"]) * (1.0 + TP2_RETURN):
                remaining = max(0.0, remaining - TP_ORIGINAL_FRACTION)
                actions.append(("tp2", symbol, remaining))
                proposed[symbol] = (
                    float(position["original_quantity"]) * remaining * close
                    / equity
                )
                changed = True
            elif not position["tp1"] and close >= float(position["entry_price"]) * (1.0 + TP1_RETURN):
                remaining = max(0.0, remaining - TP_ORIGINAL_FRACTION)
                actions.append(("tp1", symbol, remaining))
                proposed[symbol] = (
                    float(position["original_quantity"]) * remaining * close
                    / equity
                )
                changed = True

            trend_exit = bool(closes) and close < ema_last(closes[-FAST_EMA:], FAST_EMA)
            three_day_return = closes[-1] / closes[-4] - 1.0 if len(closes) >= 4 else 0.0
            if trend_exit or three_day_return <= -0.05:
                proposed.pop(symbol, None)
                actions.append(("exit", symbol, None))
                changed = True

        spy_closes = _asof_values(history["SPY"], day)
        if len(spy_closes) >= 21:
            global_crisis = spy_closes[-1] / spy_closes[-21] - 1.0 <= CRISIS_THRESHOLD
        else:
            global_crisis = True

        candidates: list[tuple[float, str, float]] = []
        if not global_crisis:
            for symbol in UNIVERSE:
                if symbol in self.positions or symbol in {
                    pending_symbol
                    for action, pending_symbol, _ in actions
                    if action == "entry"
                }:
                    continue
                closes = _asof_values(history[symbol], day)
                entry_closes = closes[-250:]
                if len(entry_closes) < MIN_ENTRY_HISTORY:
                    continue
                regime_cutoff = day - timedelta(days=310)
                regime_closes = [
                    float(value)
                    for close_day, value in sorted(history[symbol].items())
                    if regime_cutoff < close_day <= day
                ]
                if self._regional_regime(regime_closes) != "BULL":
                    continue
                fast = ema_last(entry_closes, FAST_EMA)
                slow = ema_last(entry_closes, SLOW_EMA)
                fast_five_bars_ago = ema_last(entry_closes[:-5], FAST_EMA)
                if not (
                    fast > slow
                    and fast > fast_five_bars_ago
                    and entry_closes[-1] > fast
                ):
                    continue
                atr_rows = [
                    bars
                    for bar_day, bars in sorted(
                        self.atr_history.get(symbol, {}).items()
                    )
                    if bar_day <= day
                ]
                atr_rows = atr_rows[-250:]
                if _wilder_atr(atr_rows) is None:
                    continue
                returns = _returns(entry_closes, VOL_LOOKBACK)
                if len(returns) < VOL_LOOKBACK:
                    continue
                volatility = stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR)
                if not math.isfinite(volatility) or volatility <= 0:
                    continue
                weight = min(TARGET_ANNUAL_VOL / volatility, MAX_NAME_WEIGHT)
                momentum = (entry_closes[-1] - fast) / fast
                candidates.append((momentum, symbol, weight))

        candidates.sort(key=lambda item: item[0], reverse=True)
        exiting = {symbol for action, symbol, _ in actions if action == "exit"}
        held_for_corr = [symbol for symbol in self.positions if symbol not in exiting]
        pending_entries = {
            symbol for action, symbol, _ in actions if action == "entry"
        }
        planned_weight = math.fsum(proposed.values())
        for _, symbol, wanted_weight in candidates:
            active_count = len(self.positions) - len(exiting) + len(pending_entries)
            if active_count >= MAX_POSITIONS:
                break
            headroom = max(0.0, MAX_GROSS - planned_weight)
            if headroom <= 0:
                break
            candidate_returns = _asof_returns(
                history[symbol],
                day,
                CORR_RETURNS,
                calendar_days=CORR_HISTORY_DAYS,
            )
            correlated = False
            for held_symbol in (*held_for_corr, *sorted(pending_entries)):
                held_returns = _asof_returns(
                    history[held_symbol],
                    day,
                    CORR_RETURNS,
                    calendar_days=CORR_HISTORY_DAYS,
                )
                rho = _pearson(candidate_returns, held_returns)
                rho = round(rho, 4) if rho is not None else None
                if rho is not None and rho > CORR_THRESHOLD:
                    correlated = True
                    break
            if correlated:
                continue
            weight = min(wanted_weight, headroom)
            if weight <= 0:
                continue
            proposed[symbol] = weight
            actions.append(("entry", symbol, weight))
            pending_entries.add(symbol)
            held_for_corr.append(symbol)
            planned_weight += weight
            changed = True

        if not changed:
            return None
        target = {symbol: float(proposed.get(symbol, 0.0)) for symbol in UNIVERSE}
        self.pending_target = target
        self.pending = actions
        self.last_targets = {
            symbol: weight for symbol, weight in target.items() if weight > 0
        }
        return target


def _common_dates(history: Mapping[str, Mapping[date, float]], symbols: Sequence[str]) -> list[date]:
    date_sets = [set(history[symbol]) for symbol in symbols]
    return sorted(set.intersection(*date_sets)) if date_sets else []


def _window_return(result: BacktestResult, start: date, end: date) -> float | None:
    curve = result.equity_curve
    prior = [point for point in curve if point["date"] <= start]
    through = [point for point in curve if point["date"] <= end]
    if not through:
        return None
    if prior:
        initial = float(prior[-1]["equity"])
    else:
        first_in_window = [point for point in curve if start <= point["date"] <= end]
        if not first_in_window:
            return None
        initial = float(first_in_window[0]["equity"])
    final = float(through[-1]["equity"])
    return final / initial - 1.0 if initial > 0 else None


def _correlation_with_spy(result: BacktestResult, panel: PricePanel) -> float | None:
    curve = result.equity_curve
    strategy_returns, spy_returns = [], []
    spy = panel.closes["SPY"]
    for previous, current in zip(curve, curve[1:]):
        prior_day, current_day = previous["date"], current["date"]
        if prior_day not in spy or current_day not in spy:
            continue
        previous_equity = float(previous["equity"])
        if previous_equity <= 0:
            continue
        strategy_returns.append(float(current["equity"]) / previous_equity - 1.0)
        spy_returns.append(spy[current_day] / spy[prior_day] - 1.0)
    return _pearson(strategy_returns, spy_returns)


def _diagnostics(result: BacktestResult, panel: PricePanel) -> dict[str, Any]:
    first_held = next(
        (
            event["date"] for event in result.events
            if event.get("type") == "trade" and event.get("quantity_after", 0) > 0
        ),
        None,
    )
    return {
        "five_window_returns": {
            f"{start}..{end}": _window_return(
                result, date.fromisoformat(start), date.fromisoformat(end)
            )
            for start, end in EVALUATION_WINDOWS
        },
        "spy_daily_return_correlation": _correlation_with_spy(result, panel),
        "margin_call_count": sum(event.get("type") == "margin_call" for event in result.events),
        "first_held_date": first_held,
        "actual_common_first_session": result.data_window["first_session"],
        "late_listing_calendar_note": (
            "The 16-symbol harness calendar is the intersection of all included "
            "symbols; late listings restrict its first shared session."
        ),
    }


def run_scenarios(
    panel: PricePanel | Mapping[str, Mapping[date, float]],
    atr_history: Mapping[str, Mapping[date, tuple[float, float, float]]],
) -> list[BaselineRun]:
    """Run both fixed in-sample cost cases against made-up or supplied panels."""
    if isinstance(panel, PricePanel):
        history = panel.closes
    else:
        history = panel
        panel = PricePanel(closes=history, source="provided_price_panel")
    if set(history) != set(UNIVERSE):
        raise ValueError(
            "Price panel must contain exactly the Bot1 universe; "
            f"missing={sorted(set(UNIVERSE) - set(history))}, "
            f"extra={sorted(set(history) - set(UNIVERSE))}"
        )
    if any(day > END_DATE for series in history.values() for day in series):
        raise ValueError(f"Price panel contains rows after {END_DATE.isoformat()}")
    if any(
        day > END_DATE
        for series in atr_history.values()
        for day in series
    ):
        raise ValueError(f"ATR panel contains rows after {END_DATE.isoformat()}")
    sessions = [day for day in _common_dates(history, UNIVERSE) if START_DATE <= day <= END_DATE]
    if len(sessions) < 2:
        raise ValueError("At least two common in-sample sessions are required")

    results = []
    for cost_bps in COST_SCENARIOS:
        signal = Bot1BaselineSignal(sessions, atr_history, cost_bps=cost_bps)
        result = run_backtest(
            panel,
            signal,
            START_DATE,
            END_DATE,
            cost_bps=cost_bps,
            borrow_fee_rate=0,
            risk_free_rate=0,
            margin_rate=0,
            max_gross=MAX_GROSS,
            starting_equity=STARTING_EQUITY,
            whole_shares=True,
        )
        result.parameters.update({
            "family": STRATEGY_FAMILY,
            "candidate": "live_rule_baseline",
            "cost_bps": cost_bps,
            "spec": SPEC,
            "spec_hash": spec_hash(),
        })
        results.append(BaselineRun(cost_bps, result, _diagnostics(result, panel)))
    return results


def _execute_checked(cur: Any, query: str, parameters: Sequence[Any]) -> None:
    """Guard SQL placeholder arity before passing parameters to a DB cursor."""
    placeholders = query.count("%s")
    if placeholders != len(parameters):
        raise ValueError(
            f"SQL placeholder/parameter mismatch: query has {placeholders} %s "
            f"placeholders but {len(parameters)} parameters were supplied"
        )
    cur.execute(query, tuple(parameters))


def _load_run_data() -> tuple[PricePanel, dict[str, dict[date, tuple[float, float, float]]]]:
    """Explicit --run-only Helium loader; no DB access occurs on module import."""
    panel = load_adjusted_close(
        UNIVERSE,
        start_date=WARMUP_START,
        end_date=END_DATE,
    )
    # Local import and connection are intentionally confined to this run loader.
    from db.research_postgres import get_research_conn

    atr_history: dict[str, dict[date, tuple[float, float, float]]] = {
        symbol: {} for symbol in UNIVERSE
    }
    with get_research_conn() as conn:
        with conn.cursor() as cur:
            _execute_checked(
                cur,
                """
                SELECT symbol, date, high, low, close
                FROM public.research_daily_prices
                WHERE symbol = ANY(%s)
                  AND date >= %s AND date <= %s
                  AND quality_flag IS NULL
                ORDER BY symbol, date
                """,
                (list(UNIVERSE), WARMUP_START, END_DATE),
            )
            for symbol, day, high, low, close in cur.fetchall():
                atr_history[symbol][day] = (float(high), float(low), float(close))
    return panel, atr_history


def _persist_run(record: BaselineRun) -> int:
    """Append one result to exploration_runs only."""
    result = record.result
    parameters = {
        "family": STRATEGY_FAMILY,
        "candidate": "live_rule_baseline",
        "cost_bps": record.cost_bps,
        "spec": SPEC,
        "spec_hash": spec_hash(),
        "harness_parameters": result.parameters,
    }
    persisted_result = BacktestResult(
        equity_curve=result.equity_curve,
        events=result.events,
        metrics=result.metrics,
        parameters=parameters,
        data_window=result.data_window,
    )
    return append_exploration_run(
        persisted_result,
        strategy_family=STRATEGY_FAMILY,
        notes=json.dumps(
            {"supplemental": record.diagnostics, "classification": "in-sample baseline"},
            sort_keys=True,
            allow_nan=False,
        ),
    )


def run_cli() -> dict[str, Any]:
    print_spec()
    panel, atr_history = _load_run_data()
    records = run_scenarios(panel, atr_history)
    runs = []
    for record in records:
        run_id = _persist_run(record)
        runs.append({
            "cost_bps": record.cost_bps,
            "run_id": run_id,
            "harness_metrics": record.result.metrics,
            **record.diagnostics,
        })
    report = {
        "strategy_family": STRATEGY_FAMILY,
        "requested_dates": [START_DATE.isoformat(), END_DATE.isoformat()],
        "actual_common_first_session": records[0].result.data_window["first_session"],
        "runs": runs,
    }
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-spec", action="store_true", help="print frozen specification only")
    mode.add_argument("--run", action="store_true", help="load Helium prices, run, and append two scenarios")
    args = parser.parse_args()
    if args.print_spec:
        print_spec()
    else:
        run_cli()


if __name__ == "__main__":
    main()