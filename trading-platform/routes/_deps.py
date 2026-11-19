"""
Shared mutable state and helpers used across route modules.

Imported by main.py at startup so that lifespan, middleware, and routes
all reference the SAME object instances.
"""

from __future__ import annotations

import json as _json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXPECTED_JOB_COUNT = 13
COMMENTARY_TTL_SECONDS = 1800

_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}
_kraken_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}

KRAKEN_BOT_PROFILES = {
    "davy-jones":    {"display_name": "Davy Jones' Portfolio", "db_id": 1, "strategy_label": "Conservative", "port": 8085},
    "blackbeard":    {"display_name": "Jerome", "db_id": 2, "strategy_label": "LLM Commodity Macro", "port": 8086},
    "calypso":       {"display_name": "Calypso's Tide", "db_id": 3, "strategy_label": "mean_reversion_conservative", "port": 8087},
    "apex-predator": {"display_name": "Apex Predator", "db_id": 4, "strategy_label": "Dual-TF Momentum Scalper", "port": 8088},
}

_kraken_commentary_caches: dict[str, dict[str, Any]] = {
    bot_id: {"text": None, "generated_at": None, "ts": 0}
    for bot_id in KRAKEN_BOT_PROFILES
}

_kraken_commentary_round_robin_idx = 0

_COMMENTARY_CACHE_FILE = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "commentary_cache.json"))
_commentary_file_lock = threading.Lock()

VAULT_TICKER = "JEPQ"
KNOWN_CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD"}
VAULT_TICKER_PROTECTED = {"JEPQ"}

def _load_commentary_caches() -> None:
    global _commentary_cache, _kraken_commentary_cache, _kraken_commentary_caches
    if not _COMMENTARY_CACHE_FILE.exists():
        return
    try:
        data = _json.loads(_COMMENTARY_CACHE_FILE.read_text())
        alpaca = data.get("alpaca", {})
        if alpaca.get("text") and alpaca.get("ts", 0) > 0:
            _commentary_cache.update(alpaca)
            age_min = (time.time() - alpaca["ts"]) / 60
            logger.info(f"Commentary cache | Alpaca: loaded from disk ({age_min:.0f}min old)")
        kraken = data.get("kraken", {})
        if kraken.get("text") and kraken.get("ts", 0) > 0:
            _kraken_commentary_cache.update(kraken)
            _kraken_commentary_caches["davy-jones"] = dict(kraken)
            age_min = (time.time() - kraken["ts"]) / 60
            logger.info(f"Commentary cache | Kraken (davy-jones): loaded from disk ({age_min:.0f}min old)")
        kraken_bots = data.get("kraken_bots", {})
        for bot_id, cache_data in kraken_bots.items():
            if bot_id in _kraken_commentary_caches and cache_data.get("text") and cache_data.get("ts", 0) > 0:
                _kraken_commentary_caches[bot_id] = cache_data
                age_min = (time.time() - cache_data["ts"]) / 60
                logger.info(f"Commentary cache | Kraken ({bot_id}): loaded from disk ({age_min:.0f}min old)")
    except Exception as exc:
        logger.warning(f"Commentary cache | Failed to load from disk: {exc}")


def _persist_commentary_caches() -> None:
    try:
        _COMMENTARY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "alpaca": _commentary_cache,
            "kraken": _kraken_commentary_cache,
            "kraken_bots": _kraken_commentary_caches,
        }
        tmp = str(_COMMENTARY_CACHE_FILE) + ".tmp"
        with _commentary_file_lock:
            with open(tmp, "w") as f:
                _json.dump(payload, f, indent=2)
            os.replace(tmp, str(_COMMENTARY_CACHE_FILE))
    except Exception as exc:
        logger.warning(f"Commentary cache | Failed to persist to disk: {exc}")


_OPTIONS_ENGINE_PATH = os.path.join(_REPO_ROOT, "trading-platform")
if _OPTIONS_ENGINE_PATH not in sys.path:
    sys.path.insert(0, _OPTIONS_ENGINE_PATH)

def _get_options_engine():
    """Options engine retired — Apex Predator (Bot #5) now runs as Kraken crypto momentum.
    Returns None so all callers fall through to their existing except/None-guard paths."""
    return None




def _resolve_bot(bot_id: str | None) -> tuple[str, dict]:
    bid = bot_id or "davy-jones"
    profile = KRAKEN_BOT_PROFILES.get(bid)
    if not profile:
        bid = "davy-jones"
        profile = KRAKEN_BOT_PROFILES["davy-jones"]
    return bid, profile


def _load_kraken_journal_trades() -> list[dict]:
    """Legacy journal source retired; degraded callers receive no rows."""
    return []
