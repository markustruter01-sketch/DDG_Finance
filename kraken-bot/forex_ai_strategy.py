"""Forex AI cycle: OANDA account monitor, daily AI council, and (Phase 5)
practice-account execution when the bot is unpaused and trading is enabled."""

from __future__ import annotations

import json

import math
from typing import Any, Callable

from loguru import logger

from core.bot_state import write_heartbeat, write_portfolio
from core.oanda_client import OandaClient
from forex_quant_desk import build_signal_sheet
import forex_ledger


BOT_ID = "forex_ai"


def _finite_amount(value: Any, field: str, *, allow_zero: bool = False) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"OANDA {field} is not numeric") from None
    if not math.isfinite(amount) or amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError(f"OANDA {field} must be positive and finite")
    return amount


def _position_sides(positions: list[dict[str, Any]]) -> dict[str, str]:
    sides = {}
    for position in positions:
        long_units = float((position.get("long") or {}).get("units") or 0)
        short_units = float((position.get("short") or {}).get("units") or 0)
        if long_units > 0:
            sides[position.get("instrument")] = "long"
        elif short_units != 0:
            sides[position.get("instrument")] = "short"
    return sides


def run_shadow_council(
    sheet: dict[str, Any],
    positions: list[dict[str, Any]],
    *,
    now: Callable[[], Any] = forex_ledger.utc_now,
    get_conn: Callable[[], Any] | None = None,
    council: Callable[..., dict[str, Any]] | None = None,
    kill_state: Callable[[], dict[str, Any]] | None = None,
) -> str:
    """Phase 4 shadow cycle: once per New York trading day, run the AI council
    and append the full record to the ledger. Never places orders. Returns a
    short status string for the log; never raises."""
    try:
        trading_day = forex_ledger.trading_day_due(now())
        if trading_day is None:
            return "not due"
        if kill_state is None:
            from core.forex_ai_kill import ai_kill_state as kill_state
        killed = kill_state()
        if killed["on"]:
            return f"ai kill switch on: {killed['reason'] or 'no reason given'}"
        if get_conn is None:
            from db.postgres import get_conn as get_conn  # runner puts trading-platform on sys.path
        if council is None:
            from forex_council import run_council as council
        with get_conn() as conn:
            forex_ledger.ensure_ledger(conn)
            if forex_ledger.already_logged(conn, trading_day):
                return f"already logged {trading_day}"
        record = council(sheet["rows"], _position_sides(positions))
        with get_conn() as conn:
            digest = forex_ledger.append_cycle(conn, trading_day, record)
        return f"logged {trading_day} status={record['status']} sha256={digest[:12]}"
    except Exception as exc:  # the council must never stop the account monitor
        return f"failed: {type(exc).__name__}"


def _sync_control_switch() -> str:
    """Pull DDG Control's Forex AI switch into the stored state. Never raises."""
    try:
        from core.forex_ai_kill import sync_from_control
        status = sync_from_control()
    except Exception as exc:
        status = f"failed: {type(exc).__name__}"
    logger.info(f"FOREX AI switch (DDG Control) | {status}")
    return status


_last_scorecard_day = None


def _maybe_log_weekly_scorecard(client_factory: Callable[[], Any], *, now=None, get_conn=None) -> str:
    """Saturdays (New York): score the week's shadow decisions and log one JSON
    line. Read-only. Never raises."""
    global _last_scorecard_day
    try:
        from forex_scorecard import NEW_YORK, run_weekly_scorecard
        from forex_quant_desk import FOREX_PAIRS

        ny = (now or forex_ledger.utc_now()).astimezone(NEW_YORK)
        if ny.weekday() != 5 or _last_scorecard_day == ny.date():
            return "not due"
        _last_scorecard_day = ny.date()
        if get_conn is None:
            from db.postgres import get_conn as get_conn
        with client_factory() as client:
            card = run_weekly_scorecard(client, get_conn, FOREX_PAIRS)
        logger.info(f"FOREX scorecard (weekly) | {json.dumps(card, separators=(',', ':'))}")
        return "logged"
    except Exception as exc:
        logger.warning(f"FOREX scorecard | skipped: {type(exc).__name__}")
        return f"failed: {type(exc).__name__}"


_last_audit_day = None


def _maybe_run_weekly_audit(*, now=None, get_conn=None) -> str:
    """Saturdays (New York): audit the ledger and council code; any finding goes
    to the degradation log (the warning channel). Read-only. Never raises."""
    global _last_audit_day
    try:
        from forex_audit import run_weekly_audit

        ny = (now or forex_ledger.utc_now()).astimezone(forex_ledger.NEW_YORK)
        if ny.weekday() != 5 or _last_audit_day == ny.date():
            return "not due"
        _last_audit_day = ny.date()
        if get_conn is None:
            from db.postgres import get_conn as get_conn
        findings = run_weekly_audit(get_conn)
        if findings:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="forex_council", severity="error", error_type="weekly_audit",
                message=f"Forex council weekly audit: {len(findings)} finding(s)",
                detail="; ".join(findings)[:1500], bot_id="forex_ai",
            )
        logger.info(f"FOREX audit (weekly) | findings={len(findings)}")
        return f"findings={len(findings)}"
    except Exception as exc:
        logger.warning(f"FOREX audit | skipped: {type(exc).__name__}")
        return f"failed: {type(exc).__name__}"


