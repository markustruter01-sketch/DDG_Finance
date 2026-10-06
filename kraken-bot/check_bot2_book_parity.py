#!/usr/bin/env python3
"""Compare the memory-bounded Bot 2 book with /tmp/bot2_baseline.json."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import resource
import sys
import time
import types
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path("/tmp/bot2_baseline.json")
BATCHED_PATH = Path("/tmp/bot2_batched.json")
COMPARISON_PATH = Path("/tmp/bot2_comparison.json")


def _deny_database_access(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("Database access is disabled for the parity check")


def _load_strategy():
    sys.path.insert(0, str(ROOT / "trading-platform"))

    # Importing the real database module initializes its connection pool. This
    # Alpaca-only check must not initialize or access any database.
    db_package = types.ModuleType("db")
    db_package.__path__ = []
    postgres = types.ModuleType("db.postgres")
    postgres.get_conn = _deny_database_access
    postgres.__getattr__ = lambda _name: _deny_database_access
    db_package.postgres = postgres
    sys.modules["db"] = db_package
    sys.modules["db.postgres"] = postgres

    strategy_path = ROOT / "kraken-bot" / "bot2_momentum_strategy.py"
    spec = importlib.util.spec_from_file_location(
        "bot2_momentum_parity_check", strategy_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load strategy from {strategy_path}")
    strategy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = strategy
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(strategy)
    strategy.get_conn = _deny_database_access
    return strategy


def _parse_funnel(line: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for segment in (item.strip() for item in line.split("|")[1:]):
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        if value == "None":
            values[key] = None
            continue
        try:
            values[key] = int(value)
        except ValueError:
            try:
                values[key] = float(value)
            except ValueError:
                values[key] = value
    return values


def _run() -> dict[str, Any]:
    if not BASELINE_PATH.is_file():
        raise FileNotFoundError(f"Baseline file is missing: {BASELINE_PATH}")
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    as_of = date.fromisoformat(baseline["as_of"])
    feed = os.environ.get("BOT2_ALPACA_DATA_FEED", "sip").strip().lower()
    if baseline.get("feed") != feed:
        raise RuntimeError(
            f"Feed mismatch: baseline={baseline.get('feed')} current={feed}"
        )

    strategy = _load_strategy()
    api_key = os.environ.get("ALPACA_BB_API_KEY", "")
    secret_key = os.environ.get("ALPACA_BB_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError("Required Alpaca credentials are unavailable")

    class GetOnlyClient(strategy.AlpacaMomentumClient):
        def _request(self, method: str, path: str, **kwargs: Any) -> Any:
            if method != "GET" or path != "/v2/assets":
                raise RuntimeError("Parity check denied non-asset Alpaca request")
            return super()._request(method, path, **kwargs)

        def _data_request(self, method: str, path: str, **kwargs: Any) -> Any:
            if method != "GET" or path != "/v2/stocks/bars":
                raise RuntimeError("Parity check denied non-bars Alpaca request")
            return super()._data_request(method, path, **kwargs)

    client = GetOnlyClient(api_key, secret_key)
    captured = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(captured):
        ranked, screened, summaries = strategy._build_book_batched(client, as_of)
    wall_seconds = time.perf_counter() - started
    funnel_line = next(
        (
            line for line in captured.getvalue().splitlines()
            if line.startswith("LIVE_FUNNEL | ")
        ),
        None,
    )
    if funnel_line is None:
        raise RuntimeError("Batched book did not emit a LIVE_FUNNEL line")

    ranked_output = [
        {
            "symbol": str(row["symbol"]),
            "score": float(row["momentum"]),
            "prior_close": float(row["price"]),
        }
        for row in ranked
    ]
    batched = {
        "as_of": as_of.isoformat(),
        "feed": feed,
        "screened_symbols": sorted(screened),
        "ranked_top50": ranked_output,
        "live_funnel_line": funnel_line,
        "live_funnel": _parse_funnel(funnel_line),
        "wall_seconds": wall_seconds,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "summary_count": len(summaries),
    }
    BATCHED_PATH.write_text(
        json.dumps(batched, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    baseline_symbols = baseline["screened_symbols"]
    batched_symbols = batched["screened_symbols"]
    baseline_rank = baseline["ranked_top50"]
    batched_rank = batched["ranked_top50"]
    baseline_order = [row["symbol"] for row in baseline_rank]
    batched_order = [row["symbol"] for row in batched_rank]
    batched_by_symbol = {row["symbol"]: row for row in batched_rank}
    score_differences = []
    close_differences = []
    for old_row in baseline_rank:
        new_row = batched_by_symbol.get(old_row["symbol"])
        if new_row is None:
            score_differences.append(
                {"symbol": old_row["symbol"], "missing_from_batched": True}
            )
            close_differences.append(
                {"symbol": old_row["symbol"], "missing_from_batched": True}
            )
            continue
        score_difference = abs(
            float(old_row["score"]) - float(new_row["score"])
        )
        close_difference = abs(
            float(old_row["prior_close"]) - float(new_row["prior_close"])
        )
        if score_difference:
            score_differences.append({
                "symbol": old_row["symbol"],
                "absolute_difference": score_difference,
            })
        if close_difference:
            close_differences.append({
                "symbol": old_row["symbol"],
                "absolute_difference": close_difference,
            })

    maximum_score_difference = max(
        (
            abs(float(old_row["score"]) - float(batched_by_symbol[old_row["symbol"]]["score"]))
            for old_row in baseline_rank
            if old_row["symbol"] in batched_by_symbol
        ),
        default=0.0,
    )
    comparison = {
        "as_of": as_of.isoformat(),
        "feed": feed,
        "baseline_file": str(BASELINE_PATH),
        "batched_file": str(BATCHED_PATH),
        "screened_500": {
            "baseline_count": len(baseline_symbols),
            "batched_count": len(batched_symbols),
            "identical": (
                set(baseline_symbols) == set(batched_symbols)
                and len(baseline_symbols) == 500
            ),
            "missing_from_batched": sorted(
                set(baseline_symbols) - set(batched_symbols)
            ),
            "extra_in_batched": sorted(
                set(batched_symbols) - set(baseline_symbols)
            ),
            "baseline_sha256": hashlib.sha256(
                "\n".join(sorted(baseline_symbols)).encode()
            ).hexdigest(),
            "batched_sha256": hashlib.sha256(
                "\n".join(sorted(batched_symbols)).encode()
            ).hexdigest(),
        },
        "top_50": {
            "baseline_count": len(baseline_rank),
            "batched_count": len(batched_rank),
            "identical_order": (
                baseline_order == batched_order and len(baseline_order) == 50
            ),
            "baseline_symbols": baseline_order,
            "batched_symbols": batched_order,
        },
        "scores": {
            "tolerance": 1e-9,
            "max_absolute_difference": maximum_score_difference,
            "all_within_tolerance": (
                maximum_score_difference <= 1e-9
                and not any(
                    "missing_from_batched" in item
                    for item in score_differences
                )
            ),
            "nonzero_differences": score_differences,
        },
        "prior_closes": {
            "identical": (
                not close_differences and baseline_order == batched_order
            ),
            "nonzero_differences": close_differences,
        },
        "live_funnel": {
            "identical": baseline["live_funnel"] == batched["live_funnel"],
            "baseline": baseline["live_funnel"],
            "batched": batched["live_funnel"],
        },
        "performance": {
            "baseline_wall_seconds": baseline["wall_seconds"],
            "batched_wall_seconds": wall_seconds,
            "wall_time_change_seconds": (
                wall_seconds - baseline["wall_seconds"]
            ),
            "baseline_peak_rss_kib": baseline["peak_rss_kib"],
            "batched_peak_rss_kib": batched["peak_rss_kib"],
            "peak_rss_reduction_percent": (
                100
                * (baseline["peak_rss_kib"] - batched["peak_rss_kib"])
                / baseline["peak_rss_kib"]
                if baseline["peak_rss_kib"]
                else None
            ),
            "summary_count": len(summaries),
        },
    }
    COMPARISON_PATH.write_text(
        json.dumps(comparison, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return comparison


if __name__ == "__main__":
    result = _run()
    print(json.dumps(result, sort_keys=True, indent=2))
    if not all((
        result["screened_500"]["identical"],
        result["top_50"]["identical_order"],
        result["scores"]["all_within_tolerance"],
        result["prior_closes"]["identical"],
        result["live_funnel"]["identical"],
    )):
        raise SystemExit(2)
