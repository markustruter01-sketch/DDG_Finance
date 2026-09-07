"""Test-session guardrails for the shared production-capable database."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest


_ACTIVE_TEST = "<no test currently running>"
_ALLOW_PRODUCTION_DB = False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "allow_production_db: explicitly opt into a documented production-db integration test",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    global _ACTIVE_TEST, _ALLOW_PRODUCTION_DB
    _ACTIVE_TEST = item.nodeid
    _ALLOW_PRODUCTION_DB = item.get_closest_marker("allow_production_db") is not None


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    del item, nextitem
    global _ACTIVE_TEST, _ALLOW_PRODUCTION_DB
    _ACTIVE_TEST = "<no test currently running>"
    _ALLOW_PRODUCTION_DB = False


def _production_db_blocked_error() -> RuntimeError:
    return RuntimeError(
        "Production database access blocked during test "
        f"{_ACTIVE_TEST}. Tests must not touch the production database. "
        "Use @pytest.mark.allow_production_db only for a documented "
        "integration test that genuinely requires it."
    )


@pytest.fixture(scope="session", autouse=True)
def block_production_database() -> Generator[None, None, None]:
    """Prevent tests from using the shared live-data connection boundaries."""
    import db.postgres
    from core import database_authority

    original_get_conn = db.postgres.get_conn
    original_get_authoritative_dsn = database_authority.get_authoritative_dsn

    def guarded_get_conn(*args: Any, **kwargs: Any):
        if _ALLOW_PRODUCTION_DB:
            return original_get_conn(*args, **kwargs)
        raise _production_db_blocked_error()

    def guarded_get_authoritative_dsn(*args: Any, **kwargs: Any) -> str:
        if _ALLOW_PRODUCTION_DB:
            return original_get_authoritative_dsn(*args, **kwargs)
        raise _production_db_blocked_error()

    db.postgres.get_conn = guarded_get_conn
    database_authority.get_authoritative_dsn = guarded_get_authoritative_dsn
    try:
        yield
    finally:
        db.postgres.get_conn = original_get_conn
        database_authority.get_authoritative_dsn = original_get_authoritative_dsn