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


def _position(symbol: str, market_value: float, price: float = 100.0) -> dict:
    return {
        "symbol": symbol,
        "market_value": market_value,
        "current_price": price,
        "qty": market_value / price,
        "direction": "long",
    }


def _planner_inputs(crypto_over_ceiling: bool):
    if crypto_over_ceiling:
        positions = [
            _position("BTC/USD", 6_000.0),
            _position("ETH/USD", 5_000.0),
            _position("GLD", 46_000.0),
            _position("SLV", 43_000.0),
        ]
    else:
        positions = [
            _position("BTC/USD", 2_500.0),
            _position("ETH/USD", 2_500.0),
            _position("GLD", 47_500.0),
            _position("SLV", 47_500.0),
        ]
    return (
        {"equity": 100_000.0, "cash": 100_000.0, "buying_power": 100_000.0},
        positions,
        _weights(0.03, 0.02, 0.475, 0.475),
        {"BTC/USD": 100.0, "ETH/USD": 100.0, "GLD": 100.0, "SLV": 100.0},
    )


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


def test_crypto_over_ceiling_inside_band_is_trimmed_to_ceiling(monkeypatch):
    account, positions, targets, prices = _planner_inputs(crypto_over_ceiling=True)
    decisions = []
    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decisions.append((args, kwargs)),
    )

    plan = bot3._plan_orders(
        account,
        positions,
        targets,
        "crypto-over-ceiling",
        prices,
        crypto_ceiling_usd=5_000.0,
    )

    crypto_sells = [item for item in plan if item["symbol"] in bot3.CRYPTO]
    assert {item["symbol"] for item in crypto_sells} == {"BTC/USD", "ETH/USD"}
    post_plan_crypto_value = 11_000.0 - sum(
        item["notional"] for item in crypto_sells
    )
    assert post_plan_crypto_value <= 5_000.0

    trim_decisions = [
        (args, kwargs)
        for args, kwargs in decisions
        if args[1] == "CRYPTO_OVER_CEILING_TRIM"
    ]
    assert {kwargs["symbol"] for _, kwargs in trim_decisions} == {"BTC/USD", "ETH/USD"}
    assert all(
        kwargs["context"]["crypto_ceiling_usd"] == 5_000.0
        and kwargs["context"]["pre_trim_combined_crypto_value"] == 11_000.0
        for _, kwargs in trim_decisions
    )


def test_crypto_below_ceiling_inside_band_still_holds(monkeypatch):
    account, positions, targets, prices = _planner_inputs(crypto_over_ceiling=False)
    decisions = []
    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decisions.append((args, kwargs)),
    )

    plan = bot3._plan_orders(
        account,
        positions,
        targets,
        "crypto-under-ceiling",
        prices,
        crypto_ceiling_usd=5_000.0,
    )

    assert not [item for item in plan if item["symbol"] in bot3.CRYPTO]
    assert {
        kwargs["symbol"]: args[1]
        for args, kwargs in decisions
        if kwargs["symbol"] in bot3.CRYPTO
    } == {
        "BTC/USD": "HOLD_WITHIN_DRIFT_BAND",
        "ETH/USD": "HOLD_WITHIN_DRIFT_BAND",
    }


def test_metals_still_hold_when_crypto_is_over_ceiling(monkeypatch):
    account, positions, targets, prices = _planner_inputs(crypto_over_ceiling=True)
    decisions = []
    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decisions.append((args, kwargs)),
    )

    bot3._plan_orders(
        account,
        positions,
        targets,
        "metals-still-hold",
        prices,
        crypto_ceiling_usd=5_000.0,
    )

    assert {
        kwargs["symbol"]: args[1]
        for args, kwargs in decisions
        if kwargs["symbol"] in bot3.METALS
    } == {
        "GLD": "HOLD_WITHIN_DRIFT_BAND",
        "SLV": "HOLD_WITHIN_DRIFT_BAND",
    }


def test_none_ceiling_preserves_existing_plan(monkeypatch):
    account, positions, targets, prices = _planner_inputs(crypto_over_ceiling=True)
    decisions_without_ceiling = []
    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decisions_without_ceiling.append((args, kwargs)),
    )
    plan_without_ceiling = bot3._plan_orders(
        account,
        positions,
        targets,
        "no-ceiling-default",
        prices,
    )

    decisions_with_none = []
    monkeypatch.setattr(
        bot3,
        "_log_decision",
        lambda *args, **kwargs: decisions_with_none.append((args, kwargs)),
    )
    plan_with_none = bot3._plan_orders(
        account,
        positions,
        targets,
        "no-ceiling-explicit",
        prices,
        crypto_ceiling_usd=None,
    )

    assert plan_with_none == plan_without_ceiling
    assert [
        (args[1], kwargs["symbol"], kwargs["context"])
        for args, kwargs in decisions_with_none
    ] == [
        (args[1], kwargs["symbol"], kwargs["context"])
        for args, kwargs in decisions_without_ceiling
    ]
