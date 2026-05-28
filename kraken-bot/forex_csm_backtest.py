#!/usr/bin/env python3
"""
forex_csm_backtest.py — Cross-Sectional Momentum (CSM) Backtest
================================================================
Based on Menkhoff, Sarno, Schmeling, Schrimpf (2012).
"Currency Momentum Strategies" — Journal of Financial Economics.

Mechanism:
  Monthly rebalance on first trading day of each month.
  Rank 7 G10 pairs by formation-period return (normalised vs USD).
  Long top 3, short bottom 3, skip middle 1.
  Equal-weight: equity / 6 per position.
  Hold for full calendar month. No stops, no intra-month exits.

NOT the EMA/ADX/ATR strategy. No indicators of any kind.
"""

import math
from datetime import datetime, timezone
from typing import Optional

# ── Universe ───────────────────────────────────────────────────────────────────
PAIRS       = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X", "JPY=X", "CAD=X", "CHF=X"]
COUNTER_USD = {"EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X"}
BASE_USD    = {"JPY=X", "CAD=X", "CHF=X"}

SIM_START       = "2024-01-01"
SIM_END         = "2026-05-01"
STARTING_EQUITY = 100_000.0

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# ── Data fetch ─────────────────────────────────────────────────────────────────
def _fetch_daily_ohlcv(ticker: str, days: int = 900) -> Optional[list]:
    import requests
    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{days}d", "interval": "1d"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=20)
        if resp.status_code != 200:
            return None
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        r          = result[0]
        timestamps = r.get("timestamp", [])
        quotes     = r.get("indicators", {}).get("quote", [{}])[0]
        rows = []
        for ts, c in zip(timestamps, quotes.get("close", [])):
            if c is None:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append({"date": dt, "close": float(c)})
        return rows or None
    except Exception as exc:
        print(f"  [WARN] Yahoo fetch failed for {ticker}: {exc}")
        return None

# ── Return normalisation (vs USD) ──────────────────────────────────────────────
def return_vs_usd(pair: str, price_now: float, price_formation_ago: float) -> float:
    """
    Return normalised to 'how much did this CURRENCY strengthen vs USD'.
    For counter_usd (EURUSD etc.): rising = currency strengthening → positive.
    For base_usd (JPY=X etc.):     rising = USD strengthening      → INVERT.
    """
    raw = (price_now / price_formation_ago) - 1.0
    return -raw if pair in BASE_USD else raw

# ── P&L for one position ───────────────────────────────────────────────────────
def position_pnl(pair: str, direction: str,
                 entry_price: float, exit_price: float,
                 position_usd: float) -> float:
    """
    direction = 'long'  → bet this currency strengthens vs USD
    direction = 'short' → bet this currency weakens   vs USD

    For counter_usd: long = long ticker; short = short ticker.
    For base_usd:    long = short ticker (you profit if ticker falls);
                     short = long ticker  (you profit if ticker rises).
    """
    if pair in COUNTER_USD:
        currency_return = (exit_price - entry_price) / entry_price
    else:
        # "long JPY" profits when JPY=X (USD/JPY) falls
        currency_return = (entry_price - exit_price) / entry_price

    signed_return = currency_return if direction == "long" else -currency_return
    return position_usd * signed_return

# ── Identify first trading day of each month ───────────────────────────────────
def _first_trading_days(all_dates: list[str]) -> list[str]:
    """Return the first available trading date in each calendar month."""
    seen_months = set()
    result      = []
    for d in sorted(all_dates):
        ym = d[:7]  # "YYYY-MM"
        if ym not in seen_months:
            seen_months.add(ym)
            result.append(d)
    return result

