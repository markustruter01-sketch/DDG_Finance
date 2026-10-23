"""TREND-V1-B on Atlas's (oracle's) Alpaca account: the shared live core.

One place computes what the registered sleeve wants (weights from daily bars,
then a safe whole-share rebalance plan) for both the daily SHADOW log and the
live executor (sleeve_runtime/trend_executor.py). Signal and sizing are the
same code the held-out test ran (research_harness.sleeves.trend + planner).

Capital rules (written once, here):
- Vault holdings (BIL/VOO profit reserve) are not sleeve capital: their value
  is taken out of equity and they are never traded.
- Parked cash (SGOV) is cash: its value counts as cash for the plan.
- A held fractional remainder (e.g. 0.88 of a share) is planned as whole
  shares; the remainder is reported. A full exit sells it too.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from research_harness.explore.trend_v1 import STOP_PCT, UNIVERSE
from research_harness.harness.portfolio import HistoryView
from research_harness.sleeves.trend import TrendParams, target_weights
from sleeve_runtime.planner import RebalancePlan, plan_rebalance

try:
    from loguru import logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("trend_v1b")

REGISTRATION = "TREND-V1-B"
PARAMS = TrendParams(rule="sma_210")          # registered candidate B
CASH_BUFFER_PCT = 0.01
HISTORY_CALENDAR_DAYS = 420                   # > 210 trading days of warm-up
NEW_YORK = ZoneInfo("America/New_York")
# A daily bar is final once the session has closed (16:00 New York) and the
# provider has published it; 16:15 leaves a margin. Before that, today's bar
# is still forming and is never used.
BAR_FINAL_AFTER = time(16, 15)
DUST_QTY = 1e-6

# A daily-bars fetcher: symbols, start date -> {symbol: [{"day": date, "close": float}, ...]}
BarFetcher = Callable[[list[str], date], dict[str, list[dict[str, Any]]]]


def completed_bars(bars: dict[str, list[dict[str, Any]]], now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Drop any bar for a session that has not finished (New York time)."""
    ny = now.astimezone(NEW_YORK)
    last_final = ny.date() if ny.time() >= BAR_FINAL_AFTER else ny.date() - timedelta(days=1)
    return {s: [b for b in series if b["day"] <= last_final] for s, series in bars.items()}



@dataclass
class SleeveCapital:
    equity: float
    cash: float
    held: dict[str, float]          # sleeve positions (no vault, no parked cash, no dust)
    excluded: list[str]             # vault + parked-cash symbols seen in the account
    broker_cash: float = 0.0        # cash spendable right now (parked cash not yet sold)


def sleeve_capital(account: dict[str, Any], positions: list[dict[str, Any]], *,
                   vault: set[str], cash_park: set[str]) -> SleeveCapital:
    vault_value = parked = 0.0
    held: dict[str, float] = {}
    excluded: set[str] = set()
    for p in positions:
        sym, qty = p["symbol"], float(p.get("qty") or 0)
        value = float(p.get("market_value") or 0)
        if sym in vault:
            vault_value += value
            excluded.add(sym)
        elif sym in cash_park:
            parked += value
            excluded.add(sym)
        elif qty >= DUST_QTY:
            held[sym] = qty
    equity = float(account["equity"]) - vault_value
    if equity <= 0:
        raise ValueError("sleeve equity is not positive after removing the vault")
    cash = float(account["cash"])
    return SleeveCapital(equity, cash + parked, held, sorted(excluded), cash)


@dataclass
class TrendPlan:
    plan: RebalancePlan
    weights: dict[str, float]
    signal_day: date
    price_day: date
    prices: dict[str, float | None]
    fractional: dict[str, float] = field(default_factory=dict)
    registration: str = REGISTRATION

    def stop_for(self, symbol: str) -> float | None:
        return next((a.stop for a in self.plan.stops if a.symbol == symbol), None)

    def summary(self, cap: SleeveCapital | None = None) -> dict[str, Any]:
        out = {
            "registration": self.registration,
            "signal_day": self.signal_day.isoformat(),
            "price_day": self.price_day.isoformat(),
            "weights": {s: round(w, 4) for s, w in sorted(self.weights.items())},
            "invested_pct": round(100 * sum(self.weights.values()), 1),
            "sells": [[o.symbol, o.qty] for o in self.plan.sells],
            "buys": [[o.symbol, o.qty] for o in self.plan.buys],
            "stops": [[a.symbol, a.action, a.qty, a.stop] for a in self.plan.stops],
            "skipped": self.plan.skipped,
            "buy_scale": round(self.plan.buy_scale, 4),
            "fractional": {s: round(q, 6) for s, q in sorted(self.fractional.items())},
        }
        if cap is not None:
            out.update(sleeve_equity=round(cap.equity, 2), sleeve_cash=round(cap.cash, 2),
                       excluded=cap.excluded)
        return out


