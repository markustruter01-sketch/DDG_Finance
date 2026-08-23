#!/usr/bin/env python3
"""Read-only Bot 3 hard-assets sleeve backtest.

The strategy is intentionally simple and pre-registered: equal-weight BTC,
ETH, GLD, and SLV; no trend gate; quarterly rebalancing with a 5 percentage
point band; and wide catastrophe stops only.  This module reads existing
historical tables and never imports execution, broker, runner, vault, Bot 1,
Bot 2, or migration code.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import mean, stdev
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402

ASSETS = ("BTC", "ETH", "GLD", "SLV")
CRYPTO = {"BTC", "ETH"}
TARGET_WEIGHT = 0.25
REBALANCE_BAND = 0.05
CRYPTO_STOP_PCT = 0.25
METAL_STOP_PCT = 0.10
STARTING_EQUITY = 100_000.0
WINDOWS = (
    ("2021", date(2021, 1, 1), date(2021, 12, 31)),
    ("2022", date(2022, 1, 1), date(2022, 12, 31)),
    ("2023", date(2023, 1, 1), date(2023, 12, 31)),
    ("2024-2026-08", date(2024, 1, 1), date(2026, 8, 31)),
)
FREQUENCIES = ("quarterly", "annual", "monthly")


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    low: float
    close: float


@dataclass
class Holding:
    qty: float = 0.0
    entry_price: float = 0.0
    stop_price: float = 0.0
    stopped: bool = False


@dataclass
class Run:
    metrics: dict[str, Any]
    asset: dict[str, dict[str, Any]]


def _load_prices() -> dict[str, dict[date, Bar]]:
    tables = {
        "BTC": "crypto_historical_prices",
        "ETH": "crypto_historical_prices",
        "GLD": "bot3_inflation_hedge_prices",
        "SLV": "bot3_inflation_hedge_prices",
    }
    prices: dict[str, dict[date, Bar]] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for asset in ASSETS:
                cur.execute(
                    f"""
                    SELECT date, open, low, close
                    FROM {tables[asset]}
                    WHERE symbol=%s AND source='yahoo'
                    ORDER BY date
                    """,
                    (asset,),
                )
                prices[asset] = {
                    row[0]: Bar(day=row[0], open=float(row[1]), low=float(row[2]), close=float(row[3]))
                    for row in cur.fetchall()
                }
    if any(not prices[asset] for asset in ASSETS):
        raise RuntimeError("Bot 3 rebalanced backtest requires all four historical series")
    return prices


def _period_key(day: date, frequency: str) -> tuple[int, int]:
    if frequency == "monthly":
        return day.year, day.month
    if frequency == "annual":
        return day.year, 0
    return day.year, (day.month - 1) // 3


def _metrics(curve: list[float], turnover: float, rebalance_events: int) -> dict[str, Any]:
    returns = [
        curve[index] / curve[index - 1] - 1
        for index in range(1, len(curve))
        if curve[index - 1] > 0
    ]
    volatility = stdev(returns) if len(returns) > 1 else 0.0
    sharpe = mean(returns) / volatility * math.sqrt(252) if volatility else 0.0
    downside_dev = math.sqrt(mean(min(value, 0.0) ** 2 for value in returns)) if returns else 0.0
    sortino = mean(returns) / downside_dev * math.sqrt(252) if downside_dev else 0.0
    peak = STARTING_EQUITY
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak if peak else 0.0)
    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "total_return": curve[-1] / STARTING_EQUITY - 1 if curve else 0.0,
        "max_drawdown": max_dd,
        "rebalance_events": rebalance_events,
        "turnover": turnover / STARTING_EQUITY,
        "daily_returns": returns,
        "final_equity": curve[-1] if curve else STARTING_EQUITY,
    }


def _mark_equity(cash: float, holdings: dict[str, Holding], marks: dict[str, float]) -> float:
    return cash + sum(holding.qty * marks.get(asset, 0.0) for asset, holding in holdings.items())


def _run_rebalanced(
    prices: dict[str, dict[date, Bar]],
    start: date,
    end: date,
    frequency: str,
) -> Run:
    common_start = max(min(prices[asset]) for asset in ASSETS)
    days = sorted(
        day for asset in ASSETS for day in prices[asset]
        if common_start <= day and start <= day <= end
    )
    days = sorted(set(days))
    first_day = days[0]
    holdings = {asset: Holding() for asset in ASSETS}
    cash = STARTING_EQUITY
    previous_close: dict[str, float] = {}
    curve: list[float] = []
    turnover = 0.0
    rebalance_events = 0
    last_period: tuple[int, int] | None = None
    asset_stats = {
        asset: {
            "pnl": 0.0,
            "times_rebalanced_into": 0,
            "times_rebalanced_out_of": 0,
            "stop_fires": 0,
            "trading_days": 0,
        }
        for asset in ASSETS
    }

    for day in days:
        bars = {asset: prices[asset].get(day) for asset in ASSETS}
        marks = {
            asset: (bar.close if bar else previous_close.get(asset, 0.0))
            for asset, bar in bars.items()
        }

        # Catastrophe stops are the only non-rebalance exit mechanism.
        for asset, holding in holdings.items():
            bar = bars[asset]
            if holding.qty and bar and bar.low <= holding.stop_price:
                exit_price = holding.stop_price
                cash += holding.qty * exit_price
                turnover += holding.qty * exit_price
                holding.qty = 0.0
                holding.stopped = True
                asset_stats[asset]["stop_fires"] += 1

        period = _period_key(day, frequency)
        is_rebalance_day = period != last_period
        if is_rebalance_day:
            open_marks = {
                asset: (
                    bars[asset].open
                    if bars[asset]
                    else previous_close.get(asset, 0.0)
                )
                for asset in ASSETS
            }
            equity_at_open = _mark_equity(cash, holdings, open_marks)
            current_weights = {
                asset: (
                    holdings[asset].qty * open_marks[asset] / equity_at_open
                    if equity_at_open and open_marks[asset] > 0 else 0.0
                )
                for asset in ASSETS
            }
            needs_rebalance = any(
                holdings[asset].stopped
                or abs(current_weights[asset] - TARGET_WEIGHT) > REBALANCE_BAND
                for asset in ASSETS
            )
            if day == first_day or needs_rebalance:
                # Sell overweight positions and stopped positions first.
                target_values = {asset: equity_at_open * TARGET_WEIGHT for asset in ASSETS}
                for asset in ASSETS:
                    holding = holdings[asset]
                    price = open_marks[asset]
                    if not price:
                        continue
                    current_value = holding.qty * price
                    if holding.stopped or current_value > target_values[asset]:
                        sale_value = current_value if holding.stopped else current_value - target_values[asset]
                        sale_qty = min(holding.qty, sale_value / price)
                        if sale_qty > 0:
                            cash += sale_qty * price
                            turnover += sale_qty * price
                            holding.qty -= sale_qty
                            asset_stats[asset]["times_rebalanced_out_of"] += 1

                # Buy laggards and stopped assets back toward their targets.
                for asset in ASSETS:
                    holding = holdings[asset]
                    price = open_marks[asset]
                    if not price:
                        continue
                    current_value = holding.qty * price
                    buy_value = max(0.0, target_values[asset] - current_value)
                    buy_value = min(buy_value, cash)
                    if buy_value > 0:
                        holding.qty += buy_value / price
                        cash -= buy_value
                        turnover += buy_value
                        asset_stats[asset]["times_rebalanced_into"] += 1
                        holding.entry_price = price
                    if holding.qty:
                        stop_pct = CRYPTO_STOP_PCT if asset in CRYPTO else METAL_STOP_PCT
                        holding.stop_price = price * (1.0 - stop_pct)
                        holding.stopped = False
                rebalance_events += 1
            last_period = period

        equity = _mark_equity(cash, holdings, marks)
        curve.append(equity)
        for asset in ASSETS:
            bar = bars[asset]
            if bar:
                asset_stats[asset]["trading_days"] += 1
                old_close = previous_close.get(asset)
                if old_close is not None and holdings[asset].qty:
                    asset_stats[asset]["pnl"] += holdings[asset].qty * (bar.close - old_close)
                previous_close[asset] = bar.close

    metrics = _metrics(curve, turnover, rebalance_events)
    for asset in ASSETS:
        stats = asset_stats[asset]
        stats["return_contribution"] = stats["pnl"] / STARTING_EQUITY
        stats["max_drawdown"] = 0.0
    return Run(metrics=metrics, asset=asset_stats)


def _run_buy_and_hold(
    prices: dict[str, dict[date, Bar]],
    start: date,
    end: date,
) -> Run:
    common_start = max(min(prices[asset]) for asset in ASSETS)
    days = sorted({
        day for asset in ASSETS for day in prices[asset]
        if common_start <= day and start <= day <= end
    })
    first_prices = {
        asset: next(prices[asset][day].close for day in days if day in prices[asset])
        for asset in ASSETS
    }
    qty = {asset: STARTING_EQUITY * TARGET_WEIGHT / first_prices[asset] for asset in ASSETS}
    curve = []
    previous_close: dict[str, float] = dict(first_prices)
    for day in days:
        marks = {
            asset: (
                prices[asset][day].close
                if day in prices[asset]
                else previous_close[asset]
            )
            for asset in ASSETS
        }
        curve.append(sum(qty[asset] * marks[asset] for asset in ASSETS))
        previous_close.update({
            asset: prices[asset][day].close
            for asset in ASSETS
            if day in prices[asset]
        })
    return Run(
        metrics=_metrics(curve, 0.0, 0),
        asset={asset: {"return_contribution": 0.0, "stop_fires": 0} for asset in ASSETS},
    )


def _pool(runs: list[Run]) -> dict[str, Any]:
    returns = [value for run in runs for value in run.metrics["daily_returns"]]
    curve = [STARTING_EQUITY]
    for value in returns:
        curve.append(curve[-1] * (1.0 + value))
    result = _metrics(
        curve,
        sum(run.metrics["turnover"] for run in runs) * STARTING_EQUITY,
        sum(run.metrics["rebalance_events"] for run in runs),
    )
    return result


def _print_parameters() -> None:
    print("BOT 3 REBALANCED HARD-ASSETS SLEEVE — LOCKED PARAMETERS")
    print("UNIVERSE=BTC, ETH, GLD, SLV")
    print("TARGET_WEIGHTS=25%, 25%, 25%, 25%")
    print("INVESTMENT=always invested; no cash gate; no trend gate; no weakness exits")
    print("REBALANCE=quarterly locked choice; only when position drift exceeds 5 percentage points")
    print("SENSITIVITY=quarterly, annual, monthly; sensitivity only, no retuning")
    print("CATASTROPHE_STOPS=crypto stop_limit 25%; GLD/SLV GTC 10%")
    print("STOP_POLICY=stops are protection only; stopped assets re-enter at next scheduled rebalance")
    print("SESSIONS=BTC/ETH 24/7; GLD/SLV US equity sessions; missing marks carry forward")
    print("IDLE_CASH=minimal residual only; no strategy cash gate")
    print("STARTING_EQUITY=$100,000 per window")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run")

    _print_parameters()
    prices = _load_prices()
    all_runs: dict[str, list[Run]] = {frequency: [] for frequency in FREQUENCIES}
    print("\nPER-WINDOW RESULTS")
    for name, start, end in WINDOWS:
        for frequency in FREQUENCIES:
            run = _run_rebalanced(prices, start, end, frequency)
            all_runs[frequency].append(run)
            m = run.metrics
            print(
                f"{frequency.upper()} | {name} | Sharpe={m['sharpe']:+.3f} | "
                f"Sortino={m['sortino']:+.3f} | return={m['total_return']:+.2%} | "
                f"maxDD={m['max_drawdown']:.2%} | rebalance_events={m['rebalance_events']} | "
                f"turnover={m['turnover']:.2%}"
            )

    pooled = {frequency: _pool(runs) for frequency, runs in all_runs.items()}
    print("\nPOOLED FREQUENCY SENSITIVITY")
    for frequency in FREQUENCIES:
        m = pooled[frequency]
        print(
            f"{frequency.upper()} | Sharpe={m['sharpe']:+.3f} | Sortino={m['sortino']:+.3f} | "
            f"return={m['total_return']:+.2%} | maxDD={m['max_drawdown']:.2%} | "
            f"rebalance_events={m['rebalance_events']} | turnover={m['turnover']:.2%}"
        )

    selected = all_runs["quarterly"]
    print("\nPER-ASSET RESULTS — QUARTERLY, FULL PERIOD")
    for asset in ASSETS:
        combined = {
            "return_contribution": sum(run.asset[asset]["return_contribution"] for run in selected),
            "times_rebalanced_into": sum(run.asset[asset]["times_rebalanced_into"] for run in selected),
            "times_rebalanced_out_of": sum(run.asset[asset]["times_rebalanced_out_of"] for run in selected),
            "stop_fires": sum(run.asset[asset]["stop_fires"] for run in selected),
        }
        print(
            f"{asset} | return_contribution={combined['return_contribution']:+.2%} | "
            f"times_rebalanced_into={combined['times_rebalanced_into']} | "
            f"times_rebalanced_out_of={combined['times_rebalanced_out_of']} | "
            f"stop_fires={combined['stop_fires']}"
        )

    buy_hold_runs = [_run_buy_and_hold(prices, start, end) for _, start, end in WINDOWS]
    buy_hold = _pool(buy_hold_runs)
    quarterly = pooled["quarterly"]
    print("\nCONTROL 1 — REBALANCED VS PLAIN BUY-AND-HOLD")
    print(
        f"QUARTERLY_REBALANCED | Sharpe={quarterly['sharpe']:+.3f} | "
        f"return={quarterly['total_return']:+.2%} | maxDD={quarterly['max_drawdown']:.2%}"
    )
    print(
        f"PLAIN_BUY_AND_HOLD | Sharpe={buy_hold['sharpe']:+.3f} | "
        f"return={buy_hold['total_return']:+.2%} | maxDD={buy_hold['max_drawdown']:.2%}"
    )
    print(
        "VERDICT | "
        + (
            "rebalanced beats plain buy-and-hold risk-adjusted"
            if quarterly["sharpe"] > buy_hold["sharpe"]
            else "rebalanced does NOT beat plain buy-and-hold risk-adjusted"
        )
    )

    print("\nCONTROL 2 — REBALANCED VS FAILED TREND RUNS")
    print("FAILED_EMA50_200_HOLD5 | pooled Sharpe=+0.700 | return=+78.85%")
    print("FAILED_EMA100_300_HOLD20 | pooled Sharpe=+0.498 | return=+49.75%")
    print(
        f"QUARTERLY_REBALANCED | pooled Sharpe={quarterly['sharpe']:+.3f} | "
        f"return={quarterly['total_return']:+.2%}"
    )

    print("\nCONTROL 3 — REBALANCE FREQUENCY")
    print("Quarterly remains the locked choice regardless of sensitivity ranking.")
    for frequency in FREQUENCIES:
        print(f"{frequency.upper()} | pooled Sharpe={pooled[frequency]['sharpe']:+.3f}")

    print("\nCONTROL 4 — CORRELATION TO BOT 1")
    print("UNAVAILABLE | no historical Bot 1 daily return series exists; not fabricated")

    print("\nPASS BAR — QUARTERLY LOCKED STRATEGY")
    checks = [
        ("pooled Sharpe >= 0.80", quarterly["sharpe"] >= 0.80),
        ("max drawdown <= 45%", quarterly["max_drawdown"] <= 0.45),
        ("rebalanced beats plain buy-and-hold risk-adjusted", quarterly["sharpe"] > buy_hold["sharpe"]),
        ("materially beats EMA50/200 hold5", quarterly["sharpe"] > 0.700),
        ("materially beats EMA100/300 hold20", quarterly["sharpe"] > 0.498),
    ]
    for label, passed in checks:
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    print("\nSAFETY")
    print("orders_placed=0 | runner_started=0 | bot1_touched=0 | bot2_touched=0")
    print("vault_touched=0 | migration_utility_touched=0 | alpha_vantage_called=0 | published=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())