"""Home card holdings (core/holdings.py). Inputs copied from production
bot_portfolio rows read on 10 Nov 2026 (19:06 UTC), trimmed."""
from core.holdings import alpaca_holdings, forex_holdings, group_label, holdings_by_bot


def _p(symbol, value):
    return {"symbol": symbol, "value_usd": value, "qty": 1, "side": "long"}


def test_groups_and_gearing():
    assert group_label("SSO") == "S&P 500 2x" and group_label("SPY") == "S&P 500"
    assert group_label("QLD") == "Nasdaq 2x" and group_label("UGL") == "Gold 2x"
    assert group_label("BTC/USD") == "Crypto" and group_label("ETHUSD") == "Crypto"
    assert group_label("SGOV") == "Cash" and group_label("VOO") == "Vault"
    assert group_label("NVDA") == "Stocks"


def test_alpaca_items_sum_to_100_with_cash_residual():
    held = alpaca_holdings(99179.59, [_p("BIL", 5611.07275), _p("SGOV", 1044.655326)])
    by = {i["label"]: i["pct"] for i in held["items"]}
    assert by == {"Cash": 94.3, "Vault": 5.7}
    assert held["items"][0]["label"] == "Cash"


def test_leveraged_and_borrowed():
    held = alpaca_holdings(100_000, [_p("SSO", 80_000), _p("QQQ", 40_000)])
    by = {i["label"]: i["pct"] for i in held["items"]}
    assert by == {"S&P 500 2x": 80.0, "Nasdaq": 40.0, "Borrowed": -20.0}


def test_unreadable_line_hides_the_whole_card_breakdown():
    assert alpaca_holdings(100_000, [{"symbol": "SPY"}]) is None
    assert alpaca_holdings(None, []) is None


def test_forex_pairs_direction_size_and_gross():
    positions = [
        {"instrument": "NZD_USD", "long": {"units": "0"}, "short": {"units": "-64601", "averagePrice": "0.56814"}},
        {"instrument": "USD_CHF", "long": {"units": "37013", "averagePrice": "0.82008"}, "short": {"units": "0"}},
    ]
    held = forex_holdings(100533.55, positions)
    by = {i["label"]: i["pct"] for i in held["items"]}
    # NZD_USD: 64601 x 0.56814 = $36,702.4; USD_CHF: 37013 units of USD = $37,013
    assert by == {"USD/CHF long": 36.8, "NZD/USD short": 36.5}
    assert held["gross_pct"] == 73.3


def test_by_bot_skips_inactive_and_survives_bad_rows():
    rows = [{"bot_id": "oracle", "equity_usd": "1000", "positions": [_p("SPY", 500)], "last_updated": "t"},
            {"bot_id": "forex_ai", "equity_usd": 1000, "positions": [{"instrument": "EUR_GBP", "long": {"units": "5", "averagePrice": "1"}}]},
            {"bot_id": "forex_gump", "equity_usd": 1, "positions": []}]
    out = holdings_by_bot(rows, {"oracle", "forex_ai"})
    assert set(out) == {"oracle", "forex_ai"} and out["forex_ai"] is None
    assert out["oracle"]["as_of"] == "t" and out["oracle"]["items"][0] == {"label": "S&P 500", "pct": 50.0}
