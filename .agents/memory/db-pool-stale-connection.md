---
name: DB pool stale connection fix
description: psycopg2 ThreadedConnectionPool returns connections with conn.closed==0 even when PostgreSQL server dropped them; must use SELECT 1 ping to detect.
---

## The Rule
Never rely on `conn.closed` alone to validate a psycopg2 pool connection. Always follow up with a `SELECT 1` ping. Use `_acquire_healthy_conn()` in `trading-platform/db/postgres.py`.

**Why:** `conn.closed` is a psycopg2 client-side flag. When the PostgreSQL server drops an idle connection (keepalive timeout, server restart, etc.), psycopg2 is not notified — `conn.closed` stays `0`. The connection only registers as dead when psycopg2 actually tries to send a query, at which point the caller gets `InterfaceError: connection already closed` or `OperationalError: server closed the connection unexpectedly`.

A plain `if conn.closed:` check passes for these server-dropped connections, so the stale connection gets handed to the caller who then hits the error.

**How to apply:**
- `_acquire_healthy_conn()` does a two-stage check: (1) `conn.closed != 0` catches client-side closes; (2) `SELECT 1` ping catches server-side drops.
- Retries up to 3 times, discarding each bad connection with `putconn(close=True)` so the pool creates a fresh replacement.
- Confirmed fix: dev cycle 2 (15-min idle) clean on 2026-06-04. Previous `conn.closed`-only check passed cycle 1 but failed cycle 2.
- Replit Postgres `idle_in_transaction_session_timeout=1h`, `tcp_keepalives_idle=0` — server-side drop timing is unpredictable; always ping.
