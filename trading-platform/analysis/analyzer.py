"""
Daily Analysis Cycle — Main Orchestrator
-----------------------------------------
This is the brain of the platform. Called once per trading day, it:

  1. Runs the RAG feedback injection (queries recent Closed_Loss trades).
  2. Fetches live data concurrently: FRED macro + Alpaca market prices + NewsAPI.
  3. Assembles the system prompt (with loss feedback) + user prompt (live data).
  4. Calls Groq (llama-3.3-70b-versatile) for structured JSON allocation.
  5. Validates and post-processes output via Pydantic + Kelly Criterion.
  6. Returns the final 10-slot AnalysisOutput.

The market clock check (US ET hours) lives in core/market_clock.py (Phase 4).
"""

import asyncio
import json
from typing import Any

from loguru import logger

from analysis.feedback_injection import build_system_prompt_with_feedback
from analysis.groq_client import build_user_prompt, call_groq
from analysis.schemas import AnalysisOutput
from data.fred_client import fetch_macro_data
from data.news_client import fetch_news
from data.yfinance_client import fetch_market_data
from portfolio.allocator import process_llm_output


async def run_analysis_cycle(
    lookback_days_macro: int = 90,
    market_period: str = "3mo",
    news_lookback_days: int = 3,
    n_loss_feedback: int = 5,
    dry_run: bool = False,
) -> AnalysisOutput:
    """
    Execute the complete daily analysis cycle.

    Args:
        lookback_days_macro:  FRED lookback window in days (default 90).
        market_period:        yfinance/Alpaca period string (default '3mo').
        news_lookback_days:   Days of news to fetch (default 3).
        n_loss_feedback:      Number of recent losses to inject into prompt.
        dry_run:              If True, skip the Groq API call and return mock output.

    Returns:
        Validated AnalysisOutput with 10 allocation slots.
    """
    logger.info("=" * 60)
    logger.info("ANALYSIS CYCLE STARTING")
    logger.info("=" * 60)

    logger.info("Step 1/4 | Building RAG-enhanced system prompt...")
    system_prompt = build_system_prompt_with_feedback(n_losses=n_loss_feedback)

    logger.info("Step 2/4 | Fetching live data (FRED + Market + News)...")
    macro_data, market_data, news_data = await asyncio.gather(
        fetch_macro_data(lookback_days=lookback_days_macro),
        fetch_market_data(period=market_period),
        fetch_news(lookback_days=news_lookback_days),
    )

    macro_ok  = sum(1 for v in macro_data.values() if v.get("value") is not None)
    market_ok = sum(1 for v in market_data["by_ticker"].values() if "error" not in v)
    news_ok   = len(news_data["all_headlines"])
    logger.info(
        f"  Data snapshot: FRED={macro_ok}/10 | "
        f"Market={market_ok}/22 tickers | "
        f"News={news_ok} headlines"
    )

    logger.info("Step 3/4 | Calling Groq LLM (llama-3.3-70b-versatile)...")
    user_prompt = build_user_prompt(macro_data, market_data, news_data["all_headlines"])

    if dry_run:
        logger.warning("DRY RUN: skipping actual Groq API call, returning mock output")
        raw_json = _mock_llm_response()
        output = process_llm_output(raw_json)
    else:
        output = _call_with_retry(system_prompt, user_prompt)

    logger.info("=" * 60)
    logger.info("ANALYSIS CYCLE COMPLETE")
    logger.info(f"  {output.market_regime}")
    logger.info("")
    logger.info(output.summary())
    logger.info("=" * 60)

    return output


MAX_LLM_RETRIES = 3


def _call_with_retry(system_prompt: str, user_prompt: str) -> AnalysisOutput:
    """
    Call Groq and validate the response. On validation failure, inject the
    exact Pydantic error message back into a follow-up prompt so the LLM
    can self-correct. Retries up to MAX_LLM_RETRIES times.

    Args:
        system_prompt: RAG-enhanced system context.
        user_prompt:   Live macro + market + news data.

    Returns:
        Validated AnalysisOutput.

    Raises:
        RuntimeError: If all retries are exhausted without a valid response.
    """
    last_error: Exception | None = None
    current_user_prompt = user_prompt

    for attempt in range(1, MAX_LLM_RETRIES + 1):
        logger.info(f"Step 4/{4} | LLM call attempt {attempt}/{MAX_LLM_RETRIES}...")
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
                )

    raise RuntimeError(
        f"LLM failed to produce a valid allocation after {MAX_LLM_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _mock_llm_response() -> str:
    """
    A hard-coded valid response used for dry_run / integration testing.
    Represents a realistic allocation across all four categories.
    """
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
