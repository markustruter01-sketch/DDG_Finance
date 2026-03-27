"""
Intraday Analysis Cycle — Regime-Switching Architecture
---------------------------------------------------------
v4.0 — Dynamic Regime-Switching & Adaptive Allocation

Called every market session (or 15-min for crypto off-hours):

  Full Market (Regime) mode:
    1. Query Alpaca for account state (buying power + positions).
    2. Run RAG feedback injection (recent wins, losses, slippage).
    3. Fetch 6-month data: FRED macro (cached 1hr) + Alpaca market prices
       (fresh, includes 3mo/6mo MA signals) + NewsAPI (cached 30min).
    4. Assemble system prompt + user prompt with momentum signals.
    5. Call Groq (llama-3.3-70b-versatile) for regime-switching JSON.
    6. Validate with Pydantic (RegimeAnalysisOutput).
    7. Apply even-weighting override and normalise Kelly fractions.
    8. Return final RegimeAnalysisOutput.

  Crypto-Only mode (off-hours):
    Same pipeline with crypto-only universe: BTC/USD, ETH/USD, ATOM/USD.
"""

import asyncio
import json
from typing import Any, Union

from loguru import logger

from analysis.feedback_injection import build_system_prompt_with_feedback
from analysis.groq_client import build_user_prompt, call_groq
from analysis.schemas import RegimeAnalysisOutput, CryptoAnalysisOutput
from data.cache import fred_cache, news_cache
from data.fred_client import fetch_macro_data
from data.news_client import fetch_news
from data.yfinance_client import fetch_market_data
from portfolio.allocator import process_regime_llm_output, process_crypto_llm_output


def _fetch_account_state() -> dict[str, Any]:
    from execution.broker import get_account, get_positions
    acct = get_account()
    positions = get_positions()
    held_symbols = [p["symbol"] for p in positions]
    state = {
        "buying_power": acct["buying_power"],
        "equity":       acct["equity"],
        "cash":         acct["cash"],
        "held_symbols": held_symbols,
        "held_values":  {p["symbol"]: p["market_value"] for p in positions},
    }
    logger.info(
        f"Account state | equity=${state['equity']:,.2f} "
        f"buying_power=${state['buying_power']:,.2f} "
        f"held={held_symbols or 'none'}"
    )
    return state


async def run_analysis_cycle(
    lookback_days_macro: int = 90,
    market_period: str = "1y",
    news_lookback_days: int = 3,
    n_loss_feedback: int = 5,
    dry_run: bool = False,
    crypto_only: bool = False,
) -> Union[RegimeAnalysisOutput, CryptoAnalysisOutput]:
    mode_label = "CRYPTO-ONLY" if crypto_only else "REGIME-SWITCHING FULL MARKET"
    logger.info("=" * 60)
    logger.info(f"ANALYSIS CYCLE STARTING ({mode_label})")
    logger.info("=" * 60)

    logger.info("Step 1/5 | Querying Alpaca for account state (buying power + positions)...")
    loop = asyncio.get_event_loop()
    try:
        account_state = await loop.run_in_executor(None, _fetch_account_state)
    except Exception as exc:
        logger.error(f"ABORTING analysis — cannot fetch account state: {exc}")
        raise RuntimeError(f"Account state unavailable, analysis aborted: {exc}") from exc

    logger.info("Step 2/5 | Building RAG-enhanced system prompt...")
    system_prompt = build_system_prompt_with_feedback(
        n_losses=n_loss_feedback,
        buying_power=account_state["buying_power"],
        held_symbols=account_state["held_symbols"],
        crypto_only=crypto_only,
    )

    if crypto_only:
        logger.info("Step 3/5 | Fetching data (Crypto 6mo + MA signals | News cached 30min)...")
        market_data, news_data = await asyncio.gather(
            fetch_market_data(period=market_period, crypto_only=True),
            news_cache.get_or_fetch(fetch_news, lookback_days=news_lookback_days),
        )
        macro_data = {}
    else:
        logger.info("Step 3/5 | Fetching data (FRED cached 1hr | Market 6mo + MA signals | News cached 30min)...")
        macro_data, market_data, news_data = await asyncio.gather(
            fred_cache.get_or_fetch(fetch_macro_data, lookback_days=lookback_days_macro),
            fetch_market_data(period=market_period),
            news_cache.get_or_fetch(fetch_news, lookback_days=news_lookback_days),
        )

    if crypto_only:
        market_ok = sum(1 for v in market_data["by_ticker"].values() if "error" not in v)
        news_ok   = len(news_data["all_headlines"])
        logger.info(f"  Data snapshot: Crypto={market_ok}/3 tickers | News={news_ok} headlines")
    else:
        macro_ok  = sum(1 for v in macro_data.values() if v.get("value") is not None)
        market_ok = sum(1 for v in market_data["by_ticker"].values() if "error" not in v)
        news_ok   = len(news_data["all_headlines"])
        logger.info(
            f"  Data snapshot: FRED={macro_ok}/10 | "
            f"Market={market_ok}/{len(market_data['by_ticker'])} tickers | "
            f"News={news_ok} headlines"
        )

    logger.info("Step 4/5 | Calling Groq LLM (llama-3.3-70b-versatile)...")
    user_prompt = build_user_prompt(
        macro_data,
        market_data,
        news_data["all_headlines"],
        account_state=account_state,
        crypto_only=crypto_only,
    )

    if dry_run:
        logger.warning("DRY RUN: skipping actual Groq API call, returning mock output")
        if crypto_only:
            raw_json = _mock_crypto_llm_response()
            output = process_crypto_llm_output(raw_json)
        else:
            raw_json = _mock_regime_llm_response()
            output = process_regime_llm_output(raw_json)
    else:
        if crypto_only:
            output = _call_crypto_with_retry(system_prompt, user_prompt)
        else:
            output = _call_regime_with_retry(system_prompt, user_prompt)

    logger.info("=" * 60)
    logger.info(f"ANALYSIS CYCLE COMPLETE ({mode_label})")
    logger.info(output.summary())
    logger.info("=" * 60)

    return output


