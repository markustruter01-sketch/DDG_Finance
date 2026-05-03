"""Canonical unrealised-P&L helper used by every paper engine.

Audit fix H2 (2026-05-03):
Each paper engine previously had its own ad-hoc P&L formula.  Sign conventions
diverged for shorts (kraken-bot bug already patched at paper_engine.py:457; the
same class of bug existed latent in poseidon and forex engines).  This module
defines the single canonical formula; every engine MUST route through it.

Long  P&L = (current - entry) * units - fees
Short P&L = (entry - current) * units - fees
"""
from __future__ import annotations
from typing import Literal

Side = Literal["long", "short"]


def compute_unrealized_pnl(
    side: str,
    entry: float,
    current: float,
    units: float,
    fees: float = 0.0,
) -> float:
    """Return gross P&L in quote currency (entry/current must share units).

    Args:
        side:    'long' or 'short' (case-insensitive).
        entry:   entry price.
        current: current/exit price.
        units:   absolute position size in base units (always positive).
        fees:    total round-trip fees (or just exit fee, caller's choice) in
                 quote currency.  Subtracted from gross P&L.
    """
    s = (side or "").lower()
    e = float(entry)
    c = float(current)
    u = float(units)
    f = float(fees)

    if s == "long":
        gross = (c - e) * u
    elif s == "short":
        gross = (e - c) * u
    else:
        raise ValueError(f"compute_unrealized_pnl: unknown side {side!r}")

    return gross - f
