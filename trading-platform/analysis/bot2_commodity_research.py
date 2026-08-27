#!/usr/bin/env python3
"""Development-only Bot 2 commodity research and backtest.

This file intentionally has no imports from live runners, strategy modules, or
order-placement functions.  Its only database writes are the additive
``commodity_etf`` schema support in ``bot2_data_pipeline`` and the explicit
research-ledger registration/result calls made by ``main``.

Run from ``trading-platform``:

    python3 -m analysis.bot2_commodity_research

The command performs the Part A data gate first.  If it fails, no experiment
is registered and no backtest is run.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402
from analysis.bot2_data_pipeline import (  # noqa: E402
    COMMODITY_ETFS,
    EARNINGS_TABLE,
    PRICES_TABLE,
    START_DATE,
    STOCKS,
    _expected_trading_days,
    ensure_tables,
)
from analysis.research_ledger import (  # noqa: E402
    ensure_research_tables,
    record_results,
    register_experiment,
)


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
OVERLAP_SYMBOLS = ("SPY", "GLD", "SLV", "BTC-USD", "ETH-USD")
END_DATE = date.today()
WINDOWS: tuple[tuple[str, date, date], ...] = (
    ("2021", date(2021, 1, 4), date(2021, 12, 31)),
    ("2022", date(2022, 1, 3), date(2022, 12, 30)),
    ("2023", date(2023, 1, 3), date(2023, 12, 29)),
    ("2024-present", date(2024, 1, 2), END_DATE),
)

# These values are printed and hashed before any result calculation.  They are
# deliberately not read from live strategy configuration.
LOCKED_PARAMETERS: dict[str, Any] = {
    "commodity_universe": list(COMMODITY_ETFS),
    "momentum_lookback_months_primary": 12,
    "momentum_lookback_sensitivity_months": [12, 6, 3],
    "rebalance": "first available trading session of each month",
    "momentum_signal": "close / close approximately N*21 sessions ago - 1 > 0",
    "volatility_window_sessions": 63,
    "allocation": "inverse volatility among positive-momentum commodities",
    "allocation_floor": 0.05,
    "allocation_cap": 0.40,
    "commodity_max_deployment": 0.80,
    "earnings_allocation_cap": 0.20,
    "earnings_signal": "positive reported surprise > 0",
    "earnings_report_time": "pre-market enters report session; post-market enters next session; unknown excluded",
    "earnings_exit_variants": ["close", "open"],
    "stop_loss": 0.08,
    "slippage_each_leg_bps": 10,
    "starting_equity": 100_000.0,
    "random_entry_iterations": 1000,
    "random_seed": 20260827,
}
PASS_BAR: dict[str, Any] = {
    "pooled_primary_sharpe_min": 0.50,
    "pooled_primary_max_drawdown_max": 0.20,
    "2022_primary_return_min": 0.00,
    "positive_annual_windows_min": 3,
    "primary_must_beat_commodity_alone": True,
}
HYPOTHESIS = (
    "A monthly positive-momentum commodity ETF basket, sized by inverse "
    "volatility and combined with positive-surprise earnings rotation, will "
    "produce a risk-adjusted improvement over the commodity-alone control "
    "without exceeding the locked drawdown and stop assumptions."
)


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Series:
    symbol: str
    bars: list[Bar]

    def __post_init__(self) -> None:
        self.by_date = {bar.day: bar for bar in self.bars}
        self.days = [bar.day for bar in self.bars]


def _unix_midnight(day: date) -> int:
    from datetime import datetime, timezone

    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def _json_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={"User-Agent": "Bot2-Commodity-Research/1.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_yahoo_series(symbol: str, start: date = START_DATE) -> Series:
    payload = _json_get(
        f"{YAHOO_CHART_URL}/{symbol}",
        {
            "period1": _unix_midnight(start),
            "period2": _unix_midnight(END_DATE + timedelta(days=1)),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "false",
        },
    )
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo {symbol}: {chart['error']}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo {symbol}: empty response")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    fields = {name: quote.get(name) or [] for name in ("open", "high", "low", "close", "volume")}
    bars: list[Bar] = []
    from datetime import datetime, timezone

    for index, timestamp in enumerate(timestamps):
        day = datetime.fromtimestamp(timestamp, timezone.utc).date()
        values = {
            name: fields[name][index] if index < len(fields[name]) else None
            for name in fields
        }
        if day < start or day > END_DATE:
            continue
        if any(value is None for value in values.values()):
            continue
        bars.append(
            Bar(
                day=day,
                open=float(values["open"]),
                high=float(values["high"]),
                low=float(values["low"]),
                close=float(values["close"]),
                volume=float(values["volume"]),
            )
        )
    if not bars:
        raise RuntimeError(f"Yahoo {symbol}: no complete bars returned")
    return Series(symbol, sorted(bars, key=lambda bar: bar.day))


def _load_db_series(symbols: Iterable[str]) -> dict[str, Series]:
    wanted = tuple(symbols)
    output: dict[str, Series] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, date, open, high, low, close, volume
                FROM {PRICES_TABLE}
                WHERE source='yahoo' AND symbol = ANY(%s)
                ORDER BY symbol, date
                """,
                (list(wanted),),
            )
            grouped: dict[str, list[Bar]] = defaultdict(list)
            for symbol, day, opn, high, low, close, volume in cur.fetchall():
                grouped[symbol].append(
                    Bar(day, float(opn), float(high), float(low), float(close), float(volume))
                )
    for symbol in wanted:
        output[symbol] = Series(symbol, grouped.get(symbol, []))
    return output


