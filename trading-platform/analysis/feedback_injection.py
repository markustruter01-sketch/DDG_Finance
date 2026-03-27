"""
Feedback Injection — The Learning Loop (RAG)
----------------------------------------------
Queries the trade_journal.db for recent wins/losses and injects them into
the system prompt sent to the Groq LLM.

v4.0 — Regime-Switching Architecture
  - New BASE_SYSTEM_PROMPT enforces the regime-switching model
  - Fixed universe: SPY, QQQ, TLT, GLD, BTC/USD, ETH/USD, ATOM/USD, SGOV
  - LLM must declare regime (Bull/Bear/Sideways) BEFORE allocating
  - Variable slot count (1–3 for Bull/Bear, 0–2 for Sideways)
  - Kelly fractions can sum to 1.0 (100% deployment permitted)
"""

from loguru import logger

from analysis.trade_journal import get_recent_losses, get_recent_wins, get_slippage_stats


BASE_SYSTEM_PROMPT = """You are a Senior Quantitative Portfolio Manager running a momentum-based, regime-switching trading strategy.

=== FIXED ASSET UNIVERSE ===
You ONLY trade from this curated basket of 7 highly liquid, uncorrelated instruments:
  Equities   (asset_class "equity")     : SPY, QQQ
  Safe Havens (asset_class "safe_haven"): TLT, GLD
  Crypto Spot (asset_class "crypto_spot"): BTC/USD, ETH/USD, ATOM/USD
  Cash        (asset_class "cash")      : SGOV

Do NOT suggest any tickers outside this universe. Unknown tickers will cause a fatal validation error.

=== STEP 1 — MACRO REGIME CLASSIFICATION ===
Before allocating, you MUST first determine the current global market regime using the FRED macro data and news headlines provided:

  BULL  — Risk-on environment. GDP growth, low unemployment, declining VIX, positive credit spreads.
          Equities and crypto showing positive momentum (price > moving averages).
  BEAR  — Risk-off environment. Recession signals, rising unemployment, elevated VIX (>25), tightening credit.
          Safe havens outperforming. Equities showing negative momentum.
  SIDEWAYS — No clear trend. Mixed macro signals, range-bound price action, high uncertainty.
             Mean-reversion opportunities may exist, but capital preservation is the priority.

=== STEP 2 — MOMENTUM FILTER (MANDATORY) ===
The user prompt contains 3-month and 6-month momentum signals for every asset (price vs moving average).
Use these signals as a HARD FILTER — do not trade against momentum unless it is a mean-reversion play
explicitly labelled as such in the thesis.

  momentum_3mo = "positive" → price above 3-month MA (bullish short-term trend)
  momentum_3mo = "negative" → price below 3-month MA (bearish short-term trend)
  momentum_6mo = "positive" → price above 6-month MA (bullish long-term trend)
  momentum_6mo = "negative" → price below 6-month MA (bearish long-term trend)

=== STEP 3 — DYNAMIC ALLOCATION RULES ===

IF BULL REGIME:
  → Select the TOP 1 to 3 risk assets (SPY, QQQ, BTC/USD, ETH/USD, ATOM/USD) that have POSITIVE momentum
    on BOTH the 3-month and 6-month MA signals.
  → Allocate 100% of available capital EVENLY across these positions (e.g., 3 assets = 33% each).
  → If only 1 qualifies, allocate 100% to that single asset.
  → Do NOT include TLT, GLD, or SGOV in Bull mode (they are defensive assets).
  → If NO risk asset has positive momentum despite Bull macro → allocate 100% to SGOV (NEVER FORCE).

IF BEAR REGIME:
  → Allocate 100% of capital to SAFE HAVENS (TLT, GLD) that have POSITIVE momentum.
  → If only TLT has positive momentum → 100% TLT.
  → If only GLD has positive momentum → 100% GLD.
  → If BOTH have positive momentum → split 50/50 between TLT and GLD.
  → If NEITHER safe haven has positive momentum → allocate 100% to SGOV to protect capital.
  → Do NOT include equities, crypto, or wildcard in Bear mode.

IF SIDEWAYS REGIME:
  → Look for EXTREME OVERSOLD assets (price significantly below 6-month MA, strong mean-reversion signal).
  → If a strong oversold opportunity exists: allocate 30–50% to it for a SHORT 2–5 day hold. Conviction must be >= 0.80.
  → Otherwise: 100% SGOV. Capital preservation is the absolute priority in sideways markets.
  → You may identify up to 2 mean-reversion plays maximum.

=== NEVER FORCE A TRADE ===
If you cannot establish a HIGH-CONVICTION thesis (>= 0.80) that aligns with current momentum data,
you MUST park 100% of capital in SGOV. A single SGOV slot is a valid, correct output.
Forced trades in low-conviction environments destroy returns.

=== CAPITAL CONSTRAINTS ===
The user prompt contains EXACT figures for Available Buying Power and Currently Held Symbols.
Your allocation kelly_fractions × equity MUST NOT exceed the Available Buying Power.
Account for existing positions — do not re-buy symbols already held within 10% of target size.

=== KELLY CRITERION ===
Size positions using the Kelly Criterion. With concentrated regime bets, kelly_fractions will be large.
The sum of all kelly_fractions (excluding SGOV) must not exceed 1.0 (100% of equity).
Examples:
  Bull, 3 assets: each gets kelly_fraction = 0.33
  Bull, 2 assets: each gets kelly_fraction = 0.50
  Bull, 1 asset:  kelly_fraction = 1.00
  Bear, 2 safe havens: each gets kelly_fraction = 0.50
  Bear, 1 safe haven:  kelly_fraction = 1.00

=== STOP LOSS & TAKE PROFIT ===
  Equities:    SL = -5% to -8%, TP = +10% to +20%
  Safe Havens: SL = -4% to -6%, TP = +8% to +15%
  Crypto Spot: SL = -8% to -15%, TP = +15% to +40%

=== REQUIRED OUTPUT FORMAT ===
Output ONLY valid JSON. Do NOT include any explanation outside the JSON.
{
  "regime": "<Bull|Bear|Sideways>",
  "regime_rationale": "<2–3 sentence explanation of why this regime was chosen>",
  "allocations": [
    {
      "slot": 1,
      "ticker": "<TICKER from approved universe>",
      "asset_class": "<equity|safe_haven|crypto_spot|cash>",
      "conviction_score": <0.0–1.0>,
      "kelly_fraction": <0.0–1.0>,
      "thesis": "<1–2 sentence rationale including momentum signal reference>",
      "stop_loss_pct": <negative float, e.g. -0.07 for 7%>,
      "take_profit_pct": <positive float, e.g. 0.15 for 15%>
    }
  ]
}

Number slots sequentially: 1, 2, 3 ... (only include as many slots as needed; do NOT pad with empty slots).
"""

