"""
Groq LLM Client — Regime-Switching Architecture
-------------------------------------------------
Uses Groq API (llama-3.3-70b-versatile) as the reasoning engine.

The user prompt now surfaces momentum signals (3-month MA, 6-month MA)
prominently so the LLM can apply the Bull/Bear/Sideways allocation rules.
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
    client = _get_client()
    logger.info(f"Groq | Sending request to {MODEL} (temp={temperature})")

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
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


def _momentum_badge(d: dict) -> str:
    m3 = d.get("momentum_3mo", "?")
    m6 = d.get("momentum_6mo", "?")
    tag3 = "↑" if m3 == "positive" else ("↓" if m3 == "negative" else "~")
    tag6 = "↑" if m6 == "positive" else ("↓" if m6 == "negative" else "~")
    ma3  = d.get("ma_3mo")
    ma6  = d.get("ma_6mo")
    ma3s = f" MA3m=${ma3:.2f}" if ma3 else ""
    ma6s = f" MA6m=${ma6:.2f}" if ma6 else ""
    return f"3m:{tag3}{ma3s} | 6m:{tag6}{ma6s}"


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

    if not crypto_only and macro_data:
        lines.append("=== MACROECONOMIC INDICATORS (FRED) ===")
        for sid, v in macro_data.items():
            if v.get("value") is not None:
                lines.append(f"  {v['name']}: {v['value']} (as of {v['date']})")
        lines.append("")

    if crypto_only:
        lines.append("=== CRYPTO MOMENTUM & PRICE DATA ===")
    else:
        lines.append("=== ASSET UNIVERSE — PRICE & MOMENTUM SIGNALS ===")
        lines.append("(Use momentum signals as HARD FILTER per allocation rules)")
        lines.append("")

    any_overheated = False
    for cat, tickers in market_data.get("by_category", {}).items():
        if cat == "cash":
            continue
        lines.append(f"  [{cat.upper()}]")
        for ticker, d in tickers.items():
            if "error" not in d:
                mom = _momentum_badge(d)
                z   = d.get("z_score_200d")
                rsi = d.get("rsi_14d")
                heat_parts = []
                if z is not None:
                    heat_parts.append(f"Z={z:+.2f}")
                if rsi is not None:
                    heat_parts.append(f"RSI={rsi:.1f}")
                heat_str = " | " + " ".join(heat_parts) if heat_parts else ""
                overheat_flag = ""
                if d.get("is_overheated"):
                    overheat_flag = " ⚠️ OVERHEATED"
                    any_overheated = True
                lines.append(
                    f"    {ticker:10s}: ${d['latest_price']:.2f} | "
                    f"1d={d['return_1d_pct']:+.1f}% | "
                    f"60d={d.get('return_60d_pct', 0):+.1f}% | "
                    f"vol={d.get('annualized_volatility_20d_pct', 0):.1f}%"
                    f"{heat_str} | {mom}{overheat_flag}"
                )
            else:
                lines.append(f"    {ticker:10s}: DATA UNAVAILABLE ({d['error']})")
        lines.append("")

    if any_overheated:
        lines.append("⚠️  OVERHEATED ASSET RULE: Z-Score > 2.0 OR RSI > 75 signals irrational exuberance.")
        lines.append("   → Lower conviction scores for overheated assets. Prefer rotating to SGOV or uncorrelated safe havens.")
        lines.append("   → The execution engine will automatically cut any overheated allocation by 50% as a hard guard.")
        lines.append("")

    lines.append("=== RECENT NEWS HEADLINES ===")
    for headline in news_headlines[:15]:
        lines.append(f"  • {headline}")
    lines.append("")

    if crypto_only:
        lines.append("MODE: CRYPTO-ONLY (stock market closed).")
        lines.append("Only trade BTC/USD, ETH/USD, ATOM/USD with positive momentum. Default to SGOV if low conviction.")
    else:
        lines.append("TASK: Classify regime (Bull/Bear/Sideways), apply momentum filter, then output allocations.")
        lines.append("Remember: NEVER FORCE A TRADE. If no high-conviction setup exists → 100% SGOV.")

    return "\n".join(lines)
