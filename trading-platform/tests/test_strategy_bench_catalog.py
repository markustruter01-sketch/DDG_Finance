from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone

from research.strategy_bench_catalog import (
    EXPLORATION_QUERY,
    LEDGER_QUERY,
    build_catalog,
    fetch_live_catalog,
    load_snapshot,
)


def _experiment(**overrides):
    row = {
        "experiment_id": 7,
        "strategy_family": "unit_family",
        "hypothesis": "A testable hypothesis",
        "parameters": {
            "lookback": 20,
            "api_key": "must-not-ship",
            "universe": ["A", "B", "C"],
        },
        "pass_bar": {"sharpe_min": 0.5},
        "data_window": {
            "start": "2020-01-01",
            "end": "2024-12-31",
            "daily_returns": [0.1, 0.2],
            "price_source": "adjusted_close",
        },
        "results": {
            "pooled_primary": {
                "sharpe": 0.82,
                "return": 0.34,
                "max_drawdown": -0.12,
                "daily_equity": [100, 101, 102],
            }
        },
        "outcome": "PASS",
        "created_at": datetime(2026, 10, 4, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _run():
    return {
        "run_id": 91,
        "strategy_family": "unit_family",
        "parameters": {"allocation": 0.4, "private_token": "must-not-ship"},
        "data_window": {"backtest_start": "2020-01-01"},
        "source": "backtest_harness",
        "sharpe": 0.9,
        "return_pct": 18.5,
        "max_drawdown": 0.15,
        "created_at": datetime(2026, 10, 4, tzinfo=timezone.utc),
    }


def test_build_catalog_compacts_metrics_and_excludes_secrets_and_series():
    catalog = build_catalog(
        [_experiment()],
        [_run()],
        generated_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
    )

    assert catalog["generated_at"] == "2026-10-05T00:00:00Z"
    assert catalog["row_counts"] == {"experiments": 1, "exploration_runs": 1}
    experiment = catalog["experiments"][0]
    assert experiment["outcome"] == "PASS"
    assert experiment["metrics"] == {
        "sharpe": 0.82,
        "return_pct": 34.0,
        "max_drawdown_pct": 12.0,
    }
    assert experiment["data_window"]["start"] == "2020-01-01"
    assert "daily_returns" not in experiment["data_window"]
    assert "api_key" not in experiment["parameters_summary"]
    assert "must-not-ship" not in json.dumps(catalog)
    assert "daily_equity" not in json.dumps(catalog)
    assert catalog["exploration_runs"][0]["return_pct"] == 18.5
    assert catalog["exploration_runs"][0]["max_drawdown"] == 15.0


def test_fetch_live_catalog_uses_read_only_transaction_and_only_selects():
    queries: list[str] = []

    class Cursor:
        description = []

        def __init__(self):
            self.rows = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            queries.append(sql)
            if "research_ledger" in sql:
                data = _experiment()
                columns = [
                    "experiment_id",
                    "strategy_family",
                    "hypothesis",
                    "parameters",
                    "pass_bar",
                    "data_window",
                    "results",
                    "outcome",
                    "created_at",
                ]
            else:
                data = _run()
                columns = [
                    "run_id",
                    "strategy_family",
                    "parameters",
                    "data_window",
                    "source",
                    "sharpe",
                    "return_pct",
                    "max_drawdown",
                    "created_at",
                ]
            self.description = [(column,) for column in columns]
            self.rows = [tuple(data[column] for column in columns)]

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.readonly = False
            self.rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def rollback(self):
            self.rolled_back = True

        def set_session(self, *, readonly):
            self.readonly = readonly

        def cursor(self):
            return self.cursor_instance

    connection = Connection()

    @contextmanager
    def connection_factory():
        yield connection

    catalog = fetch_live_catalog(connection_factory)

    assert connection.rolled_back
    assert connection.readonly
    assert len(queries) == 2
    assert queries == [LEDGER_QUERY, EXPLORATION_QUERY]
    assert all(query.lstrip().upper().startswith("SELECT") for query in queries)
    assert catalog["source"] == "live_research_database"
    assert catalog["row_counts"] == {"experiments": 1, "exploration_runs": 1}


def test_load_snapshot_recomputes_counts_and_labels_as_committed(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-05T00:00:00Z",
                "row_counts": {"experiments": 999, "exploration_runs": 999},
                "experiments": [_experiment()],
                "exploration_runs": [_run()],
            },
            default=str,
        ),
        encoding="utf-8",
    )

    snapshot = load_snapshot(str(snapshot_path))

    assert snapshot["source"] == "committed_snapshot"
    assert snapshot["snapshot_as_of"] == "2026-10-05T00:00:00Z"
    assert snapshot["row_counts"] == {"experiments": 1, "exploration_runs": 1}

