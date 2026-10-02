"""Shared identity and classification for cash-parking instruments."""

from __future__ import annotations

from core.symbols import canonical_symbol


CASH_PARK_SYMBOLS = {"SGOV"}


def is_cash_park(symbol: object) -> bool:
    """Return whether a symbol identifies a cash-parking instrument."""
    symbol_key = canonical_symbol(symbol)
    return any(symbol_key == canonical_symbol(candidate) for candidate in CASH_PARK_SYMBOLS)
