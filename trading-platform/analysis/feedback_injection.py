"""
Feedback Injection — The Learning Loop (RAG)
----------------------------------------------
Queries the trade_journal.db for recent Closed_Win and Closed_Loss trades
and injects them into the system prompt sent to the Groq LLM.

This is the core of the platform's "memory":
- The model reviews past FAILURES to avoid repeating losing logic.
- The model reviews past WINS to reinforce strategies that worked.
- Slippage data teaches the model to avoid wide-spread assets.
- Buying power and held symbols enforce strict capital constraints.

Supports dual-mode prompts:
  - Full Market mode: 10-slot allocation across all asset classes (market hours)
  - Crypto-Only mode: 6-slot allocation across raw crypto pairs (off-hours)

This function MUST be called before every analysis cycle.
"""

from loguru import logger

from analysis.trade_journal import get_recent_losses, get_recent_wins, get_slippage_stats


BASE_SYSTEM_PROMPT = """You are a Senior Quantitative Analyst and Portfolio Manager.

Your task is to analyse current global macroeconomic data, asset prices, and news,
then output a structured JSON investment allocation plan for exactly 10 capital slots.

STRICT CAPITAL CONSTRAINT:
The user prompt contains EXACT figures for Available Buying Power and Currently Held
Symbols, queried from the live brokerage account moments before this call.
Your 10 allocations' total notional value (sum of kelly_fraction × equity) MUST NOT
exceed the Available Buying Power figure provided. If buying power is limited, reduce
kelly_fractions proportionally so total deployed capital stays within the limit.
Do NOT assume unlimited capital — treat the buying power number as a hard ceiling.

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

SLIPPAGE AWARENESS:
- Some assets have wider bid-ask spreads than others. The user prompt may include
  historical slippage data. Prefer assets with low slippage. If a ticker has
  consistently high slippage (>0.15%), reduce its kelly_fraction or consider
  an alternative ticker in the same category.

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

CRYPTO_ONLY_SYSTEM_PROMPT = """You are a Senior Quantitative Analyst specialising in cryptocurrency markets.

The stock market is currently CLOSED. You are operating in CRYPTO-ONLY mode, trading
raw cryptocurrency pairs 24/7 through Alpaca's crypto exchange.

Your task is to analyse current crypto market data and news, then output a structured
JSON investment allocation plan for exactly 6 capital slots using only crypto pairs.

STRICT CAPITAL CONSTRAINT:
The user prompt contains EXACT figures for Available Buying Power and Currently Held
Symbols, queried from the live brokerage account moments before this call.
Your 6 allocations' total notional value (sum of kelly_fraction × equity) MUST NOT
exceed the Available Buying Power figure provided. If buying power is limited, reduce
kelly_fractions proportionally so total deployed capital stays within the limit.
Do NOT assume unlimited capital — treat the buying power number as a hard ceiling.

ALLOCATION RULES:
- Fill exactly 6 slots using crypto pairs from: BTC/USD, ETH/USD, SOL/USD, DOGE/USD, AVAX/USD, LINK/USD
- At least 4 slots MUST be crypto_spot with conviction_score >= 0.75
- Up to 2 slots may be "SGOV" with asset_class "cash" if conviction is low
- You may allocate multiple slots to the same crypto pair if conviction is high

SCORING RULES:
- Every trade slot MUST have a conviction_score between 0.0 and 1.0.
- Do NOT include conversational text. Output ONLY valid JSON.

KELLY CRITERION:
- Use the Kelly Criterion to size each position. Higher conviction + lower volatility
  = larger Kelly fraction. Cap individual Kelly fractions at 0.20 (20% of portfolio).
- Crypto is inherently more volatile — adjust Kelly fractions conservatively.

SLIPPAGE AWARENESS:
- Crypto pairs can have wider spreads during low-liquidity hours (late night, early morning).
- Prefer BTC/USD and ETH/USD for larger allocations (highest liquidity).
- Reduce kelly_fractions for smaller-cap coins during low-volume periods.

