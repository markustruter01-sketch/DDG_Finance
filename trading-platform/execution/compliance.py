"""
Fiscal Compliance — Wash-Sale Guard + DRIP Disable
-----------------------------------------------------
Module 5 of the v4.3 infrastructure refactor.

Wash-Sale Rule (IRS §1091)
--------------------------
  You cannot claim a loss on the sale of a security if you buy a
  "substantially identical" security within 30 days before or after
  the sale.  This module enforces the 30-day look-back on the buy side.

Similarity Matrix
-----------------
  Groups ETFs that are "substantially identical" for wash-sale purposes.
  SEC guidance treats funds tracking the same index as substantially
  identical even with different expense ratios or issuers.

  Group  | Tickers
  -------+------------------------------------------------------------
  US_EQ  | SPY, IVV, VOO, QQQ, QQQM, IWM, VTI
  TECH   | XLK, VGT, FTEC
  FIN    | XLF, VFH
  HEALTH | XLV, VHT
  ENERGY | XLE, VDE
  BONDS  | TLT, EDV, VGLT / IEF, VGIT
  GOLD   | GLD, IAU, SGOL
  SILVER | SLV, SIVR
  OIL    | USO, OILU
  CMDTY  | PDBC, DJP
  BTC    | IBIT, GBTC, BTCUSD, BTC/USD
  ETH    | ETHA, ETHUSD, ETH/USD
  INCOME | JEPQ, JEPI, SCHD, DIVO

DRIP Policy
-----------
  DRIP_ENABLED = False — automatic dividend reinvestment is intentionally
  disabled.  All cash dividends from JEPQ accumulate as cash and are
  handled by the profit-sweep logic on the next cycle.  Enabling DRIP
  would create fractional tax lots outside the bot's tracking scope.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from loguru import logger

# ── DRIP policy ────────────────────────────────────────────────────────────
DRIP_ENABLED: bool = False
logger.info(f"Compliance | DRIP_ENABLED={DRIP_ENABLED} — dividends accumulate as cash")


# ── Similarity matrix ──────────────────────────────────────────────────────
# Each ticker maps to a frozenset of tickers in the same similarity group.
# We build the map once at import time so lookup is O(1).

_SIMILARITY_GROUPS: list[frozenset[str]] = [
    frozenset({"SPY", "IVV", "VOO"}),
    frozenset({"QQQ", "QQQM"}),
    frozenset({"IWM", "VB", "VTI"}),
    frozenset({"XLK", "VGT", "FTEC"}),
    frozenset({"XLF", "VFH"}),
    frozenset({"XLV", "VHT"}),
    frozenset({"XLE", "VDE"}),
    frozenset({"TLT", "EDV", "VGLT"}),
    frozenset({"IEF", "VGIT"}),
    frozenset({"GLD", "IAU", "SGOL"}),
    frozenset({"SLV", "SIVR"}),
    frozenset({"USO", "OILU"}),
    frozenset({"PDBC", "DJP"}),
    frozenset({"IBIT", "GBTC", "BTCUSD", "BTC/USD"}),
    frozenset({"ETHA", "ETHUSD", "ETH/USD"}),
    frozenset({"JEPQ", "JEPI", "SCHD", "DIVO"}),
]

# ticker → set of all tickers in the same group (including itself)
SIMILARITY_MAP: dict[str, frozenset[str]] = {}
for _group in _SIMILARITY_GROUPS:
    for _ticker in _group:
        SIMILARITY_MAP[_ticker.upper()] = _group


def get_similar_tickers(ticker: str) -> frozenset[str]:
    """Return all tickers substantially identical to *ticker* (incl. itself)."""
    return SIMILARITY_MAP.get(ticker.upper(), frozenset({ticker.upper()}))


# ── Wash-sale check ────────────────────────────────────────────────────────

def check_wash_sale(ticker: str, lookback_days: int = 30) -> dict:
    """
    Check whether buying *ticker* today would trigger a wash-sale violation.

    Queries the trade journal for any Closed_Loss trade on a substantially
    identical security within the past *lookback_days* calendar days.

    Returns
    -------
    {
        "blocked":    bool,
        "reason":     str | None,
        "similar_ticker": str | None,   # the loss ticker that triggered block
        "loss_date":  str | None,       # ISO date of the blocking loss
        "pnl_pct":    float | None,
    }
    """
    similar = get_similar_tickers(ticker)
    cutoff  = (date.today() - timedelta(days=lookback_days)).isoformat()

    blocked_result = {
        "blocked":        False,
        "reason":         None,
        "similar_ticker": None,
        "loss_date":      None,
        "pnl_pct":        None,
    }

    try:
        from db.postgres import get_conn, is_pg_available

        if is_pg_available():
            _check_pg(ticker, similar, cutoff, blocked_result)
        else:
            _check_sqlite(ticker, similar, cutoff, blocked_result)
    except Exception as exc:
        logger.warning(f"Compliance | Wash-sale check failed for {ticker}: {exc} — allowing trade")
        return blocked_result  # fail-open: don't block on DB errors

    if blocked_result["blocked"]:
        logger.warning(
            f"Compliance | ⚠️  WASH-SALE BLOCK: {ticker} — "
            f"similar ticker {blocked_result['similar_ticker']} "
            f"closed at {blocked_result['pnl_pct']:+.2f}% on "
            f"{blocked_result['loss_date']} ({lookback_days}-day window)"
        )
    else:
        logger.debug(f"Compliance | {ticker} — no wash-sale conflict in past {lookback_days} days")

    return blocked_result


def _check_pg(
    ticker: str,
    similar: frozenset[str],
    cutoff: str,
    result: dict,
) -> None:
    from db.postgres import get_conn
    placeholders = ", ".join(["%s"] * len(similar))
    query = f"""
        SELECT ticker, date, pnl_percentage
        FROM   trades
        WHERE  status       = 'Closed_Loss'
          AND  ticker       IN ({placeholders})
          AND  date        >= %s
        ORDER  BY date DESC
        LIMIT  1
    """
    params = list(similar) + [cutoff]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()

    if row:
        result["blocked"]        = True
        result["similar_ticker"] = row[0]
        result["loss_date"]      = row[1]
        result["pnl_pct"]        = row[2]
        result["reason"] = (
            f"Wash-sale: {row[0]} closed at {row[2]:+.2f}% on {row[1]}; "
            f"buying {ticker} within 30 days is disallowed"
        )


def _check_sqlite(
    ticker: str,
    similar: frozenset[str],
    cutoff: str,
    result: dict,
) -> None:
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).parent.parent / "trade_journal.db"
    if not db_path.exists():
        return
    placeholders = ", ".join(["?"] * len(similar))
    query = f"""
        SELECT ticker, date, pnl_percentage
        FROM   trades
        WHERE  status  = 'Closed_Loss'
          AND  ticker  IN ({placeholders})
          AND  date   >= ?
        ORDER  BY date DESC
        LIMIT  1
    """
    params = list(similar) + [cutoff]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(query, params).fetchone()

    if row:
        result["blocked"]        = True
        result["similar_ticker"] = row["ticker"]
        result["loss_date"]      = row["date"]
        result["pnl_pct"]        = row["pnl_percentage"]
        result["reason"] = (
            f"Wash-sale: {row['ticker']} closed at {row['pnl_percentage']:+.2f}% "
            f"on {row['date']}; buying {ticker} within 30 days is disallowed"
        )
