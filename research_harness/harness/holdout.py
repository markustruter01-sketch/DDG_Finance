"""The locked held-out period.

Everything from HOLDOUT_START onwards is reserved for ONE registered test per
candidate. Exploration may only read data that ends before it. This is the
single definition; nothing else in the codebase may restate the date.
"""

from __future__ import annotations

from datetime import date, timedelta

HOLDOUT_START = date(2021, 1, 1)
EXPLORE_END = HOLDOUT_START - timedelta(days=1)


class HoldoutViolation(RuntimeError):
    """A read touched the held-out period without a registration."""


def check_window(end: date, registration_id: str | None) -> None:
    """Refuse any window reaching the held-out period unless registered.

    The id must name a committed, well-formed registration file — any string
    is not enough, or the lock could be bypassed by typing a made-up id.
    """
    if end < HOLDOUT_START:
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
