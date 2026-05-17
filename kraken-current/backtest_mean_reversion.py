"""Backtest the mean reversion strategy on historical data.

Usage: python3 backtest_mean_reversion.py

Fetches ~6 months of 1h candles from Binance (BTC/USDT, ETH/USDT, SOL/USDT)
which supports proper multi-batch pagination unlike Kraken's 720-bar cap.
Simulates the strategy bar-by-bar across 3 exit target variants and reports
win rate, profit factor, expectancy, max drawdown, per-symbol breakdown, and
a final comparison table.

Historical data source: Binance public spot API (no key required).
Live bot data source:   Kraken (unchanged).
Bot stays paused — this is paper-paper validation, no live writes.
"""

import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, '.')

import ccxt
import config as cfg
from trend_engine import (
    evaluate_trend_signal,
    calculate_position_size,
    calculate_atr,
    check_mean_reversion_exit,
    update_trailing_stop,
)

# =========================================================================
# CONSTANTS
# =========================================================================
LOOKBACK_DAYS        = 180
TIMEFRAME            = "1h"
STARTING_EQUITY      = 100_000.0
FEE_PCT              = 0.0026
SLIPPAGE_PCT         = 0.001
SYMBOLS              = cfg.SYMBOLS                              # Kraken names (live bot)
BACKTEST_SYMBOLS     = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]    # OKX equivalents
EXCHANGE_NAME        = "okx"
MIN_BARS_NEEDED      = 50
EXIT_TARGETS_TO_TEST = ["counter_band"]   # breakout: exit at opposite band

# =========================================================================
# DATA FETCH  — OKX (reachable from Replit, 300 bars/request, 1y+ history)
# =========================================================================

def fetch_historical(symbol: str, timeframe: str, days: int) -> List[List]:
    """Fetch historical OHLCV from OKX with proper pagination.

    OKX returns up to 300 bars per request and supports arbitrary since=
    timestamps. 180 days × 24h = 4320 bars ≈ 15 requests.
    """
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

class BacktestPosition:
    def __init__(self, symbol: str, direction: str, entry_price: float,
                 units: float, stop_distance: float, entry_idx: int, atr: float):
        self.symbol        = symbol
        self.direction     = direction
        self.entry_price   = entry_price
        self.units         = units
        self.stop_distance = stop_distance
        self.entry_idx     = entry_idx
        self.atr           = atr
        self.best_price    = entry_price    # tracks peak for trailing stop

# =========================================================================
# INNER SIMULATION  (histories pre-fetched, exit_target configurable)
# =========================================================================

