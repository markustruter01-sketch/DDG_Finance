---
name: Crypto removal Phase F migration
description: How production crypto table drops and bot_portfolio row deletions are handled post Phase 2 removal.
---

# Crypto Removal — Phase F Migration

## Rule
Phase F in `trading-platform/db/postgres.py` `ensure_schema()` handles the production DB cleanup triggered on first trading-api startup after publish.

## What it does
- `DROP TABLE IF EXISTS crypto_signals`
- `DROP TABLE IF EXISTS crypto_price_cache`
- `DELETE FROM bot_portfolio WHERE bot_id = ANY([depeg_hunter, momentum_alpha, momentum_beta, momentum_gamma])`

## Why
`executeSql` with `environment: "production"` is read-only — DDL and DML writes against production can only reach the DB through either the Publish schema-diff flow (for CREATE/ALTER/DROP TABLE) or startup migration code that runs in the production container after deploy.

## How to apply
If crypto_signals/crypto_price_cache still appear after publish, check trading-api startup logs for "Phase F" lines. If they failed, rerun the Phase F block manually via `executeSql` (development) or check the connection pool.

## Tables preserved (do NOT drop)
- `momentum_bot_trades` — historical trade records
- `momentum_universe` — historical universe snapshots
- `depeg_hunter_trades` — historical trade records
