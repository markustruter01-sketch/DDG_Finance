"""Pure safety and point-in-time regressions for Bot 2 momentum."""

from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re
import statistics
import sys
from datetime import date, datetime, timezone


_MODULE_PATH = pathlib.Path(__file__).with_name("bot2_momentum_strategy.py")
_SPEC = importlib.util.spec_from_file_location("bot2_momentum_strategy_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
bot2 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bot2
_SPEC.loader.exec_module(bot2)
from core.equity_universe import (  # noqa: E402
    EquitySymbolSummary,
    asset_is_eligible,
    eligible_asset_records,
    screen_universe as shared_screen_universe,
    set_screen_data,
    summarize_symbol_bars,
)
from core.bot2_universe_gate import BOT2_UNIVERSE_GATE_FILE


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


def test_symbol_summary_captures_screen_and_rank_values_without_retaining_bars() -> None:
    as_of = date(2026, 1, 1)
    bars = _bars(count=260, close=100.0, volume=1_000_000)
    bars.append({"t": as_of.isoformat(), "c": 999_999.0, "v": 999_999_999})

    summary = summarize_symbol_bars(
        bars,
        as_of,
        min_sessions=252,
        momentum_lookback=252,
        skip_recent_sessions=21,
    )
    prior = bars[:-1]

    assert isinstance(summary, EquitySymbolSummary)
    assert summary.has_bars
    assert summary.has_current_bar
    assert summary.sessions_available == 260
    assert summary.last_data_day == date.fromisoformat(prior[-1]["t"])
    assert summary.adjusted_price_artifact is False
    assert summary.median_close_60 == statistics.median(
        bar["c"] for bar in prior[-60:]
    )
    assert summary.median_dollar_volume_60 == statistics.median(
        bar["c"] * bar["v"] for bar in prior[-60:]
    )
    assert summary.momentum == prior[-22]["c"] / prior[-252]["c"] - 1
    assert summary.prior_close == prior[-1]["c"]
    assert not hasattr(summary, "bars")


def test_daily_bars_end_twenty_minutes_before_now(monkeypatch) -> None:
    fixed_now = datetime(2026, 10, 2, 15, 40, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(bot2, "datetime", FrozenDateTime)
    monkeypatch.delenv("BOT2_ALPACA_DATA_FEED", raising=False)
    requests_seen = []
    client = object.__new__(bot2.AlpacaMomentumClient)
    client._data_request = lambda method, path, **kwargs: (
        requests_seen.append(kwargs["params"]) or {"bars": {}}
    )

    client.daily_bars(["AAPL"], date(2026, 10, 2))

    assert requests_seen[0]["end"] == "2026-10-02T15:20:00Z"
    assert requests_seen[0]["feed"] == "sip"


def test_daily_bars_drop_today_during_open_nyse_session(monkeypatch) -> None:
    fixed_now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(bot2, "datetime", FrozenDateTime)
    client = object.__new__(bot2.AlpacaMomentumClient)
    client._data_request = lambda *args, **kwargs: {
        "bars": {
            "AAPL": [
                {"t": "2026-10-01T04:00:00Z", "c": 100.0, "v": 1000},
                {"t": "2026-10-02T13:30:00Z", "c": 999.0, "v": 999999},
            ]
        }
    }

    bars = client.daily_bars(["AAPL"], date(2026, 10, 2))

    assert bars == {
        "AAPL": [{"t": "2026-10-01T04:00:00Z", "c": 100.0, "v": 1000}]
    }


def test_daily_bar_batches_yield_completed_symbol_batches() -> None:
    requests_seen = []
    client = object.__new__(bot2.AlpacaMomentumClient)

    def data_request(method, path, **kwargs):
        symbols = kwargs["params"]["symbols"].split(",")
        requests_seen.append((method, path, symbols))
        return {
            "bars": {
                symbol: [{"t": "2026-09-30T04:00:00Z", "c": 100.0, "v": 1000}]
                for symbol in symbols
            }
        }

    client._data_request = data_request
    batches = list(
        client.daily_bar_batches(
            ["AAA", "BBB", "CCC"], date(2026, 10, 1), batch_size=2
        )
    )

    assert [sorted(batch) for batch in batches] == [
        ["AAA", "BBB"],
        ["CCC"],
    ]
    assert requests_seen == [
        ("GET", "/v2/stocks/bars", ["AAA", "BBB"]),
        ("GET", "/v2/stocks/bars", ["CCC"]),
    ]


def test_latest_price_falls_back_to_iex_only_after_sip_403(capsys) -> None:
    requests_seen = []
    client = object.__new__(bot2.AlpacaMomentumClient)

    def data_request(method, path, **kwargs):
        requests_seen.append((method, path, kwargs["params"]["feed"]))
        if len(requests_seen) == 1:
            response = bot2.requests.Response()
            response.status_code = 403
            raise bot2.requests.HTTPError("SIP forbidden", response=response)
        return {"quote": {"bp": 99.0, "ap": 101.0}}

    client._data_request = data_request

    assert client.latest_price("sgov") == 100.0
    assert requests_seen == [
        ("GET", "/v2/stocks/SGOV/quotes/latest", "sip"),
        ("GET", "/v2/stocks/SGOV/quotes/latest", "iex"),
    ]
    assert "feed=iex reason=sip_http_403" in capsys.readouterr().out


def test_latest_price_does_not_fall_back_for_non_403_errors() -> None:
    requests_seen = []
    client = object.__new__(bot2.AlpacaMomentumClient)

    def data_request(method, path, **kwargs):
        requests_seen.append(kwargs["params"]["feed"])
        response = bot2.requests.Response()
        response.status_code = 500
        raise bot2.requests.HTTPError("server error", response=response)

    client._data_request = data_request

    try:
        client.latest_price("SGOV")
    except bot2.requests.HTTPError as exc:
        assert exc.response.status_code == 500
    else:
        raise AssertionError("non-403 quote errors must be raised")

    assert requests_seen == ["sip"]


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

    set_screen_data(assets, bars)
    screened, _ = shared_screen_universe(
        as_of,
        bot2.UNIVERSE_SIZE,
        bot2.MIN_PRIOR_SESSIONS,
        bot2.MIN_MEDIAN_CLOSE,
    )

    assert set(screened) == {"GOOD", "LOWVOL"}


def test_instrument_filter_is_metadata_based_and_fail_closed_for_unknowns() -> None:
    assets = [
        _asset("COMMON", name="Example Common Stock"),
        _asset("ETF", name="Example Index ETF", instrument_type="ETF"),
        _asset("UNKNOWN", name="Example Security"),
    ]

    ordinary, report = eligible_asset_records(assets)

    assert {asset["symbol"] for asset in ordinary} == {"COMMON", "UNKNOWN"}
    assert report["excluded_name"] == 1


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
    symbols, funnel = shared_screen_universe(date(2026, 1, 1), 500, 252, 5)

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
    set_screen_data(assets, bars)
    screened, _ = shared_screen_universe(
        as_of,
        bot2.UNIVERSE_SIZE,
        bot2.MIN_PRIOR_SESSIONS,
        bot2.MIN_MEDIAN_CLOSE,
    )

    ranked = bot2.rank_momentum(screened, bars, as_of)

    assert [item["symbol"] for item in ranked] == ["AAA", "BBB"]


def test_bot2_cap_is_read_from_its_config_profile(monkeypatch) -> None:
    symbols = [f"S{index:03d}" for index in range(55)]
    observations = {
        symbol: {
            "asset_class": "us_equity",
            "median_dollar_volume_60": 1_000_000,
        }
        for symbol in symbols
    }
    monkeypatch.setattr(bot2, "last_screen_observations", lambda: observations)
    ranked = bot2.rank_momentum(
        set(symbols),
        {symbol: _bars() for symbol in symbols},
        date(2026, 1, 1),
    )

    assert bot2.BOT2_PROFILE["MAX_POSITIONS"] == 50
    assert bot2.MAX_POSITIONS == bot2.BOT2_PROFILE["MAX_POSITIONS"]
    assert len(ranked) == 50


def test_spy_is_excluded_from_the_top_50_stock_rank(monkeypatch) -> None:
    symbols = {f"S{index:03d}" for index in range(50)} | {"SPY"}
    observations = {
        symbol: {
            "asset_class": "us_equity",
            "median_dollar_volume_60": 1_000_000,
        }
        for symbol in symbols
    }
    monkeypatch.setattr(bot2, "last_screen_observations", lambda: observations)

    ranked = bot2.rank_momentum(
        symbols,
        {symbol: _bars() for symbol in symbols},
        date(2026, 1, 1),
        top_n=50,
    )

    assert len(ranked) == 50
    assert all(item["symbol"] != "SPY" for item in ranked)


def test_rank_screen_selects_exactly_top_500_and_reports_cutoff() -> None:
    as_of = date(2026, 1, 1)
    assets = [_asset(f"S{index:03d}") for index in range(501)]
    bars = {
        asset["symbol"]: _bars(volume=501 - index)
        for index, asset in enumerate(assets)
    }

    set_screen_data(assets, bars)
    screened, funnel = shared_screen_universe(
        as_of, 500, bot2.MIN_PRIOR_SESSIONS, bot2.MIN_MEDIAN_CLOSE
    )

    assert len(screened) == 500
    assert "S500" not in screened
    assert funnel["ranked_candidates"] == 501
    assert funnel["qualifying_symbols"] == 500
    assert funnel["rank_cutoff_dollar_volume"] == 659.0


def test_rank_rejects_extreme_adjusted_momentum_artifact() -> None:
    as_of = date(2026, 1, 1)
    assets = [_asset("SPIKE"), _asset("NORMAL")]
    spike = _bars(close=100)
    spike[-22]["c"] = 50_000
    normal = _bars(close=100)
    bars = {"SPIKE": spike, "NORMAL": normal}
    set_screen_data(assets, bars)
    screened, _ = shared_screen_universe(
        as_of,
        bot2.UNIVERSE_SIZE,
        bot2.MIN_PRIOR_SESSIONS,
        bot2.MIN_MEDIAN_CLOSE,
    )

    ranked = bot2.rank_momentum(screened, bars, as_of)

    assert [item["symbol"] for item in ranked] == ["NORMAL"]


def test_batched_book_matches_full_bar_book_on_fixed_data(capsys) -> None:
    as_of = date(2026, 1, 1)
    assets = [
        _asset("AAA"),
        _asset("BBB"),
        _asset("CCC"),
        _asset("HIGHMOM"),
        _asset("ARTI"),
        _asset("NODATA"),
        _asset("SPY"),
        _asset("ETF", name="Example ETF"),
        _asset("OTC", exchange="OTC"),
    ]
    bars = {
        "AAA": _bars(close=70.0),
        "BBB": _bars(close=100.0),
        "CCC": _bars(close=150.0),
        "HIGHMOM": _bars(close=6.0),
        "ARTI": _bars(close=100.0),
    }
    bars["ARTI"][-22]["c"] = 50_000.0

    class FullBarsClient:
        def assets(self):
            return assets

        def daily_bars(self, symbols, _as_of, batch_size=100):
            assert batch_size == 100
            return {symbol: bars[symbol] for symbol in symbols if symbol in bars}

    class BatchedBarsClient(FullBarsClient):
        def daily_bar_batches(self, symbols, _as_of, batch_size=100):
            for offset in range(0, len(symbols), batch_size):
                batch_symbols = symbols[offset:offset + batch_size]
                yield {
                    symbol: bars[symbol]
                    for symbol in batch_symbols
                    if symbol in bars
                }

    full_ranked, full_screened, _full_bars = bot2._build_book(
        FullBarsClient(), as_of
    )
    full_output = capsys.readouterr().out
    compact_ranked, compact_screened, summaries = bot2._build_book_batched(
        BatchedBarsClient(), as_of, batch_size=2
    )
    compact_output = capsys.readouterr().out

    def live_funnel(output):
        return next(
            line for line in output.splitlines()
            if line.startswith("LIVE_FUNNEL | ")
        )

    assert compact_screened == full_screened
    assert compact_ranked == full_ranked
    assert live_funnel(compact_output) == live_funnel(full_output)
    assert len(compact_screened) == 4
    assert all(isinstance(value, EquitySymbolSummary) for value in summaries.values())
    assert all(not hasattr(value, "bars") for value in summaries.values())
    assert [row["symbol"] for row in compact_ranked] == [
        row["symbol"] for row in full_ranked
    ]
    assert "HIGHMOM" not in {row["symbol"] for row in compact_ranked}
    assert "ARTI" not in compact_screened


def test_allocation_excludes_vault_from_sizing_base_and_equal_weights() -> None:
    plan = bot2.allocation_plan(100_000, 10_000, 20)

    assert plan["investable_base"] == 90_000
    assert plan["target_base"] == 90_000
    assert plan["equal_weight_notional"] == 4_500


def test_spy_sleeve_uses_twenty_percent_and_momentum_scales_only_eighty_percent() -> None:
    ranked = [{"symbol": f"S{index:02d}"} for index in range(50)]
    ranked.append({"symbol": "SPY"})
    plan = bot2.build_target_allocation_plan(
        equity=100_000,
        vault_market_value=10_000,
        ranked=ranked,
        multiplier=0.5,
        benched_symbols={"S00"},
        spy_sleeve_weight=bot2.SPY_SLEEVE_WEIGHT,
    )

    assert bot2.SPY_SLEEVE_WEIGHT == 0.20
    assert plan["target_base"] == 90_000
    assert plan["spy_target"] == 18_000
    assert plan["momentum_base"] == 72_000
    assert plan["slot_notional"] == 1_440
    assert plan["scaled_position_notional"] == 720
    assert plan["target_allocations"]["S00"] == 0
    assert "SPY" not in plan["target_allocations"]
    assert plan["stock_target"] == 49 * 720
    assert plan["sgov_target"] == 90_000 - 18_000 - 49 * 720
    assert (
        plan["spy_target"] + plan["stock_target"] + plan["sgov_target"]
        == plan["target_base"]
    )


def test_spy_stock_and_sgov_plan_never_exceeds_sizing_base() -> None:
    ranked = [{"symbol": f"S{index:02d}"} for index in range(50)]
    for multiplier in (0.0, 0.5, 1.0):
        plan = bot2.build_target_allocation_plan(
            equity=250_000,
            vault_market_value=25_000,
            ranked=ranked,
            multiplier=multiplier,
            benched_symbols={"S01", "S17"},
            spy_sleeve_weight=0.20,
        )
        planned = plan["spy_target"] + plan["stock_target"] + plan["sgov_target"]

        assert planned <= plan["target_base"] + 1e-8
        assert planned == plan["target_base"]


def test_volatility_multiplier_uses_run106_formula_and_caps_at_one() -> None:
    high_volatility = bot2.calculate_volatility_multiplier([0.02, -0.02] * 63)

    assert high_volatility["return_count"] == 126
    assert high_volatility["annualized_volatility"] > 0.12
    assert high_volatility["multiplier"] == (
        0.12 / high_volatility["annualized_volatility"]
    )

    low_volatility = bot2.calculate_volatility_multiplier([0.0001, -0.0001] * 63)

    assert low_volatility["reason"] == "calculated"
    assert low_volatility["multiplier"] == 1.0


def test_volatility_multiplier_falls_back_for_short_history_and_zero_volatility() -> None:
    short_history = bot2.calculate_volatility_multiplier([0.01] * 125)
    zero_volatility = bot2.calculate_volatility_multiplier([0.0] * 126)

    assert short_history == {
        "multiplier": 1.0,
        "annualized_volatility": None,
        "return_count": 125,
        "reason": "insufficient_returns",
    }
    assert zero_volatility["multiplier"] == 1.0
    assert zero_volatility["reason"] == "zero_volatility"


def test_volatility_returns_use_only_prior_nyse_sessions() -> None:
    as_of = date(2026, 10, 2)
    sessions = bot2._nyse_sessions_before(as_of, 127)
    points = [(day, 100.0 + index) for index, day in enumerate(sessions)]
    points.append((as_of, 1_000_000.0))

    returns = bot2.daily_returns_from_equity_points(points, as_of)

    assert len(returns) == 126
    assert returns[-1] == (226.0 / 225.0) - 1.0


def test_stop_cooldown_excludes_through_session_63_and_releases_on_64() -> None:
    close_date = date(2026, 1, 2)
    sessions = bot2.nyse_sessions_after(close_date, 64)
    closed_at = datetime.combine(
        close_date, bot2.dt_time(16, 0), tzinfo=bot2._eastern()
    )
    rows = [("AAPL", closed_at, "stop_filled")]

    on_session_63 = bot2.build_stop_cooldowns(rows, sessions[62])
    on_session_64 = bot2.build_stop_cooldowns(rows, sessions[63])

    assert on_session_63["AAPL"]["release_date"] == sessions[63]
    assert "AAPL" not in on_session_64


def test_non_stop_exit_reasons_do_not_create_cooldowns() -> None:
    close_date = date(2026, 1, 2)
    closed_at = datetime.combine(
        close_date, bot2.dt_time(16, 0), tzinfo=bot2._eastern()
    )
    as_of = bot2.nyse_sessions_after(close_date, 64)[10]
    rows = [
        ("AAPL", closed_at, "fell_out_of_top_50"),
        ("MSFT", closed_at, "stop_arm_failed_flattened"),
        ("NVDA", closed_at, "3day_drop_-5.0%"),
    ]

    assert bot2.build_stop_cooldowns(rows, as_of) == {}


def test_spy_stop_fill_never_creates_a_stock_cooldown() -> None:
    close_date = date(2026, 1, 2)
    closed_at = datetime.combine(
        close_date, bot2.dt_time(16, 0), tzinfo=bot2._eastern()
    )
    as_of = bot2.nyse_sessions_after(close_date, 10)[-1]

    cooldowns = bot2.build_stop_cooldowns(
        [("SPY", closed_at, "stop_filled"), ("AAPL", closed_at, "stop_filled")],
        as_of,
    )

    assert "SPY" not in cooldowns
    assert "AAPL" in cooldowns


def test_benched_rank_slot_stays_in_sgov_instead_of_backfilling() -> None:
    ranked = [{"symbol": f"S{index:02d}"} for index in range(50)]
    plan = bot2.build_target_allocation_plan(
        equity=100_000,
        vault_market_value=0,
        ranked=ranked,
        multiplier=0.5,
        benched_symbols={"S00"},
    )

    assert plan["slot_notional"] == 2_000
    assert plan["target_allocations"]["S00"] == 0
    assert plan["target_allocations"]["S01"] == 1_000
    assert plan["stock_target"] == 49_000
    assert plan["sgov_target"] == 51_000


class _ParkingClient:
    def __init__(self, held_qty: float, cash: float, price: float = 100.0) -> None:
        self.held_qty = held_qty
        self.cash = cash
        self.price = price
        self.submissions = []

    def positions(self):
        if self.held_qty == 0:
            return []
        return [{
            "symbol": "SGOV",
            "qty": self.held_qty,
            "market_value": self.held_qty * self.price,
        }]

    def account(self):
        return {
            "equity": 100_000.0,
            "cash": self.cash,
            "buying_power": self.cash,
            "long_market_value": self.held_qty * self.price,
        }

    def latest_price(self, symbol):
        assert symbol == "SGOV"
        return self.price

    def submit(self, symbol, side, qty, order_type):
        self.submissions.append((symbol, side, qty, order_type))
        return {"id": "dry-test-order"}


def test_sgov_parking_tops_up_existing_position_to_cover_idle_cash() -> None:
    client = _ParkingClient(held_qty=100.0, cash=10_099.0)

    result = bot2._park_idle_cash(client, set())

    assert client.submissions == [("SGOV", "buy", 100, "market")]
    assert result["held_qty"] == 100.0
    assert result["buy_qty"] == 100.0


def test_sgov_quantity_dust_is_treated_as_none() -> None:
    client = _ParkingClient(held_qty=5e-7, cash=10_099.0)

    result = bot2._park_idle_cash(client, set())

    assert result["held_qty"] == 0.0
    assert client.submissions == [("SGOV", "buy", 100, "market")]


class _PlaceholderCheckingCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=()):
        params = tuple(params or ())
        placeholders = len(re.findall(r"(?<!%)%s", query))
        if placeholders != len(params):
            raise AssertionError(
                f"query has {placeholders} placeholders but received {len(params)} params"
            )
        self.executed.append((query, params))

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self._cursor


class _SpyUpsertCursor(_PlaceholderCheckingCursor):
    def __init__(self):
        super().__init__([])
        self.rows_by_key = {}

    def execute(self, query, params=()):
        super().execute(query, params)
        if "ON CONFLICT (bot_id, symbol) WHERE status='open'" not in query:
            raise AssertionError("SPY ledger write must target the partial open-row index")
        if "DO UPDATE SET" not in query:
            raise AssertionError("SPY ledger write must update the existing open row")
        bot_id, symbol, qty, entry, notional, stop_price, stop_id = params
        key = (bot_id, symbol)
        previous = self.rows_by_key.get(key)
        self.rows_by_key[key] = {
            "id": previous["id"] if previous else len(self.rows_by_key) + 1,
            "qty": qty,
            "entry_price": entry,
            "notional_usd": notional,
            "stop_price": stop_price,
            "stop_order_id": stop_id,
        }


def test_database_fakes_enforce_placeholder_parameter_counts(monkeypatch) -> None:
    closed_rows = [
        ("AAPL", datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc), "stop_filled")
    ]
    cursor = _PlaceholderCheckingCursor(closed_rows)
    monkeypatch.setattr(bot2, "get_conn", lambda: _FakeConnection(cursor))

    rows, available = bot2.load_closed_position_history()

    assert available is True
    assert rows == closed_rows
    assert cursor.executed[0][1] == (bot2.BOT_ID,)
    try:
        cursor.execute("SELECT %s", ())
    except AssertionError:
        pass
    else:
        raise AssertionError("database fake must reject placeholder/parameter mismatch")


