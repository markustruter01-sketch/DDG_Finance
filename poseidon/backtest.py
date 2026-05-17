#!/usr/bin/env python3
"""
backtest.py — Poseidon Regime-Adaptive Strategy Backtest
=========================================================
6-month bar-by-bar simulation on 4h OKX data.
Reports overall P&L and breakdown by regime mode (breakout vs mean reversion).
"""
from __future__ import annotations

import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, ".")

import ccxt

import config as cfg
from strategy import (
    calculate_atr,
    classify_regime,
    evaluate_entry,
    check_exit,
    calculate_position_size,
)

# =========================================================================
# CONSTANTS
# =========================================================================
LOOKBACK_DAYS    = 180
TIMEFRAME        = "4h"                        # 4h candles
BARS_PER_DAY     = 6                           # 4h bars per day
STARTING_EQUITY  = cfg.PAPER_STARTING_BALANCE
FEE_PCT          = cfg.PAPER_FEE_PCT
SLIPPAGE_PCT     = 0.001

SYMBOLS          = cfg.SYMBOLS                 # Kraken names
BACKTEST_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]   # OKX format
EXCHANGE_NAME    = "okx"

MIN_BARS_NEEDED  = max(cfg.ADX_PERIOD * 3, cfg.BREAKOUT_BB_PERIOD) + 10
ATR_HISTORY_BARS = cfg.ATR_BASELINE_WINDOW * BARS_PER_DAY   # ~540 bars of ATR history

# =========================================================================
# DATA FETCH  — OKX (reachable from Replit, 300 bars/request)
# =========================================================================

def fetch_historical(symbol: str, timeframe: str, days: int) -> List[List]:
    exchange = ccxt.okx({"enableRateLimit": True})
    ms_per_candle = exchange.parse_timeframe(timeframe) * 1000
    end_ms   = exchange.milliseconds()
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)

    all_bars: List[List] = []
    since    = start_ms
    safety   = 0

    while since < end_ms:
        safety += 1
        if safety > 200:
            print(f"    safety break at {len(all_bars)} bars")
            break
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=300)
        except Exception as e:
            print(f"    fetch error: {e}; retrying in 2s")
            time.sleep(2)
            continue
        if not batch:
            break
        all_bars.extend(batch)
        new_since = batch[-1][0] + ms_per_candle
        if new_since <= since:
            break
        since = new_since

    return all_bars

# =========================================================================
# SIMULATION STATE
# =========================================================================

class BtPosition:
    def __init__(self, symbol, direction, entry_price, units,
                 stop_distance, entry_idx, atr, mode):
        self.symbol        = symbol
        self.direction     = direction
        self.entry_price   = entry_price
        self.units         = units
        self.stop_distance = stop_distance
        self.entry_idx     = entry_idx
        self.atr           = atr
        self.mode          = mode
        self.best_price    = entry_price

    def as_dict(self) -> Dict:
        """Return a position dict compatible with strategy.check_exit."""
        return {
            "symbol":      self.symbol,
            "direction":   self.direction,
            "entry_price": self.entry_price,
            "units":       self.units,
            "atr":         self.atr,
            "mode":        self.mode,
            "best_price":  self.best_price,
        }

# =========================================================================
# INNER SIMULATION
# =========================================================================

