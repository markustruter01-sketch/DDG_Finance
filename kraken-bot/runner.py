#!/usr/bin/env python3
"""
runner.py — Multiplexed runner for kraken-bot ETF/macro strategies.
Replaces 5 separate processes (bot2_spy_qqq, blackbeard, bot4_sector,
bot5_defensive, bot7_macro_bond) with one process running 5 threads.

Each thread runs its leaf strategy's cycle function on its own LOOP_SLEEP
interval. Health server reports all 5 bots' status on a single port.

Architecture:
  - Imports BOT_PROFILES from config.py (read-only dict)
  - Spawns 1 thread per bot via importlib.import_module()
  - Health server on $PORT returns JSON with all 5 bot statuses
  - Per-thread error handling with exponential backoff on failure
  - Graceful shutdown via SIGTERM
"""
from __future__ import annotations
import os
import sys
import time
import json
import signal
import threading
import importlib
import traceback
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

# Path surgery — match main.py's pattern
_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# Order matters: trading-platform must precede kraken-bot/ so that
# `db.postgres` imports resolve to the package, not the flat db.py shim.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # kraken-bot/ (last priority)
sys.path.insert(0, _REPO_ROOT)                                    # repo root
sys.path.insert(0, os.path.join(_REPO_ROOT, "trading-platform")) # trading-platform (winning priority)

from loguru import logger

# Bridge stdlib logging → loguru so that jerome_alpaca / etf_engine
# logger.error() calls are visible in the workflow output.
import logging as _stdlib_logging


