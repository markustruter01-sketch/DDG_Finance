"""Backtest the mean reversion strategy on historical Kraken data.

Usage: python3 backtest_mean_reversion.py

Fetches 6 months of 1h candles for BTC/USD, ETH/USD, SOL/USD,
simulates the strategy bar-by-bar, and reports win rate, profit factor,
expectancy, max drawdown, and per-symbol breakdown.

Bot stays paused — this is paper-paper validation, no live writes."""

import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

sys.path.insert(0, '.')

import ccxt
import config as cfg
from trend_engine import (
    evaluate_trend_signal,
    calculate_position_size,
    calculate_atr,
    check_mean_reversion_exit,
)

# =========================================================================
# CONFIG
# =========================================================================
LOOKBACK_DAYS   = 180
TIMEFRAME       = "1h"
STARTING_EQUITY = 100_000.0
FEE_PCT         = 0.0026
SLIPPAGE_PCT    = 0.001
SYMBOLS         = cfg.SYMBOLS
MIN_BARS_NEEDED = 50

# =========================================================================
# DATA FETCH
# =========================================================================

def fetch_historical(symbol: str, timeframe: str, days: int) -> List[List]:
    """Fetch historical OHLCV from Kraken (paginated)."""
    exchange = ccxt.kraken({"enableRateLimit": True})
    ms_per_candle = exchange.parse_timeframe(timeframe) * 1000
    end_ms = exchange.milliseconds()
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)

    all_bars = []
    since = start_ms
    while since < end_ms:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=720)
        except Exception as e:
            print(f"  fetch error: {e}; retrying in 2s")
            time.sleep(2)
            continue
        if not batch:
            break
        all_bars.extend(batch)
        since = batch[-1][0] + ms_per_candle
        time.sleep(0.5)
        if len(batch) < 720:
            break
    return all_bars

# =========================================================================
# SIMULATION STATE
# =========================================================================

class BacktestPosition:
    def __init__(self, symbol, direction, entry_price, units,
                 stop_distance, entry_idx, atr):
        self.symbol       = symbol
        self.direction    = direction
        self.entry_price  = entry_price
        self.units        = units
        self.stop_distance = stop_distance
        self.entry_idx    = entry_idx
        self.atr          = atr

# =========================================================================
# RUN BACKTEST
# =========================================================================

def run_backtest():
    print("=== BACKTEST: Mean Reversion (BB+RSI+Volume) ===")
    print(f"Universe: {SYMBOLS}")
    print(f"Lookback: {LOOKBACK_DAYS} days, timeframe: {TIMEFRAME}")
    print(f"Starting equity: ${STARTING_EQUITY:,.2f}")
    print(f"Fee: {FEE_PCT*100:.2f}%, Slippage: {SLIPPAGE_PCT*100:.2f}%")
    print()

    print("Fetching historical data...")
    histories = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        bars = fetch_historical(sym, TIMEFRAME, LOOKBACK_DAYS)
        histories[sym] = bars
        print(f"{len(bars)} bars")

    min_len = min(len(b) for b in histories.values())
    print(f"\nAligned series length: {min_len} bars (~{min_len/24:.0f} days)")
    print()

    aligned = {sym: bars[-min_len:] for sym, bars in histories.items()}

    equity      = STARTING_EQUITY
    peak_equity = STARTING_EQUITY
    max_dd      = 0.0
    positions: Dict[str, BacktestPosition] = {}
    trades: List[dict] = []

    for i in range(MIN_BARS_NEEDED, min_len):

        # === Step 1: Check exits on open positions ===
        for sym, pos in list(positions.items()):
            bars = aligned[sym]
            current_price = bars[i][4]
            slice_start = max(0, i - cfg.BB_PERIOD * 2)
            closes = [b[4] for b in bars[slice_start:i + 1]]

            bb_mid = (
                sum(closes[-cfg.BB_PERIOD:]) / cfg.BB_PERIOD
                if len(closes) >= cfg.BB_PERIOD
                else current_price
            )
            hours_held = i - pos.entry_idx

            should_exit, reason = check_mean_reversion_exit(
                direction=pos.direction,
                entry_price=pos.entry_price,
                current_price=current_price,
                bb_mid=bb_mid,
                atr=pos.atr,
                hours_held=hours_held,
                stop_distance=pos.stop_distance,
                take_profit_pct=cfg.TAKE_PROFIT_PCT,
                max_hold_hours=cfg.MAX_HOLD_HOURS,
            )

            if should_exit:
                if pos.direction == "long":
                    exit_slip = current_price * (1 - SLIPPAGE_PCT)
                    gross = (exit_slip - pos.entry_price) * pos.units
                else:
                    exit_slip = current_price * (1 + SLIPPAGE_PCT)
                    gross = (pos.entry_price - exit_slip) * pos.units
                fee = (pos.entry_price + exit_slip) * pos.units * FEE_PCT
                pnl = gross - fee
                equity += pnl
                trades.append({
                    "symbol":    sym,
                    "direction": pos.direction,
                    "entry":     pos.entry_price,
                    "exit":      exit_slip,
                    "units":     pos.units,
                    "pnl":       pnl,
                    "reason":    reason,
                    "hours":     hours_held,
                })
                del positions[sym]

        # === Step 2: Scan for new entry signals ===
        if len(positions) < cfg.MAX_POSITIONS:
            for sym in SYMBOLS:
                if sym in positions:
                    continue
                bars = aligned[sym]
                slice_start = max(0, i - 100)
                closes  = [b[4] for b in bars[slice_start:i + 1]]
                highs   = [b[2] for b in bars[slice_start:i + 1]]
                lows    = [b[3] for b in bars[slice_start:i + 1]]
                volumes = [b[5] for b in bars[slice_start:i + 1]]

                signal = evaluate_trend_signal(
                    closes=closes, highs=highs, lows=lows,
                    volumes=volumes,
                    bb_period=cfg.BB_PERIOD,
                    bb_std=cfg.BB_STD_DEV,
                    rsi_period=cfg.RSI_PERIOD,
                    rsi_long_max=cfg.RSI_LONG_MAX,
                    rsi_short_min=cfg.RSI_SHORT_MIN,
                    volume_ma_period=cfg.VOLUME_MA_PERIOD,
                    volume_min_mult=cfg.VOLUME_MIN_MULT,
                )

                if signal["passed"]:
                    atr = signal["atr"]
                    if atr <= 0:
                        continue
                    sizing = calculate_position_size(
                        equity=equity,
                        atr=atr,
                        price=signal["current_price"],
                        adx=0,
                        risk_per_trade=cfg.RISK_PER_TRADE,
                        atr_multiplier=cfg.ATR_STOP_MULTIPLIER,
                        max_fraction=cfg.MAX_POSITION_FRACTION,
                    )
                    if sizing["units"] > 0:
                        if signal["direction"] == "long":
                            entry_slip = signal["current_price"] * (1 + SLIPPAGE_PCT)
                        else:
                            entry_slip = signal["current_price"] * (1 - SLIPPAGE_PCT)
                        positions[sym] = BacktestPosition(
                            symbol=sym,
                            direction=signal["direction"],
                            entry_price=entry_slip,
                            units=sizing["units"],
                            stop_distance=sizing["stop_distance"],
                            entry_idx=i,
                            atr=atr,
                        )

        # Track drawdown on realised equity only
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        max_dd = max(max_dd, dd)

    # Close remaining positions at last bar close
    for sym, pos in positions.items():
        bars = aligned[sym]
        last_price = bars[-1][4]
        if pos.direction == "long":
            gross = (last_price - pos.entry_price) * pos.units
        else:
            gross = (pos.entry_price - last_price) * pos.units
        fee = (pos.entry_price + last_price) * pos.units * FEE_PCT
        pnl = gross - fee
        equity += pnl
        trades.append({
            "symbol":    sym,
            "direction": pos.direction,
            "entry":     pos.entry_price,
            "exit":      last_price,
            "units":     pos.units,
            "pnl":       pnl,
            "reason":    "backtest_end",
            "hours":     min_len - pos.entry_idx,
        })

    return equity, trades, max_dd, min_len

