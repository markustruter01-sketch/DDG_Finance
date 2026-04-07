"""
analysis/claude_budget.py  —  Claude Token Usage Tracker
=========================================================
Claude is a paid-tier API.  This module provides:

  • Token consumption tracking (for dashboards / monitoring).
  • No hard budget gates — all can_call_*() / budget_exhausted() methods
    are paid-tier no-ops that always allow calls.
  • Full API-surface compatibility with the retired GroqBudget so that
    existing call-sites continue to work unchanged during Task #67 migration.

Public API (drop-in GroqBudget replacement)
-------------------------------------------
    consume(tokens, call_type)        → None
    can_call_regime()                 → True (no-op)
    record_regime_call()              → None (no-op)
    can_call_crypto()                 → True (no-op)
    record_crypto_call()              → None (no-op)
    can_call_commentary(ep, force)    → True (no-op)
    record_commentary_call(ep)        → None (no-op)
    budget_exhausted()                → False (no-op)
    next_regime_eligible_at_iso()     → None (no-op)
    token_usage_breakdown()           → dict
    budget_status()                   → dict
    get_usage()                       → dict  (NEW — monitoring helper)
    reset()                           → None  (NEW — testing helper)
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from loguru import logger

from config.settings import settings


class ClaudeBudget:
    """
    Token usage tracker for Claude (paid tier).

    All gating methods (can_call_*, budget_exhausted) are strict no-ops
    that always allow calls.  Token counts are tracked for monitoring only.
    """

    def __init__(self) -> None:
        self._lock          = Lock()
        self._reset_day: int = self._today_utc()
        self._tokens_used: int = 0
        self._regime_calls: int = 0
        self._crypto_calls: int = 0
        self._commentary_calls: dict[str, int] = {}
        self._tokens_by_type: dict[str, int] = {}

    @staticmethod
    def _today_utc() -> int:
        return int(datetime.now(timezone.utc).strftime("%Y%m%d"))

    def _maybe_reset(self) -> None:
        today = self._today_utc()
        if today != self._reset_day:
            old_day = self._reset_day
            self._reset_day      = today
            self._tokens_used    = 0
            self._regime_calls   = 0
            self._crypto_calls   = 0
            self._commentary_calls = {}
            self._tokens_by_type   = {}
            logger.info(
                f"Claude budget | Daily counters reset ({old_day} → {today})"
            )

    # ── Token tracking ─────────────────────────────────────────────────────────

    def consume(self, tokens: int, call_type: str = "unknown") -> None:
        with self._lock:
            self._maybe_reset()
            self._tokens_used += tokens
            self._tokens_by_type[call_type] = (
                self._tokens_by_type.get(call_type, 0) + tokens
            )
            logger.debug(
                f"Claude budget | +{tokens} tokens [{call_type}] "
                f"— running_total={self._tokens_used}"
            )

    # ── Paid-tier no-ops — always allow calls ──────────────────────────────────

    def can_call_regime(self) -> bool:
        """No-op on paid tier — always True."""
        return True

    def record_regime_call(self) -> None:
        """No-op on paid tier."""
        with self._lock:
            self._maybe_reset()
            self._regime_calls += 1

    def can_call_crypto(self) -> bool:
        """No-op on paid tier — always True."""
        return True

    def record_crypto_call(self) -> None:
        """No-op on paid tier."""
        with self._lock:
            self._maybe_reset()
            self._crypto_calls += 1

    def can_call_commentary(self, endpoint: str, force: bool = False) -> bool:
        """No-op on paid tier — always True."""
        return True

    def record_commentary_call(self, endpoint: str) -> None:
        """No-op on paid tier — records count for monitoring only."""
        with self._lock:
            self._maybe_reset()
            self._commentary_calls[endpoint] = (
                self._commentary_calls.get(endpoint, 0) + 1
            )

    def budget_exhausted(self) -> bool:
        """Always False — Claude is a paid tier with no hard daily token cap."""
        return False

    def next_regime_eligible_at_iso(self) -> str | None:
        """Always None — no interval throttle on paid tier."""
        return None

    # ── Status / reporting ─────────────────────────────────────────────────────

    def token_usage_breakdown(self) -> dict:
        """Return per-call-type token breakdown for the admin token-usage endpoint."""
        with self._lock:
            self._maybe_reset()
            breakdown = dict(self._tokens_by_type)
            commentary_total = breakdown.pop("commentary", 0)
            for ep_key in [k for k in list(breakdown) if k.startswith("commentary/")]:
                commentary_total += breakdown.pop(ep_key)
            return {
                "tokens_used_today":  self._tokens_used,
                "tokens_remaining":   None,
                "token_budget_total": None,
                "pct_used":           None,
                "by_call_type": {
                    "regime":      breakdown.get("regime", 0),
                    "crypto":      breakdown.get("crypto", 0),
                    "commentary":  commentary_total,
                    "audit":       breakdown.get("audit", 0),
                    "performance": breakdown.get("performance", 0),
                    "unknown":     breakdown.get("unknown", 0),
                    **{k: v for k, v in breakdown.items()
                       if k not in ("regime", "crypto", "audit", "performance", "unknown")},
                },
                "regime_calls_today": self._regime_calls,
                "crypto_calls_today": self._crypto_calls,
            }

    def budget_status(self) -> dict:
        """Return a dict suitable for the /status claude block."""
        with self._lock:
            self._maybe_reset()
            by_type = dict(self._tokens_by_type)
            return {
                "tokens_used_today":       self._tokens_used,
                "tokens_remaining":        None,
                "token_budget_total":      None,
                "pct_used":                None,
                "regime_calls_today":      self._regime_calls,
                "crypto_calls_today":      self._crypto_calls,
                "analysis_calls_today":    self._regime_calls + self._crypto_calls,
                "commentary_calls_today":  dict(self._commentary_calls),
                "tokens_by_call_type": {
                    "regime":      by_type.get("regime", 0),
                    "crypto":      by_type.get("crypto", 0),
                    "commentary":  by_type.get("commentary", 0),
                    "audit":       by_type.get("audit", 0),
                    "performance": by_type.get("performance", 0),
                    "unknown":     by_type.get("unknown", 0),
                },
                "regime_interval_min":     0,
                "commentary_daily_cap":    None,
                "next_regime_eligible_at": None,
                "regime_call_eligible":    True,
                "provider":                "claude",
                "budget_exhausted":        False,
            }

    def get_usage(self) -> dict:
        """
        Monitoring helper — returns a lightweight snapshot of today's usage.
        Suitable for health-check endpoints and log-line reporting.
        """
        with self._lock:
            self._maybe_reset()
            return {
                "date":             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "tokens_used":      self._tokens_used,
                "regime_calls":     self._regime_calls,
                "crypto_calls":     self._crypto_calls,
                "commentary_calls": dict(self._commentary_calls),
                "by_type":          dict(self._tokens_by_type),
                "provider":         "claude",
            }

    def reset(self) -> None:
        """
        Hard-reset all counters.  Intended for testing and admin tooling only.
        """
        with self._lock:
            self._reset_day        = self._today_utc()
            self._tokens_used      = 0
            self._regime_calls     = 0
            self._crypto_calls     = 0
            self._commentary_calls = {}
            self._tokens_by_type   = {}
            logger.info("Claude budget | Counters manually reset via reset()")


budget = ClaudeBudget()
