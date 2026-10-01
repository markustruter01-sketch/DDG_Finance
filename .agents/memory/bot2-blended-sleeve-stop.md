---
name: Bot 2 blended sleeve stop
description: Preserves how candidate D's trend-only stop interacts with its passive risk-parity sleeve and frozen experiment spec.
---

Candidate D's trailing stop applies only to its trend sleeve. When a symbol is shared with the passive risk-parity sleeve, the stop must retain that passive quantity and transfer the stopped sleeve's marked value to BIL. Candidate C remains buy-and-hold without stops. Keep the frozen experiment specification and its hash unchanged when implementing this behavior.

**Why:** The user explicitly requested trend-sleeve-only stop behavior while preserving the already frozen experiment identity; a symbol-wide exit would incorrectly close passive exposure.

**How to apply:** Keep sleeve attribution in the shared research harness. When changing D's stop lifecycle, test both same-direction and offsetting trend/passive holdings, next-close execution, and no same-close trend re-entry.