REQUIRED OUTPUT FORMAT:
{
  "market_regime": "<brief description of current crypto market environment>",
  "allocations": [
    {
      "slot": 1,
      "ticker": "<TICKER>",
      "asset_class": "<crypto_spot|cash>",
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
that was wrong, the realised loss, and execution slippage.

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

SLIPPAGE_WARNING_TEMPLATE = """
SLIPPAGE ALERT — EXECUTION FRICTION DATA:
Historical analysis of {n} executed trades shows:
  Average slippage: {avg:.3f}%
  Maximum slippage: {max:.3f}%
  Worst offenders: {tickers}

High-slippage tickers eat into returns. Prefer liquid assets with tight spreads.
If a ticker appears in the worst offenders list above, consider alternatives.
"""


def _format_slippage(trade: dict) -> str:
    slip = trade.get("slippage_pct")
    if slip is not None:
        return f"Slippage: {slip:+.3f}%"
    return "Slippage: n/a"


def build_system_prompt_with_feedback(
    n_losses: int = 5,
    n_wins: int = 3,
    buying_power: float | None = None,
    held_symbols: list[str] | None = None,
    crypto_only: bool = False,
) -> str:
    losses = get_recent_losses(limit=n_losses)
    wins   = get_recent_wins(limit=n_wins)

    full_prompt = CRYPTO_ONLY_SYSTEM_PROMPT if crypto_only else BASE_SYSTEM_PROMPT

    if buying_power is not None:
        full_prompt += f"""
LIVE ACCOUNT STATE (queried from Alpaca moments ago):
  Available Buying Power: ${buying_power:,.2f}
  Currently Held Symbols: {', '.join(held_symbols) if held_symbols else 'NONE (fully in cash)'}
  Your total kelly_fraction sum × equity MUST NOT exceed ${buying_power:,.2f}.
  Account for existing positions — do not re-buy symbols already held unless
  rebalancing is required (size change > 10%).
"""
        logger.info(f"Feedback injection | Buying power: ${buying_power:,.2f}, Held: {held_symbols}")

    if losses:
        loss_entries = []
        for i, loss in enumerate(losses, 1):
            slip_text = _format_slippage(loss)
            loss_entries.append(
                f"  Loss #{i}: {loss['ticker']} ({loss['asset_class']}) | "
                f"P&L: {loss['pnl_percentage']:+.2f}% | {slip_text} | "
                f"Date: {loss['date']}\n"
                f"  Failed Thesis: \"{loss['original_thesis']}\""
            )
        full_prompt += LOSS_FEEDBACK_TEMPLATE.format(
            n=len(losses),
            loss_entries="\n\n".join(loss_entries),
        )
        logger.info(f"Feedback injection | Injected {len(losses)} past losses into system prompt")
        for loss in losses:
            slip = loss.get("slippage_pct")
            slip_str = f" slip={slip:+.3f}%" if slip is not None else ""
            logger.debug(f"  Loss: {loss['ticker']} {loss['pnl_percentage']:+.2f}% on {loss['date']}{slip_str}")
    else:
        logger.info("Feedback injection | No past losses in journal")

    if wins:
        win_entries = []
        for i, win in enumerate(wins, 1):
            slip_text = _format_slippage(win)
            win_entries.append(
                f"  Win #{i}: {win['ticker']} ({win['asset_class']}) | "
                f"P&L: {win['pnl_percentage']:+.2f}% | {slip_text} | "
                f"Date: {win['date']}\n"
                f"  Winning Thesis: \"{win['original_thesis']}\""
            )
        full_prompt += WIN_FEEDBACK_TEMPLATE.format(
            n=len(wins),
            win_entries="\n\n".join(win_entries),
        )
        logger.info(f"Feedback injection | Injected {len(wins)} past wins into system prompt")
        for win in wins:
            slip = win.get("slippage_pct")
            slip_str = f" slip={slip:+.3f}%" if slip is not None else ""
            logger.debug(f"  Win:  {win['ticker']} {win['pnl_percentage']:+.2f}% on {win['date']}{slip_str}")
    else:
        logger.info("Feedback injection | No past wins in journal")

    slippage_stats = get_slippage_stats()
    if slippage_stats.get("total_with_slippage", 0) >= 3 and slippage_stats.get("avg_slippage_pct") is not None:
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
        logger.info(
            f"Feedback injection | Slippage alert injected — "
            f"avg={slippage_stats['avg_slippage_pct']:.3f}%, "
            f"max={slippage_stats['max_slippage_pct']:.3f}%"
        )

    if not losses and not wins:
        logger.info("Feedback injection | No trading history — using clean prompt")

    return full_prompt
