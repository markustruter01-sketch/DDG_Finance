"""Pull research data into the BarStore. Read-only vendor calls; no orders, no DB.

Run from the repo root in the Replit workspace (needs vendor keys):
    python -m research_harness.fetch fx    --dataset oanda_fx_ba_to_2026-10-10 --to 2026-10-10T00:00:00Z
    python -m research_harness.fetch etf   --dataset etf_daily_yf_2026-10-16 --symbols SPY,TLT,GLD --start 2003-01-01 --end 2026-10-15
    python -m research_harness.fetch tbill --dataset fred_dtb3_2026-10-16 --start 2003-01-01 --end 2026-10-15
    python -m research_harness.fetch coinbase --dataset crypto_daily_cb_2026-10-22 --symbols BTC-USD,ETH-USD --start 2014-01-01 --end 2026-10-15
    python -m research_harness.fetch yahoo --dataset gear_etf_ych_2026-10-22 --symbols SPY,QQQ,SSO,QLD --start 1998-01-01 --end 2026-10-15

Locked datasets (FLEET-V1 onwards) are pulled in two commands: the open part
with --locked-from (every row must end before that date), then, separately,
the locked part with --locked (rows from that date; they land in _locked/):
    python -m research_harness.fetch fred    --dataset fleet_fred_2026-11-02 --series DTB3,DGS10 --start 1985-01-01 --end 2010-12-31 --locked-from 2011-01-01
    python -m research_harness.fetch fred    --dataset fleet_fred_2026-11-02 --series DTB3,DGS10 --start 2011-01-01 --end 2026-10-31 --locked
    python -m research_harness.fetch shiller --dataset fleet_shiller_2026-11-02 --start 1985-01-01 --end 2010-12-31 --locked-from 2011-01-01

Datasets are immutable: a new pull gets a new dataset name.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "trading-platform", ROOT / "kraken-bot"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

from research_harness.harness.store import BarStore  # noqa: E402

FX_FIELDS = ("day", "bo", "bh", "bl", "bc", "ao", "ah", "al", "ac")


def fetch_fx(store: BarStore, dataset: str, to: str) -> dict:
    from core.oanda_client import OandaClient
    from forex_baseline_backtest import bar_from_candle
    from forex_quant_desk import FOREX_PAIRS

    data = {}
    with OandaClient() as client:
        for pair in FOREX_PAIRS:
            candles = client.daily_candles_bid_ask(pair, count=4999, to=to)
            data[pair] = [bar_from_candle(c) for c in candles]
    return store.write_dataset(
        dataset, source=f"OANDA practice API daily BA candles, count=4999, to={to}",
        bars_by_symbol=data, fields=FX_FIELDS,
        notes="day = candle open date (NY 17:00 alignment), as in FX-BT1",
    )


def fetch_etf(store: BarStore, dataset: str, symbols: list[str], start: str, end: str) -> dict:
    import pandas as pd
    import yfinance as yf

    # yfinance's end date is exclusive; make --end inclusive.
    end_exclusive = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    data = {}
    for sym in symbols:
        df = yf.download(sym, start=start, end=end_exclusive, auto_adjust=True,
                         actions=False, progress=False)
        if df is None or df.empty:
            raise RuntimeError(f"no data for {sym}")
        if isinstance(df.columns, pd.MultiIndex):  # newer yfinance: (field, ticker)
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        data[sym] = [
            {"day": idx.date(), "open": r["Open"], "high": r["High"], "low": r["Low"], "close": r["Close"]}
            for idx, r in df.iterrows()
        ]
    return store.write_dataset(
        dataset, source=f"yfinance auto_adjust=True {start}..{end}", bars_by_symbol=data,
        notes=("Dividend/split-adjusted OHLC (total-return proxy). The vendor revises "
               "adjusted history, so a later pull can differ; the manifest hash pins this one."),
    )


COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/{product}/candles"
COINBASE_MAX_CANDLES = 300   # the public endpoint returns at most 300 candles per call


def parse_coinbase_candles(rows: list) -> list[dict]:
    """Coinbase rows are [time, low, high, open, close, volume], newest first,
    time = UTC epoch seconds of the day's start. Returns oldest first."""
    from datetime import datetime, timezone
    out = [{"day": datetime.fromtimestamp(int(r[0]), tz=timezone.utc).date(),
            "open": float(r[3]), "high": float(r[2]), "low": float(r[1]), "close": float(r[4])}
           for r in rows]
    return sorted({b["day"]: b for b in out}.values(), key=lambda b: b["day"])