# ── Core backtest ──────────────────────────────────────────────────────────────
def run_csm_backtest(
    pair_data:      dict,
    formation_days: int   = 21,
    n_long:         int   = 3,
    n_short:        int   = 3,
    rebalance_freq: str   = "monthly",   # "monthly" or "biweekly"
    label:          str   = "PRIMARY",
) -> dict:
    """
    Execute one configuration of the CSM strategy.

    pair_data: dict[pair] = list of {date, close} rows (already fetched).
    """

    # Build per-pair price lookup: date → close
    price_lookup = {}
    all_dates    = set()
    for pair, rows in pair_data.items():
        price_lookup[pair] = {}
        for r in rows:
            price_lookup[pair][r["date"]] = r["close"]
            all_dates.add(r["date"])

    # Sim date universe (dates present for ALL 7 pairs)
    sim_dates = sorted(
        d for d in all_dates
        if SIM_START <= d <= SIM_END
        and all(d in price_lookup[p] for p in PAIRS if p in pair_data)
    )

    if not sim_dates:
        print(f"  [{label}] ERROR: No valid dates. Aborting.")
        return {}

    # Rebalance schedule
    if rebalance_freq == "monthly":
        rebalance_days = [d for d in _first_trading_days(sim_dates)
                          if SIM_START <= d <= SIM_END]
    else:  # biweekly — every ~10 trading days
        rebalance_days = []
        last = None
        for d in sim_dates:
            if last is None or len([x for x in sim_dates if last < x <= d]) >= 10:
                rebalance_days.append(d)
                last = d

    # ── Main simulation loop ───────────────────────────────────────────────────
    equity    = STARTING_EQUITY
    positions = {}   # pair → {direction, entry_price, position_usd}

    rebalance_records = []
    daily_equity      = []   # (date, equity) for Sharpe/DD

    prev_rb_date = None

    for rb_date in rebalance_days:
        # ── Step 1: Close all open positions at today's close ──────────────
        realized_pnl = 0.0
        pair_contributions_this_rb = {}
        for pair, pos in positions.items():
            exit_px = price_lookup.get(pair, {}).get(rb_date)
            if exit_px is None:
                continue
            pnl = position_pnl(pair, pos["direction"],
                               pos["entry_price"], exit_px,
                               pos["position_usd"])
            equity               += pnl
            realized_pnl         += pnl
            pair_contributions_this_rb[pair] = round(pnl, 2)

        if prev_rb_date is not None:
            rebalance_records.append({
                "date":         rb_date,
                "net_pnl":      round(realized_pnl, 2),
                "equity_after": round(equity, 2),
                "positions_closed": dict(positions),
                "pair_pnl":     pair_contributions_this_rb,
            })

        # ── Step 2: Rank all pairs by formation-period return ──────────────
        returns = {}
        for pair in PAIRS:
            pl = price_lookup.get(pair, {})
            price_now = pl.get(rb_date)
            # Find price ~formation_days trading days ago
            past_dates = [d for d in sorted(pl.keys()) if d < rb_date]
            if len(past_dates) < formation_days or price_now is None:
                returns[pair] = None
                continue
            price_ago = pl[past_dates[-formation_days]]
            returns[pair] = return_vs_usd(pair, price_now, price_ago)

        # Drop pairs with missing data
        valid_pairs = [(p, r) for p, r in returns.items() if r is not None]
        valid_pairs.sort(key=lambda x: x[1], reverse=True)  # highest first

        if len(valid_pairs) < n_long + n_short + 1:
            positions = {}
            prev_rb_date = rb_date
            continue

        long_pairs  = [p for p, _ in valid_pairs[:n_long]]
        short_pairs = [p for p, _ in valid_pairs[-(n_short):]]
        # middle pair(s) get no position

        # ── Step 3: Open new positions ─────────────────────────────────────
        n_positions  = n_long + n_short
        position_usd = equity / n_positions

        positions = {}
        for pair in long_pairs:
            px = price_lookup.get(pair, {}).get(rb_date)
            if px is None:
                continue
            positions[pair] = {
                "direction":    "long",
                "entry_price":  px,
                "position_usd": position_usd,
                "rank_return":  returns[pair],
            }
        for pair in short_pairs:
            px = price_lookup.get(pair, {}).get(rb_date)
            if px is None:
                continue
            positions[pair] = {
                "direction":    "short",
                "entry_price":  px,
                "position_usd": position_usd,
                "rank_return":  returns[pair],
            }

        prev_rb_date = rb_date

    # ── Force-close remaining positions at sim end ─────────────────────────
    final_date = sim_dates[-1]
    final_pnl  = 0.0
    for pair, pos in positions.items():
        exit_px = price_lookup.get(pair, {}).get(final_date)
        if exit_px is None:
            continue
        pnl       = position_pnl(pair, pos["direction"],
                                 pos["entry_price"], exit_px,
                                 pos["position_usd"])
        equity   += pnl
        final_pnl += pnl
    if positions:
        rebalance_records.append({
            "date":         final_date,
            "net_pnl":      round(final_pnl, 2),
            "equity_after": round(equity, 2),
            "positions_closed": dict(positions),
            "pair_pnl":     {},
        })

    # ── Build daily equity curve (for Sharpe / max-DD) ────────────────────
    running = STARTING_EQUITY
    rebalance_idx   = 0
    daily_returns_l = []

    rb_dates_sorted = [r["date"] for r in rebalance_records]

    open_positions = {}  # approximate daily mark using last rebalance state

    rb_open = {}   # pair → {direction, entry_price, position_usd, rb_date}
    rb_ptr  = 0

    # Reconstruct which positions were open on each day
    # (we replay the rebalance log)
    rb_log = []  # (open_date, close_date, positions_dict)
    rb_dates_all = rebalance_days
    for i, rb in enumerate(rb_dates_all[:-1]):
        close_d = rb_dates_all[i + 1]
        rb_log.append((rb, close_d))
    if rb_dates_all:
        rb_log.append((rb_dates_all[-1], final_date))

    # Rebuild positions per rebalance period for daily curve
    # (reconstruct from scratch — simpler than tracking in the main loop)
    daily_equity_curve = []
    eq2 = STARTING_EQUITY

    for open_d, close_d in rb_log:
        # Find what positions were opened on open_d
        returns2 = {}
        for pair in PAIRS:
            pl = price_lookup.get(pair, {})
            pn = pl.get(open_d)
            past = [d for d in sorted(pl.keys()) if d < open_d]
            if len(past) < formation_days or pn is None:
                returns2[pair] = None
                continue
            returns2[pair] = return_vs_usd(pair, pn, pl[past[-formation_days]])
        valid2 = [(p, r) for p, r in returns2.items() if r is not None]
        valid2.sort(key=lambda x: x[1], reverse=True)
        if len(valid2) < n_long + n_short + 1:
            continue

        lp2  = [p for p, _ in valid2[:n_long]]
        sp2  = [p for p, _ in valid2[-(n_short):]]
        pos2 = {}
        pu2  = eq2 / (n_long + n_short)
        for p in lp2:
            px = price_lookup.get(p, {}).get(open_d)
            if px: pos2[p] = {"direction": "long",  "entry": px, "pos_usd": pu2}
        for p in sp2:
            px = price_lookup.get(p, {}).get(open_d)
            if px: pos2[p] = {"direction": "short", "entry": px, "pos_usd": pu2}

        period_dates = [d for d in sim_dates if open_d < d <= close_d]
        prev_eq      = eq2

        for d in period_dates:
            port_val = eq2  # start with cash/equity
            unrealized = 0.0
            for pair, p in pos2.items():
                cur_px = price_lookup.get(pair, {}).get(d)
                if cur_px is None:
                    continue
                upnl = position_pnl(pair, p["direction"],
                                    p["entry"], cur_px, p["pos_usd"])
                unrealized += upnl
            total = eq2 + unrealized
            daily_equity_curve.append((d, total))
            daily_returns_l.append((total - prev_eq) / prev_eq if prev_eq else 0)
            prev_eq = total

        # Realise: compute end-of-period equity
        for pair, p in pos2.items():
            exit_px = price_lookup.get(pair, {}).get(close_d)
            if exit_px is None:
                continue
            eq2 += position_pnl(pair, p["direction"],
                                 p["entry"], exit_px, p["pos_usd"])

    final_equity = equity  # from the main simulation loop

    # ── Metrics ───────────────────────────────────────────────────────────
    n_rb    = len(rebalance_records)
    winners = [r for r in rebalance_records if r["net_pnl"] > 0]
    win_rate = len(winners) / n_rb * 100 if n_rb else 0
    avg_pnl  = sum(r["net_pnl"] for r in rebalance_records) / n_rb if n_rb else 0
    total_ret = (final_equity - STARTING_EQUITY) / STARTING_EQUITY * 100

    # Sharpe from daily returns
    if daily_returns_l:
        mu  = sum(daily_returns_l) / len(daily_returns_l)
        var = sum((r - mu) ** 2 for r in daily_returns_l) / len(daily_returns_l)
        std = math.sqrt(var) if var > 0 else 1e-9
        sharpe = (mu / std) * math.sqrt(252)
    else:
        sharpe = 0.0

    # Max drawdown
    peak = STARTING_EQUITY; dd = 0.0
    eq_run = STARTING_EQUITY
    for _, eq_v in daily_equity_curve:
        peak   = max(peak, eq_v)
        dd     = max(dd, (peak - eq_v) / peak if peak > 0 else 0)

    # Per-pair stats
    pair_stats = {p: {"long": 0, "short": 0, "skip": 0, "net_pnl": 0.0}
                  for p in PAIRS}
    for rb in rebalance_records:
        for pair, pos in rb.get("positions_closed", {}).items():
            d = pos.get("direction", pos.get("direction", "?"))
            if d in ("long", "short"):
                pair_stats[pair][d] += 1
            pnl_v = rb["pair_pnl"].get(pair, 0)
            pair_stats[pair]["net_pnl"] += pnl_v
    for p in PAIRS:
        appeared = pair_stats[p]["long"] + pair_stats[p]["short"]
        pair_stats[p]["skip"] = n_rb - appeared

    return {
        "label":         label,
        "formation":     formation_days,
        "rebalances":    n_rb,
        "final_equity":  final_equity,
        "total_ret":     total_ret,
        "sharpe":        sharpe,
        "max_dd":        dd,
        "win_rate":      win_rate,
        "avg_pnl":       avg_pnl,
        "rebalance_recs": rebalance_records,
        "pair_stats":    pair_stats,
        "daily_curve":   daily_equity_curve,
        "go":            (sharpe >= 0.5 and dd <= 0.20 and
                          total_ret > 0 and n_rb >= 20),
    }

