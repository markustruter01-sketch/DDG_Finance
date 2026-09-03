#!/usr/bin/env python3
"""Development-only reproduction gate for the Strategy Bench experiments.

This gate deliberately calls the lower-level backtest loaders, screener/cache,
and simulators.  It does not call either experiment's top-level ``run()``
function because those functions register or record immutable ledger results.
It also never reads the dashboard's generated ``strategy-bench.json`` payload.
The only database write performed by this module is one append-only
``exploration_runs`` row per requested experiment.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_ROOT = Path(__file__).resolve().parents[2]
_PLATFORM = _ROOT / "trading-platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from core.equity_universe import (  # noqa: E402
    eligible_asset_records,
    set_screen_data,
)
from db.research_postgres import get_research_conn as get_conn, is_research_available  # noqa: E402
from analysis.bot2_momentum_pead_v3 import (  # noqa: E402
    ASSET_TABLE,
    PRICE_SOURCES,
    PRICE_TABLE,
)
from analysis.bot2_sp500_data import REFERENCE_PRICE_SOURCES  # noqa: E402
from analysis.bot2_momentum_pead_v4 import (  # noqa: E402
    CONTROL_ITERATIONS,
    RANDOM_SEED,
    SLIPPAGE_BPS,
    STOP_LOSS,
    TARGET_UNIVERSE,
    TOP_N,
    build_momentum_cache,
    simulate_momentum,
)
from analysis.bot2_momentum_rank500_backtest import (  # noqa: E402
    BACKTEST_START,
    WARMUP_START,
    _latest_complete_month_end,
    _load_compact_panel,
    _windows,
)
from analysis.bot2_momentum_rank500_regime import (  # noqa: E402
    BASELINE_EXPERIMENT_ID,
    REGIME_LOOKBACK,
    REGIME_OFF,
    REGIME_ON,
    SGOV_SYMBOL,
    _build_regime_cache,
    _load_reference_series,
    simulate_regime,
)


TOLERANCE = 1e-4
EXTERNAL_REFERENCE_CURVE_RELATIVE_TOLERANCE = 2e-4
EXPERIMENT_18 = 18
EXPERIMENT_19 = 19
POOLED_WINDOW = "pooled_2019-02_latest_complete"
GENERATOR_PATH = _PLATFORM / "analysis" / "export_bot2_strategy_bench.py"
ARTIFACT_PATHS = (
    _ROOT / "artifacts" / "dashboard" / "public" / "strategy-bench.json",
    _ROOT / "artifacts" / "dashboard" / "dist" / "public" / "strategy-bench.json",
)


class GateError(RuntimeError):
    """A fail-closed gate error that should also be recorded as a failed run."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, default=str)


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise GateError(f"invalid {field}: {value!r}") from exc


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
    configured_host = os.environ.get("PGHOST")
    if not configured_host:
        dsn = os.environ.get("DATABASE_URL", "")
        if dsn:
            configured_host = urlsplit(dsn).hostname
    host = socket_host or configured_host or "unix_socket"
    port = socket_port or configured_port
    return {"database": database, "host": host, "port": port}


def _print_provenance(identity: dict[str, Any]) -> None:
    print(
        "DATABASE | "
        f"name={identity['database']} | host={identity['host']} | port={identity['port']}"
    )
    print(f"GENERATOR | path={GENERATOR_PATH} | artifact_content_read=NO")
    for path in ARTIFACT_PATHS:
        if path.exists():
            written = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            print(
                f"ARTIFACT | path={path} | last_written={written} "
                f"| bytes={path.stat().st_size} | content_read=NO"
            )
        else:
            print(f"ARTIFACT | path={path} | status=MISSING | content_read=NO")
    print(
        "DATA_PROVENANCE | "
        f"price_table={PRICE_TABLE} | price_sources={list(PRICE_SOURCES)} | "
        f"reference_price_sources={list(REFERENCE_PRICE_SOURCES)} | "
        "screener=core.equity_universe.screen_universe"
    )
    print(
        "ENGINE_ENTRY_POINTS | "
        f"experiment_18={_PLATFORM / 'analysis' / 'bot2_momentum_rank500_backtest.py'}:"
        "build_momentum_cache->simulate_momentum | "
        f"experiment_19={_PLATFORM / 'analysis' / 'bot2_momentum_rank500_regime.py'}:"
        "_build_regime_cache->simulate_regime"
    )
    print(
        "TOP_LEVEL_RUNNERS | "
        "not_called=bot2_momentum_rank500_backtest.run,"
        "bot2_momentum_rank500_regime.run"
    )


