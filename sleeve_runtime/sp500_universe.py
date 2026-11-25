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
from html.parser import HTMLParser
from typing import Callable

SSGA_URL = ("https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/"
            "etfs/us/holdings-daily-us-en-spy.xlsx")
IVV_URL = ("https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/1467271812596.ajax"
           "?fileType=csv&fileName=IVV_holdings&dataType=fund")
# Sectors only (the Shadow League's sector cap), tried when the holdings files carry none:
# 20 Nov 2026 SSGA wrote "-" in every Sector cell and the IVV link returned a web page, not a CSV.
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
GICS_SECTORS = {"Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy", "Financials",
                "Health Care", "Industrials", "Information Technology", "Materials", "Real Estate", "Utilities"}
NO_SECTOR = {"", "-", "--", "—", "N/A"}   # placeholders, not sectors
MIN_SECTOR_SHARE = 0.9                  # below this, the sector list is treated as unavailable
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
    out = {t: by_ticker.get(t, "") for t in tickers}
    return {t: ("" if s in NO_SECTOR else s) for t, s in out.items()}   # SSGA writes "-" in every row


def sector_share(by_ticker: dict[str, str]) -> float:
    """Share of members with a real sector (0 when there are none)."""
    return sum(1 for s in by_ticker.values() if s) / len(by_ticker) if by_ticker else 0.0


def load_ivv_sectors(http_get: Callable[[str], bytes],
                     tickers: list[str]) -> dict[str, str]:
    """Sectors for ``tickers`` from the iShares IVV holdings file."""
    return sectors(parse_ivv_csv(http_get(IVV_URL).decode("utf-8-sig")), tickers)


class _WikiTable(HTMLParser):
    """Cells of the table with id="constituents" (Symbol, Security, GICS Sector, ...)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._depth = 0          # >0 while inside the constituents table
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and (self._depth or dict(attrs).get("id") == "constituents"):
            self._depth += 1
        elif self._depth == 1 and tag == "tr":
            self.rows.append([])
        elif self._depth == 1 and tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self._depth:
            self._depth -= 1
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None and self.rows:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_wikipedia_details(html: str) -> dict[str, dict[str, str]]:
    """{ticker: {"name", "sector", "industry"}} from Wikipedia's S&P 500 list (Security,
    GICS Sector, GICS Sub-Industry). Tickers in Alpaca's dot form (BRK.B). A sector outside
    the 11 GICS names counts as no sector (''); a missing column gives ''."""
    p = _WikiTable()
    p.feed(html)
    if not p.rows:
        return {}
    head = p.rows[0]
    if "Symbol" not in head or "GICS Sector" not in head:
        return {}
    i_sym, i_sec = head.index("Symbol"), head.index("GICS Sector")
    i_name = head.index("Security") if "Security" in head else None
    i_ind = head.index("GICS Sub-Industry") if "GICS Sub-Industry" in head else None
    cell = lambda r, i: r[i] if i is not None and i < len(r) else ""
    out = {}
    for r in p.rows[1:]:
        if len(r) > max(i_sym, i_sec):
            out[r[i_sym].replace("-", ".").strip()] = {
                "name": cell(r, i_name), "sector": r[i_sec] if r[i_sec] in GICS_SECTORS else "",
                "industry": cell(r, i_ind)}
    return out


def parse_wikipedia_sectors(html: str) -> dict[str, str]:
    """{ticker: GICS sector} from Wikipedia's S&P 500 list. Tickers in Alpaca's dot form (BRK.B).
    Only the 11 GICS sector names are kept; anything else counts as no sector."""
    return {t: d["sector"] for t, d in parse_wikipedia_details(html).items() if d["sector"]}


def load_wikipedia_details(http_get: Callable[[str], bytes]) -> dict[str, dict[str, str]]:
    return parse_wikipedia_details(http_get(WIKI_SP500_URL).decode("utf-8", "replace"))


def load_wikipedia_sectors(http_get: Callable[[str], bytes], tickers: list[str]) -> dict[str, str]:
    by_ticker = parse_wikipedia_sectors(http_get(WIKI_SP500_URL).decode("utf-8", "replace"))
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
