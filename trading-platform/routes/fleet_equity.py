"""Single source of truth: GET /fleet/equity aggregates equity & P&L for all 4 bots."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from loguru import logger

fleet_equity_router = APIRouter()

_STARTING = 100_000.0
_CACHE_TTL = 30  # seconds

_cache: dict = {"data": None, "ts": 0.0}


def _fetch_24h_pnl() -> dict[str, float]:
    """
    Return {bot_id: realized_pnl_last_24h}.
    Queries oracle/spy_qqq_trend from trades, jerome_macro from jerome_positions.
    Best-effort — silently returns {} on any failure.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return {}
        result: dict[str, float] = {}
        with get_conn() as conn:
            with conn.cursor() as cur:
                # oracle (momentum_equity) + spy_qqq_trend (momentum_etf)
                cur.execute("""
                    SELECT
                        CASE asset_class
                            WHEN 'momentum_equity' THEN 'oracle'
                            WHEN 'momentum_etf'    THEN 'spy_qqq_trend'
                        END AS bot_id,
                        COALESCE(SUM(realized_pnl), 0) AS pnl_24h
                    FROM trades
                    WHERE asset_class IN ('momentum_equity', 'momentum_etf')
                      AND status LIKE 'Closed_%'
                      AND closed_at > NOW() - INTERVAL '24 hours'
                      AND realized_pnl IS NOT NULL
                    GROUP BY 1
                """)
                for row in cur.fetchall():
                    if row[0]:
                        result[row[0]] = round(float(row[1]), 2)
                # jerome_macro from jerome_positions
                cur.execute("""
                    SELECT bot_id, COALESCE(SUM(realised_pnl_usd), 0) AS pnl_24h
                    FROM jerome_positions
                    WHERE bot_id = 'jerome_macro'
                      AND status = 'closed'
                      AND closed_at > NOW() - INTERVAL '24 hours'
                      AND realised_pnl_usd IS NOT NULL
                    GROUP BY bot_id
                """)
                for row in cur.fetchall():
                    result[row[0]] = round(float(row[1]), 2)
        return result
    except Exception as exc:
        logger.debug(f"fleet_equity | 24h pnl fetch failed: {exc}")
        return {}


def _fetch_24h_mark_to_market(bot_ids: list[str]) -> dict[str, float | None]:
    """Return each bot's nearest equity baseline around 24 hours ago."""
    baselines: dict[str, float | None] = {bot_id: None for bot_id in bot_ids}
    if not bot_ids:
        return baselines
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return baselines

        target = datetime.now(timezone.utc) - timedelta(hours=24)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (bot_id)
                           bot_id, equity_usd
                    FROM fleet_equity_snapshots
                    WHERE bot_id = ANY(%s)
                      AND snapshot_ts BETWEEN %s AND %s
                    ORDER BY bot_id,
                             ABS(EXTRACT(EPOCH FROM (snapshot_ts - %s)))
                    """,
                    (
                        bot_ids,
                        target - timedelta(hours=2),
                        target + timedelta(hours=2),
                        target,
                    ),
                )
                for bot_id, equity_usd in cur.fetchall():
                    baselines[bot_id] = float(equity_usd)
    except Exception as exc:
        logger.debug(f"fleet_equity | 24h mark-to-market fetch failed: {exc}")
    return baselines


def _fetch_win_rates() -> dict[str, tuple[int, int]]:
    """
    Return {bot_id: (wins_30d, total_30d)} from each bot's canonical trade table.
    Used to compute per-bot and fleet win_rate in _fetch_fleet_equity().
    Silently returns {} on any failure — win_rate is best-effort.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return {}
        counts: dict[str, tuple[int, int]] = {}
        with get_conn() as conn:
            with conn.cursor() as cur:
                # oracle (momentum_equity) and spy_qqq_trend (momentum_etf)
                cur.execute("""
                    SELECT
                        CASE
                            WHEN asset_class = 'momentum_equity' THEN 'oracle'
                            WHEN asset_class = 'momentum_etf'    THEN 'spy_qqq_trend'
                        END AS bot_id,
                        COUNT(*) FILTER (WHERE realized_pnl > 0) AS wins,
                        COUNT(*) AS total
                    FROM trades
                    WHERE asset_class IN ('momentum_equity', 'momentum_etf')
                      AND status LIKE 'Closed%'
                      AND closed_at > NOW() - INTERVAL '30 days'
                      AND realized_pnl IS NOT NULL
                      AND exit_reason NOT LIKE 'orphan%'
                      AND exit_reason != 'reconciler_race_phantom'
                      AND NOT COALESCE(is_recon_tracking, FALSE)
                    GROUP BY 1
                """)
                for row in cur.fetchall():
                    bid, wins, total = row
                    if bid:
                        counts[bid] = (int(wins), int(total))

                # jerome_macro and buck_futures from jerome_positions
                cur.execute("""
                    SELECT
                        bot_id,
                        COUNT(*) FILTER (WHERE realised_pnl_usd > 0) AS wins,
                        COUNT(*) AS total
                    FROM jerome_positions
                    WHERE bot_id IN ('jerome_macro', 'buck_futures')
                      AND status = 'closed'
                      AND closed_at > NOW() - INTERVAL '30 days'
                    GROUP BY bot_id
                """)
                for row in cur.fetchall():
                    bid, wins, total = row
                    counts[bid] = (int(wins), int(total))
        return counts
    except Exception as exc:
        logger.debug(f"fleet_equity | win_rate fetch failed: {exc}")
        return {}


