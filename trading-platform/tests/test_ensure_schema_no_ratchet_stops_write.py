"""Ensure startup schema checks never write to ratchet_stops."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

from db import postgres


class _RecordingCursor:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements
        self.rowcount = 0

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def execute(self, statement: str, params=None) -> None:
        self.statements.append(statement)

    def fetchone(self):
        return None

    def fetchall(self) -> list:
        return []


class _RecordingConnection:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.statements)


def test_ensure_schema_executes_no_ratchet_stops_mutations(monkeypatch) -> None:
    statements: list[str] = []

    @contextmanager
    def fake_get_conn() -> Iterator[_RecordingConnection]:
        yield _RecordingConnection(statements)

    monkeypatch.setattr(postgres, "is_pg_available", lambda: True)
    monkeypatch.setattr(postgres, "get_conn", fake_get_conn)

    postgres.ensure_schema()

    mutation = re.compile(
        r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
        r"(?:[A-Z_][A-Z0-9_$]*\s*\.\s*)?ratchet_stops\b",
        re.IGNORECASE,
    )
    offending = [statement for statement in statements if mutation.search(statement)]

    assert statements, "ensure_schema should have exercised the recording connection"
    assert not offending, "\n\n".join(offending)
