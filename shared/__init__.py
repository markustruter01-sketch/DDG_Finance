"""
shared  —  Common risk infrastructure for Davy Jones' Portfolio (Kraken)
          and the AI Quantitative Trading Platform (Alpaca).

Exports:
  RiskProfile           — Portfolio-level risk envelope (ring-fence, reserve, caps)
  ExitBracket           — Stop-loss / take-profit / trail-activation level calculator
  CircuitBreaker        — Flash-crash detector (price-drop within a rolling window)
  validate_snapshot     — Market data integrity gate (Data Circuit Breaker)
  ValidationResult      — Return type of validate_snapshot()

Both bots import this package by inserting the repo root on sys.path:

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from shared import RiskProfile, ExitBracket, CircuitBreaker
    from shared.market_snapshot_validator import validate_snapshot
"""

from shared.risk_profile import RiskProfile
from shared.exit_bracket import ExitBracket
from shared.circuit_breaker import CircuitBreaker
from shared.market_snapshot_validator import validate_snapshot, ValidationResult

__all__ = [
    "RiskProfile",
    "ExitBracket",
    "CircuitBreaker",
    "validate_snapshot",
    "ValidationResult",
]
