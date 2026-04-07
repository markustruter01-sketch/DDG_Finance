"""
analysis/claude_budget.py  —  Claude Token Usage Tracker & Soft Throttle
=========================================================================
Claude is a paid-tier API — there is no hard daily token budget gate.

This module provides:
  1. Token consumption tracking (for monitoring/dashboards).
  2. Interval throttle on regime/crypto calls (pacing, not blocking).
  3. A daily cap on auto-triggered commentary calls per endpoint.
  4. NO hard budget exhaustion gate — budget_exhausted() always returns False.

All counters reset at midnight UTC.  Interval and cap settings are read
from settings.claude_regime_interval_minutes and claude_commentary_daily_cap
(with legacy groq_* aliases as fallback).

Usage:
    from analysis.claude_budget import budget

    budget.consume(tokens, call_type="regime")
    budget.can_call_regime()              # True unless interval not elapsed
    budget.record_regime_call()
    budget.can_call_crypto()              # shares regime timer
    budget.record_crypto_call()
    budget.can_call_commentary(ep, force) # True unless daily cap hit
    budget.record_commentary_call(ep)
    budget.budget_exhausted()             # always False (paid tier)
    budget.budget_status()                # dict for /status claude block
    budget.token_usage_breakdown()        # per-type breakdown
"""

import time
from datetime import datetime, timedelta, timezone
from threading import Lock

from loguru import logger

from config.settings import settings


def _regime_interval_minutes() -> int:
    """Prefer claude_regime_interval_minutes; fall back to groq legacy alias."""
    return settings.claude_regime_interval_minutes


def _commentary_daily_cap() -> int:
    """Prefer claude_commentary_daily_cap; fall back to groq legacy alias."""
    return settings.claude_commentary_daily_cap


