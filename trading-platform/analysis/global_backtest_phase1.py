"""
global_backtest_phase1.py — Phase 1: Per-ETF Baseline, Full History

Runs the EXACT validated Moe trend strategy (spy_qqq_trend live params) on
every ticker in the pre-registered global universe, per historical window.

LOCKED PARAMETERS (bot2_spy_qqq.py — as-deployed):
  EMA_FAST         = 50      EMA_SLOW  = 200
  TRAIL_STOP_PCT   = 0.08    (software trailing stop, ratchets up)
  MAX_3DAY_DROP    = 0.05    (FIXED: last-3-bars only — closes[-1] vs closes[-4])
  POSITION_SIZE    = 0.40    (40% equity per entry)
  MAX_DEPLOYMENT   = 0.80    CASH_RESERVE = 0.20
  MIN_HOLD_DAYS    = 5       (calendar days from entry date)
  TP1_PCT          = 0.06    (+6% → close 33.3% of ORIGINAL qty)
  TP2_PCT          = 0.12    (+12% → close 33.3% of ORIGINAL qty)
  CRISIS_THRESHOLD = -0.12   (SPY 20d return; fail-safe = blocked)

DATA RULE:
  Yahoo Finance v8 API (period1/period2, daily bars) for ALL windows.
  Alpaca SIP is not available on this account (403). IEX only reaches ~Jul-2020.
  Single source per window — no mid-window splicing.
  Crisis gate uses SPY data fetched from the same source.

FIDELITY GAPS vs LIVE:
  1. Cadence: daily close. Live = hourly. Stops checked 1x/day (conservative).
  2. EMA seed: prices[0] — naive (AS-CODED, matches live).
  3. 3-day exit: LAST 3 BARS ONLY — closes[-1] vs closes[-4] (fixed version).
  4. TP qty: ORIGINAL qty, not decremented (AS-CODED).
  5. Gap-through-stop: approximated as (stop_price - close)/entry at stop fires.
     Daily-close simulation understates true intraday gap risk. See note.

WINDOWS (7):
  2008 GFC | 2011 EM selloff | 2015-16 EM bear | 2018 | 2020 COVID |
  2022 rate shock | 2023-24 recovery

READ-ONLY. No trades, no DB writes, no live orders.
"""
from __future__ import annotations

import math
import datetime
import time
import sys
import os
import requests
from typing import Optional

# ── Universe (ARGT removed 2026-08-06 on structural grounds) ─────────────────
sys.path.insert(0, os.path.dirname(__file__))
from global_universe import TICKER_REGION

UNIVERSE_TICKERS = [
    "SPY", "QQQ",                                    # US_CORE
    "EWY", "EWT", "INDA", "EWJ", "EWM", "VNM",      # ASIA_PACIFIC
    "EWZ", "EWW", "ECH",                             # LATIN_AMERICA (ARGT removed)
    "EEM", "EZA", "EPOL", "GREK", "TUR",             # FRONTIER_EM
]

# ── Locked strategy parameters ────────────────────────────────────────────────
EMA_FAST          = 50
EMA_SLOW          = 200
TRAIL_STOP_PCT    = 0.08
MAX_3DAY_DROP_PCT = 0.05
POSITION_SIZE_PCT = 0.40
MAX_DEPLOYMENT    = 0.80
CASH_RESERVE      = 0.20
MIN_HOLD_DAYS     = 5
TP1_PCT           = 0.06
TP2_PCT           = 0.12
CRISIS_THRESHOLD  = -0.12
STARTING_EQUITY   = 100_000.0

