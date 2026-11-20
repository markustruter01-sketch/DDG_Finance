"""Shadow League, nightly (roadmap Phase 1). No orders, ever.

Each registered strategy in research_harness/league/families.py gets a
pretend account in the twins tables (bot_id "league"). Each night, after the
US close, this module asks every strategy what it would hold on each session
since its last decision and appends that to the twin's hash-chained decision
log. The twins nightly job then replays every account, shadows included,
through the same engine, costs and stops as the mirror twins.

Version 0 is the PROVING run (from the first night this is published): it
shows that all lines produce a value every night. It is not the record. The
lock weekend starts version 1 (bump LEAGUE_VERSION once, after Markus's yes).

A strategy with no registration file does not start. The registration's
hash is stored on the account, so a later edit to the file is visible.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from research_harness.harness.portfolio import HistoryView
from research_harness.harness.registry import registration_hash
from research_harness.league import base, families
from twins import engine, store
from twins.config import DAILY

LEAGUE_BOT = "league"
LEAGUE_VERSION = 0                     # 0 = proving run; 1 starts at the lock (Markus's yes)
START_EQUITY = 100_000.0
REG_DIR = Path(__file__).resolve().parents[2] / "research_harness" / "registrations" / "league"
HISTORY_CALENDAR_DAYS = 600            # covers 380 sessions of warm-up (momentum's 12-1 + its brake)
CATCH_UP_SESSIONS = 15                 # a longer outage is reported; older sessions are not re-asked
UNIVERSE_TIMEOUT_SECONDS = 30
FX_DAILY_CANDLES = 500                 # ~2 years of forex days: FX-BT1 walks from its start (13 months in 2027)


def oanda_daily(pairs: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Complete OANDA daily mid candles per pair (read-only)."""
    from core.oanda_client import OandaClient

    with OandaClient() as client:
        return {p: client.daily_candles(p, count=FX_DAILY_CANDLES) for p in pairs}


def twin_id(sid: str) -> str:
    return f"{LEAGUE_BOT}:{sid}:v{LEAGUE_VERSION}"


def kind_of(strategy: base.Strategy) -> str:
    return "yardstick" if strategy.family == "yardstick" else "shadow"


def load_registration(sid: str, directory: Path = REG_DIR) -> dict[str, Any] | None:
    path = directory / f"{sid}.json"
    if not path.exists():
        return None
    reg = json.loads(path.read_text())
    if reg.get("id") != sid:
        raise ValueError(f"registration {path.name} has id {reg.get('id')!r}")
    return reg


def _http_get(url: str) -> bytes:
    import requests

    resp = requests.get(url, timeout=UNIVERSE_TIMEOUT_SECONDS,
                        headers={"User-Agent": "Mozilla/5.0 (DDG Finance research)"})
    resp.raise_for_status()
    return resp.content


def load_universe(http_get: Callable[[str], bytes] = _http_get) -> tuple[tuple[str, ...], dict[str, str], str]:
    """S&P 500 members and their sectors (same source as MOMO-V2)."""
    from sleeve_runtime.sp500_universe import (MIN_SECTOR_SHARE, load_ivv_sectors, load_sp500_rows,
                                               sector_share, sectors)

    tickers, rows, source = load_sp500_rows(http_get)
    by_ticker = sectors(rows, tickers)
    if sector_share(by_ticker) < MIN_SECTOR_SHARE:      # 20 Nov: SSGA's Sector column is "-" in every row
        try:
            by_ticker, source = load_ivv_sectors(http_get, tickers), f"{source}; sectors from ishares_ivv"
        except Exception as exc:
            logger.warning(f"league | IVV sector list unavailable: {type(exc).__name__}: {exc}")
    return tuple(tickers), by_ticker, source


def ensure_accounts(get_conn, session: date, registrations: dict[str, dict[str, Any]]) -> list[str]:
    """Create the pretend account of every registered strategy that has none.
    All start at the close of ``session`` with the same fake balance."""
    have = {a["twin_id"] for a in store.accounts(get_conn)}
    made = []
    step_at = engine.step_close(session, DAILY)
    for strategy in families.STRATEGIES:
        reg = registrations.get(strategy.id)
        tid = twin_id(strategy.id)
        if reg is None or tid in have:
            continue
        cfg = {"registration": strategy.id, "registration_hash": registration_hash(reg),
               "league_version": LEAGUE_VERSION, "family": strategy.family, "name": strategy.name,
               "max_gross": strategy.max_gross, "allow_short": strategy.allow_short,
               "stop_pct": strategy.stop_pct,
               "costs": "twins.config.SHARE_COSTS (0 commission, 2 bps half spread, 3 bps slippage); "
                        + ("OANDA overnight financing charged at each 17:00 roll (twins/financing.py, rates read nightly from 20 Nov 2026)" if strategy.forex else
                           "2x funds carry their own borrowing cost in their price; idle money in BIL")}
        if store.create_account(get_conn, twin_id=tid, bot_id=LEAGUE_BOT, kind=kind_of(strategy),
                                version=LEAGUE_VERSION, bars=DAILY, start_at=step_at,
                                start_equity=START_EQUITY, config=cfg):
            store.log_change(get_conn, kind="twin_start", bot_id=LEAGUE_BOT, source="twins:league",
                             summary=f"shadow {tid} started with {START_EQUITY:,.2f}",
                             detail={"twin_id": tid, "start_at": step_at, **cfg})
            made.append(tid)
    return made


