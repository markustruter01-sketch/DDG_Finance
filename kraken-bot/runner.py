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

# PROPOSED supervisor contract. Replit's documented automatic restart does not
# currently expose exit-code filtering, but these codes make the distinction
# explicit for any future supported supervisor.
EXIT_SUCCESS = 0
EXIT_CRASH = 70       # unexpected process failure / startup infrastructure failure
EXIT_REFUSAL = 78     # deliberate fail-closed refusal (leases or pause alignment)

# Proposed value: retry a published-to-published lease handoff every 15 seconds.
LEASE_WAIT_RETRY_SECONDS = 15
# Proposed value: alert once after waiting longer than ten minutes for leases.
LEASE_WAIT_ALERT_SECONDS = 600

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
try:
    _cfg_spec.loader.exec_module(_cfg_mod)
except Exception as exc:
    logger.critical(f"Runner | configuration import failed: {exc}")
    raise SystemExit(EXIT_CRASH) from exc
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
    _bs_is_paused = lambda *a, **k: True  # noqa: E731  # fail closed: no pause read, no trading
    _bs_get_state = lambda *a, **k: {}  # noqa: E731
    _bs_normalise = lambda bot_id: bot_id  # noqa: E731

try:
    from core.bot_state import write_portfolio as _bs_write_portfolio
    _portfolio_write_ok = True
except ImportError:
    _bs_write_portfolio = lambda *a, **k: None  # noqa: E731
    _portfolio_write_ok = False

try:
    from core.runner_lock import (
        claim_lock as _claim_runner_lock,
        ensure_lock_table as _ensure_runner_lock_table,
        list_locks as _list_runner_locks,
        make_owner_token as _make_runner_owner_token,
        refresh_lock as _refresh_runner_lock,
        release_locks as _release_runner_locks,
    )
    _runner_lock_import_ok = True
except Exception as _lock_exc:
    logger.critical(f"Runner | ownership lock unavailable: {_lock_exc}")
    _runner_lock_import_ok = False
    _claim_runner_lock = None
    _ensure_runner_lock_table = None
    _list_runner_locks = None
    _make_runner_owner_token = None
    _refresh_runner_lock = None
    _release_runner_locks = None

# Map registered identities to leaf strategies; the registry controls which
# non-retired bots receive a runner lease and cycle-health record.
from core.bot_registry import active_bot_ids as _registry_active_bot_ids

_BOT_RUNNERS = {
    "oracle": ("asia_trend_strategy", "run_asia_cycle"),
    "jerome_macro": ("bullion_strategy", "run_bullion_cycle"),   # FLEET-V1-C1 since 3 Nov 2026
    "spy_qqq_trend": ("momo_strategy", "run_momo_account_cycle"),       # MOMO-V2 (forward-only experiment)
    "forex_ai": ("forex_ai_strategy", "run_forex_cycle"),
}
_registered_ids = _registry_active_bot_ids()
_unregistered_ids = set(_registered_ids) - set(_BOT_RUNNERS)
if _unregistered_ids:
    raise RuntimeError(
        f"Runner has no leaf strategy for registered bots: {sorted(_unregistered_ids)}"
    )
BOTS = [
    (bot_id, *_BOT_RUNNERS[bot_id])
    for bot_id in _BOT_RUNNERS
    if bot_id in _registered_ids
]

RUNNER_ENVIRONMENT = os.environ.get(
    "RUNNER_ENVIRONMENT",
    "published" if os.environ.get("REPLIT_DEPLOYMENT") == "1" else "dev",
)
RUNNER_EXECUTION_MODE = os.environ.get("RUNNER_EXECUTION_MODE", "read_only").lower()
if RUNNER_EXECUTION_MODE not in {"live", "read_only"}:
    logger.critical(
        f"Runner | invalid RUNNER_EXECUTION_MODE={RUNNER_EXECUTION_MODE!r}; "
        "failing closed as read_only"
    )
    RUNNER_EXECUTION_MODE = "read_only"
_runner_can_trade = RUNNER_EXECUTION_MODE == "live"
_runner_lock_ready = False
_owned_lock_bot_ids: set[str] = set()
_runner_lock_failure_reason: str | None = None
_runner_lock_failure_detail: dict[str, Any] | None = None
# PID values can be reused during a deployment handoff. The token carries the
# kernel process identity and a unique nonce, so the lease can distinguish a
# reused PID from the original runner instance.
RUNNER_OWNER_TOKEN = (
    _make_runner_owner_token(os.getpid())
    if _make_runner_owner_token is not None
    else f"unavailable:{os.getpid()}"
)

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
_pause_state_ok = True


