---
name: Alpaca cancel and order-list consistency
description: Cancel acknowledgements and immediate open-order listings can lag the broker's terminal order status.
---

Alpaca can return HTTP 204 for a cancel request while the order remains `pending_cancel` across subsequent polls, including 90- and 120-second recovery windows. The order is not safe to treat as canceled until a later status read is actually `canceled`.

Separately, an order-specific GET can report `canceled` while an immediate `open_orders()` response still includes that same order. Do not let a stale collection snapshot override the terminal status returned for the specific order.

**Why:** In two published Bot 3 rebalance cycles, order-specific state showed cancellation while the subsequent open-order listing still triggered an abort. The first case proves that a cancel request alone is insufficient; the second shows that a single stale collection response is not conclusive either.

**How to apply:** Poll the specific order status after DELETE and stop on timeout. Once terminal cancellation is confirmed, allow for bounded collection-view lag rather than treating one stale listing as proof the order remains live. Preserve protective coverage and fail closed if the specific order state is still unresolved; do not submit conflicting orders.