def run_backtest_inner(
    histories: Dict[str, List[List]],
    exit_target: str,
) -> Tuple[float, List[dict], float, int]:
    """
    Bar-by-bar simulation over pre-fetched OHLCV histories.
    Returns (final_equity, trades, max_drawdown, total_bars).
    """
    min_len = min(len(b) for b in histories.values())
    aligned = {sym: bars[-min_len:] for sym, bars in histories.items()}

    equity      = STARTING_EQUITY
    peak_equity = STARTING_EQUITY
    max_dd      = 0.0
    positions: Dict[str, BacktestPosition] = {}
    trades: List[dict] = []

    for i in range(MIN_BARS_NEEDED, min_len):

        # ── Exit check ────────────────────────────────────────────────────
        for sym, pos in list(positions.items()):
            bars          = aligned[sym]
            current_price = bars[i][4]  # close
            slice_start   = max(0, i - cfg.BB_PERIOD * 2)
            closes        = [b[4] for b in bars[slice_start: i + 1]]

            # Compute all 3 BB levels
            if len(closes) >= cfg.BB_PERIOD:
                bb_vals  = closes[-cfg.BB_PERIOD:]
                bb_mid   = sum(bb_vals) / cfg.BB_PERIOD
                bb_std   = (sum((v - bb_mid) ** 2 for v in bb_vals) / cfg.BB_PERIOD) ** 0.5
                bb_lower = bb_mid - cfg.BB_STD_DEV * bb_std
                bb_upper = bb_mid + cfg.BB_STD_DEV * bb_std
            else:
                bb_mid = bb_lower = bb_upper = current_price

            hours_held = i - pos.entry_idx

            # Update trailing stop — breakout strategy trails winners
            trail = update_trailing_stop(
                current_price=current_price,
                best_price=pos.best_price,
                entry_price=pos.entry_price,
                stop_distance=pos.stop_distance,
                direction=pos.direction,
                trail_trigger_multiplier=cfg.ATR_TRAIL_TRIGGER,
                atr=pos.atr,
                trail_atr_mult=cfg.ATR_TRAIL_MULT,
            )
            pos.best_price = trail["best_price"]

            # Check trailing/hard stop hit first
            stop_hit = (
                (pos.direction == "long"  and current_price <= trail["stop_level"]) or
                (pos.direction == "short" and current_price >= trail["stop_level"])
            )
            if stop_hit:
                should_exit = True
                reason = "trailing_stop" if trail["trailing_active"] else "stop_loss"
            else:
                should_exit, reason = check_mean_reversion_exit(
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    current_price=current_price,
                    bb_mid=bb_mid,
                    bb_lower=bb_lower,
                    bb_upper=bb_upper,
                    atr=pos.atr,
                    hours_held=hours_held,
                    stop_distance=pos.stop_distance,
                    take_profit_pct=cfg.TAKE_PROFIT_PCT,
                    max_hold_hours=cfg.MAX_HOLD_HOURS,
                    exit_target=exit_target,
                )

            if should_exit:
                if pos.direction == "long":
                    exit_slip = current_price * (1 - SLIPPAGE_PCT)
                    gross     = (exit_slip - pos.entry_price) * pos.units
                else:
                    exit_slip = current_price * (1 + SLIPPAGE_PCT)
                    gross     = (pos.entry_price - exit_slip) * pos.units
                fee    = (pos.entry_price + exit_slip) * pos.units * FEE_PCT
                pnl    = gross - fee
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

        # ── Entry scan ────────────────────────────────────────────────────
        if len(positions) < cfg.MAX_POSITIONS:
            for sym in SYMBOLS:
                if sym in positions:
                    continue
                bars        = aligned[sym]
                slice_start = max(0, i - 100)
                closes      = [b[4] for b in bars[slice_start: i + 1]]
                highs       = [b[2] for b in bars[slice_start: i + 1]]
                lows        = [b[3] for b in bars[slice_start: i + 1]]
                volumes     = [b[5] for b in bars[slice_start: i + 1]]

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

        # ── Drawdown (realised equity) ────────────────────────────────────
        peak_equity = max(peak_equity, equity)
        dd          = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        max_dd      = max(max_dd, dd)

    # Close remaining positions at last bar close
    for sym, pos in positions.items():
        bars       = aligned[sym]
        last_price = bars[-1][4]
        if pos.direction == "long":
            gross = (last_price - pos.entry_price) * pos.units
        else:
            gross = (pos.entry_price - last_price) * pos.units
        fee    = (pos.entry_price + last_price) * pos.units * FEE_PCT
        pnl    = gross - fee
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

def report(final_equity: float, trades: List[dict],
           max_dd: float, total_bars: int, label: str = "") -> None:
    if label:
        print(f"\n{'='*60}")
        print(f"  exit_target = {label}")
        print(f"{'='*60}")

    wins         = [t for t in trades if t["pnl"] > 0]
    losses       = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))

    print(f"Total trades:     {len(trades)}")
    print(f"Final equity:     ${final_equity:,.2f}")
    print(f"Total P&L:        ${final_equity - STARTING_EQUITY:,.2f}  "
          f"({(final_equity / STARTING_EQUITY - 1) * 100:+.2f}%)")
    print(f"Max drawdown:     {max_dd * 100:.2f}%")
    print(f"Period:           ~{total_bars/24:.0f} days "
          f"(~{total_bars/24/30:.1f} months)")

    if not trades:
        print("  No trades — strategy too restrictive on this period.")
        return

    print(f"Win rate:         {len(wins)/len(trades)*100:.1f}%  "
          f"({len(wins)}W / {len(losses)}L)")
    print(f"Profit factor:    "
          f"{gross_profit / gross_loss if gross_loss > 0 else float('inf'):.2f}")
    print(f"Avg win:          ${sum(t['pnl'] for t in wins)/len(wins) if wins else 0:,.2f}")
    print(f"Avg loss:         "
          f"${sum(t['pnl'] for t in losses)/len(losses) if losses else 0:,.2f}")
    print(f"Expectancy/trade: ${sum(t['pnl'] for t in trades)/len(trades):,.2f}")
    print(f"Best trade:       ${max((t['pnl'] for t in trades), default=0):,.2f}")
    print(f"Worst trade:      ${min((t['pnl'] for t in trades), default=0):,.2f}")
    print(f"Avg hold (hrs):   {sum(t['hours'] for t in trades)/len(trades):.1f}")

    print("\n  --- Per-symbol ---")
    by_sym: Dict[str, list] = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t)
    for sym, ts in sorted(by_sym.items()):
        ws        = [t for t in ts if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in ts)
        print(f"    {sym}: {len(ts)} trades, "
              f"{len(ws)}/{len(ts)} wins "
              f"({len(ws)/len(ts)*100:.0f}%), "
              f"P&L ${total_pnl:,.2f}")

    print("\n  --- Exit reasons ---")
    by_reason: Dict[str, list] = {}
    for t in trades:
        by_reason.setdefault(t["reason"], []).append(t)
    for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        avg = sum(t["pnl"] for t in ts) / len(ts)
        print(f"    {reason:30s}: {len(ts):3d} trades, avg ${avg:,.2f}")

