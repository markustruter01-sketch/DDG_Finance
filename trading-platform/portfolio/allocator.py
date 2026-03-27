"""
Portfolio Allocator
---------------------
Post-processes the raw LLM JSON output:

  1. Parse and validate with Pydantic (AllocationSlot / AnalysisOutput).
  2. Override: any slot with conviction < threshold → replace with SGOV.
  3. Recalculate Kelly fractions using our own Python formula (overrides LLM values).
  4. Normalise Kelly fractions so total ≤ 100%.
  5. Return the final validated AnalysisOutput.

This layer ensures that even if the LLM makes arithmetic errors on Kelly sizing
or sneaks in a low-conviction trade, our hard-coded Python defences catch it.
"""

import json
from typing import Any

from loguru import logger
from pydantic import ValidationError

from analysis.schemas import AllocationSlot, AnalysisOutput
from config.settings import settings
from portfolio.kelly import compute_kelly_for_slots, normalise_kelly_fractions

SGOV_SLOT_TEMPLATE = {
    "ticker": "SGOV",
    "asset_class": "cash",
    "conviction_score": 1.0,
    "kelly_fraction": 0.0,
    "thesis": "Conviction below threshold — holding short-term US Treasury ETF as cash equivalent.",
    "stop_loss_pct": -0.01,
    "take_profit_pct": 0.01,
}


def _enforce_conviction_threshold(allocations: list[dict]) -> list[dict]:
    """
    Hard-coded defence: replace any slot below the conviction threshold with SGOV.
    """
    threshold = settings.conviction_threshold
    enforced = []
    for slot in allocations:
        if slot["conviction_score"] < threshold and slot["ticker"] != "SGOV":
            logger.warning(
                f"Allocator | Slot {slot['slot']}: {slot['ticker']} conviction "
                f"{slot['conviction_score']:.0%} < {threshold:.0%} threshold → replacing with SGOV"
            )
            sgov = {**SGOV_SLOT_TEMPLATE, "slot": slot["slot"]}
            enforced.append(sgov)
        else:
            enforced.append(slot)
    return enforced


def process_llm_output(raw_json: str) -> AnalysisOutput:
    """
    Full allocation pipeline. Takes raw LLM JSON string, returns a validated
    AnalysisOutput with Python-computed Kelly fractions.

    Args:
        raw_json: Raw JSON string from Groq API call.

    Returns:
        Validated AnalysisOutput ready for execution.

    Raises:
        ValueError:       If JSON is malformed.
        ValidationError:  If the allocation structure violates Pydantic rules.
    """
    try:
        data: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    allocations: list[dict] = data.get("allocations", [])

    if len(allocations) != 10:
        raise ValueError(f"Expected 10 allocation slots, LLM returned {len(allocations)}")

    logger.info(f"Allocator | Processing {len(allocations)} slots from LLM output")

    allocations = _enforce_conviction_threshold(allocations)

    allocations = compute_kelly_for_slots(allocations)
    allocations = normalise_kelly_fractions(allocations)

    data["allocations"] = allocations

    try:
        output = AnalysisOutput.model_validate(data)
    except ValidationError as exc:
        logger.error(f"Allocator | Pydantic validation failed:\n{exc}")
        raise

    low_conv = output.low_conviction_slots()
    if low_conv:
        logger.warning(
            f"Allocator | {len(low_conv)} slots still below conviction threshold after enforcement"
        )

    total_kelly = sum(a.kelly_fraction for a in output.allocations if a.ticker != "SGOV")
    logger.info(
        f"Allocator | Final allocation — total deployed Kelly: {total_kelly:.1%} | "
        f"cash slots: {sum(1 for a in output.allocations if a.ticker == 'SGOV')}"
    )

    return output
