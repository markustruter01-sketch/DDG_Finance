---
name: Strategy bench isolation
description: Durable boundary for the Bot 2 strategy research surface.
---

The strategy bench is development-only and must remain a static research surface with no live trading, order, vault, or streaming-page execution path.

**Why:** The bench is intended for fast parameter exploration and overfitting review; connecting it to live systems would blur the safety boundary between research and execution.

**How to apply:** Keep its data source read-only/static, keep its controls client-side or explicitly research-scoped, and expose it as its own page rather than adding controls to the homepage or streaming suite.