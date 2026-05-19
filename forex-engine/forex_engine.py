"""
forex_engine.py — The Navigator: Groq LLM Forex Investment Engine (Bot #6)
===========================================================================
4-Hour (H4) cycle — exit/SL/TP management runs every cycle.
Groq LLM makes new ENTRY decisions twice daily: 08:00 UTC + 20:00 UTC.
Holds positions for days-to-weeks (2–14 day horizon).

Strategy:
  1. Every 4H cycle: check open positions for SL/TP/time-stop hits
  2. 08:00 UTC / 20:00 UTC only: Groq investment analysis
     a. Fetch forex pair prices + macro indicators (DXY, VIX, Gold, SPY)
     b. Groq Llama-3.3-70B analyses context and returns structured JSON
     c. Validator sanity-checks Groq output (conviction ≥ 0.6, R:R ≥ 1.0)
     d. Execute validated entries via paper engine
     e. Close positions early if Groq recommends
  3. Capital Vault → Friday 4PM EST sweep
"""

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_ENGINE_DIR, "..")
_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")

if _TRADING_PLATFORM not in sys.path:
    sys.path.append(_TRADING_PLATFORM)
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from forex_config import (
    PAPER_TRADING, PAPER_STARTING_BALANCE, PAPER_SPREAD_COST_PCT,
    PAIRS, PAIR_LABELS, PAIR_DIRECTIONS, JPY_PAIRS, USD_BASE_PAIRS, PIP_SIZE,
    CROSS_QUOTE_USD,
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT, ATR_PERIOD, ATR_MIN_PIPS,
    SL_ATR_MULT, TP_ATR_MULT, TRAIL_ATR_MULT, BREAKEVEN_ATR_MULT,
    MAX_RISK_PER_TRADE_PCT,
    MAX_OPEN_POSITIONS, MAX_POSITION_SIZE_PCT,
    BOT_ID, BOT_DISPLAY_NAME, BOT_DB_ID, BOT_STRATEGY_LABEL,
    CONTROL_FILE, LIVE_STATE_FILE, VAULT_SWEEP_PCT,
    CB_DRAWDOWN_THRESHOLD, CB_COOLDOWN_HOURS,
    get_quote_to_usd,
)
from indicators import calculate_atr, calculate_rsi, calculate_ema, fetch_h4_candles
from paper_engine import (
    get_paper_equity, get_paper_positions, get_paper_portfolio_summary,
    paper_open_position, paper_close_position, get_available_capital,
    perform_vault_sweep, update_position_fields,
)
import forex_nav_db as _db
import journal as _journal

_cycle_lock = threading.Lock()

_state = {
    "status": "idle",
    "cycle_count": 0,
    "usd_bias": "NEUTRAL",
    "news_blackout": False,
    "last_scan": None,
    "last_scan_results": [],
    "error": None,
    "paused": False,
    "circuit_breaker_active": False,
    "circuit_breaker_reason": None,
    "circuit_breaker_tripped_at": None,
    "_cb_session_hwm": 0.0,
}

_latest_prices: dict[str, float] = {}

_USD_BIAS_CACHE: dict = {"bias": "NEUTRAL", "thesis": "", "cached_at": 0}
_USD_BIAS_CACHE_TTL = 4 * 3600

# ── Groq investor state ────────────────────────────────────────────────────────
_last_groq_cycle: Optional[datetime] = None

# Maps Groq's "EUR/USD" display format → internal yfinance ticker
_GROQ_PAIR_MAP: dict[str, str] = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "CAD=X",
    "USD/CHF": "CHF=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "AUD/JPY": "AUDJPY=X",
}
# Reverse: internal ticker → "EUR/USD" display format (for formatting open positions)
_GROQ_PAIR_REVERSE: dict[str, str] = {v: k for k, v in _GROQ_PAIR_MAP.items()}

# Groq investment cycles fire at 08:00 and 20:00 UTC (window = first 15 min)
_GROQ_CYCLE_HOURS = (8, 20)
_GROQ_CYCLE_WINDOW_MINUTES = 15


def is_bot_paused() -> bool:
    # Prefer bots_state table; fall back to navigator_control.json
    try:
        _tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
        if _tp not in sys.path:
            sys.path.append(_tp)
        from core.bot_state import is_paused as _bs_is_paused
        return _bs_is_paused("forex_gump")
    except Exception:
        pass
    import pathlib
    ctrl = pathlib.Path(CONTROL_FILE)
    if not ctrl.exists():
        return False
    try:
        return bool(json.loads(ctrl.read_text()).get("bot_paused", False))
    except Exception:
        return False


def _check_news_blackout() -> bool:
    try:
        import requests
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            logger.warning("Forex | News calendar API returned non-200 — proceeding without blackout")
            return False

        events = resp.json()
        now = datetime.now(tz=timezone.utc)
        blackout_window = timedelta(hours=4)

        high_impact_currencies = {"USD", "EUR", "GBP", "JPY", "AUD", "CHF"}

        for event in events:
            impact = event.get("impact", "").lower()
            if impact not in ("high", "holiday"):
                continue

            currency = event.get("country", "").upper()
            if currency not in high_impact_currencies:
                continue

            event_date = event.get("date", "")
            try:
                event_dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
                if now <= event_dt <= now + blackout_window:
                    logger.warning(
                        f"Forex | NEWS BLACKOUT — High-impact {currency} event "
                        f"'{event.get('title', '?')}' in {(event_dt - now).total_seconds() / 3600:.1f}h"
                    )
                    return True
            except Exception:
                continue

        return False

    except Exception as exc:
        logger.warning(f"Forex | News blackout check failed: {exc} — proceeding (no hard block)")
        return False


def _gemini_compass_fallback(rag_block: str = "") -> tuple[str, str]:
    """
    Fallback USD-bias call routed through the Replit AI Integration proxy
    (AI_INTEGRATIONS_GEMINI_BASE_URL / AI_INTEGRATIONS_GEMINI_API_KEY).
    No longer touches GOOGLE_GEMINI_API_KEY or the direct Google API.
    """
    from analysis.groq_client import call_groq

    system_prompt = (
        "You are a Forex Macro Compass. Your ONLY job is to determine the directional bias "
        "for the US Dollar based on central bank policy, interest rate expectations, and "
        "macroeconomic conditions.\n\n"
        "You must output EXACTLY one of three values in a JSON object:\n"
        '{"bias": "USD_BULLISH", "thesis": "brief 1-sentence reason"}\n'
        '{"bias": "USD_BEARISH", "thesis": "brief 1-sentence reason"}\n'
        '{"bias": "NEUTRAL", "thesis": "brief 1-sentence reason"}\n\n'
        "Do NOT output anything else."
    )

    user_prompt = (
        f"Current date: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "Based on current central bank policy stances (Fed, ECB, BOJ, BOE, RBA, SNB), "
        "recent economic data releases, and interest rate expectations, "
        "what is the directional bias for the US Dollar?\n\n"
        "Consider: Fed rate path, inflation trends, employment data, "
        "relative growth differentials, and risk sentiment.\n"
        f"{rag_block}"
    )

    raw = call_groq(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=8192,
        call_type="forex_compass_fallback",
    )
    result = json.loads(raw)

    bias = result.get("bias", "NEUTRAL").upper()
    thesis = result.get("thesis", "")
    if bias not in ("USD_BULLISH", "USD_BEARISH", "NEUTRAL"):
        bias = "NEUTRAL"
        thesis = f"Gemini returned invalid bias '{result.get('bias')}' — defaulting to NEUTRAL"

    return bias, thesis


