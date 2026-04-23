"""
momentum_portfolio.py — Poseidon Momentum Portfolio Manager
Tracks single-asset positions (long or short) for the momentum strategy.
Follows the same atomic-write pattern as the original PaperPortfolio.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

PAPER_FEE_PCT = 0.0026  # Kraken taker fee


class MomentumPortfolio:
    """
    Single-asset paper portfolio for Poseidon momentum strategy.

    State schema (JSON):
    {
      "cash": float,
      "reserved_margin": float,
      "positions": {
        "BTC/USD": {
          "symbol":        str,
          "direction":     "long" | "short",
          "units":         float,
          "position_usd":  float,
          "entry_price":   float,
          "atr":           float,
          "best_price":    float,
          "opened_at":     ISO8601 str,
          "fees_paid":     float
        }
      },
      "total_trades":       int,
      "consecutive_losses": int,
      "updated_at":         ISO8601 str
    }
    """

    def __init__(self, state_file: str, starting_balance: float = 95_175.84):
        self.state_file = Path(state_file)
        self.starting_balance = starting_balance
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if self.state_file.exists():
            try:
                d = json.loads(self.state_file.read_text())
                # If old file is a pairs-trading portfolio, start fresh
                if "positions" in d and d["positions"]:
                    first = next(iter(d["positions"].values()))
                    if isinstance(first, dict) and "pair_set_id" in first:
                        logger.info("MomentumPortfolio | Detected legacy pairs portfolio — resetting to momentum format")
                        self._reset()
                        return
                self.cash               = float(d.get("cash", self.starting_balance))
                self.reserved_margin    = float(d.get("reserved_margin", 0.0))
                self.positions: dict[str, dict] = d.get("positions", {})
                self.total_trades       = int(d.get("total_trades", 0))
                self.consecutive_losses = int(d.get("consecutive_losses", 0))
                return
            except Exception as e:
                logger.warning(f"MomentumPortfolio | Load failed: {e} — resetting")
        self._reset()

    def _reset(self):
        self.cash               = self.starting_balance
        self.reserved_margin    = 0.0
        self.positions          = {}
        self.total_trades       = 0
        self.consecutive_losses = 0
        self._save()

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        d = {
            "cash":               self.cash,
            "reserved_margin":    self.reserved_margin,
            "positions":          self.positions,
            "total_trades":       self.total_trades,
            "consecutive_losses": self.consecutive_losses,
            "updated_at":         datetime.now(timezone.utc).isoformat(),
        }
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        tmp.replace(self.state_file)

    # ── Equity ───────────────────────────────────────────────────────────────

    def equity(self, current_prices: dict[str, float]) -> float:
        """Total equity = cash + margin locked + unrealised P&L."""
        total = self.cash
        for sym, pos in self.positions.items():
            price = current_prices.get(sym, pos["entry_price"])
            pnl   = self._unrealised_pnl(pos, price)
            total += pos["position_usd"] + pnl
        return total

    def _unrealised_pnl(self, pos: dict, current_price: float) -> float:
        if pos["direction"] == "long":
            return (current_price - pos["entry_price"]) * pos["units"] - pos["fees_paid"]
        else:
            return (pos["entry_price"] - current_price) * pos["units"] - pos["fees_paid"]

    # ── Capacity checks ───────────────────────────────────────────────────────

    def can_open(self, max_positions: int, allow_shorts: bool = True, max_shorts: int = 1) -> bool:
        return len(self.positions) < max_positions

    def short_count(self) -> int:
        return sum(1 for p in self.positions.values() if p["direction"] == "short")

    def is_holding(self, symbol: str) -> bool:
        return symbol in self.positions

    # ── Open / Close ─────────────────────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        direction: str,
        units: float,
        position_usd: float,
        entry_price: float,
        atr: float,
    ) -> bool:
        """Open a single-asset position. Returns False if insufficient funds."""
        cost = position_usd
        if cost > self.cash:
            logger.warning(
                f"MomentumPortfolio | Insufficient cash for {symbol}: "
                f"need ${cost:.0f}, have ${self.cash:.0f}"
            )
            return False

        fees_paid = units * entry_price * PAPER_FEE_PCT
        self.cash            -= cost
        self.reserved_margin += cost
        self.positions[symbol] = {
            "symbol":       symbol,
            "direction":    direction,
            "units":        units,
            "position_usd": position_usd,
            "entry_price":  entry_price,
            "atr":          atr,
            "best_price":   entry_price,
            "opened_at":    datetime.now(timezone.utc).isoformat(),
            "fees_paid":    round(fees_paid, 4),
        }
        self._save()
        logger.info(
            f"MomentumPortfolio | Opened {direction.upper()} {symbol} "
            f"@ ${entry_price:.4f} units={units:.6f} size=${position_usd:.0f} ATR={atr:.4f}"
        )
        return True

    def update_best_price(self, symbol: str, current_price: float) -> None:
        """Update the high-water mark for trailing stop tracking."""
        pos = self.positions.get(symbol)
        if not pos:
            return
        if pos["direction"] == "long":
            pos["best_price"] = max(pos["best_price"], current_price)
        else:
            pos["best_price"] = min(pos["best_price"], current_price)

    def close_position(self, symbol: str, current_price: float, reason: str) -> Optional[dict]:
        """Close a position. Returns trade summary dict or None."""
        pos = self.positions.get(symbol)
        if not pos:
            return None

        exit_fees = pos["units"] * current_price * PAPER_FEE_PCT
        raw_pnl   = self._unrealised_pnl(pos, current_price)
        net_pnl   = raw_pnl - exit_fees

        self.cash            += pos["position_usd"] + net_pnl
        self.reserved_margin  = max(0.0, self.reserved_margin - pos["position_usd"])

        if net_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self.total_trades += 1
        del self.positions[symbol]
        self._save()

        opened = datetime.fromisoformat(pos["opened_at"].replace("Z", "+00:00"))
        holding_hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600

        logger.info(
            f"MomentumPortfolio | Closed {pos['direction'].upper()} {symbol} "
            f"@ ${current_price:.4f} P&L=${net_pnl:+.2f} "
            f"held={holding_hours:.1f}h reason={reason}"
        )
        return {
            "symbol":        symbol,
            "direction":     pos["direction"],
            "entry_price":   pos["entry_price"],
            "exit_price":    current_price,
            "units":         pos["units"],
            "position_usd":  pos["position_usd"],
            "net_pnl":       round(net_pnl, 4),
            "holding_hours": round(holding_hours, 2),
            "reason":        reason,
            "atr":           pos["atr"],
        }

    def holding_hours(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        opened = datetime.fromisoformat(pos["opened_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - opened).total_seconds() / 3600
