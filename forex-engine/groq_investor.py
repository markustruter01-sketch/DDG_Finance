"""
groq_investor.py — Gemini LLM investment decision engine for Navigator.

Uses the shared analysis.groq_client.call_groq() wrapper (which routes through
Gemini via the Replit AI Integration proxy — named 'call_groq' for backwards
compatibility with the existing codebase).

Analyses market context and returns structured JSON with:
- Which pairs to enter (long or short)
- Conviction level per trade
- Investment thesis per trade
- Which existing positions to close early

Called twice daily: 08:00 UTC (Asian/European open) and 20:00 UTC (US close/Asian prep).
Holds positions for days to weeks — not intraday scalping.
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("navigator.groq_investor")

_MAX_POSITIONS = 3
_MAX_RETRIES   = 2

# Ensure trading-platform is on sys.path so we can import analysis.groq_client
def _ensure_tp_path() -> None:
    import os as _os
    _engine_dir = _os.path.dirname(_os.path.abspath(__file__))
    _tp = _os.path.join(_engine_dir, "..", "trading-platform")
    _tp = _os.path.normpath(_tp)
    if _tp not in sys.path:
        sys.path.insert(0, _tp)

_ensure_tp_path()


def get_investment_decisions(
    context: dict,
    equity: float,
    max_positions: int = _MAX_POSITIONS,
) -> dict:
    """
    Send market context to Gemini (via call_groq wrapper) and get investment decisions.
    Returns a validated decision dict, or empty decisions on failure.

    Return schema:
        {
          "market_regime": str,
          "usd_bias": "bullish"|"bearish"|"neutral",
          "enter": [ {pair, direction, conviction, position_size_pct,
                      stop_loss_pips, take_profit_pips, max_hold_days, thesis} ],
          "close": [ {pair, reason} ],
          "reasoning": str,
        }
    """
    system_prompt, user_prompt = _build_prompts(context, equity, max_positions)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            raw = _call_llm(system_prompt, user_prompt)
            decisions = _parse_and_validate(raw, context)
            if decisions is not None:
                logger.info(
                    f"GroqInvestor | Got {len(decisions.get('enter', []))} entries "
                    f"and {len(decisions.get('close', []))} closes on attempt {attempt}"
                )
                return decisions
        except Exception as exc:
            logger.warning(f"GroqInvestor | Attempt {attempt} failed: {exc}")

    logger.error("GroqInvestor | All attempts failed — returning empty decisions")
    return {"enter": [], "close": [], "reasoning": "llm_unavailable",
            "market_regime": "unknown", "usd_bias": "neutral"}


def _build_prompts(context: dict, equity: float, max_positions: int) -> tuple[str, str]:
    """Build system + user prompt pair for the Gemini/call_groq interface."""
    ts       = context.get("timestamp", "unknown")
    pairs    = context.get("forex_pairs", {})
    macro    = context.get("macro_indicators", {})
    open_pos = context.get("open_positions", [])
    errors   = context.get("errors", [])

    system_prompt = (
        "You are a professional forex macro investment manager making SHORT-TERM INVESTMENT "
        "decisions (holding 2-14 days). You are NOT a scalper or day trader. You invest in "
        "currency trends based on macro themes. You ALWAYS respond with valid JSON only — "
        "no preamble, no explanation outside the JSON object."
    )

    pos_text = "None currently open."
    if open_pos:
        lines = []
        for p in open_pos:
            lines.append(
                f"  - {p.get('pair')} {str(p.get('direction', '')).upper()} | "
                f"entry={p.get('entry_price')} | "
                f"unrealised P&L=${p.get('unrealised_pnl_usd', 0):.2f} | "
                f"held {p.get('hours_held', 0):.0f}h"
            )
        pos_text = "\n".join(lines)

    pair_lines = []
    for name, data in pairs.items():
        pair_lines.append(
            f"  {name:<12} price={data.get('price')} | "
            f"1d={data.get('return_1d') or 0:+.2f}% | "
            f"5d={data.get('return_5d') or 0:+.2f}% | "
            f"20d={data.get('return_20d') or 0:+.2f}% | "
            f"30d-range-pos={data.get('vs_30d_range', 50):.0f}%"
        )
    pair_text = "\n".join(pair_lines) if pair_lines else "  (no pair data available this cycle)"

    macro_lines = []
    for name, data in macro.items():
        macro_lines.append(
            f"  {name:<6} price={data.get('price')} | "
            f"5d={data.get('return_5d') or 0:+.2f}% | "
            f"trend={data.get('trend')}"
        )
    macro_text = "\n".join(macro_lines) if macro_lines else "  (no macro data available this cycle)"

    data_warnings = ""
    if errors:
        data_warnings = f"\nDATA WARNINGS (some feeds failed): {', '.join(errors[:5])}\n"

    user_prompt = f"""Current time: {ts}
Portfolio equity: ${equity:,.2f}
Maximum simultaneous positions: {max_positions}

CURRENT OPEN POSITIONS:
{pos_text}

FOREX PAIR PRICES AND RETURNS:
{pair_text}