def _maybe_execute(sheet: dict[str, Any], factory: Callable[[], Any], max_gross: float) -> str:
    """Phase 5: carry out the day's decision on the practice account. Only
    called when the runner says this bot may trade (unpaused, published) and
    FOREX_TRADING_ENABLED is on. Never raises."""
    try:
        from core.forex_ai_kill import ai_kill_state
        from core.kill_switch import latch_tripped, read_oanda_account_snapshot
        from core.oanda_trader import OandaTrader
        from db.postgres import get_conn
        from forex_execution import PgForexStore, run_forex_execution

        if latch_tripped():
            return "kill switch tripped: no trading"
        killed = ai_kill_state()
        if killed["on"]:
            return f"ai kill switch on: no trading ({killed['reason'] or 'no reason given'})"
        with factory() as reader, OandaTrader() as trader:
            report = run_forex_execution(
                reader=reader, trader=trader, store=PgForexStore(get_conn),
                snapshot=read_oanda_account_snapshot, sheet_rows=sheet["rows"],
                max_gross=max_gross)
        status = str(report.get("status"))
        if status.startswith("failed") or report.get("errors"):
            from core.degradation_tracker import record_degradation
            critical = status.startswith("failed") or any("CRITICAL" in e for e in report.get("errors", []))
            record_degradation(
                component="forex_execution", severity="critical" if critical else "error",
                error_type="forex_execution", message=f"Forex execution: {status}"[:300],
                detail=json.dumps(report.get("errors") or report, default=str)[:1500], bot_id=BOT_ID)
        return status
    except Exception as exc:
        return f"failed: {type(exc).__name__}"


def run_forex_cycle(
    *,
    profile: dict[str, Any] | None = None,
    db_id: int | None = None,
    client_factory: Callable[[], Any] | None = None,
    trading_allowed: bool = False,
) -> dict[str, Any]:
    """Read USD account NAV and open positions, persist portfolio health, build
    the quant desk's signal sheet, run the once-a-day AI council into the
    append-only ledger (FOREX_COUNCIL_ENABLED), and, only when the runner
    passes trading_allowed (bot unpaused, published runner) AND the profile sets
    FOREX_TRADING_ENABLED, execute the day's decision on the practice account.
    """
    del db_id
    trading = bool(trading_allowed and (profile or {}).get("FOREX_TRADING_ENABLED", False))
    council_enabled = bool((profile or {}).get("FOREX_COUNCIL_ENABLED", False))
    factory = client_factory or OandaClient
    with factory() as client:
        account = client.account_summary()
        if account.get("currency") != "USD":
            raise ValueError(
                f"forex_ai requires a USD OANDA account; got {account.get('currency')!r}"
            )
        equity = _finite_amount(account.get("nav"), "NAV")
        cash = _finite_amount(account.get("balance"), "balance", allow_zero=True)
        positions = client.open_positions()
        if not isinstance(positions, list):
            raise ValueError("OANDA open positions response must be a list")
        try:
            sheet = build_signal_sheet(client)
        except Exception as exc:  # the sheet must never stop the account monitor
            sheet = {"rows": [], "errors": [f"signal sheet failed: {exc}"]}

    write_heartbeat(
        BOT_ID,
        equity=equity,
        cash=cash,
        positions=len(positions),
        status="running" if trading else "paused",
    )
    write_portfolio(BOT_ID, cash=cash, equity=equity, positions=positions)
    for row in sheet["rows"]:
        if "error" in row:
            logger.warning(f"FOREX quant desk | {row['pair']} | no data: {row['error']}")
        else:
            logger.info(
                f"FOREX quant desk | {row['pair']} | baseline={row['baseline']['direction']} "
                f"trend={row['trend']} mom63={row['momentum_return']:+.4f} "
                f"atr%={row['atr_pct']:.4f} carry={row['carry']['status']}"
            )
    for error in sheet["errors"]:
        logger.warning(f"FOREX quant desk | {error}")
    if council_enabled:
        _sync_control_switch()
    council_status = (
        run_shadow_council(sheet, positions) if council_enabled else "disabled"
    )
    if council_enabled:
        logger.info(f"FOREX council | {council_status}")
        _maybe_log_weekly_scorecard(factory)
        _maybe_run_weekly_audit()
    execution_status = "trading off"
    if trading:
        execution_status = _maybe_execute(sheet, factory, float((profile or {}).get("FOREX_MAX_GROSS", 2.0)))
        logger.info(f"FOREX execution | {execution_status}")
    return {
        "bot_id": BOT_ID,
        "currency": "USD",
        "equity_usd": equity,
        "cash_usd": cash,
        "open_positions": len(positions),
        "signal_sheet": sheet,
        "council": council_status,
        "execution": execution_status,
    }