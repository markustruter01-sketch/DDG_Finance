"""Read-only catalog projection for Strategy Bench records."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any, Callable


LEDGER_QUERY = """
    SELECT experiment_id, strategy_family, hypothesis, parameters, pass_bar,
           data_window, results, outcome, created_at
    FROM public.research_ledger
    ORDER BY experiment_id
"""

EXPLORATION_QUERY = """
    SELECT run_id, strategy_family, parameters, data_window, source, sharpe,
           return_pct, max_drawdown, created_at
    FROM public.exploration_runs
    ORDER BY run_id DESC
"""

_SENSITIVE_KEY = re.compile(
    r"(?:password|secret|token|credential|api[_-]?key|dsn|connection.?string)",
    re.IGNORECASE,
)
_CONNECTION_STRING = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|redis)://[^\s\"'<>]+", re.IGNORECASE
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"\b(api[_-]?key|secret|token|password|credential)\s*[:=]\s*[^,\s;}]+",
    re.IGNORECASE,
)
_SERIES_KEY = re.compile(
    r"(?:daily[_-]?returns?|daily[_-]?series|equity[_-]?curve|"
    r"price[_-]?series|return[_-]?series|curve[_-]?points|"
    r"^(?:bars|daily_equity|equity_values)$)",
    re.IGNORECASE,
)


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value)
    text = _CONNECTION_STRING.sub("[redacted connection string]", text)
    text = _CREDENTIAL_ASSIGNMENT.sub(r"\1=[redacted]", text)
    return text[:limit]


def _iso_utc(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return _safe_text(value, 100)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _compact_tree(value: Any, depth: int = 0) -> Any:
    """Retain useful descriptive fields without copying large data series."""
    if depth > 5:
        return "[nested details omitted]"
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            safe_key = _safe_text(key, 80)
            if _SENSITIVE_KEY.search(safe_key) or _SERIES_KEY.search(safe_key):
                continue
            compact[safe_key] = _compact_tree(item, depth + 1)
        return compact
    if isinstance(value, (list, tuple)):
        if len(value) > 12:
            return f"[{len(value)} items omitted]"
        return [_compact_tree(item, depth + 1) for item in value]
    if isinstance(value, datetime) or isinstance(value, date):
        return _iso_utc(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (int, bool)) or value is None:
        return value
    return _safe_text(value)


def _brief_parameter_value(value: Any) -> str:
    if isinstance(value, dict):
        return f"{len(value)} fields"
    if isinstance(value, (list, tuple)):
        return f"{len(value)} items"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        return "null"
    return _safe_text(value, 100)


def _parameters_summary(parameters: Any) -> str:
    if not isinstance(parameters, dict):
        return _brief_parameter_value(parameters)
    pairs = [
        f"{_safe_text(key, 80)}={_brief_parameter_value(value)}"
        for key, value in sorted(parameters.items(), key=lambda pair: str(pair[0]))
        if not _SENSITIVE_KEY.search(str(key))
    ][:18]
    summary = "; ".join(pairs)
    return summary[:700] if summary else "No public parameters recorded"


def _metric_candidates(
    value: Any, path: tuple[str, ...] = (), depth: int = 0
) -> list[tuple[str, str, float]]:
    if depth > 12:
        return []
    found: list[tuple[str, str, float]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text) or _SERIES_KEY.search(key_text):
                continue
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                number = float(item)
                if math.isfinite(number):
                    found.append((key_text, ".".join((*path, key_text)), number))
            else:
                found.extend(
                    _metric_candidates(item, (*path, key_text), depth + 1)
                )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value[:100]):
            found.extend(
                _metric_candidates(item, (*path, str(index)), depth + 1)
            )
    return found


def _metric_score(key: str, path: str, kind: str) -> tuple[int, int, str]:
    key_normalized = key.lower().replace("-", "_")
    path_normalized = path.lower().replace("-", "_")
    score = 0
    if "pooled_primary" in path_normalized:
        score += 120
    elif "primary" in path_normalized:
        score += 90
    elif "pooled" in path_normalized:
        score += 70
    elif "validation" in path_normalized:
        score += 55
    elif "evaluation" in path_normalized:
        score += 45
    if any(term in path_normalized for term in ("random", "control", "benchmark")):
        score -= 100
    if kind == "return":
        if key_normalized in {"return_pct", "total_return_pct"}:
            score += 35
        elif key_normalized in {"return", "total_return"}:
            score += 25
        elif key_normalized == "cagr":
            score -= 10
    elif kind == "max_drawdown":
        if key_normalized.endswith("_pct") or key_normalized.endswith("_percent"):
            score += 30
        if key_normalized in {"max_drawdown", "maxdd"}:
            score += 20
    elif "sharpe" in key_normalized:
        score += 20
    return (score, -len(path), path)


def _normalized_metric(results: Any, kind: str) -> float | None:
    aliases = {
        "sharpe": {"sharpe", "sharpe_ratio", "pooled_sharpe", "pooled_primary_sharpe"},
        "return": {"return", "return_pct", "total_return", "total_return_pct", "cagr"},
        "max_drawdown": {
            "max_drawdown",
            "max_drawdown_pct",
            "max_drawdown_percent",
            "maxdd",
            "maxdd_pct",
        },
    }[kind]
    candidates = [
        entry
        for entry in _metric_candidates(results)
        if entry[0].lower().replace("-", "_") in aliases
    ]
    if not candidates:
        return None
    key, path, value = max(
        candidates, key=lambda item: _metric_score(item[0], item[1], kind)
    )
    normalized_key = key.lower().replace("-", "_")
    if kind == "sharpe":
        return value
    if kind == "return":
        return value if normalized_key.endswith(("_pct", "_percent")) else value * 100
    return abs(value) if normalized_key.endswith(("_pct", "_percent")) else abs(value) * 100


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_catalog(
    experiments: list[dict[str, Any]],
    exploration_runs: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    source: str = "helium_research_database_snapshot",
    source_label: str = "Helium research database; read-only export",
) -> dict[str, Any]:
    """Project the two research tables into a small, secret-safe UI contract."""
    stamp = _iso_utc(generated_at or datetime.now(timezone.utc))
    clean_experiments = []
    for row in experiments:
        results = row.get("results")
        clean_experiments.append(
            {
                "id": int(row["experiment_id"]),
                "family": _safe_text(row.get("strategy_family", ""), 120),
                "hypothesis": _safe_text(row.get("hypothesis", ""), 700),
                "parameters_summary": _parameters_summary(row.get("parameters")),
                "pass_bar": _compact_tree(row.get("pass_bar")),
                "data_window": _compact_tree(row.get("data_window")),
                "metrics": {
                    "sharpe": _normalized_metric(results, "sharpe"),
                    "return_pct": _normalized_metric(results, "return"),
                    "max_drawdown_pct": _normalized_metric(results, "max_drawdown"),
                },
                "outcome": (
                    _safe_text(row["outcome"], 80)
                    if row.get("outcome") is not None
                    else "PENDING"
                ),
                "created_at": _iso_utc(row.get("created_at")),
            }
        )

    clean_runs = []
    for row in exploration_runs:
        clean_runs.append(
            {
                "id": int(row["run_id"]),
                "family": _safe_text(row.get("strategy_family", ""), 120),
                "parameters_summary": _parameters_summary(row.get("parameters")),
                "data_window": _compact_tree(row.get("data_window")),
                "sharpe": _number_or_none(row.get("sharpe")),
                "return_pct": _number_or_none(row.get("return_pct")),
                "max_drawdown": (
                    abs(_number_or_none(row.get("max_drawdown"))) * 100
                    if _number_or_none(row.get("max_drawdown")) is not None
                    else None
                ),
                "source": _safe_text(row.get("source") or "", 180),
                "created_at": _iso_utc(row.get("created_at")),
            }
        )

    return mark_counted({
        "schema_version": 1,
        "generated_at": stamp,
        "snapshot_as_of": stamp,
        "source": source,
        "source_label": source_label,
        "row_counts": {
            "experiments": len(clean_experiments),
            "exploration_runs": len(clean_runs),
        },
        "experiments": clean_experiments,
        "exploration_runs": clean_runs,
    })


# Records that do not count as evidence. Source: handoff v9 (5 Oct 2026),
# "Void results" and "Citing experiment 7 or experiment 4 as evidence".
# Marked when served; the research tables and the committed snapshot stay
# exactly as recorded.
_NO_WINDOW = (
    "Not counted: no data window was recorded and it was never tied to rules "
    "(handoff v9, 5 Oct 2026)."
)
_VOID = "Not counted: listed as a void result in handoff v9 (5 Oct 2026)."
NOT_COUNTED_EXPERIMENTS = {4: _NO_WINDOW, 7: _NO_WINDOW, 10: _VOID, 13: _VOID, 17: _VOID}
NOT_COUNTED_RUN_FAMILIES = {
    "bot2_momentum_rank500_sweep": (
        "Not counted: the 3 Sept 2026 64-combination sweep, descriptive only "
        "with no pass bar; listed as void in handoff v9 (5 Oct 2026)."
    ),
}


def mark_counted(catalog: dict[str, Any]) -> dict[str, Any]:
    """Add ``counted`` (and ``not_counted_reason`` when false) to every row."""
    for row in catalog["experiments"]:
        reason = NOT_COUNTED_EXPERIMENTS.get(row.get("id"))
        row["counted"] = reason is None
        if reason:
            row["not_counted_reason"] = reason
    for row in catalog["exploration_runs"]:
        reason = NOT_COUNTED_RUN_FAMILIES.get(str(row.get("family", "")))
        row["counted"] = reason is None
        if reason:
            row["not_counted_reason"] = reason
    return catalog


def _rows_as_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_live_catalog(connection_factory: Callable[[], Any]) -> dict[str, Any]:
    """Read both research tables under a PostgreSQL read-only transaction."""
    with connection_factory() as connection:
        connection.rollback()
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute(LEDGER_QUERY)
            experiments = _rows_as_dicts(cursor)
            cursor.execute(EXPLORATION_QUERY)
            exploration_runs = _rows_as_dicts(cursor)
    return build_catalog(
        experiments,
        exploration_runs,
        source="live_research_database",
        source_label="Helium research database · workspace read-only",
    )


def load_snapshot(path: str) -> dict[str, Any]:
    """Load and validate the committed snapshot before it is served."""
    import json

    with open(path, encoding="utf-8") as handle:
        snapshot = json.load(handle)
    required = {
        "generated_at",
        "row_counts",
        "experiments",
        "exploration_runs",
    }
    if not isinstance(snapshot, dict) or not required.issubset(snapshot):
        raise ValueError("Committed Strategy Bench snapshot has an invalid shape")
    if not isinstance(snapshot["experiments"], list) or not isinstance(
        snapshot["exploration_runs"], list
    ):
        raise ValueError("Committed Strategy Bench snapshot rows must be arrays")
    snapshot["source"] = "committed_snapshot"
    snapshot["source_label"] = "Committed Helium research snapshot"
    snapshot["snapshot_as_of"] = snapshot["generated_at"]
    snapshot.setdefault("schema_version", 1)
    snapshot["row_counts"] = {
        "experiments": len(snapshot["experiments"]),
        "exploration_runs": len(snapshot["exploration_runs"]),
    }
    return mark_counted(snapshot)