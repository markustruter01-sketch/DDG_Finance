"""
Feedback Injection — The Learning Loop (RAG)
----------------------------------------------
Queries the trade_journal.db for the 5 most recent Closed_Loss trades
and injects them into the system prompt sent to the Groq LLM.

This is the core of the platform's "memory" — the model is explicitly
instructed to review its own past failures and adjust its reasoning to
avoid repeating the same mistakes.

This function MUST be called before every daily analysis cycle.
"""

from loguru import logger

from analysis.trade_journal import get_recent_losses


BASE_SYSTEM_PROMPT = """You are a Senior Quantitative Analyst and Portfolio Manager.

Your task is to analyse current global macroeconomic data, asset prices, and news,
then output a structured JSON investment allocation plan for exactly 10 capital slots.

ALLOCATION RULES:
You MUST fill the following slots with tickers that have conviction_score >= 0.75.
If you cannot find a qualifying ticker for a required slot, use the LEAST BAD option
in that category — do NOT fall back to SGOV for these required slots.

REQUIRED (conviction >= 0.75 for each):
- Crypto ETFs:    exactly 2 slots  → pick 2 from: BITO, IBIT, GBTC, ETHA
- Commodity ETFs: exactly 3 slots  → pick 3 from: GLD, SLV, USO, DBA, PDBC, CPER
- Currency ETFs:  exactly 1 slot   → pick 1 from: UUP, FXE, FXY, FXB, EUO, YCS
- Wildcard:       exactly 1 slot   → pick 1 from: QQQ, SPY, TLT, HYG, EEM

OPTIONAL (remaining 3 slots — use conviction to decide):
- Allocate remaining 3 slots to any approved category.
- Use ticker "SGOV" with asset_class "cash" only for slots where
  conviction_score < 0.75 AND they are not in the required count above.

SCORING RULES:
- Every trade slot MUST have a conviction_score between 0.0 and 1.0.
- Do NOT include conversational text. Output ONLY valid JSON.

KELLY CRITERION:
- Use the Kelly Criterion to size each position. Higher conviction + lower volatility
  = larger Kelly fraction. Cap individual Kelly fractions at 0.20 (20% of portfolio).

REQUIRED OUTPUT FORMAT:
{
  "market_regime": "<brief description of current macro environment>",
  "allocations": [
    {
      "slot": 1,
      "ticker": "<TICKER>",
      "asset_class": "<crypto|commodity|currency|wildcard|cash>",
      "conviction_score": <0.0-1.0>,
      "kelly_fraction": <0.0-0.20>,
      "thesis": "<1-2 sentence rationale>",
      "stop_loss_pct": <negative float, e.g. -0.05 for 5%>,
      "take_profit_pct": <positive float, e.g. 0.10 for 10%>
    }
  ]
}
"""

LOSS_FEEDBACK_TEMPLATE = """
CRITICAL — LEARNING FROM PAST FAILURES:
Review your {n} most recent failed strategies below. You MUST adjust your
macroeconomic reasoning today to ensure you do not repeat the specific logic
that led to these losses. Each entry shows the ticker, the original thesis
that was wrong, and the realised loss.

{loss_entries}

Do NOT repeat any of the logical errors described above. If you see similar
conditions today, be sceptical and consider SGOV (cash) instead.
"""


def build_system_prompt_with_feedback(n_losses: int = 5) -> str:
    """
    Build the full system prompt for today's analysis cycle.

    Queries the last N Closed_Loss trades from the journal and injects
    them as a mandatory feedback block into the system prompt.

    Args:
        n_losses: Number of recent losses to inject (default 5).

    Returns:
        Complete system prompt string ready to send to Groq.
    """
    losses = get_recent_losses(limit=n_losses)

    if not losses:
        logger.info("Feedback injection | No past losses in journal — using clean prompt")
        return BASE_SYSTEM_PROMPT

    loss_entries = []
    for i, loss in enumerate(losses, 1):
        loss_entries.append(
            f"  Loss #{i}: {loss['ticker']} ({loss['asset_class']}) | "
            f"P&L: {loss['pnl_percentage']:+.2f}% | "
            f"Date: {loss['date']}\n"
            f"  Failed Thesis: \"{loss['original_thesis']}\""
        )

    feedback_block = LOSS_FEEDBACK_TEMPLATE.format(
        n=len(losses),
        loss_entries="\n\n".join(loss_entries),
    )

    full_prompt = BASE_SYSTEM_PROMPT + feedback_block

    logger.info(
        f"Feedback injection | Injected {len(losses)} past losses into system prompt"
    )
    for loss in losses:
        logger.debug(
            f"  Injected: {loss['ticker']} {loss['pnl_percentage']:+.2f}% "
            f"on {loss['date']}"
        )

    return full_prompt
