"""
Portfolio Allocator — Regime-Switching Architecture
-----------------------------------------------------
v4.4 — Volatility-Adjusted Sizing + 82% Utilization Target + Asset Class Caps

Post-processes the raw LLM JSON output:

  Full Market (Regime) mode:
    1. Parse & validate with Pydantic.
    2. SPY EMA Anchor — override Bull → Sideways if SPY < EMA-20;
       replace all leveraged_risk slots with SGOV.
    3. Conviction threshold — low-conviction slots → SGOV.
    4. ── VOLATILITY-ADJUSTED SIZING (v4.4) ──────────────────────────────
       Replace even-weight with inverse-volatility sizing:
         weight_i ∝ 1 / annualised_volatility_i
       Target total deployment: 82 % of equity (TARGET_UTILIZATION).
       Per-asset cap: 15 % (MAX_POSITION_KELLY).
       Falls back to even-weight if volatility data unavailable.
       ──────────────────────────────────────────────────────────────────
    5. ── ASSET CLASS CONCENTRATION CAP (v4.4) ───────────────────────────
       Cap any single asset class to MAX_ASSET_CLASS_KELLY (35 %).
       Excess is swept into a SGOV slot so capital is explicitly bought.
       ──────────────────────────────────────────────────────────────────
    6. ── LEVERAGED FENCE (v4.3) ──────────────────────────────────────────
       Cap leveraged_risk group to MAX_LEVERAGED_KELLY (20 %).
       Excess swept to SGOV.
       ──────────────────────────────────────────────────────────────────
    7. Normalise Kelly fractions so total ≤ 1.0.
    8. Return validated RegimeAnalysisOutput.

  Crypto-Only mode (off-hours):
    Same pipeline for CryptoAnalysisOutput — no EMA anchor or leveraged fence.
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

# ── Allocation Constants ─────────────────────────────────────────────────────

TARGET_UTILIZATION:    float = 0.82   # 82% of equity actively deployed
MAX_POSITION_KELLY:    float = 0.15   # 15% max per individual position
MAX_ASSET_CLASS_KELLY: float = 0.35   # 35% max per asset class
MAX_LEVERAGED_KELLY:   float = 0.20   # 20% max for entire leveraged_risk group

SGOV_SLOT_TEMPLATE = {
    "ticker":           "SGOV",
    "asset_class":      "cash",
    "conviction_score": 1.0,
    "kelly_fraction":   0.0,
    "thesis": "Conviction below threshold — holding short-term US Treasury ETF as cash equivalent.",
    "stop_loss_pct":    -0.01,
    "take_profit_pct":   0.01,
}


# ── Slot utilities ────────────────────────────────────────────────────────────

def _renumber_slots(allocations: list[dict]) -> list[dict]:
    for i, slot in enumerate(allocations, start=1):
        slot["slot"] = i
    return allocations


def _inject_sgov_slot(allocations: list[dict], kelly: float, thesis: str) -> list[dict]:
    """Append a SGOV slot with non-zero kelly (will be actively purchased by executor)."""
    if kelly < 0.001:
        return allocations
    max_slot = max(s["slot"] for s in allocations)
    allocations.append({
        **SGOV_SLOT_TEMPLATE,
        "slot":           max_slot + 1,
        "kelly_fraction": round(kelly, 4),
        "thesis":         thesis,
    })
    return _renumber_slots(allocations)


# ── Step 1: SPY 20-Day EMA Regime Anchor ─────────────────────────────────────

def _apply_spy_ema_anchor(data: dict, regime: str) -> tuple[str, dict]:
    """
    Hard gate: Bull regime is ONLY confirmed if SPY price > SPY 20-Day EMA.
    If blocked, regime overrides to Sideways and all leveraged_risk slots
    are replaced with SGOV before any sizing is applied.
    """
    if regime != "Bull":
        return regime, data

    try:
        from data.yfinance_client import get_spy_ema_anchor
        anchor = get_spy_ema_anchor()
    except Exception as exc:
        logger.warning(f"EMA Anchor | Could not read SPY cache: {exc} — permissive (Bull allowed)")
        return regime, data

    spy_price        = anchor.get("spy_price")
    spy_ema_20d      = anchor.get("spy_ema_20d")
    spy_above_ema_20 = anchor.get("spy_above_ema_20")

    if spy_above_ema_20 is None:
        logger.warning("EMA Anchor | SPY EMA-20 data unavailable — permitting Bull regime without anchor check.")
        return regime, data

    if spy_above_ema_20:
        logger.info(
            f"EMA Anchor | SPY ${spy_price:.2f} > EMA-20 ${spy_ema_20d:.2f} — "
            f"Bull regime CONFIRMED. Leveraged risk positions permitted."
        )
        return regime, data

    logger.warning(
        f"EMA Anchor | SPY ${spy_price:.2f} < EMA-20 ${spy_ema_20d:.2f} — "
        f"Bull regime BLOCKED → overriding to Sideways. All LETF slots replaced with SGOV."
    )

    allocations: list[dict] = data.get("allocations", [])
    new_allocs = []
    letf_replaced = 0
    for slot in allocations:
        if slot.get("asset_class") == "leveraged_risk" or slot.get("ticker") in LEVERAGED_RISK_TICKERS:
            new_allocs.append({
                **SGOV_SLOT_TEMPLATE,
                "slot": slot["slot"],
                "thesis": (
                    f"EMA Anchor override: SPY ${spy_price:.2f} < EMA-20 ${spy_ema_20d:.2f}. "
                    f"Leveraged position {slot.get('ticker', '?')} blocked — holding SGOV."
                ),
            })
            letf_replaced += 1
        else:
            new_allocs.append(slot)

    if letf_replaced:
        logger.warning(f"EMA Anchor | {letf_replaced} LETF slot(s) replaced with SGOV.")

    data = {**data, "regime": "Sideways", "allocations": new_allocs}
    return "Sideways", data


# ── Step 2: Conviction Threshold ──────────────────────────────────────────────

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


# ── Step 3: Volatility-Adjusted Sizing ───────────────────────────────────────

def _apply_volatility_adjusted_weight(allocations: list[dict]) -> list[dict]:
    """
    Assign kelly_fractions using inverse-volatility weighting, targeting
    TARGET_UTILIZATION (82%) of equity deployed.

    Algorithm:
      1. Look up each ticker's 20d annualised volatility from the market-data cache.
      2. weight_i = (1 / vol_i) — lower volatility → larger allocation.
      3. Normalise so the sum = min(TARGET_UTILIZATION, n × MAX_POSITION_KELLY).
      4. Iteratively cap each position at MAX_POSITION_KELLY and redistribute
         the excess to uncapped positions until stable.
      5. Falls back to even-weight if volatility data is unavailable for any ticker.
    """
    threshold = settings.conviction_threshold
    active = [
        s for s in allocations
        if s["ticker"] != "SGOV" and s["conviction_score"] >= threshold
    ]
    if not active:
        return allocations

    n = len(active)

    # ── Collect volatility data ───────────────────────────────────────────────
    try:
        from data.yfinance_client import get_cached_market_data
        cache = get_cached_market_data()
    except Exception:
        cache = None

    inv_vols: dict[str, float] = {}
    missing_vol = []
    for slot in active:
        ticker = slot["ticker"]
        vol = None
        if cache:
            vol = cache.get("by_ticker", {}).get(ticker, {}).get("volatility_20d_annualised_pct")
        if vol and vol > 0:
            inv_vols[ticker] = 1.0 / vol
        else:
            missing_vol.append(ticker)
            inv_vols[ticker] = 1.0  # neutral weight if missing

    if missing_vol:
        logger.info(
            f"Allocator | Vol data missing for {missing_vol} — using uniform inverse-vol weight"
        )

    # ── Compute initial weights ───────────────────────────────────────────────
    total_inv_vol = sum(inv_vols.values())
    # Realistic maximum: can't exceed n × per-asset cap
    realistic_target = min(TARGET_UTILIZATION, n * MAX_POSITION_KELLY)
    raw_weights: dict[str, float] = {
        t: (v / total_inv_vol) * realistic_target for t, v in inv_vols.items()
    }

    # ── Iterative cap-and-redistribute ───────────────────────────────────────
    weights = dict(raw_weights)
    for _iteration in range(10):
        capped = {t: min(w, MAX_POSITION_KELLY) for t, w in weights.items()}
        excess = sum(weights[t] - capped[t] for t in weights)
        weights = capped

        if excess < 1e-6:
            break
        uncapped = [t for t, w in weights.items() if w < MAX_POSITION_KELLY - 1e-6]
        if not uncapped:
            break
        extra_each = excess / len(uncapped)
        for t in uncapped:
            weights[t] = min(weights[t] + extra_each, MAX_POSITION_KELLY)

    total_deployed = sum(weights.values())
    vol_labels = [f"{t}={w:.1%}" for t, w in sorted(weights.items(), key=lambda x: -x[1])]
    logger.info(
        f"Allocator | Vol-adjusted sizing: [{', '.join(vol_labels)}] "
        f"total={total_deployed:.1%} (target={realistic_target:.1%})"
    )

    # ── Apply weights to allocations ──────────────────────────────────────────
    result = []
    for slot in allocations:
        if slot["ticker"] != "SGOV" and slot["conviction_score"] >= threshold:
            w = round(weights.get(slot["ticker"], 0.0), 4)
            result.append({**slot, "kelly_fraction": w})
        else:
            result.append({**slot, "kelly_fraction": 0.0})
    return result


# ── Step 4: Asset Class Concentration Cap ─────────────────────────────────────

def _enforce_asset_class_cap(allocations: list[dict]) -> list[dict]:
    """
    Cap total kelly_fraction per asset_class to MAX_ASSET_CLASS_KELLY (35%).
    If any class exceeds this, all slots in that class are scaled down
    proportionally and a SGOV slot is injected with the excess kelly.
    """
    class_totals: dict[str, float] = {}
    for slot in allocations:
        if slot["ticker"] == "SGOV" or slot["kelly_fraction"] == 0:
            continue
        cls = slot.get("asset_class", "unknown")
        class_totals[cls] = class_totals.get(cls, 0.0) + slot["kelly_fraction"]

    breached = {cls: total for cls, total in class_totals.items() if total > MAX_ASSET_CLASS_KELLY}
    if not breached:
        return allocations

    for cls, total in breached.items():
        logger.warning(
            f"Allocator | Asset-class cap: {cls} total={total:.1%} > "
            f"{MAX_ASSET_CLASS_KELLY:.0%} cap — scaling down proportionally"
        )

    total_excess = 0.0
    result = []
    for slot in allocations:
        cls = slot.get("asset_class", "unknown")
        if slot["ticker"] != "SGOV" and slot["kelly_fraction"] > 0 and cls in breached:
            scale = MAX_ASSET_CLASS_KELLY / breached[cls]
            original = slot["kelly_fraction"]
            capped = round(original * scale, 4)
            excess = original - capped
            total_excess += excess
            logger.info(
                f"Allocator | Asset-class cap: {slot['ticker']} kelly "
                f"{original:.4f} → {capped:.4f} (excess={excess:.4f})"
            )
            result.append({**slot, "kelly_fraction": capped})
        else:
            result.append(slot)

    if total_excess >= 0.001:
        result = _inject_sgov_slot(
            result, total_excess,
            thesis=f"Asset-class concentration cap: {total_excess:.1%} excess swept from "
                   f"{list(breached.keys())} to SGOV.",
        )

    return result


# ── Step 5: Leveraged Satellite Fence ─────────────────────────────────────────

def _enforce_leveraged_fence(allocations: list[dict]) -> list[dict]:
    """
    Cap total kelly_fraction for the leveraged_risk group to MAX_LEVERAGED_KELLY (20%).
    Excess is injected as a non-zero-kelly SGOV slot so it is actively purchased.
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
            f"{MAX_LEVERAGED_KELLY:.0%} cap — no adjustment"
        )
        return allocations

    scale = MAX_LEVERAGED_KELLY / total_leveraged
    excess_kelly = round(total_leveraged - MAX_LEVERAGED_KELLY, 4)
    tickers_capped = [s["ticker"] for s in leveraged]

    logger.warning(
        f"Allocator | Leveraged fence TRIGGERED: {tickers_capped} total={total_leveraged:.1%} "
        f"→ capped to {MAX_LEVERAGED_KELLY:.0%} | excess={excess_kelly:.4f} swept to SGOV"
    )

    result = []
    for slot in allocations:
        is_letf = (
            slot.get("asset_class") == "leveraged_risk"
            or slot.get("ticker") in LEVERAGED_RISK_TICKERS
        )
        if is_letf and slot["kelly_fraction"] > 0:
            result.append({**slot, "kelly_fraction": round(slot["kelly_fraction"] * scale, 4)})
        else:
            result.append(slot)

    if excess_kelly >= 0.001:
        result = _inject_sgov_slot(
            result, excess_kelly,
            thesis=f"Leveraged risk fence: {excess_kelly:.1%} excess swept from "
                   f"{', '.join(tickers_capped)}.",
        )

    return result


