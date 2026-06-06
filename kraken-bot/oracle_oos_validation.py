"""
oracle_oos_validation.py — Out-of-sample validation for Oracle (Stock Trend Follower v1.0)

LOCKED PARAMETERS (algo_scanner.py / oracle_exit_manager.py):
  EMA_FAST=20, EMA_SLOW=50
  ADX_PERIOD=14, ADX_ENTRY_MIN=25.0, ADX_EXIT_MIN=20.0
  ATR_PERIOD=14, ATR_MULTIPLIER=2.0
  TRAIL_TRIGGER=2.5  ← live constant (algo_scanner.py L74); docstrings say 1.5 — WRONG
  RISK_PER_TRADE=0.015, MAX_POSITION_PCT=0.20
  MAX_LONG_SLOTS=5, MAX_SHORT_SLOTS=2  (7 total)
  LONG_RSI_LOW=40.0, LONG_RSI_HIGH=75.0
  SHORT_RSI_LOW=25.0, SHORT_RSI_HIGH=60.0
  MOMENTUM_DAYS=10
  MIN_HOLD_DAYS=1   proxy for live 4h min-hold (daily resolution)
  MAX_HOLD_DAYS=15  trading days (oracle_exit_manager.py L46)
  KILL_SWITCH_DD=0.05  5% daily portfolio drawdown halts entries

KNOWN FIDELITY COMPROMISES (flagged in output):
  1. Daily bars instead of live 15-min cycle.
  2. Short "shortable/easy-to-borrow" broker check skipped — assume all shortable.
  3. Min-hold 4h mapped to 1 trading day (first bar of entry protected).
  4. Kill switch 5% approximated on daily open-to-close equity change.
  5. After-hours crypto cycle excluded (separate strategy — not Oracle equity).
  6. TRAIL_TRIGGER=2.5 (live constant) used — NOT 1.5 as stated in docstrings.
  7. Indicators computed via pandas EWM (Wilder-approximation); converges to live
     values after ~50-bar warm-up (fetch starts 2018-01-01 for W1 2019 warm-up).

READ-ONLY. No live orders. No DB writes. No strategy changes.

Run:
    cd kraken-bot
    python3 oracle_oos_validation.py
"""
from __future__ import annotations

import math
import time
import warnings
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# EXACT live strategy parameters
# ─────────────────────────────────────────────────────────────────────────────
EMA_FAST         = 20
EMA_SLOW         = 50
ADX_PERIOD       = 14
ADX_ENTRY_MIN    = 25.0
ADX_EXIT_MIN     = 20.0
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.0
TRAIL_TRIGGER    = 2.5     # algo_scanner.py L74 — docstrings say 1.5 but code is 2.5
RISK_PER_TRADE   = 0.015
MAX_POSITION_PCT = 0.20
MAX_LONG_SLOTS   = 5
MAX_SHORT_SLOTS  = 2
LONG_RSI_LOW     = 40.0
LONG_RSI_HIGH    = 75.0
SHORT_RSI_LOW    = 25.0
SHORT_RSI_HIGH   = 60.0
MOMENTUM_DAYS    = 10
MIN_HOLD_DAYS    = 1       # proxy: 4h min-hold → 1 trading day
MAX_HOLD_DAYS    = 15      # trading days
KILL_SWITCH_DD   = 0.05    # 5% daily drawdown halts new entries
STARTING_CAPITAL = 100_000.0

