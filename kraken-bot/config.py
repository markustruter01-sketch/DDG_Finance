"""
config.py  —  Kraken Bot Configuration (Multi-Bot)
====================================================
Single source of truth for every tunable parameter in the bot.
Supports multiple bot profiles via BOT_ID environment variable.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


PAPER_TRADING = True
PAPER_STARTING_BALANCE = 100_000.0
PAPER_FEE_PCT = 0.0026

GLOBAL_EMERGENCY_STOP = False

# APPROVED 10 Oct 2026 (registered Forex plan, item 4): gross exposure cap
# 2.0x Forex equity for MVP. No 5x/10x tiers.
# CHANGED 21 Nov 2026 by Markus ("yes I want the real forex account to be 1.5"):
# 1.5x from the next publish. Open trades are kept; only new entries get less room.
FOREX_MAX_GROSS = 1.5

BOT_PROFILES = {
    "oracle": {
        # Phase 3: Bot 1 is the single global ETF trend account. Regional
        # attribution is retained by the durable per-symbol scan ledger.
        "display_name":      "Global ETF Trend",
        "db_id":             5,
        "strategy_type":     "etf_trend_global",
        "strategy_label":    "FLEET-V1-F1: 65% geared S&P/Nasdaq trend core + 35% cross-asset trend (bonds, gold, commodities, dollar)",
        # ── Alpaca account (oracle's dedicated paper account) ──────────────────
        "ALPACA_API_KEY":    os.environ.get("ALPACA_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        "LOOP_SLEEP_SECONDS": 3600,    # hourly cycle (exits every hour)
        # Runner schedules one additional full cycle at this deterministic UTC
        # window start, so the entry scan cannot drift past its 19:40–19:59 gate.
        "ENTRY_WINDOW_START_UTC": (19, 40),
        "ENTRY_WINDOW_DURATION_MINUTES": 20,
        # ── Universe ──────────────────────────────────────────────────────────
        "GLOBAL_UNIVERSE":   [
            "SPY", "QQQ",
            "EWY", "EWT", "INDA", "EWJ", "EWM", "VNM",
            "EWZ", "EWW", "ECH", "EEM", "EZA", "EPOL", "GREK", "TUR",
        ],
        # ── Risk management: proposed consolidated starting hypothesis ─────
        "MAX_POSITIONS":     6,
        "VOL_TARGET":        0.12,
        "VOL_CAP":           0.13,
        "TRAIL_STOP_PCT":    0.08,
        "TP1_PCT":           0.06,
        "TP2_PCT":           0.12,
        "MIN_HOLD_DAYS":     5,
        # FLEET-V1-F1 can invest ~99% of sleeve equity (1% cash buffer); the
        # kill switch's deployment check must allow it.
        "MAX_DEPLOYMENT":    1.00,
        # FLEET-V1-F1 owns this account (sleeve_runtime/fleet_live.py), by
        # Markus's decision 2 Nov 2026 (sleeve_runtime/FLEET-V1-LIVE-SPEC.md).
        # It sells G4's holdings it does not want on its first cycle.
        # Rollback to G4: FLEET_SLEEVE_LIVE False, GEAR_SLEEVE_LIVE True, publish.
        "FLEET_SLEEVE_LIVE": True,
        "GEAR_SLEEVE_LIVE":  False,
        # TREND-V1-B cutover: cancelled 23 Oct 2026 (G4 took the account).
        "TREND_SLEEVE_LIVE": False,
    },
    "jerome_macro": {
        # Stage 5 merge (2026-08-11): LatAm (EWZ/EWW/ECH) + Frontier (EEM/EZA/EPOL/GREK/TUR)
        # merged into one 8-ETF Emerging Markets bot. Resolves the two-bots-one-account
        # collision. Jerome account (6da42513) is now the sole account for this bot.
        # FLEET-V1-C1 owns this account since 3 Nov 2026 (kraken-bot/bullion_strategy.py):
        # F1's equity core without the cross-asset sleeve. The EM settings below
        # are history; the runner no longer calls bot3_hard_assets_strategy.
        "display_name":      "Atlas V2",
        "db_id":             2,
        "strategy_type":     "fleet_v1_c1",
        "strategy_label":    "FLEET-V1-C1: geared S&P/Nasdaq trend core (F1 without the cross-asset sleeve)",
        # ── Alpaca account (Jerome's dedicated paper account — sole EM bot) ───
        "ALPACA_API_KEY":    os.environ.get("ALPACA_JEROME_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_JEROME_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        "LOOP_SLEEP_SECONDS": 3600,    # hourly cycle (exits every hour)
        # ── Bot 3 is event-driven; it has no fixed daily entry window ───
        "EM_UNIVERSE":       ["EWZ", "EWW", "ECH", "EEM", "EZA", "EPOL", "GREK", "TUR"],
        # ── Risk management ───────────────────────────────────────────────────
        "MAX_POSITIONS":     3,        # 8-ETF basket; preserve cash headroom
        "VOL_TARGET":        0.12,
        "TRAIL_STOP_PCT":    0.08,
        "TP1_PCT":           0.06,
        "TP2_PCT":           0.12,
        "MIN_HOLD_DAYS":     5,
        "MAX_DEPLOYMENT":    1.00,
        # Reserved for Phase 3 Bot 3; activation follows separate validation.
        # Paused in code pending an owner decision (audit 2 Nov 2026,
        # FLEET-V1-LIVE-SPEC.md section 1): the cycle returns before reading
        # or trading anything. Its open positions keep their broker stops.
        "PAUSED_IN_CODE":    True,
    },

    # ── Phase 2: New Alpaca-based bots (built paused, staggered activation) ───
    #
    # All 4 share the ALPACA_BB paper account with Jerome.
    # Pause/resume is bots_state.paused only (dashboard or POST /bots/{id}/pause|resume).
    # Historical activation schedule:
    #   Week 2: bot2_spy_qqq   (db_id=1, replaces Davy Jones)
    #   Week 3: bot4_sector    (db_id=3, replaces Calypso)
    #   Week 4: bot7_macro_bond (db_id=7, replaces FOMO Fred/Poseidon)
    #   Week 5: bot5_defensive  (db_id=4, replaces Apex Predator)
    #
    # ACTIVATION CHECKLIST:
    #   1. UPDATE kraken_heartbeat SET bot_id=<new>, bot_display_name=<new>
    #      WHERE id=<db_id>;
    #   2. Resume the bot (bots_state.paused = false via the dashboard/API).

    "bot2_spy_qqq": {
        # Momentum's account (canonical id spy_qqq_trend). Since 2 Nov 2026:
        # MOMO-V2, 50 S&P 500 names by 12-1 momentum with brakes on the book
        # itself; a forward-only paper experiment (kraken-bot/momo_strategy.py).
        "display_name":      "Momentum",
        "db_id":             1,
        "strategy_type":     "momo_v2",
        "strategy_label":    "MOMO-V2: 50 S&P 500 stocks by momentum, brakes on the book (paper experiment)",
        "ALPACA_API_KEY":    os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        "STARTING_CAPITAL":  100_000,
        "LOOP_SLEEP_SECONDS": 3600,
        "MAX_DEPLOYMENT":    1.00,
    },

    "forex_ai": {
        # 2 Nov 2026 (FLEET-V1-LIVE-SPEC.md section 5) the council and trading were
        # switched off, the bot kept as a read-only NAV monitor (its OANDA NAV is part
        # of fleet equity and the fleet high-water mark). 7 Nov 2026 (Markus): back on,
        # council v2 (news + strategy reasons) on the PRACTICE account until its forward
        # record starts 1 Jan 2027. Trading also needs forex_ai unpaused (Controls page).
        "display_name":      "Forex",
        "db_id":             None,
        "strategy_type":     "forex_ai_council",
        "strategy_label":    "Forex AI council (practice account)",
        "LOOP_SLEEP_SECONDS": 3600,
        "STARTING_CAPITAL":  100_000,
        "FOREX_MAX_GROSS":   FOREX_MAX_GROSS,
        # On again 7 Nov 2026 (Markus): council v2 trades the PRACTICE account to pre-test
        # before its forward record starts on 1 Jan 2027. Still needs forex_ai unpaused.
        "FOREX_COUNCIL_ENABLED": True,
        "FOREX_TRADING_ENABLED": True,
    },
}

BOT_ID = os.environ.get("BOT_ID", "oracle")
if BOT_ID not in BOT_PROFILES:
    print(f"ERROR: Unknown BOT_ID '{BOT_ID}'. Valid: {list(BOT_PROFILES.keys())}")
    sys.exit(1)

_profile = BOT_PROFILES[BOT_ID]
BOT_DISPLAY_NAME = _profile["display_name"]
BOT_DB_ID = _profile["db_id"]
BOT_STRATEGY_LABEL = _profile["strategy_label"]
BOT_STRATEGY_TYPE = _profile.get("strategy_type", "mean_reversion")
IS_SCALP_BOT          = BOT_STRATEGY_TYPE in ("momentum_wave", "liquidity_scout")
IS_SWING_BOT          = BOT_STRATEGY_TYPE in ("momentum_breakout", "trend_following", "flow_sentiment")
IS_MOMENTUM_SCALPER   = BOT_STRATEGY_TYPE == "momentum_scalper"

if PAPER_TRADING:
    print("\n" + "=" * 65)
    print(f"  PAPER TRADING MODE  —  {BOT_DISPLAY_NAME}")
    print(f"  Bot ID: {BOT_ID} (DB id={BOT_DB_ID}) | Strategy: {BOT_STRATEGY_LABEL}")
    print(f"  Simulated ${PAPER_STARTING_BALANCE:,.0f} account")
    print("=" * 65 + "\n")

else:
    KRAKEN_API_KEY    = os.environ.get("KRAKEN_API_KEY", "")
    KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

    if not KRAKEN_API_KEY or not KRAKEN_SECRET_KEY:
        print("\n" + "=" * 65)
        print(" STARTUP ERROR — Missing Kraken API credentials")
        print("=" * 65)
        print(" Live trading requires API keys.")
        print(" Add these in Replit (padlock icon → Secrets):")
        print("   KRAKEN_API_KEY    — Your Kraken Pro API key ID")
        print("   KRAKEN_SECRET_KEY — Your Kraken Pro secret key")
        print(" OR set PAPER_TRADING = True in config.py to run")
        print(" safely with a simulated $100K account first.")
        print("=" * 65 + "\n")
        sys.exit(1)

BLACKLIST = _profile.get("BLACKLIST", ["ALGO/USD", "OP/USD", "RENDER/USD"])

PAIR_SIZING_PENALIZED = {
    "ETH/USD":    0.50,
    "SOL/USD":    0.50,
    "W/USD":      0.50,
    "VET/USD":    0.50,
    "STX/USD":    0.50,
    "SUI/USD":    0.50,
}
PAIR_SIZING_PENALIZED_GRADUATE_WIN_RATE = 0.35
PAIR_SIZING_PENALIZED_GRADUATE_MIN_TRADES = 20

PAIR_SIZING_BOOSTED = {
    "TIA/USD":  1.25,
    "IMX/USD":  1.25,
    "SEI/USD":  1.25,
    "TAO/USD":  1.25,
    "ARB/USD":  1.25,
    "DYM/USD":  1.25,
}

SYMBOLS = _profile.get("SYMBOLS") or [
    "BTC/USD",
    "ETH/USD",
    "XRP/USD",
    "SOL/USD",
    "BNB/USD",
    "DOGE/USD",
    "ADA/USD",
    "TRX/USD",
    "AVAX/USD",
    "SHIB/USD",
    "LINK/USD",
    "TON/USD",
    "DOT/USD",
    "UNI/USD",
    "BCH/USD",
    "NEAR/USD",
    "LTC/USD",
    "ATOM/USD",
    "APT/USD",
    "ICP/USD",
    "FIL/USD",
    "ARB/USD",
    "OP/USD",
    "SUI/USD",
    "INJ/USD",
    "RENDER/USD",
    "STX/USD",
    "TAO/USD",
    "PEPE/USD",
    "POL/USD",
    "IMX/USD",
    "GRT/USD",
    "VET/USD",
    "HBAR/USD",
    "RUNE/USD",
    "SNX/USD",
    "ENS/USD",
    "WLD/USD",
    "JUP/USD",
    "TIA/USD",
    "ONDO/USD",
    "SEI/USD",
    "PYTH/USD",
    "W/USD",
    "DYM/USD",
    "STRK/USD",
    "ENA/USD",
    "AAVE/USD",
    "CRV/USD",
]


RSI_PERIOD       = 14
RSI_OVERSOLD     = _profile.get("RSI_OVERSOLD", 40)
RSI_OVERBOUGHT   = _profile.get("RSI_OVERBOUGHT", 60)

ZSCORE_WINDOW    = 20
ZSCORE_ENTRY     = _profile.get("ZSCORE_ENTRY", 1.0)
ZSCORE_EXIT      = 0.45

OHLCV_TIMEFRAME  = _profile.get("OHLCV_TIMEFRAME", "1h")
OHLCV_LIMIT      = _profile.get("OHLCV_LIMIT", 100)


CASH_RESERVE          = _profile.get("CASH_RESERVE", 0.20)
MAX_POSITION_FRACTION = _profile.get("MAX_POSITION_FRACTION", 0.10)
MAX_POSITIONS         = _profile.get("MAX_POSITIONS", 8)
RISK_FRACTION         = _profile.get("RISK_FRACTION", 0.01)
STOP_LOSS_PCT         = _profile.get("STOP_LOSS_PCT", 0.015)
ATR_STOP_MULTIPLIER   = _profile.get("ATR_STOP_MULTIPLIER", 1.5)
TRAIL_PCT             = 0.039

VPIN_ENTRY_BLOCK      = _profile.get("VPIN_ENTRY_BLOCK", 0.65)

try:
    from vpin_adaptive import get_dynamic_threshold as _get_dyn_vpin
    VPIN_ENTRY_BLOCK_DYNAMIC = True
except ImportError:
    VPIN_ENTRY_BLOCK_DYNAMIC = False

VPIN_ELEVATED_CAP     = 0.90
VOLUME_SURGE_RATIO    = 1.50

CONTRARIAN_RSI_THRESH = 28
CONTRARIAN_EQUITY_PCT = 0.015

VPIN_DECAY_AFTER_CYCLES = 4
VPIN_DECAY_RATE         = 0.10

DEEP_OVERSOLD_RSI     = 20
MICRO_LOT_EQUITY_PCT  = 0.01

BEAR_MAX_POSITIONS       = 5
BEAR_MAX_POSITION_FRACTION = 0.075

REGIME_COOLDOWN_CYCLES  = 3
REGIME_CONFIDENCE_GATE  = 0.67

MIN_POSITION_USD      = 500.0
MIN_NET_PROFIT_PCT    = 0.0104

STALE_EXIT_HOURS      = 24
STALE_DEAD_ZONE_PCT   = 0.005


EQUITY_REFRESH_INTERVAL = 3600
LOOP_SLEEP_SECONDS      = _profile.get("LOOP_SLEEP_SECONDS", 60)
RESTART_SLEEP_SECONDS   = 30

SCALP_TP_PCT             = _profile.get("SCALP_TP_PCT", 0.010)
SCALP_SL_PCT             = _profile.get("SCALP_SL_PCT", 0.005)
SCALP_STAGNANCY_MINUTES  = _profile.get("SCALP_STAGNANCY_MINUTES", 15)
SCALP_STAGNANCY_DEADZONE = _profile.get("SCALP_STAGNANCY_DEADZONE", 0.002)
LATENCY_TAX_BPS          = _profile.get("LATENCY_TAX_BPS", 0)
LATENCY_TAX_PCT          = LATENCY_TAX_BPS / 10000.0
SCALP_FEE_RATE           = _profile.get("SCALP_FEE_RATE", PAPER_FEE_PCT)

EMA_FAST         = _profile.get("EMA_FAST", 8)
EMA_MID          = _profile.get("EMA_MID", 13)
EMA_SLOW         = _profile.get("EMA_SLOW", 21)
RVOL_THRESHOLD   = _profile.get("RVOL_THRESHOLD", 1.5)
RVOL_PERIOD      = _profile.get("RVOL_PERIOD", 20)

KELTNER_EMA_PERIOD  = _profile.get("KELTNER_EMA_PERIOD", 20)
KELTNER_ATR_MULT    = _profile.get("KELTNER_ATR_MULT", 1.5)
VWAP_PROXIMITY_PCT  = _profile.get("VWAP_PROXIMITY_PCT", 0.002)

MIN_CONVICTION            = _profile.get("MIN_CONVICTION", 0.50)
STAGNANCY_COOLDOWN_MINUTES = _profile.get("STAGNANCY_COOLDOWN_MINUTES", 0)
MAX_NEW_ENTRIES_PER_CYCLE  = _profile.get("MAX_NEW_ENTRIES_PER_CYCLE", 99)


CB_PRICE_DROP_PCT = 0.10
CB_WINDOW_MINUTES = 5
CB_PAUSE_HOURS    = 2

LOSS_STREAK_LIMIT          = _profile.get("LOSS_STREAK_LIMIT", 10)
LOSS_STREAK_COOLDOWN_HOURS = _profile.get("LOSS_STREAK_COOLDOWN_HOURS", 8)

SWING_TP_ATR_MULT         = _profile.get("SWING_TP_ATR_MULT", 3.0)
SWING_SL_ATR_MULT         = _profile.get("SWING_SL_ATR_MULT", 1.5)
SWING_TRAIL_TRIGGER_ATR   = _profile.get("SWING_TRAIL_TRIGGER_ATR", 1.0)
SWING_TRAIL_ATR_MULT      = _profile.get("SWING_TRAIL_ATR_MULT", 1.5)
SWING_MIN_HOLD_HOURS      = _profile.get("SWING_MIN_HOLD_HOURS", 4)
SWING_MAX_HOLD_HOURS      = _profile.get("SWING_MAX_HOLD_HOURS", 72)

MOMENTUM_LOOKBACK_CANDLES = _profile.get("MOMENTUM_LOOKBACK_CANDLES", 4)
MOMENTUM_ATR_THRESHOLD    = _profile.get("MOMENTUM_ATR_THRESHOLD", 1.5)
VOLUME_MA_PERIOD          = _profile.get("VOLUME_MA_PERIOD", 20)

TREND_EMA_FAST            = _profile.get("TREND_EMA_FAST", 30)
TREND_EMA_SLOW            = _profile.get("TREND_EMA_SLOW", 75)
TREND_PULLBACK_ATR_MULT   = _profile.get("TREND_PULLBACK_ATR_MULT", 0.5)

FLOW_IMBALANCE_LONG_THRESHOLD  = _profile.get("FLOW_IMBALANCE_LONG_THRESHOLD", 0.65)
FLOW_IMBALANCE_SHORT_THRESHOLD = _profile.get("FLOW_IMBALANCE_SHORT_THRESHOLD", 0.35)
FLOW_VPIN_MAX                  = _profile.get("FLOW_VPIN_MAX", 0.75)
FLOW_VPIN_SPIKE_BLOCK          = _profile.get("FLOW_VPIN_SPIKE_BLOCK", 0.85)
FLOW_RSI_MIN                   = _profile.get("FLOW_RSI_MIN", 40)
FLOW_RSI_MAX                   = _profile.get("FLOW_RSI_MAX", 60)
FLOW_VOLUME_MA_PERIOD          = _profile.get("FLOW_VOLUME_MA_PERIOD", 20)
FLOW_VOLUME_MULT               = _profile.get("FLOW_VOLUME_MULT", 1.5)

SYMBOL_WINRATE_LOOKBACK           = _profile.get("SYMBOL_WINRATE_LOOKBACK", 15)
SYMBOL_WINRATE_PENALTY_THRESHOLD  = _profile.get("SYMBOL_WINRATE_PENALTY_THRESHOLD", 0.35)
SYMBOL_WINRATE_RECOVERY_THRESHOLD = _profile.get("SYMBOL_WINRATE_RECOVERY_THRESHOLD", 0.40)
SYMBOL_WINRATE_PENALTY_FACTOR     = _profile.get("SYMBOL_WINRATE_PENALTY_FACTOR", 0.70)


CALYPSO_TIER1_MAX = _profile.get("CALYPSO_TIER1_MAX", 0.05)
CALYPSO_TIER2_MAX = _profile.get("CALYPSO_TIER2_MAX", 0.05)
CALYPSO_TIER3_MAX = _profile.get("CALYPSO_TIER3_MAX", 0.05)

APEX_TP_ATR_MULT      = _profile.get("APEX_TP_ATR_MULT", 3.0)
APEX_EMA_FAST         = _profile.get("APEX_EMA_FAST", 20)
APEX_EMA_SLOW         = _profile.get("APEX_EMA_SLOW", 50)
APEX_VOLUME_MULT      = _profile.get("APEX_VOLUME_MULT", 0.75)
APEX_VPIN_BLOCK       = _profile.get("APEX_VPIN_BLOCK", 0.80)
APEX_TREND_TIMEFRAME  = _profile.get("APEX_TREND_TIMEFRAME", "4h")


STATUS_FILE           = f"kraken-bot/{BOT_ID}_status.json"
LIVE_STATE_FILE       = f"kraken-bot/{BOT_ID}_live_state.json"
PAPER_PORTFOLIO_FILE  = f"kraken-bot/{BOT_ID}_paper_portfolio.json"
CONTROL_FILE          = f"kraken-bot/{BOT_ID}_control.json"
MARKET_CACHE_FILE     = "kraken-bot/_market_cache.json"
IS_PRIMARY_FETCHER    = (BOT_ID == "davy-jones")
MARKET_CACHE_TTL      = 45
