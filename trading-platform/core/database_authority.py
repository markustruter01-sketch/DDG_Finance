"""Authoritative database connection guard for the live platform."""

from __future__ import annotations

import os


def get_authoritative_dsn() -> str:
    """Return DATABASE_URL or fail closed; never select an alternate DSN."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is required; refusing to resolve another database"
        )
    return dsn


def assert_database_authority() -> bool:
    """Startup assertion that the platform has its required shared DSN."""
    get_authoritative_dsn()
    return True