def fetch_coinbase(store: BarStore, dataset: str, symbols: list[str], start: str, end: str,
                   http_get=None, pause: float = 0.25) -> dict:
    """Daily UTC candles from Coinbase Exchange's free public API (no key)."""
    import time as _time
    if http_get is None:
        import httpx
        http_get = httpx.get
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    data = {}
    for product in symbols:
        bars: list[dict] = []
        lo = first
        while lo <= last:
            hi = min(last, lo + timedelta(days=COINBASE_MAX_CANDLES - 1))
            resp = http_get(COINBASE_CANDLES.format(product=product),
                            params={"granularity": 86400, "start": f"{lo.isoformat()}T00:00:00Z",
                                    "end": f"{hi.isoformat()}T23:59:59Z"},
                            headers={"User-Agent": "ddg-research-harness/1.0"}, timeout=30.0)
            resp.raise_for_status()
            bars += parse_coinbase_candles(resp.json())
            lo = hi + timedelta(days=1)
            _time.sleep(pause)
        bars = [b for b in sorted({b["day"]: b for b in bars}.values(), key=lambda b: b["day"])
                if first <= b["day"] <= last]
        if not bars:
            raise RuntimeError(f"no data for {product}")
        data[product] = bars
    return store.write_dataset(
        dataset, source=f"Coinbase Exchange public candles, granularity 86400 (UTC days) {start}..{end}",
        bars_by_symbol=data,
        notes="Single-exchange daily OHLC; a product's history starts when Coinbase listed it.",
    )


YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def parse_yahoo_chart(payload: dict, first: date, last: date) -> list[dict]:
    """Daily bars from Yahoo's chart API, adjusted the way yfinance's
    auto_adjust=True does it: every price is scaled by adjclose / close, so
    dividends and splits are in the series (a total-return proxy). Days with
    any missing value are dropped. Dates are exchange-local trading days."""
    from datetime import datetime, timezone
    res = payload["chart"]["result"][0]
    offset = int(res["meta"].get("gmtoffset", 0))
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, lo, c, a = q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]
        if None in (o, h, lo, c, a) or c <= 0:
            continue
        day = datetime.fromtimestamp(ts + offset, tz=timezone.utc).date()
        if not first <= day <= last:
            continue
        f = a / c
        out.append({"day": day, "open": o * f, "high": h * f, "low": lo * f, "close": a})
    return sorted({b["day"]: b for b in out}.values(), key=lambda b: b["day"])


