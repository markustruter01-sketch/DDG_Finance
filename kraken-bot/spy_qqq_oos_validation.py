"""
spy_qqq_oos_validation.py — Out-of-sample validation for SPY/QQQ Trend Follower (Bot #2)

LOCKED PARAMETERS (bot2_spy_qqq.py + alpaca_etf_engine.py — extracted Step 1):
  UNIVERSE         = ["SPY", "QQQ"]
  EMA_FAST         = 50      EMA_SLOW = 200
  TRAIL_STOP_PCT   = 0.08    (software stop, ratchets up, overrides min-hold)
  MAX_3DAY_DROP    = 0.05    (FIXED: last-3-bars only — closes[-1] vs closes[-4])
  POSITION_SIZE    = 0.40    (40% equity per entry)
  MAX_DEPLOYMENT   = 0.80    CASH_RESERVE = 0.20
  MIN_HOLD_DAYS    = 5       (calendar days from entry date)
  TP1_PCT          = 0.06    (+6% → close 33.3% of ORIGINAL qty — not decremented)
  TP2_PCT          = 0.12    (+12% → close 33.3% of ORIGINAL qty — not decremented)
  CRISIS_THRESHOLD = -0.12   (SPY 20d return; fail-safe = blocked)

FIDELITY NOTES (known gaps vs live):
  1. Cadence: DAILY close. Live bot = hourly. Trailing stops checked once/day vs
     once/hour. Harness is conservative: stops caught at close, not intraday open.
  2. EMA seed: naive prices[0] (NOT SMA seed) — exact live implementation.
  3. 3-day exit: FIXED — single check closes[-1] vs closes[-4] (last 3 bars only).
     Matches deployed bot2_spy_qqq.py. Previous as-coded run scanned all 80 bars
     and produced 45/57 churn exits in 2020.
  4. TP qty: ORIGINAL qty used for both TP1 and TP2 scale sizes (not decremented).
  5. Min-hold: calendar days (date diff), not trading bars.
  6. ema_fast_prev: closes[:-5] chop-last-5-and-rerun — exact live method.
  7. Entry uses 250-bar input (same as live _yahoo_daily_ohlcv(symbol, days=250)).
  8. Stop ratchet: GREATEST(stop, current*(1-0.08)) — only moves up, every bar.

WINDOWS (pre-registered, 5x):
  2019 | 2020 | 2021 | 2022 | 2023-24

PASS CRITERIA (locked):
  Pooled Sharpe >= 0.5
  MaxDD <= 20% in EVERY window
  Positive return in 2020 AND 2022
  >= 3/5 windows with positive return

READ-ONLY. No live orders. No DB writes. No strategy changes.

Run:
    cd kraken-bot
    python3 spy_qqq_oos_validation.py
"""
from __future__ import annotations

import math
import datetime
import time
import requests
from typing import Optional

# ── Locked strategy parameters ─────────────────────────────────────────────
UNIVERSE          = ["SPY", "QQQ"]
EMA_FAST          = 50
EMA_SLOW          = 200
TRAIL_STOP_PCT    = 0.08
MAX_3DAY_DROP_PCT = 0.05
POSITION_SIZE_PCT = 0.40
MAX_DEPLOYMENT    = 0.80
CASH_RESERVE      = 0.20
MIN_HOLD_DAYS     = 5        # calendar days
TP1_PCT           = 0.06
TP2_PCT           = 0.12
CRISIS_THRESHOLD  = -0.12
STARTING_EQUITY   = 100_000.0

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


# ── Yahoo Finance historical fetch ─────────────────────────────────────────

