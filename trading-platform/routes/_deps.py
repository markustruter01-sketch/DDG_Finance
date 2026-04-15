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

EXPECTED_JOB_COUNT = 16
COMMENTARY_TTL_SECONDS = 1800

_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}
_kraken_commentary_cache: dict[str, Any] = {"text": None, "generated_at": None, "ts": 0}

KRAKEN_BOT_PROFILES = {
    "davy-jones": {"display_name": "Davy Jones' Portfolio", "db_id": 1, "strategy_label": "Conservative", "port": 8085},
    "blackbeard": {"display_name": "Blackbeard's Fleet", "db_id": 2, "strategy_label": "Aggressive", "port": 8086},
    "calypso":    {"display_name": "Calypso's Tide", "db_id": 3, "strategy_label": "mean_reversion_conservative", "port": 8087},
}

_kraken_commentary_caches: dict[str, dict[str, Any]] = {
    bot_id: {"text": None, "generated_at": None, "ts": 0}
    for bot_id in KRAKEN_BOT_PROFILES
}

_kraken_commentary_round_robin_idx = 0

_COMMENTARY_CACHE_FILE = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "commentary_cache.json"))
_commentary_file_lock = threading.Lock()

_heal_log: list[dict] = []
_heal_lock = threading.Lock()

VAULT_TICKER = "JEPQ"
KNOWN_CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD"}
VAULT_TICKER_PROTECTED = {"JEPQ"}

_KRAKEN_IMPORTED_SIDECAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "kraken_imported_trades.json")
_kraken_imported_lock = threading.Lock()


def _add_heal_entry(component: str, action: str, result: str, success: bool, triggered_by: str = "manual") -> dict:
    entry = {
        "ts": time.time(),
        "component": component,
        "action": action,
        "result": result,
        "success": success,
        "triggered_by": triggered_by,
        "heal_type": "HEALED" if success else "LOGGED",
    }
    with _heal_lock:
        _heal_log.insert(0, entry)
        while len(_heal_log) > 50:
            _heal_log.pop()
    return entry


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

_options_engine_module = None
def _get_options_engine():
    """Lazy singleton for the options_engine module (Apex Predator, Bot #5)."""
    global _options_engine_module
    if _options_engine_module is not None:
        return _options_engine_module
    try:
        import importlib.util as _ilu4
        _opts_path = os.path.join(_REPO_ROOT, "trading-platform", "options_engine.py")
        spec = _ilu4.spec_from_file_location("options_engine", _opts_path)
        mod = _ilu4.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _options_engine_module = mod
        return mod
    except Exception as exc:
        logger.debug(f"Options engine import failed: {exc}")
        return None


_FOREX_ENGINE_PATH = os.path.join(_REPO_ROOT, "forex-engine")
if _FOREX_ENGINE_PATH not in sys.path:
    sys.path.append(_FOREX_ENGINE_PATH)

_forex_engine_module = None
def _get_forex_engine():
    global _forex_engine_module
    if _forex_engine_module is not None:
        return _forex_engine_module
    try:
        import importlib.util as _ilu3
        _fx_path = os.path.join(_REPO_ROOT, "forex-engine")
        if _fx_path not in sys.path:
            sys.path.insert(0, _fx_path)
        spec = _ilu3.spec_from_file_location("forex_engine", os.path.join(_fx_path, "forex_engine.py"))
        mod = _ilu3.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _forex_engine_module = mod
        return mod
    except Exception as exc:
        logger.warning(f"Forex engine import failed: {exc}")
        return None

_forex_db_module = None
def _get_forex_db():
    global _forex_db_module
    if _forex_db_module is not None:
        return _forex_db_module
    try:
        import importlib.util as _ilu2
        _fx_path = os.path.join(_REPO_ROOT, "forex-engine")
        spec = _ilu2.spec_from_file_location("forex_db", os.path.join(_fx_path, "forex_nav_db.py"))
        mod = _ilu2.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _forex_db_module = mod
        return mod
    except Exception as exc:
        logger.warning(f"Forex DB import failed: {exc}")
        return None


def _resolve_bot(bot_id: str | None) -> tuple[str, dict]:
    bid = bot_id or "davy-jones"
    profile = KRAKEN_BOT_PROFILES.get(bid)
    if not profile:
        bid = "davy-jones"
        profile = KRAKEN_BOT_PROFILES["davy-jones"]
    return bid, profile


def _load_kraken_imported() -> set[str]:
    try:
        if os.path.exists(_KRAKEN_IMPORTED_SIDECAR):
            with open(_KRAKEN_IMPORTED_SIDECAR) as f:
                return set(_json.load(f))
    except Exception as exc:
        logger.warning(f"Kraken sync | Failed to load import sidecar: {exc}")
    return set()


def _save_kraken_imported(keys: set[str]) -> None:
    tmp = _KRAKEN_IMPORTED_SIDECAR + ".tmp"
    try:
        with open(tmp, "w") as f:
            _json.dump(list(keys), f)
        os.replace(tmp, _KRAKEN_IMPORTED_SIDECAR)
    except Exception as exc:
        logger.warning(f"Kraken sync | Failed to save import sidecar: {exc}")


