"""MOMO-V2's universe: the S&P 500's current members (research_harness/explore/MOMO-V2-PLAN.md, rule 1).

Declared sources, in order:
1. State Street's SPY holdings file (xlsx, published daily).
2. Fallback: iShares' IVV holdings file (csv).
Common stock only, one share class per company (the larger index weight).
Fails loud: if neither source yields a plausible list (>= MIN_MEMBERS names),
UniverseUnavailable is raised and the caller trades nothing.

Pure parsing functions take bytes/text so they are testable offline; the
network call is injected (``http_get(url) -> bytes``).
"""

from __future__ import annotations

import csv
import io
import re
from typing import Callable

SSGA_URL = ("https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/"
            "etfs/us/holdings-daily-us-en-spy.xlsx")
IVV_URL = ("https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/1467271812596.ajax"
           "?fileType=csv&fileName=IVV_holdings&dataType=fund")
MIN_MEMBERS = 450                      # the index has ~503 lines; fewer means a broken file
TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
# iShares writes share-class tickers without the dot; Alpaca uses the dot form.
IVV_TICKER_FIX = {"BRKB": "BRK.B", "BFB": "BF.B"}
_CLASS_SUFFIX = re.compile(r"\s+(CLASS|CL)\s+[A-Z]$")

Row = dict  # {"ticker": str, "name": str, "weight": float}


class UniverseUnavailable(RuntimeError):
    """Neither declared source produced a usable S&P 500 member list."""


def _company_key(name: str) -> str:
    n = re.sub(r"[^A-Z0-9 ]", " ", name.upper())
    n = re.sub(r"\s+", " ", n).strip()
    return _CLASS_SUFFIX.sub("", n)


def _weight(value) -> float:
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _table(rows: list[list], *, ticker_col: str, name_col: str, weight_col: str,
           asset_col: str | None = None, sector_col: str | None = None) -> list[Row]:
    """Rows after the header line that holds the named columns."""
    header_at = next((i for i, r in enumerate(rows)
                      if r and ticker_col in [str(c).strip() for c in r]
                      and name_col in [str(c).strip() for c in r]), None)
    if header_at is None:
        return []
    head = [str(c).strip() for c in rows[header_at]]
    ti, ni, wi = head.index(ticker_col), head.index(name_col), head.index(weight_col)
    ai = head.index(asset_col) if asset_col and asset_col in head else None
    si = head.index(sector_col) if sector_col and sector_col in head else None
    out = []
    for r in rows[header_at + 1:]:
        if len(r) <= max(ti, ni, wi):
            continue
        if ai is not None and str(r[ai]).strip().lower() != "equity":
            continue
        row = {"ticker": str(r[ti] or "").strip().upper(), "name": str(r[ni] or "").strip(),
               "weight": _weight(r[wi])}
        if si is not None and len(r) > si:
            row["sector"] = str(r[si] or "").strip()
        out.append(row)
    return out


def parse_ssga_xlsx(content: bytes) -> list[Row]:
    from openpyxl import load_workbook              # Replit has it with pandas; else the fallback runs

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return _table(rows, ticker_col="Ticker", name_col="Name", weight_col="Weight", sector_col="Sector")


def parse_ivv_csv(text: str) -> list[Row]:
    rows = list(csv.reader(io.StringIO(text)))
    out = _table(rows, ticker_col="Ticker", name_col="Name", weight_col="Weight (%)", asset_col="Asset Class",
                 sector_col="Sector")
    for r in out:
        r["ticker"] = IVV_TICKER_FIX.get(r["ticker"], r["ticker"])
    return out


def members(rows: list[Row]) -> list[str]:
    """Tickers of common stocks, one share class per company (the heavier one)."""
    best: dict[str, Row] = {}
    for r in rows:
        if not TICKER_RE.match(r["ticker"]) or r["weight"] <= 0:
            continue
        key = _company_key(r["name"]) or r["ticker"]
        if key not in best or r["weight"] > best[key]["weight"]:
            best[key] = r
    return sorted(r["ticker"] for r in best.values())


def sectors(rows: list[Row], tickers: list[str]) -> dict[str, str]:
    """Each member's sector as the holdings file states it ('' if the file has none).
    Used by the Shadow League's sector cap; MOMO-V2 does not read it."""
    by_ticker = {r["ticker"]: r.get("sector", "") for r in rows}
    return {t: by_ticker.get(t, "") for t in tickers}


def load_sp500_rows(http_get: Callable[[str], bytes]) -> tuple[list[str], list[Row], str]:
    """(tickers, raw rows, source). Tries SSGA, then IVV; raises UniverseUnavailable."""
    errors = []
    for source, url, parse in (("ssga_spy", SSGA_URL, parse_ssga_xlsx),
                               ("ishares_ivv", IVV_URL, lambda b: parse_ivv_csv(b.decode("utf-8-sig")))):
        try:
            rows = parse(http_get(url))
            tickers = members(rows)
        except Exception as exc:                     # any failure moves to the next source
            errors.append(f"{source}: {type(exc).__name__}: {exc}"[:200])
            continue
        if len(tickers) >= MIN_MEMBERS:
            return tickers, rows, source
        errors.append(f"{source}: only {len(tickers)} members")
    raise UniverseUnavailable("; ".join(errors))


def load_sp500(http_get: Callable[[str], bytes]) -> tuple[list[str], str]:
    """(tickers, source). Tries SSGA, then IVV; raises UniverseUnavailable."""
    tickers, _rows, source = load_sp500_rows(http_get)
    return tickers, source
