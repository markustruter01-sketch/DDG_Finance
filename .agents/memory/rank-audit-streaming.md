---
name: Rank audit streaming
description: Resource constraint for broad historical Bot 2 universe audits
---

Broad SIP universe audits must stream bars in date order while retaining only each symbol's 252-session window; materializing the full panel exceeds the 8 GiB development container.

**Why:** The retained panel contains millions of rows and Python dataclass materialization reached roughly 6 GiB before the process was stopped.

**How to apply:** Use the bounded streaming audit path for monthly coverage, implied rank cutoffs, samples, and current diagnostics; reserve full-panel loading for explicitly requested simulations.