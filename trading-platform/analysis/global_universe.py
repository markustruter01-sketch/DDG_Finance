"""
PRE-REGISTERED 2026-08-06. Universe locked before backtest.
Selection = liquidity + diversification only. No performance-based changes
permitted without documented re-registration.
"""

# ── GLOBAL REGIONAL ETF UNIVERSE ─────────────────────────────────────────────
# Anchor: the validated Moe trend strategy runs on US_CORE.
# All regional lists chosen on liquidity + structural diversification ONLY.
# DO NOT add or remove tickers based on how they performed. That is data
# snooping. Any change to this list requires a new dated registration block
# above with a written justification referencing structural, not performance,
# criteria.

US_CORE       = ["SPY", "QQQ"]               # US anchor — always included
ASIA_PACIFIC  = ["EWY", "EWT", "INDA", "EWJ", "EWM", "VNM"]  # Korea, Taiwan, India, Japan, Malaysia, Vietnam
LATIN_AMERICA = ["EWZ", "EWW", "ECH", "ARGT"]                 # Brazil, Mexico, Chile, Argentina
FRONTIER_EM   = ["EEM", "EZA", "EPOL", "GREK", "TUR"]         # Broad EM, South Africa, Poland, Greece, Turkey
BENCHMARK     = ["SPY", "EEM"]               # Test targets — any new strategy must beat these

# Flat list of all unique tickers (preserves the locked order)
ALL_TICKERS: list[str] = list(dict.fromkeys(
    US_CORE + ASIA_PACIFIC + LATIN_AMERICA + FRONTIER_EM
))

# Region mapping for reporting
TICKER_REGION: dict[str, str] = {
    **{t: "US_CORE"       for t in US_CORE},
    **{t: "ASIA_PACIFIC"  for t in ASIA_PACIFIC},
    **{t: "LATIN_AMERICA" for t in LATIN_AMERICA},
    **{t: "FRONTIER_EM"   for t in FRONTIER_EM},
}

# Historical test windows (crisis + recovery cycles)
# Each entry: (label, window_start, window_end, ema200_warmup_from)
# The EMA200 warmup requires ~1 year of prior data before window_start.
TEST_WINDOWS = [
    ("2008 GFC",             "2008-01-01", "2009-12-31", "2007-01-01"),
    ("2011 EM selloff",      "2011-01-01", "2012-06-30", "2010-01-01"),
    ("2013 taper tantrum",   "2013-01-01", "2014-06-30", "2012-01-01"),
    ("2015-16 EM bear",      "2015-01-01", "2016-12-31", "2014-01-01"),
    ("2018 correction",      "2018-01-01", "2019-03-31", "2017-01-01"),
    ("2020 COVID",           "2020-01-01", "2021-06-30", "2019-01-01"),
    ("2022 rate shock",      "2022-01-01", "2023-03-31", "2021-01-01"),
    ("2023-24 recovery",     "2023-01-01", "2024-12-31", "2022-01-01"),
]

if __name__ == "__main__":
    print("=== PRE-REGISTERED UNIVERSE (2026-08-06) ===")
    for region, tickers in [
        ("US_CORE",       US_CORE),
        ("ASIA_PACIFIC",  ASIA_PACIFIC),
        ("LATIN_AMERICA", LATIN_AMERICA),
        ("FRONTIER_EM",   FRONTIER_EM),
        ("BENCHMARK",     BENCHMARK),
    ]:
        print(f"  {region:<14}: {tickers}")
    print(f"\n  Total unique tickers: {len(ALL_TICKERS)}")
