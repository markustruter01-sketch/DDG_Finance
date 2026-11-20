"""Scheduled twin work (registered in core/scheduler.py). Never raises.

hourly (minute 55, New York):
  - change log: bot pauses and resumes, and each new running build;
  - Forex mirror: read the real OANDA positions; a change is a new mirror
    decision. The 16:55 read is also the day's real NAV for the mirror check.
nightly (17:15 New York, Monday-Friday):
  - on a US session day: read each Alpaca account at the close (first run:
    the twins are created here, all starting with the real balance);
    baseline decisions;
  - replay every twin from its start, store its daily equity and fills;
  - mirror check against the real account (alarm through the degradation
    log), and a re-check of every twin's hash chain.

Reads: bot_portfolio, bots_state (the runners write them), market data.
Writes: the twin tables only. Orders: none, ever.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

from loguru import logger

from twins import config, engine, prices, store
from twins.config import DAILY, HOURLY, FOREX_BOT, SHARE_BOTS
from twins.engine import NEW_YORK, SnapshotError

COMPONENT = "twins"
SHARE_COSTS_LABEL = config.SHARE_COSTS.label() + " (0 commission, 2 bps half spread, 3 bps slippage)"
CLOCK_PAIR = "EUR_USD"                        # gives an all-cash forex twin its hours
SPREAD_LOOKBACK = timedelta(days=14)          # hourly candles measured for the forex spread
PORTFOLIO_MAX_AGE = timedelta(hours=2)        # an older forex read is not trusted
FOREX_DAY_LAST_BAR_MINUTE = (16, 55)          # New York: the read inside the forex day's last bar


# ── wiring (all replaceable in tests) ─────────────────────────────────────────
def _default_get_conn():
    from db.postgres import get_conn
    return get_conn


def _default_alarm(severity: str, error_type: str, message: str, bot_id: str | None = None) -> None:
    from core.degradation_tracker import has_recent_open, record_degradation
    # The hourly job may fail every hour of an outage: one open alarm a day is enough.
    if error_type == "twin_job_failed" and has_recent_open(COMPONENT, error_type, hours=24):
        return
    record_degradation(component=COMPONENT, severity=severity, error_type=error_type,
                       message=message, bot_id=bot_id)


def _default_resolve(error_type: str) -> None:
    """Clears every bot's open alarm of this type: call only when none still applies."""
    from core.degradation_tracker import has_recent_open, mark_resolved
    if has_recent_open(COMPONENT, error_type, hours=24 * 30):
        mark_resolved(COMPONENT, error_type, reason="twins: condition cleared")


def _ensure_schema(get_conn) -> None:
    """Table set-up once per process (spec: at startup), not on every run."""
    if not getattr(get_conn, "_twins_schema_ready", False):
        store.ensure_schema(get_conn)
        get_conn._twins_schema_ready = True


def _ny(now: datetime) -> datetime:
    return now.astimezone(NEW_YORK)


def forex_open(now: datetime) -> bool:
    """Sunday 17:00 to Friday 17:00, New York."""
    ny = _ny(now)
    wd, t = ny.weekday(), ny.time()
    if wd == 5:
        return False
    if wd == 6:
        return t >= engine.FOREX_DAY_CLOSE
    if wd == 4:
        return t < engine.FOREX_DAY_CLOSE
    return True


