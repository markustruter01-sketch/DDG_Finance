"""GEAR-V1-G4 forward shadow test: no orders, ever.

G4 failed its held-out drawdown bar (research_harness/explore/GEAR-V1-PLAN.md)
but beat SPY's return in both windows. Markus's goal is >10.5% a year, so it
is followed forward on live data at zero risk: each evening the registered G4
rules are replayed with the SAME simulator and costs as the backtest, from
SHADOW_START to the last finished session, next to SPY buy-and-hold.
Deterministic replay means no state to drift; the daily row is the audit trail.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from research_harness.explore.gear_v1 import COSTS, STOP_PCT, SYMBOLS, WHOLE_SHARES
from research_harness.harness import metrics
from research_harness.harness.portfolio import simulate
from research_harness.sleeves.gear import CANDIDATES, gear_stats, make_strategy
from sleeve_runtime.trend_v1b import completed_bars

REGISTRATION = "GEAR-V1-G4"
CANDIDATE = "G4"
SHADOW_START = date(2026, 10, 23)        # first session after the held-out test
WARMUP_CALENDAR_DAYS = 420                # > 200 sessions before SHADOW_START for the signal
ALPACA_DATA = "https://data.alpaca.markets/v2/stocks/bars"

OhlcFetcher = Callable[[list[str], date], dict[str, list[dict[str, Any]]]]


def alpaca_ohlc_fetcher(key: str, secret: str, http_get=None) -> OhlcFetcher:
    """Daily split/dividend-adjusted OHLC from Alpaca's data API (SIP, then IEX)."""
    if http_get is None:
        import requests
        http_get = requests.get

    def fetch(symbols: list[str], start: date) -> dict[str, list[dict[str, Any]]]:
        last_err: Exception | None = None
        for feed in ("sip", "iex"):
            try:
                out: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
                token = None
                while True:
                    params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start.isoformat(),
                              "adjustment": "all", "feed": feed, "limit": 10000}
                    if token:
                        params["page_token"] = token
                    r = http_get(ALPACA_DATA, params=params, timeout=30,
                                 headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
                    r.raise_for_status()
                    body = r.json()
                    for sym, rows in (body.get("bars") or {}).items():
                        out.setdefault(sym, []).extend(
                            {"day": date.fromisoformat(b["t"][:10]), "open": float(b["o"]), "high": float(b["h"]),
                             "low": float(b["l"]), "close": float(b["c"])} for b in rows)
                    token = body.get("next_page_token")
                    if not token:
                        break
                for s in out:
                    out[s] = sorted({b["day"]: b for b in out[s]}.values(), key=lambda b: b["day"])
                return out
            except Exception as exc:     # try the next feed; reported if both fail
                last_err = exc
        raise RuntimeError(f"daily bars unavailable ({type(last_err).__name__})")
    return fetch


def run_gear_shadow(fetch: OhlcFetcher, now: datetime) -> dict[str, Any]:
    """Replay G4 and SPY from SHADOW_START to the last finished session.
    Cash earns nothing here (no live T-bill feed), which slightly understates
    both sides equally. Returns a plain dict for logging and storage."""
    # Fixed start: the warm-up must sit before SHADOW_START however long the shadow runs.
    bars = completed_bars(fetch(SYMBOLS, SHADOW_START - timedelta(days=WARMUP_CALENDAR_DAYS)), now)
    spy_days = [b["day"] for b in bars.get("SPY", []) if b["day"] >= SHADOW_START]
    if len(spy_days) < 2:
        return {"status": "waiting", "shadow_start": SHADOW_START.isoformat(),
                "message": "Shadow starts after two finished sessions from 23 Oct 2026."}
    end = spy_days[-1]
    log: list = []
    res = simulate(bars, make_strategy(CANDIDATE, log), costs=COSTS, rf_annual=None,
                   start=SHADOW_START, end=end, registration_id=REGISTRATION,
                   whole_shares=WHOLE_SHARES, stop_pct=STOP_PCT)
    spy = simulate({"SPY": bars["SPY"]}, lambda d, v: {"SPY": 1.0}, costs=COSTS, rf_annual=None,
                   start=SHADOW_START, end=end, registration_id=REGISTRATION)
    g, s = metrics.summarize(res.curve, res.trades), metrics.summarize(spy.curve, spy.trades)
    gear_today = log[-1][1] if log else None
    return {
        "status": "ok",
        "as_of": end.isoformat(),
        "shadow_start": SHADOW_START.isoformat(),
        "gear": gear_today,
        "target_weights": {} if gear_today in (None, "safe") else CANDIDATES[CANDIDATE][gear_today],
        "g4": {"equity": round(res.curve[-1][1], 2), "return_pct": g.get("total_return_pct"),
               "max_drawdown_pct": g.get("max_drawdown_pct"), "trades": g.get("trades"),
               "stops_hit": res.stops_hit, "costs_paid_usd": round(res.costs_paid, 2)},
        "spy": {"equity": round(spy.curve[-1][1], 2), "return_pct": s.get("total_return_pct"),
                "max_drawdown_pct": s.get("max_drawdown_pct")},
        "gears": gear_stats(log, CANDIDATE, SHADOW_START, end),
    }
