"""
health_monitor.py — Stage 4: Deterministic Strategy Health Monitor
====================================================================
Runs at 4:00 AM UTC daily for all three Kraken bots (davy-jones,
blackbeard, calypso).  Fully deterministic — no LLM calls.

Six metrics, each scored 0–100 with a HEALTHY / WARNING / CRITICAL status:

  1. recent_win_rate       — WR of the last 20 closed trades
  2. recent_profit_factor  — PF of the last 20 closed trades
  3. equity_drawdown       — (peak – current) / peak equity
  4. loss_streak           — consecutive losses counted from most recent trade
  5. fee_efficiency        — total_fees / gross_profit (last 20 trades)
  6. symbol_concentration  — largest single-symbol share of gross losses

Overall score  = weighted mean of component scores
Overall status = CRITICAL if any component is CRITICAL,
                 WARNING  if any WARNING,
                 HEALTHY  otherwise

Results are stored in kraken_health_snapshots (JSONB) and surfaced by the
portfolio report section.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

# ── constants ──────────────────────────────────────────────────────────────

LOOKBACK_N         = 20     # trades used for "recent" metrics
MIN_TRADES_FOR_PF  = 5      # PF needs at least this many trades

# Score thresholds — (min_value_for_HEALTHY, min_value_for_WARNING)
# Values below the WARNING threshold get a CRITICAL rating.
_WR_HEALTHY    = 0.50
_WR_WARNING    = 0.38

_PF_HEALTHY    = 1.20
_PF_WARNING    = 0.80

_DD_HEALTHY    = 0.05   # ≤ 5% drawdown → HEALTHY
_DD_WARNING    = 0.12   # ≤ 12%         → WARNING, else CRITICAL

_STREAK_HEALTHY = 3     # ≤ 3 consecutive losses → HEALTHY
_STREAK_WARNING = 7     # ≤ 7                    → WARNING, else CRITICAL

_FEE_HEALTHY    = 0.20  # fees / gross_profit ≤ 20% → HEALTHY
_FEE_WARNING    = 0.40  # ≤ 40% → WARNING, else CRITICAL

_CONC_HEALTHY   = 0.35  # single-symbol loss share ≤ 35% → HEALTHY
_CONC_WARNING   = 0.55  # ≤ 55% → WARNING, else CRITICAL

# Weights for overall score (must sum to 1.0)
_WEIGHTS = {
    "recent_win_rate":      0.25,
    "recent_profit_factor": 0.25,
    "equity_drawdown":      0.20,
    "loss_streak":          0.15,
    "fee_efficiency":       0.10,
    "symbol_concentration": 0.05,
}


# ── DB helpers ─────────────────────────────────────────────────────────────

def _pg_conn():
    """Return a psycopg2 connection from the trading-platform pool."""
    from db.postgres import get_conn
    return get_conn()


def _query(sql: str, params: tuple = ()) -> list[dict]:
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning(f"HealthMonitor | DB query failed: {exc}")
        return []


def _scalar(sql: str, params: tuple = (), default=None):
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row[0] if row else default
    except Exception as exc:
        logger.warning(f"HealthMonitor | DB scalar failed: {exc}")
        return default


def _ensure_table() -> None:
    # Health snapshots were retired with the scheduled health-monitor job.
    return


# ── scoring helpers ─────────────────────────────────────────────────────────

def _score_linear(value: float, healthy_thresh: float, warning_thresh: float,
                  higher_is_better: bool = True) -> tuple[int, str]:
    """
    Map a metric value to (score 0–100, status).
    higher_is_better=True: value >= healthy_thresh → HEALTHY, etc.
    higher_is_better=False: value <= healthy_thresh → HEALTHY, etc.
    """
    if higher_is_better:
        if value >= healthy_thresh:
            return 100, "HEALTHY"
        if value >= warning_thresh:
            return 60, "WARNING"
        return 20, "CRITICAL"
    else:
        if value <= healthy_thresh:
            return 100, "HEALTHY"
        if value <= warning_thresh:
            return 60, "WARNING"
        return 20, "CRITICAL"


# ── individual metric checks ────────────────────────────────────────────────

def _check_recent_win_rate(bot_id: str) -> dict:
    rows = _query(
        """
        SELECT pnl_usd
        FROM   kraken_trades
        WHERE  bot_id = %s
        ORDER  BY closed_at DESC
        LIMIT  %s
        """,
        (bot_id, LOOKBACK_N),
    )
    n = len(rows)
    if n < 3:
        return {
            "score": 50, "status": "WARNING",
            "value": None, "n": n,
            "details": f"Insufficient data ({n} trades < 3 minimum)",
        }
    wins = sum(1 for r in rows if r["pnl_usd"] > 0)
    wr = wins / n
    score, status = _score_linear(wr, _WR_HEALTHY, _WR_WARNING, higher_is_better=True)
    return {
        "score": score, "status": status,
        "value": round(wr, 4), "n": n,
        "details": f"WR={wr:.1%} over last {n} trades ({wins}W / {n-wins}L)",
    }


def _check_recent_profit_factor(bot_id: str) -> dict:
    rows = _query(
        """
        SELECT pnl_usd
        FROM   kraken_trades
        WHERE  bot_id = %s
        ORDER  BY closed_at DESC
        LIMIT  %s
        """,
        (bot_id, LOOKBACK_N),
    )
    n = len(rows)
    if n < MIN_TRADES_FOR_PF:
        return {
            "score": 50, "status": "WARNING",
            "value": None, "n": n,
            "details": f"Insufficient data ({n} trades < {MIN_TRADES_FOR_PF} minimum)",
        }
    gross_profit = sum(r["pnl_usd"] for r in rows if r["pnl_usd"] > 0)
    gross_loss   = abs(sum(r["pnl_usd"] for r in rows if r["pnl_usd"] <= 0))
    if gross_loss == 0:
        pf = 9.99
    else:
        pf = gross_profit / gross_loss
    pf = min(pf, 9.99)
    score, status = _score_linear(pf, _PF_HEALTHY, _PF_WARNING, higher_is_better=True)
    return {
        "score": score, "status": status,
        "value": round(pf, 3), "n": n,
        "details": f"PF={pf:.2f} (gross_profit=${gross_profit:.2f} / gross_loss=${gross_loss:.2f})",
    }


def _check_equity_drawdown(bot_id: str) -> dict:
    """
    Drawdown = (peak_equity - current_equity) / peak_equity.
    Uses kraken_portfolio for current equity and canonical fleet snapshots for peak.
    Falls back to kraken_portfolio starting balance if no fleet history exists.
    """
    current_eq = _scalar(
        "SELECT cash_usd + COALESCE((SELECT SUM((value->>'size_usd')::float) FROM jsonb_each(positions)), 0) FROM kraken_portfolio WHERE bot_id = %s",
        (bot_id,),
        default=None,
    )
    if current_eq is None:
        return {
            "score": 50, "status": "WARNING",
            "value": None, "details": "Portfolio data unavailable",
        }

    peak_eq = _scalar(
        """
        SELECT MAX(equity_usd)
        FROM   fleet_equity_snapshots
        WHERE  bot_id = %s
        """,
        (bot_id,),
        default=None,
    )
    if peak_eq is None or peak_eq <= 0:
        # Fallback: use starting_balance_usd
        peak_eq = _scalar(
            "SELECT starting_balance_usd FROM kraken_portfolio WHERE bot_id = %s",
            (bot_id,),
            default=100_000.0,
        ) or 100_000.0

    dd = max(0.0, (peak_eq - current_eq) / peak_eq)
    score, status = _score_linear(dd, _DD_HEALTHY, _DD_WARNING, higher_is_better=False)
    return {
        "score": score, "status": status,
        "value": round(dd, 4),
        "details": f"DD={dd:.1%}  current=${current_eq:,.2f}  peak=${peak_eq:,.2f}",
    }


def _check_loss_streak(bot_id: str) -> dict:
    """Count consecutive losses starting from the most recent trade."""
    rows = _query(
        """
        SELECT pnl_usd
        FROM   kraken_trades
        WHERE  bot_id = %s
        ORDER  BY closed_at DESC
        LIMIT  30
        """,
        (bot_id,),
    )
    streak = 0
    for r in rows:
        if r["pnl_usd"] <= 0:
            streak += 1
        else:
            break
    score, status = _score_linear(streak, _STREAK_HEALTHY, _STREAK_WARNING, higher_is_better=False)
    return {
        "score": score, "status": status,
        "value": streak,
        "details": f"{streak} consecutive loss(es) from most recent trade",
    }


def _check_fee_efficiency(bot_id: str) -> dict:
    rows = _query(
        """
        SELECT pnl_usd, COALESCE(fees_usd, 0) AS fees_usd
        FROM   kraken_trades
        WHERE  bot_id = %s
        ORDER  BY closed_at DESC
        LIMIT  %s
        """,
        (bot_id, LOOKBACK_N),
    )
    n = len(rows)
    if n < 3:
        return {
            "score": 50, "status": "WARNING",
            "value": None, "n": n,
            "details": f"Insufficient data ({n} trades)",
        }
    total_fees   = sum(r["fees_usd"] for r in rows)
    gross_profit = sum(r["pnl_usd"] for r in rows if r["pnl_usd"] > 0)
    if gross_profit <= 0:
        ratio = 1.0
    else:
        ratio = total_fees / gross_profit
    score, status = _score_linear(ratio, _FEE_HEALTHY, _FEE_WARNING, higher_is_better=False)
    return {
        "score": score, "status": status,
        "value": round(ratio, 4), "n": n,
        "details": f"Fees={ratio:.1%} of gross profit  (fees=${total_fees:.2f} / profit=${gross_profit:.2f})",
    }


def _check_symbol_concentration(bot_id: str) -> dict:
    """Largest single-symbol share of gross losses over last LOOKBACK_N trades."""
    rows = _query(
        """
        SELECT symbol, SUM(ABS(pnl_usd)) AS gross_loss
        FROM   kraken_trades
        WHERE  bot_id = %s
          AND  pnl_usd < 0
          AND  closed_at >= NOW() - INTERVAL '30 days'
        GROUP  BY symbol
        ORDER  BY gross_loss DESC
        """,
        (bot_id,),
    )
    if not rows:
        return {
            "score": 100, "status": "HEALTHY",
            "value": 0.0,
            "details": "No losing trades in last 30 days",
        }
    total_losses = sum(r["gross_loss"] for r in rows)
    top_sym      = rows[0]["symbol"]
    top_loss     = rows[0]["gross_loss"]
    concentration = top_loss / total_losses if total_losses > 0 else 0.0
    score, status = _score_linear(concentration, _CONC_HEALTHY, _CONC_WARNING, higher_is_better=False)
    return {
        "score": score, "status": status,
        "value": round(concentration, 4),
        "top_symbol": top_sym,
        "details": f"Top loser: {top_sym}={concentration:.1%} of gross losses (${top_loss:.2f} / ${total_losses:.2f})",
    }


# ── recommendations ─────────────────────────────────────────────────────────

def _generate_recommendations(metrics: dict[str, dict]) -> list[str]:
    recs: list[str] = []
    wr_m   = metrics.get("recent_win_rate", {})
    pf_m   = metrics.get("recent_profit_factor", {})
    dd_m   = metrics.get("equity_drawdown", {})
    sl_m   = metrics.get("loss_streak", {})
    fee_m  = metrics.get("fee_efficiency", {})
    conc_m = metrics.get("symbol_concentration", {})

    if wr_m.get("status") == "CRITICAL":
        recs.append("WIN RATE CRITICAL: Widen z-score entry threshold or reduce position frequency.")
    elif wr_m.get("status") == "WARNING":
        recs.append("Win rate declining — review entry signal quality; consider tightening z-score.")

    if pf_m.get("status") == "CRITICAL":
        recs.append("PROFIT FACTOR CRITICAL: Average loss far exceeds average win. Review stop-loss sizing.")
    elif pf_m.get("status") == "WARNING":
        recs.append("Profit factor below neutral — consider tighter take-profit or looser stop-loss.")

    if dd_m.get("status") == "CRITICAL":
        dd_val = dd_m.get("value", 0)
        recs.append(f"DRAWDOWN CRITICAL ({dd_val:.1%}): Consider pausing new entries until equity recovers.")
    elif dd_m.get("status") == "WARNING":
        recs.append("Drawdown elevated — regime multiplier should be reducing sizes automatically.")

    if sl_m.get("status") == "CRITICAL":
        streak = sl_m.get("value", 0)
        recs.append(f"LOSS STREAK CRITICAL ({streak} consecutive): Emergency rebalance may be warranted.")
    elif sl_m.get("status") == "WARNING":
        recs.append("Loss streak elevated — verify market regime is not in a tail-risk event.")

    if fee_m.get("status") == "CRITICAL":
        recs.append("FEE DRAG CRITICAL: Fees consuming >40% of gross profit. Increase min profit threshold.")
    elif fee_m.get("status") == "WARNING":
        recs.append("Fee drag elevated — increase MIN_NET_PROFIT_PCT or MIN_POSITION_USD.")

    if conc_m.get("status") == "WARNING":
        top = conc_m.get("top_symbol", "?")
        recs.append(f"Symbol concentration WARNING: {top} driving outsized losses — consider adding to blacklist.")
    elif conc_m.get("status") == "CRITICAL":
        top = conc_m.get("top_symbol", "?")
        recs.append(f"SYMBOL CONCENTRATION CRITICAL: {top} causing extreme loss concentration.")

    if not recs:
        recs.append("All metrics HEALTHY — strategy operating within normal parameters.")
    return recs


# ── main entry point ────────────────────────────────────────────────────────

def run_health_check(bot_id: str) -> dict[str, Any]:
    """
    Run all 6 health checks for bot_id, compute overall score/status,
    generate recommendations, persist to DB, and return the result dict.
    """
    _ensure_table()
    logger.info(f"HealthMonitor | Running health check for {bot_id}")

    metrics = {
        "recent_win_rate":      _check_recent_win_rate(bot_id),
        "recent_profit_factor": _check_recent_profit_factor(bot_id),
        "equity_drawdown":      _check_equity_drawdown(bot_id),
        "loss_streak":          _check_loss_streak(bot_id),
        "fee_efficiency":       _check_fee_efficiency(bot_id),
        "symbol_concentration": _check_symbol_concentration(bot_id),
    }

    # Weighted overall score
    overall_score = int(sum(
        metrics[key]["score"] * weight
        for key, weight in _WEIGHTS.items()
        if key in metrics
    ))

    # Overall status = worst component
    statuses = [m["status"] for m in metrics.values()]
    if "CRITICAL" in statuses:
        overall_status = "CRITICAL"
    elif "WARNING" in statuses:
        overall_status = "WARNING"
    else:
        overall_status = "HEALTHY"

    recommendations = _generate_recommendations(metrics)

    result = {
        "bot_id":         bot_id,
        "checked_at":     datetime.now(timezone.utc).isoformat(),
        "overall_score":  overall_score,
        "overall_status": overall_status,
        "metrics":        metrics,
        "recommendations": recommendations,
    }

    # Persist to DB
    _persist(bot_id, overall_score, overall_status, metrics, recommendations)

    # Adaptive params bridge: auto-tighten params on CRITICAL
    # The legacy Kraken adaptive-parameter bridge was retired with the
    # cryptocurrency fleet. Health scoring remains active and database-backed.
    bridge_actions: list[str] = []
    if bridge_actions:
        result["adaptive_bridge_actions"] = bridge_actions

    n_critical = sum(1 for m in metrics.values() if m["status"] == "CRITICAL")
    n_warning  = sum(1 for m in metrics.values() if m["status"] == "WARNING")
    logger.info(
        f"HealthMonitor | {bot_id}: score={overall_score}/100 status={overall_status} "
        f"[{n_critical} CRITICAL, {n_warning} WARNING]"
        + (f" | bridge: {len(bridge_actions)} param(s) tightened" if bridge_actions else "")
    )
    return result


def _persist(bot_id: str, overall_score: int, overall_status: str,
             metrics: dict, recommendations: list[str]) -> None:
    sql = """
    INSERT INTO kraken_health_snapshots
        (bot_id, checked_at, overall_score, overall_status, metrics, recommendations)
    VALUES (%s, NOW(), %s, %s, %s, %s)
    """
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    bot_id, overall_score, overall_status,
                    json.dumps(metrics), json.dumps(recommendations),
                ))
            conn.commit()
    except Exception as exc:
        logger.warning(f"HealthMonitor | Failed to persist snapshot for {bot_id}: {exc}")


def _apply_adaptive_bridge(bot_id: str, metrics: dict[str, dict], overall_status: str) -> list[str]:
    """
    Compatibility no-op for callers from the retired crypto fleet.
    """
    return []


def run_all_bots() -> dict[str, dict]:
    """
    Run health checks for all Kraken-based bots.
    Called by the 4:00 AM UTC scheduler job.
    """
    try:
        from config.settings import settings
    except Exception:
        pass
    bot_ids = ["davy-jones", "blackbeard", "calypso"]
    results = {}
    for bid in bot_ids:
        try:
            results[bid] = run_health_check(bid)
        except Exception as exc:
            logger.error(f"HealthMonitor | {bid}: health check failed: {exc}")
            results[bid] = {"error": str(exc)}
    return results


def get_latest_snapshot(bot_id: str) -> dict | None:
    """Load the most recent health snapshot for bot_id from DB."""
    rows = _query(
        """
        SELECT bot_id, checked_at, overall_score, overall_status, metrics, recommendations
        FROM   kraken_health_snapshots
        WHERE  bot_id = %s
        ORDER  BY checked_at DESC
        LIMIT  1
        """,
        (bot_id,),
    )
    return rows[0] if rows else None


def get_recent_snapshots(bot_id: str, limit: int = 7) -> list[dict]:
    """Load the last `limit` health snapshots for trend display."""
    return _query(
        """
        SELECT checked_at, overall_score, overall_status
        FROM   kraken_health_snapshots
        WHERE  bot_id = %s
        ORDER  BY checked_at DESC
        LIMIT  %s
        """,
        (bot_id, limit),
    )
