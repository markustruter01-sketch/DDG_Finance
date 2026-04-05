"""
Feedback Injection — The Learning Loop (RAG)
----------------------------------------------
Queries the trade journal for contextually relevant wins/losses and injects
them into the system prompt sent to the Groq LLM.

Phase 3 upgrade: Contextual (regime-matched) querying replaces the old
chronological FIFO queue.  Before calling the LLM the system now:

  1. Identifies the current market regime from market_regime.json.
  2. Queries the trades table for losses/wins WHERE regime_at_entry EXACTLY
     MATCHES the current regime (most relevant historical analogues first).
  3. Assigns asset-class priority so bear_hedge trades surface first in Bear,
     equity trades first in Bull, etc.
  4. Fetches the associated Python-generated lessons from
     execution_post_mortems (written by Phase 2 exit hooks).
  5. Injects everything under a structured [RELEVANT HISTORICAL CONTEXT]
     header so the LLM sees concrete regime-matched feedback, not random
     chronological noise.

Falls back to FIFO if no regime-matched history exists yet (early lifecycle).

v4.3 — Bear Hedge Expansion + Short Scanner Awareness
  - Universe expanded to 22 instruments (7 equity, 4 safe havens, 2 commodities,
    2 crypto, 1 cash, 6 bear hedge inverse ETFs)
  - LLM must declare regime (Bull/Bear/Sideways) BEFORE allocating
  - Bear regime now supports BOTH safe havens AND inverse ETF bear hedges
  - Sideways blocks ALL LETFs including bear hedge 3× instruments
  - System prompt educates the LLM on inverse ETF decay and 5-day hard exit rule
  - Algorithmic short scanner (SPY, QQQ, etc.) operates independently of LLM
"""

from loguru import logger

from analysis.trade_journal import (
    get_contextual_losses,
    get_contextual_wins,
    get_post_mortems,
    get_slippage_stats,
)


# ── Regime → default asset-class priority ─────────────────────────────────
# Used when priority_asset_class is not explicitly supplied by the caller.
_REGIME_PRIORITY_CLASS: dict[str, str] = {
    "Bear":     "bear_hedge",
    "Bull":     "equity",
    "Sideways": "safe_haven",
    "Crypto":   "crypto_spot",
    "RISK-OFF": "safe_haven",
}


