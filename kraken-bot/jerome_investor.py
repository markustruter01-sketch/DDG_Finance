"""
jerome_investor.py — Groq LLM commodity macro investment engine for Jerome (#3).

Jerome analyses macro conditions and commodity price action twice daily,
then decides which commodity ETFs to buy or sell on a separate Alpaca account.
Holds positions 2-21 days. Pure macro investment — not scalping.

Named Jerome because he trades on Fed policy like he IS the Fed.

Uses raw Groq SDK (llama-3.3-70b-versatile) with fallback to the shared
analysis.groq_client wrapper (Gemini) if the Groq SDK fails in this environment.
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("jerome.investor")

_GROQ_MODEL    = "llama-3.3-70b-versatile"
_MAX_RETRIES   = 2
_MAX_POSITIONS = 3


def get_commodity_decisions(
    context: dict,
    equity: float,
    open_positions: list[dict],
    config: dict,
) -> dict:
    """
    Send commodity market context to Groq and get investment decisions.
    Returns validated decision dict or empty decisions on failure.
    """
    prompt = _build_prompt(context, equity, open_positions, config)
    raw = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            raw = _call_groq(prompt)
            decisions = _parse_and_validate(raw, config)
            if decisions:
                logger.info(
                    f"Jerome | Groq returned {len(decisions.get('enter', []))} "
                    f"entries and {len(decisions.get('close', []))} closes "
                    f"(attempt {attempt})"
                )
                _persist_decision(decisions, raw)
                return decisions
        except Exception as exc:
            logger.warning(f"Jerome | Attempt {attempt} failed: {exc}")

    logger.error("Jerome | All Groq attempts failed — skipping cycle")
    return {"enter": [], "close": [], "reasoning": "groq_unavailable",
            "market_regime": "unknown", "usd_bias": "neutral",
            "inflation_bias": "neutral", "risk_appetite": "neutral"}


def _build_prompt(
    context: dict,
    equity: float,
    open_positions: list[dict],
    config: dict,
) -> str:
    ts       = context.get("timestamp", "unknown")
    macro    = context.get("macro_indicators", {})
    prices   = context.get("commodity_prices", {})
    themes   = config.get("COMMODITY_THEMES", {})
    max_pos  = config.get("MAX_POSITIONS", 3)
    min_conv = config.get("MIN_CONVICTION", 0.65)

    if open_positions:
        pos_lines = []
        for p in open_positions:
            pos_lines.append(
                f"  - {p.get('symbol')} {p.get('direction','long').upper()} | "
                f"entry=${p.get('entry_price', 0):.2f} | "
                f"unrealised={p.get('unrealised_pct', 0):+.2f}% | "
                f"held {p.get('days_held', 0):.1f}d | "
                f"theme={p.get('theme', 'unknown')}"
            )
        pos_text = "\n".join(pos_lines)
    else:
        pos_text = "  None — fully in cash"

    macro_lines = []
    for name, data in macro.items():
        macro_lines.append(
            f"  {name:<8} "
            f"price={data.get('price', '?')} | "
            f"1d={data.get('return_1d', 0):+.2f}% | "
            f"5d={data.get('return_5d', 0):+.2f}% | "
            f"trend={data.get('trend', '?')}"
        )
    macro_text = "\n".join(macro_lines) if macro_lines else "  Unavailable"

    price_lines = []
    for theme, symbols in themes.items():
        price_lines.append(f"\n  [{theme.upper()}]")
        for sym in symbols:
            data = prices.get(sym, {})
            if data:
                price_lines.append(
                    f"    {sym:<6} "
                    f"${data.get('price', 0):.2f} | "
                    f"1d={data.get('return_1d', 0):+.2f}% | "
                    f"5d={data.get('return_5d', 0):+.2f}% | "
                    f"20d={data.get('return_20d', 0):+.2f}% | "
                    f"range_pos={data.get('vs_30d_range', 50):.0f}%"
                )
    price_text = "\n".join(price_lines) if price_lines else "  Unavailable"

    return f"""You are Jerome, a professional commodity macro portfolio manager making SHORT-TERM INVESTMENT decisions (holding 2-21 days).

