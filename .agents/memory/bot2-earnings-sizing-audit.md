---
name: Bot 2 earnings sizing audit
description: Position-sizing limitation discovered in the development-only earnings validation.
---

The earnings validation runner stores one return per event and compounds those returns sequentially. It has no notional, cash, quantity, overlap, or deployment cap, so overlapping PEAD events implicitly use more than 100% of capital and the reported event curve is not comparable to an unlevered buy-and-hold portfolio.

**Why:** The read-only audit found a maximum of six simultaneous PEAD-20 positions, 163.93% mean implied deployment, and 600% maximum implied deployment. A separate dynamic equal-weight, 100%-capped reconstruction returned 29.66% with Sharpe 0.784 and max drawdown -13.00%.

**How to apply:** Treat experiment 10 as a research signal comparison only. Any future portfolio conclusion must use explicit cash-constrained sizing, declare its sizing model in the research ledger, and must not overwrite the immutable experiment result.