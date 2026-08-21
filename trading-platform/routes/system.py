"""System routes: health, status, health-architecture, degradations, remediation."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from core.pipeline import get_last_run, reset_error_state
from core.scheduler import get_job_status
from core.market_clock import is_market_open, get_next_open
from data.cache import get_cache_stats
from data.economic_calendar import is_blackout_active
from execution.broker import get_account, get_positions
from execution.kill_switch import get_state as ks_get_state

from routes._deps import (
    EXPECTED_JOB_COUNT,
    _commentary_cache,
    _kraken_commentary_cache,
    _get_forex_engine,
)

system_router = APIRouter(tags=["System"])


@system_router.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict:
    jobs = get_job_status()
    last = get_last_run()

    job_count = len(jobs)
    last_status = last.get("last_run_status", "never")
    error_count = last.get("error_count", 0)

    if job_count < EXPECTED_JOB_COUNT:
        system_status = "degraded"
        status_reason = f"Only {job_count}/{EXPECTED_JOB_COUNT} scheduler jobs registered"
    elif last_status in ("error", "analysis_failed", "execution_failed", "kill_switch_tripped"):
        system_status = "degraded"
        status_reason = f"Last run failed ({error_count} total errors)"
    elif last_status in ("never", "never_run"):
        system_status = "online"
        status_reason = "Scheduler running — no analysis run yet today"
    else:
        system_status = "online"
        status_reason = "All systems operational"

    return {
        "status": "ok",
        "version": "3.0.0",
        "system_status": system_status,
        "status_reason": status_reason,
        "scheduler_job_count": job_count,
        "last_run_status": last_status,
        "error_count": error_count,
    }


def _get_signal_guard_status() -> dict | None:
    try:
        from analysis.signal_guard import get_last_guard_result
        return get_last_guard_result()
    except Exception:
        return None


@system_router.get("/status")
async def status() -> dict:
    from analysis.analyzer import get_groq_status as _get_groq_status, get_emergency_regime_status as _get_emergency
    from analysis.groq_budget import budget as _groq_budget
    from core.market_clock import is_alpaca_maintenance_window
    market_open = is_market_open()
    alpaca_maintenance = is_alpaca_maintenance_window()
    last_run = get_last_run()
    if not is_auto_trading_enabled():
        trading_mode = "idle"
    elif market_open:
        trading_mode = "full_market"
    else:
        trading_mode = "afterhours_crypto"
    groq_status = _get_groq_status()
    groq_status["using_fallback"] = last_run.get("groq_using_fallback", False)
    groq_status.update(_groq_budget.budget_status())

    _afterhours_crypto_positions = []
    _afterhours_unrealized_pnl = 0.0
    if trading_mode == "afterhours_crypto":
        try:
            from execution.broker import get_positions as _gah_pos
            from core.pipeline import _is_alpaca_crypto_symbol
            _all_pos = _gah_pos()
            _afterhours_crypto_positions = [
                {
                    "symbol":        p["symbol"],
                    "market_value":  p.get("market_value", 0.0),
                    "unrealized_pl": p.get("unrealized_pl", 0.0),
                    "qty":           p.get("qty", 0.0),
                }
                for p in _all_pos
                if _is_alpaca_crypto_symbol(p["symbol"])
            ]
            _afterhours_unrealized_pnl = sum(
                p["unrealized_pl"] for p in _afterhours_crypto_positions
            )
        except Exception:
            pass

    return {
        "market": {
            "is_open":   market_open,
            "next_open": get_next_open() if not market_open else None,
        },
        "kill_switch":    ks_get_state(),
        "scheduler_jobs": get_job_status(),
        "last_run":       last_run,
        "auto_trading":   is_auto_trading_enabled(),
        "cycle_interval": last_run.get("cycle_interval", "15min"),
        "trading_mode":   trading_mode,
        "afterhours_crypto": {
            "active":           trading_mode == "afterhours_crypto",
            "positions":        _afterhours_crypto_positions,
            "position_count":   len(_afterhours_crypto_positions),
            "unrealized_pnl":   round(_afterhours_unrealized_pnl, 2),
        },
        "data_cache":     get_cache_stats(),
        "blackout":       is_blackout_active(),
        "groq":           groq_status,
        "signal_guard":   _get_signal_guard_status(),
        "emergency_regime": _get_emergency(),
        "alpaca_maintenance": alpaca_maintenance,
    }


from core.scheduler import is_auto_trading_enabled


@system_router.get("/system/health-architecture")
async def system_health_architecture() -> dict:
    import json as _json, time as _time
    from pathlib import Path as _Path

    now = _time.time()
    nodes: dict[str, dict] = {}

    try:
        jobs = get_job_status()
        last = get_last_run()
        job_count = len(jobs)
        last_status = last.get("last_run_status", "never")
        last_ts = last.get("last_run_timestamp")
        age_s = (now - last_ts) if last_ts else None
        latency_ms = 0
        _mkt_open_h = False
        try:
            _mkt_open_h = is_market_open()
        except Exception:
            pass
        _groq_exhausted_h = False
        try:
            from analysis.groq_budget import budget as _gb_h
            _groq_exhausted_h = _gb_h.budget_exhausted()
        except Exception:
            pass
        if job_count < EXPECTED_JOB_COUNT:
            level = "red"
        elif last_status in ("error", "execution_failed"):
            level = "red"
        elif last_status == "analysis_failed":
            if _groq_exhausted_h:
                level = "yellow"
            else:
                level = "red" if _mkt_open_h else "yellow"
        else:
            level = "green"
        nodes["platform_core"] = {
            "label": "Main Platform Core",
            "level": level,
            "latency_ms": latency_ms,
            "data_age_s": round(age_s, 1) if age_s else None,
            "detail": f"{job_count}/{EXPECTED_JOB_COUNT} jobs · last: {last_status}",
        }
    except Exception as exc:
        nodes["platform_core"] = {"label": "Main Platform Core", "level": "red", "latency_ms": None, "data_age_s": None, "detail": str(exc)}

    _acct_cache: dict | None = None
    try:
        t0 = _time.time()
        _acct_cache = get_account()
        latency = round((_time.time() - t0) * 1000)
        if latency > 1000:
            level = "red"
        elif latency > 200:
            level = "yellow"
        else:
            level = "green"
        nodes["alpaca_api"] = {
            "label": "Alpaca API (US Equities)",
            "level": level,
            "latency_ms": latency,
            "data_age_s": 0,
            "detail": f"Equity ${_acct_cache['equity']:,.2f}",
        }
    except Exception as exc:
        nodes["alpaca_api"] = {"label": "Alpaca API (US Equities)", "level": "red", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    try:
        from datetime import datetime as _dt, timezone as _tz
        import psycopg2 as _pg2, psycopg2.extras as _pg2x, os as _kos
        _kdburl = _kos.environ.get("DATABASE_URL")
        _ARCH_BOTS: list = []
        _bot_levels: list[str] = []
        _bot_detail_parts: list[str] = []

        if _kdburl:
            _kpgconn = _pg2.connect(_kdburl)
            try:
                for _arch_idx, _arch_bot_id, _arch_label in _ARCH_BOTS:
                    try:
                        with _kpgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _kc:
                            _kc.execute(
                                "SELECT status, last_heartbeat, paused, error_message "
                                "FROM bots_state WHERE bot_id = %s",
                                (_arch_bot_id,)
                            )
                            _kr = _kc.fetchone()
                        if _kr:
                            _klast = _kr["last_heartbeat"]
                            _kage = (now - _klast.timestamp()) if _klast else None
                            _kstatus = _kr["status"] or "unknown"
                            _kpaused = bool(_kr.get("paused", False))
                            if _kpaused:
                                _blevel = "yellow"
                            elif _kstatus == "error":
                                _blevel = "red"
                            elif _kage is None:
                                _blevel = "yellow"
                            elif _kage < 600:
                                _blevel = "green"
                            elif _kage < 1800:
                                _blevel = "yellow"
                            else:
                                _blevel = "red"
                            _bot_levels.append(_blevel)
                            _age_str = f"{int(_kage)}s" if _kage else "no hb"
                            _bot_detail_parts.append(f"{_arch_label}: {_kstatus} ({_age_str})")
                            nodes[f"wild_{_arch_bot_id}"] = {
                                "label": f"Wild Bot: {_arch_label}",
                                "level": _blevel,
                                "latency_ms": None,
                                "data_age_s": round(_kage, 1) if _kage else None,
                                "detail": f"Status: {_kstatus} · {_age_str} ago"
                                          + (" · paused" if _kpaused else ""),
                            }
                        else:
                            _bot_levels.append("yellow")
                            _bot_detail_parts.append(f"{_arch_label}: not started")
                            nodes[f"wild_{_arch_bot_id}"] = {
                                "label": f"Wild Bot: {_arch_label}",
                                "level": "yellow", "latency_ms": None,
                                "data_age_s": None, "detail": "Bot not started",
                            }
                    except Exception as _bexc:
                        _bot_levels.append("red")
                        _bot_detail_parts.append(f"{_arch_label}: error")
                        nodes[f"wild_{_arch_bot_id}"] = {
                            "label": f"Wild Bot: {_arch_label}",
                            "level": "red", "latency_ms": None,
                            "data_age_s": None, "detail": str(_bexc)[:60],
                        }
            finally:
                _kpgconn.close()

        if not _bot_levels:
            # DATABASE_URL unavailable — cannot assess fleet status
            _summary_level = "yellow"
        else:
            _summary_level = "red" if "red" in _bot_levels else ("yellow" if "yellow" in _bot_levels else "green")
        _n_ok = sum(1 for l in _bot_levels if l == "green")
        nodes["wild_crypto_fleet"] = {
            "label": "Wild Crypto Bots (4 bots)",
            "level": _summary_level,
            "latency_ms": None,
            "data_age_s": None,
            "detail": (
                f"{_n_ok}/{len(_ARCH_BOTS)} bots healthy · " + " | ".join(_bot_detail_parts)
                if _bot_levels else "DB unavailable — fleet status unknown"
            ),
        }
    except Exception as exc:
        nodes["wild_crypto_fleet"] = {"label": "Wild Crypto Bots (4 bots)", "level": "red", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    try:
        caches = get_cache_stats()
        cached_count = sum(1 for c in caches if c.get("cached"))
        ages = [c["age_seconds"] for c in caches if c.get("cached") and c["age_seconds"] >= 0]
        oldest = max(ages) if ages else None
        _mkt_open_dp = False
        try:
            _mkt_open_dp = is_market_open()
        except Exception:
            pass
        if oldest is not None and oldest > 1800 and _mkt_open_dp:
            level = "red"
        elif oldest is not None and oldest > 900:
            level = "yellow"
        elif cached_count == 0:
            level = "yellow"
        else:
            level = "green"
        nodes["data_pipeline"] = {
            "label": "Data Pipeline (fetch_data)",
            "level": level,
            "latency_ms": None,
            "data_age_s": round(oldest, 1) if oldest else None,
            "detail": f"{cached_count}/{len(caches)} feeds cached" if cached_count else "No data cached yet",
        }
    except Exception as exc:
        nodes["data_pipeline"] = {"label": "Data Pipeline (fetch_data)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    try:
        positions = get_positions()
        acct_dict = _acct_cache if _acct_cache is not None else get_account()
        equity_val = float(acct_dict["equity"])
        # Use the larger of current equity or the bot's intended starting capital ($100k).
        # This prevents a bot that has taken losses from generating false-positive
        # concentration alarms simply because its account shrank.
        reference_equity = max(equity_val, 100_000.0)
        total_market = sum(float(p["market_value"]) for p in positions) if positions else 0
        _EXEMPT_SYMBOLS = {"SGOV", "JEPQ"}
        active_positions = [p for p in positions if p.get("symbol", "") not in _EXEMPT_SYMBOLS]
        max_single = max((float(p["market_value"]) for p in active_positions), default=0)
        if len(active_positions) == 0 or equity_val < 100:
            level = "green"
            max_pct = 0.0
        else:
            max_pct = (max_single / reference_equity * 100) if reference_equity > 0 else 0
            if max_pct > 20.0:
                level = "red"
            elif max_pct > 15.0:
                level = "yellow"
            else:
                level = "green"
        _exempt_count = len(positions) - len(active_positions)
        _detail_parts = [f"Max active position: {max_pct:.1f}%", f"{len(active_positions)} active holding(s)"]
        if _exempt_count:
            _detail_parts.append(f"{_exempt_count} exempt (SGOV/JEPQ vault)")
        nodes["equity_manager"] = {
            "label": "Equity Manager (15% Enforcer)",
            "level": level,
            "latency_ms": None,
            "data_age_s": 0,
            "detail": " · ".join(_detail_parts),
        }
    except Exception as exc:
        nodes["equity_manager"] = {"label": "Equity Manager (15% Enforcer)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM execution_post_mortems")
                pm_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM hardcoded_rules WHERE active = TRUE")
                rule_count = cur.fetchone()[0]
                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT ticker, regime, exit_reason
                        FROM execution_post_mortems
                        WHERE pnl_pct < 0
                        GROUP BY ticker, regime, exit_reason
                        HAVING COUNT(*) BETWEEN 1 AND 2
                    ) sub
                """)
                pending_count = cur.fetchone()[0]
        if pm_count == 0:
            level = "yellow"
            detail = f"No post-mortems yet · {rule_count} rules · awaiting first loss cycle"
        else:
            level = "green"
            detail = f"{pm_count} post-mortems · {rule_count} permanent rules · {pending_count} patterns pending"
        nodes["rag_engine"] = {
            "label": "RAG Learning Engine (4-Phase)",
            "level": level,
            "latency_ms": None,
            "data_age_s": None,
            "detail": detail,
        }
    except Exception as exc:
        nodes["rag_engine"] = {
            "label": "RAG Learning Engine (4-Phase)",
            "level": "red",
            "latency_ms": None,
            "data_age_s": None,
            "detail": f"DB error: {str(exc)[:70]}",
        }

    try:
        import psycopg2 as _pg2_fx, os as _os_fx
        _db_fx = _os_fx.environ.get("DATABASE_URL")
        _fx_detail = "No heartbeat yet"
        _fx_level = "yellow"
        if _db_fx:
            _fx_conn = _pg2_fx.connect(_db_fx)
            try:
                with _fx_conn.cursor() as _fxc:
                    _fxc.execute(
                        "SELECT status, last_heartbeat, paused, equity_usd, open_positions "
                        "FROM bots_state WHERE bot_id = 'forex_gump'"
                    )
                    _fx_row = _fxc.fetchone()
                    if _fx_row:
                        _fx_status, _fx_hb, _fx_paused, _fx_eq, _fx_pos = _fx_row
                        _fx_eq = float(_fx_eq or 0)
                        _fx_pos = int(_fx_pos or 0)
                        _fx_age = (now - _fx_hb.timestamp()) if _fx_hb else None
                        if _fx_paused:
                            _fx_level = "yellow"
                            _fx_detail = f"Paused · ${_fx_eq:,.0f} · {_fx_pos} positions"
                        elif _fx_age is not None and _fx_age < 600:
                            _fx_level = "green"
                            _fx_detail = f"{_fx_status} · ${_fx_eq:,.0f} · {_fx_pos} positions"
                        else:
                            _fx_level = "yellow"
                            _fx_detail = f"{_fx_status} · ${_fx_eq:,.0f} · stale {int(_fx_age or 0)}s"
            finally:
                _fx_conn.close()
        nodes["forex_bot"] = {
            "label": "Forex Gump (Forex Bot)",
            "level": _fx_level,
            "latency_ms": None,
            "data_age_s": None,
            "detail": _fx_detail,
        }
    except Exception as exc:
        nodes["forex_bot"] = {"label": "Forex Gump (Forex Bot)", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    try:
        from notifications.telegram import is_configured as _tg_ok
        from notifications.discord import is_configured as _dc_ok
        from notifications.alert_manager import get_queue_status as _aq_status
        _alert_st = _aq_status()
        _tg = _alert_st.get("telegram_configured", False)
        _dc = _alert_st.get("discord_configured", False)
        _q_size = _alert_st.get("queue_size", 0)
        _channels = []
        if _tg: _channels.append("TG")
        if _dc: _channels.append("DC")
        _ch_str = "+".join(_channels) if _channels else "No channels"
        nodes["alert_system"] = {
            "label": "Alert System (Telegram/Discord)",
            "level": "green" if _channels else "yellow",
            "latency_ms": None,
            "data_age_s": None,
            "detail": f"{_ch_str} · {_q_size} queued · {_alert_st['config'].get('interval_minutes', 60)}min interval",
        }
    except Exception as exc:
        nodes["alert_system"] = {"label": "Alert System", "level": "yellow", "latency_ms": None, "data_age_s": None, "detail": str(exc)[:80]}

    # Phase 2 health contract: expose only the live Alpaca ETF fleet and
    # analysis/support services. Retired broker and strategy nodes must not
    # leak into the dashboard response.
    for _retired_key in (
        "wild_crypto_fleet", "forex_bot", "options_bot", "kraken_api",
        "rag_engine", "kraken_davy_jones", "kraken_blackbeard",
        "kraken_poseidon", "kraken_kraken_current",
    ):
        nodes.pop(_retired_key, None)
    _fleet_level = nodes.get("platform_core", {}).get("level", "yellow")
    for _bot_key, _bot_label in (
        ("bot_oracle", "Oracle / US Core"),
        ("bot_spy_qqq", "SPY/QQQ Trend / Asia-Pacific"),
        ("bot_jerome", "Jerome Macro / Emerging Markets"),
    ):
        nodes[_bot_key] = {
            "label": _bot_label,
            "level": _fleet_level,
            "latency_ms": None,
            "data_age_s": nodes.get("platform_core", {}).get("data_age_s"),
            "detail": "Active Alpaca ETF fleet · status follows platform core",
        }

    return {
        "timestamp": now,
        "nodes": nodes,
    }
@system_router.get("/system/degradations")
async def system_degradations_endpoint(
    hours: int = 48,
    component: str | None = None,
    unresolved_only: bool = False,
    limit: int = 100,
) -> dict:
    from core.degradation_tracker import get_recent_events, get_stats
    events = get_recent_events(limit=limit, hours=hours, component=component, unresolved_only=unresolved_only)
    stats = get_stats(hours=hours)
    return {
        "window_hours": hours,
        "total": len(events),
        "stats": stats,
        "events": events,
    }


@system_router.get("/system/degradations/report")
async def system_degradations_report(hours: int = 48) -> dict:
    import json as _json
    from pathlib import Path as _Path
    from core.degradation_tracker import build_bug_report

    live_health: dict | None = None
    groq_budget: dict | None = None
    kraken_status: dict | None = None
    market_open_flag: bool | None = None
    market_next_open: str | None = None
    heal_log_data: list[dict] | None = None

    try:
        import asyncio
        live_health = await asyncio.wait_for(system_health_architecture(), timeout=10.0)
    except Exception:
        pass

    try:
        from analysis.groq_budget import budget as _gb
        groq_budget = _gb.budget_status()
        groq_budget["budget_exhausted"] = _gb.budget_exhausted()
        groq_budget["daily_limit"] = groq_budget.get("token_budget_total", 100000)
    except Exception:
        pass

    try:
        import psycopg2 as _pg2dr, psycopg2.extras as _pg2xdr, os as _osdr
        _dburldr = _osdr.environ.get("DATABASE_URL")
        if _dburldr:
            _drconn = _pg2dr.connect(_dburldr)
            try:
                with _drconn.cursor(cursor_factory=_pg2xdr.RealDictCursor) as _drc:
                    _drc.execute("SELECT status, equity_usd, cycle_count, last_updated FROM kraken_heartbeat WHERE id = 1")
                    _drrow = _drc.fetchone()
                    if _drrow:
                        kraken_status = {
                            "status":           _drrow["status"],
                            "total_equity_usd": _drrow["equity_usd"],
                            "cycle_count":      _drrow["cycle_count"],
                            "last_updated":     _drrow["last_updated"].isoformat() if _drrow["last_updated"] else None,
                        }
            finally:
                _drconn.close()
    except Exception:
        pass

    try:
        market_open_flag = is_market_open()
        if not market_open_flag:
            nxt = get_next_open()
            market_next_open = str(nxt)[:19].replace("T", " ") + " UTC" if nxt else None
    except Exception:
        pass

    try:
        with _heal_lock:
            heal_log_data = list(_heal_log[:20])
    except Exception:
        pass

    report = build_bug_report(
        hours=hours,
        live_health=live_health,
        groq_budget=groq_budget,
        kraken_status=kraken_status,
        market_open=market_open_flag,
        market_next_open=market_next_open,
        heal_log=heal_log_data,
    )
    return {"hours": hours, "report": report}


@system_router.post("/system/degradations/record")
async def record_manual_degradation(
    component: str,
    severity: str,
    error_type: str,
    message: str,
    detail: str | None = None,
) -> dict:
    from core.degradation_tracker import record_degradation
    ok = record_degradation(
        component=component,
        severity=severity,
        error_type=error_type,
        message=message,
        detail=detail,
    )
    return {"recorded": ok}


@system_router.get("/status/summary", tags=["System"])
async def status_summary() -> dict:
    """Bulk endpoint returning all frequently polled data points in one call."""
    from notifications import alert_manager as _alert_mgr
    from core.market_clock import is_alpaca_maintenance_window
    from core.scheduler import is_auto_trading_enabled

    jobs = get_job_status()
    last = get_last_run()
    job_count = len(jobs)
    last_status = last.get("last_run_status", "never_run")
    error_count = last.get("error_count", 0)
    run_count = last.get("run_count", 0)

    if job_count < EXPECTED_JOB_COUNT:
        system_status = "degraded"
    elif last_status in ("error", "analysis_failed", "execution_failed", "kill_switch_tripped"):
        system_status = "degraded"
    else:
        system_status = "online"

    portfolio_totals = {"equity": 0, "cash": 0, "buying_power": 0}
    try:
        acct = get_account()
        portfolio_totals = {
            "equity": float(acct.get("equity", 0)),
            "cash": float(acct.get("cash", 0)),
            "buying_power": float(acct.get("buying_power", 0)),
        }
    except Exception:
        pass

    position_count = 0
    try:
        positions = get_positions()
        position_count = len(positions) if positions else 0
    except Exception:
        pass

    bot_statuses = {}
    try:
        from routes._deps import KRAKEN_BOT_PROFILES
        for bot_id, profile in KRAKEN_BOT_PROFILES.items():
            bot_status = "running"
            try:
                from kraken_bot.engine import get_kraken_engine
                eng = get_kraken_engine(bot_id)
                if eng and hasattr(eng, "paused") and eng.paused:
                    bot_status = "paused"
            except Exception:
                pass
            bot_statuses[bot_id] = {
                "display_name": profile["display_name"],
                "status": bot_status,
            }
    except Exception:
        pass

    try:
        import psycopg2 as _pg2_apex, os as _os_apex
        _db_apex = _os_apex.environ.get("DATABASE_URL")
        _apex_status = "unknown"
        if _db_apex:
            _apex_conn = _pg2_apex.connect(_db_apex)
            try:
                with _apex_conn.cursor() as _apexc:
                    _apexc.execute("SELECT status FROM kraken_heartbeat WHERE id = 4")
                    _apexr = _apexc.fetchone()
                    if _apexr:
                        _apex_status = str(_apexr[0] or "running").lower()
            finally:
                _apex_conn.close()
        bot_statuses["apex-predator"] = {"display_name": "Apex Predator \u2014 Crypto Momentum", "status": _apex_status}
    except Exception as _apex_exc:
        logger.debug(f"[STATUS] Apex Predator state unavailable: {_apex_exc}")
        bot_statuses["apex-predator"] = {"display_name": "Apex Predator \u2014 Crypto Momentum", "status": "unknown"}

    try:
        fx = _get_forex_engine()
        if fx:
            fx_state = fx.get_state()
            bot_statuses["navigator"] = {
                "display_name": "Navigator",
                "status": "paused" if fx_state.get("paused") else "running",
            }
    except Exception:
        bot_statuses["navigator"] = {"display_name": "Navigator", "status": "unknown"}


    alert_queue_size = 0
    try:
        q_status = _alert_mgr.get_queue_status()
        alert_queue_size = q_status.get("queue_size", 0)
    except Exception:
        pass

    market_open = False
    next_market_open = None
    try:
        market_open = is_market_open()
        if not market_open:
            next_market_open = get_next_open()
    except Exception:
        pass

    ks = {"tripped": False}
    try:
        ks = ks_get_state()
    except Exception:
        pass

    alpaca_maintenance = False
    try:
        alpaca_maintenance = is_alpaca_maintenance_window()
    except Exception:
        pass

    groq_info: dict[str, Any] | None = None
    try:
        from analysis.analyzer import get_groq_status as _get_groq_status
        from analysis.groq_budget import budget as _groq_budget
        groq_info = _get_groq_status()
        groq_info["using_fallback"] = last.get("groq_using_fallback", False)
        groq_info.update(_groq_budget.budget_status())
    except Exception:
        pass

    emergency_regime: dict[str, Any] | None = None
    try:
        from analysis.analyzer import get_emergency_regime_status as _get_emergency
        emergency_regime = _get_emergency()
    except Exception:
        pass

    if not is_auto_trading_enabled():
        trading_mode = "idle"
    elif market_open:
        trading_mode = "full_market"
    else:
        trading_mode = "afterhours_crypto"

    _ah_summary: dict = {
        "active":         trading_mode == "afterhours_crypto",
        "position_count": 0,
        "unrealized_pnl": 0.0,
        "positions":      [],
    }
    if trading_mode == "afterhours_crypto":
        try:
            from execution.broker import get_positions as _gah_pos2
            from core.pipeline import _is_alpaca_crypto_symbol as _is_ah_sym2
            _ah_pos2 = _gah_pos2()
            _ah_crypto2 = [
                {
                    "symbol":        p["symbol"],
                    "market_value":  p.get("market_value", 0.0),
                    "unrealized_pl": p.get("unrealized_pl", 0.0),
                    "qty":           p.get("qty", 0.0),
                }
                for p in _ah_pos2
                if _is_ah_sym2(p["symbol"])
            ]
            _ah_summary["position_count"] = len(_ah_crypto2)
            _ah_summary["unrealized_pnl"] = round(sum(p["unrealized_pl"] for p in _ah_crypto2), 2)
            _ah_summary["positions"] = _ah_crypto2
        except Exception:
            pass

    return {
        "system_health": {
            "system_status": system_status,
            "scheduler_job_count": job_count,
            "last_run_status": last_status,
            "error_count": error_count,
            "run_count": run_count,
        },
        "portfolio_totals": portfolio_totals,
        "position_count": position_count,
        "bot_statuses": bot_statuses,
        "alert_queue_size": alert_queue_size,
        "market_open": market_open,
        "next_market_open": next_market_open,
        "kill_switch_tripped": ks.get("tripped", False),
        "alpaca_maintenance": alpaca_maintenance,
        "trading_mode": trading_mode,
        "afterhours_crypto": _ah_summary,
        "groq": groq_info,
        "emergency_regime": emergency_regime,
        "scheduler_jobs": jobs,
        "auto_trading": is_auto_trading_enabled(),
    }


@system_router.get("/regime/retrospective")
async def regime_retrospective(days: int = 10) -> dict:
    """
    Compare old regime thresholds (VIX>25 = Bear) vs new three-condition gate
    (Bear requires VIX>30 AND SPY 20d return negative AND SPY below SMA-50)
    over the last `days` trading days.
    """
    import datetime
    try:
        import yfinance as yf
    except ImportError:
        raise HTTPException(status_code=503, detail="yfinance not available")

    try:
        lookback_days = max(days + 60, 80)   # need 50+ bars of history for SMA-50
        end   = datetime.datetime.utcnow()
        start = end - datetime.timedelta(days=lookback_days)

        spy_hist = yf.download("SPY", start=start, end=end, progress=False)
        vix_hist = yf.download("^VIX", start=start, end=end, progress=False)

        if spy_hist.empty or vix_hist.empty:
            raise HTTPException(status_code=503, detail="Could not fetch SPY / VIX history")

        spy_close = spy_hist["Close"].squeeze()
        vix_close = vix_hist["Close"].squeeze()

        # Align on common dates
        common_dates = spy_close.index.intersection(vix_close.index)
        spy_close = spy_close.loc[common_dates]
        vix_close = vix_close.loc[common_dates]

        # Keep only last `days` bars
        spy_close = spy_close.iloc[-days:]
        vix_close = vix_close.iloc[-days:]

        # Precompute SMA-50 and 20-day returns for the full aligned series
        spy_full = spy_hist["Close"].squeeze().loc[common_dates]

        rows = []
        for i, (date, spy_px) in enumerate(spy_close.items()):
            spy_px    = float(spy_px)
            vix       = float(vix_close.loc[date])

            # position in the full aligned series
            full_idx  = list(spy_full.index).index(date)

            # 20-day return
            if full_idx >= 20:
                spy_ret20 = (spy_px / float(spy_full.iloc[full_idx - 20]) - 1) * 100
            else:
                spy_ret20 = None

            # SMA-50
            if full_idx >= 50:
                sma_50 = float(spy_full.iloc[full_idx - 49: full_idx + 1].mean())
                above_sma50 = spy_px > sma_50
            else:
                sma_50, above_sma50 = None, None

            # ── Old threshold: VIX > 25 → Bear, VIX > 18 → Sideways, else Bull
            if vix > 25:
                old_regime = "Bear"
            elif vix > 18:
                old_regime = "Sideways"
            else:
                old_regime = "Bull"

            # ── New threshold: all three conditions required for Bear
            bear_conditions_met = (
                vix > 30
                and (spy_ret20 is not None and spy_ret20 < 0)
                and (above_sma50 is False)
            )
            bull_conditions_met = (
                vix < 20
                and (spy_ret20 is not None and spy_ret20 >= 0)
                and (above_sma50 is True)
            )
            if bear_conditions_met:
                new_regime = "Bear"
            elif bull_conditions_met:
                new_regime = "Bull"
            else:
                new_regime = "Sideways"

            rows.append({
                "date":          date.strftime("%Y-%m-%d"),
                "spy_price":     round(spy_px, 2),
                "vix":           round(vix, 2),
                "spy_ret_20d":   round(spy_ret20, 2) if spy_ret20 is not None else None,
                "sma_50":        round(sma_50, 2) if sma_50 is not None else None,
                "above_sma50":   above_sma50,
                "old_regime":    old_regime,
                "new_regime":    new_regime,
                "regime_changed": old_regime != new_regime,
            })

        changes = sum(1 for r in rows if r["regime_changed"])
        return {
            "days_analysed": len(rows),
            "regime_changes": changes,
            "old_threshold": "VIX>25→Bear | VIX>18→Sideways | else Bull",
            "new_threshold": "Bear=ALL(VIX>30, SPY_20d<0, SPY<SMA-50) | Bull=ALL(VIX<20, SPY_20d≥0, SPY>SMA-50) | else Sideways",
            "rows": rows,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@system_router.get("/fleet/weekly-review")
async def fleet_weekly_review():
    """
    Monday morning 5-query fleet health check.
    Run this every week before market open.
    """
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"error": "db_unavailable"}

    result = {}

    with get_conn() as conn:
        with conn.cursor() as cur:

            # 1 — Fleet heartbeat
            cur.execute("""
                SELECT id, bot_id, equity_usd, status, bot_paused, last_updated
                FROM kraken_heartbeat
                ORDER BY id
            """)
            rows = cur.fetchall()
            result["fleet_heartbeat"] = [
                {
                    "id": r[0], "bot_id": r[1],
                    "equity_usd": float(r[2]) if r[2] else 0,
                    "status": r[3], "paused": bool(r[4]),
                    "last_updated": r[5].isoformat() if r[5] else None,
                    "stale": (
                        r[5] is not None and
                        (datetime.now(timezone.utc) - r[5]).total_seconds() > 3600
                    ),
                }
                for r in rows
            ]

            # 2 — Oracle trades this week
            cur.execute("""
                SELECT
                    status,
                    COUNT(*) as count,
                    ROUND(AVG(realized_pnl)::numeric, 2) as avg_pnl,
                    ROUND(SUM(realized_pnl)::numeric, 2) as total_pnl
                FROM trades
                WHERE closed_at > NOW() - INTERVAL '7 days'
                AND status IN ('Closed_Win', 'Closed_Loss')
                GROUP BY status
            """)
            rows = cur.fetchall()
            result["oracle_week"] = [
                {"status": r[0], "count": r[1],
                 "avg_pnl": float(r[2]) if r[2] else None,
                 "total_pnl": float(r[3]) if r[3] else None}
                for r in rows
            ]

            # 3 — Vault ledger
            cur.execute("""
                SELECT hwm, total_vaulted_usd, total_sweeps, last_sweep_date
                FROM vault_ledger WHERE id = 1
            """)
            row = cur.fetchone()
            result["vault"] = {
                "hwm": float(row[0]) if row else 0,
                "total_vaulted": float(row[1]) if row else 0,
                "total_sweeps": row[2] if row else 0,
                "last_sweep": str(row[3]) if row else None,
            } if row else {}

            # 4 — Top 5 losses this week
            cur.execute("""
                SELECT ticker, realized_pnl, exit_reason,
                       time_in_trade_hours, closed_at
                FROM trades
                WHERE status = 'Closed_Loss'
                AND closed_at > NOW() - INTERVAL '7 days'
                AND realized_pnl IS NOT NULL
                ORDER BY realized_pnl ASC
                LIMIT 5
            """)
            rows = cur.fetchall()
            result["top_losses_week"] = [
                {
                    "ticker": r[0],
                    "realized_pnl": float(r[1]) if r[1] else None,
                    "exit_reason": r[2],
                    "hold_hours": float(r[3]) if r[3] else None,
                    "closed_at": r[4].isoformat() if r[4] else None,
                }
                for r in rows
            ]

            # 5 — Math auditor CRITICAL count
            cur.execute("""
                SELECT COUNT(DISTINCT (bot_id, formula_name)) as critical_count
                FROM math_audit_log
                WHERE status = 'FAIL'
                AND audit_timestamp > NOW() - INTERVAL '24 hours'
            """)
            row = cur.fetchone()
            result["math_audit_criticals"] = int(row[0]) if row else 0

            # 6 — Current canonical fleet equity
            cur.execute("""
                SELECT
                    COALESCE(SUM(equity_usd), 0),
                    COALESCE(SUM(equity_usd) FILTER (WHERE bot_id = 'oracle'), 0)
                FROM fleet_equity_snapshots
                WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                  AND snapshot_ts = (
                      SELECT MAX(snapshot_ts)
                      FROM fleet_equity_snapshots
                      WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                  )
            """)
            eq_row = cur.fetchone()
            total_eq  = float(eq_row[0]) if eq_row and eq_row[0] else 0.0
            oracle_eq = float(eq_row[1]) if eq_row and eq_row[1] else 0.0
            nav_eq    = 0.0

    # Fleet equity summary (oracle_eq / nav_eq captured inside cursor block above)
    kraken_eq = sum(
        b["equity_usd"] for b in result["fleet_heartbeat"]
        if b["bot_id"] not in ("navigator",)
    )
    kraken_eq = max(0.0, total_eq - oracle_eq)
    from core.fleet_capital import fleet_starting_capital
    _sc = fleet_starting_capital()
    result["fleet_summary"] = {
        "oracle_equity":    oracle_eq,
        "navigator_equity": nav_eq,
        "kraken_equity":    kraken_eq,
        "total_equity":     total_eq,
        "starting_capital": _sc,
        "pnl_usd":  round(total_eq - _sc, 2),
        "pnl_pct":  round((total_eq - _sc) / _sc * 100, 2),
        "bots_paused": sum(1 for b in result["fleet_heartbeat"] if b["paused"]),
        "bots_stale":  sum(1 for b in result["fleet_heartbeat"] if b["stale"]),
    }

    # ── 30-Day Benchmark Comparison ───────────────────────────────────────────
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT snapshot_date, spy_close, qqq_close, agg_close, fleet_equity
                    FROM benchmark_snapshots
                    WHERE snapshot_date >= CURRENT_DATE - INTERVAL '32 days'
                    ORDER BY snapshot_date ASC
                """)
                bm_rows = cur.fetchall()

        if len(bm_rows) >= 2:
            oldest = bm_rows[0]
            newest = bm_rows[-1]

            def _pct(new, old):
                if old and new and float(old) != 0:
                    return round((float(new) - float(old)) / float(old) * 100, 2)
                return None

            spy_30d   = _pct(newest[1], oldest[1])
            qqq_30d   = _pct(newest[2], oldest[2])
            agg_30d   = _pct(newest[3], oldest[3])
            fleet_30d = _pct(newest[4], oldest[4])

            result["benchmark_30d"] = {
                "period_start":   str(oldest[0]),
                "period_end":     str(newest[0]),
                "spy_return_pct":    spy_30d,
                "qqq_return_pct":    qqq_30d,
                "agg_return_pct":    agg_30d,
                "fleet_return_pct":  fleet_30d,
                "alpha_vs_spy":  round(fleet_30d - spy_30d, 2) if fleet_30d is not None and spy_30d is not None else None,
                "alpha_vs_qqq":  round(fleet_30d - qqq_30d, 2) if fleet_30d is not None and qqq_30d is not None else None,
                "data_points": len(bm_rows),
            }
        else:
            result["benchmark_30d"] = {
                "message": "Fewer than 2 benchmark snapshots recorded — check back after market close",
                "data_points": len(bm_rows),
            }

        # ── Drawdown HWM states ────────────────────────────────────────────────
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT bot_id, hwm, pause_threshold_pct, is_paused_by_drawdown,
                           CASE WHEN hwm > 0
                                THEN ROUND(((hwm - (
                                    SELECT COALESCE(equity_usd, hwm)
                                    FROM kraken_heartbeat kh
                                    WHERE kh.bot_id = bdh.bot_id
                                    LIMIT 1
                                )) / hwm * 100)::numeric, 2)
                                ELSE 0 END AS drawdown_pct
                    FROM bot_drawdown_hwm bdh
                    ORDER BY bot_id
                """)
                dd_rows = cur.fetchall()
        result["drawdown_states"] = [
            {
                "bot_id":         r[0],
                "hwm":            float(r[1]) if r[1] else 0,
                "threshold_pct":  float(r[2]) * 100 if r[2] else 8,
                "paused_by_drawdown": bool(r[3]),
                "current_drawdown_pct": float(r[4]) if r[4] else 0,
            }
            for r in dd_rows
        ]
    except Exception as _bm_exc:
        result["benchmark_30d"] = {"error": str(_bm_exc)}
        result["drawdown_states"] = []

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