# ─────────────────────────────────────────────────────────────────────────────
# Universe — FULL_UNIVERSE from momentum_universe.py (inverse_bear_etfs excluded)
# ─────────────────────────────────────────────────────────────────────────────
FULL_UNIVERSE: list[str] = [
    # TECHNOLOGY (42)
    "AAPL", "MSFT", "NVDA", "GOOG", "META", "AMZN", "TSLA", "AMD", "AVGO",
    "CRM", "ORCL", "ADBE", "INTC", "CSCO", "TXN", "QCOM", "MU", "AMAT",
    "LRCX", "KLAC", "MRVL", "SNPS", "CDNS", "NOW", "PANW", "CRWD", "FTNT",
    "NET", "DDOG", "ZS", "PLTR", "ARM", "SMCI", "DELL", "HPE", "UBER",
    "ABNB", "DASH", "SHOP", "XYZ", "SNOW", "COIN", "MSTR",
    # FINANCIALS (21)
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
    "COF", "C", "USB", "PNC", "TFC", "AIG", "MET", "PRU", "ALL", "CB",
    "PYPL",
    # HEALTHCARE (26)
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "ISRG", "BSX", "MDT", "SYK", "EW", "ZTS", "REGN",
    "VRTX", "HCA", "CI", "ELV", "GEHC", "MRNA", "BIIB",
    # ENERGY (17)
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "DVN",
    "HAL", "FANG", "HES", "BKR", "KMI", "FSLR", "ENPH",
    # INDUSTRIALS (21)
    "CAT", "DE", "HON", "UNP", "LMT", "RTX", "GE", "BA", "MMM", "ITW",
    "EMR", "ETN", "PH", "GD", "NOC", "WM", "RSG", "CSX", "NSC", "FDX",
    "UPS",
    # CONSUMER DISCRETIONARY (20)
    "HD", "LOW", "NKE", "SBUX", "MCD", "LULU", "TJX", "ROST", "YUM", "CMG",
    "DHI", "LEN", "GM", "F", "BKNG", "MAR", "HLT", "RCL", "CCL", "EBAY",
    # CONSUMER STAPLES (16)
    "WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "CL", "KMB", "GIS",
    "HSY", "MDLZ", "STZ", "TGT", "DG", "DLTR",
    # COMMUNICATION (11)
    "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "CHTR", "EA", "TTWO",
    "RBLX", "SPOT",
    # MATERIALS (10)
    "LIN", "APD", "ECL", "SHW", "FCX", "NEM", "NUE", "CF", "DD", "DOW",
    # REITS (10)
    "AMT", "PLD", "CCI", "EQIX", "SPG", "O", "PSA", "DLR", "WELL", "AVB",
    # UTILITIES (10)
    "NEE", "DUK", "SO", "AEP", "D", "SRE", "EXC", "XEL", "WEC", "ES",
    # INTERNATIONAL ADRS (9)
    "TSM", "ASML", "NVO", "SAP", "TM", "MELI", "NU", "PDD", "SE",
    # SECTOR ETFS (15)
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLE", "XLI",
    "XLP", "XLY", "XLC", "XLB", "XLRE", "XLU",
    # SAFE HAVEN ETFS (8)
    "TLT", "IEF", "GLD", "SLV", "AGG", "BND", "TIP", "GOVT",
    # COMMODITY ETFS (5)
    "USO", "PDBC", "DBA", "UNG", "COPX",
    # LEVERAGED BULL ETFS (3)
    "TQQQ", "SOXL", "UPRO",
    # INVERSE_BEAR_ETFS excluded: SH PSQ DOG SPXS SQQQ SRTY SDS SDOW
]

WINDOWS = [
    ("W1 2019",    date(2019, 1, 1), date(2019, 12, 31)),
    ("W2 2020",    date(2020, 1, 1), date(2020, 12, 31)),
    ("W3 2021",    date(2021, 1, 1), date(2021, 12, 31)),
    ("W4 2022",    date(2022, 1, 1), date(2022, 12, 31)),
    ("W5 2023-24", date(2023, 1, 1), date(2024, 12, 31)),
]

