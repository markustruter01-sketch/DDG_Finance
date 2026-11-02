"""FLEET-V1 instrument reconstructions (plan: research_harness/explore/FLEET-V1-PLAN.md, "Data").

Every live instrument is a *spliced* series: before its ETF existed it is
rebuilt from index levels, yields and dividends with the plan's declared
formulas; from the ETF's first day it is the real ETF (Yahoo dividend-adjusted
OHLC). The rebuilt part is scaled so the two parts meet exactly on the ETF's
first day, so returns are continuous and the real-ETF era is the real ETF.

Rebuilt bars are close-only (open = high = low = close): old index data has
no reliable opens, so a signal read at Monday's close fills at TUESDAY's
close, and stops can only fire at a close. (G4-STRESS-1985 used open =
previous close, which fills at the same close the signal was read from -
a one-session look-ahead; removed here at step 5.)

All series share one calendar: the S&P 500's trading days. Other series are
carried forward onto it (never backward), so a value is only used on or after
the day it was published.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Iterable

from research_harness.harness.metrics import TRADING_DAYS, rf_daily_for

Series = list[tuple[date, float]]          # (day, level), ascending

# ── declared values (plan) ────────────────────────────────────────────────────
NDX_YIELD = 0.008                          # Nasdaq-100 dividend yield before QQQ (sensitivities 0%, 1.5%)
BORROW_SPREAD = 0.005                      # 2x funds pay DTB3 + 0.50% on the borrowed 1x
FEES_2X = {"SSO": 0.0089, "QLD": 0.0095}   # ProShares, read 2 Nov 2026
BOND_MATURITY_YEARS = 10
SHILLER_LAG_MONTHS = 3                     # Shiller's monthly dividend is paid this many months after its label
REAL_ETF = {                               # live instrument -> the rebuilt series it is spliced onto
    "SPY": "SPX_TR", "QQQ": "NDX_TR", "SSO": "SSO_R", "QLD": "QLD_R",
    "IEF": "UST10_TR", "GLD": "GOLD", "DBC": "GSCI", "UUP": "DXY",
}
INDEX = {"SP": "^GSPC", "NDX": "^NDX", "GSCI": "^SPGSCI", "DXY": "DX-Y.NYB"}


# ── calendar and alignment ────────────────────────────────────────────────────
def calendar(bars: Iterable[dict[str, Any]]) -> list[date]:
    return sorted({b["day"] for b in bars})


def from_bars(bars: Iterable[dict[str, Any]], field: str = "close") -> Series:
    return sorted(((b["day"], float(b[field])) for b in bars), key=lambda x: x[0])


def align(points: Series | dict[date, float], cal: list[date]) -> Series:
    """Values on calendar days, carried forward from the last published value.
    Days before the first published value are dropped (no back-filling)."""
    pts = sorted(points.items()) if isinstance(points, dict) else list(points)
    out: Series = []
    j, last = 0, None
    for d in cal:
        while j < len(pts) and pts[j][0] <= d:
            last = pts[j][1]
            j += 1
        if last is not None:
            out.append((d, last))
    return out


def returns(s: Series) -> list[tuple[date, float]]:
    return [(s[i][0], s[i][1] / s[i - 1][1] - 1) for i in range(1, len(s))]


def from_returns(first_day: date, rets: list[tuple[date, float]], start_value: float = 100.0) -> Series:
    out: Series = [(first_day, start_value)]
    for d, r in rets:
        out.append((d, max(out[-1][1] * (1 + r), 1e-9)))
    return out


# ── declared formulas ─────────────────────────────────────────────────────────
def sp500_tr(price: Series, monthly: list[dict[str, Any]]) -> Series:
    """S&P 500 total return: the daily price index with Shiller's monthly
    dividend (annual rate / 12, index points) reinvested on the first session
    of each month.

    The dividend is lagged SHILLER_LAG_MONTHS (one quarter): the first session
    of month m pays the dividend labelled month m-3. Shiller interpolates his
    monthly dividends from quarterly data, so month m's value was not knowable
    at the time. Months with no m-3 dividend pay nothing."""
    def _pay_month(d: date) -> tuple[int, int]:
        k = d.year * 12 + (d.month - 1) + SHILLER_LAG_MONTHS
        return k // 12, k % 12 + 1

    div = {_pay_month(m["day"]): m["dividend"] / 12 for m in monthly}
    rets, seen = [], set()
    for i in range(1, len(price)):
        d, p = price[i]
        key = (d.year, d.month)
        paid = 0.0
        if key not in seen and price[i - 1][0].month != d.month:
            paid = div.get(key, 0.0)
        seen.add(key)
        rets.append((d, (p + paid) / price[i - 1][1] - 1))
    return from_returns(price[0][0], rets, price[0][1])


def add_yield(price: Series, annual_yield: float) -> Series:
    """Price index plus a constant dividend yield accrued daily (Nasdaq-100 before QQQ)."""
    rets = [(d, r + annual_yield / TRADING_DAYS) for d, r in returns(price)]
    return from_returns(price[0][0], rets, price[0][1])


def bond_duration(y: float, years: int = BOND_MATURITY_YEARS) -> float:
    """Modified duration, in YEARS, of a par bond with semiannual coupons:
    (1 - (1 + y/2)^-2n) / (y/2) counts half-year periods, so it is divided by 2.
    (The plan's formula omitted the /2 - found at step 5 when the rebuilt
    series showed 2.3x IEF's volatility; see Amendment 1.)"""
    if y <= 1e-9:
        return float(years)
    return (1 - (1 + y / 2) ** (-2 * years)) / (y / 2) / 2


def bond_tr(yields: Series) -> Series:
    """Treasury 10-year total return from the daily yield (decimal), Swinkels (2019):
    r_t = -D(y_{t-1}) x (y_t - y_{t-1}) + y_{t-1} / 252."""
    rets = []
    for i in range(1, len(yields)):
        y0, y1 = yields[i - 1][1], yields[i][1]
        rets.append((yields[i][0], -bond_duration(y0) * (y1 - y0) + y0 / TRADING_DAYS))
    return from_returns(yields[0][0], rets)


def levered(under: Series, rf_annual: dict[date, float], fee: float, lev: float = 2.0,
            spread: float = BORROW_SPREAD) -> Series:
    """Daily-reset leveraged fund: lev x the underlying's daily return, minus
    (T-bill + spread) on the borrowed (lev - 1), minus the fund's yearly fee."""
    rets = returns(under)
    rf_d = rf_daily_for([d for d, _ in rets], rf_annual)
    out = []
    for (d, r), rf in zip(rets, rf_d):
        out.append((d, lev * r - (lev - 1) * (rf + spread / TRADING_DAYS) - fee / TRADING_DAYS))
    return from_returns(under[0][0], out)


def with_collateral(s: Series, rf_annual: dict[date, float]) -> Series:
    """An index plus T-bill interest on fully collateralised futures."""
    rets = returns(s)
    rf_d = rf_daily_for([d for d, _ in rets], rf_annual)
    return from_returns(s[0][0], [(d, r + rf) for (d, r), rf in zip(rets, rf_d)], s[0][1])


# ── bars and splicing ─────────────────────────────────────────────────────────
def close_to_close(s: Series) -> list[dict[str, Any]]:
    """Close-only bars: a next-open fill becomes a next-close fill."""
    return [{"day": d, "open": c, "high": c, "low": c, "close": c} for d, c in s]


def splice(recon: Series, etf_bars: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Rebuilt bars before the ETF's first day (scaled to meet it), real ETF bars from it."""
    if not etf_bars:
        return close_to_close(recon)
    first = etf_bars[0]["day"]
    before = [(d, v) for d, v in recon if d <= first]
    if not before:
        return [dict(b) for b in etf_bars]
    scale = etf_bars[0]["close"] / before[-1][1]
    rebuilt = close_to_close([(d, v * scale) for d, v in before if d < first])
    return rebuilt + [dict(b) for b in etf_bars]


def build(
    index_bars: dict[str, list[dict[str, Any]]],
    etf_bars: dict[str, list[dict[str, Any]]],
    rates: dict[str, dict[date, float]],
    shiller: list[dict[str, Any]],
    *,
    ndx_yield: float = NDX_YIELD,
    gold: Series | None = None,
    collateral: bool = True,
) -> dict[str, Any]:
    """All FLEET-V1 instruments.

    index_bars: Yahoo index bars keyed by INDEX symbols.
    etf_bars: Yahoo adjusted bars for the live ETFs (any may be missing).
    rates: {"DTB3": {day: rate}, "DGS10": {day: rate}} (annual decimals).
    shiller: monthly S&P price/dividend rows.
    gold: the rebuilt gold series for before GLD, or None (then the gold
        line exists only from GLD's first day). The source is an open
        decision for the plan (FRED's LBMA series has been withdrawn).
    collateral: if True (default, the plan's step-5 decision), the GSCI and
        DXY series that DBC and UUP are spliced onto are the index plus T-bill
        interest (DTB3) on fully collateralised futures (with_collateral); if
        False they are the plain index. recon["GSCI"] / recon["DXY"] hold
        whichever series is spliced.

    Returns {"instruments": {symbol: bars}, "recon": {name: Series}, "calendar": [...]}.
    """
    cal = calendar(index_bars[INDEX["SP"]])
    dtb3 = rates["DTB3"]
    sp = align(from_bars(index_bars[INDEX["SP"]]), cal)
    ndx = align(from_bars(index_bars[INDEX["NDX"]]), cal)
    recon: dict[str, Series] = {}
    recon["SPX_TR"] = sp500_tr(sp, shiller)
    recon["NDX_TR"] = add_yield(ndx, ndx_yield)
    recon["SSO_R"] = levered(recon["SPX_TR"], dtb3, FEES_2X["SSO"])
    recon["QLD_R"] = levered(recon["NDX_TR"], dtb3, FEES_2X["QLD"])
    recon["UST10_TR"] = bond_tr(align(rates["DGS10"], cal))
    recon["GSCI"] = align(from_bars(index_bars[INDEX["GSCI"]]), cal)
    recon["DXY"] = align(from_bars(index_bars[INDEX["DXY"]]), cal)
    if collateral:
        recon["GSCI"] = with_collateral(recon["GSCI"], dtb3)
        recon["DXY"] = with_collateral(recon["DXY"], dtb3)
    if gold is not None:
        recon["GOLD"] = align(gold, cal)
    instruments = {}
    for sym, name in REAL_ETF.items():
        etf = etf_bars.get(sym)
        if name in recon:
            instruments[sym] = splice(recon[name], etf)
        elif etf:
            instruments[sym] = [dict(b) for b in etf]
    return {"instruments": instruments, "recon": recon, "calendar": cal}


def cagr(s: Series) -> float | None:
    years = (s[-1][0] - s[0][0]).days / 365.25
    if years <= 0 or s[0][1] <= 0:
        return None
    return (s[-1][1] / s[0][1]) ** (1 / years) - 1


def max_drawdown(s: Series) -> float:
    peak, mdd = s[0][1], 0.0
    for _, v in s:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


def ann_vol(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(TRADING_DAYS)