def _load_ledger_row(experiment_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT experiment_id, strategy_family, bot_id, hypothesis,
                       parameters, pass_bar, data_window, variations_tested,
                       spec_hash, results, outcome
                  FROM research_ledger
                 WHERE experiment_id = %s
                """,
                (experiment_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise GateError(f"Helium experiment {experiment_id} does not exist")
    if row[9] is None:
        raise GateError(f"Helium experiment {experiment_id} has no immutable results")
    return {
        "experiment_id": row[0],
        "strategy_family": row[1],
        "bot_id": row[2],
        "hypothesis": row[3],
        "parameters": row[4],
        "pass_bar": row[5],
        "data_window": row[6],
        "variations_tested": row[7],
        "spec_hash": row[8],
        "results": row[9],
        "outcome": row[10],
    }


def _ledger_snapshot(row: dict[str, Any]) -> str:
    return _json(
        {
            key: row[key]
            for key in (
                "experiment_id",
                "strategy_family",
                "bot_id",
                "hypothesis",
                "parameters",
                "pass_bar",
                "data_window",
                "variations_tested",
                "spec_hash",
                "results",
                "outcome",
            )
        }
    )


def _asset_records() -> tuple[list[dict[str, Any]], set[str]]:
    """Read the existing audited asset table without running its DDL bootstrap."""
    # load_stored_assets() is intentionally not used: its historical wrapper
    # calls ensure_asset_table(), which can issue DDL.  This gate must not
    # mutate any research/data table.
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
    if not stored:
        raise GateError(f"audited asset table {ASSET_TABLE} is empty")
    records = stored
    eligible, funnel = eligible_asset_records(records)
    candidates = {str(item["symbol"]).upper() for item in eligible}
    print(
        f"ASSETS | table={ASSET_TABLE} | stored={len(records)} "
        f"| eligible={len(eligible)} | candidates={len(candidates)} "
        f"| funnel={_json(funnel)}"
    )
    if not candidates:
        raise GateError("audited asset table produced no eligible candidates")
    return list(eligible), candidates


def _validate_spec(row: dict[str, Any]) -> tuple[date, tuple[tuple[str, date, date], ...]]:
    data_window = row["data_window"]
    parameters = row["parameters"]
    if not isinstance(data_window, dict) or not isinstance(parameters, dict):
        raise GateError("ledger parameters/data_window are not JSON objects")

    expected_end = _date(data_window.get("backtest_end"), "data_window.backtest_end")
    if expected_end != _latest_complete_month_end():
        raise GateError(
            "stored backtest_end does not match the latest complete stored price month: "
            f"stored={expected_end} current={_latest_complete_month_end()}"
        )
    expected = {
        "universe_size": TARGET_UNIVERSE,
        "top_n": TOP_N,
        "slippage_each_leg_bps": SLIPPAGE_BPS,
        "catastrophe_stop": STOP_LOSS,
        "max_deployment": 1.0,
        "allocation": "equal_weight",
        "momentum": "12-1",
        "rebalance": "monthly first-trading-day",
        "idle_capital": "cash",
        "random_control_iterations": CONTROL_ITERATIONS,
        "random_control_seed": RANDOM_SEED,
    }
    for key, expected_value in expected.items():
        if parameters.get(key) != expected_value:
            raise GateError(
                f"experiment {row['experiment_id']} parameter mismatch for {key}: "
                f"stored={parameters.get(key)!r} expected={expected_value!r}"
            )
    if data_window.get("price_table") != PRICE_TABLE:
        raise GateError(
            f"price table mismatch: stored={data_window.get('price_table')!r} "
            f"expected={PRICE_TABLE!r}"
        )
    if data_window.get("price_sources") != list(PRICE_SOURCES):
        raise GateError(
            f"price sources mismatch: stored={data_window.get('price_sources')!r} "
            f"expected={list(PRICE_SOURCES)!r}"
        )
    if data_window.get("screener_implementation") != (
        "core.equity_universe.screen_universe"
    ):
        raise GateError(
            "stored screener implementation is not the shared canonical screener"
        )
    if _date(data_window.get("warmup_start"), "data_window.warmup_start") != WARMUP_START:
        raise GateError("stored warmup_start differs from the canonical engine")
    if _date(data_window.get("backtest_start"), "data_window.backtest_start") != BACKTEST_START:
        raise GateError("stored backtest_start differs from the canonical engine")

    window_rows = data_window.get("windows")
    if not isinstance(window_rows, list):
        raise GateError("stored data_window.windows is not a list")
    stored_windows = tuple(
        (
            str(item["name"]),
            _date(item["start"], f"window {item.get('name')}.start"),
            _date(item["end"], f"window {item.get('name')}.end"),
        )
        for item in window_rows
    )
    canonical_windows = _windows(expected_end)
    if stored_windows != canonical_windows:
        raise GateError(
            "stored windows differ from the canonical engine: "
            f"stored={stored_windows!r} expected={canonical_windows!r}"
        )

    if row["experiment_id"] == EXPERIMENT_19:
        regime = parameters.get("market_regime")
        expected_regime = {
            "symbol": SGOV_SYMBOL,
            "signal_symbol": "SPY",
            "lookback_sessions": REGIME_LOOKBACK,
            "rule": (
                "RISK_ON iff prior SPY close > prior 200-session SMA; "
                "otherwise RISK_OFF"
            ),
            "evaluation_timing": "each monthly rebalance using bars strictly before date",
            "risk_off_asset": SGOV_SYMBOL,
            "position_policy": "binary; no momentum positions while RISK_OFF",
        }
        if regime != expected_regime:
            raise GateError(
                f"experiment 19 market_regime mismatch: stored={_json(regime)} "
                f"expected={_json(expected_regime)}"
            )
        if parameters.get("direct_baseline_experiment_id") != BASELINE_EXPERIMENT_ID:
            raise GateError("experiment 19 does not point directly to experiment 18")
    return expected_end, stored_windows


def _prepare_panel(
    row: dict[str, Any], end: date
) -> tuple[list[dict[str, Any]], set[str], dict[str, Any], dict[str, Any]]:
    assets, candidates = _asset_records()
    series = _load_compact_panel(candidates, end)
    panel_symbols = set(series) & candidates
    if not panel_symbols:
        raise GateError("stored price panel has no overlap with audited candidates")
    set_screen_data(assets, series)
    counts = {
        "candidate_symbols": len(candidates),
        "panel_symbols": len(panel_symbols),
        "stored_bars": sum(len(data.bars) for data in series.values()),
    }
    stored_counts = row["results"].get("universe", {})
    print(
        f"PANEL | candidates={counts['candidate_symbols']} "
        f"| panel_symbols={counts['panel_symbols']} | stored_bars={counts['stored_bars']} "
        f"| stored_universe={_json(stored_counts)}"
    )
    for key in ("candidate_symbols", "panel_symbols", "stored_bars"):
        if stored_counts.get(key) != counts[key]:
            print(
                f"DIVERGENCE | kind=panel_count | field={key} "
                f"| stored={stored_counts.get(key)!r} | computed={counts[key]!r}"
            )
    return assets, panel_symbols, series, counts


def _pooled_target(row: dict[str, Any]) -> dict[str, float]:
    try:
        window = row["results"]["windows"][POOLED_WINDOW]
        key = "momentum" if row["experiment_id"] == EXPERIMENT_18 else "filtered_regime_momentum"
        metrics = window[key]
        return {
            field: float(metrics[field])
            for field in ("sharpe", "return", "max_drawdown")
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise GateError(
            f"experiment {row['experiment_id']} has no unambiguous pooled target"
        ) from exc


def _first_curve_divergence(
    stored: dict[str, Any],
    computed: dict[str, Any],
    relative_tolerance: float = 0.0,
) -> dict[str, Any] | None:
    stored_rows = {
        str(item.get("date")): float(item["equity"])
        for item in stored.get("daily_deployment", [])
        if isinstance(item, dict) and "date" in item and "equity" in item
    }
    computed_rows = {
        str(item.get("date")): float(item["equity"])
        for item in computed.get("daily_deployment", [])
        if isinstance(item, dict) and "date" in item and "equity" in item
    }
    for day in sorted(set(stored_rows) | set(computed_rows)):
        if day not in stored_rows or day not in computed_rows:
            return {
                "date": day,
                "stored": stored_rows.get(day),
                "computed": computed_rows.get(day),
                "absolute_difference": None,
                "allowed_difference": None,
            }
        difference = abs(stored_rows[day] - computed_rows[day])
        allowed_difference = max(
            TOLERANCE,
            abs(stored_rows[day]) * relative_tolerance,
        )
        if difference > allowed_difference:
            return {
                "date": day,
                "stored": stored_rows[day],
                "computed": computed_rows[day],
                "absolute_difference": difference,
                "allowed_difference": allowed_difference,
            }
    return None


def _run_engine(
    row: dict[str, Any], end: date, windows: tuple[tuple[str, date, date], ...]
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, panel_symbols, series, panel_counts = _prepare_panel(row, end)
    ranking_cache = build_momentum_cache(
        series, panel_symbols, TARGET_UNIVERSE, end
    )
    print(
        f"RANKING_CACHE | experiment={row['experiment_id']} "
        f"| monthly_rebalances={len(ranking_cache)}"
    )
    results: dict[str, Any] = {}
    if row["experiment_id"] == EXPERIMENT_18:
        # Match experiment 18's benchmark simulator's exact data path.  SPY
        # is not needed to reproduce the momentum target itself.
        for name, start, window_end in windows:
            results[name] = simulate_momentum(
                series, panel_symbols, TARGET_UNIVERSE,
                start, window_end, ranking_cache,
            )
        return results, {
            "ranking_cache": ranking_cache,
            "panel_counts": panel_counts,
            "engine": "build_momentum_cache->simulate_momentum",
        }

    if row["experiment_id"] != EXPERIMENT_19:
        raise GateError(
            f"unsupported experiment {row['experiment_id']}; only 18 and 19 are allowed"
        )
    spy = _load_reference_series("SPY", end)
    sgov = _load_reference_series(SGOV_SYMBOL, end)
    regime_cache = _build_regime_cache(spy, end)
    for name, start, window_end in windows:
        results[name] = simulate_regime(
            series, sgov, start, window_end, ranking_cache, regime_cache
        )
    return results, {
        "ranking_cache": ranking_cache,
        "panel_counts": panel_counts,
        "regime_cache": regime_cache,
        "engine": "build_momentum_cache->_build_regime_cache->simulate_regime",
    }


def _insert_exploration_run(
    row: dict[str, Any],
    computed_metrics: dict[str, Any] | None,
    status: str,
    note: str,
) -> int:
    pooled = (computed_metrics or {}).get("computed", {})
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO exploration_runs
                    (strategy_family, parameters, data_window, spec_hash, source,
                     sharpe, return_pct, max_drawdown, notes)
                VALUES (%s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)
                RETURNING run_id
                """,
                (
                    row["strategy_family"],
                    _json(row["parameters"]),
                    _json(row["data_window"]),
                    row["spec_hash"],
                    "bench_gate",
                    pooled.get("sharpe"),
                    pooled.get("return"),
                    pooled.get("max_drawdown"),
                    (
                        f"experiment_id={row['experiment_id']} | "
                        f"reproduction={status} | {note}"
                    )[:4000],
                ),
            )
            run_id = int(cur.fetchone()[0])
    print(
        f"EXPLORATION_RUN | run_id={run_id} | experiment={row['experiment_id']} "
        f"| source=bench_gate | status={status}"
    )
    return run_id


