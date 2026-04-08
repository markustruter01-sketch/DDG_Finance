"""
LLM Client — Regime-Switching Architecture
-------------------------------------------
Routes all calls through Gemini via the Replit AI Integration proxy
(AI_INTEGRATIONS_GEMINI_BASE_URL / AI_INTEGRATIONS_GEMINI_API_KEY).
Falls back to the direct Google API (GOOGLE_GEMINI_API_KEY) if the
integration vars are absent.

Public interface is identical to the old Groq-backed version so no
callers need to change.
"""

import json

import requests
from loguru import logger

from analysis.groq_budget import budget as _budget
from analysis.input_sanitizer import sanitize_news_payload

_GEMINI_FALLBACK_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-3-flash-preview"


def _base_url() -> str:
    import os
    return os.environ.get("AI_INTEGRATIONS_GEMINI_BASE_URL") or _GEMINI_FALLBACK_BASE


def _api_key() -> str:
    import os
    key = (
        os.environ.get("AI_INTEGRATIONS_GEMINI_API_KEY")
        or os.environ.get("GOOGLE_GEMINI_API_KEY", "")
    )
    if not key:
        raise RuntimeError(
            "No Gemini API key available — set AI_INTEGRATIONS_GEMINI_API_KEY or GOOGLE_GEMINI_API_KEY"
        )
    return key


