"""Forex shadows (roadmap Phase 1): FX-BT1 baseline and a simple currency trend.

Pure, like every league strategy. Bars are OANDA daily mid candles, one bar per
New York forex day (17:00 to 17:00), labelled with the date the day closes.
The view holds each pair under its OANDA name (EUR_USD, USD_JPY, ...); weights
are signed shares of equity on the US-dollar-priced instrument the twins
engine trades (EUR_USD, JPY_USD, ...): long USD_JPY = negative JPY_USD.

FX-BT1 is path-dependent (entries, stops fixed at entry), so its target walks
the rule forward from the shadow's first day (ctx.start) on daily bars:
  1. stops: a holding whose day's low (long) / high (short) reached its stop is closed;
  2. exits: a holding whose call changed is closed;
  3. entries: flat pairs with a long/short call, strongest first, up to 4 open,
     each sized to lose 0.5% of equity at its stop (2 x ATR14 from the entry
     close), total gross at most 2x.
Same order and numbers as kraken-bot/forex_baseline_backtest.py (FX-BT1).
Known differences (stated in the registration): a stop is seen at the day's
close and filled at the next open, not at the stop price; entry is the close,
not the ask/bid; sizes are kept as shares of equity, not as fixed units.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from research_harness.harness.portfolio import HistoryView
from research_harness.league.base import Call, Context, ann_vol, closes, has_today, sma

PAIRS = ("EUR_USD", "USD_JPY", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD")
TREND_SMA_DAYS = 100        # forex_quant_desk constants (FX-BT1); test_league_forex checks they match
MOMENTUM_DAYS = 63
ATR_DAYS = 14
STOP_ATR_MULTIPLE = 2.0
RISK_PER_TRADE = 0.005
MAX_OPEN = 4
GROSS_CAP = 2.0
WARMUP = TREND_SMA_DAYS + 1


def synthetic(pair: str) -> str:
    """Same mapping as twins.engine.synthetic (that module may not be imported here)."""
    base, quote = pair.split("_")
    return pair if quote == "USD" else f"{quote}_{base}"


def signed_weight(pair: str, direction: str, w: float) -> tuple[str, float]:
    """A long or short in the OANDA pair as a signed weight on its synthetic."""
    sign = 1.0 if direction == "long" else -1.0
    if synthetic(pair) != pair:          # USD_XXX: long the pair = short XXX
        sign = -sign
    return synthetic(pair), sign * w


def signal(bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """FX-BT1's call, ATR and strength at the last bar (needs WARMUP + 1 bars)."""
    if len(bars) < WARMUP + 1:
        return None
    c = [b["close"] for b in bars]
    close, avg = c[-1], sum(c[-TREND_SMA_DAYS:]) / TREND_SMA_DAYS
    mom = close / c[-1 - MOMENTUM_DAYS] - 1
    trs = [max(bars[j]["high"] - bars[j]["low"], abs(bars[j]["high"] - c[j - 1]), abs(bars[j]["low"] - c[j - 1]))
           for j in range(len(bars) - ATR_DAYS, len(bars))]
    atr = sum(trs) / ATR_DAYS
    call = "long" if close > avg and mom > 0 else "short" if close < avg and mom < 0 else "flat"
    return {"call": call, "atr": atr, "strength": abs(mom) / (atr / close) if atr else 0.0, "close": close}


