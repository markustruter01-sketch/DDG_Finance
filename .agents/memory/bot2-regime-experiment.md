---
name: Bot 2 regime-filter experiment
description: Locked rank-500 momentum test with a binary prior-SPY-200-day-SMA filter and SGOV risk-off allocation.
---

The binary prior-data-only SPY 200-day SMA filter did not repair the rank-500 momentum failure: February 2021 remained RISK_ON, 2021–2022 drawdown was not reduced, and pooled risk-adjusted performance fell below both the unfiltered strategy and SPY. Bot 2 should remain paused.

**Why:** The filter only exits on monthly rebalance dates, and the observed February 2021 failure occurred while the regime signal was still RISK_ON.

**How to apply:** Treat this as a failed locked experiment, not a reason to retune the threshold or activate the strategy. Any next research change must be separately pre-registered.