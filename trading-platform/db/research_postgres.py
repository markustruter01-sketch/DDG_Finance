"""Explicit connection boundary for development-only Helium research.

This module is intentionally separate from ``db.postgres``.  It never reads
DATABASE_URL or PG* variables, and it rejects any database other than the
recovered Helium research database.  The cache fallback is only for this
workspace's development session; a durable HELIUM_DATABASE_URL remains the
preferred configuration.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

import psycopg2


EXPECTED_DATABASE = "heliumdb"
_CACHE_PATH = Path(__file__).resolve().parents[2] / ".cache" / "replit" / "env" / "latest.json"


def _cache_dsn() -> str:
    if not _CACHE_PATH.exists():
        return ""
    try:
        with _CACHE_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        return str(payload.get("environment", {}).get("DATABASE_URL", "") or "")
    except (OSError, ValueError, TypeError):
        return ""


def research_dsn() -> str:
    """Return the explicit research DSN without consulting shared DB config."""
    configured = os.environ.get("HELIUM_DATABASE_URL", "").strip()
    if configured:
        return configured
    if os.environ.get("RUNNER_ENVIRONMENT", "dev") in {"dev", "development"}:
        recovered = _cache_dsn()
        if recovered:
            return recovered
    raise RuntimeError(
        "HELIUM_DATABASE_URL is required for Strategy Bench research "
        "(the non-durable cache fallback was unavailable)"
    )


def research_dsn_host() -> str:
    """Return only the configured host for safe provenance logging."""
    host = urlsplit(research_dsn()).hostname
    return host or "unknown"


@contextmanager
def get_research_conn() -> Iterator[psycopg2.extensions.connection]:
    """Open a standalone Helium connection and commit only the caller's work."""
    conn = psycopg2.connect(
        research_dsn(),
        application_name="strategy-bench-research",
        connect_timeout=15,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            database = cur.fetchone()[0]
        if database != EXPECTED_DATABASE:
            raise RuntimeError(
                f"research connection resolved to {database!r}; "
                f"expected {EXPECTED_DATABASE!r}"
            )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def is_research_available() -> bool:
    """Return whether the explicit research connection can be opened."""
    try:
        with get_research_conn():
            return True
    except Exception:
        return False