"""The Allocator, rules version (roadmap Phase 3), on fake money. PURE.

1. A regime label each US session from four measurements (prices only):
   - trend: SPY close above its 200-session average;
   - breadth: share of S&P 500 members whose close is above their own 200-session average;
   - rates: IEF (7-10 year Treasuries) 60-session return; a fall means rates rising;
   - roughness: SPY 20-session volatility above the middle (median) of its own
     20-session volatility over the past 252 sessions.
   Direction is "up" when at least 2 of 3 hold: trend above, breadth >= 50%,
   IEF 60-session return >= 0. Labels: calm up, rough up, calm down, rough down.
2. A fixed share for each strategy family per label (TABLE), split equally
   between that family's lines that have a value that day.
3. Limits: no line above 40% of the fund; total exposure (2x funds count
   double, cash counts nothing) at most 1.5x, scaled down into cash if above;
   a 15% fall from the fund's high puts everything in cash for good (until a
   human resets it).
Two funds: "equal" (every rules line the same share, monthly) and "rules"
(the table). Same limits and costs for both. The AI fund (c) is not built:
it needs Markus's yes on the extra AI cost.

A fund holds the league lines themselves: its daily return is the weighted sum
of their daily returns (their own trading costs already inside). Moving money
between lines costs 5 bps of the amount moved. Decided at a session's close,
applied from the next session. Numbers PROPOSED (Opus 19 Nov): registration
research_harness/registrations/league/ALLOCATOR-V1.json.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from research_harness.harness.portfolio import HistoryView
from research_harness.league.base import ann_vol, closes, has_today, is_month_start, sma

TREND_SESSIONS = 200
RATES_SESSIONS = 60
VOL_SESSIONS = 20
VOL_LOOKBACK = 252
BREADTH_UP = 0.50
LABELS = ("calm up", "rough up", "calm down", "rough down")
FAMILIES = ("trend", "stocks", "diversifier", "short_term", "forex")
TABLE: dict[str, dict[str, float]] = {
    "calm up":    {"trend": 0.35, "stocks": 0.35, "diversifier": 0.10, "short_term": 0.10, "forex": 0.10},
    "rough up":   {"trend": 0.25, "stocks": 0.25, "diversifier": 0.25, "short_term": 0.10, "forex": 0.15},
    "calm down":  {"trend": 0.20, "stocks": 0.15, "diversifier": 0.35, "short_term": 0.10, "forex": 0.20},
    "rough down": {"trend": 0.15, "stocks": 0.10, "diversifier": 0.40, "short_term": 0.10, "forex": 0.25},
}
LINE_CAP = 0.40
MAX_EXPOSURE = 1.5
STOP_FALL = 0.15
SWITCH_COST_BPS = 5.0
CASH_LINE = "Y-CASH"
GEARED = {"SSO": 2.0, "QLD": 2.0}


# ── 1. the regime label ───────────────────────────────────────────────────────
def measurements(view: HistoryView, universe: tuple[str, ...]) -> dict[str, Any] | None:
    spy = closes(view, "SPY", VOL_LOOKBACK + VOL_SESSIONS + 1)
    ief = closes(view, "IEF", RATES_SESSIONS + 1)
    if len(spy) < max(TREND_SESSIONS, VOL_LOOKBACK + VOL_SESSIONS + 1) or len(ief) < RATES_SESSIONS + 1:
        return None
    vols = [ann_vol(spy[: len(spy) - k], VOL_SESSIONS) for k in range(VOL_LOOKBACK)]
    above, counted = 0, 0
    for s in universe:
        c = closes(view, s, TREND_SESSIONS)
        if len(c) == TREND_SESSIONS:
            counted += 1
            above += c[-1] > sma(c, TREND_SESSIONS)
    if not counted or any(v is None for v in vols):
        return None
    return {"spy_above_trend": spy[-1] > sma(spy, TREND_SESSIONS),
            "breadth": round(above / counted, 4), "members_counted": counted,
            "ief_60d": round(ief[-1] / ief[0] - 1, 6),
            "vol20": round(vols[0], 6), "vol20_median": round(statistics.median(vols), 6)}


def label(m: dict[str, Any]) -> str:
    votes = sum((m["spy_above_trend"], m["breadth"] >= BREADTH_UP, m["ief_60d"] >= 0))
    rough = m["vol20"] > m["vol20_median"]
    return f"{'rough' if rough else 'calm'} {'up' if votes >= 2 else 'down'}"


# ── 2 + 3. weights and limits ────────────────────────────────────────────────
def table_weights(lab: str, families: dict[str, str]) -> dict[str, float]:
    """The label's family shares, split equally between the family's lines present."""
    out: dict[str, float] = {}
    for fam, share in TABLE[lab].items():
        lines = sorted(i for i, f in families.items() if f == fam)
        for i in lines:
            out[i] = share / len(lines)
    missing = 1.0 - sum(out.values())                # a family with no lines today: its share to cash
    if missing > 1e-9:
        out[CASH_LINE] = out.get(CASH_LINE, 0.0) + missing
    return out


def equal_weights(families: dict[str, str]) -> dict[str, float]:
    lines = sorted(families)
    return {i: 1.0 / len(lines) for i in lines}


def limited(weights: dict[str, float], exposure: dict[str, float]) -> dict[str, float]:
    """No line above 40% (the excess to cash); total exposure at most 1.5x (scaled into cash)."""
    w = {i: min(x, LINE_CAP) for i, x in weights.items() if i != CASH_LINE}
    total = sum(w[i] * exposure.get(i, 1.0) for i in w)
    if total > MAX_EXPOSURE:
        w = {i: x * MAX_EXPOSURE / total for i, x in w.items()}
    w[CASH_LINE] = 1.0 - sum(w.values())
    return {i: round(x, 10) for i, x in w.items() if x > 1e-12}


def line_exposure(weights: dict[str, float] | None) -> float:
    """A line's exposure from the holdings it has decided: 2x funds count double, BIL nothing."""
    if not weights:
        return 0.0
    return sum(abs(x) * GEARED.get(s, 1.0) for s, x in weights.items() if s != "BIL")


