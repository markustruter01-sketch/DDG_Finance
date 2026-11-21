"""The macro state (roadmap v2, V2-06) and the four daily flags (V2-19). PURE, prices only.

Every rule and number here is PROPOSED (written by Fable 5.2 on 21 Nov 2026,
never run on data). Markus said yes to roadmap v2 on 22 Nov 2026.

1. Six votes, each "close above its own 200-session average":
   growth    : SPY · IWM · the ratio HYG / IEF (risky bonds beating safe bonds)
   inflation : DBC · USO · the ratio TIP / IEF (inflation-protected beating plain bonds)
   Growth is "up" on 2 of 3; inflation is "up" on 2 of 3.
2. Label: goldilocks (growth up, inflation down) · reflation (up, up) ·
   stagflation (down, up) · bust (down, down).
3. A new label counts only after 5 sessions in a row; until then yesterday's
   label stands. Worked by walking the raw labels of the last LABEL_WALK
   sessions (so it can be replayed on any history, the warm-up of V2-08
   included). If no label held 5 sessions in that walk, there is no label yet.
4. Stored, read by no rule: "bonds are hedging" (63-session correlation of SPY
   and IEF daily returns below zero), "rough" (the Allocator V1 measure: SPY's
   20-session volatility above the median of its own last 252), dollar trend
   (UUP above its 200-session average).
5. The four flags (V2-19), read by no table and no fund (roadmap v2, rule 10):
   - sell_off_fast : SPY, TLT and UUP each closed lower than 21 sessions earlier;
   - sell_off_slow : SPY, TLT and UUP each below their own 200-session average;
   - hard_assets_lead : GLD / SPY and DBC / SPY each above their own 200-session average;
   - tight_money (D14) : TIP below its own 200-session average and UUP above its own.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from research_harness.harness.portfolio import HistoryView
from research_harness.league.base import ann_vol

TREND = 200
CONFIRM = 5
LABEL_WALK = 252
FAST = 21
HEDGE_SESSIONS = 63
ROUGH_VOL, ROUGH_LOOKBACK = 20, 252          # the Allocator V1 roughness measure (allocator.py)
LABELS = ("goldilocks", "reflation", "stagflation", "bust")
SYMBOLS = ("SPY", "IWM", "HYG", "IEF", "TIP", "DBC", "USO", "UUP", "TLT", "GLD")
FLAGS = ("sell_off_fast", "sell_off_slow", "hard_assets_lead", "tight_money")


# ── series helpers (aligned by day, up to view.today) ────────────────────────
def _series(view: HistoryView, symbol: str, n: int) -> dict[date, float] | None:
    """The last n closes up to today, by day; None if the symbol has no bar today."""
    if symbol not in view.symbols():
        return None
    rows = view.window(symbol, n)
    if not rows or rows[-1]["day"] != view.today:
        return None
    return {b["day"]: b["close"] for b in rows}


def _closes(view: HistoryView, symbol: str, n: int) -> list[float] | None:
    s = _series(view, symbol, n)
    return list(s.values()) if s is not None and len(s) == n else None


def _ratio(view: HistoryView, top: str, bottom: str, n: int) -> list[float] | None:
    """top / bottom on the days both have a close (the last n of them, today included)."""
    a, b = _series(view, top, n + 40), _series(view, bottom, n + 40)
    if a is None or b is None:
        return None
    days = sorted(set(a) & set(b))[-n:]
    return [a[d] / b[d] for d in days] if len(days) == n else None


def _above_average(c: list[float] | None) -> bool | None:
    return None if c is None else c[-1] > sum(c) / len(c)


# ── 1 + 2. votes and the raw label ───────────────────────────────────────────
def votes(view: HistoryView) -> dict[str, bool] | None:
    out = {
        "spy": _above_average(_closes(view, "SPY", TREND)),
        "iwm": _above_average(_closes(view, "IWM", TREND)),
        "hyg_ief": _above_average(_ratio(view, "HYG", "IEF", TREND)),
        "dbc": _above_average(_closes(view, "DBC", TREND)),
        "uso": _above_average(_closes(view, "USO", TREND)),
        "tip_ief": _above_average(_ratio(view, "TIP", "IEF", TREND)),
    }
    return None if any(v is None for v in out.values()) else out


def raw_label(v: dict[str, bool]) -> str:
    growth = sum((v["spy"], v["iwm"], v["hyg_ief"])) >= 2
    inflation = sum((v["dbc"], v["uso"], v["tip_ief"])) >= 2
    return {(True, False): "goldilocks", (True, True): "reflation",
            (False, True): "stagflation", (False, False): "bust"}[(growth, inflation)]


# ── 3. the five-session rule ─────────────────────────────────────────────────
def confirm(raw: list[str | None]) -> list[str | None]:
    """Confirmed label per session: a raw label counts once it has held CONFIRM
    sessions in a row; until then the previous confirmed label stands."""
    out: list[str | None] = []
    for i, lab in enumerate(raw):
        run = raw[max(0, i - CONFIRM + 1): i + 1]
        held = lab is not None and len(run) == CONFIRM and all(x == lab for x in run)
        out.append(lab if held else (out[-1] if out else None))
    return out


def label_on(view: HistoryView, calendar: tuple[date, ...], day: date) -> tuple[str | None, str | None]:
    """(confirmed label, raw label) at ``day``'s close, walking the last LABEL_WALK sessions."""
    import bisect
    end = bisect.bisect_right(calendar, day)
    walk = calendar[max(0, end - LABEL_WALK): end]
    today = view.today
    raw = []
    for d in walk:
        view.today = d
        v = votes(view)
        raw.append(raw_label(v) if v else None)
    view.today = today
    return (confirm(raw)[-1] if raw else None), (raw[-1] if raw else None)