def _load_earnings() -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, reported_date, surprise, report_time
                FROM {EARNINGS_TABLE}
                WHERE reported_date >= %s
                ORDER BY reported_date, symbol
                """,
                (START_DATE,),
            )
            return [
                {
                    "symbol": row[0],
                    "reported_date": row[1],
                    "surprise": float(row[2]) if row[2] is not None else None,
                    "report_time": (row[3] or "").strip().lower(),
                }
                for row in cur.fetchall()
            ]


def print_database_boundary() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            database, user = cur.fetchone()
            cur.execute(
                f"""
                SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date)
                FROM {PRICES_TABLE}
                WHERE asset_type='commodity_etf'
                """
            )
            commodity_count, commodity_symbols, first_day, last_day = cur.fetchone()
            cur.execute(f"SELECT COUNT(*) FROM {PRICES_TABLE}")
            all_count = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM {EARNINGS_TABLE}")
            earnings_count = cur.fetchone()[0]
    print(
        f"database_boundary | database={database} | user={user} | "
        f"table={PRICES_TABLE} | rows={all_count} | earnings_rows={earnings_count}"
    )
    print(
        f"commodity_dataset | symbols={commodity_symbols} | rows={commodity_count} | "
        f"first_date={first_day} | last_date={last_day}"
    )


def print_alpaca_availability() -> None:
    """Read asset metadata only; this function has no order API path."""
    print("alpaca_availability | symbol | tradable | fractionable | shortable | exchange | asset_class")
    try:
        from alpaca.trading.client import TradingClient
        from config.settings import settings

        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise RuntimeError("Alpaca credentials are not configured")
        client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,
        )
        for symbol in COMMODITY_ETFS:
            asset = client.get_asset(symbol)
            asset_class = getattr(asset, "asset_class", "")
            asset_class = getattr(asset_class, "value", asset_class)
            exchange = getattr(asset, "exchange", "")
            exchange = getattr(exchange, "value", exchange)
            print(
                f"{symbol} | {bool(getattr(asset, 'tradable', False))} | "
                f"{bool(getattr(asset, 'fractionable', False))} | "
                f"{bool(getattr(asset, 'shortable', False))} | "
                f"{exchange} | {asset_class}"
            )
    except Exception as exc:
        print(f"alpaca_availability_error | {type(exc).__name__}: {exc}")
        for symbol in COMMODITY_ETFS:
            print(f"{symbol} | unavailable | unavailable | unavailable | unavailable | unavailable")


def commodity_integrity_gate(series: dict[str, Series]) -> bool:
    valid = True
    print("commodity_integrity | symbol | rows | first_date | last_date | expected_days | null_count | unexplained_gaps")
    for symbol in COMMODITY_ETFS:
        bars = series.get(symbol, Series(symbol, [])).bars
        days = [bar.day for bar in bars]
        expected = _expected_trading_days(days[0], days[-1]) if days else set()
        missing = sorted(expected - set(days))
        null_count = sum(
            1
            for bar in bars
            if any(value is None for value in (bar.open, bar.high, bar.low, bar.close, bar.volume))
        )
        inception_warning = ""
        if not days or days[0] > START_DATE:
            inception_warning = " | WARNING=inception_after_2021-01-01"
        print(
            f"{symbol} | {len(bars)} | {days[0] if days else None} | "
            f"{days[-1] if days else None} | {len(expected)} | {null_count} | "
            f"{len(missing)}{inception_warning}"
        )
        if missing:
            print(f"  unexplained_gaps={','.join(map(str, missing[:20]))}")
        if (
            not days
            or days[0] != date(2021, 1, 4)
            or null_count
            or missing
            or len(days) != len(set(days))
        ):
            valid = False
    print(
        "holiday_handling | NYSE holidays excluded from expected sessions; "
        f"gate={'PASS' if valid else 'STOP'}"
    )
    print(f"commodity_integrity_gate | {'PASS' if valid else 'STOP'}")
    return valid


def _returns(series: Series) -> list[float]:
    return [
        bar.close / previous.close - 1
        for previous, bar in zip(series.bars, series.bars[1:])
        if previous.close > 0
    ]


def _correlation(left: list[float], right: list[float]) -> float | None:
    n = min(len(left), len(right))
    if n < 3:
        return None
    left, right = left[:n], right[:n]
    mean_left, mean_right = statistics.mean(left), statistics.mean(right)
    denom_left = math.sqrt(sum((value - mean_left) ** 2 for value in left))
    denom_right = math.sqrt(sum((value - mean_right) ** 2 for value in right))
    if denom_left == 0 or denom_right == 0:
        return None
    return sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right)
    ) / (denom_left * denom_right)


def print_liquidity_roll_and_correlation(series: dict[str, Series]) -> None:
    print("liquidity | symbol | median_dollar_volume | zero_volume_days | annualized_volatility")
    for symbol in COMMODITY_ETFS:
        bars = series[symbol].bars
        dollar_volume = [bar.close * bar.volume for bar in bars]
        returns = _returns(series[symbol])
        volatility = statistics.pstdev(returns) * math.sqrt(252) if returns else 0.0
        print(
            f"{symbol} | {statistics.median(dollar_volume):.2f} | "
            f"{sum(1 for bar in bars if bar.volume == 0)} | {volatility:.4f}"
        )

    print(
        "roll_decay_proxy | price-only ETF proxy; futures roll yield is not "
        "observable from this OHLCV table"
    )
    print("roll_decay_proxy | symbol | annualized_price_return | max_drawdown")
    for symbol in COMMODITY_ETFS:
        bars = series[symbol].bars
        total = bars[-1].close / bars[0].close if bars and bars[0].close else 0.0
        years = max((bars[-1].day - bars[0].day).days / 365.25, 1 / 365.25) if bars else 1
        annualized = total ** (1 / years) - 1 if total > 0 else -1.0
        peak = bars[0].close if bars else 0.0
        max_dd = 0.0
        for bar in bars:
            peak = max(peak, bar.close)
            max_dd = max(max_dd, (peak - bar.close) / peak if peak else 0.0)
        print(f"{symbol} | {annualized:.4f} | {max_dd:.4f}")

    daily = {symbol: _returns(series[symbol]) for symbol in COMMODITY_ETFS}
    print("commodity_correlation | pair | correlation")
    for index, left_symbol in enumerate(COMMODITY_ETFS):
        for right_symbol in COMMODITY_ETFS[index + 1:]:
            correlation = _correlation(daily[left_symbol], daily[right_symbol])
            print(f"{left_symbol}/{right_symbol} | {correlation:.4f}" if correlation is not None else f"{left_symbol}/{right_symbol} | None")


def print_overlap_analysis(series: dict[str, Series]) -> dict[str, Series]:
    overlap: dict[str, Series] = {}
    print("overlap_data | symbol | source | rows | first_date | last_date")
    for symbol in OVERLAP_SYMBOLS:
        try:
            overlap[symbol] = _fetch_yahoo_series(symbol)
            data = overlap[symbol]
            print(f"{symbol} | yahoo | {len(data.bars)} | {data.days[0]} | {data.days[-1]}")
        except Exception as exc:
            print(f"{symbol} | yahoo | ERROR={type(exc).__name__}: {exc}")
    print("overlap_correlation | commodity | comparison | correlation")
    for commodity in COMMODITY_ETFS:
        commodity_returns = {bar.day: value for bar, value in zip(series[commodity].bars[1:], _returns(series[commodity]))}
        for comparison, comparison_series in overlap.items():
            comparison_returns = {bar.day: value for bar, value in zip(comparison_series.bars[1:], _returns(comparison_series))}
            common = sorted(set(commodity_returns) & set(comparison_returns))
            corr = _correlation(
                [commodity_returns[day] for day in common],
                [comparison_returns[day] for day in common],
            )
            print(
                f"{commodity} | {comparison} | {corr:.4f}"
                if corr is not None
                else f"{commodity} | {comparison} | None"
            )
    return overlap


def finalize_universe(series: dict[str, Series]) -> tuple[str, ...]:
    final = tuple(
        symbol for symbol in COMMODITY_ETFS
        if len(series.get(symbol, Series(symbol, [])).bars) > 0
    )
    excluded = tuple(symbol for symbol in COMMODITY_ETFS if symbol not in final)
    print(f"universe_finalized | included={','.join(final)}")
    print(f"universe_excluded | excluded={','.join(excluded) if excluded else 'NONE'}")
    print("universe_gate | PASS" if len(final) == len(COMMODITY_ETFS) else "universe_gate | STOP")
    return final


def _find_uncompleted_experiment() -> int | None:
    """Return the latest matching uncompleted run so a crashed run is resumable."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT experiment_id
                FROM research_ledger
                WHERE strategy_family = 'bot2_commodity_earnings_research'
                  AND bot_id = 'bot2_spy_qqq'
                  AND results IS NULL
                ORDER BY experiment_id DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    return int(row[0]) if row else None


