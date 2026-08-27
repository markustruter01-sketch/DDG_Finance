---
name: Bot 2 v4 rotation boundary
description: Durable boundary for the one-book momentum-to-PEAD research experiment.
---

Bot 2 v4 rotation research must stay development-only and use one shared cash
ledger for momentum liquidation, progressive PEAD entries, cash parking, and
post-close momentum re-entry. Immutable earlier experiment rows, including
their specification/result discrepancies, are evidence to document rather than
repair in place.

**Why:** A second account or retroactive ledger correction would make the
rotation comparison impossible to interpret and could accidentally blur the
boundary with live trading.

**How to apply:** Keep future validation in the isolated research runner,
register a new experiment for a new specification, and never alter a recorded
Experiment 12 row.