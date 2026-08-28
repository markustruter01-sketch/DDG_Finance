"""Pure safety and point-in-time regressions for Bot 2 momentum."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import date, datetime, timezone


_MODULE_PATH = pathlib.Path(__file__).with_name("bot2_momentum_strategy.py")
_SPEC = importlib.util.spec_from_file_location("bot2_momentum_strategy_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
bot2 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot2
_SPEC.loader.exec_module(bot2)
from core.equity_universe import (  # noqa: E402
    asset_is_eligible,
    screen_universe as shared_screen_universe,
    set_screen_data,
)


def _bars(count: int = 260, close: float = 100.0, volume: int = 1_000_000):
    return [
        {
            "t": date(2025, 1, 1).fromordinal(date(2025, 1, 1).toordinal() + index).isoformat(),
            "c": close + index,
            "v": volume,
        }
        for index in range(count)
    ]


def _asset(symbol: str, **overrides):
    return {
        "symbol": symbol,
        "name": "Example Common Stock",
        "status": "active",
        "asset_class": "us_equity",
        "tradable": True,
        "exchange": "NASDAQ",
        **overrides,
    }


def test_screen_requires_tradable_us_equity_and_mechanical_liquidity_gates() -> None:
    as_of = date(2026, 1, 1)
    assets = [
        _asset("GOOD"),
        _asset("OTC", exchange="OTC"),
        _asset("LOWVOL",),
        _asset("NOTRADE", tradable=False),
    ]
    bars = {
        "GOOD": _bars(),
        "OTC": _bars(),
        "LOWVOL": _bars(volume=10),
        "NOTRADE": _bars(),
    }

    screened = bot2.screen_universe(assets, bars, as_of)

    assert set(screened) == {"GOOD"}


def test_instrument_filter_is_metadata_based_and_fail_closed_for_unknowns() -> None:
    assets = [
        _asset("COMMON", name="Example Common Stock"),
        _asset("ETF", name="Example Index ETF", instrument_type="ETF"),
        _asset("UNKNOWN", name="Example Security"),
    ]

    ordinary, report = bot2.filter_ordinary_equity_assets(assets)

    assert {asset["symbol"] for asset in ordinary} == {"COMMON", "UNKNOWN"}
    assert report["excluded_name"] == 1
    assert report["metadata_complete"] is True
    assert "ETF" in report["excluded_symbols"]


def test_shared_exclusion_screener_keeps_required_real_share_shapes() -> None:
    included = [
        _asset("AAPL", name="Apple Inc."),
        _asset("BRK.B", name="Berkshire Hathaway Inc."),
        _asset("TSM", name="Taiwan Semiconductor Manufacturing Co., Ltd."),
    ]
    excluded = [
        _asset("QQQ", name="Invesco QQQ Trust, Series 1"),
        _asset("ABC.WS", name="Example Security"),
        _asset("ABC.U", name="Example Security"),
        _asset("ABC.R", name="Example Security"),
        _asset("ABC.P", name="Example Security"),
        _asset("LEVER", name="Example 3X Daily Leveraged Fund"),
    ]

    assert all(asset_is_eligible(asset) for asset in included)
    assert not any(asset_is_eligible(asset) for asset in excluded)

    bars = {asset["symbol"]: _bars() for asset in included + excluded}
    set_screen_data(included + excluded, bars)
    symbols, funnel = shared_screen_universe(date(2026, 1, 1), 0, 252, 5)

    assert symbols == {"AAPL", "BRK.B", "TSM"}
    assert funnel["excluded_name"] == 2
    assert funnel["excluded_symbol_structure"] == 4


def test_screen_excludes_as_of_bar_and_momentum_skips_recent_21_sessions() -> None:
    as_of = date(2026, 1, 1)
    bars = _bars()
    bars.append({"t": as_of.isoformat(), "c": 99999.0, "v": 999999999})

    score = bot2.momentum_12_1(bars, as_of)

    # Latest eligible close is the one before the 21-session skip window.
    assert score is not None
    eligible = bars[:-1]
    expected = eligible[-22]["c"] / eligible[-252]["c"] - 1
    assert abs(score - expected) < 1e-12
    assert all(bot2._bar_date(bar) < as_of for bar in bars if bot2._bar_date(bar) < as_of)


def test_rank_is_descending_with_deterministic_symbol_tie_break() -> None:
    as_of = date(2026, 1, 1)
    assets = [_asset("BBB"), _asset("AAA")]
    bars = {"AAA": _bars(close=100), "BBB": _bars(close=100)}
    screened = bot2.screen_universe(assets, bars, as_of)

    ranked = bot2.rank_momentum(screened, bars, as_of)

    assert [item["symbol"] for item in ranked] == ["AAA", "BBB"]


def test_rank_rejects_extreme_adjusted_momentum_artifact() -> None:
    as_of = date(2026, 1, 1)
    assets = [_asset("SPIKE"), _asset("NORMAL")]
    spike = _bars(close=100)
    spike[-22]["c"] = 50_000
    normal = _bars(close=100)
    screened = bot2.screen_universe(assets, {"SPIKE": spike, "NORMAL": normal}, as_of)

    ranked = bot2.rank_momentum(screened, {"SPIKE": spike, "NORMAL": normal}, as_of)

    assert [item["symbol"] for item in ranked] == ["NORMAL"]


def test_allocation_excludes_vault_from_sizing_base_and_equal_weights() -> None:
    plan = bot2.allocation_plan(100_000, 10_000, 20)

    assert plan["investable_base"] == 90_000
    assert plan["target_base"] == 90_000
    assert plan["equal_weight_notional"] == 4_500


def test_buy_guard_rejects_negative_cash_and_deployment_overage() -> None:
    account = {"equity": 100_000, "cash": 1_000, "long_market_value": 80_000}
    allowed, projection = bot2.fresh_buy_guard(account, [], 2_000)

    assert not allowed
    assert projection["projected_cash"] == -1_000

    account = {"equity": 100_000, "cash": 50_000, "long_market_value": 79_000}
    allowed, projection = bot2.fresh_buy_guard(account, [], 2_000)

    assert allowed
    assert projection["projected_deployment"] == 0.81


def test_pause_is_first_branch_and_does_not_construct_client(monkeypatch) -> None:
    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("paused Bot 2 must not create an Alpaca client")

    monkeypatch.setattr(bot2, "AlpacaMomentumClient", ExplodingClient)

    result = bot2.run_bot2_cycle(
        profile={"ALPACA_API_KEY": "not-used", "ALPACA_SECRET_KEY": "not-used"},
        now=datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc),
    )

    assert result == {"status": "paused", "orders": 0}


class _EntryClient:
    def __init__(self, stop_failures: int = 0) -> None:
        self.stop_failures = stop_failures
        self.stop_attempts = 0
        self.submissions: list[tuple[str, str, int]] = []
        self.qty = 0

    def submit(self, symbol, side, qty, order_type, **extra):
        self.submissions.append((side, order_type, int(qty)))
        if order_type == "stop":
            self.stop_attempts += 1
            if self.stop_attempts <= self.stop_failures:
                raise RuntimeError("synthetic stop rejection")
            return {"id": f"stop-{self.stop_attempts}"}
        if side == "buy":
            self.qty = int(qty)
            return {"id": "buy-1"}
        self.qty = 0
        return {"id": "sell-1"}

    def wait_for_fill(self, order_id):
        return {
            "status": "filled",
            "filled_qty": self.qty if order_id == "buy-1" else 0,
            "filled_avg_price": 100.0,
        }

    def positions(self):
        if self.qty < 1:
            return []
        return [{
            "symbol": "AAPL",
            "qty": self.qty,
            "entry_price": 100.0,
            "current_price": 100.0,
            "market_value": self.qty * 100.0,
        }]

    def open_orders(self):
        return []

    def cancel_confirm(self, order_id):
        return True


def test_confirmed_entry_records_only_after_fill_and_stop(monkeypatch) -> None:
    client = _EntryClient()
    recorded = []
    monkeypatch.setattr(
        bot2,
        "record_open",
        lambda symbol, qty, entry, stop_price, stop_id: recorded.append(
            (symbol, qty, entry, stop_price, stop_id)
        ),
    )

    assert bot2._place_confirmed_entry(client, "AAPL", 10, "cycle") is True
    assert recorded == [("AAPL", 10, 100.0, 80.0, "stop-1")]
    assert [item[:2] for item in client.submissions] == [
        ("buy", "market"), ("sell", "stop")
    ]


def test_stop_failure_retries_then_flattens_without_recording(monkeypatch) -> None:
    client = _EntryClient(stop_failures=2)
    monkeypatch.setattr(
        bot2,
        "record_open",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("unprotected entry must never be recorded")
        ),
    )

    try:
        bot2._place_confirmed_entry(client, "AAPL", 10, "cycle")
    except RuntimeError as exc:
        assert "stop arm failed twice" in str(exc)
    else:
        raise AssertionError("stop failure should abort the entry")

    assert client.stop_attempts == 2
    assert client.qty == 0
    assert ("sell", "market", 10) in client.submissions


def test_first_trading_day_skips_weekend_and_january_holiday() -> None:
    first_session = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
    monday = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    tuesday = datetime(2026, 1, 6, 15, 0, tzinfo=timezone.utc)

    assert bot2.is_first_trading_day(first_session) is True
    assert bot2.is_first_trading_day(monday) is False
    assert bot2.is_first_trading_day(tuesday) is False