# ── Bear Regime Controls ──────────────────────────────────────────────────────

BEAR_KELLY_MULTIPLIER = 0.50   # Additional position-size haircut in Bear/RISK-OFF
SAFE_HAVEN_TICKERS    = {"GLD", "TLT"}   # Safe-haven assets checked for positive momentum


def _apply_bear_half_kelly(allocations: list[dict]) -> list[dict]:
    """
    Bear regime capital-preservation step.
    Applies an additional 0.50x multiplier to all non-SGOV kelly_fractions,
    then injects the freed capacity as a SGOV slot.
    This is on top of the existing half-Kelly baked into the vol-adjusted sizing,
    making it an effective quarter-Kelly in a confirmed Bear regime.
    """
    active = [s for s in allocations if s["ticker"] != "SGOV" and s["kelly_fraction"] > 0]
    if not active:
        return allocations

    excess = 0.0
    result = []
    for slot in allocations:
        if slot["ticker"] != "SGOV" and slot["kelly_fraction"] > 0:
            original_frac = slot["kelly_fraction"]
            new_frac = round(original_frac * BEAR_KELLY_MULTIPLIER, 4)
            excess += original_frac - new_frac
            result.append({**slot, "kelly_fraction": new_frac})
        else:
            result.append(slot)

    logger.warning(
        f"Allocator | BEAR Half-Kelly: all positions scaled by {BEAR_KELLY_MULTIPLIER:.0%} "
        f"— {excess:.1%} excess capital swept to SGOV"
    )

    if excess >= 0.001:
        result = _inject_sgov_slot(
            result, excess,
            thesis=(
                f"Bear Regime capital preservation: additional {BEAR_KELLY_MULTIPLIER:.0%} position-size "
                f"haircut applied — excess {excess:.1%} held as SGOV."
            ),
        )

    return result