# ── Test windows ──────────────────────────────────────────────────────────────
# (label, window_start, window_end, warmup_from)
WINDOWS = [
    ("2008_GFC",      datetime.date(2008, 1, 1),  datetime.date(2009, 12, 31), datetime.date(2007, 1, 1)),
    ("2011_EM",       datetime.date(2011, 1, 1),  datetime.date(2012, 6, 30),  datetime.date(2010, 1, 1)),
    ("2015-16_EM",    datetime.date(2015, 1, 1),  datetime.date(2016, 12, 31), datetime.date(2014, 1, 1)),
    ("2018",          datetime.date(2018, 1, 1),  datetime.date(2019, 3, 31),  datetime.date(2017, 1, 1)),
    ("2020_COVID",    datetime.date(2020, 1, 1),  datetime.date(2021, 6, 30),  datetime.date(2019, 1, 1)),
    ("2022_rates",    datetime.date(2022, 1, 1),  datetime.date(2023, 3, 31),  datetime.date(2021, 1, 1)),
    ("2023-24",       datetime.date(2023, 1, 1),  datetime.date(2024, 12, 31), datetime.date(2022, 1, 1)),
]

EM_BEAR_WINDOWS = {"2011_EM", "2015-16_EM"}

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Yahoo Finance fetch ───────────────────────────────────────────────────────

