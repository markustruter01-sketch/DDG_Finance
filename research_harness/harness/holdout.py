"""The locked held-out period.

Two locks live here.

1. The legacy date lock (registrations up to GEAR-V2): everything from
   HOLDOUT_START onwards is reserved for ONE registered test per candidate.
   Exploration may only read data that ends before it.

2. The dataset lock (FLEET-V1 onwards): a dataset written with a
   ``locked_from`` date keeps its rows from that date in a separate folder
   (``<root>/_locked/<dataset>``). Those rows can only be read with a
   ReadGrant, and a grant is only issued by ``registry.begin_locked_run`` for
   a registration whose structured ``lock`` field names the dataset, the
   symbol, and a window end covering the read. A grant is spent when its run
   is recorded and cannot be used again.

A determined person can always read a CSV by hand; the point is that no
harness code path can read locked rows by accident or by typing an id.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping

HOLDOUT_START = date(2021, 1, 1)
EXPLORE_END = HOLDOUT_START - timedelta(days=1)

# Plans whose committed plan file declares an exploration window that runs past
# the legacy lock (their own held-out rows live in a dataset's locked part).
# Each entry must cite its plan; a test checks the plan file states the date.
DECLARED_EXPLORATION_END = {
    "MOMO-V1": date(2024, 12, 31),     # research_harness/explore/MOMO-V1-PLAN.md, "Windows"
}


class HoldoutViolation(RuntimeError):
    """A read touched a held-out period without permission."""


@dataclass(frozen=True, eq=False)
class ReadGrant:
    """Permission to read locked rows. Create only through registry.begin_locked_run."""
    registration_id: str
    kind: str
    datasets: Mapping[str, frozenset[str]]
    end: date
    serial: int


_serials = itertools.count(1)
_live: dict[int, ReadGrant] = {}
_spent: set[int] = set()


def issue_grant(registration_id: str, kind: str,
                datasets: Mapping[str, frozenset[str]], end: date) -> ReadGrant:
    """Called by the registry only, after it has validated the registration."""
    grant = ReadGrant(registration_id, kind, dict(datasets), end, next(_serials))
    _live[grant.serial] = grant
    return grant


def spend_grant(grant: ReadGrant) -> None:
    _check_grant(grant)
    _spent.add(grant.serial)
    del _live[grant.serial]


def _check_grant(grant: ReadGrant | None) -> ReadGrant:
    if not isinstance(grant, ReadGrant):
        raise HoldoutViolation("locked read refused: no read grant (use registry.begin_locked_run)")
    if grant.serial in _spent:
        raise HoldoutViolation(f"locked read refused: the grant for {grant.registration_id} is spent")
    if _live.get(grant.serial) is not grant:
        raise HoldoutViolation("locked read refused: this grant was not issued by the registry")
    return grant


def check_locked_read(grant: ReadGrant | None, dataset: str, symbol: str, end: date) -> None:
    """Refuse a read of locked rows unless the grant covers this dataset, symbol and end date."""
    g = _check_grant(grant)
    if symbol not in g.datasets.get(dataset, frozenset()):
        raise HoldoutViolation(
            f"locked read refused: {dataset}/{symbol} is not in {g.registration_id}'s declared universe")
    if end > g.end:
        raise HoldoutViolation(
            f"locked read refused: {end.isoformat()} is after {g.registration_id}'s window end "
            f"{g.end.isoformat()}")


def check_window(end: date, registration_id: str | None, grant: ReadGrant | None = None,
                 plan: str | None = None) -> None:
    """Legacy date lock: refuse any window reaching HOLDOUT_START unless registered.

    A valid grant whose window covers ``end`` also passes, and so does an
    exploration read for a plan in DECLARED_EXPLORATION_END that ends on or
    before that plan's declared exploration end. Otherwise the id must name a
    committed, well-formed registration file — any string is not enough, or
    the lock could be bypassed by typing a made-up id.
    """
    if end < HOLDOUT_START:
        return
    if plan is not None:
        declared = DECLARED_EXPLORATION_END.get(plan)
        if declared is None:
            raise HoldoutViolation(f"plan {plan!r} declares no exploration window past {EXPLORE_END}")
        if end > declared:
            raise HoldoutViolation(
                f"window ends {end.isoformat()}, after {plan}'s declared exploration end {declared.isoformat()}")
        return
    if grant is not None:
        g = _check_grant(grant)
        if end > g.end:
            raise HoldoutViolation(
                f"window ends {end.isoformat()}, after {g.registration_id}'s window end {g.end.isoformat()}")
        return
    if not registration_id:
        raise HoldoutViolation(
            f"window ends {end.isoformat()}, inside the held-out period "
            f"(from {HOLDOUT_START.isoformat()}). Exploration must end by "
            f"{EXPLORE_END.isoformat()}; held-out reads need a registration id."
        )
    from research_harness.harness.registry import RegistrationError, load_registration

    try:
        load_registration(registration_id)
    except RegistrationError as exc:
        raise HoldoutViolation(f"held-out read refused: {exc}") from exc