def _get_usd_bias() -> tuple[str, str]:
    now = time.time()
    if now - _USD_BIAS_CACHE["cached_at"] < _USD_BIAS_CACHE_TTL and _USD_BIAS_CACHE["bias"]:
        logger.info(f"Forex | Using cached USD bias: {_USD_BIAS_CACHE['bias']}")
        return _USD_BIAS_CACHE["bias"], _USD_BIAS_CACHE["thesis"]

    rag_block = ""
    try:
        from analysis.groq_budget import budget as groq_budget
        from analysis.groq_client import call_groq

        if not groq_budget.can_call_regime():
            logger.info("Forex | Groq budget throttled — trying Gemini fallback")
            try:
                bias, thesis = _gemini_compass_fallback()
                _USD_BIAS_CACHE["bias"] = bias
                _USD_BIAS_CACHE["thesis"] = thesis
                _USD_BIAS_CACHE["cached_at"] = time.time()
                logger.info(f"Forex | Gemini fallback USD bias: {bias} — {thesis}")
                return bias, thesis
            except Exception as gem_exc:
                logger.warning(f"Forex | Gemini fallback failed: {gem_exc}")
                cached_bias = _USD_BIAS_CACHE["bias"] or "NEUTRAL"
                cached_thesis = _USD_BIAS_CACHE["thesis"] or "Budget throttled — using last known bias"
                logger.info(f"Forex | Using cached bias: {cached_bias}")
                return cached_bias, cached_thesis

        losing_trades = _journal.get_recent_losers(limit=5) or _db.load_losing_trades(limit=5)
        if losing_trades:
            rag_block = "\n\nRECENT LOSING TRADES (learn from these mistakes):\n"
            for lt in losing_trades:
                rag_block += (
                    f"  - {lt.get('pair')} {lt.get('direction')}: {lt.get('pnl_pips', 0):+.1f} pips | "
                    f"Thesis: {lt.get('llm_thesis', 'N/A')}\n"
                )

        system_prompt = (
            "You are a Forex Macro Compass. Your ONLY job is to determine the directional bias "
            "for the US Dollar based on central bank policy, interest rate expectations, and "
            "macroeconomic conditions.\n\n"
            "You must output EXACTLY one of three values in a JSON object:\n"
            '{"bias": "USD_BULLISH", "thesis": "brief 1-sentence reason"}\n'
            '{"bias": "USD_BEARISH", "thesis": "brief 1-sentence reason"}\n'
            '{"bias": "NEUTRAL", "thesis": "brief 1-sentence reason"}\n\n'
            "Do NOT output anything else. No calculations, no trade recommendations, no numbers.\n"
            "Just the directional USD bias based on macro fundamentals."
        )

        user_prompt = (
            f"Current date: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            "Based on current central bank policy stances (Fed, ECB, BOJ, BOE, RBA, SNB), "
            "recent economic data releases, and interest rate expectations, "
            "what is the directional bias for the US Dollar?\n\n"
            "Consider: Fed rate path, inflation trends, employment data, "
            "relative growth differentials, and risk sentiment.\n"
            f"{rag_block}"
        )

        raw = call_groq(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=256,
            call_type="forex_compass",
        )

        groq_budget.record_regime_call()

        result = json.loads(raw)
        bias = result.get("bias", "NEUTRAL").upper()
        thesis = result.get("thesis", "")

        if bias not in ("USD_BULLISH", "USD_BEARISH", "NEUTRAL"):
            bias = "NEUTRAL"
            thesis = f"LLM returned invalid bias '{result.get('bias')}' — defaulting to NEUTRAL"

        _USD_BIAS_CACHE["bias"] = bias
        _USD_BIAS_CACHE["thesis"] = thesis
        _USD_BIAS_CACHE["cached_at"] = now

        logger.info(f"Forex | Groq USD bias: {bias} — {thesis}")
        return bias, thesis

    except Exception as exc:
        logger.warning(f"Forex | Groq compass failed: {exc} — trying Gemini fallback")
        try:
            bias, thesis = _gemini_compass_fallback(rag_block)
            _USD_BIAS_CACHE["bias"] = bias
            _USD_BIAS_CACHE["thesis"] = thesis
            _USD_BIAS_CACHE["cached_at"] = time.time()
            logger.info(f"Forex | Gemini fallback USD bias: {bias} — {thesis}")
            return bias, thesis
        except Exception as gem_exc:
            logger.warning(f"Forex | Gemini fallback also failed: {gem_exc}")
            cached_bias = _USD_BIAS_CACHE["bias"] or "NEUTRAL"
            cached_thesis = _USD_BIAS_CACHE["thesis"] or f"Both LLMs unavailable — using NEUTRAL"
            return cached_bias, cached_thesis


def _filter_pairs_by_bias(bias: str) -> dict[str, str]:
    allowed = {}
    for pair in PAIRS:
        direction_type = PAIR_DIRECTIONS.get(pair, "cross")

        if direction_type == "cross":
            allowed[pair] = "both"
        elif bias == "USD_BULLISH":
            if direction_type == "counter_usd":
                allowed[pair] = "short"
            else:
                allowed[pair] = "long"
        elif bias == "USD_BEARISH":
            if direction_type == "counter_usd":
                allowed[pair] = "long"
            else:
                allowed[pair] = "short"
        else:
            allowed[pair] = "both"

    return allowed


def _calculate_units(equity: float, entry_price: float, sl_distance: float, pair: str) -> float:
    from forex_config import get_quote_to_usd
    risk_amount = equity * MAX_RISK_PER_TRADE_PCT

    pip_size = PIP_SIZE.get(pair, 0.0001)
    sl_pips = sl_distance / pip_size

    if sl_pips <= 0:
        return 0

    conv = get_quote_to_usd(pair, entry_price, _latest_prices)
    if conv is None:
        return 0
    pip_value_per_unit = pip_size * conv

    if pip_value_per_unit <= 0:
        return 0

    units = risk_amount / (sl_pips * pip_value_per_unit)

    max_size = equity * MAX_POSITION_SIZE_PCT
    unit_value_usd = entry_price * conv if entry_price > 0 else 1
    max_units = max_size / unit_value_usd if unit_value_usd > 0 else 0
    units = min(units, max_units)

    return max(0, round(units))


