"""
analysis/arc2_walk_forward.py — Nightly walk-forward validation engine.

ARC 2: Compares each bot's trailing live performance against its
pre-registered OOS envelope.  Runs nightly at 17:30 ET (Mon-Fri).

Status classifications:
  GREEN            trailing-90d Sharpe >= OOS worst-window floor
  AMBER            below floor for < 60 consecutive job-run days
  RED              below floor for >= 60 consecutive job-run days
  INSUFFICIENT_DATA < 10 closed trades in trailing 90d (no comparison made)
  DISQUALIFIED     no OOS envelope registered (jerome_macro / buck_futures)

Pre-registered human protocol (surfaced in report/Discord — NOT auto-executed):
  RED for 60d  → halve position sizing pending review
  RED for 120d → halt entries
  Human executes; system reminds.

Arc-0 ghost exclusions applied to all metric queries:
  oracle       — exclude [v1_duplicate] and reconciler_race_phantom rows
  spy_qqq      — exclude multi_lot_primary_closed secondary-lot closes
  jerome/buck  — exclude pre-v2 LLM rows via opened_at date cutoff
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger


# ── OOS envelope (pre-registered — do NOT change without a new OOS run) ───────

_OOS_ENVELOPE: dict[str, dict] = {
    "oracle": {
        "pooled_sharpe":       0.633,
        "worst_window_sharpe": -0.153,
        "worst_window":        "2021",
        "best_window_sharpe":  1.526,
        "worst_window_maxdd":  0.170,
        "oos_run_date":        "2026-07-14",
        "disqualified":        False,
        "disqualified_reason": None,
    },
    "spy_qqq_trend": {
        "pooled_sharpe":       0.862,
        "worst_window_sharpe": -1.889,
        "worst_window":        "2022",
        "best_window_sharpe":  1.411,
        "worst_window_maxdd":  0.065,
        "oos_run_date":        "2026-07-14",
        "disqualified":        False,
        "disqualified_reason": None,
    },
    "jerome_macro": {
        # Stage 4 pivot (2026-08-07): commodity-macro retired; slot repurposed to
        # Latin America ETF trend (EWZ/EWW/ECH). Old commodity envelope voided.
        # Floor seeded from Phase-1 LatAm backtest (Sharpe ~0.71); no full OOS
        # window data yet — status will read INSUFFICIENT_DATA until 10+ live
        # trades accumulate in the trailing 90d window.
        "pooled_sharpe":       0.71,
        "worst_window_sharpe": None,
        "worst_window":        None,
        "best_window_sharpe":  None,
        "worst_window_maxdd":  None,
        "oos_run_date":        "2026-08-07",
        "disqualified":        False,
        "disqualified_reason": None,
    },
    "buck_futures": {
        "pooled_sharpe":       None,
        "worst_window_sharpe": None,
        "worst_window":        None,
        "best_window_sharpe":  None,
        "worst_window_maxdd":  None,
        "oos_run_date":        None,
        "disqualified":        True,
        "disqualified_reason": "No OOS run completed — flag any live trading as anomaly",
    },
}

# ── Strategy params (as-of OOS run — drift from these fires a banner) ─────────
# Change these dicts ONLY after running a new OOS validation.

_STRATEGY_PARAMS: dict[str, dict] = {
    "oracle": {
        "strategy": "stf_v1.0_momentum_equity",
        "note":     "STF v1.0 deployed config as-of 2026-07-14 OOS run",
    },
    "spy_qqq_trend": {
        "ema_fast":          50,
        "ema_slow":          200,
        "trail_stop_pct":    0.08,
        "position_size_pct": 0.40,
        "max_deployment":    0.80,
        "min_hold_days":     5,
        "tp1_pct":           0.06,
        "tp2_pct":           0.12,
        "crisis_threshold":  -0.12,
        "max_3day_drop_pct": 0.05,
    },
    "jerome_macro": {
        # Stage 4 LatAm pivot — seeded from Phase-1 backtest; no OOS windows yet.
        "strategy":    "etf_trend_latam_v1.0",
        "universe":    ["EWZ", "EWW", "ECH"],
        "ema_fast":    50,
        "ema_slow":    200,
        "trail_stop":  0.08,
        "vol_target":  0.12,
        "vol_cap":     0.25,
        "max_pos":     3,
        "tp1_pct":     0.06,
        "tp2_pct":     0.12,
        "seeded_sharpe_floor": 0.71,
        "note": "Phase-1 backtest floor; re-run OOS after 90d live history",
    },
    "buck_futures":  {"disqualified": True},
}


def compute_params_hash(bot_id: str) -> str:
    """SHA-256[:16] of the strategy-params dict for this bot."""
    params = _STRATEGY_PARAMS.get(bot_id, {})
    return hashlib.sha256(
        json.dumps(params, sort_keys=True).encode()
    ).hexdigest()[:16]


# ── Arc-0 ghost-exclusion SQL fragments ───────────────────────────────────────

_ARC0: dict[str, str] = {
    "oracle": """
        AND status       NOT IN ('Active')
        AND closed_at    IS NOT NULL
        AND realized_pnl IS NOT NULL
        AND exit_reason  NOT LIKE '%%[v1_duplicate]%%'
        AND exit_reason  != 'reconciler_race_phantom'
        AND exit_reason  != 'stf_v1_liquidation'
    """,
    "spy_qqq_trend": """
        AND status       = 'closed'
        AND realised_pnl IS NOT NULL
        AND (exit_reason IS DISTINCT FROM 'multi_lot_primary_closed')
    """,
    "jerome_macro": """
        AND status           = 'closed'
        AND realised_pnl_usd IS NOT NULL
        AND opened_at        >= '2026-05-28 00:00:00+00'
    """,
    "buck_futures": """
        AND status           = 'closed'
        AND realised_pnl_usd IS NOT NULL
        AND opened_at        >= '2026-05-29 00:00:00+00'
    """,
}


# ── Data fetchers ─────────────────────────────────────────────────────────────

def _fetch_closed_trades(bot_id: str, days_back: int) -> list[tuple[datetime, float]]:
    """
    Returns (closed_at, pnl_usd) pairs for the trailing days_back window
    with Arc-0 ghost exclusions applied.
    """
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    arc0   = _ARC0.get(bot_id, "")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if bot_id == "oracle":
                    cur.execute(f"""
                        SELECT closed_at, realized_pnl
                        FROM   trades
                        WHERE  asset_class = 'momentum_equity'
                          AND  closed_at  >= %s
                          {arc0}
                        ORDER  BY closed_at
                    """, (cutoff,))

                elif bot_id == "spy_qqq_trend":
                    cur.execute(f"""
                        SELECT closed_at, realised_pnl::float
                        FROM   alpaca_etf_positions
                        WHERE  bot_id    = 'bot2_spy_qqq'
                          AND  closed_at >= %s
                          {arc0}
                        ORDER  BY closed_at
                    """, (cutoff,))

                elif bot_id in ("jerome_macro", "buck_futures"):
                    cur.execute(f"""
                        SELECT closed_at, realised_pnl_usd::float
                        FROM   jerome_positions
                        WHERE  bot_id    = %s
                          AND  closed_at >= %s
                          {arc0}
                        ORDER  BY closed_at
                    """, (bot_id, cutoff))

                else:
                    return []

                rows = cur.fetchall()

        result: list[tuple[datetime, float]] = []
        for row in rows:
            closed_at, pnl = row[0], row[1]
            if closed_at is None or pnl is None:
                continue
            if hasattr(closed_at, "tzinfo") and closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=timezone.utc)
            result.append((closed_at, float(pnl)))
        return result

    except Exception as exc:
        logger.warning(f"arc2_wf | _fetch_closed_trades({bot_id}, {days_back}d): {exc}")
        return []


# ── Metrics ───────────────────────────────────────────────────────────────────

def _sharpe_annualised(daily_pnls: list[float]) -> Optional[float]:
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


def _max_drawdown(daily_pnls: list[float]) -> float:
    if not daily_pnls:
        return 0.0
    STARTING = 100_000.0
    total, peak, mdd = 0.0, None, 0.0
    for p in daily_pnls:
        total += p
        if peak is None or total > peak:
            peak = total
        dd = (peak - total) / STARTING
        if dd > mdd:
            mdd = dd
    return mdd


def _compute_metrics(trades: list[tuple[datetime, float]]) -> dict[str, Any]:
    """Compute Sharpe, maxDD, WR, expectancy from (closed_at, pnl_usd) pairs."""
    if not trades:
        return {
            "trades_count":   0,
            "win_rate":       None,
            "expectancy_usd": None,
            "sharpe":         None,
            "max_drawdown":   None,
        }

    pnls  = [pnl for _, pnl in trades]
    count = len(pnls)
    wins  = sum(1 for p in pnls if p > 0)
    wr    = wins / count

    winners = [p for p in pnls if p > 0]
    losers  = [p for p in pnls if p < 0]
    avg_w   = sum(winners) / len(winners) if winners else 0.0
    avg_l   = sum(losers)  / len(losers)  if losers  else 0.0
    exp     = wr * avg_w + (1 - wr) * avg_l

    daily: dict[str, float] = {}
    for closed_at, pnl in trades:
        key = closed_at.strftime("%Y-%m-%d")
        daily[key] = daily.get(key, 0.0) + pnl
    daily_series = [daily[d] for d in sorted(daily)]

    return {
        "trades_count":   count,
        "win_rate":       round(wr, 4),
        "expectancy_usd": round(exp, 2),
        "sharpe":         _sharpe_annualised(daily_series),
        "max_drawdown":   _max_drawdown(daily_series),
    }


# ── Consecutive-days-below-floor ──────────────────────────────────────────────

def _count_consecutive_below_floor(bot_id: str, oos_floor: float) -> int:
    """
    Count consecutive trailing WF rows (most-recent first) where
    wf_sharpe_90d < oos_floor.  Drives the AMBER → RED promotion.
    """
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT wf_sharpe_90d, wf_oos_floor_sharpe
                    FROM   bot_evaluation_history
                    WHERE  bot_id    = %s
                      AND  wf_status IS NOT NULL
                    ORDER  BY snapshot_at DESC
                    LIMIT  120
                """, (bot_id,))
                rows = cur.fetchall()
        count = 0
        for (sh90, floor) in rows:
            if sh90 is not None and floor is not None and float(sh90) < float(floor):
                count += 1
            else:
                break
        return count
    except Exception as exc:
        logger.warning(f"arc2_wf | consecutive_below({bot_id}): {exc}")
        return 0


