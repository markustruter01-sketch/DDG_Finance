"""The dataset lock (FLEET-V1 plan, step 2): locked rows need a registry-issued,
unspent grant that covers the dataset, the symbol and the window end."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from research_harness.harness import holdout, registry  # noqa: E402
from research_harness.harness.holdout import HoldoutViolation, ReadGrant  # noqa: E402
from research_harness.harness.store import BarStore  # noqa: E402

LOCK = date(2011, 1, 1)


def bars(first: date, n: int) -> list[dict]:
    out, d = [], first
    while len(out) < n:
        if d.weekday() < 5:
            out.append({"day": d, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5})
        d += timedelta(days=1)
    return out


@pytest.fixture
def setup(tmp_path):
    store = BarStore(tmp_path / "data")
    store.write_dataset("ds", source="t", bars_by_symbol={"AAA": bars(date(2010, 12, 1), 20),
                                                         "BBB": bars(date(2010, 12, 1), 20)},
                        locked_from=LOCK)
    store.write_dataset("ds", source="t", bars_by_symbol={"AAA": bars(LOCK, 30), "BBB": bars(LOCK, 30)},
                        locked=True)
    regs = tmp_path / "regs"
    regs.mkdir()
    reg = {f: "x" for f in registry.REQUIRED_FIELDS}
    reg.update(id="R1", lock={"datasets": {"ds": ["AAA"]}, "end": "2011-01-31"})
    (regs / "R1.json").write_text(json.dumps(reg))
    paths = dict(directory=regs, ledger=tmp_path / "ledger.jsonl", run_starts=tmp_path / "starts.jsonl")
    return store, paths


def test_open_rows_load_without_a_grant(setup):
    store, _ = setup
    rows = store.load("ds", "AAA", start=date(2010, 1, 1), end=date(2010, 12, 31))
    assert rows and rows[-1]["day"] < LOCK


def test_locked_rows_refused_without_grant_or_with_an_id(setup):
    store, _ = setup
    with pytest.raises(HoldoutViolation, match="no read grant"):
        store.load("ds", "AAA", start=date(2010, 1, 1), end=date(2011, 1, 5))
    with pytest.raises(HoldoutViolation, match="no read grant"):   # a registration id is not enough
        store.load("ds", "AAA", start=date(2010, 1, 1), end=date(2011, 1, 5), registration_id="FX-BT1")


def test_grant_reads_declared_symbol_within_window(setup):
    store, paths = setup
    _, grant = registry.begin_locked_run("R1", "holdout_test", **paths)
    rows = store.load("ds", "AAA", start=date(2010, 12, 1), end=date(2011, 1, 31), grant=grant)
    assert rows[0]["day"] < LOCK <= rows[-1]["day"]
    assert store.locked_manifest_hash("ds")


def test_grant_refuses_other_symbol_and_later_end(setup):
    store, paths = setup
    _, grant = registry.begin_locked_run("R1", "holdout_test", **paths)
    with pytest.raises(HoldoutViolation, match="declared universe"):
        store.load("ds", "BBB", start=date(2010, 12, 1), end=date(2011, 1, 31), grant=grant)
    with pytest.raises(HoldoutViolation, match="window end"):
        store.load("ds", "AAA", start=date(2010, 12, 1), end=date(2011, 2, 28), grant=grant)


def test_forged_grant_refused(setup):
    store, _ = setup
    fake = ReadGrant("R1", "holdout_test", {"ds": frozenset({"AAA"})}, date(2011, 1, 31), 999_999)
    with pytest.raises(HoldoutViolation, match="not issued"):
        store.load("ds", "AAA", start=date(2010, 12, 1), end=date(2011, 1, 31), grant=fake)


def test_grant_is_spent_when_the_run_is_recorded(setup):
    store, paths = setup
    reg, grant = registry.begin_locked_run("R1", "holdout_test", **paths)
    registry.record_run(reg, "holdout_test", {"ok": True}, data_manifest_hashes={}, code_commit=None,
                        ledger=paths["ledger"], grant=grant)
    with pytest.raises(HoldoutViolation, match="spent"):
        store.load("ds", "AAA", start=date(2010, 12, 1), end=date(2011, 1, 31), grant=grant)


def test_holdout_test_cannot_start_twice_even_if_unrecorded(setup):
    _, paths = setup
    registry.begin_locked_run("R1", "holdout_test", **paths)
    with pytest.raises(registry.RegistrationError, match="already started"):
        registry.begin_locked_run("R1", "holdout_test", **paths)
    registry.begin_locked_run("R1", "replication", **paths)   # replications stay allowed


def test_registration_without_structured_lock_refused(setup, tmp_path):
    _, paths = setup
    reg = {f: "x" for f in registry.REQUIRED_FIELDS}
    reg["id"] = "R2"
    (paths["directory"] / "R2.json").write_text(json.dumps(reg))
    with pytest.raises(registry.RegistrationError, match="structured lock"):
        registry.begin_locked_run("R2", "holdout_test", **paths)


def test_open_part_rejects_rows_on_or_after_lock_and_locked_part_rejects_earlier(tmp_path):
    store = BarStore(tmp_path)
    with pytest.raises(ValueError, match="on/after locked_from"):
        store.write_dataset("x", source="t", bars_by_symbol={"A": bars(date(2010, 12, 20), 20)},
                            locked_from=LOCK)
    store.write_dataset("y", source="t", bars_by_symbol={"A": bars(date(2010, 12, 1), 5)}, locked_from=LOCK)
    with pytest.raises(ValueError, match="rows before"):
        store.write_dataset("y", source="t", bars_by_symbol={"A": bars(date(2010, 12, 20), 20)}, locked=True)


def test_legacy_window_check_accepts_a_covering_grant(setup):
    _, paths = setup
    _, grant = registry.begin_locked_run("R1", "holdout_test", **paths)
    with pytest.raises(HoldoutViolation, match="window end"):
        holdout.check_window(date(2021, 6, 1), None, grant)
