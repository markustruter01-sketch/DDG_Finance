---
name: Kraken adaptive params retirement
description: The legacy Kraken adaptive-parameter table was removed from dev schema and all consumers must fail closed without querying it.
---

The legacy Kraken adaptive-parameter store is retired. Current ETF bots do not depend on it. Legacy Fleet Commander chat compatibility symbols remain available, but reads return no parameters and writes return false so the live route cannot query or recreate the removed table.

**Why:** The table held only placeholder rows for retired bot IDs, while an active dashboard route still imported the old helper symbols. Removing the symbols entirely caused API startup failure, so compatibility must be preserved as an explicit no-op guard.

**How to apply:** Do not reintroduce bootstraps, runtime ALTERs, readers, or writers for the table. Treat any future request to restore Kraken parameter controls as a separate migration decision.