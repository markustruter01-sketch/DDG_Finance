"""Generic, close-to-close long/short backtest harness for Helium research.

Signals are computed from an as-of view containing no prices later than the
decision date. A non-empty signal maps symbols to signed target weights of
equity; omitted symbols are targeted to zero. It is executed at the next
common valid close. Empty mappings and None mean "no new signal".

The Bot 3 rebalanced backtest is not reused: its rebalance path assumes
non-negative holdings, and it reads through the shared application DB rather
than the isolated Helium research connection.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean, stdev
from typing import Any

from db.research_postgres import get_research_conn

EXPLORE_END = date(2022, 12, 31)
PRICE_TABLE = "public.research_daily_prices"
RUN_SOURCE = "backtest_harness"
MAINTENANCE_EQUITY_RATIO = 0.30
TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365
_EPSILON = 1e-12


@dataclass(frozen=True)
class PricePanel:
    """Adjusted closes with quality-flagged rows removed, without imputation."""

    closes: Mapping[str, Mapping[date, float]]
    flagged_rows_dropped: int = 0
    source: str = PRICE_TABLE


@dataclass(frozen=True)
class BacktestResult:
    """Run output, including daily marks, events, metrics, and persisted metadata."""

    equity_curve: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    metrics: dict[str, float | int]
    parameters: dict[str, Any]
    data_window: dict[str, Any]


SignalFunction = Callable[
    [Mapping[str, Mapping[date, float]], date],
    Mapping[str, float] | None,
]


@dataclass
class _Book:
    cash: float
    quantities: dict[str, float]
    high_water: dict[str, float] = field(default_factory=dict)
    low_water: dict[str, float] = field(default_factory=dict)
    total_costs: float = 0.0
    total_interest: float = 0.0
    total_borrow_fees: float = 0.0
    traded_notional: float = 0.0


def _coerce_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, date):
        raise TypeError(f"Expected a date, got {type(value).__name__}")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number, not a boolean")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _panel_from_rows(
    rows: Sequence[tuple[str, date, Any, str | None]],
    *,
    source: str = PRICE_TABLE,
) -> PricePanel:
    """Build a panel from (symbol, date, adj_close, quality_flag) rows."""
    closes: dict[str, dict[date, float]] = {}
    flagged_rows_dropped = 0
    seen: set[tuple[str, date]] = set()

    for symbol, raw_day, adjusted_close, quality_flag in rows:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"Invalid price symbol: {symbol!r}")
        day = _coerce_date(raw_day)
        key = (symbol, day)
        if key in seen:
            raise ValueError(f"Duplicate price row for {symbol} on {day}")
        seen.add(key)

        if quality_flag is not None:
            flagged_rows_dropped += 1
            continue
        if adjusted_close is None:
            raise ValueError(f"Missing adjusted close for {symbol} on {day}")
        price = _finite_number(adjusted_close, f"{symbol} adjusted close on {day}")
        if price <= 0:
            raise ValueError(f"Adjusted close must be positive for {symbol} on {day}")
        closes.setdefault(symbol, {})[day] = price

    if not closes:
        raise ValueError("No unflagged adjusted-close rows were available")
    return PricePanel(
        closes={symbol: dict(sorted(series.items())) for symbol, series in closes.items()},
        flagged_rows_dropped=flagged_rows_dropped,
        source=source,
    )


def load_adjusted_close(
    symbols: Sequence[str],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PricePanel:
    """Load adjusted closes from Helium; quality-flagged rows are dropped, not filled."""
    if isinstance(symbols, (str, bytes)):
        raise ValueError("symbols must be a sequence of symbol names, not a string")
    raw_symbols = tuple(symbols)
    if any(not isinstance(symbol, str) for symbol in raw_symbols):
        raise ValueError("Every symbol must be a string")
    selected = tuple(dict.fromkeys(symbol.strip() for symbol in raw_symbols))
    if not selected or any(not symbol for symbol in selected):
        raise ValueError("At least one non-empty symbol is required")
    if start_date is not None:
        start_date = _coerce_date(start_date)
    if end_date is not None:
        end_date = _coerce_date(end_date)
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must not be after end_date")

    clauses = ["symbol = ANY(%s)"]
    params: list[Any] = [list(selected)]
    if start_date is not None:
        clauses.append("date >= %s")
        params.append(start_date)
    if end_date is not None:
        clauses.append("date <= %s")
        params.append(end_date)

    with get_research_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, date, adj_close, quality_flag
                FROM {PRICE_TABLE}
                WHERE {" AND ".join(clauses)}
                ORDER BY symbol, date
                """,
                tuple(params),
            )
            rows = cur.fetchall()

    panel = _panel_from_rows(rows)
    missing = sorted(set(selected) - set(panel.closes))
    if missing:
        raise ValueError(
            "No usable unflagged adjusted-close rows for requested symbols: "
            + ", ".join(missing)
        )
    return panel