_CROSS_REF_SYMBOLS = sorted(set(ref for ref, _ in CROSS_QUOTE_USD.values()))


def _prefetch_reference_prices():
    import time as _time
    for ref_sym in _CROSS_REF_SYMBOLS:
        if ref_sym in _latest_prices:
            continue
        for attempt in range(2):
            try:
                candles = fetch_h4_candles(ref_sym, count=5)
                if candles is not None and not candles.empty:
                    _latest_prices[ref_sym] = float(candles.iloc[-1]["Close"])
                    logger.debug(f"Forex | Pre-fetched ref price {ref_sym} = {_latest_prices[ref_sym]:.5f}")
                    break
                if attempt == 0:
                    logger.debug(f"Forex | ref price {ref_sym} returned empty on attempt 1 — retrying")
                    _time.sleep(1.5)
            except Exception as exc:
                if attempt == 0:
                    logger.debug(f"Forex | ref price {ref_sym} attempt 1 failed: {exc} — retrying")
                    _time.sleep(1.5)
                else:
                    logger.warning(f"Forex | Failed to pre-fetch ref price {ref_sym} after 2 attempts: {exc}")


# ── HARD PAIR WHITELIST ──────────────────────────────────────────────────────
# This frozenset is the SINGLE SOURCE OF TRUTH for which pairs Navigator is
# permitted to hold or enter.  It is intentionally NOT derived from forex_config.PAIRS
# so that editing the config cannot silently expand the universe.
# To add a pair you must edit BOTH this constant AND forex_config.PAIRS.
# Mandate: 10 pairs — 5 USD majors + USD/CHF + 4 liquid JPY/GBP crosses
# ────────────────────────────────────────────────────────────────────────────
_PERMITTED_PAIRS: frozenset[str] = frozenset({
    "EURUSD=X",   # EUR/USD
    "GBPUSD=X",   # GBP/USD
    "JPY=X",      # USD/JPY
    "AUDUSD=X",   # AUD/USD
    "CAD=X",      # USD/CAD
    "CHF=X",      # USD/CHF
    "EURGBP=X",   # EUR/GBP
    "AUDJPY=X",   # AUD/JPY
    "GBPJPY=X",   # GBP/JPY
    "EURJPY=X",   # EUR/JPY
})

logger.info(
    f"Navigator | Hard pair whitelist active: "
    + ", ".join(sorted(_PERMITTED_PAIRS))
)

