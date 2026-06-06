---
name: OOS Harness Cash-Tracking Pattern
description: Critical pattern for daily-bar backtest engines — must track cash explicitly to avoid double-counting gains via MTM + exit P&L.
---

## The bug
In daily-bar backtests with mark-to-market (MTM) equity updates, doing `equity += pnl_usd` on position close double-counts gains:

```python
# BAD — double-counts: MTM already moved equity for the unrealized pnl
equity += pnl_usd   # on exit
equity = mtm(...)   # MTM re-applies the same price move
```

## The fix — explicit cash tracking (Jerome/Buck/Oracle harness pattern)
```python
cash = STARTING_CAPITAL

# Opening a position: subtract notional from cash
cash -= notional

# Closing a position: return notional + P&L to cash
pnl_usd = (exit_price - entry_price) * qty   # long example
cash += pos.notional + pnl_usd

# MTM equity (computed each bar, does NOT touch cash):
mtm = cash
for pos in open_positions:
    close = current_price(pos.ticker)
    mtm += pos.notional + (close - pos.entry_price) * pos.qty
equity = mtm
```

**Why:** `cash` represents truly free capital. Open positions are "locked" (subtracted from cash on entry, returned on exit). MTM just peeks at current value without modifying cash. Equity = cash + mark-to-market value of all positions.

**How to apply:** All OOS harness scripts (`oos_validation.py`, `oracle_oos_validation.py`) use this pattern. Any future bot backtest must do the same. Never do `equity += pnl` on close when the engine also runs daily MTM.
