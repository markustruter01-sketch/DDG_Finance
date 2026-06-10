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

# Alpaca IEX range (existing cache — 3-window run only)
DATA_START = date(2020, 6, 1)
DATA_END   = date(2024, 12, 31)

# Yahoo Finance range — covers all 5 windows + warmup for 2019
# 2018-01-01 gives ~252 bars before 2019-01-01 (EMA50 needs 50; plenty)
DATA_START_YAHOO = date(2018, 1, 1)
DATA_END_YAHOO   = date(2024, 12, 31)

# Alpaca SIP (consolidated tape) range — confirmed accessible from 2018-01-02.
# SIP is the primary source for the 5-window baseline: full tape, no single-
# exchange bias, same adjustment model as IEX (adjustment=all).
DATA_START_SIP = date(2018, 1, 1)
DATA_END_SIP   = date(2024, 12, 31)

CACHE_DIR  = Path(__file__).parent.parent / ".local" / "oos_data"
CACHE_FILE_YAHOO = (
    CACHE_DIR / f"universe_yahoo_{DATA_START_YAHOO}_{DATA_END_YAHOO}.pkl"
)
CACHE_FILE_SIP = (
    CACHE_DIR / f"universe_sip_{DATA_START_SIP}_{DATA_END_SIP}.pkl"
)

# Kill-switch threshold: if equity drops ≥5% from prior day, block new entries
KILLSWITCH_DAILY_DD = 0.05

# ── MSE (Market State Engine) Pass B constants ────────────────────────────────
# Regime thresholds
MSE_CRISIS_THRESHOLD  = -0.12   # SPY 20d rolling return ≤ -12% → CRISIS
MSE_HIGH_VOL_ANN      =  0.30   # SPY 10d realized vol (annualized) > 30% → HIGH_VOL

# Sizing
MSE_HIGH_VOL_SCALE    =  0.50   # Position size multiplier in HIGH_VOL conditions

# Cooldown and pause
MSE_COOLDOWN_DAYS     =  5      # Per-ticker cooldown (trading days) after stop-loss exit
MSE_DAILY_STOP_PAUSE  =  3      # If ≥N stops fire on a day, block all new entries that day

# Slot limits
MSE_MAX_LONG_BEAR     =  3      # MAX_LONG_SLOTS in BEAR regime (vs 5 in BULL)
MSE_SECTOR_CAP        =  2      # Max simultaneous longs per sector tag

# Safe-haven tickers (the only longs allowed in CRISIS regime)
MSE_SAFE_HAVENS: frozenset = frozenset({"TLT", "GLD", "IEF"})

