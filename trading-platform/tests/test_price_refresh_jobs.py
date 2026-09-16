from __future__ import annotations

import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import main
from analysis import bot3_data_pipeline, crypto_data_pipeline


class _RecordingScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, **kwargs):
        self.jobs.append(kwargs)


def _fake_logger(monkeypatch):
    records = {"info": [], "error": []}
    monkeypatch.setattr(
        main,
        "logger",
        SimpleNamespace(
            info=lambda message: records["info"].append(message),
            error=lambda message: records["error"].append(message),
        ),
    )
    return records


def test_yahoo_refresh_jobs_schedule_delayed_first_run_and_six_hour_interval(monkeypatch):
    calls = []
    records = _fake_logger(monkeypatch)
    monkeypatch.setattr(
        crypto_data_pipeline,
        "ingest_yahoo_history",
        lambda: calls.append("crypto") or {"BTC/USD": 10, "ETH/USD": 11},
    )
    monkeypatch.setattr(
        bot3_data_pipeline,
        "ingest_metals",
        lambda: calls.append("metals") or {"GLD": 12, "SLV": 13},
    )
    scheduler = _RecordingScheduler()
    before_registration = datetime.now(timezone.utc)

    main._register_yahoo_refresh_jobs(scheduler)

    assert calls == []
    assert [job["id"] for job in scheduler.jobs] == [
        "crypto_yahoo_history_refresh",
        "bot3_metals_history_refresh",
    ]
    assert all(job["replace_existing"] is True for job in scheduler.jobs)
    assert all(job["misfire_grace_time"] == 300 for job in scheduler.jobs)
    assert all(job["trigger"].interval.total_seconds() == 6 * 60 * 60 for job in scheduler.jobs)
    assert all(job["next_run_time"] >= before_registration for job in scheduler.jobs)
    assert all(
        50 <= (job["next_run_time"] - before_registration).total_seconds() <= 70
        for job in scheduler.jobs
    )
    assert any("6-hour interval" in message for message in records["info"])


def test_yahoo_refresh_registration_makes_no_network_or_pipeline_call(monkeypatch):
    def fail_if_called():
        raise AssertionError("Yahoo refresh ran during job registration")

    monkeypatch.setattr(main, "_refresh_crypto_yahoo_history", fail_if_called)
    monkeypatch.setattr(main, "_refresh_bot3_metals_history", fail_if_called)
    scheduler = _RecordingScheduler()

    main._register_yahoo_refresh_jobs(scheduler)

    assert [job["id"] for job in scheduler.jobs] == [
        "crypto_yahoo_history_refresh",
        "bot3_metals_history_refresh",
    ]


@pytest.mark.parametrize(
    ("job", "pipeline", "ingest_name", "error_type", "failure_text"),
    [
        (
            main._refresh_crypto_yahoo_history,
            crypto_data_pipeline,
            "ingest_yahoo_history",
            "crypto_yahoo_history_refresh_failed",
            "crypto refresh unavailable",
        ),
        (
            main._refresh_bot3_metals_history,
            bot3_data_pipeline,
            "ingest_metals",
            "bot3_metals_history_refresh_failed",
            "metals refresh unavailable",
        ),
    ],
)
def test_yahoo_refresh_failures_log_error_and_record_degradation(
    monkeypatch,
    job,
    pipeline,
    ingest_name,
    error_type,
    failure_text,
):
    records = _fake_logger(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        ingest_name,
        lambda: (_ for _ in ()).throw(RuntimeError(failure_text)),
    )
    degradation_records = []
    degradation_tracker = importlib.import_module("core.degradation_tracker")
    monkeypatch.setattr(
        degradation_tracker,
        "record_degradation",
        lambda **kwargs: degradation_records.append(kwargs),
    )

    job()

    assert any(failure_text in message for message in records["error"])
    assert len(degradation_records) == 1
    record = degradation_records[0]
    assert record["component"] == "data_pipeline"
    assert record["severity"] == "error"
    assert record["error_type"] == error_type
    assert failure_text in record["message"]
    assert record["detail"] == repr(RuntimeError(failure_text))
