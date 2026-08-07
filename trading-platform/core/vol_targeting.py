"""
core/vol_targeting.py — Vol-Targeted Position Sizer
----------------------------------------------------
Stage 1 shared infrastructure.  NOT wired to any bot yet.

Function
--------
    vol_scaled_size(equity, etf, price, target_vol=0.12) → int shares

Sizing formula
--------------
    realized_vol = trailing 20d annualized vol of ETF daily returns
    raw_notional = equity × (target_vol / realized_vol)
    notional     = min(raw_notional, equity × 0.25)    ← 25% hard cap
    shares       = floor(notional / price)             ← whole shares only

Fail-safe direction
-------------------
All failure modes return 0 — skip the entry, never guess.
Consistent with Arc-3 audit: every silent-failure path is fail-CLOSED.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
VOL_PERIOD        = 20           # trading days for realized vol
VOL_ANN_FACTOR    = math.sqrt(252)
MAX_POSITION_FRAC = 0.25         # hard cap: 25% of equity per position
MIN_VOL_FLOOR     = 0.02         # floor: never divide by vol < 2% (stale-data guard)
FETCH_DAYS        = 35           # buffer: need 22+ bars → fetch 35d to be safe

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; trading-platform/1.0)"}


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch_daily_closes(ticker: str, days: int = FETCH_DAYS) -> Optional[list[float]]:
    """
    Yahoo Finance v8 daily adjClose — same endpoint used by bot2_spy_qqq
    via alpaca_etf_engine._yahoo_daily_ohlcv.  Implemented here standalone
    so this module has zero cross-package dependencies.

    Returns list of closes (oldest first) or None on any error.
    """
    import requests

    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{days}d", "interval": "1d", "includePrePost": "false"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"VolTarget | Yahoo {ticker} → HTTP {resp.status_code}")
            return None
        data   = resp.json()
        result = (data.get("chart", {}).get("result") or [None])[0]
        if not result:
            return None
        # Prefer adjClose (dividend/split-adjusted)
        adj    = (result.get("indicators", {}).get("adjclose") or [{}])[0]
        closes = adj.get("adjclose") or result["indicators"]["quote"][0].get("close", [])
        clean  = [float(c) for c in closes if c is not None and c > 0]
        return clean or None
    except Exception as exc:
        logger.warning(f"VolTarget | fetch failed for {ticker}: {exc}")
        return None


# ── Volatility calculation ─────────────────────────────────────────────────────

def _realized_vol_20d(closes: list[float]) -> Optional[float]:
    """
    Trailing 20-day annualized realized volatility from daily returns.
    Returns None when fewer than VOL_PERIOD + 2 bars available.
    """
    if len(closes) < VOL_PERIOD + 2:
        return None
    window     = closes[-(VOL_PERIOD + 1):]           # 21 closes → 20 returns
    daily_rets = [window[i] / window[i - 1] - 1 for i in range(1, len(window))]
    if len(daily_rets) < VOL_PERIOD:
        return None
    mu  = sum(daily_rets) / len(daily_rets)
    var = sum((r - mu) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
    return math.sqrt(var) * VOL_ANN_FACTOR


# ── Public API ────────────────────────────────────────────────────────────────

def vol_scaled_size(
    equity:     float,
    etf:        str,
    price:      float,
    target_vol: float = 0.12,
) -> int:
    """
    Vol-targeted position size for a single entry.

    Parameters
    ----------
    equity     : current portfolio equity in USD
    etf        : ticker symbol (e.g. "EWY")
    price      : current share price (ask or last close)
    target_vol : annualised portfolio vol target (default 12%)

    Returns
    -------
    int : whole shares to buy (floor).
          Returns 0 on ANY error — fail-CLOSED, never guesses.

    Notes
    -----
    A calm ETF (low realized vol) receives a larger allocation; a volatile
    EM ETF receives a smaller one.  The 25% cap prevents any single name
    from dominating regardless of vol.  Caller is responsible for the
    cash/deployment check before using the returned quantity.
    """
    if equity <= 0 or price <= 0:
        logger.warning(f"VolTarget | invalid inputs equity={equity} price={price} — returning 0")
        return 0

    closes = _fetch_daily_closes(etf)
    if not closes:
        logger.warning(f"VolTarget | {etf}: fetch returned no data — returning 0 (fail-CLOSED)")
        return 0

    rv = _realized_vol_20d(closes)
    if rv is None:
        logger.warning(
            f"VolTarget | {etf}: insufficient bars ({len(closes)}) for 20d vol "
            f"(need {VOL_PERIOD + 2}) — returning 0 (fail-CLOSED)"
        )
        return 0

    if rv < MIN_VOL_FLOOR:
        logger.warning(
            f"VolTarget | {etf}: realized_vol={rv:.4f} below floor {MIN_VOL_FLOOR} "
            f"(stale/flat data?) — returning 0 (fail-CLOSED)"
        )
        return 0

    raw_notional    = equity * (target_vol / rv)
    capped_notional = min(raw_notional, equity * MAX_POSITION_FRAC)
    shares          = int(capped_notional / price)

    logger.info(
        f"VolTarget | {etf}: rv={rv:.1%}  raw_notional=${raw_notional:,.0f}  "
        f"capped=${capped_notional:,.0f}  price=${price:.2f}  shares={shares}"
    )
    return shares


# ── Self-test (3 cases as specified) ─────────────────────────────────────────

def _selftest() -> None:
    """
    Three unit-test cases:
      1. Low-vol ETF  (IEF ~4-5% annualized)  → larger notional, more shares
      2. High-vol ETF (TUR ~30-40% annualized) → smaller notional, fewer shares
      3. Missing data (FAKE_TICKER99)           → 0 shares (fail-CLOSED)
    """
    EQUITY     = 100_000.0
    TARGET_VOL = 0.12

    print("=" * 70)
    print("UNIT TEST — core/vol_targeting.py")
    print("=" * 70)

    cases = [
        ("IEF",           95.0,  "Low-vol bond ETF  — expect larger position (closer to 25% cap)"),
        ("TUR",           35.0,  "High-vol EM ETF   — expect smaller position (vol-scaled down)"),
        ("FAKE_TICKER99", 50.0,  "Non-existent ETF  — expect 0 shares (fail-CLOSED)"),
    ]

    all_pass = True
    for etf, price, description in cases:
        shares      = vol_scaled_size(EQUITY, etf, price, TARGET_VOL)
        notional    = shares * price
        pct_eq      = notional / EQUITY

        print(f"\n  Case: {description}")
        print(f"    ticker={etf}  price=${price}  shares={shares}  "
              f"notional=${notional:,.0f}  ({pct_eq:.1%} of equity)")

        if etf == "FAKE_TICKER99":
            ok = (shares == 0)
            msg = "PASS ✅ — returned 0 on missing data (fail-CLOSED)" if ok \
                  else "FAIL ❌ — should have returned 0"
            if not ok:
                all_pass = False
        elif pct_eq == 0:
            ok = False
            msg = "FAIL ❌ — returned 0 on live data (check Yahoo connectivity)"
            all_pass = False
        elif pct_eq > 0.25 + 1e-9:
            ok = False
            msg = f"FAIL ❌ — exceeded 25% cap ({pct_eq:.2%})"
            all_pass = False
        else:
            ok = True
            msg = "PASS ✅ — non-zero, within 25% cap"
        print(f"    → {msg}")

    print()
    print(f"{'ALL TESTS PASS ✅' if all_pass else 'SOME TESTS FAILED ❌'}")
    print("=" * 70)
    return all_pass


if __name__ == "__main__":
    import logging as _log
    _log.basicConfig(level=logging.WARNING)
    _selftest()