def _check_open_positions():
    positions = get_paper_positions()
    if not positions:
        return

    for pair, pos in list(positions.items()):
        if pair not in _PERMITTED_PAIRS:
            label = PAIR_LABELS.get(pair, pair)
            logger.warning(f"Forex | NON-PERMITTED pair {label} — closing immediately")
            try:
                candles = fetch_h4_candles(pair, count=5)
                if not candles.empty:
                    cp = float(candles.iloc[-1]["Close"])
                else:
                    cp = pos["entry_price"]
                result = paper_close_position(pair, cp, "non_permitted_pair", latest_prices=_latest_prices)
                if result:
                    try:
                        _journal.log_trade_close(
                            pair=label, exit_price=cp,
                            pnl_pips=result.get("pnl_pips", 0), pnl_usd=result.get("pnl_usd", 0),
                            final_trailing_sl=pos.get("trailing_sl"),
                            reason="non_permitted_pair",
                        )
                    except Exception:
                        pass
                    try:
                        _db.record_trade(
                            pair=label,
                            direction=pos["direction"],
                            entry_price=pos["entry_price"],
                            exit_price=cp,
                            pnl_usd=result.get("pnl_usd", 0),
                            pnl_pips=result.get("pnl_pips", 0),
                            reason="non_permitted_pair",
                        )
                    except Exception:
                        pass
                    logger.info(f"Forex | Closed non-permitted {label}: PnL ${result.get('pnl_usd', 0):+.2f}")
            except Exception as exc:
                logger.error(f"Forex | Failed to close non-permitted {label}: {exc}")
            continue

    for pair, pos in list(positions.items()):
        if pair not in _PERMITTED_PAIRS:
            continue
        try:
            direction = pos["direction"]
            entry = pos["entry_price"]

            field_updates = {}
            if not pos.get("original_sl"):
                field_updates["original_sl"] = pos["sl_price"]
                pos["original_sl"] = pos["sl_price"]
            if not pos.get("trailing_sl"):
                field_updates["trailing_sl"] = pos["sl_price"]
                pos["trailing_sl"] = pos["sl_price"]
            if direction == "long" and not pos.get("highest_price"):
                field_updates["highest_price"] = entry
                pos["highest_price"] = entry
            if direction == "short" and not pos.get("lowest_price"):
                field_updates["lowest_price"] = entry
                pos["lowest_price"] = entry

            if field_updates:
                update_position_fields(pair, field_updates)
                field_updates = {}

            candles = fetch_h4_candles(pair, count=max(ATR_PERIOD + 5, 20))
            if candles.empty:
                continue

            current_price = float(candles.iloc[-1]["Close"])
            _latest_prices[pair] = current_price

            highs = candles["High"].tolist()
            lows = candles["Low"].tolist()
            closes = candles["Close"].tolist()
            current_atr = calculate_atr(highs, lows, closes, period=ATR_PERIOD)

            if current_atr > 0:
                candle_high = float(candles.iloc[-1]["High"])
                candle_low = float(candles.iloc[-1]["Low"])
                if direction == "long":
                    if candle_high > pos.get("highest_price", entry):
                        pos["highest_price"] = candle_high
                        field_updates["highest_price"] = candle_high

                    pip_size = PIP_SIZE.get(pair, 0.0001)
                    spread_offset = pip_size * 2
                    if (current_price - entry) >= BREAKEVEN_ATR_MULT * current_atr:
                        be_sl = entry + spread_offset
                        if be_sl > pos["trailing_sl"]:
                            pos["trailing_sl"] = round(be_sl, 5)
                            field_updates["trailing_sl"] = pos["trailing_sl"]
                            logger.info(f"Forex | BREAKEVEN lock on LONG {PAIR_LABELS.get(pair, pair)} — trailing SL → {pos['trailing_sl']:.5f}")

                    new_trail = pos["highest_price"] - (TRAIL_ATR_MULT * current_atr)
                    if new_trail > pos["trailing_sl"]:
                        pos["trailing_sl"] = round(new_trail, 5)
                        field_updates["trailing_sl"] = pos["trailing_sl"]
                        logger.info(f"Forex | TRAIL SL ratcheted on LONG {PAIR_LABELS.get(pair, pair)} — trailing SL → {pos['trailing_sl']:.5f}")

                    _GAIN_LOCK_PAIRS = {"EURUSD=X"}
                    if pair in _GAIN_LOCK_PAIRS:
                        unrealized_gain = current_price - entry
                        if unrealized_gain > 0:
                            gain_lock_sl = round(entry + (unrealized_gain * 0.50), 5)
                            if gain_lock_sl > pos["trailing_sl"]:
                                pos["trailing_sl"] = gain_lock_sl
                                field_updates["trailing_sl"] = pos["trailing_sl"]
                                logger.info(f"Forex | {PAIR_LABELS.get(pair, pair)} 50% gain-lock ratchet on LONG — trailing SL → {pos['trailing_sl']:.5f} (locks 50% of +{unrealized_gain:.5f})")

                    _IMMEDIATE_BE_PAIRS: frozenset[str] = frozenset()
                    if pair in _IMMEDIATE_BE_PAIRS:
                        pip_size_be = PIP_SIZE.get(pair, 0.01)
                        be_price = round(entry + (pip_size_be * 2), 5)
                        if current_price > entry and be_price > pos["trailing_sl"]:
                            pos["trailing_sl"] = be_price
                            field_updates["trailing_sl"] = pos["trailing_sl"]
                            logger.warning(f"Forex | {PAIR_LABELS.get(pair, pair)} IMMEDIATE BREAK-EVEN on LONG — trailing SL → {pos['trailing_sl']:.5f} (protecting unrealized gain)")

                else:
                    if candle_low < pos.get("lowest_price", entry):
                        pos["lowest_price"] = candle_low
                        field_updates["lowest_price"] = candle_low

                    pip_size = PIP_SIZE.get(pair, 0.0001)
                    spread_offset = pip_size * 2
                    if (entry - current_price) >= BREAKEVEN_ATR_MULT * current_atr:
                        be_sl = entry - spread_offset
                        if be_sl < pos["trailing_sl"]:
                            pos["trailing_sl"] = round(be_sl, 5)
                            field_updates["trailing_sl"] = pos["trailing_sl"]
                            logger.info(f"Forex | BREAKEVEN lock on SHORT {PAIR_LABELS.get(pair, pair)} — trailing SL → {pos['trailing_sl']:.5f}")

                    new_trail = pos["lowest_price"] + (TRAIL_ATR_MULT * current_atr)
                    if new_trail < pos["trailing_sl"]:
                        pos["trailing_sl"] = round(new_trail, 5)
                        field_updates["trailing_sl"] = pos["trailing_sl"]
                        logger.info(f"Forex | TRAIL SL ratcheted on SHORT {PAIR_LABELS.get(pair, pair)} — trailing SL → {pos['trailing_sl']:.5f}")

                    _GAIN_LOCK_PAIRS_SHORT = {"EURUSD=X"}
                    if pair in _GAIN_LOCK_PAIRS_SHORT:
                        unrealized_gain = entry - current_price
                        if unrealized_gain > 0:
                            gain_lock_sl = round(entry - (unrealized_gain * 0.50), 5)
                            if gain_lock_sl < pos["trailing_sl"]:
                                pos["trailing_sl"] = gain_lock_sl
                                field_updates["trailing_sl"] = pos["trailing_sl"]
                                logger.info(f"Forex | {PAIR_LABELS.get(pair, pair)} 50% gain-lock ratchet on SHORT — trailing SL → {pos['trailing_sl']:.5f} (locks 50% of +{unrealized_gain:.5f})")

                    _IMMEDIATE_BE_PAIRS_SHORT: frozenset[str] = frozenset()
                    if pair in _IMMEDIATE_BE_PAIRS_SHORT:
                        pip_size_be = PIP_SIZE.get(pair, 0.01)
                        be_price = round(entry - (pip_size_be * 2), 5)
                        if current_price < entry and be_price < pos["trailing_sl"]:
                            pos["trailing_sl"] = be_price
                            field_updates["trailing_sl"] = pos["trailing_sl"]
                            logger.warning(f"Forex | {PAIR_LABELS.get(pair, pair)} IMMEDIATE BREAK-EVEN on SHORT — trailing SL → {pos['trailing_sl']:.5f} (protecting unrealized gain)")

                field_updates["sl_price"] = pos["trailing_sl"]
                pos["sl_price"] = pos["trailing_sl"]

            if field_updates:
                update_position_fields(pair, field_updates)

            sl = pos["sl_price"]
            tp = pos["tp_price"]

            def _close_and_journal(p, cp, reason):
                result = paper_close_position(p, cp, reason, latest_prices=_latest_prices)
                if result:
                    final_tsl = pos.get("trailing_sl")
                    result["final_trailing_sl"] = final_tsl
                    try:
                        _journal.log_trade_close(
                            pair=PAIR_LABELS.get(p, p), exit_price=cp,
                            pnl_pips=result.get("pnl_pips", 0), pnl_usd=result.get("pnl_usd", 0),
                            final_trailing_sl=final_tsl,
                        )
                    except Exception:
                        pass
                    _pnl_usd = result.get("pnl_usd", 0)
                    if _pnl_usd > 0:
                        try:
                            import sys as _sys, os as _os
                            _tp_root = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "trading-platform")
                            if _tp_root not in _sys.path:
                                _sys.path.insert(0, _tp_root)
                            from notifications.alert_manager import enqueue_profitable_trade
                            enqueue_profitable_trade(
                                bot_name="The Navigator (Forex)",
                                symbol=PAIR_LABELS.get(p, p),
                                pnl_pct=result.get("pnl_pct", 0),
                                pnl_usd=_pnl_usd,
                                reason=reason,
                            )
                        except Exception:
                            pass
                return result

            # ── Groq time-stop: close if max_hold_days exceeded ───────────────
            groq_hold_days = pos.get("groq_max_hold_days")
            if groq_hold_days:
                entry_time_str = pos.get("entry_time", "")
                if entry_time_str:
                    try:
                        et = datetime.fromisoformat(entry_time_str)
                        hours_held = (datetime.now(tz=timezone.utc) - et).total_seconds() / 3600.0
                        groq_hold_hours = float(groq_hold_days) * 24.0
                        if hours_held >= groq_hold_hours:
                            label = PAIR_LABELS.get(pair, pair)
                            logger.info(
                                f"Navigator | TIME STOP: {label} held {hours_held:.0f}h "
                                f">= {groq_hold_hours:.0f}h ({groq_hold_days}d max) — closing"
                            )
                            _close_and_journal(pair, current_price, "groq_time_stop")
                            continue
                    except Exception as _ts_exc:
                        logger.debug(f"Navigator | Time-stop check failed for {pair}: {_ts_exc}")

            if direction == "long":
                if current_price <= sl:
                    reason = "trailing_stop" if sl > pos.get("original_sl", sl) else "stop_loss"
                    _close_and_journal(pair, current_price, reason)
                    logger.info(f"Forex | {reason.upper()} HIT on LONG {pair} @ {current_price:.5f}")
                elif current_price >= tp:
                    _close_and_journal(pair, current_price, "take_profit")
                    logger.info(f"Forex | TP HIT on LONG {pair} @ {current_price:.5f}")
            else:
                if current_price >= sl:
                    reason = "trailing_stop" if sl < pos.get("original_sl", sl) else "stop_loss"
                    _close_and_journal(pair, current_price, reason)
                    logger.info(f"Forex | {reason.upper()} HIT on SHORT {pair} @ {current_price:.5f}")
                elif current_price <= tp:
                    _close_and_journal(pair, current_price, "take_profit")
                    logger.info(f"Forex | TP HIT on SHORT {pair} @ {current_price:.5f}")

        except Exception as exc:
            logger.warning(f"Forex | Position check failed for {pair}: {exc}")


