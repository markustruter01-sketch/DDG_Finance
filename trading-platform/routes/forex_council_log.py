"""Forex AI council — the decision record, for the dashboard's Forex page.

Read-only. Everything shown comes from the append-only decision ledger
(forex_decision_ledger), the execution log (forex_execution_log) and the
scorecard computed from the ledger plus OANDA daily candles.

- GET /forex-council/days                 newest days first: status and final calls
- GET /forex-council/day/{trading_day}    one day in full: news, both members, decider, trades
- GET /forex-council/scorecard            hit rate and average move per AI and per strategy
- GET /forex-council/costs                what the council's AI calls cost, per month (list prices)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

_KRAKEN_BOT = str(Path(__file__).resolve().parents[2] / "kraken-bot")
if _KRAKEN_BOT not in sys.path:
    sys.path.append(_KRAKEN_BOT)

forex_council_log_router = APIRouter()

ROLES = ("member_1", "member_2", "member_3")
SCORECARD_TTL_SECONDS = 30 * 60
_scorecard_cache: dict[str, Any] = {"at": 0.0, "card": None}


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else json.loads(value)


def member_views(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each council member's calls, by pair. Old (lettered) records are mapped
    back to pair names; a member whose reply could not be read is left out."""
    from forex_council import CouncilError, _json_object

    label_map = record.get("label_map") or {}
    out: dict[str, dict[str, Any]] = {}
    for call in record.get("calls") or []:
        role = call.get("role")
        if role not in ROLES:
            continue
        try:
            calls = _json_object(call.get("raw", "")).get("calls") or []
            rows = []
            for c in calls:
                pair = label_map.get(c.get("pair") or c.get("label"))
                if pair:
                    rows.append({"pair": pair, "direction": c.get("direction"), "strategy": c.get("strategy"),
                                 "conviction": c.get("conviction"), "stop_atr_multiple": c.get("stop_atr_multiple"),
                                 "reason": c.get("reason"),
                                 "why_not_others": c.get("why_not_others"),
                                 "expected_move_pct": c.get("expected_move_pct"),
                                 "horizon_days": c.get("horizon_days"), "expected_path": c.get("expected_path")})
        except (CouncilError, AttributeError, TypeError):
            continue
        # The last readable attempt is the one the council used.
        out[role] = {"provider": call.get("provider"), "model": call.get("model"),
                     "calls": sorted(rows, key=lambda r: r["pair"])}
    return out


