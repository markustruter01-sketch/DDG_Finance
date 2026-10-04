---
name: Bot 2 mechanical-gate parity
description: Preserve shared point-in-time screening behavior in memory-bounded gate runs.
---

Memory-bounded gate implementations are independent screening implementations and must match the shared screen's static asset eligibility and point-in-time OHLCV semantics. Matching only the final universe count is not enough.

**Why:** A streaming implementation can admit candidates excluded by the shared asset filters, changing the ranked universe while still passing broad count tolerances.

**How to apply:** Reuse the same normalized asset eligibility and source priority, then preserve strictly-prior windows, adjusted-price checks, history and liquidity filters, and ranking tie-breaks. Test membership and funnel parity on fixtures before relying on live audit results.