def _fetch_yahoo(ticker: str, start: datetime.date, end: datetime.date,
                 retries: int = 4) -> Optional[dict]:
    """
    Fetch daily OHLCV via Yahoo Finance v8 (period1/period2, interval=1d).
    Returns {'dates','opens','highs','lows','closes','volumes'} or None.
    """
    p1 = int(datetime.datetime.combine(start, datetime.time.min,
             tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime.combine(end, datetime.time.max,
             tzinfo=datetime.timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": p1, "period2": p2, "interval": "1d",
              "includePrePost": "false", "events": "div,splits"}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=30)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                return None
            data = r.json()
            result = data.get("chart", {}).get("result")
            if not result:
                return None
            res0 = result[0]
            ts    = res0.get("timestamp", [])
            q     = res0.get("indicators", {}).get("quote", [{}])[0]
            # Try adjclose first (adjusted for splits/dividends)
            adj   = res0.get("indicators", {}).get("adjclose", [{}])
            adj_c = adj[0].get("adjclose", []) if adj else []

            opens  = q.get("open",   [])
            highs  = q.get("high",   [])
            lows   = q.get("low",    [])
            closes = q.get("close",  [])
            vols   = q.get("volume", [])

            # Use adjclose if available, else close
            use_close = adj_c if adj_c and len(adj_c) == len(ts) else closes

            rows = [
                (t, o, h, l, c, v)
                for t, o, h, l, c, v in zip(ts, opens, highs, lows, use_close, vols)
                if None not in (o, h, l, c)
            ]
            if not rows:
                return None
            ts2, o2, h2, l2, c2, v2 = zip(*rows)
            dates = [datetime.date.fromtimestamp(t) for t in ts2]
            return {
                "dates":   list(dates),
                "opens":   list(o2),
                "highs":   list(h2),
                "lows":    list(l2),
                "closes":  list(c2),
                "volumes": list(v2),
            }
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return None


# ── EMA — naive first-price seed (EXACT live implementation) ──────────────────

def _ema(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


# ── Entry signal (EXACT live implementation) ───────────────────────────────────

def _entry_signal(closes_250: list[float]) -> bool:
    if len(closes_250) < EMA_SLOW + 5:
        return False
    ema_fast_now  = _ema(closes_250,      EMA_FAST)
    ema_slow_now  = _ema(closes_250,      EMA_SLOW)
    ema_fast_prev = _ema(closes_250[:-5], EMA_FAST)
    if any(v is None for v in (ema_fast_now, ema_slow_now, ema_fast_prev)):
        return False
    return (ema_fast_now > ema_slow_now and
            ema_fast_now > ema_fast_prev and
            closes_250[-1] > ema_fast_now)


# ── Crisis gate (SPY 20d return ≤ -12%) ───────────────────────────────────────

def _crisis_gate(spy_closes: list[float], up_to: int) -> bool:
    """Returns True = entries blocked."""
    start = max(0, up_to - 20)
    slc = spy_closes[start: up_to + 1]
    if len(slc) < 21:
        return True  # fail-safe
    return (slc[-1] / slc[0] - 1) <= CRISIS_THRESHOLD


# ── Exit: price below EMA-50 ───────────────────────────────────────────────────

def _exit_below_ema50(closes_80: list[float]) -> Optional[str]:
    if len(closes_80) < 4:
        return None
    slc = closes_80[-EMA_FAST:] if len(closes_80) >= EMA_FAST else closes_80
    ema50 = _ema(slc, EMA_FAST)
    if ema50 and closes_80[-1] < ema50:
        return f"below_ema50({closes_80[-1]:.2f}<{ema50:.2f})"
    return None


# ── Exit: 3-day drop ≥ 5% (LAST 3 BARS ONLY — fixed) ─────────────────────────

def _exit_3day_drop(closes_80: list[float]) -> Optional[str]:
    if len(closes_80) >= 4:
        chg = (closes_80[-1] - closes_80[-4]) / closes_80[-4]
        if chg <= -MAX_3DAY_DROP_PCT:
            return f"3day_drop({chg*100:.1f}%)"
    return None


# ── Position ──────────────────────────────────────────────────────────────────

class _Pos:
    __slots__ = ("entry_date", "entry_price", "original_qty", "actual_qty",
                 "stop_price", "tp1_price", "tp2_price", "scaled_tp1", "scaled_tp2")

    def __init__(self, entry_date, entry_price, qty):
        self.entry_date   = entry_date
        self.entry_price  = entry_price
        self.original_qty = qty
        self.actual_qty   = qty
        self.stop_price   = entry_price * (1 - TRAIL_STOP_PCT)
        self.tp1_price    = entry_price * (1 + TP1_PCT)
        self.tp2_price    = entry_price * (1 + TP2_PCT)
        self.scaled_tp1   = False
        self.scaled_tp2   = False

    def min_hold_ok(self, current_date):
        return (current_date - self.entry_date).days >= MIN_HOLD_DAYS

    def ratchet(self, price):
        new_stop = price * (1 - TRAIL_STOP_PCT)
        if new_stop > self.stop_price:
            self.stop_price = new_stop


# ── Single-ticker window runner ────────────────────────────────────────────────

def _run_single_ticker_window(
    ticker_closes: list[float],
    ticker_highs:  list[float],
    ticker_lows:   list[float],
    ticker_dates:  list[datetime.date],
    spy_closes:    list[float],   # parallel to ticker arrays (same index = same date)
    window_start:  datetime.date,
    window_end:    datetime.date,
) -> dict:
    """
    Run Moe strategy on a single ticker for one window.
    ticker_* arrays cover [warmup_start → window_end].
    spy_closes is same-length (aligned by date).
    Returns metrics dict.
    """
    equity = STARTING_EQUITY
    cash   = STARTING_EQUITY
    pos: Optional[_Pos] = None   # single position
    equity_curve = [equity]
    peak   = equity
    max_dd = 0.0

    bars_in_window   = 0
    bars_in_position = 0
    trade_log: list[dict] = []
    entry_log:  list[dict] = []
    gap_slips:  list[float] = []   # (stop_price - exit_price) / entry_price for stop exits

    tp1_fires = tp2_fires = threeday_fires = 0
    n = len(ticker_closes)

    def _tail(arr, up_to, n_bars):
        return arr[max(0, up_to - n_bars + 1): up_to + 1]

    for i, date in enumerate(ticker_dates):
        if not (window_start <= date <= window_end):
            continue
        bars_in_window += 1
        price = ticker_closes[i]

        # ── Exits ──────────────────────────────────────────────────────────────
        if pos is not None:
            pos.ratchet(price)

            # Stop
            if price <= pos.stop_price:
                slip = (pos.stop_price - price) / pos.entry_price
                gap_slips.append(slip)
                pnl_usd = pos.actual_qty * price - pos.original_qty * pos.entry_price
                pnl_pct = (price - pos.entry_price) / pos.entry_price * 100
                cash += pos.actual_qty * price
                trade_log.append({"date": date, "exit": "trailing_stop",
                                   "pnl_pct": pnl_pct, "pnl_usd": pnl_usd})
                pos = None

            if pos is not None:
                min_ok = pos.min_hold_ok(date)

                # TP2
                if min_ok and not pos.scaled_tp2 and price >= pos.tp2_price:
                    scale = pos.original_qty * 0.333
                    cash += scale * price
                    pos.actual_qty -= scale
                    pos.scaled_tp2 = True
                    tp2_fires += 1

                # TP1
                if min_ok and not pos.scaled_tp1 and price >= pos.tp1_price:
                    scale = pos.original_qty * 0.333
                    cash += scale * price
                    pos.actual_qty -= scale
                    pos.scaled_tp1 = True
                    tp1_fires += 1

                if min_ok and pos is not None:
                    c80 = _tail(ticker_closes, i, 80)
                    reason = _exit_below_ema50(c80)
                    if reason:
                        pnl_usd = pos.actual_qty * price - pos.original_qty * pos.entry_price
                        pnl_pct = (price - pos.entry_price) / pos.entry_price * 100
                        cash += pos.actual_qty * price
                        trade_log.append({"date": date, "exit": "below_ema50",
                                          "pnl_pct": pnl_pct, "pnl_usd": pnl_usd})
                        pos = None

                if pos is not None:
                    c80 = _tail(ticker_closes, i, 80)
                    reason = _exit_3day_drop(c80)
                    if reason:
                        pnl_usd = pos.actual_qty * price - pos.original_qty * pos.entry_price
                        pnl_pct = (price - pos.entry_price) / pos.entry_price * 100
                        cash += pos.actual_qty * price
                        trade_log.append({"date": date, "exit": "3day_drop",
                                          "pnl_pct": pnl_pct, "pnl_usd": pnl_usd})
                        pos = None
                        threeday_fires += 1

        # ── Entry ──────────────────────────────────────────────────────────────
        if pos is None:
            in_crisis = _crisis_gate(spy_closes, i)
            if not in_crisis:
                c250 = _tail(ticker_closes, i, 250)
                if _entry_signal(c250):
                    notional = min(equity * POSITION_SIZE_PCT,
                                   equity * (1 - CASH_RESERVE),
                                   cash)
                    if notional > 0:
                        qty = notional / price
                        cash -= notional
                        pos = _Pos(date, price, qty)
                        entry_log.append({"date": date, "price": price, "notional": notional})

        # ── MTM ────────────────────────────────────────────────────────────────
        pos_val = (pos.actual_qty * price) if pos is not None else 0.0
        equity  = cash + pos_val
        equity_curve.append(equity)
        if pos is not None:
            bars_in_position += 1

        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Force-close at window end
    if pos is not None and trade_log is not None:
        last_price = ticker_closes[len([d for d in ticker_dates if d <= window_end]) - 1]
        pnl_usd = pos.actual_qty * last_price - pos.original_qty * pos.entry_price
        pnl_pct = (last_price - pos.entry_price) / pos.entry_price * 100
        cash += pos.actual_qty * last_price
        trade_log.append({"date": window_end, "exit": "window_end",
                          "pnl_pct": pnl_pct, "pnl_usd": pnl_usd})
        equity = cash
        if equity < peak:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

    # Metrics
    total_return = (equity - STARTING_EQUITY) / STARTING_EQUITY
    daily_rets = []
    for j in range(1, len(equity_curve)):
        p = equity_curve[j - 1]
        if p > 0:
            daily_rets.append(equity_curve[j] / p - 1)

    if len(daily_rets) > 1:
        mu  = sum(daily_rets) / len(daily_rets)
        var = sum((r - mu)**2 for r in daily_rets) / (len(daily_rets) - 1)
        sharpe = (mu / math.sqrt(var) * math.sqrt(252)) if var > 0 else 0.0
    else:
        sharpe = 0.0

    wins = [t for t in trade_log if t["pnl_usd"] > 0]
    wr   = len(wins) / len(trade_log) if trade_log else 0.0
    time_in_cash = 1.0 - (bars_in_position / bars_in_window) if bars_in_window > 0 else 1.0

    max_single_swing = 0.0
    for j in range(1, len(equity_curve)):
        p = equity_curve[j - 1]
        if p > 0:
            s = abs(equity_curve[j] / p - 1)
            if s > max_single_swing:
                max_single_swing = s

    worst_gap = max(gap_slips) if gap_slips else 0.0

    return {
        "total_return":      total_return,
        "max_dd":            max_dd,
        "sharpe":            sharpe,
        "win_rate":          wr,
        "closed_trades":     len(trade_log),
        "entries":           len(entry_log),
        "tp1_fires":         tp1_fires,
        "tp2_fires":         tp2_fires,
        "threeday_fires":    threeday_fires,
        "time_in_cash":      time_in_cash,
        "worst_gap_through_stop": worst_gap,
        "daily_rets":        daily_rets,
        "max_single_swing":  max_single_swing,
        "trade_log":         trade_log,
    }


# ── Date-aligned fetch and merge ──────────────────────────────────────────────

def _build_aligned(ticker_raw: dict, spy_raw: dict) -> tuple[list, list, list, list, list]:
    """
    Intersect ticker and SPY dates. Return aligned arrays.
    Returns (dates, closes, highs, lows, spy_closes).
    """
    spy_map   = {d: i for i, d in enumerate(spy_raw["dates"])}
    tick_map  = {d: i for i, d in enumerate(ticker_raw["dates"])}
    common    = sorted(set(spy_raw["dates"]) & set(ticker_raw["dates"]))
    dates  = common
    closes = [ticker_raw["closes"][tick_map[d]] for d in common]
    highs  = [ticker_raw["highs"][tick_map[d]]  for d in common]
    lows   = [ticker_raw["lows"][tick_map[d]]   for d in common]
    spy_c  = [spy_raw["closes"][spy_map[d]]     for d in common]
    return dates, closes, highs, lows, spy_c


# ── Sharpe pooling ─────────────────────────────────────────────────────────────

def _pooled_sharpe(window_results: dict) -> float:
    pooled = []
    for r in window_results.values():
        if r and "daily_rets" in r:
            pooled.extend(r["daily_rets"])
    if len(pooled) < 2:
        return 0.0
    mu  = sum(pooled) / len(pooled)
    var = sum((r - mu)**2 for r in pooled) / (len(pooled) - 1)
    return (mu / math.sqrt(var) * math.sqrt(252)) if var > 0 else 0.0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 90)
    print("PHASE 1 — PER-ETF BASELINE — FULL HISTORY (Moe strategy, as-deployed)")
    print("Data: Yahoo Finance v8 daily adjClose (Alpaca SIP unavailable on free tier)")
    print("=" * 90)
    print()

    # Determine fetch range: earliest warmup to latest window end
    FETCH_START = datetime.date(2007, 1, 1)   # covers 2008 GFC warmup
    FETCH_END   = datetime.date(2024, 12, 31)

    # Per-ticker first-available dates (from Phase 0 audit, Yahoo confirmed)
    TICKER_FIRST: dict[str, datetime.date] = {
        "SPY": datetime.date(1993, 2, 1),
        "QQQ": datetime.date(1999, 4, 1),
        "EWY": datetime.date(2000, 6, 1),
        "EWT": datetime.date(2000, 7, 1),
        "INDA": datetime.date(2012, 3, 1),
        "EWJ": datetime.date(1996, 4, 1),
        "EWM": datetime.date(1996, 4, 1),
        "VNM": datetime.date(2009, 9, 1),
        "EWZ": datetime.date(2000, 8, 1),
        "EWW": datetime.date(1996, 4, 1),
        "ECH": datetime.date(2007, 12, 1),
        "EEM": datetime.date(2003, 5, 1),
        "EZA": datetime.date(2003, 3, 1),
        "EPOL": datetime.date(2010, 6, 1),
        "GREK": datetime.date(2012, 1, 1),
        "TUR": datetime.date(2008, 4, 1),
    }

    # Fetch SPY once for the full range (crisis gate)
    print("Fetching SPY (crisis gate + US_CORE baseline)…")
    spy_raw = _fetch_yahoo("SPY", FETCH_START, FETCH_END)
    if not spy_raw:
        print("FATAL: cannot fetch SPY — aborting")
        return
    print(f"  SPY: {spy_raw['dates'][0]} → {spy_raw['dates'][-1]} ({len(spy_raw['dates'])} bars)")
    time.sleep(0.5)

    # Fetch all tickers
    raw_data: dict[str, Optional[dict]] = {"SPY": spy_raw}
    all_tickers = [t for t in UNIVERSE_TICKERS if t != "SPY"]
    for ticker in all_tickers:
        first = TICKER_FIRST.get(ticker, FETCH_START)
        fetch_from = max(first, FETCH_START)
        sys.stdout.write(f"  {ticker:<6} ({fetch_from})… ")
        sys.stdout.flush()
        d = _fetch_yahoo(ticker, fetch_from, FETCH_END)
        if d:
            print(f"{d['dates'][0]} → {d['dates'][-1]} ({len(d['dates'])} bars)")
        else:
            print("FAILED")
        raw_data[ticker] = d
        time.sleep(0.4)

    print()

    # ── Per-ticker, per-window backtest ───────────────────────────────────────
    all_results: dict[str, dict[str, Optional[dict]]] = {}

    for ticker in UNIVERSE_TICKERS:
        raw = raw_data.get(ticker)
        if not raw:
            all_results[ticker] = {}
            continue

        # Align with SPY for crisis gate
        dates, closes, highs, lows, spy_c = _build_aligned(raw, spy_raw)

        ticker_results: dict[str, Optional[dict]] = {}
        for label, wstart, wend, warmup_from in WINDOWS:
            # Check coverage: need warmup_from data
            if not dates or dates[0] > wstart:
                ticker_results[label] = None  # skip
                continue

            # Check we have enough data inside the window
            window_bars = [d for d in dates if wstart <= d <= wend]
            if len(window_bars) < 20:
                ticker_results[label] = None
                continue

            r = _run_single_ticker_window(
                closes, highs, lows, dates, spy_c, wstart, wend
            )
            ticker_results[label] = r

        all_results[ticker] = ticker_results

    # ── Print full results table ──────────────────────────────────────────────
    print("=" * 120)
    print("RESULTS TABLE  (source: Yahoo Finance adjClose daily)")
    print(f"{'Ticker':<6}  {'Region':<14}  {'Window':<12}  {'Return':>7}  "
          f"{'MaxDD':>6}  {'Sharpe':>7}  {'WR':>5}  {'Trades':>6}  "
          f"{'InCash':>7}  {'WrstGap':>8}  Flags")
    print("-" * 120)

    for ticker in UNIVERSE_TICKERS:
        region = TICKER_REGION.get(ticker, "?")
        ticker_res = all_results.get(ticker, {})
        if not ticker_res:
            print(f"{ticker:<6}  {region:<14}  NO DATA")
            continue

        for label, wstart, wend, warmup_from in WINDOWS:
            r = ticker_res.get(label)
            if r is None:
                skip_reason = "insufficient data" if TICKER_FIRST.get(ticker, FETCH_START) > wstart else "skip"
                print(f"{ticker:<6}  {region:<14}  {label:<12}  "
                      f"{'SKIP':>7}  {'—':>6}  {'—':>7}  {'—':>5}  {'—':>6}  "
                      f"{'—':>7}  {'—':>8}  ({skip_reason})")
                continue

            sign = "+" if r["total_return"] >= 0 else ""
            flags = []
            if r["max_dd"] >= 0.99:       flags.append("⚠️maxDD≥99%")
            if r["closed_trades"] == 0:   flags.append("⚠️zeroTrades")
            if r["max_single_swing"] > 0.50: flags.append(f"⚠️swing{r['max_single_swing']:.0%}")
            if r["worst_gap_through_stop"] > 0.05: flags.append(f"⚠️gap{r['worst_gap_through_stop']:.1%}")
            em_tag = " EM_BEAR" if label in EM_BEAR_WINDOWS else ""

            print(f"{ticker:<6}  {region:<14}  {label:<12}  "
                  f"{sign}{r['total_return']:>6.1%}  "
                  f"{r['max_dd']:>6.1%}  "
                  f"{r['sharpe']:>7.3f}  "
                  f"{r['win_rate']:>5.0%}  "
                  f"{r['closed_trades']:>6}  "
                  f"{r['time_in_cash']:>7.0%}  "
                  f"{r['worst_gap_through_stop']:>8.2%}  "
                  f"{'  '.join(flags)}{em_tag}")
        print()

    # ── Per-ticker pooled summary ──────────────────────────────────────────────
    print("=" * 90)
    print("PER-TICKER POOLED (across all covered windows)")
    print(f"{'Ticker':<6}  {'Region':<14}  {'PooledSharpe':>12}  "
          f"{'AvgReturn':>10}  {'AvgMaxDD':>9}  {'TotalTrades':>11}  "
          f"{'WindowsCovered':>14}  {'EM_Bear_Avg':>11}")
    print("-" * 90)

    ticker_pooled: dict[str, dict] = {}
    for ticker in UNIVERSE_TICKERS:
        region = TICKER_REGION.get(ticker, "?")
        ticker_res = all_results.get(ticker, {})
        valid_res  = {k: v for k, v in ticker_res.items() if v is not None}
        if not valid_res:
            print(f"{ticker:<6}  {region:<14}  NO DATA")
            continue

        ps = _pooled_sharpe(valid_res)
        avg_ret  = sum(r["total_return"] for r in valid_res.values()) / len(valid_res)
        avg_dd   = sum(r["max_dd"]       for r in valid_res.values()) / len(valid_res)
        tot_trd  = sum(r["closed_trades"] for r in valid_res.values())
        em_res   = {k: v for k, v in valid_res.items() if k in EM_BEAR_WINDOWS}
        em_avg   = (sum(r["total_return"] for r in em_res.values()) / len(em_res)
                    if em_res else float("nan"))

        em_str   = f"{em_avg:+.1%}" if not math.isnan(em_avg) else "N/A"
        s_sign   = "+" if avg_ret >= 0 else ""
        ticker_pooled[ticker] = {"sharpe": ps, "avg_ret": avg_ret, "em_avg": em_avg,
                                 "region": region, "windows": len(valid_res)}

        print(f"{ticker:<6}  {region:<14}  {ps:>12.3f}  "
              f"{s_sign}{avg_ret:>9.1%}  {avg_dd:>9.1%}  {tot_trd:>11}  "
              f"{len(valid_res):>14}  {em_str:>11}")

    # ── Region summary ─────────────────────────────────────────────────────────
    print()
    print("=" * 90)
    print("REGION SUMMARY (avg pooled Sharpe per region)")
    print(f"{'Region':<14}  {'Tickers':<8}  {'AvgPooledSharpe':>15}  {'AvgReturn':>10}  {'EM_Bear_Avg':>11}")
    print("-" * 90)

    from collections import defaultdict
    region_groups: dict[str, list] = defaultdict(list)
    for ticker, data in ticker_pooled.items():
        region_groups[data["region"]].append(data)

    for region in ["US_CORE", "ASIA_PACIFIC", "LATIN_AMERICA", "FRONTIER_EM"]:
        group = region_groups.get(region, [])
        if not group:
            print(f"{region:<14}  (no data)")
            continue
        avg_s   = sum(d["sharpe"]  for d in group) / len(group)
        avg_r   = sum(d["avg_ret"] for d in group) / len(group)
        em_vals = [d["em_avg"] for d in group if not math.isnan(d.get("em_avg", float("nan")))]
        em_str  = f"{sum(em_vals)/len(em_vals):+.1%}" if em_vals else "N/A"
        print(f"{region:<14}  {len(group):<8}  {avg_s:>15.3f}  {avg_r:>+10.1%}  {em_str:>11}")

    # ── EM bear specific breakdown ─────────────────────────────────────────────
    print()
    print("=" * 90)
    print("EM BEAR WINDOW DETAIL — Does trend exit protect or whipsaw?")
    print("(Positive = strategy sat out the selloff; Negative = rode it down or whipsawed)")
    print(f"{'Ticker':<6}  {'Region':<14}  {'2011_EM':>9}  {'2015-16_EM':>11}  {'AvgDD_EMbear':>12}  {'AvgInCash':>10}")
    print("-" * 90)
    for ticker in UNIVERSE_TICKERS:
        region    = TICKER_REGION.get(ticker, "?")
        ticker_res = all_results.get(ticker, {})
        r11  = ticker_res.get("2011_EM")
        r15  = ticker_res.get("2015-16_EM")
        def _fmt(r):
            if r is None: return "  SKIP   "
            s = "+" if r["total_return"] >= 0 else ""
            return f"{s}{r['total_return']:+.1%}/{r['time_in_cash']:.0%}cash"
        avg_dd_em = []
        avg_ic_em = []
        for r in [r11, r15]:
            if r:
                avg_dd_em.append(r["max_dd"])
                avg_ic_em.append(r["time_in_cash"])
        dd_str = f"{sum(avg_dd_em)/len(avg_dd_em):.1%}" if avg_dd_em else "N/A"
        ic_str = f"{sum(avg_ic_em)/len(avg_ic_em):.0%}" if avg_ic_em else "N/A"
        print(f"{ticker:<6}  {region:<14}  {_fmt(r11):>18}  {_fmt(r15):>18}  {dd_str:>12}  {ic_str:>10}")

    # ── Sanity gates ───────────────────────────────────────────────────────────
    print()
    print("=" * 90)
    print("SANITY GATES — flag for inspection")
    print(f"{'Ticker':<6}  {'Window':<12}  {'Trades':>6}  {'MaxSwing':>8}  Status")
    print("-" * 90)
    any_flags = False
    for ticker in UNIVERSE_TICKERS:
        ticker_res = all_results.get(ticker, {})
        for label, *_ in WINDOWS:
            r = ticker_res.get(label)
            if not r:
                continue
            issues = []
            if r["max_dd"] >= 0.99:              issues.append("maxDD≥99%")
            if r["closed_trades"] == 0:          issues.append("ZERO_trades")
            if r["max_single_swing"] > 0.50:     issues.append(f"swing={r['max_single_swing']:.0%}")
            if issues:
                any_flags = True
                print(f"{ticker:<6}  {label:<12}  {r['closed_trades']:>6}  "
                      f"{r['max_single_swing']:>8.1%}  ⚠️  {', '.join(issues)}")
    if not any_flags:
        print("  All windows pass sanity gates — no data-bug indicators detected.")

    print()
    print("FIDELITY NOTES:")
    print("  1. Daily close simulation — stops checked 1×/day (conservative vs live hourly)")
    print("  2. Gap-through-stop is daily-close approximation; true intraday gap risk is larger")
    print("  3. Crisis gate uses SPY 20d return for ALL tickers (matches live params)")
    print("  4. 3-day exit: FIXED last-3-bars-only (closes[-1] vs closes[-4])")
    print("  5. Data source: Yahoo Finance v8 adjClose — Alpaca SIP unavailable (free tier)")
    print("=" * 90)


if __name__ == "__main__":
    main()