# ── GICS-aligned sector map for all 245 FULL_UNIVERSE tickers ─────────────────
# Purpose: enforce MSE_SECTOR_CAP (≤2 simultaneous longs per sector).
# Unmapped tickers fall back to "OTHER" (also capped at 2).
# Sector ETFs are mapped to their underlying sector so they compete with
# single-stock longs for the same slot.  Broad-market/leveraged ETFs get
# their own "ETF_BROAD" bucket.
_SECTOR_MAP: dict[str, str] = {
    # ── Technology ──────────────────────────────────────────────────────────
    "AAPL":  "TECHNOLOGY", "ADBE":  "TECHNOLOGY", "AMD":   "TECHNOLOGY",
    "AMAT":  "TECHNOLOGY", "ARM":   "TECHNOLOGY", "ASML":  "TECHNOLOGY",
    "AVGO":  "TECHNOLOGY", "CDNS":  "TECHNOLOGY", "CRM":   "TECHNOLOGY",
    "CRWD":  "TECHNOLOGY", "CSCO":  "TECHNOLOGY", "DDOG":  "TECHNOLOGY",
    "DELL":  "TECHNOLOGY", "FTNT":  "TECHNOLOGY", "HPE":   "TECHNOLOGY",
    "INTC":  "TECHNOLOGY", "KLAC":  "TECHNOLOGY", "LRCX":  "TECHNOLOGY",
    "MRVL":  "TECHNOLOGY", "MSFT":  "TECHNOLOGY", "MSTR":  "TECHNOLOGY",
    "MU":    "TECHNOLOGY", "NET":   "TECHNOLOGY", "NOW":   "TECHNOLOGY",
    "NVDA":  "TECHNOLOGY", "ORCL":  "TECHNOLOGY", "PANW":  "TECHNOLOGY",
    "PLTR":  "TECHNOLOGY", "QCOM":  "TECHNOLOGY", "SAP":   "TECHNOLOGY",
    "SHOP":  "TECHNOLOGY", "SMCI":  "TECHNOLOGY", "SNPS":  "TECHNOLOGY",
    "SNOW":  "TECHNOLOGY", "TSM":   "TECHNOLOGY", "TXN":   "TECHNOLOGY",
    "XYZ":   "TECHNOLOGY", "ZS":    "TECHNOLOGY",
    "XLK":   "TECHNOLOGY",   # sector ETF → same bucket
    # ── Communication Services ───────────────────────────────────────────────
    "CHTR":  "COMM_SERVICES", "CMCSA": "COMM_SERVICES", "DIS":  "COMM_SERVICES",
    "EA":    "COMM_SERVICES", "GOOG":  "COMM_SERVICES", "META": "COMM_SERVICES",
    "NFLX":  "COMM_SERVICES", "RBLX":  "COMM_SERVICES", "SE":   "COMM_SERVICES",
    "SPOT":  "COMM_SERVICES", "T":     "COMM_SERVICES", "TMUS": "COMM_SERVICES",
    "TTWO":  "COMM_SERVICES", "VZ":    "COMM_SERVICES",
    "XLC":   "COMM_SERVICES",
    # ── Consumer Discretionary ──────────────────────────────────────────────
    "ABNB":  "CONSUMER_DISC", "AMZN":  "CONSUMER_DISC", "BKNG":  "CONSUMER_DISC",
    "CCL":   "CONSUMER_DISC", "CMG":   "CONSUMER_DISC", "DASH":  "CONSUMER_DISC",
    "DG":    "CONSUMER_DISC", "DHI":   "CONSUMER_DISC", "DLTR":  "CONSUMER_DISC",
    "F":     "CONSUMER_DISC", "GM":    "CONSUMER_DISC", "HD":    "CONSUMER_DISC",
    "HLT":   "CONSUMER_DISC", "LEN":   "CONSUMER_DISC", "LOW":   "CONSUMER_DISC",
    "LULU":  "CONSUMER_DISC", "MAR":   "CONSUMER_DISC", "MCD":   "CONSUMER_DISC",
    "MELI":  "CONSUMER_DISC", "NKE":   "CONSUMER_DISC", "PDD":   "CONSUMER_DISC",
    "RCL":   "CONSUMER_DISC", "ROST":  "CONSUMER_DISC", "SBUX":  "CONSUMER_DISC",
    "TGT":   "CONSUMER_DISC", "TJX":   "CONSUMER_DISC", "TM":    "CONSUMER_DISC",
    "TSLA":  "CONSUMER_DISC", "UBER":  "CONSUMER_DISC", "YUM":   "CONSUMER_DISC",
    "XLY":   "CONSUMER_DISC",
    # ── Consumer Staples ────────────────────────────────────────────────────
    "CL":    "CONSUMER_STAPLES", "COST":  "CONSUMER_STAPLES", "GIS":  "CONSUMER_STAPLES",
    "HSY":   "CONSUMER_STAPLES", "KMB":   "CONSUMER_STAPLES", "KO":   "CONSUMER_STAPLES",
    "MDLZ":  "CONSUMER_STAPLES", "MO":    "CONSUMER_STAPLES", "PEP":  "CONSUMER_STAPLES",
    "PG":    "CONSUMER_STAPLES", "PM":    "CONSUMER_STAPLES", "STZ":  "CONSUMER_STAPLES",
    "WMT":   "CONSUMER_STAPLES",
    "XLP":   "CONSUMER_STAPLES",
    # ── Healthcare ──────────────────────────────────────────────────────────
    "ABBV":  "HEALTHCARE", "ABT":  "HEALTHCARE", "AMGN":  "HEALTHCARE",
    "BIIB":  "HEALTHCARE", "BMY":  "HEALTHCARE", "BSX":   "HEALTHCARE",
    "CI":    "HEALTHCARE", "DHR":  "HEALTHCARE", "ELV":   "HEALTHCARE",
    "EW":    "HEALTHCARE", "GEHC": "HEALTHCARE", "GILD":  "HEALTHCARE",
    "HCA":   "HEALTHCARE", "ISRG": "HEALTHCARE", "JNJ":   "HEALTHCARE",
    "LLY":   "HEALTHCARE", "MDT":  "HEALTHCARE", "MRK":   "HEALTHCARE",
    "MRNA":  "HEALTHCARE", "NVO":  "HEALTHCARE", "PFE":   "HEALTHCARE",
    "REGN":  "HEALTHCARE", "SYK":  "HEALTHCARE", "TMO":   "HEALTHCARE",
    "UNH":   "HEALTHCARE", "VRTX": "HEALTHCARE", "ZTS":   "HEALTHCARE",
    "XLV":   "HEALTHCARE",
    # ── Financials ──────────────────────────────────────────────────────────
    "AIG":   "FINANCIALS", "ALL":   "FINANCIALS", "AXP":   "FINANCIALS",
    "BAC":   "FINANCIALS", "BLK":   "FINANCIALS", "C":     "FINANCIALS",
    "CB":    "FINANCIALS", "COIN":  "FINANCIALS", "COF":   "FINANCIALS",
    "GS":    "FINANCIALS", "JPM":   "FINANCIALS", "MA":    "FINANCIALS",
    "MET":   "FINANCIALS", "MS":    "FINANCIALS", "NU":    "FINANCIALS",
    "PNC":   "FINANCIALS", "PRU":   "FINANCIALS", "PYPL":  "FINANCIALS",
    "SCHW":  "FINANCIALS", "TFC":   "FINANCIALS", "USB":   "FINANCIALS",
    "V":     "FINANCIALS", "WFC":   "FINANCIALS",
    "XLF":   "FINANCIALS",
    # ── Industrials ─────────────────────────────────────────────────────────
    "BA":    "INDUSTRIALS", "CAT":  "INDUSTRIALS", "CSX":  "INDUSTRIALS",
    "DE":    "INDUSTRIALS", "EMR":  "INDUSTRIALS", "ETN":  "INDUSTRIALS",
    "FDX":   "INDUSTRIALS", "GD":   "INDUSTRIALS", "GE":   "INDUSTRIALS",
    "HON":   "INDUSTRIALS", "ITW":  "INDUSTRIALS", "LMT":  "INDUSTRIALS",
    "MMM":   "INDUSTRIALS", "NOC":  "INDUSTRIALS", "NSC":  "INDUSTRIALS",
    "PH":    "INDUSTRIALS", "RSG":  "INDUSTRIALS", "RTX":  "INDUSTRIALS",
    "UNP":   "INDUSTRIALS", "UPS":  "INDUSTRIALS", "WM":   "INDUSTRIALS",
    "XLI":   "INDUSTRIALS",
    # ── Energy ──────────────────────────────────────────────────────────────
    "BKR":   "ENERGY", "COP":  "ENERGY", "CVX":  "ENERGY", "DVN":  "ENERGY",
    "EOG":   "ENERGY", "FANG": "ENERGY", "HAL":  "ENERGY", "HES":  "ENERGY",
    "KMI":   "ENERGY", "MPC":  "ENERGY", "OXY":  "ENERGY", "PSX":  "ENERGY",
    "SLB":   "ENERGY", "VLO":  "ENERGY", "XOM":  "ENERGY",
    "XLE":   "ENERGY",
    # ── Materials ───────────────────────────────────────────────────────────
    "APD":   "MATERIALS", "CF":  "MATERIALS", "COPX": "MATERIALS",
    "DD":    "MATERIALS", "DOW": "MATERIALS", "ECL":  "MATERIALS",
    "FCX":   "MATERIALS", "LIN": "MATERIALS", "NEM":  "MATERIALS",
    "NUE":   "MATERIALS", "SHW": "MATERIALS",
    "XLB":   "MATERIALS",
    # ── Real Estate ─────────────────────────────────────────────────────────
    "AMT":   "REAL_ESTATE", "AVB":  "REAL_ESTATE", "CCI":  "REAL_ESTATE",
    "DLR":   "REAL_ESTATE", "EQIX": "REAL_ESTATE", "O":    "REAL_ESTATE",
    "PLD":   "REAL_ESTATE", "PSA":  "REAL_ESTATE", "SPG":  "REAL_ESTATE",
    "WELL":  "REAL_ESTATE",
    "XLRE":  "REAL_ESTATE",
    # ── Utilities ───────────────────────────────────────────────────────────
    "AEP":   "UTILITIES", "D":   "UTILITIES", "DUK":  "UTILITIES",
    "ES":    "UTILITIES", "EXC": "UTILITIES", "NEE":  "UTILITIES",
    "SO":    "UTILITIES", "SRE": "UTILITIES", "WEC":  "UTILITIES",
    "XEL":   "UTILITIES",
    "XLU":   "UTILITIES",
    # ── Safe Havens (allowed even in CRISIS) ────────────────────────────────
    "TLT":   "SAFE_HAVEN", "GLD": "SAFE_HAVEN", "IEF": "SAFE_HAVEN",
    # ── Broad/Leveraged ETFs ────────────────────────────────────────────────
    "DIA":   "ETF_BROAD", "IWM":  "ETF_BROAD", "QQQ":   "ETF_BROAD",
    "SPY":   "ETF_BROAD", "TQQQ": "ETF_BROAD", "UPRO":  "ETF_BROAD",
    # ── Fixed-Income / Bond ETFs ────────────────────────────────────────────
    "AGG":   "FIXED_INCOME", "BND": "FIXED_INCOME", "GOVT": "FIXED_INCOME",
    "TIP":   "FIXED_INCOME",
    # ── Commodity ETFs ──────────────────────────────────────────────────────
    "DBA":   "COMMODITY_ETF", "PDBC": "COMMODITY_ETF", "SLV": "COMMODITY_ETF",
    "UNG":   "COMMODITY_ETF", "USO":  "COMMODITY_ETF",
}

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


