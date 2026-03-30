"""
shared  —  Common risk infrastructure for Davy Jones' Portfolio (Kraken)
          and the AI Quantitative Trading Platform (Alpaca).

Exports:
  RiskProfile    — Portfolio-level risk envelope (ring-fence, reserve, caps)
  ExitBracket    — Stop-loss / take-profit / trail-activation level calculator
  CircuitBreaker — Flash-crash detector (price-drop within a rolling window)

Both bots import this package by inserting the repo root on sys.path:

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from shared import RiskProfile, ExitBracket, CircuitBreaker
"""

from shared.risk_profile import RiskProfile
from shared.exit_bracket import ExitBracket
from shared.circuit_breaker import CircuitBreaker

__all__ = ["RiskProfile", "ExitBracket", "CircuitBreaker"]
