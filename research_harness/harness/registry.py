"""Pre-registrations and the run ledger.

A registration is a JSON file in research_harness/registrations/, committed BEFORE the
held-out test runs. The ledger (research_harness/ledger.jsonl, committed) records every
held-out run. A registration may be held-out tested once; replications of an
earlier run are allowed but are recorded as replications, never as new tests.

Registrations from FLEET-V1 on also carry a structured ``lock``:
    {"datasets": {"<dataset>": ["SYM", ...]}, "end": "YYYY-MM-DD"}
``begin_locked_run`` validates it, writes a start marker (so a held-out test
cannot be started twice, even if the first one crashed before recording), and
returns the only object that can read locked dataset rows.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
REGISTRATIONS_DIR = RESEARCH_ROOT / "registrations"
LEDGER_PATH = RESEARCH_ROOT / "ledger.jsonl"
RUN_STARTS_PATH = RESEARCH_ROOT / "run_starts.jsonl"

REQUIRED_FIELDS = (
    "id", "registered_at", "hypothesis", "candidate", "candidates_declared",
    "prior_variants_tried", "universe", "window", "sizing", "leverage",
    "costs", "pass_bar",
)
RUN_KINDS = ("holdout_test", "replication")


class RegistrationError(RuntimeError):
    """A registration is missing, malformed, changed, or already used."""


def load_registration(reg_id: str, directory: Path = REGISTRATIONS_DIR) -> dict[str, Any]:
    path = directory / f"{reg_id}.json"
    if not path.exists():
        raise RegistrationError(f"no registration file {path}")
    data = json.loads(path.read_text())
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise RegistrationError(f"registration {reg_id} missing fields: {missing}")
    if data["id"] != reg_id:
        raise RegistrationError(f"registration id mismatch: file {reg_id}, body {data['id']}")
    return data


def registration_hash(reg: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(reg, sort_keys=True).encode()).hexdigest()


def ledger_entries(ledger: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def begin_run(
    reg_id: str,
    kind: str,
    *,
    directory: Path = REGISTRATIONS_DIR,
    ledger: Path = LEDGER_PATH,
) -> dict[str, Any]:
    """Validate that this run is allowed. Returns the registration."""
    if kind not in RUN_KINDS:
        raise RegistrationError(f"kind must be one of {RUN_KINDS}")
    reg = load_registration(reg_id, directory)
    previous = [e for e in ledger_entries(ledger) if e["registration_id"] == reg_id]
    if kind == "holdout_test" and any(e["kind"] == "holdout_test" for e in previous):
        raise RegistrationError(
            f"{reg_id} has already had its one held-out test; a re-run is a replication"
        )
    for e in previous:
        if e["registration_hash"] != registration_hash(reg):
            raise RegistrationError(
                f"{reg_id} was edited after it was first run; register a new id instead"
            )
    return reg


def parse_lock(reg: dict[str, Any]) -> tuple[dict[str, frozenset[str]], date]:
    """The structured lock of a registration: {dataset: symbols} and the window end."""
    lock = reg.get("lock")
    if not isinstance(lock, dict) or not isinstance(lock.get("datasets"), dict) or "end" not in lock:
        raise RegistrationError(f"registration {reg.get('id')} has no structured lock "
                                '({"datasets": {...}, "end": "YYYY-MM-DD"})')
    datasets = {}
    for ds, syms in lock["datasets"].items():
        if not isinstance(syms, list) or not syms or not all(isinstance(s, str) for s in syms):
            raise RegistrationError(f"lock.datasets[{ds!r}] must be a non-empty list of symbols")
        datasets[ds] = frozenset(syms)
    return datasets, date.fromisoformat(lock["end"])


def begin_locked_run(
    reg_id: str,
    kind: str,
    *,
    directory: Path = REGISTRATIONS_DIR,
    ledger: Path = LEDGER_PATH,
    run_starts: Path = RUN_STARTS_PATH,
):
    """begin_run, plus the single-use start marker and a read grant for locked rows.

    Returns (registration, grant). Pass the grant to BarStore.load and to
    record_run, which spends it.
    """
    from research_harness.harness.holdout import issue_grant

    reg = begin_run(reg_id, kind, directory=directory, ledger=ledger)
    datasets, end = parse_lock(reg)
    starts = ([json.loads(x) for x in run_starts.read_text().splitlines() if x.strip()]
              if run_starts.exists() else [])
    if kind == "holdout_test" and any(
            s["registration_id"] == reg_id and s["kind"] == "holdout_test" for s in starts):
        raise RegistrationError(
            f"{reg_id}'s held-out test was already started (see {run_starts.name}); "
            "a second start is refused even if the first did not finish. Record a replication instead.")
    with run_starts.open("a") as fh:
        fh.write(json.dumps({"registration_id": reg_id, "kind": kind,
                             "registration_hash": registration_hash(reg),
                             "started_at": datetime.now(timezone.utc).isoformat()},
                            sort_keys=True) + "\n")
    return reg, issue_grant(reg_id, kind, datasets, end)


def record_run(
    reg: dict[str, Any],
    kind: str,
    result: dict[str, Any],
    *,
    data_manifest_hashes: dict[str, str],
    code_commit: str | None,
    ledger: Path = LEDGER_PATH,
    grant=None,
) -> dict[str, Any]:
    entry = {
        "registration_id": reg["id"],
        "registration_hash": registration_hash(reg),
        "kind": kind,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": code_commit,
        "data_manifests": data_manifest_hashes,
        "result": result,
    }
    with ledger.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    if grant is not None:
        from research_harness.harness.holdout import spend_grant
        spend_grant(grant)
    return entry
