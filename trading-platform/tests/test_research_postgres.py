from __future__ import annotations

import pytest

from db import research_postgres


class _Cursor:
    def __init__(self, database: str) -> None:
        self.database = database

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _query: str) -> None:
        return None

    def fetchone(self) -> tuple[str]:
        return (self.database,)


class _Connection:
    def __init__(self, database: str) -> None:
        self.database = database
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self.database)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_research_dsn_prefers_explicit_helium_and_ignores_shared_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HELIUM_DATABASE_URL", "postgresql://research.example/heliumdb")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared.example/shared")
    monkeypatch.setenv("PGHOST", "shared.example")
    monkeypatch.setenv("PGDATABASE", "shared")
    assert research_postgres.research_dsn() == "postgresql://research.example/heliumdb"


def test_research_dsn_fails_closed_without_explicit_or_permitted_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("HELIUM_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared.example/shared")
    monkeypatch.setenv("PGHOST", "shared.example")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "dev")
    monkeypatch.setattr(
        research_postgres,
        "_CACHE_PATH",
        tmp_path / "missing-latest.json",
    )
    with pytest.raises(RuntimeError, match="HELIUM_DATABASE_URL"):
        research_postgres.research_dsn()


def test_research_connection_rejects_non_helium_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection("not-helium")
    monkeypatch.setenv("HELIUM_DATABASE_URL", "postgresql://example/not-helium")
    monkeypatch.setattr(research_postgres.psycopg2, "connect", lambda *args, **kwargs: connection)
    with pytest.raises(RuntimeError, match="expected 'heliumdb'"):
        with research_postgres.get_research_conn():
            raise AssertionError("the rejected connection must not be yielded")
    assert connection.rolled_back is True
    assert connection.committed is False
    assert connection.closed is True


def test_research_connection_commits_only_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection("heliumdb")
    monkeypatch.setenv("HELIUM_DATABASE_URL", "postgresql://example/heliumdb")
    monkeypatch.setattr(research_postgres.psycopg2, "connect", lambda *args, **kwargs: connection)
    with research_postgres.get_research_conn() as yielded:
        assert yielded is connection
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True