def day_summary(trading_day: date, status: str, record: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    decisions = record.get("decisions") or []
    return {
        "trading_day": trading_day.isoformat(),
        "status": status,
        "low_confidence": bool(record.get("low_confidence")),
        "news_count": len((record.get("pack") or {}).get("news") or []) if isinstance((record.get("pack") or {}).get("news"), list) else 0,
        "errors": len(record.get("errors") or []),
        "trades": [{"pair": d["pair"], "direction": d["direction"], "strategy": d.get("strategy"),
                    "conviction": d.get("conviction"), "outcome": d.get("outcome")} for d in decisions if d.get("direction") in ("long", "short")],
        "executed": bool(report),
    }


def day_detail(trading_day: date, status: str, record: dict[str, Any], sha: str,
               report: dict[str, Any] | None) -> dict[str, Any]:
    pack = record.get("pack") or {}
    return {
        **day_summary(trading_day, status, record, report),
        "record_sha256": sha,
        "pack_version": pack.get("version", 1),
        "council_version": record.get("council_version", 2),
        "news": pack.get("news") if isinstance(pack.get("news"), list) else [],
        "news_sources": record.get("news_sources") or [],
        "market": pack.get("pairs") or [],
        "members": member_views(record),
        "decisions": sorted(record.get("decisions") or [], key=lambda d: d["pair"]),
        "errors_list": record.get("errors") or [],
        "execution": report,
    }


def _rows(sql: str, params: tuple = ()) -> list[tuple]:
    from db.postgres import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('forex_decision_ledger') IS NOT NULL")
        if not cur.fetchone()[0]:
            return []
        cur.execute(sql, params)
        return cur.fetchall()


def _reports(days: list[date]) -> dict[date, dict[str, Any]]:
    if not days:
        return {}
    try:
        rows = _rows("SELECT trading_day, report FROM forex_execution_log WHERE trading_day = ANY(%s)", (days,))
    except Exception:  # the log table may not exist yet
        return {}
    return {d: _record(r) for d, r in rows}


@forex_council_log_router.get("/forex-council/days")
async def forex_council_days(limit: int = Query(60, ge=1, le=400)):
    rows = _rows("SELECT trading_day, status, record FROM forex_decision_ledger ORDER BY trading_day DESC LIMIT %s", (limit,))
    reports = _reports([d for d, _, _ in rows])
    return {"days": [day_summary(d, s, _record(r), reports.get(d)) for d, s, r in rows]}


@forex_council_log_router.get("/forex-council/day/{trading_day}")
async def forex_council_day(trading_day: date):
    rows = _rows("SELECT trading_day, status, record, record_sha256 FROM forex_decision_ledger WHERE trading_day = %s",
                 (trading_day,))
    if not rows:
        raise HTTPException(status_code=404, detail="No council record for that day")
    d, s, r, sha = rows[0]
    return day_detail(d, s, _record(r), sha, _reports([d]).get(d))


def council_costs(rows: list[tuple]) -> list[dict[str, Any]]:
    """Each month's AI cost of the real council, from the token counts the ledger already keeps.

    Prices come from twins.ai_council.PRICES (one list for the whole platform). A call with no
    token counts, or a model with no listed price, is counted as "unpriced", never as $0.
    """
    from twins.ai_council import cost_usd
    months: dict[str, dict[str, Any]] = {}
    for trading_day, record in rows:
        m = months.setdefault(trading_day.strftime("%Y-%m"), {"month": trading_day.strftime("%Y-%m"),
                                                              "usd": 0.0, "calls": 0, "unpriced": 0})
        for call in _record(record).get("calls") or []:
            m["calls"] += 1
            c = cost_usd(call.get("model", ""), call.get("usage"))
            if c is None:
                m["unpriced"] += 1
            else:
                m["usd"] = round(m["usd"] + c, 6)
    return sorted(months.values(), key=lambda m: m["month"], reverse=True)


@forex_council_log_router.get("/forex-council/costs")
async def forex_council_costs():
    rows = await asyncio.to_thread(_rows, "SELECT trading_day, record FROM forex_decision_ledger ORDER BY trading_day")
    return {"months": council_costs(rows), "prices": "list prices; a free tier would make some calls cheaper"}


@forex_council_log_router.get("/forex-council/scorecard")
async def forex_council_scorecard():
    """Scored from the ledger and OANDA's daily candles; cached for 30 minutes."""
    if _scorecard_cache["card"] is not None and time.time() - _scorecard_cache["at"] < SCORECARD_TTL_SECONDS:
        return _scorecard_cache["card"]
    try:
        from core.oanda_client import OandaClient
        from db.postgres import get_conn
        from forex_quant_desk import FOREX_PAIRS
        from forex_scorecard import run_weekly_scorecard

        with OandaClient() as client:
            card = run_weekly_scorecard(client, get_conn, FOREX_PAIRS)
    except Exception as exc:
        logger.warning(f"forex council scorecard unavailable: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail=f"Scorecard unavailable ({type(exc).__name__})") from None
    card = {**card, "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _scorecard_cache.update(at=time.time(), card=card)
    return card


@forex_council_log_router.get("/forex/open", tags=["Forex council"])
async def forex_open() -> dict[str, Any]:
    """The Forex account's balance and open trades straight from OANDA (read-only GETs)."""
    def read() -> dict[str, Any]:
        from core.oanda_client import OandaClient
        with OandaClient() as client:
            summary = client.account_summary()
            trades = client.open_trades()
        out = []
        for t in trades:
            units = float(t.get("currentUnits") or 0)
            stop = (t.get("stopLossOrder") or {}).get("price")
            out.append({"pair": t.get("instrument"), "side": "buy" if units > 0 else "sell", "units": abs(units),
                        "entry": float(t["price"]) if t.get("price") else None,
                        "stop": float(stop) if stop else None,
                        "unrealized_usd": float(t["unrealizedPL"]) if t.get("unrealizedPL") else None,
                        "opened": t.get("openTime")})
        return {"currency": summary["currency"], "balance": float(summary["balance"]), "nav": float(summary["nav"]),
                "margin_used": float(summary["margin_used"]), "open": out}
    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        logger.warning(f"forex | open trades unreadable: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="OANDA unreadable")