class ClaudeBudget:
    """
    Token usage tracker with soft interval/cap throttles.

    Key design decisions vs. GroqBudget
    ------------------------------------
    • No hard budget gate — Claude is paid tier.  budget_exhausted() → False.
    • can_call_regime/crypto only enforce the minimum interval (pacing).
    • can_call_commentary enforces the per-endpoint daily call cap only.
    • All token consumption is still tracked for reporting.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._reset_day: int = self._today_utc()
        self._tokens_used: int = 0
        self._regime_calls: int = 0
        self._crypto_calls: int = 0
        self._last_regime_call_at: float = 0.0
        self._commentary_calls: dict[str, int] = {}
        self._tokens_by_type: dict[str, int] = {}
        self._budget_warned: set[str] = set()

    @staticmethod
    def _today_utc() -> int:
        return int(datetime.now(timezone.utc).strftime("%Y%m%d"))

    def _maybe_reset(self) -> None:
        today = self._today_utc()
        if today != self._reset_day:
            old_day = self._reset_day
            self._reset_day = today
            self._tokens_used = 0
            self._regime_calls = 0
            self._crypto_calls = 0
            self._commentary_calls = {}
            self._tokens_by_type = {}
            self._last_regime_call_at = 0.0
            self._budget_warned = set()
            logger.info(
                f"Claude budget | Daily counters reset ({old_day} → {today})"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Token tracking (monitoring only — not a gate)
    # ──────────────────────────────────────────────────────────────────────────

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

    # ──────────────────────────────────────────────────────────────────────────
    # Regime / crypto interval throttle
    # ──────────────────────────────────────────────────────────────────────────

    def can_call_regime(self) -> bool:
        """
        True unless the minimum interval since the last regime call has not
        elapsed yet.  No hard budget gate (paid tier).
        """
        with self._lock:
            self._maybe_reset()
            min_interval_min = _regime_interval_minutes()
            if min_interval_min <= 0 or self._last_regime_call_at == 0.0:
                return True
            interval_s = min_interval_min * 60
            elapsed    = time.time() - self._last_regime_call_at
            if elapsed < interval_s:
                wait_min = (interval_s - elapsed) / 60
                logger.info(
                    f"Claude budget | Regime call throttled — "
                    f"{elapsed / 60:.1f}min since last call, "
                    f"min={min_interval_min}min — eligible in {wait_min:.1f}min"
                )
                return False
            return True

    def record_regime_call(self) -> None:
        with self._lock:
            self._maybe_reset()
            self._last_regime_call_at = time.time()
            self._regime_calls += 1
            logger.info(
                f"Claude budget | Regime call #{self._regime_calls} recorded "
                f"(total_tokens={self._tokens_used})"
            )

    def can_call_crypto(self) -> bool:
        """
        Shares the same interval timer as can_call_regime().
        True unless the minimum interval has not elapsed.
        """
        with self._lock:
            self._maybe_reset()
            min_interval_min = _regime_interval_minutes()
            if min_interval_min <= 0 or self._last_regime_call_at == 0.0:
                return True
            interval_s = min_interval_min * 60
            elapsed    = time.time() - self._last_regime_call_at
            if elapsed < interval_s:
                wait_min = (interval_s - elapsed) / 60
                logger.info(
                    f"Claude budget | Crypto call throttled — "
                    f"{elapsed / 60:.1f}min since last LLM call, "
                    f"min={min_interval_min}min — eligible in {wait_min:.1f}min"
                )
                return False
            return True

    def record_crypto_call(self) -> None:
        with self._lock:
            self._maybe_reset()
            self._last_regime_call_at = time.time()
            self._crypto_calls += 1
            logger.info(
                f"Claude budget | Crypto call #{self._crypto_calls} recorded "
                f"(total_tokens={self._tokens_used})"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Commentary daily cap
    # ──────────────────────────────────────────────────────────────────────────

    def can_call_commentary(self, endpoint: str, force: bool = False) -> bool:
        """
        True unless the per-endpoint daily auto-refresh cap is exceeded.
        force=True bypasses the cap (for manual refreshes via the dashboard).
        No hard budget gate.
        """
        with self._lock:
            self._maybe_reset()
            if force:
                return True
            cap   = _commentary_daily_cap()
            count = self._commentary_calls.get(endpoint, 0)
            if count >= cap:
                logger.info(
                    f"Claude budget | Commentary[{endpoint}] throttled — "
                    f"{count}/{cap} auto-refreshes today"
                )
                return False
            return True

    def record_commentary_call(self, endpoint: str) -> None:
        with self._lock:
            self._maybe_reset()
            self._commentary_calls[endpoint] = (
                self._commentary_calls.get(endpoint, 0) + 1
            )
            logger.info(
                f"Claude budget | Commentary[{endpoint}] call "
                f"#{self._commentary_calls[endpoint]} recorded"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Paid-tier no-ops
    # ──────────────────────────────────────────────────────────────────────────

    def budget_exhausted(self) -> bool:
        """Always False — Claude is a paid tier with no hard daily token cap."""
        return False

    # ──────────────────────────────────────────────────────────────────────────
    # Status / reporting
    # ──────────────────────────────────────────────────────────────────────────

    def next_regime_eligible_at_iso(self) -> str | None:
        min_interval_min = _regime_interval_minutes()
        if min_interval_min <= 0 or self._last_regime_call_at == 0.0:
            return None
        interval_s = min_interval_min * 60
        elapsed    = time.time() - self._last_regime_call_at
        if elapsed >= interval_s:
            return None
        wait_s = interval_s - elapsed
        dt = datetime.now(timezone.utc) + timedelta(seconds=wait_s)
        return dt.isoformat()

    def token_usage_breakdown(self) -> dict:
        """Return per-call-type token breakdown for the admin token-usage endpoint."""
        with self._lock:
            self._maybe_reset()
            used      = self._tokens_used
            breakdown = dict(self._tokens_by_type)
            commentary_total = breakdown.pop("commentary", 0)
            for ep_key in [k for k in breakdown if k.startswith("commentary/")]:
                commentary_total += breakdown.pop(ep_key)
            return {
                "tokens_used_today":  used,
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
            min_interval_min = _regime_interval_minutes()
            interval_s       = min_interval_min * 60
            elapsed          = time.time() - self._last_regime_call_at
            regime_eligible  = (
                self._last_regime_call_at == 0.0
                or min_interval_min <= 0
                or elapsed >= interval_s
            )
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
                "regime_interval_min":     min_interval_min,
                "commentary_daily_cap":    _commentary_daily_cap(),
                "next_regime_eligible_at": self.next_regime_eligible_at_iso(),
                "regime_call_eligible":    regime_eligible,
                "provider":                "claude",
                "budget_exhausted":        False,
            }


budget = ClaudeBudget()