# =========================================================================
# REPORT
# =========================================================================

def report(final_equity, trades, max_dd, total_bars):
    print("\n=== RESULTS ===")
    print(f"Total trades:  {len(trades)}")
    print(f"Final equity:  ${final_equity:,.2f}")
    print(f"Total P&L:     ${final_equity - STARTING_EQUITY:,.2f}  "
          f"({(final_equity / STARTING_EQUITY - 1) * 100:+.2f}%)")
    print(f"Max drawdown:  {max_dd * 100:.2f}%")
    print(f"Period:        ~{total_bars/24:.0f} days "
          f"(~{total_bars/24/30:.1f} months)")

    if not trades:
        print("\nNo trades — strategy may be too restrictive on this period.")
        return

    wins        = [t for t in trades if t["pnl"] > 0]
    losses      = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))

    print(f"\nWin rate:         {len(wins)/len(trades)*100:.1f}%  "
          f"({len(wins)}W / {len(losses)}L)")
    print(f"Profit factor:    "
          f"{gross_profit / gross_loss if gross_loss > 0 else float('inf'):.2f}")
    print(f"Avg win:          ${sum(t['pnl'] for t in wins)/len(wins) if wins else 0:,.2f}")
    print(f"Avg loss:         ${sum(t['pnl'] for t in losses)/len(losses) if losses else 0:,.2f}")
    print(f"Expectancy/trade: ${sum(t['pnl'] for t in trades)/len(trades):,.2f}")
    print(f"Best trade:       ${max((t['pnl'] for t in trades), default=0):,.2f}")
    print(f"Worst trade:      ${min((t['pnl'] for t in trades), default=0):,.2f}")
    print(f"Avg hold (hrs):   {sum(t['hours'] for t in trades)/len(trades):.1f}")

    print("\n--- Per-symbol ---")
    by_sym: Dict[str, list] = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t)
    for sym, ts in sorted(by_sym.items()):
        ws        = [t for t in ts if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in ts)
        wr        = len(ws) / len(ts) * 100
        print(f"  {sym}: {len(ts)} trades, "
              f"{len(ws)}/{len(ts)} wins ({wr:.0f}%), "
              f"P&L ${total_pnl:,.2f}")

    print("\n--- Exit reasons ---")
    by_reason: Dict[str, list] = {}
    for t in trades:
        by_reason.setdefault(t["reason"], []).append(t)
    for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        avg = sum(t["pnl"] for t in ts) / len(ts)
        print(f"  {reason:25s}: {len(ts):3d} trades, avg ${avg:,.2f}")

# =========================================================================
# MAIN
# =========================================================================

if __name__ == "__main__":
    final_equity, trades, max_dd, total_bars = run_backtest()
    report(final_equity, trades, max_dd, total_bars)