MAX_LLM_RETRIES = 3


def _call_regime_with_retry(system_prompt: str, user_prompt: str) -> RegimeAnalysisOutput:
    last_error: Exception | None = None
    current_user_prompt = user_prompt

    for attempt in range(1, MAX_LLM_RETRIES + 1):
        logger.info(f"Step 5/5 | Regime LLM call attempt {attempt}/{MAX_LLM_RETRIES}...")
        try:
            raw_json = call_groq(
                system_prompt=system_prompt,
                user_prompt=current_user_prompt,
                temperature=0.2,
                max_tokens=2048,
            )
            output = process_regime_llm_output(raw_json)
            if attempt > 1:
                logger.info(f"  LLM self-corrected on attempt {attempt}")
            return output

        except Exception as exc:
            last_error = exc
            error_msg = str(exc)
            logger.warning(f"  Attempt {attempt} failed: {error_msg[:300]}")

            if attempt < MAX_LLM_RETRIES:
                current_user_prompt = (
                    f"{user_prompt}\n\n"
                    f"--- CORRECTION REQUIRED (attempt {attempt} was invalid) ---\n"
                    f"Your previous JSON output failed validation with this error:\n"
                    f"  {error_msg}\n\n"
                    f"Please fix and return corrected JSON only. Key rules:\n"
                    f"  - 'regime' must be exactly 'Bull', 'Bear', or 'Sideways'\n"
                    f"  - Bull: 1-3 slots of equity/crypto_spot with positive momentum\n"
                    f"  - Bear: 1-2 slots of TLT/GLD (safe_haven) with positive momentum, else SGOV\n"
                    f"  - Sideways: 0-2 mean-reversion slots, or single SGOV slot\n"
                    f"  - Only approved tickers: SPY, QQQ, TLT, GLD, BTC/USD, ETH/USD, ATOM/USD, SGOV\n"
                    f"  - Slots numbered 1, 2, 3 ... sequentially\n"
                    f"  - kelly_fraction sum (excluding SGOV) must not exceed 1.0\n"
                    f"  - asset_class must match ticker: equity→SPY/QQQ, safe_haven→TLT/GLD, "
                    f"crypto_spot→BTC/USD/ETH/USD/ATOM/USD, cash→SGOV\n"
                )

    raise RuntimeError(
        f"Regime LLM failed after {MAX_LLM_RETRIES} attempts. Last error: {last_error}"
    )


