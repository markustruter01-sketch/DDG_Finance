---
name: Stop ledger replacement invariant
description: Broker-native protective stop replacements must update the ETF execution ledger atomically with the live stop reference.
---

## Rule
Every protective-stop placement, replacement, or restore must persist both the broker `stop_order_id` and the broker `stop_price` in the matching open ETF ledger row. A broker rearm outside that helper can leave safety reports firing even when coverage is correct.

**Why:** A live Oracle account had full-quantity broker stops but no matching open production ledger rows after a trim/rearm path, causing repeated false kill-switch triggers.

**How to apply:** Keep all replacement paths routed through the shared ledger writer, include canonical `bot_id` and a reconciliation/runner `cycle_id` on degradation records, and verify the authoritative production DSN before writing.