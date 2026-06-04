"""
GET /fleet/scorecard — Live-capital readiness framework.

Scores each of the 4 bots against 6 evaluation gates and produces a
readiness verdict.  Snapshots are written to bot_evaluation_history
at most once per 12 hours.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone, date as date_type
from typing import Any

from fastapi import APIRouter
from loguru import logger

scorecard_router = APIRouter()

_STARTING_EQUITY        = 100_000.0
_SNAPSHOT_MIN_INTERVAL_H = 12          # hours between auto-snapshots
_TARGET_DECISION_DATE   = "2026-07-04"

# ── Bot configuration ──────────────────────────────────────────────────────────

_BOT_CFG: dict[str, dict] = {
    "oracle": {
        "strategy":               "STF v1.0 mechanical",
        "evaluation_window_start": "2025-12-01",
        "table":                  "trades",
        "asset_class":            "momentum_equity",
    },
    "spy_qqq_trend": {
        "strategy":               "EMA50/200 long-only ETF trend",
        "evaluation_window_start": "2026-04-30",
        "table":                  "trades",
        "asset_class":            "momentum_etf",
    },
    "jerome_macro": {
        "strategy":               "Jerome v2 EMA/ADX/ATR trend-following",
        "evaluation_window_start": "2026-05-28",
        "table":                  "jerome_positions",
        "bot_id":                 "jerome_macro",
    },
    "buck_futures": {
        "strategy":               "Buck Futures commodity clone of Jerome v2",
        "evaluation_window_start": "2026-05-29",
        "table":                  "jerome_positions",
        "bot_id":                 "buck_futures",
    },
}

# ── Maths helpers ──────────────────────────────────────────────────────────────

def _sharpe(daily_pnls: list[float]) -> float | None:
    """Annualised Sharpe from daily PnL series.  Returns None if <5 days."""
    if len(daily_pnls) < 5:
        return None
    mean = statistics.mean(daily_pnls)
    try:
        std = statistics.stdev(daily_pnls)
    except statistics.StatisticsError:
        return None
    if std == 0.0:
        return None
    return (mean / std) * math.sqrt(252)


def _max_drawdown(daily_pnls: list[float], starting: float = _STARTING_EQUITY) -> float:
    """Largest peak-to-trough decline on cumulative PnL as fraction of starting equity."""
    if not daily_pnls:
        return 0.0
    cum, total = [], 0.0
    for p in daily_pnls:
        total += p
        cum.append(total)
    peak, mdd = cum[0], 0.0
    for v in cum:
        if v > peak:
            peak = v
        dd = (peak - v) / starting
        if dd > mdd:
            mdd = dd
    return mdd


# ── Data fetchers ──────────────────────────────────────────────────────────────

def _rows_to_metrics(rows: list, pnl_idx: int, win_fn) -> dict[str, Any]:
    """Convert raw query rows to gate metric dict."""
    if not rows:
        return {"trades_count": 0}

    pnls   = [float(r[pnl_idx]) for r in rows]
    wins   = sum(1 for r in rows if win_fn(r))
    total  = len(rows)

    # Aggregate daily PnL by close date
    daily: dict[str, float] = {}
    for r in rows:
        key = str(r[2])          # close_day is always index 2
        daily[key] = daily.get(key, 0.0) + float(r[pnl_idx])
    daily_series = [daily[d] for d in sorted(daily.keys())]

    # Adverse survived: has a loss AND a win that came after that loss
    loss_idxs = [i for i, r in enumerate(rows) if float(r[pnl_idx]) < 0]
    win_idxs  = [i for i, r in enumerate(rows) if float(r[pnl_idx]) > 0]
    adverse = bool(
        loss_idxs and win_idxs and max(win_idxs) > min(loss_idxs)
    )

    return {
        "trades_count":    total,
        "wins":            wins,
        "win_rate":        wins / total,
        "expectancy":      statistics.mean(pnls),
        "sharpe":          _sharpe(daily_series),
        "sharpe_days":     len(daily_series),
        "max_drawdown":    _max_drawdown(daily_series),
        "adverse_survived": adverse,
    }


def _fetch_trades_metrics(cur, asset_class: str, window_start: str) -> dict[str, Any]:
    # trades table uses 'date' (DATE) for entry date, not opened_at
    cur.execute(
        """
        SELECT realized_pnl,
               status,
               DATE(closed_at) AS close_day
        FROM   trades
        WHERE  asset_class   = %s
          AND  closed_at     IS NOT NULL
          AND  realized_pnl  IS NOT NULL
          AND  date          >= %s
        ORDER  BY closed_at
        """,
        (asset_class, window_start),
    )
    rows = cur.fetchall()
    return _rows_to_metrics(rows, pnl_idx=0, win_fn=lambda r: r[1] == "Closed_Win")


def _fetch_jerome_metrics(cur, bot_id: str, window_start: str) -> dict[str, Any]:
    cur.execute(
        """
        SELECT realised_pnl_usd,
               CASE WHEN realised_pnl_usd > 0 THEN 'win' ELSE 'loss' END AS outcome,
               DATE(closed_at) AS close_day
        FROM   jerome_positions
        WHERE  bot_id      = %s
          AND  status      = 'closed'
          AND  opened_at   >= %s
          AND  realised_pnl_usd IS NOT NULL
        ORDER  BY closed_at
        """,
        (bot_id, window_start),
    )
    rows = cur.fetchall()
    return _rows_to_metrics(rows, pnl_idx=0, win_fn=lambda r: r[1] == "win")


# ── Gate builder ───────────────────────────────────────────────────────────────

def _build_gates(m: dict) -> tuple[dict, int, int, float, str]:
    """
    Build the gates dict plus summary stats from metrics.
    Returns (gates, gates_passed, gates_strong, readiness_score, verdict).
    """
    wr    = m["win_rate"]
    exp   = m["expectancy"]
    sh    = m["sharpe"]
    days  = m["sharpe_days"]
    mdd   = m["max_drawdown"]
    tc    = m["trades_count"]
    adv   = m["adverse_survived"]

    sharpe_pass   = sh is not None and sh >= 0.5
    sharpe_strong = sh is not None and sh >= 1.0
    sharpe_note   = (
        f"computed from {days} trading day(s) — treat with caution"
        if days < 20 else None
    )

    gates: dict[str, Any] = {
        "sample_size": {
            "value":     tc,
            "pass":      tc >= 10,
            "strong":    tc >= 20,
            "threshold": 10,
            "note":      None,
        },
        "win_rate": {
            "value":     round(wr, 4),
            "pass":      wr >= 0.45,
            "strong":    wr >= 0.55,
            "threshold": 0.45,
            "note":      None,
        },
        "expectancy": {
            "value":     round(exp, 2),
            "pass":      exp > 0,
            "strong":    exp >= 50.0,
            "threshold": 0.0,
            "note":      None,
        },
        "sharpe": {
            "value":     round(sh, 4) if sh is not None else None,
            "pass":      sharpe_pass,
            "strong":    sharpe_strong,
            "threshold": 0.5,
            "note":      sharpe_note,
        },
        "max_drawdown": {
            "value":     round(mdd, 6),
            "pass":      mdd <= 0.15,
            "strong":    mdd <= 0.10,
            "threshold": 0.15,
            "note":      None,
        },
        "adverse_survived": {
            "value":     adv,
            "pass":      adv,
            "strong":    adv,
            "threshold": None,
            "note":      "manual review recommended" if not adv else None,
        },
    }

    gates_passed = sum(1 for g in gates.values() if g["pass"])
    gates_strong = sum(1 for g in gates.values() if g["strong"])
    # readiness_score: max numerator = 6 passes (6.0) + 6 strongs (3.0) = 9.0
    readiness_score = round((gates_passed * 1.0 + gates_strong * 0.5) / 9.0, 4)

    if gates_passed == 6:
        verdict = "LIVE_CAPITAL_READY"
    elif gates_passed >= 4:
        verdict = "PROMISING"
    elif gates_passed >= 2:
        verdict = "AT_RISK"
    else:
        verdict = "DISQUALIFIED"

    return gates, gates_passed, gates_strong, readiness_score, verdict


# ── Snapshot writer ────────────────────────────────────────────────────────────

def _maybe_write_snapshots(bots: dict[str, dict], now: datetime) -> None:
    """Write bot_evaluation_history rows if last snapshot is >12 h old."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_id, data in bots.items():
                    try:
                        cur.execute(
                            """
                            SELECT snapshot_at FROM bot_evaluation_history
                            WHERE  bot_id = %s
                            ORDER  BY snapshot_at DESC
                            LIMIT  1
                            """,
                            (bot_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            last = row[0]
                            if last.tzinfo is None:
                                last = last.replace(tzinfo=timezone.utc)
                            if (now - last).total_seconds() < _SNAPSHOT_MIN_INTERVAL_H * 3600:
                                continue

                        gates = data.get("gates") or {}
                        cur.execute(
                            """
                            INSERT INTO bot_evaluation_history
                              (bot_id, snapshot_at, trades_count, win_rate,
                               expectancy_usd, sharpe, max_drawdown,
                               gates_passed, readiness_score, verdict)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                bot_id,
                                now,
                                data.get("trades_count"),
                                gates.get("win_rate",    {}).get("value"),
                                gates.get("expectancy",  {}).get("value"),
                                gates.get("sharpe",      {}).get("value"),
                                gates.get("max_drawdown",{}).get("value"),
                                data.get("gates_passed"),
                                data.get("readiness_score"),
                                data.get("verdict"),
                            ),
                        )
                        logger.debug(f"scorecard | snapshot written → {bot_id}")
                    except Exception as _exc:
                        logger.warning(f"scorecard | snapshot write failed for {bot_id}: {_exc}")
    except Exception as exc:
        logger.warning(f"scorecard | snapshot block failed: {exc}")


# ── Route ──────────────────────────────────────────────────────────────────────

@scorecard_router.get("/fleet/scorecard")
async def fleet_scorecard() -> dict:
    """Live-capital readiness scorecard — 6 evaluation gates per bot."""
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return {"error": "database unavailable", "generated_at": datetime.now(timezone.utc).isoformat()}

    now = datetime.now(timezone.utc)
    target_dt = datetime.fromisoformat(_TARGET_DECISION_DATE)
    days_left  = max(0, (target_dt.date() - now.date()).days)

    bots: dict[str, dict] = {}
    live_capital_ready: list[str] = []
    insufficient_data:  list[str] = []
    disqualified:       list[str] = []
    promising:          list[str] = []

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_id, cfg in _BOT_CFG.items():
                    window_start = cfg["evaluation_window_start"]

                    if cfg["table"] == "trades":
                        m = _fetch_trades_metrics(cur, cfg["asset_class"], window_start)
                    else:
                        m = _fetch_jerome_metrics(cur, cfg["bot_id"], window_start)

                    tc = m.get("trades_count", 0)

                    if tc < 10:
                        bots[bot_id] = {
                            "strategy":               cfg["strategy"],
                            "evaluation_window_start": window_start,
                            "trades_count":           tc,
                            "gates":                  None,
                            "gates_passed":           None,
                            "gates_strong":           None,
                            "readiness_score":        None,
                            "verdict":                "INSUFFICIENT_DATA",
                            "notes":                  (
                                f"{tc} close(s) since {window_start}; "
                                "need ≥10 to score gates"
                            ),
                        }
                        insufficient_data.append(bot_id)
                    else:
                        gates, gp, gs, rs, verdict = _build_gates(m)
                        bots[bot_id] = {
                            "strategy":               cfg["strategy"],
                            "evaluation_window_start": window_start,
                            "trades_count":           tc,
                            "gates":                  gates,
                            "gates_passed":           gp,
                            "gates_strong":           gs,
                            "readiness_score":        rs,
                            "verdict":                verdict,
                            "notes":                  None,
                        }
                        if verdict == "LIVE_CAPITAL_READY":
                            live_capital_ready.append(bot_id)
                        elif verdict in ("DISQUALIFIED", "AT_RISK"):
                            disqualified.append(bot_id)
                        else:
                            promising.append(bot_id)

    except Exception as exc:
        logger.error(f"scorecard | DB query failed: {exc}")
        return {
            "error":        str(exc),
            "generated_at": now.isoformat(),
        }

    _maybe_write_snapshots(bots, now)

    return {
        "generated_at":        now.isoformat(),
        "target_decision_date": _TARGET_DECISION_DATE,
        "days_to_decision":    days_left,
        "bots":                bots,
        "fleet_summary": {
            "live_capital_ready": live_capital_ready,
            "promising":          promising,
            "insufficient_data":  insufficient_data,
            "disqualified":       disqualified,
        },
    }
