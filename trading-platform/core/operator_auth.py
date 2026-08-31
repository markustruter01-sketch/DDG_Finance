"""Fail-closed operator authorization for protected Fleet Command routes."""

from __future__ import annotations

import os

from loguru import logger


OPERATOR_ALLOWLIST_ENV = "TRADING_API_OPERATOR_ALLOWLIST"


class OperatorAccessDenied(PermissionError):
    """Raised when an authenticated identity is not an approved operator."""


def operator_allowlist() -> frozenset[str]:
    """Return the configured Clerk user IDs, normalized for exact matching."""
    raw = os.getenv(OPERATOR_ALLOWLIST_ENV, "")
    return frozenset(
        entry.strip()
        for entry in raw.split(",")
        if entry.strip()
    )


def is_operator_allowed(clerk_user_id: str | None) -> bool:
    """Return True only for a non-empty ID explicitly present in the allowlist."""
    return bool(clerk_user_id and clerk_user_id in operator_allowlist())


def require_operator_allowed(
    clerk_user_id: str | None,
    *,
    context: str,
) -> None:
    """Enforce the allowlist and log only the attempted non-secret identity."""
    if is_operator_allowed(clerk_user_id):
        return

    logger.warning(
        "Operator access rejected: context={} clerk_user_id={} "
        "allowlist_configured={}",
        context,
        clerk_user_id or "<unknown>",
        bool(operator_allowlist()),
    )
    raise OperatorAccessDenied("Operator access is not authorized.")