def _check_vault_sweep():
    now = datetime.now(tz=timezone.utc)
    eastern_offset = timedelta(hours=-4)
    eastern_now = now + eastern_offset

    if eastern_now.weekday() != 4:
        return
    if eastern_now.hour < 16 or eastern_now.hour > 17:
        return

    equity = get_paper_equity(current_prices=_latest_prices)
    result = perform_vault_sweep(equity)
    if result:
        logger.info(f"Forex | Friday vault sweep: ${result:,.2f}")
        try:
            from paper_engine import _load_portfolio
            p = _load_portfolio()
            _journal.log_vault_sweep(
                sweep_amount=result,
                equity_at_sweep=equity,
                hwm_at_sweep=p.get("hwm_usd", equity),
                vault_total=p.get("vault_total_usd", 0),
            )
        except Exception:
            pass


# ── Groq investor helpers ──────────────────────────────────────────────────────

def _should_run_groq_cycle() -> bool:
    """
    Returns True if we are inside the 08:00–08:15 UTC or 20:00–20:15 UTC window
    AND we have not already run a Groq cycle in the last 60 minutes.
    """
    global _last_groq_cycle
    now = datetime.now(timezone.utc)
    if now.hour not in _GROQ_CYCLE_HOURS or now.minute >= _GROQ_CYCLE_WINDOW_MINUTES:
        return False
    if _last_groq_cycle is not None:
        elapsed = (now - _last_groq_cycle).total_seconds()
        if elapsed < 3600:
            return False
    _last_groq_cycle = now
    logger.info(f"Navigator | Groq investment cycle triggered at {now.strftime('%H:%M UTC')}")
    return True


def _format_open_positions_for_groq(positions: dict) -> list[dict]:
    """
    Converts the internal positions dict (keyed by "EURUSD=X") into a list
    of dicts using the "EUR/USD" display format that Groq understands.
    """
    result = []
    now = datetime.now(timezone.utc)
    for ticker, pos in positions.items():
        display_pair = _GROQ_PAIR_REVERSE.get(ticker, ticker)
        entry_time_str = pos.get("entry_time", "")
        hours_held = 0.0
        if entry_time_str:
            try:
                et = datetime.fromisoformat(entry_time_str)
                hours_held = (now - et).total_seconds() / 3600.0
            except Exception:
                pass
        current_price = _latest_prices.get(ticker, pos.get("entry_price", 0))
        entry_price   = pos.get("entry_price", 0)
        size_usd      = pos.get("size_usd", 0)
        direction     = pos.get("direction", "long")
        sign = 1 if direction == "long" else -1
        unrealised = 0.0
        if entry_price > 0:
            pct_move = (current_price - entry_price) / entry_price
            unrealised = size_usd * pct_move * sign
        result.append({
            "pair":               display_pair,
            "direction":          direction,
            "entry_price":        round(entry_price, 5),
            "current_price":      round(current_price, 5),
            "unrealised_pnl_usd": round(unrealised, 2),
            "hours_held":         round(hours_held, 1),
            "size_usd":           round(size_usd, 2),
        })
    return result


def _open_groq_position(entry: dict, equity: float, available: float) -> bool:
    """
    Translates a validated Groq entry decision into a paper_open_position() call.

    entry keys: pair (EUR/USD), direction, conviction, position_size_pct,
                stop_loss_pips, take_profit_pips, max_hold_days, thesis
    """
    display_pair = entry["pair"]
    ticker = _GROQ_PAIR_MAP.get(display_pair)
    if not ticker:
        logger.warning(f"Navigator | _open_groq_position: no internal ticker for {display_pair!r}")
        return False

    direction    = entry["direction"]
    size_pct     = entry["position_size_pct"]
    sl_pips      = entry["stop_loss_pips"]
    tp_pips      = entry["take_profit_pips"]
    max_hold_days = entry["max_hold_days"]
    thesis       = entry["thesis"]
    conviction   = entry["conviction"]

    # Use latest fetched price; fall back to yfinance fast fetch
    current_price = _latest_prices.get(ticker)
    if not current_price:
        try:
            import yfinance as yf
            data = yf.Ticker(ticker).history(period="1d", interval="1m")
            current_price = float(data["Close"].iloc[-1]) if not data.empty else None
        except Exception as exc:
            logger.warning(f"Navigator | Price fetch failed for {ticker}: {exc}")
    if not current_price:
        logger.warning(f"Navigator | Cannot open {display_pair} — price unavailable")
        return False

    pip_size = PIP_SIZE.get(ticker, 0.0001)
    sl_distance = sl_pips * pip_size
    tp_distance = tp_pips * pip_size

    if direction == "long":
        sl_price = current_price - sl_distance
        tp_price = current_price + tp_distance
    else:
        sl_price = current_price + sl_distance
        tp_price = current_price - tp_distance

    size_usd = equity * size_pct
    size_usd = min(size_usd, available * 0.95)
    if size_usd < 500:
        logger.warning(f"Navigator | {display_pair}: position size too small (${size_usd:.0f})")
        return False

    units = round(size_usd / current_price) if current_price > 0 else 0
    if units <= 0:
        logger.warning(f"Navigator | {display_pair}: computed 0 units — skipping")
        return False

    llm_thesis = f"Groq ({conviction:.0%} conviction, {max_hold_days}d hold): {thesis}"

    logger.info(
        f"Navigator | GROQ ENTRY {display_pair} {direction.upper()} "
        f"@ {current_price:.5f} | SL={sl_price:.5f} TP={tp_price:.5f} "
        f"size=${size_usd:,.0f} ({size_pct:.0%} equity) hold={max_hold_days}d | {thesis}"
    )

    result = paper_open_position(
        pair=ticker,
        direction=direction,
        size_usd=size_usd,
        entry_price=current_price,
        units=units,
        sl_price=sl_price,
        tp_price=tp_price,
        llm_thesis=llm_thesis,
    )
    if not result:
        return False

    # Store Groq metadata for time-stop logic in position check
    try:
        update_position_fields(ticker, {"groq_max_hold_days": max_hold_days, "groq_thesis": thesis})
    except Exception as exc:
        logger.debug(f"Navigator | update_position_fields failed (non-fatal): {exc}")

    try:
        _journal.log_trade_open(
            pair=PAIR_LABELS.get(ticker, ticker),
            direction=direction,
            entry_price=current_price,
            sl_price=sl_price,
            tp_price=tp_price,
            units=units,
            llm_thesis=llm_thesis,
            usd_bias=_state.get("usd_bias", "NEUTRAL"),
            rsi_at_entry=None,
            atr_at_entry=None,
        )
    except Exception:
        pass

    return True