FETCH_START = date(2018, 1, 1)   # ~252 bar warm-up before W1
FETCH_END   = date(2025, 1, 3)

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_yahoo(ticker: str) -> Optional[pd.DataFrame]:
    p1  = int(datetime(FETCH_START.year, FETCH_START.month, FETCH_START.day).timestamp())
    p2  = int(datetime(FETCH_END.year,   FETCH_END.month,   FETCH_END.day).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        r = requests.get(url, params={"period1": p1, "period2": p2, "interval": "1d"},
                         headers=_YAHOO_HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        data   = r.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        res  = result[0]
        ts   = res.get("timestamp", [])
        q    = res.get("indicators", {}).get("quote", [{}])[0]
        adjl = res.get("indicators", {}).get("adjclose", [{}])
        opens  = q.get("open",  [None] * len(ts))
        highs  = q.get("high",  [None] * len(ts))
        lows   = q.get("low",   [None] * len(ts))
        closes = q.get("close", [None] * len(ts))
        adjc   = adjl[0].get("adjclose", closes) if adjl else closes
        rows = [
            (datetime.utcfromtimestamp(ts[i]).date(),
             opens[i], highs[i], lows[i], closes[i], adjc[i])
            for i in range(len(ts))
            if None not in (opens[i], highs[i], lows[i], closes[i])
        ]
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "adjclose"])
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)
        return df
    except Exception as exc:
        print(f"  WARN: {ticker} fetch failed — {exc}")
        return None


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    l = df["low"]

    # EMA20, EMA50
    df["ema20"] = c.ewm(span=EMA_FAST, adjust=False, min_periods=EMA_FAST).mean()
    df["ema50"] = c.ewm(span=EMA_SLOW, adjust=False, min_periods=EMA_SLOW).mean()

    # 10-day momentum
    df["ret10d"] = c.pct_change(MOMENTUM_DAYS)

    # RSI(14) — Wilder smoothing (com = period-1)
    delta    = c.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=ADX_PERIOD - 1, adjust=False, min_periods=ADX_PERIOD).mean()
    avg_loss = loss.ewm(com=ADX_PERIOD - 1, adjust=False, min_periods=ADX_PERIOD).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    # ATR(14) — Wilder smoothed
    hl  = h - l
    hpc = (h - c.shift(1)).abs()
    lpc = (l - c.shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=ATR_PERIOD - 1, adjust=False, min_periods=ATR_PERIOD).mean()

    # ADX(14) — Wilder smoothed DI+/DI-
    up_move  = h.diff()
    dn_move  = (-l.diff())
    plus_dm  = pd.Series(
        np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0), index=df.index
    )
    sm_tr    = tr.ewm(com=ADX_PERIOD - 1, adjust=False, min_periods=ADX_PERIOD).mean()
    sm_pdm   = plus_dm.ewm(com=ADX_PERIOD - 1, adjust=False, min_periods=ADX_PERIOD).mean()
    sm_mdm   = minus_dm.ewm(com=ADX_PERIOD - 1, adjust=False, min_periods=ADX_PERIOD).mean()
    di_plus  = 100.0 * sm_pdm / sm_tr.replace(0, np.nan)
    di_minus = 100.0 * sm_mdm / sm_tr.replace(0, np.nan)
    denom    = (di_plus + di_minus).replace(0, np.nan)
    dx       = 100.0 * (di_plus - di_minus).abs() / denom
    df["adx"] = dx.ewm(com=ADX_PERIOD - 1, adjust=False, min_periods=ADX_PERIOD).mean()

    return df


# Pre-convert DataFrame to fast dict: date → {col: value}
def _df_to_dict(df: pd.DataFrame) -> dict[date, dict]:
    cols = ["close", "ema20", "ema50", "ret10d", "rsi", "atr", "adx"]
    out: dict[date, dict] = {}
    for idx, row in df[cols].iterrows():
        out[idx] = {c: (None if pd.isna(row[c]) else float(row[c])) for c in cols}
    return out


def _load_universe(tickers: list[str]) -> dict[str, dict[date, dict]]:
    """Load and pre-index all universe data for fast simulation access."""
    print(f"  Fetching {len(tickers)} tickers (≈{len(tickers)*0.35/60:.0f} min)...")
    data: dict[str, dict[date, dict]] = {}
    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i:3d}/{len(tickers)}] {ticker:<8}", end=" ", flush=True)
        df = _fetch_yahoo(ticker)
        if df is None or len(df) < EMA_SLOW + 10:
            print("SKIP (no data / insufficient bars)")
        else:
            df    = _add_indicators(df)
            first = df.index[0]
            print(f"OK  ({len(df)} bars, first={first})")
            data[ticker] = _df_to_dict(df)
        time.sleep(0.3)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Position record
# ─────────────────────────────────────────────────────────────────────────────
class Position:
    __slots__ = [
        "ticker", "side", "entry_price", "qty", "notional",
        "entry_date", "entry_atr", "stop_price", "best_price", "td_held",
    ]

    def __init__(self, ticker: str, side: str, entry_price: float, qty: float,
                 notional: float, entry_date: date, entry_atr: float, stop_price: float):
        self.ticker      = ticker
        self.side        = side
        self.entry_price = entry_price
        self.qty         = qty
        self.notional    = notional   # entry-day notional (fixed — used for cash accounting)
        self.entry_date  = entry_date
        self.entry_atr   = entry_atr
        self.stop_price  = stop_price
        self.best_price  = entry_price  # highest seen for long, lowest for short
        self.td_held     = 0            # trading days held (incremented each bar after entry)