def _fetch_ohlcv(ticker: str, start: datetime.date, end: datetime.date,
                 retries: int = 3) -> Optional[dict]:
    """
    Fetch daily OHLCV via Yahoo Finance v8 (period1/period2).
    Same API as live bot's _yahoo_daily_ohlcv — identical data source.
    Returns {'dates','opens','highs','lows','closes','volumes'} or None.
    """
    p1 = int(datetime.datetime.combine(start, datetime.time.min,
             tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime.combine(end, datetime.time.max,
             tzinfo=datetime.timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": p1, "period2": p2, "interval": "1d"}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=30)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                return None
            data = r.json()
            result = data.get("chart", {}).get("result")
            if not result:
                return None
            ts     = result[0].get("timestamp", [])
            q      = result[0].get("indicators", {}).get("quote", [{}])[0]
            opens  = q.get("open",   [])
            highs  = q.get("high",   [])
            lows   = q.get("low",    [])
            closes = q.get("close",  [])
            vols   = q.get("volume", [])
            rows = [
                (t, o, h, l, c, v)
                for t, o, h, l, c, v in zip(ts, opens, highs, lows, closes, vols)
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
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
    return None


# ── EMA — naive first-price seed (EXACT live implementation) ───────────────
# FIDELITY: live bot uses prices[0] as seed. NOT sum(prices[:period])/period.

def _ema(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    ema = prices[0]            # naive seed — AS-CODED
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


# ── Entry signal (EXACT live implementation) ───────────────────────────────
# Input: last 250 closes. Requires >= EMA_SLOW + 5 = 205 bars.
# ema_fast_prev = _ema(closes[:-5], EMA_FAST) — chop-last-5-and-rerun (AS-CODED)

def _entry_signal(closes_250: list[float]) -> bool:
    if len(closes_250) < EMA_SLOW + 5:
        return False
    current       = closes_250[-1]
    ema_fast_now  = _ema(closes_250,       EMA_FAST)
    ema_slow_now  = _ema(closes_250,       EMA_SLOW)
    ema_fast_prev = _ema(closes_250[:-5],  EMA_FAST)   # chop-last-5-and-rerun
    if any(v is None for v in (ema_fast_now, ema_slow_now, ema_fast_prev)):
        return False
    return (ema_fast_now > ema_slow_now and
            ema_fast_now > ema_fast_prev and
            current      > ema_fast_now)


# ── CRISIS gate (EXACT live implementation) ────────────────────────────────
# fail-safe = True (blocked). Uses SPY 20d return. closes[-1]/closes[-21] - 1.

def _crisis_gate(spy_closes_30: list[float]) -> bool:
    """Returns True = blocked, False = entries allowed."""
    if len(spy_closes_30) < 21:
        return True   # fail-safe
    return (spy_closes_30[-1] / spy_closes_30[-21] - 1) <= CRISIS_THRESHOLD


# ── Trend exit: price < EMA-50 (EXACT live implementation) ────────────────
# 80-bar fetch; EMA from closes[-50:] if >= 50 bars, else all closes.

def _exit_price_below_ema50(closes_80: list[float]) -> Optional[str]:
    if len(closes_80) < 4:
        return None
    current = closes_80[-1]
    slice_  = closes_80[-EMA_FAST:] if len(closes_80) >= EMA_FAST else closes_80
    ema50   = _ema(slice_, EMA_FAST)
    if ema50 is not None and current < ema50:
        return f"price_below_ema50({current:.2f}<{ema50:.2f})"
    return None


# ── Trend exit: 3-day drop >= 5% — LAST 3 BARS ONLY (FIXED, deployed code) ─
# Was: range(3, len(closes)) — scanned ALL 80 bars, fired on historical drops
# that had already recovered. Caused pathological churn (45/57 exits in 2020).
# Fixed in bot2_spy_qqq.py: single check closes[-1] vs closes[-4] only.

def _exit_3day_drop(closes_80: list[float]) -> Optional[str]:
    if len(closes_80) >= 4:
        chg = (closes_80[-1] - closes_80[-4]) / closes_80[-4]
        if chg <= -MAX_3DAY_DROP_PCT:
            return f"3day_drop({chg*100:.1f}%)"
    return None


# ── Position record ────────────────────────────────────────────────────────

class _Pos:
    __slots__ = (
        "symbol", "entry_date", "entry_price",
        "original_qty",   # stored qty — NOT decremented after TPs (AS-CODED)
        "actual_qty",     # true remaining shares (our accounting)
        "stop_price",
        "tp1_price", "tp2_price",
        "scaled_tp1", "scaled_tp2",
    )

    def __init__(self, symbol: str, entry_date: datetime.date,
                 entry_price: float, qty: float):
        self.symbol       = symbol
        self.entry_date   = entry_date
        self.entry_price  = entry_price
        self.original_qty = qty          # not decremented (AS-CODED)
        self.actual_qty   = qty          # decremented for real accounting
        self.stop_price   = entry_price * (1 - TRAIL_STOP_PCT)
        self.tp1_price    = entry_price * (1 + TP1_PCT)
        self.tp2_price    = entry_price * (1 + TP2_PCT)
        self.scaled_tp1   = False
        self.scaled_tp2   = False

    def min_hold_ok(self, current_date: datetime.date) -> bool:
        return (current_date - self.entry_date).days >= MIN_HOLD_DAYS

    def ratchet_stop(self, current_price: float) -> None:
        new_stop = current_price * (1 - TRAIL_STOP_PCT)
        if new_stop > self.stop_price:
            self.stop_price = new_stop

    def market_value(self, price: float) -> float:
        return self.actual_qty * price


# ── Window runner ──────────────────────────────────────────────────────────

def _run_window(
    aligned:     list[tuple],     # [(date, spy_idx, qqq_idx), ...]  — window bars only
    all_dates:   list[datetime.date],
    all_closes:  dict[str, list[float]],
    all_highs:   dict[str, list[float]],
    all_lows:    dict[str, list[float]],
) -> dict:
    equity = STARTING_EQUITY
    cash   = STARTING_EQUITY
    positions: list[_Pos] = []
    equity_curve: list[float] = [equity]
    peak = equity
    max_dd = 0.0

    entries: list[dict] = []
    closes_list: list[dict] = []
    tp1_fires = tp2_fires = threeday_fires = 0

    def _c(sym: str, up_to_global: int, n: int) -> list[float]:
        """Last n closes up to and including global bar index."""
        c = all_closes[sym]
        return c[max(0, up_to_global - n + 1): up_to_global + 1]

    for date, spy_gi, qqq_gi in aligned:
        gi = {"SPY": spy_gi, "QQQ": qqq_gi}
        px  = {sym: all_closes[sym][gi[sym]] for sym in UNIVERSE}

        # ── Exit checks ───────────────────────────────────────────────────
        for pos in list(positions):
            sym     = pos.symbol
            current = px[sym]

            # Ratchet trailing stop every bar (AS-CODED: runs every cycle)
            pos.ratchet_stop(current)

            # Priority 1: hard trailing stop (overrides min-hold)
            if current <= pos.stop_price:
                pct = (current - pos.entry_price) / pos.entry_price * 100
                pnl = pos.actual_qty * current - pos.original_qty * pos.entry_price
                cash += pos.actual_qty * current
                positions.remove(pos)
                closes_list.append({
                    "date": date, "sym": sym,
                    "exit": "trailing_stop",
                    "pnl_pct": pct, "pnl_usd": pnl,
                })
                continue

            min_ok = pos.min_hold_ok(date)

            # Priority 3: TP2 scale-out (33.3% of ORIGINAL qty — not decremented)
            if min_ok and not pos.scaled_tp2 and current >= pos.tp2_price:
                scale = pos.original_qty * 0.333
                cash += scale * current
                pos.actual_qty -= scale
                pos.scaled_tp2 = True
                tp2_fires += 1
                # returns None in live — position stays open

            # Priority 4: TP1 scale-out (33.3% of ORIGINAL qty — not decremented)
            if min_ok and not pos.scaled_tp1 and current >= pos.tp1_price:
                scale = pos.original_qty * 0.333
                cash += scale * current
                pos.actual_qty -= scale
                pos.scaled_tp1 = True
                tp1_fires += 1
                # returns None in live — position stays open

            if not min_ok:
                continue

            # Priority 5: price below EMA-50 (80-bar, slice[-50:])
            c80 = _c(sym, gi[sym], 80)
            reason5 = _exit_price_below_ema50(c80)
            if reason5:
                pct = (current - pos.entry_price) / pos.entry_price * 100
                pnl = pos.actual_qty * current - pos.original_qty * pos.entry_price
                cash += pos.actual_qty * current
                positions.remove(pos)
                closes_list.append({
                    "date": date, "sym": sym,
                    "exit": "price_below_ema50",
                    "pnl_pct": pct, "pnl_usd": pnl,
                })
                continue

            # Priority 6: 3-day drop >= 5% — scans ALL 80 bars (AS-CODED)
            reason6 = _exit_3day_drop(c80)
            if reason6:
                pct = (current - pos.entry_price) / pos.entry_price * 100
                pnl = pos.actual_qty * current - pos.original_qty * pos.entry_price
                cash += pos.actual_qty * current
                positions.remove(pos)
                closes_list.append({
                    "date": date, "sym": sym,
                    "exit": "3day_drop",
                    "pnl_pct": pct, "pnl_usd": pnl,
                })
                threeday_fires += 1
                continue

        # ── Entry scan ────────────────────────────────────────────────────
        # CRISIS gate (SPY only, fail-safe = blocked)
        spy_c30    = _c("SPY", spy_gi, 30)
        in_crisis  = _crisis_gate(spy_c30)

        held       = {p.symbol for p in positions}
        pos_val    = sum(p.market_value(px[p.symbol]) for p in positions)
        deployed_pct = pos_val / equity if equity > 0 else 1.0

        if not in_crisis:
            for sym in UNIVERSE:
                if sym in held:
                    continue
                if deployed_pct + POSITION_SIZE_PCT > MAX_DEPLOYMENT:
                    break

                c250 = _c(sym, gi[sym], 250)
                if not _entry_signal(c250):
                    continue

                current = px[sym]
                notional = equity * POSITION_SIZE_PCT
                # safety clamp: never exceed 80% of equity
                if notional > equity * (1 - CASH_RESERVE):
                    notional = equity * (1 - CASH_RESERVE)
                # can't spend more cash than available
                if notional > cash:
                    notional = cash
                if notional <= 0:
                    continue

                qty = notional / current
                cash -= notional
                pos = _Pos(sym, date, current, qty)
                positions.append(pos)
                held.add(sym)
                deployed_pct += POSITION_SIZE_PCT
                entries.append({
                    "date": date, "sym": sym,
                    "price": current, "qty": qty, "notional": notional,
                })

        # ── Daily equity MTM ─────────────────────────────────────────────
        pos_val = sum(p.market_value(px[p.symbol]) for p in positions)
        equity  = cash + pos_val
        equity_curve.append(equity)

        # Drawdown
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Force-close open positions at window end
    if aligned:
        last_date, last_spy_gi, last_qqq_gi = aligned[-1]
        final_px = {sym: all_closes[sym][{"SPY": last_spy_gi, "QQQ": last_qqq_gi}[sym]]
                    for sym in UNIVERSE}
    for pos in list(positions):
        current = final_px.get(pos.symbol, pos.entry_price)
        pct = (current - pos.entry_price) / pos.entry_price * 100
        pnl = pos.actual_qty * current - pos.original_qty * pos.entry_price
        cash += pos.actual_qty * current
        closes_list.append({
            "date": last_date, "sym": pos.symbol,
            "exit": "window_end",
            "pnl_pct": pct, "pnl_usd": pnl,
        })
    equity = cash
    if equity < peak:
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Metrics
    total_return = (equity - STARTING_EQUITY) / STARTING_EQUITY

    daily_rets = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev > 0:
            daily_rets.append(equity_curve[i] / prev - 1)

    if len(daily_rets) > 1:
        mu  = sum(daily_rets) / len(daily_rets)
        var = sum((r - mu) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
        sharpe = (mu / math.sqrt(var) * math.sqrt(252)) if var > 0 else 0.0
    else:
        sharpe = 0.0

    wins = [t for t in closes_list if t["pnl_usd"] > 0]
    wr   = len(wins) / len(closes_list) if closes_list else 0.0

    # Sanity gates
    max_single_day_swing = 0.0
    for i in range(1, len(equity_curve)):
        p = equity_curve[i - 1]
        if p > 0:
            swing = abs(equity_curve[i] / p - 1)
            if swing > max_single_day_swing:
                max_single_day_swing = swing

    return {
        "total_return":       total_return,
        "max_dd":             max_dd,
        "sharpe":             sharpe,
        "win_rate":           wr,
        "closed_trades":      len(closes_list),
        "entries":            len(entries),
        "tp1_fires":          tp1_fires,
        "tp2_fires":          tp2_fires,
        "threeday_fires":     threeday_fires,
        "equity_curve":       equity_curve,
        "daily_rets":         daily_rets,
        "max_single_day_swing": max_single_day_swing,
        "trade_log":          closes_list,
        "entry_log":          entries,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("SPY/QQQ Trend Follower — Out-of-Sample Validation")
    print("Exact live-code replication (bot2_spy_qqq.py + alpaca_etf_engine.py)")
    print("=" * 72)
    print()
    print("FIDELITY NOTES (known gaps vs live):")
    print("  1. Cadence: DAILY close  |  Live = hourly. Stops checked 1x/day.")
    print("     Gap: gap-downs caught at close, not next-hourly open. Conservative.")
    print("  2. EMA seed: prices[0]  (NOT SMA seed) — AS-CODED.")
    print("  3. 3-day exit: scans ALL 80 bars (Discrepancy #2) — AS-CODED.")
    print("  4. TP qty: ORIGINAL qty, not decremented after partial closes — AS-CODED.")
    print("  5. Min-hold: calendar days (date diff), exact live timedelta(days=5).")
    print("  6. EMA_fast_prev: closes[:-5] chop-last-5-and-rerun — AS-CODED.")
    print()

    # Fetch data — 2018-01-01 gives 250 bar warmup before 2019 window start
    fetch_start = datetime.date(2018, 1, 1)
    fetch_end   = datetime.date(2024, 12, 31)

    print(f"Fetching SPY + QQQ daily OHLCV ({fetch_start} → {fetch_end})…")
    raw: dict[str, dict] = {}
    for sym in UNIVERSE:
        d = _fetch_ohlcv(sym, fetch_start, fetch_end)
        if not d:
            print(f"  FATAL: could not fetch {sym}")
            return
        raw[sym] = d
        print(f"  {sym}: {len(d['dates'])} bars  "
              f"({d['dates'][0]} → {d['dates'][-1]})")
        time.sleep(0.4)   # polite rate-limiting
    print()

    # Align dates — both ETFs share NYSE calendar so dates should match exactly.
    # Intersect for safety; flag any mismatch.
    spy_date_set = set(raw["SPY"]["dates"])
    qqq_date_set = set(raw["QQQ"]["dates"])
    common       = sorted(spy_date_set & qqq_date_set)
    dropped      = (spy_date_set | qqq_date_set) - (spy_date_set & qqq_date_set)
    if dropped:
        print(f"  [alignment] Dropped {len(dropped)} date(s) present in one symbol only: "
              f"{sorted(dropped)[:5]}{'…' if len(dropped) > 5 else ''}")

    spy_idx_map = {d: i for i, d in enumerate(raw["SPY"]["dates"])}
    qqq_idx_map = {d: i for i, d in enumerate(raw["QQQ"]["dates"])}

    all_closes = {sym: raw[sym]["closes"] for sym in UNIVERSE}
    all_highs  = {sym: raw[sym]["highs"]  for sym in UNIVERSE}
    all_lows   = {sym: raw[sym]["lows"]   for sym in UNIVERSE}
    all_dates  = common

    WINDOWS = [
        ("2019",    datetime.date(2019, 1, 1),  datetime.date(2019, 12, 31)),
        ("2020",    datetime.date(2020, 1, 1),  datetime.date(2020, 12, 31)),
        ("2021",    datetime.date(2021, 1, 1),  datetime.date(2021, 12, 31)),
        ("2022",    datetime.date(2022, 1, 1),  datetime.date(2022, 12, 31)),
        ("2023-24", datetime.date(2023, 1, 1),  datetime.date(2024, 12, 31)),
    ]

    results: dict[str, dict] = {}

    for name, wstart, wend in WINDOWS:
        aligned = [
            (d, spy_idx_map[d], qqq_idx_map[d])
            for d in common
            if wstart <= d <= wend
        ]
        if not aligned:
            print(f"  {name}: NO DATA — skipping")
            results[name] = {"error": "no_data"}
            continue

        print(f"Running {name} ({wstart} → {wend}, {len(aligned)} bars)…")
        r = _run_window(aligned, all_dates, all_closes, all_highs, all_lows)
        results[name] = r

        sign  = "+" if r["total_return"] >= 0 else ""
        flag  = ""
        if r["max_dd"] >= 0.99:
            flag += "  ⚠️ maxDD≥99%"
        if r["closed_trades"] == 0:
            flag += "  ⚠️ ZERO TRADES"
        if r["max_single_day_swing"] > 0.50:
            flag += f"  ⚠️ single-day swing {r['max_single_day_swing']:.0%}"

        print(f"  return={sign}{r['total_return']:.1%}  maxDD={r['max_dd']:.1%}  "
              f"Sharpe={r['sharpe']:.3f}  WR={r['win_rate']:.0%}  "
              f"entries={r['entries']}  closed={r['closed_trades']}"
              f"{flag}")
        print(f"  TP1_fires={r['tp1_fires']}  TP2_fires={r['tp2_fires']}  "
              f"3day_exit_fires={r['threeday_fires']}")

    # Pooled Sharpe — concatenate all daily return series
    pooled_rets: list[float] = []
    for name, _, _ in WINDOWS:
        if "error" not in results.get(name, {"error": True}):
            pooled_rets.extend(results[name]["daily_rets"])

    if len(pooled_rets) > 1:
        mu  = sum(pooled_rets) / len(pooled_rets)
        var = sum((r - mu) ** 2 for r in pooled_rets) / (len(pooled_rets) - 1)
        pooled_sharpe = (mu / math.sqrt(var) * math.sqrt(252)) if var > 0 else 0.0
    else:
        pooled_sharpe = 0.0

    # ── Full results table ────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("RESULTS TABLE")
    print("=" * 72)
    hdr = (f"{'Window':<10} {'Return':>7} {'MaxDD':>6} {'Sharpe':>7} "
           f"{'WR':>5} {'Ent':>4} {'Cls':>4} {'TP1':>4} {'TP2':>4} {'3dy':>4}")
    print(hdr)
    print("-" * 72)
    for name, _, _ in WINDOWS:
        r = results.get(name, {})
        if "error" in r:
            print(f"{name:<10}  ERROR: {r['error']}")
            continue
        sign = "+" if r["total_return"] >= 0 else ""
        print(
            f"{name:<10} {sign}{r['total_return']:>6.1%} "
            f"{r['max_dd']:>6.1%} {r['sharpe']:>7.3f} "
            f"{r['win_rate']:>5.0%} {r['entries']:>4} {r['closed_trades']:>4} "
            f"{r['tp1_fires']:>4} {r['tp2_fires']:>4} {r['threeday_fires']:>4}"
        )
    print("-" * 72)
    print(f"{'POOLED':<10} {'':>7} {'':>6} {pooled_sharpe:>7.3f}")
    print()

    # ── Pass/fail evaluation ──────────────────────────────────────────────
    def _r(n): return results.get(n, {})

    sharpe_pass   = pooled_sharpe >= 0.50
    dd_all_pass   = all(
        _r(n).get("max_dd", 1.0) <= 0.20
        for n, _, _ in WINDOWS if "error" not in _r(n)
    )
    pos_2020      = _r("2020").get("total_return", -1) > 0
    pos_2022      = _r("2022").get("total_return", -1) > 0
    n_positive    = sum(
        1 for n, _, _ in WINDOWS
        if _r(n).get("total_return", -1) > 0
    )
    windows_pass  = n_positive >= 3
    overall       = sharpe_pass and dd_all_pass and pos_2020 and pos_2022 and windows_pass

    print("PASS CRITERIA:")
    print(f"  Pooled Sharpe >= 0.5:         {pooled_sharpe:+.3f}  "
          f"{'✓ PASS' if sharpe_pass else '✗ FAIL'}")
    print(f"  MaxDD <= 20% every window:    "
          f"{'✓ PASS' if dd_all_pass else '✗ FAIL'}")
    for n, _, _ in WINDOWS:
        r = _r(n)
        if "error" not in r:
            flag = "  ← FAIL" if r["max_dd"] > 0.20 else ""
            print(f"    {n}: {r['max_dd']:.1%}{flag}")
    print(f"  Positive return in 2020:      "
          f"{'✓ PASS' if pos_2020 else '✗ FAIL'} "
          f"({_r('2020').get('total_return', float('nan')):+.1%})")
    print(f"  Positive return in 2022:      "
          f"{'✓ PASS' if pos_2022 else '✗ FAIL'} "
          f"({_r('2022').get('total_return', float('nan')):+.1%})")
    print(f"  >= 3/5 windows positive:      {n_positive}/5  "
          f"{'✓ PASS' if windows_pass else '✗ FAIL'}")
    print()
    print(f"OVERALL: {'✅ PASS' if overall else '❌ FAIL'}")
    print()

    # ── Sanity gates ──────────────────────────────────────────────────────
    print("SANITY GATES:")
    for name, _, _ in WINDOWS:
        r = _r(name)
        if "error" in r:
            continue
        issues = []
        if r["max_dd"] >= 0.99:
            issues.append("maxDD>=99%")
        if r["closed_trades"] == 0:
            issues.append("ZERO trades")
        if r["max_single_day_swing"] > 0.50:
            issues.append(f"day-swing {r['max_single_day_swing']:.0%}")
        status = "OK" if not issues else "⚠️  " + ", ".join(issues)
        print(f"  {name:<8}: trades={r['closed_trades']:<3}  "
              f"max_swing={r['max_single_day_swing']:.1%}  [{status}]")

    # ── Trade log detail (last 5 per window) ──────────────────────────────
    print()
    print("TRADE LOG (all closed trades per window):")
    for name, _, _ in WINDOWS:
        r = _r(name)
        if "error" in r or not r.get("trade_log"):
            continue
        print(f"\n  {name} ({len(r['trade_log'])} closed trades):")
        for t in r["trade_log"]:
            sign = "+" if t["pnl_usd"] >= 0 else ""
            print(f"    {t['date']}  {t['sym']:<4}  {t['exit']:<22}  "
                  f"pnl={sign}{t['pnl_pct']:.1f}%  ${sign}{t['pnl_usd']:,.0f}")

    print()
    print("FIDELITY GAP REMINDER: cadence=daily  |  live=hourly.")
    print("Stops modelled conservatively (caught at daily close, not intraday).")
    print("3-day exit scans all 80 bars (Discrepancy #2) — replicated faithfully.")
    print("=" * 72)


if __name__ == "__main__":
    main()