def test_spy_ledger_upserts_one_open_row_and_checks_placeholder_counts(monkeypatch) -> None:
    cursor = _SpyUpsertCursor()
    monkeypatch.setattr(bot2, "get_conn", lambda: _FakeConnection(cursor))

    bot2.record_spy_open(5, 100.0, 65.0, "spy-stop-1")
    bot2.record_spy_open(6, 105.0, 68.25, "spy-stop-2")

    assert len(cursor.rows_by_key) == 1
    row = cursor.rows_by_key[(bot2.BOT_ID, "SPY")]
    assert row == {
        "id": 1,
        "qty": 6,
        "entry_price": 105.0,
        "notional_usd": 630.0,
        "stop_price": 68.25,
        "stop_order_id": "spy-stop-2",
    }
    assert len(cursor.executed) == 2


def test_stop_fill_reconciliation_records_canonical_exit_reason(monkeypatch) -> None:
    class FilledStopClient:
        def positions(self):
            return []

        def get_order(self, order_id):
            assert order_id == "stop-1"
            return {
                "status": "filled",
                "side": "sell",
                "type": "stop",
                "filled_qty": "10",
                "filled_avg_price": "80",
            }

    recorded = []
    monkeypatch.setattr(
        bot2,
        "record_close",
        lambda symbol, reason, pnl: recorded.append((symbol, reason, pnl)),
    )
    positions = [{
        "symbol": "AAPL",
        "qty": 10,
        "entry_price": 100.0,
        "stop_order_id": "stop-1",
    }]

    remaining = bot2._reconcile_protective_stops(FilledStopClient(), positions)

    assert remaining == []
    assert recorded == [("AAPL", "stop_filled", -200.0)]


