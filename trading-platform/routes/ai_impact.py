"""AI Impact Timeline — tracks performance vs AI interventions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter
from loguru import logger

ai_impact_router = APIRouter(prefix="/ai-impact", tags=["AI Impact"])


def _get_conn():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"])


@ai_impact_router.get("/timeline")
async def get_ai_impact_timeline():
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, ts, source, overall_verdict, bot_verdicts,
                       param_changes, vetoed_tickers, critique_summary,
                       critique_flags, conditions, equity_at_time
                FROM ai_interventions
                ORDER BY ts ASC
            """)
            cols = [d[0] for d in cur.description]
            interventions = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["ts"] = d["ts"].isoformat() if d["ts"] else None
                for k in ("bot_verdicts", "param_changes", "vetoed_tickers", "critique_flags", "conditions"):
                    if isinstance(d[k], str):
                        try:
                            d[k] = json.loads(d[k])
                        except Exception:
                            pass
                interventions.append(d)

            cur.execute("""
                SELECT ts, alpaca_equity, kraken_equity, options_equity,
                       forex_equity, total_equity, regime
                FROM equity_snapshots
                ORDER BY ts ASC
            """)
            eq_cols = [d[0] for d in cur.description]
            equity_curve = []
            for row in cur.fetchall():
                d = dict(zip(eq_cols, row))
                d["ts"] = d["ts"].isoformat() if d["ts"] else None
                equity_curve.append(d)

            for iv in interventions:
                iv_ts = iv["ts"]
                if not iv_ts:
                    iv["performance_before"] = None
                    iv["performance_after"] = None
                    continue

                ts_dt = datetime.fromisoformat(iv_ts)
                before_start = (ts_dt - timedelta(hours=24)).isoformat()
                after_end = (ts_dt + timedelta(hours=24)).isoformat()

                cur.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN pnl_usd >= 0 THEN 1 ELSE 0 END) as wins,
                           COALESCE(SUM(pnl_usd), 0) as net_pnl
                    FROM kraken_trades
                    WHERE closed_at >= %s AND closed_at < %s
                """, (before_start, iv_ts))
                before_row = cur.fetchone()
                before_total = before_row[0] or 0
                iv["performance_before"] = {
                    "trades": before_total,
                    "wins": before_row[1] or 0,
                    "win_rate": round((before_row[1] or 0) / before_total * 100, 1) if before_total > 0 else None,
                    "net_pnl": round(float(before_row[2] or 0), 2),
                }

                cur.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN pnl_usd >= 0 THEN 1 ELSE 0 END) as wins,
                           COALESCE(SUM(pnl_usd), 0) as net_pnl
                    FROM kraken_trades
                    WHERE closed_at >= %s AND closed_at < %s
                """, (iv_ts, after_end))
                after_row = cur.fetchone()
                after_total = after_row[0] or 0
                iv["performance_after"] = {
                    "trades": after_total,
                    "wins": after_row[1] or 0,
                    "win_rate": round((after_row[1] or 0) / after_total * 100, 1) if after_total > 0 else None,
                    "net_pnl": round(float(after_row[2] or 0), 2),
                }

        helped = 0
        hurt = 0
        neutral = 0
        for iv in interventions:
            before = iv.get("performance_before") or {}
            after = iv.get("performance_after") or {}
            if not before.get("trades") or not after.get("trades"):
                neutral += 1
                continue
            if (after.get("net_pnl", 0) or 0) > (before.get("net_pnl", 0) or 0):
                helped += 1
                iv["impact"] = "helped"
            elif (after.get("net_pnl", 0) or 0) < (before.get("net_pnl", 0) or 0):
                hurt += 1
                iv["impact"] = "hurt"
            else:
                neutral += 1
                iv["impact"] = "neutral"

        return {
            "equity_curve": equity_curve,
            "interventions": interventions,
            "summary": {
                "total_interventions": len(interventions),
                "helped": helped,
                "hurt": hurt,
                "neutral": neutral,
            },
        }
    except Exception as exc:
        logger.warning(f"AI Impact timeline error: {exc}")
        return {"equity_curve": [], "interventions": [], "summary": {"total_interventions": 0, "helped": 0, "hurt": 0, "neutral": 0}}
    finally:
        conn.close()
