"""Pull research data into the BarStore. Read-only vendor calls; no orders, no DB.

Run from the repo root in the Replit workspace (needs vendor keys):
    python -m research_harness.fetch fx    --dataset oanda_fx_ba_to_2026-10-10 --to 2026-10-10T00:00:00Z
    python -m research_harness.fetch etf   --dataset etf_daily_yf_2026-10-16 --symbols SPY,TLT,GLD --start 2003-01-01 --end 2026-10-15
    python -m research_harness.fetch tbill --dataset fred_dtb3_2026-10-16 --start 2003-01-01 --end 2026-10-15

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


def fetch_tbill(store: BarStore, dataset: str, start: str, end: str) -> dict:
    """DTB3 from FRED's public CSV endpoint (no API key needed)."""
    import httpx

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    resp = httpx.get(url, params={"id": "DTB3", "cosd": start, "coed": end},
                     timeout=60, follow_redirects=True)
    resp.raise_for_status()
    rows = [r for r in parse_fred_csv(resp.text)
            if date.fromisoformat(start) <= r["day"] <= date.fromisoformat(end)]
    return store.write_dataset(
        dataset, source=f"FRED DTB3 public CSV (3-month T-bill, secondary market, discount basis) {start}..{end}",
        bars_by_symbol={"DTB3": rows}, fields=("day", "rate"), positive_fields=(),
        notes="rate is annual, decimal (0.05 = 5%)",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("fx", "etf", "tbill"))
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--to")
    ap.add_argument("--symbols")
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args(argv)
    store = BarStore()
    if a.kind == "fx":
        m = fetch_fx(store, a.dataset, a.to)
    elif a.kind == "etf":
        m = fetch_etf(store, a.dataset, a.symbols.split(","), a.start, a.end)
    else:
        m = fetch_tbill(store, a.dataset, a.start, a.end)
    for sym, e in m["symbols"].items():
        print(f"{sym}: {e['rows']} rows {e['first']}..{e['last']} sha256={e['sha256'][:12]}")
    print(f"manifest hash: {store.manifest_hash(a.dataset)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
