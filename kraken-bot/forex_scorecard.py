"""Forex weekly scorecard (registered plan: Stage 1 needs it).

For every logged shadow day, score each source's direction call per pair at
1, 5 and 20 trading days: member 1, member 2, the decision-maker and the
registered baseline. A long scores the pair's return, a short the negative,
flat is not a call. Only horizons that have matured are counted.

Pure functions plus one read-only job; no orders, no DB writes.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from forex_council import CouncilError, parse_council_reply

NEW_YORK = ZoneInfo("America/New_York")
HORIZONS = (1, 5, 20)
SOURCES = ("member_1", "member_2", "decision_maker", "baseline")
CANDLES_FOR_SCORING = 60


def closes_by_day(candles: list[dict[str, Any]]) -> dict[date, float]:
    """OANDA daily mid candles keyed by the New York trading day they close on.
    A candle starting at the 17:00 New York close closes at the next one."""
    out: dict[date, float] = {}
    for c in candles:
        if c.get("complete") is not True:
            continue
        start = datetime.fromisoformat(c["time"][:19] + "+00:00").astimezone(NEW_YORK)
        out[(start + timedelta(days=1)).date()] = float(c["mid"]["c"])
    return out


def source_calls(record: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Each source's direction per pair for one ledger record."""
    label_map: dict[str, str] = record.get("label_map") or {}
    labels = sorted(label_map)
    out: dict[str, dict[str, str]] = {
        "baseline": dict(record.get("baseline") or {}),
        "decision_maker": {d["pair"]: d["direction"] for d in record.get("decisions") or []},
    }
    for role in ("member_1", "member_2"):
        for call in record.get("calls") or []:
            if call.get("role") != role:
                continue
            try:
                parsed = parse_council_reply(call.get("raw", ""), labels)
            except CouncilError:
                continue
            out[role] = {label_map[p["label"]]: p["direction"] for p in parsed}
    return out


def score(rows: Iterable[tuple[date, dict[str, Any]]], closes: dict[str, dict[date, float]]) -> dict[str, Any]:
    """Score every source at every horizon that has matured."""
    tally = {s: {h: {"calls": 0, "hits": 0, "sum_ret": 0.0} for h in HORIZONS} for s in SOURCES}
    days = {"logged": 0, "shadow": 0, "no_trade": 0, "low_confidence": 0}
    sorted_days = {pair: sorted(d) for pair, d in closes.items()}
    for trading_day, record in rows:
        days["logged"] += 1
        status = record.get("status")
        days["shadow" if status == "shadow" else "no_trade"] += 1
        days["low_confidence"] += bool(record.get("low_confidence"))
        for source, calls in source_calls(record).items():
            if source not in tally:
                continue
            for pair, direction in calls.items():
                if direction not in ("long", "short") or pair not in closes:
                    continue
                series, order = closes[pair], sorted_days[pair]
                if trading_day not in series:
                    continue
                i = order.index(trading_day)
                for h in HORIZONS:
                    if i + h >= len(order):
                        continue
                    ret = series[order[i + h]] / series[trading_day] - 1
                    signed = ret if direction == "long" else -ret
                    t = tally[source][h]
                    t["calls"] += 1
                    t["hits"] += signed > 0
                    t["sum_ret"] += signed
    table = {
        s: {
            f"{h}d": {
                "calls": t["calls"],
                "hit_rate_pct": round(100 * t["hits"] / t["calls"], 1) if t["calls"] else None,
                "avg_return_pct": round(100 * t["sum_ret"] / t["calls"], 4) if t["calls"] else None,
            }
            for h, t in by_h.items()
        }
        for s, by_h in tally.items()
    }
    return {"days": days, "sources": table,
            "note": "Shadow only. Holding no position scores 0. Returns are before spreads and financing."}


def run_weekly_scorecard(client: Any, get_conn: Any, pairs: Iterable[str]) -> dict[str, Any]:
    """Read the ledger and recent candles, score, and return the scorecard."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trading_day, record FROM forex_decision_ledger ORDER BY trading_day")
            rows = [(d, r if isinstance(r, dict) else json.loads(r)) for d, r in cur.fetchall()]
    closes = {p: closes_by_day(client.daily_candles(p, count=CANDLES_FOR_SCORING)) for p in pairs}
    return score(rows, closes)