def run_backtest(histories: Dict[str, List[List]]) -> Tuple[float, List[dict], float, int]:
    min_len = min(len(b) for b in histories.values())
    aligned = {sym: bars[-min_len:] for sym, bars in histories.items()}

    equity      = STARTING_EQUITY
    peak_equity = STARTING_EQUITY
    max_dd      = 0.0
    positions: Dict[str, BtPosition] = {}
    trades: List[dict] = []

    for i in range(MIN_BARS_NEEDED, min_len):

        # ── Exit check ────────────────────────────────────────────────────
        for sym, pos in list(positions.items()):
            bars           = aligned[sym]
            current_price  = bars[i][4]   # close
            slice_start    = max(0, i - cfg.BREAKOUT_BB_PERIOD * 4)
            closes_window  = [b[4] for b in bars[slice_start: i + 1]]

            pos_dict = pos.as_dict()
            hours_held = (i - pos.entry_idx) * 4   # 4h candles → hours

            reason = check_exit(pos_dict, current_price, closes_window, hours_held, cfg)
            pos.best_price = pos_dict.get("best_price", pos.best_price)  # sync updated peak

            if reason:
                if pos.direction == "long":
                    exit_slip = current_price * (1 - SLIPPAGE_PCT)
                    gross     = (exit_slip - pos.entry_price) * pos.units
                else:
                    exit_slip = current_price * (1 + SLIPPAGE_PCT)
                    gross     = (pos.entry_price - exit_slip) * pos.units
                fee   = (pos.entry_price + exit_slip) * pos.units * FEE_PCT
                pnl   = gross - fee
                equity += pnl
                trades.append({
                    "symbol":    sym,
                    "direction": pos.direction,
                    "mode":      pos.mode,
                    "entry":     pos.entry_price,
                    "exit":      exit_slip,
                    "units":     pos.units,
                    "pnl":       pnl,
                    "reason":    reason,
                    "hours":     hours_held,
                })
                del positions[sym]

        # ── Drawdown tracking ─────────────────────────────────────────────
        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity
        if dd > max_dd:
            max_dd = dd

        # ── Entry scan ────────────────────────────────────────────────────
        if len(positions) >= cfg.MAX_POSITIONS:
            continue

        for live_sym in SYMBOLS:
            if live_sym in positions:
                continue
            if live_sym not in aligned:
                continue

            bars  = aligned[live_sym]
            slice_start = max(0, i - 400)
            window      = bars[slice_start: i + 1]

            closes_4h  = [b[4] for b in window]
            highs_4h   = [b[2] for b in window]
            lows_4h    = [b[3] for b in window]
            volumes_4h = [b[5] for b in window]

            # Build ATR history for regime classifier percentile
            atr_start = max(0, i - ATR_HISTORY_BARS)
            atr_window = bars[atr_start: i + 1]
            atr_history: List[float] = []
            for j in range(cfg.ADX_PERIOD + 1, len(atr_window)):
                c  = [b[4] for b in atr_window[:j + 1]]
                h  = [b[2] for b in atr_window[:j + 1]]
                lo = [b[3] for b in atr_window[:j + 1]]
                a  = calculate_atr(h, lo, c, cfg.ADX_PERIOD)
                if a > 0:
                    atr_history.append(a)

            signal = evaluate_entry(
                live_sym, closes_4h, highs_4h, lows_4h, volumes_4h,
                closes_4h, volumes_4h,   # 1h not fetched separately — use 4h as proxy
                cfg,
                atr_history=atr_history,
            )

            if signal is None:
                continue

            price    = signal["price"]
            atr_val  = signal["atr"]
            mode     = signal.get("mode", "breakout")

            units, pos_usd = calculate_position_size(equity, price, atr_val, cfg)
            if units <= 0:
                continue

            # Apply entry slippage
            if signal["direction"] == "long":
                fill_price = price * (1 + SLIPPAGE_PCT)
            else:
                fill_price = price * (1 - SLIPPAGE_PCT)

            entry_fee = fill_price * units * FEE_PCT
            equity   -= entry_fee

            stop_dist = (
                atr_val * cfg.BREAKOUT_ATR_STOP_MULT if mode == "breakout"
                else atr_val * cfg.MEANREV_ATR_STOP_MULT
            )

            positions[live_sym] = BtPosition(
                symbol=live_sym,
                direction=signal["direction"],
                entry_price=fill_price,
                units=units,
                stop_distance=stop_dist,
                entry_idx=i,
                atr=atr_val,
                mode=mode,
            )

    return equity, trades, max_dd, min_len

# =========================================================================
# REPORTING
# =========================================================================

