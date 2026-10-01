---
name: Multi-account position identity
description: The live Alpaca position feed can contain the same symbol in multiple bot accounts.
---

Live position records are account-scoped, even when their symbols match. Any frontend list key or local expansion state based only on `symbol` is unsafe once `/positions/live` returns all active Alpaca accounts.

**Why:** The shared SGOV cash-park holding appeared in more than one account, producing duplicate React keys and ambiguous UI state after the endpoint was corrected to return the full fleet.

**How to apply:** Use `bot_id` (or another stable account identifier) together with `symbol` for rendering keys and per-position UI state. Keep `positions_by_bot` available for views that need explicit attribution.

Do not hide API-reported positions or journal trades using a static retired-symbol list. A symbol being retired from a strategy does not prove the broker has no current position or that its trade history is irrelevant.

**Why:** Static ticker exclusions can silently suppress real broker or journal records and make the dashboard disagree with its service source.

**How to apply:** Show all reported open positions; filter journal history by its returned trade status and requested time/row limit, not by a frontend-maintained ticker blacklist.