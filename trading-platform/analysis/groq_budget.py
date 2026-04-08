"""
LLM Budget Manager (Gemini)
---------------------------------
Tracks daily token consumption across all Gemini API calls and enforces:
  1. A minimum interval between regime/crypto LLM calls (default 90 min).
  2. A daily cap on auto-triggered commentary calls per endpoint (default 4/day).
  3. A daily token budget (default 10M — effectively unlimited for Gemini).

All counters reset at midnight UTC. Settings are fully configurable via
settings.py (env vars GROQ_DAILY_TOKEN_BUDGET, GROQ_MIN_REGIME_INTERVAL_MINUTES,
GROQ_COMMENTARY_DAILY_CAP).

Usage:
    from analysis.groq_budget import budget

    budget.consume(tokens)                # called automatically by groq_client.py
    budget.can_call_regime()              # True if interval + budget allows it
    budget.record_regime_call()           # call after a successful regime LLM call
    budget.can_call_commentary(ep, force) # True if cap not exceeded (force bypasses)
    budget.record_commentary_call(ep)     # call after a successful commentary call
    budget.budget_status()               # dict for the /status groq block
"""

import os
import time
from datetime import datetime, timedelta, timezone
from threading import Lock

from loguru import logger

try:
    from config.settings import settings as _cfg_settings
except (ImportError, ModuleNotFoundError):
    class _cfg_settings:  # type: ignore[no-redef]
        groq_daily_token_budget: int = int(os.environ.get("GROQ_DAILY_TOKEN_BUDGET", "10000000"))
        groq_min_regime_interval_minutes: int = int(os.environ.get("GROQ_MIN_REGIME_INTERVAL_MINUTES", "90"))
        groq_commentary_daily_cap: int = int(os.environ.get("GROQ_COMMENTARY_DAILY_CAP", "4"))

settings = _cfg_settings