You are NOT a day trader. You invest in commodity themes based on macroeconomic conditions.
Your edge is reading macro signals (Fed policy, USD strength, risk appetite, inflation) and
translating them into commodity ETF positions.

Current time: {ts} UTC
Portfolio equity: ${equity:,.2f}
Maximum positions: {max_pos} (max 1 per commodity theme)
Minimum conviction to enter: {min_conv}

CURRENT OPEN POSITIONS:
{pos_text}

MACRO ENVIRONMENT:
{macro_text}

COMMODITY PRICES BY THEME:
{price_text}

YOUR MACRO FRAMEWORK:
- USD STRENGTH → bearish gold/silver, bearish oil (dollar-denominated)
- USD WEAKNESS → bullish gold/silver, bullish oil
- RISK-OFF (VIX rising, SPY falling) → bullish gold, bearish oil/industrial metals
- RISK-ON (VIX falling, SPY rising) → bullish energy/industrial, neutral gold
- FED HAWKISH → USD up → gold down, energy mixed
- FED DOVISH → USD down → gold up, energy up
- INFLATION RISING (TNX up, TIP up) → bullish all commodities
- RECESSION FEARS → bullish gold, bearish oil/industrial/agriculture

STRICT RULES:
1. Maximum 1 position per theme (precious_metals, energy, agriculture, industrial)
2. Only enter when macro thesis is CLEAR — if uncertain, hold cash
3. Conviction below {min_conv} = no trade
4. Never hold opposing positions (no long GLD and short SLV simultaneously)
5. Consider closing existing positions if the macro thesis has changed
6. Cash is a valid position — 0 entries is often correct

AVAILABLE INSTRUMENTS:
- Precious metals: GLD, SLV, GDX, GDXJ, PPLT
- Energy: USO, BNO, UNG, XLE, OIH
- Agriculture: DBA, WEAT, CORN, SOYB, JO
- Industrial/Broad: COPX, JJC, PDBC, GSG, DJP

Respond ONLY with valid JSON. No text outside the JSON:

{{
  "market_regime": "one sentence macro environment summary",
  "usd_bias": "bullish",
  "inflation_bias": "rising",
  "risk_appetite": "risk_on",
  "enter": [
    {{
      "symbol": "GLD",
      "direction": "long",
      "theme": "precious_metals",
      "conviction": 0.75,
      "position_size_pct": 0.15,
      "stop_loss_pct": 0.04,
      "take_profit_pct": 0.08,
      "max_hold_days": 10,
      "thesis": "one sentence macro thesis"
    }}
  ],
  "close": [
    {{
      "symbol": "GLD",
      "reason": "one sentence reason to close early"
    }}
  ],
  "reasoning": "2-3 sentence overall macro view and why these decisions"
}}"""


def _call_groq(prompt: str) -> str:
    """
    Call Groq API (llama-3.3-70b-versatile).
    Tries raw Groq SDK first; falls back to shared call_groq wrapper (Gemini)
    if the SDK fails with a proxies/environment error.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")

    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            response = client.chat.completions.create(
                model=_GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1024,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning(f"Jerome | Groq SDK failed ({exc}) — falling back to Gemini wrapper")

    _ensure_tp_path()
    from analysis.groq_client import call_groq
    return call_groq(
        system_prompt=(
            "You are Jerome, a commodity macro portfolio manager. "
            "Respond ONLY with valid JSON as instructed."
        ),
        user_prompt=prompt,
        temperature=0.2,
        max_tokens=1024,
        call_type="jerome_commodity",
        json_mode=True,
    )


def _ensure_tp_path() -> None:
    tp = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform"))
    if tp not in sys.path:
        sys.path.insert(0, tp)


def _parse_and_validate(raw: str, config: dict) -> Optional[dict]:
    """Parse and validate Groq JSON response."""
    clean = raw.strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()

    decisions = json.loads(clean)

    universe     = set(config.get("COMMODITY_UNIVERSE", []))
    themes_map   = config.get("COMMODITY_THEMES", {})
    symbol_theme = {s: theme for theme, syms in themes_map.items() for s in syms}

    min_conv    = config.get("MIN_CONVICTION", 0.65)
    themes_used = set()
    validated   = []

    for entry in decisions.get("enter", []):
        sym       = str(entry.get("symbol", "")).upper()
        direction = str(entry.get("direction", "long")).lower()
        try:
            conviction = float(entry.get("conviction", 0))
            size_pct   = float(entry.get("position_size_pct", 0.10))
            sl_pct     = float(entry.get("stop_loss_pct", 0.04))
            tp_pct     = float(entry.get("take_profit_pct", 0.08))
            hold_days  = int(entry.get("max_hold_days", 7))
        except (TypeError, ValueError) as exc:
            logger.warning(f"Jerome | Skipping entry with bad numeric fields: {entry} — {exc}")
            continue

        theme = str(entry.get("theme") or symbol_theme.get(sym, "unknown"))

        if sym not in universe:
            logger.warning(f"Jerome | Rejected unknown symbol: {sym}")
            continue
        if direction not in ("long", "short"):
            logger.warning(f"Jerome | Rejected invalid direction: {direction!r}")
            continue
        if conviction < min_conv:
            logger.info(f"Jerome | Rejected low conviction: {sym} {conviction:.2f}")
            continue
        if theme in themes_used:
            logger.info(f"Jerome | Rejected duplicate theme {theme}: {sym}")
            continue
        if tp_pct < sl_pct * 1.5:
            logger.warning(f"Jerome | Rejected poor R:R for {sym}: tp={tp_pct:.3f} sl={sl_pct:.3f}")
            continue

        size_pct  = max(0.05, min(0.20, size_pct))
        sl_pct    = max(0.02, min(0.06, sl_pct))
        tp_pct    = max(0.04, min(0.12, tp_pct))
        hold_days = max(2, min(21, hold_days))

        themes_used.add(theme)
        validated.append({
            "symbol":            sym,
            "direction":         direction,
            "theme":             theme,
            "conviction":        round(conviction, 2),
            "position_size_pct": round(size_pct, 3),
            "stop_loss_pct":     round(sl_pct, 3),
            "take_profit_pct":   round(tp_pct, 3),
            "max_hold_days":     hold_days,
            "thesis":            str(entry.get("thesis", ""))[:200],
        })
        if len(validated) >= _MAX_POSITIONS:
            break

    decisions["enter"] = validated

    logger.info(f"Jerome | regime={str(decisions.get('market_regime','?'))[:80]}")
    logger.info(
        f"Jerome | usd_bias={decisions.get('usd_bias')} "
        f"inflation={decisions.get('inflation_bias')} "
        f"risk={decisions.get('risk_appetite')}"
    )
    for e in validated:
        logger.info(
            f"Jerome | ENTER {e['symbol']} {e['direction'].upper()} "
            f"theme={e['theme']} conviction={e['conviction']} "
            f"sl={e['stop_loss_pct']*100:.1f}% tp={e['take_profit_pct']*100:.1f}% "
            f"hold={e['max_hold_days']}d | {e['thesis']}"
        )
    logger.info(f"Jerome | reasoning: {decisions.get('reasoning','')}")

    return decisions


def _persist_decision(decisions: dict, raw: str) -> None:
    """Persist Jerome's decision to DB for audit trail."""
    try:
        _ensure_tp_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jerome_groq_decisions
                        (market_regime, usd_bias, inflation_bias,
                         risk_appetite, reasoning,
                         entries_count, closes_count,
                         raw_response, entries_json, closes_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    str(decisions.get("market_regime", ""))[:200],
                    decisions.get("usd_bias", ""),
                    decisions.get("inflation_bias", ""),
                    decisions.get("risk_appetite", ""),
                    str(decisions.get("reasoning", ""))[:500],
                    len(decisions.get("enter", [])),
                    len(decisions.get("close", [])),
                    raw[:5000],
                    json.dumps(decisions.get("enter", [])),
                    json.dumps(decisions.get("close", [])),
                ))
            conn.commit()
        logger.info("Jerome | Decision persisted to DB")
    except Exception as exc:
        logger.debug(f"Jerome | DB persist failed (non-fatal): {exc}")
