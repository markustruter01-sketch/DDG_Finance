"""
core/correlation_cap.py — Rolling Correlation Cap
--------------------------------------------------
Stage 1 shared infrastructure.  NOT wired to any bot yet.

Function
--------
    corr_cap_check(candidate_etf, held_etfs, price_history,
                   threshold=0.75, max_correlated=2)
    → (allowed: bool, reason: str | None)

Rule
----
    Compute rolling 60-day Pearson correlation between the candidate and each
    currently held position.  If the number of held positions with ρ > threshold
    is >= max_correlated, block the entry and return (False, reason_with_rho_values).
    Otherwise return (True, None).

Fail-safe direction
-------------------
    Missing / insufficient history for a given pair → treat as ρ=0 (allow).
    We do NOT block entries because of sparse data — the vol_targeting and
    regional_regime modules provide the fail-CLOSED gates.  Blocking on
    insufficient correlation data would cause entries to be wrongly suppressed
    during early-position warm-up.

Helper
------
    fetch_price_history(tickers, days=90) → dict[str, list[float]]
    Convenience fetch for callers that don't pre-populate price_history.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
CORR_PERIOD  = 60   # rolling window: 60 trading days of daily returns
MIN_OVERLAP  = 20   # minimum bars required to compute a meaningful ρ

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; trading-platform/1.0)"}


# ── Math helpers ───────────────────────────────────────────────────────────────

def _daily_returns(closes: list[float], period: int = CORR_PERIOD) -> list[float]:
    """
    Last `period` daily returns from a close series (oldest-first input).
    Returns an empty list if fewer than 2 bars available.
    """
    n = len(closes)
    if n < 2:
        return []
    # Take last period+1 closes so we get exactly `period` returns
    window = closes[max(0, n - period - 1):]
    return [window[i] / window[i - 1] - 1 for i in range(1, len(window))]


def _pearson_corr(ret_a: list[float], ret_b: list[float]) -> Optional[float]:
    """
    Pearson correlation of two return series.
    Aligned from the tail (both series trimmed to common length).
    Returns None when fewer than MIN_OVERLAP observations overlap.
    """
    n = min(len(ret_a), len(ret_b))
    if n < MIN_OVERLAP:
        return None
    a = ret_a[-n:]
    b = ret_b[-n:]
    mu_a = sum(a) / n
    mu_b = sum(b) / n
    cov   = sum((ai - mu_a) * (bi - mu_b) for ai, bi in zip(a, b)) / (n - 1)
    var_a = sum((ai - mu_a) ** 2 for ai in a) / (n - 1)
    var_b = sum((bi - mu_b) ** 2 for bi in b) / (n - 1)
    if var_a <= 0 or var_b <= 0:
        return None
    return cov / math.sqrt(var_a * var_b)


# ── Data helper ───────────────────────────────────────────────────────────────

def fetch_price_history(tickers: list[str], days: int = 90) -> dict[str, list[float]]:
    """
    Fetch Yahoo Finance v8 daily adjClose for a list of tickers.

    Returns dict of ticker → closes (oldest first).
    Tickers that fail are omitted from the result (not included as empty list)
    so callers can distinguish "not fetched" from "fetched, but empty".

    Same Yahoo v8 endpoint used by bot2_spy_qqq via alpaca_etf_engine.
    """
    import requests

    result: dict[str, list[float]] = {}
    for ticker in tickers:
        url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {"range": f"{days}d", "interval": "1d", "includePrePost": "false"}
        try:
            resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"CorrCap | fetch {ticker} → HTTP {resp.status_code}")
                continue
            data   = resp.json()
            res    = (data.get("chart", {}).get("result") or [None])[0]
            if not res:
                continue
            adj    = (res.get("indicators", {}).get("adjclose") or [{}])[0]
            closes = adj.get("adjclose") or res["indicators"]["quote"][0].get("close", [])
            clean  = [float(c) for c in closes if c is not None and c > 0]
            if clean:
                result[ticker] = clean
        except Exception as exc:
            logger.warning(f"CorrCap | fetch {ticker} failed: {exc}")
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def corr_cap_check(
    candidate_etf:  str,
    held_etfs:      list[str],
    price_history:  dict[str, list[float]],
    threshold:      float = 0.75,
    max_correlated: int   = 2,
) -> tuple[bool, Optional[str]]:
    """
    Rolling 60-day correlation cap check.

    Parameters
    ----------
    candidate_etf  : ticker we want to enter (e.g. "EWT")
    held_etfs      : list of tickers currently in the portfolio
    price_history  : ticker → daily closes (oldest first).  Must include
                     both the candidate and all held tickers.
                     Use fetch_price_history() to build this mapping.
    threshold      : ρ above which two positions are "correlated"  (default 0.75)
    max_correlated : block entry when count_correlated >= max_correlated.
                     With max_correlated=2: block when ≥2 held positions each
                     have ρ > threshold with the candidate, preventing a
                     cluster of 3+ correlated names.  (default 2)

    Returns
    -------
    (True, None)
        Entry allowed — fewer than max_correlated correlated partners found.

    (False, reason_str)
        Entry BLOCKED — reason_str includes the ρ values for transparency,
        e.g. "corr_cap_blocked: EWT has ρ>0.75 with 2 held: EWY(ρ=0.831), ..."

    Fail-safe
    ---------
    Any pair where ρ cannot be computed (insufficient overlap) is treated as
    ρ=0 (allowed).  This is intentionally permissive on data gaps so that
    early-position warm-up doesn't incorrectly suppress entries.
    """
    if not held_etfs:
        return True, None

    cand_closes = price_history.get(candidate_etf, [])
    if len(cand_closes) < 2:
        logger.debug(
            f"CorrCap | {candidate_etf}: no price history in price_history dict — "
            f"treating ρ=0, allowing entry"
        )
        return True, None

    cand_rets = _daily_returns(cand_closes)
    correlated_partners: list[tuple[str, float]] = []   # (ticker, rho)
    all_rhos: list[tuple[str, float | None]] = []        # for logging

    for held in held_etfs:
        held_closes = price_history.get(held, [])
        if len(held_closes) < 2:
            logger.debug(f"CorrCap | {held}: no price history — treating ρ=0, allowing")
            all_rhos.append((held, None))
            continue

        held_rets = _daily_returns(held_closes)
        rho       = _pearson_corr(cand_rets, held_rets)

        if rho is None:
            logger.debug(
                f"CorrCap | {candidate_etf} vs {held}: insufficient overlap "
                f"(need {MIN_OVERLAP} bars) — treating ρ=0, allowing"
            )
            all_rhos.append((held, None))
            continue

        rho_r = round(rho, 4)
        all_rhos.append((held, rho_r))
        logger.debug(f"CorrCap | {candidate_etf} vs {held}: ρ={rho_r:.4f}  threshold={threshold}")

        if rho_r > threshold:
            correlated_partners.append((held, rho_r))

    logger.info(
        f"CorrCap | {candidate_etf}: correlated_partners={len(correlated_partners)}"
        f"/{len(held_etfs)} above threshold {threshold}  "
        f"all_rhos=[{', '.join(f'{t}:{r:.3f}' if r is not None else f'{t}:N/A' for t,r in all_rhos)}]"
    )

    if len(correlated_partners) >= max_correlated:
        pairs_str = ", ".join(f"{t}(ρ={r:.3f})" for t, r in correlated_partners)
        reason = (
            f"corr_cap_blocked: {candidate_etf} has ρ>{threshold} with "
            f"{len(correlated_partners)} held position(s): {pairs_str} "
            f"(max_correlated={max_correlated})"
        )
        logger.info(f"CorrCap | BLOCKED {candidate_etf} — {reason}")
        return False, reason

    return True, None


# ── Self-test ─────────────────────────────────────────────────────────────────

def _selftest() -> bool:
    """
    Two unit-test cases:

    Case 1: held=[EWY], candidate=EWT, max_correlated=1
        EWY (South Korea — semiconductor/tech heavy) vs EWT (Taiwan — TSMC-heavy)
        are historically highly correlated (same Asia tech theme).
        Expect BLOCKED when ρ > 0.75.

    Case 2: held=[EWY], candidate=EWZ, max_correlated=1
        EWZ (Brazil — commodity/financials) vs EWY (Korea — tech) are different
        EM themes and should be less correlated.
        Expect ALLOWED when ρ ≤ 0.75.

    Uses max_correlated=1 in the test (block when ≥1 partner is correlated)
    so a single pair triggers the cap.  The function default (max_correlated=2)
    is for production fleet use where one correlated buddy is acceptable.
    """
    import time

    print("=" * 70)
    print("UNIT TEST — core/correlation_cap.py")
    print("=" * 70)

    print("\n  Fetching 90d price history for EWY, EWT, EWZ…")
    t0      = time.time()
    history = fetch_price_history(["EWY", "EWT", "EWZ"], days=90)
    elapsed = time.time() - t0

    for tk in ["EWY", "EWT", "EWZ"]:
        n = len(history.get(tk, []))
        print(f"    {tk}: {n} bars")
    print(f"  Fetch completed in {elapsed:.1f}s")

    all_pass = True

    # ── Case 1: EWY held, EWT candidate ──────────────────────────────────────
    print(f"\n  Case 1: held=[EWY]  candidate=EWT  max_correlated=1")
    allowed1, reason1 = corr_cap_check(
        "EWT", ["EWY"], history, threshold=0.75, max_correlated=1
    )

    # Show the raw ρ
    rho_1 = _pearson_corr(
        _daily_returns(history.get("EWT", [])),
        _daily_returns(history.get("EWY", [])),
    )
    rho_1_str = f"{rho_1:.4f}" if rho_1 is not None else "N/A (insufficient data)"
    print(f"    ρ(EWT vs EWY) = {rho_1_str}")
    print(f"    allowed={allowed1}  reason={reason1}")

    if rho_1 is not None and rho_1 > 0.75:
        ok1 = not allowed1
        label1 = "PASS ✅ — correctly BLOCKED (ρ > 0.75 same-theme pair)" if ok1 \
                 else "FAIL ❌ — should have been BLOCKED"
    else:
        # ρ ≤ 0.75 at this time: entry correctly allowed
        ok1 = allowed1
        label1 = (
            f"PASS ✅ — ρ={rho_1_str} ≤ 0.75 right now; correctly ALLOWED  "
            f"(threshold not breached by live data)"
        )
    if not ok1:
        all_pass = False
    print(f"    → {label1}")

    # ── Case 2: EWY held, EWZ candidate ──────────────────────────────────────
    print(f"\n  Case 2: held=[EWY]  candidate=EWZ  max_correlated=1")
    allowed2, reason2 = corr_cap_check(
        "EWZ", ["EWY"], history, threshold=0.75, max_correlated=1
    )

    rho_2 = _pearson_corr(
        _daily_returns(history.get("EWZ", [])),
        _daily_returns(history.get("EWY", [])),
    )
    rho_2_str = f"{rho_2:.4f}" if rho_2 is not None else "N/A (insufficient data)"
    print(f"    ρ(EWZ vs EWY) = {rho_2_str}")
    print(f"    allowed={allowed2}  reason={reason2}")

    if rho_2 is not None and rho_2 <= 0.75:
        ok2 = allowed2
        label2 = "PASS ✅ — correctly ALLOWED (ρ ≤ 0.75 different-theme pair)" if ok2 \
                 else "FAIL ❌ — should have been ALLOWED"
    else:
        # ρ > 0.75: corr-cap correctly blocked even for the "different theme" pair
        ok2 = not allowed2
        label2 = (
            f"PASS ✅ — ρ={rho_2_str} > 0.75 right now; correctly BLOCKED  "
            f"(EM selloffs drive cross-regional correlation up)"
        )
    if not ok2:
        all_pass = False
    print(f"    → {label2}")

    print()
    print(f"{'ALL TESTS PASS ✅' if all_pass else 'SOME TESTS FAILED ❌'}")
    print("=" * 70)
    return all_pass


if __name__ == "__main__":
    import logging as _log
    _log.basicConfig(level=logging.WARNING)
    _selftest()