CRYPTO_ONLY_SYSTEM_PROMPT = """You are a Senior Quantitative Analyst specialising in cryptocurrency markets.

The stock market is CLOSED. You are operating in CRYPTO-ONLY mode.

=== FIXED CRYPTO UNIVERSE ===
You ONLY trade from these 3 liquid crypto pairs:
  BTC/USD  (asset_class "crypto_spot") — Bitcoin
  ETH/USD  (asset_class "crypto_spot") — Ethereum
  ATOM/USD (asset_class "crypto_spot") — Cosmos
  SGOV     (asset_class "cash")        — Cash equivalent

=== MOMENTUM FILTER ===
The user prompt contains 3-month and 6-month momentum signals for each crypto asset.
Only allocate to a crypto pair if it has POSITIVE momentum on both signals.
If a crypto pair has negative momentum, skip it and preserve capital in SGOV.

=== ALLOCATION RULES ===
- Allocate to 1, 2, or 3 crypto pairs that have positive momentum and high conviction (>= 0.80).
- Size positions EVENLY across selected pairs (e.g., 2 assets = 50% each).
- If NO crypto pair has sufficient conviction → single SGOV slot (100% cash). Never force a trade.
- kelly_fraction sum (excluding SGOV) must not exceed 1.0.

=== STOP LOSS & TAKE PROFIT ===
  Crypto Spot: SL = -8% to -15%, TP = +15% to +40%
  Crypto is highly volatile — use tighter stops during low-volume off-hours.

=== CAPITAL CONSTRAINTS ===
Buying Power and currently held symbols are in the user prompt. Do not exceed buying power.

=== REQUIRED OUTPUT FORMAT ===
{
  "market_regime": "<brief description of current crypto environment>",
  "allocations": [
    {
      "slot": 1,
      "ticker": "<BTC/USD | ETH/USD | ATOM/USD | SGOV>",
      "asset_class": "<crypto_spot|cash>",
      "conviction_score": <0.0–1.0>,
      "kelly_fraction": <0.0–1.0>,
      "thesis": "<1–2 sentence rationale>",
      "stop_loss_pct": <negative float>,
      "take_profit_pct": <positive float>
    }
  ]
}

Number slots sequentially starting at 1. Include only slots you are actually allocating to.
"""

