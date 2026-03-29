"""
Groq Daily Token Budget Manager
---------------------------------
Tracks daily token consumption across all Groq API calls and enforces:
  1. A minimum interval between regime/crypto LLM calls (default 90 min).
  2. A daily cap on auto-triggered commentary calls per endpoint (default 4/day).
  3. A hard daily token budget (default 100,000 TPD — free-tier limit).

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

import time
from datetime import datetime, timedelta, timezone
from threading import Lock

from loguru import logger

from config.settings import settings


class GroqBudget:
    def __init__(self) -> None:
        self._lock = Lock()
        self._reset_day: int = self._today_utc()
        self._tokens_used: int = 0
        self._regime_calls: int = 0
        self._last_regime_call_at: float = 0.0
        self._commentary_calls: dict[str, int] = {}

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
            self._commentary_calls = {}
            self._last_regime_call_at = 0.0
            logger.info(
                f"Groq budget | Daily counters reset (day rolled over "
                f"{old_day} → {today})"
            )

    def consume(self, tokens: int) -> None:
        with self._lock:
            self._maybe_reset()
            self._tokens_used += tokens
            remaining = max(0, settings.groq_daily_token_budget - self._tokens_used)
            pct = self._tokens_used / settings.groq_daily_token_budget * 100
            logger.debug(
                f"Groq budget | +{tokens} tokens consumed — "
                f"used={self._tokens_used}/{settings.groq_daily_token_budget} "
                f"({pct:.1f}%) remaining={remaining}"
            )
            if pct >= 90:
                logger.warning(
                    f"Groq budget | ⚠️  {pct:.1f}% of daily token budget consumed"
                )

    def can_call_regime(self) -> bool:
        """
        True if both conditions are satisfied:
          - Daily token budget not exhausted
          - Minimum interval since last regime call has elapsed (or 0 = disabled)
        """
        with self._lock:
            self._maybe_reset()

            remaining = settings.groq_daily_token_budget - self._tokens_used
            if remaining <= 0:
                logger.warning(
                    "Groq budget | Regime call blocked — daily token budget exhausted"
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
                f"Groq budget | Regime call #{self._regime_calls} recorded "
                f"(used={self._tokens_used}/{settings.groq_daily_token_budget})"
            )

    def can_call_commentary(self, endpoint: str, force: bool = False) -> bool:
        if force:
            return True
        with self._lock:
            self._maybe_reset()

            remaining = settings.groq_daily_token_budget - self._tokens_used
            if remaining <= 0:
                logger.warning(
                    f"Groq budget | Commentary[{endpoint}] blocked — "
                    "daily token budget exhausted"
                )
                return False

            cap = settings.groq_commentary_daily_cap
            count = self._commentary_calls.get(endpoint, 0)
            if count >= cap:
                logger.info(
                    f"Groq budget | Commentary[{endpoint}] throttled — "
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
            return {
                "tokens_used_today":       used,
                "tokens_remaining":        remaining,
                "token_budget_total":      total,
                "pct_used":                pct_used,
                "regime_calls_today":      self._regime_calls,
                "commentary_calls_today":  dict(self._commentary_calls),
                "regime_interval_min":     settings.groq_min_regime_interval_minutes,
                "commentary_daily_cap":    settings.groq_commentary_daily_cap,
                "next_regime_eligible_at": self.next_regime_eligible_at_iso(),
                "regime_call_eligible":    regime_eligible,
            }


budget = GroqBudget()
