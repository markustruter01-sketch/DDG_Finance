---
name: Rank audit streaming
description: Resource constraint for broad historical Bot 2 universe audits
---

Broad SIP audits and historical momentum simulations must avoid heavyweight full-panel materialization; use bounded streaming or compact sorted series, and keep screener window work linear.

**Why:** The retained panel contains millions of rows and Python dataclass materialization reached roughly 6 GiB before the process was stopped. A seemingly equivalent `bar in artifact_window` check made the monthly screener quadratic and turned a compact run into an unusably long CPU pass.

**How to apply:** Use bounded streaming for coverage audits and compact sorted series for explicitly requested simulations. In the shared screener, iterate the bounded artifact window directly; never test each prior bar for membership in that window.