def _bounded_weights(raw: dict[str, float], floor: float, cap: float, total: float) -> dict[str, float]:
    if not raw:
        return {}
    target_total = min(total, cap * len(raw))
    weights = {symbol: target_total * value / sum(raw.values()) for symbol, value in raw.items()}
    unfixed = set(weights)
    while unfixed:
        changed = False
        for symbol in tuple(unfixed):
            if weights[symbol] < floor:
                weights[symbol] = floor
                unfixed.remove(symbol)
                changed = True
            elif weights[symbol] > cap:
                weights[symbol] = cap
                unfixed.remove(symbol)
                changed = True
        if not changed:
            break
        remaining = target_total - sum(weights[symbol] for symbol in weights if symbol not in unfixed)
        raw_remaining = sum(raw[symbol] for symbol in unfixed)
        if unfixed and raw_remaining > 0:
            for symbol in unfixed:
                weights[symbol] = remaining * raw[symbol] / raw_remaining
    return weights


def _first_session_each_month(days: list[date]) -> set[date]:
    output: set[date] = set()
    seen: set[tuple[int, int]] = set()
    for day in days:
        key = (day.year, day.month)
        if key not in seen:
            output.add(day)
            seen.add(key)
    return output


def _metrics(equity_curve: list[float], trades: int, turnover: float, stops: int = 0) -> dict[str, Any]:
    if not equity_curve:
        return {
            "return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "trades": 0,
            "turnover": 0.0, "stops": 0, "daily_returns": [],
        }
    returns = [
        equity_curve[index] / equity_curve[index - 1] - 1
        for index in range(1, len(equity_curve))
        if equity_curve[index - 1] > 0
    ]
    mean = statistics.mean(returns) if returns else 0.0
    stdev = statistics.stdev(returns) if len(returns) > 1 else 0.0
    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak if peak else 0.0)
    return {
        "return": equity_curve[-1] / equity_curve[0] - 1 if equity_curve[0] else 0.0,
        "max_drawdown": max_drawdown,
        "sharpe": mean / stdev * math.sqrt(252) if stdev else 0.0,
        "trades": trades,
        "turnover": turnover / equity_curve[0] if equity_curve[0] else 0.0,
        "stops": stops,
        "daily_returns": returns,
    }


