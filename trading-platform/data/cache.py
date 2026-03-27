import asyncio
import time
from typing import Any

from loguru import logger


class TTLCache:
    def __init__(self, name: str, ttl_seconds: float):
        self._name = name
        self._ttl = ttl_seconds
        self._data: Any = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()
        self._hit_count = 0
        self._miss_count = 0

    @property
    def is_valid(self) -> bool:
        return self._data is not None and (time.time() - self._fetched_at) < self._ttl

    @property
    def age_seconds(self) -> float:
        if self._fetched_at == 0:
            return -1
        return time.time() - self._fetched_at

    @property
    def stats(self) -> dict:
        return {
            "name": self._name,
            "ttl_seconds": self._ttl,
            "cached": self._data is not None,
            "age_seconds": round(self.age_seconds, 1),
            "hits": self._hit_count,
            "misses": self._miss_count,
        }

    def invalidate(self) -> None:
        self._data = None
        self._fetched_at = 0.0
        logger.info(f"Cache[{self._name}] | Invalidated")

    async def get_or_fetch(self, fetch_fn, *args, **kwargs) -> Any:
        if self.is_valid:
            self._hit_count += 1
            age = self.age_seconds
            logger.info(
                f"Cache[{self._name}] | HIT (age={age:.0f}s, ttl={self._ttl}s)"
            )
            return self._data

        async with self._lock:
            if self.is_valid:
                self._hit_count += 1
                return self._data

            self._miss_count += 1
            logger.info(f"Cache[{self._name}] | MISS — fetching fresh data...")
            self._data = await fetch_fn(*args, **kwargs)
            self._fetched_at = time.time()
            logger.info(f"Cache[{self._name}] | Stored (ttl={self._ttl}s)")
            return self._data


fred_cache = TTLCache("fred_macro", ttl_seconds=3600)
news_cache = TTLCache("newsapi", ttl_seconds=1800)


def get_cache_stats() -> list[dict]:
    return [fred_cache.stats, news_cache.stats]


def invalidate_all() -> None:
    fred_cache.invalidate()
    news_cache.invalidate()
