---
name: Bot 2 commodity research
description: Durable safety boundary for the commodity ETF research pipeline and its ledgered backtests.
---

Commodity ETF research must run against the development database reached by `DATABASE_URL`, use read-only broker metadata only, and remain isolated from live strategy registration, runners, and order APIs.

**Why:** The research data is intentionally additive and experimental; production data and live execution must not be changed by a backtest or its ingestion path.

**How to apply:** Before future commodity research runs, confirm the database identity and execution mode, keep the universe gate ahead of ledger registration and result computation, and treat a failed pass bar as a valid recorded research outcome rather than a reason to retune.