def test_committed_snapshot_marks_void_records_without_changing_them():
    """Handoff v9's void list: experiments 4, 7, 10, 13, 17 and the 3 Sept sweep."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "strategy_bench_snapshot.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    served = load_snapshot(str(path))

    not_counted = sorted(e["id"] for e in served["experiments"] if not e["counted"])
    assert not_counted == [4, 7, 10, 13, 17]
    sweep = [r for r in served["exploration_runs"] if not r["counted"]]
    assert len(sweep) == 64
    assert {r["family"] for r in sweep} == {"bot2_momentum_rank500_sweep"}
    assert {r["created_at"][:10] for r in sweep} == {"2026-09-03"}
    assert all(r["not_counted_reason"].startswith("Not counted:") for r in sweep)
    assert all("not_counted_reason" not in r for r in served["exploration_runs"] if r["counted"])
    # the recorded outcomes and numbers are served exactly as stored
    by_id = {e["id"]: e for e in raw["experiments"]}
    for e in served["experiments"]:
        assert e["outcome"] == by_id[e["id"]]["outcome"] and e["metrics"] == by_id[e["id"]]["metrics"]


def test_harness_ledger_rows_become_counted_experiments(tmp_path):
    import json
    from research.strategy_bench_catalog import with_harness_ledger

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(row) for row in [
        {"registration_id": "GEAR-V1-G4", "kind": "holdout_test", "ran_at": "2026-10-22T05:32:30+00:00",
         "result": {"verdict": "FAIL: 3_max_drawdown_smaller_than_spy", "pass_bar": {"1_cagr_beats_spy": True},
                    "summary": {"sharpe_excess_tbill": 0.76, "total_return_pct": 160.82,
                                "max_drawdown_pct": -24.5, "from": "2021-01-04", "to": "2026-10-15"}}},
        {"registration_id": "FX-BT1", "kind": "replication", "ran_at": "2026-10-15T18:49:34+00:00",
         "result": {"reproduced": True, "summary": {"sharpe_daily_rf0": -0.02, "total_return_pct": -17.62,
                                                    "max_drawdown_pct": -33.88}}},
    ]) + "\n", encoding="utf-8")
    catalog = {"experiments": [{"id": 1}], "exploration_runs": [], "row_counts": {"experiments": 1, "exploration_runs": 0},
               "source_label": "Committed Helium research snapshot"}

    served = with_harness_ledger(catalog, str(ledger))

    gear, fx = served["experiments"][1:]
    assert (gear["id"], gear["outcome"], gear["counted"]) == ("GEAR-V1-G4", "FAIL", True)
    assert gear["metrics"] == {"sharpe": 0.76, "return_pct": 160.82, "max_drawdown_pct": -24.5}
    assert gear["family"].startswith("atlas")
    assert (fx["outcome"], fx["metrics"]["sharpe"]) == ("REPRODUCED", -0.02)
    assert served["row_counts"]["experiments"] == 3
    assert served["source_label"].endswith("research harness ledger")
