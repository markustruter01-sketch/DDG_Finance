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
import urllib.request
from datetime import date, datetime, timedelta, timezone
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

# Heartbeat and pause helpers — loaded after sys.path is configured so
# core.bot_state resolves clean. touch_heartbeat updates ONLY
# last_heartbeat/status/error — never zeroes equity_usd.
try:
    from core.bot_state import (
        touch_heartbeat as _bs_touch,
        is_paused as _bs_is_paused,
        get_bot_state as _bs_get_state,
    )
    from core.bot_registry import normalise_bot_id as _bs_normalise
    _heartbeat_ok = True
except Exception as _hb_exc:
    logger.warning(f"Runner | Could not import heartbeat helpers: {_hb_exc}")
    _heartbeat_ok = False
    _bs_touch = lambda *a, **k: None  # noqa: E731
    _bs_is_paused = lambda *a, **k: False  # noqa: E731
    _bs_get_state = lambda *a, **k: {}  # noqa: E731
    _bs_normalise = lambda bot_id: bot_id  # noqa: E731

try:
    from core.bot_state import write_portfolio as _bs_write_portfolio
    _portfolio_write_ok = True
except ImportError:
    _bs_write_portfolio = lambda *a, **k: None  # noqa: E731
    _portfolio_write_ok = False

# Bot registry: (canonical_bot_id, leaf_module_name, leaf_function_name).
# Each registered strategy is checked against its profile and canonical DB row
# before any cycle thread is allowed to start.
BOTS = [
    # Consolidated Bot 1: US Core + Asia-Pacific + Emerging Markets.
    # bot2_spy_qqq and jerome_macro remain registered for their future
    # validation runs, but are paused until their accounts are reset.
    ("oracle",        "asia_trend_strategy", "run_asia_cycle"),
    # Bot 3 wiring only: the leaf module remains permanently paused until
    # explicit activation. It owns the same reserved Jerome profile/account
    # but ignores the legacy EM universe and vault symbols.
    ("jerome_macro",  "bot3_hard_assets_strategy", "run_bot3_cycle"),
    ("bot2_spy_qqq",  "bot2_spy_qqq",        "run_bot2_cycle"),
]

FAILURE_ALERT_EVERY = 3
API_LIVENESS_INTERVAL_SECONDS = 60
API_LIVENESS_FAILURE_THRESHOLD = 3
API_LIVENESS_TIMEOUT_SECONDS = 5
API_HEALTH_URL = os.environ.get(
    "TRADING_API_HEALTH_URL",
    "http://127.0.0.1:8000/trading-api/health",
)

# Per-bot status tracker for health endpoint
_bot_status: dict[str, dict] = {}
_status_lock = threading.Lock()
_api_liveness: dict[str, object] = {
    "url": API_HEALTH_URL,
    "status": "starting",
    "consecutive_failures": 0,
    "last_check_at": None,
    "last_success_at": None,
    "last_error": None,
}
_shutdown_event = threading.Event()
_pause_alignment_ok = True

try:
    from core.bot_liveness import write_cycle as _write_cycle_liveness
except Exception as _live_exc:
    logger.critical(f"Runner | liveness layer unavailable: {_live_exc}")
    _write_cycle_liveness = None


def _assert_pause_alignment() -> bool:
    """Require module, profile, and canonical DB pause sources to agree."""
    aligned = True
    for bot_id, module_name, _ in BOTS:
        profile = BOT_PROFILES.get(bot_id, {})
        canonical = _bs_normalise(bot_id) or bot_id
        state = _bs_get_state(canonical) if _heartbeat_ok else {}
        static_paused = bool(profile.get("BOT_PAUSED", False))
        database_paused = state.get("paused") if state else None
        try:
            strategy_module = importlib.import_module(module_name)
            module_paused = getattr(strategy_module, "BOT_PAUSED", None)
        except Exception as exc:
            module_paused = None
            aligned = False
            logger.critical(
                f"Pause alignment module load failed | bot={bot_id} "
                f"module={module_name}: {exc}; runner will fail closed"
            )
        logger.info(
            f"Pause alignment | bot={bot_id} canonical={canonical} "
            f"module={module_paused if module_paused is not None else 'not_defined'} "
            f"profile={static_paused} database={database_paused}"
        )
        module_disagrees = (
            module_paused is not None and bool(module_paused) != static_paused
        )
        if (
            database_paused is None
            or static_paused != bool(database_paused)
            or module_disagrees
        ):
            aligned = False
            logger.critical(
                f"Pause alignment disagreement | bot={bot_id} "
                f"module={module_paused if module_paused is not None else 'not_defined'} "
                f"profile={static_paused} database={database_paused}; "
                "runner will fail closed"
            )
    return aligned


