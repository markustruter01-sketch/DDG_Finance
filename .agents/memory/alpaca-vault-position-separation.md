---
name: Alpaca vault position separation
description: Same-account vault and strategy holdings require ownership accounting and strategy-side quantity guards.
---

Alpaca exposes a net position per symbol, so a client order ID alone cannot separate vault SGOV/QQQ from strategy SGOV/QQQ. Vault-owned quantities must be tracked independently, removed from strategy sizing and stop scans, and protected from aggregate close shortcuts.

**Why:** Selling or stopping a net symbol position can unintentionally consume the other owner’s quantity when both use the same paper account.

**How to apply:** Any future vault execution or rebalance must reconcile tagged fills into vault holdings and keep strategy paths filtered and fail-closed for mixed symbols.