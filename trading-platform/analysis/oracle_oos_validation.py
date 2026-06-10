"""
Oracle OOS Validation Harness
==============================
Pass A — Baseline Oracle (EMA/ADX/ATR/Kelly), no MSE, no cooldowns.
Pass B — Oracle + MSE policy (Phase 2, after Pass A calibration).

Data source : Yahoo Finance v8 API (direct HTTP — yfinance library broken in env)
Warmup      : 60 trading days before each window start
Starting $  : $100,000 per window
Fee model   : none (Alpaca paper, no commissions)

Strategy constants mirror algo_scanner.py exactly — no tuning allowed.
"""

from __future__ import annotations

import json
import math
import os
import pickle
import statistics
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

# ── Strategy constants (must match algo_scanner.py exactly) ───────────────────
EMA_FAST         = 20
EMA_SLOW         = 50
ADX_PERIOD       = 14
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.0      # stop = ATR × 2.0 from entry
TRAIL_TRIGGER    = 2.5      # trailing activates after profit ≥ ATR × 2.5
RISK_PER_TRADE   = 0.015    # 1.5% of equity at risk per trade (heat cap)
MAX_POSITION_PCT = 0.20     # hard cap 20% per position
LONG_RSI_LOW     = 40.0
LONG_RSI_HIGH    = 75.0
SHORT_RSI_LOW    = 25.0
SHORT_RSI_HIGH   = 60.0
MOMENTUM_DAYS    = 10
ADX_ENTRY_MIN    = 25.0
ADX_EXIT_MIN     = 20.0
MAX_LONG_SLOTS   = 5
MAX_SHORT_SLOTS  = 2
MAX_HOLD_DAYS    = 15       # calendar trading days
MIN_BARS_NEEDED  = EMA_SLOW + 5  # 55 — minimum history to compute EMA50

STARTING_EQUITY  = 100_000.0
WARMUP_DAYS      = 60       # trading days before window start for indicator warmup

# ── OOS Windows ───────────────────────────────────────────────────────────────
OOS_WINDOWS = [
    {"name": "2019",    "start": date(2019, 1,  1),  "end": date(2019, 12, 31)},
    {"name": "2020",    "start": date(2020, 1,  1),  "end": date(2020, 12, 31)},
    {"name": "2021",    "start": date(2021, 1,  1),  "end": date(2021, 12, 31)},
    {"name": "2022",    "start": date(2022, 1,  1),  "end": date(2022, 12, 31)},
    {"name": "2023-24", "start": date(2023, 1,  1),  "end": date(2024, 12, 31)},
]

# Full data range — Alpaca IEX available from ~2020-07.
# 60 trading-day warmup for the 2021 window start needs data from ~2020-09.
# Setting DATA_START = 2020-06-01 gives ~130 warmup bars by Jan 2021 (plenty).
# 2019 and 2020 windows are UNAVAILABLE with IEX; only 2021, 2022, 2023-24 run.
DATA_START = date(2020, 6, 1)
DATA_END   = date(2024, 12, 31)

CACHE_DIR  = Path(__file__).parent.parent / ".local" / "oos_data"

# ── Technical indicator functions (exact copies from algo_scanner.py) ─────────

def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k   = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
    return ema


def _adx(
    highs:  list[float],
    lows:   list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    if len(highs) < period * 2 + 1:
        return 0.0
    try:
        plus_dm:  list[float] = []
        minus_dm: list[float] = []
        trs:      list[float] = []
        for i in range(1, len(highs)):
            up   = highs[i]  - highs[i - 1]
            down = lows[i - 1] - lows[i]
            plus_dm.append(up   if (up > down   and up   > 0) else 0.0)
            minus_dm.append(down if (down > up   and down > 0) else 0.0)
            hl  = highs[i]  - lows[i]
            hpc = abs(highs[i]  - closes[i - 1])
            lpc = abs(lows[i]   - closes[i - 1])
            trs.append(max(hl, hpc, lpc))

        def _smooth(series: list[float], p: int) -> list[float]:
            r = [sum(series[:p]) / p]
            for v in series[p:]:
                r.append(r[-1] - r[-1] / p + v)
            return r

        sm_tr  = _smooth(trs,      period)
        sm_pdm = _smooth(plus_dm,  period)
        sm_mdm = _smooth(minus_dm, period)

        di_plus  = [(sm_pdm[i] / sm_tr[i] * 100) if sm_tr[i] > 0 else 0.0
                    for i in range(len(sm_tr))]
        di_minus = [(sm_mdm[i] / sm_tr[i] * 100) if sm_tr[i] > 0 else 0.0
                    for i in range(len(sm_tr))]

        dx_list: list[float] = []
        for i in range(len(di_plus)):
            denom = di_plus[i] + di_minus[i]
            dx_list.append(
                abs(di_plus[i] - di_minus[i]) / denom * 100 if denom > 0 else 0.0
            )

        if len(dx_list) < period:
            return 0.0
        return min(100.0, max(0.0, sum(dx_list[-period:]) / period))
    except Exception:
        return 0.0


def _atr(
    highs:  list[float],
    lows:   list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    if len(highs) < period + 1:
        return (highs[-1] - lows[-1]) if len(highs) > 1 else 0.0
    trs: list[float] = []
    for i in range(1, len(highs)):
        hl  = highs[i]  - lows[i]
        hpc = abs(highs[i]  - closes[i - 1])
        lpc = abs(lows[i]   - closes[i - 1])
        trs.append(max(hl, hpc, lpc))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder-smoothed RSI.  Returns None if insufficient data."""
    if len(closes) < period + 2:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_gain = sum(max(0.0, d) for d in deltas[:period]) / period
    avg_loss = sum(max(0.0, -d) for d in deltas[:period]) / period
    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(0.0,  d)) / period
        avg_loss = (avg_loss * (period - 1) + max(0.0, -d)) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ── Indicator series pre-computation (O(N) per ticker, call once per window) ──
# These replace the per-day O(N) indicator calls with O(1) index look-ups.

def _ema_series(closes: list, period: int) -> list:
    """EMA causal series; None until `period` bars available."""
    n = len(closes)
    out = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    out[period - 1] = ema
    for i in range(period, n):
        ema = closes[i] * k + ema * (1.0 - k)
        out[i] = ema
    return out


def _atr_series(highs: list, lows: list, closes: list, period: int = 14) -> list:
    """Wilder's ATR causal series."""
    n = len(highs)
    out = [None] * n
    if n < 2:
        return out
    trs = []
    for i in range(1, n):
        hl  = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i]  - closes[i - 1])
        trs.append(max(hl, hpc, lpc))
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period] = atr
    for j in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[j]) / period
        out[j + 1] = atr
    return out


