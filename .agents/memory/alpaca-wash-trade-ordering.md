---
name: Alpaca wash-trade ordering
description: Alpaca can reject an add-on buy while an opposite-side stop remains open for the same symbol.
---

Alpaca may reject a market buy for a symbol that already has an open sell stop, returning `potential wash trade detected` and directing the caller to use complex orders. A standing protective stop cannot be assumed to coexist with an add-on buy.

**Why:** A GLD buy was rejected while the prior GLD sell stop remained open during a staged rebalance.

**How to apply:** Before increasing a position, use a broker-supported complex order or an explicitly authorized cancel-buy-replace-stop sequence. Preserve the coverage gate and do not improvise the order sequence during live execution.