def test_buy_guard_rejects_negative_cash_and_deployment_overage() -> None:
    account = {"equity": 100_000, "cash": 1_000, "long_market_value": 80_000}
    allowed, projection = bot2.fresh_buy_guard(account, [], 2_000)

    assert not allowed
    assert projection["projected_cash"] == -1_000

    account = {"equity": 100_000, "cash": 50_000, "long_market_value": 79_000}
    allowed, projection = bot2.fresh_buy_guard(account, [], 2_000)

    assert allowed
    assert projection["projected_deployment"] == 0.81


def test_buy_guard_excludes_cash_park_using_canonical_symbol() -> None:
    account = {"equity": 100_000, "cash": 60_000, "long_market_value": 80_000}
    positions = [{"symbol": "s-gov", "market_value": 80_000}]

    allowed, projection = bot2.fresh_buy_guard(
        account,
        positions,
        20_000,
        max_deployment=0.25,
    )

    assert allowed
    assert projection["projected_deployment"] == 0.2


def test_pause_is_first_branch_and_does_not_construct_client(monkeypatch) -> None:
    monkeypatch.setattr(bot2, "BOT_PAUSED", True)

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("paused Bot 2 must not create an Alpaca client")

    monkeypatch.setattr(bot2, "AlpacaMomentumClient", ExplodingClient)

    result = bot2.run_bot2_cycle(
        profile={"ALPACA_API_KEY": "not-used", "ALPACA_SECRET_KEY": "not-used"},
        now=datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc),
    )

    assert result == {"status": "paused", "orders": 0}