def _rsi_series(closes: list, period: int = 14) -> list:
    """Wilder's RSI causal series."""
    n = len(closes)
    out = [None] * n
    if n < period + 2:
        return out
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    ag = sum(max(0.0,  d) for d in deltas[:period]) / period
    al = sum(max(0.0, -d) for d in deltas[:period]) / period
    def _v(ag, al):
        if al == 0.0: return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)
    out[period] = _v(ag, al)
    for j in range(period, len(deltas)):
        d = deltas[j]
        ag = (ag * (period - 1) + max(0.0,  d)) / period
        al = (al * (period - 1) + max(0.0, -d)) / period
        out[j + 1] = _v(ag, al)
    return out


def _adx_series(highs: list, lows: list, closes: list, period: int = 14) -> list:
    """ADX causal series matching _adx() point-in-time logic (simple avg of last period DX)."""
    n = len(highs)
    out = [None] * n
    if n < period * 2 + 1:
        return out
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up   if (up   > down and up   > 0) else 0.0)
        minus_dm.append(down if (down > up   and down > 0) else 0.0)
        hl  = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i]  - closes[i - 1])
        trs.append(max(hl, hpc, lpc))

    def _smooth_wilder(series, p):
        r = [sum(series[:p]) / p]
        for v in series[p:]:
            r.append(r[-1] - r[-1] / p + v)
        return r

    sm_tr  = _smooth_wilder(trs,      period)
    sm_pdm = _smooth_wilder(plus_dm,  period)
    sm_mdm = _smooth_wilder(minus_dm, period)

    dx_list = []
    for k in range(len(sm_tr)):
        dip = (sm_pdm[k] / sm_tr[k] * 100) if sm_tr[k] > 0 else 0.0
        dim = (sm_mdm[k] / sm_tr[k] * 100) if sm_tr[k] > 0 else 0.0
        den = dip + dim
        dx_list.append(abs(dip - dim) / den * 100 if den > 0 else 0.0)

    # Sliding window average of last `period` DX values
    win_sum = 0.0
    win: list = []
    for k, dx in enumerate(dx_list):
        win.append(dx)
        win_sum += dx
        if len(win) > period:
            win_sum -= win[-period - 1]
        if len(win) >= period:
            bar_i = period + k
            if bar_i < n:
                out[bar_i] = min(100.0, max(0.0, win_sum / period))
    return out


def precompute_indicators(universe_data: dict) -> dict:
    """
    Pre-compute all indicator series for every ticker in O(N) per ticker.
    Call once before simulate_window's main loop; then use ind_cache[t][key][idx]
    instead of calling _ema/_adx/_atr/_rsi on slices on every trading day.
    """
    cache = {}
    for ticker, data in universe_data.items():
        c = data["closes"]
        h = data["highs"]
        lo = data["lows"]
        n  = len(c)
        cache[ticker] = {
            "ema20":  _ema_series(c, EMA_FAST),
            "ema50":  _ema_series(c, EMA_SLOW),
            "atr":    _atr_series(h, lo, c, ATR_PERIOD),
            "adx":    _adx_series(h, lo, c, ADX_PERIOD),
            "rsi":    _rsi_series(c, 14),
            "ret10d": [
                None if i < MOMENTUM_DAYS else c[i] / c[i - MOMENTUM_DAYS] - 1.0
                for i in range(n)
            ],
        }
    return cache


# ── Yahoo Finance v8 data fetcher ─────────────────────────────────────────────

_YF_SESSION:  requests.Session | None = None
_YF_CRUMB:    str | None = None
_YF_INIT_LOCK = False


