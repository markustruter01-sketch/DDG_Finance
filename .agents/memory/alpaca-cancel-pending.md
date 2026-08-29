---
name: Alpaca cancel pending behavior
description: A successful cancel request can leave an Alpaca order pending_cancel and must not be treated as canceled.
---

Alpaca can return HTTP 204 for a cancel request while the order remains `pending_cancel` across subsequent polls. The order is not safe to treat as canceled until a later status read is actually `canceled`.

**Why:** A GLD stop cancel acknowledged with 204 but remained pending through the full polling window, so proceeding with a buy would have violated the cancel-first safety gate.

**How to apply:** Poll the specific order status after DELETE, stop on timeout, and do not submit an add-on buy while the prior opposite-side stop is unresolved.