class _AsOfSeries(Mapping[date, float]):
    def __init__(
        self,
        series: Mapping[date, float],
        ordered_dates: tuple[date, ...],
        cutoff: date,
    ) -> None:
        self._series = series
        self._dates = ordered_dates
        self._end = bisect_right(ordered_dates, cutoff)
        self._cutoff = cutoff

    def __getitem__(self, day: date) -> float:
        normalized = _coerce_date(day)
        if normalized > self._cutoff:
            raise KeyError(normalized)
        return self._series[normalized]

    def __iter__(self):
        for index in range(self._end):
            yield self._dates[index]

    def __len__(self) -> int:
        return self._end


class _AsOfPanel(Mapping[str, Mapping[date, float]]):
    """Read-only, lazily sliced view that rejects all future-date lookups."""

    def __init__(
        self,
        panel: PricePanel,
        cutoff: date,
        ordered_dates: Mapping[str, tuple[date, ...]],
    ) -> None:
        self._panel = panel
        self._cutoff = cutoff
        self._ordered_dates = ordered_dates

    def __getitem__(self, symbol: str) -> Mapping[date, float]:
        series = self._panel.closes[symbol]
        return _AsOfSeries(series, self._ordered_dates[symbol], self._cutoff)

    def __iter__(self):
        return iter(self._panel.closes)

    def __len__(self) -> int:
        return len(self._panel.closes)


def _coerce_panel(data: PricePanel | Mapping[str, Mapping[date, float]]) -> PricePanel:
    if isinstance(data, PricePanel):
        source = data.source
        dropped = data.flagged_rows_dropped
        raw_closes = data.closes
    else:
        source = "provided_price_panel"
        dropped = 0
        raw_closes = data
    if isinstance(dropped, bool) or not isinstance(dropped, int) or dropped < 0:
        raise ValueError("flagged_rows_dropped must be a non-negative integer")
    if not raw_closes:
        raise ValueError("Price panel has no symbols")

    normalized: dict[str, dict[date, float]] = {}
    for symbol, series in raw_closes.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"Invalid price symbol: {symbol!r}")
        if not series:
            raise ValueError(f"Price series for {symbol} is empty")
        converted: dict[date, float] = {}
        for raw_day, raw_price in series.items():
            day = _coerce_date(raw_day)
            if day in converted:
                raise ValueError(f"Duplicate price date for {symbol} on {day}")
            price = _finite_number(raw_price, f"{symbol} adjusted close on {day}")
            if price <= 0:
                raise ValueError(f"Adjusted close must be positive for {symbol} on {day}")
            converted[day] = price
        normalized[symbol] = dict(sorted(converted.items()))
    return PricePanel(normalized, dropped, source)