def _has_safe_haven_momentum(allocations: list[dict]) -> bool:
    """
    Returns True if any SGOV-replacement safe-haven asset (GLD or TLT) that
    appears in the allocation list has positive 3-month momentum in the
    market data cache.  If neither ticker is in the allocation, returns True
    (no SGOV sweep — we can't assert the condition is failed).
    """
    present_safe_havens = [
        s["ticker"] for s in allocations
        if s["ticker"] in SAFE_HAVEN_TICKERS and s["ticker"] != "SGOV"
    ]
    if not present_safe_havens:
        return True  # no safe havens in allocation — don't force SGOV

    try:
        from data.yfinance_client import get_cached_market_data
        cache = get_cached_market_data()
        by_ticker = cache.get("by_ticker", {}) if cache else {}
        for ticker in present_safe_havens:
            mom = by_ticker.get(ticker, {}).get("momentum_3mo", "negative")
            if mom == "positive":
                return True
    except Exception as exc:
        logger.debug(f"Allocator | Could not read safe-haven momentum: {exc}")
        return True   # fail-safe: don't force SGOV if we can't check

    return False   # no safe haven has positive 3-month momentum


def _apply_bear_sgov_default(allocations: list[dict]) -> list[dict]:
    """
    Bear regime SGOV default sweep.
    If NO safe-haven asset (GLD, TLT) in the allocation shows positive
    3-month momentum, force ALL non-SGOV slots to SGOV.
    This ensures that when even the safe havens are in downtrends the bot
    holds 100% of non-vault equity in short-term Treasuries.
    """
    if _has_safe_haven_momentum(allocations):
        return allocations  # at least one safe haven is bullish — normal allocation OK

    # Calculate total kelly across all non-SGOV slots to preserve for SGOV
    total_redirected = sum(
        s["kelly_fraction"] for s in allocations
        if s["ticker"] != "SGOV" and s["kelly_fraction"] > 0
    )

    logger.warning(
        f"Allocator | BEAR SGOV Default: no safe-haven (GLD/TLT) has positive 3-month momentum — "
        f"ALL {total_redirected:.1%} non-SGOV allocation redirected to SGOV"
    )

    result = []
    max_slot = max(s["slot"] for s in allocations)
    sgov_slot = 1
    for slot in allocations:
        if slot["ticker"] == "SGOV":
            result.append(slot)
        else:
            result.append({
                **SGOV_SLOT_TEMPLATE,
                "slot": slot["slot"],
                "thesis": (
                    f"Bear Regime SGOV Default: no safe-haven has positive 3-month momentum. "
                    f"{slot['ticker']} ({slot.get('asset_class', 'unknown')}) replaced with SGOV."
                ),
            })

    if total_redirected >= 0.001:
        result = _inject_sgov_slot(
            result, total_redirected,
            thesis=(
                f"Bear Regime SGOV Default: {total_redirected:.1%} of equity swept to SGOV "
                f"— no GLD/TLT with positive 3-month momentum."
            ),
        )

    return result


