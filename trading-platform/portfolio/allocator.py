"""
Portfolio Allocator — Regime-Switching Architecture
-----------------------------------------------------
v4.3 — Leveraged Risk Satellite + SPY 20-Day EMA Anchor

Post-processes the raw LLM JSON output:

  Full Market (Regime) mode:
    1. Parse & validate with Pydantic (RegimeAllocationSlot / RegimeAnalysisOutput).
    2. ── SPY EMA ANCHOR (NEW) ────────────────────────────────────────────────
       If regime == "Bull" AND SPY price < SPY 20-Day EMA:
         • Override regime → "Sideways".
         • Replace all leveraged_risk slots with SGOV.
       ──────────────────────────────────────────────────────────────────────
    3. Override: slots with conviction < threshold → replace with SGOV.
    4. Recalculate Kelly fractions using even-weight Python formula
       (overrides LLM values for consistency within a regime).
    5. ── LEVERAGED FENCE (NEW) ──────────────────────────────────────────────
       Cap total leveraged_risk kelly_fraction to MAX_LEVERAGED_KELLY (20%).
       Excess is swept into an explicit SGOV slot so it gets purchased.
       ──────────────────────────────────────────────────────────────────────
    6. Normalise Kelly fractions so total ≤ 1.0 (100% of equity).
    7. Return the final validated RegimeAnalysisOutput.

  Crypto-Only mode (off-hours):
    Same pipeline for CryptoAnalysisOutput with BTC/ETH universe.
    No leveraged fence or EMA anchor applies in crypto-only mode.
"""

import json
from typing import Any

from loguru import logger
from pydantic import ValidationError

from analysis.schemas import (
    RegimeAllocationSlot, RegimeAnalysisOutput,
    CryptoAllocationSlot, CryptoAnalysisOutput,
    LEVERAGED_RISK_TICKERS,
)
from config.settings import settings
from portfolio.kelly import compute_kelly_for_slots, normalise_kelly_fractions

# ── Constants ────────────────────────────────────────────────────────────────

MAX_LEVERAGED_KELLY: float = 0.20   # 20 % of equity max for leveraged_risk group

SGOV_SLOT_TEMPLATE = {
    "ticker":       "SGOV",
    "asset_class":  "cash",
    "conviction_score": 1.0,
    "kelly_fraction":   0.0,
    "thesis": "Conviction below threshold — holding short-term US Treasury ETF as cash equivalent.",
    "stop_loss_pct":    -0.01,
    "take_profit_pct":   0.01,
}


# ── Step 1: SPY 20-Day EMA Regime Anchor ─────────────────────────────────────

def _apply_spy_ema_anchor(data: dict, regime: str) -> tuple[str, dict]:
    """
    Hard-gate: if the LLM declared "Bull" but SPY is below its 20-Day EMA,
    override the regime to "Sideways" and replace all leveraged_risk slots
    with SGOV before any Kelly sizing is applied.

    Returns (effective_regime, possibly_mutated_data).
    """
    if regime != "Bull":
        return regime, data

    try:
        from data.yfinance_client import get_spy_ema_anchor
        anchor = get_spy_ema_anchor()
    except Exception as exc:
        logger.warning(f"EMA Anchor | Could not read SPY cache: {exc} — anchor skipped (permissive)")
        return regime, data

    spy_price       = anchor.get("spy_price")
    spy_ema_20d     = anchor.get("spy_ema_20d")
    spy_above_ema_20 = anchor.get("spy_above_ema_20")

    if spy_above_ema_20 is None:
        logger.warning(
            "EMA Anchor | SPY EMA-20 data unavailable — permitting Bull regime without anchor check. "
            "Run a full market-data fetch first to populate the cache."
        )
        return regime, data

    if spy_above_ema_20:
        logger.info(
            f"EMA Anchor | SPY ${spy_price:.2f} > EMA-20 ${spy_ema_20d:.2f} — "
            f"Bull regime CONFIRMED. Leveraged risk positions permitted."
        )
        return regime, data

    # ── SPY is BELOW its 20-Day EMA: block Bull, override to Sideways ────────
    logger.warning(
        f"EMA Anchor | SPY ${spy_price:.2f} < EMA-20 ${spy_ema_20d:.2f} — "
        f"LLM attempted Bull regime but technical anchor BLOCKED it. "
        f"Overriding regime → Sideways. All leveraged_risk slots replaced with SGOV."
    )

    allocations: list[dict] = data.get("allocations", [])
    new_allocations = []
    letf_replaced = 0
    for slot in allocations:
        if slot.get("asset_class") == "leveraged_risk" or slot.get("ticker") in LEVERAGED_RISK_TICKERS:
            new_allocations.append({
                **SGOV_SLOT_TEMPLATE,
                "slot": slot["slot"],
                "thesis": (
                    f"EMA Anchor override: SPY ${spy_price:.2f} < EMA-20 ${spy_ema_20d:.2f}. "
                    f"Leveraged position {slot.get('ticker', '?')} blocked — holding SGOV."
                ),
            })
            letf_replaced += 1
        else:
            new_allocations.append(slot)

    if letf_replaced:
        logger.warning(f"EMA Anchor | {letf_replaced} leveraged_risk slot(s) replaced with SGOV.")

    data = {**data, "regime": "Sideways", "allocations": new_allocations}
    return "Sideways", data


# ── Step 2: Conviction Threshold ─────────────────────────────────────────────

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


# ── Step 3: Even-Weight Kelly ─────────────────────────────────────────────────

def _apply_even_weight(allocations: list[dict]) -> list[dict]:
    """
    Override LLM kelly_fractions with even-weight sizing across non-SGOV slots.
    This enforces the regime rule: "allocate evenly across top N assets".
    """
    active = [
        s for s in allocations
        if s["ticker"] != "SGOV" and s["conviction_score"] >= settings.conviction_threshold
    ]
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


