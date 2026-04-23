"""
Resilience Layer — Alpaca 429 Rate-Limit Backoff
--------------------------------------------------
Wraps Alpaca API calls with exponential backoff to handle the retail
limit of 200 requests/minute (≈ one request every 300 ms).

Strategy
--------
  • Detect HTTP 429 (Too Many Requests) from the alpaca-py SDK.
  • Retry with full-jitter exponential backoff: wait ∈ [0, min(cap, base·2ⁿ)]
  • Max 5 attempts, cap at 60 s, base = 1 s.
  • Non-429 errors propagate immediately — no unnecessary retry.

Usage
-----
    from execution.resilience import alpaca_retry

    @alpaca_retry
    def my_broker_fn():
        ...
"""

import functools
import time
import random
import threading as _threading

from loguru import logger

# ── constants ──────────────────────────────────────────────────────────────
_MAX_TRIES   = 5
_BASE_WAIT   = 1.0    # seconds
_WAIT_CAP    = 60.0   # seconds
_MIN_SPACING = 0.30   # 300 ms floor between any two Alpaca calls (200 req/min)

# Track last-call timestamp for spacing (shared across sync and async wrappers)
_last_call_ts: float = 0.0
_rate_limit_lock = _threading.Lock()
_async_rate_limit_lock: "asyncio.Lock | None" = None


def _is_rate_limit_error(exc: BaseException) -> bool:
    """
    Return True for any exception that signals an Alpaca 429 response.
    alpaca-py raises APIError / RequestError whose str() contains the
    HTTP status code; we also check for httpx.HTTPStatusError.
    """
    msg = str(exc).lower()
    if "429" in msg or "too many requests" in msg or "rate limit" in msg:
        return True
    try:
        # httpx wraps the status code on the response attribute
        if hasattr(exc, "response") and getattr(exc.response, "status_code", 0) == 429:
            return True
    except Exception:
        pass
    return False


def alpaca_retry(fn):
    """
    Decorator: wraps fn with:
      1. Minimum-spacing enforcement (300 ms between calls).
      2. Exponential-backoff retry on 429 errors (up to 5 tries).
    Non-429 exceptions propagate immediately on the first occurrence.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global _last_call_ts

        # --- minimum spacing (atomic read-check-sleep-write under lock) ---
        with _rate_limit_lock:
            elapsed = time.monotonic() - _last_call_ts
            if elapsed < _MIN_SPACING:
                time.sleep(_MIN_SPACING - elapsed)
            _last_call_ts = time.monotonic()

        for attempt in range(1, _MAX_TRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    if attempt == _MAX_TRIES:
                        logger.error(
                            f"Resilience | {fn.__name__} — 429 after "
                            f"{_MAX_TRIES} attempts; giving up."
                        )
                        raise
                    # full-jitter exponential backoff
                    cap   = min(_WAIT_CAP, _BASE_WAIT * (2 ** attempt))
                    wait  = random.uniform(0, cap)
                    logger.warning(
                        f"Resilience | {fn.__name__} — 429 rate-limited "
                        f"(attempt {attempt}/{_MAX_TRIES}); "
                        f"backing off {wait:.1f}s"
                    )
                    time.sleep(wait)
                else:
                    raise  # not a 429 — propagate immediately

    return wrapper


def alpaca_retry_async(fn):
    """
    Async variant of alpaca_retry for coroutines.
    """
    import asyncio

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        global _last_call_ts, _async_rate_limit_lock

        # --- lazy-init async lock (must be created inside a running loop) ---
        if _async_rate_limit_lock is None:
            _async_rate_limit_lock = asyncio.Lock()

        # --- minimum spacing (atomic read-check-sleep-write under async lock) ---
        async with _async_rate_limit_lock:
            elapsed = time.monotonic() - _last_call_ts
            if elapsed < _MIN_SPACING:
                await asyncio.sleep(_MIN_SPACING - elapsed)
            _last_call_ts = time.monotonic()

        for attempt in range(1, _MAX_TRIES + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    if attempt == _MAX_TRIES:
                        logger.error(
                            f"Resilience | {fn.__name__} — 429 after "
                            f"{_MAX_TRIES} attempts; giving up."
                        )
                        raise
                    cap  = min(_WAIT_CAP, _BASE_WAIT * (2 ** attempt))
                    wait = random.uniform(0, cap)
                    logger.warning(
                        f"Resilience | {fn.__name__} — 429 rate-limited "
                        f"(attempt {attempt}/{_MAX_TRIES}); "
                        f"backing off {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

    return wrapper