# ── Public Pipeline Functions ─────────────────────────────────────────────────

def process_regime_llm_output(raw_json: str) -> RegimeAnalysisOutput:
    """
    Full regime-switching allocation pipeline.
    Pipeline order:
      parse → EMA anchor → conviction threshold → vol-adjusted sizing
      → asset-class cap → leveraged fence → kelly normalise → Pydantic validate
    """
    try:
        data: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    allocations: list[dict] = data.get("allocations", [])
    regime = data.get("regime", "unknown")

    if not allocations:
        raise ValueError("LLM returned no allocation slots")

    logger.info(
        f"Allocator | Regime={regime} | {len(allocations)} slot(s) | "
        f"target utilization={TARGET_UTILIZATION:.0%} | "
        f"per-asset cap={MAX_POSITION_KELLY:.0%} | "
        f"class cap={MAX_ASSET_CLASS_KELLY:.0%}"
    )

    # Step 1: SPY EMA Anchor
    regime, data = _apply_spy_ema_anchor(data, regime)
    allocations = data.get("allocations", allocations)

    # Step 2: Conviction threshold
    allocations = _enforce_conviction_threshold(allocations)

    # Step 3: Volatility-adjusted sizing (82% target)
    allocations = _apply_volatility_adjusted_weight(allocations)

    # Step 4: Asset class concentration cap (35%)
    allocations = _enforce_asset_class_cap(allocations)

    # Step 5: Leveraged satellite fence (20%)
    allocations = _enforce_leveraged_fence(allocations)

    # Step 6: Normalise so non-SGOV total ≤ 1.0
    allocations = normalise_kelly_fractions(allocations)

    # ── Bear Regime Controls (steps 6a & 6b) ─────────────────────────────────
    # Only applied when the Alpaca bot has confirmed a Bear or RISK-OFF regime.
    _BEAR_REGIMES_ALLOC = {"Bear", "RISK-OFF", "Risk-Off", "bear", "risk-off"}
    if regime in _BEAR_REGIMES_ALLOC:
        logger.warning(
            f"Allocator | Bear Regime active ('{regime}') — applying defensive controls"
        )

        # Step 6a: Half-Kelly multiplier — halve all position sizes, sweep excess to SGOV.
        # This is additive on top of the existing vol-adjusted sizing, making the
        # effective sizing ~quarter-Kelly of full Kelly to preserve capital.
        allocations = _apply_bear_half_kelly(allocations)

        # Step 6b: SGOV default sweep — if no safe-haven (GLD/TLT) has positive
        # 3-month momentum, redirect ALL remaining capital to SGOV.
        allocations = _apply_bear_sgov_default(allocations)

        # Re-normalise after bear controls (excess was already redistributed to SGOV)
        allocations = normalise_kelly_fractions(allocations)

    # Step 7: Apply hardcoded per-asset-class SL/TP (overrides LLM placeholder values)
    from analysis.hardcoded_exits import apply_hardcoded_exits
    allocations = apply_hardcoded_exits(allocations)

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
    total_lev_kelly = sum(a.kelly_fraction for a in leveraged)

    logger.info(
        f"Allocator | Regime={output.regime} | "
        f"{len(non_cash)} active position(s) | "
        f"total deployed={total_kelly:.1%} (target={TARGET_UTILIZATION:.0%}) | "
        f"leveraged_risk={total_lev_kelly:.1%} | "
        f"cash slots={sum(1 for a in output.allocations if a.ticker == 'SGOV')}"
    )

    return output


