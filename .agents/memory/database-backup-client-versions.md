---
name: Database backup client versions
description: Major-version compatibility rules for PostgreSQL backups in this workspace
---

Use a pg_dump client matching the server's major version before creating a complete
custom-format backup. PostgreSQL 16 can back up the current production server, while
the development server requires PostgreSQL 17 tooling.

**Why:** pg_dump 16.10 refuses to back up the development PostgreSQL 17.11 server.

**How to apply:** Check the server version and pg_dump version first. Keep compatible
client support in the workspace environment, and verify archives with pg_restore before
presenting them.