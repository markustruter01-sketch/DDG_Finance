"""Development-only verified Strategy Bench API.

The browser used to calculate a different, synthetic strategy from a checked-in
JSON export.  This route is deliberately small and explicit: it loads the
Helium panel, calls the canonical lower-level research engines, and records
each request in ``exploration_runs`` without touching ``research_ledger``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import asyncio
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from core.equity_universe import eligible_asset_records, set_screen_data
from db.research_postgres import get_research_conn as get_conn, research_dsn_host
from research.strategy_bench_catalog import fetch_live_catalog, load_snapshot
from analysis.bot2_momentum_pead_v3 import ASSET_TABLE, PRICE_SOURCES, PRICE_TABLE
from analysis.bot2_momentum_pead_v4 import (
    CONTROL_ITERATIONS,
    RANDOM_SEED,
    SLIPPAGE_BPS,
    STOP_LOSS,
    TARGET_UNIVERSE,
    TOP_N,
    build_momentum_cache,
    simulate_momentum,
)
from analysis.bot2_momentum_rank500_backtest import (
    BACKTEST_START,
    WARMUP_START,
    _latest_complete_month_end,
    _load_compact_panel,
)
from analysis.bot2_momentum_rank500_regime import (
    REGIME_LOOKBACK,
    SGOV_SYMBOL,
    _build_regime_cache,
    _load_reference_series,
    simulate_regime,
)


router = APIRouter()
SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "strategy_bench_snapshot.json"
)
_ENGINE_LOCK = threading.RLock()
_PANEL_CACHE: dict[date, tuple[list[dict[str, Any]], set[str], dict[str, Any]]] = {}
_RANKING_CACHE: dict[
    tuple[date, int], dict[date, list[tuple[str, float, float]]]
] = {}
_REFERENCE_CACHE: dict[date, tuple[Any, Any, dict[date, dict[str, Any]]]] = {}


class BenchRunRequest(BaseModel):
    strategy_family: Literal[
        "bot2_momentum_rank500", "bot2_momentum_rank500_regime"
    ] = "bot2_momentum_rank500"
    parameters: dict[str, Any] = Field(default_factory=dict)
    data_window: dict[str, Any]


def _runner_environment() -> str:
    return os.environ.get(
        "RUNNER_ENVIRONMENT",
        "published" if os.environ.get("REPLIT_DEPLOYMENT") == "1" else "dev",
    )


def _committed_snapshot() -> dict[str, Any]:
    try:
        return load_snapshot(str(SNAPSHOT_PATH))
    except Exception as exc:
        logger.error(
            "committed Strategy Bench snapshot unavailable ({})",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="The committed Strategy Bench snapshot is unavailable or invalid.",
        ) from exc


@router.get("/research/strategy-bench/catalog", tags=["Development Research"])
async def get_strategy_bench_catalog() -> dict[str, Any]:
    if _runner_environment() not in {"dev", "development"}:
        return _committed_snapshot()

    try:
        return await asyncio.to_thread(fetch_live_catalog, get_conn)
    except Exception as exc:
        logger.warning(
            "Strategy Bench research read unavailable; serving committed snapshot ({})",
            type(exc).__name__,
        )
        snapshot = _committed_snapshot()
        snapshot["source_detail"] = (
            "The research database is unavailable in this workspace; "
            "showing the committed snapshot."
        )
        return snapshot


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def _database_identity() -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT current_database(), inet_server_addr()::text,
                       inet_server_port(), current_setting('port')
                """
            )
            database, socket_host, socket_port, configured_port = cur.fetchone()
    return {
        "database": database,
        "host": socket_host or research_dsn_host(),
        "port": socket_port or configured_port,
    }


