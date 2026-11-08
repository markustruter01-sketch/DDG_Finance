---
name: Workflow database binding
description: Prevent local workflow restarts from running schema migrations against production.
---

**Rule:** Verify the API workflow's database identity before restarting it. In the observed environment, `DATABASE_URL` and `NEON_DATABASE_URL` resolved to the same production Neon database, and the API startup routine ran schema changes there.

**Why:** A requested workflow restart emitted startup migration logs for dropping legacy columns/tables and deleting retired portfolio rows. No before-snapshot was available to determine which operations changed existing data.

**How to apply:** Before restarting the trading API or runner, check the connection target without exposing credentials. If it is production, do not restart unless production writes are authorized; use an isolated development database for local workflows.
