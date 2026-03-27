"""
Portfolio Allocator — Regime-Switching Architecture
-----------------------------------------------------
Post-processes the raw LLM JSON output:

  Full Market (Regime) mode:
    1. Parse & validate with Pydantic (RegimeAllocationSlot / RegimeAnalysisOutput).
    2. Override: slots with conviction < threshold → replace with SGOV.
    3. Recalculate Kelly fractions using even-weight Python formula
       (overrides LLM values for consistency within a regime).
    4. Normalise Kelly fractions so total ≤ 1.0 (100% of equity).
    5. Return the final validated RegimeAnalysisOutput.

  Crypto-Only mode (off-hours):
    Same pipeline for CryptoAnalysisOutput with BTC/ETH/ATOM universe.
"""

import json
from typing import Any

from loguru import logger
from pydantic import ValidationError

from analysis.schemas import (
    RegimeAllocationSlot, RegimeAnalysisOutput,
    CryptoAllocationSlot, CryptoAnalysisOutput,
)
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
    threshold = settings.conviction_threshold
    enforced = []
    for slot in allocations:
        if slot["conviction_score"] < threshold and slot["ticker"] != "SGOV":
            logger.warning(
                f"Allocator | Slot {slot['slot']}: {slot['ticker']} conviction "
                f"{slot['conviction_score']:.0%} < {threshold:.0%} threshold → replacing with SGOV"
            )
            enforced.append({**SGOV_SLOT_TEMPLATE, "slot": slot["slot"]})
        else:
            enforced.append(slot)
    return enforced


def _apply_even_weight(allocations: list[dict]) -> list[dict]:
    """
    Override LLM kelly_fractions with even-weight sizing across non-SGOV slots.
    This enforces the regime rule: "allocate evenly across top N assets".
    """
    active = [s for s in allocations if s["ticker"] != "SGOV" and s["conviction_score"] >= settings.conviction_threshold]
    if not active:
        return allocations

    weight = round(1.0 / len(active), 4)
    result = []
    for slot in allocations:
        if slot["ticker"] != "SGOV" and slot["conviction_score"] >= settings.conviction_threshold:
            result.append({**slot, "kelly_fraction": weight})
        else:
            result.append({**slot, "kelly_fraction": 0.0})
    return result


def process_regime_llm_output(raw_json: str) -> RegimeAnalysisOutput:
    """
    Full regime-switching allocation pipeline.
    Takes raw LLM JSON string, returns a validated RegimeAnalysisOutput.
    """
    try:
        data: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    allocations: list[dict] = data.get("allocations", [])
    regime = data.get("regime", "unknown")

    if not allocations:
        raise ValueError("LLM returned no allocation slots")

    logger.info(f"Allocator | Regime={regime} | Processing {len(allocations)} slot(s) from LLM output")

    allocations = _enforce_conviction_threshold(allocations)
    allocations = _apply_even_weight(allocations)
    allocations = normalise_kelly_fractions(allocations)

    data["allocations"] = allocations

    try:
        output = RegimeAnalysisOutput.model_validate(data)
    except ValidationError as exc:
        logger.error(f"Allocator | Pydantic validation failed:\n{exc}")
        raise

    non_cash = [a for a in output.allocations if a.ticker != "SGOV"]
    total_kelly = sum(a.kelly_fraction for a in non_cash)
    logger.info(
        f"Allocator | Regime={output.regime} | "
        f"{len(non_cash)} active position(s) | "
        f"total Kelly={total_kelly:.1%} | "
        f"cash slots={sum(1 for a in output.allocations if a.ticker == 'SGOV')}"
    )

    return output


def process_crypto_llm_output(raw_json: str) -> CryptoAnalysisOutput:
    """
    Crypto-only allocation pipeline for off-hours trading.
    """
    try:
        data: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    allocations: list[dict] = data.get("allocations", [])

    if not allocations:
        raise ValueError("LLM returned no crypto allocation slots")

    logger.info(f"Allocator | Crypto mode | Processing {len(allocations)} slot(s) from LLM output")

    allocations = _enforce_conviction_threshold(allocations)
    allocations = _apply_even_weight(allocations)
    allocations = normalise_kelly_fractions(allocations)

    data["allocations"] = allocations

    try:
        output = CryptoAnalysisOutput.model_validate(data)
    except ValidationError as exc:
        logger.error(f"Allocator | Crypto Pydantic validation failed:\n{exc}")
        raise

    non_cash = [a for a in output.allocations if a.ticker != "SGOV"]
    total_kelly = sum(a.kelly_fraction for a in non_cash)
    logger.info(
        f"Allocator | Crypto: {len(non_cash)} active crypto position(s) | "
        f"total Kelly={total_kelly:.1%}"
    )

    return output