def _normalise_request(request: BenchRunRequest) -> tuple[dict[str, Any], date, date]:
    supplied = dict(request.parameters)
    allowed = {
        "universe_size",
        "top_n",
        "slippage_each_leg_bps",
        "catastrophe_stop",
        "max_deployment",
        "allocation",
        "momentum",
        "rebalance",
        "idle_capital",
        "market_regime",
    }
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise ValueError(f"unsupported parameter(s): {', '.join(unknown)}")

    parameters = {
        "universe_size": int(supplied.get("universe_size", TARGET_UNIVERSE)),
        "top_n": int(supplied.get("top_n", TOP_N)),
        "slippage_each_leg_bps": float(
            supplied.get("slippage_each_leg_bps", SLIPPAGE_BPS)
        ),
        "catastrophe_stop": float(supplied.get("catastrophe_stop", STOP_LOSS)),
        "max_deployment": float(supplied.get("max_deployment", 1.0)),
        "allocation": supplied.get("allocation", "equal_weight"),
        "momentum": supplied.get("momentum", "12-1"),
        "rebalance": supplied.get("rebalance", "monthly first-trading-day"),
        "idle_capital": supplied.get("idle_capital", "cash"),
    }
    if request.strategy_family == "bot2_momentum_rank500_regime":
        parameters["market_regime"] = supplied.get(
            "market_regime",
            {
                "symbol": SGOV_SYMBOL,
                "signal_symbol": "SPY",
                "lookback_sessions": REGIME_LOOKBACK,
                "rule": (
                    "RISK_ON iff prior SPY close > prior 200-session SMA; "
                    "otherwise RISK_OFF"
                ),
            },
        )
    elif "market_regime" in supplied:
        raise ValueError("market_regime is only valid for the regime engine")

    if not 1 <= parameters["universe_size"] <= 500:
        raise ValueError("universe_size must be between 1 and 500")
    if parameters["top_n"] != TOP_N:
        raise ValueError(f"top_n is locked to the canonical value {TOP_N}")
    if parameters["slippage_each_leg_bps"] != SLIPPAGE_BPS:
        raise ValueError(f"slippage_each_leg_bps is locked to {SLIPPAGE_BPS}")
    if parameters["catastrophe_stop"] != STOP_LOSS:
        raise ValueError(f"catastrophe_stop is locked to {STOP_LOSS}")
    if parameters["max_deployment"] != 1.0:
        raise ValueError("max_deployment is locked to 1.0")
    if parameters["allocation"] != "equal_weight":
        raise ValueError("allocation is locked to equal_weight")
    if parameters["momentum"] != "12-1":
        raise ValueError("momentum is locked to 12-1")
    if parameters["rebalance"] != "monthly first-trading-day":
        raise ValueError("rebalance is locked to monthly first-trading-day")
    if parameters["idle_capital"] != "cash":
        raise ValueError("idle_capital is locked to cash")
    if request.strategy_family == "bot2_momentum_rank500_regime":
        regime = parameters["market_regime"]
        if not isinstance(regime, dict) or regime.get("lookback_sessions") != REGIME_LOOKBACK:
            raise ValueError("market_regime lookback_sessions is locked to 200")

    window = request.data_window
    warmup_start = _date(window.get("warmup_start"), "data_window.warmup_start")
    start = _date(window.get("backtest_start"), "data_window.backtest_start")
    end = _date(window.get("backtest_end"), "data_window.backtest_end")
    if warmup_start != WARMUP_START:
        raise ValueError(f"warmup_start must be {WARMUP_START.isoformat()}")
    if start < BACKTEST_START:
        raise ValueError(f"backtest_start must be on or after {BACKTEST_START.isoformat()}")
    if start > end:
        raise ValueError("backtest_start must be on or before backtest_end")
    latest = _latest_complete_month_end()
    if end > latest:
        raise ValueError(
            f"backtest_end cannot exceed latest complete stored month {latest.isoformat()}"
        )
    next_month = date(
        end.year + (1 if end.month == 12 else 0),
        1 if end.month == 12 else end.month + 1,
        1,
    )
    if end != next_month - date.resolution:
        raise ValueError("backtest_end must be the last calendar day of a month")

    data_window = {
        "warmup_start": warmup_start.isoformat(),
        "backtest_start": start.isoformat(),
        "backtest_end": end.isoformat(),
        "price_table": PRICE_TABLE,
        "price_sources": list(PRICE_SOURCES),
        "screener_implementation": "core.equity_universe.screen_universe",
    }
    return parameters, start, end