def _verify_ledger_unchanged(
    row: dict[str, Any], before: str
) -> None:
    after = _ledger_snapshot(_load_ledger_row(row["experiment_id"]))
    if before != after:
        raise GateError(
            f"research_ledger experiment {row['experiment_id']} changed during gate"
        )
    print(
        f"LEDGER_IMMUTABILITY | experiment={row['experiment_id']} "
        "| status=PASS"
    )


def _run_one(experiment_id: int) -> bool:
    row = _load_ledger_row(experiment_id)
    before = _ledger_snapshot(row)
    print(f"=== GATE EXPERIMENT {experiment_id} ===")
    print(f"SPEC | experiment={experiment_id} | strategy_family={row['strategy_family']}")
    print(f"SPEC_PARAMETERS | experiment={experiment_id} | value={_json(row['parameters'])}")
    print(f"SPEC_DATA_WINDOW | experiment={experiment_id} | value={_json(row['data_window'])}")
    print(
        f"SPEC_TARGET | experiment={experiment_id} | pooled_window={POOLED_WINDOW} "
        f"| values={_json(_pooled_target(row))} | stored_outcome={row['outcome']}"
    )
    computed_metrics: dict[str, Any] | None = None
    try:
        end, windows = _validate_spec(row)
        computed, engine_context = _run_engine(row, end, windows)
        target = _pooled_target(row)
        pooled_key = (
            "momentum"
            if experiment_id == EXPERIMENT_18
            else "filtered_regime_momentum"
        )
        comparison_pass, comparison_metrics = _compare_results(
            row, computed, engine_context["ranking_cache"], pooled_key, target
        )
        passed = comparison_pass
        computed_metrics = comparison_metrics
        status = "PASS" if passed else "FAIL"
        note = (
            f"tolerance={TOLERANCE}; engine={engine_context['engine']}; "
            f"monthly_rebalances={len(engine_context['ranking_cache'])}"
        )
    except Exception as exc:
        status = "FAIL"
        note = f"fail_closed={type(exc).__name__}: {exc}"
        print(
            f"GATE_ERROR | experiment={experiment_id} | "
            f"type={type(exc).__name__} | message={exc}"
        )
    finally:
        run_id = _insert_exploration_run(row, computed_metrics, status, note)
        print(
            f"EXPLORATION_SPEC | run_id={run_id} | parameters={_json(row['parameters'])} "
            f"| data_window={_json(row['data_window'])}"
        )
        _verify_ledger_unchanged(row, before)
    print(f"EXPERIMENT_VERDICT | experiment={experiment_id} | status={status}")
    return status == "PASS"


