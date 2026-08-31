from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from analysis import bot2_sp500_data as data


def test_pinned_bundle_reconstructs_historical_membership() -> None:
    bundle = data.load_bundle()

    assert data.source_coverage_end(bundle) == date(2026, 8, 27)
    assert len(data.members_asof(bundle, date(2018, 12, 31))) == 507
    assert "TWTR" in data.members_asof(bundle, date(2020, 12, 31))
    assert "TWTR" not in data.members_asof(bundle, date(2022, 12, 31))
    assert "RDDT" in data.members_asof(bundle, date(2026, 8, 27))
    assert "FERG" in data.members_asof(bundle, date(2026, 8, 27))


def test_membership_intervals_include_removed_symbols() -> None:
    bundle = data.load_bundle()
    intervals = data.membership_intervals(
        bundle,
        start=date(2018, 1, 1),
        end=date(2026, 8, 26),
    )
    twtr = [item for item in intervals if item.symbol == "TWTR"]

    assert twtr == [
        data.MembershipInterval("TWTR", date(2018, 6, 7), date(2022, 10, 31))
    ]


def test_historical_ticker_alias_uses_continuous_price_symbol() -> None:
    bundle = data.load_bundle()

    assert data.price_symbol(bundle, "FB") == "META"
    assert data.price_symbol(bundle, "META") == "META"


def test_recent_sip_entitlement_falls_back_to_iex(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(symbol, start, end, feed, retries=4):
        calls.append(feed)
        if feed == "sip" and end >= data.RECENT_SIP_CUTOFF:
            return [], "HTTP 403: subscription does not permit querying recent SIP data"
        if feed == "sip":
            return [
                data.PriceBar(
                    symbol, date(2025, 12, 31), 1, 1, 1, 1, 100, data.PRICE_SOURCE
                )
            ], None
        return [
            data.PriceBar(
                symbol,
                date(2026, 8, 26),
                1,
                1,
                1,
                1,
                100,
                data.RECENT_PRICE_SOURCE,
            )
        ], None

    monkeypatch.setattr(data, "_fetch_feed", fake_fetch)
    symbol, bars, error = data._fetch_one_symbol(
        "AAPL", date(2018, 1, 1), date(2026, 8, 26)
    )

    assert symbol == "AAPL"
    assert error is None
    assert [bar.source for bar in bars] == [
        data.PRICE_SOURCE,
        data.RECENT_PRICE_SOURCE,
    ]
    assert calls == ["sip", "sip", "iex"]


def test_expected_sessions_treat_juneteenth_as_exchange_holiday_from_2022() -> None:
    assert date(2021, 6, 18) in data.expected_sessions(date(2021, 6, 18), date(2021, 6, 21))
    assert date(2022, 6, 20) not in data.expected_sessions(date(2022, 6, 20), date(2022, 6, 21))


def test_yahoo_source_is_reference_only() -> None:
    assert data.YAHOO_PRICE_SOURCE not in data.PRICE_SOURCES
    assert data.YAHOO_PRICE_SOURCE in data.REFERENCE_PRICE_SOURCES


def test_yahoo_chart_adjusted_ohlc_uses_adjusted_close_factor(monkeypatch) -> None:
    timestamp = int(datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp())

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [timestamp],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [100.0],
                                        "high": [110.0],
                                        "low": [90.0],
                                        "close": [100.0],
                                        "volume": [1234.0],
                                    }
                                ],
                                "adjclose": [{"adjclose": [80.0]}],
                            },
                        }
                    ]
                }
            }

    monkeypatch.setattr(
        "analysis.bot2_sp500_data.requests.get",
        lambda *args, **kwargs: Response(),
    )
    symbol, bars, error = data._fetch_yahoo_symbol(
        "SPY", date(2024, 1, 1), date(2024, 1, 3)
    )

    assert error is None
    assert symbol == "SPY"
    assert bars[0].source == data.YAHOO_PRICE_SOURCE
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == (
        80.0,
        88.0,
        72.0,
        80.0,
    )


def test_reference_sanity_reports_duplicate_missing_and_large_move() -> None:
    bars = [
        data.PriceBar(
            "SPY", date(2024, 1, 2), 100, 100, 100, 100, 1, data.YAHOO_PRICE_SOURCE
        ),
        data.PriceBar(
            "SPY", date(2024, 1, 3), 100, 100, 100, 130, 1, data.YAHOO_PRICE_SOURCE
        ),
        data.PriceBar(
            "SPY", date(2024, 1, 3), 100, 100, 100, 130, 1, data.YAHOO_PRICE_SOURCE
        ),
    ]

    issues = data._reference_data_issues(bars, date(2024, 1, 5))

    assert any(issue.startswith("duplicate_dates=") for issue in issues)
    assert any(issue.startswith("missing_nyse_sessions=") for issue in issues)
    assert any(issue.startswith("moves_over_20pct=") for issue in issues)


def test_reference_loader_refuses_existing_rows() -> None:
    with pytest.raises(RuntimeError, match="existing rows would be modified.*SPY=2"):
        data._assert_reference_symbols_empty({"SPY": 2, "SGOV": 0})