def _alpaca_sip_fetch_raw(ticker: str, start: date, end: date) -> dict | None:
    """
    Fetch daily adjusted OHLCV from Alpaca SIP (consolidated tape).
    Identical to _alpaca_fetch_raw except feed=sip instead of feed=iex.
    SIP: full consolidated tape, confirmed accessible from 2018-01-02.
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
        "feed":       "sip",          # consolidated tape
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
                print(f"    Alpaca SIP fetch failed {ticker}: {exc}")
                return None

    if not all_bars:
        return None

    all_bars.sort(key=lambda b: b["t"])
    return {
        "dates":   [b["t"][:10]    for b in all_bars],
        "opens":   [float(b["o"])  for b in all_bars],
        "highs":   [float(b["h"])  for b in all_bars],
        "lows":    [float(b["l"])  for b in all_bars],
        "closes":  [float(b["c"])  for b in all_bars],
        "volumes": [float(b["v"])  for b in all_bars],
    }


def load_universe_data_sip(
    tickers: list[str],
    verbose: bool = True,
) -> dict[str, dict]:
    """
    Load OHLCV data for all tickers from Alpaca SIP (consolidated tape).
    Range: DATA_START_SIP (2018-01-01) → DATA_END_SIP (2024-12-31).
    Cache: CACHE_FILE_SIP — separate from IEX and Yahoo caches.

    Incremental caching: partial results written every 25 tickers so a
    mid-fetch kill loses at most 25 tickers of progress.  On restart the
    cache is loaded and the run resumes from where it left off.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Load complete cache if it exists
    if CACHE_FILE_SIP.exists():
        if verbose:
            print(f"  Loading SIP cache: {CACHE_FILE_SIP}")
        with open(CACHE_FILE_SIP, "rb") as f:
            data = pickle.load(f)
        if verbose:
            print(f"  Loaded {len(data)} tickers from cache")
        return data

    if not _ALPACA_KEY:
        raise RuntimeError("ALPACA_API_KEY not set — cannot fetch SIP data")

    # Partial cache: resume from checkpoint if prior run was killed mid-fetch
    partial_path = CACHE_DIR / "universe_sip_partial.pkl"
    universe_data: dict[str, dict] = {}
    if partial_path.exists():
        with open(partial_path, "rb") as f:
            universe_data = pickle.load(f)
        if verbose:
            print(f"  Resuming from partial cache: {len(universe_data)} tickers already fetched")

    already_done = set(universe_data.keys())
    remaining    = [t for t in tickers if t not in already_done]
    missing: list[str] = []

    if verbose:
        print(f"  Fetching {len(remaining)}/{len(tickers)} tickers via Alpaca SIP "
              f"({DATA_START_SIP} → {DATA_END_SIP}) …")
        print(f"  (feed=sip consolidated tape; ~0.15s/ticker + checkpoint every 25)")

    for i, ticker in enumerate(remaining):
        data = _alpaca_sip_fetch_raw(ticker, DATA_START_SIP, DATA_END_SIP)
        if data:
            universe_data[ticker] = data
        else:
            missing.append(ticker)
        time.sleep(0.15)

        # Checkpoint every 25 tickers — survive mid-fetch kills
        if (i + 1) % 25 == 0:
            with open(partial_path, "wb") as f:
                pickle.dump(universe_data, f)
            if verbose:
                done_total = len(already_done) + i + 1
                print(f"    checkpoint: {done_total}/{len(tickers)} fetched "
                      f"({len(universe_data)} ok, {len(missing)} missing this run) …")

    if verbose:
        total_ok = len(universe_data)
        print(f"  Done: {total_ok}/{len(tickers)} tickers loaded")
        if missing:
            print(f"  Missing/skipped (newly-listed/delisted): {missing}")

    # Write final complete cache and clean up partial
    with open(CACHE_FILE_SIP, "wb") as f:
        pickle.dump(universe_data, f)
    if partial_path.exists():
        partial_path.unlink()
    if verbose:
        print(f"  Saved SIP cache: {CACHE_FILE_SIP}")
    return universe_data


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


def _yf_fetch_simple(ticker: str, start: date, end: date) -> dict | None:
    """
    Crumb-free Yahoo Finance v8 fetch using adjclose.
    The v8 chart endpoint accepts requests with only a User-Agent header —
    confirmed working in this environment (no crumb/cookie needed for basic OHLCV).
    Falls back to the crumb-session path if this returns a 401/403.
    """
    p1 = int(datetime(start.year, start.month, start.day).timestamp())
    p2 = int(datetime(end.year,   end.month,   end.day, 23, 59).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0"
        )
    }
    params = {
        "period1":              p1,
        "period2":              p2,
        "interval":             "1d",
        "events":               "div,splits",
        "includeAdjustedClose": "true",
    }
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code == 404:
                return None
            if r.status_code in (401, 403):
                # Fall back to crumb-session path
                if _init_yf_session():
                    return _yf_fetch_raw(ticker, start, end)
                return None
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
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
                print(f"    YF simple fetch failed {ticker}: {exc}")
                return None
    return None


def _fetch_ticker_yahoo(ticker: str, start: date, end: date) -> dict | None:
    """Yahoo Finance only fetch — used for the all-5-window baseline run."""
    data = _yf_fetch_simple(ticker, start, end)
    if data and len(data["dates"]) >= MIN_BARS_NEEDED:
        return data
    return None


