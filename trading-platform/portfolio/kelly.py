"""
Kelly Criterion Position Sizer
--------------------------------
Computes optimal position sizes using a practical adaptation of the Kelly
Criterion suited for ETF-based trading with LLM conviction scores.

Full Kelly formula: f* = (bp - q) / b
  where b = net odds (expected gain per unit risked)
        p = probability of win (conviction_score)
        q = probability of loss (1 - conviction_score)

For our system we derive b from the take_profit and stop_loss percentages:
  b = take_profit_pct / abs(stop_loss_pct)

This gives: f* = (b * p - q) / b = p - q/b

We then apply a fractional Kelly (50% of full Kelly) as a safety buffer,
and hard-cap each position at MAX_KELLY_FRACTION.

A negative Kelly result means the bet has negative expected value — in that
case, the slot is forced to SGOV regardless of conviction score.
"""

MAX_KELLY_FRACTION = 0.20
KELLY_MULTIPLIER   = 0.50   # Use half-Kelly for risk management


def compute_kelly(
    conviction_score: float,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> float:
    """
    Compute the position size as a fraction of total portfolio.

    Args:
        conviction_score: LLM probability of success (0.0 – 1.0).
        take_profit_pct:  Expected gain as a positive decimal (e.g. 0.10 = 10%).
        stop_loss_pct:    Maximum acceptable loss as a negative decimal (e.g. -0.05).

    Returns:
        Kelly fraction clamped to [0.0, MAX_KELLY_FRACTION].
        Returns 0.0 if the trade has negative expected value.
    """
    if conviction_score <= 0 or take_profit_pct <= 0 or stop_loss_pct >= 0:
        return 0.0

    p = conviction_score
    q = 1.0 - conviction_score
    b = take_profit_pct / abs(stop_loss_pct)

    full_kelly = (b * p - q) / b

    if full_kelly <= 0:
        return 0.0

    fractional_kelly = full_kelly * KELLY_MULTIPLIER
    return round(min(fractional_kelly, MAX_KELLY_FRACTION), 4)


def compute_kelly_for_slots(allocations: list[dict]) -> list[dict]:
    """
    Apply Kelly sizing to a list of allocation dicts (from LLM output).
    Overwrites the 'kelly_fraction' field with the computed value.

    Args:
        allocations: List of dicts, each with conviction_score,
                     take_profit_pct, stop_loss_pct.

    Returns:
        Same list with kelly_fraction updated in-place.
    """
    for slot in allocations:
        slot["kelly_fraction"] = compute_kelly(
            conviction_score=slot["conviction_score"],
            take_profit_pct=slot["take_profit_pct"],
            stop_loss_pct=slot["stop_loss_pct"],
        )
    return allocations


def normalise_kelly_fractions(allocations: list[dict]) -> list[dict]:
    """
    Ensure total Kelly fractions across all slots do not exceed 1.0.
    If they do, scale all fractions proportionally downward.
    Slots with kelly_fraction = 0.0 (SGOV) are excluded from scaling.

    Args:
        allocations: List with 'kelly_fraction' and 'ticker' keys.

    Returns:
        Same list with kelly_fraction values normalised.
    """
    active = [s for s in allocations if s.get("ticker") != "SGOV" and s["kelly_fraction"] > 0]
    total = sum(s["kelly_fraction"] for s in active)

    if total > 1.0:
        scale = 1.0 / total
        for slot in active:
            slot["kelly_fraction"] = round(slot["kelly_fraction"] * scale, 4)

    return allocations