def _compare_results(
    row: dict[str, Any],
    computed: dict[str, Any],
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    computed_key: str,
    target: dict[str, float],
) -> tuple[bool, dict[str, Any]]:
    pooled = computed[POOLED_WINDOW]
    metric_report: dict[str, Any] = {}
    passed = True
    for field in ("sharpe", "return", "max_drawdown"):
        stored_value = target[field]
        computed_value = float(pooled[field])
        difference = abs(stored_value - computed_value)
        field_passed = math.isfinite(computed_value) and difference <= TOLERANCE
        passed = passed and field_passed
        metric_report[field] = {
            "stored": stored_value,
            "computed": computed_value,
            "absolute_difference": difference,
            "status": "PASS" if field_passed else "FAIL",
        }
        print(
            f"METRIC | experiment={row['experiment_id']} | window={POOLED_WINDOW} "
            f"| field={field} | stored={stored_value:.12f} "
            f"| computed={computed_value:.12f} | absolute_difference={difference:.12f} "
            f"| tolerance={TOLERANCE:.1e} | status={metric_report[field]['status']}"
        )

    stored_rebalances = row["results"].get("universe", {}).get("monthly_rebalances")
    if stored_rebalances != len(ranking_cache):
        passed = False
        print(
            f"DIVERGENCE | kind=monthly_rebalance_count "
            f"| stored={stored_rebalances!r} | computed={len(ranking_cache)!r}"
        )
    else:
        print(
            f"REBALANCE_COUNT | stored={stored_rebalances} "
            f"| computed={len(ranking_cache)} | status=PASS"
        )

    stored_pooled = row["results"]["windows"][POOLED_WINDOW][computed_key]
    curve_relative_tolerance = (
        EXTERNAL_REFERENCE_CURVE_RELATIVE_TOLERANCE
        if row["experiment_id"] == EXPERIMENT_19
        else 0.0
    )
    divergence = _first_curve_divergence(
        stored_pooled,
        pooled,
        relative_tolerance=curve_relative_tolerance,
    )
    if divergence is not None:
        passed = False
        print(f"DIVERGENCE | kind=first_equity_curve | details={_json(divergence)}")
    else:
        print(
            f"EQUITY_CURVE | experiment={row['experiment_id']} "
            f"| window={POOLED_WINDOW} | first_divergence=NONE_ABOVE_TOLERANCE "
            f"| relative_tolerance={curve_relative_tolerance:.1e} "
            f"| reason={'external_reference_vendor' if curve_relative_tolerance else 'exact_match'} "
            f"| status=PASS"
        )
    return passed, {
        "pooled": metric_report,
        "computed": {
            field: float(pooled[field])
            for field in ("sharpe", "return", "max_drawdown")
        },
        "monthly_rebalances": len(ranking_cache),
        "first_equity_curve_divergence": divergence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce immutable Helium Strategy Bench experiments 18 and 19"
    )
    parser.add_argument(
        "--experiment-id",
        type=int,
        action="append",
        dest="experiment_ids",
        help="Experiment to reproduce; repeat for multiple experiments (default: 18 and 19)",
    )
    args = parser.parse_args()
    experiment_ids = args.experiment_ids or [EXPERIMENT_18, EXPERIMENT_19]
    if any(experiment_id not in {EXPERIMENT_18, EXPERIMENT_19} for experiment_id in experiment_ids):
        parser.error("only experiment IDs 18 and 19 are supported")
    if not is_research_available():
        raise SystemExit("refusing to run without the explicit Helium research connection")

    identity = _database_identity()
    _print_provenance(identity)
    outcomes = [_run_one(experiment_id) for experiment_id in experiment_ids]
    final = all(outcomes)
    print(f"FINAL_VERDICT | {'VERIFIED' if final else 'NOT_VERIFIED'}")
    return 0 if final else 4


if __name__ == "__main__":
    raise SystemExit(main())