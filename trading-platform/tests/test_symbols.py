from core.symbols import alpaca_symbol, canonical_symbol, same_symbol


def test_crypto_forms_share_identity():
    assert canonical_symbol("BTCUSD") == canonical_symbol("BTC/USD")
    assert same_symbol("BTCUSD", "BTC/USD")
    assert same_symbol("ETHUSD", "ETH/USD")


def test_equity_symbols_are_unchanged_in_identity():
    assert canonical_symbol("GLD") == "GLD"
    assert canonical_symbol("VOO") == "VOO"
    assert alpaca_symbol("GLD") == "GLD"


def test_coverage_matching_works_across_crypto_formats():
    position = {"symbol": "BTCUSD", "qty": 1}
    order = {"symbol": "BTC/USD", "side": "sell"}
    assert same_symbol(position["symbol"], order["symbol"])