class GroqBudget:
    def __init__(self) -> None:
        self._lock = Lock()
        self._reset_day: int = self._today_utc()
        self._tokens_used: int = 0
        self._regime_calls: int = 0
        self._crypto_calls: int = 0
        self._last_regime_call_at: float = 0.0
        self._commentary_calls: dict[str, int] = {}
        # Per-call-type token tracking: {"regime": 0, "crypto": 0, "commentary": 0, ...}
        self._tokens_by_type: dict[str, int] = {}
        # Track which endpoints have already received a budget-exhausted warning
        # today — prevents log spam under repeated polling.
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
            self._budget_warned = set()  # clear one-shot warning state on day roll
            logger.info(
                f"Groq budget | Daily counters reset (day rolled over "
                f"{old_day} → {today})"
            )

    def consume(self, tokens: int, call_type: str = "unknown") -> None:
        with self._lock:
            self._maybe_reset()
            self._tokens_used += tokens
            self._tokens_by_type[call_type] = (
                self._tokens_by_type.get(call_type, 0) + tokens
            )
            remaining = max(0, settings.groq_daily_token_budget - self._tokens_used)
            pct = (
                self._tokens_used / settings.groq_daily_token_budget * 100
                if settings.groq_daily_token_budget > 0 else 0.0
            )
            logger.debug(
                f"Groq budget | +{tokens} tokens [{call_type}] — "
                f"used={self._tokens_used}/{settings.groq_daily_token_budget} "
                f"({pct:.1f}%) remaining={remaining}"
            )
            if settings.groq_daily_token_budget > 0 and pct >= 90:
                logger.warning(
                    f"Groq budget | ⚠️  {pct:.1f}% of daily token budget consumed"
                )

    def can_call_regime(self, cache_age_min: float = 0.0) -> bool:
        """
        True if both conditions are satisfied:
          - Daily token budget not exhausted
          - Minimum interval since last regime call has elapsed (or 0 = disabled)

        Args:
            cache_age_min: Age of the current regime cache in minutes. If > 360
                           (6 hours stale), the throttle interval is bypassed so a
                           refresh is forced regardless of when the last call ran.
        """
        with self._lock:
            self._maybe_reset()

            remaining = settings.groq_daily_token_budget - self._tokens_used
            if remaining <= 0:
                logger.warning(
                    "Groq budget | Regime call blocked — daily token budget exhausted"
                )
                return False

            # Stale-cache override: if the cache is > 6 hours old, bypass the
            # interval throttle unconditionally so we never get locked out of a
            # refresh by a prior failed call that still advanced the timer.
            if cache_age_min > 360:
                logger.info(
                    f"Groq budget | Stale-cache override: cache_age={cache_age_min:.0f}min > 360 "
                    "— bypassing throttle to force refresh"
                )
                return True

            min_interval_min = settings.groq_min_regime_interval_minutes
            if min_interval_min <= 0:
                return True

            interval_s = min_interval_min * 60
            elapsed = time.time() - self._last_regime_call_at
            if self._last_regime_call_at > 0 and elapsed < interval_s:
                wait_min = (interval_s - elapsed) / 60
                logger.info(
                    f"Groq budget | Regime call throttled — "
                    f"{elapsed / 60:.1f}min since last call, "
                    f"min={min_interval_min}min — "
                    f"eligible in {wait_min:.1f}min"
                )
                return False

            return True

    def record_regime_call(self) -> None:
        with self._lock:
            self._maybe_reset()
            self._last_regime_call_at = time.time()
            self._regime_calls += 1
            logger.info(
                f"Groq budget | Full-regime call #{self._regime_calls} recorded "
                f"(used={self._tokens_used}/{settings.groq_daily_token_budget})"
            )

    def record_regime_failure(self) -> None:
        """
        Record a FAILED regime/crypto LLM call.
        Instead of advancing the timer by the full 90-min interval (which would
        lock out retries for 90 minutes even after a transient error), this sets
        the timer so the throttle clears in ~15 minutes — a short retry window.
        """
        with self._lock:
            self._maybe_reset()
            interval_s = settings.groq_min_regime_interval_minutes * 60
            # Set timer as if the call happened (interval - 15min) ago so the
            # next can_call_regime() check clears in ~15 minutes.
            self._last_regime_call_at = time.time() - (interval_s - 15 * 60)
            logger.warning(
                "Groq budget | Regime/crypto call FAILED — "
                "next retry eligible in ~15 min (failure retry window)"
            )

    def can_call_crypto(self) -> bool:
        """
        True if a crypto-only LLM call is allowed right now:
          - Daily token budget not exhausted
          - Minimum interval since last ANY regime/crypto LLM call has elapsed
        Shares the same `_last_regime_call_at` timer as `can_call_regime()` so
        that the 90-min pacing applies across the full+crypto call mix.
        """
        with self._lock:
            self._maybe_reset()

            remaining = settings.groq_daily_token_budget - self._tokens_used
            if remaining <= 0:
                logger.warning(
                    "Groq budget | Crypto call blocked — daily token budget exhausted"
                )
                return False

            min_interval_min = settings.groq_min_regime_interval_minutes
            if min_interval_min <= 0:
                return True

            interval_s = min_interval_min * 60
            elapsed = time.time() - self._last_regime_call_at
            if self._last_regime_call_at > 0 and elapsed < interval_s:
                wait_min = (interval_s - elapsed) / 60
                logger.info(
                    f"Groq budget | Crypto call throttled — "
                    f"{elapsed / 60:.1f}min since last LLM call, "
                    f"min={min_interval_min}min — "
                    f"eligible in {wait_min:.1f}min"
                )
                return False

            return True

    def record_crypto_call(self) -> None:
        """Record a successful crypto-only LLM call (updates shared timer + own counter)."""
        with self._lock:
            self._maybe_reset()
            self._last_regime_call_at = time.time()
            self._crypto_calls += 1
            logger.info(
                f"Groq budget | Crypto call #{self._crypto_calls} recorded "
                f"(used={self._tokens_used}/{settings.groq_daily_token_budget})"
            )

    def can_call_commentary(self, endpoint: str, force: bool = False) -> bool:
        with self._lock:
            self._maybe_reset()

            remaining = settings.groq_daily_token_budget - self._tokens_used
            if remaining <= 0:
                # Zero budget blocks even forced refreshes — calling Groq would
                # just return a 429 and generate an error event.
                # Only emit one warning per endpoint per day to avoid log spam.
                if endpoint not in self._budget_warned:
                    self._budget_warned.add(endpoint)
                    logger.warning(
                        f"Groq budget | Commentary[{endpoint}] budget exhausted — "
                        "all further calls suppressed until midnight UTC"
                    )
                return False

            # force=True bypasses the *call-count* cap but not the zero-budget
            # check above.  This lets the user manually refresh when they still
            # have tokens remaining, without wasting tokens they no longer have.
            if force:
                return True

            cap = settings.groq_commentary_daily_cap
            count = self._commentary_calls.get(endpoint, 0)
            if count >= cap:
                logger.info(
                    f"Groq budget | Commentary[{endpoint}] throttled — "
                    f"{count}/{cap} auto-refreshes today"
                )
                return False

            return True

    def token_usage_breakdown(self) -> dict:
        """
        Return per-call-type token breakdown for the admin token-usage endpoint.
        Includes daily totals broken down by: regime, crypto, commentary, unknown.
        """
        with self._lock:
            self._maybe_reset()
            used = self._tokens_used
            total = settings.groq_daily_token_budget
            remaining = max(0, total - used)
            pct = round(used / total * 100, 1) if total > 0 else 0.0
            breakdown = dict(self._tokens_by_type)
            commentary_total = breakdown.pop("commentary", 0)
            for ep_key in [k for k in breakdown if k.startswith("commentary/")]:
                commentary_total += breakdown.pop(ep_key)
            return {
                "tokens_used_today":    used,
                "tokens_remaining":     remaining,
                "token_budget_total":   total,
                "pct_used":             pct,
                "by_call_type":         {
                    "regime":      breakdown.get("regime", 0),
                    "crypto":      breakdown.get("crypto", 0),
                    "commentary":  commentary_total,
                    "audit":       breakdown.get("audit", 0),
                    "performance": breakdown.get("performance", 0),
                    "unknown":     breakdown.get("unknown", 0),
                    **{k: v for k, v in breakdown.items()
                       if k not in ("regime", "crypto", "audit", "performance", "unknown")},
                },
                "regime_calls_today":   self._regime_calls,
                "crypto_calls_today":   self._crypto_calls,
            }

    def budget_exhausted(self) -> bool:
        """Return True when the daily token budget is at zero."""
        with self._lock:
            self._maybe_reset()
            return (settings.groq_daily_token_budget - self._tokens_used) <= 0

    def record_commentary_call(self, endpoint: str) -> None:
        with self._lock:
            self._maybe_reset()
            self._commentary_calls[endpoint] = (
                self._commentary_calls.get(endpoint, 0) + 1
            )
            logger.info(
                f"Groq budget | Commentary[{endpoint}] call "
                f"#{self._commentary_calls[endpoint]} recorded"
            )

    def next_regime_eligible_at_iso(self) -> str | None:
        min_interval_min = settings.groq_min_regime_interval_minutes
        if min_interval_min <= 0 or self._last_regime_call_at == 0:
            return None
        interval_s = min_interval_min * 60
        elapsed = time.time() - self._last_regime_call_at
        if elapsed >= interval_s:
            return None
        wait_s = interval_s - elapsed
        dt = datetime.now(timezone.utc) + timedelta(seconds=wait_s)
        return dt.isoformat()

    def budget_status(self) -> dict:
        """
        Return a dict suitable for the /status groq block.

        `commentary_calls_today` counts AUTO-triggered refreshes only (force=False).
        Manual force=True calls bypass the cap and are not counted here,
        though their token usage IS still tracked in `tokens_used_today`.
        """
        with self._lock:
            self._maybe_reset()
            used = self._tokens_used
            total = settings.groq_daily_token_budget
            remaining = max(0, total - used)
            pct_used = round(used / total * 100, 1) if total > 0 else 0.0
            interval_s = settings.groq_min_regime_interval_minutes * 60
            elapsed = time.time() - self._last_regime_call_at
            regime_eligible = (
                self._last_regime_call_at == 0
                or settings.groq_min_regime_interval_minutes <= 0
                or elapsed >= interval_s
            ) and (used < total)
            by_type = dict(self._tokens_by_type)
            return {
                "tokens_used_today":       used,
                "tokens_remaining":        remaining,
                "token_budget_total":      total,
                "pct_used":                pct_used,
                "regime_calls_today":      self._regime_calls,
                "crypto_calls_today":      self._crypto_calls,
                "analysis_calls_today":    self._regime_calls + self._crypto_calls,
                "commentary_calls_today":  dict(self._commentary_calls),
                "tokens_by_call_type":     {
                    "regime":      by_type.get("regime", 0),
                    "crypto":      by_type.get("crypto", 0),
                    "commentary":  by_type.get("commentary", 0),
                    "audit":       by_type.get("audit", 0),
                    "performance": by_type.get("performance", 0),
                    "unknown":     by_type.get("unknown", 0),
                },
                "regime_interval_min":     settings.groq_min_regime_interval_minutes,
                "commentary_daily_cap":    settings.groq_commentary_daily_cap,
                "next_regime_eligible_at": self.next_regime_eligible_at_iso(),
                "regime_call_eligible":    regime_eligible,
            }


budget = GroqBudget()