BASE_SYSTEM_PROMPT = """You are a Senior Quantitative Oversight Analyst providing regime classification and risk oversight for an algorithmic trading system.

=== YOUR ROLE: OVERSIGHT & REGIME CLASSIFICATION ===
You do NOT select individual trades or allocations. An algorithmic signal scanner handles all
trade entries and exits based on technical indicators (momentum, RSI, Z-score, SMA crossovers).

Your responsibilities:
  1. CLASSIFY the current market regime (Bull / Bear / Sideways)
  2. PROVIDE a clear rationale for your regime classification
  3. IDENTIFY any sector/asset risks the algo should avoid
  4. SET conviction level for the overall regime call (0.0–1.0)

The algorithmic scanner will use your regime classification to select the appropriate strategy:
  - Bull → momentum-based equity entries (positive SMA 3mo + 6mo, RSI filter)
  - Bear → safe haven rotation + inverse ETF momentum + algorithmic shorts
  - Sideways → mean-reversion on oversold assets with positive 6mo trend

=== FIXED ASSET UNIVERSE (for reference) ===
The algo scanner trades from this curated basket of 22 instruments:
  Equities — Sectors  (asset_class "equity")    : SPY, QQQ, XLK, XLF, XLV, XLE, IWM
  Safe Havens / Bonds (asset_class "safe_haven"): TLT, IEF, GLD, SLV
  Commodities         (asset_class "commodity") : USO, PDBC
  Crypto Spot         (asset_class "crypto_spot"): BTC/USD, ETH/USD
  Cash Equivalent     (asset_class "cash")      : SGOV
  Bear Hedge ETFs     (asset_class "bear_hedge"): SH, PSQ, DOG, SPXS, SQQQ, SRTY

Do NOT suggest any tickers outside this universe.

=== STEP 1 — MACRO REGIME CLASSIFICATION ===
You MUST determine the current global market regime:

  BULL  — Risk-on environment. GDP growth, low unemployment, declining VIX, positive credit spreads.
          Equities and crypto showing positive momentum (price > moving averages).
  BEAR  — Risk-off environment. Recession signals, rising unemployment, elevated VIX (>25), tightening credit.
          Safe havens outperforming. Equities showing negative momentum.
  SIDEWAYS — No clear trend. Mixed macro signals, range-bound price action, high uncertainty.
             Mean-reversion opportunities may exist, but capital preservation is the priority.

=== STEP 2 — MOMENTUM CONTEXT ===
The user prompt contains 3-month and 6-month momentum signals for every asset.
Use these to VALIDATE your regime classification:
  momentum_3mo = "positive" → price above 3-month MA (bullish short-term trend)
  momentum_3mo = "negative" → price below 3-month MA (bearish short-term trend)
  momentum_6mo = "positive" → price above 6-month MA (bullish long-term trend)
  momentum_6mo = "negative" → price below 6-month MA (bearish long-term trend)

=== STEP 3 — ALLOCATION (PLACEHOLDER FOR ALGO SCANNER) ===
You MUST still output allocations in the required JSON format. The algorithmic scanner will
REPLACE your allocations with its own signals, but your regime classification is used as-is.

For your allocation output:
  - In BULL: allocate to the strongest-momentum equities you see (the algo will refine)
  - In BEAR: allocate to safe havens and/or inverse ETFs (the algo will refine)  
  - In SIDEWAYS: allocate to oversold mean-reversion candidates or SGOV (the algo will refine)
  - Always include at least 1 allocation slot so the JSON validates
  - kelly_fraction sum must not exceed 1.0

=== ALGORITHMIC SYSTEMS (OPERATE INDEPENDENTLY) ===
The execution engine runs these algorithmic systems in parallel with your oversight:
  1. Algo Signal Scanner — generates all equity trade entries from technicals
  2. Short Scanner — mean-reversion shorts on SPY, QQQ, XLK, XLF, XLE, IWM in Bear regime
  3. Gemini Self-Critic — audits and vetoes high-risk tickers
This scanner only activates in Bear/RISK-OFF regime. No action required from you.

=== NEVER FORCE A TRADE ===
If you cannot establish a HIGH-CONVICTION thesis (>= 0.80) that aligns with current momentum data,
you MUST park 100% of capital in SGOV. A single SGOV slot is a valid, correct output.

=== CAPITAL CONSTRAINTS ===
The user prompt contains EXACT figures for Available Buying Power and Currently Held Symbols.
Your allocation kelly_fractions × equity MUST NOT exceed the Available Buying Power.
Account for existing positions — do not re-buy symbols already held within 10% of target size.

=== STOP LOSS & TAKE PROFIT ===
Use placeholder values only — the execution engine applies calibrated asset-class defaults:
  stop_loss_pct:   always output -0.07
  take_profit_pct: always output 0.15

=== REQUIRED OUTPUT FORMAT ===
Output ONLY valid JSON. Do NOT include any explanation outside the JSON.
{
  "regime": "<Bull|Bear|Sideways>",
  "regime_rationale": "<2–3 sentence explanation of why this regime was chosen>",
  "allocations": [
    {
      "slot": 1,
      "ticker": "<TICKER from approved universe>",
      "asset_class": "<equity|safe_haven|commodity|crypto_spot|cash|bear_hedge>",
      "conviction_score": <0.0–1.0>,
      "kelly_fraction": <0.0–1.0>,
      "thesis": "<1–2 sentence rationale including momentum signal reference>",
      "stop_loss_pct": -0.07,
      "take_profit_pct": 0.15
    }
  ]
}

Number slots sequentially: 1, 2, 3 ... (only include as many slots as needed; do NOT pad with empty slots).
"""