def _momentum_weights(
    series: dict[str, Series],
    signal_day: date,
    lookback_months: int,
) -> dict[str, float]:
    raw: dict[str, float] = {}
    lookback = lookback_months * 21
    for symbol in COMMODITY_ETFS:
        bars = [bar for bar in series[symbol].bars if bar.day < signal_day]
        if len(bars) < max(lookback + 1, 64):
            continue
        momentum = bars[-1].close / bars[-lookback - 1].close - 1
        returns = _returns(Series(symbol, bars[-64:]))
        volatility = statistics.pstdev(returns) * math.sqrt(252) if returns else 0.0
        if momentum > 0 and volatility > 0:
            raw[symbol] = 1 / volatility
    return _bounded_weights(
        raw,
        float(LOCKED_PARAMETERS["allocation_floor"]),
        float(LOCKED_PARAMETERS["allocation_cap"]),
        float(LOCKED_PARAMETERS["commodity_max_deployment"]),
    )


def simulate_commodity(
    series: dict[str, Series],
    lookback_months: int,
    window_start: date,
    window_end: date,
    stops_enabled: bool = True,
) -> dict[str, Any]:
    common_days = sorted(set.intersection(*(set(series[symbol].days) for symbol in COMMODITY_ETFS)))
    rebalance_days = _first_session_each_month(common_days)
    slippage = float(LOCKED_PARAMETERS["slippage_each_leg_bps"]) / 10_000
    stop_loss = float(LOCKED_PARAMETERS["stop_loss"])
    cash = float(LOCKED_PARAMETERS["starting_equity"])
    holdings: dict[str, dict[str, float]] = {}
    curve: list[float] = []
    turnover = 0.0
    trades = 0
    stops = 0
    for day in common_days:
        bars = {symbol: series[symbol].by_date[day] for symbol in COMMODITY_ETFS}
        if day in rebalance_days:
            equity_open = cash + sum(
                holding["qty"] * bars[symbol].open for symbol, holding in holdings.items()
            )
            for symbol, holding in list(holdings.items()):
                exit_value = holding["qty"] * bars[symbol].open * (1 - slippage)
                cash += exit_value
                turnover += exit_value
                del holdings[symbol]
            targets = _momentum_weights(series, day, lookback_months)
            for symbol, weight in targets.items():
                entry_price = bars[symbol].open * (1 + slippage)
                notional = min(equity_open * weight, cash)
                if notional <= 0:
                    continue
                qty = notional / entry_price
                cash -= notional
                turnover += notional
                trades += 1
                holdings[symbol] = {
                    "qty": qty,
                    "stop": entry_price * (1 - stop_loss),
                }
        for symbol, holding in list(holdings.items()):
            bar = bars[symbol]
            if stops_enabled and bar.low <= holding["stop"]:
                stop_price = min(bar.open, holding["stop"])
                exit_value = holding["qty"] * stop_price * (1 - slippage)
                cash += exit_value
                turnover += exit_value
                stops += 1
                del holdings[symbol]
        equity_close = cash + sum(
            holding["qty"] * bars[symbol].close for symbol, holding in holdings.items()
        )
        if window_start <= day <= window_end:
            curve.append(equity_close)
        if day >= window_end:
            break
    for symbol, holding in holdings.items():
        bar = series[symbol].by_date.get(window_end)
        if bar is not None:
            exit_value = holding["qty"] * bar.close * (1 - slippage)
            turnover += exit_value
            cash += exit_value
    result = _metrics(curve, trades, turnover, stops)
    result.update({"lookback_months": lookback_months, "stop_enabled": stops_enabled})
    return result