def currency_exposure(pos: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Net exposure to each currency, as a multiple of equity: a long EUR_USD of w is +w EUR and -w USD."""
    out: dict[str, float] = {}
    for pair, q in pos.items():
        base, quote = pair.split("_")
        s = q["w"] if q["dir"] == "long" else -q["w"]
        out[base] = out.get(base, 0.0) + s
        out[quote] = out.get(quote, 0.0) - s
    return out


def capped_size(pos: dict[str, dict[str, Any]], pair: str, direction: str, w: float, cap: float) -> float:
    """The largest size up to ``w`` that keeps every currency's net exposure within ``cap`` (0 = skip)."""
    base, quote = pair.split("_")
    s = 1.0 if direction == "long" else -1.0
    now = currency_exposure(pos)
    room = w
    for cur, sign in ((base, s), (quote, -s)):
        have = now.get(cur, 0.0)
        room = min(room, cap - have if sign > 0 else cap + have)
    return max(0.0, room)


def bt1_positions(view: HistoryView, start: date, trail: list | None = None,
                  currency_cap: float | None = None) -> dict[str, dict[str, Any]]:
    """Walk FX-BT1 from ``start`` to view.today; the open positions at today's close.
    ``trail`` (tests) collects every closed holding: (pair, dir, entry_day, exit_day, reason).
    ``currency_cap`` (FX-BT1-CAP, AU13): a new entry is cut so no currency's net exposure passes it."""
    today = view.today
    hist = {p: [b for b in view.bars(p)] for p in PAIRS if p in view.symbols()}
    days = sorted({b["day"] for rows in hist.values() for b in rows if start <= b["day"] <= today})
    idx = {p: {b["day"]: i for i, b in enumerate(rows)} for p, rows in hist.items()}
    pos: dict[str, dict[str, Any]] = {}
    for day in days:
        sig = {}
        for p, rows in hist.items():
            i = idx[p].get(day)
            if i is not None:
                sig[p] = (rows[i], signal(rows[: i + 1]))
        for p in list(pos):                                   # 1. stops
            if p not in sig:
                continue
            bar, q = sig[p][0], pos[p]
            if (q["dir"] == "long" and bar["low"] <= q["stop"]) or (q["dir"] == "short" and bar["high"] >= q["stop"]):
                _close(pos, p, day, "stop", trail)
        for p in list(pos):                                   # 2. call changed
            s = sig.get(p, (None, None))[1]
            if s is not None and s["call"] != pos[p]["dir"]:
                _close(pos, p, day, "signal", trail)
        cands = sorted(((s["strength"], p, s) for p, (_, s) in sig.items()
                        if s is not None and s["call"] != "flat" and p not in pos), reverse=True)
        for _, p, s in cands:                                 # 3. entries
            if len(pos) >= MAX_OPEN:
                break
            dist = STOP_ATR_MULTIPLE * s["atr"]
            if dist <= 0:
                continue
            w = RISK_PER_TRADE * s["close"] / dist            # notional / equity (same for XXX_USD and USD_XXX)
            room = GROSS_CAP - sum(q["w"] for q in pos.values())
            if room <= 1e-9:
                break
            w = min(w, room)
            if currency_cap is not None:
                w = capped_size(pos, p, s["call"], w, currency_cap)
                if w <= 1e-9:
                    continue                                  # this currency is full: try the next pair
            pos[p] = {"dir": s["call"], "w": w, "entry_day": day, "entry": s["close"],
                      "stop": s["close"] - dist if s["call"] == "long" else s["close"] + dist}
    return pos


def _close(pos: dict[str, dict[str, Any]], pair: str, day: date, reason: str, trail: list | None) -> None:
    q = pos.pop(pair)
    if trail is not None:
        trail.append((pair, q["dir"], q["entry_day"], day, reason))


CURRENCY_CAP = 1.5          # FX-BT1-CAP: Markus 21 Nov 2026 07:02 Brisbane ("1.5, not 1")


def _fx_bt1(view: HistoryView, ctx: Context, currency_cap: float | None = None) -> Call | None:
    if ctx.start is None or not any(has_today(view, p) for p in PAIRS):
        return None
    if any(len(closes(view, p, WARMUP + 1)) < WARMUP + 1 for p in PAIRS if has_today(view, p)):
        return None
    pos = bt1_positions(view, ctx.start, currency_cap=currency_cap)
    weights = dict(signed_weight(p, q["dir"], q["w"]) for p, q in pos.items())
    state = tuple(sorted((p, q["dir"], q["entry_day"].isoformat()) for p, q in pos.items()))
    note = {p: {"dir": q["dir"], "stop": round(q["stop"], 6), "entry": round(q["entry"], 6)} for p, q in pos.items()}
    return Call(weights, state=state, note={"open": note})


TREND_VOL_TARGET = 0.10      # each pair sized to 10% a year volatility, divided by the 7 pairs
TREND_VOL_DAYS = 63


def _fx_trend(view: HistoryView, ctx: Context) -> Call | None:
    """Always in every pair: long when the close is above its 100-day average,
    short when below; each sized 0.10 / its 63-day volatility / 7; gross capped
    at 2x (scaled down). First session of each month and on any direction change."""
    if not all(has_today(view, p) for p in PAIRS):
        return None
    dirs, raw = {}, {}
    for p in PAIRS:
        c = closes(view, p, TREND_SMA_DAYS + TREND_VOL_DAYS)
        avg, vol = sma(c, TREND_SMA_DAYS), ann_vol(c, TREND_VOL_DAYS)
        if avg is None or vol is None:
            return None
        dirs[p] = "long" if c[-1] > avg else "short"
        raw[p] = TREND_VOL_TARGET / vol / len(PAIRS)
    scale = min(1.0, GROSS_CAP / sum(raw.values()))
    weights = dict(signed_weight(p, dirs[p], raw[p] * scale) for p in PAIRS)
    return Call(weights, state=tuple(sorted(dirs.items())))


def _fx_bt1_cap(view: HistoryView, ctx: Context) -> Call | None:
    return _fx_bt1(view, ctx, currency_cap=CURRENCY_CAP)


def bars_from_daily_candles(candles: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """OANDA daily mid candles -> view bars per pair (OANDA name) AND per
    synthetic instrument (inverted for USD_XXX), labelled with the New York
    date each forex day closes (the candle opens 17:00 New York the day before)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    out: dict[str, list[dict[str, Any]]] = {}
    for pair, rows in candles.items():
        mine, inv = {}, {}
        for c in rows:
            opened = datetime.fromisoformat(str(c["time"])[:19]).replace(tzinfo=ZoneInfo("UTC")).astimezone(ny)
            day = (opened + timedelta(hours=24)).date()        # 17:00 day X -> closes 17:00 day X+1
            m = c["mid"]
            o, h, lo, cl = (float(m[k]) for k in ("o", "h", "l", "c"))
            if min(o, h, lo, cl) <= 0 or h < max(o, cl, lo) or lo > min(o, cl):
                continue                                  # a bad candle is left out, not repaired
            mine[day] = {"day": day, "open": o, "high": h, "low": lo, "close": cl}
            inv[day] = {"day": day, "open": 1 / o, "high": 1 / lo, "low": 1 / h, "close": 1 / cl}
        out[pair] = [mine[d] for d in sorted(mine)]
        if synthetic(pair) != pair:
            out[synthetic(pair)] = [inv[d] for d in sorted(inv)]
    return out