def _init_yf_session() -> bool:
    """
    Initialise the Yahoo Finance session: load cookies then grab crumb.
    Must be called once before any _yf_fetch_raw() calls.
    Returns True on success.
    """
    global _YF_SESSION, _YF_CRUMB, _YF_INIT_LOCK
    if _YF_SESSION and _YF_CRUMB:
        return True
    if _YF_INIT_LOCK:
        return False
    _YF_INIT_LOCK = True

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })

    # Step 1: load Yahoo Finance homepage to get consent cookie
    for _ in range(2):
        try:
            r = sess.get("https://fc.yahoo.com", timeout=10, allow_redirects=True)
            break
        except Exception:
            time.sleep(1)
    try:
        sess.get("https://finance.yahoo.com/", timeout=10)
    except Exception:
        pass

    # Step 2: fetch crumb
    sess.headers.update({"Accept": "application/json, text/plain, */*"})
    crumb = None
    for attempt in range(3):
        try:
            r = sess.get(
                "https://query2.finance.yahoo.com/v1/test/getcrumb",
                timeout=10,
            )
            if r.status_code == 200 and r.text.strip():
                crumb = r.text.strip()
                break
        except Exception:
            pass
        time.sleep(1.0)

    if not crumb:
        # Fallback: try query1 endpoint
        try:
            r = sess.get(
                "https://query1.finance.yahoo.com/v1/test/getcrumb",
                timeout=10,
            )
            if r.status_code == 200 and r.text.strip():
                crumb = r.text.strip()
        except Exception:
            pass

    if crumb:
        _YF_SESSION = sess
        _YF_CRUMB   = crumb
        _YF_INIT_LOCK = False
        return True

    _YF_INIT_LOCK = False
    return False


def _parse_yf_response(r: requests.Response) -> dict | None:
    """Parse a Yahoo Finance v8 chart response into our standard OHLCV dict."""
    try:
        data = r.json()
    except Exception:
        return None
    result = data.get("chart", {}).get("result")
    if not result:
        return None
    result = result[0]
    timestamps = result.get("timestamp", [])
    if not timestamps:
        return None
    quotes    = result["indicators"]["quote"][0]
    adj_close = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])

    rows_dates:   list[str]   = []
    rows_opens:   list[float] = []
    rows_highs:   list[float] = []
    rows_lows:    list[float] = []
    rows_closes:  list[float] = []
    rows_volumes: list[float] = []

    for i, ts in enumerate(timestamps):
        try:
            adj_c = adj_close[i] if adj_close and i < len(adj_close) else None
            raw_c = quotes["close"][i]
            if raw_c is None or adj_c is None:
                continue
            adj_factor = adj_c / raw_c if raw_c != 0 else 1.0
            rows_dates.append(datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"))
            rows_opens.append(  (quotes["open"][i]  or raw_c) * adj_factor)
            rows_highs.append(  (quotes["high"][i]  or raw_c) * adj_factor)
            rows_lows.append(   (quotes["low"][i]   or raw_c) * adj_factor)
            rows_closes.append( adj_c)
            rows_volumes.append(quotes["volume"][i] or 0.0)
        except (TypeError, IndexError, ZeroDivisionError):
            continue

    if not rows_dates:
        return None
    order = sorted(range(len(rows_dates)), key=lambda k: rows_dates[k])
    return {
        "dates":   [rows_dates[k]   for k in order],
        "opens":   [rows_opens[k]   for k in order],
        "highs":   [rows_highs[k]   for k in order],
        "lows":    [rows_lows[k]    for k in order],
        "closes":  [rows_closes[k]  for k in order],
        "volumes": [rows_volumes[k] for k in order],
    }


def _yf_fetch_raw(ticker: str, start: date, end: date) -> dict | None:
    """
    Fetch daily adjusted OHLCV from Yahoo Finance v8 chart API.
    Requires prior call to _init_yf_session().
    Returns None on failure or insufficient data.
    """
    global _YF_CRUMB
    if not _YF_SESSION or not _YF_CRUMB:
        return None

    start_ts = int(datetime(start.year, start.month, start.day).timestamp())
    end_ts   = int(datetime(end.year,   end.month,   end.day,  23, 59).timestamp())
    url    = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "period1":             start_ts,
        "period2":             end_ts,
        "interval":            "1d",
        "events":              "div,splits",
        "includeAdjustedClose": "true",
        "crumb":               _YF_CRUMB,
    }

    for attempt in range(4):
        try:
            r = _YF_SESSION.get(url, params=params, timeout=15)
            if r.status_code == 404:
                return None     # delisted / unknown symbol
            if r.status_code == 429:
                wait = 2.0 * (attempt + 1)
                time.sleep(wait)
                continue
            if r.status_code == 401:
                # Crumb expired — reinitialise once
                _YF_CRUMB = None
                if _init_yf_session():
                    params["crumb"] = _YF_CRUMB
                continue
            r.raise_for_status()
            result = _parse_yf_response(r)
            return result
        except requests.exceptions.HTTPError:
            raise
        except Exception as exc:
            if attempt < 3:
                time.sleep(1.0 * (attempt + 1))
            else:
                print(f"    YF fetch failed {ticker}: {exc}")
                return None
    return None


# ── Alpaca IEX data fetcher (primary source) ──────────────────────────────────
# Alpaca IEX: available from ~2020-07-01, covers 2021/2022/2023-24 OOS windows.
# adjustment=all applies split + dividend adjustments (c, o, h, l are adjusted).
# Yahoo Finance (secondary) requires a crumb session; rate-limited by IP in CI envs.

_ALPACA_KEY    = os.environ.get("ALPACA_API_KEY",    "")
_ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
_ALPACA_DATA   = "https://data.alpaca.markets"


