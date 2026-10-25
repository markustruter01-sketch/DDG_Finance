---
name: Strategy bench isolation
description: Durable boundary for the Bot 2 strategy research surface.
---

The Strategy Bench is a read-only research surface with no live trading, order, vault, or streaming-page execution path. In the workspace it may read the explicit Helium research database; published environments use a committed, sanitized snapshot.

**Why:** The bench is intended for reviewing experiments and overfitting evidence; connecting it to live systems or allowing published research jobs would blur the boundary between research and execution.

**How to apply:** Keep catalog reads isolated behind the research connection, use the committed snapshot outside the workspace, disable workshop/sweep/backtest actions on the live site, and keep the Bench as its own page.

For Strategy Bench redesign requests, the deliverable is the actual dashboard `/bench` page—not a canvas gallery of mockup variants. A canvas preview does not substitute for changing the user-facing page.

**Why:** The user corrected a prior response that presented design concepts instead of redesigning the actual page.

**How to apply:** Make and verify visual changes on the integrated dashboard route. Use the canvas only when the user explicitly asks for previews or alternatives.