def test_universe_gate_requires_full_provenance_and_pass(monkeypatch, tmp_path, caplog):
    gate_file = tmp_path / "bot2_universe_gate.json"
    assert bot2.BOT2_UNIVERSE_GATE_FILE == BOT2_UNIVERSE_GATE_FILE
    monkeypatch.setattr(bot2, "BOT2_UNIVERSE_GATE_FILE", gate_file)
    caplog.set_level(logging.INFO, logger="bot2.momentum")

    assert not bot2.universe_gate_is_passed()

    valid_payload = {
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "full",
        "research_database": "heliumdb",
        "scored_window": {"start": "2019-02-01", "end": "2026-10-03"},
        "sample_dates": ["2019-06-03", "2022-06-01"],
        "git_commit": "a" * 40,
    }
    gate_file.write_text(json.dumps(valid_payload), encoding="utf-8")
    assert bot2.universe_gate_is_passed()

    invalid_payloads = []
    missing_provenance = valid_payload.copy()
    del missing_provenance["sample_dates"]
    invalid_payloads.append(missing_provenance)
    non_full = valid_payload.copy()
    non_full["mode"] = "audit_only"
    invalid_payloads.append(non_full)
    failed_gate = valid_payload.copy()
    failed_gate["status"] = "STOP"
    invalid_payloads.append(failed_gate)
    for payload in invalid_payloads:
        gate_file.write_text(json.dumps(payload), encoding="utf-8")
        assert not bot2.universe_gate_is_passed()

    assert "universe gate age=" in caplog.text