def _entry_window_bounds(profile: dict[str, Any], now: datetime) -> tuple[datetime, datetime] | None:
    """Return today's runner-aligned entry window, or None for ordinary bots."""
    configured_start = profile.get("ENTRY_WINDOW_START_UTC")
    if not configured_start:
        return None

    try:
        hour, minute = configured_start
        duration_minutes = int(profile.get("ENTRY_WINDOW_DURATION_MINUTES", 30))
        start = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        return start, start + timedelta(minutes=duration_minutes)
    except (TypeError, ValueError):
        logger.error(
            f"[{profile.get('display_name', 'unknown')}] Invalid ENTRY_WINDOW_START_UTC "
            f"configuration: {configured_start!r}"
        )
        return None


def _next_window_aligned_cycle(
    profile: dict[str, Any],
    last_window_cycle_date: date | None,
    now: datetime,
) -> datetime | None:
    """
    Return the next deterministic window cycle for a regional profile.

    Ordinary profiles return None and retain their free-running interval. For
    window-aligned profiles, a normal hourly cycle before the window is followed
    by an additional full cycle at the window start. A process that starts during
    the window runs immediately and records that day's window cycle.
    """
    bounds = _entry_window_bounds(profile, now)
    if bounds is None:
        return None

    start, end = bounds
    if last_window_cycle_date == now.date() or now >= end:
        return start + timedelta(days=1)
    if now >= start:
        return now
    return start


