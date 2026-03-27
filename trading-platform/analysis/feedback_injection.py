"""
Feedback Injection — The Learning Loop (RAG)
----------------------------------------------
Queries the trade_journal.db for recent Closed_Win and Closed_Loss trades
and injects them into the system prompt sent to the Groq LLM.

This is the core of the platform's "memory":
- The model reviews past FAILURES to avoid repeating losing logic.
- The model reviews past WINS to reinforce strategies that worked.

This function MUST be called before every daily analysis cycle.
"""

from loguru import logger

from analysis.trade_journal import get_recent_losses, get_recent_wins


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

WIN_FEEDBACK_TEMPLATE = """
REINFORCEMENT — WHAT WORKED RECENTLY:
The following {n} strategies produced positive returns. Study the conditions
and thesis that drove these wins. When you see similar macro setups today,
these patterns are worth repeating (at appropriate conviction levels).

{win_entries}

Use these successful patterns as positive signal — but re-evaluate whether
current conditions still support the same thesis before repeating them.
"""


def build_system_prompt_with_feedback(n_losses: int = 5, n_wins: int = 3) -> str:
    """
    Build the full system prompt for today's analysis cycle.

    Injects both a 'what failed' (losses) block and a 'what worked' (wins)
    block so the LLM learns bidirectionally from its trading history.

    Args:
        n_losses: Number of recent losses to inject (default 5).
        n_wins:   Number of recent wins to inject (default 3).

    Returns:
        Complete system prompt string ready to send to Groq.
    """
    losses = get_recent_losses(limit=n_losses)
    wins   = get_recent_wins(limit=n_wins)

    full_prompt = BASE_SYSTEM_PROMPT

    if losses:
        loss_entries = []
        for i, loss in enumerate(losses, 1):
            loss_entries.append(
                f"  Loss #{i}: {loss['ticker']} ({loss['asset_class']}) | "
                f"P&L: {loss['pnl_percentage']:+.2f}% | "
                f"Date: {loss['date']}\n"
                f"  Failed Thesis: \"{loss['original_thesis']}\""
            )
        full_prompt += LOSS_FEEDBACK_TEMPLATE.format(
            n=len(losses),
            loss_entries="\n\n".join(loss_entries),
        )
        logger.info(f"Feedback injection | Injected {len(losses)} past losses into system prompt")
        for loss in losses:
            logger.debug(f"  Loss: {loss['ticker']} {loss['pnl_percentage']:+.2f}% on {loss['date']}")
    else:
        logger.info("Feedback injection | No past losses in journal")

    if wins:
        win_entries = []
        for i, win in enumerate(wins, 1):
            win_entries.append(
                f"  Win #{i}: {win['ticker']} ({win['asset_class']}) | "
                f"P&L: {win['pnl_percentage']:+.2f}% | "
                f"Date: {win['date']}\n"
                f"  Winning Thesis: \"{win['original_thesis']}\""
            )
        full_prompt += WIN_FEEDBACK_TEMPLATE.format(
            n=len(wins),
            win_entries="\n\n".join(win_entries),
        )
        logger.info(f"Feedback injection | Injected {len(wins)} past wins into system prompt")
        for win in wins:
            logger.debug(f"  Win:  {win['ticker']} {win['pnl_percentage']:+.2f}% on {win['date']}")
    else:
        logger.info("Feedback injection | No past wins in journal")

    if not losses and not wins:
        logger.info("Feedback injection | No trading history — using clean prompt")

    return full_prompt