def load_universe_data_yahoo(
    tickers: list[str],
    verbose: bool = True,
) -> dict[str, dict]:
    """
    Load OHLCV data for all tickers from Yahoo Finance adjclose only.
    Range: DATA_START_YAHOO (2018-01-01) → DATA_END_YAHOO (2024-12-31).
    Cache: CACHE_FILE_YAHOO — separate from the IEX cache, never overwrites it.
    Ticker rate: ~0.35s sleep → ~245 tickers in ~90s.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if CACHE_FILE_YAHOO.exists():
        if verbose:
            print(f"  Loading Yahoo cache: {CACHE_FILE_YAHOO}")
        with open(CACHE_FILE_YAHOO, "rb") as f:
            return pickle.load(f)

    if verbose:
        print(f"  Fetching {len(tickers)} tickers via Yahoo Finance adjclose "
              f"({DATA_START_YAHOO} → {DATA_END_YAHOO}) …")
        print(f"  (crumb-free v8 endpoint; rate: ~0.35s/ticker ≈ {len(tickers)*0.35/60:.0f} min total)")

    universe_data: dict[str, dict] = {}
    missing: list[str] = []

    for i, ticker in enumerate(tickers):
        data = _fetch_ticker_yahoo(ticker, DATA_START_YAHOO, DATA_END_YAHOO)
        if data:
            universe_data[ticker] = data
        else:
            missing.append(ticker)
        if verbose and (i + 1) % 25 == 0:
            print(f"    {i+1}/{len(tickers)} fetched "
                  f"({len(universe_data)} ok, {len(missing)} missing) …")
        time.sleep(0.35)

    if verbose:
        print(f"  Done: {len(universe_data)}/{len(tickers)} tickers loaded")
        if missing:
            print(f"  Missing/skipped (newly-listed or delisted): {missing}")

    with open(CACHE_FILE_YAHOO, "wb") as f:
        pickle.dump(universe_data, f)
    if verbose:
        print(f"  Saved Yahoo cache: {CACHE_FILE_YAHOO}")
    return universe_data


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
    # IEX coverage gaps (and pre-IPO gaps in Yahoo data) cause some tickers to
    # skip certain calendar dates that SPY includes.  Without carry-forward,
    # open positions on gap days are silently excluded from MTM → equity
    # collapses to cash.
    last_known_bar: dict    = {}

    # Kill-switch tracking (mirrors live algo_scanner behaviour):
    # If equity drops ≥5% from the previous day, block all new entries that day.
    killswitch_days: int    = 0   # cumulative count of days kill-switch fired
    prev_equity:     float  = STARTING_EQUITY

    # Sanity tracking
    max_single_day_swing: float = 0.0   # largest abs daily equity % change

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

        # Sanity: track largest single-day absolute equity swing
        if prev_equity > 0:
            day_swing = abs(equity / prev_equity - 1.0)
            if day_swing > max_single_day_swing:
                max_single_day_swing = day_swing

        # ── Kill-switch check (mirrors live algo_scanner) ─────────────────────
        # If equity dropped ≥5% from yesterday, skip all entries today.
        daily_dd = (prev_equity - equity) / prev_equity if prev_equity > 0 else 0.0
        killswitch_fired = daily_dd >= KILLSWITCH_DAILY_DD
        if killswitch_fired:
            killswitch_days += 1
        prev_equity = equity

        # ── 3. Entry signals ──────────────────────────────────────────────────
        n_longs  = sum(1 for p in positions.values() if p["side"] == "long")
        n_shorts = sum(1 for p in positions.values() if p["side"] == "short")
        avail_long  = MAX_LONG_SLOTS  - n_longs
        avail_short = MAX_SHORT_SLOTS - n_shorts

        if (avail_long > 0 or avail_short > 0) and not killswitch_fired:
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
        "window":               window_name,
        "start":                ws,
        "end":                  we,
        "trading_days":         len(window_dates),
        "sharpe":               round(sharpe,   4),
        "max_dd":               round(max_dd,   4),
        "win_rate":             round(win_rate, 4),
        "n_trades":             len(all_trades),
        "total_return":         round(total_ret, 4),
        "final_equity":         round(final_eq, 2),
        "equity_curve":         equity_curve,
        "daily_returns":        daily_returns,
        "trades":               all_trades,
        "coverage_pct":         round(coverage_pct, 1),
        "missing_at_start":     missing_at_start[:20],
        "killswitch_days":      killswitch_days,
        "max_single_day_swing": round(max_single_day_swing, 6),
    }


# ── MSE helpers ───────────────────────────────────────────────────────────────

def _compute_spy_mse_series(spy_data: dict) -> dict[str, dict]:
    """
    Pre-compute per-day MSE regime signals from the full SPY time-series.

    Returns {date_str: {regime, high_vol, ema50, ema200, ret_20d, vol_10d_ann}}

    Regime logic:
      CRISIS : SPY 20d rolling return ≤ MSE_CRISIS_THRESHOLD (-12%)
      BEAR   : SPY 50d EMA < SPY 200d EMA  (and not CRISIS)
      BULL   : otherwise

    HIGH_VOL : SPY 10d realised vol (annualised) > MSE_HIGH_VOL_ANN (30%)

    EMA200 needs ~200 bars to stabilise; data starts 2018-01-02 so by 2019-01-01
    we have ~252 warm-up bars — fully settled before the first OOS window.
    """
    dates  = spy_data["dates"]
    closes = spy_data["closes"]
    n      = len(closes)

    alpha50  = 2.0 / (50  + 1)
    alpha200 = 2.0 / (200 + 1)
    ema50  = closes[0]
    ema200 = closes[0]

    result: dict[str, dict] = {}
    for i in range(n):
        c = closes[i]
        ema50  = alpha50  * c + (1 - alpha50)  * ema50
        ema200 = alpha200 * c + (1 - alpha200) * ema200

        # 20-day rolling return (needs 20 prior bars)
        ret_20d = (c / closes[i - 20] - 1.0) if i >= 20 else 0.0

        # 10-day realised vol annualised (needs 10 prior bars)
        if i >= 10:
            lr = [
                math.log(closes[j] / closes[j - 1])
                for j in range(i - 9, i + 1)
                if closes[j - 1] > 0
            ]
            vol_10d_ann = (statistics.stdev(lr) * math.sqrt(252)
                           if len(lr) >= 2 else 0.0)
        else:
            vol_10d_ann = 0.0

        # Regime — require i >= 200 for EMA200 to be meaningful
        if i < 200:
            regime = "BULL"
        elif ret_20d <= MSE_CRISIS_THRESHOLD:
            regime = "CRISIS"
        elif ema50 < ema200:
            regime = "BEAR"
        else:
            regime = "BULL"

        result[dates[i]] = {
            "regime":      regime,
            "high_vol":    vol_10d_ann > MSE_HIGH_VOL_ANN,
            "ema50":       ema50,
            "ema200":      ema200,
            "ret_20d":     ret_20d,
            "vol_10d_ann": vol_10d_ann,
        }
    return result


def simulate_window_mse(
    universe_data: dict[str, dict],
    window_start:  date,
    window_end:    date,
    window_name:   str,
    spy_mse:       dict[str, dict],
    verbose:       bool = False,
) -> dict:
    """
    MSE-augmented Oracle simulation for one OOS window.

    Adds on top of simulate_window:
      • CRISIS/BEAR/BULL regime gates (SPY 20d return / EMA50 vs EMA200)
      • Safe-haven rotation in CRISIS (only TLT/GLD/IEF longs allowed)
      • HIGH_VOL 0.5× position sizing (SPY 10d realised vol > 30% ann.)
      • Per-ticker 5-day cooldown after any stop-loss exit
      • Daily 3-stop pause (≥3 stops in a day → no new entries rest of day)
      • Sector cap ≤ 2 long positions per GICS-aligned sector tag

    MSE constants are module-level (MSE_*); sector tags from _SECTOR_MAP.
    """
    spy_data = universe_data.get("SPY")
    if spy_data is None:
        print(f"  [{window_name}] ERROR: SPY data missing")
        return {}

    all_dates_str = spy_data["dates"]
    ws = window_start.strftime("%Y-%m-%d")
    we = window_end.strftime("%Y-%m-%d")
    window_dates = [d for d in all_dates_str if ws <= d <= we]

    if not window_dates:
        print(f"  [{window_name}] No trading days found in range {ws} → {we}")
        return {}

    ticker_date_idx: dict[str, dict[str, int]] = {}
    for ticker, data in universe_data.items():
        ticker_date_idx[ticker] = {d: i for i, d in enumerate(data["dates"])}

    first_trading_day = window_dates[0]
    tickers_with_data = [
        t for t in universe_data
        if first_trading_day in ticker_date_idx.get(t, {})
    ]
    coverage_pct    = len(tickers_with_data) / max(len(universe_data), 1) * 100
    missing_at_start = [t for t in universe_data if t not in tickers_with_data]

    if verbose:
        print(f"  [{window_name}] {len(window_dates)} trading days  "
              f"coverage {coverage_pct:.0f}% ({len(tickers_with_data)}/{len(universe_data)} tickers)")

    ind_cache = precompute_indicators(universe_data)

    # ── Simulation state ──────────────────────────────────────────────────────
    equity:       float = STARTING_EQUITY
    cash:         float = STARTING_EQUITY
    positions:    dict  = {}
    equity_curve: list  = []
    all_trades:   list  = []
    last_known_bar: dict = {}

    # Existing kill-switch (5% daily DD)
    killswitch_days: int   = 0
    prev_equity:     float = STARTING_EQUITY

    # Sanity tracking
    max_single_day_swing: float = 0.0

    # ── MSE state ─────────────────────────────────────────────────────────────
    # cooldown_until[ticker] = day_n after which the ticker may be re-entered
    cooldown_until: dict[str, int] = {}
    # Day-level MSE counters / stats
    regime_days:           dict[str, int] = {"CRISIS": 0, "BEAR": 0, "BULL": 0}
    high_vol_days:         int  = 0
    blocked_days_crisis:   int  = 0   # days where CRISIS blocked non-safe-haven longs
    blocked_days_pause:    int  = 0   # days where ≥3-stop pause blocked entries
    safe_haven_entries:    int  = 0
    cooldown_blocks:       int  = 0   # candidate skips due to cooldown

    for day_n, day_str in enumerate(window_dates):
        fresh_bar: dict = {}
        for ticker in universe_data:
            idx = ticker_date_idx[ticker].get(day_str, -1)
            if idx >= 0:
                fresh_bar[ticker] = idx
                last_known_bar[ticker] = idx

        mtm_bar: dict = {**fresh_bar}
        for ticker in positions:
            if ticker not in mtm_bar and ticker in last_known_bar:
                mtm_bar[ticker] = last_known_bar[ticker]

        # ── 1. Exit checks ────────────────────────────────────────────────────
        positions, closed = _check_exits(
            positions, universe_data, fresh_bar, day_n, ind_cache
        )
        stops_today = 0
        for trade in closed:
            if trade["side"] == "long":
                cash += trade["exit_price"] * trade["shares"]
            else:
                cash += max(0.0, (2.0 * trade["entry_price"] - trade["exit_price"])
                             * trade["shares"])
            # MSE: start per-ticker cooldown on stop exits
            reason = trade.get("exit_reason", "")
            if reason in ("stop", "stop_gapdown", "stop_gapup"):
                stops_today += 1
                cooldown_until[trade["ticker"]] = day_n + MSE_COOLDOWN_DAYS
        all_trades.extend(closed)

        # ── 2. Mark-to-market equity ──────────────────────────────────────────
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
                pos_value += max(
                    0.0, (2.0 * pos["entry_price"] - close_p) * pos["shares"]
                )
        equity = cash + pos_value
        equity_curve.append(equity)

        if prev_equity > 0:
            day_swing = abs(equity / prev_equity - 1.0)
            if day_swing > max_single_day_swing:
                max_single_day_swing = day_swing

        # ── Kill-switch check ─────────────────────────────────────────────────
        daily_dd         = (prev_equity - equity) / prev_equity if prev_equity > 0 else 0.0
        killswitch_fired = daily_dd >= KILLSWITCH_DAILY_DD
        if killswitch_fired:
            killswitch_days += 1
        prev_equity = equity

        # ── MSE regime for this day ───────────────────────────────────────────
        mse_day  = spy_mse.get(day_str, {"regime": "BULL", "high_vol": False})
        regime   = mse_day["regime"]
        high_vol = mse_day["high_vol"]
        regime_days[regime] += 1
        if high_vol:
            high_vol_days += 1

        # Daily-stop pause: if ≥3 stops fired today, block all new entries
        daily_stop_pause = stops_today >= MSE_DAILY_STOP_PAUSE
        if daily_stop_pause:
            blocked_days_pause += 1

        # ── 3. Entry signals ──────────────────────────────────────────────────
        n_longs  = sum(1 for p in positions.values() if p["side"] == "long")
        n_shorts = sum(1 for p in positions.values() if p["side"] == "short")

        # BEAR regime: tighten long slot count to MSE_MAX_LONG_BEAR
        effective_max_long = (
            MSE_MAX_LONG_BEAR if regime == "BEAR"
            else MAX_LONG_SLOTS
        )
        avail_long  = effective_max_long - n_longs
        avail_short = MAX_SHORT_SLOTS    - n_shorts

        entries_allowed = (
            (avail_long > 0 or avail_short > 0)
            and not killswitch_fired
            and not daily_stop_pause
        )

        if entries_allowed:
            long_cands, short_cands = _compute_signals(
                universe_data, fresh_bar, set(positions.keys()), equity, ind_cache
            )

            # ── MSE filters on long candidates ────────────────────────────────
            # CRISIS: only safe-haven tickers may enter as longs
            if regime == "CRISIS":
                pre_filter_count = len(long_cands)
                long_cands = [c for c in long_cands
                              if c["ticker"] in MSE_SAFE_HAVENS]
                if pre_filter_count > 0 and len(long_cands) < pre_filter_count:
                    blocked_days_crisis += 1

            # Cooldown filter: skip tickers still in cooldown
            def _in_cooldown(ticker: str) -> bool:
                return cooldown_until.get(ticker, -1) > day_n

            pre_cd = len(long_cands) + len(short_cands)
            long_cands  = [c for c in long_cands  if not _in_cooldown(c["ticker"])]
            short_cands = [c for c in short_cands if not _in_cooldown(c["ticker"])]
            cooldown_blocks += (pre_cd - len(long_cands) - len(short_cands))

            # Sector-cap filter: skip tickers whose sector is already at cap
            sector_counts: dict[str, int] = {}
            for t, p in positions.items():
                if p["side"] == "long":
                    sec = _SECTOR_MAP.get(t, "OTHER")
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1

            def _sector_ok(ticker: str) -> bool:
                sec = _SECTOR_MAP.get(ticker, "OTHER")
                return sector_counts.get(sec, 0) < MSE_SECTOR_CAP

            long_cands = [c for c in long_cands if _sector_ok(c["ticker"])]

            # Assemble entries respecting slot limits
            entries = (
                [(c, "long")  for c in long_cands[:avail_long]]
                + [(c, "short") for c in short_cands[:avail_short]]
            )

            for cand, side in entries:
                ticker = cand["ticker"]
                price  = cand["price"]
                atr    = cand["atr"]

                risk_amount    = equity * RISK_PER_TRADE
                stop_dist      = atr * ATR_MULTIPLIER
                if stop_dist <= 0:
                    continue
                shares_raw     = risk_amount / stop_dist
                position_value = shares_raw * price
                kelly_frac     = min(position_value / equity, MAX_POSITION_PCT)
                position_value = kelly_frac * equity

                # HIGH_VOL: scale down position size by 0.5×
                if high_vol:
                    position_value *= MSE_HIGH_VOL_SCALE

                shares = position_value / price

                if shares <= 0 or position_value > cash:
                    continue

                stop_price = (
                    price - atr * ATR_MULTIPLIER if side == "long"
                    else price + atr * ATR_MULTIPLIER
                )

                positions[ticker] = {
                    "side":            side,
                    "entry_price":     price,
                    "shares":          shares,
                    "atr_at_entry":    atr,
                    "stop_price":      stop_price,
                    "best_price":      price,
                    "trailing_active": False,
                    "entry_day":       day_n,
                }
                cash -= position_value

                if side == "long" and ticker in MSE_SAFE_HAVENS:
                    safe_haven_entries += 1

                # Update sector counts immediately so same-day entries respect cap
                if side == "long":
                    sec = _SECTOR_MAP.get(ticker, "OTHER")
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1

    # ── Force-close open positions at window end ──────────────────────────────
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
        pnl     = ((close_p - entry_p) * shares if side == "long"
                   else max((entry_p - close_p) * shares, -entry_p * shares))
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

    peak_eq = STARTING_EQUITY
    max_dd  = 0.0
    for eq in equity_curve:
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq
        if dd > max_dd:
            max_dd = dd

    wins     = [t for t in all_trades if t["pnl"] > 0]
    win_rate = len(wins) / len(all_trades) if all_trades else 0.0
    total_ret = (equity_curve[-1] - STARTING_EQUITY) / STARTING_EQUITY

    return {
        "window":               window_name,
        "start":                ws,
        "end":                  we,
        "trading_days":         len(window_dates),
        "sharpe":               round(sharpe,   4),
        "max_dd":               round(max_dd,   4),
        "win_rate":             round(win_rate, 4),
        "n_trades":             len(all_trades),
        "total_return":         round(total_ret, 4),
        "final_equity":         round(equity_curve[-1], 2),
        "equity_curve":         equity_curve,
        "daily_returns":        daily_returns,
        "trades":               all_trades,
        "coverage_pct":         round(coverage_pct, 1),
        "missing_at_start":     missing_at_start[:20],
        "killswitch_days":      killswitch_days,
        "max_single_day_swing": round(max_single_day_swing, 6),
        # ── MSE-specific fields ───────────────────────────────────────────────
        "regime_days":          regime_days,
        "high_vol_days":        high_vol_days,
        "blocked_days_crisis":  blocked_days_crisis,
        "blocked_days_pause":   blocked_days_pause,
        "safe_haven_entries":   safe_haven_entries,
        "cooldown_blocks":      cooldown_blocks,
    }


# ── Pass A: Oracle first-ever OOS baseline (all 5 windows, Yahoo data) ────────

def run_pass_a(verbose: bool = True) -> list[dict]:
    """
    Pass A — Oracle baseline, no MSE, all 5 OOS windows.

    Data source : Yahoo Finance adjclose (2018-01-01 → 2024-12-31)
    Windows     : 2019, 2020, 2021, 2022, 2023-24 (all non-overlapping)
    No target   : this IS the first Oracle OOS run; the output is the baseline.
    Sanity gates: MaxDD<99%, no single-day swing>50%, trade count plausible,
                  kill-switch day count reported for each window.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from execution.momentum_universe import FULL_UNIVERSE

    SEP  = "=" * 72
    SEP2 = "-" * 72

    # ── Data loading ──────────────────────────────────────────────────────────
    print(SEP)
    print("ORACLE OOS VALIDATION — PASS A  (FIRST-EVER ORACLE OOS BASELINE)")
    print(SEP)
    print(f"Universe  : {len(FULL_UNIVERSE)} tickers (FULL_UNIVERSE)")
    print(f"Data range: {DATA_START_SIP} → {DATA_END_SIP}")
    print(f"Data src  : Alpaca SIP (consolidated tape, adjustment=all)")
    print(f"SIP access: CONFIRMED 2018-01-02+ (SPY/AAPL/MSFT/XOM/JPM Q1-2018 = 61 bars each)")
    print(f"Windows   : ALL 5 (2019, 2020, 2021, 2022, 2023-24)")
    print(f"No target : this output IS the Oracle baseline — no comparison to Jerome/Buck")
    print(f"Cache     : {CACHE_FILE_SIP}")
    print()

    universe_data = load_universe_data_sip(FULL_UNIVERSE, verbose=True)
    print(f"\nLoaded: {len(universe_data)}/{len(FULL_UNIVERSE)} tickers\n")

    missing_global = sorted(t for t in FULL_UNIVERSE if t not in universe_data)
    if missing_global:
        print(f"Globally missing tickers (newly-listed/delisted, excluded from all windows):")
        print(f"  {missing_global}\n")

    # ── Run all 5 windows ─────────────────────────────────────────────────────
    results: list[dict] = []
    for window in OOS_WINDOWS:
        print(f"Running window: {window['name']}  ({window['start']} → {window['end']}) …")
        r = simulate_window(
            universe_data,
            window["start"],
            window["end"],
            window["name"],
            verbose=True,
        )
        results.append(r)
        if "error" not in r and r.get("sharpe") is not None:
            ks = r.get("killswitch_days", 0)
            sw = r.get("max_single_day_swing", 0.0)
            print(f"  → Sharpe={r['sharpe']:+.3f}  MaxDD={r['max_dd']:.1%}  "
                  f"WR={r['win_rate']:.1%}  Trades={r['n_trades']}  "
                  f"TotRet={r['total_return']:+.1%}  "
                  f"Coverage={r['coverage_pct']:.0f}%  "
                  f"KillSwitch={ks}d  MaxDaySwing={sw:.1%}")
        else:
            print(f"  → ERROR: {r.get('error')}")
        print()

    # ── Summary table ─────────────────────────────────────────────────────────
    valid = [r for r in results if "error" not in r and r.get("sharpe") is not None]
    if not valid:
        print("No valid windows — harness failed.")
        return results

    # Pooled Sharpe: mean of per-window Sharpes (method 1)
    pooled_sharpe_mean = statistics.mean(r["sharpe"]   for r in valid)
    pooled_dd          = max(r["max_dd"]               for r in valid)
    pooled_wr          = statistics.mean(r["win_rate"] for r in valid)
    total_trades       = sum(r["n_trades"]             for r in valid)

    # Pooled Sharpe: combined daily returns concatenated (method 2 — primary)
    all_daily: list[float] = []
    for r in valid:
        all_daily.extend(r.get("daily_returns", []))
    if len(all_daily) > 1:
        m = statistics.mean(all_daily)
        s = statistics.stdev(all_daily)
        pooled_sharpe_combined = (m / s) * math.sqrt(252) if s > 0 else 0.0
    else:
        pooled_sharpe_combined = pooled_sharpe_mean

    print(SEP)
    print("PASS A RESULTS — ORACLE FIRST-EVER OOS BASELINE")
    print(SEP)
    print(f"{'Window':<10} {'Sharpe':>8} {'MaxDD':>8} {'WR':>7} "
          f"{'Trades':>7} {'TotRet':>8} {'Cov%':>6} "
          f"{'KillSw':>7} {'MaxDaySw':>9} {'Used/Ttl':>9}")
    print(SEP2)
    for r in results:
        if "error" in r:
            print(f"{r['window']:<10}  ERROR: {r.get('error')}")
        else:
            ks = r.get("killswitch_days", 0)
            sw = r.get("max_single_day_swing", 0.0)
            n_used  = int(r["coverage_pct"] / 100 * len(universe_data) + 0.5)
            print(f"{r['window']:<10} "
                  f"{r['sharpe']:>+8.3f} "
                  f"{r['max_dd']:>7.1%} "
                  f"{r['win_rate']:>6.1%} "
                  f"{r['n_trades']:>7d} "
                  f"{r['total_return']:>+7.1%} "
                  f"{r['coverage_pct']:>5.0f}% "
                  f"{ks:>7d} "
                  f"{sw:>8.1%} "
                  f"{n_used:>4d}/{len(universe_data)}")
    print(SEP2)
    print(f"{'POOLED':<10} "
          f"{pooled_sharpe_mean:>+8.3f} "
          f"{pooled_dd:>7.1%} "
          f"{pooled_wr:>6.1%} "
          f"{total_trades:>7d}  (mean-of-windows Sharpe)")
    print(f"{'(concat)':<10} "
          f"{pooled_sharpe_combined:>+8.3f}"
          f"{'':>40}  (daily returns concatenated — primary)")
    print()

    # ── Sanity gates ──────────────────────────────────────────────────────────
    print("SANITY GATES")
    print(SEP2)
    gate_pass = True

    # Gate 1: No window MaxDD ≥ 99% (data-gap bug fingerprint)
    bad_dd = [r for r in valid if r["max_dd"] >= 0.99]
    if bad_dd:
        for r in bad_dd:
            print(f"  FAIL  MaxDD≥99% in {r['window']}: {r['max_dd']:.1%}  "
                  f"← data-gap MTM bug still present")
        gate_pass = False
    else:
        print(f"  PASS  No window MaxDD ≥ 99%  (data-gap MTM bug confirmed absent)")

    # Gate 2: No single-day equity swing > 50% (the $95k→$19→$94k artifact)
    bad_swing = [r for r in valid if r.get("max_single_day_swing", 0) > 0.50]
    if bad_swing:
        for r in bad_swing:
            print(f"  FAIL  Single-day swing >{50}% in {r['window']}: "
                  f"{r['max_single_day_swing']:.1%}  ← round-trip artifact")
        gate_pass = False
    else:
        print(f"  PASS  No single-day equity swing > 50%")

    # Gate 3: Trade count plausible (>0, roughly 80–300 per annual window)
    bad_trades = [r for r in valid if r["n_trades"] == 0]
    if bad_trades:
        for r in bad_trades:
            print(f"  FAIL  Zero trades in {r['window']} — strategy never triggered")
        gate_pass = False
    else:
        trade_summary = "  ".join(f"{r['window']}:{r['n_trades']}" for r in valid)
        print(f"  PASS  Trades per window: {trade_summary}")

    # Gate 4: 2020 kill-switch report (informational — not pass/fail)
    w2020 = next((r for r in valid if r["window"] == "2020"), None)
    if w2020:
        ks = w2020.get("killswitch_days", 0)
        print(f"  INFO  2020 COVID: kill-switch (≥5% daily DD) fired {ks} day(s)"
              f"  ← new-entry blocking during Feb-Mar crash")
    else:
        print(f"  WARN  2020 window not found in valid results")

    print()
    if gate_pass:
        print("ALL SANITY GATES PASSED — baseline numbers are trustworthy.")
    else:
        print("SANITY GATE FAILURES DETECTED — do not proceed to Pass B until resolved.")
    print()

    # ── Per-window coverage report ────────────────────────────────────────────
    print("COVERAGE REPORT (per-window missing tickers at window start)")
    print(SEP2)
    for r in results:
        if "error" not in r:
            miss = r.get("missing_at_start", [])
            print(f"  {r['window']}: {len(miss)} missing  {miss[:15]}"
                  + ("…" if len(miss) > 15 else ""))
    print()
    print("NOTE: ARM/COIN/GEHC/RBLX/NU missing in early windows is expected")
    print("      (IPO after window start).  These tickers are excluded per-window.")

    return results