# ─────────────────────────────────────────────────────────────────────────────
# Backtest engine — explicit cash tracking (mirrors Jerome harness pattern)
# ─────────────────────────────────────────────────────────────────────────────
def run_window(
    data: dict[str, dict[date, dict]],
    start: date,
    end: date,
) -> dict:
    # Tickers with any data in this window
    tradeable = sorted(
        t for t in data
        if any(start <= d <= end for d in data[t])
    )
    skipped = sorted(t for t in FULL_UNIVERSE if t not in tradeable)

    all_dates: list[date] = sorted({
        d for t in tradeable for d in data[t] if start <= d <= end
    })

    cash             = STARTING_CAPITAL    # uninvested cash (explicit)
    open_longs:  list[Position] = []
    open_shorts: list[Position] = []
    closed_trades: list[dict]   = []
    equity_curve: list[tuple]   = []
    peak_equity      = STARTING_CAPITAL
    max_drawdown     = 0.0

    for dt in all_dates:
        # ── 0. Compute start-of-day equity for kill switch ────────────────
        mtm_bos = cash
        for pos in open_longs + open_shorts:
            row = data[pos.ticker].get(dt)
            if row and row["close"] is not None:
                close = row["close"]
                if pos.side == "long":
                    mtm_bos += pos.notional + (close - pos.entry_price) * pos.qty
                else:
                    mtm_bos += pos.notional + (pos.entry_price - close) * pos.qty
            else:
                mtm_bos += pos.notional
        equity_bos = mtm_bos

        # ── 1. Update trailing stops + check exits ────────────────────────
        still_longs:  list[Position] = []
        still_shorts: list[Position] = []

        for pos in open_longs + open_shorts:
            row = data[pos.ticker].get(dt)
            if row is None or row["close"] is None:
                (still_longs if pos.side == "long" else still_shorts).append(pos)
                continue

            close = row["close"]
            atr   = row["atr"]   if row["atr"]   is not None else pos.entry_atr
            ema20 = row["ema20"]
            ema50 = row["ema50"]
            adx   = row["adx"]   if row["adx"]   is not None else 0.0

            pos.td_held += 1

            # Update best_price (ratchet)
            if pos.side == "long":
                if close > pos.best_price:
                    pos.best_price = close
            else:
                if close < pos.best_price:
                    pos.best_price = close

            # Update trailing stop if profit >= ATR × TRAIL_TRIGGER
            if atr and atr > 0:
                profit_dist = (
                    (close - pos.entry_price) if pos.side == "long"
                    else (pos.entry_price - close)
                )
                if profit_dist >= atr * TRAIL_TRIGGER:
                    if pos.side == "long":
                        candidate = pos.best_price - atr * ATR_MULTIPLIER
                        if candidate > pos.stop_price:
                            pos.stop_price = candidate
                    else:
                        candidate = pos.best_price + atr * ATR_MULTIPLIER
                        if candidate < pos.stop_price:
                            pos.stop_price = candidate

            # Unrealized P&L for profit-buffer gates
            unrealized_pnl = (
                (close - pos.entry_price) * pos.qty if pos.side == "long"
                else (pos.entry_price - close) * pos.qty
            )
            exit_reason: Optional[str] = None

            # Priority 1: trailing stop — always fires (overrides min-hold)
            stop_hit = (
                (pos.side == "long"  and close <= pos.stop_price) or
                (pos.side == "short" and close >= pos.stop_price)
            )
            if stop_hit:
                exit_reason = "trailing_stop"

            elif pos.td_held >= MIN_HOLD_DAYS:
                # Priority 2: EMA reversal (only if in profit)
                if ema20 is not None and ema50 is not None and unrealized_pnl > 0:
                    ema_rev = (
                        (pos.side == "long"  and ema20 < ema50) or
                        (pos.side == "short" and ema20 > ema50)
                    )
                    if ema_rev:
                        exit_reason = "ema_reversal"

                # Priority 3: ADX weakness (only if in profit)
                if exit_reason is None and adx > 0 and adx < ADX_EXIT_MIN and unrealized_pnl > 0:
                    exit_reason = f"adx_weak"

                # Priority 4: max hold 15 trading days
                if exit_reason is None and pos.td_held >= MAX_HOLD_DAYS:
                    exit_reason = "max_hold"

            if exit_reason:
                pnl_usd = (
                    (close - pos.entry_price) * pos.qty if pos.side == "long"
                    else (pos.entry_price - close) * pos.qty
                )
                # Return notional + pnl to cash (explicit — matches Jerome pattern)
                cash += pos.notional + pnl_usd
                closed_trades.append({
                    "ticker":      pos.ticker,
                    "side":        pos.side,
                    "entry_date":  pos.entry_date,
                    "exit_date":   dt,
                    "hold_days":   (dt - pos.entry_date).days,
                    "td_held":     pos.td_held,
                    "entry_price": pos.entry_price,
                    "exit_price":  close,
                    "qty":         pos.qty,
                    "notional":    pos.notional,
                    "pnl_usd":     round(pnl_usd, 2),
                    "pnl_pct":     round(pnl_usd / pos.notional * 100, 2) if pos.notional else 0,
                    "exit_reason": exit_reason,
                })
            else:
                (still_longs if pos.side == "long" else still_shorts).append(pos)

        open_longs  = still_longs
        open_shorts = still_shorts

        # ── 2. Mark-to-market equity ──────────────────────────────────────
        mtm = cash
        for pos in open_longs + open_shorts:
            row = data[pos.ticker].get(dt)
            if row and row["close"] is not None:
                close = row["close"]
                if pos.side == "long":
                    mtm += pos.notional + (close - pos.entry_price) * pos.qty
                else:
                    mtm += pos.notional + (pos.entry_price - close) * pos.qty
            else:
                mtm += pos.notional
        equity = mtm
        equity_curve.append((dt, round(equity, 2)))

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100.0
        if dd > max_drawdown:
            max_drawdown = dd

        # ── 3. Kill switch: skip entries if daily loss >= 5% ─────────────
        daily_loss_pct = (equity_bos - equity) / equity_bos if equity_bos > 0 else 0.0
        if daily_loss_pct >= KILL_SWITCH_DD:
            continue

        # ── 4. Entry scan ─────────────────────────────────────────────────
        open_syms    = {p.ticker for p in open_longs + open_shorts}
        n_open_long  = len(open_longs)
        n_open_short = len(open_shorts)

        if n_open_long >= MAX_LONG_SLOTS and n_open_short >= MAX_SHORT_SLOTS:
            continue

        long_cands:  list[dict] = []
        short_cands: list[dict] = []

        for ticker in tradeable:
            if ticker in open_syms:
                continue
            row = data[ticker].get(dt)
            if row is None:
                continue
            close = row["close"]
            ema20 = row["ema20"]
            ema50 = row["ema50"]
            adx   = row["adx"]
            atr   = row["atr"]
            rsi   = row["rsi"]
            r10   = row["ret10d"]

            if any(v is None for v in (close, ema20, ema50, adx, atr, rsi, r10)):
                continue
            if close <= 0 or atr <= 0:
                continue
            if adx < ADX_ENTRY_MIN:
                continue

            ema_spread = (ema20 - ema50) / ema50 * 100.0

            if (ema20 > ema50
                    and r10 > 0
                    and LONG_RSI_LOW <= rsi <= LONG_RSI_HIGH
                    and close > ema20):
                long_cands.append({
                    "ticker": ticker, "close": close, "atr": atr,
                    "adx": adx, "ema_spread": ema_spread,
                })
            elif (ema20 < ema50
                    and r10 < 0
                    and SHORT_RSI_LOW <= rsi <= SHORT_RSI_HIGH
                    and close < ema20):
                short_cands.append({
                    "ticker": ticker, "close": close, "atr": atr,
                    "adx": adx, "ema_spread": ema_spread,
                })

        # Rank: ADX desc, then |EMA spread| desc
        long_cands.sort(key=lambda x: (x["adx"], abs(x["ema_spread"])), reverse=True)
        short_cands.sort(key=lambda x: (x["adx"], abs(x["ema_spread"])), reverse=True)

        # Fill long slots
        for c in long_cands:
            if n_open_long >= MAX_LONG_SLOTS:
                break
            if c["ticker"] in open_syms:
                continue
            close_p = c["close"]
            atr_val = c["atr"]
            risk_usd  = equity * RISK_PER_TRADE
            stop_dist = atr_val * ATR_MULTIPLIER
            shares    = risk_usd / stop_dist
            notional  = shares * close_p
            if notional / equity > MAX_POSITION_PCT:
                notional = equity * MAX_POSITION_PCT
                shares   = notional / close_p
            if notional < 500 or notional > cash:
                continue
            stop_price = close_p - stop_dist
            pos = Position(c["ticker"], "long", close_p, shares, notional,
                           dt, atr_val, stop_price)
            open_longs.append(pos)
            open_syms.add(c["ticker"])
            cash -= notional
            n_open_long += 1

        # Fill short slots
        for c in short_cands:
            if n_open_short >= MAX_SHORT_SLOTS:
                break
            if c["ticker"] in open_syms:
                continue
            close_p = c["close"]
            atr_val = c["atr"]
            risk_usd  = equity * RISK_PER_TRADE
            stop_dist = atr_val * ATR_MULTIPLIER
            shares    = risk_usd / stop_dist
            notional  = shares * close_p
            if notional / equity > MAX_POSITION_PCT:
                notional = equity * MAX_POSITION_PCT
                shares   = notional / close_p
            if notional < 500 or notional > cash:
                continue
            stop_price = close_p + stop_dist
            pos = Position(c["ticker"], "short", close_p, shares, notional,
                           dt, atr_val, stop_price)
            open_shorts.append(pos)
            open_syms.add(c["ticker"])
            cash -= notional
            n_open_short += 1

    # ── Force-close remaining positions at window end ─────────────────────
    last_dt = all_dates[-1] if all_dates else end
    for pos in open_longs + open_shorts:
        row = data[pos.ticker].get(last_dt)
        close = (row["close"] if row and row["close"] is not None else None)
        if close is None:
            # scan backward for last available price
            candidates = [d for d in data[pos.ticker] if d <= last_dt]
            if candidates:
                d2  = max(candidates)
                row2 = data[pos.ticker][d2]
                close = row2["close"] or pos.entry_price
            else:
                close = pos.entry_price
        pnl_usd = (
            (close - pos.entry_price) * pos.qty if pos.side == "long"
            else (pos.entry_price - close) * pos.qty
        )
        closed_trades.append({
            "ticker":      pos.ticker,
            "side":        pos.side,
            "entry_date":  pos.entry_date,
            "exit_date":   last_dt,
            "hold_days":   (last_dt - pos.entry_date).days,
            "td_held":     pos.td_held,
            "entry_price": pos.entry_price,
            "exit_price":  close,
            "qty":         pos.qty,
            "notional":    pos.notional,
            "pnl_usd":     round(pnl_usd, 2),
            "pnl_pct":     round(pnl_usd / pos.notional * 100, 2) if pos.notional else 0,
            "exit_reason": "forced_close_eow",
        })

    return {
        "equity_curve":  equity_curve,
        "closed_trades": closed_trades,
        "max_drawdown":  round(max_drawdown, 2),
        "final_equity":  round(equity_curve[-1][1] if equity_curve else STARTING_CAPITAL, 2),
        "tradeable":     tradeable,
        "skipped":       skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────
def _window_stats(result: dict) -> dict:
    trades   = result["closed_trades"]
    eq_curve = result["equity_curve"]
    final_eq = result["final_equity"]
    max_dd   = result["max_drawdown"]
    n        = len(trades)
    total_ret = (final_eq - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0

    if n == 0:
        return {
            "trades": 0, "win_rate": None, "total_return": total_ret,
            "sharpe": None, "max_drawdown": max_dd, "avg_hold": None,
            "best_trade": None, "worst_trade": None,
            "tradeable": result["tradeable"], "skipped": result["skipped"],
        }

    winners  = [t for t in trades if t["pnl_usd"] > 0]
    win_rate = len(winners) / n * 100.0

    eq_s     = pd.Series(
        [e for _, e in eq_curve],
        index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in eq_curve])
    )
    daily_ret = eq_s.pct_change().dropna()
    sharpe    = (
        daily_ret.mean() / daily_ret.std() * math.sqrt(252)
        if len(daily_ret) > 1 and daily_ret.std() > 0 else None
    )

    avg_hold  = sum(t["hold_days"] for t in trades) / n
    best      = max(trades, key=lambda t: t["pnl_pct"])
    worst     = min(trades, key=lambda t: t["pnl_pct"])

    return {
        "trades":       n,
        "win_rate":     round(win_rate, 1),
        "total_return": round(total_ret, 2),
        "sharpe":       round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown": max_dd,
        "avg_hold":     round(avg_hold, 1),
        "best_trade":   f"{best['ticker']} {best['pnl_pct']:+.1f}%",
        "worst_trade":  f"{worst['ticker']} {worst['pnl_pct']:+.1f}%",
        "tradeable":    result["tradeable"],
        "skipped":      result["skipped"],
    }


