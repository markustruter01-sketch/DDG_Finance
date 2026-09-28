from __future__ import annotations

import importlib
import json
from datetime import date, datetime, timezone
from io import BytesIO
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


def _yahoo_payload(days, values):
    quote = {
        field: list(values[field])
        for field in ("open", "high", "low", "close", "volume")
    }
    timestamps = [
        int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        for day in days
    ]
    return {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {"quote": [quote]},
                }
            ],
            "error": None,
        }
    }


def _patch_yahoo_response(monkeypatch, pipeline, days, values):
    response = json.dumps(_yahoo_payload(days, values)).encode("utf-8")
    monkeypatch.setattr(
        pipeline,
        "urlopen",
        lambda *_args, **_kwargs: BytesIO(response),
    )


def _fetch_daily(pipeline, symbol, end_exclusive):
    if pipeline is crypto_data_pipeline:
        return pipeline._fetch_yahoo_daily(
            symbol,
            date(2024, 1, 1),
            end_exclusive,
        )
    return pipeline._yahoo_daily(symbol, end_exclusive)


def _complete_yahoo_values(count):
    return {
        "open": [10.0 + index for index in range(count)],
        "high": [11.0 + index for index in range(count)],
        "low": [9.0 + index for index in range(count)],
        "close": [10.5 + index for index in range(count)],
        "volume": [1000.0 + index for index in range(count)],
    }


_YAHOO_FETCHERS = [
    pytest.param(crypto_data_pipeline, "BTC", id="crypto"),
    pytest.param(bot3_data_pipeline, "GLD", id="bot3"),
]


@pytest.mark.parametrize(("pipeline", "symbol"), _YAHOO_FETCHERS)
def test_newest_null_ohlc_bar_is_dropped_and_earlier_bars_are_kept(
    monkeypatch,
    pipeline,
    symbol,
):
    days = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    values = _complete_yahoo_values(len(days))
    for field in ("open", "high", "low", "close"):
        values[field][-1] = None
    _patch_yahoo_response(monkeypatch, pipeline, days, values)
    log_messages = []
    monkeypatch.setattr(
        crypto_data_pipeline,
        "logger",
        SimpleNamespace(info=lambda message, *args: log_messages.append(message.format(*args))),
    )

    bars = _fetch_daily(pipeline, symbol, date(2024, 1, 4))

    assert [bar["date"] for bar in bars] == days[:2]
    assert [bar["close"] for bar in bars] == [10.5, 11.5]
    assert [bar["volume"] for bar in bars] == [1000.0, 1001.0]
    assert log_messages == [
        f"Yahoo {symbol}: dropping newest bar with null OHLC on 2024-01-03"
    ]


@pytest.mark.parametrize(("pipeline", "symbol"), _YAHOO_FETCHERS)
def test_earlier_null_bar_still_raises(monkeypatch, pipeline, symbol):
    days = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    values = _complete_yahoo_values(len(days))
    values["close"][0] = None
    _patch_yahoo_response(monkeypatch, pipeline, days, values)

    with pytest.raises(
        RuntimeError,
        match=f"Yahoo {symbol}: null OHLCV value on 2024-01-01",
    ):
        _fetch_daily(pipeline, symbol, date(2024, 1, 4))


@pytest.mark.parametrize(("pipeline", "symbol"), _YAHOO_FETCHERS)
def test_all_null_bars_raise_instead_of_returning_empty_history(
    monkeypatch,
    pipeline,
    symbol,
):
    for days in ([date(2024, 1, 1)], [date(2024, 1, 1), date(2024, 1, 2)]):
        values = {field: [None] * len(days) for field in ("open", "high", "low", "close", "volume")}
        _patch_yahoo_response(monkeypatch, pipeline, days, values)

        with pytest.raises(
            RuntimeError,
            match=f"Yahoo {symbol}: null OHLCV value on 2024-01-01",
        ):
            _fetch_daily(pipeline, symbol, date(2024, 1, 4))


@pytest.mark.parametrize(("pipeline", "symbol"), _YAHOO_FETCHERS)
def test_each_fetcher_calls_the_shared_newest_bar_helper(
    monkeypatch,
    pipeline,
    symbol,
):
    days = [date(2024, 1, 1)]
    _patch_yahoo_response(
        monkeypatch,
        pipeline,
        days,
        _complete_yahoo_values(len(days)),
    )
    calls = []
    shared_helper = crypto_data_pipeline._drop_incomplete_latest_yahoo_bar

    def record_helper_call(called_symbol, bars):
        calls.append((called_symbol, len(bars)))
        return shared_helper(called_symbol, bars)

    monkeypatch.setattr(
        crypto_data_pipeline,
        "_drop_incomplete_latest_yahoo_bar",
        record_helper_call,
    )

    bars = _fetch_daily(pipeline, symbol, date(2024, 1, 2))

    assert len(bars) == 1
    assert calls == [(symbol, 1)]


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
    resolutions = []
    monkeypatch.setattr(
        degradation_tracker,
        "mark_resolved",
        lambda **kwargs: resolutions.append(kwargs),
    )
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
    assert resolutions == []


@pytest.mark.parametrize(
    ("job", "pipeline", "ingest_name", "error_type", "counts"),
    [
        (
            main._refresh_crypto_yahoo_history,
            crypto_data_pipeline,
            "ingest_yahoo_history",
            "crypto_yahoo_history_refresh_failed",
            {"BTC": 10, "ETH": 11},
        ),
        (
            main._refresh_bot3_metals_history,
            bot3_data_pipeline,
            "ingest_metals",
            "bot3_metals_history_refresh_failed",
            {"GLD": 12, "SLV": 13},
        ),
    ],
)
def test_successful_yahoo_refresh_resolves_its_failure_alert(
    monkeypatch,
    job,
    pipeline,
    ingest_name,
    error_type,
    counts,
):
    _fake_logger(monkeypatch)
    monkeypatch.setattr(pipeline, ingest_name, lambda: counts)
    degradation_tracker = importlib.import_module("core.degradation_tracker")
    resolutions = []
    monkeypatch.setattr(
        degradation_tracker,
        "mark_resolved",
        lambda **kwargs: resolutions.append(kwargs),
    )

    job()

    assert resolutions == [
        {
            "component": "data_pipeline",
            "error_type": error_type,
            "reason": "refresh succeeded",
        }
    ]