@system_router.get("/review-flags")
async def get_review_flags():
    """Return all pending review flags for dashboard display."""
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"flags": [], "error": "db_unavailable"}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT flag_key, title, description, due_date,
                       priority, status, created_at, resolved_note
                FROM review_flags
                WHERE status = 'pending'
                ORDER BY
                    CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    due_date ASC
            """)
            rows = cur.fetchall()
    from datetime import date as _date
    today = _date.today()
    return {
        "flags": [
            {
                "flag_key":    r[0],
                "title":       r[1],
                "description": r[2],
                "due_date":    str(r[3]),
                "priority":    r[4],
                "status":      r[5],
                "created_at":  r[6].isoformat() if r[6] else None,
                "overdue":     r[3] < today if r[3] else False,
                "days_until":  (r[3] - today).days if r[3] else None,
            }
            for r in rows
        ],
        "pending_count": len(rows),
        "high_priority_count": sum(1 for r in rows if r[4] == "high"),
    }


@system_router.post("/review-flags/{flag_key}/resolve")
async def resolve_review_flag(flag_key: str, note: str = ""):
    """Manually resolve a review flag after reporting back to Claude."""
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        raise HTTPException(status_code=503, detail="DB unavailable")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE review_flags
                SET status = 'resolved',
                    resolved_at = NOW(),
                    resolved_note = %s
                WHERE flag_key = %s AND status = 'pending'
            """, (note or "Manually resolved", flag_key))
        conn.commit()
    return {"resolved": flag_key}
