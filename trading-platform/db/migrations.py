"""Versioned, run-once data migrations.

Replaces the pattern of "one-time" repairs that re-run on every boot.
Each migration:

* runs at most once per database, recorded in ``platform_migrations``;
* runs inside ONE transaction under an advisory lock, so two processes
  starting together cannot both apply it;
* checks its own guards and raises ``MigrationGuardError`` when the
  database does not look the way the migration expects. The transaction
  then rolls back, nothing is recorded, and the error is logged. Startup
  continues either way — a migration never blocks the platform from booting.

Production-only migrations are skipped outside the published deployment
(``REPLIT_DEPLOYMENT == "1"``), because their guards are written against a
reconciled production snapshot.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

_ADVISORY_LOCK_KEY = 72016451  # arbitrary, fixed; scopes the lock to this module


class MigrationGuardError(RuntimeError):
    """The database did not match what the migration expected."""


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    apply: Callable[[Any], dict]
    production_only: bool = True


# ── 2026-10-15-001: resolve stale degradations ────────────────────────────────
# Reconciled read-only on 2026-10-15 ~09:58 UTC (P0-CLEANUP-RECON.txt).
# The SGOV cash-park fix went live ~06:34 UTC and the Atlas noise fixes
# (closed-market deferral, fresh-price ATR audit) ~09:35 UTC.

_FIXES_LIVE_AT = "2026-10-15 09:35:00+00"
_RESOLVED_REASON = (
    "migration 2026-10-15-001: stale or pre-fix alert, bulk-resolved after "
    "reconciliation (see .local/claude_reports/P0-CLEANUP-RECON.txt)"
)
# error_type -> only rows raised before the fix went live are resolved
_RESOLVE_BEFORE_FIX = (
    "audit_fail_atr_stop_check",
    "protective_stop_ratchet_deferred",
    "wf_insufficient_data",
    "503",
    "orphan_db_closed",
)
# The /status/summary crash fixed in this same deploy (scheduler.py getattr).
_ATTRIBUTE_ERROR_ROW_ID = 7974
_M001_MAX_ROWS = 1000  # sanity bound: recon counted ~460


def _m001_resolve_stale_degradations(cur) -> dict:
    counts: dict[str, int] = {}

    # The meta alert only reports that other unresolved high-severity rows
    # exist; it re-fires on its next run if any genuinely remain.
    cur.execute(
        "UPDATE system_degradations SET resolved_at = NOW(), resolved_reason = %s "
        "WHERE resolved_at IS NULL "
        "AND error_type = 'zero_unresolved_high_severity_degradations'",
        (_RESOLVED_REASON,),
    )
    counts["zero_unresolved_high_severity_degradations"] = cur.rowcount

    for error_type in _RESOLVE_BEFORE_FIX:
        cur.execute(
            "UPDATE system_degradations SET resolved_at = NOW(), resolved_reason = %s "
            "WHERE resolved_at IS NULL AND error_type = %s AND ts < %s",
            (_RESOLVED_REASON, error_type, _FIXES_LIVE_AT),
        )
        counts[error_type] = cur.rowcount

    cur.execute(
        "UPDATE system_degradations SET resolved_at = NOW(), resolved_reason = %s "
        "WHERE resolved_at IS NULL AND id = %s AND error_type = 'AttributeError' "
        "AND message LIKE %s",
        (
            _RESOLVED_REASON,
            _ATTRIBUTE_ERROR_ROW_ID,
            "%'Job' object has no attribute 'next_run_time'%",
        ),
    )
    counts["AttributeError"] = cur.rowcount

    total = sum(counts.values())
    if total > _M001_MAX_ROWS:
        raise MigrationGuardError(
            f"would resolve {total} rows, above the {_M001_MAX_ROWS} sanity bound"
        )
    return {"resolved": counts, "total": total}


# ── 2026-10-15-002: delete the 17 dead ratchet_stops rows (FIN-22c) ──────────
# Reconciled 2026-10-15 09:59 UTC: none of these stop_order_ids is open at the
# broker; 16 symbols are not held anywhere; DELL is held by spy_qqq_trend but
# protected by its own different stop order, not this row. FIN-22b (deployed
# 06:34 UTC) stopped the boot code that re-seeded them.

_DEAD_RATCHET_ROWS = {
    "ABT": "789e6ad1-0cc3-4129-860b-55b9df923c5a",
    "AMGN": "99a1203a-81c7-4a60-b31b-046f23653dff",
    "ARM": "b5c5020c-0110-45cf-af2b-cfa0077d6c28",
    "BMY": "ce87b15e-19eb-475c-bb87-df33427e35b5",
    "CSCO": "9605dae2-d4e5-4751-a939-d74a75515390",
    "DELL": "5899798a-5079-4472-984b-58c119dfab56",
    "EMR": "12d4a42d-d9ab-40f9-8851-282add6d15ef",
    "ITW": "dae38837-ffad-46c5-82a3-4dd6f1e58c86",
    "LMT": "94fbdd62-0bf1-48e0-9697-f68981420f03",
    "MMM": "a954a71c-0eef-4414-aa5f-e919f42407dd",
    "MS": "d9df546c-fa03-478e-a16a-4f3d8e257928",
    "MU": "e2ea75e3-63e9-42bf-8dc7-a5b00c900905",
    "PANW": "b289f55a-1af3-49ac-9d7b-5c4699f7e9e6",
    "PRU": "95e6042c-5c0b-43d1-80fd-634a0c9da6ad",
    "PYPL": "2ac36523-2c48-40b2-9c25-4707bc70388f",
    "RTX": "24231654-f2ba-40ea-929e-4fff99dfcee6",
    "SCHW": "80662c50-b474-4f61-a8cf-bd63492afb05",
}


def _m002_delete_dead_ratchet_rows(cur) -> dict:
    cur.execute("SELECT symbol, stop_order_id FROM ratchet_stops FOR UPDATE")
    current = {row[0]: row[1] for row in cur.fetchall()}
    if current != _DEAD_RATCHET_ROWS:
        extra = sorted(set(current) - set(_DEAD_RATCHET_ROWS))
        missing = sorted(set(_DEAD_RATCHET_ROWS) - set(current))
        changed = sorted(
            s for s in set(current) & set(_DEAD_RATCHET_ROWS)
            if current[s] != _DEAD_RATCHET_ROWS[s]
        )
        raise MigrationGuardError(
            "ratchet_stops no longer matches the reconciled snapshot "
            f"(extra={extra}, missing={missing}, changed_order_id={changed})"
        )
    symbols = sorted(_DEAD_RATCHET_ROWS)
    cur.execute("DELETE FROM ratchet_stops WHERE symbol = ANY(%s)", (symbols,))
    if cur.rowcount != len(symbols):
        raise MigrationGuardError(
            f"expected to delete {len(symbols)} rows, deleted {cur.rowcount}"
        )
    return {"deleted": symbols, "count": cur.rowcount}


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        id="2026-10-15-001-resolve-stale-degradations",
        description="Resolve pre-fix and stale system_degradations rows",
        apply=_m001_resolve_stale_degradations,
    ),
    Migration(
        id="2026-10-15-002-delete-dead-ratchet-rows",
        description="FIN-22c: delete the 17 dead ratchet_stops rows",
        apply=_m002_delete_dead_ratchet_rows,
    ),
)


def _is_production() -> bool:
    return os.environ.get("REPLIT_DEPLOYMENT") == "1"


def apply_pending_migrations(
    get_conn: Callable,
    migrations: tuple[Migration, ...] = MIGRATIONS,
    is_production: Callable[[], bool] = _is_production,
) -> dict[str, str]:
    """Apply each pending migration once. Returns {migration id: outcome}."""
    outcomes: dict[str, str] = {}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS platform_migrations ("
                    " id TEXT PRIMARY KEY,"
                    " applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                    " description TEXT NOT NULL,"
                    " summary JSONB)"
                )
    except Exception as exc:
        logger.error(f"DB | migrations: could not ensure platform_migrations: {exc}")
        return {m.id: "error" for m in migrations}

    for migration in migrations:
        if migration.production_only and not is_production():
            outcomes[migration.id] = "skipped-not-production"
            continue
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_KEY,))
                    cur.execute(
                        "SELECT 1 FROM platform_migrations WHERE id = %s",
                        (migration.id,),
                    )
                    if cur.fetchone():
                        outcomes[migration.id] = "already-applied"
                        continue
                    summary = migration.apply(cur)
                    cur.execute(
                        "INSERT INTO platform_migrations (id, description, summary) "
                        "VALUES (%s, %s, %s)",
                        (migration.id, migration.description, json.dumps(summary)),
                    )
            outcomes[migration.id] = "applied"
            logger.info(f"DB | migration applied: {migration.id} {summary}")
        except MigrationGuardError as exc:
            outcomes[migration.id] = "guard-failed"
            logger.error(f"DB | migration guard failed, rolled back: {migration.id}: {exc}")
        except Exception as exc:
            outcomes[migration.id] = "error"
            logger.error(f"DB | migration error, rolled back: {migration.id}: {exc}")
    return outcomes