# ── Pass B: MSE-augmented run ─────────────────────────────────────────────────

def run_pass_b(verbose: bool = True) -> list[dict]:
    """
    Pass B — MSE-augmented Oracle OOS run.

    MSE overlay:
      • CRISIS/BEAR/BULL regime gates  (SPY 20d return / EMA50 vs EMA200)
      • Safe-haven rotation            (TLT/GLD/IEF only in CRISIS)
      • HIGH_VOL 0.5× sizing           (SPY 10d realised vol > 30% ann.)
      • Per-ticker 5-day cooldown      (after any stop-loss exit)
      • Daily 3-stop pause             (≥3 stops → block rest-of-day entries)
      • Sector cap ≤ 2                 (per GICS-aligned sector tag)

    PRE-REGISTERED SUCCESS BAR (locked before run):
      1. Pooled Sharpe (concat) >= 0.70
      2. Pooled MaxDD         <= 14%
      3. BOTH 2021 AND 2022 Sharpe improve vs Pass A baseline
         (baseline: 2021=-0.153, 2022=-0.059)
      4. 2019 Sharpe NOT degrade by >0.30 vs baseline (+1.411)
         2020 Sharpe NOT degrade by >0.30 vs baseline (+1.363)
      PARTIAL: if pooled improves + 2021/2022 improve but 2020 degrades >0.30
               → report as "DEFENSIVE BUT COSTS UPSIDE" (no quiet tuning)
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from execution.momentum_universe import FULL_UNIVERSE

    SEP  = "=" * 72
    SEP2 = "-" * 72

    # Pass A baseline for side-by-side comparison
    PASS_A_BASELINE = {
        "2019":     {"sharpe": +1.411, "max_dd": 0.066, "win_rate": 0.608,
                     "n_trades": 107,  "total_return": +0.175},
        "2020":     {"sharpe": +1.363, "max_dd": 0.146, "win_rate": 0.533,
                     "n_trades": 150,  "total_return": +0.337},
        "2021":     {"sharpe": -0.153, "max_dd": 0.130, "win_rate": 0.504,
                     "n_trades": 123,  "total_return": -0.041},
        "2022":     {"sharpe": -0.059, "max_dd": 0.128, "win_rate": 0.449,
                     "n_trades": 136,  "total_return": -0.027},
        "2023-24":  {"sharpe": +0.561, "max_dd": 0.170, "win_rate": 0.525,
                     "n_trades": 238,  "total_return": +0.164},
        "_pooled_sharpe_concat": 0.599,
        "_pooled_max_dd":        0.170,
    }

    print(SEP)
    print("ORACLE OOS VALIDATION — PASS B  (MSE-AUGMENTED)")
    print(SEP)
    print(f"Universe  : {len(FULL_UNIVERSE)} tickers (FULL_UNIVERSE)")
    print(f"Data src  : Alpaca SIP (consolidated tape, cache={CACHE_FILE_SIP.name})")
    print(f"MSE overlay:")
    print(f"  Regime  : CRISIS (SPY 20d ret≤-12%), BEAR (EMA50<EMA200), BULL")
    print(f"  CRISIS  : block non-safe-haven longs; safe havens = TLT/GLD/IEF")
    print(f"  BEAR    : MAX_LONG_SLOTS={MSE_MAX_LONG_BEAR} (vs {MAX_LONG_SLOTS} in BULL)")
    print(f"  HIGH_VOL: SPY 10d vol>30%ann → position size ×{MSE_HIGH_VOL_SCALE}")
    print(f"  Cooldown: {MSE_COOLDOWN_DAYS}d per-ticker after stop-loss")
    print(f"  Pause   : {MSE_DAILY_STOP_PAUSE} stops in a day → block rest-of-day entries")
    print(f"  SectCap : ≤{MSE_SECTOR_CAP} longs per GICS sector")
    print(f"Success bar (PRE-REGISTERED, no tuning):")
    print(f"  Pooled Sharpe ≥0.70 | MaxDD ≤14% | 2021+2022 both improve | "
          f"2019/2020 degrade ≤0.30")
    print()

    universe_data = load_universe_data_sip(FULL_UNIVERSE, verbose=True)
    print(f"\nLoaded: {len(universe_data)}/{len(FULL_UNIVERSE)} tickers\n")

    # Pre-compute MSE regime series from SPY (full data range, not just windows)
    spy_data = universe_data.get("SPY")
    if spy_data is None:
        raise RuntimeError("SPY missing from universe — cannot compute MSE regime")
    print("  Computing MSE regime series (SPY EMA50/200, 20d return, 10d vol) …")
    spy_mse = _compute_spy_mse_series(spy_data)
    print(f"  MSE series ready: {len(spy_mse)} dates\n")

    # ── Run all 5 windows ─────────────────────────────────────────────────────
    results: list[dict] = []
    for window in OOS_WINDOWS:
        print(f"Running window: {window['name']}  ({window['start']} → {window['end']}) …")
        r = simulate_window_mse(
            universe_data,
            window["start"],
            window["end"],
            window["name"],
            spy_mse,
            verbose=True,
        )
        results.append(r)
        if "error" not in r and r.get("sharpe") is not None:
            ks    = r.get("killswitch_days",    0)
            sw    = r.get("max_single_day_swing", 0.0)
            rgd   = r.get("regime_days",        {})
            she   = r.get("safe_haven_entries", 0)
            bdc   = r.get("blocked_days_crisis",0)
            bdp   = r.get("blocked_days_pause", 0)
            hv    = r.get("high_vol_days",      0)
            print(f"  → Sharpe={r['sharpe']:+.3f}  MaxDD={r['max_dd']:.1%}  "
                  f"WR={r['win_rate']:.1%}  Trades={r['n_trades']}  "
                  f"TotRet={r['total_return']:+.1%}  KillSw={ks}d")
            print(f"     Regime: BULL={rgd.get('BULL',0)}d BEAR={rgd.get('BEAR',0)}d "
                  f"CRISIS={rgd.get('CRISIS',0)}d  HighVol={hv}d")
            print(f"     Blocked: crisis={bdc}d pause={bdp}d | "
                  f"SafeHavenEntries={she} | MaxDaySwing={sw:.1%}")
        else:
            print(f"  → ERROR: {r.get('error')}")
        print()

    # ── Summary table ─────────────────────────────────────────────────────────
    valid = [r for r in results if "error" not in r and r.get("sharpe") is not None]
    if not valid:
        print("No valid windows — harness failed.")
        return results

    pooled_sharpe_mean = statistics.mean(r["sharpe"]   for r in valid)
    pooled_dd          = max(r["max_dd"]               for r in valid)
    pooled_wr          = statistics.mean(r["win_rate"] for r in valid)
    total_trades       = sum(r["n_trades"]             for r in valid)

    all_daily: list[float] = []
    for r in valid:
        all_daily.extend(r.get("daily_returns", []))
    if len(all_daily) > 1:
        m = statistics.mean(all_daily)
        s = statistics.stdev(all_daily)
        pooled_sharpe_concat = (m / s) * math.sqrt(252) if s > 0 else 0.0
    else:
        pooled_sharpe_concat = pooled_sharpe_mean

    # ── Side-by-side table ────────────────────────────────────────────────────
    print(SEP)
    print("PASS B RESULTS — MSE-AUGMENTED vs PASS A BASELINE (SIDE BY SIDE)")
    print(SEP)
    hdr = (f"{'Window':<10}  {'── PASS A (baseline) ──':^31}  "
           f"{'── PASS B (MSE) ──':^31}  {'Δ Sharpe':>9}")
    print(hdr)
    print(f"{'':10}  {'Sharpe':>8} {'MaxDD':>6} {'WR':>6} {'TotRet':>8}  "
          f"{'Sharpe':>8} {'MaxDD':>6} {'WR':>6} {'TotRet':>8}  {'(B-A)':>9}")
    print(SEP2)

    result_map = {r["window"]: r for r in results if "error" not in r}
    for window in OOS_WINDOWS:
        wn  = window["name"]
        a   = PASS_A_BASELINE.get(wn, {})
        b   = result_map.get(wn, {})
        if not a or not b:
            print(f"{wn:<10}  (missing)")
            continue
        da  = b["sharpe"] - a["sharpe"]
        print(f"{wn:<10}  "
              f"{a['sharpe']:>+8.3f} {a['max_dd']:>6.1%} "
              f"{a['win_rate']:>6.1%} {a['total_return']:>+8.1%}  "
              f"{b['sharpe']:>+8.3f} {b['max_dd']:>6.1%} "
              f"{b['win_rate']:>6.1%} {b['total_return']:>+8.1%}  "
              f"{da:>+9.3f}")

    print(SEP2)
    pa_pool_s = PASS_A_BASELINE["_pooled_sharpe_concat"]
    pa_pool_d = PASS_A_BASELINE["_pooled_max_dd"]
    delta_s   = pooled_sharpe_concat - pa_pool_s
    delta_d   = pooled_dd - pa_pool_d
    print(f"{'POOLED':<10}  "
          f"{pa_pool_s:>+8.3f} {pa_pool_d:>6.1%} "
          f"{'-':>6} {'-':>8}  "
          f"{pooled_sharpe_concat:>+8.3f} {pooled_dd:>6.1%} "
          f"{pooled_wr:>6.1%} {'-':>8}  "
          f"{delta_s:>+9.3f}")
    print(f"(concat)   pass-a pooled={pa_pool_s:+.3f}  pass-b pooled={pooled_sharpe_concat:+.3f}  "
          f"Δ={delta_s:+.3f}")
    print()

    # ── MSE activity table ────────────────────────────────────────────────────
    print("MSE ACTIVITY PER WINDOW")
    print(SEP2)
    print(f"{'Window':<10}  {'BULL':>5} {'BEAR':>5} {'CRISIS':>7}  "
          f"{'HiVol':>6}  {'BlkCrisis':>10} {'BlkPause':>9}  "
          f"{'SafeHaven':>10} {'CdBlocks':>9}")
    print(SEP2)
    for window in OOS_WINDOWS:
        wn = window["name"]
        b  = result_map.get(wn, {})
        if not b:
            continue
        rgd = b.get("regime_days", {})
        print(f"{wn:<10}  "
              f"{rgd.get('BULL',0):>5} {rgd.get('BEAR',0):>5} {rgd.get('CRISIS',0):>7}  "
              f"{b.get('high_vol_days',0):>6}  "
              f"{b.get('blocked_days_crisis',0):>10} {b.get('blocked_days_pause',0):>9}  "
              f"{b.get('safe_haven_entries',0):>10} {b.get('cooldown_blocks',0):>9}")
    print()

    # ── Verdict ───────────────────────────────────────────────────────────────
    print(SEP)
    print("PASS B VERDICT  (pre-registered bar, no post-hoc tuning)")
    print(SEP)

    # Gate 1: pooled Sharpe ≥ 0.70
    g1 = pooled_sharpe_concat >= 0.70
    print(f"  Gate 1  Pooled Sharpe ≥ 0.70  :  "
          f"{pooled_sharpe_concat:+.3f}  →  {'PASS ✓' if g1 else 'FAIL ✗'}")

    # Gate 2: MaxDD ≤ 14%
    g2 = pooled_dd <= 0.14
    print(f"  Gate 2  MaxDD ≤ 14%            :  "
          f"{pooled_dd:.1%}      →  {'PASS ✓' if g2 else 'FAIL ✗'}")

    # Gate 3: 2021 AND 2022 both improve
    a21 = PASS_A_BASELINE["2021"]["sharpe"]
    a22 = PASS_A_BASELINE["2022"]["sharpe"]
    b21 = result_map.get("2021", {}).get("sharpe", a21)
    b22 = result_map.get("2022", {}).get("sharpe", a22)
    g3a = b21 > a21
    g3b = b22 > a22
    g3  = g3a and g3b
    print(f"  Gate 3a 2021 Sharpe improves   :  "
          f"A={a21:+.3f} → B={b21:+.3f}  Δ={b21-a21:+.3f}  →  {'PASS ✓' if g3a else 'FAIL ✗'}")
    print(f"  Gate 3b 2022 Sharpe improves   :  "
          f"A={a22:+.3f} → B={b22:+.3f}  Δ={b22-a22:+.3f}  →  {'PASS ✓' if g3b else 'FAIL ✗'}")

    # Gate 4: 2019 and 2020 do NOT degrade by more than 0.30
    a19 = PASS_A_BASELINE["2019"]["sharpe"]
    a20 = PASS_A_BASELINE["2020"]["sharpe"]
    b19 = result_map.get("2019", {}).get("sharpe", a19)
    b20 = result_map.get("2020", {}).get("sharpe", a20)
    g4a = (a19 - b19) <= 0.30
    g4b = (a20 - b20) <= 0.30
    g4  = g4a and g4b
    print(f"  Gate 4a 2019 degrade ≤ 0.30    :  "
          f"A={a19:+.3f} → B={b19:+.3f}  drop={a19-b19:.3f}  →  {'PASS ✓' if g4a else 'FAIL ✗'}")
    print(f"  Gate 4b 2020 degrade ≤ 0.30    :  "
          f"A={a20:+.3f} → B={b20:+.3f}  drop={a20-b20:.3f}  →  {'PASS ✓' if g4b else 'FAIL ✗'}")

    print(SEP2)
    all_pass      = g1 and g2 and g3 and g4
    partial_cond  = (g1 and g3) and (not g4b) and (a20 - b20 > 0.30)
    if all_pass:
        verdict = "PASS — MSE overlay earns its complexity across all gates."
    elif partial_cond:
        verdict = ("PARTIAL / DEFENSIVE — pooled improves and 2021/2022 improve, "
                   "but 2020 COVID recovery degrades >0.30 Sharpe. "
                   "MSE is defensive but costs upside. Decide openly.")
    else:
        fails = []
        if not g1: fails.append(f"pooled Sharpe {pooled_sharpe_concat:+.3f}<0.70")
        if not g2: fails.append(f"MaxDD {pooled_dd:.1%}>14%")
        if not g3: fails.append(f"2021/2022 did not both improve")
        if not g4: fails.append(f"2019/2020 degraded >0.30")
        verdict = f"FAIL — {'; '.join(fails)}."
    print(f"\n  VERDICT: {verdict}\n")

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_pass_b(verbose=True)
