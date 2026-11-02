"""Calibrate the FLEET-V1 reconstructions against the real ETFs (plan, "Data").

For each rebuilt series and the ETF it stands in for, over the days both
exist and only up to the end of exploration (2010-12-31 — locked rows are
never read here):

- return gap: rebuilt CAGR minus ETF CAGR (a yearly figure);
- correlation of daily returns;
- max-drawdown gap: rebuilt max drawdown minus ETF max drawdown;
- haircut: how much deeper the ETF's drawdown was than the rebuilt one's
  (zero when the rebuilt series is the deeper one). The plan applies it to
  the rebuilt part of any candidate's drawdown, so a reconstruction that
  understates losses cannot flatter a result.

Commodities and the dollar are reported twice — the plain index, and the
index plus T-bill interest (the collateral yield a futures fund earns) —
because neither Yahoo index includes it; the plan's later steps choose.
The Nasdaq-100 yield is reported at 0%, 0.8% (declared) and 1.5%.

Run:  python3 -m research_harness.recon.calibrate --index DS --etf DS --rates DS --shiller DS
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from typing import Any

from research_harness.recon import reconstruct as rc

CAL_END = date(2010, 12, 31)
NDX_YIELDS = (0.0, 0.008, 0.015)


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def compare(recon: rc.Series, etf: rc.Series, end: date = CAL_END) -> dict[str, Any] | None:
    """Gap statistics over the common days up to ``end``; None if under 60 common days."""
    r = dict(recon)
    common = [(d, v) for d, v in etf if d in r and d <= end]
    if len(common) < 60:
        return None
    e = common
    x = [(d, r[d]) for d, _ in common]
    re, rx = rc.returns(e), rc.returns(x)
    mdd_e, mdd_x = rc.max_drawdown(e), rc.max_drawdown(x)
    cagr_e, cagr_x = rc.cagr(e), rc.cagr(x)
    return {
        "first": e[0][0].isoformat(), "last": e[-1][0].isoformat(), "days": len(e),
        "cagr_recon": cagr_x, "cagr_etf": cagr_e,
        "return_gap": None if cagr_x is None or cagr_e is None else cagr_x - cagr_e,
        "correlation": _pearson([v for _, v in rx], [v for _, v in re]),
        "vol_recon": rc.ann_vol([v for _, v in rx]), "vol_etf": rc.ann_vol([v for _, v in re]),
        "mdd_recon": mdd_x, "mdd_etf": mdd_e, "mdd_gap": mdd_x - mdd_e,
        "haircut": max(0.0, mdd_x - mdd_e),   # drawdowns are negative: positive gap = rebuilt shallower
    }


def calibrate(index_bars, etf_bars, rates, shiller, *, gold: rc.Series | None = None,
              end: date = CAL_END) -> dict[str, Any]:
    """Calibration report for every pair the data allows."""
    built = rc.build(index_bars, etf_bars, rates, shiller, gold=gold)
    recon = built["recon"]
    etf = {s: rc.from_bars(b) for s, b in etf_bars.items() if b}
    out: dict[str, Any] = {"end": end.isoformat(), "pairs": {}, "missing": []}

    def add(label: str, series: rc.Series | None, sym: str) -> None:
        if series is None or sym not in etf:
            out["missing"].append(label)
            return
        res = compare(series, etf[sym], end)
        if res is None:
            out["missing"].append(label)
        else:
            out["pairs"][label] = res

    add("SPX_TR vs SPY", recon["SPX_TR"], "SPY")
    add("SSO_R vs SSO", recon["SSO_R"], "SSO")
    add("QLD_R vs QLD", recon["QLD_R"], "QLD")
    add("UST10_TR vs IEF", recon["UST10_TR"], "IEF")
    add("GOLD vs GLD", recon.get("GOLD"), "GLD")
    add("GSCI plain vs DBC", recon["GSCI"], "DBC")
    add("GSCI + T-bill vs DBC", rc.with_collateral(recon["GSCI"], rates["DTB3"]), "DBC")
    add("DXY plain vs UUP", recon["DXY"], "UUP")
    add("DXY + T-bill vs UUP", rc.with_collateral(recon["DXY"], rates["DTB3"]), "UUP")
    ndx = rc.align(rc.from_bars(index_bars[rc.INDEX["NDX"]]), built["calendar"])
    for y in NDX_YIELDS:
        add(f"NDX_TR {y:.1%} vs QQQ", rc.add_yield(ndx, y), "QQQ")
    return out


def _load(store, args) -> tuple:
    start = date(1985, 1, 1)
    idx = {s: store.load(args.index, s, start=start, end=CAL_END) for s in rc.INDEX.values()}
    etfs = {}
    for s in rc.REAL_ETF:
        try:
            etfs[s] = store.load(args.etf, s, start=start, end=CAL_END)
        except KeyError:            # ETF not pulled (e.g. GLD before 2004 is simply absent)
            etfs[s] = []
    rates = {s: store.load_rates(args.rates, s, start=start, end=CAL_END) for s in ("DTB3", "DGS10")}
    shiller = store.load(args.shiller, "SP500", start=start, end=CAL_END)
    gold = None
    if args.gold:
        gold = rc.from_bars(store.load(args.gold, args.gold_symbol, start=start, end=CAL_END))
    return idx, etfs, rates, shiller, gold


def main(argv: list[str] | None = None) -> int:
    from research_harness.harness.store import BarStore

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--index", required=True)
    p.add_argument("--etf", required=True)
    p.add_argument("--rates", required=True)
    p.add_argument("--shiller", required=True)
    p.add_argument("--gold", help="dataset holding a pre-GLD gold series (optional)")
    p.add_argument("--gold-symbol", default="GC=F")
    p.add_argument("--out", help="write the JSON report here")
    args = p.parse_args(argv)
    store = BarStore()
    idx, etfs, rates, shiller, gold = _load(store, args)
    report = calibrate(idx, etfs, rates, shiller, gold=gold)
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
