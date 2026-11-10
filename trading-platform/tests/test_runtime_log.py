"""30-day log copy (core/runtime_log.py): filter and install guard, no DB."""
from types import SimpleNamespace

from core import runtime_log


def _rec(level_no, name):
    return {"level": SimpleNamespace(no=level_no), "name": name}


def test_warnings_always_kept_info_only_on_the_order_path():
    assert runtime_log.keep(_rec(30, "anything.module"), process="trading-api")
    assert runtime_log.keep(_rec(40, "main"), process="trading-api")
    assert runtime_log.keep(_rec(20, "alpaca_etf_engine"), process="runner")
    assert runtime_log.keep(_rec(20, "execution.reconciliation"), process="trading-api")
    assert runtime_log.keep(_rec(20, "__main__"), process="runner")
    assert not runtime_log.keep(_rec(20, "__main__"), process="trading-api")
    assert not runtime_log.keep(_rec(20, "analysis.news"), process="trading-api")
    assert not runtime_log.keep(_rec(10, "alpaca_etf_engine"), process="runner")


def test_not_installed_outside_the_published_deployment(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setattr(runtime_log, "_installed", False)
    assert runtime_log.install("runner") is False