def _fetch_fleet_equity() -> dict:
    """
    Primary path: read all bot portfolios from bot_portfolio in a single query.
    Raises on failure — route handler converts to HTTP 503.
    """
    try:
        from core.bot_state import get_all_portfolios
        portfolios = get_all_portfolios()  # 9 rows in one query

        if not portfolios:
            raise RuntimeError("bot_portfolio returned empty — falling back")

        result: dict = {}
        _now_utc   = datetime.now(timezone.utc)
        _STALE_SEC = 25 * 60  # bot cycles every 15 min; stale after 25 min without update

        for p in portfolios:
            bot_id = p["bot_id"]
            eq      = float(p["equity_usd"] or _STARTING)
            start   = float(p["starting_usd"] or _STARTING)
            cash    = float(p["cash_usd"] or 0.0)
            pos_raw = p.get("positions") or []
            pos_count = len(pos_raw) if isinstance(pos_raw, list) else 0
            pnl     = eq - start
            pnl_pct = round((pnl / start) * 100, 4) if start else 0.0
            upd     = p.get("last_updated")

            # Compute staleness from last_updated before converting to string
            if upd is None:
                stale = True
            elif isinstance(upd, datetime):
                upd_aware = upd if upd.tzinfo else upd.replace(tzinfo=timezone.utc)
                stale = (_now_utc - upd_aware).total_seconds() > _STALE_SEC
            else:
                try:
                    upd_dt = datetime.fromisoformat(str(upd).replace("Z", "+00:00"))
                    if upd_dt.tzinfo is None:
                        upd_dt = upd_dt.replace(tzinfo=timezone.utc)
                    stale = (_now_utc - upd_dt).total_seconds() > _STALE_SEC
                except Exception:
                    stale = False

            result[bot_id] = {
                "equity":    round(eq, 2),
                "starting":  round(start, 2),
                "cash":      round(cash, 2),
                "pnl":       round(pnl, 2),
                "pnl_pct":   pnl_pct,
                "positions": pos_count,
                "source":    "bot_portfolio",
                "last_updated": upd if isinstance(upd, str) else (upd.isoformat() if upd else None),
                "stale":     stale,
            }

        # Merge paused state from bots_state
        try:
            from core.bot_state import get_all_states
            states = {s["bot_id"]: s for s in get_all_states()}
            for bid, data in result.items():
                data["paused"] = bool(states.get(bid, {}).get("paused", False))
        except Exception as _exc:
            logger.debug(f"fleet_equity | paused merge failed: {_exc}")
            for data in result.values():
                data.setdefault("paused", False)

        # Fleet totals
        _meta_keys = {"fleet_total", "generated_at", "errors"}
        _bot_vals  = [v for k, v in result.items() if k not in _meta_keys]

        fleet_eq      = sum(b["equity"]    for b in _bot_vals)
        fleet_start   = sum(b["starting"]  for b in _bot_vals)
        fleet_pnl     = sum(b["pnl"]       for b in _bot_vals)
        fleet_pos     = sum(b["positions"] for b in _bot_vals)
        fleet_pnl_pct = round((fleet_pnl / fleet_start) * 100, 4) if fleet_start else 0.0

        result["fleet_total"] = {
            "equity":    round(fleet_eq, 2),
            "starting":  round(fleet_start, 2),
            "cash":      round(sum(b.get("cash", 0) for b in _bot_vals), 2),
            "pnl":       round(fleet_pnl, 2),
            "pnl_pct":   fleet_pnl_pct,
            "positions": fleet_pos,
            "source":    "computed",
        }

        # Inject 30-day win rates (best-effort — failure leaves win_rate=None)
        _wr = _fetch_win_rates()
        fleet_w = fleet_t = 0
        for bid, data in result.items():
            if bid in _meta_keys or bid in {"generated_at", "errors"}:
                continue
            wc = _wr.get(bid)
            if wc and wc[1] > 0:
                data["win_rate"] = round(wc[0] / wc[1], 4)
                fleet_w += wc[0]
                fleet_t += wc[1]
            else:
                data["win_rate"] = None
        result["fleet_total"]["win_rate"] = round(fleet_w / fleet_t, 4) if fleet_t > 0 else None

        # Inject 24h mark-to-market P&L. Missing history remains null so a
        # real zero is not confused with insufficient snapshot history.
        _bot_ids = [k for k in result if k not in _meta_keys]
        _baselines = _fetch_24h_mark_to_market(_bot_ids)
        _history_complete = all(_baselines.get(bid) is not None for bid in _bot_ids)
        fleet_24h_sum = 0.0
        for bid, data in result.items():
            if bid in _meta_keys or bid in {"generated_at", "errors"}:
                continue
            baseline = _baselines.get(bid)
            data["pnl_24h"] = (
                round(data["equity"] - baseline, 2)
                if baseline is not None else None
            )
            if data["pnl_24h"] is not None:
                fleet_24h_sum += data["pnl_24h"]
        result["fleet_total"]["pnl_24h"] = (
            round(fleet_24h_sum, 2) if _history_complete else None
        )
        result["fleet_total"]["pnl_24h_pct"] = (
            round(fleet_24h_sum / sum(_baselines.values()) * 100, 4)
            if _history_complete and sum(_baselines.values()) else None
        )

        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        result["errors"] = []
        return result

    except Exception as exc:
        logger.error(f"fleet_equity unified path failed: {exc}", exc_info=True)
        raise




