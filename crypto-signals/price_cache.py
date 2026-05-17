"""
price_cache.py — Read/write crypto_price_cache table.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.insert(0, _TRADING_PLATFORM)


def _get_conn():
    from db.postgres import get_conn
    return get_conn()


def update_price(symbol: str, price_usd: float) -> None:
    """Upsert a price entry for the given symbol."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crypto_price_cache (symbol, price_usd, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (symbol) DO UPDATE
                    SET price_usd  = EXCLUDED.price_usd,
                        updated_at = NOW()
                """,
                (symbol, price_usd),
            )


def get_price(symbol: str) -> Optional[float]:
    """Return the cached price for a symbol, or None if not cached."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price_usd FROM crypto_price_cache WHERE symbol = %s",
                (symbol,),
            )
            row = cur.fetchone()
            return float(row[0]) if row else None


def get_all_cached_prices() -> dict[str, float]:
    """Return all cached prices as {symbol: price_usd}."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol, price_usd FROM crypto_price_cache")
            return {row[0]: float(row[1]) for row in cur.fetchall()}