def call_groq(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    call_type: str = "unknown",
    json_mode: bool = True,
) -> str:
    """
    Send a request to Gemini and return the response text.

    Keeps the same signature as the old call_groq() so all callers work unchanged.
    `json_mode=True` requests JSON output via Gemini's responseMimeType.
    """
    api_key = _api_key()
    url = f"{_base_url()}/models/{MODEL}:generateContent"

    generation_config: dict = {
        # Gemini's reasoning uses output-token headroom; enforce a floor of 8192
        # so the model never exhausts its budget before writing the actual JSON body.
        "maxOutputTokens": max(max_tokens, 8192),
        "temperature": temperature,
    }
    if json_mode:
        generation_config["responseMimeType"] = "application/json"

    body = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "generationConfig": generation_config,
    }

    logger.info(f"Gemini | Sending request to {MODEL} (temp={temperature}, type={call_type})")

    try:
        resp = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json=body,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Gemini HTTP request failed: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini returned HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        usage = data.get("usageMetadata", {})
        total_tokens = (
            usage.get("totalTokenCount")
            or (usage.get("promptTokenCount", 0) + usage.get("candidatesTokenCount", 0))
        )
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        logger.info(
            f"Gemini | Response received [{call_type}] — "
            f"prompt_tokens={usage.get('promptTokenCount', '?')} "
            f"completion_tokens={usage.get('candidatesTokenCount', '?')} "
            f"total={total_tokens}"
        )
        _budget.consume(total_tokens or 0, call_type=call_type)
        return content
    except (KeyError, IndexError, ValueError) as exc:
        raise RuntimeError(f"Unexpected Gemini response structure: {exc}") from exc


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
    algo_short_context: dict | None = None,
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
        # ── REGIME SIGNALS — key three-condition gate for Bull/Sideways/Bear ──
        try:
            from data.yfinance_client import get_spy_ema_anchor as _spy_anchor
            _spy = _spy_anchor()
            _vix_val: float | None = None
            if macro_data:
                for _sid, _mv in macro_data.items():
                    if "VIX" in _mv.get("name", "").upper() or _sid == "VIXCLS":
                        try:
                            _vix_val = float(_mv["value"])
                        except (TypeError, ValueError):
                            pass
                        break
            lines.append("=== REGIME SIGNALS (apply mechanically to determine Bull/Sideways/Bear) ===")
            if _vix_val is not None:
                if _vix_val < 20:
                    _vix_label = "LOW (<20) → Bull condition MET"
                elif _vix_val <= 30:
                    _vix_label = f"ELEVATED (20–30) → Sideways condition MET (NOT Bear)"
                else:
                    _vix_label = f"HIGH (>30) → Bear condition MET"
                lines.append(f"  VIX: {_vix_val:.1f}  [{_vix_label}]")
            else:
                lines.append("  VIX: unavailable")
            _spy_price  = _spy.get("spy_price")
            _spy_sma_50 = _spy.get("spy_sma_50d")
            _spy_ret_20 = _spy.get("spy_ret_20d")
            _above_sma  = _spy.get("spy_above_sma_50")
            if _spy_price is not None:
                _ret_str   = f"{_spy_ret_20:+.2f}%" if _spy_ret_20 is not None else "n/a"
                _ret_label = ("POSITIVE → Bull/Sideways condition MET" if (_spy_ret_20 or 0) >= 0
                              else "NEGATIVE → Bear condition MET")
                lines.append(f"  SPY 20-day return: {_ret_str}  [{_ret_label}]")
                if _spy_sma_50 is not None:
                    _sma_label = ("ABOVE SMA-50 → Bull/Sideways condition MET" if _above_sma
                                  else "BELOW SMA-50 → Bear condition MET")
                    lines.append(
                        f"  SPY vs 50-day SMA: ${_spy_price:.2f} vs SMA-50 ${_spy_sma_50:.2f}  [{_sma_label}]"
                    )
            # Derived regime assessment
            _bear_all  = (_vix_val is not None and _vix_val > 30
                          and (_spy_ret_20 or 0) < 0
                          and _above_sma is False)
            _bull_all  = (_vix_val is not None and _vix_val < 20
                          and (_spy_ret_20 or 0) >= 0
                          and _above_sma is True)
            if _bear_all:
                _regime_assess = "→ BEAR (all three Bear conditions confirmed)"
            elif _bull_all:
                _regime_assess = "→ BULL (all three Bull conditions confirmed)"
            else:
                _regime_assess = "→ SIDEWAYS (not all Bear or all Bull conditions met simultaneously)"
            lines.append(f"  Regime assessment: {_regime_assess}")
            lines.append("")
        except Exception as _exc:
            lines.append(f"  [Regime signals unavailable: {_exc}]")
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

    if algo_short_context and algo_short_context.get("activated"):
        lines.append("=== ALGORITHMIC SHORT SCANNER REPORT (Bear/RISK-OFF) ===")
        open_shorts = algo_short_context.get("open_shorts", [])
        if open_shorts:
            lines.append("  Active algo shorts (do NOT buy these ETFs as longs):")
            for s in open_shorts:
                sym   = s.get("symbol", "?")
                qty   = s.get("qty", 0)
                ep    = s.get("entry_price", 0.0)
                cp    = s.get("current_price", 0.0)
                pl    = s.get("unrealized_pl", 0.0)
                plpc  = s.get("unrealized_plpc", 0.0)
                exp   = s.get("exposure_pct", 0.0)
                lines.append(
                    f"    SHORT {sym}: qty={qty} entry=${ep:.2f} now=${cp:.2f} "
                    f"P&L=${pl:+.2f} ({plpc:+.1f}%) exposure={exp:.1f}%"
                )
        else:
            lines.append("  No active algo short positions at this time.")
        exp_usd = algo_short_context.get("short_exposure_usd", 0.0)
        exp_pct = algo_short_context.get("short_exposure_pct", 0.0)
        lines.append(f"  Total short exposure: ${exp_usd:,.0f} ({exp_pct:.1f}% of equity)")
        lines.append(
            "  NOTE: The short scanner runs INDEPENDENTLY. "
            "Do not include SPY/QQQ/XLK/XLF/XLE/IWM as direct short allocations — "
            "use bear_hedge ETFs (SH, PSQ, DOG, SPXS, SQQQ, SRTY) instead."
        )
        lines.append("")

    clean_headlines = sanitize_news_payload(news_headlines, cap=15)
    lines.append("=== RECENT NEWS HEADLINES ===")
    for headline in clean_headlines:
        lines.append(f"  • {headline}")
    lines.append("")

    if crypto_only:
        lines.append("MODE: CRYPTO-ONLY (stock market closed).")
        lines.append("Only trade BTC/USD or ETH/USD with positive momentum. Default to SGOV if low conviction. Do NOT use ATOM/USD.")
        lines.append("Output your response as valid json.")
    else:
        lines.append("TASK: Classify regime (Bull/Bear/Sideways), apply momentum filter, then output allocations.")
        lines.append("Remember: NEVER FORCE A TRADE. If no high-conviction setup exists → 100% SGOV.")
        lines.append("Output your response as valid json.")

    return "\n".join(lines)