def test_paused_cycle_logs_gate_age_every_cycle(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(bot2, "BOT2_UNIVERSE_GATE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(bot2, "BOT_PAUSED", True)
    caplog.set_level(logging.INFO, logger="bot2.momentum")

    first = bot2.run_bot2_cycle()
    second = bot2.run_bot2_cycle()

    assert first == {"status": "paused", "orders": 0}
    assert second == {"status": "paused", "orders": 0}
    assert caplog.text.count("universe gate age=") == 2


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
            "qty_available": self.qty,
            "entry_price": 100.0,
            "current_price": 100.0,
            "market_value": self.qty * 100.0,
        }]

    def open_orders(self):
        return []

    def cancel_confirm(self, order_id):
        return True


class _SellGuardClient:
    def __init__(
        self,
        *,
        qty: int = 10,
        available_qty: float = 10,
        order_statuses: dict[str, str] | None = None,
        cancel_statuses: dict[str, str] | None = None,
        open_orders: list[dict[str, str]] | None = None,
        order_symbols: dict[str, str] | None = None,
        failed_get_ids: set[str] | None = None,
    ) -> None:
        self.qty = qty
        self.available_qty = available_qty
        self.order_statuses = dict(order_statuses or {})
        self.cancel_statuses = dict(cancel_statuses or {})
        self.orders = list(open_orders or [])
        self.order_symbols = dict(order_symbols or {})
        self.failed_get_ids = set(failed_get_ids or ())
        self.events: list[tuple] = []
        self.submissions: list[tuple[str, str, int, str]] = []

    def account(self):
        return {
            "equity": 100_000.0,
            "cash": 90_000.0,
            "long_market_value": self.qty * 100.0,
        }

    def positions(self):
        if self.qty < 1:
            return []
        return [{
            "symbol": "AAPL",
            "qty": str(self.qty),
            "qty_available": str(self.available_qty),
            "market_value": self.qty * 100.0,
        }]

    def open_orders(self):
        return [dict(order) for order in self.orders]

    def get_order(self, order_id):
        self.events.append(("get", order_id, self.order_statuses.get(order_id)))
        if order_id in self.failed_get_ids:
            raise RuntimeError("synthetic order GET failure")
        return {
            "id": order_id,
            "symbol": self.order_symbols.get(order_id, "AAPL"),
            "status": self.order_statuses[order_id],
        }

    def cancel_confirm(self, order_id):
        self.events.append(("cancel", order_id))
        self.order_statuses[order_id] = self.cancel_statuses.get(
            order_id, "canceled"
        )
        return True

    def submit(self, symbol, side, qty, order_type, **extra):
        self.events.append(("submit", symbol, side, int(qty), order_type))
        self.submissions.append((symbol, side, int(qty), order_type))
        if side == "sell":
            self.qty = max(0, self.qty - int(qty))
            self.available_qty = max(0, self.available_qty - int(qty))
        return {"id": "market-sell-1"}

    def wait_for_fill(self, order_id):
        return {"status": "filled", "filled_avg_price": "100"}


