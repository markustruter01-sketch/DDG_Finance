"""Compare the Bot 2 Candidate A sleeve with a BIL sleeve in the three-bot fleet.

All source strategies are run in memory from Helium's research price panel.
This module appends results only when explicitly invoked with ``--run``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import mean, stdev
from typing import Any

START_DATE = date(2008, 1, 1)
END_DATE = date(2022, 12, 31)
COMMON_WINDOW_EXPECTED_START = date(2018, 4, 3)
COMMON_WINDOW_EXPECTED_END = date(2022, 12, 30)
STARTING_EQUITY_PER_SLEEVE = 100_000.0
SLEEVE_COUNT = 3
RISK_FREE_RATE = 0.0
COST_SCENARIOS = (5, 10)
SHARPE_DELTA_BAR = 0.05
STRATEGY_FAMILY = "fleet_test_v1"
SOURCE = "backtest_harness_fleet_test"

BOT1_RUN_IDS = {5: 123, 10: 124}
BOT2_CANDIDATE_A_RUN_IDS = {5: 115, 10: 119}
BOT3_RUN_IDS = {5: 125, 10: 126}
BOT1_SPEC_HASH = "7708be0e4007ccd95e5aede6429d06e60ed0463cd7fca3b341466be67b196745"
BOT2_CANDIDATE_A_SPEC_HASH = "5ec520ad6d1e093c0b939a5475cbfd2f4122e982f74430cdf16d24d4234d52d0"
BOT3_SPEC_HASH = "c079e8e4a21cb1ec8e6de5f0f97e701385166762441626d3b66f2b49df6f8cd0"

SPEC: dict[str, Any] = {
    "strategy_family": STRATEGY_FAMILY,
    "question": "Does Bot 2 Candidate A improve the Bot 1 + Bot 2 + Bot 3 fleet?",
    "sleeves": {
        "bot1": {
            "strategy_family": "bot1_baseline_v1",
            "run_ids_by_cost_bps": {str(k): v for k, v in BOT1_RUN_IDS.items()},
            "frozen_spec_hash": BOT1_SPEC_HASH,
        },
        "bot2_without_candidate_a": {
            "instrument": "BIL buy-and-hold",
            "method": (
                "one initial BIL target through analysis.backtest_harness.run_backtest; "
                "subsequent signal is None"
            ),
        },
        "bot2_with_candidate_a": {
            "strategy_family": "bot2_trend_v1.1",
            "candidate": "A",
            "frozen_spec_hash": BOT2_CANDIDATE_A_SPEC_HASH,
            "run_ids_by_cost_bps": {
                str(k): v for k, v in BOT2_CANDIDATE_A_RUN_IDS.items()
            },
        },
        "bot3": {
            "strategy_family": "bot3_baseline_v1",
            "run_ids_by_cost_bps": {str(k): v for k, v in BOT3_RUN_IDS.items()},
            "frozen_spec_hash": BOT3_SPEC_HASH,
            "fleet_equity_proxy": (
                "Bot3's existing 3x multiplier remains inside its crypto-cap logic; "
                "do not multiply the sleeve's returns a second time"
            ),
        },
        "starting_equity_per_sleeve": STARTING_EQUITY_PER_SLEEVE,
        "fleet_starting_equity": STARTING_EQUITY_PER_SLEEVE * SLEEVE_COUNT,
        "no_transfers_between_sleeves": True,
    },
    "periods": {
        "source_runs_requested": [
            START_DATE.isoformat(),
            END_DATE.isoformat(),
        ],
        "fleet_window": (
            "latest first-held session among Bot 1, Bot 2 (A or BIL), and Bot 3 "
            "through the last shared daily-return date"
        ),
        "expected_actual_fleet_window": [
            COMMON_WINDOW_EXPECTED_START.isoformat(),
            COMMON_WINDOW_EXPECTED_END.isoformat(),
        ],
        "no_data_after": END_DATE.isoformat(),
    },
    "method": {
        "source_returns": (
            "daily close-to-close returns from each sleeve's own in-memory "
            "backtest_harness run; persisted reference metrics are checked before use"
        ),
        "daily_calendar": (
            "exact intersection of all eight 5/10 bps source daily-return "
            "calendars, restricted to the common fleet window"
        ),
        "window_start_return": (
            "include the daily return dated on the first common-window session; "
            "rebase each sleeve to 100000 immediately before compounding"
        ),
        "fleet_equity": (
            "sum of three independently compounded 100000 starting-equity sleeves; "
            "no transfers or rebalancing between sleeves"
        ),
        "annualized_volatility": "sample standard deviation of daily returns x sqrt(252)",
        "sharpe": "mean daily return / sample standard deviation x sqrt(252); risk-free rate 0",
        "sortino": (
            "mean daily return / root-mean-square negative daily return x sqrt(252); "
            "target return 0"
        ),
        "cagr": "total return annualized over elapsed calendar days using 365 days/year",
        "max_drawdown": "peak-to-trough drawdown including the initial 300000 fleet equity",
        "correlation": "Pearson correlation matrix of the three aligned daily return series",
    },
    "costs": {
        "bps": list(COST_SCENARIOS),
        "same_cost_for_all_sleeves": True,
        "BIL_buy_and_hold": (
            "run separately at each cost; harness applies the one-time entry cost "
            "and does not force liquidation at the final close"
        ),
    },
    "pass_bar": {
        "per_cost": (
            "with-A fleet Sharpe minus without-A fleet Sharpe >= 0.05, AND "
            "Candidate A full-period 2008-2022 CAGR > BIL buy-and-hold CAGR "
            "at the same cost"
        ),
        "overall": "PASS only when both per-cost checks pass at both 5 and 10 bps",
        "sharpe_delta_minimum": SHARPE_DELTA_BAR,
        "sharpe_boundary_abs_tolerance": 1e-12,
        "candidate_a_cagr_reference_run_ids": [
            BOT2_CANDIDATE_A_RUN_IDS[5],
            BOT2_CANDIDATE_A_RUN_IDS[10],
        ],
    },
    "integrity_checks": {
        "candidate_a_spec_hash_must_match": BOT2_CANDIDATE_A_SPEC_HASH,
        "recompute_baselines_and_candidate_a_in_memory": True,
        "standalone_metrics_must_match_persisted_reference_runs": True,
        "reject_any_loaded_price_after": END_DATE.isoformat(),
        "never_write_research_ledger": True,
    },
    "persistence": {
        "destination": "exploration_runs only",
        "append_exactly": 4,
        "one_row_per": ["with_candidate_A/5_bps", "without_candidate_A/5_bps",
                        "with_candidate_A/10_bps", "without_candidate_A/10_bps"],
    },
}


def canonical_spec_json(spec: Mapping[str, Any] = SPEC) -> str:
    return json.dumps(
        spec,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def spec_hash(spec: Mapping[str, Any] = SPEC) -> str:
    return hashlib.sha256(canonical_spec_json(spec).encode("utf-8")).hexdigest()


def print_spec() -> dict[str, Any]:
    payload = {"spec": SPEC, "spec_hash": spec_hash()}
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False), flush=True)
    return payload


def _execute_checked(cur: Any, query: str, parameters: Sequence[Any]) -> None:
    """Reject SQL placeholder/parameter mismatches before calling the cursor."""
    placeholder_count = query.count("%s")
    if placeholder_count != len(parameters):
        raise ValueError(
            f"SQL placeholder/parameter mismatch: query has {placeholder_count} "
            f"%s placeholders but {len(parameters)} parameters were supplied"
        )
    cur.execute(query, tuple(parameters))


def _metrics_from_notes(notes: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for line in notes.splitlines():
        try:
            payload = json.loads(line)
        except (TypeError, ValueError):
            continue
        nested = payload.get("metrics")
        if isinstance(nested, dict):
            metrics.update(nested)
    if not metrics:
        raise ValueError("Reference exploration run has no stored metrics in notes")
    return metrics


def _load_reference_runs() -> dict[int, dict[str, Any]]:
    """Read the frozen source rows from Helium and fail closed on drift."""
    from db.research_postgres import get_research_conn

    reference_ids = sorted(
        set(BOT1_RUN_IDS.values())
        | set(BOT2_CANDIDATE_A_RUN_IDS.values())
        | set(BOT3_RUN_IDS.values())
    )
    query = """
        SELECT run_id, strategy_family, parameters, data_window, notes
        FROM public.exploration_runs
        WHERE run_id = ANY(%s)
        ORDER BY run_id
    """
    with get_research_conn() as conn:
        with conn.cursor() as cur:
            _execute_checked(cur, query, (reference_ids,))
            rows = cur.fetchall()
            _execute_checked(
                cur,
                "SELECT COUNT(*) FROM public.exploration_runs WHERE strategy_family = %s",
                (STRATEGY_FAMILY,),
            )
            fleet_rows = int(cur.fetchone()[0])
    if fleet_rows != 0:
        raise RuntimeError(
            f"{STRATEGY_FAMILY} already has {fleet_rows} row(s); refusing duplicate append"
        )

    references: dict[int, dict[str, Any]] = {}
    for run_id, family, parameters, data_window, notes in rows:
        references[int(run_id)] = {
            "strategy_family": family,
            "parameters": parameters,
            "data_window": data_window,
            "metrics": _metrics_from_notes(notes),
        }

    expected = {
        **{
            run_id: ("bot1_baseline_v1", "live_rule_baseline", cost, BOT1_SPEC_HASH)
            for cost, run_id in BOT1_RUN_IDS.items()
        },
        **{
            run_id: (
                "bot2_trend_v1.1",
                "A",
                cost,
                BOT2_CANDIDATE_A_SPEC_HASH,
            )
            for cost, run_id in BOT2_CANDIDATE_A_RUN_IDS.items()
        },
        **{
            run_id: ("bot3_baseline_v1", None, cost, BOT3_SPEC_HASH)
            for cost, run_id in BOT3_RUN_IDS.items()
        },
    }
    if set(references) != set(expected):
        raise RuntimeError(
            f"Expected reference run ids {sorted(expected)}, got {sorted(references)}"
        )

    for run_id, (family, candidate, cost, frozen_hash) in expected.items():
        row = references[run_id]
        parameters = row["parameters"]
        if row["strategy_family"] != family:
            raise RuntimeError(
                f"Run {run_id} family mismatch: {row['strategy_family']!r}"
            )
        if parameters.get("cost_bps") != cost:
            raise RuntimeError(f"Run {run_id} has an unexpected cost_bps")
        if parameters.get("spec_hash") != frozen_hash:
            raise RuntimeError(f"Run {run_id} frozen spec hash does not match")
        if candidate is not None and parameters.get("candidate") != candidate:
            raise RuntimeError(f"Run {run_id} candidate does not match {candidate}")
        window = row["data_window"]
        if (
            window.get("requested_start") != START_DATE.isoformat()
            or window.get("requested_end") != END_DATE.isoformat()
            or window.get("last_session", "") > END_DATE.isoformat()
        ):
            raise RuntimeError(f"Run {run_id} has an unexpected date window")
    return references


def _assert_metrics_match(
    result: Any,
    reference: Mapping[str, Any],
    *,
    run_id: int,
) -> None:
    required = (
        "total_return",
        "cagr",
        "annualised_volatility",
        "sharpe",
        "sortino",
        "max_drawdown",
    )
    stored = reference["metrics"]
    for metric in required:
        if metric not in stored or metric not in result.metrics:
            raise RuntimeError(f"Run {run_id} is missing metric {metric!r}")
        if not math.isclose(
            float(result.metrics[metric]),
            float(stored[metric]),
            rel_tol=1e-9,
            abs_tol=1e-10,
        ):
            raise RuntimeError(
                f"Recomputed run {run_id} {metric} differs from its persisted reference"
            )


def _daily_returns(result: Any) -> dict[date, float]:
    curve = result.equity_curve
    if len(curve) < 2:
        raise ValueError("Every sleeve run requires at least two equity marks")
    returns: dict[date, float] = {}
    for previous, current in zip(curve, curve[1:]):
        prior_equity = float(previous["equity"])
        current_equity = float(current["equity"])
        if not math.isfinite(prior_equity) or prior_equity <= 0:
            raise ValueError("A sleeve equity mark must be finite and positive")
        if not math.isfinite(current_equity):
            raise ValueError("A sleeve equity mark must be finite")
        day = current["date"]
        if not isinstance(day, date):
            raise TypeError("Backtest equity-curve dates must be date objects")
        if day > END_DATE:
            raise ValueError("A source run contains an equity mark after the cutoff")
        returns[day] = current_equity / prior_equity - 1.0
    return returns


def _first_held_date(result: Any) -> date:
    for event in result.events:
        if event.get("type") != "trade":
            continue
        if float(event.get("quantity_after", 0.0)) > 0:
            day = event["date"]
            if isinstance(day, date):
                return day
            if isinstance(day, str):
                try:
                    return date.fromisoformat(day)
                except ValueError as exc:
                    raise ValueError(
                        f"Backtest trade-event date is not ISO formatted: {day!r}"
                    ) from exc
            raise TypeError("Backtest trade-event dates must be dates or ISO strings")
    raise ValueError("A sleeve run has no filled long position")


def _bil_signal(first_session: date):
    submitted = False

    def signal(history: Mapping[str, Mapping[date, float]], day: date):
        nonlocal submitted
        if day == first_session and not submitted:
            submitted = True
            return {"BIL": 1.0}
        return None

    return signal


def _load_and_run_source_sleeves(
    references: Mapping[int, Mapping[str, Any]],
) -> dict[int | str, Any]:
    """Recreate source runs in memory; no exploration rows are written here."""
    from analysis import bot1_baseline as bot1
    from analysis import bot2_trend_candidates as bot2
    from analysis import bot3_baseline as bot3
    from analysis.backtest_harness import run_backtest

    if bot1.spec_hash() != BOT1_SPEC_HASH:
        raise RuntimeError("Current Bot 1 frozen spec does not match the reference rows")
    if bot2.spec_hash() != BOT2_CANDIDATE_A_SPEC_HASH:
        raise RuntimeError("Current Bot 2 candidate spec does not match run 115/119")
    if bot3.spec_hash() != BOT3_SPEC_HASH:
        raise RuntimeError("Current Bot 3 frozen spec does not match the reference rows")

    bot1_panel, atr_history = bot1._load_run_data()
    bot1_records = bot1.run_scenarios(bot1_panel, atr_history)

    bot2_panel, bot2_spy_panel = bot2.load_research_panels()
    if any(
        day > END_DATE
        for panel in (bot2_panel, bot2_spy_panel)
        for series in panel.closes.values()
        for day in series
    ):
        raise ValueError("A Bot 2 price panel contains data after 2022-12-31")
    bot2_sessions = bot2._common_sessions(bot2_panel)
    if len(bot2_sessions) < 2:
        raise ValueError("BIL buy-and-hold requires at least two common sessions")

    bot2_a_records = {
        cost: bot2._make_result_record(
            "A",
            cost,
            bot2_panel,
            bot2_spy_panel,
        )
        for cost in COST_SCENARIOS
    }
    bil_records = {
        cost: run_backtest(
            bot2_panel,
            _bil_signal(bot2_sessions[0]),
            START_DATE,
            END_DATE,
            cost_bps=cost,
            borrow_fee_rate=bot2.BORROW_FEE_RATE,
            risk_free_rate=RISK_FREE_RATE,
            margin_rate=bot2.MARGIN_RATE,
            max_gross=bot2.CASH_GROSS_CAP,
            starting_equity=bot2.STARTING_EQUITY,
            whole_shares=True,
        )
        for cost in COST_SCENARIOS
    }

    bot3_panel = bot3.load_price_panel()
    bot3_records = bot3.run_scenarios(bot3_panel)

    runs: dict[int | str, Any] = {}
    for record in bot1_records:
        runs[BOT1_RUN_IDS[record.cost_bps]] = record.result
    for cost, record in bot2_a_records.items():
        runs[BOT2_CANDIDATE_A_RUN_IDS[cost]] = record.result
    for record in bot3_records:
        runs[BOT3_RUN_IDS[record.cost_bps]] = record.result

    for run_id, result in runs.items():
        _assert_metrics_match(result, references[run_id], run_id=run_id)
    for result in [*bil_records.values()]:
        if any(
            point["date"] > END_DATE
            for point in result.equity_curve
        ):
            raise ValueError("BIL run contains an equity mark after 2022-12-31")
    runs.update(
        {
            _bil_reference_key(cost): result
            for cost, result in bil_records.items()
        }
    )
    return runs


def _bil_reference_key(cost_bps: int) -> str:
    return f"in_memory_bil_buy_and_hold_{cost_bps}bps"


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    left_var = math.fsum((value - left_mean) ** 2 for value in left)
    right_var = math.fsum((value - right_mean) ** 2 for value in right)
    if left_var <= 0 or right_var <= 0:
        return None
    covariance = math.fsum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right, strict=True)
    )
    return covariance / math.sqrt(left_var * right_var)


def _sharpe(returns: Sequence[float]) -> float:
    if len(returns) < 2:
        return 0.0
    deviation = stdev(returns)
    if deviation <= 0:
        return 0.0
    return mean(returns) / deviation * math.sqrt(252)


def _evaluate_cost_bar(
    with_a_sharpe: float,
    without_a_sharpe: float,
    candidate_a_cagr: float,
    bil_cagr: float,
) -> dict[str, Any]:
    delta = with_a_sharpe - without_a_sharpe
    sharpe_pass = delta >= SHARPE_DELTA_BAR or math.isclose(
        delta,
        SHARPE_DELTA_BAR,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    cagr_pass = candidate_a_cagr > bil_cagr
    return {
        "sharpe_delta": delta,
        "sharpe_bar_pass": sharpe_pass,
        "cagr_bar_pass": cagr_pass,
        "status": "PASS" if sharpe_pass and cagr_pass else "FAIL",
    }


def _correlation_matrix(
    aligned_returns: Mapping[str, Sequence[float]],
) -> dict[str, dict[str, float | None]]:
    names = tuple(aligned_returns)
    matrix: dict[str, dict[str, float | None]] = {}
    for left in names:
        matrix[left] = {}
        for right in names:
            if left == right:
                matrix[left][right] = 1.0
            else:
                matrix[left][right] = _pearson(
                    aligned_returns[left],
                    aligned_returns[right],
                )
    return matrix


def _fleet_metrics(
    aligned_returns: Mapping[str, Sequence[float]],
    sessions: Sequence[date],
) -> tuple[dict[str, float], tuple[dict[str, Any], ...]]:
    if len(aligned_returns) != SLEEVE_COUNT:
        raise ValueError(f"Fleet aggregation requires exactly {SLEEVE_COUNT} sleeves")
    if not sessions:
        raise ValueError("Fleet window has no aligned return dates")
    if any(len(values) != len(sessions) for values in aligned_returns.values()):
        raise ValueError("Each sleeve must have one return for every common session")

    sleeve_equity = {
        name: STARTING_EQUITY_PER_SLEEVE for name in aligned_returns
    }
    start_equity = STARTING_EQUITY_PER_SLEEVE * SLEEVE_COUNT
    fleet_equities: list[float] = []
    fleet_returns: list[float] = []
    curve: list[dict[str, Any]] = []
    previous_fleet_equity = start_equity

    for index, day in enumerate(sessions):
        for name, series in aligned_returns.items():
            daily_return = float(series[index])
            if not math.isfinite(daily_return) or daily_return <= -1.0:
                raise ValueError(f"Invalid daily return for {name} on {day}")
            sleeve_equity[name] *= 1.0 + daily_return
        fleet_equity = math.fsum(sleeve_equity.values())
        fleet_return = fleet_equity / previous_fleet_equity - 1.0
        fleet_equities.append(fleet_equity)
        fleet_returns.append(fleet_return)
        curve.append(
            {
                "date": day,
                "equity": fleet_equity,
                "gross_exposure": 0.0,
                "net_exposure": 0.0,
            }
        )
        previous_fleet_equity = fleet_equity

    volatility = (
        stdev(fleet_returns) * math.sqrt(252)
        if len(fleet_returns) > 1
        else 0.0
    )
    downside_deviation = (
        math.sqrt(mean(min(value, 0.0) ** 2 for value in fleet_returns))
        if fleet_returns
        else 0.0
    )
    sharpe = _sharpe(fleet_returns)
    sortino = (
        mean(fleet_returns) / downside_deviation * math.sqrt(252)
        if downside_deviation > 0
        else 0.0
    )
    total_return = fleet_equities[-1] / start_equity - 1.0
    elapsed_days = (sessions[-1] - sessions[0]).days
    cagr = (
        (fleet_equities[-1] / start_equity) ** (365.0 / elapsed_days) - 1.0
        if elapsed_days > 0
        else total_return
    )
    peak = start_equity
    max_drawdown = 0.0
    for equity in fleet_equities:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    metrics = {
        "total_return": total_return,
        "cagr": cagr,
        "annualised_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
    }
    if any(not math.isfinite(value) for value in metrics.values()):
        raise ValueError("Fleet metrics must all be finite")
    return metrics, tuple(curve)


def _reference_ids_for_cost(cost_bps: int) -> dict[str, int]:
    return {
        "bot1": BOT1_RUN_IDS[cost_bps],
        "bot2_candidate_a": BOT2_CANDIDATE_A_RUN_IDS[cost_bps],
        "bot3": BOT3_RUN_IDS[cost_bps],
    }


def _build_report(
    runs: Mapping[int | str, Any],
    references: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    return_maps = {run_id: _daily_returns(result) for run_id, result in runs.items()}
    held_dates = {
        run_id: _first_held_date(result)
        for run_id, result in runs.items()
    }
    common_start = max(held_dates.values())
    common_end = min(
        min(max(return_map) for return_map in return_maps.values()),
        COMMON_WINDOW_EXPECTED_END,
    )
    common_dates = set.intersection(
        *(set(return_map) for return_map in return_maps.values())
    )
    sessions = sorted(
        day for day in common_dates if common_start <= day <= common_end
    )
    if len(sessions) < 2:
        raise ValueError("The source runs have fewer than two common fleet return dates")

    outputs: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    by_cost: dict[int, dict[str, Any]] = {}
    for cost_bps in COST_SCENARIOS:
        baseline_ids = _reference_ids_for_cost(cost_bps)
        base = {
            "bot1": [return_maps[baseline_ids["bot1"]][day] for day in sessions],
            "bot3": [return_maps[baseline_ids["bot3"]][day] for day in sessions],
        }
        with_bot2_id = baseline_ids["bot2_candidate_a"]
        without_bot2_id = _bil_reference_key(cost_bps)
        with_returns = {
            **base,
            "bot2_candidate_a": [
                return_maps[with_bot2_id][day] for day in sessions
            ],
        }
        without_returns = {
            **base,
            "bot2_bil_buy_and_hold": [
                return_maps[without_bot2_id][day] for day in sessions
            ],
        }
        with_metrics, with_curve = _fleet_metrics(with_returns, sessions)
        without_metrics, without_curve = _fleet_metrics(without_returns, sessions)
        with_standalone = {
            name: _sharpe(values) for name, values in with_returns.items()
        }
        without_standalone = {
            name: _sharpe(values) for name, values in without_returns.items()
        }
        delta = with_metrics["sharpe"] - without_metrics["sharpe"]
        a_cagr = float(references[with_bot2_id]["metrics"]["cagr"])
        bil_cagr = float(runs[without_bot2_id].metrics["cagr"])
        bar = _evaluate_cost_bar(
            with_metrics["sharpe"],
            without_metrics["sharpe"],
            a_cagr,
            bil_cagr,
        )
        by_cost[cost_bps] = {
            "with_a": with_metrics,
            "without_a": without_metrics,
            "sharpe_delta": bar["sharpe_delta"],
            "candidate_a_cagr_full_period": a_cagr,
            "bil_cagr_full_period": bil_cagr,
            "sharpe_bar_pass": bar["sharpe_bar_pass"],
            "cagr_bar_pass": bar["cagr_bar_pass"],
            "status": bar["status"],
        }
        for mode, metrics, curve, returns, standalone, mode_sources in (
            (
                "with_candidate_A",
                with_metrics,
                with_curve,
                with_returns,
                with_standalone,
                {
                    "bot1": baseline_ids["bot1"],
                    "bot2_candidate_a": with_bot2_id,
                    "bot3": baseline_ids["bot3"],
                },
            ),
            (
                "without_candidate_A",
                without_metrics,
                without_curve,
                without_returns,
                without_standalone,
                {
                    "bot1": baseline_ids["bot1"],
                    "bot2_bil_buy_and_hold": without_bot2_id,
                    "bot3": baseline_ids["bot3"],
                },
            ),
        ):
            report = {
                "mode": mode,
                "cost_bps": cost_bps,
                "metrics": metrics,
                "window": {
                    "start": sessions[0].isoformat(),
                    "end": sessions[-1].isoformat(),
                    "session_count": len(sessions),
                },
                "source_run_refs": mode_sources,
                "standalone_sharpes": standalone,
                "correlation_matrix": _correlation_matrix(returns),
                "sharpe_delta_with_minus_without": bar["sharpe_delta"],
                "candidate_a_cagr_full_period": a_cagr,
                "bil_cagr_full_period": bil_cagr,
                "sharpe_bar_pass": bar["sharpe_bar_pass"],
                "cagr_bar_pass": bar["cagr_bar_pass"],
                "status": bar["status"],
            }
            outputs.append(report)
            records.append(
                {
                    **report,
                    "equity_curve": curve,
                }
            )

    overall_pass = all(
        by_cost[cost]["status"] == "PASS"
        for cost in COST_SCENARIOS
    )
    return {
        "strategy_family": STRATEGY_FAMILY,
        "spec_hash": spec_hash(),
        "expected_window": [
            COMMON_WINDOW_EXPECTED_START.isoformat(),
            COMMON_WINDOW_EXPECTED_END.isoformat(),
        ],
        "actual_window": {
            "start": sessions[0].isoformat(),
            "end": sessions[-1].isoformat(),
            "session_count": len(sessions),
        },
        "first_held_dates": {
            str(run_id): held_day.isoformat()
            for run_id, held_day in held_dates.items()
        },
        "by_cost": {str(cost): by_cost[cost] for cost in COST_SCENARIOS},
        "overall_status": "PASS" if overall_pass else "FAIL",
        "runs": outputs,
        "_records": records,
    }


def _make_data_window(record: Mapping[str, Any]) -> dict[str, Any]:
    window = record["window"]
    return {
        "requested_start": window["start"],
        "requested_end": END_DATE.isoformat(),
        "first_session": window["start"],
        "last_session": window["end"],
        "holdout_cutoff": END_DATE.isoformat(),
        "session_calendar": "intersection_of_source_daily_return_dates",
        "price_source": "Helium public.research_daily_prices via baseline harness runs",
        "component_sources": record["source_run_refs"],
        "source_requested_start": START_DATE.isoformat(),
        "fleet_expected_start": COMMON_WINDOW_EXPECTED_START.isoformat(),
        "fleet_expected_end": COMMON_WINDOW_EXPECTED_END.isoformat(),
    }


def _insert_records(report: Mapping[str, Any]) -> list[int]:
    from db.research_postgres import get_research_conn

    insert_query = """
        INSERT INTO public.exploration_runs
            (strategy_family, parameters, data_window, spec_hash, source,
             sharpe, return_pct, max_drawdown, notes)
        VALUES (%s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)
        RETURNING run_id
    """
    run_ids: list[int] = []
    records = report["_records"]
    if len(records) != 4:
        raise ValueError(f"Expected four fleet records, got {len(records)}")

    with get_research_conn() as conn:
        with conn.cursor() as cur:
            _execute_checked(
                cur,
                "SELECT COUNT(*) FROM public.exploration_runs WHERE strategy_family = %s",
                (STRATEGY_FAMILY,),
            )
            existing = int(cur.fetchone()[0])
            if existing != 0:
                raise RuntimeError(
                    f"{STRATEGY_FAMILY} already has {existing} row(s); refusing duplicate append"
                )
            for record in records:
                parameters = {
                    "family": STRATEGY_FAMILY,
                    "mode": record["mode"],
                    "cost_bps": record["cost_bps"],
                    "spec": SPEC,
                    "spec_hash": spec_hash(),
                    "component_sources": record["source_run_refs"],
                    "starting_equity_per_sleeve": STARTING_EQUITY_PER_SLEEVE,
                    "risk_free_rate": RISK_FREE_RATE,
                    "candidate_a_spec_hash": BOT2_CANDIDATE_A_SPEC_HASH,
                    "fleet_sharpe_delta": record["sharpe_delta_with_minus_without"],
                    "candidate_a_cagr_full_period": record[
                        "candidate_a_cagr_full_period"
                    ],
                    "bil_cagr_full_period": record["bil_cagr_full_period"],
                    "status": record["status"],
                }
                data_window = _make_data_window(record)
                hash_payload = {
                    "strategy_family": STRATEGY_FAMILY,
                    "parameters": parameters,
                    "data_window": data_window,
                }
                row_spec_hash = hashlib.sha256(
                    json.dumps(
                        hash_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest()
                notes = {
                    "classification": "in-sample fleet comparison",
                    "metrics": record["metrics"],
                    "report": {
                        key: value
                        for key, value in record.items()
                        if key != "equity_curve"
                    },
                    "overall_status": report["overall_status"],
                    "fleet_window": report["actual_window"],
                }
                serialized_notes = json.dumps(
                    notes,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if len(serialized_notes) > 4000:
                    raise ValueError(
                        "Fleet notes exceed exploration_runs' 4000-character limit"
                    )
                _execute_checked(
                    cur,
                    insert_query,
                    (
                        STRATEGY_FAMILY,
                        json.dumps(parameters, sort_keys=True, allow_nan=False),
                        json.dumps(data_window, sort_keys=True, allow_nan=False),
                        row_spec_hash,
                        SOURCE,
                        float(record["metrics"]["sharpe"]),
                        float(record["metrics"]["total_return"]) * 100.0,
                        float(record["metrics"]["max_drawdown"]),
                        serialized_notes,
                    ),
                )
                inserted = cur.fetchone()
                if inserted is None:
                    raise RuntimeError("Fleet insert returned no run_id")
                run_ids.append(int(inserted[0]))
            _execute_checked(
                cur,
                "SELECT COUNT(*) FROM public.exploration_runs WHERE strategy_family = %s",
                (STRATEGY_FAMILY,),
            )
            final_count = int(cur.fetchone()[0])
            if final_count != 4:
                raise RuntimeError(
                    f"Expected four {STRATEGY_FAMILY} rows after insert, got {final_count}"
                )
    return run_ids


def run_and_persist() -> dict[str, Any]:
    """Print the frozen spec, compute four cases, then append four Helium rows."""
    print_spec()
    references = _load_reference_runs()
    runs = _load_and_run_source_sleeves(references)
    report = _build_report(runs, references)
    run_ids = _insert_records(report)
    report["run_ids"] = run_ids
    report.pop("_records", None)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--print-spec", action="store_true")
    actions.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    if args.print_spec:
        print_spec()
    elif args.run:
        output = run_and_persist()
        print(json.dumps(output, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())