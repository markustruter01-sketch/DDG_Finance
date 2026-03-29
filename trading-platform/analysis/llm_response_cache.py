"""
LLM Response Cache
-------------------
Prevents redundant Groq API calls when market signals and news have not
materially changed since the last analysis cycle.

Cache key: MD5 of (call_type + per-ticker momentum fingerprint + news fingerprint)
TTL:       90 minutes (configurable via env: LLM_CACHE_TTL_MINUTES)
Backing:   JSON file at data/llm_response_cache.json (survives short restarts)

Expected savings: 1–3 Groq calls per day on quiet days where signals
are stable across consecutive 15-minute cycles (e.g. overnight crypto mode).

Usage:
    from analysis.llm_response_cache import llm_cache

    key = llm_cache.make_key(call_type, market_data, news_headlines)
    cached = llm_cache.get(key)
    if cached:
        return cached          # raw_json string — skip Groq call
    ...
    llm_cache.put(key, raw_json)
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path
from threading import Lock

from loguru import logger


_CATEGORY_RE = re.compile(r"^\[[A-Z]+\]\s*")
_DEFAULT_TTL_MINUTES = int(os.environ.get("LLM_CACHE_TTL_MINUTES", "90"))
_CACHE_FILE = Path(__file__).parent.parent / "data" / "llm_response_cache.json"


class LLMResponseCache:
    """Thread-safe, disk-persisted LLM response cache."""

    def __init__(self, ttl_minutes: int = _DEFAULT_TTL_MINUTES) -> None:
        self._ttl_s = ttl_minutes * 60
        self._lock = Lock()
        self._store: dict[str, dict] = {}  # key → {"raw_json": str, "saved_at": float}
        self._hits = 0
        self._misses = 0
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not _CACHE_FILE.exists():
            return
        try:
            raw = json.loads(_CACHE_FILE.read_text())
            now = time.time()
            for k, v in raw.items():
                if now - v.get("saved_at", 0) < self._ttl_s:
                    self._store[k] = v
            logger.debug(
                f"LLMResponseCache | Loaded {len(self._store)} live entries from disk"
            )
        except Exception as exc:
            logger.warning(f"LLMResponseCache | Load failed (non-fatal): {exc}")

    def _persist(self) -> None:
        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(_CACHE_FILE) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._store, f, indent=2)
            os.replace(tmp, str(_CACHE_FILE))
        except Exception as exc:
            logger.warning(f"LLMResponseCache | Persist failed (non-fatal): {exc}")

    # ── Cache key construction ────────────────────────────────────────────────

    @staticmethod
    def make_key(
        call_type: str,
        market_data: dict,
        news_headlines: list[str],
    ) -> str:
        """
        Build a stable MD5 cache key from the signals that drive LLM decisions.

        Components:
          - call_type:  'regime' or 'crypto'
          - Momentum signals for every ticker (positive/negative — strips price noise)
          - First 5 news headline titles (stripped of description + category prefix)
        """
        momentum_parts: list[str] = []
        for cat, tickers in market_data.get("by_category", {}).items():
            if not isinstance(tickers, dict):
                continue
            for ticker, d in tickers.items():
                if isinstance(d, dict) and "error" not in d:
                    m3 = (d.get("momentum_3mo") or "?")[0]
                    m6 = (d.get("momentum_6mo") or "?")[0]
                    momentum_parts.append(f"{ticker}:{m3}{m6}")
        momentum_parts.sort()

        news_parts: list[str] = []
        for h in news_headlines[:5]:
            clean = _CATEGORY_RE.sub("", h).split(" — ")[0].strip()[:60].lower()
            news_parts.append(clean)

        key_str = f"{call_type}|{','.join(momentum_parts)}|{','.join(news_parts)}"
        return hashlib.md5(key_str.encode()).hexdigest()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        """
        Return cached raw_json string if the entry exists and is within TTL.
        Returns None on miss or expiry.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            age = time.time() - entry.get("saved_at", 0)
            if age > self._ttl_s:
                del self._store[key]
                self._misses += 1
                logger.debug(
                    f"LLMResponseCache | MISS (expired {age / 60:.1f}min > "
                    f"{self._ttl_s / 60:.0f}min TTL) key={key[:8]}…"
                )
                return None
            self._hits += 1
            logger.info(
                f"LLMResponseCache | HIT — skipping Groq call "
                f"(age={age / 60:.1f}min, key={key[:8]}…) "
                f"[hits={self._hits} misses={self._misses}]"
            )
            return entry["raw_json"]

    def put(self, key: str, raw_json: str) -> None:
        """Store a successful LLM raw_json response under key."""
        with self._lock:
            self._store[key] = {"raw_json": raw_json, "saved_at": time.time()}
            self._persist()
            logger.debug(
                f"LLMResponseCache | Stored key={key[:8]}… "
                f"({len(raw_json)} chars)"
            )

    def stats(self) -> dict:
        with self._lock:
            live = sum(
                1 for v in self._store.values()
                if time.time() - v.get("saved_at", 0) < self._ttl_s
            )
            return {
                "cache_hits":       self._hits,
                "cache_misses":     self._misses,
                "live_entries":     live,
                "ttl_minutes":      self._ttl_s // 60,
            }

    def invalidate(self) -> None:
        """Clear all cached entries (manual invalidation)."""
        with self._lock:
            cleared = len(self._store)
            self._store.clear()
            self._persist()
            logger.info(f"LLMResponseCache | Invalidated {cleared} entries")


llm_cache = LLMResponseCache()
