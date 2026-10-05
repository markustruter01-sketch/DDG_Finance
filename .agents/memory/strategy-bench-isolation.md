---
name: Strategy bench isolation
description: Durable boundary for the Bot 2 strategy research surface.
---

The Strategy Bench is a read-only research surface with no live trading, order, vault, or streaming-page execution path. In the workspace it may read the explicit Helium research database; published environments use a committed, sanitized snapshot.

**Why:** The bench is intended for reviewing experiments and overfitting evidence; connecting it to live systems or allowing published research jobs would blur the boundary between research and execution.

**How to apply:** Keep catalog reads isolated behind the research connection, use the committed snapshot outside the workspace, disable workshop/sweep/backtest actions on the live site, and keep the Bench as its own page.