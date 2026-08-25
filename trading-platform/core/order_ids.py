"""Shared Alpaca client-order ID generation and duplicate-ID retry support."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, TypeVar


ALPACA_CLIENT_ORDER_ID_MAX_LENGTH = 48
_UUID_FRAGMENT_LENGTH = 16
_logger = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")


def make_client_order_id(prefix: str) -> str:
    """Return a bounded, per-call unique Alpaca client order ID."""
    suffix = uuid.uuid4().hex[:_UUID_FRAGMENT_LENGTH]
    prefix_text = str(prefix).strip().lower().strip("-")
    max_prefix_length = ALPACA_CLIENT_ORDER_ID_MAX_LENGTH - len(suffix) - 1
    bounded_prefix = prefix_text[:max_prefix_length]
    return f"{bounded_prefix}-{suffix}"


def is_duplicate_client_order_id_error(exc: BaseException) -> bool:
    """Recognize Alpaca's duplicate client-order-ID rejection."""
    text = str(exc).lower()
    return (
        "client_order_id" in text
        and ("unique" in text or "duplicate" in text or "already" in text)
    )


def submit_with_unique_client_order_id(
    submit: Callable[[str], _ResultT],
    prefix: str,
) -> tuple[_ResultT, str]:
    """Submit with a generated ID and retry once only on duplicate-ID errors."""
    for attempt in range(2):
        client_order_id = make_client_order_id(prefix)
        try:
            return submit(client_order_id), client_order_id
        except Exception as exc:
            if attempt == 0 and is_duplicate_client_order_id_error(exc):
                _logger.warning(
                    "Order ID collision rejected; regenerating ID and retrying once "
                    "prefix=%s",
                    prefix,
                )
                continue
            raise
    raise RuntimeError("unreachable duplicate client-order ID retry state")