def _load_kraken_journal_trades() -> list[dict]:
    try:
        import psycopg2 as _pg2j, psycopg2.extras as _pg2xj
        _dburlj = os.environ.get("DATABASE_URL")
        if not _dburlj:
            return []
        _jconn = _pg2j.connect(_dburlj)
        try:
            with _jconn.cursor(cursor_factory=_pg2xj.RealDictCursor) as _jc:
                _jc.execute(
                    """
                    SELECT symbol, side, pnl_pct, pnl_usd, reason, closed_at,
                           COALESCE(bot_id, 'davy-jones') AS bot_id
                    FROM   kraken_trades ORDER BY closed_at ASC
                    """
                )
                _jrows = _jc.fetchall()
        finally:
            _jconn.close()
        trades = []
        for idx, t in enumerate(_jrows):
            if t.get("pnl_pct") is None:
                continue
            _pnl = float(t["pnl_pct"])
            _pusd = t.get("pnl_usd")
            _reason = t.get("reason")
            trades.append({
                "trade_id": f"kraken-{idx}",
                "date": (t["closed_at"].isoformat() if t.get("closed_at") else "")[:10],
                "ticker": t.get("symbol", "?"),
                "asset_class": "crypto",
                "conviction_score": None,
                "original_thesis": f"Kraken {t.get('side','?')} {t.get('symbol','?')} — exit: {_reason or '?'}",
                "pnl_percentage": _pnl,
                "realized_pnl": float(_pusd) if _pusd is not None else None,
                "exit_reason": _reason,
                "status": "Closed_Win" if _pnl > 0 else "Closed_Loss",
                "intended_price": None,
                "actual_fill_price": None,
                "slippage_pct": None,
                "source": "kraken",
                "bot_id": t.get("bot_id", "davy-jones"),
            })
        return trades
    except Exception as _e:
        logger.warning(f"Kraken journal load failed: {_e}")
        return []


def _sync_kraken_trades_to_journal() -> dict:
    from db.postgres import is_pg_available, get_conn
    from datetime import date

    if not is_pg_available():
        return {"imported": 0, "skipped": 0, "reason": "PostgreSQL unavailable"}

    all_trades = []
    try:
        with get_conn() as _kconn:
            with _kconn.cursor() as _kc:
                _kc.execute(
                    """
                    SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                           fees_usd, reason, closed_at
                    FROM   kraken_trades ORDER BY closed_at ASC
                    """
                )
                for row in _kc.fetchall():
                    sym, side, ep, xp, pct, pusd, fees, reason, cat = row
                    all_trades.append({
                        "symbol":      sym,
                        "side":        side,
                        "entry_price": float(ep) if ep is not None else None,
                        "exit_price":  float(xp) if xp is not None else None,
                        "pnl_pct":     float(pct) if pct is not None else None,
                        "pnl_usd":     float(pusd) if pusd is not None else None,
                        "fees_usd":    float(fees) if fees is not None else None,
                        "reason":      reason,
                        "closed_at":   cat.isoformat() if hasattr(cat, "isoformat") else str(cat) if cat else "",
                    })
    except Exception as exc:
        return {"imported": 0, "skipped": 0, "error": f"Could not read kraken_trades DB: {exc}"}

    if not all_trades:
        return {"imported": 0, "skipped": 0, "reason": "No trades in kraken_trades table"}

    with _kraken_imported_lock:
        imported_keys = _load_kraken_imported()
        new_keys = set()
        imported = 0
        skipped = 0
        errors = 0

        for trade in all_trades:
            symbol = trade.get("symbol", "UNKNOWN")
            closed_at = trade.get("closed_at", "")
            key = f"{symbol}|{closed_at}"
            if key in imported_keys:
                skipped += 1
                continue

            import hashlib
            trade_id = "KRK-" + hashlib.md5(key.encode()).hexdigest()[:16]

            try:
                from datetime import datetime, timezone
                _dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                trade_date = _dt.date().isoformat()
            except Exception:
                trade_date = date.today().isoformat()

            pnl_pct = trade.get("pnl_pct")
            entry_price = trade.get("entry_price")
            exit_price = trade.get("exit_price")
            reason = trade.get("reason", "kraken_paper")

            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO trades
                                (trade_id, date, ticker, asset_class, conviction_score,
                                 original_thesis, pnl_percentage, status,
                                 intended_price, actual_fill_price)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (trade_id) DO NOTHING
                            """,
                            (
                                trade_id,
                                trade_date,
                                symbol.replace("/", ""),
                                "Crypto",
                                5.0,
                                f"Kraken paper trade ({reason})",
                                pnl_pct,
                                "Closed",
                                entry_price,
                                exit_price,
                            ),
                        )
                new_keys.add(key)
                imported += 1
                logger.info(f"Kraken sync | Imported {symbol} {trade_date} pnl={pnl_pct}%")
            except Exception as exc:
                logger.error(f"Kraken sync | Failed to insert {key}: {exc}")
                errors += 1

        imported_keys.update(new_keys)
        if new_keys:
            _save_kraken_imported(imported_keys)

    logger.info(f"Kraken journal sync | imported={imported} skipped={skipped} errors={errors}")
    return {"imported": imported, "skipped": skipped, "errors": errors}
