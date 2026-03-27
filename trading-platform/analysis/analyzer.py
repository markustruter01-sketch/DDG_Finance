"""
Intraday Analysis Cycle — Main Orchestrator
---------------------------------------------
The brain of the platform. Called every 15 minutes:

  During market hours (full universe):
    1. Queries Alpaca for exact buying_power and held symbols (State Awareness).
    2. Runs the RAG feedback injection (queries recent wins, losses, slippage).
    3. Fetches live data: FRED macro (cached 1hr) + Alpaca market prices (fresh)
       + NewsAPI headlines (cached 30min).
    4. Assembles the system prompt (with feedback + buying power) + user prompt.
    5. Calls Groq (llama-3.3-70b-versatile) for structured JSON allocation.
    6. Validates and post-processes output via Pydantic + Kelly Criterion.
    7. Returns the final 10-slot AnalysisOutput.

  During off-hours (crypto-only):
    1. Queries Alpaca for account state.
    2. Runs the RAG feedback injection (crypto-focused).
    3. Fetches crypto market data (fresh) + NewsAPI headlines (cached 30min).
    4. Uses crypto-only system prompt (6 slots, crypto pairs only).
    5. Returns the final 6-slot CryptoAnalysisOutput.
"""

import asyncio
import json
from typing import Any, Union

from loguru import logger

from analysis.feedback_injection import build_system_prompt_with_feedback
from analysis.groq_client import build_user_prompt, call_groq
from analysis.schemas import AnalysisOutput, CryptoAnalysisOutput
from data.cache import fred_cache, news_cache
from data.fred_client import fetch_macro_data
from data.news_client import fetch_news
from data.yfinance_client import fetch_market_data
from portfolio.allocator import process_llm_output, process_crypto_llm_output


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
    market_period: str = "3mo",
    news_lookback_days: int = 3,
    n_loss_feedback: int = 5,
    dry_run: bool = False,
    crypto_only: bool = False,
) -> Union[AnalysisOutput, CryptoAnalysisOutput]:
    mode_label = "CRYPTO-ONLY" if crypto_only else "FULL MARKET"
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
        logger.info("Step 3/5 | Fetching data (Crypto fresh | News cached 30min)...")
        market_data, news_data = await asyncio.gather(
            fetch_market_data(period=market_period, crypto_only=True),
            news_cache.get_or_fetch(fetch_news, lookback_days=news_lookback_days),
        )
        macro_data = {}
    else:
        logger.info("Step 3/5 | Fetching data (FRED cached 1hr | Market fresh | News cached 30min)...")
        macro_data, market_data, news_data = await asyncio.gather(
            fred_cache.get_or_fetch(fetch_macro_data, lookback_days=lookback_days_macro),
            fetch_market_data(period=market_period),
            news_cache.get_or_fetch(fetch_news, lookback_days=news_lookback_days),
        )

    if crypto_only:
        market_ok = sum(1 for v in market_data["by_ticker"].values() if "error" not in v)
        news_ok   = len(news_data["all_headlines"])
        logger.info(f"  Data snapshot: Crypto={market_ok}/6 tickers | News={news_ok} headlines")
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
            raw_json = _mock_llm_response()
            output = process_llm_output(raw_json)
    else:
        if crypto_only:
            output = _call_crypto_with_retry(system_prompt, user_prompt)
        else:
            output = _call_with_retry(system_prompt, user_prompt)

    logger.info("=" * 60)
    logger.info(f"ANALYSIS CYCLE COMPLETE ({mode_label})")
    logger.info(f"  {output.market_regime}")
    logger.info("")
    logger.info(output.summary())
    logger.info("=" * 60)

    return output


MAX_LLM_RETRIES = 3


