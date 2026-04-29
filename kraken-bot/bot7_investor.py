"""
bot7_investor.py — Groq LLM fixed income macro investment engine for Bot #7.

Bot #7 (Macro Bond Trader) analyses Treasury yield environment, inflation
expectations, credit conditions, and USD direction twice daily, then decides
which bond ETFs to buy or sell.

Holds positions 14–60 days. Pure macro fixed income investing — not scalping.

Universe: TLT (20Y Treasuries), IEF (7-10Y), SHY (1-3Y / rate hedge),
          TIP (TIPS / inflation), HYG (high yield), LQD (IG corporate), EMB (EM bonds)

Follows jerome_investor.py exactly — same Groq SDK call pattern, same
validation, same persistence (to macro_bond_decisions table).
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("bot7.investor")

_GROQ_MODEL    = "llama-3.3-70b-versatile"
_MAX_RETRIES   = 2

UNIVERSE = ["TLT", "IEF", "SHY", "TIP", "HYG", "LQD", "EMB"]

MIN_CONVICTION        = 0.65
MAX_POSITIONS         = 3
POSITION_SIZE_MIN_PCT = 0.10
POSITION_SIZE_MAX_PCT = 0.30
MIN_HOLD_DAYS         = 14
MAX_HOLD_DAYS         = 60


def get_bond_decisions(
    context: dict,
    equity: float,
    open_positions: list[dict],
    config: dict,
) -> dict:
    """
    Send macro bond context to Groq and get investment decisions.
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
                    f"Bot7 | Groq returned {len(decisions.get('enter', []))} entries "
                    f"and {len(decisions.get('close', []))} closes (attempt {attempt})"
                )
                _persist_decision(decisions, raw)
                return decisions
        except Exception as exc:
            logger.warning(f"Bot7 | Attempt {attempt} failed: {exc}")

    logger.error("Bot7 | All Groq attempts failed — skipping cycle")
    return {
        "enter": [], "close": [],
        "reasoning": "groq_unavailable",
        "rate_environment": "unknown",
        "duration_bias": "neutral",
        "inflation_view": "neutral",
        "credit_bias": "neutral",
    }


