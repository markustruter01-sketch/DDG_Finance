---
name: Full-market research memory
description: Resource and comparability constraints for broad Bot 2 research runs.
---

Broad ordinary-equity research should calculate historical screen observations in PostgreSQL and materialize only the warmup plus requested backtest period in Python. Forking a large in-memory panel for random controls can exceed the process memory limit; use cached in-process controls or a smaller serialized panel.

**Why:** The full adjusted-bar catalogue is large enough that Python object expansion and forked random-control workers can be terminated by the environment before results are written.

**How to apply:** Keep the universe calibration and point-in-time coverage checks SQL-backed, use the existing simulator on a bounded recent panel, and preserve the individual control returns without changing the locked strategy rules.