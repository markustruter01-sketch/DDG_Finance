---
name: Live deleveraging ledger synchronization
description: Manual broker de-leveraging must update the matching execution ledger and replacement stop ownership before runner restart.
---

When a live position is partially reduced and its protective stop is replaced, update the active execution ledger to the filled broker quantity and new stop ID before restarting strategy workers.

**Why:** The broker can be correctly protected while a stale canceled stop ID in the runner's database causes duplicate stop-management attempts and misleading reconciliation failures.

**How to apply:** After any manual partial sell, reconcile broker fill quantity, replacement stop, and the database row in the database environment used by the runner; then restart or reload the worker.