def _pooled_stats(all_results: list[dict]) -> dict:
    all_trades: list[dict] = []
    all_eq: list[tuple]    = []
    for r in all_results:
        all_trades.extend(r["closed_trades"])
        all_eq.extend(r["equity_curve"])

    if not all_trades:
        return {"trades": 0, "win_rate": None, "sharpe": None, "total_return": None}

    all_eq.sort(key=lambda x: x[0])
    eq_s      = pd.Series([e for _, e in all_eq],
                          index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in all_eq]))
    daily_ret = eq_s.pct_change().dropna()
    sharpe    = (
        daily_ret.mean() / daily_ret.std() * math.sqrt(252)
        if len(daily_ret) > 1 and daily_ret.std() > 0 else None
    )
    n         = len(all_trades)
    winners   = [t for t in all_trades if t["pnl_usd"] > 0]
    total_pnl = sum(t["pnl_usd"] for t in all_trades)

    return {
        "trades":       n,
        "win_rate":     round(len(winners) / n * 100.0, 1),
        "sharpe":       round(sharpe, 3) if sharpe is not None else None,
        "total_return": round(total_pnl / STARTING_CAPITAL * 100.0, 2),
        "avg_hold":     round(sum(t["hold_days"] for t in all_trades) / n, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pass/Fail (4 criteria per user spec)
# ─────────────────────────────────────────────────────────────────────────────
def _evaluate(window_stats: list[dict], pooled: dict):
    # 1. Positive return AND positive Sharpe in >= 4/5 windows
    pos_both = sum(
        1 for s in window_stats
        if (s["total_return"] is not None and s["total_return"] > 0)
        and (s["sharpe"] is not None and s["sharpe"] > 0)
    )

    # 2. No window MaxDD > 20%
    no_big_dd = all(s["max_drawdown"] <= 20.0 for s in window_stats)

    # 3. Pooled Sharpe >= 0.5
    pooled_sharpe_ok = pooled["sharpe"] is not None and pooled["sharpe"] >= 0.5

    # 4. Survived 2020 (W2) + 2022 (W4) — no MaxDD > 20% in stress windows
    w2_dd = window_stats[1]["max_drawdown"]
    w4_dd = window_stats[3]["max_drawdown"]
    stress_ok = w2_dd <= 20.0 and w4_dd <= 20.0

    criteria = [
        ("Positive return+Sharpe ≥4/5 windows", pos_both >= 4,   f"{pos_both}/5"),
        ("No window MaxDD > 20%",                no_big_dd,        "OK" if no_big_dd else "FAIL"),
        ("Pooled Sharpe ≥ 0.5",                  pooled_sharpe_ok, f"{pooled['sharpe']}"),
        ("Survived 2020+2022 (MaxDD≤20%)",        stress_ok,        f"W2={w2_dd:.1f}% W4={w4_dd:.1f}%"),
    ]
    met = sum(1 for _, passed, _ in criteria if passed)
    if met == 4:
        verdict = "PASS"
    elif met >= 2:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    return verdict, criteria, met


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────
SEP  = "═" * 82
SEP2 = "─" * 82


def _print_table(window_stats_list: list[dict]) -> None:
    print(f"\n{SEP}")
    print("  ORACLE (Stock Trend Follower v1.0) — OUT-OF-SAMPLE RESULTS")
    print(SEP)
    print(f"  {'Window':<12} {'Tradeable':>10} {'Trades':>7} {'WR%':>6} "
          f"{'Return':>9} {'Sharpe':>8} {'MaxDD':>7} {'AvgHold':>9} {'Verdict':>8}")
    print(f"  {SEP2}")
    for (wname, _, _), s in zip(WINDOWS, window_stats_list):
        td_s  = f"{len(s['tradeable'])}/{len(FULL_UNIVERSE)}"
        tr_s  = str(s["trades"])
        wr_s  = f"{s['win_rate']:.0f}%" if s["win_rate"] is not None else "—"
        ret_s = f"{s['total_return']:+.1f}%" if s["total_return"] is not None else "—"
        sh_s  = f"{s['sharpe']:.3f}" if s["sharpe"] is not None else "—"
        dd_s  = f"{s['max_drawdown']:.1f}%"
        hld_s = f"{s['avg_hold']:.0f}d" if s["avg_hold"] is not None else "—"
        win   = (s["total_return"] is not None and s["total_return"] > 0 and
                 s["sharpe"] is not None and s["sharpe"] > 0)
        print(f"  {wname:<12} {td_s:>10} {tr_s:>7} {wr_s:>6} "
              f"{ret_s:>9} {sh_s:>8} {dd_s:>7} {hld_s:>9} {'PASS' if win else 'FAIL':>8}")


def _print_pooled_verdict(pooled: dict, verdict: str, criteria: list, met: int) -> None:
    stars = {"PASS": "✅ PASS", "MARGINAL": "⚠️  MARGINAL", "FAIL": "❌ FAIL"}
    wr_s  = f"{pooled['win_rate']:.0f}%" if pooled["win_rate"] is not None else "—"
    sh_s  = f"{pooled['sharpe']:.3f}"    if pooled["sharpe"]   is not None else "—"
    ret_s = f"{pooled['total_return']:+.1f}%" if pooled["total_return"] is not None else "—"
    hld_s = f"{pooled['avg_hold']:.0f}d"      if pooled.get("avg_hold") is not None else "—"
    print(f"  {'POOLED':<12} {'—':>10} {pooled['trades']:>7} {wr_s:>6} "
          f"{ret_s:>9} {sh_s:>8} {'—':>7} {hld_s:>9} {stars[verdict]:>8}")
    print(f"\n  {SEP2}")
    print(f"  PASS/FAIL CRITERIA ({met}/4 met):")
    for label, passed, detail in criteria:
        mark = "✅" if passed else "❌"
        print(f"    {mark} {label:<46} {detail}")
    print(f"\n  OVERALL VERDICT: {stars[verdict]}")


def _print_skipped(window_stats_list: list[dict]) -> None:
    print(f"\n{SEP}")
    print("  TICKERS SKIPPED PER WINDOW (not yet listed / insufficient data)")
    print(SEP)
    for (wname, _, _), s in zip(WINDOWS, window_stats_list):
        missing = s["skipped"]
        if missing:
            print(f"  {wname}: {', '.join(missing)} ({len(missing)} total)")
        else:
            print(f"  {wname}: none skipped")


def _print_fidelity_flags() -> None:
    print(f"\n{SEP}")
    print("  FIDELITY COMPROMISES (known backtest vs live differences)")
    print(SEP)
    for f in [
        "1. Daily bars used instead of live 15-min cycle.",
        "2. Short 'shortable/easy-to-borrow' check SKIPPED — all shorts assumed eligible.",
        "3. Min-hold 4h → 1 trading day (daily bar resolution limit).",
        "4. Kill switch 5% DD approximated on daily open-to-close equity change.",
        "5. After-hours crypto cycle EXCLUDED (separate Z-score/RSI mean-reversion strategy).",
        "6. TRAIL_TRIGGER=2.5 (live constant) used — NOT 1.5 as stated in docstrings.",
        "7. Indicators via pandas EWM (≈ Wilder); converges to live values after ~50-bar warm-up.",
    ]:
        print(f"  ⚠  {f}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print(SEP)
    print("  OUT-OF-SAMPLE VALIDATION — ORACLE (Stock Trend Follower v1.0)")
    print(f"  EMA{EMA_FAST}/{EMA_SLOW}  ADX_entry≥{ADX_ENTRY_MIN}  ADX_exit<{ADX_EXIT_MIN}  "
          f"ATR×{ATR_MULTIPLIER}  TRAIL_TRIGGER={TRAIL_TRIGGER}  RISK={RISK_PER_TRADE*100:.1f}%")
    print(f"  MAX_POS_PCT={MAX_POSITION_PCT*100:.0f}%  SLOTS={MAX_LONG_SLOTS}L+{MAX_SHORT_SLOTS}S  "
          f"MAX_HOLD={MAX_HOLD_DAYS}td  KILL_SWITCH={KILL_SWITCH_DD*100:.0f}%dd")
    print(f"  Universe: {len(FULL_UNIVERSE)} tickers  |  Data: {FETCH_START} → {FETCH_END}")
    print(f"  Starting capital per window: ${STARTING_CAPITAL:,.0f}")
    print(SEP)

    _print_fidelity_flags()

    print(f"\n{SEP}")
    print("  LOADING UNIVERSE DATA")
    print(SEP)
    data = _load_universe(FULL_UNIVERSE)
    print(f"\n  Loaded: {len(data)}/{len(FULL_UNIVERSE)} tickers with data")

    print(f"\n{SEP}")
    print("  RUNNING WINDOWS")
    print(SEP)
    all_results: list[dict] = []
    all_stats:   list[dict] = []
    for wname, wstart, wend in WINDOWS:
        print(f"\n  → {wname} ({wstart} → {wend})", flush=True)
        res   = run_window(data, wstart, wend)
        stats = _window_stats(res)
        all_results.append(res)
        all_stats.append(stats)
        print(f"     tradeable={len(res['tradeable'])}/{len(FULL_UNIVERSE)}  "
              f"trades={stats['trades']}  WR={stats['win_rate']}%  "
              f"return={stats['total_return']:+.1f}%  sharpe={stats['sharpe']}  "
              f"maxDD={stats['max_drawdown']:.1f}%")

    pooled                 = _pooled_stats(all_results)
    verdict, criteria, met = _evaluate(all_stats, pooled)

    _print_table(all_stats)
    _print_pooled_verdict(pooled, verdict, criteria, met)
    _print_skipped(all_stats)
    print(f"\n{SEP}")


if __name__ == "__main__":
    main()
