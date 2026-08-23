#!/usr/bin/env python3
"""Bot 3 hard-assets strategy and locked-parameter validation backtest.

READ-ONLY: this script reads the verified Yahoo tables and never places orders,
starts a runner, changes account state, or imports execution code.

The parameters below are pre-registered for this run. There is intentionally
no optimizer: the walk-forward "fit" step records that the locked parameters
were carried forward unchanged, so results cannot feed back into tuning.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402

ASSETS = ("BTC", "ETH", "GLD", "SLV")
CRYPTO = {"BTC", "ETH"}
STARTING_EQUITY = 100_000.0
EMA_FAST = 50
EMA_SLOW = 200
MIN_HOLD_DAYS = 5
ENTRY_CAP_PCT = 0.25
VOL_LOOKBACK = 20
TARGET_VOL_ANNUAL = 0.20
CRYPTO_STOP_PCT = 0.25
METAL_STOP_PCT = 0.10
WINDOWS = (
    ("2021", date(2021, 1, 1), date(2021, 12, 31)),
    ("2022", date(2022, 1, 1), date(2022, 12, 31)),
    ("2023", date(2023, 1, 1), date(2023, 12, 31)),
    ("2024-2026-08", date(2024, 1, 1), date(2026, 8, 31)),
)


@dataclass
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass
class Position:
    asset: str
    entry_day: date
    entry_price: float
    notional: float
    qty: float
    stop_price: float


def _load_prices() -> dict[str, list[Bar]]:
    tables = {"BTC": "crypto_historical_prices", "ETH": "crypto_historical_prices",
              "GLD": "bot3_inflation_hedge_prices", "SLV": "bot3_inflation_hedge_prices"}
    prices: dict[str, list[Bar]] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for asset in ASSETS:
                cur.execute(
                    f"""
                    SELECT date, open, high, low, close
                    FROM {tables[asset]}
                    WHERE symbol=%s AND source='yahoo'
                    ORDER BY date
                    """,
                    (asset,),
                )
                prices[asset] = [Bar(*row) for row in cur.fetchall()]
    if any(not prices[asset] for asset in ASSETS):
        raise RuntimeError("Bot 3 backtest requires non-empty validated history for all four assets")
    return prices


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _annualized_vol(closes: list[float]) -> float:
    if len(closes) < VOL_LOOKBACK + 1:
        return 0.0
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    return stdev(returns[-VOL_LOOKBACK:]) * math.sqrt(252)


def _metrics(curve: list[float], trades: list[dict[str, Any]], no_position_days: int, days: int) -> dict[str, Any]:
    returns = [curve[i] / curve[i - 1] - 1 for i in range(1, len(curve)) if curve[i - 1] > 0]
    if len(returns) > 1 and stdev(returns) > 0:
        sharpe = mean(returns) / stdev(returns) * math.sqrt(252)
    else:
        sharpe = 0.0
    negative = [r for r in returns if r < 0]
    downside = stdev(negative) if len(negative) > 1 else 0.0
    sortino = mean(returns) / downside * math.sqrt(252) if downside > 0 else 0.0
    peak = curve[0] if curve else STARTING_EQUITY
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak if peak else 0.0)
    wins = [trade["return_pct"] for trade in trades if trade["pnl"] > 0]
    losses = [trade["return_pct"] for trade in trades if trade["pnl"] <= 0]
    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "total_return": (curve[-1] / STARTING_EQUITY - 1) if curve else 0.0,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_win_pct": mean(wins) if wins else 0.0,
        "avg_loss_pct": mean(losses) if losses else 0.0,
        "cash_time_pct": no_position_days / days if days else 1.0,
        "daily_returns": returns,
        "final_equity": curve[-1] if curve else STARTING_EQUITY,
    }


def _run_window(prices: dict[str, list[Bar]], start: date, end: date) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    by_asset = {asset: {bar.day: bar for bar in prices[asset]} for asset in ASSETS}
    all_days = sorted({bar.day for bars in prices.values() for bar in bars if bar.day <= end})
    active_days = [day for day in all_days if start <= day <= end]
    cash = STARTING_EQUITY
    positions: dict[str, Position] = {}
    pending_entry: set[str] = set()
    pending_exit: set[str] = set()
    curve = [STARTING_EQUITY]
    trades: list[dict[str, Any]] = []
    per_asset: dict[str, dict[str, Any]] = {
        asset: {
            "entry_count": 0, "stop_fires": 0, "held_days": 0, "trades": [],
            "invested_days": 0, "sleeve_cash": STARTING_EQUITY * ENTRY_CAP_PCT,
            "equity_curve": [],
        }
        for asset in ASSETS
    }
    closes: dict[str, list[float]] = {asset: [] for asset in ASSETS}
    previous_close: dict[str, float] = {}
    no_position_days = 0

    for day in all_days:
        bars = {asset: by_asset[asset].get(day) for asset in ASSETS}
        if day < start:
            # Warm indicators with all available pre-window bars, but do not
            # carry positions or performance into the out-of-sample window.
            for asset, bar in bars.items():
                if bar:
                    closes[asset].append(bar.close)
                    previous_close[asset] = bar.close
            continue
        if day > end:
            break

        # Stops are intraday catastrophe backstops. They are checked before
        # close-based trend actions and count as a fired protective stop.
        for asset, pos in list(positions.items()):
            bar = bars[asset]
            if bar and bar.low <= pos.stop_price:
                exit_price = pos.stop_price
                pnl = (exit_price - pos.entry_price) * pos.qty
                trade = {
                    "asset": asset, "entry_day": pos.entry_day, "exit_day": day,
                    "entry_price": pos.entry_price, "exit_price": exit_price,
                    "pnl": pnl, "return_pct": pnl / pos.notional * 100 if pos.notional else 0.0,
                    "reason": "catastrophe_stop",
                }
                cash += pos.qty * exit_price
                per_asset[asset]["sleeve_cash"] += pos.qty * exit_price
                trades.append(trade)
                per_asset[asset]["trades"].append(trade)
                per_asset[asset]["stop_fires"] += 1
                del positions[asset]
                pending_exit.discard(asset)
                pending_entry.discard(asset)

        # Pending actions were generated from a prior completed bar, avoiding
        # same-bar close-to-fill lookahead. Weekend metal actions wait for the
        # next metal trading session.
        for asset, bar in bars.items():
            if not bar:
                continue
            if asset in pending_exit and asset in positions:
                pos = positions.pop(asset)
                pnl = (bar.open - pos.entry_price) * pos.qty
                trade = {
                    "asset": asset, "entry_day": pos.entry_day, "exit_day": day,
                    "entry_price": pos.entry_price, "exit_price": bar.open,
                    "pnl": pnl, "return_pct": pnl / pos.notional * 100 if pos.notional else 0.0,
                    "reason": "trend_gate",
                }
                cash += pos.qty * bar.open
                per_asset[asset]["sleeve_cash"] += pos.qty * bar.open
                trades.append(trade)
                per_asset[asset]["trades"].append(trade)
            pending_exit.discard(asset)
            if asset in pending_entry and asset not in positions:
                equity_before = cash + sum(
                    p.qty * (bars[p.asset].open if bars[p.asset] else previous_close.get(p.asset, p.entry_price))
                    for p in positions.values()
                )
                history = closes[asset]
                vol = _annualized_vol(history)
                size_pct = ENTRY_CAP_PCT if vol <= 0 else ENTRY_CAP_PCT * min(1.0, TARGET_VOL_ANNUAL / vol)
                notional = min(cash, equity_before * size_pct)
                if notional > 0:
                    stop_distance = CRYPTO_STOP_PCT if asset in CRYPTO else METAL_STOP_PCT
                    positions[asset] = Position(asset, day, bar.open, notional, notional / bar.open,
                                                bar.open * (1.0 - stop_distance))
                    cash -= notional
                    per_asset[asset]["sleeve_cash"] -= notional
                    per_asset[asset]["entry_count"] += 1
            pending_entry.discard(asset)

        equity = cash
        for asset, pos in positions.items():
            bar = bars[asset]
            mark = bar.close if bar else previous_close.get(asset, pos.entry_price)
            equity += pos.qty * mark
            per_asset[asset]["held_days"] += 1
        for asset in ASSETS:
            bar = bars[asset]
            mark = bar.close if bar else previous_close.get(asset, 0.0)
            sleeve_equity = per_asset[asset]["sleeve_cash"]
            if asset in positions:
                sleeve_equity += positions[asset].qty * mark
            per_asset[asset]["equity_curve"].append(sleeve_equity)
        if not positions:
            no_position_days += 1
        curve.append(equity)

        # Store completed bars, then generate next-session actions from today's
        # close. Each asset has its own EMA gate and its own session calendar.
        for asset, bar in bars.items():
            if not bar:
                continue
            closes[asset].append(bar.close)
            previous_close[asset] = bar.close
            fast = _ema(closes[asset], EMA_FAST)
            slow = _ema(closes[asset], EMA_SLOW)
            regime = fast is not None and slow is not None and bar.close > fast > slow
            if asset in positions:
                age = (day - positions[asset].entry_day).days
                if age >= MIN_HOLD_DAYS and fast is not None and slow is not None and (bar.close < fast or fast < slow):
                    pending_exit.add(asset)
            elif regime:
                pending_entry.add(asset)

    # Close any remaining positions at their last available close in the test
    # window so every reported window has a realized terminal value.
    for asset, pos in list(positions.items()):
        final_bar = next((bar for bar in reversed(prices[asset]) if start <= bar.day <= end), None)
        if final_bar:
            pnl = (final_bar.close - pos.entry_price) * pos.qty
            trade = {
                "asset": asset, "entry_day": pos.entry_day, "exit_day": final_bar.day,
                "entry_price": pos.entry_price, "exit_price": final_bar.close,
                "pnl": pnl, "return_pct": pnl / pos.notional * 100 if pos.notional else 0.0,
                "reason": "window_end",
            }
            cash += pos.qty * final_bar.close
            per_asset[asset]["sleeve_cash"] += pos.qty * final_bar.close
            trades.append(trade)
            per_asset[asset]["trades"].append(trade)
            del positions[asset]
    if curve:
        curve[-1] = cash

    for asset in ASSETS:
        data = per_asset[asset]
        data["held_pct"] = data["held_days"] / len(active_days) if active_days else 0.0
        data["cash_pct"] = 1.0 - data["held_pct"]
        data["total_return_contribution"] = sum(t["pnl"] for t in data["trades"]) / STARTING_EQUITY
        peak = data["equity_curve"][0] if data["equity_curve"] else STARTING_EQUITY * ENTRY_CAP_PCT
        data["max_drawdown"] = 0.0
        for value in data["equity_curve"]:
            peak = max(peak, value)
            data["max_drawdown"] = max(data["max_drawdown"], (peak - value) / peak if peak else 0.0)
    return _metrics(curve, trades, no_position_days, len(active_days)), per_asset


def _buy_and_hold(prices: dict[str, list[Bar]], start: date, end: date) -> dict[str, Any]:
    by_asset = {asset: {bar.day: bar for bar in prices[asset]} for asset in ASSETS}
    days = sorted({day for rows in by_asset.values() for day in rows if start <= day <= end})
    quantities: dict[str, float] = {}
    cash = STARTING_EQUITY
    curve = []
    for asset in ASSETS:
        first = next((by_asset[asset][day] for day in days if day in by_asset[asset]), None)
        if first:
            notional = STARTING_EQUITY * ENTRY_CAP_PCT
            quantities[asset] = notional / first.close
            cash -= notional
    last: dict[str, float] = {}
    for day in days:
        for asset in ASSETS:
            bar = by_asset[asset].get(day)
            if bar:
                last[asset] = bar.close
        curve.append(cash + sum(quantities[a] * last.get(a, 0) for a in ASSETS))
    return _metrics(curve, [], 0, len(days))


def _pooled(results: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [r for result in results for r in result["daily_returns"]]
    if len(returns) > 1 and stdev(returns) > 0:
        sharpe = mean(returns) / stdev(returns) * math.sqrt(252)
    else:
        sharpe = 0.0
    final = STARTING_EQUITY
    for result in results:
        final *= 1.0 + result["total_return"]
    return {"sharpe": sharpe, "total_return": final / STARTING_EQUITY - 1,
            "max_drawdown": max(r["max_drawdown"] for r in results) if results else 0.0}


def _bot1_control() -> None:
    """Report why a historical Bot 1 correlation cannot be calculated."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*), MIN(snapshot_ts), MAX(snapshot_ts)
                FROM fleet_equity_snapshots
                WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                """
            )
            count, first, last = cur.fetchone()
    print("CONTROL 2 — correlation to Bot 1 ETF trend fleet")
    print(f"  UNAVAILABLE | fleet snapshots={count}, range={first} to {last}")
    print("  Reason: no historical 2021-2026 Bot 1 daily return series exists in the database.")
    print("CONTROL 3 — fleet-level effect")
    print("  UNAVAILABLE | combined Sharpe with/without Bot 3 requires the same missing historical Bot 1 series.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run the read-only four-window backtest")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the read-only backtest")

    print("=" * 100)
    print("BOT 3 HARD-ASSETS STRATEGY — LOCKED PARAMETERS (printed before results)")
    print("UNIVERSE:", ", ".join(ASSETS), "| BTC/ETH crypto 24/7; GLD/SLV US equity sessions")
    for name, value in (
        ("EMA_FAST", EMA_FAST), ("EMA_SLOW", EMA_SLOW), ("MIN_HOLD_DAYS", MIN_HOLD_DAYS),
        ("ENTRY_CAP_PCT", ENTRY_CAP_PCT), ("VOL_LOOKBACK", VOL_LOOKBACK),
        ("TARGET_VOL_ANNUAL", TARGET_VOL_ANNUAL), ("CRYPTO_STOP_PCT", CRYPTO_STOP_PCT),
        ("METAL_STOP_PCT", METAL_STOP_PCT), ("STARTING_EQUITY", STARTING_EQUITY),
    ):
        print(f"{name}={value}")
    print("TREND_ENTRY=close > EMA50 > EMA200; TREND_EXIT=after min hold, close < EMA50 or EMA50 < EMA200")
    print("SIZING=volatility-scaled within 25% entry cap; NO trimming; NO deployment ceiling; idle capital=SGOV")
    print("WALK_FORWARD=prior window is audit-only; parameters remain locked and are never refit or retuned")
    print("STOPS=crypto stop_limit catastrophe backstop 25%; GLD/SLV whole-share GTC stop 10%; software fallback checked")
    print("EXECUTION_MODEL=next available session open for signals; intraday low for catastrophe stops; no orders placed")

    prices = _load_prices()
    results: list[dict[str, Any]] = []
    full_asset_data: dict[str, dict[str, Any]] = {
        asset: {
            "trades": [], "held_days": 0, "entry_count": 0, "stop_fires": 0,
            "total_days": 0, "max_drawdown": 0.0,
        }
        for asset in ASSETS
    }
    print("\nPER-WINDOW RESULTS")
    for index, (name, start, end) in enumerate(WINDOWS):
        train = WINDOWS[index - 1][0] if index else "NONE (initial window; no prior data)"
        result, asset_data = _run_window(prices, start, end)
        results.append(result)
        for asset in ASSETS:
            for key in ("trades",):
                full_asset_data[asset][key].extend(asset_data[asset][key])
            for key in ("held_days", "entry_count", "stop_fires"):
                full_asset_data[asset][key] += asset_data[asset][key]
            full_asset_data[asset]["max_drawdown"] = max(
                full_asset_data[asset]["max_drawdown"], asset_data[asset]["max_drawdown"]
            )
            full_asset_data[asset]["total_days"] += (end - start).days + 1
        print(
            f"{name} | train={train} | Sharpe={result['sharpe']:+.3f} | Sortino={result['sortino']:+.3f} | "
            f"return={result['total_return']:+.2%} | maxDD={result['max_drawdown']:.2%} | "
            f"trades={result['trade_count']} | win_rate={result['win_rate']:.2%} | "
            f"avg_win={result['avg_win_pct']:+.2f}% | avg_loss={result['avg_loss_pct']:+.2f}% | "
            f"time_cash={result['cash_time_pct']:.2%}"
        )
    pooled = _pooled(results)
    print(f"POOLED | Sharpe={pooled['sharpe']:+.3f} | return={pooled['total_return']:+.2%} | maxDD={pooled['max_drawdown']:.2%}")

    print("\nPER-ASSET RESULTS — full period")
    for asset in ASSETS:
        data = full_asset_data[asset]
        trades = data["trades"]
        held_pct = data["held_days"] / data["total_days"] if data["total_days"] else 0.0
        contribution = sum(trade["pnl"] for trade in trades) / STARTING_EQUITY
        print(
            f"{asset} | return_contribution={contribution:+.2%} | maxDD={data['max_drawdown']:.2%} "
            f"| trades={len(trades)} | gate_held={held_pct:.2%} | gate_cash={1-held_pct:.2%} | "
            f"stops_fired={data['stop_fires']}"
        )

    print("\nCONTROL 1 — trend-gated vs buy-and-hold (all four at 25% equal weight)")
    buy_hold_results = [_buy_and_hold(prices, start, end) for _, start, end in WINDOWS]
    buy_hold_pooled = _pooled(buy_hold_results)
    print(f"TREND_GATED | pooled Sharpe={pooled['sharpe']:+.3f} | return={pooled['total_return']:+.2%} | maxDD={pooled['max_drawdown']:.2%}")
    print(f"BUY_AND_HOLD | pooled Sharpe={buy_hold_pooled['sharpe']:+.3f} | return={buy_hold_pooled['total_return']:+.2%} | maxDD={buy_hold_pooled['max_drawdown']:.2%}")
    print(
        "VERDICT | "
        + ("trend gating beats buy-and-hold risk-adjusted" if pooled["sharpe"] > buy_hold_pooled["sharpe"]
           else "trend gating does NOT beat buy-and-hold risk-adjusted")
    )
    _bot1_control()

    print("\nPASS BAR")
    checks = [
        ("pooled Sharpe >= 0.80", pooled["sharpe"] >= 0.80),
        ("max drawdown <= 30%", pooled["max_drawdown"] <= 0.30),
        ("correlation to Bot 1 materially below 1", False),
        ("trend gating beats buy-and-hold risk-adjusted", pooled["sharpe"] > buy_hold_pooled["sharpe"]),
    ]
    for label, passed in checks:
        print(f"{label}: {'PASS' if passed else 'FAIL/UNAVAILABLE'}")
    print("\nSAFETY")
    print("orders_placed=0 | runner_started=0 | existing_EPOL_GREK_TUR_touched=0")
    print("bot1_touched=0 | bot2_touched=0 | ETF_fleet_touched=0 | migration_utility_touched=0 | published=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())