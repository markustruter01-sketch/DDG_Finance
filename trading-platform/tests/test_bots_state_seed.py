from __future__ import annotations

import re
from pathlib import Path


def test_bots_state_seed_has_no_trailing_comma_before_on_conflict() -> None:
    postgres_path = Path(__file__).resolve().parents[1] / "db" / "postgres.py"
    source = postgres_path.read_text()
    seed_match = re.search(
        r"INSERT\s+INTO\s+bots_state\b"
        r".*?ON\s+CONFLICT\s+\(bot_id\)\s+DO\s+NOTHING\s*;",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )

    assert seed_match is not None, "bots_state seed statement not found"
    assert re.search(
        r",\s*ON\s+CONFLICT",
        seed_match.group(),
        flags=re.IGNORECASE,
    ) is None