def _canonical_lock_bot_id(bot_id: str) -> str:
    try:
        return _bs_normalise(bot_id) or bot_id
    except Exception:
        return bot_id


def _profile_for_bot(bot_id: str) -> dict[str, Any]:
    """Resolve the legacy profile key while the runner uses canonical IDs."""
    profile = BOT_PROFILES.get(bot_id)
    if profile is not None:
        return profile
    if _canonical_lock_bot_id(bot_id) == "spy_qqq_trend":
        return BOT_PROFILES.get("bot2_spy_qqq", {})
    return {}


def _lock_interval_seconds(bot_id: str) -> float:
    profile = _profile_for_bot(bot_id)
    return max(60.0, float(profile.get("LOOP_SLEEP_SECONDS", 3600)))


def _log_runner_locks(prefix: str) -> None:
    if not _runner_lock_import_ok or _list_runner_locks is None:
        logger.critical(f"Runner lock | {prefix} | lock module unavailable")
        return
    incoming_pid = os.getpid()
    try:
        locks = _list_runner_locks()
        if not locks:
            logger.info(
                f"Runner lock | {prefix} | incoming_pid={incoming_pid} "
                "no lock rows"
            )
        for lock in locks:
            logger.info(
                f"Runner lock | {prefix} | bot={lock['bot_id']} "
                f"environment={lock['environment']} "
                f"incoming_pid={incoming_pid} holder_pid={lock['pid']} "
                f"heartbeat={lock['heartbeat_at']} "
                f"owner_token={lock.get('owner_token', 'unknown')}"
            )
    except Exception as exc:
        logger.critical(f"Runner lock | {prefix} | could not read locks: {exc}")


