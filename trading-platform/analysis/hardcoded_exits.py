"""
Hardcoded Exit Parameters
--------------------------
Provides per-asset-class stop-loss and take-profit defaults that are applied
AFTER the LLM output is parsed but BEFORE final Pydantic validation.

Motivation: The LLM wastes reasoning tokens producing SL/TP values that vary
little from these calibrated defaults. By fixing them in Python we:
  - Remove ~50 output tokens per allocation slot from the LLM's burden
  - Ensure consistent, back-tested risk parameters across all cycles
  - Eliminate validation retries caused by out-of-range SL/TP values

Asset-class defaults (midpoint of back-tested ranges):
  equity          SL = -6%   TP = +15%
  safe_haven      SL = -5%   TP = +10%
  commodity       SL = -8%   TP = +18%
  crypto_spot     SL = -10%  TP = +25%
  leveraged_risk  SL = -8%   TP = +20%
  cash (SGOV)     SL = -1%   TP = +1%   (nominal — never triggered in practice)
"""

from loguru import logger


_SL_TP_BY_CLASS: dict[str, tuple[float, float]] = {
    "equity":          (-0.06,  0.15),
    "safe_haven":      (-0.05,  0.10),
    "commodity":       (-0.08,  0.18),
    "crypto_spot":     (-0.10,  0.25),
    "leveraged_risk":  (-0.08,  0.20),
    "cash":            (-0.01,  0.01),
}

_DEFAULT_SL_TP: tuple[float, float] = (-0.07, 0.15)


def apply_hardcoded_exits(allocations: list[dict]) -> list[dict]:
    """
    Overwrite stop_loss_pct and take_profit_pct in each allocation dict
    using the hardcoded per-asset-class table.

    Call this on the raw list[dict] BEFORE Pydantic validation so the
    schema validators always see valid, in-range values.

    Args:
        allocations: List of allocation dicts (as parsed from LLM JSON).

    Returns:
        Same list with stop_loss_pct / take_profit_pct overwritten in-place.
    """
    overridden = 0
    for slot in allocations:
        asset_class = slot.get("asset_class", "")
        sl, tp = _SL_TP_BY_CLASS.get(asset_class, _DEFAULT_SL_TP)

        old_sl = slot.get("stop_loss_pct")
        old_tp = slot.get("take_profit_pct")

        slot["stop_loss_pct"]    = sl
        slot["take_profit_pct"]  = tp

        if old_sl != sl or old_tp != tp:
            overridden += 1
            logger.debug(
                f"HardcodedExits | {slot.get('ticker', '?')} ({asset_class}): "
                f"SL {old_sl} → {sl}  TP {old_tp} → {tp}"
            )

    if overridden:
        logger.info(
            f"HardcodedExits | Applied per-class SL/TP to {overridden}/{len(allocations)} slot(s)"
        )
    return allocations


def get_exit_params(asset_class: str) -> tuple[float, float]:
    """Return (stop_loss_pct, take_profit_pct) for a given asset class."""
    return _SL_TP_BY_CLASS.get(asset_class, _DEFAULT_SL_TP)