# ── Pretty-print ───────────────────────────────────────────────────────────────
def print_results(res: dict, print_rebalances: bool = False) -> None:
    label     = res["label"]
    formation = res["formation"]
    n_rb      = res["rebalances"]
    eq        = res["final_equity"]
    ret       = res["total_ret"]
    sharpe    = res["sharpe"]
    dd        = res["max_dd"]
    wr        = res["win_rate"]
    avg_pnl   = res["avg_pnl"]

    ok_sharpe = sharpe >= 0.5
    ok_dd     = dd <= 0.20
    ok_ret    = ret > 0
    ok_rb     = n_rb >= 20
    go        = res["go"]

    print(f"\n{'='*72}")
    print(f"  {label}  (formation={formation}d)")
    print(f"{'='*72}")
    print(f"  {'Final equity':<32} ${eq:>12,.2f}")
    print(f"  {'Total return':<32} {ret:>12.2f}%")
    print(f"  {'Sharpe (annualised)':<32} {sharpe:>12.2f}  {'PASS' if ok_sharpe else 'FAIL'}")
    print(f"  {'Max drawdown':<32} {dd*100:>12.2f}%  {'PASS' if ok_dd else 'FAIL'}")
    print(f"  {'Monthly win rate':<32} {wr:>12.1f}%  (winning months: {int(wr*n_rb/100)}/{n_rb})")
    print(f"  {'Avg P&L per rebalance':<32} ${avg_pnl:>12,.2f}")
    print(f"  {'Total rebalances':<32} {n_rb:>12d}  {'PASS' if ok_rb else 'FAIL'}")
    print(f"  {'Total return > 0':<32} {'YES' if ok_ret else 'NO':>12s}  {'PASS' if ok_ret else 'FAIL'}")
    print(f"\n  VERDICT: {'*** GO ***' if go else 'NO-GO'}")

    # Per-pair stats
    print(f"\n  PER-PAIR CONTRIBUTION")
    print(f"  {'Pair':<12} {'Long':>6} {'Short':>6} {'Skip':>6} {'Net P&L':>12}")
    print(f"  {'-'*48}")
    for pair in PAIRS:
        ps = res["pair_stats"][pair]
        print(f"  {pair:<12} {ps['long']:>6d} {ps['short']:>6d} {ps['skip']:>6d} ${ps['net_pnl']:>11,.2f}")

    if print_rebalances:
        print(f"\n  PER-REBALANCE BREAKDOWN")
        print(f"  {'Date':<12} {'Net P&L':>10} {'Equity After':>14}")
        print(f"  {'-'*40}")
        for rb in res["rebalance_recs"]:
            pos_closed = rb.get("positions_closed", {})
            longs  = [p for p, v in pos_closed.items()
                      if v.get("direction") == "long"]
            shorts = [p for p, v in pos_closed.items()
                      if v.get("direction") == "short"]
            lstr   = ",".join(p.replace("=X","").replace("USD","") for p in longs) or "—"
            sstr   = ",".join(p.replace("=X","").replace("USD","") for p in shorts) or "—"
            sign   = "▲" if rb["net_pnl"] > 0 else "▼"
            print(f"  {rb['date']:<12} {sign}${rb['net_pnl']:>9,.0f}  ${rb['equity_after']:>12,.0f}"
                  f"   L:[{lstr:<18}] S:[{sstr}]")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("  FOREX CROSS-SECTIONAL MOMENTUM — 28-Month Backtest")
    print("  Based on Menkhoff, Sarno, Schmeling, Schrimpf (2012)")
    print("=" * 72)
    print()

    # ── Fetch data ─────────────────────────────────────────────────────────
    print("  Fetching daily data from Yahoo Finance...")
    pair_data = {}
    for pair in PAIRS:
        print(f"    {pair}...", end=" ", flush=True)
        rows = _fetch_daily_ohlcv(pair, days=900)
        if rows:
            pair_data[pair] = rows
            print(f"{len(rows)} bars  [{rows[0]['date']} → {rows[-1]['date']}]")
        else:
            print("FAILED")

    if len(pair_data) < len(PAIRS):
        missing = [p for p in PAIRS if p not in pair_data]
        print(f"\n  ERROR: Missing data for: {missing}. Aborting.")
        return

    print()

    # ── Verify return_vs_usd logic (paste-able verification block) ────────
    # (This is the block the spec asked to confirm.)
    print("  RETURN_VS_USD VERIFICATION BLOCK:")
    print("  ─────────────────────────────────────────────────────────────")
    print("  def return_vs_usd(pair, price_now, price_formation_ago):")
    print("    raw = (price_now / price_formation_ago) - 1.0")
    print("    return -raw if pair in BASE_USD else raw")
    print()
    print("  BASE_USD  = {JPY=X, CAD=X, CHF=X}   ← returns inverted")
    print("  COUNTER_USD = {EURUSD=X, GBPUSD=X, AUDUSD=X, NZDUSD=X}")
    print()
    print("  Example: JPY=X rises 2% (USD strengthened by 2%)")
    print("    raw = +0.02; return_vs_usd = -0.02  (JPY weakened, correct)")
    print("  Example: EURUSD=X rises 1.5% (EUR strengthened by 1.5%)")
    print("    raw = +0.015; return_vs_usd = +0.015 (EUR strengthened, correct)")
    print("  ─────────────────────────────────────────────────────────────")
    print()

    # ── Run all variants ───────────────────────────────────────────────────
    configs = [
        dict(label="PRIMARY   — formation=21d, 3L+3S, monthly",
             formation_days=21, n_long=3, n_short=3, rebalance_freq="monthly"),
        dict(label="V2        — formation=42d, 3L+3S, monthly",
             formation_days=42, n_long=3, n_short=3, rebalance_freq="monthly"),
        dict(label="V3        — formation=63d, 3L+3S, monthly",
             formation_days=63, n_long=3, n_short=3, rebalance_freq="monthly"),
        dict(label="V4        — formation=21d, 2L+2S, monthly",
             formation_days=21, n_long=2, n_short=2, rebalance_freq="monthly"),
        dict(label="V5        — formation=21d, 3L+3S, bi-weekly",
             formation_days=21, n_long=3, n_short=3, rebalance_freq="biweekly"),
    ]

    results = []
    best    = None

    for cfg in configs:
        res = run_csm_backtest(pair_data, **cfg)
        results.append(res)

        # Full print for primary; concise for variants
        print_results(res, print_rebalances=(cfg["label"].startswith("PRIMARY")))

        if res.get("go") and best is None:
            best = res
            print(f"\n  ★ First passing config found: {res['label']}")
            print("    Stopping variant sweep (per spec instructions).\n")
            break

    # ── Variant comparison table ───────────────────────────────────────────
    print(f"\n\n{'='*72}")
    print("  VARIANT COMPARISON SUMMARY")
    print(f"{'='*72}")
    print(f"  {'Variant':<48} {'Shr':>5} {'DD%':>5} {'WR%':>5} {'Ret%':>6} {'Rb':>4} {'GO':>5}")
    print("  " + "─" * 78)
    for r in results:
        g = "YES" if r.get("go") else "no"
        lbl = r["label"][:48]
        print(f"  {lbl:<48} {r['sharpe']:>5.2f} {r['max_dd']*100:>5.1f} "
              f"{r['win_rate']:>5.1f} {r['total_ret']:>6.2f} {r['rebalances']:>4d} {g:>5}")

    # ── Final verdict ──────────────────────────────────────────────────────
    any_go = any(r.get("go") for r in results)
    print()
    if any_go:
        winner = next(r for r in results if r.get("go"))
        print(f"  VERDICT: GO")
        print(f"  Best config: {winner['label']}")
        print(f"  Sharpe={winner['sharpe']:.2f}  MaxDD={winner['max_dd']*100:.1f}%  "
              f"Return={winner['total_ret']:.2f}%  Rebalances={winner['rebalances']}")
        print()
        print("  Full per-rebalance breakdown for best config:")
        print_results(winner, print_rebalances=True)
    else:
        print("  VERDICT: NO-GO — all 5 variants failed thresholds.")
        print("  Recommend: (a) test carry trade variant, or")
        print("             (b) pause forex indefinitely, focus on other bots.")
    print()


if __name__ == "__main__":
    main()
