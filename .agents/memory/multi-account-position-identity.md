---
name: Multi-account position identity
description: The live Alpaca position feed can contain the same symbol in multiple bot accounts.
---

Live position records are account-scoped, even when their symbols match. Any frontend list key or local expansion state based only on `symbol` is unsafe once `/positions/live` returns all active Alpaca accounts.

**Why:** The shared SGOV cash-park holding appeared in more than one account, producing duplicate React keys and ambiguous UI state after the endpoint was corrected to return the full fleet.

**How to apply:** Use `bot_id` (or another stable account identifier) together with `symbol` for rendering keys and per-position UI state. Keep `positions_by_bot` available for views that need explicit attribution.