MACRO INDICATORS:
{macro_text}
{data_warnings}
INVESTMENT PHILOSOPHY:
- Only enter when there is a clear macro thesis (USD strength/weakness, risk-on/off, carry trade dynamics)
- Prefer pairs showing consistent directional momentum (5d and 20d returns aligned)
- Avoid pairs near 30d highs/lows unless momentum is extremely strong
- Maximum 1 position per correlated pair group (don't hold EUR/USD and EUR/GBP simultaneously)
- If unsure, hold cash. 0 entries is a valid and often correct decision
- Consider closing existing positions if thesis has changed or target is near

POSITION SIZING RULES (strictly follow):
- Maximum 20% of equity per position, minimum 10%
- Minimum conviction score 0.6 to enter
- Stop loss: 30-200 pips. Take profit: 50-400 pips. Ratio >= 1.5:1 (TP/SL)

Respond ONLY with valid JSON matching this exact schema:

{{
  "market_regime": "string describing overall macro environment in 1 sentence",
  "usd_bias": "bullish",
  "enter": [
    {{
      "pair": "EUR/USD",
      "direction": "long",
      "conviction": 0.75,
      "position_size_pct": 0.15,
      "stop_loss_pips": 50,
      "take_profit_pips": 100,
      "max_hold_days": 7,
      "thesis": "one sentence macro thesis"
    }}
  ],
  "close": [
    {{
      "pair": "EUR/USD",
      "reason": "one sentence reason to close early"
    }}
  ],
  "reasoning": "2-3 sentence overall market view and why these decisions were made"
}}"""

    return system_prompt, user_prompt


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call Gemini via the shared analysis.groq_client wrapper."""
    from analysis.groq_client import call_groq
    return call_groq(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=2048,
        call_type="navigator_invest",
        json_mode=True,
    )


def _parse_and_validate(raw: str, context: dict) -> Optional[dict]:
    """Parse LLM JSON response and validate all fields. Returns None on hard failure."""
    clean = raw.strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()

    decisions = json.loads(clean)

    valid_pairs      = set(context.get("forex_pairs", {}).keys())
    valid_directions = {"long", "short"}
    valid_usd_bias   = {"bullish", "bearish", "neutral"}

    usd_bias = str(decisions.get("usd_bias", "neutral")).lower()
    if usd_bias not in valid_usd_bias:
        usd_bias = "neutral"
    decisions["usd_bias"] = usd_bias

    validated_entries: list[dict] = []
    for entry in decisions.get("enter", []):
        pair      = str(entry.get("pair", ""))
        direction = str(entry.get("direction", "")).lower()
        try:
            conviction = float(entry.get("conviction", 0))
            size_pct   = float(entry.get("position_size_pct", 0.15))
            sl_pips    = int(entry.get("stop_loss_pips", 0))
            tp_pips    = int(entry.get("take_profit_pips", 0))
            hold_days  = int(entry.get("max_hold_days", 7))
        except (TypeError, ValueError) as exc:
            logger.warning(f"GroqInvestor | Skipping entry with bad numeric fields: {entry} — {exc}")
            continue

        if pair not in valid_pairs:
            logger.warning(f"GroqInvestor | Rejected unknown pair: {pair!r}")
            continue
        if direction not in valid_directions:
            logger.warning(f"GroqInvestor | Rejected invalid direction: {direction!r}")
            continue
        if conviction < 0.6:
            logger.info(f"GroqInvestor | Rejected low-conviction: {pair} conviction={conviction:.2f}")
            continue
        if sl_pips <= 0 or tp_pips <= 0:
            logger.warning(f"GroqInvestor | Rejected missing stops: {pair} sl={sl_pips} tp={tp_pips}")
            continue
        if sl_pips > 500:
            logger.warning(f"GroqInvestor | Rejected excessive stop: {pair} sl={sl_pips}pips")
            continue
        if tp_pips / sl_pips < 1.0:
            logger.info(f"GroqInvestor | Rejected poor R:R: {pair} tp/sl={tp_pips/sl_pips:.2f}")
            continue

        size_pct  = max(0.05, min(0.20, size_pct))
        hold_days = max(2, min(14, hold_days))

        validated_entries.append({
            "pair":              pair,
            "direction":         direction,
            "conviction":        round(conviction, 2),
            "position_size_pct": round(size_pct, 3),
            "stop_loss_pips":    sl_pips,
            "take_profit_pips":  tp_pips,
            "max_hold_days":     hold_days,
            "thesis":            str(entry.get("thesis", ""))[:200],
        })

    decisions["enter"] = validated_entries[:_MAX_POSITIONS]

    logger.info(f"GroqInvestor | market_regime: {decisions.get('market_regime', '?')}")
    logger.info(f"GroqInvestor | usd_bias: {decisions.get('usd_bias', '?')}")
    logger.info(f"GroqInvestor | entries={len(decisions['enter'])} closes={len(decisions.get('close', []))}")
    for e in decisions["enter"]:
        logger.info(
            f"GroqInvestor | ENTER {e['pair']} {e['direction'].upper()} "
            f"conviction={e['conviction']} sl={e['stop_loss_pips']}p "
            f"tp={e['take_profit_pips']}p hold={e['max_hold_days']}d | {e['thesis']}"
        )
    logger.info(f"GroqInvestor | reasoning: {decisions.get('reasoning', '')}")

    return decisions