@fleet_equity_router.get("/fleet/equity")
async def fleet_equity():
    """Return consistent equity & P&L for all 9 bots. 30-second server-side cache."""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        data = _fetch_fleet_equity()
    except Exception as exc:
        logger.error(f"[fleet/equity] Primary path failed: {exc}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="fleet_equity unavailable — bot_portfolio read failed")

    _cache["data"] = data
    _cache["ts"] = now
    return data


@fleet_equity_router.get("/fleet/equity-history")
async def fleet_equity_history():
    """
    Life-of-platform fleet equity time series for the home dashboard sparkline.
    Written nightly by the scheduler. Returns [] until the first snapshot is saved.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return {"history": []}
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT snapshot_date::text, total_equity
                    FROM fleet_equity_history
                    ORDER BY snapshot_date ASC
                """)
                rows = cur.fetchall()
        history = [{"date": str(r[0]), "total_equity": round(float(r[1]), 2)} for r in rows]
        return {"history": history}
    except Exception as exc:
        logger.debug(f"fleet_equity_history | error (non-fatal): {exc}")
        return {"history": []}


@fleet_equity_router.get("/fleet/region-status")
async def fleet_region_status():
    """
    Per-bot in-market status: true when the bot holds real (non-SGOV) strategy positions.
    Used by the pulsing world map on the home dashboard.
    """
    result: dict = {"oracle": False, "spy_qqq_trend": False, "jerome_macro": False}
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return result
        with get_conn() as conn:
            with conn.cursor() as cur:
                # oracle + spy_qqq_trend from alpaca_etf_positions
                cur.execute("""
                    SELECT bot_id, COUNT(*)
                    FROM alpaca_etf_positions
                    WHERE bot_id IN ('oracle', 'spy_qqq_trend')
                      AND status = 'open'
                      AND symbol != 'SGOV'
                    GROUP BY bot_id
                """)
                for row in cur.fetchall():
                    bid, cnt = row
                    if bid in result and cnt > 0:
                        result[bid] = True
                # jerome_macro from jerome_positions
                cur.execute("""
                    SELECT COUNT(*) FROM jerome_positions
                    WHERE bot_id = 'jerome_macro'
                      AND status = 'open'
                      AND symbol != 'SGOV'
                """)
                row = cur.fetchone()
                if row and row[0] > 0:
                    result["jerome_macro"] = True
        return result
    except Exception as exc:
        logger.debug(f"fleet_region_status | error (non-fatal): {exc}")
        return result
