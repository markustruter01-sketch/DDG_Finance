"""
paper_portfolio.py — Kraken Current Paper Portfolio Manager
Tracks individual trend-following positions with ATR trailing stops
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

PAPER_FEE_PCT = 0.0026


class TrendPosition:
    """A single open trend position."""
    def __init__(
        self,
        symbol: str,
        direction: str,  # 'long' or 'short'
        units: float,
        entry_price: float,
        stop_distance: float,
        position_value: float,
        ema_fast: float,
        ema_slow: float,
        adx: float,
        trail_immediate: bool = False,
    ):
        self.symbol = symbol
        self.direction = direction
        self.units = units
        self.entry_price = entry_price
        self.stop_distance = stop_distance
        self.position_value = position_value
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.adx = adx
        self.best_price = entry_price
        self.stop_level = (
            (entry_price - stop_distance) if direction == "long"
            else (entry_price + stop_distance)
        )
        self.trail_immediate = trail_immediate
        self.trailing_active = trail_immediate
        self.opened_at = datetime.now(timezone.utc).isoformat()
        self.fees_paid = units * entry_price * PAPER_FEE_PCT

    def update_stop(self, current_price: float, atr: float, trail_trigger_mult: float = 1.5):
        if self.direction == "long":
            self.best_price = max(self.best_price, current_price)
            profit_dist = self.best_price - self.entry_price
            if self.trail_immediate or (atr > 0 and profit_dist >= atr * trail_trigger_mult):
                self.trailing_active = True
            if self.trailing_active:
                self.stop_level = max(self.stop_level, self.best_price - self.stop_distance)
        else:
            self.best_price = min(self.best_price, current_price)
            profit_dist = self.entry_price - self.best_price
            if self.trail_immediate or (atr > 0 and profit_dist >= atr * trail_trigger_mult):
                self.trailing_active = True
            if self.trailing_active:
                self.stop_level = min(self.stop_level, self.best_price + self.stop_distance)

    def is_stop_hit(self, current_price: float) -> bool:
        if self.direction == "long":
            return current_price <= self.stop_level
        else:
            return current_price >= self.stop_level

    def unrealised_pnl(self, current_price: float) -> float:
        if self.direction == "long":
            return (current_price - self.entry_price) * self.units - self.fees_paid
        else:
            return (self.entry_price - current_price) * self.units - self.fees_paid

    def holding_days(self) -> float:
        opened = datetime.fromisoformat(self.opened_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - opened
        return delta.total_seconds() / 86400

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "units": self.units,
            "entry_price": self.entry_price,
            "stop_distance": self.stop_distance,
            "position_value": self.position_value,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "adx": self.adx,
            "best_price": self.best_price,
            "stop_level": self.stop_level,
            "trail_immediate": self.trail_immediate,
            "trailing_active": self.trailing_active,
            "opened_at": self.opened_at,
            "fees_paid": self.fees_paid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrendPosition":
        pos = cls.__new__(cls)
        for k, v in d.items():
            setattr(pos, k, v)
        return pos


class PaperPortfolio:
    """Simulated paper portfolio for Kraken Current trend following."""

    def __init__(self, state_file: str, starting_balance: float = 100_000.0):
        self.state_file = Path(state_file)
        self.starting_balance = starting_balance
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                d = json.loads(self.state_file.read_text())
                self.cash = float(d.get("cash", self.starting_balance))
                self.positions: dict[str, TrendPosition] = {}
                for sym, v in d.get("positions", {}).items():
                    self.positions[sym] = TrendPosition.from_dict(v)
                self.total_trades = int(d.get("total_trades", 0))
                self.equity_7d_low = float(d.get("equity_7d_low", self.starting_balance))
                self.circuit_breaker_until = d.get("circuit_breaker_until")
                return
            except Exception as e:
                logger.warning(f"KrakenCurrent | Portfolio load failed: {e}")
        self.cash = self.starting_balance
        self.positions = {}
        self.total_trades = 0
        self.equity_7d_low = self.starting_balance
        self.circuit_breaker_until = None
        self._save()

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        d = {
            "cash": self.cash,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "total_trades": self.total_trades,
            "equity_7d_low": self.equity_7d_low,
            "circuit_breaker_until": self.circuit_breaker_until,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Atomic write: write to .tmp then rename so a mid-write crash never
        # produces a corrupt state file that would wipe the portfolio on restart.
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        tmp.replace(self.state_file)

    def equity(self, current_prices: dict[str, float]) -> float:
        total = self.cash
        for sym, pos in self.positions.items():
            price = current_prices.get(sym, pos.entry_price)
            pnl = pos.unrealised_pnl(price)
            total += pos.position_value + pnl
        return total

    def can_open(self, symbol: str, max_positions: int) -> bool:
        return symbol not in self.positions and len(self.positions) < max_positions

    def is_circuit_breaker_active(self) -> bool:
        if not self.circuit_breaker_until:
            return False
        cb_until = datetime.fromisoformat(self.circuit_breaker_until.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < cb_until

    def check_circuit_breaker(self, current_equity: float, cb_drawdown_pct: float = 0.08, starting: float = 100_000.0):
        drawdown = (starting - current_equity) / starting
        if drawdown >= cb_drawdown_pct:
            from datetime import timedelta
            cb_until = datetime.now(timezone.utc) + timedelta(hours=48)
            self.circuit_breaker_until = cb_until.isoformat()
            logger.warning(f"KrakenCurrent | Circuit breaker: {drawdown:.1%} drawdown. Paused until {cb_until.isoformat()}")
            self._save()

    def open_position(self, pos: TrendPosition) -> bool:
        if pos.position_value > self.cash:
            logger.warning(f"KrakenCurrent | Insufficient cash for {pos.symbol}: need ${pos.position_value:.0f}, have ${self.cash:.0f}")
            return False
        self.cash -= pos.position_value
        self.positions[pos.symbol] = pos
        self._save()
        logger.info(f"KrakenCurrent | Opened {pos.direction} {pos.symbol} @ ${pos.entry_price:.4f} size=${pos.position_value:.0f} ADX={pos.adx:.1f}")
        return True

    def close_position(self, symbol: str, exit_price: float, reason: str) -> Optional[dict]:
        pos = self.positions.get(symbol)
        if not pos:
            return None
        exit_fees = pos.units * exit_price * PAPER_FEE_PCT
        pnl = pos.unrealised_pnl(exit_price) - exit_fees
        self.cash += pos.position_value + pnl
        self.total_trades += 1
        del self.positions[symbol]
        self._save()
        logger.info(f"KrakenCurrent | Closed {pos.direction} {symbol} @ ${exit_price:.4f} P&L=${pnl:+.2f} ({reason})")
        return {
            "symbol": symbol,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "units": pos.units,
            "pnl": pnl,
            "holding_days": pos.holding_days(),
            "reason": reason,
        }