class _SpyRebalanceClient:
    def __init__(
        self,
        *,
        qty: int = 0,
        entry_price: float = 100.0,
        cancel_allowed: bool = True,
    ) -> None:
        self.qty = qty
        self.entry_price = entry_price if qty else 0.0
        self.price = 100.0
        self.cash = 100_000.0 - qty * self.price
        self.cancel_allowed = cancel_allowed
        self.orders = {}
        self.submissions = []
        self.events = []
        self.next_id = 1

    def seed_stop(
        self, order_id: str, qty: int, stop_price: float = 65.0
    ) -> None:
        self.orders[order_id] = {
            "id": order_id,
            "symbol": "SPY",
            "side": "sell",
            "type": "stop",
            "status": "new",
            "qty": str(qty),
            "stop_price": stop_price,
            "time_in_force": "gtc",
        }

    def account(self):
        return {
            "equity": 100_000.0,
            "cash": self.cash,
            "long_market_value": self.qty * self.price,
        }

    def positions(self):
        if self.qty < 1:
            return []
        reserved_qty = sum(
            int(order.get("qty", 0))
            for order in self.orders.values()
            if (
                order["symbol"] == "SPY"
                and order["side"] == "sell"
                and order["type"] == "stop"
                and order["status"] == "new"
            )
        )
        return [{
            "symbol": "SPY",
            "qty": self.qty,
            "qty_available": max(0, self.qty - reserved_qty),
            "entry_price": self.entry_price,
            "current_price": self.price,
            "market_value": self.qty * self.price,
        }]

    def open_orders(self):
        # Include terminal orders to model a stale collection response.
        return [dict(order) for order in self.orders.values()]

    def get_order(self, order_id):
        order = self.orders[order_id]
        self.events.append(("get", order_id, order["status"]))
        return dict(order)

    def cancel_confirm(self, order_id):
        self.events.append(("cancel", order_id))
        if not self.cancel_allowed:
            return False
        self.orders[order_id]["status"] = "canceled"
        return True

    def submit(self, symbol, side, qty, order_type, **extra):
        order_id = f"spy-order-{self.next_id}"
        self.next_id += 1
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "qty": str(qty),
            "status": "new" if order_type == "stop" else "filled",
            "time_in_force": "gtc" if order_type == "stop" else "day",
            **extra,
        }
        self.orders[order_id] = order
        self.submissions.append((symbol, side, int(qty), order_type, dict(extra)))
        self.events.append(("submit", symbol, side, int(qty), order_type, order_id))
        if order_type == "market":
            if side == "buy":
                new_qty = self.qty + int(qty)
                self.entry_price = (
                    (self.qty * self.entry_price + int(qty) * self.price) / new_qty
                    if new_qty
                    else 0.0
                )
                self.qty = new_qty
                self.cash -= int(qty) * self.price
            else:
                if int(qty) > self.qty:
                    raise AssertionError("test client cannot sell more shares than held")
                self.qty -= int(qty)
                self.cash += int(qty) * self.price
                if self.qty == 0:
                    self.entry_price = 0.0
        return dict(order)

    def wait_for_fill(self, order_id):
        order = self.orders[order_id]
        return {
            "id": order_id,
            "status": order["status"],
            "filled_qty": order["qty"],
            "filled_avg_price": str(self.price),
        }


