"""
paper_portfolio.py — Poseidon Paper Portfolio Manager
Tracks pair positions (two-legged: long one asset, short another simultaneously)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

PAPER_FEE_PCT = 0.0026


# Audit fix H2: canonical unrealised-P&L helper.
# Keep in sync with trading-platform/core/pnl_math.py — every paper engine
# (kraken-bot, forex-engine, poseidon, kraken-current) uses the same formula
# so short-side sign conventions never diverge again.
def _compute_unrealized_pnl(side: str, entry: float, current: float,
                            units: float, fees: float = 0.0) -> float:
    s = (side or "").lower()
    e, c, u, f = float(entry), float(current), float(units), float(fees)
    if s == "long":
        gross = (c - e) * u
    elif s == "short":
        gross = (e - c) * u
    else:
        raise ValueError(f"_compute_unrealized_pnl: unknown side {side!r}")
    return gross - f


class PairPosition:
    """Represents a single open pair position (two legs)."""
    def __init__(
        self,
        pair_set_id: int,
        asset_a: str,
        asset_b: str,
        direction: str,  # 'long_a_short_b' or 'short_a_long_b'
        leg_a_side: str,  # 'long' or 'short'
        leg_b_side: str,
        leg_a_units: float,
        leg_b_units: float,
        leg_a_entry: float,
        leg_b_entry: float,
        position_value: float,
        entry_zscore: float,
        hedge_ratio: float,
    ):
        self.pair_set_id = pair_set_id
        self.asset_a = asset_a
        self.asset_b = asset_b
        self.direction = direction
        self.leg_a_side = leg_a_side
        self.leg_b_side = leg_b_side
        self.leg_a_units = leg_a_units
        self.leg_b_units = leg_b_units
        self.leg_a_entry = leg_a_entry
        self.leg_b_entry = leg_b_entry
        self.position_value = position_value
        self.entry_zscore = entry_zscore
        self.entry_hedge_ratio = hedge_ratio
        self.opened_at = datetime.now(timezone.utc).isoformat()
        self.fees_paid = (
            leg_a_units * leg_a_entry * PAPER_FEE_PCT
            + leg_b_units * leg_b_entry * PAPER_FEE_PCT
        )

    def current_pnl(self, price_a: float, price_b: float) -> dict:
        """Compute unrealised P&L for both legs.

        Audit fix H2: routes through the canonical compute_unrealized_pnl
        helper (mirror of trading-platform/core/pnl_math.py) so the long/short
        sign convention is identical across every engine.
        """
        leg_a_pnl = _compute_unrealized_pnl(
            self.leg_a_side, self.leg_a_entry, price_a, self.leg_a_units
        )
        leg_b_pnl = _compute_unrealized_pnl(
            self.leg_b_side, self.leg_b_entry, price_b, self.leg_b_units
        )
        total_pnl = leg_a_pnl + leg_b_pnl - self.fees_paid
        return {
            "leg_a_pnl": leg_a_pnl,
            "leg_b_pnl": leg_b_pnl,
            "total_pnl": total_pnl,
            "leg_a_current": price_a,
            "leg_b_current": price_b,
        }

    def holding_hours(self) -> float:
        opened = datetime.fromisoformat(self.opened_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - opened
        return delta.total_seconds() / 3600

    def to_dict(self) -> dict:
        return {
            "pair_set_id": self.pair_set_id,
            "asset_a": self.asset_a,
            "asset_b": self.asset_b,
            "direction": self.direction,
            "leg_a_side": self.leg_a_side,
            "leg_b_side": self.leg_b_side,
            "leg_a_units": self.leg_a_units,
            "leg_b_units": self.leg_b_units,
            "leg_a_entry": self.leg_a_entry,
            "leg_b_entry": self.leg_b_entry,
            "position_value": self.position_value,
            "entry_zscore": self.entry_zscore,
            "entry_hedge_ratio": self.entry_hedge_ratio,
            "opened_at": self.opened_at,
            "fees_paid": self.fees_paid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PairPosition":
        pos = cls.__new__(cls)
        for k, v in d.items():
            setattr(pos, k, v)
        return pos


class PaperPortfolio:
    """Simulated paper portfolio for Poseidon pairs trading."""

    def __init__(self, state_file: str, starting_balance: float = 100_000.0):
        self.state_file = Path(state_file)
        self.starting_balance = starting_balance
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                d = json.loads(self.state_file.read_text())
                self.cash = float(d.get("cash", self.starting_balance))
                self.reserved_margin = float(d.get("reserved_margin", 0.0))
                self.positions: dict[int, PairPosition] = {}
                for k, v in d.get("positions", {}).items():
                    self.positions[int(k)] = PairPosition.from_dict(v)
                self.total_trades = int(d.get("total_trades", 0))
                self.consecutive_losses = int(d.get("consecutive_losses", 0))
                return
            except Exception as e:
                logger.warning(f"Poseidon | Portfolio load failed: {e}")
        self.cash = self.starting_balance
        self.reserved_margin = 0.0
        self.positions = {}
        self.total_trades = 0
        self.consecutive_losses = 0
        self._save()

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        d = {
            "cash": self.cash,
            "reserved_margin": self.reserved_margin,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "total_trades": self.total_trades,
            "consecutive_losses": self.consecutive_losses,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Atomic write: write to .tmp then rename so a mid-write crash never
        # produces a corrupt state file that would wipe the portfolio on restart.
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        tmp.replace(self.state_file)

    def equity(self, current_prices: dict[str, float]) -> float:
        """Total equity = cash + unrealised P&L of all positions."""
        total = self.cash
        for pos in self.positions.values():
            pa = current_prices.get(pos.asset_a, pos.leg_a_entry)
            pb = current_prices.get(pos.asset_b, pos.leg_b_entry)
            pnl = pos.current_pnl(pa, pb)
            total += pnl["total_pnl"] + pos.position_value  # value locked in position
        return total

    def can_open(self, max_positions: int) -> bool:
        return len(self.positions) < max_positions

    def open_position(self, pos: PairPosition) -> bool:
        """Open a pair position. Returns False if insufficient funds."""
        # In pairs trading one leg's proceeds fund the other, so the cash
        # requirement is one leg's value (position_value).  The previous check
        # of position_value * 2 was inconsistent with the actual deduction of
        # position_value * 1 and allowed capital over-deployment.
        cost = pos.position_value
        if cost > self.cash:
            logger.warning(f"Poseidon | Insufficient cash for pair {pos.pair_set_id}: need ${cost:.0f}, have ${self.cash:.0f}")
            return False
        self.cash -= pos.position_value  # reserve one leg value as margin
        self.reserved_margin += pos.position_value
        self.positions[pos.pair_set_id] = pos
        self._save()
        logger.info(f"Poseidon | Opened pair {pos.pair_set_id} ({pos.asset_a}/{pos.asset_b}) {pos.direction} Z={pos.entry_zscore:.2f}")
        return True

    def close_position(self, pair_set_id: int, price_a: float, price_b: float, reason: str) -> Optional[dict]:
        """Close a pair position. Returns closed trade details."""
        pos = self.positions.get(pair_set_id)
        if not pos:
            return None

        pnl_data = pos.current_pnl(price_a, price_b)
        exit_fees = (
            pos.leg_a_units * price_a * PAPER_FEE_PCT
            + pos.leg_b_units * price_b * PAPER_FEE_PCT
        )
        net_pnl = pnl_data["total_pnl"] - exit_fees

        # Return cash + P&L
        self.cash += pos.position_value + net_pnl
        self.reserved_margin = max(0, self.reserved_margin - pos.position_value)

        if net_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self.total_trades += 1
        del self.positions[pair_set_id]
        self._save()

        holding_h = pos.holding_hours()
        logger.info(
            f"Poseidon | Closed pair {pair_set_id} ({reason}) "
            f"P&L=${net_pnl:+.2f} held={holding_h:.1f}h"
        )
        return {
            "pair_set_id": pair_set_id,
            "asset_a": pos.asset_a,
            "asset_b": pos.asset_b,
            "direction": pos.direction,
            "leg_a_entry": pos.leg_a_entry,
            "leg_b_entry": pos.leg_b_entry,
            "leg_a_exit": price_a,
            "leg_b_exit": price_b,
            "leg_a_pnl": pnl_data["leg_a_pnl"],
            "leg_b_pnl": pnl_data["leg_b_pnl"],
            "net_pnl": net_pnl,
            "entry_zscore": pos.entry_zscore,
            "holding_hours": holding_h,
            "reason": reason,
        }
