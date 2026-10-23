"""Forex risk officer: sizes to 0.5% risk, never enlarges, enforces every limit."""
from __future__ import annotations

import pytest

import forex_risk as fr

NAV = 100_000.0
ROWS = {
    "EUR_USD": {"pair": "EUR_USD", "close": 1.08, "atr": 0.006},
    "USD_JPY": {"pair": "USD_JPY", "close": 150.0, "atr": 1.0},
    "GBP_USD": {"pair": "GBP_USD", "close": 1.30, "atr": 0.008},
    "AUD_USD": {"pair": "AUD_USD", "close": 0.66, "atr": 0.005},
    "USD_CAD": {"pair": "USD_CAD", "close": 1.38, "atr": 0.006},
}


def _d(pair, direction, conviction=3, stop=2.0):
    return {"pair": pair, "direction": direction, "conviction": conviction, "stop_atr_multiple": stop}


def _plan(decisions, **kw):
    return fr.plan_forex_actions(decisions=decisions, rows_by_pair=ROWS, nav=kw.pop("nav", NAV),
                                 open_trades=kw.pop("open_trades", []), max_gross=2.0, **kw)


def test_risk_to_the_stop_is_half_a_percent_for_usd_quote_and_base_pairs():
    plan = _plan([_d("EUR_USD", "long"), _d("USD_JPY", "short")])
    eur, jpy = {o["pair"]: o for o in plan["opens"]}.values()
    # EUR_USD: 500 / (2 x 0.006 USD per unit) = 41,666 units
    assert eur["units"] == 41_666 and eur["stop_distance"] == pytest.approx(0.012)
    # USD_JPY: 500 / (2 x 1.0 JPY / 150) = 37,500 units, short = negative
    assert jpy["units"] == -37_500
    assert all(o["risk_usd"] <= 500.0 for o in plan["opens"])


def test_low_confidence_halves_the_risk():
    plan = _plan([_d("EUR_USD", "long")], low_confidence=True)
    assert plan["opens"][0]["units"] == 20_833


def test_at_most_four_open_trades_highest_conviction_first():
    held = [{"trade_id": "1", "instrument": "NZD_USD", "signed_units": 1000, "market_value": 600.0}]
    decisions = [_d("EUR_USD", "long", 2), _d("GBP_USD", "long", 5), _d("AUD_USD", "short", 4),
                 _d("USD_CAD", "long", 1), _d("NZD_USD", "long", 3)]
    plan = _plan(decisions, open_trades=held)
    assert [o["pair"] for o in plan["opens"]] == ["GBP_USD", "AUD_USD", "EUR_USD"]
    assert plan["skipped"] == [{"pair": "USD_CAD", "reason": "already 4 open trades"}]
    assert plan["closes"] == []                                   # NZD held long, AI says long


def test_flat_or_opposite_call_closes_the_trade():
    held = [{"trade_id": "7", "instrument": "EUR_USD", "signed_units": 5000, "market_value": 5400.0},
            {"trade_id": "8", "instrument": "USD_JPY", "signed_units": -5000, "market_value": 5000.0}]
    plan = _plan([_d("EUR_USD", "flat"), _d("USD_JPY", "long")], open_trades=held)
    assert [c["trade_id"] for c in plan["closes"]] == ["7", "8"]
    assert [o["pair"] for o in plan["opens"]] == ["USD_JPY"]      # reopened the other way


def test_gross_cap_shrinks_then_blocks():
    huge = [{"trade_id": "1", "instrument": "USD_CAD", "signed_units": 199_000, "market_value": 199_000.0}]
    plan = _plan([_d("EUR_USD", "long")], open_trades=huge)
    assert plan["opens"][0]["units"] == int(1_000 / 1.08)         # only the room left under 2x NAV
    full = [{"trade_id": "1", "instrument": "USD_CAD", "signed_units": 200_000, "market_value": 200_000.0}]
    assert _plan([_d("EUR_USD", "long")], open_trades=full)["skipped"][0]["reason"] == "gross exposure cap reached"


def test_daily_loss_blocks_new_trades_but_not_closes():
    held = [{"trade_id": "7", "instrument": "EUR_USD", "signed_units": 5000, "market_value": 5400.0}]
    plan = _plan([_d("EUR_USD", "flat"), _d("GBP_USD", "long")], open_trades=held,
                 nav=97_900.0, nav_at_last_cycle=100_000.0)
    assert plan["closes"][0]["trade_id"] == "7" and plan["opens"] == []
    assert "daily loss" in plan["skipped"][0]["reason"]


def test_blackout_and_missing_data_are_skipped_and_reported():
    plan = _plan([_d("EUR_USD", "long"), _d("NZD_USD", "long")], blackout_pairs=frozenset({"EUR_USD"}))
    reasons = {s["pair"]: s["reason"] for s in plan["skipped"]}
    assert reasons == {"EUR_USD": "event blackout", "NZD_USD": "no usable price, ATR or stop multiple"}
    assert plan["checks"]["event_blackout"] == "enforced"
    assert _plan([])["checks"]["event_blackout"].startswith("not enforced")


def test_stop_levels_are_on_the_right_side_and_rounded():
    assert fr.stop_price("EUR_USD", "long", 1.081234, 0.012) == 1.06923
    assert fr.stop_price("USD_JPY", "short", 150.1234, 2.0) == 152.123