def _sell_guard_position(stop_order_id: str | None = "stop-1"):
    return {
        "symbol": "AAPL",
        "qty": 10,
        "entry_price": 100.0,
        "stop_order_id": stop_order_id,
    }


def test_sell_gets_and_cancels_recorded_stop_missing_from_list_before_sale(
    monkeypatch,
) -> None:
    client = _SellGuardClient(
        order_statuses={"stop-1": "new", "open-2": "accepted"},
        open_orders=[
            {"id": "open-2", "symbol": "aApL"},
            {"id": "unrelated", "symbol": "MSFT"},
        ],
    )
    recorded = []
    monkeypatch.setattr(
        bot2,
        "record_close",
        lambda symbol, reason, pnl: recorded.append((symbol, reason, pnl)),
    )

    assert bot2._sell_confirmed(
        client, _sell_guard_position(), "fell_out_of_top_50"
    )

    assert [event[1] for event in client.events if event[0] == "cancel"] == [
        "stop-1",
        "open-2",
    ]
    assert client.submissions == [("AAPL", "sell", 10, "market")]
    assert recorded == [("AAPL", "fell_out_of_top_50", 0.0)]
    assert client.events.index(("get", "stop-1", "new")) < client.events.index(
        ("cancel", "stop-1")
    )
    assert client.events.index(("get", "stop-1", "canceled")) < client.events.index(
        ("submit", "AAPL", "sell", 10, "market")
    )


def test_confirmed_cancelled_order_in_stale_list_does_not_block_sell(
    monkeypatch,
) -> None:
    client = _SellGuardClient(
        order_statuses={"stop-1": "canceled"},
        open_orders=[{"id": "stop-1", "symbol": "AAPL"}],
    )
    monkeypatch.setattr(bot2, "record_close", lambda *args: None)

    assert bot2._sell_confirmed(
        client, _sell_guard_position(), "fell_out_of_top_50"
    )

    assert not any(event[0] == "cancel" for event in client.events)
    assert client.submissions == [("AAPL", "sell", 10, "market")]


