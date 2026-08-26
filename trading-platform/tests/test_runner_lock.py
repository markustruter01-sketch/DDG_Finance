from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from core import runner_lock


def _fake_conn():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    return conn, cursor


def test_claim_returns_owned_row():
    conn, cursor = _fake_conn()
    cursor.fetchone.return_value = (
        "oracle",
        "published",
        101,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc),
    )
    with patch("db.postgres.is_pg_available", return_value=True), patch(
        "db.postgres.get_conn"
    ) as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock("oracle", "published", 101, 10800)

    assert result["owned"] is True
    assert result["lock"]["environment"] == "published"


def test_fresh_other_environment_is_refused():
    conn, cursor = _fake_conn()
    cursor.fetchone.side_effect = [
        None,
        (
            "oracle",
            "published",
            101,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        ),
    ]
    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock("oracle", "dev", 202, 10800)

    assert result["owned"] is False
    assert result["lock"]["environment"] == "published"