def _validate_registered_experiment(experiment_id: int) -> None:
    if isinstance(experiment_id, bool) or not isinstance(experiment_id, int) or experiment_id <= 0:
        raise ValueError("registered_experiment_id must be a positive integer")
    with get_research_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT results IS NULL
                FROM research_ledger
                WHERE experiment_id = %s
                """,
                (experiment_id,),
            )
            row = cur.fetchone()
    if row is None or row[0] is not True:
        raise ValueError(
            "Holdout runs require a registered research_ledger experiment "
            "that exists and has no results recorded"
        )


def _validate_run_parameters(
    *,
    cost_bps: float,
    borrow_fee_rate: float,
    risk_free_rate: float,
    margin_rate: float,
    max_gross: float,
    starting_equity: float,
    trail_pct: float | None,
) -> tuple[float, float, float, float, float, float, float | None]:
    cost_bps = _finite_number(cost_bps, "cost_bps")
    borrow_fee_rate = _finite_number(borrow_fee_rate, "borrow_fee_rate")
    risk_free_rate = _finite_number(risk_free_rate, "risk_free_rate")
    margin_rate = _finite_number(margin_rate, "margin_rate")
    max_gross = _finite_number(max_gross, "max_gross")
    starting_equity = _finite_number(starting_equity, "starting_equity")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")
    if borrow_fee_rate < 0:
        raise ValueError("borrow_fee_rate must be non-negative")
    if margin_rate < 0:
        raise ValueError("margin_rate must be non-negative")
    if risk_free_rate <= -1:
        raise ValueError("risk_free_rate must be greater than -1")
    if max_gross <= 0:
        raise ValueError("max_gross must be positive")
    if starting_equity <= 0:
        raise ValueError("starting_equity must be positive")
    if trail_pct is not None:
        trail_pct = _finite_number(trail_pct, "trail_pct")
        if not 0 < trail_pct < 1:
            raise ValueError("trail_pct must be between 0 and 1")
    return (
        cost_bps,
        borrow_fee_rate,
        risk_free_rate,
        margin_rate,
        max_gross,
        starting_equity,
        trail_pct,
    )


def _equity(book: _Book, prices: Mapping[str, float]) -> float:
    return book.cash + sum(
        book.quantities[symbol] * prices[symbol]
        for symbol in book.quantities
    )


def _gross_and_net(book: _Book, prices: Mapping[str, float]) -> tuple[float, float]:
    values = {
        symbol: quantity * prices[symbol]
        for symbol, quantity in book.quantities.items()
    }
    return sum(abs(value) for value in values.values()), sum(values.values())


def _rounded_quantity(quantity: float, whole_shares: bool) -> float:
    return float(math.trunc(quantity)) if whole_shares else quantity


def _trade_to_quantities(
    book: _Book,
    target_quantities: Mapping[str, float],
    prices: Mapping[str, float],
    *,
    cost_rate: float,
    whole_shares: bool,
    day: date,
    reason: str,
    events: list[dict[str, Any]],
) -> None:
    for symbol in sorted(book.quantities):
        old_quantity = book.quantities[symbol]
        target_quantity = _rounded_quantity(
            target_quantities.get(symbol, old_quantity),
            whole_shares,
        )
        change = target_quantity - old_quantity
        if abs(change) <= _EPSILON:
            continue

        price = prices[symbol]
        notional = change * price
        cost = abs(notional) * cost_rate
        # A negative quantity change sells shares and credits short-sale proceeds.
        book.cash -= notional
        book.cash -= cost
        book.total_costs += cost
        book.traded_notional += abs(notional)
        book.quantities[symbol] = (
            0.0 if abs(target_quantity) <= _EPSILON else target_quantity
        )

        if abs(target_quantity) <= _EPSILON:
            book.high_water.pop(symbol, None)
            book.low_water.pop(symbol, None)
        elif old_quantity == 0 or old_quantity * target_quantity < 0:
            book.high_water.pop(symbol, None)
            book.low_water.pop(symbol, None)
            if target_quantity > 0:
                book.high_water[symbol] = price
            else:
                book.low_water[symbol] = price
        elif target_quantity > 0:
            book.high_water.setdefault(symbol, price)
        else:
            book.low_water.setdefault(symbol, price)

        events.append(
            {
                "type": "trade",
                "date": day.isoformat(),
                "symbol": symbol,
                "quantity_change": change,
                "quantity_after": book.quantities[symbol],
                "price": price,
                "notional": abs(notional),
                "cost": cost,
                "reason": reason,
            }
        )


def _enforce_gross_cap(
    book: _Book,
    prices: Mapping[str, float],
    *,
    cost_rate: float,
    max_gross: float,
    whole_shares: bool,
    day: date,
    reason: str,
    events: list[dict[str, Any]],
) -> float:
    total_scale = 1.0
    for _ in range(32):
        equity = _equity(book, prices)
        gross, _ = _gross_and_net(book, prices)
        allowed = max_gross * max(equity, 0.0)
        if gross <= allowed + 1e-9:
            return total_scale
        if gross <= _EPSILON or equity <= 0:
            scale = 0.0
        else:
            scale = allowed / gross
        target = {
            symbol: _rounded_quantity(quantity * scale, whole_shares)
            for symbol, quantity in book.quantities.items()
        }
        if all(
            abs(target[symbol] - book.quantities[symbol]) <= _EPSILON
            for symbol in book.quantities
        ):
            target = {symbol: 0.0 for symbol in book.quantities}
            scale = 0.0
        total_scale *= scale
        _trade_to_quantities(
            book,
            target,
            prices,
            cost_rate=cost_rate,
            whole_shares=whole_shares,
            day=day,
            reason=reason,
            events=events,
        )
    raise RuntimeError(f"Could not enforce max_gross={max_gross} on {day}")


def _accrue_financing(
    book: _Book,
    previous_prices: Mapping[str, float],
    *,
    calendar_days: int,
    margin_rate: float,
    borrow_fee_rate: float,
    day: date,
    events: list[dict[str, Any]],
) -> None:
    """Charge margin interest and short borrow fees for the elapsed calendar days."""
    if calendar_days <= 0:
        return
    interest = (
        max(0.0, -book.cash)
        * margin_rate
        * calendar_days
        / CALENDAR_DAYS_PER_YEAR
    )
    short_market_value = sum(
        max(0.0, -book.quantities[symbol]) * previous_prices[symbol]
        for symbol in book.quantities
    )
    borrow_fee = (
        short_market_value
        * borrow_fee_rate
        * calendar_days
        / CALENDAR_DAYS_PER_YEAR
    )
    book.cash -= interest + borrow_fee
    book.total_interest += interest
    book.total_borrow_fees += borrow_fee
    if interest:
        events.append(
            {
                "type": "margin_interest",
                "date": day.isoformat(),
                "calendar_days": calendar_days,
                "amount": interest,
            }
        )
    if borrow_fee:
        events.append(
            {
                "type": "borrow_fee",
                "date": day.isoformat(),
                "calendar_days": calendar_days,
                "amount": borrow_fee,
            }
        )


def _check_maintenance_margin(
    book: _Book,
    prices: Mapping[str, float],
    *,
    cost_rate: float,
    max_gross: float,
    whole_shares: bool,
    day: date,
    events: list[dict[str, Any]],
) -> bool:
    """Record a maintenance call and de-lever the book to its gross cap."""
    equity = _equity(book, prices)
    gross, _ = _gross_and_net(book, prices)
    ratio = equity / gross if gross > 0 else math.inf
    if gross <= 0 or ratio >= MAINTENANCE_EQUITY_RATIO:
        return False
    events.append(
        {
            "type": "margin_call",
            "date": day.isoformat(),
            "equity_before": equity,
            "gross_exposure_before": gross,
            "equity_to_gross_before": ratio,
        }
    )
    # The default cap (1.5x) is below the maintenance limit (3.33x).
    # Keep both limits satisfied when callers configure a larger max_gross.
    maintenance_cap = min(max_gross, 1.0 / MAINTENANCE_EQUITY_RATIO)
    _enforce_gross_cap(
        book,
        prices,
        cost_rate=cost_rate,
        max_gross=maintenance_cap,
        whole_shares=whole_shares,
        day=day,
        reason="margin_call_deleverage",
        events=events,
    )
    return True


def _exit_due_stops(
    book: _Book,
    stopped_symbols: set[str],
    prices: Mapping[str, float],
    *,
    cost_rate: float,
    whole_shares: bool,
    day: date,
    events: list[dict[str, Any]],
) -> None:
    """Exit stop-triggered positions at this close, charging normal trade costs."""
    for symbol in sorted(stopped_symbols):
        if abs(book.quantities[symbol]) <= _EPSILON:
            continue
        _trade_to_quantities(
            book,
            {**book.quantities, symbol: 0.0},
            prices,
            cost_rate=cost_rate,
            whole_shares=whole_shares,
            day=day,
            reason="trailing_stop_exit",
            events=events,
        )
        events.append(
            {
                "type": "trailing_stop_exit",
                "date": day.isoformat(),
                "symbol": symbol,
                "price": prices[symbol],
            }
        )


def _update_trailing_stops(
    book: _Book,
    prices: Mapping[str, float],
    *,
    trail_pct: float | None,
    day: date,
    next_close_available: bool,
    pending_stops: set[str],
    events: list[dict[str, Any]],
) -> None:
    """Update long/short trailing levels and schedule close breaches for next close."""
    if trail_pct is None:
        return
    for symbol, quantity in book.quantities.items():
        if quantity > 0:
            high = max(
                book.high_water.get(symbol, prices[symbol]),
                prices[symbol],
            )
            book.high_water[symbol] = high
            stop_price = high * (1.0 - trail_pct)
            breached = prices[symbol] <= stop_price
            side = "long"
        elif quantity < 0:
            low = min(
                book.low_water.get(symbol, prices[symbol]),
                prices[symbol],
            )
            book.low_water[symbol] = low
            stop_price = low * (1.0 + trail_pct)
            breached = prices[symbol] >= stop_price
            side = "short"
        else:
            continue
        if breached:
            if next_close_available:
                pending_stops.add(symbol)
            events.append(
                {
                    "type": "trailing_stop_triggered",
                    "date": day.isoformat(),
                    "symbol": symbol,
                    "side": side,
                    "stop_price": stop_price,
                    "close": prices[symbol],
                    "next_close_available": next_close_available,
                }
            )


def _exit_due_sleeve_stops(
    book: _Book,
    stopped_sleeves: Mapping[str, float],
    sleeve_quantities: dict[str, float],
    prices: Mapping[str, float],
    *,
    cost_rate: float,
    whole_shares: bool,
    max_gross: float,
    cash_asset: str | None,
    day: date,
    events: list[dict[str, Any]],
) -> None:
    """Exit only the stopped virtual sleeve, retaining other sleeve exposure."""
    for symbol, stopped_quantity in sorted(stopped_sleeves.items()):
        if abs(stopped_quantity) <= _EPSILON:
            continue
        targets = dict(book.quantities)
        symbol_quantity_before = book.quantities[symbol]
        targets[symbol] = _rounded_quantity(
            symbol_quantity_before - stopped_quantity, whole_shares
        )
        cash_adjustment_quantity = 0.0
        if cash_asset is not None:
            if cash_asset == symbol:
                raise ValueError("trailing_stop_cash_asset cannot be the stopped symbol")
            exited_quantity = book.quantities[symbol] - targets[symbol]
            requested_cash_quantity = (
                exited_quantity * prices[symbol] / prices[cash_asset]
            )
            cash_target = _rounded_quantity(
                book.quantities[cash_asset] + requested_cash_quantity,
                whole_shares,
            )
            cash_adjustment_quantity = cash_target - book.quantities[cash_asset]
            targets[cash_asset] = _rounded_quantity(
                cash_target,
                whole_shares,
            )
        _trade_to_quantities(
            book,
            targets,
            prices,
            cost_rate=cost_rate,
            whole_shares=whole_shares,
            day=day,
            reason="trailing_stop_sleeve_exit",
            events=events,
        )
        _enforce_gross_cap(
            book,
            prices,
            cost_rate=cost_rate,
            max_gross=max_gross,
            whole_shares=whole_shares,
            day=day,
            reason="post_stop_gross_cap",
            events=events,
        )
        sleeve_quantities[symbol] = 0.0
        book.high_water.pop(symbol, None)
        book.low_water.pop(symbol, None)
        events.append(
            {
                "type": "trailing_stop_exit",
                "date": day.isoformat(),
                "symbol": symbol,
                "sleeve": "trend",
                "quantity": stopped_quantity,
                "quantity_change": targets[symbol] - symbol_quantity_before,
                "price": prices[symbol],
                "quantity_after": book.quantities[symbol],
                "cash_asset": cash_asset,
                "cash_adjustment_quantity": cash_adjustment_quantity,
            }
        )


def _update_sleeve_trailing_stops(
    sleeve_quantities: Mapping[str, float],
    high_water: dict[str, float],
    low_water: dict[str, float],
    prices: Mapping[str, float],
    *,
    trail_pct: float,
    day: date,
    next_close_available: bool,
    pending_stops: dict[str, float],
    events: list[dict[str, Any]],
) -> None:
    """Schedule stops against sleeve quantities, not net symbol quantities."""
    for symbol, quantity in sleeve_quantities.items():
        if abs(quantity) <= _EPSILON or symbol in pending_stops:
            continue
        if quantity > 0:
            high = max(high_water.get(symbol, prices[symbol]), prices[symbol])
            high_water[symbol] = high
            stop_price = high * (1.0 - trail_pct)
            breached = prices[symbol] <= stop_price
            side = "long"
        else:
            low = min(low_water.get(symbol, prices[symbol]), prices[symbol])
            low_water[symbol] = low
            stop_price = low * (1.0 + trail_pct)
            breached = prices[symbol] >= stop_price
            side = "short"
        if not breached:
            continue
        if next_close_available:
            pending_stops[symbol] = quantity
        events.append(
            {
                "type": "trailing_stop_triggered",
                "date": day.isoformat(),
                "symbol": symbol,
                "sleeve": "trend",
                "side": side,
                "quantity": quantity,
                "stop_price": stop_price,
                "close": prices[symbol],
                "next_close_available": next_close_available,
            }
        )


def _rebalance_to_weights(
    book: _Book,
    target_weights: Mapping[str, float],
    prices: Mapping[str, float],
    *,
    cost_rate: float,
    max_gross: float,
    whole_shares: bool,
    day: date,
    events: list[dict[str, Any]],
) -> tuple[float, float]:
    equity = _equity(book, prices)
    if equity <= 0:
        targets = {symbol: 0.0 for symbol in book.quantities}
        scale = 0.0
    else:
        target_values = {
            symbol: target_weights.get(symbol, 0.0) * equity
            for symbol in book.quantities
        }
        gross = sum(abs(value) for value in target_values.values())
        cap = max_gross * equity
        scale = min(1.0, cap / gross) if gross else 1.0
        targets = {
            symbol: _rounded_quantity(
                target_values[symbol] * scale / prices[symbol],
                whole_shares,
            )
            for symbol in book.quantities
        }

    _trade_to_quantities(
        book,
        targets,
        prices,
        cost_rate=cost_rate,
        whole_shares=whole_shares,
        day=day,
        reason="signal_rebalance",
        events=events,
    )
    enforced_scale = _enforce_gross_cap(
        book,
        prices,
        cost_rate=cost_rate,
        max_gross=max_gross,
        whole_shares=whole_shares,
        day=day,
        reason="post_cost_gross_cap",
        events=events,
    )
    return equity, scale * enforced_scale


def _normalise_signal(
    raw_signal: Mapping[str, float] | None,
    symbols: tuple[str, ...],
) -> dict[str, float] | None:
    if raw_signal is None:
        return None
    if not isinstance(raw_signal, Mapping):
        raise TypeError("A strategy signal must be a symbol-to-weight mapping or None")
    if not raw_signal:
        return None
    unknown = set(raw_signal) - set(symbols)
    if unknown:
        raise ValueError(f"Signal contains unknown symbols: {sorted(unknown)}")
    return {
        symbol: (
            _finite_number(raw_signal[symbol], f"target weight for {symbol}")
            if symbol in raw_signal
            else 0.0
        )
        for symbol in symbols
    }


def _calculate_metrics(
    equity_curve: Sequence[Mapping[str, Any]],
    *,
    starting_equity: float,
    risk_free_rate: float,
    book: _Book,
    number_of_trades: int,
) -> dict[str, float | int]:
    equities = [float(point["equity"]) for point in equity_curve]
    dates = [point["date"] for point in equity_curve]
    returns = [
        equities[index] / equities[index - 1] - 1
        if equities[index - 1] > 0
        else 0.0
        for index in range(1, len(equities))
    ]
    rf_daily = (1.0 + risk_free_rate) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0
    excess_returns = [value - rf_daily for value in returns]
    volatility = (
        stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR)
        if len(returns) > 1
        else 0.0
    )
    sharpe = (
        mean(excess_returns) / stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR)
        if len(returns) > 1 and stdev(returns) > 0
        else 0.0
    )
    downside_deviation = (
        math.sqrt(
            mean(min(value, 0.0) ** 2 for value in excess_returns)
        )
        if excess_returns
        else 0.0
    )
    sortino = (
        mean(excess_returns) / downside_deviation * math.sqrt(TRADING_DAYS_PER_YEAR)
        if excess_returns and downside_deviation > 0
        else 0.0
    )

    peak = starting_equity
    max_drawdown = 0.0
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)

    total_return = equities[-1] / starting_equity - 1.0
    elapsed_days = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
    if elapsed_days <= 0:
        cagr = total_return
    elif equities[-1] <= 0:
        cagr = -1.0
    else:
        try:
            cagr = (equities[-1] / starting_equity) ** (
                CALENDAR_DAYS_PER_YEAR / elapsed_days
            ) - 1.0
        except OverflowError as exc:
            raise ValueError("CAGR overflowed; check run horizon and price inputs") from exc
        if not math.isfinite(cagr):
            raise ValueError("CAGR is not finite; check run horizon and price inputs")
    calmar = cagr / max_drawdown if max_drawdown > 0 else 0.0

    gross_exposures = [
        float(point["gross_exposure"]) / float(point["equity"])
        if float(point["equity"]) > 0
        else 0.0
        for point in equity_curve
    ]
    net_exposures = [
        float(point["net_exposure"]) / float(point["equity"])
        if float(point["equity"]) > 0
        else 0.0
        for point in equity_curve
    ]
    average_equity = mean(equities) if equities else starting_equity
    turnover = book.traded_notional / average_equity if average_equity > 0 else 0.0

    return {
        "total_return": total_return,
        "cagr": cagr,
        "annualised_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "turnover": turnover,
        "average_gross_exposure": mean(gross_exposures) if gross_exposures else 0.0,
        "average_net_exposure": mean(net_exposures) if net_exposures else 0.0,
        "number_of_trades": number_of_trades,
        "total_costs": book.total_costs,
        "total_interest": book.total_interest,
        "total_borrow_fees": book.total_borrow_fees,
        "total_traded_notional": book.traded_notional,
    }


def run_backtest(
    data: PricePanel | Mapping[str, Mapping[date, float]],
    signal_function: SignalFunction,
    start: date,
    end: date,
    *,
    cost_bps: float,
    borrow_fee_rate: float,
    risk_free_rate: float,
    margin_rate: float = 0.0625,
    max_gross: float = 1.5,
    starting_equity: float = 100_000.0,
    whole_shares: bool = False,
    trail_pct: float | None = None,
    trailing_stop_signal: SignalFunction | None = None,
    trailing_stop_cash_asset: str | None = None,
    registered_experiment_id: int | None = None,
) -> BacktestResult:
    """Run a generic signed-target-weight strategy over a synchronized close panel.

    ``signal_function`` receives only history dated on or before the decision
    day. Each non-empty mapping is a full target portfolio expressed as signed
    fractions of equity; it trades on the next common valid close. Missing
    symbol dates are excluded from the common session calendar, never forward-
    filled. Financing accrues over actual calendar days between closes.

    ``trailing_stop_signal`` can identify one virtual sleeve inside a net
    symbol position. Its signed target weights must be emitted alongside each
    portfolio target. A triggered stop exits only that sleeve; when supplied,
    ``trailing_stop_cash_asset`` receives the stopped sleeve's marked notional.
    """
    if not callable(signal_function):
        raise TypeError("signal_function must be callable")
    if trailing_stop_signal is not None and not callable(trailing_stop_signal):
        raise TypeError("trailing_stop_signal must be callable when provided")
    start = _coerce_date(start)
    end = _coerce_date(end)
    if start > end:
        raise ValueError("start must not be after end")
    if end > EXPLORE_END:
        if registered_experiment_id is None:
            raise ValueError(
                f"Runs ending after {EXPLORE_END.isoformat()} require a registered "
                "research_ledger experiment with no results recorded"
            )
        _validate_registered_experiment(registered_experiment_id)

    (
        cost_bps,
        borrow_fee_rate,
        risk_free_rate,
        margin_rate,
        max_gross,
        starting_equity,
        trail_pct,
    ) = _validate_run_parameters(
        cost_bps=cost_bps,
        borrow_fee_rate=borrow_fee_rate,
        risk_free_rate=risk_free_rate,
        margin_rate=margin_rate,
        max_gross=max_gross,
        starting_equity=starting_equity,
        trail_pct=trail_pct,
    )
    if not isinstance(whole_shares, bool):
        raise ValueError("whole_shares must be a boolean")
    if trailing_stop_signal is not None and trail_pct is None:
        raise ValueError(
            "trail_pct is required when trailing_stop_signal is provided"
        )
    if trailing_stop_signal is None and trailing_stop_cash_asset is not None:
        raise ValueError(
            "trailing_stop_cash_asset requires trailing_stop_signal"
        )

    panel = _coerce_panel(data)
    symbols = tuple(sorted(panel.closes))
    if (
        trailing_stop_cash_asset is not None
        and trailing_stop_cash_asset not in symbols
    ):
        raise ValueError(
            "trailing_stop_cash_asset must be present in the price panel"
        )
    common_dates = set.intersection(
        *(set(series) for series in panel.closes.values())
    )
    sessions = sorted(day for day in common_dates if start <= day <= end)
    if len(sessions) < 2:
        raise ValueError(
            "At least two common valid closes are required to evaluate a run"
        )

    prices_by_symbol = panel.closes
    book = _Book(
        cash=starting_equity,
        quantities={symbol: 0.0 for symbol in symbols},
    )
    events: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    cost_rate = cost_bps / 10_000.0
    previous_day: date | None = None
    previous_prices: dict[str, float] | None = None
    pending_signal: dict[str, float] | None = None
    pending_sleeve_signal: dict[str, float] | None = None
    pending_stops: set[str] = set()
    pending_sleeve_stops: dict[str, float] = {}
    sleeve_quantities = {symbol: 0.0 for symbol in symbols}
    sleeve_high_water: dict[str, float] = {}
    sleeve_low_water: dict[str, float] = {}
    ordered_dates = {
        symbol: tuple(sorted(series))
        for symbol, series in panel.closes.items()
    }

    for index, day in enumerate(sessions):
        current_prices = {
            symbol: prices_by_symbol[symbol][day]
            for symbol in symbols
        }

        if previous_day is not None and previous_prices is not None:
            _accrue_financing(
                book,
                previous_prices,
                calendar_days=(day - previous_day).days,
                margin_rate=margin_rate,
                borrow_fee_rate=borrow_fee_rate,
                day=day,
                events=events,
            )

        # Check maintenance against the marked portfolio before scheduled trades.
        quantities_before_margin_check = dict(book.quantities)
        margin_called = _check_maintenance_margin(
            book,
            current_prices,
            cost_rate=cost_rate,
            max_gross=max_gross,
            whole_shares=whole_shares,
            day=day,
            events=events,
        )
        if margin_called and trailing_stop_signal is not None:
            for symbol in symbols:
                before = quantities_before_margin_check[symbol]
                if abs(before) > _EPSILON:
                    sleeve_quantities[symbol] *= (
                        book.quantities[symbol] / before
                    )

        stopped_today = set(pending_stops)
        pending_stops.clear()
        _exit_due_stops(
            book,
            stopped_today,
            current_prices,
            cost_rate=cost_rate,
            whole_shares=whole_shares,
            day=day,
            events=events,
        )

        stopped_sleeves_today = dict(pending_sleeve_stops)
        pending_sleeve_stops.clear()
        _exit_due_sleeve_stops(
            book,
            stopped_sleeves_today,
            sleeve_quantities,
            current_prices,
            cost_rate=cost_rate,
            whole_shares=whole_shares,
            max_gross=max_gross,
            cash_asset=trailing_stop_cash_asset,
            day=day,
            events=events,
        )
        for symbol in stopped_sleeves_today:
            sleeve_high_water.pop(symbol, None)
            sleeve_low_water.pop(symbol, None)

        if pending_signal is not None:
            targets = dict(pending_signal)
            if trailing_stop_signal is None:
                for symbol in stopped_today:
                    targets[symbol] = 0.0
                _rebalance_to_weights(
                    book,
                    targets,
                    current_prices,
                    cost_rate=cost_rate,
                    max_gross=max_gross,
                    whole_shares=whole_shares,
                    day=day,
                    events=events,
                )
            else:
                if pending_sleeve_signal is None:
                    raise RuntimeError(
                        "A sleeve-aware portfolio target is missing its stop-sleeve target"
                    )
                sleeve_targets = dict(pending_sleeve_signal)
                for symbol in stopped_sleeves_today:
                    stopped_weight = sleeve_targets.get(symbol, 0.0)
                    targets[symbol] = targets.get(symbol, 0.0) - stopped_weight
                    if trailing_stop_cash_asset is not None:
                        targets[trailing_stop_cash_asset] = (
                            targets.get(trailing_stop_cash_asset, 0.0)
                            + stopped_weight
                        )
                    sleeve_targets[symbol] = 0.0
                equity_before_trade, effective_scale = _rebalance_to_weights(
                    book,
                    targets,
                    current_prices,
                    cost_rate=cost_rate,
                    max_gross=max_gross,
                    whole_shares=whole_shares,
                    day=day,
                    events=events,
                )
                for symbol in symbols:
                    old_quantity = sleeve_quantities[symbol]
                    target_quantity = (
                        sleeve_targets.get(symbol, 0.0)
                        * equity_before_trade
                        * effective_scale
                        / current_prices[symbol]
                    )
                    sleeve_quantities[symbol] = target_quantity
                    if abs(target_quantity) <= _EPSILON:
                        sleeve_high_water.pop(symbol, None)
                        sleeve_low_water.pop(symbol, None)
                    elif (
                        abs(old_quantity) <= _EPSILON
                        or old_quantity * target_quantity < 0
                    ):
                        sleeve_high_water.pop(symbol, None)
                        sleeve_low_water.pop(symbol, None)
                        if target_quantity > 0:
                            sleeve_high_water[symbol] = current_prices[symbol]
                        else:
                            sleeve_low_water[symbol] = current_prices[symbol]
        pending_signal = None
        pending_sleeve_signal = None

        equity = _equity(book, current_prices)
        gross_exposure, net_exposure = _gross_and_net(book, current_prices)
        equity_curve.append(
            {
                "date": day,
                "equity": equity,
                "cash": book.cash,
                "gross_exposure": gross_exposure,
                "net_exposure": net_exposure,
            }
        )

        if trailing_stop_signal is None:
            _update_trailing_stops(
                book,
                current_prices,
                trail_pct=trail_pct,
                day=day,
                next_close_available=index + 1 < len(sessions),
                pending_stops=pending_stops,
                events=events,
            )
        elif trail_pct is not None:
            _update_sleeve_trailing_stops(
                sleeve_quantities,
                sleeve_high_water,
                sleeve_low_water,
                current_prices,
                trail_pct=trail_pct,
                day=day,
                next_close_available=index + 1 < len(sessions),
                pending_stops=pending_sleeve_stops,
                events=events,
            )

        as_of_history = _AsOfPanel(panel, day, ordered_dates)
        raw_signal = signal_function(as_of_history, day)
        normalized_signal = _normalise_signal(raw_signal, symbols)
        raw_sleeve_signal = (
            trailing_stop_signal(as_of_history, day)
            if trailing_stop_signal is not None
            else None
        )
        normalized_sleeve_signal = (
            (
                {symbol: 0.0 for symbol in symbols}
                if not raw_sleeve_signal
                else _normalise_signal(raw_sleeve_signal, symbols)
            )
            if trailing_stop_signal is not None and raw_sleeve_signal is not None
            else None
        )
        if (
            normalized_signal is None
            and normalized_sleeve_signal is not None
            and not any(
                abs(weight) > _EPSILON
                for weight in normalized_sleeve_signal.values()
            )
        ):
            normalized_sleeve_signal = None
        if trailing_stop_signal is not None and (
            (normalized_signal is None) != (normalized_sleeve_signal is None)
        ):
            raise ValueError(
                "Portfolio and trailing-stop sleeve signals must be emitted together"
            )
        if normalized_signal is not None:
            if index + 1 >= len(sessions):
                raise ValueError(
                    f"Signal on final session {day} has no next close for execution"
                )
            pending_signal = normalized_signal
            pending_sleeve_signal = normalized_sleeve_signal

        previous_day = day
        previous_prices = current_prices

    metrics = _calculate_metrics(
        equity_curve,
        starting_equity=starting_equity,
        risk_free_rate=risk_free_rate,
        book=book,
        number_of_trades=sum(event["type"] == "trade" for event in events),
    )
    parameters: dict[str, Any] = {
        "cost_bps": cost_bps,
        "borrow_fee_rate": borrow_fee_rate,
        "risk_free_rate": risk_free_rate,
        "margin_rate": margin_rate,
        "max_gross": max_gross,
        "starting_equity": starting_equity,
        "whole_shares": whole_shares,
        "trail_pct": trail_pct,
        "trailing_stop_mode": (
            "sleeve_signal"
            if trailing_stop_signal is not None
            else "portfolio"
            if trail_pct is not None
            else "disabled"
        ),
        "trailing_stop_cash_asset": trailing_stop_cash_asset,
        "registered_experiment_id": registered_experiment_id,
    }
    data_window = {
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "first_session": sessions[0].isoformat(),
        "last_session": sessions[-1].isoformat(),
        "symbols": list(symbols),
        "price_source": panel.source,
        "flagged_rows_dropped": panel.flagged_rows_dropped,
        "session_calendar": "intersection_of_unflagged_adjusted_close_dates",
        "holdout_cutoff": EXPLORE_END.isoformat(),
    }
    return BacktestResult(
        equity_curve=tuple(equity_curve),
        events=tuple(events),
        metrics=metrics,
        parameters=parameters,
        data_window=data_window,
    )


def append_exploration_run(
    result: BacktestResult,
    *,
    strategy_family: str,
    notes: str = "",
) -> int:
    """Append a completed harness run using exploration_runs' existing columns."""
    if not isinstance(strategy_family, str) or not strategy_family.strip():
        raise ValueError("strategy_family must be a non-empty string")

    spec_payload = {
        "strategy_family": strategy_family,
        "parameters": result.parameters,
        "data_window": result.data_window,
    }
    spec_json = json.dumps(
        spec_payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    spec_hash = hashlib.sha256(spec_json.encode("utf-8")).hexdigest()
    note_payload = {
        "engine": "signed_long_short_backtest_harness",
        "metrics": result.metrics,
    }
    serialized_notes = json.dumps(
        note_payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if notes.strip():
        serialized_notes = f"{notes.strip()}\n{serialized_notes}"

    with get_research_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO exploration_runs
                    (strategy_family, parameters, data_window, spec_hash, source,
                     sharpe, return_pct, max_drawdown, notes)
                VALUES (%s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)
                RETURNING run_id
                """,
                (
                    strategy_family,
                    json.dumps(result.parameters, sort_keys=True, allow_nan=False),
                    json.dumps(result.data_window, sort_keys=True, allow_nan=False),
                    spec_hash,
                    RUN_SOURCE,
                    float(result.metrics["sharpe"]),
                    float(result.metrics["total_return"]) * 100.0,
                    float(result.metrics["max_drawdown"]),
                    serialized_notes[:4000],
                ),
            )
            row = cur.fetchone()
    if row is None:
        raise RuntimeError("exploration_runs insert returned no run_id")
    return int(row[0])
