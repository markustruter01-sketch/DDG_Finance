---
name: Claude Report Endpoint
description: Notes on GET /trading-api/claude-report behavior, dev/prod DB gap, and route registration.
---

## Route Registration
- File: `trading-platform/routes/claude_report.py`
- Registered in: `trading-platform/routes/__init__.py` → `ALL_ROUTERS`
- Path: `@router.get("/claude-report")` — prefix `/trading-api` comes from `APIRouter(prefix=API_PREFIX)` in `main.py`
- The published URL `quant-financial-engineer.replit.app` and the dev domain both proxy to the same uvicorn process on port 8000. Route changes require a workflow restart (WatchFiles sometimes misses edits during rapid sequential changes).

## Dev/Prod DB Gap
The trading-api workflow connects to the **dev** PostgreSQL instance.
`executeSql(environment: "production")` connects to the **production** DB.
They have different data:
- `jerome_positions`: empty in dev, 11 rows in prod (5 open, 6 closed all null pnl)
- `alpaca_etf_positions bot2_spy_qqq`: 0 rows in dev, 1 row opened 2026-04-30 in prod
- `jerome_groq_decisions`: dev has up to id≈6 (2026-05-23); prod has up to id=16 (2026-05-26)

**Why:** Dev and prod are separate Replit PostgreSQL instances. Never assume they match.
**How to apply:** Null jerome/spy sections in dev tests are expected and correct. Use `days=7+` in dev to exercise decisions_pending. Use production DB queries to verify prod-specific values.

## Performance
Verified: 613–667ms response time (target <2000ms). ~46 sequential DB queries — acceptable.
If latency grows, consider batching `_get_last_trade_at` calls into a single UNION ALL query.