CRYPTO_ONLY_SYSTEM_PROMPT = """You are a Senior Quantitative Analyst specialising in cryptocurrency markets.

The stock market is CLOSED. You are operating in CRYPTO-ONLY mode.

=== FIXED CRYPTO UNIVERSE ===
You ONLY trade from these 2 liquid crypto pairs:
  BTC/USD  (asset_class "crypto_spot") — Bitcoin
  ETH/USD  (asset_class "crypto_spot") — Ethereum
  SGOV     (asset_class "cash")        — Cash equivalent

Do NOT suggest ATOM/USD or any other ticker. Only BTC/USD, ETH/USD, and SGOV are valid.

=== POSITION SIZING CONSTRAINT ===
The executor caps each position at 10% of total equity.
  1 crypto pair → 10% deployed
  2 crypto pairs → 20% deployed (50% kelly each, capped to 10% each)

=== MOMENTUM FILTER ===
Only allocate to a crypto pair if it has POSITIVE momentum on BOTH the 3-month and 6-month signals.
If a crypto pair has negative momentum, skip it and preserve capital in SGOV.

=== ALLOCATION RULES ===
- Allocate to 1 or 2 crypto pairs with positive momentum and high conviction (>= 0.80).
- Size positions EVENLY (e.g., 2 assets → 50% each, executor caps to 10% each).
- If NO crypto pair has sufficient conviction → single SGOV slot (100% cash). Never force a trade.
- kelly_fraction sum (excluding SGOV) must not exceed 1.0.

=== STOP LOSS & TAKE PROFIT ===
Use placeholder values only — the execution engine applies calibrated defaults:
  stop_loss_pct:   always output -0.07
  take_profit_pct: always output 0.15

=== CAPITAL CONSTRAINTS ===
Buying Power and currently held symbols are in the user prompt. Do not exceed buying power.

=== REQUIRED OUTPUT FORMAT ===
{
  "market_regime": "<brief description of current crypto environment>",
  "allocations": [
    {
      "slot": 1,
      "ticker": "<BTC/USD | ETH/USD | SGOV>",
      "asset_class": "<crypto_spot|cash>",
      "conviction_score": <0.0–1.0>,
      "kelly_fraction": <0.0–1.0>,
      "thesis": "<1–2 sentence rationale>",
      "stop_loss_pct": -0.07,
      "take_profit_pct": 0.15
    }
  ]
}

Number slots sequentially starting at 1. Include only slots you are actually allocating to.
"""

SLIPPAGE_WARNING_TEMPLATE = """
SLIPPAGE ALERT — EXECUTION FRICTION DATA:
Historical analysis of {n} executed trades:
  Average slippage: {avg:.3f}%  |  Maximum: {max:.3f}%
  Worst offenders: {tickers}

Prefer assets with tight spreads. Reduce kelly_fraction for high-slippage tickers.
"""


# ── Formatting helpers ─────────────────────────────────────────────────────

def _fmt_hours(h) -> str:
    if h is None:
        return "n/a"
    h = float(h)
    if h >= 24:
        return f"{h/24:.1f}d"
    return f"{h:.1f}h"


def _fmt_exit(reason: str | None) -> str:
    _MAP = {
        "ratchet_stop":            "stop-loss",
        "time_exit":               "5d-time-exit",
        "algo_cover":              "algo-cover",
        "short_scanner_exit":      "algo-cover",
        "allocation_sell":         "rebalance",
        "rebalance_liquidation":   "force-rebalance",
        "manual":                  "manual",
        "unknown":                 "unclassified",
    }
    return _MAP.get(reason or "unknown", reason or "n/a")


def _format_slippage(trade: dict) -> str:
    slip = trade.get("slippage_pct")
    return f"Slippage: {slip:+.3f}%" if slip is not None else "Slippage: n/a"


