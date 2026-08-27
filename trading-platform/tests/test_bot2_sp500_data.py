from __future__ import annotations

from datetime import date

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