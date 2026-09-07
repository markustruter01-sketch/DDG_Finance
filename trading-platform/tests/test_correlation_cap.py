"""Regression tests for the live correlation-cap entry gate."""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "kraken-bot"))

import asia_trend_strategy as asia
from core.correlation_cap import corr_cap_check


def test_import_failure_blocks_when_held_etf_exists(monkeypatch) -> None:
    monkeypatch.setattr(asia, "_CORR_CAP_OK", False)

    allowed, reason = asia._corr_cap_check("EWT", ["EWY"])

    assert (allowed, reason) == (False, "corr_cap_unavailable")


def test_empty_held_list_allows_even_when_cap_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(asia, "_CORR_CAP_OK", False)

    allowed, reason = asia._corr_cap_check("EWT", [])

    assert (allowed, reason) == (True, "no_held_etfs")


def test_missing_candidate_history_blocks() -> None:
    allowed, reason = corr_cap_check(
        "EWT",
        ["EWY"],
        {"EWY": [100.0, 101.0]},
    )

    assert (allowed, reason) == (False, "corr_cap_no_candidate_history")


def test_missing_held_history_still_allows_with_candidate_history() -> None:
    allowed, reason = corr_cap_check(
        "EWT",
        ["EWY"],
        {"EWT": [100.0, 101.0, 102.0]},
        max_correlated=1,
    )

    assert (allowed, reason) == (True, None)