def _build_prompt(
    context: dict,
    equity: float,
    open_positions: list[dict],
    config: dict,
) -> str:
    ts       = context.get("timestamp", "unknown")
    macro    = context.get("macro_indicators", {})
    bonds    = context.get("bond_prices", {})
    yields   = context.get("yield_environment", {})

    min_conv  = config.get("MIN_CONVICTION",    MIN_CONVICTION)
    max_pos   = config.get("MAX_POSITIONS",      MAX_POSITIONS)
    min_hold  = config.get("MIN_HOLD_DAYS",      MIN_HOLD_DAYS)
    max_hold  = config.get("MAX_HOLD_DAYS",      MAX_HOLD_DAYS)
    size_min  = config.get("POSITION_SIZE_MIN",  POSITION_SIZE_MIN_PCT)
    size_max  = config.get("POSITION_SIZE_MAX",  POSITION_SIZE_MAX_PCT)

    # Format open positions
    if open_positions:
        pos_lines = [
            f"  - {p['symbol']} {p.get('direction','long').upper()} | "
            f"entry=${p.get('entry_price',0):.2f} | "
            f"unrealised={p.get('unrealised_pct',0):+.2f}%"
            for p in open_positions
        ]
        pos_text = "\n".join(pos_lines)
    else:
        pos_text = "  None — fully in cash"

    # Format yield environment
    y10 = yields.get("yield_10y", {})
    curve = yields.get("curve_shape", {})
    infl  = yields.get("inflation_expectations", {})
    credit = yields.get("credit_conditions", {})

    yield_text = f"""  10Y Yield:     {y10.get('current','?'):.2%} | 30d change: {y10.get('change_30d_bp','?')}bp | trend: {y10.get('trend','?')}
  Curve (TLT-SHY 20d): {curve.get('tlt_minus_shy','?'):.2f}% → {curve.get('interpretation','?')}
  Inflation (TIP-IEF): {infl.get('breakeven_proxy_pct','?'):.2f}% → {infl.get('direction','?')}
  Credit (LQD-HYG):    {credit.get('spread_proxy_pct','?'):.2f}% → {credit.get('direction','?')} ({credit.get('risk_signal','?')})"""

    # Format macro
    macro_lines = [
        f"  {name:<5} price={data.get('price','?')} | "
        f"1d={data.get('return_1d',0):+.2f}% | "
        f"5d={data.get('return_5d',0):+.2f}% | "
        f"trend={data.get('trend','?')}"
        for name, data in macro.items()
    ]
    macro_text = "\n".join(macro_lines) if macro_lines else "  Unavailable"

    # Format bond prices
    bond_lines = [
        f"  {sym:<5} ${data.get('price',0):.2f} | "
        f"1d={data.get('return_1d',0):+.2f}% | "
        f"5d={data.get('return_5d',0):+.2f}% | "
        f"20d={data.get('return_20d',0):+.2f}% | "
        f"range_pos={data.get('vs_30d_range',50):.0f}%"
        for sym, data in bonds.items()
    ]
    bond_text = "\n".join(bond_lines) if bond_lines else "  Unavailable"

    return f"""You are the Macro Bond Trader, a professional fixed income macro portfolio manager making MEDIUM-TERM INVESTMENT decisions (holding {min_hold}–{max_hold} days).

You are NOT a day trader. You allocate to bond ETFs based on macroeconomic conditions — rate cycle, inflation, credit risk, and USD dynamics.

Current time: {ts} UTC
Portfolio equity: ${equity:,.2f}
Maximum positions: {max_pos}
Position size range: {size_min*100:.0f}%–{size_max*100:.0f}% of equity
Minimum conviction to enter: {min_conv}

CURRENT OPEN POSITIONS:
{pos_text}

YIELD ENVIRONMENT:
{yield_text}

MACRO INDICATORS:
{macro_text}

BOND ETF PRICES:
{bond_text}

BOND ETF DEFINITIONS:
  TLT  — iShares 20+ Year Treasury (maximum rate sensitivity, long duration)
  IEF  — iShares 7-10 Year Treasury (moderate duration, neutral)
  SHY  — iShares 1-3 Year Treasury (rate hedge, cash equivalent with yield)
  TIP  — iShares TIPS Bond (inflation-protected)
  HYG  — iShares High Yield Corp (credit risk ON, spreads tight)
  LQD  — iShares IG Corp Bond (investment grade, duration + credit)
  EMB  — iShares EM USD Bond (EM credit, USD-sensitive)

YOUR MACRO FRAMEWORK:
- RATES RISING → bearish TLT/LQD (duration pain), bullish SHY/TIP
- RATES FALLING → bullish TLT/IEF (duration gain)
- INFLATION RISING → bullish TIP, mixed on TLT (real yield matters)
- INFLATION FALLING → mixed TIP, bullish TLT
- CREDIT SPREADS TIGHTENING → bullish HYG/LQD/EMB
- CREDIT SPREADS WIDENING → bearish HYG, flight to TLT/SHY
- USD STRENGTHENING → bearish EMB (EM sovereign debt)
- USD WEAKENING → bullish EMB
- CURVE STEEPENING → long TLT + short SHY not ideal; prefer IEF
- CURVE FLATTENING → TLT outperforms; SHY underperforms

STRICT RULES:
1. Maximum {max_pos} positions total
2. Only enter when macro thesis is CLEAR — if uncertain, hold cash
3. Conviction below {min_conv} = no trade
4. Size within {size_min*100:.0f}%–{size_max*100:.0f}% of equity
5. Consider closing if the rate/credit thesis has reversed
6. Cash is valid — 0 entries is often the right answer

Respond ONLY with valid JSON. No text outside the JSON:

{{
  "rate_environment": "one sentence on current rate environment",
  "duration_bias": "long | short | neutral",
  "inflation_view": "rising | falling | stable",
  "credit_bias": "risk_on | risk_off | neutral",
  "enter": [
    {{
      "symbol": "TLT",
      "direction": "long",
      "conviction": 0.75,
      "position_size_pct": 0.20,
      "stop_loss_pct": 0.04,
      "take_profit_pct": 0.08,
      "max_hold_days": 30,
      "thesis": "one sentence macro thesis for this specific bond ETF"
    }}
  ],
  "close": [
    {{
      "symbol": "HYG",
      "reason": "one sentence reason to close"
    }}
  ],
  "reasoning": "2-3 sentence overall macro view and why these decisions"
}}"""


