from __future__ import annotations

import importlib.util
import math
import pathlib
import sys

import pytest


_MODULE_PATH = (
    pathlib.Path(__file__).parents[2] / "kraken-bot" / "bot3_hard_assets_strategy.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "bot3_hard_assets_strategy_crypto_cap_test",
    _MODULE_PATH,
)
assert _SPEC and _SPEC.loader
bot3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot3
_SPEC.loader.exec_module(bot3)


def _weights(
    btc: float,
    eth: float,
    gld: float,
    slv: float,
) -> dict[str, float]:
    return {
        "BTC/USD": btc,
        "ETH/USD": eth,
        "GLD": gld,
        "SLV": slv,
    }


def test_crypto_under_ceiling_keeps_weights_unchanged():
    weights = _weights(0.10, 0.10, 0.40, 0.40)

    adjusted = bot3.apply_crypto_fleet_cap(
        weights,
        target_base=1_000.0,
        fleet_equity=10_000.0,
    )

    assert adjusted == weights


def test_crypto_over_ceiling_scales_crypto_and_metals_absorb_remainder():
    weights = _weights(0.30, 0.20, 0.30, 0.20)

    adjusted = bot3.apply_crypto_fleet_cap(
        weights,
        target_base=10_000.0,
        fleet_equity=10_000.0,
    )

    assert math.isclose(
        (adjusted["BTC/USD"] + adjusted["ETH/USD"]) * 10_000.0,
        500.0,
    )
    assert math.isclose(adjusted["BTC/USD"], 0.03)
    assert math.isclose(adjusted["ETH/USD"], 0.02)
    assert math.isclose(adjusted["GLD"], 0.57)
    assert math.isclose(adjusted["SLV"], 0.38)
    assert math.isclose(sum(adjusted.values()), 1.0)


def test_crypto_weight_can_fall_below_weight_floor_when_cap_requires_it():
    weights = _weights(0.45, 0.35, 0.10, 0.10)

    adjusted = bot3.apply_crypto_fleet_cap(
        weights,
        target_base=10_000.0,
        fleet_equity=10_000.0,
    )

    assert adjusted["BTC/USD"] < bot3.WEIGHT_FLOOR
    assert adjusted["ETH/USD"] < bot3.WEIGHT_FLOOR
    assert math.isclose(adjusted["GLD"], 0.475)
    assert math.isclose(adjusted["SLV"], 0.475)
    assert math.isclose(sum(adjusted.values()), 1.0)


@pytest.mark.parametrize(
    "fleet_equity",
    [0.0, -1.0, float("nan"), "not-a-number"],
)
def test_invalid_fleet_equity_raises(fleet_equity):
    with pytest.raises(ValueError):
        bot3.apply_crypto_fleet_cap(
            _weights(0.25, 0.25, 0.25, 0.25),
            target_base=10_000.0,
            fleet_equity=fleet_equity,
        )


def test_live_fleet_equity_failure_raises_before_order_planning(monkeypatch):
    decision_calls = []
    planned = []

    def fail_fleet_equity():
        raise RuntimeError("spy_qqq_trend account unavailable")

    monkeypatch.setattr(
        "core.fleet_equity.get_fleet_equity",
        fail_fleet_equity,
    )
    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decision_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        bot3,
        "_plan_orders",
        lambda *args, **kwargs: planned.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="spy_qqq_trend"):
        bot3._apply_live_crypto_cap(
            "DRYRUN",
            _weights(0.25, 0.25, 0.25, 0.25),
            target_base=10_000.0,
        )

    assert planned == []
    assert decision_calls[0][0] == ("DRYRUN", "CRYPTO_CAP_UNAVAILABLE")