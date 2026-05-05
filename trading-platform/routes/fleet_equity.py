"""Single source of truth: GET /fleet/equity aggregates equity & P&L for all 8 bots."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from fastapi import APIRouter
from loguru import logger

try:
    import psycopg2
    import psycopg2.extras
    _RealDictCursor = psycopg2.extras.RealDictCursor
except ImportError:
    psycopg2 = None  # type: ignore[assignment]
    _RealDictCursor = None  # type: ignore[assignment]

fleet_equity_router = APIRouter()

_STARTING = 100_000.0
_CACHE_TTL = 30  # seconds

_cache: dict = {"data": None, "ts": 0.0}


def _empty_bot(source: str = "unavailable") -> dict:
    return {
        "equity": _STARTING,
        "pnl": 0.0,
        "pnl_pct": 0.0,
        "starting": _STARTING,
        "positions": 0,
        "source": source,
    }


def _pg_connect():
    db_url = os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url or psycopg2 is None:
        return None
    return psycopg2.connect(db_url)


def _fetch_fleet_equity() -> dict:
    errors: list[str] = []
    result: dict = {}

    # ── Bot #1 Oracle (Alpaca) ────────────────────────────────────────────────
    try:
        from execution.broker import get_account, get_positions
        acct = get_account()
        oracle_eq = float(acct.get("equity") or _STARTING)
        oracle_pnl = oracle_eq - _STARTING
        try:
            oracle_pos_count = len(get_positions())
        except Exception:
            oracle_pos_count = 0
        result["oracle"] = {
            "equity": round(oracle_eq, 2),
            "pnl": round(oracle_pnl, 2),
            "pnl_pct": round((oracle_pnl / _STARTING) * 100, 4),
            "starting": _STARTING,
            "positions": oracle_pos_count,
            "source": "alpaca",
        }
    except Exception as exc:
        errors.append(f"oracle: {exc}")
        result["oracle"] = _empty_bot("alpaca_error")

    # ── Kraken 4-bot family: Davy Jones, Blackbeard, Calypso, Apex ───────────
    KRAKEN_BOTS = [
        ("bot2_spy_qqq",    "bot2_spy_qqq",   1),
        ("blackbeard",      "blackbeard",      2),
        ("bot4_sector",     "bot4_sector",     3),
        ("bot5_defensive",  "bot5_defensive",  4),
        ("bot7_macro_bond", "bot7_macro_bond", 7),
    ]
    conn = None
    try:
        conn = _pg_connect()
        if conn is None:
            raise RuntimeError("DATABASE_URL not set")

        # Open position counts from kraken_portfolio.positions JSON.
        # kraken_trades only stores CLOSED trades; open positions live in portfolio JSON.
        import json as _json_fe
        _DB_ID_TO_KEY = {
            1: "bot2_spy_qqq",
            2: "blackbeard",
            3: "bot4_sector",
            4: "bot5_defensive",
            7: "bot7_macro_bond",
        }
        open_pos_map: dict[str, int] = {}
        with conn.cursor(cursor_factory=_RealDictCursor) as cur:
            cur.execute(
                "SELECT id, positions FROM kraken_portfolio WHERE id = ANY(%s)",
                ([1, 2, 3, 4, 7],)
            )
            for row in cur.fetchall():
                pos_raw = row["positions"] or {}
                if isinstance(pos_raw, str):
                    try:
                        pos_raw = _json_fe.loads(pos_raw)
                    except Exception:
                        pos_raw = {}
                bot_key = _DB_ID_TO_KEY.get(row["id"], "")
                if bot_key:
                    open_pos_map[bot_key] = len(pos_raw) if pos_raw else 0

        for key, bid, db_id in KRAKEN_BOTS:
            try:
                with conn.cursor(cursor_factory=_RealDictCursor) as cur:
                    cur.execute(
                        "SELECT starting_balance_usd FROM kraken_portfolio WHERE id = %s",
                        (db_id,)
                    )
                    pr = cur.fetchone()
                    starting = float(pr["starting_balance_usd"] or _STARTING) if pr else _STARTING

                    # Audit fix H5: skip stale heartbeat reads (>5 min old).
                    # If the bot died, fall back to starting balance and flag stale=True
                    # so the dashboard can render an "UNRELIABLE" badge.
                    cur.execute(
                        """
                        SELECT equity_usd,
                               EXTRACT(EPOCH FROM (NOW() - last_updated))/60 AS mins_ago
                          FROM kraken_heartbeat WHERE id = %s
                        """,
                        (db_id,)
                    )
                    hr = cur.fetchone()
                    _mins = float(hr["mins_ago"]) if hr and hr.get("mins_ago") is not None else 9999.0
                    _is_stale = _mins > 5.0
                    eq = float(hr["equity_usd"] or 0) if (hr and not _is_stale) else 0.0
                    if eq <= 0:
                        eq = starting

                pnl = eq - starting
                # H5: when heartbeat is stale, also zero position count — last-known
                # value from kraken_portfolio is just as untrustworthy as the equity.
                _pos_count = 0 if _is_stale else open_pos_map.get(key, 0)
                result[key] = {
                    "equity": round(eq, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((pnl / starting) * 100, 4) if starting > 0 else 0.0,
                    "starting": starting,
                    "positions": _pos_count,
                    "source": "kraken_db",
                    # H5: surface heartbeat freshness so the UI can flag the bot
                    "stale": bool(_is_stale),
                    "heartbeat_mins_ago": round(_mins, 1) if _mins < 9999 else None,
                }
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                result[key] = _empty_bot("kraken_db_error")

        # ── Bot #7 Poseidon ───────────────────────────────────────────────────
        try:
            with conn.cursor(cursor_factory=_RealDictCursor) as cur:
                cur.execute(
                    "SELECT equity_usd, open_positions FROM poseidon_portfolio WHERE id = 7"
                )
                psr = cur.fetchone()
            ps_eq = float(psr["equity_usd"] or _STARTING) if psr else _STARTING
            ps_positions = int(psr["open_positions"] or 0) if psr else 0
            ps_pnl = ps_eq - _STARTING
            result["poseidon"] = {
                "equity": round(ps_eq, 2),
                "pnl": round(ps_pnl, 2),
                "pnl_pct": round((ps_pnl / _STARTING) * 100, 4),
                "starting": _STARTING,
                "positions": ps_positions,
                "source": "poseidon_db",
            }
        except Exception as exc:
            errors.append(f"poseidon: {exc}")
            result["poseidon"] = _empty_bot("poseidon_db_error")

        # ── Bot #8 Kraken Current ─────────────────────────────────────────────
        try:
            with conn.cursor(cursor_factory=_RealDictCursor) as cur:
                cur.execute(
                    "SELECT equity_usd FROM kraken_current_portfolio WHERE id = 8"
                )
                kcpr = cur.fetchone()
                # H5: include heartbeat freshness so a dead bot doesn't show last-known
                # data as if it were live.
                cur.execute(
                    """
                    SELECT position_count,
                           EXTRACT(EPOCH FROM (NOW() - last_updated))/60 AS mins_ago
                      FROM kraken_heartbeat WHERE id = 8
                    """
                )
                kchb = cur.fetchone()
            _kc_mins = float(kchb["mins_ago"]) if kchb and kchb.get("mins_ago") is not None else 9999.0
            _kc_stale = _kc_mins > 5.0
            # H5: when heartbeat is stale, fall back to starting balance for equity AND
            # zero positions — kraken_current_portfolio cache is updated by the bot, so
            # if the bot is dead its equity row is also untrustworthy.
            if _kc_stale:
                kc_eq = _STARTING
                kc_positions = 0
            else:
                kc_eq = float(kcpr["equity_usd"] or _STARTING) if kcpr else _STARTING
                kc_positions = int(kchb["position_count"] or 0) if kchb else 0
            kc_pnl = kc_eq - _STARTING
            result["kraken_current"] = {
                "equity": round(kc_eq, 2),
                "pnl": round(kc_pnl, 2),
                "pnl_pct": round((kc_pnl / _STARTING) * 100, 4),
                "starting": _STARTING,
                "positions": kc_positions,
                "source": "kraken_current_db",
                "stale": bool(_kc_stale),
                "heartbeat_mins_ago": round(_kc_mins, 1) if _kc_mins < 9999 else None,
            }
        except Exception as exc:
            errors.append(f"kraken_current: {exc}")
            result["kraken_current"] = _empty_bot("kraken_current_db_error")

    except Exception as exc:
        errors.append(f"db_connect: {exc}")
        for key, _, _ in KRAKEN_BOTS:
            if key not in result:
                result[key] = _empty_bot("db_unavailable")
        if "poseidon" not in result:
            result["poseidon"] = _empty_bot("db_unavailable")
        if "kraken_current" not in result:
            result["kraken_current"] = _empty_bot("db_unavailable")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    # ── Bot #6 Navigator (Forex) ──────────────────────────────────────────────
    try:
        from routes._deps import _get_forex_engine
        fx = _get_forex_engine()
        if fx is None:
            raise RuntimeError("Forex engine not loaded")
        state = fx.get_state()
        nav_eq = float(state.get("total_equity") or state.get("paper_equity") or _STARTING)
        nav_pnl = float(state.get("total_pnl") or (nav_eq - _STARTING))
        nav_positions = int(state.get("position_count") or 0)
        result["navigator"] = {
            "equity": round(nav_eq, 2),
            "pnl": round(nav_pnl, 2),
            "pnl_pct": round((nav_pnl / _STARTING) * 100, 4),
            "starting": _STARTING,
            "positions": nav_positions,
            "source": "forex_engine",
        }
    except Exception as exc:
        errors.append(f"navigator: {exc}")
        result["navigator"] = _empty_bot("forex_error")

    # ── Fleet total ───────────────────────────────────────────────────────────
    all_bots = [
        result["oracle"],
        result["bot2_spy_qqq"],
        result["blackbeard"],
        result["bot4_sector"],
        result["bot5_defensive"],
        result["bot7_macro_bond"],
        result["navigator"],
        result["poseidon"],
        result["kraken_current"],
    ]
    fleet_equity = sum(b["equity"] for b in all_bots)
    fleet_starting = sum(b["starting"] for b in all_bots)
    fleet_pnl = fleet_equity - fleet_starting
    fleet_positions = sum(b["positions"] for b in all_bots)

    result["fleet_total"] = {
        "equity": round(fleet_equity, 2),
        "pnl": round(fleet_pnl, 2),
        "pnl_pct": round((fleet_pnl / fleet_starting) * 100, 4) if fleet_starting > 0 else 0.0,
        "starting": fleet_starting,
        "positions": fleet_positions,
        "source": "computed",
    }
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["errors"] = errors

    return result


@fleet_equity_router.get("/fleet/equity")
async def fleet_equity():
    """Return consistent equity & P&L for all 8 bots. 30-second server-side cache."""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        data = _fetch_fleet_equity()
    except Exception as exc:
        logger.error(f"[fleet/equity] Unexpected error: {exc}")
        data = {
            "oracle":          _empty_bot("error"),
            "bot2_spy_qqq":    _empty_bot("error"),
            "blackbeard":      _empty_bot("error"),
            "bot4_sector":     _empty_bot("error"),
            "bot5_defensive":  _empty_bot("error"),
            "bot7_macro_bond": _empty_bot("error"),
            "navigator":       _empty_bot("error"),
            "poseidon":        _empty_bot("error"),
            "kraken_current":  _empty_bot("error"),
            "fleet_total":     _empty_bot("error"),
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "errors":          [str(exc)],
        }

    _cache["data"] = data
    _cache["ts"] = now
    return data