# ── reads of the platform's own tables ────────────────────────────────────────
def _portfolios(get_conn, bot_ids) -> dict[str, dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT bot_id, cash_usd, equity_usd, positions, last_updated
                       FROM bot_portfolio WHERE bot_id = ANY(%s)""", (list(bot_ids),))
        out = {}
        for bot_id, cash, equity, positions, updated in cur.fetchall():
            if isinstance(positions, str):
                positions = json.loads(positions)
            out[bot_id] = {"cash": cash, "equity": equity, "positions": positions, "last_updated": updated}
        return out


def _bot_states(get_conn) -> dict[str, dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT bot_id, paused, pause_reason, paused_at, metadata FROM bots_state")
        out = {}
        for bot_id, paused, reason, paused_at, meta in cur.fetchall():
            if isinstance(meta, str):
                meta = json.loads(meta or "{}")
            out[bot_id] = {"paused": bool(paused), "reason": reason or "", "paused_at": paused_at,
                           "metadata": meta or {}}
        return out


# ── change log ────────────────────────────────────────────────────────────────
def capture_changes(get_conn, now: datetime, commit: str | None = None) -> list[str]:
    """Pauses, resumes and a new running build, each once."""
    from core.bot_registry import active_bot_ids, display_name

    logged = []
    states = _bot_states(get_conn)
    for bot_id in active_bot_ids():
        st = states.get(bot_id)
        if st is None:
            continue
        last = store.last_change(get_conn, ("pause", "resume"), bot_id)
        was_paused = bool(last and last["kind"] == "pause")
        if st["paused"] != was_paused:
            kind = "pause" if st["paused"] else "resume"
            summary = (f"{display_name(bot_id)} paused: {st['reason'] or 'no reason given'}"
                       if st["paused"] else f"{display_name(bot_id)} resumed")
            store.log_change(get_conn, kind=kind, summary=summary, source="twins:bots_state", bot_id=bot_id,
                             detail={"reason": st["reason"]},
                             at=st["paused_at"] if st["paused"] and st["paused_at"] else now)
            logged.append(f"{bot_id}:{kind}")
    if commit is None:
        from core.build_info import current_commit
        commit = current_commit()
    if commit and commit != "unknown":
        last = store.last_change(get_conn, ("publish",))
        if last is None or last["detail"].get("commit") != commit:
            store.log_change(get_conn, kind="publish", summary=f"running build {commit}",
                             source="twins:build_info", detail={"commit": commit}, at=now)
            logged.append(f"publish:{commit}")
    return logged


# ── decisions ─────────────────────────────────────────────────────────────────
def _last_decision(get_conn, twin_id: str) -> dict[str, Any] | None:
    rows = store.decisions(get_conn, twin_id)
    live = [r for r in rows if not r["missed"]]
    return live[-1] if live else None


def _decide(get_conn, twin_id: str, now: datetime, step_at: datetime, weights, *, inputs=None,
            inputs_ref=None, same=None, reason="") -> bool:
    """Append a decision unless it repeats the last one (``same`` compares)."""
    last = _last_decision(get_conn, twin_id)
    if last is not None and (same(last) if same else last["weights"] == _rounded(weights)):
        return False
    store.append_decision(get_conn, twin_id=twin_id, decided_at=now, step_at=step_at, weights=weights,
                          inputs=inputs, inputs_ref=inputs_ref, reason=reason)
    return True


def _rounded(weights: dict[str, float]) -> dict[str, float]:
    return {k: round(float(v), 10) for k, v in sorted(weights.items())}


def _missed(get_conn, twin_id: str, now: datetime, step_at: datetime, reason: str) -> None:
    store.append_decision(get_conn, twin_id=twin_id, decided_at=now, step_at=step_at, weights=None,
                          missed=True, reason=reason[:300])


def _create(get_conn, spec: config.TwinSpec, start_at: datetime, start_equity: float,
            extra: dict[str, Any] | None = None) -> bool:
    cfg = {"registration": config.REGISTRATION, "max_gross": spec.max_gross,
           "allow_short": spec.allow_short, "stop_pct": spec.stop_pct, **(extra or {})}
    made = store.create_account(get_conn, twin_id=spec.twin_id, bot_id=spec.bot_id, kind=spec.kind,
                                version=config.VERSION, bars=spec.bars, start_at=start_at,
                                start_equity=round(start_equity, 2), config=cfg)
    if made:
        store.log_change(get_conn, kind="twin_start", bot_id=spec.bot_id, source="twins:job",
                         summary=f"twin {spec.twin_id} started with {start_equity:,.2f}",
                         detail={"twin_id": spec.twin_id, "start_at": start_at, **cfg})
    return made


# ── share bots: the session close ─────────────────────────────────────────────
def share_close(get_conn, now: datetime, bars: dict[str, list[dict[str, Any]]], session) -> dict[str, str]:
    """Read each Alpaca account at the close of ``session`` (a date)."""
    from core.bot_registry import OWNER_KEPT

    out: dict[str, str] = {}
    have = {a["twin_id"] for a in store.accounts(get_conn)}
    ports = _portfolios(get_conn, SHARE_BOTS)
    states = _bot_states(get_conn)
    step_at = engine.step_close(session, DAILY)
    closes = engine.closes_on(bars, session)
    earliest = datetime.combine(session, time(15, 0), NEW_YORK)   # the account read in the last hour
    specs = config.phase_a_twins()
    for bot_id in SHARE_BOTS:
        mirror_id = f"{bot_id}:mirror:v{config.VERSION}"
        try:
            port = ports.get(bot_id)
            if port is None:
                raise SnapshotError("no bot_portfolio row")
            if port["last_updated"] is None or port["last_updated"] < earliest:
                raise SnapshotError(f"account last read {port['last_updated']}, before the session's last hour")
            snap = engine.share_snapshot(port["positions"], port["cash"], closes,
                                         OWNER_KEPT.get(bot_id, frozenset()))
        except SnapshotError as exc:
            if mirror_id in have:
                _missed(get_conn, mirror_id, now, step_at, f"account unreadable: {exc}")
            out[bot_id] = f"missed: {exc}"
            continue
        for spec in (s for s in specs if s.bot_id == bot_id):
            if spec.twin_id not in have:
                _create(get_conn, spec, step_at, snap["equity"], {"costs": SHARE_COSTS_LABEL})
        inputs = {"qty": snap["qty"], "cash": float(port["cash"]), "equity": round(snap["equity"], 2),
                  "account_read_at": port["last_updated"]}
        changed = _decide(get_conn, mirror_id, now, step_at, snap["weights"], inputs=inputs,
                          inputs_ref="bot_portfolio", same=lambda last: last["inputs"].get("qty") == snap["qty"],
                          reason="real holdings at the close")
        store.record_ref(get_conn, mirror_id, session, snap["equity"], step_at,
                         {"cash": float(port["cash"]), "qty": snap["qty"], "kept": snap["kept"]})
        names = ((states.get(bot_id) or {}).get("metadata") or {}).get(config.MOMO_STATE_KEY, {}).get("names")
        for kind in ("baseline_full", "baseline_spy"):
            w = config.baseline_weights(bot_id, kind, names)
            if w is not None:
                _decide(get_conn, f"{bot_id}:{kind}:v{config.VERSION}", now, step_at, w,
                        inputs_ref="twins.config.baseline_weights", reason=kind)
        out[bot_id] = "changed" if changed else "same holdings"
    return out


def share_symbols(get_conn, states) -> list[str]:
    """Every symbol the share twins may need tonight."""
    syms = {"SPY"}
    for bot_id in SHARE_BOTS:
        names = ((states.get(bot_id) or {}).get("metadata") or {}).get(config.MOMO_STATE_KEY, {}).get("names")
        for kind in ("baseline_full", "baseline_spy"):
            syms |= set(config.baseline_weights(bot_id, kind, names) or {})
    from core.bot_registry import OWNER_KEPT
    from core.symbols import canonical_symbol
    for bot_id, port in _portfolios(get_conn, SHARE_BOTS).items():
        kept = OWNER_KEPT.get(bot_id, frozenset())
        syms |= {canonical_symbol(p.get("symbol")) for p in port["positions"] or []} - kept
    for acct in store.accounts(get_conn):
        if acct["bars"] == DAILY and not _league_forex(acct):    # forex prices come from OANDA, not Alpaca
            for d in store.decisions(get_conn, acct["twin_id"]):
                syms |= set(d["weights"] or {})
    return sorted(s for s in syms if s)


def _league_forex(acct: dict[str, Any]) -> bool:
    """A Shadow League forex line: daily bars, but OANDA prices (merged in by the league)."""
    return (acct.get("config") or {}).get("family") == "forex"


# ── forex ─────────────────────────────────────────────────────────────────────
def _pair_of(sym: str) -> str:
    """The OANDA pair behind a simulator symbol: CHF_USD -> USD_CHF, EUR_USD -> EUR_USD.
    Every symbol is X_USD, so the direction comes from the registered pair list."""
    from research_harness.league.forex import PAIRS
    return {engine.synthetic(p): p for p in PAIRS}[sym]


def _mids(candles: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    return {p: float(rows[-1]["mid"]["c"]) for p, rows in candles.items() if rows}


def forex_read(get_conn, now: datetime, fetch_hourly=prices.oanda_hourly, *, create: bool = False,
               spread_candles: dict[str, list[dict[str, Any]]] | None = None) -> str:
    """Read the real OANDA account: a mirror decision if the holdings changed,
    the day's reference NAV in the forex day's last hour, the twins on create."""
    mirror_id = f"{FOREX_BOT}:mirror:v{config.VERSION}"
    have = {a["twin_id"] for a in store.accounts(get_conn)}
    if mirror_id not in have and not create:
        return "no forex twins yet"
    step = engine.bar_hour(now)                      # the bar in progress; the read reflects its holdings
    if create:
        step = step - engine.HOUR                    # nightly runs after the bar closed
    step_at = engine.step_close(step, HOURLY)
    port = _portfolios(get_conn, [FOREX_BOT]).get(FOREX_BOT)
    try:
        if port is None:
            raise SnapshotError("no bot_portfolio row")
        if port["last_updated"] is None or now - port["last_updated"] > PORTFOLIO_MAX_AGE:
            raise SnapshotError(f"account last read {port['last_updated']}")
        held = sorted({str(p.get("instrument")) for p in port["positions"] or []})
        try:
            candles = fetch_hourly(held, now - timedelta(hours=4)) if held else {}
        except Exception as exc:              # OANDA's intermittent 401s: a missed read, not an alarm
            raise SnapshotError(f"OANDA prices unavailable: {type(exc).__name__}") from None
        snap = engine.forex_snapshot(port["positions"], port["equity"], _mids(candles))
    except SnapshotError as exc:
        if mirror_id in have:
            _missed(get_conn, mirror_id, now, step_at, f"account unreadable: {exc}")
        return f"missed: {exc}"
    if create and mirror_id not in have:
        spread = {p: engine.half_spread_bps(rows) for p, rows in (spread_candles or {}).items()}
        missing = sorted(set(config.FOREX_PAIRS) - set(spread))
        if missing:
            return f"not created: no spread for {missing}"
        for spec in (s for s in config.phase_a_twins() if s.bot_id == FOREX_BOT):
            if spec.bars == HOURLY:
                _create(get_conn, spec, step_at, snap["equity"],
                        {"spread_bps": spread, "costs": engine.forex_costs(spread).label()})
    inputs = {"units": snap["units"], "nav": round(snap["equity"], 2), "account_read_at": port["last_updated"]}
    changed = _decide(get_conn, mirror_id, now, step_at, snap["weights"], inputs=inputs, inputs_ref="bot_portfolio",
                      same=lambda last: last["inputs"].get("units") == snap["units"],
                      reason="real holdings this hour")
    ny = _ny(now)
    if create or (ny.hour, ny.minute) >= FOREX_DAY_LAST_BAR_MINUTE and ny.hour == 16:
        store.record_ref(get_conn, mirror_id, _ny(step_at).date(), snap["equity"], port["last_updated"])
    return "changed" if changed else "same holdings"


def forex_start(get_conn, now: datetime, session, fetch_hourly) -> str:
    """First run: the Forex mirror (from the real account) and its S&P baseline."""
    have = {a["twin_id"]: a for a in store.accounts(get_conn)}
    mirror_id = f"{FOREX_BOT}:mirror:v{config.VERSION}"
    status = "exists"
    if mirror_id not in have:
        if not forex_open(now - timedelta(minutes=30)):
            return "forex closed: not started"
        spread = fetch_hourly(list(config.FOREX_PAIRS), now - SPREAD_LOOKBACK)
        status = forex_read(get_conn, now, fetch_hourly, create=True, spread_candles=spread)
        have = {a["twin_id"]: a for a in store.accounts(get_conn)}
    spy_id = f"{FOREX_BOT}:baseline_spy:v{config.VERSION}"
    if mirror_id in have:
        step_at = engine.step_close(session, DAILY)
        if spy_id not in have:
            spec = next(s for s in config.phase_a_twins() if s.twin_id == spy_id)
            _create(get_conn, spec, step_at, have[mirror_id]["start_equity"], {"costs": SHARE_COSTS_LABEL})
        _decide(get_conn, spy_id, now, step_at, config.baseline_weights(FOREX_BOT, "baseline_spy"),
                inputs_ref="twins.config.baseline_weights", reason="baseline_spy")
    return status


# ── replay + checks ───────────────────────────────────────────────────────────
def _decision_steps(rows, bars_kind):
    return [{"id": r["id"], "step": engine.step_of(r["step_at"], bars_kind), "weights": r["weights"]}
            for r in rows]


def replay_twin(get_conn, acct: dict[str, Any], bars: dict[str, list[dict[str, Any]]]) -> engine.Replay:
    rows = store.decisions(get_conn, acct["twin_id"])
    cfg = acct["config"]
    costs = engine.forex_costs(cfg["spread_bps"]) if acct["bars"] == HOURLY else config.SHARE_COSTS
    needed = {s for r in rows for s in (r["weights"] or {})}
    return engine.replay(bars_kind=acct["bars"], mirror=acct["kind"] == "mirror",
                         start=engine.step_of(acct["start_at"], acct["bars"]),
                         start_equity=acct["start_equity"], decisions=_decision_steps(rows, acct["bars"]),
                         bars={s: bars[s] for s in needed | {"SPY"} if s in bars} if acct["bars"] == DAILY
                         else bars,
                         costs=costs, max_gross=cfg["max_gross"], allow_short=cfg["allow_short"],
                         stop_pct=cfg.get("stop_pct"))


def flow_days(rows: list[dict[str, Any]]) -> frozenset:
    """Days on which an owner-kept holding changed (sold by its stop, say): the
    cash it brought is money arriving, not the strategy's return."""
    days, prev = set(), None
    for r in rows:
        kept = (r.get("ref_holdings") or {}).get("kept")
        if kept is None:
            continue
        if prev is not None and kept != prev:
            days.add(r["day"])
        prev = kept
    return frozenset(days)


def check_mirror(get_conn, acct, result: engine.Replay) -> float | None:
    """Store the mirror's gap to the real account per day; return the latest.

    The real side is the value recorded on the day (raw closes), never a later
    re-valuation: dividend-adjusted bars lower past closes, and the dividend
    cash then arrives as well, so re-valuing would count each dividend twice.
    Known and temporary: the mirror books a dividend on the ex-date, the real
    account on the pay date, so the gap opens by weight x dividend in between."""
    rows = store.equity_rows(get_conn, acct["twin_id"])
    flows = flow_days(rows)
    if acct["bars"] == DAILY:
        pairs = [(r["day"], r["equity"], r["ref_equity"]) for r in rows]
    else:
        pairs = [(r["day"], engine.equity_at(result.curve, r["ref_at"], HOURLY, acct["start_equity"])
                  if r["ref_at"] else None, r["ref_equity"]) for r in rows]
    gaps = engine.mirror_gaps(pairs, flows)
    store.set_gaps(get_conn, acct["twin_id"], gaps)
    return gaps[max(gaps)] if gaps else None


def _league(get_conn, now, session, daily, fetch_daily, universe_loader, alarm, resolve, fetch_fx_daily=None):
    """The Shadow League's decisions for tonight. It must never stop the bot twins:
    any failure is one alarm and the night goes on."""
    try:
        from twins import league
        report, league_bars = league.run(get_conn, now, session, fetch_daily=fetch_daily,
                                         universe_loader=universe_loader, fetch_fx_daily=fetch_fx_daily)
        for sym, rows in league_bars.items():     # names first held tonight need prices to replay
            daily.setdefault(sym, rows)
        resolve("league_failed")
        return report
    except Exception as exc:
        logger.exception("league nightly failed")
        alarm("error", "league_failed", f"Shadow League nightly failed: {type(exc).__name__}: {str(exc)[:200]}")
        return f"failed: {type(exc).__name__}"


def nightly(now: datetime | None = None, *, get_conn=None, fetch_daily=None, fetch_hourly=prices.oanda_hourly,
            alarm: Callable[..., None] = _default_alarm, resolve: Callable[..., None] = _default_resolve,
            commit: str | None = None, with_league: bool = True, universe_loader=None,
            fetch_fx_daily=None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    get_conn = get_conn or _default_get_conn()
    report: dict[str, Any] = {"at": now.isoformat()}
    try:
        _ensure_schema(get_conn)
        report["changes"] = capture_changes(get_conn, now, commit)
        states = _bot_states(get_conn)
        accts = store.accounts(get_conn)
        starts = [a["start_at"] for a in accts if a["bars"] == DAILY]
        first = (min(starts).astimezone(NEW_YORK).date() if starts else _ny(now).date() - timedelta(days=10))
        daily = prices.alpaca_daily(share_symbols(get_conn, states), first, now, fetch=fetch_daily)
        session = daily["SPY"][-1]["day"]
        report["session"] = session.isoformat()
        if session == _ny(now).date():
            report["share_close"] = share_close(get_conn, now, daily, session)
            report["league"] = (_league(get_conn, now, session, daily, fetch_daily, universe_loader, alarm,
                                        resolve, fetch_fx_daily) if with_league else "off")
            try:                                  # an OANDA outage must not stop the share twins
                report["forex_start"] = forex_start(get_conn, now, session, fetch_hourly)
            except Exception as exc:
                logger.warning(f"twins | forex start skipped tonight: {type(exc).__name__}")
                report["forex_start"] = f"failed: {type(exc).__name__}"
        else:
            report["share_close"] = "no US session today"
        report["twins"] = replay_all(get_conn, now, daily, fetch_hourly, alarm, resolve)
        report["chains"] = verify_all(get_conn, alarm)
        report["month_end"] = _month_end(get_conn, now, report["twins"], alarm, resolve)
        report["allocator"] = _allocator(get_conn, now, alarm) if with_league else "off"
        resolve("twin_job_failed")
    except Exception as exc:
        logger.exception("twins nightly failed")
        alarm("error", "twin_job_failed", f"twins nightly failed: {type(exc).__name__}: {str(exc)[:200]}")
        report["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return report


def _month_end(get_conn, now, replayed: dict[str, Any], alarm, resolve) -> Any:
    """Freeze finished months (only for twins valued tonight), check drift, copy off-site.
    Its failure is one alarm; it never stops the night."""
    try:
        from twins import month_end
        ok = {tid for tid, r in replayed.items() if isinstance(r, dict)}
        return month_end.run(get_conn, now, alarm, resolve, only=ok)
    except Exception as exc:
        logger.exception("month-end step failed")
        alarm("error", "twin_month_end_failed", f"month-end step failed: {type(exc).__name__}: {str(exc)[:200]}")
        return f"failed: {type(exc).__name__}"


def _allocator(get_conn, now, alarm) -> Any:
    """The two shadow funds' values tonight; one alarm the first time one falls 15%. Never stops the night."""
    try:
        from twins import allocator
        return allocator.check(get_conn, now, alarm)
    except Exception as exc:
        logger.exception("allocator check failed")
        alarm("error", "allocator_check_failed", f"Allocator check failed: {type(exc).__name__}: {str(exc)[:200]}")
        return f"failed: {type(exc).__name__}"


def replay_all(get_conn, now, daily, fetch_hourly, alarm, resolve) -> dict[str, Any]:
    """Replay every twin; one alarm per failed twin and per drifting mirror.
    The degradation log resolves by type for all bots at once, so a type is
    resolved only on a night when it applies to no twin."""
    out: dict[str, Any] = {}
    failed, drifting = 0, 0
    for acct in store.accounts(get_conn):
        tid = acct["twin_id"]
        try:
            if acct["bars"] == HOURLY:
                rows = store.decisions(get_conn, tid)
                pairs = sorted({_pair_of(s) for r in rows for s in (r["weights"] or {})} | {CLOCK_PAIR})
                start = engine.step_of(acct["start_at"], HOURLY)
                try:
                    candles = fetch_hourly(pairs, start)
                except Exception:                    # OANDA's intermittent 401s: one retry
                    candles = fetch_hourly(pairs, start)
                bars = engine.forex_bars(candles)
            else:
                bars = daily
                if _league_forex(acct):
                    need = {s for r in store.decisions(get_conn, tid) for s in (r["weights"] or {})}
                    if not need <= set(bars):
                        out[tid] = "no forex prices tonight: last value kept"
                        continue
            result = replay_twin(get_conn, acct, bars)
            if not result.curve:
                out[tid] = "no bars yet"
                continue
            store.upsert_equity(get_conn, tid, engine.daily_points(result.curve, acct["bars"]))
            store.upsert_fills(get_conn, tid, result.fills)
            gap = check_mirror(get_conn, acct, result) if acct["kind"] == "mirror" else None
            out[tid] = {"equity": round(result.curve[-1][1], 2), "fills": len(result.fills), "gap_pp": gap}
            if gap is not None and abs(gap) > config.MIRROR_GUARD_PP:
                drifting += 1
                alarm("error", "twin_mirror_drift",
                      f"{tid}: the pretend-account engine is {gap:+.2f} percentage points away from the real "
                      f"account since the twin started (guard {config.MIRROR_GUARD_PP}). Twin results for "
                      f"this bot are not trusted until this is explained.", acct["bot_id"])
        except Exception as exc:
            failed += 1
            logger.exception(f"twin replay failed: {tid}")
            alarm("error", "twin_replay_failed", f"{tid}: replay failed: {type(exc).__name__}: {str(exc)[:200]}",
                  acct["bot_id"])
            out[tid] = f"failed: {type(exc).__name__}"
    if not failed:
        resolve("twin_replay_failed")
    if not drifting and not failed:
        resolve("twin_mirror_drift")
    return out


def verify_all(get_conn, alarm) -> dict[str, int]:
    broken = {}
    for acct in store.accounts(get_conn, active_only=False):
        problems = store.verify_chain(store.decisions(get_conn, acct["twin_id"]))
        if problems:
            broken[acct["twin_id"]] = len(problems)
            alarm("error", "twin_ledger_broken",
                  f"{acct['twin_id']}: decision log fails its hash check: {problems[0]}", acct["bot_id"])
    return broken


def hourly(now: datetime | None = None, *, get_conn=None, fetch_hourly=prices.oanda_hourly,
           alarm: Callable[..., None] = _default_alarm, commit: str | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    get_conn = get_conn or _default_get_conn()
    report: dict[str, Any] = {"at": now.isoformat()}
    try:
        _ensure_schema(get_conn)
        report["changes"] = capture_changes(get_conn, now, commit)
        report["forex"] = forex_read(get_conn, now, fetch_hourly) if forex_open(now) else "forex closed"
    except Exception as exc:
        logger.exception("twins hourly failed")
        alarm("error", "twin_job_failed", f"twins hourly failed: {type(exc).__name__}: {str(exc)[:200]}")
        report["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return report
