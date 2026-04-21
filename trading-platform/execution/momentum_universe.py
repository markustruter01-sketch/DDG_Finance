"""
Momentum Universe — ~250+ Liquid NYSE/NASDAQ Stocks & ETFs
-----------------------------------------------------------
Organized by GICS sector and asset class for regime-aware filtering.
Bear regime favors defensive sectors (healthcare, utilities, staples, energy).
Bull/Sideways scans the full universe.
"""

from __future__ import annotations

TECHNOLOGY: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOG", "META", "AMZN", "TSLA", "AMD", "AVGO",
    "CRM", "ORCL", "ADBE", "INTC", "CSCO", "TXN", "QCOM", "MU", "AMAT",
    "LRCX", "KLAC", "MRVL", "SNPS", "CDNS", "NOW", "PANW", "CRWD", "FTNT",
    "NET", "DDOG", "ZS", "PLTR", "ARM", "SMCI", "DELL", "HPE", "UBER",
    "ABNB", "DASH", "SHOP", "XYZ", "SNOW", "COIN", "MSTR",
]

FINANCIALS: list[str] = [
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
    "COF", "C", "USB", "PNC", "TFC", "AIG", "MET", "PRU", "ALL", "CB",
    "PYPL",
]

HEALTHCARE: list[str] = [
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "ISRG", "BSX", "MDT", "SYK", "EW", "ZTS", "REGN",
    "VRTX", "HCA", "CI", "ELV", "GEHC", "MRNA", "BIIB",
]

ENERGY: list[str] = [
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "DVN",
    "HAL", "FANG", "HES", "BKR", "KMI", "FSLR", "ENPH",
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

INTERNATIONAL_ADRS: list[str] = [
    "TSM", "ASML", "NVO", "SAP", "TM", "MELI", "NU", "PDD", "SE",
]

SECTOR_ETFS: list[str] = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLE", "XLI",
    "XLP", "XLY", "XLC", "XLB", "XLRE", "XLU",
]

SAFE_HAVEN_ETFS: list[str] = [
    "TLT", "IEF", "GLD", "SLV", "AGG", "BND", "TIP", "GOVT",
]

COMMODITY_ETFS: list[str] = [
    "USO", "PDBC", "DBA", "UNG", "COPX",
]

LEVERAGED_BULL_ETFS: list[str] = [
    "TQQQ", "SOXL", "UPRO",
]

INVERSE_BEAR_ETFS: list[str] = [
    "SH", "PSQ", "DOG", "SPXS", "SQQQ", "SRTY", "SDS", "SDOW",
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
    "international_adrs": INTERNATIONAL_ADRS,
    "sector_etfs": SECTOR_ETFS,
    "safe_haven_etfs": SAFE_HAVEN_ETFS,
    "commodity_etfs": COMMODITY_ETFS,
    "leveraged_bull_etfs": LEVERAGED_BULL_ETFS,
    "inverse_bear_etfs": INVERSE_BEAR_ETFS,
}

DEFENSIVE_SECTORS: set[str] = {
    "healthcare", "utilities", "consumer_staples", "energy",
    "safe_haven_etfs", "commodity_etfs",
}

CYCLICAL_SECTORS: set[str] = {
    "technology", "financials", "industrials",
    "consumer_discretionary", "communication", "materials",
    "international_adrs",
}

# Inverse ETFs are excluded from the momentum scan universe.
# Oracle shorting an inverse ETF creates leveraged long exposure (e.g. shorting SQQQ = leveraged long QQQ).
# They remain in INVERSE_BEAR_ETFS for use by the allocator's bear hedge logic only.
_SCAN_EXCLUDED_SECTORS = {"inverse_bear_etfs"}

FULL_UNIVERSE: list[str] = []
for _sector_name, _sector_tickers in ALL_SECTORS.items():
    if _sector_name not in _SCAN_EXCLUDED_SECTORS:
        FULL_UNIVERSE.extend(_sector_tickers)

TICKER_TO_SECTOR: dict[str, str] = {}
for _sector_name, _sector_tickers in ALL_SECTORS.items():
    for _t in _sector_tickers:
        TICKER_TO_SECTOR[_t] = _sector_name

DEFENSIVE_TICKERS: set[str] = set()
for _s in DEFENSIVE_SECTORS:
    DEFENSIVE_TICKERS.update(ALL_SECTORS[_s])

UNIVERSE_SIZE: int = len(FULL_UNIVERSE)
