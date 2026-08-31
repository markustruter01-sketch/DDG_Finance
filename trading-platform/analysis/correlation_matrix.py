"""
correlation_matrix.py — Rolling Bot-to-Bot Correlation & Systemic Shock Detector (Stage 3)
==========================================================================================
Computes a rolling 60-day Pearson correlation matrix between all bot daily returns.

When correlation converges toward 1.0 (all bots winning/losing together),
this indicates a systemic shock scenario where diversification has failed.
The system responds by auto-scaling position sizes by 50%.

Data source: canonical bot_daily_returns rows (PostgreSQL).  Dates are
intersected before pairwise calculations; missing dates are never padded or
matched by list position.

Output: correlation_state.json with:
  - matrix: dict of bot-pair → correlation coefficient
  - max_correlation: float (highest off-diagonal correlation)
  - systemic_shock: bool (True if max_correlation > SHOCK_THRESHOLD)
  - position_scale_factor: float (1.0 normal, 0.5 during shock)
  - computed_at: ISO timestamp
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from core.market_clock import ET

_DATA_DIR = Path(__file__).parent.parent / "data"
_CORR_FILE = _DATA_DIR / "correlation_state.json"

ROLLING_WINDOW_DAYS = 60
SHOCK_THRESHOLD = 0.85
SHOCK_SCALE_FACTOR = 0.50
MIN_DATA_POINTS = 3

_cache: dict[str, Any] = {"data": None, "ts": 0}
_CACHE_TTL = 900


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < MIN_DATA_POINTS or n != len(y):
        return None

    mx = sum(x) / n
    my = sum(y) / n

    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))

    if sx < 1e-12 or sy < 1e-12:
        return None

    return cov / (sx * sy)


def _daily_returns(values: list[float]) -> list[float]:
    if len(values) < 2:
        return []
    returns = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev > 0:
            returns.append((values[i] - prev) / prev)
        else:
            returns.append(0.0)
    return returns


def compute_correlation_matrix() -> dict:
    """
    Compute pair-wise Pearson correlation of canonical daily returns over the
    exact dates present for every included bot.
    """
    try:
        from analysis.research_ledger import (
            MEANINGFUL_HISTORY_THRESHOLD,
            get_fleet_daily_returns,
        )
        rolling_start = datetime.now(ET).date() - timedelta(
            days=ROLLING_WINDOW_DAYS
        )
        aligned = get_fleet_daily_returns(start_date=rolling_start)
    except Exception as exc:
        logger.warning(f"CorrMatrix | canonical return query failed: {exc}")
        return _empty_result("db_error")

    bot_names = list(aligned["bot_ids"])
    returns = aligned["returns"]
    common_data_points = int(aligned["common_data_points"])
    matrix: dict[str, float | None] = {}
    max_corr = -1.0
    max_pair = ""

    for i in range(len(bot_names)):
        for j in range(i + 1, len(bot_names)):
            a, b = bot_names[i], bot_names[j]
            ra, rb = returns[a], returns[b]

            if common_data_points < MIN_DATA_POINTS:
                matrix[f"{a}_vs_{b}"] = None
                continue

            corr = _pearson(ra, rb)
            if corr is not None:
                matrix[f"{a}_vs_{b}"] = round(corr, 4)
                if corr > max_corr:
                    max_corr = corr
                    max_pair = f"{a}_vs_{b}"
            else:
                matrix[f"{a}_vs_{b}"] = None

    systemic_shock = max_corr > SHOCK_THRESHOLD
    scale_factor = SHOCK_SCALE_FACTOR if systemic_shock else 1.0

    if systemic_shock:
        logger.warning(
            f"CorrMatrix | SYSTEMIC SHOCK — max_corr={max_corr:.3f} ({max_pair}) > "
            f"{SHOCK_THRESHOLD} — position scaling reduced to {scale_factor:.0%}"
        )
    else:
        logger.debug(
            f"CorrMatrix | max_corr={max_corr:.3f} ({max_pair}) — normal operations"
        )

    data_points = {b: len(returns[b]) for b in bot_names}

    result = {
        "matrix": matrix,
        "max_correlation": round(max_corr, 4) if max_corr >= 0 else None,
        "max_pair": max_pair,
        "systemic_shock": systemic_shock,
        "position_scale_factor": scale_factor,
        "shock_threshold": SHOCK_THRESHOLD,
        "data_points": data_points,
        "common_data_points": common_data_points,
        "meaningful_history": {
            "threshold": MEANINGFUL_HISTORY_THRESHOLD,
            "status": "PROPOSED",
            "met": common_data_points >= MEANINGFUL_HISTORY_THRESHOLD,
        },
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CORR_FILE.write_text(json.dumps(result, indent=2))
    except Exception as exc:
        logger.warning(f"CorrMatrix | File write failed: {exc}")

    _cache["data"] = result
    _cache["ts"] = time.time()

    return result


def get_equity_crypto_correlation() -> float:
    state = get_cached_state()
    if state is None:
        return 0.0
    matrix = state.get("matrix", {})
    corr = matrix.get("alpaca_vs_kraken")
    return corr if corr is not None else 0.0


def get_position_scale_factor() -> float:
    state = get_cached_state()
    if state is None:
        return 1.0
    return state.get("position_scale_factor", 1.0)


def get_cached_state() -> dict | None:
    if _cache["data"] and (time.time() - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        if _CORR_FILE.exists():
            data = json.loads(_CORR_FILE.read_text())
            written = data.get("computed_at", "")
            if written:
                age = (
                    datetime.now(timezone.utc) - datetime.fromisoformat(written)
                ).total_seconds()
                if age < _CACHE_TTL:
                    _cache["data"] = data
                    _cache["ts"] = time.time()
                    return data
    except Exception:
        pass

    return None


def _empty_result(reason: str) -> dict:
    return {
        "matrix": {},
        "max_correlation": None,
        "max_pair": "",
        "systemic_shock": False,
        "position_scale_factor": 1.0,
        "shock_threshold": SHOCK_THRESHOLD,
        "data_points": {},
        "common_data_points": 0,
        "meaningful_history": {
            "threshold": 60,
            "status": "PROPOSED",
            "met": False,
        },
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "note": reason,
    }