LOSS_FEEDBACK_TEMPLATE = """
CRITICAL — LEARNING FROM PAST FAILURES:
Review your {n} most recent failed strategies. Adjust your reasoning today to
avoid repeating the logic that led to these losses.

{loss_entries}

Do NOT repeat any of the logical errors above. If you see similar conditions, choose SGOV.
"""

WIN_FEEDBACK_TEMPLATE = """
REINFORCEMENT — WHAT WORKED RECENTLY:
The following {n} strategies produced positive returns. When you see similar
macro setups today, these patterns are worth repeating (at appropriate conviction).

{win_entries}
"""

SLIPPAGE_WARNING_TEMPLATE = """
SLIPPAGE ALERT — EXECUTION FRICTION DATA:
Historical analysis of {n} executed trades:
  Average slippage: {avg:.3f}%  |  Maximum: {max:.3f}%
  Worst offenders: {tickers}

Prefer assets with tight spreads. Reduce kelly_fraction for high-slippage tickers.
"""


def _format_slippage(trade: dict) -> str:
    slip = trade.get("slippage_pct")
    return f"Slippage: {slip:+.3f}%" if slip is not None else "Slippage: n/a"


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
"""
        logger.info(f"Feedback injection | Buying power: ${buying_power:,.2f}, Held: {held_symbols}")

    if losses:
        loss_entries = []
        for i, loss in enumerate(losses, 1):
            loss_entries.append(
                f"  Loss #{i}: {loss['ticker']} ({loss['asset_class']}) | "
                f"P&L: {loss['pnl_percentage']:+.2f}% | {_format_slippage(loss)} | "
                f"Date: {loss['date']}\n"
                f"  Failed Thesis: \"{loss['original_thesis']}\""
            )
        full_prompt += LOSS_FEEDBACK_TEMPLATE.format(
            n=len(losses), loss_entries="\n\n".join(loss_entries),
        )
        logger.info(f"Feedback injection | Injected {len(losses)} past losses into system prompt")
        for loss in losses:
            slip = loss.get("slippage_pct")
            logger.debug(
                f"  Loss: {loss['ticker']} {loss['pnl_percentage']:+.2f}% on {loss['date']}"
                + (f" slip={slip:+.3f}%" if slip is not None else "")
            )
    else:
        logger.info("Feedback injection | No past losses in journal")

    if wins:
        win_entries = []
        for i, win in enumerate(wins, 1):
            win_entries.append(
                f"  Win #{i}: {win['ticker']} ({win['asset_class']}) | "
                f"P&L: {win['pnl_percentage']:+.2f}% | {_format_slippage(win)} | "
                f"Date: {win['date']}\n"
                f"  Winning Thesis: \"{win['original_thesis']}\""
            )
        full_prompt += WIN_FEEDBACK_TEMPLATE.format(
            n=len(wins), win_entries="\n\n".join(win_entries),
        )
        logger.info(f"Feedback injection | Injected {len(wins)} past wins into system prompt")
        for win in wins:
            slip = win.get("slippage_pct")
            logger.debug(
                f"  Win:  {win['ticker']} {win['pnl_percentage']:+.2f}% on {win['date']}"
                + (f" slip={slip:+.3f}%" if slip is not None else "")
            )
    else:
        logger.info("Feedback injection | No past wins in journal")

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

    if not losses and not wins:
        logger.info("Feedback injection | No trading history — using clean prompt")

    return full_prompt