def fetch_yahoo_chart(store: BarStore, dataset: str, symbols: list[str], start: str, end: str,
                      http_get=None, pause: float = 0.5, **lock) -> dict:
    """Same vendor and adjustment as fetch_etf, through Yahoo's chart endpoint
    directly (the yfinance library stopped returning data in the Replit
    workspace on 22 Oct 2026 while this endpoint still answered)."""
    import time as _time
    from datetime import datetime, timezone
    if http_get is None:
        import requests
        http_get = requests.get
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    p1 = int(datetime(first.year, first.month, first.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(last.year, last.month, last.day, tzinfo=timezone.utc).timestamp()) + 2 * 86400
    data = {}
    for sym in symbols:
        resp = http_get(YAHOO_CHART.format(symbol=sym),
                        params={"period1": p1, "period2": p2, "interval": "1d",
                                "events": "div,splits", "includeAdjustedClose": "true"},
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        bars = parse_yahoo_chart(resp.json(), first, last)
        if not bars:
            raise RuntimeError(f"no data for {sym}")
        data[sym] = bars
        _time.sleep(pause)
    return store.write_dataset(
        dataset, source=f"Yahoo chart API v8, adjusted by adjclose/close (as yfinance auto_adjust=True) {start}..{end}",
        bars_by_symbol=data,
        notes=("Dividend/split-adjusted OHLC (total-return proxy). The vendor revises "
               "adjusted history, so a later pull can differ; the manifest hash pins this one. "
               "Index symbols (^...) carry no dividends: adjclose equals close."),
        **lock,
    )


def parse_fred_csv(text: str) -> list[dict]:
    """FRED's keyless CSV: header row, then 'date,value'; '.' or '' = missing."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2 or "," not in lines[0]:
        raise RuntimeError(f"unexpected FRED CSV header: {lines[:1]}")
    rows = []
    for ln in lines[1:]:
        day, value = ln.split(",")[:2]
        if value in (".", ""):
            continue
        rows.append({"day": date.fromisoformat(day), "rate": float(value) / 100})
    if not rows:
        raise RuntimeError("FRED CSV contained no observations")
    return rows


FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch_fred(store: BarStore, dataset: str, series: list[str], start: str, end: str,
               http_get=None, **lock) -> dict:
    """Percent-rate series (DTB3, DGS10, ...) from FRED's public CSV endpoint
    (no API key needed), stored as annual decimals in a 'rate' field."""
    if http_get is None:
        import httpx

        def http_get(url, params):
            return httpx.get(url, params=params, timeout=60, follow_redirects=True)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    data = {}
    for s in series:
        resp = http_get(FRED_CSV, {"id": s, "cosd": start, "coed": end})
        resp.raise_for_status()
        rows = [r for r in parse_fred_csv(resp.text) if first <= r["day"] <= last]
        if not rows:
            raise RuntimeError(f"FRED {s}: no observations in {start}..{end}")
        data[s] = rows
    return store.write_dataset(
        dataset, source=f"FRED public CSV {','.join(series)} {start}..{end}",
        bars_by_symbol=data, fields=("day", "rate"), positive_fields=(),
        notes="rate is annual, decimal (0.05 = 5%); FRED's missing days ('.') are dropped", **lock,
    )


def fetch_tbill(store: BarStore, dataset: str, start: str, end: str) -> dict:
    """DTB3 from FRED's public CSV endpoint (no API key needed)."""
    return fetch_fred(store, dataset, ["DTB3"], start, end)


SHILLER_XLS = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"


def parse_shiller_rows(rows: list[list], first: date, last: date) -> list[dict]:
    """Shiller's 'Data' sheet rows -> monthly {day (1st of month), price, dividend}.

    Column 0 is the date as a float (1987.01 = January, 1987.1 = October),
    column 1 the monthly average S&P composite price, column 2 the dividend
    (annual rate, index points). Rows without a positive price and dividend
    (headers, the latest months whose dividend is not yet published) are
    skipped."""
    out = []
    for r in rows:
        if len(r) < 3 or not isinstance(r[0], (int, float)):
            continue
        year = int(r[0])
        month = int(round((r[0] - year) * 100))
        if not 1 <= month <= 12:
            continue
        try:
            price, div = float(r[1]), float(r[2])
        except (TypeError, ValueError):
            continue
        if price <= 0 or div <= 0:
            continue
        day = date(year, month, 1)
        if first <= day <= last:
            out.append({"day": day, "price": price, "dividend": div})
    return sorted({b["day"]: b for b in out}.values(), key=lambda b: b["day"])


def fetch_shiller(store: BarStore, dataset: str, start: str, end: str, **lock) -> dict:
    """S&P composite monthly price and dividend from Robert Shiller's ie_data.xls.
    Needs the free xlrd package (pip install --no-user --target /tmp/pylib xlrd,
    then PYTHONPATH=/tmp/pylib); it is not a project dependency."""
    import tempfile

    import requests
    import xlrd

    resp = requests.get(SHILLER_XLS, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".xls") as fh:
        fh.write(resp.content)
        fh.flush()
        sheet = xlrd.open_workbook(fh.name).sheet_by_name("Data")
        rows = [sheet.row_values(i) for i in range(sheet.nrows)]
    data = parse_shiller_rows(rows, date.fromisoformat(start), date.fromisoformat(end))
    if not data:
        raise RuntimeError("Shiller: no rows in range")
    return store.write_dataset(
        dataset, source=f"Shiller ie_data.xls (econ.yale.edu) sheet Data {start}..{end}",
        bars_by_symbol={"SP500": data}, fields=("day", "price", "dividend"),
        notes="monthly; day = 1st of the month; dividend = annual rate in index points", **lock,
    )


PANEL_FIELDS = ("day", "open", "high", "low", "close", "volume")


def panel_symbols_to_keep(bars_by_symbol: dict[str, list[dict]], start: date, end: date) -> set[str]:
    """Every stock that is in MOMO-V1's universe (sleeves/momo_v1.universe_on)
    at any month's first session in [start, end]. Pruning to this set leaves
    every monthly universe exactly as it is on the full panel (a stock that is
    never in the top 500 can never be ranked or held), and keeps the dataset
    small. Uses only price, volume and history length, never returns."""
    from research_harness.sleeves import momo_v1 as mv

    panel = mv.Panel(bars_by_symbol)
    calendar = sorted({b["day"] for bs in panel.bars.values() for b in bs})
    keep: set[str] = set()
    for d in mv.month_first_sessions(calendar, start, end):
        keep.update(mv.universe_on(panel, d))
    return keep


def split_panel(bars_by_symbol: dict[str, list[dict]], keep: set[str],
                locked_from: date) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """(open rows before locked_from, locked rows from it) for every kept stock.
    A stock with no row before locked_from still gets an empty open file, so
    its locked rows can be read with a grant."""
    open_part = {s: [b for b in bars_by_symbol[s] if b["day"] < locked_from] for s in sorted(keep)}
    locked_part = {s: [b for b in bars_by_symbol[s] if b["day"] >= locked_from] for s in sorted(keep)}
    return open_part, {s: b for s, b in locked_part.items() if b}


DELISTED_CHOICES = ("include", "exclude")


def momo_candidates(records: list[dict], delisted: str) -> set[str]:
    """Stocks to read bars for. The research asset table describes TODAY:
    a stock delisted since 2018 is inactive and untradable now, so the
    platform's static gates (experiments 18-19) drop it, which biases a
    2018-2026 backtest toward survivors. ``delisted="include"`` applies
    every other gate (US ordinary equity, name and symbol structure) but not
    the gates that only describe today's listing (status, tradable, exchange).
    No default: the choice is the plan owner's and is written in the manifest."""
    from core.equity_universe import eligible_asset_records

    if delisted not in DELISTED_CHOICES:
        raise ValueError(f"delisted must be one of {DELISTED_CHOICES}")
    if delisted == "include":
        records = [{**r, "status": "active", "tradable": True, "exchange": "NYSE"} for r in records]
    eligible, _ = eligible_asset_records(records)
    return {str(r["symbol"]).upper() for r in eligible}


def fetch_momo_panel(store: BarStore, dataset: str, start: str, end: str, locked_from: str,
                     universe_from: str, delisted: str) -> dict:
    """MOMO-V1's stock panel from the research database's rank-500 panel
    (the tables and price sources of experiments 18-19), written as an open
    part (before locked_from) and a locked part in one go, with the same
    stock set. Runs where the research database is (the DDG - Finance Replit)."""
    import sys

    tp = Path(__file__).resolve().parents[1] / "trading-platform"
    if str(tp) not in sys.path:
        sys.path.insert(0, str(tp))
    from analysis.bot2_momentum_pead_v3 import load_stored_assets
    from analysis.bot2_momentum_rank500_backtest import _load_compact_panel

    first, last, lf = date.fromisoformat(start), date.fromisoformat(end), date.fromisoformat(locked_from)
    records = [{"symbol": a.symbol, "asset_class": a.asset_class, "status": a.status,
                "exchange": a.exchange, "tradable": a.tradable, "name": a.name}
               for a in load_stored_assets()]
    candidates = momo_candidates(records, delisted)
    inactive = sum(1 for r in records if str(r["status"]).lower() != "active")
    raw = _load_compact_panel(candidates, last)
    bars: dict[str, list[dict]] = {}
    for sym, series in raw.items():
        rows = []
        for b in series.bars:
            if first <= b.day <= last and b.close > 0 and b.open > 0 and b.high > 0 and b.low > 0:
                rows.append({"day": b.day, "open": float(b.open), "high": float(b.high),
                             "low": float(b.low), "close": float(b.close), "volume": float(b.volume)})
        if rows:
            bars[sym] = rows
    keep = panel_symbols_to_keep(bars, date.fromisoformat(universe_from), last)
    if not keep:
        raise RuntimeError("MOMO panel: no stock ever qualifies for the universe")
    open_part, locked_part = split_panel(bars, keep, lf)
    note = (f"rank-500 research panel; delisted={delisted} ({inactive} of {len(records)} stored assets "
            f"are inactive today); {len(candidates)} candidates; {len(bars)} with bars; {len(keep)} ever in "
            f"the top-500 universe {universe_from}..{end}. Prices as stored (alpaca_sip_adjusted preferred).")
    store.write_dataset(dataset, source=f"research panel {start}..{locked_from} (open)",
                        bars_by_symbol=open_part, fields=PANEL_FIELDS,
                        positive_fields=("open", "high", "low", "close"), notes=note, locked_from=lf)
    return store.write_dataset(dataset, source=f"research panel {locked_from}..{end} (locked)",
                               bars_by_symbol=locked_part, fields=PANEL_FIELDS,
                               positive_fields=("open", "high", "low", "close"), notes=note, locked=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("fx", "etf", "tbill", "coinbase", "yahoo", "fred", "shiller", "momo_panel"))
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--to")
    ap.add_argument("--symbols")
    ap.add_argument("--series")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--locked-from", help="open part: every row must end before this date")
    ap.add_argument("--locked", action="store_true", help="write the locked part of an open dataset")
    ap.add_argument("--universe-from", help="momo_panel: first month whose universe decides the stock set")
    ap.add_argument("--delisted", choices=DELISTED_CHOICES,
                    help="momo_panel (required): include or exclude stocks inactive today")
    a = ap.parse_args(argv)
    store = BarStore()
    lock = {"locked": True} if a.locked else (
        {"locked_from": date.fromisoformat(a.locked_from)} if a.locked_from else {})
    if a.kind == "fx":
        m = fetch_fx(store, a.dataset, a.to)
    elif a.kind == "etf":
        m = fetch_etf(store, a.dataset, a.symbols.split(","), a.start, a.end)
    elif a.kind == "yahoo":
        m = fetch_yahoo_chart(store, a.dataset, a.symbols.split(","), a.start, a.end, **lock)
    elif a.kind == "fred":
        m = fetch_fred(store, a.dataset, a.series.split(","), a.start, a.end, **lock)
    elif a.kind == "shiller":
        m = fetch_shiller(store, a.dataset, a.start, a.end, **lock)
    elif a.kind == "momo_panel":
        if not a.delisted:
            ap.error("momo_panel needs --delisted include|exclude (the plan owner's choice)")
        m = fetch_momo_panel(store, a.dataset, a.start, a.end, a.locked_from, a.universe_from, a.delisted)
        print(f"open part manifest hash: {store.manifest_hash(a.dataset)}")
        a.locked = True
    elif a.kind == "coinbase":
        m = fetch_coinbase(store, a.dataset, a.symbols.split(","), a.start, a.end)
    else:
        m = fetch_tbill(store, a.dataset, a.start, a.end)
    for sym, e in m["symbols"].items():
        print(f"{sym}: {e['rows']} rows {e['first']}..{e['last']} sha256={e['sha256'][:12]}")
    print(f"manifest hash: {store.locked_manifest_hash(a.dataset) if a.locked else store.manifest_hash(a.dataset)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