def process_crypto_llm_output(raw_json: str) -> CryptoAnalysisOutput:
    """
    Crypto-only allocation pipeline for off-hours trading.
    No EMA anchor, asset-class cap, or leveraged fence in crypto mode.
    """
    try:
        data: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    allocations: list[dict] = data.get("allocations", [])
    if not allocations:
        raise ValueError("LLM returned no crypto allocation slots")

    logger.info(f"Allocator | Crypto mode | {len(allocations)} slot(s)")

    allocations = _enforce_conviction_threshold(allocations)
    allocations = _apply_volatility_adjusted_weight(allocations)
    allocations = normalise_kelly_fractions(allocations)

    # Apply hardcoded per-asset-class SL/TP (overrides LLM placeholder values)
    from analysis.hardcoded_exits import apply_hardcoded_exits
    allocations = apply_hardcoded_exits(allocations)

    data["allocations"] = allocations

    try:
        output = CryptoAnalysisOutput.model_validate(data)
    except ValidationError as exc:
        logger.error(f"Allocator | Crypto Pydantic validation failed:\n{exc}")
        raise

    non_cash = [a for a in output.allocations if a.ticker != "SGOV"]
    total_kelly = sum(a.kelly_fraction for a in non_cash)
    logger.info(
        f"Allocator | Crypto: {len(non_cash)} active position(s) | "
        f"total deployed={total_kelly:.1%}"
    )

    return output
