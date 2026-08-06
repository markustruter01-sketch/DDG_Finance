"""
Phase 0 — Data Coverage Audit
Queries Alpaca SIP daily bars for every ticker in global_universe.py,
then checks Yahoo Finance for tickers that don't reach 2007.
READ-ONLY. No trades, no signals, no bots.
"""
import os, sys, time, datetime
from collections import defaultdict

# ── Universe ──────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from global_universe import ALL_TICKERS, TICKER_REGION, TEST_WINDOWS

# ── Alpaca client ──────────────────────────────────────────────────────────────
import requests

ALPACA_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA_URL = "https://data.alpaca.markets/v2"

def alpaca_bars(symbol: str, start="2000-01-01", end="2026-08-06") -> list[dict]:
    """Fetch all daily bars for a symbol via Alpaca SIP."""
    headers = {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }
    bars = []
    page_token = None
    while True:
        params = {
            "symbols": symbol,
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "limit": 10000,
            "feed": "sip",
            "adjustment": "all",
        }
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{ALPACA_DATA_URL}/stocks/bars", headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
        bars.extend(data.get("bars", {}).get(symbol, []))
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.1)
    return bars

def parse_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s[:10])

def find_gaps(dates: list[datetime.date], threshold: int = 5) -> list[tuple]:
    """Return list of (gap_start, gap_end, calendar_days) for gaps > threshold calendar days."""
    gaps = []
    for i in range(1, len(dates)):
        delta = (dates[i] - dates[i-1]).days
        if delta > threshold:
            gaps.append((dates[i-1], dates[i], delta))
    return gaps

# ── Yahoo Finance backup ───────────────────────────────────────────────────────
def yahoo_earliest(symbol: str) -> str | None:
    """Return earliest date available on Yahoo Finance, or None on failure."""
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        hist = tk.history(period="max", interval="1d", auto_adjust=True, actions=False)
        if hist.empty:
            return None
        return str(hist.index.min().date())
    except Exception:
        return None

# ── Window coverage check ──────────────────────────────────────────────────────
def window_coverage(first_bar: datetime.date) -> dict[str, str]:
    """For each test window, return 'YES', 'PARTIAL', or 'NO'."""
    result = {}
    for label, _wstart, _wend, warmup_from in TEST_WINDOWS:
        warmup_date = parse_date(warmup_from)
        if first_bar <= warmup_date:
            result[label] = "YES"
        elif first_bar <= parse_date(_wstart):
            result[label] = "PARTIAL"   # has window data but no warmup
        else:
            result[label] = "NO"
    return result