# ── Step 4: Leveraged Satellite Fence ────────────────────────────────────────

def _enforce_leveraged_fence(allocations: list[dict]) -> list[dict]:
    """
    Cap total kelly_fraction for the leveraged_risk group to MAX_LEVERAGED_KELLY (20 %).

    If the combined leveraged allocation exceeds the cap:
      1. Scale all leveraged_risk slots down proportionally so their total = 20 %.
      2. Inject a SGOV slot carrying the excess kelly_fraction so the capital is
         explicitly purchased as SGOV rather than left as untracked cash.
      3. Renumber all slots sequentially.

    If leveraged slots are within the fence, no changes are made.
    """
    leveraged = [
        s for s in allocations
        if (s.get("asset_class") == "leveraged_risk" or s.get("ticker") in LEVERAGED_RISK_TICKERS)
        and s["kelly_fraction"] > 0
    ]

    if not leveraged:
        return allocations

    total_leveraged = sum(s["kelly_fraction"] for s in leveraged)

    if total_leveraged <= MAX_LEVERAGED_KELLY:
        logger.info(
            f"Allocator | Leveraged fence: total={total_leveraged:.1%} ≤ "
            f"{MAX_LEVERAGED_KELLY:.0%} cap — no adjustment needed"
        )
        return allocations

    # Scale leveraged slots down proportionally
    scale = MAX_LEVERAGED_KELLY / total_leveraged
    excess_kelly = round(total_leveraged - MAX_LEVERAGED_KELLY, 4)

    tickers_capped = [s["ticker"] for s in leveraged]
    logger.warning(
        f"Allocator | Leveraged fence TRIGGERED: {tickers_capped} total={total_leveraged:.1%} "
        f"exceeds {MAX_LEVERAGED_KELLY:.0%} cap. "
        f"Scale factor={scale:.3f} | Excess kelly={excess_kelly:.4f} swept → SGOV."
    )

    result = []
    for slot in allocations:
        if (
            (slot.get("asset_class") == "leveraged_risk" or slot.get("ticker") in LEVERAGED_RISK_TICKERS)
            and slot["kelly_fraction"] > 0
        ):
            capped = round(slot["kelly_fraction"] * scale, 4)
            logger.info(
                f"Allocator | Leveraged fence: {slot['ticker']} kelly "
                f"{slot['kelly_fraction']:.4f} → {capped:.4f}"
            )
            result.append({**slot, "kelly_fraction": capped})
        else:
            result.append(slot)

    # Inject SGOV slot for the swept excess (non-zero kelly → executor will buy it)
    if excess_kelly >= 0.001:
        max_slot = max(s["slot"] for s in result)
        result.append({
            **SGOV_SLOT_TEMPLATE,
            "slot":           max_slot + 1,
            "kelly_fraction": excess_kelly,
            "thesis": (
                f"Leveraged risk fence: {excess_kelly:.1%} excess capital swept from "
                f"capped leveraged_risk allocation ({', '.join(tickers_capped)})."
            ),
        })
        logger.info(
            f"Allocator | SGOV sweep slot injected: kelly={excess_kelly:.4f} "
            f"({excess_kelly * 100:.1f}% of equity)."
        )

    # Renumber all slots sequentially (1-based, preserving order)
    for i, slot in enumerate(result, start=1):
        slot["slot"] = i

    return result


# ── Public Pipeline Functions ─────────────────────────────────────────────────

def process_regime_llm_output(raw_json: str) -> RegimeAnalysisOutput:
    """
    Full regime-switching allocation pipeline.
    Takes raw LLM JSON string, returns a validated RegimeAnalysisOutput.

    Pipeline order:
      parse → EMA anchor → conviction threshold → even weight → leveraged fence
      → kelly normalise → Pydantic validate
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

    # Step 1: SPY 20-Day EMA Anchor — may override Bull → Sideways
    regime, data = _apply_spy_ema_anchor(data, regime)
    allocations = data.get("allocations", allocations)

    # Step 2: Conviction threshold
    allocations = _enforce_conviction_threshold(allocations)

    # Step 3: Even-weight Kelly sizing
    allocations = _apply_even_weight(allocations)

    # Step 4: Leveraged satellite fence (20 % cap + SGOV sweep)
    allocations = _enforce_leveraged_fence(allocations)

    # Step 5: Normalise so total ≤ 1.0
    allocations = normalise_kelly_fractions(allocations)

    data["allocations"] = allocations
    data["regime"] = regime

    try:
        output = RegimeAnalysisOutput.model_validate(data)
    except ValidationError as exc:
        logger.error(f"Allocator | Pydantic validation failed:\n{exc}")
        raise

    non_cash = [a for a in output.allocations if a.ticker != "SGOV"]
    leveraged = [a for a in non_cash if a.ticker in LEVERAGED_RISK_TICKERS]
    total_kelly = sum(a.kelly_fraction for a in non_cash)
    total_leveraged_kelly = sum(a.kelly_fraction for a in leveraged)

    logger.info(
        f"Allocator | Regime={output.regime} | "
        f"{len(non_cash)} active position(s) | "
        f"total Kelly={total_kelly:.1%} | "
        f"leveraged_risk Kelly={total_leveraged_kelly:.1%} (cap={MAX_LEVERAGED_KELLY:.0%}) | "
        f"cash slots={sum(1 for a in output.allocations if a.ticker == 'SGOV')}"
    )

    return output


def process_crypto_llm_output(raw_json: str) -> CryptoAnalysisOutput:
    """
    Crypto-only allocation pipeline for off-hours trading.
    No EMA anchor or leveraged fence applies in crypto-only mode.
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
