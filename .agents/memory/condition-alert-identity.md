---
name: Condition alert identity
description: Stable identity, suppression, and recovery rules for safety-condition Discord alerts
---

Safety-condition alerts are keyed by source, condition type, and canonical bot scope; changing numeric diagnostics must not create a new condition. The first occurrence alerts immediately, repeats are suppressed for the short policy window, and a proven clear resets the key so recurrence alerts again.

**Why:** Persistent monitoring findings often include changing ages, quantities, or error text. Including those values in identity bypasses deduplication and can flood the operator channel.

**How to apply:** Reuse the shared condition-alert path for liveness, invariants, reconciliation, degradation, and kill-switch findings. Keep detection logic separate from delivery policy, and preserve suppressed findings in logs/source records.