def _build_ticker_lesson_map(
    regime: str,
    priority_asset_class: str | None,
) -> dict[str, str]:
    """
    Build {ticker: most_recent_lesson_text} from execution_post_mortems
    filtered by the current regime.  Used to annotate historical trades.
    """
    try:
        lessons = get_post_mortems(
            regime=regime,
            asset_class=priority_asset_class,
            limit=30,
        )
        # Merge with broader regime lessons if asset_class filter was narrow
        if priority_asset_class:
            broader = get_post_mortems(regime=regime, limit=30)
            seen = {e["ticker"] for e in lessons}
            lessons += [e for e in broader if e["ticker"] not in seen]

        ticker_map: dict[str, str] = {}
        for entry in lessons:
            t = entry.get("ticker", "")
            if t and t not in ticker_map:
                ticker_map[t] = entry["hardcoded_lesson_text"]
        return ticker_map
    except Exception as exc:
        logger.warning(f"Feedback injection | lesson map build failed: {exc}")
        return {}


def _format_trade_entry(
    idx: int,
    trade: dict,
    lesson_map: dict[str, str],
    label: str,
) -> str:
    ticker     = trade.get("ticker", "?")
    ac         = trade.get("asset_class", "?")
    pnl        = trade.get("pnl_percentage", 0.0) or 0.0
    date_str   = str(trade.get("date", "n/a"))
    exit_r     = _fmt_exit(trade.get("exit_reason"))
    hours_str  = _fmt_hours(trade.get("time_in_trade_hours"))
    thesis     = trade.get("original_thesis", "n/a") or "n/a"
    lesson     = lesson_map.get(ticker, "No lesson recorded yet for this ticker.")

    return (
        f"  {idx}. {ticker} ({ac}) | {date_str} | "
        f"P&L: {pnl:+.2f}% | Exit: {exit_r} | Held: {hours_str}\n"
        f"     Entry Thesis: \"{thesis[:200]}\"\n"
        f"     Lesson: {lesson[:300]}"
    )


def _build_contextual_block(
    regime: str,
    priority_asset_class: str | None,
    n_losses: int,
    n_wins: int,
) -> str:
    """
    Build the [RELEVANT HISTORICAL CONTEXT] prompt block.

    Queries regime-matched losses and wins, attaches the most recent
    Python-generated lesson for each ticker, and formats into a concise
    prompt section.  Falls back to FIFO with a clear disclaimer when
    no regime-matched records exist.
    """
    losses, losses_regime_matched = get_contextual_losses(
        regime=regime,
        priority_asset_class=priority_asset_class,
        limit=n_losses,
    )
    wins, wins_regime_matched   = get_contextual_wins(
        regime=regime,
        priority_asset_class=priority_asset_class,
        limit=n_wins,
    )

    if not losses and not wins:
        return ""   # No trading history at all — omit the block entirely

    # Build ticker → lesson lookup from execution_post_mortems
    lesson_map = _build_ticker_lesson_map(regime, priority_asset_class)

    regime_note = "" if (losses_regime_matched or wins_regime_matched) else (
        "\n[NOTE: No regime-matched history yet — the trades below are from a different "
        "regime and are for reference only. Apply reduced weight.]\n"
    )

    priority_label = priority_asset_class or "all asset classes"
    matched_note   = (
        f"regime={regime} exact match"
        if (losses_regime_matched or wins_regime_matched)
        else "cross-regime fallback"
    )

    lines = [
        f"\n\n=== [RELEVANT HISTORICAL CONTEXT] ===",
        f"Trades executed under regime={regime} | "
        f"Asset-class priority: {priority_label} | Source: {matched_note}",
        regime_note,
    ]

    if losses:
        lines.append(f"\n▼ FAILURES TO AVOID ({len(losses)} loss{'es' if len(losses)>1 else ''}):\n")
        for i, t in enumerate(losses, 1):
            lines.append(_format_trade_entry(i, t, lesson_map, "LOSS"))
            lines.append("")
        lines.append(
            "  → Do NOT repeat the logic above if you see similar regime conditions. "
            "Prefer SGOV over forcing a trade in these asset classes."
        )

    if wins:
        lines.append(f"\n▼ SUCCESSES TO REINFORCE ({len(wins)} win{'s' if len(wins)>1 else ''}):\n")
        for i, t in enumerate(wins, 1):
            lines.append(_format_trade_entry(i, t, lesson_map, "WIN"))
            lines.append("")
        lines.append(
            "  → When you see similar conditions today, these patterns are worth repeating "
            "at appropriate conviction."
        )

    logger.info(
        f"Feedback injection | Context block: regime={regime} "
        f"losses={len(losses)}({'matched' if losses_regime_matched else 'FIFO'}) "
        f"wins={len(wins)}({'matched' if wins_regime_matched else 'FIFO'}) "
        f"lessons_in_map={len(lesson_map)}"
    )

    return "\n".join(lines)