def _call_groq(prompt: str) -> str:
    """
    Call Groq API. Tries raw Groq SDK first; falls back to shared wrapper.
    Identical pattern to jerome_investor._call_groq().
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
            logger.warning(f"Bot7 | Groq SDK failed ({exc}) — falling back to Gemini wrapper")

    _ensure_tp_path()
    from analysis.groq_client import call_groq
    return call_groq(
        system_prompt=(
            "You are the Macro Bond Trader, a professional fixed income portfolio manager. "
            "Respond ONLY with valid JSON as instructed."
        ),
        user_prompt=prompt,
        temperature=0.2,
        max_tokens=1024,
        call_type="bot7_macro_bond",
        json_mode=True,
    )


def _ensure_tp_path() -> None:
    tp = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
    )
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

    universe  = set(config.get("BOND_UNIVERSE", UNIVERSE))
    min_conv  = config.get("MIN_CONVICTION", MIN_CONVICTION)
    size_min  = config.get("POSITION_SIZE_MIN", POSITION_SIZE_MIN_PCT)
    size_max  = config.get("POSITION_SIZE_MAX", POSITION_SIZE_MAX_PCT)

    validated = []
    for entry in decisions.get("enter", []):
        sym       = str(entry.get("symbol", "")).upper()
        direction = str(entry.get("direction", "long")).lower()

        try:
            conviction = float(entry.get("conviction", 0))
            size_pct   = float(entry.get("position_size_pct", 0.15))
            sl_pct     = float(entry.get("stop_loss_pct", 0.04))
            tp_pct     = float(entry.get("take_profit_pct", 0.08))
            hold_days  = int(entry.get("max_hold_days", MIN_HOLD_DAYS))
        except (TypeError, ValueError) as exc:
            logger.warning(f"Bot7 | Skipping entry with bad numeric fields: {entry} — {exc}")
            continue

        if sym not in universe:
            logger.warning(f"Bot7 | Rejected unknown symbol: {sym}")
            continue
        if direction not in ("long", "short"):
            logger.warning(f"Bot7 | Rejected invalid direction: {direction!r}")
            continue
        if conviction < min_conv:
            logger.info(f"Bot7 | Rejected low conviction: {sym} {conviction:.2f}")
            continue
        if tp_pct < sl_pct * 1.5:
            logger.warning(f"Bot7 | Rejected poor R:R for {sym}: tp={tp_pct:.3f} sl={sl_pct:.3f}")
            continue

        # Clamp to allowed ranges
        size_pct  = max(size_min, min(size_max, size_pct))
        sl_pct    = max(0.02, min(0.08, sl_pct))
        tp_pct    = max(0.04, min(0.15, tp_pct))
        hold_days = max(MIN_HOLD_DAYS, min(MAX_HOLD_DAYS, hold_days))

        validated.append({
            "symbol":            sym,
            "direction":         direction,
            "conviction":        round(conviction, 2),
            "position_size_pct": round(size_pct, 3),
            "stop_loss_pct":     round(sl_pct, 3),
            "take_profit_pct":   round(tp_pct, 3),
            "max_hold_days":     hold_days,
            "thesis":            str(entry.get("thesis", ""))[:200],
        })
        if len(validated) >= MAX_POSITIONS:
            break

    decisions["enter"] = validated

    logger.info(f"Bot7 | rate_env={str(decisions.get('rate_environment','?'))[:80]}")
    logger.info(
        f"Bot7 | duration={decisions.get('duration_bias')} "
        f"inflation={decisions.get('inflation_view')} "
        f"credit={decisions.get('credit_bias')}"
    )
    for e in validated:
        logger.info(
            f"Bot7 | ENTER {e['symbol']} {e['direction'].upper()} "
            f"conviction={e['conviction']} size={e['position_size_pct']*100:.0f}% "
            f"sl={e['stop_loss_pct']*100:.1f}% tp={e['take_profit_pct']*100:.1f}% "
            f"hold={e['max_hold_days']}d | {e['thesis']}"
        )
    logger.info(f"Bot7 | reasoning: {decisions.get('reasoning','')}")
    return decisions


def _persist_decision(decisions: dict, raw: str) -> None:
    """Persist Bot7's decision to macro_bond_decisions table."""
    try:
        _ensure_tp_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO macro_bond_decisions
                        (rate_environment, inflation_view, duration_bias,
                         credit_bias, reasoning,
                         entries_count, closes_count,
                         raw_response, entries_json, closes_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    str(decisions.get("rate_environment", ""))[:200],
                    decisions.get("inflation_view", ""),
                    decisions.get("duration_bias", ""),
                    decisions.get("credit_bias", ""),
                    str(decisions.get("reasoning", ""))[:500],
                    len(decisions.get("enter", [])),
                    len(decisions.get("close", [])),
                    raw[:5000],
                    json.dumps(decisions.get("enter", [])),
                    json.dumps(decisions.get("close", [])),
                ))
            conn.commit()
        logger.info("Bot7 | Decision persisted to macro_bond_decisions")
    except Exception as exc:
        logger.debug(f"Bot7 | DB persist failed (non-fatal): {exc}")