def _load_panel(end: date) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    cached = _PANEL_CACHE.get(end)
    if cached is not None:
        return cached
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, asset_class, status, exchange, tradable,
                       fractionable, name
                  FROM {ASSET_TABLE}
                 WHERE asset_class='us_equity'
                   AND instrument_classification='ordinary_equity'
                """
            )
            rows = cur.fetchall()
    stored = [
        {
            "symbol": symbol,
            "asset_class": asset_class,
            "status": status,
            "exchange": exchange or "",
            "tradable": bool(tradable),
            "fractionable": fractionable,
            "name": name or "",
        }
        for symbol, asset_class, status, exchange, tradable, fractionable, name in rows
    ]
    eligible, funnel = eligible_asset_records(stored)
    candidates = {str(item["symbol"]).upper() for item in eligible}
    if not candidates:
        raise RuntimeError("audited asset table produced no eligible candidates")
    series = _load_compact_panel(candidates, end)
    panel_symbols = set(series) & candidates
    if not panel_symbols:
        raise RuntimeError("stored price panel has no overlap with audited candidates")
    set_screen_data(eligible, series)
    counts = {
        "asset_rows": len(stored),
        "candidate_symbols": len(candidates),
        "panel_symbols": len(panel_symbols),
        "stored_bars": sum(len(data.bars) for data in series.values()),
        "asset_funnel": funnel,
    }
    cached = (eligible, panel_symbols, {"series": series, "counts": counts})
    _PANEL_CACHE[end] = cached
    return cached


def _engine_result(
    strategy_family: str, parameters: dict[str, Any], start: date, end: date
) -> tuple[dict[str, Any], dict[str, Any]]:
    with _ENGINE_LOCK:
        _, symbols, panel = _load_panel(end)
        series = panel["series"]
        ranking_key = (end, parameters["universe_size"])
        ranking_cache = _RANKING_CACHE.get(ranking_key)
        if ranking_cache is None:
            set_screen_data(_load_panel(end)[0], series)
            ranking_cache = build_momentum_cache(
                series, symbols, parameters["universe_size"], end
            )
            _RANKING_CACHE[ranking_key] = ranking_cache

        if strategy_family == "bot2_momentum_rank500":
            result = simulate_momentum(
                series,
                symbols,
                parameters["universe_size"],
                start,
                end,
                ranking_cache,
            )
            engine = "bot2_momentum_rank500_backtest.build_momentum_cache->simulate_momentum"
        else:
            references = _REFERENCE_CACHE.get(end)
            if references is None:
                spy = _load_reference_series("SPY", end)
                sgov = _load_reference_series(SGOV_SYMBOL, end)
                references = (spy, sgov, _build_regime_cache(spy, end))
                _REFERENCE_CACHE[end] = references
            spy, sgov, regime_cache = references
            result = simulate_regime(
                series, sgov, start, end, ranking_cache, regime_cache
            )
            engine = (
                "bot2_momentum_rank500_regime.build_momentum_cache"
                "->_build_regime_cache->simulate_regime"
            )
        return result, {
            "engine": engine,
            "panel_counts": panel["counts"],
            "monthly_rebalances": len(ranking_cache),
        }


def _curve(result: dict[str, Any]) -> list[dict[str, Any]]:
    deployment = result.get("daily_deployment", [])
    if not deployment:
        return []
    first_equity = float(deployment[0]["equity"])
    peak = first_equity
    points: list[dict[str, Any]] = []
    for item in deployment:
        equity = float(item["equity"])
        peak = max(peak, equity)
        points.append(
            {
                "date": str(item["date"]),
                "equity": equity,
                "growth_of_100": equity / first_equity * 100 if first_equity else 100,
                "drawdown_pct": (equity / peak - 1) * 100 if peak else 0,
                "positions": int(item.get("positions", 0)),
                "mode": item.get("mode"),
                "regime": item.get("regime"),
            }
        )
    return points


def _record_run(
    strategy_family: str,
    parameters: dict[str, Any],
    data_window: dict[str, Any],
    spec_hash: str,
    result: dict[str, Any] | None,
    note: str,
) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO exploration_runs
                    (strategy_family, parameters, data_window, spec_hash, source,
                     sharpe, return_pct, max_drawdown, notes)
                VALUES (%s, %s::jsonb, %s::jsonb, %s, 'strategy_bench',
                        %s, %s, %s, %s)
                RETURNING run_id
                """,
                (
                    strategy_family,
                    _json(parameters),
                    _json(data_window),
                    spec_hash,
                    result.get("sharpe") if result else None,
                    result.get("return", 0) * 100 if result else None,
                    result.get("max_drawdown") if result else None,
                    note[:4000],
                ),
            )
            return int(cur.fetchone()[0])