def print_results(equity: float, trades: List[dict], max_dd: float, total_bars: int):
    n       = len(trades)
    pnl     = equity - STARTING_EQUITY
    pct     = pnl / STARTING_EQUITY * 100
    wins    = [t for t in trades if t["pnl"] > 0]
    losses  = [t for t in trades if t["pnl"] <= 0]
    wr      = len(wins) / n * 100 if n else 0
    avg_win = sum(t["pnl"] for t in wins)  / len(wins)  if wins   else 0
    avg_los = sum(t["pnl"] for t in losses)/ len(losses) if losses else 0
    gross_w = sum(t["pnl"] for t in wins)
    gross_l = abs(sum(t["pnl"] for t in losses))
    pf      = gross_w / gross_l if gross_l > 0 else float("inf")
    exp     = pnl / n if n else 0
    days    = total_bars * 4 / 24

    print(f"\nTotal trades:     {n}")
    print(f"Final equity:     ${equity:,.2f}")
    print(f"Total P&L:        ${pnl:,.2f}  ({pct:+.2f}%)")
    print(f"Max drawdown:     {max_dd * 100:.2f}%")
    print(f"Period:           ~{days:.0f} days (~{days/30:.1f} months)")
    if n > 0:
        print(f"Win rate:         {wr:.1f}%  ({len(wins)}W / {len(losses)}L)")
        print(f"Profit factor:    {pf:.2f}")
        print(f"Avg win:          ${avg_win:,.2f}")
        print(f"Avg loss:         ${avg_los:,.2f}")
        print(f"Expectancy/trade: ${exp:,.2f}")
        best = max(t["pnl"] for t in trades)
        worst = min(t["pnl"] for t in trades)
        avg_h = sum(t["hours"] for t in trades) / n
        print(f"Best trade:       ${best:,.2f}")
        print(f"Worst trade:      ${worst:,.2f}")
        print(f"Avg hold (hrs):   {avg_h:.1f}")

        # Per-symbol
        print("\n  --- Per-symbol ---")
        for sym in SYMBOLS:
            st = [t for t in trades if t["symbol"] == sym]
            if not st:
                continue
            sw = [t for t in st if t["pnl"] > 0]
            sym_pnl = sum(t["pnl"] for t in st)
            print(f"    {sym}: {len(st)} trades, {len(sw)}/{len(st)} wins "
                  f"({len(sw)*100//len(st)}%), P&L ${sym_pnl:,.2f}")

        # By mode
        print("\n  --- By regime mode ---")
        for mode in ["breakout", "meanrev"]:
            mt = [t for t in trades if t.get("mode") == mode]
            if not mt:
                print(f"    {mode}: no trades")
                continue
            mw = [t for t in mt if t["pnl"] > 0]
            m_pnl = sum(t["pnl"] for t in mt)
            m_wr = len(mw) / len(mt) * 100
            m_gw = sum(t["pnl"] for t in mw)
            m_gl = abs(sum(t["pnl"] for t in mt if t["pnl"] <= 0))
            m_pf = m_gw / m_gl if m_gl > 0 else float("inf")
            print(f"    {mode}: {len(mt)} trades  WR={m_wr:.1f}%  "
                  f"PF={m_pf:.2f}  P&L=${m_pnl:,.2f}")

        # Exit reasons
        print("\n  --- Exit reasons ---")
        reason_map: Dict[str, List[float]] = {}
        for t in trades:
            r = t["reason"] if not t["reason"].startswith("time_stop") else "time_stop"
            reason_map.setdefault(r, []).append(t["pnl"])
        for r, pnls in sorted(reason_map.items(), key=lambda x: -len(x[1])):
            avg = sum(pnls) / len(pnls)
            print(f"    {r:<30}: {len(pnls):3d} trades, avg ${avg:,.2f}")
    else:
        print("  No trades generated.")

# =========================================================================
# MAIN
# =========================================================================

def main():
    print("=== BACKTEST: Poseidon Regime-Adaptive Strategy ===")
    print(f"Universe: {SYMBOLS}")
    print(f"Lookback: {LOOKBACK_DAYS} days | timeframe: {TIMEFRAME}")
    print(f"Starting equity: ${STARTING_EQUITY:,.2f} | Fee: {FEE_PCT*100:.2f}% | "
          f"Slippage: {SLIPPAGE_PCT*100:.2f}%")
    print()

    print(f"Fetching {LOOKBACK_DAYS} days of {TIMEFRAME} data from {EXCHANGE_NAME}...")
    histories: Dict[str, List[List]] = {}
    for okx_sym, live_sym in zip(BACKTEST_SYMBOLS, SYMBOLS):
        print(f"  {okx_sym} (live: {live_sym})... ", end="", flush=True)
        bars = fetch_historical(okx_sym, TIMEFRAME, LOOKBACK_DAYS)
        print(f"{len(bars)} bars")
        if bars:
            histories[live_sym] = bars   # key by live symbol for position dict compat

    if not histories:
        print("No data fetched — abort.")
        return

    min_len = min(len(b) for b in histories.values())
    days_approx = min_len * 4 / 24
    print(f"\nAligned series: {min_len} bars (~{days_approx:.0f} days, "
          f"~{days_approx/30:.1f} months)")

    print("\n" + "=" * 60)
    equity, trades, max_dd, total_bars = run_backtest(histories)
    print_results(equity, trades, max_dd, total_bars)
    print("=" * 60)

    # Final safety check
    print(f"\nposeidon_control.json status: ", end="")
    try:
        import json
        with open("poseidon/poseidon_control.json") as f:
            ctrl = json.load(f)
        print(f"bot_paused={ctrl.get('bot_paused')} ✓" if ctrl.get("bot_paused")
              else "WARNING: bot not paused!")
    except Exception as e:
        print(f"could not read: {e}")


if __name__ == "__main__":
    main()
