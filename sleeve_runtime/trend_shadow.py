"""TREND-V1-B in SHADOW on Atlas's Alpaca account: compute the registered
sleeve's target weights from live daily bars, turn them into a rebalance plan
against the account as it stands, and LOG the plan. No orders, no DB writes.

Why: it proves the live path (data -> weights -> safe plan) on the real
account before cutover, and the logged plans show exactly what cutover would
trade. The signal and sizing are the same code the held-out test ran
(research_harness.sleeves.trend + sleeve_runtime.planner).

Never raises into the caller: any failure is logged and returns None.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from research_harness.explore.trend_v1 import STOP_PCT, UNIVERSE
from research_harness.harness.portfolio import HistoryView
from research_harness.sleeves.trend import TrendParams, target_weights
from sleeve_runtime.planner import plan_rebalance

try:
    from loguru import logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("trend_shadow")

REGISTRATION = "TREND-V1-B"
PARAMS = TrendParams(rule="sma_210")          # registered candidate B
CASH_BUFFER_PCT = 0.01
HISTORY_CALENDAR_DAYS = 420                   # > 210 trading days of warm-up

# A daily-bars fetcher: symbols, start date -> {symbol: [{"day": date, "close": float}, ...]}
BarFetcher = Callable[[list[str], date], dict[str, list[dict[str, Any]]]]


def is_rebalance_day(today: date, previous_bar_day: date | None) -> bool:
    """The sleeve rebalances on the first close of each month (as tested)."""
    return previous_bar_day is None or (previous_bar_day.year, previous_bar_day.month) != (today.year, today.month)


def compute_plan(
    *,
    bars: dict[str, list[dict[str, Any]]],
    positions: dict[str, float],
    equity: float,
    cash: float,
    exclude: set[str] = frozenset(),
) -> dict[str, Any]:
    """Pure: weights + rebalance plan for the latest common bar day."""
    days = [b["day"] for s in UNIVERSE for b in bars.get(s, [])[-1:]]
    if not days:
        raise ValueError("no bars for any universe symbol")
    today = max(days)
    view = HistoryView({s: bars[s] for s in UNIVERSE if bars.get(s)})
    view.today = today
    weights = target_weights(view, UNIVERSE, PARAMS)

    held = {s: q for s, q in positions.items() if s not in exclude}
    prices: dict[str, float | None] = {}
    for s in set(weights) | set(held):
        series = bars.get(s) or []
        prices[s] = series[-1]["close"] if series and series[-1]["day"] == today else None
    plan = plan_rebalance(weights=weights, equity=equity, cash=cash, positions=held,
                          prices=prices, stop_pct=STOP_PCT, cash_buffer_pct=CASH_BUFFER_PCT)
    earlier = [b["day"] for s in UNIVERSE for b in bars.get(s, []) if b["day"] < today]
    return {
        "registration": REGISTRATION,
        "bar_day": today.isoformat(),
        "rebalance_day": is_rebalance_day(today, max(earlier) if earlier else None),
        "weights": {s: round(w, 4) for s, w in sorted(weights.items())},
        "invested_pct": round(100 * sum(weights.values()), 1),
        "sells": [[o.symbol, o.qty] for o in plan.sells],
        "buys": [[o.symbol, o.qty] for o in plan.buys],
        "stops": [[a.symbol, a.action, a.qty, a.stop] for a in plan.stops],
        "skipped": plan.skipped,
        "buy_scale": round(plan.buy_scale, 4),
        "excluded": sorted(exclude & set(positions)),
    }


def alpaca_bar_fetcher(api) -> BarFetcher:
    """Daily, split/dividend-adjusted bars from an alpaca_trade_api REST client.
    Consolidated (SIP) feed first; IEX if the account cannot read SIP."""
    def fetch(symbols: list[str], start: date) -> dict[str, list[dict[str, Any]]]:
        last_err: Exception | None = None
        for feed in ("sip", "iex"):
            try:
                raw = api.get_bars(symbols, "1Day", start=start.isoformat(),
                                   adjustment="all", feed=feed)
                out: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
                # Raw rows: {"S": symbol, "t": "2026-10-16T04:00:00Z", "c": close, ...}
                for b in raw._raw:
                    out[b["S"]].append({"day": date.fromisoformat(b["t"][:10]), "close": float(b["c"])})
                for s in out:
                    out[s].sort(key=lambda r: r["day"])
                return out
            except Exception as exc:   # try the next feed; reported if both fail
                last_err = exc
        raise RuntimeError(f"daily bars unavailable ({type(last_err).__name__})")
    return fetch


def run_shadow(
    *,
    fetch_bars: BarFetcher,
    account: dict[str, float],
    positions: list[dict[str, Any]],
    exclude: set[str],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Fetch, plan and log one shadow plan. Never raises."""
    now = now or datetime.now(timezone.utc)
    try:
        bars = fetch_bars(UNIVERSE, now.date() - timedelta(days=HISTORY_CALENDAR_DAYS))
        result = compute_plan(
            bars=bars,
            positions={p["symbol"]: float(p["qty"]) for p in positions},
            equity=float(account["equity"]), cash=float(account["cash"]), exclude=exclude,
        )
    except Exception as exc:
        log.warning(f"TREND-V1-B shadow | skipped: {type(exc).__name__}: {exc}")
        return None
    log.info(f"TREND-V1-B shadow plan | {json.dumps(result, separators=(',', ':'))}")
    return result