def _alpaca_fetch_raw(ticker: str, start: date, end: date) -> dict | None:
    """
    Fetch daily adjusted OHLCV from Alpaca IEX.
    Returns {dates, opens, highs, lows, closes, volumes} or None on failure.
    Prices are fully adjusted (split + dividend) via adjustment=all.
    """
    if not _ALPACA_KEY or not _ALPACA_SECRET:
        return None

    headers = {
        "APCA-API-KEY-ID":     _ALPACA_KEY,
        "APCA-API-SECRET-KEY": _ALPACA_SECRET,
    }
    params: dict[str, Any] = {
        "symbols":    ticker,
        "timeframe":  "1Day",
        "start":      start.isoformat(),
        "end":        end.isoformat(),
        "adjustment": "all",
        "feed":       "iex",
        "limit":      10_000,
    }

    all_bars: list[dict] = []
    for attempt in range(3):
        try:
            while True:
                r = requests.get(
                    f"{_ALPACA_DATA}/v2/stocks/bars",
                    headers=headers,
                    params=params,
                    timeout=20,
                )
                if r.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    break
                if r.status_code != 200:
                    return None
                body = r.json()
                bars = body.get("bars", {}).get(ticker, [])
                all_bars.extend(bars)
                npt = body.get("next_page_token")
                if not npt:
                    break
                params["page_token"] = npt
            if all_bars:
                break
        except Exception as exc:
            if attempt < 2:
                time.sleep(1.0)
            else:
                print(f"    Alpaca fetch failed {ticker}: {exc}")
                return None

    if not all_bars:
        return None

    all_bars.sort(key=lambda b: b["t"])
    return {
        "dates":   [b["t"][:10]  for b in all_bars],
        "opens":   [float(b["o"]) for b in all_bars],
        "highs":   [float(b["h"]) for b in all_bars],
        "lows":    [float(b["l"]) for b in all_bars],
        "closes":  [float(b["c"]) for b in all_bars],
        "volumes": [float(b["v"]) for b in all_bars],
    }


def _fetch_ticker(ticker: str, start: date, end: date) -> dict | None:
    """
    Try Alpaca IEX first (fast, no rate-limit issues).
    Fall back to Yahoo Finance if Alpaca unavailable.
    """
    data = _alpaca_fetch_raw(ticker, start, end)
    if data and len(data["dates"]) >= MIN_BARS_NEEDED:
        return data
    # Fallback: YF (only if session already initialised; don't block here)
    if _YF_SESSION and _YF_CRUMB:
        data = _yf_fetch_raw(ticker, start, end)
        if data and len(data["dates"]) >= MIN_BARS_NEEDED:
            return data
    return None


