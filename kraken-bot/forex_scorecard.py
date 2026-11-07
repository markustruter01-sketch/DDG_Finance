"""Forex weekly scorecard (registered plan: Stage 1 needs it).

For every logged shadow day, score each source's direction call per pair at
1, 5 and 20 trading days: member 1, member 2, the decision-maker and the
registered baseline. A long scores the pair's return, a short the negative,
flat is not a call. Only horizons that have matured are counted. The final
decisions are also scored by the strategy they named (pack version 2 on), and
each AI's prediction (expected % move over its own horizon, 8 Nov on) is
compared with what the pair actually did over that horizon.

Pure functions plus one read-only job; no orders, no DB writes.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from forex_council import CouncilError, STRATEGIES, _json_object

NEW_YORK = ZoneInfo("America/New_York")
HORIZONS = (1, 5, 20)
# "decision_maker" is the final call: the vote result from council v3 on,
# the decider's call before. Members are scored on their own calls.
MEMBERS = ("member_1", "member_2", "member_3")
SOURCES = (*MEMBERS, "decision_maker", "baseline")
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
    """Each source's direction per pair for one ledger record. Works for every
    pack version: old records used letters (label_map), new ones pair names."""
    label_map: dict[str, str] = record.get("label_map") or {}
    out: dict[str, dict[str, str]] = {
        "baseline": dict(record.get("baseline") or {}),
        "decision_maker": {d["pair"]: d["direction"] for d in record.get("decisions") or []},
    }
    for role in MEMBERS:
        for call in record.get("calls") or []:
            if call.get("role") != role:
                continue
            try:
                calls = _json_object(call.get("raw", "")).get("calls") or []
                parsed = {label_map[c.get("pair") or c.get("label")]: c["direction"] for c in calls}
            except (CouncilError, KeyError, TypeError, AttributeError):
                continue
            out[role] = parsed
    return out


def strategy_calls(record: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """The final decision per pair as (strategy, direction); empty for old records."""
    return {d["pair"]: (d["strategy"], d["direction"]) for d in record.get("decisions") or [] if d.get("strategy")}


def prediction_calls(record: dict[str, Any]) -> dict[str, dict[str, tuple[float, int]]]:
    """Each AI's predicted move (percent) and horizon (trading days) per pair; empty for older records."""
    label_map: dict[str, str] = record.get("label_map") or {}
    out: dict[str, dict[str, tuple[float, int]]] = {}

    def pick(items: list[dict[str, Any]], key) -> dict[str, tuple[float, int]]:
        return {key(c): (float(c["expected_move_pct"]), int(c["horizon_days"]))
                for c in items if "expected_move_pct" in c and "horizon_days" in c and key(c)}

    out["decision_maker"] = pick(record.get("decisions") or [], lambda c: c.get("pair"))
    for call in record.get("calls") or []:
        role = call.get("role")
        if role not in MEMBERS:
            continue
        try:
            calls = _json_object(call.get("raw", "")).get("calls") or []
            out[role] = pick(calls, lambda c: label_map.get(c.get("pair") or c.get("label")))
        except (CouncilError, KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def score_predictions(rows: Iterable[tuple[date, dict[str, Any]]], closes: dict[str, dict[date, float]]) -> dict[str, Any]:
    """Predicted vs actual move, per AI, for predictions whose horizon has passed.
    Direction is judged only on predictions of a real move (not 0)."""
    tally = {s: {"predictions": 0, "dir_calls": 0, "dir_right": 0, "sum_pred": 0.0, "sum_actual": 0.0, "sum_miss": 0.0}
             for s in SOURCES if s != "baseline"}
    sorted_days = {pair: sorted(d) for pair, d in closes.items()}
    for trading_day, record in rows:
        for source, preds in prediction_calls(record).items():
            for pair, (pred, days) in preds.items():
                series, order = closes.get(pair), sorted_days.get(pair)
                if not series or trading_day not in series:
                    continue
                i = order.index(trading_day)
                if i + days >= len(order):
                    continue  # not matured yet
                actual = 100 * (series[order[i + days]] / series[trading_day] - 1)
                t = tally[source]
                t["predictions"] += 1
                t["sum_pred"] += pred
                t["sum_actual"] += actual
                t["sum_miss"] += abs(actual - pred)
                if pred != 0:
                    t["dir_calls"] += 1
                    t["dir_right"] += (actual > 0) == (pred > 0) and actual != 0
    return {
        s: {
            "predictions": t["predictions"],
            "direction_right_pct": round(100 * t["dir_right"] / t["dir_calls"], 1) if t["dir_calls"] else None,
            "avg_predicted_pct": round(t["sum_pred"] / t["predictions"], 3) if t["predictions"] else None,
            "avg_actual_pct": round(t["sum_actual"] / t["predictions"], 3) if t["predictions"] else None,
            "avg_miss_pct": round(t["sum_miss"] / t["predictions"], 3) if t["predictions"] else None,
        }
        for s, t in tally.items()
    }


def score(rows: Iterable[tuple[date, dict[str, Any]]], closes: dict[str, dict[date, float]]) -> dict[str, Any]:
    """Score every source at every horizon that has matured."""
    rows = list(rows)
    tally = {s: {h: {"calls": 0, "hits": 0, "sum_ret": 0.0} for h in HORIZONS} for s in SOURCES}
    by_strategy = {s: {h: {"calls": 0, "hits": 0, "sum_ret": 0.0} for h in HORIZONS} for s in STRATEGIES if s != "stay_out"}
    days = {"logged": 0, "shadow": 0, "no_trade": 0, "low_confidence": 0}
    sorted_days = {pair: sorted(d) for pair, d in closes.items()}
    for trading_day, record in rows:
        days["logged"] += 1
        status = record.get("status")
        days["shadow" if status == "shadow" else "no_trade"] += 1
        days["low_confidence"] += bool(record.get("low_confidence"))
        sources = {s: {p: (None, d) for p, d in c.items()} for s, c in source_calls(record).items()}
        sources["by_strategy"] = strategy_calls(record)
        for source, calls in sources.items():
            if source not in tally and source != "by_strategy":
                continue
            for pair, (strategy, direction) in calls.items():
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
                    t = by_strategy[strategy][h] if source == "by_strategy" else tally[source][h]
                    t["calls"] += 1
                    t["hits"] += signed > 0
                    t["sum_ret"] += signed
    def summary(by_h):
        return {
            f"{h}d": {
                "calls": t["calls"],
                "hit_rate_pct": round(100 * t["hits"] / t["calls"], 1) if t["calls"] else None,
                "avg_return_pct": round(100 * t["sum_ret"] / t["calls"], 4) if t["calls"] else None,
            }
            for h, t in by_h.items()
        }

    table = {s: summary(by_h) for s, by_h in tally.items()}
    return {"days": days, "sources": table, "strategies": {s: summary(t) for s, t in by_strategy.items()},
            "predictions": score_predictions(rows, closes),
            "note": "Shadow only. Holding no position scores 0. Returns are before spreads and financing."}


def run_weekly_scorecard(client: Any, get_conn: Any, pairs: Iterable[str]) -> dict[str, Any]:
    """Read the ledger and recent candles, score, and return the scorecard."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trading_day, record FROM forex_decision_ledger ORDER BY trading_day")
            rows = [(d, r if isinstance(r, dict) else json.loads(r)) for d, r in cur.fetchall()]
    closes = {p: closes_by_day(client.daily_candles(p, count=CANDLES_FOR_SCORING)) for p in pairs}
    return score(rows, closes)
