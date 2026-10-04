import json
from datetime import date, timedelta

from analysis import bot2_momentum_pead_v3 as research
from analysis.bot2_momentum_pead_v3 import (
    Bar,
    PEAD_SYMBOLS,
    Series,
    _is_signal_earnings_event,
    screen_universe,
    simulate_momentum,
)
from core.bot2_universe_gate import BOT2_UNIVERSE_GATE_FILE


def _series(symbol: str, count: int = 320, volume: float = 1_000_000.0) -> Series:
    bars = []
    first = date(2018, 1, 1)
    for index in range(count):
        day = first + timedelta(days=index)
        close = 100.0 + index * 0.25 + (index % 5) * 0.10
        bars.append(Bar(day, close, close + 1, close - 1, close, volume))
    return Series(symbol, bars)


def test_screen_uses_only_bars_strictly_before_as_of():
    data = _series("AAA")
    as_of = data.bars[280].day
    qualified, observations = screen_universe(
        {"AAA": data}, {"AAA"}, as_of, universe_size=500
    )

    assert qualified == {"AAA"}
    assert observations["AAA"]["last_data_day"] < as_of
    assert observations["AAA"]["uses_future_data"] is False
    assert observations["AAA"]["sessions_available"] == 280


def test_rank_screen_selects_top_n_by_dollar_volume():
    series = {
        f"S{index}": _series(f"S{index}", volume=(index + 1) * 1_000_000)
        for index in range(4)
    }

    qualified, observations = screen_universe(
        series, set(series), date(2018, 10, 20), universe_size=2
    )

    assert qualified == {"S3", "S2"}
    assert observations["S2"]["median_dollar_volume_60"] < (
        observations["S3"]["median_dollar_volume_60"]
    )


def test_mechanical_screen_rejects_insufficient_history_and_low_price():
    short = _series("SHORT", count=100)
    low = _series("LOW")
    low.bars = [
        Bar(bar.day, bar.open, bar.high, bar.low, 4.0, bar.volume)
        for bar in low.bars
    ]
    low.__post_init__()

    qualified, observations = screen_universe(
        {"SHORT": short, "LOW": low},
        {"SHORT", "LOW"},
        date(2018, 10, 20),
        universe_size=500,
    )

    assert qualified == set()
    assert "SHORT" not in observations
    assert observations["LOW"]["median_close_60"] == 4.0


def test_cash_constrained_momentum_never_exceeds_full_deployment():
    data = _series("AAA", count=900)
    result = simulate_momentum(
        {"AAA": data},
        {"AAA"},
        universe_size=500,
        start=date(2018, 1, 1),
        end=data.bars[-1].day,
    )

    assert result["trades"] > 0
    assert result["max_deployment"] <= 1.0000001
    assert sum(
        days["invested"] + days["cash"]
        for days in result["mode_days"].values()
    ) > 0


def test_manual_cost_is_excluded_but_non_manual_cost_remains_eligible():
    assert "COST" in PEAD_SYMBOLS
    assert not _is_signal_earnings_event("COST", 1.0, "post-market", "manual")
    assert _is_signal_earnings_event("COST", 1.0, "post-market", "alphavantage")


def test_full_gate_writer_records_deployment_provenance(tmp_path, monkeypatch):
    gate_file = tmp_path / "bot2_universe_gate.json"
    assert research.BOT2_UNIVERSE_GATE_FILE == BOT2_UNIVERSE_GATE_FILE
    monkeypatch.setattr(research, "BOT2_UNIVERSE_GATE_FILE", gate_file)
    monkeypatch.setattr(research, "_current_git_commit", lambda: "a" * 40)

    research.persist_universe_gate(True, {"monthly": {}, "annual": {}})

    payload = json.loads(gate_file.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["mode"] == "full"
    assert payload["research_database"] == research.RESEARCH_DATABASE_LABEL
    assert payload["research_database"]
    assert payload["scored_window"]["start"] == "2019-02-01"
    assert payload["scored_window"]["end"]
    assert payload["sample_dates"] == [
        day.isoformat() for day in research.SAMPLE_DATES
    ]
    assert payload["generated_at"].endswith("Z")
    assert payload["git_commit"] == "a" * 40


def test_full_gate_evaluator_prints_and_persists_each_gate_check(capsys):
    report = {
        "sample_dates": {
            day.isoformat(): {
                "qualified_count": 500,
                "history_eligible": 500,
                "future_rows": 0,
                "funnel": {"rank_cutoff_dollar_volume": 1_000_000.0},
            }
            for day in research.SAMPLE_DATES
        },
        "dropouts": ["OLD"],
        "early_delisted": ["OLD1", "OLD2", "OLD3"],
        "first_full_500": "2019-02-01",
    }

    passed, universe_size, result = research.mechanical_gate_from_rank_audit(
        report
    )

    assert passed
    assert universe_size == 500
    assert result["mechanical_gate_checks"]
    assert all(
        check["result"] == "PASS"
        for check in result["mechanical_gate_checks"].values()
    )
    output = capsys.readouterr().out
    assert "mechanical_check | future_data_" in output
    assert "mechanical_check | parity_" in output
    assert "mechanical_check | screen_rules" in output
    assert "mechanical_check | dropout" in output
    assert "mechanical_check | delisted_members" in output
    assert "mechanical_check | monthly_full_universe" in output


def test_full_gate_stops_on_future_data_and_parity_failure():
    first_sample = research.SAMPLE_DATES[0]
    report = {
        "sample_dates": {
            day.isoformat(): {
                "qualified_count": 399 if day == first_sample else 500,
                "history_eligible": 500,
                "future_rows": 1 if day == first_sample else 0,
                "funnel": {"rank_cutoff_dollar_volume": 1_000_000.0},
            }
            for day in research.SAMPLE_DATES
        },
        "dropouts": ["OLD"],
        "early_delisted": ["OLD1", "OLD2", "OLD3"],
        "first_full_500": "2019-02-01",
    }

    passed, _universe_size, result = research.mechanical_gate_from_rank_audit(
        report
    )

    assert not passed
    assert (
        result["mechanical_gate_checks"]["future_data_2019-06-03"]["result"]
        == "STOP"
    )
    assert result["mechanical_gate_checks"]["parity_2019-06-03"]["result"] == "STOP"


def test_audit_only_writes_diagnostics_and_never_touches_gate(tmp_path, monkeypatch):
    gate_file = tmp_path / "bot2_universe_gate.json"
    diagnostics_file = tmp_path / "bot2_universe_gate_audit.json"
    monkeypatch.setattr(research, "BOT2_UNIVERSE_GATE_FILE", gate_file)
    monkeypatch.setattr(research, "AUDIT_DIAGNOSTICS_FILE", diagnostics_file)
    monkeypatch.setattr(research, "ensure_asset_table", lambda: None)
    monkeypatch.setattr(research, "load_stored_assets", lambda **_kwargs: [])
    monkeypatch.setattr(research, "coverage_report", lambda _symbols: {})
    monkeypatch.setattr(
        research,
        "_stored_rank_audit",
        lambda _symbols: {"sample_dates": {}, "monthly": {}},
    )

    result = research.run_research(refresh_assets=False, audit_only=True)

    assert result["status"] == "STOP"
    assert not gate_file.exists()
    diagnostic_payload = json.loads(diagnostics_file.read_text(encoding="utf-8"))
    assert diagnostic_payload["mode"] == "audit_only"