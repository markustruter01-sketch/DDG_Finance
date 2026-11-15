"""Twin definitions match the live code they copy (the twins may not import it)."""

from __future__ import annotations

import json
from pathlib import Path

from twins import config


def test_copied_constants_match_the_live_code():
    from sleeve_runtime import fleet_live, momo_live

    assert config.FLEET_F1_SPLIT == (fleet_live.F1.core_weight, fleet_live.F1.xasset_weight)
    assert config.MOMO_STATE_KEY == momo_live.STATE_KEY


def test_baselines_are_fully_invested_without_borrowing():
    f1 = config.baseline_weights("oracle", "baseline_full")
    c1 = config.baseline_weights("jerome_macro", "baseline_full")
    assert 0.99 <= sum(f1.values()) <= 1.0 and 0.98 <= sum(c1.values()) <= 1.0
    assert set(f1) == {"SPY", "SSO", "QQQ", "QLD", "IEF", "GLD", "DBC", "UUP"}
    from research_harness.sleeves import core_v1
    assert round(core_v1.exposure(c1), 6) == round(1.5 * 0.99, 6)          # the 1.5x limit, 1% cash buffer
    momo = config.baseline_weights("spy_qqq_trend", "baseline_full", ["MSFT", "AAPL", "AAPL"])
    assert momo == {"AAPL": 0.5, "MSFT": 0.5}
    assert config.baseline_weights("spy_qqq_trend", "baseline_full", []) is None
    assert config.baseline_weights("forex_ai", "baseline_spy") == {"SPY": 1.0}


def test_every_twin_has_a_unique_id_and_a_known_kind():
    specs = config.phase_a_twins()
    assert len({s.twin_id for s in specs}) == len(specs) == 11
    assert all(s.kind in config.KINDS for s in specs)


def test_owner_kept_lines_have_one_definition():
    import core.bot_registry as reg
    src = (Path(__file__).resolve().parents[2] / "kraken-bot" / "fleet_account.py").read_text()
    assert "from core.bot_registry import OWNER_KEPT" in src and "OWNER_KEPT = {" not in src
    assert reg.OWNER_KEPT == {"jerome_macro": frozenset({"BTCUSD"})}     # ETH sold by its stop, 14 Nov


def test_registration_is_well_formed():
    from research_harness.harness.registry import load_registration
    reg = load_registration(config.REGISTRATION)
    assert reg["id"] == "TWINS-V1"
    assert str(config.MIRROR_GUARD_PP) in reg["pass_bar"]
    assert json.loads(json.dumps(reg)) == reg
