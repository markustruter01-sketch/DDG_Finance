---
name: Fleet win rate — missing canonical server source
description: No server endpoint computes fleet-wide win rate; two client-side assemblies diverge.
---

## Rule
Phase 2 must add a server-side fleet win rate. Do not trust either client-side assembly as ground truth.

## Current state
- `FleetPerformanceHero.tsx`: `(alpacaWins + krakenWins + forexWins) / totalTrades` — uses `journal.summary.wins` + `fleetSummary.total_wins` + `fxState.total_wins`
- `useRealFeed.ts`: same concept but uses per-bot `useKrakenPerformance()` win_count instead of fleet-summary — different denominator and numerator
- These two assemblies will produce different numbers whenever kraken_trades diverge from kraken_heartbeat data.

## What exists per-scope
- Oracle: `/performance/summary` → `avg_win_rate` (daily snapshots average), `/performance/attribution` → `overall.win_rate` (trade-level)
- Kraken per-bot: `/kraken/performance?bot_id=X` → `win_rate_pct` (authoritative, from kraken_trades)
- Fleet-wide: NOTHING server-side

## Fix
Add `fleet_win_rate` to `/fleet/equity` response, computed from `SUM(wins) / SUM(total_trades)` across journal + kraken_trades + forex_trades. Or add a dedicated `/fleet/win-rate` endpoint.
