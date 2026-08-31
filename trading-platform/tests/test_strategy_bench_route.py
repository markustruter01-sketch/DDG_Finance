from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from main import app
from routes import strategy_bench


def _request() -> dict:
    return {
        "strategy_family": "bot2_momentum_rank500",
        "parameters": {"universe_size": 500},
        "data_window": {
            "warmup_start": "2018-01-01",
            "backtest_start": "2019-02-01",
            "backtest_end": "2024-12-31",
        },
    }


def _result() -> dict:
    return {
        "return": 0.12,
        "max_drawdown": 0.2,
        "sharpe": 0.8,
        "sortino": 1.1,
        "expectancy": 0.01,
        "trades": 4,
        "turnover": 0.4,
        "cost_paid": 10.0,
        "mean_deployment": 0.8,
        "max_deployment": 1.0,
        "mode_days": {"2024": {"cash": 2}},
        "daily_deployment": [
            {"date": "2024-01-02", "equity": 100_000, "positions": 2, "mode": "momentum"},
            {"date": "2024-12-31", "equity": 112_000, "positions": 2, "mode": "momentum"},
        ],
    }


def test_strategy_bench_requires_api_secret(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    client = TestClient(app)
    response = client.post("/trading-api/research/strategy-bench/run", json=_request())
    client.close()
    assert response.status_code == 401


def test_strategy_bench_returns_verified_engine_result_and_records_once(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    recorded: list[dict] = []
    result = _result()
    monkeypatch.setattr(
        strategy_bench,
        "_normalise_request",
        lambda _request: (
            {
                "universe_size": 500,
                "top_n": 20,
                "slippage_each_leg_bps": 10.0,
                "catastrophe_stop": 0.2,
                "max_deployment": 1.0,
                "allocation": "equal_weight",
                "momentum": "12-1",
                "rebalance": "monthly first-trading-day",
                "idle_capital": "cash",
            },
            date(2019, 2, 1),
            date(2024, 12, 31),
        ),
    )
    monkeypatch.setattr(
        strategy_bench,
        "_engine_result",
        lambda *_args: (
            result,
            {"engine": "direct-engine", "panel_counts": {}, "monthly_rebalances": 70},
        ),
    )
    monkeypatch.setattr(
        strategy_bench,
        "_record_run",
        lambda *args: recorded.append({"args": args}) or 41,
    )
    monkeypatch.setattr(
        strategy_bench,
        "_database_identity",
        lambda: {"database": "helium", "host": "db", "port": 5432},
    )

    client = TestClient(app)
    response = client.post(
        "/trading-api/research/strategy-bench/run",
    headers={"X-Trading-API-Internal-Secret": "test-api-secret"},
        json=_request(),
    )
    client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "verified"
    assert payload["run_id"] == 41
    assert payload["metrics"]["return_pct"] == 12.0
    assert payload["provenance"]["database"]["database"] == "helium"
    assert payload["provenance"]["dashboard_json_used"] is False
    assert len(recorded) == 1
    assert recorded[0]["args"][0] == "bot2_momentum_rank500"
    assert "strategy_bench" not in recorded[0]["args"][-1]


def test_strategy_bench_validation_failure_is_recorded_once(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    recorded: list[dict] = []
    monkeypatch.setattr(
        strategy_bench,
        "_normalise_request",
        lambda _request: (_ for _ in ()).throw(ValueError("bad window")),
    )
    monkeypatch.setattr(
        strategy_bench,
        "_record_run",
        lambda *args: recorded.append({"args": args}) or 42,
    )

    client = TestClient(app)
    response = client.post(
        "/trading-api/research/strategy-bench/run",
        headers={"X-Trading-API-Internal-Secret": "test-api-secret"},
        json=_request(),
    )
    client.close()

    assert response.status_code == 422
    assert response.json()["detail"]["status"] == "unverified"
    assert response.json()["detail"]["run_id"] == 42
    assert len(recorded) == 1