def _call_with_retry(system_prompt: str, user_prompt: str) -> AnalysisOutput:
    last_error: Exception | None = None
    current_user_prompt = user_prompt

    for attempt in range(1, MAX_LLM_RETRIES + 1):
        logger.info(f"Step 5/{5} | LLM call attempt {attempt}/{MAX_LLM_RETRIES}...")
        try:
            raw_json = call_groq(
                system_prompt=system_prompt,
                user_prompt=current_user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            output = process_llm_output(raw_json)
            if attempt > 1:
                logger.info(f"  LLM self-corrected on attempt {attempt}")
            return output

        except Exception as exc:
            last_error = exc
            error_msg = str(exc)
            logger.warning(f"  Attempt {attempt} failed: {error_msg[:200]}")

            if attempt < MAX_LLM_RETRIES:
                current_user_prompt = (
                    f"{user_prompt}\n\n"
                    f"--- CORRECTION REQUIRED (attempt {attempt} was invalid) ---\n"
                    f"Your previous JSON output failed validation with this error:\n"
                    f"  {error_msg}\n\n"
                    f"Please fix your response and return corrected JSON only. "
                    f"Remember:\n"
                    f"  - Exactly 10 slots numbered 1-10\n"
                    f"  - At least 2 crypto slots (BITO, IBIT, GBTC, ETHA)\n"
                    f"  - At least 2 commodity slots (GLD, SLV, USO, DBA, PDBC, CPER)\n"
                    f"  - At least 1 currency slot (UUP, FXE, FXY, FXB, EUO, YCS)\n"
                    f"  - At least 1 wildcard slot (QQQ, SPY, TLT, HYG, EEM)\n"
                    f"  - Low conviction slots will be replaced with SGOV automatically\n"
                    f"  - All tickers must match their declared asset_class\n"
                    f"  - Total kelly_fractions must not exceed buying power\n"
                )

    raise RuntimeError(
        f"LLM failed to produce a valid allocation after {MAX_LLM_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _call_crypto_with_retry(system_prompt: str, user_prompt: str) -> CryptoAnalysisOutput:
    last_error: Exception | None = None
    current_user_prompt = user_prompt

    for attempt in range(1, MAX_LLM_RETRIES + 1):
        logger.info(f"Step 5/{5} | Crypto LLM call attempt {attempt}/{MAX_LLM_RETRIES}...")
        try:
            raw_json = call_groq(
                system_prompt=system_prompt,
                user_prompt=current_user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            output = process_crypto_llm_output(raw_json)
            if attempt > 1:
                logger.info(f"  LLM self-corrected on attempt {attempt}")
            return output

        except Exception as exc:
            last_error = exc
            error_msg = str(exc)
            logger.warning(f"  Attempt {attempt} failed: {error_msg[:200]}")

            if attempt < MAX_LLM_RETRIES:
                current_user_prompt = (
                    f"{user_prompt}\n\n"
                    f"--- CORRECTION REQUIRED (attempt {attempt} was invalid) ---\n"
                    f"Your previous JSON output failed validation with this error:\n"
                    f"  {error_msg}\n\n"
                    f"Please fix your response and return corrected JSON only. "
                    f"Remember:\n"
                    f"  - Exactly 6 slots numbered 1-6\n"
                    f"  - Crypto pairs only: BTC/USD, ETH/USD, SOL/USD, DOGE/USD, AVAX/USD, LINK/USD\n"
                    f"  - asset_class must be 'crypto_spot' or 'cash'\n"
                    f"  - Use 'SGOV' with asset_class 'cash' for low conviction slots\n"
                    f"  - At least 4 crypto_spot slots required\n"
                    f"  - Total kelly_fractions must not exceed buying power\n"
                )

    raise RuntimeError(
        f"Crypto LLM failed to produce a valid allocation after {MAX_LLM_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _mock_llm_response() -> str:
    return json.dumps({
        "market_regime": (
            "Risk-off environment: elevated VIX (25+), inverted yield curve normalising, "
            "Fed on hold. Dollar strengthening moderately. Crypto under pressure."
        ),
        "allocations": [
            {"slot": 1,  "ticker": "IBIT",  "asset_class": "crypto",    "conviction_score": 0.78, "kelly_fraction": 0.08, "thesis": "Bitcoin ETF inflows remain strong despite macro headwinds. Asymmetric upside on Fed pivot.",     "stop_loss_pct": -0.07, "take_profit_pct": 0.15},
            {"slot": 2,  "ticker": "BITO",  "asset_class": "crypto",    "conviction_score": 0.76, "kelly_fraction": 0.07, "thesis": "BTC futures ETF as secondary crypto exposure. Momentum positive on weekly timeframe.",           "stop_loss_pct": -0.07, "take_profit_pct": 0.14},
            {"slot": 3,  "ticker": "SGOV",  "asset_class": "cash",      "conviction_score": 1.00, "kelly_fraction": 0.00, "thesis": "Low crypto conviction — cash equivalent.",                                                     "stop_loss_pct": -0.01, "take_profit_pct": 0.01},
            {"slot": 4,  "ticker": "GLD",   "asset_class": "commodity",  "conviction_score": 0.88, "kelly_fraction": 0.14, "thesis": "Gold breaking out above $2400. Real rates declining, USD peaking. Safe haven demand surging.", "stop_loss_pct": -0.05, "take_profit_pct": 0.12},
            {"slot": 5,  "ticker": "SLV",   "asset_class": "commodity",  "conviction_score": 0.82, "kelly_fraction": 0.10, "thesis": "Silver lagging gold. Industrial demand from solar panels robust. Catch-up trade probable.",    "stop_loss_pct": -0.06, "take_profit_pct": 0.13},
            {"slot": 6,  "ticker": "USO",   "asset_class": "commodity",  "conviction_score": 0.77, "kelly_fraction": 0.08, "thesis": "WTI crude supported by OPEC+ cuts. $85-90 range likely to hold near-term.",                   "stop_loss_pct": -0.06, "take_profit_pct": 0.10},
            {"slot": 7,  "ticker": "UUP",   "asset_class": "currency",  "conviction_score": 0.80, "kelly_fraction": 0.09, "thesis": "USD index strengthening on rate differential. Fed higher-for-longer vs ECB easing.",           "stop_loss_pct": -0.04, "take_profit_pct": 0.08},
            {"slot": 8,  "ticker": "FXY",   "asset_class": "currency",  "conviction_score": 0.72, "kelly_fraction": 0.00, "thesis": "JPY recovery thesis requires BOJ pivot confirmation — not yet convincing.",                    "stop_loss_pct": -0.05, "take_profit_pct": 0.09},
            {"slot": 9,  "ticker": "TLT",   "asset_class": "wildcard",  "conviction_score": 0.79, "kelly_fraction": 0.09, "thesis": "Long-duration treasuries as recession hedge. Yield curve normalisation benefits TLT.",         "stop_loss_pct": -0.05, "take_profit_pct": 0.12},
            {"slot": 10, "ticker": "GLD",   "asset_class": "commodity",  "conviction_score": 0.85, "kelly_fraction": 0.12, "thesis": "Second gold position given macro backdrop. Double weight justified by strong conviction.",      "stop_loss_pct": -0.05, "take_profit_pct": 0.12},
        ],
    })


def _mock_crypto_llm_response() -> str:
    return json.dumps({
        "market_regime": (
            "Crypto markets consolidating after recent rally. BTC holding above key support. "
            "ETH showing relative strength. Altcoin rotation favouring SOL ecosystem."
        ),
        "allocations": [
            {"slot": 1, "ticker": "BTC/USD",  "asset_class": "crypto_spot", "conviction_score": 0.85, "kelly_fraction": 0.15, "thesis": "Bitcoin holding key support with strong institutional inflows. Network hash rate at all-time highs.", "stop_loss_pct": -0.08, "take_profit_pct": 0.15},
            {"slot": 2, "ticker": "ETH/USD",  "asset_class": "crypto_spot", "conviction_score": 0.82, "kelly_fraction": 0.12, "thesis": "Ethereum showing relative strength with growing DeFi TVL and staking yields.",                      "stop_loss_pct": -0.08, "take_profit_pct": 0.14},
            {"slot": 3, "ticker": "SOL/USD",  "asset_class": "crypto_spot", "conviction_score": 0.78, "kelly_fraction": 0.10, "thesis": "Solana ecosystem growth accelerating with increasing DEX volume and NFT activity.",                   "stop_loss_pct": -0.10, "take_profit_pct": 0.18},
            {"slot": 4, "ticker": "LINK/USD", "asset_class": "crypto_spot", "conviction_score": 0.76, "kelly_fraction": 0.08, "thesis": "Chainlink oracle demand growing with RWA tokenisation trend. CCIP adoption rising.",                  "stop_loss_pct": -0.10, "take_profit_pct": 0.16},
            {"slot": 5, "ticker": "SGOV",     "asset_class": "cash",        "conviction_score": 1.00, "kelly_fraction": 0.00, "thesis": "Low conviction on remaining crypto — preserving capital in cash equivalent.",                          "stop_loss_pct": -0.01, "take_profit_pct": 0.01},
            {"slot": 6, "ticker": "AVAX/USD", "asset_class": "crypto_spot", "conviction_score": 0.75, "kelly_fraction": 0.07, "thesis": "Avalanche subnet growth and institutional partnerships providing tailwinds.",                          "stop_loss_pct": -0.10, "take_profit_pct": 0.16},
        ],
    })
