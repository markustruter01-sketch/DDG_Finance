#!/bin/bash
set -e

# Install dependencies from the lockfile
pnpm install --frozen-lockfile

# Run Drizzle schema push only when the schema actually defines tables.
# The lib/db schema is managed by the Node.js SaaS API; the trading platform
# manages its own PostgreSQL tables directly via Python/SQLAlchemy.
# Skipping push when no tables are defined prevents drizzle-kit from
# attempting to DROP Python-managed tables that aren't in the Drizzle schema.
#
# NOTE: Strip comment lines before grepping so the commented-out pgTable
# example in the scaffold file does not trigger a false positive.
SCHEMA_FILE="lib/db/src/schema/index.ts"
if grep -vE '^\s*//' "$SCHEMA_FILE" 2>/dev/null | grep -qE "pgTable|pgView"; then
    echo "Drizzle schema has table definitions — running push-force"
    pnpm --filter @workspace/db push-force
else
    echo "No Drizzle table definitions found in ${SCHEMA_FILE} — skipping db push"
fi
