from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def runner_module():
    path = Path(__file__).parents[2] / "kraken-bot" / "runner.py"
    spec = importlib.util.spec_from_file_location("test_runner_exit_code_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_deliberate_lease_refusal_returns_refusal_code(runner_module, monkeypatch):
    monkeypatch.setattr(runner_module, "_runner_can_trade", True)
    monkeypatch.setattr(runner_module, "_prepare_runner_locks", lambda: False)
    monkeypatch.setattr(
        runner_module,
        "_runner_lock_failure_reason",
        "lease refused by another live runner",
    )

    assert runner_module.main() == runner_module.EXIT_REFUSAL
    runner_module._shutdown_event.clear()


def test_uncaught_startup_failure_returns_crash_code(runner_module, monkeypatch):
    monkeypatch.setattr(runner_module, "_prepare_runner_locks", lambda: True)
    monkeypatch.setattr(
        runner_module,
        "_assert_pause_alignment",
        lambda: (_ for _ in ()).throw(RuntimeError("startup boom")),
    )

    assert runner_module.main() == runner_module.EXIT_CRASH
    runner_module._shutdown_event.clear()