def load_universe_data(
    tickers: list[str],
    start:   date = DATA_START,
    end:     date = DATA_END,
    verbose: bool = True,
) -> dict[str, dict]:
    """
    Load OHLCV data for all tickers, using disk cache when available.
    Primary: Alpaca IEX (data from 2020-07).
    Fallback: Yahoo Finance (if YF session already active).
    Returns {ticker: {dates, opens, highs, lows, closes, volumes}}.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"universe_{start}_{end}.pkl"

    if cache_file.exists():
        if verbose:
            print(f"  Loading from cache: {cache_file}")
        with open(cache_file, "rb") as f:
            return pickle.load(f)

    if not _ALPACA_KEY:
        raise RuntimeError("ALPACA_API_KEY not set — cannot fetch data")

    if verbose:
        print(f"  Fetching {len(tickers)} tickers via Alpaca IEX "
              f"({start} → {end}) …")

    universe_data: dict[str, dict] = {}
    missing: list[str] = []

    for i, ticker in enumerate(tickers):
        data = _fetch_ticker(ticker, start, end)
        if data:
            universe_data[ticker] = data
        else:
            missing.append(ticker)
        if verbose and (i + 1) % 25 == 0:
            print(f"    {i + 1}/{len(tickers)} fetched "
                  f"({len(universe_data)} ok, {len(missing)} missing) …")
        time.sleep(0.12)   # ~120ms — well inside Alpaca's 200 req/min limit

    if verbose:
        print(f"  Done: {len(universe_data)}/{len(tickers)} tickers loaded")
        if missing:
            print(f"  Missing/insufficient: {missing}")

    with open(cache_file, "wb") as f:
        pickle.dump(universe_data, f)
    return universe_data


# ── Simulation engine ─────────────────────────────────────────────────────────

def _compute_signals(
    universe_data: dict,
    bar_idx:       dict,   # ticker → current bar index in its data
    open_symbols:  set,
    equity:        float,
    ind_cache:     dict,   # pre-computed indicator series from precompute_indicators()
) -> tuple:
    """
    Compute entry signals for all tickers at bar_idx[ticker].
    Uses pre-computed ind_cache for O(1) indicator look-ups (vs O(N) recompute).
    Returns (long_candidates, short_candidates) sorted by ADX desc, ema_spread tiebreaker.
    """
    long_cands:  list = []
    short_cands: list = []

    for ticker, data in universe_data.items():
        idx = bar_idx.get(ticker, -1)
        if idx < MIN_BARS_NEEDED:
            continue
        if ticker in open_symbols:
            continue

        ind = ind_cache.get(ticker)
        if ind is None or idx >= len(data["closes"]):
            continue

        ema20  = ind["ema20"][idx]
        ema50  = ind["ema50"][idx]
        atr    = ind["atr"][idx]
        adx    = ind["adx"][idx]
        rsi    = ind["rsi"][idx]
        ret10d = ind["ret10d"][idx]

        if any(v is None for v in (ema20, ema50, atr, adx, rsi, ret10d)):
            continue
        if ema20 == ema50 or atr <= 0 or adx < ADX_ENTRY_MIN:
            continue

        price          = data["closes"][idx]
        ema_spread_pct = (ema20 - ema50) / ema50 * 100.0

        if ema20 > ema50:
            if (LONG_RSI_LOW <= rsi <= LONG_RSI_HIGH
                    and ret10d > 0
                    and price > ema20):
                long_cands.append({
                    "ticker":     ticker,
                    "price":      price,
                    "atr":        atr,
                    "adx":        adx,
                    "ema_spread": ema_spread_pct,
                    "side":       "long",
                })
        else:
            if (SHORT_RSI_LOW <= rsi <= SHORT_RSI_HIGH
                    and ret10d < 0
                    and price < ema20):
                short_cands.append({
                    "ticker":     ticker,
                    "price":      price,
                    "atr":        atr,
                    "adx":        adx,
                    "ema_spread": ema_spread_pct,
                    "side":       "short",
                })

    long_cands.sort( key=lambda x: (x["adx"], abs(x["ema_spread"])), reverse=True)
    short_cands.sort(key=lambda x: (x["adx"], abs(x["ema_spread"])), reverse=True)
    return long_cands, short_cands


def _check_exits(
    positions:     dict,
    universe_data: dict,
    bar_idx:       dict,
    trade_day_n:   int,              # trading-day index within the window
    ind_cache:     dict,             # pre-computed indicator series
) -> tuple:
    """
    Update trailing stops and check exit conditions for all open positions.
    Returns (updated_positions, closed_trades).
    """
    to_close: list[str] = []
    closed_trades: list[dict] = []

    for ticker, pos in positions.items():
        idx = bar_idx.get(ticker, -1)
        if idx < 0 or idx >= len(universe_data[ticker]["closes"]):
            continue

        data       = universe_data[ticker]
        open_p     = data["opens"][idx]
        high_p     = data["highs"][idx]
        low_p      = data["lows"][idx]
        close_p    = data["closes"][idx]
        side       = pos["side"]
        entry_p    = pos["entry_price"]
        atr_e      = pos["atr_at_entry"]
        stop_p     = pos["stop_price"]
        best_p     = pos["best_price"]
        entry_day  = pos["entry_day"]
        hold_days  = trade_day_n - entry_day

        # ── Update best price ─────────────────────────────────────────────────
        if side == "long":
            best_p = max(best_p, high_p)
        else:
            best_p = min(best_p, low_p)
        pos["best_price"] = best_p

        # ── Trailing stop update ──────────────────────────────────────────────
        profit_ticks = (best_p - entry_p) if side == "long" else (entry_p - best_p)
        if profit_ticks >= atr_e * TRAIL_TRIGGER:
            pos["trailing_active"] = True

        if pos["trailing_active"]:
            if side == "long":
                new_trail = best_p - atr_e * ATR_MULTIPLIER
                pos["stop_price"] = max(stop_p, new_trail)
            else:
                new_trail = best_p + atr_e * ATR_MULTIPLIER
                pos["stop_price"] = min(stop_p, new_trail)
            stop_p = pos["stop_price"]

        # ── Exit conditions ───────────────────────────────────────────────────
        exit_reason = None
        exit_price  = None

        # 1. Gap through stop at open
        if side == "long" and open_p <= stop_p:
            exit_reason = "stop_gapdown"
            exit_price  = open_p
        elif side == "short" and open_p >= stop_p:
            exit_reason = "stop_gapup"
            exit_price  = open_p

        # 2. Stop hit intraday
        if exit_reason is None:
            if side == "long" and low_p <= stop_p:
                exit_reason = "stop"
                exit_price  = stop_p
            elif side == "short" and high_p >= stop_p:
                exit_reason = "stop"
                exit_price  = stop_p

        # 3. Signal-based exits (use close; honour minimum-hold = 1 day)
        if exit_reason is None and hold_days >= 1:
            ind = ind_cache.get(ticker)
            ema20_now = ind["ema20"][idx] if ind else None
            ema50_now = ind["ema50"][idx] if ind else None
            adx_now   = ind["adx"][idx]   if ind else None

            if ema20_now is not None and ema50_now is not None:
                if side == "long" and ema20_now < ema50_now:
                    exit_reason = "ema_cross"
                    exit_price  = close_p
                elif side == "short" and ema20_now > ema50_now:
                    exit_reason = "ema_cross"
                    exit_price  = close_p

            if exit_reason is None and adx_now is not None and adx_now < ADX_EXIT_MIN:
                exit_reason = "adx_fade"
                exit_price  = close_p

        # 4. Max hold
        if exit_reason is None and hold_days >= MAX_HOLD_DAYS:
            exit_reason = "max_hold"
            exit_price  = close_p

        # 5. Forced cover (short): price > 2× entry → collateral fully consumed (≡ margin call)
        if exit_reason is None and side == "short" and close_p >= 2.0 * entry_p:
            exit_reason = "forced_cover"
            exit_price  = close_p

        if exit_reason:
            shares = pos["shares"]
            # P&L capped model: long = (exit-entry)×shares; short = max((entry-exit)×shares, -entry×shares)
            if side == "long":
                pnl = (exit_price - entry_p) * shares
            else:
                pnl = max((entry_p - exit_price) * shares, -entry_p * shares)
            closed_trades.append({
                "ticker":       ticker,
                "side":         side,
                "entry_price":  entry_p,
                "exit_price":   exit_price,
                "shares":       shares,
                "pnl":          pnl,
                "hold_days":    hold_days,
                "exit_reason":  exit_reason,
            })
            to_close.append(ticker)

    for ticker in to_close:
        pos = positions.pop(ticker)
        # Return notional back to cash (managed outside — caller handles equity)

    return positions, closed_trades


def simulate_window(
    universe_data:  dict[str, dict],
    window_start:   date,
    window_end:     date,
    window_name:    str,
    verbose:        bool = False,
) -> dict:
    """
    Simulate the Oracle strategy over one OOS window.

    Returns dict with per-window metrics:
      sharpe, max_dd, win_rate, n_trades, equity_curve,
      daily_returns, trades, missing_tickers, coverage_pct
    """
    # Build a sorted master list of all trading dates in [window_start, window_end]
    # Use the SPY calendar as the reference (SPY is in FULL_UNIVERSE)
    spy_data = universe_data.get("SPY")
    if spy_data is None:
        print(f"  [{window_name}] ERROR: SPY data missing — cannot build trading calendar")
        return {}

    all_dates_str = spy_data["dates"]
    ws = window_start.strftime("%Y-%m-%d")
    we = window_end.strftime("%Y-%m-%d")
    window_dates = [d for d in all_dates_str if ws <= d <= we]

    if not window_dates:
        print(f"  [{window_name}] No trading days found in range {ws} → {we}")
        return {}

    # Build bar_idx for each ticker → date → index in that ticker's data array
    ticker_date_idx: dict[str, dict[str, int]] = {}
    for ticker, data in universe_data.items():
        ticker_date_idx[ticker] = {d: i for i, d in enumerate(data["dates"])}

    # Coverage stats: how many tickers have data on the first actual trading day?
    first_trading_day = window_dates[0] if window_dates else ws
    tickers_with_data = [
        t for t in universe_data
        if first_trading_day in ticker_date_idx.get(t, {})
    ]
    coverage_pct = len(tickers_with_data) / max(len(universe_data), 1) * 100
    missing_at_start = [t for t in universe_data if t not in tickers_with_data]

    if verbose:
        print(f"  [{window_name}] {len(window_dates)} trading days  "
              f"coverage {coverage_pct:.0f}% ({len(tickers_with_data)}/{len(universe_data)} tickers)")

    # ── Pre-compute indicator series (O(N·T) once vs O(N·W·T) without cache) ──
    ind_cache = precompute_indicators(universe_data)

    # ── Simulation state ──────────────────────────────────────────────────────
    equity:    float        = STARTING_EQUITY
    cash:      float        = STARTING_EQUITY
    positions: dict         = {}          # ticker → position dict
    equity_curve: list      = []
    all_trades:   list      = []
    # Carry-forward: last bar index with real data, per ticker.
    # IEX coverage gaps cause some tickers to skip certain dates even when SPY
    # (our trading calendar) has a bar.  Without carry-forward, open positions
    # on gap days are silently excluded from MTM → equity collapses to cash.
    last_known_bar: dict    = {}

    for day_n, day_str in enumerate(window_dates):
        # fresh_bar: tickers that actually have data for today
        # (used for exit/entry logic — OHLC must be current-day)
        fresh_bar: dict = {}
        for ticker in universe_data:
            idx = ticker_date_idx[ticker].get(day_str, -1)
            if idx >= 0:
                fresh_bar[ticker] = idx
                last_known_bar[ticker] = idx   # update carry-forward

        # mtm_bar: fresh data where available, last-known close otherwise
        # (used only for MTM equity — carries forward price on data-gap days)
        mtm_bar: dict = {**fresh_bar}
        for ticker in positions:
            if ticker not in mtm_bar and ticker in last_known_bar:
                mtm_bar[ticker] = last_known_bar[ticker]

        # ── 1. Exit checks ────────────────────────────────────────────────────
        # Accounting model — collateral model (consistent for longs and shorts):
        #   Entry (both):  cash -= entry_price × shares  (capital reserved)
        #   Exit (long):   cash += exit_price × shares
        #   Exit (short):  cash += max(0, (2×entry − exit) × shares)
        #     — capped at 0 so loss never exceeds initial collateral (≡ margin call)
        #   MTM (long):    value = close × shares
        #   MTM (short):   value = max(0, (2×entry − close) × shares)
        # Use fresh_bar for exits: stale OHLC would falsely trigger stops.
        positions, closed = _check_exits(positions, universe_data, fresh_bar, day_n, ind_cache)
        for trade in closed:
            if trade["side"] == "long":
                cash += trade["exit_price"] * trade["shares"]
            else:
                cash += max(0.0, (2.0 * trade["entry_price"] - trade["exit_price"])
                             * trade["shares"])
        all_trades.extend(closed)

        # ── 2. Mark-to-market equity ──────────────────────────────────────────
        # Rebuild mtm_bar post-exits (closed positions removed from positions)
        mtm_bar = {**fresh_bar}
        for ticker in positions:
            if ticker not in mtm_bar and ticker in last_known_bar:
                mtm_bar[ticker] = last_known_bar[ticker]

        pos_value = 0.0
        for ticker, pos in list(positions.items()):
            idx = mtm_bar.get(ticker, -1)
            if idx < 0:
                continue
            close_p = universe_data[ticker]["closes"][idx]
            if pos["side"] == "long":
                pos_value += close_p * pos["shares"]
            else:
                # Short MTM: capped at 0 — max loss = initial collateral
                pos_value += max(0.0, (2.0 * pos["entry_price"] - close_p) * pos["shares"])
        equity = cash + pos_value
        equity_curve.append(equity)

        # ── 3. Entry signals ──────────────────────────────────────────────────
        n_longs  = sum(1 for p in positions.values() if p["side"] == "long")
        n_shorts = sum(1 for p in positions.values() if p["side"] == "short")
        avail_long  = MAX_LONG_SLOTS  - n_longs
        avail_short = MAX_SHORT_SLOTS - n_shorts

        if avail_long > 0 or avail_short > 0:
            long_cands, short_cands = _compute_signals(
                universe_data, fresh_bar, set(positions.keys()), equity, ind_cache
            )
            entries = (
                [(c, "long")  for c in long_cands[:avail_long]]
                + [(c, "short") for c in short_cands[:avail_short]]
            )
            for cand, side in entries:
                ticker  = cand["ticker"]
                price   = cand["price"]
                atr     = cand["atr"]

                risk_amount    = equity * RISK_PER_TRADE
                stop_dist      = atr * ATR_MULTIPLIER
                if stop_dist <= 0:
                    continue
                shares_raw     = risk_amount / stop_dist
                position_value = shares_raw * price
                kelly_frac     = min(position_value / equity, MAX_POSITION_PCT)
                position_value = kelly_frac * equity
                shares         = position_value / price

                if shares <= 0 or position_value > cash:
                    continue  # insufficient cash

                stop_price = (
                    price - atr * ATR_MULTIPLIER if side == "long"
                    else price + atr * ATR_MULTIPLIER
                )

                positions[ticker] = {
                    "side":             side,
                    "entry_price":      price,
                    "shares":           shares,
                    "atr_at_entry":     atr,
                    "stop_price":       stop_price,
                    "best_price":       price,
                    "trailing_active":  False,
                    "entry_day":        day_n,
                }
                if side == "long":
                    cash -= position_value
                else:
                    # Short: hold collateral equal to position value aside
                    cash -= position_value

    # ── Force-close any open positions at window end (at last close) ──────────
    last_day_str = window_dates[-1]
    last_bar: dict[str, int] = {}
    for ticker in universe_data:
        idx = ticker_date_idx[ticker].get(last_day_str, -1)
        if idx >= 0:
            last_bar[ticker] = idx

    for ticker, pos in list(positions.items()):
        idx = last_bar.get(ticker, -1)
        if idx < 0:
            continue
        close_p = universe_data[ticker]["closes"][idx]
        shares  = pos["shares"]
        entry_p = pos["entry_price"]
        side    = pos["side"]
        if side == "long":
            pnl = (close_p - entry_p) * shares
        else:
            pnl = max((entry_p - close_p) * shares, -entry_p * shares)
        all_trades.append({
            "ticker":      ticker,
            "side":        side,
            "entry_price": entry_p,
            "exit_price":  close_p,
            "shares":      shares,
            "pnl":         pnl,
            "hold_days":   len(window_dates) - pos["entry_day"],
            "exit_reason": "window_end",
        })

    # ── Metrics ───────────────────────────────────────────────────────────────
    if len(equity_curve) < 2:
        return {
            "window": window_name, "sharpe": 0.0, "max_dd": 0.0,
            "win_rate": 0.0, "n_trades": 0, "error": "insufficient_data",
        }

    daily_returns = [
        (equity_curve[i] / equity_curve[i - 1] - 1)
        for i in range(1, len(equity_curve))
    ]

    mean_ret = statistics.mean(daily_returns)
    std_ret  = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 1e-9
    sharpe   = (mean_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0.0

    peak_eq  = STARTING_EQUITY
    max_dd   = 0.0
    for eq in equity_curve:
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq
        if dd > max_dd:
            max_dd = dd

    closed_trades = [t for t in all_trades if t["exit_reason"] != "window_end"]
    wins     = [t for t in all_trades if t["pnl"] > 0]
    win_rate = len(wins) / len(all_trades) if all_trades else 0.0
    final_eq = equity_curve[-1]
    total_ret = (final_eq - STARTING_EQUITY) / STARTING_EQUITY

    return {
        "window":          window_name,
        "start":           ws,
        "end":             we,
        "trading_days":    len(window_dates),
        "sharpe":          round(sharpe,   4),
        "max_dd":          round(max_dd,   4),
        "win_rate":        round(win_rate, 4),
        "n_trades":        len(all_trades),
        "total_return":    round(total_ret, 4),
        "final_equity":    round(final_eq, 2),
        "equity_curve":    equity_curve,
        "daily_returns":   daily_returns,
        "trades":          all_trades,
        "coverage_pct":    round(coverage_pct, 1),
        "missing_at_start": missing_at_start[:20],  # cap list for readability
    }


# ── Pass A: Baseline calibration ──────────────────────────────────────────────

def run_pass_a(verbose: bool = True) -> list[dict]:
    """
    Pass A — Oracle baseline, no MSE.

    Target: pooled Sharpe ≈ 0.156 (prior OOS run).
    Tolerance for calibration check: ±0.05 (i.e. 0.106 – 0.206).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from execution.momentum_universe import FULL_UNIVERSE

    # ── Data source check ─────────────────────────────────────────────────────
    if not _ALPACA_KEY:
        print("ERROR: ALPACA_API_KEY not set — cannot fetch data.")
        return []

    # ── Data loading ──────────────────────────────────────────────────────────
    print("=" * 65)
    print("ORACLE OOS VALIDATION — PASS A (BASELINE CALIBRATION)")
    print("=" * 65)
    print(f"Universe  : {len(FULL_UNIVERSE)} tickers (FULL_UNIVERSE)")
    print(f"Data range: {DATA_START} → {DATA_END}")
    print(f"Data src  : Alpaca IEX (adjustment=all; available from ~2020-07)")
    print(f"Note      : 2019/2020 windows SKIPPED — IEX data unavailable for warmup")
    print(f"Cache dir : {CACHE_DIR}")
    print()

    universe_data = load_universe_data(FULL_UNIVERSE, DATA_START, DATA_END, verbose=True)
    print(f"\nLoaded: {len(universe_data)}/{len(FULL_UNIVERSE)} tickers\n")

    missing_global = [t for t in FULL_UNIVERSE if t not in universe_data]
    if missing_global:
        print(f"Missing tickers (global): {missing_global}")
    print()

    # ── Run each window ───────────────────────────────────────────────────────
    # Skip 2019 and 2020: Alpaca IEX starts 2020-07-27; no warmup data available
    # for windows requiring pre-2020-07 history.
    IEX_RUNNABLE = {"2021", "2022", "2023-24"}

    results: list[dict] = []
    for window in OOS_WINDOWS:
        if window["name"] not in IEX_RUNNABLE:
            print(f"SKIPPED window: {window['name']}  "
                  f"(no IEX data for warmup period)")
            results.append({
                "window": window["name"], "sharpe": None,
                "skipped": True, "reason": "no_iex_warmup_data",
            })
            continue
        print(f"Running window: {window['name']}  ({window['start']} → {window['end']}) …")
        r = simulate_window(
            universe_data,
            window["start"],
            window["end"],
            window["name"],
            verbose=True,
        )
        results.append(r)
        if "error" not in r:
            print(f"  → Sharpe={r['sharpe']:+.3f}  MaxDD={r['max_dd']:.1%}  "
                  f"WR={r['win_rate']:.1%}  Trades={r['n_trades']}  "
                  f"TotalRet={r['total_return']:+.1%}  "
                  f"Coverage={r['coverage_pct']:.0f}%")
        else:
            print(f"  → ERROR: {r.get('error')}")
        print()

    # ── Summary table ─────────────────────────────────────────────────────────
    valid = [r for r in results if "error" not in r and r.get("sharpe") is not None]
    if not valid:
        print("No valid windows — harness failed.")
        return results

    pooled_sharpe = statistics.mean(r["sharpe"]    for r in valid)
    pooled_dd     = max(r["max_dd"]                for r in valid)
    pooled_wr     = statistics.mean(r["win_rate"]  for r in valid)
    total_trades  = sum(r["n_trades"]              for r in valid)

    # Pooled Sharpe from combined daily returns (second computation method)
    all_daily = []
    for r in valid:
        all_daily.extend(r.get("daily_returns", []))
    if len(all_daily) > 1:
        m = statistics.mean(all_daily)
        s = statistics.stdev(all_daily)
        pooled_sharpe_combined = (m / s) * math.sqrt(252) if s > 0 else 0.0
    else:
        pooled_sharpe_combined = pooled_sharpe

    print("=" * 65)
    print("PASS A RESULTS")
    print("=" * 65)
    print(f"{'Window':<10} {'Sharpe':>8} {'MaxDD':>8} {'WR':>7} {'Trades':>7} {'TotRet':>8} {'Coverage':>9}")
    print("-" * 65)
    for r in results:
        if r.get("skipped"):
            print(f"{r['window']:<10} {'SKIPPED (no IEX warmup data)':>55}")
        elif "error" in r:
            print(f"{r['window']:<10} {'ERROR':>8}")
        else:
            print(f"{r['window']:<10} "
                  f"{r['sharpe']:>+8.3f} "
                  f"{r['max_dd']:>7.1%} "
                  f"{r['win_rate']:>6.1%} "
                  f"{r['n_trades']:>7d} "
                  f"{r['total_return']:>+7.1%} "
                  f"{r['coverage_pct']:>8.0f}%")
    print("-" * 65)
    print(f"{'POOLED':<10} "
          f"{pooled_sharpe:>+8.3f} "
          f"{pooled_dd:>7.1%} "
          f"{pooled_wr:>6.1%} "
          f"{total_trades:>7d}")
    print(f"{'(combined)':<10} {pooled_sharpe_combined:>+8.3f}  (all windows' daily returns concatenated)")
    print()

    # ── Calibration verdict ───────────────────────────────────────────────────
    BASELINE   = 0.156
    TOLERANCE  = 0.05
    lo, hi     = BASELINE - TOLERANCE, BASELINE + TOLERANCE
    check_val  = pooled_sharpe_combined

    print(f"Calibration target  : {BASELINE:.3f}  (±{TOLERANCE:.3f}  →  [{lo:.3f}, {hi:.3f}])")
    print(f"Harness pooled Sharpe: {check_val:.3f}")

    if lo <= check_val <= hi:
        print("Calibration: ✅  PASS — within tolerance, harness is correct")
        print("             Ready to proceed to Pass B.")
    elif check_val > hi:
        print("Calibration: ⚠️   ABOVE RANGE — harness may be missing realistic costs")
        print("             Investigate before Pass B.  STOP per spec.")
    else:
        print("Calibration: ❌  BELOW RANGE — harness may have a bug or wrong constants")
        print("             Do NOT proceed to Pass B.  Investigate first.  STOP per spec.")

    print()
    # Per-window missing ticker log
    print("Missing ticker log (per window, at window start):")
    for r in results:
        if "error" not in r and r.get("missing_at_start"):
            print(f"  {r['window']}: {r['missing_at_start']}")

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_pass_a(verbose=True)