def build_system_prompt_with_feedback(
    n_losses: int = 5,
    n_wins: int = 3,
    buying_power: float | None = None,
    held_symbols: list[str] | None = None,
    crypto_only: bool = False,
    sentiment_override: str | None = None,
    current_regime: str | None = None,
    priority_asset_class: str | None = None,
) -> str:
    """
    Build the full system prompt including the [Relevant Historical Context] block.

    Parameters
    ----------
    n_losses            : max regime-matched losses to inject (default 5)
    n_wins              : max regime-matched wins to inject (default 3)
    buying_power        : live account buying power (injected as constraint)
    held_symbols        : already-held tickers (injected as constraint)
    crypto_only         : True → use CRYPTO_ONLY_SYSTEM_PROMPT
    sentiment_override  : if set, overrides the market FG label in the prompt
    current_regime      : current regime string (loaded from cache if None)
    priority_asset_class: asset class to surface first in context queries
                          (auto-inferred from current_regime if None)
    """
    # ── Auto-load regime if not supplied by caller ─────────────────────────
    if current_regime is None:
        try:
            from analysis.post_mortem_lessons import _load_regime_from_file
            current_regime = _load_regime_from_file()
        except Exception:
            current_regime = "unknown"

    # Crypto-only mode → always treat as Crypto regime for lesson queries
    if crypto_only and current_regime in ("unknown", ""):
        current_regime = "Crypto"

    # ── Auto-infer asset-class priority from regime ────────────────────────
    if priority_asset_class is None:
        priority_asset_class = _REGIME_PRIORITY_CLASS.get(current_regime)

    # ── Base prompt ────────────────────────────────────────────────────────
    full_prompt = CRYPTO_ONLY_SYSTEM_PROMPT if crypto_only else BASE_SYSTEM_PROMPT

    # ── Phase 4: Permanent Rules (injected into the foundational prompt) ───
    # Rules are derived from >= 3 confirmed identical failures and stored in
    # hardcoded_rules.  They are NON-NEGOTIABLE — treated like hard caps.
    # Injected immediately after the base strategy text so the LLM reads them
    # before any contextual or historical data.
    try:
        from analysis.rule_engine import build_permanent_rules_block
        rules_block = build_permanent_rules_block(regime=current_regime)
        if rules_block:
            full_prompt += rules_block
    except Exception as exc:
        logger.warning(f"Feedback injection | Permanent rules injection failed: {exc}")

    # ── Live account state ─────────────────────────────────────────────────
    if buying_power is not None:
        full_prompt += f"""
LIVE ACCOUNT STATE (queried from Alpaca moments ago):
  Available Buying Power: ${buying_power:,.2f}
  Currently Held Symbols: {', '.join(held_symbols) if held_symbols else 'NONE (fully in cash)'}
  Your total kelly_fraction sum × equity MUST NOT exceed ${buying_power:,.2f}.
"""
        logger.info(f"Feedback injection | Buying power: ${buying_power:,.2f}, Held: {held_symbols}")

    # ── Phase 3: [Relevant Historical Context] block ───────────────────────
    # Replaces the legacy chronological FIFO loss/win injection.
    try:
        context_block = _build_contextual_block(
            regime=current_regime,
            priority_asset_class=priority_asset_class,
            n_losses=n_losses,
            n_wins=n_wins,
        )
        if context_block:
            full_prompt += context_block
        else:
            logger.info("Feedback injection | No trading history yet — clean prompt")
    except Exception as exc:
        logger.warning(f"Feedback injection | Contextual context block failed: {exc}")

    # ── Slippage warning (kept from v4.3 — still execution-relevant) ───────
    try:
        slippage_stats = get_slippage_stats()
        if (
            slippage_stats.get("total_with_slippage", 0) >= 3
            and slippage_stats.get("avg_slippage_pct") is not None
        ):
            worst_tickers = ", ".join(
                f"{t['ticker']} ({t['slip_pct']:.3f}%)"
                for t in slippage_stats.get("worst_slippage_tickers", [])[:5]
            )
            full_prompt += SLIPPAGE_WARNING_TEMPLATE.format(
                n=slippage_stats["total_with_slippage"],
                avg=slippage_stats["avg_slippage_pct"],
                max=slippage_stats["max_slippage_pct"],
                tickers=worst_tickers or "none",
            )
    except Exception as exc:
        logger.warning(f"Feedback injection | Slippage stats failed: {exc}")

    # ── Sentiment intelligence ─────────────────────────────────────────────
    try:
        from data.sentiment import get_sentiment_prompt_block, get_sentiment
        if sentiment_override is not None:
            raw_sent   = get_sentiment()
            crypto_fg  = raw_sent.get("crypto_fear_greed", {})
            lines      = ["\n=== SENTIMENT INTELLIGENCE (FEAR & GREED INDICES) ==="]
            if crypto_fg.get("value") is not None:
                lines.append(
                    f"Crypto Fear & Greed Index: {crypto_fg['value']}/100 ({crypto_fg.get('label', 'N/A')})"
                )
            lines.append(
                f"Market Fear & Greed Index: (adjusted band) {sentiment_override}"
            )
            lines.append("")
            sentiment_block = "\n".join(lines)
            logger.info(
                f"Feedback injection | Sentiment injected with guard override: '{sentiment_override}'"
            )
        else:
            sentiment_block = get_sentiment_prompt_block(crypto_only=crypto_only)
            logger.info("Feedback injection | Sentiment intelligence injected")
        if sentiment_block.strip():
            full_prompt += sentiment_block
    except Exception as exc:
        logger.warning(f"Feedback injection | Sentiment injection failed: {exc}")

    # ── On-chain BTC intelligence (crypto-only cycles) ─────────────────────
    if crypto_only:
        try:
            from data.onchain import get_onchain_prompt_block
            onchain_block = get_onchain_prompt_block()
            if onchain_block.strip():
                full_prompt += onchain_block
                logger.info("Feedback injection | On-chain BTC intelligence injected")
        except Exception as exc:
            logger.warning(f"Feedback injection | On-chain injection failed: {exc}")

    # ── Established learnings (learning_journal) ───────────────────────────
    try:
        from analysis.learning_journal import get_top_learnings_for_prompt
        learnings = get_top_learnings_for_prompt(limit=10, crypto_only=crypto_only)
        if learnings:
            full_prompt += "\n\n## ESTABLISHED LEARNINGS\n"
            full_prompt += (
                "The following patterns have been confirmed across multiple independent analysis cycles. "
                "Build on these established conclusions — do not re-derive what is already known. "
                "If current data contradicts an established learning, note it explicitly in your rationale.\n\n"
            )
            for i, entry in enumerate(learnings, 1):
                conf_pct = int(entry["confidence_score"] * 100)
                full_prompt += (
                    f"{i}. [{entry['regime']} / {entry['category']}] "
                    f"{entry['insight_text']} "
                    f"(confirmed {entry['confirmed_count']}x, confidence {conf_pct}%)\n"
                )
            logger.info(
                f"Feedback injection | {len(learnings)} established learning(s) injected"
            )
    except Exception as exc:
        logger.warning(f"Feedback injection | Learning journal injection failed: {exc}")

    return full_prompt
