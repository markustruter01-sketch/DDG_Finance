"""Canonical symbol identity helpers shared by broker, ledger, and UI paths."""

from __future__ import annotations

from typing import Any


def canonical_symbol(symbol: Any) -> str:
    """Return a case-insensitive identity key for a tradable symbol."""
    return str(symbol or "").replace("/", "").replace("-", "").upper()


def same_symbol(left: Any, right: Any) -> bool:
    return canonical_symbol(left) == canonical_symbol(right)


def is_crypto_symbol(symbol: Any) -> bool:
    return canonical_symbol(symbol) in {"BTCUSD", "ETHUSD"}


def alpaca_symbol(symbol: Any) -> str:
    """Return Alpaca's slash form for crypto and unchanged form for equities."""
    value = str(symbol or "")
    key = canonical_symbol(value)
    if key == "BTCUSD":
        return "BTC/USD"
    if key == "ETHUSD":
        return "ETH/USD"
    return value