def _close_groq_position(display_pair: str, reason: str) -> None:
    """Close an open position identified by its display pair name (e.g. 'EUR/USD')."""
    ticker = _GROQ_PAIR_MAP.get(display_pair)
    if not ticker:
        logger.warning(f"Navigator | Groq early-close: unknown pair {display_pair!r}")
        return
    positions = get_paper_positions()
    if ticker not in positions:
        logger.info(f"Navigator | Groq early-close {display_pair}: not open, skipping")
        return
    current_price = _latest_prices.get(ticker)
    if not current_price:
        logger.warning(f"Navigator | Groq early-close {display_pair}: price unavailable")
        return
    _close_and_journal(ticker, current_price, f"groq_early_close: {reason}")
    logger.info(f"Navigator | GROQ EARLY CLOSE {display_pair} @ {current_price:.5f} | {reason}")


def _run_groq_entries(equity: float, positions: dict, available: float) -> None:
    """
    Full Groq investment cycle:
      1. Fetch market context
      2. Ask Groq for decisions
      3. Execute validated entries (skip if pair already open)
      4. Close positions Groq wants to exit early
    """
    from market_context import get_market_context
    from groq_investor import get_investment_decisions

    open_positions_fmt = _format_open_positions_for_groq(positions)
    logger.info(f"Navigator | Fetching market context for Groq ({len(open_positions_fmt)} open positions)...")

    try:
        context = get_market_context(open_positions_fmt)
        pairs_available = list(context.get("forex_pairs", {}).keys())
        macro_available = list(context.get("macro_indicators", {}).keys())
        logger.info(f"Navigator | Market context: {len(pairs_available)} pairs, {len(macro_available)} macro indicators")
        if context.get("errors"):
            logger.debug(f"Navigator | Context warnings: {context['errors']}")
    except Exception as exc:
        logger.error(f"Navigator | Failed to fetch market context: {exc}")
        return

    try:
        decisions = get_investment_decisions(context, equity=equity, max_positions=MAX_OPEN_POSITIONS)
    except Exception as exc:
        logger.error(f"Navigator | Groq decision call failed: {exc}")
        return

    _state["usd_bias"] = decisions.get("usd_bias", "neutral").upper()

    # Handle early closes first (frees up capacity before entering)
    for close_rec in decisions.get("close", []):
        pair_display = close_rec.get("pair", "")
        close_reason = close_rec.get("reason", "groq_recommendation")
        try:
            _close_groq_position(pair_display, close_reason)
        except Exception as exc:
            logger.warning(f"Navigator | Groq close failed for {pair_display}: {exc}")

    # Refresh positions after closes
    positions = get_paper_positions()
    available = get_available_capital()

    # Execute new entries
    entries_filled = 0
    for entry in decisions.get("enter", []):
        pair_display = entry.get("pair", "")
        ticker = _GROQ_PAIR_MAP.get(pair_display)
        if ticker and ticker in positions:
            logger.info(f"Navigator | Skipping {pair_display} — already open")
            continue
        if len(positions) + entries_filled >= MAX_OPEN_POSITIONS:
            logger.info(f"Navigator | Max positions reached — stopping entries")
            break
        try:
            ok = _open_groq_position(entry, equity, available)
            if ok:
                entries_filled += 1
                available = get_available_capital()
        except Exception as exc:
            logger.warning(f"Navigator | Entry failed for {pair_display}: {exc}")

    logger.info(
        f"Navigator | Groq cycle complete — "
        f"{entries_filled} positions entered, "
        f"{len(decisions.get('close', []))} close recommendations processed"
    )


def run_cycle() -> dict:
    global _state

    # ── Fleet halt check — cross-process emergency stop ───────────────────────
    try:
        import sys as _sys_fh
        import os as _os_fh
        _tp = _os_fh.path.join(_os_fh.path.dirname(_os_fh.path.abspath(__file__)), "..", "trading-platform")
        if _tp not in _sys_fh.path:
            _sys_fh.path.insert(0, _tp)
        from core.fleet_halt import is_halted as _is_fleet_halted
        if _is_fleet_halted():
            logger.warning(
                f"Bot | FLEET HALT ACTIVE — skipping cycle. "
                f"Resume via POST /trading-api/fleet/resume"
            )
            return _state
    except Exception as _fh_exc:
        logger.debug(f"Bot | Fleet halt check failed (non-fatal, continuing): {_fh_exc}")

    if not _cycle_lock.acquire(blocking=False):
        logger.warning("Forex | Cycle already in progress — skipping concurrent invocation")
        return _state

    try:
        return _run_cycle_inner()
    finally:
        _cycle_lock.release()