def compute_plan(
    *,
    bars: dict[str, list[dict[str, Any]]],
    positions: dict[str, float],
    equity: float,
    cash: float,
    signal_day: date | None = None,
    frozen: dict[str, str] | None = None,
) -> TrendPlan:
    """Pure. Weights as of signal_day (default: the latest bar day); share
    counts and stops from the latest bar day's closes. Bars must already be
    completed sessions only."""
    days = [b["day"] for s in UNIVERSE for b in bars.get(s, [])[-1:]]
    if not days:
        raise ValueError("no bars for any universe symbol")
    price_day = max(days)
    signal_day = signal_day or price_day
    if signal_day > price_day:
        raise ValueError("signal day is after the latest bar")
    view = HistoryView({s: bars[s] for s in UNIVERSE if bars.get(s)})
    view.today = signal_day
    weights = target_weights(view, UNIVERSE, PARAMS)
    return plan_from_weights(weights=weights, bars=bars, positions=positions, equity=equity,
                             cash=cash, signal_day=signal_day, price_day=price_day,
                             frozen=frozen, stop_pct=STOP_PCT, registration=REGISTRATION)


def plan_from_weights(
    *,
    weights: dict[str, float],
    bars: dict[str, list[dict[str, Any]]],
    positions: dict[str, float],
    equity: float,
    cash: float,
    signal_day: date,
    price_day: date,
    frozen: dict[str, str] | None,
    stop_pct: float,
    registration: str,
) -> TrendPlan:
    """Shared by every live sleeve: whole-share plan and stops from the
    latest bar day's closes, for the given target weights."""
    whole = {s: float(math.floor(q + 1e-9)) for s, q in positions.items()}
    fractional = {s: q - whole[s] for s, q in positions.items() if q - whole[s] > DUST_QTY}
    prices: dict[str, float | None] = {}
    for s in set(weights) | set(whole):
        series = bars.get(s) or []
        prices[s] = series[-1]["close"] if series and series[-1]["day"] == price_day else None
    plan = plan_rebalance(weights=weights, equity=equity, cash=cash,
                          positions={s: q for s, q in whole.items() if q > 0},
                          prices=prices, stop_pct=stop_pct, cash_buffer_pct=CASH_BUFFER_PCT,
                          frozen=frozen)
    return TrendPlan(plan, weights, signal_day, price_day, prices, fractional, registration)


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


def fetch_completed(fetch_bars: BarFetcher, held: dict[str, float], now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Bars for the universe plus anything the sleeve holds (so legacy
    holdings outside the universe get a price and can be sold)."""
    symbols = sorted(set(UNIVERSE) | set(held))
    return completed_bars(fetch_bars(symbols, now.date() - timedelta(days=HISTORY_CALENDAR_DAYS)), now)


def run_shadow(
    *,
    fetch_bars: BarFetcher,
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    vault: set[str],
    cash_park: set[str],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Fetch, plan and log one shadow plan. No orders, no writes. Never raises."""
    now = now or datetime.now(timezone.utc)
    try:
        cap = sleeve_capital(account, positions, vault=vault, cash_park=cash_park)
        bars = fetch_completed(fetch_bars, cap.held, now)
        result = compute_plan(bars=bars, positions=cap.held, equity=cap.equity, cash=cap.cash).summary(cap)
    except Exception as exc:
        log.warning(f"TREND-V1-B shadow | skipped: {type(exc).__name__}: {exc}")
        return None
    log.info(f"TREND-V1-B shadow plan | {json.dumps(result, separators=(',', ':'))}")
    return result