def _call_crypto_with_retry(system_prompt: str, user_prompt: str) -> CryptoAnalysisOutput:
    last_error: Exception | None = None
    current_user_prompt = user_prompt

    for attempt in range(1, MAX_LLM_RETRIES + 1):
        logger.info(f"Step 5/5 | Crypto LLM call attempt {attempt}/{MAX_LLM_RETRIES}...")
        try:
            raw_json = call_groq(
                system_prompt=system_prompt,
                user_prompt=current_user_prompt,
                temperature=0.2,
                max_tokens=2048,
            )
            output = process_crypto_llm_output(raw_json)
            if attempt > 1:
                logger.info(f"  LLM self-corrected on attempt {attempt}")
            return output

        except Exception as exc:
            last_error = exc
            error_msg = str(exc)
            logger.warning(f"  Attempt {attempt} failed: {error_msg[:300]}")

            if attempt < MAX_LLM_RETRIES:
                current_user_prompt = (
                    f"{user_prompt}\n\n"
                    f"--- CORRECTION REQUIRED (attempt {attempt} was invalid) ---\n"
                    f"Your previous JSON output failed validation with this error:\n"
                    f"  {error_msg}\n\n"
                    f"Please fix and return corrected JSON only. Rules:\n"
                    f"  - Only approved tickers: BTC/USD, ETH/USD, ATOM/USD, SGOV\n"
                    f"  - asset_class: 'crypto_spot' for BTC/ETH/ATOM, 'cash' for SGOV\n"
                    f"  - 1 to 3 slots, numbered sequentially from 1\n"
                    f"  - kelly_fraction sum (excluding SGOV) <= 1.0\n"
                    f"  - Only allocate to crypto with POSITIVE momentum. Default SGOV if uncertain.\n"
                )

    raise RuntimeError(
        f"Crypto LLM failed after {MAX_LLM_RETRIES} attempts. Last error: {last_error}"
    )


def _mock_regime_llm_response() -> str:
    return json.dumps({
        "regime": "Bear",
        "regime_rationale": (
            "Elevated VIX above 25, inverted yield curve normalising from deeply negative levels, "
            "Fed holding rates higher-for-longer with no pivot signal. Equity momentum is negative "
            "on both 3-month and 6-month MAs. Safe havens showing positive momentum."
        ),
        "allocations": [
            {
                "slot": 1,
                "ticker": "GLD",
                "asset_class": "safe_haven",
                "conviction_score": 0.88,
                "kelly_fraction": 0.50,
                "thesis": "Gold breaking out above key resistance. Real rates declining as inflation expectations "
                          "remain elevated. 3-month and 6-month momentum both positive.",
                "stop_loss_pct": -0.05,
                "take_profit_pct": 0.12,
            },
            {
                "slot": 2,
                "ticker": "TLT",
                "asset_class": "safe_haven",
                "conviction_score": 0.82,
                "kelly_fraction": 0.50,
                "thesis": "Long-duration Treasuries benefiting from flight-to-quality. Momentum positive "
                          "on both MAs as recession risk increases and Fed nears peak rates.",
                "stop_loss_pct": -0.05,
                "take_profit_pct": 0.10,
            },
        ],
    })


def _mock_crypto_llm_response() -> str:
    return json.dumps({
        "market_regime": (
            "Crypto markets consolidating with BTC holding key support. "
            "ETH showing relative strength. ATOM lagging with negative momentum."
        ),
        "allocations": [
            {
                "slot": 1,
                "ticker": "BTC/USD",
                "asset_class": "crypto_spot",
                "conviction_score": 0.85,
                "kelly_fraction": 0.50,
                "thesis": "Bitcoin holding key support with strong institutional inflows. "
                          "3-month and 6-month momentum both positive.",
                "stop_loss_pct": -0.08,
                "take_profit_pct": 0.18,
            },
            {
                "slot": 2,
                "ticker": "ETH/USD",
                "asset_class": "crypto_spot",
                "conviction_score": 0.80,
                "kelly_fraction": 0.50,
                "thesis": "Ethereum showing relative strength with growing staking yields "
                          "and DeFi TVL recovery. Positive momentum on both MAs.",
                "stop_loss_pct": -0.09,
                "take_profit_pct": 0.20,
            },
        ],
    })