def _event_schedule(
    earnings: list[dict[str, Any]],
    stock_series: dict[str, Series],
    exit_variant: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in earnings:
        symbol = event["symbol"]
        if event["surprise"] is None or event["surprise"] <= 0 or symbol not in stock_series:
            continue
        days = stock_series[symbol].days
        report_day = event["reported_date"]
        report_time = event["report_time"]
        if "post" in report_time or "after" in report_time:
            entry_candidates = [day for day in days if day > report_day]
        elif "pre" in report_time or "before" in report_time:
            entry_candidates = [day for day in days if day >= report_day]
        else:
            continue
        if not entry_candidates:
            continue
        entry_day = entry_candidates[0]
        entry_index = days.index(entry_day)
        if exit_variant == "close":
            exit_day = entry_day
        else:
            if entry_index + 1 >= len(days):
                continue
            exit_day = days[entry_index + 1]
        events.append(
            {
                "symbol": symbol,
                "entry_day": entry_day,
                "exit_day": exit_day,
                "surprise": event["surprise"],
            }
        )
    return events


def simulate_earnings(
    earnings: list[dict[str, Any]],
    stock_series: dict[str, Series],
    window_start: date,
    window_end: date,
    exit_variant: str,
) -> tuple[dict[str, Any], list[float]]:
    events = [
        event for event in _event_schedule(earnings, stock_series, exit_variant)
        if window_start <= event["entry_day"] <= window_end
    ]
    slippage = float(LOCKED_PARAMETERS["slippage_each_leg_bps"]) / 10_000
    stop_loss = float(LOCKED_PARAMETERS["stop_loss"])
    cap = float(LOCKED_PARAMETERS["earnings_allocation_cap"])
    cash = float(LOCKED_PARAMETERS["starting_equity"])
    positions: list[dict[str, Any]] = []
    curve: list[float] = []
    turnover = 0.0
    trades = 0
    stops = 0
    returns_by_trade: list[float] = []
    days = sorted(
        set(day for series in stock_series.values() for day in series.days)
    )
    events_by_entry: dict[date, list[dict[str, Any]]] = defaultdict(list)
    events_by_exit: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_entry[event["entry_day"]].append(event)
        events_by_exit[event["exit_day"]].append(event)

    for day in days:
        if day < window_start or day > window_end:
            continue
        # Scheduled open exits happen before new open entries.
        for position in list(positions):
            if position["exit_day"] == day and exit_variant == "open":
                bar = stock_series[position["symbol"]].by_date[day]
                raw_exit = min(bar.open, position["stop"]) if bar.open <= position["stop"] else bar.open
                exit_price = raw_exit * (1 - slippage)
                value = position["qty"] * exit_price
                cash += value
                turnover += value
                trades += 1
                returns_by_trade.append(exit_price / position["entry_price"] - 1)
                positions.remove(position)
        entries = events_by_entry.get(day, [])
        for event in entries:
            if not entries:
                continue
            allocation = min(cap / len(entries), max(0.0, cap - sum(p["allocation"] for p in positions)))
            bar = stock_series[event["symbol"]].by_date[day]
            entry_price = bar.open * (1 + slippage)
            equity_open = cash + sum(
                p["qty"] * stock_series[p["symbol"]].by_date[day].open for p in positions
            )
            notional = min(equity_open * allocation, cash)
            if notional <= 0:
                continue
            cash -= notional
            turnover += notional
            positions.append(
                {
                    "symbol": event["symbol"],
                    "entry_day": day,
                    "exit_day": event["exit_day"],
                    "entry_price": entry_price,
                    "qty": notional / entry_price,
                    "stop": entry_price * (1 - stop_loss),
                    "allocation": allocation,
                }
            )
        for position in list(positions):
            bar = stock_series[position["symbol"]].by_date.get(day)
            if bar is None or bar.low > position["stop"]:
                continue
            stop_price = min(bar.open, position["stop"])
            exit_price = stop_price * (1 - slippage)
            value = position["qty"] * exit_price
            cash += value
            turnover += value
            stops += 1
            trades += 1
            returns_by_trade.append(exit_price / position["entry_price"] - 1)
            positions.remove(position)
        if exit_variant == "close":
            for position in list(positions):
                if position["exit_day"] != day:
                    continue
                bar = stock_series[position["symbol"]].by_date[day]
                exit_price = bar.close * (1 - slippage)
                value = position["qty"] * exit_price
                cash += value
                turnover += value
                trades += 1
                returns_by_trade.append(exit_price / position["entry_price"] - 1)
                positions.remove(position)
        equity_close = cash + sum(
            p["qty"] * stock_series[p["symbol"]].by_date[day].close for p in positions
        )
        curve.append(equity_close)
    for position in positions:
        bar = stock_series[position["symbol"]].by_date.get(window_end)
        if bar is not None:
            cash += position["qty"] * bar.close * (1 - slippage)
            turnover += position["qty"] * bar.close
    result = _metrics(curve, trades, turnover, stops)
    result.update({"exit_variant": exit_variant, "events": len(events)})
    return result, returns_by_trade


def _random_entry_distribution(
    earnings: list[dict[str, Any]],
    stock_series: dict[str, Series],
    window_start: date,
    window_end: date,
    exit_variant: str,
    iterations: int = 1000,
) -> dict[str, Any]:
    candidates = [
        event for event in _event_schedule(
            [dict(event, surprise=1.0) for event in earnings],
            stock_series,
            exit_variant,
        )
        if window_start <= event["entry_day"] <= window_end
    ]
    if not candidates:
        return {"iterations": iterations, "candidate_trades": 0, "mean": 0.0, "p05": 0.0, "p95": 0.0}
    slippage = float(LOCKED_PARAMETERS["slippage_each_leg_bps"]) / 10_000
    stop_loss = float(LOCKED_PARAMETERS["stop_loss"])
    candidate_returns: list[float] = []
    for event in candidates:
        bar = stock_series[event["symbol"]].by_date[event["entry_day"]]
        exit_bar = stock_series[event["symbol"]].by_date[event["exit_day"]]
        entry = bar.open * (1 + slippage)
        stop = entry * (1 - stop_loss)
        if bar.low <= stop:
            exit_price = min(bar.open, stop) * (1 - slippage)
        elif exit_variant == "close":
            exit_price = exit_bar.close * (1 - slippage)
        else:
            exit_price = exit_bar.open * (1 - slippage)
        candidate_returns.append(exit_price / entry - 1)
    seed = int(LOCKED_PARAMETERS["random_seed"]) + sum(ord(c) for c in f"{window_start}{window_end}{exit_variant}")
    rng = random.Random(seed)
    signal_events = [
        event for event in _event_schedule(earnings, stock_series, exit_variant)
        if window_start <= event["entry_day"] <= window_end
    ]
    sample_size = max(1, len(signal_events))
    outcomes = [
        math.prod(1 + rng.choice(candidate_returns) * 0.20 / sample_size for _ in range(sample_size)) - 1
        for _ in range(iterations)
    ]
    outcomes.sort()
    return {
        "iterations": iterations,
        "candidate_trades": len(candidate_returns),
        "mean": statistics.mean(outcomes),
        "p05": outcomes[max(0, int(iterations * 0.05) - 1)],
        "p95": outcomes[min(iterations - 1, int(iterations * 0.95))],
    }


def _buy_hold(series: Series, window_start: date, window_end: date) -> dict[str, Any]:
    bars = [bar for bar in series.bars if window_start <= bar.day <= window_end]
    if len(bars) < 2:
        return _metrics([], 0, 0.0)
    slippage = float(LOCKED_PARAMETERS["slippage_each_leg_bps"]) / 10_000
    start = bars[0].open * (1 + slippage)
    equity = [bar.close / start * (1 - slippage) * 100_000 for bar in bars]
    return _metrics(equity, 1, 200_000 * slippage)


def _combine_curves(left: dict[str, Any], right: dict[str, Any], left_weight: float, right_weight: float) -> dict[str, Any]:
    left_returns, right_returns = left["daily_returns"], right["daily_returns"]
    n = min(len(left_returns), len(right_returns))
    curve = [100_000.0]
    for index in range(n):
        curve.append(curve[-1] * (1 + left_weight * left_returns[index] + right_weight * right_returns[index]))
    result = _metrics(curve, left["trades"] + right["trades"], left["turnover"] + right["turnover"], left["stops"] + right["stops"])
    return result


def run_backtests(
    series: dict[str, Series],
    overlap: dict[str, Series],
    earnings: list[dict[str, Any]],
    final_universe: tuple[str, ...],
) -> dict[str, Any]:
    # This function is called only after register_experiment() succeeds.
    results: dict[str, Any] = {"windows": {}, "controls": {}, "random_entry": {}}
    primary_by_window: dict[str, dict[str, Any]] = {}
    print("backtest_results | lookback | window | exit_variant | return | max_drawdown | sharpe | trades | turnover | stops")
    stock_series = _load_db_series(STOCKS)
    for lookback in (12, 6, 3):
        for label, start, end in WINDOWS:
            commodity = simulate_commodity(series, lookback, start, end, True)
            for exit_variant in ("close", "open"):
                earnings_result, _ = simulate_earnings(
                    earnings, stock_series, start, end, exit_variant
                )
                combined = _combine_curves(commodity, earnings_result, 0.80, 0.20)
                print(
                    f"{lookback} | {label} | {exit_variant} | "
                    f"{combined['return']:.4f} | {combined['max_drawdown']:.4f} | "
                    f"{combined['sharpe']:.4f} | {combined['trades']} | "
                    f"{combined['turnover']:.4f} | {combined['stops']}"
                )
                results["windows"][f"{lookback}:{label}:{exit_variant}"] = combined
                if lookback == 12:
                    primary_by_window[f"{label}:{exit_variant}"] = combined

            if lookback == 12:
                commodity_alone = simulate_commodity(series, 12, start, end, True)
                commodity_no_stop = simulate_commodity(series, 12, start, end, False)
                earnings_close, _ = simulate_earnings(earnings, stock_series, start, end, "close")
                spy = _buy_hold(overlap["SPY"], start, end) if "SPY" in overlap else _metrics([], 0, 0)
                controls = {
                    "commodity_alone": commodity_alone,
                    "earnings_alone": earnings_close,
                    "spy_buy_hold": spy,
                    "commodity_no_stop": commodity_no_stop,
                }
                results["controls"][label] = controls
                random_result = _random_entry_distribution(
                    earnings, stock_series, start, end, "close", 1000
                )
                results["random_entry"][label] = random_result
                print(
                    f"control | {label} | commodity_alone | {commodity_alone['return']:.4f} | "
                    f"dd={commodity_alone['max_drawdown']:.4f} | sharpe={commodity_alone['sharpe']:.4f}"
                )
                print(
                    f"control | {label} | earnings_alone | {earnings_close['return']:.4f} | "
                    f"dd={earnings_close['max_drawdown']:.4f} | sharpe={earnings_close['sharpe']:.4f}"
                )
                print(
                    f"control | {label} | SPY_buy_hold | {spy['return']:.4f} | "
                    f"dd={spy['max_drawdown']:.4f} | sharpe={spy['sharpe']:.4f}"
                )
                print(
                    f"control | {label} | commodity_no_stop | {commodity_no_stop['return']:.4f} | "
                    f"dd={commodity_no_stop['max_drawdown']:.4f} | sharpe={commodity_no_stop['sharpe']:.4f}"
                )
                print(
                    f"control | {label} | random_entry_1000 | mean={random_result['mean']:.4f} | "
                    f"p05={random_result['p05']:.4f} | p95={random_result['p95']:.4f}"
                )
    pooled: list[float] = []
    for key, result in results["windows"].items():
        if key.startswith("12:") and key.endswith(":close"):
            pooled.extend(result["daily_returns"])
    pooled_curve = [100_000.0]
    for value in pooled:
        pooled_curve.append(pooled_curve[-1] * (1 + value))
    pooled_metrics = _metrics(
        pooled_curve,
        sum(
            result["trades"]
            for key, result in results["windows"].items()
            if key.startswith("12:") and key.endswith(":close")
        ),
        sum(
            result["turnover"]
            for key, result in results["windows"].items()
            if key.startswith("12:") and key.endswith(":close")
        ),
    )
    results["pooled_primary"] = pooled_metrics
    print(
        f"pooled_primary | return={pooled_metrics['return']:.4f} | "
        f"max_drawdown={pooled_metrics['max_drawdown']:.4f} | sharpe={pooled_metrics['sharpe']:.4f}"
    )
    return results


def evaluate_pass_bar(results: dict[str, Any]) -> dict[str, Any]:
    pooled = results["pooled_primary"]
    annual = [
        results["windows"][f"12:{label}:close"]["return"]
        for label, _, _ in WINDOWS
    ]
    controls_2022 = results["controls"]["2022"]["commodity_alone"]
    combined_2022 = results["windows"]["12:2022:close"]
    checks = {
        "pooled_sharpe": pooled["sharpe"] >= PASS_BAR["pooled_primary_sharpe_min"],
        "pooled_max_drawdown": pooled["max_drawdown"] <= PASS_BAR["pooled_primary_max_drawdown_max"],
        "2022_return": combined_2022["return"] >= PASS_BAR["2022_primary_return_min"],
        "positive_annual_windows": sum(value > 0 for value in annual) >= PASS_BAR["positive_annual_windows_min"],
        "beats_commodity_alone_2022": combined_2022["return"] > controls_2022["return"],
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    print(
        f"pass_bar | pooled_sharpe={pooled['sharpe']:.4f} >= {PASS_BAR['pooled_primary_sharpe_min']:.2f} "
        f"| pooled_max_drawdown={pooled['max_drawdown']:.4f} <= {PASS_BAR['pooled_primary_max_drawdown_max']:.2f} "
        f"| 2022_return={combined_2022['return']:.4f} >= {PASS_BAR['2022_primary_return_min']:.2f} "
        f"| positive_windows={sum(value > 0 for value in annual)} >= {PASS_BAR['positive_annual_windows_min']} "
        f"| 2022_beats_commodity_alone={checks['beats_commodity_alone_2022']} | {status}"
    )
    print(
        f"2022_prominent | combined_return={combined_2022['return']:.4f} | "
        f"commodity_alone_return={controls_2022['return']:.4f} | "
        f"commodity_alone_sharpe={controls_2022['sharpe']:.4f}"
    )
    return {"status": status, "checks": checks}


def verification_output() -> None:
    print(
        "verification | execution_mode=read_only | orders_placed=0 | "
        "order_api_calls=0 | live_strategy_module=0 | kill_switch_armed=0 | "
        "bot1_touched=0 | bot3_touched=0 | vault_touched=0 | monitoring_touched=0 | "
        "published=0"
    )
    try:
        from core.runner_lock import list_locks

        locks = list_locks()
        published = [lock for lock in locks if lock["environment"] == "published"]
        print(f"published_runner_locks | count={len(published)} | status=read_only_observed")
    except Exception as exc:
        print(f"published_runner_locks | status=unavailable | reason={type(exc).__name__}")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*), COUNT(*) FILTER (WHERE stop_order_id IS NOT NULL)
                    FROM (
                        SELECT stop_order_id
                        FROM alpaca_etf_positions
                        WHERE status='open'
                        UNION ALL
                        SELECT stop_order_id
                        FROM bot3_positions
                        WHERE status='open'
                    ) AS open_strategy_positions
                    """
                )
                total, covered = cur.fetchone()
        print(f"strategy_stop_coverage | covered={covered}/{total} | status={'PASS' if total == covered else 'FAIL'}")
    except Exception as exc:
        print(f"strategy_stop_coverage | status=unavailable | reason={type(exc).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-ingest", action="store_true", help="Use existing commodity rows only")
    args = parser.parse_args()
    print("=" * 100)
    print("BOT 2 COMMODITY RESEARCH | DEV-ONLY | READ-ONLY EXECUTION")
    print("=" * 100)
    ensure_tables()
    print_database_boundary()
    print_alpaca_availability()
    if not args.skip_ingest:
        from analysis.bot2_data_pipeline import ingest_commodity_prices

        ingest_commodity_prices()
    series = _load_db_series(COMMODITY_ETFS)
    if not commodity_integrity_gate(series):
        print("STOP: Part A integrity gate failed; Part B registration/backtest skipped.")
        verification_output()
        return 2
    print_liquidity_roll_and_correlation(series)
    overlap = print_overlap_analysis(series)
    final_universe = finalize_universe(series)
    if final_universe != COMMODITY_ETFS:
        print("STOP: final universe is incomplete; Part B registration/backtest skipped.")
        verification_output()
        return 3

    print("locked_configuration | " + json.dumps({
        "hypothesis": HYPOTHESIS,
        "parameters": LOCKED_PARAMETERS,
        "pass_bar": PASS_BAR,
        "data_window": {"start": str(START_DATE), "end": str(END_DATE), "windows": [label for label, _, _ in WINDOWS]},
        "variations_tested": 1,
    }, sort_keys=True))
    ensure_research_tables()
    experiment_id = _find_uncompleted_experiment()
    if experiment_id is not None:
        print(f"experiment_registration | experiment_id={experiment_id} | status=resume_uncompleted")
    else:
        experiment_id = register_experiment(
            strategy_family="bot2_commodity_earnings_research",
            bot_id="bot2_spy_qqq",
            hypothesis=HYPOTHESIS,
            parameters=LOCKED_PARAMETERS,
            pass_bar=PASS_BAR,
            data_window={
                "start": str(START_DATE),
                "end": str(END_DATE),
                "windows": [label for label, _, _ in WINDOWS],
                "price_source": "Yahoo Finance daily OHLCV",
                "earnings_source": "existing bot2_earnings_dates",
            },
            variations_tested=1,
            went_live=False,
            notes="Development-only research; no live strategy or broker orders.",
        )
        print(f"experiment_registered | experiment_id={experiment_id} | variations_tested=1")
    results = run_backtests(series, overlap, _load_earnings(), final_universe)
    evaluation = evaluate_pass_bar(results)
    results["evaluation"] = evaluation
    record_results(experiment_id, results, evaluation["status"])
    print(f"results_recorded | experiment_id={experiment_id} | outcome={evaluation['status']}")
    verification_output()
    return 0 if evaluation["status"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())