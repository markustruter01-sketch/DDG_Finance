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
  bear_hedge      SL = -8%   TP = +20%  (same risk profile as leveraged)
  cash (SGOV)     SL = -1%   TP = +1%   (nominal — never triggered in practice)

5-Day Time Exit (v4.4)
-----------------------
  3× inverse ETFs (SPXS, SQQQ, SRTY) decay rapidly due to daily rebalancing.
  check_time_exits() is called from the pipeline each cycle and force-exits
  any 3× inverse ETF position held for >= 5 trading days.
"""

import math
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger

# 3× inverse ETFs subject to 5-trading-day max hold
_BEAR_HEDGE_3X: frozenset[str] = frozenset({"SPXS", "SQQQ", "SRTY"})
_MAX_HOLD_TRADING_DAYS: int = 5


_SL_TP_BY_CLASS: dict[str, tuple[float, float]] = {
    "equity":          (-0.06,  0.15),
    "safe_haven":      (-0.05,  0.10),
    "commodity":       (-0.08,  0.18),
    "crypto_spot":     (-0.10,  0.25),
    "leveraged_risk":  (-0.08,  0.20),
    "bear_hedge":      (-0.08,  0.20),   # inverse ETFs: same risk profile as leveraged
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


def _count_trading_days_held(entry_time: Any) -> int:
    """
    Estimate the number of trading days a position has been held.
    entry_time can be a datetime object, ISO string, or None.
    Returns 0 if we cannot determine entry time.
    """
    if entry_time is None:
        return 0
    try:
        if isinstance(entry_time, str):
            if "T" in entry_time or " " in entry_time:
                entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
            else:
                entry_dt = datetime.fromisoformat(entry_time)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        elif isinstance(entry_time, datetime):
            entry_dt = entry_time
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        else:
            return 0

        now = datetime.now(timezone.utc)
        calendar_days = (now - entry_dt).days
        # Approximate: 5 trading days ≈ 7 calendar days (excludes weekends)
        trading_days = math.floor(calendar_days * 5.0 / 7.0)
        return max(0, trading_days)
    except Exception:
        return 0


def check_time_exits(
    positions: list[dict],
    dry_run: bool = False,
) -> list[str]:
    """
    Force-exit 3× inverse ETF positions (SPXS, SQQQ, SRTY) held for >= 5 trading days.

    Parameters
    ----------
    positions : list[dict]
        From broker.get_positions() — each dict has ``symbol``, ``qty``, and
        optionally ``entry_time`` (ISO string or datetime).
    dry_run : bool
        If True, log but do not actually close positions.

    Returns
    -------
    list[str]
        Symbols that were force-exited (or would be, in dry_run).
    """
    exited: list[str] = []

    for pos in positions:
        symbol = str(pos.get("symbol", "")).upper()
        if symbol not in _BEAR_HEDGE_3X:
            continue

        entry_time = pos.get("entry_time") or pos.get("created_at") or pos.get("filled_at")
        days_held = _count_trading_days_held(entry_time)

        if days_held < _MAX_HOLD_TRADING_DAYS:
            logger.debug(
                f"TimeExit | {symbol} held ~{days_held}d — below {_MAX_HOLD_TRADING_DAYS}d limit"
            )
            continue

        logger.warning(
            f"TimeExit | {symbol} held ~{days_held} trading days ≥ {_MAX_HOLD_TRADING_DAYS} "
            f"— triggering mandatory time-exit for 3× inverse ETF"
        )

        if dry_run:
            logger.info(f"TimeExit | DRY RUN — would force-close {symbol}")
            exited.append(symbol)
            continue

        try:
            from execution.broker import close_position
            close_position(symbol)
            logger.warning(f"TimeExit | {symbol} force-closed (5-day 3× inverse ETF rule)")
            exited.append(symbol)
            # Clear entry timestamp so a future re-open gets a fresh timestamp
            # and is NOT prematurely force-exited on the next cycle.
            try:
                from db.postgres import delete_position_entry
                delete_position_entry(symbol)
            except Exception:
                pass  # Non-fatal
        except Exception as exc:
            logger.error(f"TimeExit | Failed to close {symbol}: {exc}")

    return exited
