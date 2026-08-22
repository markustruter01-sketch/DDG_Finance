"""Locked Bot 4 crypto universe.

Yahoo Finance is the validation-history source. Kraken public OHLC via ccxt is
the live paper-feed source. These mappings are deliberately centralized so the
two data paths cannot drift to different symbols.
"""

from __future__ import annotations

from datetime import date

BOT4_CRYPTO_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL", "ADA", "AVAX", "LINK")
BOT4_VALIDATION_START: date = date(2021, 1, 1)

YAHOO_SYMBOLS: dict[str, str] = {symbol: f"{symbol}-USD" for symbol in BOT4_CRYPTO_SYMBOLS}
KRAKEN_SYMBOLS: dict[str, str] = {symbol: f"{symbol}/USD" for symbol in BOT4_CRYPTO_SYMBOLS}