# ── 4 + 5. side measures and flags (stored; read by no rule) ─────────────────
def _returns(c: list[float]) -> list[float]:
    return [c[i] / c[i - 1] - 1 for i in range(1, len(c))]


def side(view: HistoryView) -> dict[str, Any]:
    out: dict[str, Any] = {"bonds_hedging": None, "rough": None, "dollar_up": None}
    spy, ief = _series(view, "SPY", HEDGE_SESSIONS + 41), _series(view, "IEF", HEDGE_SESSIONS + 41)
    if spy and ief:
        days = sorted(set(spy) & set(ief))[-(HEDGE_SESSIONS + 1):]
        if len(days) == HEDGE_SESSIONS + 1:
            a, b = _returns([spy[d] for d in days]), _returns([ief[d] for d in days])
            try:
                corr = statistics.correlation(a, b)
                out["bonds_hedging"], out["spy_ief_corr63"] = corr < 0, round(corr, 4)
            except statistics.StatisticsError:      # a flat series has no correlation
                pass
    c = _closes(view, "SPY", ROUGH_LOOKBACK + ROUGH_VOL + 1)
    if c is not None:
        vols = [ann_vol(c[: len(c) - k], ROUGH_VOL) for k in range(ROUGH_LOOKBACK)]
        if all(v is not None for v in vols):
            out["rough"] = vols[0] > statistics.median(vols)
    out["dollar_up"] = _above_average(_closes(view, "UUP", TREND))
    return out


def flags(view: HistoryView) -> dict[str, bool | None]:
    def lower_than(sym: str) -> bool | None:
        c = _closes(view, sym, FAST + 1)
        return None if c is None else c[-1] < c[0]

    def below(sym: str) -> bool | None:
        up = _above_average(_closes(view, sym, TREND))
        return None if up is None else not up

    def all_of(xs: list[bool | None]) -> bool | None:
        return None if any(x is None for x in xs) else all(xs)

    return {
        "sell_off_fast": all_of([lower_than(s) for s in ("SPY", "TLT", "UUP")]),
        "sell_off_slow": all_of([below(s) for s in ("SPY", "TLT", "UUP")]),
        "hard_assets_lead": all_of([_above_average(_ratio(view, "GLD", "SPY", TREND)),
                                    _above_average(_ratio(view, "DBC", "SPY", TREND))]),
        "tight_money": all_of([below("TIP"), _above_average(_closes(view, "UUP", TREND))]),
    }


def state(view: HistoryView, calendar: tuple[date, ...], day: date) -> dict[str, Any]:
    """Everything stored for one session (the macro_state row)."""
    view.today = day
    v = votes(view)
    confirmed, raw = label_on(view, calendar, day)
    view.today = day
    return {"label": confirmed, "raw_label": raw, "votes": v, "flags": flags(view), "side": side(view)}