def _is_unrecorded_window_cycle(
    profile: dict[str, Any],
    last_window_cycle_date: date | None,
    now: datetime,
) -> bool:
    """Whether this cycle starts inside the configured entry window."""
    bounds = _entry_window_bounds(profile, now)
    return bool(
        bounds
        and last_window_cycle_date != now.date()
        and bounds[0] <= now < bounds[1]
    )


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

    Stage 5 merge (2026-08-11): buck_futures retired; jerome_macro is now the sole
    EM bot on account 6da42513. No account-sharing special cases needed.
    """
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

        canonical = _bs_normalise(bot_id) or bot_id

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


def _record_cycle_liveness(
    bot_id: str,
    cycle_started_at: datetime,
    cycle_ended_at: datetime,
    cycle_count: int,
    status: str,
    *,
    success: bool = False,
    consecutive_failures: int = 0,
    last_error: str | None = None,
) -> None:
    if _write_cycle_liveness is None:
        logger.critical(f"[{bot_id}] liveness write unavailable; durable cycle state is blind")
        return
    _write_cycle_liveness(
        bot_id,
        cycle_start=cycle_started_at,
        cycle_end=cycle_ended_at,
        cycle_count=cycle_count,
        status=status,
        success=success,
        consecutive_failures=consecutive_failures,
        last_error=last_error,
    )


def _probe_trading_api() -> None:
    """Monitor API response health from the independent runner process."""
    consecutive_failures = 0
    alert_sent_for_incident = False

    while not _shutdown_event.is_set():
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            request = urllib.request.Request(
                API_HEALTH_URL,
                headers={"User-Agent": "kraken-bot-runner-api-liveness"},
            )
            with urllib.request.urlopen(
                request,
                timeout=API_LIVENESS_TIMEOUT_SECONDS,
            ) as response:
                body = response.read(4096).decode("utf-8", errors="replace")
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.loads(body)
                if payload.get("status") != "ok":
                    raise RuntimeError(
                        f"health status={payload.get('status', 'missing')}"
                    )

            recovered = consecutive_failures > 0
            consecutive_failures = 0
            with _status_lock:
                _api_liveness.update({
                    "status": "healthy",
                    "consecutive_failures": 0,
                    "last_check_at": checked_at,
                    "last_success_at": checked_at,
                    "last_error": None,
                })
            if recovered:
                logger.warning(
                    f"API LIVENESS RECOVERED | {API_HEALTH_URL} responded HTTP 200"
                )
                alert_sent_for_incident = False
        except Exception as exc:
            consecutive_failures += 1
            with _status_lock:
                _api_liveness.update({
                    "status": "unresponsive",
                    "consecutive_failures": consecutive_failures,
                    "last_check_at": checked_at,
                    "last_error": str(exc)[:300],
                })
            logger.error(
                "API LIVENESS FAILURE | "
                f"consecutive={consecutive_failures}/{API_LIVENESS_FAILURE_THRESHOLD} "
                f"url={API_HEALTH_URL} error={exc}"
            )
            if (
                consecutive_failures >= API_LIVENESS_FAILURE_THRESHOLD
                and not alert_sent_for_incident
            ):
                message = (
                    f"Trading API has failed {consecutive_failures} consecutive "
                    f"health checks. URL: {API_HEALTH_URL}. Latest error: {exc}"
                )
                logger.critical(f"API LIVENESS ALERT | {message}")
                try:
                    from notifications.discord import alert_critical
                    alert_critical(
                        "Trading API unresponsive",
                        message,
                        fields=[
                            {
                                "name": "Consecutive failures",
                                "value": str(consecutive_failures),
                                "inline": True,
                            },
                            {
                                "name": "Probe timeout",
                                "value": f"{API_LIVENESS_TIMEOUT_SECONDS}s",
                                "inline": True,
                            },
                        ],
                    )
                except Exception as alert_exc:
                    logger.error(
                        f"API liveness Discord alert failed: {alert_exc}"
                    )
                alert_sent_for_incident = True

        _shutdown_event.wait(API_LIVENESS_INTERVAL_SECONDS)


def _run_bot_loop(bot_id: str, module_name: str, fn_name: str):
    """Per-bot thread entry point. Loops cycle function with sleep + error handling."""
    logger.info(f"[{bot_id}] Thread starting...")
    if not _pause_alignment_ok:
        logger.critical(f"[{bot_id}] Startup pause alignment failed — refusing to run")
        _update_status(bot_id, status="paused", pause_source="alignment_assertion")
        return

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
    last_window_cycle_date: date | None = None

    while not _shutdown_event.is_set():
        try:
            cycle_count += 1
            cycle_start = time.time()
            cycle_started_at = datetime.now(timezone.utc)
            if _is_unrecorded_window_cycle(profile, last_window_cycle_date, cycle_started_at):
                last_window_cycle_date = cycle_started_at.date()
                logger.info(
                    f"[{bot_id}] Window-aligned entry cycle starting at "
                    f"{cycle_started_at.strftime('%H:%M UTC')}"
                )
            _update_status(bot_id, status="running", cycle_count=cycle_count,
                           last_cycle_start=cycle_started_at.isoformat())

            # Fail closed on either pause source.  The static profile guard is
            # retained for defense in depth, while bots_state lets the
            # platform pause a runner without relying on a legacy alias.
            db_paused = _bs_is_paused(bot_id) if _heartbeat_ok else False
            profile_paused = bool(profile.get("BOT_PAUSED", False))
            if profile_paused or db_paused:
                logger.info(
                    f"[{bot_id}] Paused — "
                    f"profile={profile_paused} database={db_paused}; skipping cycle"
                )
                _update_status(
                    bot_id,
                    status="paused",
                    pause_source="profile" if profile_paused else "database",
                    consecutive_errors=0,
                )
                _record_cycle_liveness(
                    bot_id, cycle_started_at, datetime.now(timezone.utc), cycle_count,
                    "paused", consecutive_failures=0,
                )
                if _heartbeat_ok:
                    try:
                        _bs_touch(
                            _bs_normalise(bot_id) or bot_id,
                            status="paused",
                            error="",
                        )
                    except Exception as _hb_e:
                        logger.debug(f"[{bot_id}] paused heartbeat write failed (non-fatal): {_hb_e}")
            else:
                cycle_fn(profile=profile, db_id=db_id)

                cycle_duration = time.time() - cycle_start
                _update_status(bot_id, status="running",
                               last_cycle_duration_seconds=round(cycle_duration, 2),
                               last_cycle_end=datetime.now(timezone.utc).isoformat(),
                               error=None, consecutive_errors=0)
                consecutive_errors = 0
                _record_cycle_liveness(
                    bot_id, cycle_started_at, datetime.now(timezone.utc), cycle_count,
                    "success", success=True,
                )

                if _heartbeat_ok:
                    try:
                        _bs_touch(_bs_normalise(bot_id) or bot_id, status="running", error="")
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
            _record_cycle_liveness(
                bot_id,
                cycle_started_at if "cycle_started_at" in locals() else datetime.now(timezone.utc),
                datetime.now(timezone.utc),
                cycle_count,
                "error",
                consecutive_failures=consecutive_errors,
                last_error=str(exc),
            )
            if consecutive_errors >= FAILURE_ALERT_EVERY and consecutive_errors % FAILURE_ALERT_EVERY == 0:
                failure_message = (
                    f"{bot_id} has failed {consecutive_errors} consecutive cycles. "
                    f"Latest error: {exc}"
                )
                logger.critical(f"RUNNER DEGRADATION ALERT | {failure_message}")
                try:
                    from notifications.discord import alert_critical
                    alert_critical(
                        f"Bot degradation: {bot_id}",
                        failure_message,
                        fields=[
                            {"name": "Bot", "value": bot_id, "inline": True},
                            {"name": "Consecutive failures", "value": str(consecutive_errors), "inline": True},
                        ],
                    )
                except Exception as alert_exc:
                    logger.error(f"[{bot_id}] Discord degradation alert failed: {alert_exc}")
                try:
                    from core.degradation_tracker import record_exception
                    record_exception(
                        component="platform_core",
                        severity="critical",
                        error_type="bot_cycle_failure",
                        message=f"{bot_id} consecutive cycle failures={consecutive_errors}",
                        exc=exc,
                        bot_id=bot_id,
                        cycle_id=f"{bot_id}:{cycle_count}",
                    )
                except Exception as degradation_exc:
                    logger.error(f"[{bot_id}] degradation record failed: {degradation_exc}")
            if _heartbeat_ok:
                try:
                    _bs_touch(_bs_normalise(bot_id) or bot_id, status="error", error=str(exc)[:200])
                except Exception:
                    pass

        # Exponential backoff on repeated errors (capped at 8x sleep)
        backoff_multiplier = min(2 ** min(consecutive_errors, 3), 8) if consecutive_errors else 1
        sleep_for = sleep_seconds * backoff_multiplier
        now = datetime.now(timezone.utc)
        next_window_cycle = _next_window_aligned_cycle(profile, last_window_cycle_date, now)
        if next_window_cycle is not None:
            seconds_until_window_cycle = max(0.0, (next_window_cycle - now).total_seconds())
            if seconds_until_window_cycle < sleep_for:
                sleep_for = seconds_until_window_cycle
                logger.info(
                    f"[{bot_id}] Next cycle aligned to entry window at "
                    f"{next_window_cycle.strftime('%Y-%m-%d %H:%M UTC')} "
                    f"(in {sleep_for:.0f}s)"
                )

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
                "trading_api_liveness": dict(_api_liveness),
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
    global _pause_alignment_ok
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    logger.info("=" * 60)
    logger.info("KRAKEN-BOT RUNNER — multiplexed strategy host")
    logger.info(f"Bots: {', '.join(b[0] for b in BOTS)}")
    logger.info("=" * 60)
    _pause_alignment_ok = _assert_pause_alignment()
    logger.info(f"Pause alignment assertion: {'PASS' if _pause_alignment_ok else 'FAIL — fail closed'}")

    # Start health server BEFORE bot threads so port binds fast
    _start_health_server()
    threading.Thread(
        target=_probe_trading_api,
        daemon=True,
        name="trading-api-liveness",
    ).start()
    logger.info(
        "Runner | Trading API liveness probe started "
        f"(interval={API_LIVENESS_INTERVAL_SECONDS}s, "
        f"timeout={API_LIVENESS_TIMEOUT_SECONDS}s, "
        f"threshold={API_LIVENESS_FAILURE_THRESHOLD}, url={API_HEALTH_URL})"
    )

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