# ── Main audit ────────────────────────────────────────────────────────────────
def run_audit():
    rows = []
    print(f"\nAuditing {len(ALL_TICKERS)} tickers against Alpaca SIP…\n")

    for ticker in ALL_TICKERS:
        sys.stdout.write(f"  {ticker:<6} … ")
        sys.stdout.flush()
        bars = alpaca_bars(ticker)
        if not bars:
            print("NO DATA from Alpaca SIP")
            rows.append({
                "ticker": ticker,
                "region": TICKER_REGION.get(ticker, "?"),
                "first_bar": None,
                "last_bar": None,
                "days": 0,
                "gaps": [],
                "usable_from": None,
                "alpaca_ok": False,
            })
            continue

        dates = sorted(parse_date(b["t"]) for b in bars)
        gaps  = find_gaps(dates)
        first = dates[0]
        last  = dates[-1]
        # usable_from: first clean date after any significant early gap
        usable_from = first
        for gap_start, gap_end, _ in gaps:
            if gap_end < parse_date("2005-01-01"):
                usable_from = gap_end  # fast-forward past early halts

        gap_summary = "; ".join(f"{g[0]}→{g[1]} ({g[2]}d)" for g in gaps[:5])
        gap_flag = "YES" if gaps else "none"

        print(f"{first}  →  {last}  ({len(dates)} days)  gaps: {len(gaps)}")
        rows.append({
            "ticker": ticker,
            "region": TICKER_REGION.get(ticker, "?"),
            "first_bar": first,
            "last_bar": last,
            "days": len(dates),
            "gaps": gaps,
            "gap_summary": gap_summary,
            "usable_from": usable_from,
            "alpaca_ok": True,
        })
        time.sleep(0.15)  # rate-limit

    # ── Step 3: Yahoo backup for tickers that don't reach 2007 ────────────────
    CUTOFF = datetime.date(2007, 1, 1)
    needs_backup = [r for r in rows if not r["alpaca_ok"] or (r["first_bar"] and r["first_bar"] > CUTOFF)]

    yahoo_results = {}
    if needs_backup:
        print(f"\nChecking Yahoo Finance backup for {len(needs_backup)} tickers that don't reach 2007…")
        for r in needs_backup:
            tk = r["ticker"]
            sys.stdout.write(f"  {tk:<6} … ")
            sys.stdout.flush()
            earliest = yahoo_earliest(tk)
            yahoo_results[tk] = earliest
            print(f"Yahoo earliest: {earliest}")
            time.sleep(0.5)

    # ── Print coverage table ──────────────────────────────────────────────────
    print("\n" + "═"*100)
    print("STEP 2 — ALPACA SIP COVERAGE TABLE")
    print("═"*100)
    hdr = f"{'Ticker':<6}  {'Region':<14}  {'First Bar':<12}  {'Last Bar':<12}  {'Days':>5}  {'Gaps?':<6}  {'Usable From':<12}  Yahoo Earliest"
    print(hdr)
    print("─"*len(hdr))
    for r in rows:
        fb   = str(r["first_bar"])  if r["first_bar"]  else "N/A"
        lb   = str(r["last_bar"])   if r["last_bar"]   else "N/A"
        uf   = str(r["usable_from"]) if r["usable_from"] else "N/A"
        gaps = "YES" if r.get("gaps") else ("none" if r["alpaca_ok"] else "NO DATA")
        yh   = yahoo_results.get(r["ticker"], "—")
        print(f"{r['ticker']:<6}  {r['region']:<14}  {fb:<12}  {lb:<12}  {r['days']:>5}  {gaps:<6}  {uf:<12}  {yh}")

    # ── Print window-coverage matrix ──────────────────────────────────────────
    window_labels = [w[0] for w in TEST_WINDOWS]
    print("\n" + "═"*100)
    print("STEP 2b — WINDOW COVERAGE MATRIX (YES = has 1yr warmup + full window | PARTIAL = window only | NO = missing)")
    print("═"*100)
    col_w = 22
    header = f"{'Ticker':<6}  " + "  ".join(f"{lbl[:col_w]:<{col_w}}" for lbl in window_labels)
    print(header)
    print("─"*len(header))
    for r in rows:
        if not r["first_bar"]:
            coverage = {lbl: "NO DATA" for lbl, *_ in TEST_WINDOWS}
        else:
            coverage = window_coverage(r["first_bar"])
        row = f"{r['ticker']:<6}  " + "  ".join(f"{coverage[lbl]:<{col_w}}" for lbl, *_ in TEST_WINDOWS)
        print(row)

    # ── Step 3 summary ────────────────────────────────────────────────────────
    print("\n" + "═"*100)
    print("STEP 3 — PUBLIC BACKUP AVAILABILITY")
    print("═"*100)
    if not yahoo_results:
        print("All tickers reach back to 2007 on Alpaca SIP — no backup needed.")
    else:
        for tk, earliest in yahoo_results.items():
            alpaca_first = next((str(r["first_bar"]) for r in rows if r["ticker"] == tk), "N/A")
            best = earliest if earliest and (alpaca_first == "N/A" or earliest < alpaca_first) else alpaca_first
            print(f"  {tk:<6}: Alpaca={alpaca_first}  Yahoo={earliest or 'unavailable'}  → best: {best}")

    # ── Verdict ───────────────────────────────────────────────────────────────
    print("\n" + "═"*100)
    print("VERDICT")
    print("═"*100)
    # Can any ticker cover 2008 GFC window (warmup from 2007-01-01)?
    can_do_gfc = [r["ticker"] for r in rows if r["first_bar"] and r["first_bar"] <= datetime.date(2007, 1, 1)]
    can_do_em_bear = [r["ticker"] for r in rows if r["first_bar"] and r["first_bar"] <= datetime.date(2014, 1, 1)]
    limited = [r["ticker"] for r in rows if not r["first_bar"] or r["first_bar"] > datetime.date(2007, 1, 1)]

    if not limited:
        print("✅ FULL MULTI-CYCLE BACKTEST POSSIBLE: all tickers cover 2007+ (GFC + full EM bear).")
    elif can_do_em_bear and len(can_do_em_bear) >= len(ALL_TICKERS) * 0.7:
        print(f"⚠️  PARTIAL: {len(can_do_em_bear)}/{len(ALL_TICKERS)} tickers cover the 2015-16 EM bear window.")
        print(f"   Limited tickers (post-2007 data only): {limited}")
        print(f"   → Multi-cycle test IS possible for the subset that covers 2007+.")
        print(f"   → Tickers below the cutoff are limited to 2018-2024 windows only.")
    else:
        print(f"❌ LIMITED: only {len(can_do_gfc)} tickers cover the 2008 GFC window.")
        print(f"   The honest backtest window for this universe is 2018-2024 only.")
        print(f"   That CANNOT include a full EM bear cycle — interpret results with caution.")

    print("\n  Tickers with pre-2007 Alpaca data:", can_do_gfc if can_do_gfc else "none")
    print("  Tickers needing Yahoo or limited to post-2018:", limited if limited else "none")
    print()

if __name__ == "__main__":
    run_audit()