def _run_cycle_inner() -> dict:
    global _state

    if is_bot_paused():
        _state["status"] = "paused"
        logger.info("Forex | Bot is paused — skipping cycle")
        _write_heartbeat()
        return _state

    _state["status"] = "scanning"
    _state["cycle_count"] += 1
    _state["error"] = None
    cycle_start = time.time()

    logger.info(f"{'=' * 60}")
    logger.info(f"  THE NAVIGATOR — Forex Cycle #{_state['cycle_count']}")
    logger.info(f"{'=' * 60}")

    try:
        _prefetch_reference_prices()
        _check_open_positions()

        if _state["circuit_breaker_active"]:
            tripped_at = _state.get("circuit_breaker_tripped_at")
            if tripped_at:
                try:
                    tripped_dt = datetime.fromisoformat(tripped_at)
                    elapsed_hours = (datetime.now(tz=timezone.utc) - tripped_dt).total_seconds() / 3600.0
                    if elapsed_hours >= CB_COOLDOWN_HOURS:
                        _state["circuit_breaker_active"] = False
                        _state["circuit_breaker_reason"] = None
                        _state["circuit_breaker_tripped_at"] = None
                        _state["_cb_session_hwm"] = get_paper_equity(current_prices=_latest_prices)
                        logger.info(f"Forex | Circuit breaker RESET after {CB_COOLDOWN_HOURS}h cooldown — HWM rebased to ${_state['_cb_session_hwm']:,.2f}")
                except Exception:
                    pass

        equity = get_paper_equity(current_prices=_latest_prices)

        if _state["_cb_session_hwm"] < equity:
            _state["_cb_session_hwm"] = equity

        if _state["_cb_session_hwm"] > 0 and not _state["circuit_breaker_active"]:
            drawdown = (_state["_cb_session_hwm"] - equity) / _state["_cb_session_hwm"]
            if drawdown >= CB_DRAWDOWN_THRESHOLD:
                _state["circuit_breaker_active"] = True
                _state["circuit_breaker_reason"] = (
                    f"Equity drawdown {drawdown:.1%} exceeds {CB_DRAWDOWN_THRESHOLD:.0%} threshold "
                    f"(equity ${equity:,.2f} vs HWM ${_state['_cb_session_hwm']:,.2f})"
                )
                _state["circuit_breaker_tripped_at"] = datetime.now(tz=timezone.utc).isoformat()
                logger.warning(f"Forex | CIRCUIT BREAKER TRIPPED — {_state['circuit_breaker_reason']}")

        if _state["circuit_breaker_active"]:
            _state["status"] = "circuit_breaker"
            _state["last_scan"] = datetime.now(tz=timezone.utc).isoformat()
            logger.warning("Forex | Circuit breaker active — no new trades this cycle")
            _write_heartbeat()
            _write_live_state()
            return _state

        news_blackout = _check_news_blackout()
        _state["news_blackout"] = news_blackout

        if news_blackout:
            _state["status"] = "news_blackout"
            _state["last_scan"] = datetime.now(tz=timezone.utc).isoformat()
            logger.warning("Forex | News blackout active — no new trades this cycle")
            _write_heartbeat()
            return _state

        positions  = get_paper_positions()
        equity     = get_paper_equity(current_prices=_latest_prices)
        available  = get_available_capital()
        open_count = len(positions)

        logger.info(
            f"Navigator | Open positions: {open_count}/{MAX_OPEN_POSITIONS} | "
            f"Equity: ${equity:,.2f} | Available: ${available:,.2f}"
        )

        # ── Groq investment cycle (fires at 08:00 UTC and 20:00 UTC only) ─────
        if _should_run_groq_cycle():
            if open_count < MAX_OPEN_POSITIONS:
                _run_groq_entries(equity, positions, available)
            else:
                logger.info(
                    f"Navigator | Groq cycle fired but max positions "
                    f"({MAX_OPEN_POSITIONS}) already open — no new entries"
                )
        else:
            logger.info("Navigator | Not a Groq cycle window — exit management only this pass")

        _state["last_scan_results"] = []
        _state["last_scan"] = datetime.now(tz=timezone.utc).isoformat()
        _state["status"] = "idle"

        _check_vault_sweep()

        elapsed = time.time() - cycle_start
        logger.info(f"Forex | Cycle #{_state['cycle_count']} complete in {elapsed:.1f}s — {len(_state.get('last_scan_results', []))} pairs scanned")

    except Exception as exc:
        _state["status"] = "error"
        _state["error"] = str(exc)
        logger.error(f"Forex | Cycle failed: {exc}")

    _write_heartbeat()
    _write_live_state()
    return _state


def _write_navigator_heartbeat() -> None:
    """Write Navigator equity to kraken_heartbeat so fleet monitor can see it."""
    try:
        import psycopg2 as _pg2_hb, os as _os_hb
        _dsn = _os_hb.environ.get("DATABASE_URL")
        if not _dsn:
            return
        equity = get_paper_equity(current_prices=_latest_prices)
        positions = get_paper_positions()
        _hb_conn = _pg2_hb.connect(_dsn)
        try:
            with _hb_conn.cursor() as _cur:
                _cur.execute("""
                    INSERT INTO kraken_heartbeat
                        (id, bot_id, equity_usd, position_count,
                         status, bot_paused, last_updated)
                    VALUES (6, 'navigator', %s, %s, 'running', FALSE, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        equity_usd     = EXCLUDED.equity_usd,
                        position_count = EXCLUDED.position_count,
                        status         = EXCLUDED.status,
                        last_updated   = NOW()
                """, (round(equity, 2), len(positions)))
            _hb_conn.commit()
        finally:
            _hb_conn.close()
    except Exception as exc:
        logger.debug(f"Navigator | Heartbeat write failed (non-fatal): {exc}")


def _write_heartbeat():
    equity = get_paper_equity(current_prices=_latest_prices)
    positions = get_paper_positions()

    _db.upsert_heartbeat(
        status=_state["status"],
        cycle_count=_state["cycle_count"],
        equity_usd=round(equity, 2),
        position_count=len(positions),
        paper_trading=PAPER_TRADING,
        bot_paused=is_bot_paused(),
        usd_bias=_state.get("usd_bias", "NEUTRAL"),
        news_blackout=_state.get("news_blackout", False),
        error=_state.get("error"),
    )
    _write_navigator_heartbeat()

    # ── Dual-write to bots_state (migration Phase 1) ──────────────────────────
    try:
        _tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
        if _tp not in sys.path:
            sys.path.append(_tp)
        from core.bot_state import write_heartbeat as _bs_hb
        _fx_eq = get_paper_equity(current_prices=_latest_prices)
        _fx_pos = get_paper_positions()
        _bs_hb("forex_gump", _fx_eq, positions=len(_fx_pos))
    except Exception as _bse:
        logger.debug(f"Navigator | bots_state dual-write failed (non-fatal): {_bse}")

    # ── Dual-write to bot_portfolio (Stage 2) ─────────────────────────────────
    try:
        _tp2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
        if _tp2 not in sys.path:
            sys.path.append(_tp2)
        from core.bot_state import write_portfolio as _bs_write_pf
        _fx_eq2   = get_paper_equity(current_prices=_latest_prices)
        _fx_pos2  = get_paper_positions()
        _fx_summ  = get_paper_portfolio_summary()
        _fx_cash  = _fx_summ.get("cash_usd", _fx_eq2)
        _bs_write_pf(
            "forex_gump",
            cash=round(_fx_cash, 2),
            equity=round(_fx_eq2, 2),
            positions=[
                {"symbol": PAIR_LABELS.get(_pair, _pair),
                 "side": _fp["direction"],
                 "size": round(_fp.get("size_usd", 0), 2),
                 "entry": _fp["entry_price"],
                 "value_usd": round(_fp.get("size_usd", 0), 2)}
                for _pair, _fp in _fx_pos2.items()
            ],
        )
    except Exception as _pf_exc:
        logger.debug(f"Navigator | bot_portfolio dual-write failed (non-fatal): {_pf_exc}")


