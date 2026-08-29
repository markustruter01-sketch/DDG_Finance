---
name: Research registry result shapes
description: Pooled research metrics can be direct or nested, and ambiguous multi-strategy windows must stay null.
---

The research registry must support pooled metrics stored directly on a window, under a `metrics` object, or under strategy-labelled objects. When several non-benchmark strategies remain and the ledger does not identify one unambiguously, report NULL rather than selecting by position or inventing a match.

**Why:** Research result JSON has evolved across runs, and silently choosing one of several pooled strategies would make the registry look more precise than the audit evidence supports.

**How to apply:** Inspect the persisted JSON shape before changing extraction logic; exclude explicit benchmark/control labels, select only an evidence-backed own strategy, and leave ambiguous pooled scalars NULL.