def run_days(calendar: tuple[date, ...], last_run: date | None, session: date) -> tuple[list[date], int]:
    """(sessions to ask every shadow about tonight, how many were skipped).
    Normally just tonight's session; after an outage, the missed sessions too,
    up to CATCH_UP_SESSIONS. Older missed sessions are skipped and reported:
    the rule compares a session only with the one before, so the walk does not
    need to reach further back, but a skipped month start is a lost rebalance."""
    after = last_run if last_run is not None else session - timedelta(days=1)
    days = [d for d in calendar if after < d <= session]
    return days[-CATCH_UP_SESSIONS:], max(0, len(days) - CATCH_UP_SESSIONS)


def run(get_conn, now: datetime, session: date, *, fetch_daily=None,
        universe_loader: Callable[[], tuple[tuple[str, ...], dict[str, str], str]] | None = None,
        fetch_fx_daily: Callable[[list[str]], dict[str, list[dict[str, Any]]]] | None = None,
        reg_dir: Path = REG_DIR) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Decisions for every shadow up to ``session``. Returns (report, bars);
    the caller merges the bars into the night's replay so new names have prices."""
    from twins import prices
    from twins.job import _decide, _missed

    report: dict[str, Any] = {}
    registrations = {s.id: r for s in families.STRATEGIES if (r := load_registration(s.id, reg_dir))}
    unregistered = sorted(s.id for s in families.STRATEGIES if s.id not in registrations)
    if unregistered:
        report["not_registered"] = unregistered
    report["started"] = ensure_accounts(get_conn, session, registrations)
    accts = {a["twin_id"]: a for a in store.accounts(get_conn) if a["bot_id"] == LEAGUE_BOT}

    todo = [(s, accts[twin_id(s.id)]) for s in families.STRATEGIES if twin_id(s.id) in accts]
    last = store.last_change(get_conn, ("league_run",), LEAGUE_BOT)
    last_run = date.fromisoformat(last["detail"]["session"]) if last else None
    oldest = session - timedelta(days=2 * CATCH_UP_SESSIONS)      # the earliest session it may ask about

    universe: tuple[str, ...] = ()
    sectors: dict[str, str] = {}
    need_universe = any(s.uses_universe for s, _ in todo)
    if need_universe:
        try:
            universe, sectors, source = (universe_loader or load_universe)()
            report["universe"] = {"members": len(universe), "source": source}
        except Exception as exc:
            report["universe"] = f"unavailable: {type(exc).__name__}"
            logger.warning(f"league | S&P 500 list unavailable tonight: {type(exc).__name__}: {exc}")

    symbols = set(families.fixed_symbols()) | set(universe)
    bars = prices.alpaca_daily(sorted(symbols), oldest - timedelta(days=HISTORY_CALENDAR_DAYS), now,
                               fetch=fetch_daily)
    fx_ok = False
    if any(s.forex for s, _ in todo):
        from research_harness.league import forex as fx
        try:
            bars.update(fx.bars_from_daily_candles((fetch_fx_daily or oanda_daily)(list(fx.PAIRS))))
            fx_ok = all(p in bars for p in fx.PAIRS)
            report["forex"] = "ok" if fx_ok else "some pairs missing"
        except Exception as exc:              # OANDA's intermittent 401s: a missed night for the forex lines
            report["forex"] = f"unavailable: {type(exc).__name__}"
            logger.warning(f"league | OANDA daily candles unavailable tonight: {type(exc).__name__}: {exc}")
    calendar = tuple(b["day"] for b in bars.get("SPY", []))
    ctx = base.Context(calendar=calendar, universe=tuple(s for s in universe if s in bars), sectors=sectors)
    view = HistoryView(bars)
    from sleeve_runtime.sp500_universe import MIN_SECTOR_SHARE, sector_share
    sectors_ok = sector_share({s: sectors.get(s, "") for s in ctx.universe}) >= MIN_SECTOR_SHARE

    days, skipped = run_days(calendar, last_run, session)
    if skipped:
        report["skipped_sessions"] = skipped
        logger.warning(f"league | {skipped} sessions before tonight's catch-up window were not asked about")
    for strategy, acct in todo:
        tid = acct["twin_id"]
        start = engine.step_of(acct["start_at"], DAILY)
        mine = [d for d in days if d >= start]
        rows = store.decisions(get_conn, tid)
        why_not = ("S&P 500 member list unavailable" if strategy.uses_universe and not ctx.universe else
                   "S&P 500 sector list unavailable" if strategy.uses_sectors and not sectors_ok else
                   "OANDA daily candles unavailable" if strategy.forex and not fx_ok else None)
        if why_not:
            for d in mine:
                _missed(get_conn, tid, now, engine.step_close(d, DAILY), why_not)
            report[tid] = f"missed {len(mine)}: {why_not}"
            continue
        has_decision = any(not r["missed"] for r in rows)
        sent = 0
        mine_ctx = replace(ctx, start=start)
        for d in mine:
            call = base.decide(strategy, view, mine_ctx, d, has_decision)
            if call is None:
                continue
            if _decide(get_conn, tid, now, engine.step_close(d, DAILY), call.weights,
                       inputs={"state": json.loads(json.dumps(call.state, default=str)), **call.note},
                       inputs_ref="research_harness.league.families", reason=strategy.id):
                sent += 1
            has_decision = True
        report[tid] = {"sessions": len(mine), "decisions": sent}
    if days and universe:                     # the Allocator's regime label (breadth needs the member list)
        from twins import allocator
        report["regime"] = allocator.record_labels(get_conn, view, ctx.universe, days, now)
    if days:
        store.log_change(get_conn, kind="league_run", bot_id=LEAGUE_BOT, source="twins:league",
                         summary=f"league asked {len(todo)} shadows about {len(days)} session(s)",
                         detail={"session": days[-1].isoformat(), "sessions": len(days), "skipped": skipped},
                         at=now)
    return report, bars