# ── Envelope reader ───────────────────────────────────────────────────────────

def _get_envelope(bot_id: str) -> dict:
    """Read oos_envelope row from DB; fall back to in-memory constant."""
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return _OOS_ENVELOPE.get(bot_id, {})
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pooled_sharpe, worst_window_sharpe, best_window_sharpe,
                           worst_window_maxdd, disqualified, disqualified_reason,
                           params_hash
                    FROM   oos_envelope
                    WHERE  bot_id = %s
                """, (bot_id,))
                row = cur.fetchone()
        if not row:
            return _OOS_ENVELOPE.get(bot_id, {})
        return {
            "pooled_sharpe":       row[0],
            "worst_window_sharpe": row[1],
            "best_window_sharpe":  row[2],
            "worst_window_maxdd":  row[3],
            "disqualified":        bool(row[4]) if row[4] is not None else False,
            "disqualified_reason": row[5],
            "params_hash":         row[6],
        }
    except Exception as exc:
        logger.warning(f"arc2_wf | _get_envelope({bot_id}): {exc}")
        return _OOS_ENVELOPE.get(bot_id, {})


# ── Status classifier ─────────────────────────────────────────────────────────

_MIN_TRADES = 10


def _classify(m90: dict, envelope: dict, consecutive: int) -> str:
    if envelope.get("disqualified"):
        return "DISQUALIFIED"
    if m90["trades_count"] < _MIN_TRADES or m90["sharpe"] is None:
        return "INSUFFICIENT_DATA"
    oos_floor = envelope.get("worst_window_sharpe")
    if oos_floor is None:
        return "INSUFFICIENT_DATA"
    if m90["sharpe"] >= oos_floor:
        return "GREEN"
    return "RED" if consecutive >= 60 else "AMBER"


# ── Main job ──────────────────────────────────────────────────────────────────

_BOT_IDS = ["oracle", "spy_qqq_trend", "jerome_macro", "buck_futures"]


def run_walk_forward_job(dry_run: bool = False) -> dict[str, dict]:
    """
    Compute trailing 30d/90d metrics for all 4 bots, classify vs OOS
    envelope, and persist to bot_evaluation_history (unless dry_run=True).
    Returns per-bot result dict.
    """
    from db.postgres import get_conn, is_pg_available

    now     = datetime.now(timezone.utc)
    results: dict[str, dict] = {}

    for bot_id in _BOT_IDS:
        envelope  = _get_envelope(bot_id)
        t90       = _fetch_closed_trades(bot_id, days_back=90)
        t30       = _fetch_closed_trades(bot_id, days_back=30)
        m90       = _compute_metrics(t90)
        m30       = _compute_metrics(t30)
        oos_floor = envelope.get("worst_window_sharpe")

        consecutive = (
            _count_consecutive_below_floor(bot_id, oos_floor)
            if oos_floor is not None and not envelope.get("disqualified")
            else 0
        )

        status = _classify(m90, envelope, consecutive)

        live_hash      = compute_params_hash(bot_id)
        stored_hash    = envelope.get("params_hash")
        params_drifted = (
            stored_hash is not None
            and live_hash != stored_hash
            and not envelope.get("disqualified")
        )

        result: dict = {
            "bot_id":               bot_id,
            "status":               status,
            "wf_sharpe_90d":        m90["sharpe"],
            "wf_sharpe_30d":        m30["sharpe"],
            "wf_maxdd_90d":         m90["max_drawdown"],
            "wf_maxdd_30d":         m30["max_drawdown"],
            "wf_trades_90d":        m90["trades_count"],
            "wf_trades_30d":        m30["trades_count"],
            "wf_win_rate_90d":      m90["win_rate"],
            "wf_win_rate_30d":      m30["win_rate"],
            "wf_expectancy_90d":    m90["expectancy_usd"],
            "wf_expectancy_30d":    m30["expectancy_usd"],
            "wf_consecutive_below": consecutive,
            "oos_floor":            oos_floor,
            "params_drifted":       params_drifted,
            "disqualified":         envelope.get("disqualified", False),
            "disqualified_reason":  envelope.get("disqualified_reason"),
        }
        results[bot_id] = result

        if status == "RED" and not dry_run:
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component=f"walk_forward/{bot_id}",
                    severity="medium",
                    error_type="wf_red_status",
                    message=(
                        f"{bot_id} RED: trailing-90d Sharpe "
                        f"{m90['sharpe']:.3f} below OOS floor {oos_floor:.3f} "
                        f"for {consecutive} day(s)"
                    ),
                )
            except Exception as exc:
                logger.warning(f"arc2_wf | degradation write ({bot_id}): {exc}")

        if not dry_run and is_pg_available():
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO bot_evaluation_history (
                                bot_id, snapshot_at, trades_count,
                                wf_sharpe_30d,      wf_sharpe_90d,
                                wf_maxdd_30d,       wf_maxdd_90d,
                                wf_trades_30d,      wf_trades_90d,
                                wf_win_rate_30d,    wf_win_rate_90d,
                                wf_expectancy_30d,  wf_expectancy_90d,
                                wf_status, wf_consecutive_below_floor,
                                wf_oos_floor_sharpe, verdict
                            ) VALUES (
                                %s,%s,%s,
                                %s,%s, %s,%s, %s,%s, %s,%s, %s,%s,
                                %s,%s,%s,%s
                            )
                        """, (
                            bot_id, now, m90["trades_count"],
                            m30["sharpe"],        m90["sharpe"],
                            m30["max_drawdown"],  m90["max_drawdown"],
                            m30["trades_count"],  m90["trades_count"],
                            m30["win_rate"],      m90["win_rate"],
                            m30["expectancy_usd"], m90["expectancy_usd"],
                            status, consecutive, oos_floor,
                            f"WF_{status}",
                        ))
                logger.info(f"arc2_wf | {bot_id} → {status} (persisted)")
            except Exception as exc:
                logger.error(f"arc2_wf | DB persist ({bot_id}): {exc}")

    logger.info(
        "arc2_wf | job complete — "
        + ", ".join(f"{b}: {r['status']}" for b, r in results.items())
    )
    return results