def test_failed_order_get_blocks_sale(monkeypatch) -> None:
    client = _SellGuardClient(failed_get_ids={"stop-1"})

    assert not bot2._sell_confirmed(
        client, _sell_guard_position(), "fell_out_of_top_50"
    )

    assert client.submissions == []


def test_nonfinal_post_cancel_status_blocks_sale(monkeypatch) -> None:
    client = _SellGuardClient(
        order_statuses={"stop-1": "new"},
        cancel_statuses={"stop-1": "pending_cancel"},
    )

    assert not bot2._sell_confirmed(
        client, _sell_guard_position(), "fell_out_of_top_50"
    )

    assert client.submissions == []


def test_spy_rebalances_whole_shares_with_one_35_percent_stop_and_one_ledger_row(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bot2.time, "sleep", lambda *_args: None)
    client = _SpyRebalanceClient()
    ledger = {}

    def upsert(qty, entry, stop_price, stop_id):
        ledger["SPY"] = {
            "symbol": "SPY",
            "qty": qty,
            "entry_price": entry,
            "stop_price": stop_price,
            "stop_order_id": stop_id,
        }

    monkeypatch.setattr(bot2, "record_spy_open", upsert)
    first = bot2._rebalance_spy_sleeve(client, 5, None, set(), 100.0)
    second = bot2._rebalance_spy_sleeve(client, 6, ledger["SPY"], set(), 100.0)
    third = bot2._rebalance_spy_sleeve(client, 3, ledger["SPY"], set(), 100.0)

    active_stops = [
        order
        for order in client.orders.values()
        if order["symbol"] == "SPY"
        and order["side"] == "sell"
        and order["type"] == "stop"
        and order["status"] == "new"
    ]
    market_orders = [
        item for item in client.submissions if item[3] == "market"
    ]

    assert [first["settled_qty"], second["settled_qty"], third["settled_qty"]] == [
        5, 6, 3
    ]
    assert market_orders == [
        ("SPY", "buy", 5, "market", {}),
        ("SPY", "buy", 1, "market", {}),
        ("SPY", "sell", 3, "market", {}),
    ]
    assert len(active_stops) == 1
    assert int(active_stops[0]["qty"]) == 3
    assert active_stops[0]["stop_price"] == 65.0
    assert ledger["SPY"]["qty"] == 3
    assert ledger["SPY"]["stop_price"] == 65.0
    assert len(ledger) == 1
    for old_id in ("spy-order-2", "spy-order-4"):
        assert client.orders[old_id]["status"] == "canceled"
    for stop_id, market_id in (
        ("spy-order-2", "spy-order-3"),
        ("spy-order-4", "spy-order-5"),
    ):
        assert client.events.index(("get", stop_id, "canceled")) < next(
            index for index, event in enumerate(client.events)
            if event[0] == "submit" and event[-1] == market_id
        )


def test_spy_does_not_trade_when_an_open_order_cannot_be_confirmed_cancelled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bot2.time, "sleep", lambda *_args: None)
    client = _SpyRebalanceClient(qty=5, cancel_allowed=False)
    client.seed_stop("existing-spy-stop", 5)
    ledger_position = {
        "symbol": "SPY",
        "qty": 5,
        "entry_price": 100.0,
        "stop_order_id": "existing-spy-stop",
    }

    try:
        bot2._rebalance_spy_sleeve(
            client, 6, ledger_position, set(), 100.0
        )
    except RuntimeError as exc:
        assert "unconfirmed open order" in str(exc)
    else:
        raise AssertionError("SPY must not trade while cancellation is unconfirmed")

    assert client.submissions == []
    assert client.qty == 5


def test_spy_reconciliation_replaces_a_non_35_percent_stop(monkeypatch) -> None:
    monkeypatch.setattr(bot2.time, "sleep", lambda *_args: None)
    client = _SpyRebalanceClient(qty=5)
    client.seed_stop("legacy-spy-stop", 5, stop_price=80.0)
    recorded = []
    monkeypatch.setattr(
        bot2,
        "record_spy_open",
        lambda qty, entry, stop_price, stop_id: recorded.append(
            (qty, entry, stop_price, stop_id)
        ),
    )
    ledger_position = {
        "symbol": "SPY",
        "qty": 5,
        "entry_price": 100.0,
        "stop_price": 80.0,
        "stop_order_id": "legacy-spy-stop",
    }

    remaining = bot2._reconcile_protective_stops(client, [ledger_position])

    active_stops = [
        order for order in client.orders.values()
        if order["type"] == "stop" and order["status"] == "new"
    ]
    assert remaining == [ledger_position]
    assert client.orders["legacy-spy-stop"]["status"] == "canceled"
    assert len(active_stops) == 1
    assert active_stops[0]["stop_price"] == 65.0
    assert recorded == [(5, 100.0, 65.0, active_stops[0]["id"])]


def test_available_quantity_short_of_sale_blocks_order(monkeypatch) -> None:
    client = _SellGuardClient(available_qty=9)
    monkeypatch.setattr(bot2, "record_close", lambda *args: None)

    assert not bot2._sell_confirmed(
        client, _sell_guard_position(stop_order_id=None), "fell_out_of_top_50"
    )

    assert client.submissions == []


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