# ── the fund ──────────────────────────────────────────────────────────────────
def run_fund(mode: str, days: list[date], labels: dict[date, str], returns: dict[str, dict[date, float]],
             families: dict[str, str], exposure: dict[str, dict[date, float]]) -> dict[str, Any]:
    """Equity (starting 1.0) of fund ``mode`` ('equal' or 'rules') over ``days``.

    returns[line][day]: that line's return on ``day`` (0 if it has none).
    families: rules lines -> family (Y-CASH is the cash line, not a choice).
    A decision at day d's close uses only d's label and exposures; it earns from d+1.
    """
    equity, peak, held, curve, decisions, tripped = 1.0, 1.0, None, [], [], None
    for i, d in enumerate(days):
        if held is not None:                                   # today's return on yesterday's holdings
            r = sum(w * returns.get(line, {}).get(d, 0.0) for line, w in held.items())
            equity *= 1 + r
            grown = {line: w * (1 + returns.get(line, {}).get(d, 0.0)) for line, w in held.items()}
            total = sum(grown.values()) or 1.0
            held = {line: w / total for line, w in grown.items()}
        peak = max(peak, equity)
        if tripped is None and equity <= peak * (1 - STOP_FALL):
            tripped = d
        curve.append((d, equity))
        lab = labels.get(d)
        if tripped is not None:
            want = {CASH_LINE: 1.0}
        elif lab is None:
            continue
        else:
            due = held is None or is_month_start(tuple(days), d) or (
                mode == "rules" and decisions and decisions[-1]["label"] != lab)
            if not due:
                continue
            base = table_weights(lab, families) if mode == "rules" else equal_weights(families)
            want = limited(base, {line: exposure.get(line, {}).get(d, 1.0) for line in base})
        if want == held:
            continue
        moved = sum(abs(want.get(k, 0.0) - (held or {}).get(k, 0.0)) for k in set(want) | set(held or {}))
        equity *= 1 - SWITCH_COST_BPS / 1e4 * (moved if held is not None else 1.0)
        curve[-1] = (d, equity)
        held = dict(want)
        decisions.append({"day": d, "label": lab if tripped is None else "stopped: 15% fall", "weights": held})
    return {"curve": curve, "decisions": decisions, "tripped": tripped}