class _InterceptHandler(_stdlib_logging.Handler):
    def emit(self, record: _stdlib_logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


_stdlib_logging.basicConfig(handlers=[_InterceptHandler()], level=_stdlib_logging.INFO, force=True)

# Load kraken-bot's local config.py by absolute path.
# Cannot use `from config import ...` because trading-platform/ comes first
# in sys.path (required for db.postgres resolution), and trading-platform/
# has its own config/ package without BOT_PROFILES.
import importlib.util as _ilu
_KRAKEN_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
_cfg_spec = _ilu.spec_from_file_location("_kraken_local_config", _KRAKEN_CONFIG_PATH)
_cfg_mod = _ilu.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(_cfg_mod)
BOT_PROFILES = _cfg_mod.BOT_PROFILES

# Heartbeat helpers — loaded after sys.path is configured so core.bot_state resolves clean.
# touch_heartbeat updates ONLY last_heartbeat/status/error — never zeroes equity_usd.
try:
    from core.bot_state import touch_heartbeat as _bs_touch, LEGACY_TO_CANONICAL as _bs_canonical
    _heartbeat_ok = True
except Exception as _hb_exc:
    logger.warning(f"Runner | Could not import heartbeat helpers: {_hb_exc}")
    _heartbeat_ok = False
    _bs_canonical: dict = {}
    _bs_touch = lambda *a, **k: None  # noqa: E731

try:
    from core.bot_state import write_portfolio as _bs_write_portfolio
    _portfolio_write_ok = True
except ImportError:
    _bs_write_portfolio = lambda *a, **k: None  # noqa: E731
    _portfolio_write_ok = False

# Bot registry: (canonical_bot_id, leaf_module_name, leaf_function_name)
BOTS = [
    # Stage 3B (2026-08-07): oracle slot repurposed to Asia-Pacific ETF trend.
    # bot_id stays "oracle" (frozen — DB, dashboard, fleet equity all key on it).
    ("oracle",           "asia_trend_strategy",   "run_asia_cycle"),
    ("blackbeard",       "latam_trend_strategy",  "run_latam_cycle"),
    ("bot2_spy_qqq",     "bot2_spy_qqq",          "run_bot2_cycle"),
    # Stage 5 (2026-08-11): buck_futures slot repurposed to Frontier/EM ETF trend.
    # bot_id stays "buck_futures" (frozen — DB, dashboard, fleet equity all key on it).
    # Alpaca account: ALPACA_JEROME_API_KEY / ALPACA_JEROME_SECRET_KEY (Jerome paper
    # account, shared with blackbeard/LatAm — partitioned by non-overlapping universe).
    ("buck_futures",     "frontier_trend_strategy", "run_frontier_cycle"),
]

# Per-bot status tracker for health endpoint
_bot_status: dict[str, dict] = {}
_status_lock = threading.Lock()
_shutdown_event = threading.Event()


def _update_status(bot_id: str, **fields):
    with _status_lock:
        if bot_id not in _bot_status:
            _bot_status[bot_id] = {}
        _bot_status[bot_id].update(fields)
        _bot_status[bot_id]["last_updated"] = datetime.now(timezone.utc).isoformat()


def _write_portfolio_from_alpaca(bot_id: str, profile: dict) -> bool:
    """Fetch live Alpaca account state and write to bot_portfolio.
    Called by _run_bot_loop after each successful leaf cycle.
    Returns True if write succeeded, False if any step failed.
    All exceptions are caught — never propagates.

    Note: buck_futures shares the Jerome account (6da42513-...) with blackbeard.
    Its equity is NOT written here — blackbeard's cycle already writes the shared
    account equity to jerome_macro. Writing it again under buck_futures would
    double-count that account in the fleet total. Buck is tracked as a $100k
    notional sim entry in bot_portfolio; its equity does not change via Alpaca writes.
    """
    if bot_id == "buck_futures":
        logger.debug(f"[{bot_id}] portfolio write skipped — shares Jerome account; tracked as notional sim")
        return True
    if not _portfolio_write_ok or not _heartbeat_ok:
        return False
    try:
        import alpaca_trade_api as tradeapi

        api_key = profile.get("ALPACA_API_KEY", "")
        secret_key = profile.get("ALPACA_SECRET_KEY", "")
        base_url = profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        if not api_key or not secret_key:
            logger.debug(f"[{bot_id}] portfolio write skipped — no Alpaca credentials")
            return False

        api = tradeapi.REST(api_key, secret_key, base_url=base_url)
        acct = api.get_account()
        posns = api.list_positions()

        canonical = _bs_canonical.get(bot_id, bot_id)

        positions_list = [
            {
                "symbol": p.symbol,
                "side": p.side,
                "size": float(p.market_value or 0),
                "entry": float(p.avg_entry_price or 0),
                "value_usd": float(p.market_value or 0),
                "unrealized_pl": float(p.unrealized_pl or 0),
                "qty": float(p.qty or 0),
            }
            for p in posns
        ]

        _bs_write_portfolio(
            canonical,
            cash=float(acct.cash or 0),
            equity=float(acct.equity or 0),
            positions=positions_list,
        )
        logger.debug(f"[{bot_id}] bot_portfolio write OK — equity={acct.equity}")
        return True
    except Exception as exc:
        logger.debug(f"[{bot_id}] portfolio write failed (non-fatal): {exc}")
        return False


def _run_bot_loop(bot_id: str, module_name: str, fn_name: str):
    """Per-bot thread entry point. Loops cycle function with sleep + error handling."""
    logger.info(f"[{bot_id}] Thread starting...")

    # Lazy load the bot profile — BOT_PROFILES loaded at module level via importlib
    profile = BOT_PROFILES.get(bot_id)
    if not profile:
        logger.error(f"[{bot_id}] Profile not found in BOT_PROFILES")
        _update_status(bot_id, status="error", error="profile_not_found")
        return

    sleep_seconds = profile.get("LOOP_SLEEP_SECONDS", 900)
    db_id = profile.get("db_id")

    # Lazy import the leaf module
    try:
        mod = importlib.import_module(module_name)
        cycle_fn = getattr(mod, fn_name)
    except Exception as exc:
        logger.error(f"[{bot_id}] Could not load {module_name}.{fn_name}: {exc}")
        _update_status(bot_id, status="error", error=f"import_failed: {exc}")
        return

    logger.info(f"[{bot_id}] Ready. Cycle interval: {sleep_seconds}s")
    _update_status(bot_id, status="running", cycle_count=0, sleep_seconds=sleep_seconds)

    cycle_count = 0
    consecutive_errors = 0

    while not _shutdown_event.is_set():
        try:
            cycle_count += 1
            cycle_start = time.time()
            _update_status(bot_id, status="running", cycle_count=cycle_count,
                           last_cycle_start=datetime.now(timezone.utc).isoformat())

            cycle_fn(profile=profile, db_id=db_id)

            cycle_duration = time.time() - cycle_start
            _update_status(bot_id, status="running",
                           last_cycle_duration_seconds=round(cycle_duration, 2),
                           last_cycle_end=datetime.now(timezone.utc).isoformat(),
                           error=None)
            consecutive_errors = 0

            if _heartbeat_ok:
                try:
                    _bs_touch(_bs_canonical.get(bot_id, bot_id), status="running", error="")
                except Exception as _hb_e:
                    logger.debug(f"[{bot_id}] heartbeat write failed (non-fatal): {_hb_e}")

            # Write live Alpaca state to bot_portfolio (Stage 2 unification)
            _write_portfolio_from_alpaca(bot_id, profile)

        except Exception as exc:
            consecutive_errors += 1
            tb = traceback.format_exc()
            logger.error(f"[{bot_id}] Cycle {cycle_count} failed (consecutive={consecutive_errors}): {exc}\n{tb}")
            _update_status(bot_id, status="error", error=str(exc),
                           consecutive_errors=consecutive_errors)
            if _heartbeat_ok:
                try:
                    _bs_touch(_bs_canonical.get(bot_id, bot_id), status="error", error=str(exc)[:200])
                except Exception:
                    pass

        # Exponential backoff on repeated errors (capped at 8x sleep)
        backoff_multiplier = min(2 ** min(consecutive_errors, 3), 8) if consecutive_errors else 1
        sleep_for = sleep_seconds * backoff_multiplier

        # Sleep in small intervals so shutdown is responsive
        end_time = time.time() + sleep_for
        while time.time() < end_time and not _shutdown_event.is_set():
            time.sleep(min(5.0, end_time - time.time()))

    logger.info(f"[{bot_id}] Thread exiting (shutdown event set).")
    _update_status(bot_id, status="stopped")


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        with _status_lock:
            payload = {
                "service": "kraken-bot-runner",
                "uptime_seconds": int(time.time() - _start_time),
                "bots": dict(_bot_status),
                "bot_count": len(_bot_status),
            }
        body = json.dumps(payload, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # suppress access logs


_start_time = time.time()


def _start_health_server():
    port = int(os.environ.get("PORT", "8085"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info(f"Runner | Health server listening on :{port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    thread.start()
    return server


def _shutdown_handler(signum, frame):
    logger.info(f"Runner | Received signal {signum}, initiating shutdown...")
    _shutdown_event.set()


def main():
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    logger.info("=" * 60)
    logger.info("KRAKEN-BOT RUNNER — multiplexed strategy host")
    logger.info(f"Bots: {', '.join(b[0] for b in BOTS)}")
    logger.info("=" * 60)

    # Start health server BEFORE bot threads so port binds fast
    _start_health_server()

    # Spawn one thread per bot
    threads = []
    for bot_id, module_name, fn_name in BOTS:
        t = threading.Thread(
            target=_run_bot_loop,
            args=(bot_id, module_name, fn_name),
            daemon=False,
            name=f"bot-{bot_id}"
        )
        t.start()
        threads.append(t)
        _update_status(bot_id, status="starting")
        time.sleep(0.5)  # small stagger to avoid thundering herd on imports

    logger.info(f"Runner | {len(threads)} bot threads started")

    # Main thread waits for shutdown
    try:
        while not _shutdown_event.is_set():
            time.sleep(5)
    except KeyboardInterrupt:
        _shutdown_event.set()

    logger.info("Runner | Shutting down all bot threads...")
    for t in threads:
        t.join(timeout=10)
    logger.info("Runner | All threads stopped. Goodbye.")


if __name__ == "__main__":
    main()