def _failure_window(request: BenchRunRequest) -> dict[str, Any]:
    return {
        "warmup_start": request.data_window.get("warmup_start"),
        "backtest_start": request.data_window.get("backtest_start"),
        "backtest_end": request.data_window.get("backtest_end"),
    }


def _execute_request(
    request: BenchRunRequest,
    request_parameters: dict[str, Any],
    request_window: dict[str, Any],
    spec_hash: str,
) -> dict[str, Any]:
    parameters, start, end = _normalise_request(request)
    data_window = {
        **request_window,
        "warmup_start": WARMUP_START.isoformat(),
        "backtest_start": start.isoformat(),
        "backtest_end": end.isoformat(),
        "price_table": PRICE_TABLE,
        "price_sources": list(PRICE_SOURCES),
        "screener_implementation": "core.equity_universe.screen_universe",
    }
    result, context = _engine_result(
        request.strategy_family, parameters, start, end
    )
    run_id = _record_run(
        request.strategy_family,
        parameters,
        data_window,
        spec_hash,
        result,
        f"status=PASS; engine={context['engine']}; "
        f"monthly_rebalances={context['monthly_rebalances']}",
    )
    identity = _database_identity()
    return {
        "status": "verified",
        "run_id": run_id,
        "spec_hash": spec_hash,
        "strategy_family": request.strategy_family,
        "parameters": parameters,
        "data_window": data_window,
        "metrics": {
            "return": result["return"],
            "return_pct": result["return"] * 100,
            "max_drawdown": result["max_drawdown"],
            "max_drawdown_pct": result["max_drawdown"] * 100,
            "sharpe": result["sharpe"],
            "sortino": result["sortino"],
            "expectancy": result["expectancy"],
            "trades": result["trades"],
            "turnover": result["turnover"],
            "cost_paid": result["cost_paid"],
            "mean_deployment": result["mean_deployment"],
            "max_deployment": result["max_deployment"],
            "days_cash": sum(
                value.get("cash", 0) for value in result.get("mode_days", {}).values()
            ),
        },
        "curve": _curve(result),
        "provenance": {
            "database": identity,
            "price_table": PRICE_TABLE,
            "price_sources": list(PRICE_SOURCES),
            "data_feed": "development Helium price panel",
            "screener": "core.equity_universe.screen_universe",
            "engine": context["engine"],
            "artifact_content_read": False,
            "dashboard_json_used": False,
        },
    }


@router.post("/research/strategy-bench/run", tags=["Development Research"])
async def run_strategy_bench(request: BenchRunRequest) -> dict[str, Any]:
    if _runner_environment() not in {"dev", "development"}:
        raise HTTPException(
            status_code=403,
            detail="Strategy Bench workshop and sweep actions are disabled on the live site.",
        )

    request_parameters = dict(request.parameters)
    request_window = _failure_window(request)
    trigger = {
        "strategy_family": request.strategy_family,
        "parameters": request_parameters,
        "data_window": request_window,
    }
    spec_hash = hashlib.sha256(_json(trigger).encode()).hexdigest()
    try:
        return await asyncio.to_thread(
            _execute_request,
            request,
            request_parameters,
            request_window,
            spec_hash,
        )
    except Exception as exc:
        try:
            run_id = await asyncio.to_thread(
                _record_run,
                request.strategy_family,
                request_parameters,
                request_window,
                spec_hash,
                None,
                f"status=FAIL; fail_closed={type(exc).__name__}: {exc}",
            )
        except Exception as record_exc:
            logger.error(f"strategy bench failure could not be recorded: {record_exc}")
            raise HTTPException(status_code=503, detail="Strategy Bench failure could not be recorded")
        raise HTTPException(
            status_code=422 if isinstance(exc, (ValueError, TypeError)) else 503,
            detail={
                "message": str(exc),
                "status": "unverified",
                "run_id": run_id,
                "spec_hash": spec_hash,
                "provenance": None,
            },
        ) from exc