def _lease_row_with_age(row: dict[str, Any]) -> dict[str, Any]:
    """Return the alert-safe lease fields, including age at read time."""
    heartbeat_at = row.get("heartbeat_at")
    heartbeat_age_seconds: float | None = None
    if heartbeat_at:
        try:
            parsed = (
                heartbeat_at
                if isinstance(heartbeat_at, datetime)
                else datetime.fromisoformat(str(heartbeat_at).replace("Z", "+00:00"))
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            heartbeat_age_seconds = max(
                0.0,
                round((datetime.now(timezone.utc) - parsed).total_seconds(), 3),
            )
        except (TypeError, ValueError):
            heartbeat_age_seconds = None
    return {
        "bot_id": row.get("bot_id"),
        "environment": row.get("environment"),
        "pid": row.get("pid"),
        "owner_token": row.get("owner_token"),
        "heartbeat_at": heartbeat_at,
        "heartbeat_age_seconds": heartbeat_age_seconds,
    }


def _lease_refusal_evidence() -> tuple[list[dict[str, Any]], str | None]:
    """Read lease evidence without ever turning an unavailable read into []."""
    detail = _runner_lock_failure_detail or {}
    claim_result = detail.get("claim_result") or {}
    claim_holder = claim_result.get("lock")

    try:
        if not _runner_lock_import_ok or _list_runner_locks is None:
            raise RuntimeError("lock listing is unavailable")
        listed_rows = _list_runner_locks()
    except Exception as exc:
        if isinstance(claim_holder, dict):
            return [_lease_row_with_age(claim_holder)], (
                f"whole-table lease read failed ({exc}); using the failed claim result"
            )
        return [], f"lease listing failed: {exc}"

    valid_rows = [
        _lease_row_with_age(row)
        for row in listed_rows
        if isinstance(row, dict)
    ]
    if valid_rows:
        return valid_rows, None
    if listed_rows:
        return [], (
            "lease listing returned rows in an unexpected format; no usable lease "
            "row could be read"
        )

    if isinstance(claim_holder, dict):
        return [_lease_row_with_age(claim_holder)], (
            "whole-table lease read returned no rows; using the failed claim result "
            "because it contains the refusing claim's holder"
        )

    return [], (
        "whole-table lease read returned no rows and the claim result contained no "
        "holder row; the lease was released or the refusal was not an occupied lease"
    )


def _prepare_runner_locks() -> bool:
    """Claim all live bot leases before any strategy thread can trade."""
    global _runner_lock_ready, _runner_lock_failure_reason, _runner_lock_failure_detail
    _runner_lock_ready = False
    _runner_lock_failure_reason = None
    _runner_lock_failure_detail = None

    if not _runner_lock_import_ok or _ensure_runner_lock_table is None:
        _runner_lock_failure_reason = "lock module unavailable"
        _runner_lock_failure_detail = {
            "cause": "lock_module_unavailable",
            "claim_result": None,
        }
        logger.critical("Runner lock | fail closed: lock module unavailable")
        return False
    try:
        table_ready = _ensure_runner_lock_table()
    except Exception as exc:
        _runner_lock_failure_reason = f"table bootstrap failed: {exc}"
        _runner_lock_failure_detail = {
            "cause": "table_bootstrap_failed",
            "error": str(exc),
            "claim_result": None,
        }
        logger.critical(f"Runner lock | fail closed: table bootstrap failed: {exc}")
        return False
    if not table_ready:
        _runner_lock_failure_reason = "PostgreSQL unavailable"
        _runner_lock_failure_detail = {
            "cause": "postgresql_unavailable",
            "claim_result": None,
        }
        logger.critical("Runner lock | fail closed: PostgreSQL unavailable")
        return False

    _log_runner_locks("before-claim")
    if not _runner_can_trade:
        logger.warning(
            f"Runner | execution mode={RUNNER_EXECUTION_MODE}; "
            "this process is read-only and will not claim trading leases"
        )
        return True

    claimed: list[str] = []
    try:
        for bot_id, _module_name, _fn_name in BOTS:
            lock_bot_id = _canonical_lock_bot_id(bot_id)
            result = _claim_runner_lock(
                lock_bot_id,
                RUNNER_ENVIRONMENT,
                os.getpid(),
                3 * _lock_interval_seconds(bot_id),
                owner_token=RUNNER_OWNER_TOKEN,
            )
            if not result.get("owned"):
                holder = result.get("lock") or {}
                _runner_lock_failure_detail = {
                    "cause": "occupied_lease" if holder else "claim_refused_without_holder",
                    "bot_id": lock_bot_id,
                    "claim_result": result,
                }
                _runner_lock_failure_reason = (
                    f"claim returned owned={result.get('owned')!r} for {lock_bot_id}; "
                    f"refusal_cause={_runner_lock_failure_detail['cause']}"
                )
                logger.critical(
                    f"Runner lock | REFUSED | bot={lock_bot_id} "
                    f"holder_environment={holder.get('environment', 'unknown')} "
                    f"holder_pid={holder.get('pid', 'unknown')} "
                    f"holder_heartbeat={holder.get('heartbeat_at', 'unknown')} "
                    f"holder_owner_token={holder.get('owner_token', 'unknown')}"
                )
                if _release_runner_locks is not None and claimed:
                    _release_runner_locks(
                        RUNNER_ENVIRONMENT,
                        os.getpid(),
                        owner_token=RUNNER_OWNER_TOKEN,
                    )
                _owned_lock_bot_ids.clear()
                return False
            claimed.append(lock_bot_id)
            _owned_lock_bot_ids.add(lock_bot_id)
            lock = result.get("lock") or {}
            logger.info(
                f"Runner lock | CLAIMED | bot={lock_bot_id} "
                f"environment={lock.get('environment')} pid={lock.get('pid')} "
                f"heartbeat={lock.get('heartbeat_at')} "
                f"owner_token={lock.get('owner_token', 'unknown')}"
            )
        _runner_lock_ready = True
        _log_runner_locks("after-claim")
        return True
    except Exception as exc:
        _runner_lock_failure_reason = f"claim failed: {exc}"
        _runner_lock_failure_detail = {
            "cause": "claim_exception",
            "error": str(exc),
            "claim_result": None,
        }
        logger.critical(f"Runner lock | fail closed during claim: {exc}")
        if _release_runner_locks is not None and claimed:
            try:
                _release_runner_locks(
                    RUNNER_ENVIRONMENT,
                    os.getpid(),
                    owner_token=RUNNER_OWNER_TOKEN,
                )
            except Exception as release_exc:
                _runner_lock_failure_reason = (
                    f"claim failed: {exc}; release failed: {release_exc}"
                )
                logger.critical(f"Runner lock | release after failed claim failed: {release_exc}")
        _owned_lock_bot_ids.clear()
        return False


def _refresh_bot_lock(bot_id: str) -> bool:
    if not _runner_can_trade:
        return True
    if not _runner_lock_ready or _refresh_runner_lock is None:
        logger.critical(f"[{bot_id}] Runner lock not ready — refusing to trade")
        return False
    lock_bot_id = _canonical_lock_bot_id(bot_id)
    try:
        owned = _refresh_runner_lock(
            lock_bot_id,
            RUNNER_ENVIRONMENT,
            os.getpid(),
            owner_token=RUNNER_OWNER_TOKEN,
        )
    except Exception as exc:
        logger.critical(f"[{bot_id}] Runner lock heartbeat failed: {exc}")
        return False
    if not owned:
        logger.critical(
            f"[{bot_id}] Runner lock ownership lost — refusing further trading"
        )
    return owned

try:
    from core.bot_liveness import write_cycle as _write_cycle_liveness
except Exception as _live_exc:
    logger.critical(f"Runner | liveness layer unavailable: {_live_exc}")
    _write_cycle_liveness = None

try:
    from core.runner_heartbeat import (
        RUNNER_LOOP_INTERVAL_SECONDS as _RUNNER_LOOP_INTERVAL_SECONDS,
        write_runner_heartbeat as _write_runner_heartbeat,
    )
    _runner_heartbeat_import_ok = True
except Exception as _runner_hb_exc:
    logger.critical(f"Runner | process heartbeat layer unavailable: {_runner_hb_exc}")
    _runner_heartbeat_import_ok = False
    _RUNNER_LOOP_INTERVAL_SECONDS = 5.0
    _write_runner_heartbeat = None

_runner_started_at = datetime.now(timezone.utc)


def _record_runner_heartbeat(loop_count: int, status: str) -> bool:
    """Attempt a durable process heartbeat without altering bot execution."""
    if not _runner_heartbeat_import_ok or _write_runner_heartbeat is None:
        logger.critical("Runner heartbeat | unavailable; durable aliveness is not established")
        return False
    return _write_runner_heartbeat(
        instance_token=RUNNER_OWNER_TOKEN,
        pid=os.getpid(),
        environment=RUNNER_ENVIRONMENT,
        execution_mode=RUNNER_EXECUTION_MODE,
        started_at=_runner_started_at,
        loop_count=loop_count,
        bots_registered=len(BOTS),
        status=status,
    )


def _assert_pause_state_readable() -> bool:
    """bots_state.paused is the only pause switch. Refuse to start unless every
    bot's row exists and can be read (a missing row would leave that bot
    permanently paused, which is safe but almost certainly a setup error)."""
    if not _heartbeat_ok:
        logger.critical("Pause state | bot_state helpers unavailable; runner will fail closed")
        return False
    readable = True
    for bot_id, _module_name, _ in BOTS:
        canonical = _bs_normalise(bot_id) or bot_id
        try:
            state = _bs_get_state(canonical)
        except Exception as exc:
            state = {}
            logger.critical(f"Pause state | read failed bot={bot_id}: {exc}")
        paused = state.get("paused") if state else None
        logger.info(f"Pause state | bot={bot_id} canonical={canonical} paused={paused}")
        if paused is None:
            readable = False
            logger.critical(
                f"Pause state | bot={bot_id} has no readable bots_state row; runner will fail closed"
            )
    return readable


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
    canonical = _bs_normalise(bot_id) or bot_id
    account_read_ok = False
    positions_read_ok = False
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
        account_read_ok = True
        posns = api.list_positions()
        positions_read_ok = True

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
            positions_read_ok=True,
            account_read_ok=True,
        )
        logger.debug(f"[{bot_id}] bot_portfolio write OK — equity={acct.equity}")
        return True
    except Exception as exc:
        if not positions_read_ok:
            try:
                from core.bot_state import sync_cash_asset_ledger
                sync_cash_asset_ledger(
                    canonical,
                    None,
                    positions_read_ok=False,
                    account_read_ok=account_read_ok,
                )
            except Exception:
                pass
        logger.debug(f"[{bot_id}] portfolio write failed (non-fatal): {exc}")
        return False


