"""Pre-registrations and the run ledger.

A registration is a JSON file in research_harness/registrations/, committed BEFORE the
held-out test runs. The ledger (research_harness/ledger.jsonl, committed) records every
held-out run. A registration may be held-out tested once; replications of an
earlier run are allowed but are recorded as replications, never as new tests.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
REGISTRATIONS_DIR = RESEARCH_ROOT / "registrations"
LEDGER_PATH = RESEARCH_ROOT / "ledger.jsonl"

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


def record_run(
    reg: dict[str, Any],
    kind: str,
    result: dict[str, Any],
    *,
    data_manifest_hashes: dict[str, str],
    code_commit: str | None,
    ledger: Path = LEDGER_PATH,
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
    return entry
