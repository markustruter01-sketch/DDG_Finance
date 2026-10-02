---
name: Client order ID uniqueness
description: Every Alpaca order submission must use a bounded per-call UUID client-order ID with one duplicate-ID retry.
---

Ordinary Alpaca submissions must use the shared bounded UUID helper and begin with the environment component `pub`, `dev`, or fail-closed `unk`. The per-bot vault is a narrow exception: its queue has one row per bot and no per-order intent ID, so vault IDs use environment, bot, successful-submission ordinal, and symbol to support duplicate adoption after an ambiguous result.

**Why:** Alpaca retains canceled IDs, so a vault retry after a terminal order needs a new ordinal. Conversely, changing the ID after an uncertain submit can create a second live order if the first request reached Alpaca but its response or DB write failed.

**How to apply:** Keep all non-vault orders on the shared UUID path. For vault orders, advance the ordinal only after adopting/storing an order, stop submitting the other symbol after an ambiguous error, and retry with the same deterministic ID so duplicate lookup can adopt the broker order. Ownership matching must understand tagged IDs while retaining legacy untagged orders for safe stop reconciliation.