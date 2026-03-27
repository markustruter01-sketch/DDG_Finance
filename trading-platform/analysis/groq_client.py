"""
Groq LLM Client — Free Inference via Llama 3
----------------------------------------------
Uses the Groq API (free tier) with Meta's llama3-70b-8192 model as the
primary reasoning engine for daily macroeconomic analysis.

Groq provides:
  - Free API access with generous rate limits
  - Extremely fast inference (LPU hardware)
  - llama3-70b-8192: high-quality 70B parameter model with 8k context

The client receives:
  - A system prompt (which includes the RAG feedback from trade losses)
  - A user prompt (macro data + market prices + news headlines)

It returns a strictly-formatted JSON string that the caller parses with Pydantic.
"""

from groq import Groq
from loguru import logger

from config.settings import settings

MODEL = "llama-3.3-70b-versatile"

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def call_groq(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """
    Send a chat completion request to Groq (llama3-70b-8192).

    Args:
        system_prompt: Full system context including RAG feedback injection.
        user_prompt:   The macro + market + news data payload.
        temperature:   Low temperature (0.2) for consistent, analytical output.
        max_tokens:    Maximum tokens in the response.

    Returns:
        Raw string response from the model (expected to be JSON).

    Raises:
        RuntimeError: If the API call fails after logging the error.
    """
    client = _get_client()
    logger.info(f"Groq | Sending request to {MODEL} (temp={temperature})")

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        usage = response.usage
        logger.info(
            f"Groq | Response received — "
            f"prompt_tokens={usage.prompt_tokens} "
            f"completion_tokens={usage.completion_tokens} "
            f"total={usage.total_tokens}"
        )
        return content

    except Exception as exc:
        logger.error(f"Groq | API call failed: {exc}")
        raise RuntimeError(f"Groq API call failed: {exc}") from exc


def build_user_prompt(
    macro_data: dict,
    market_data: dict,
    news_headlines: list[str],
    account_state: dict | None = None,
    crypto_only: bool = False,
) -> str:
    lines = []

    if account_state and account_state.get("buying_power") is not None:
        lines.append("=== LIVE ACCOUNT STATE (from Alpaca) ===")
        lines.append(f"  Equity:       ${account_state['equity']:,.2f}")
        lines.append(f"  Cash:         ${account_state['cash']:,.2f}")
        lines.append(f"  Buying Power: ${account_state['buying_power']:,.2f}")
        held = account_state.get("held_symbols", [])
        if held:
            lines.append(f"  Held Symbols: {', '.join(held)}")
            for sym, val in account_state.get("held_values", {}).items():
                lines.append(f"    {sym}: ${val:,.2f}")
        else:
            lines.append("  Held Symbols: NONE (fully in cash)")
        lines.append("")

    if not crypto_only:
        lines.append("=== MACROECONOMIC INDICATORS (FRED) ===")
        for sid, v in macro_data.items():
            if v.get("value") is not None:
                lines.append(f"  {v['name']}: {v['value']} (as of {v['date']})")

    if crypto_only:
        lines.append("=== CRYPTO MARKET PRICES & MOMENTUM (24/7) ===")
    else:
        lines.append("\n=== MARKET PRICES & MOMENTUM ===")

    for cat, tickers in market_data.get("by_category", {}).items():
        lines.append(f"  [{cat.upper()}]")
        for ticker, d in tickers.items():
            if "error" not in d:
                lines.append(
                    f"    {ticker}: ${d['latest_price']:.2f} | "
                    f"1d={d['return_1d_pct']:+.1f}% | "
                    f"20d={d.get('return_20d_pct', 0):+.1f}% | "
                    f"vol={d.get('annualized_volatility_20d_pct', 0):.1f}%"
                )

    lines.append("\n=== RECENT NEWS HEADLINES ===")
    for headline in news_headlines[:15]:
        lines.append(f"  • {headline}")

    if crypto_only:
        lines.append("\nMODE: CRYPTO-ONLY (stock market closed). Allocate 6 slots using crypto pairs only.")

    return "\n".join(lines)