# =========================================================================
# MAIN RUNNER  (fetch once, simulate 3 variants)
# =========================================================================

def run_all_variants() -> None:
    print("=== BACKTEST: Mean Reversion (BB+RSI+Volume) — 3 exit target variants ===")
    print(f"Universe: {SYMBOLS}")
    print(f"Lookback: {LOOKBACK_DAYS} days | timeframe: {TIMEFRAME}")
    print(f"Starting equity: ${STARTING_EQUITY:,.2f} | "
          f"Fee: {FEE_PCT*100:.2f}% | Slippage: {SLIPPAGE_PCT*100:.2f}%")
    print()

    # Fetch once from Binance, store under Kraken symbol names so simulation
    # code works unchanged (it never sees the Binance symbol strings).
    print(f"Fetching {LOOKBACK_DAYS} days of historical data from {EXCHANGE_NAME}...")
    histories: Dict[str, List[List]] = {}
    for b_sym, k_sym in zip(BACKTEST_SYMBOLS, SYMBOLS):
        print(f"  {b_sym} (live: {k_sym})...", end=" ", flush=True)
        bars = fetch_historical(b_sym, TIMEFRAME, LOOKBACK_DAYS)
        histories[k_sym] = bars
        print(f"{len(bars)} bars")
    print()

    min_len = min(len(b) for b in histories.values())
    print(f"Aligned series: {min_len} bars (~{min_len/24:.0f} days, "
          f"~{min_len/24/30:.1f} months)\n")

    results: Dict[str, tuple] = {}
    for target in EXIT_TARGETS_TO_TEST:
        equity, trades, max_dd, total_bars = run_backtest_inner(histories, target)
        results[target] = (equity, trades, max_dd, total_bars)
        report(equity, trades, max_dd, total_bars, label=target)

    # Comparison table
    print("\n\n" + "="*75)
    print("  COMPARISON SUMMARY")
    print("="*75)
    print(f"{'Target':25} {'Trades':>7} {'WR':>7} {'PF':>7} "
          f"{'P&L':>12} {'AvgWin':>9} {'AvgLoss':>9} {'MaxDD':>7}")
    print("-"*75)
    for target, (eq, trades, dd, _) in results.items():
        if not trades:
            print(f"{target:25}  (no trades)")
            continue
        wins  = [t for t in trades if t["pnl"] > 0]
        ls    = [t for t in trades if t["pnl"] <= 0]
        gp    = sum(t["pnl"] for t in wins)
        gl    = abs(sum(t["pnl"] for t in ls))
        pf    = gp / gl if gl > 0 else float("inf")
        wr    = len(wins) / len(trades) * 100
        pnl   = eq - STARTING_EQUITY
        aw    = gp / len(wins) if wins else 0
        al    = -gl / len(ls) if ls else 0
        print(f"{target:25} {len(trades):>7} {wr:>6.1f}% {pf:>7.2f} "
              f"${pnl:>10,.0f} ${aw:>8,.0f} ${al:>8,.0f} {dd*100:>6.2f}%")

if __name__ == "__main__":
    run_all_variants()