def _refresh_paused_portfolio(bot_id: str, profile: dict) -> None:
    """Refresh live portfolio state without affecting cycle health on failure."""
    if bot_id == "forex_ai":
        # The Forex cycle is read-only and is the only valid OANDA portfolio
        # refresh path; do not send it through the Alpaca portfolio helper.
        module = importlib.import_module("forex_ai_strategy")
        module.run_forex_cycle(profile=profile, db_id=profile.get("db_id"))
        return
    try:
        if not _write_portfolio_from_alpaca(bot_id, profile):
            logger.error(
                f"[{bot_id}] paused portfolio refresh failed — "
                "writer returned False"
            )
    except Exception as portfolio_exc:
        logger.error(
            f"[{bot_id}] paused portfolio refresh raised an error: "
            f"{portfolio_exc}"
        )


def _maintain_stops_while_paused(bot_id: str, profile: dict) -> None:
    """A paused bot still keeps every holding under its protective stop.

    Pausing (by the owner or the kill switch) stops entries and exits, not
    protection. On 9 Nov 2026 Atlas lost its SPY/QQQ stops mid-rebalance, the
    kill switch paused every bot, and because a paused bot never ran its
    cycle nothing put the stops back for 6+ hours. This places or repairs
    protective stops only (engine.reconcile_protective_stops); it never buys,
    sells or cancels anything else. Failures are logged and alerted by the
    engine and never break the paused loop."""
    try:
        from alpaca_etf_engine import AlpacaEtfEngine

        api_key = profile.get("ALPACA_API_KEY", "")
        secret_key = profile.get("ALPACA_SECRET_KEY", "")
        if not api_key or not secret_key:
            logger.warning(f"[{bot_id}] paused stop check skipped — no Alpaca credentials in profile")
            return
        engine = AlpacaEtfEngine(
            api_key=api_key,
            secret_key=secret_key,
            base_url=profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
        # Same id the bot's own cycle uses for its ledger rows (oracle, jerome_macro, spy_qqq_trend).
        engine.reconcile_protective_stops(bot_id, engine.get_db_positions(bot_id))
        logger.info(f"[{bot_id}] paused — protective stops checked")
    except Exception as exc:
        logger.error(f"[{bot_id}] paused stop check failed: {exc!r}")


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
    if _runner_can_trade and _canonical_lock_bot_id(bot_id) not in _owned_lock_bot_ids:
        logger.critical(f"[{bot_id}] Runner lock refused — strategy thread will not trade")
        _update_status(bot_id, status="lock_refused", error="runner_lock_not_owned")
        return
    if not _pause_state_ok:
        logger.critical(f"[{bot_id}] Startup pause-state check failed — refusing to run")
        _update_status(bot_id, status="paused", pause_source="pause_state_check")
        return

    # Lazy load the bot profile — BOT_PROFILES loaded at module level via importlib
    profile = _profile_for_bot(bot_id)
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

            if not _refresh_bot_lock(bot_id):
                _update_status(bot_id, status="lock_lost", error="runner_lock_lost")
                return

            # bots_state.paused is the only pause switch; is_paused fails
            # closed (unreadable or missing row = paused).
            db_paused = _bs_is_paused(bot_id)
            if not _runner_can_trade:
                logger.info(
                    f"[{bot_id}] Read-only runner — skipping strategy cycle"
                )
                _update_status(
                    bot_id,
                    status="read_only",
                    consecutive_errors=0,
                    error=None,
                )
                if bot_id == "forex_ai":
                    # This strategy only reads account summary/open positions;
                    # refresh its USD NAV while keeping all trading disabled.
                    cycle_fn(profile=profile, db_id=db_id)
                    _record_cycle_liveness(
                        bot_id,
                        cycle_started_at,
                        datetime.now(timezone.utc),
                        cycle_count,
                        "read_only",
                        success=True,
                    )
            elif db_paused:
                logger.info(f"[{bot_id}] Paused (bots_state) — skipping cycle")
                pause_source = "database"
                if bot_id == "forex_ai":
                    monitor_error = None
                    try:
                        _refresh_paused_portfolio(bot_id, profile)
                    except Exception as exc:
                        consecutive_errors += 1
                        monitor_error = str(exc)
                        logger.error(
                            f"[{bot_id}] paused monitor refresh failed "
                            f"(consecutive={consecutive_errors}): {exc}"
                        )
                    else:
                        consecutive_errors = 0
                    _update_status(
                        bot_id,
                        status="paused",
                        pause_source=pause_source,
                        consecutive_errors=consecutive_errors,
                        error=monitor_error,
                    )
                    _record_cycle_liveness(
                        bot_id,
                        cycle_started_at,
                        datetime.now(timezone.utc),
                        cycle_count,
                        "paused",
                        success=monitor_error is None,
                        consecutive_failures=consecutive_errors,
                        last_error=monitor_error,
                    )
                else:
                    _update_status(
                        bot_id,
                        status="paused",
                        pause_source=pause_source,
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
                if bot_id != "forex_ai":
                    _refresh_paused_portfolio(bot_id, profile)
                    _maintain_stops_while_paused(bot_id, profile)
            else:
                if bot_id == "forex_ai":
                    # Unpaused on the published runner: the only path where
                    # Forex may place practice orders (FOREX_TRADING_ENABLED).
                    cycle_fn(profile=profile, db_id=db_id, trading_allowed=True)
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

            if not _refresh_bot_lock(bot_id):
                _update_status(bot_id, status="lock_lost", error="runner_lock_lost")
                return

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
            if _runner_can_trade and not _refresh_bot_lock(bot_id):
                _update_status(bot_id, status="lock_lost", error="runner_lock_lost")
                return

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
                "environment": RUNNER_ENVIRONMENT,
                "execution_mode": RUNNER_EXECUTION_MODE,
                "lock_ready": _runner_lock_ready,
                "owned_lock_bot_ids": sorted(_owned_lock_bot_ids),
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


def _release_owned_runner_locks() -> None:
    """Release only this runner instance's leases, without masking shutdown."""
    if not _runner_lock_ready or _release_runner_locks is None:
        return
    try:
        released = _release_runner_locks(
            RUNNER_ENVIRONMENT,
            os.getpid(),
            owner_token=RUNNER_OWNER_TOKEN,
        )
        _owned_lock_bot_ids.clear()
        logger.info(
            f"Runner lock | released={released} environment={RUNNER_ENVIRONMENT}"
        )
    except Exception as exc:
        logger.critical(f"Runner lock | release failed: {exc}")


def _send_lease_refusal_alert(
    reason: str,
    lease_rows: list[dict[str, Any]],
    lease_evidence: str,
) -> None:
    """Send the existing published-only lease refusal alert."""
    if str(RUNNER_ENVIRONMENT).lower() == "published":
        try:
            from notifications.discord import alert_critical

            if lease_rows:
                alert_fields = [
                    {
                        "name": f"Lease row {index}",
                        "value": json.dumps(row, default=str),
                    }
                    for index, row in enumerate(lease_rows, start=1)
                ]
            else:
                alert_fields = [
                    {
                        "name": "Lease evidence",
                        "value": lease_evidence,
                    }
                ]
            alert_critical(
                "Runner startup blocked by lease refusal",
                "Live runner refused to start because the lease claim returned "
                f"owned=False. Reason: {reason}",
                fields=alert_fields,
            )
        except Exception as exc:
            logger.critical(
                f"Runner | failed to send lease-refusal alert: {type(exc).__name__}"
            )
    else:
        logger.critical(
            "Runner | lease-refusal Discord alert suppressed; "
            f"environment={RUNNER_ENVIRONMENT}; reason={reason}; "
            f"lease_evidence={lease_evidence}"
        )


def main() -> int:
    global _pause_state_ok
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    threads = []
    exit_code = EXIT_SUCCESS
    health_server_started = False
    runner_loop_count = 0

    def start_health_server_once() -> None:
        nonlocal health_server_started
        if not health_server_started:
            _start_health_server()
            health_server_started = True

    try:
        if not _record_runner_heartbeat(runner_loop_count, "starting"):
            logger.critical(
                "Runner heartbeat | startup write failed; "
                "continuing without presenting process aliveness as healthy"
            )

        locks_ready = _prepare_runner_locks()
        if _runner_can_trade and not locks_ready:
            reason = _runner_lock_failure_reason
            if reason is None:
                reason = "unknown lease preparation failure"
            detail = _runner_lock_failure_detail or {}
            initial_claim_result = detail.get("claim_result")
            if not isinstance(initial_claim_result, dict):
                initial_claim_result = {}
            initial_holder = initial_claim_result.get("lock")
            wait_for_published_holder = (
                RUNNER_ENVIRONMENT == "published"
                and detail.get("cause") == "occupied_lease"
                and isinstance(initial_holder, dict)
                and initial_holder.get("environment") == "published"
            )

            if wait_for_published_holder:
                start_health_server_once()
                lease_wait_started_at = time.monotonic()
                lease_wait_alert_sent = False
                retry_exception: Exception | None = None

                while not locks_ready and not _shutdown_event.is_set():
                    if not _record_runner_heartbeat(
                        runner_loop_count, "awaiting_leases"
                    ):
                        logger.critical(
                            "Runner heartbeat | awaiting_leases write failed"
                        )

                    latest_detail = _runner_lock_failure_detail or {}
                    latest_result = latest_detail.get("claim_result")
                    if not isinstance(latest_result, dict):
                        latest_result = {}
                    if retry_exception is not None:
                        logger.critical(
                            "Runner | lease retry raised; continuing to wait; "
                            f"error={type(retry_exception).__name__}: {retry_exception}; "
                            f"cause={latest_detail.get('cause')}; "
                            f"claim_result={json.dumps(latest_result, default=str)}; "
                            f"decision={latest_result.get('decision', 'unknown')}"
                        )
                        retry_exception = None
                    else:
                        logger.warning(
                            "Runner | awaiting published leases; "
                            f"reason={_runner_lock_failure_reason}; "
                            f"cause={latest_detail.get('cause')}; "
                            f"claim_result={json.dumps(latest_result, default=str)}; "
                            f"decision={latest_result.get('decision', 'unknown')}"
                        )

                    shutdown_requested = _shutdown_event.wait(
                        LEASE_WAIT_RETRY_SECONDS
                    )
                    waited_seconds = time.monotonic() - lease_wait_started_at
                    if (
                        not lease_wait_alert_sent
                        and waited_seconds > LEASE_WAIT_ALERT_SECONDS
                    ):
                        if isinstance(initial_holder, dict):
                            alert_rows = [_lease_row_with_age(initial_holder)]
                            alert_evidence = json.dumps(alert_rows, default=str)
                        else:
                            alert_rows, alert_note = _lease_refusal_evidence()
                            alert_evidence = (
                                json.dumps(alert_rows, default=str)
                                if alert_rows
                                else f"lease rows unreadable: {alert_note}"
                            )
                        _send_lease_refusal_alert(
                            reason,
                            alert_rows,
                            alert_evidence,
                        )
                        lease_wait_alert_sent = True

                    if shutdown_requested or _shutdown_event.is_set():
                        break

                    try:
                        locks_ready = _prepare_runner_locks()
                    except Exception as exc:
                        locks_ready = False
                        retry_exception = exc

                if _shutdown_event.is_set():
                    logger.info(
                        "Runner | shutdown requested while awaiting published leases"
                    )
                    return EXIT_SUCCESS

            if not locks_ready:
                lease_rows, lease_read_note = _lease_refusal_evidence()
                if lease_rows:
                    lease_evidence = json.dumps(lease_rows, default=str)
                else:
                    lease_evidence = f"lease rows unreadable: {lease_read_note}"
                logger.critical(
                    "Runner | LIVE STARTUP ABORTED — lease preparation failed; "
                    f"reason={reason}; lease_evidence={lease_evidence}"
                )
                _send_lease_refusal_alert(reason, lease_rows, lease_evidence)

                exit_code = EXIT_REFUSAL
                return exit_code

        logger.info("=" * 60)
        logger.info("KRAKEN-BOT RUNNER — multiplexed strategy host")
        logger.info(f"Bots: {', '.join(b[0] for b in BOTS)}")
        logger.info("=" * 60)
        _pause_state_ok = _assert_pause_state_readable()
        logger.info(f"Pause state check: {'PASS' if _pause_state_ok else 'FAIL — fail closed'}")
        if not _pause_state_ok:
            logger.critical(
                "Runner | pause state unreadable; refusing to start bot threads"
            )
            exit_code = EXIT_REFUSAL
            return exit_code

        # Start the health server after successful startup checks, unless it was
        # already started to serve a published runner waiting for leases.
        start_health_server_once()
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
        while not _shutdown_event.is_set():
            runner_loop_count += 1
            if not _record_runner_heartbeat(runner_loop_count, "running"):
                logger.critical(
                    f"Runner heartbeat | loop write failed at loop_count={runner_loop_count}"
                )
            _shutdown_event.wait(_RUNNER_LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        _shutdown_event.set()
    except Exception as exc:
        logger.exception(f"Runner | uncaught process failure: {exc}")
        exit_code = EXIT_CRASH
    finally:
        _shutdown_event.set()
        logger.info("Runner | Shutting down all bot threads...")
        for t in threads:
            t.join(timeout=10)
        _release_owned_runner_locks()
    logger.info("Runner | All threads stopped. Goodbye.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
