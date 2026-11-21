"""One table says which FLEET-V1 variant trades on which account
(sleeve_runtime/fleet_accounts.py). Every label, list and exemption that
names Atlas V2's strategy must agree with it, so the lock-day switch to
FLEET-V1-X1 (roadmap v2, V2-03; Markus D2 = B) cannot leave one behind."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import twins  # noqa: F401  (puts the repo root on the path)
from core import bot_registry
from core.stop_policy import STOP_EXEMPT, TREND_EXIT_LINES
from sleeve_runtime import fleet_accounts as fa
from twins import config as twins_config

ROOT = Path(__file__).resolve().parents[2]


def _kraken_config():
    spec = importlib.util.spec_from_file_location("_kraken_config", ROOT / "kraken-bot" / "config.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_screens_and_settings_name_the_variant_the_table_names():
    reg = fa.ACCOUNTS["jerome_macro"]
    assert bot_registry.BOT_REGISTRY["jerome_macro"].strategy_label == fa.LABELS[reg]
    cfg = _kraken_config()
    jerome = cfg.BOT_PROFILES["jerome_macro"]
    assert jerome["strategy_type"] == fa.state_key(reg) and jerome["strategy_label"] == fa.LABELS[reg]


def test_the_ddg_push_lists_the_variants_instruments():
    from core import ddg_push
    from research_harness.sleeves import core_v1, xasset_v1
    core_w, xasset_w = fa.SPLITS[fa.ACCOUNTS["jerome_macro"]]
    core = {s for pair in core_v1.INSTRUMENTS.values() for s in pair} if core_w > 0 else set()
    want = core | (set(xasset_v1.LINES) if xasset_w > 0 else set()) | {"SGOV"}
    assert set(ddg_push._DETAIL_INSTRUMENTS["jerome_macro"]) == want


def test_every_fleet_account_is_stop_exempt_for_the_cross_asset_lines_only():
    for bot in fa.ACCOUNTS:
        assert STOP_EXEMPT[bot] == TREND_EXIT_LINES
    assert "spy_qqq_trend" not in STOP_EXEMPT and "forex_ai" not in STOP_EXEMPT


def test_baseline_twin_follows_the_variant(monkeypatch):
    c1 = twins_config.baseline_weights("jerome_macro", "baseline_full")
    assert set(c1) == {"SPY", "SSO", "QQQ", "QLD"}                   # C1 today: the 1.5x core, never in cash
    monkeypatch.setitem(twins_config.FLEET_ACCOUNTS, "jerome_macro", "FLEET-V1-X1")
    x1 = twins_config.baseline_weights("jerome_macro", "baseline_full")
    assert x1 == {"IEF": 0.25, "GLD": 0.25, "DBC": 0.25, "UUP": 0.25}  # X1: all four lines, never in cash
    f1 = twins_config.baseline_weights("oracle", "baseline_full")
    assert abs(sum(f1.values()) - (0.65 * sum(c1.values()) + 0.35)) < 1e-9
