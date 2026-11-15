"""Shared Alpaca client-order ID generation and duplicate-ID retry support."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from typing import Any, TypeVar


ALPACA_CLIENT_ORDER_ID_MAX_LENGTH = 48
_UUID_FRAGMENT_LENGTH = 16
_logger = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")


def client_order_id_environment_tag() -> str:
    """Return the short, fail-closed environment component for new IDs."""
    environment = os.environ.get("RUNNER_ENVIRONMENT", "").strip().lower()
    return {
        "published": "pub",
        "dev": "dev",
    }.get(environment, "unk")


def _bounded_prefix(prefix: str, environment_tag: str | None) -> str:
    prefix_text = str(prefix).strip().lower().strip("-")
    if environment_tag:
        prefix_text = f"{environment_tag}-{prefix_text}".strip("-")
    max_prefix_length = ALPACA_CLIENT_ORDER_ID_MAX_LENGTH - _UUID_FRAGMENT_LENGTH - 1
    return prefix_text[:max_prefix_length]


def make_client_order_id(prefix: str) -> str:
    """Return a bounded, tagged, per-call unique Alpaca client order ID."""
    suffix = uuid.uuid4().hex[:_UUID_FRAGMENT_LENGTH]
    bounded_prefix = _bounded_prefix(prefix, client_order_id_environment_tag())
    return f"{bounded_prefix}-{suffix}"


def client_order_id_matches_prefix(client_order_id: str, prefix: str) -> bool:
    """Match current tagged IDs while retaining ownership of legacy IDs."""
    normalized_id = str(client_order_id or "").strip().lower()
    current_prefix = _bounded_prefix(prefix, client_order_id_environment_tag())
    if normalized_id.startswith(f"{current_prefix}-"):
        return True
    # Existing broker orders predate environment tagging. Keep them discoverable
    # so stop/exit reconciliation does not create overlapping protection.
    legacy_prefix = _bounded_prefix(prefix, None)
    return normalized_id.startswith(f"{legacy_prefix}-")


def is_duplicate_client_order_id_error(exc: BaseException) -> bool:
    """Recognize Alpaca's duplicate client-order-ID rejection."""
    text = str(exc).lower()
    return (
        "client_order_id" in text
        and ("unique" in text or "duplicate" in text or "already" in text)
    )


def _order_status(order: Any) -> str:
    status = order.get("status") if isinstance(order, dict) else getattr(order, "status", "")
    return str(status or "").lower().rsplit(".", 1)[-1]


def submit_with_unique_client_order_id(
    submit: Callable[[str], _ResultT],
    prefix: str,
    *,
    lookup: Callable[[str], _ResultT],
) -> tuple[_ResultT, str]:
    """Send ONE order with a new client ID. It is never sent a second time.

    When the send raises, the order may still have reached the broker: the
    Alpaca libraries resend a request that got HTTP 504, and if the first try
    had been accepted the resend is refused as a duplicate client ID; a reply
    can also be lost after the broker took the order. So on any error the
    order is looked up by its client ID. Found (and not rejected): it is
    adopted and returned as if the send had succeeded. Not found: the
    original error is raised. A duplicate-ID refusal that cannot be read back
    raises too; the caller then treats the order as failed, never resends.
    (Until 16 Nov 2026 a duplicate-ID refusal made a new ID and sent the
    order again: one order could become two.)
    """
    client_order_id = make_client_order_id(prefix)
    try:
        return submit(client_order_id), client_order_id
    except Exception as exc:
        duplicate = is_duplicate_client_order_id_error(exc)
        try:
            order = lookup(client_order_id)
        except Exception as lookup_exc:
            if duplicate:
                raise RuntimeError(
                    f"order {client_order_id} is at the broker (duplicate client ID) "
                    f"but could not be read back: {lookup_exc}"
                ) from exc
            raise exc
        if order is None or _order_status(order) == "rejected":
            raise
        _logger.warning(
            "Order send raised but the broker holds it; adopted, not resent "
            "client_order_id=%s error=%s",
            client_order_id,
            str(exc)[:200],
        )
        return order, client_order_id