def _write_live_state():
    equity = get_paper_equity(current_prices=_latest_prices)
    positions = get_paper_positions()

    positions_list = []
    for pair, pos in positions.items():
        current_price = _latest_prices.get(pair, pos["entry_price"])
        entry = pos["entry_price"]
        direction = pos["direction"]

        if direction == "long":
            pnl_raw = (current_price - entry) * pos.get("units", 0)
        else:
            pnl_raw = (entry - current_price) * pos.get("units", 0)

        conv = get_quote_to_usd(pair, current_price, _latest_prices)
        pnl_usd = pnl_raw * conv if conv is not None else 0.0

        pip_size = PIP_SIZE.get(pair, 0.0001)
        if direction == "long":
            pnl_pips = (current_price - entry) / pip_size
        else:
            pnl_pips = (entry - current_price) / pip_size

        positions_list.append({
            "pair": PAIR_LABELS.get(pair, pair),
            "direction": direction,
            "entry_price": round(entry, 5),
            "current_price": round(current_price, 5),
            "sl_price": round(pos.get("sl_price", 0), 5),
            "tp_price": round(pos.get("tp_price", 0), 5),
            "original_sl": round(pos.get("original_sl", pos.get("sl_price", 0)), 5),
            "trailing_sl": round(pos.get("trailing_sl", pos.get("sl_price", 0)), 5),
            "highest_price": round(pos["highest_price"], 5) if pos.get("highest_price") is not None else None,
            "lowest_price": round(pos["lowest_price"], 5) if pos.get("lowest_price") is not None else None,
            "units": pos.get("units", 0),
            "size_usd": round(pos.get("size_usd", 0), 2),
            "unrealized_pnl_usd": round(pnl_usd, 2),
            "unrealized_pnl_pips": round(pnl_pips, 1),
            "entry_time": pos.get("entry_time", ""),
        })

    summary = get_paper_portfolio_summary()

    live_state = {
        "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        "status": _state["status"],
        "cycle_count": _state["cycle_count"],
        "usd_bias": _state.get("usd_bias", "NEUTRAL"),
        "news_blackout": _state.get("news_blackout", False),
        "equity_usd": round(equity, 2),
        "paper_trading": PAPER_TRADING,
        "positions": positions_list,
        "scan_results": _state.get("last_scan_results", []),
        "last_scan": _state.get("last_scan"),
        "summary": summary,
        "error": _state.get("error"),
        "circuit_breaker_active": _state.get("circuit_breaker_active", False),
        "circuit_breaker_reason": _state.get("circuit_breaker_reason"),
    }

    try:
        tmp = LIVE_STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(live_state, f, indent=2, default=str)
        os.replace(tmp, LIVE_STATE_FILE)
    except Exception as exc:
        logger.warning(f"Forex | Could not write live state: {exc}")


def get_state() -> dict:
    equity = get_paper_equity(current_prices=_latest_prices)
    positions = get_paper_positions()
    summary = get_paper_portfolio_summary()

    return {
        "status": _state["status"],
        "paused": is_bot_paused(),
        "cycle_count": _state["cycle_count"],
        "usd_bias": _state.get("usd_bias", "NEUTRAL"),
        "news_blackout": _state.get("news_blackout", False),
        "last_scan": _state.get("last_scan"),
        "last_scan_results": _state.get("last_scan_results", []),
        "paper_mode": PAPER_TRADING,
        "paper_equity": round(equity, 2),
        "total_equity": round(equity, 2),
        "position_count": len(positions),
        "total_trades": summary.get("total_trades", 0),
        "total_wins": summary.get("win_count", 0),
        "total_pnl": summary.get("all_time_pnl_usd", 0),
        "hwm_usd": summary.get("hwm_usd", PAPER_STARTING_BALANCE),
        "vault_total_usd": summary.get("vault_total_usd", 0),
        "error": _state.get("error"),
        "circuit_breaker_active": _state.get("circuit_breaker_active", False),
        "circuit_breaker_reason": _state.get("circuit_breaker_reason"),
    }


def get_positions() -> list[dict]:
    positions = get_paper_positions()
    result = []
    for pair, pos in positions.items():
        current_price = _latest_prices.get(pair, pos["entry_price"])
        entry = pos["entry_price"]
        direction = pos["direction"]

        if direction == "long":
            pnl_raw = (current_price - entry) * pos.get("units", 0)
        else:
            pnl_raw = (entry - current_price) * pos.get("units", 0)

        conv = get_quote_to_usd(pair, current_price, _latest_prices)
        pnl_usd = pnl_raw * conv if conv is not None else 0.0

        pip_size = PIP_SIZE.get(pair, 0.0001)
        pnl_pips = ((current_price - entry) / pip_size) if direction == "long" else ((entry - current_price) / pip_size)

        result.append({
            "pair": PAIR_LABELS.get(pair, pair),
            "direction": direction,
            "entry_price": round(entry, 5),
            "current_price": round(current_price, 5),
            "sl_price": round(pos.get("sl_price", 0), 5),
            "tp_price": round(pos.get("tp_price", 0), 5),
            "original_sl": round(pos.get("original_sl", pos.get("sl_price", 0)), 5),
            "trailing_sl": round(pos.get("trailing_sl", pos.get("sl_price", 0)), 5),
            "highest_price": round(pos["highest_price"], 5) if pos.get("highest_price") is not None else None,
            "lowest_price": round(pos["lowest_price"], 5) if pos.get("lowest_price") is not None else None,
            "units": pos.get("units", 0),
            "size_usd": round(pos.get("size_usd", 0), 2),
            "unrealized_pnl_usd": round(pnl_usd, 2),
            "unrealized_pnl_pips": round(pnl_pips, 1),
            "entry_time": pos.get("entry_time", ""),
        })
    return result


def pause_bot():
    import pathlib
    ctrl = pathlib.Path(CONTROL_FILE)
    ctrl.parent.mkdir(parents=True, exist_ok=True)
    ctrl.write_text(json.dumps({"bot_paused": True}))
    _state["paused"] = True
    logger.info("Forex | Bot PAUSED via API")


def resume_bot():
    import pathlib
    ctrl = pathlib.Path(CONTROL_FILE)
    ctrl.parent.mkdir(parents=True, exist_ok=True)
    ctrl.write_text(json.dumps({"bot_paused": False}))
    _state["paused"] = False
    logger.info("Forex | Bot RESUMED via API")