# ── Current-status reader ─────────────────────────────────────────────────────

def get_current_wf_status() -> list[dict]:
    """
    Most-recent walk-forward row per bot from bot_evaluation_history.
    Used by Discord brief and claude-report.  Returns [] if table not yet
    populated (first run).
    """
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (bot_id)
                        bot_id,
                        snapshot_at,
                        wf_status,
                        wf_sharpe_90d,
                        wf_sharpe_30d,
                        wf_consecutive_below_floor,
                        wf_oos_floor_sharpe,
                        wf_trades_90d,
                        wf_maxdd_90d
                    FROM   bot_evaluation_history
                    WHERE  wf_status IS NOT NULL
                    ORDER  BY bot_id, snapshot_at DESC
                """)
                rows = cur.fetchall()
        cols = (
            "bot_id", "snapshot_at", "wf_status",
            "wf_sharpe_90d", "wf_sharpe_30d",
            "wf_consecutive_below_floor", "wf_oos_floor_sharpe",
            "wf_trades_90d", "wf_maxdd_90d",
        )
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            if d.get("snapshot_at") and hasattr(d["snapshot_at"], "isoformat"):
                d["snapshot_at"] = d["snapshot_at"].isoformat()
            result.append(d)
        return result
    except Exception as exc:
        logger.warning(f"arc2_wf | get_current_wf_status: {exc}")
        return []
