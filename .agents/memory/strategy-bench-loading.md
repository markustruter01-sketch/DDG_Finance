---
name: Strategy Bench loading behavior
description: Canonical Helium Bench runs can take minutes even for a bounded historical window.
---

The Bench must render its navigation, research context, and an explicit in-progress state before the canonical server simulation completes; a full-screen blank-looking spinner makes a healthy long-running request appear broken.

**Why:** The verified engine loads a large development price panel and is intentionally slower than the retired static JSON path.

**How to apply:** Keep the UI responsive while the server run is pending, and do not replace the verified engine with cached dashboard artifacts just to make the first paint faster.