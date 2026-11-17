"""
No crypto, anywhere (Markus, 17 Nov 2026: "none of the accounts at all trade any crypto, full stop").

No bot, job, script or person-triggered path may BUY a cryptocurrency or a fund
that holds one. The rule sits at the lowest level every order passes through
(the HTTP session of every Alpaca client, see core/broker_http.py, and the
OANDA order call), so no strategy, old module or new code can get round it.

Selling is still allowed: a protective stop, or closing a holding, only ever
reduces crypto. Whether to sell the one crypto holding left (owner-kept BTC in
the jerome_macro account) is Markus's decision; nothing here sells it.
"""
from __future__ import annotations

from typing import Any

# Coins Alpaca or OANDA list, by their base symbol (BTC/USD, BTCUSD, BTC_USD all match "BTC").
CRYPTO_COINS = frozenset({
    "BTC", "ETH", "SOL", "AVAX", "DOGE", "LTC", "BCH", "LINK", "UNI", "AAVE", "DOT", "XRP", "ADA",
    "MATIC", "POL", "SHIB", "XTZ", "SUSHI", "MKR", "BAT", "CRV", "GRT", "YFI", "TRUMP", "PEPE",
    "USDT", "USDC", "SKY", "XLM", "ALGO", "ATOM", "NEAR", "FIL", "TRX", "HBAR", "TON", "ARB", "OP",
})
# Exchange-traded funds and trusts whose value comes from crypto.
CRYPTO_FUNDS = frozenset({
    "IBIT", "GBTC", "BTC", "FBTC", "ARKB", "BITB", "HODL", "BRRR", "EZBC", "BTCO", "BTCW", "DEFI",
    "BITO", "BITX", "BITI", "BTF", "MAXI", "XBTF", "BTCZ",
    "ETHA", "ETHE", "ETH", "FETH", "ETHW", "CETH", "ETHV", "QETH", "EZET", "ETHU", "ETHD", "EETH",
    "BSOL", "SOLZ", "XRPI", "MSTU", "MSTX", "CONL", "SATO", "BKCH", "WGMI", "BLOK", "BITQ",
})
QUOTES = ("USD", "USDT", "USDC")


class CryptoTradingBlocked(RuntimeError):
    """Raised instead of sending an order that would buy crypto."""


def is_crypto(symbol: str | None) -> bool:
    """True for a coin pair (BTC/USD, BTCUSD, BTC_USD, ETH-USD) or a crypto fund (IBIT)."""
    s = str(symbol or "").strip().upper()
    if not s:
        return False
    if s in CRYPTO_FUNDS:
        return True
    for sep in ("/", "_", "-"):
        if sep in s:
            base, _, quote = s.partition(sep)
            return base in CRYPTO_COINS or (quote in QUOTES[1:])
    for q in QUOTES:
        if s.endswith(q) and s[: -len(q)] in CRYPTO_COINS:
            return True
    # A bare coin name ("LINK", "SKY") is also a stock ticker, so it is not treated as crypto:
    # Alpaca and OANDA always name coins as pairs (BTC/USD, BTCUSD, BTC_USD).
    return False


def is_buy(side: Any) -> bool:
    return str(getattr(side, "value", side) or "").strip().lower().rsplit(".", 1)[-1] in ("buy", "buy_to_cover")


def refuse_crypto_buy(symbol: Any, side: Any, where: str) -> None:
    """Raise CryptoTradingBlocked if this order would buy crypto. Sells pass."""
    if is_crypto(symbol) and is_buy(side):
        _report(f"{where}: refused to BUY {symbol}: no crypto is traded on any account (Markus, 17 Nov 2026)")
        raise CryptoTradingBlocked(f"crypto buy refused: {symbol} ({where})")


def refuse_crypto_units(instrument: Any, units: Any, where: str) -> None:
    """OANDA: refuse any order that opens a crypto position (OANDA orders only ever open here)."""
    if is_crypto(instrument):
        _report(f"{where}: refused an order on {instrument}: no crypto is traded on any account")
        raise CryptoTradingBlocked(f"crypto order refused: {instrument} ({where})")


def _report(message: str) -> None:
    try:
        from loguru import logger
        logger.critical(message)
    except Exception:  # pragma: no cover - logging must never stop the refusal
        pass
