"""
Momentum Universe — ~200 Liquid NYSE/NASDAQ Stocks
---------------------------------------------------
Organized by GICS sector for regime-aware filtering.
Bear regime favors defensive sectors (healthcare, utilities, staples, energy).
Bull/Sideways scans the full universe.
"""

from __future__ import annotations

TECHNOLOGY: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOG", "META", "AMZN", "TSLA", "AMD", "AVGO",
    "CRM", "ORCL", "ADBE", "INTC", "CSCO", "TXN", "QCOM", "MU", "AMAT",
    "LRCX", "KLAC", "MRVL", "SNPS", "CDNS", "NOW", "PANW", "CRWD", "FTNT",
    "NET", "DDOG", "ZS", "PLTR", "ARM", "SMCI", "DELL", "HPE", "UBER",
    "ABNB", "DASH", "SHOP", "SQ",
]

FINANCIALS: list[str] = [
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
    "COF", "C", "USB", "PNC", "TFC", "AIG", "MET", "PRU", "ALL", "CB",
]

HEALTHCARE: list[str] = [
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "ISRG", "BSX", "MDT", "SYK", "EW", "ZTS", "REGN",
    "VRTX", "HCA", "CI", "ELV", "GEHC",
]

ENERGY: list[str] = [
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "DVN",
    "HAL", "FANG", "HES", "BKR", "KMI",
]

INDUSTRIALS: list[str] = [
    "CAT", "DE", "HON", "UNP", "LMT", "RTX", "GE", "BA", "MMM", "ITW",
    "EMR", "ETN", "PH", "GD", "NOC", "WM", "RSG", "CSX", "NSC", "FDX",
    "UPS",
]

CONSUMER_DISCRETIONARY: list[str] = [
    "HD", "LOW", "NKE", "SBUX", "MCD", "LULU", "TJX", "ROST", "YUM", "CMG",
    "DHI", "LEN", "GM", "F", "BKNG", "MAR", "HLT", "RCL", "CCL", "EBAY",
]

CONSUMER_STAPLES: list[str] = [
    "WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "CL", "KMB", "GIS",
    "HSY", "MDLZ", "STZ", "TGT", "DG", "DLTR",
]

COMMUNICATION: list[str] = [
    "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "CHTR", "EA", "TTWO",
    "RBLX", "SPOT",
]

MATERIALS: list[str] = [
    "LIN", "APD", "ECL", "SHW", "FCX", "NEM", "NUE", "CF", "DD", "DOW",
]

REITS: list[str] = [
    "AMT", "PLD", "CCI", "EQIX", "SPG", "O", "PSA", "DLR", "WELL", "AVB",
]

UTILITIES: list[str] = [
    "NEE", "DUK", "SO", "AEP", "D", "SRE", "EXC", "XEL", "WEC", "ES",
]

SECTOR_ETFS: list[str] = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLE", "XLI",
    "XLP", "XLY", "XLC", "XLB", "XLRE", "XLU",
]

ALL_SECTORS: dict[str, list[str]] = {
    "technology": TECHNOLOGY,
    "financials": FINANCIALS,
    "healthcare": HEALTHCARE,
    "energy": ENERGY,
    "industrials": INDUSTRIALS,
    "consumer_discretionary": CONSUMER_DISCRETIONARY,
    "consumer_staples": CONSUMER_STAPLES,
    "communication": COMMUNICATION,
    "materials": MATERIALS,
    "reits": REITS,
    "utilities": UTILITIES,
    "sector_etfs": SECTOR_ETFS,
}

DEFENSIVE_SECTORS: set[str] = {
    "healthcare", "utilities", "consumer_staples", "energy",
}

CYCLICAL_SECTORS: set[str] = {
    "technology", "financials", "industrials",
    "consumer_discretionary", "communication", "materials",
}

FULL_UNIVERSE: list[str] = []
for _sector_tickers in ALL_SECTORS.values():
    FULL_UNIVERSE.extend(_sector_tickers)

TICKER_TO_SECTOR: dict[str, str] = {}
for _sector_name, _sector_tickers in ALL_SECTORS.items():
    for _t in _sector_tickers:
        TICKER_TO_SECTOR[_t] = _sector_name

DEFENSIVE_TICKERS: set[str] = set()
for _s in DEFENSIVE_SECTORS:
    DEFENSIVE_TICKERS.update(ALL_SECTORS[_s])

UNIVERSE_SIZE: int = len(FULL_UNIVERSE)
