"""FLEET-V1 live (spec: sleeve_runtime/FLEET-V1-LIVE-SPEC.md).

Owner's decision (Markus, 2 Nov 2026): run FLEET-V1-F1 on Atlas's (oracle's)
Alpaca paper account, and its equity core alone (C1) on Momentum's account
as a forward control. Which variant runs where: sleeve_runtime/fleet_accounts.py
(the one place). Roadmap v2, V2-03: X1, the cross-asset rule alone (no shares),
replaces C1 on Atlas V2's account at the lock (Markus, D2 = B). F1 FAILED its registered "beat the index" bar on
2011-2020 (ledger FLEET-V1-F1); it is run for what it did deliver: about
half the index's drawdowns.

Rules are the registered code, imported, never copied:
- core (research_harness/sleeves/core_v1.py, mix C1): votes, vol20, E,
  the 1x/2x split. Due when the vote count changes or a month starts.
- cross-asset (research_harness/sleeves/xasset_v1.py): weights as of the
  month's first completed session, so they only ever change monthly.
- fleet = core_weight x core + xasset_weight x cross-asset; everything else
  is cash (parked in SGOV). Whenever anything is due, the whole vector is
  recomputed from current equity.
- 20% protective stops on the core's instruments only; the cross-asset
  lines are stop-free (the monthly call is their exit).

Account drawdown governor (spec section 4), from the account's closing
equity (Alpaca's last_equity) against its high-water mark since cutover:
- above SOFT: every target is halved, until equity is back to 95% of the
  high-water mark;
- above HARD: everything is sold to cash and the account halts until the
  owner clears it (clear_halt resets the high-water mark to today's equity).
A change of mode is itself a rebalance.

Order machinery: the tested TREND-V1-B executor, as GEAR-V1-G4 used it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import partial
from typing import Any, Callable

from research_harness.harness.portfolio import HistoryView
from research_harness.sleeves import core_v1, xasset_v1
from sleeve_runtime import fleet_accounts
from sleeve_runtime.trend_executor import (
    MAX_ATTEMPTS,
    MAX_BAR_AGE_DAYS,
    close_flat_rows,
    execute_rebalance,
)
from sleeve_runtime.trend_v1b import (
    NEW_YORK,
    BarFetcher,
    TrendPlan,
    completed_bars,
    plan_from_weights,
    sleeve_capital,
)

try:
    from loguru import logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("fleet_live")

SIGNAL = core_v1.SIGNAL                                  # "SPY"
CORE_SYMBOLS = tuple(s for pair in core_v1.INSTRUMENTS.values() for s in pair)
XASSET_SYMBOLS = tuple(xasset_v1.LINES)
NO_STOP_SYMBOLS = frozenset(XASSET_SYMBOLS)              # must equal core/stop_policy.TREND_EXIT_LINES
HISTORY_CALENDAR_DAYS = 420                              # ~290 sessions > the 253 the votes need
RECOVER_FRACTION = 0.95
MODE_SCALE = {"normal": 1.0, "soft": 0.5, "halt": 0.0}


@dataclass(frozen=True)
class FleetVariant:
    registration: str
    state_key: str                 # bots_state.metadata key
    exit_reason: str               # ledger exit reason; also the alert error_type
    core_weight: float
    xasset_weight: float

    @property
    def has_core(self) -> bool:
        return self.core_weight > 0

    @property
    def symbols(self) -> tuple[str, ...]:
        """The instruments this variant may hold. X1 holds no share fund."""
        return ((CORE_SYMBOLS if self.has_core else ())
                + (XASSET_SYMBOLS if self.xasset_weight > 0 else ()))

    @property
    def feed(self) -> tuple[str, ...]:
        """The bars it reads: its instruments plus SPY, the session calendar (never a target unless held)."""
        return tuple(dict.fromkeys(self.symbols + (SIGNAL,)))


def _variant(registration: str) -> FleetVariant:
    key = fleet_accounts.state_key(registration)
    return FleetVariant(registration, key, f"{key}_rebalance", *fleet_accounts.SPLITS[registration])


F1 = _variant("FLEET-V1-F1")
C1 = _variant("FLEET-V1-C1")
X1 = _variant("FLEET-V1-X1")       # roadmap v2, V2-03: the cross-asset rule alone (D2 = B, at the lock)
VARIANTS = {v.registration: v for v in (F1, C1, X1)}
ACCOUNTS = {bot: VARIANTS[reg] for bot, reg in fleet_accounts.ACCOUNTS.items()}   # which variant trades where


# ── signal (pure) ─────────────────────────────────────────────────────────────
def core_signal(bars: dict[str, list[dict[str, Any]]], day: date) -> dict[str, Any] | None:
    """Votes, vol20, E and core weights from SPY closes up to and including ``day``."""
    closes = [b["close"] for b in bars.get(SIGNAL, []) if b["day"] <= day]
    if len(closes) < core_v1.NEED:
        return None
    closes = closes[-core_v1.NEED:]
    v = core_v1.votes(closes)
    vol = core_v1.vol20(closes)
    e = core_v1.target_exposure(v, vol)
    return {"votes": v, "vol20": vol, "exposure": e,
            "weights": core_v1.weights_for(e, core_v1.MIXES["C1"])}


def month_first_session(bars: dict[str, list[dict[str, Any]]], day: date) -> date | None:
    days = [b["day"] for b in bars.get(SIGNAL, []) if b["day"] <= day
            and (b["day"].year, b["day"].month) == (day.year, day.month)]
    return min(days) if days else None


def xasset_signal(bars: dict[str, list[dict[str, Any]]], day: date) -> dict[str, float]:
    """Cross-asset weights as of the first completed session of ``day``'s month."""
    first = month_first_session(bars, day)
    if first is None:
        return {}
    view = HistoryView({s: bars[s] for s in XASSET_SYMBOLS if bars.get(s)})
    view.today = first
    return xasset_v1.target_weights(view)


def fleet_weights(core_w: dict[str, float], xasset_w: dict[str, float],
                  variant: FleetVariant, scale: float = 1.0) -> dict[str, float]:
    """The account's target vector. Raises (never clamps) if gross exceeds 1."""
    out: dict[str, float] = {}
    for s, w in (core_w.items() if variant.has_core else ()):
        out[s] = out.get(s, 0.0) + variant.core_weight * w * scale
    if variant.xasset_weight > 0:
        for s, w in xasset_w.items():
            out[s] = out.get(s, 0.0) + variant.xasset_weight * w * scale
    gross = sum(out.values())
    if gross > 1.0 + 1e-9 or any(w < 0 for w in out.values()):
        raise ValueError(f"fleet target gross {gross:.6f} breaks the no-borrowing rule")
    return {s: w for s, w in out.items() if w > 1e-12}


# ── drawdown governor (pure) ──────────────────────────────────────────────────
def drawdown_mode(equity: float, hwm: float, prev_mode: str, halted: bool, *,
                  soft: float, hard: float) -> str:
    if halted:
        return "halt"
    dd = 1 - equity / hwm if hwm > 0 else 0.0
    if dd > hard:
        return "halt"
    if dd > soft:
        return "soft"
    if prev_mode == "soft" and equity < hwm * RECOVER_FRACTION:
        return "soft"
    return "normal"


def update_drawdown(dd_state: dict[str, Any], closing_equity: float | None, as_of: date, *,
                    soft: float, hard: float) -> dict[str, Any]:
    """Once per session: raise the high-water mark and set the mode.
    Unknown closing equity keeps the previous state (and is reported)."""
    st = dict(dd_state or {})
    if closing_equity is None or closing_equity <= 0:
        st["error"] = "closing equity unknown; mode unchanged"
        st.setdefault("mode", "normal")
        return st
    if st.get("as_of") == as_of.isoformat():
        return st
    hwm = max(float(st.get("hwm") or 0.0), closing_equity)
    mode = drawdown_mode(closing_equity, hwm, st.get("mode", "normal"), bool(st.get("halted")),
                         soft=soft, hard=hard)
    st.update(hwm=hwm, equity=closing_equity, drawdown=round(1 - closing_equity / hwm, 6),
              mode=mode, halted=mode == "halt", as_of=as_of.isoformat())
    st.pop("error", None)
    return st


def clear_halt(dd_state: dict[str, Any], equity: float, by: str) -> dict[str, Any]:
    """Owner action: leave a hard halt. The high-water mark restarts at today's equity."""
    if equity <= 0:
        raise ValueError("equity must be positive to clear a halt")
    st = dict(dd_state or {})
    st.update(halted=False, mode="normal", hwm=equity, equity=equity, drawdown=0.0,
              cleared_by=by, cleared_at=datetime.now(timezone.utc).isoformat())
    return st


# ── plan and schedule ─────────────────────────────────────────────────────────
def targets_on(bars: dict[str, list[dict[str, Any]]], day: date, variant: FleetVariant,
               mode: str) -> dict[str, Any] | None:
    core = core_signal(bars, day)
    if core is None:
        return None
    xa = xasset_signal(bars, day) if variant.xasset_weight > 0 else {}
    w = fleet_weights(core["weights"], xa, variant, MODE_SCALE[mode])
    return {**core, "xasset": xa, "mode": mode, "fleet": w}


def compute_fleet_plan(*, bars, positions, equity, cash, signal_day=None, frozen=None,
                       variant: FleetVariant = F1, mode: str = "normal") -> TrendPlan:
    """Pure. Same plan shape as TREND-V1-B, with the fleet's weights."""
    spy = bars.get(SIGNAL) or []
    if not spy:
        raise ValueError("no SPY bars")
    price_day = spy[-1]["day"]
    signal_day = signal_day or price_day
    if signal_day > price_day:
        raise ValueError("signal day is after the latest bar")
    t = targets_on(bars, signal_day, variant, mode)
    if t is None:
        raise ValueError("not enough SPY history for the core's votes")
    return plan_from_weights(weights=t["fleet"], bars=bars, positions=positions, equity=equity,
                             cash=cash, signal_day=signal_day, price_day=price_day, frozen=frozen,
                             stop_pct=core_v1.STOP_PCT, registration=variant.registration,
                             no_stop=NO_STOP_SYMBOLS)


def rebalance_key(day: date, votes: int, mode: str, variant: FleetVariant = F1) -> str:
    """A rebalance is due whenever this changes: new month, new vote count, new drawdown mode.
    A variant with no share core (X1) ignores the vote count: its weights only change monthly."""
    if not variant.has_core:
        return f"{day.year:04d}-{day.month:02d}|{mode}"
    return f"{day.year:04d}-{day.month:02d}|v{votes}|{mode}"


def fleet_due(bars, today_ny: date, state: dict[str, Any], mode: str,
              variant: FleetVariant = F1) -> tuple[date, dict, str] | None:
    """(signal day, signal, key) if a rebalance is due now, else None.
    A stale feed is never due; a halted account is due once (to go to cash)."""
    spy = bars.get(SIGNAL) or []
    if not spy or (today_ny - spy[-1]["day"]).days > MAX_BAR_AGE_DAYS:
        return None
    signal_day = spy[-1]["day"]
    core = core_signal(bars, signal_day)
    if core is None:
        return None
    key = rebalance_key(signal_day, core["votes"], mode, variant)
    if mode == "halt" and str(state.get("key", "")).endswith("|halt") and state.get("done"):
        return None                         # already in cash; stays there until cleared
    if state.get("key") == key and (state.get("done") or int(state.get("attempts", 0)) >= MAX_ATTEMPTS):
        return None
    return signal_day, core, key


def daily_mark(state: dict[str, Any], bars, sleeve_equity: float,
               total_equity: float | None = None) -> dict[str, Any] | None:
    """Once per session: the account's sleeve equity and SPY's close, plus the
    first such mark (the cutover). Returns the new state, or None if unchanged.
    SPY's close is from the adjusted series, so later dividends are not in
    the comparison: it is a price-return benchmark, labelled as such.
    `total_equity` is broker equity including the vault (VAULT-V2 section 3:
    performance is reported on it, so a skim never makes an account look worse)."""
    spy = bars.get(SIGNAL) or []
    if not spy or sleeve_equity <= 0:
        return None
    mark = {"day": spy[-1]["day"].isoformat(), "spy": float(spy[-1]["close"]),
            "equity": round(float(sleeve_equity), 2)}
    if total_equity:
        mark["total"] = round(float(total_equity), 2)
    if (state.get("mark") or {}).get("day") == mark["day"]:
        return None
    return {**state, "mark": mark, "cutover": state.get("cutover") or mark}


def fetch_fleet_bars(fetch_bars: BarFetcher, held: dict[str, float], now: datetime,
                     variant: FleetVariant):
    """The variant's feed plus anything held (legacy holdings get a price to sell)."""
    symbols = sorted(set(variant.feed) | set(held))
    return completed_bars(fetch_bars(symbols, now.date() - timedelta(days=HISTORY_CALENDAR_DAYS)), now)


def run_fleet_cycle(
    engine,
    *,
    bot_id: str,
    fetch_bars: BarFetcher,
    vault: set[str],
    cash_park: set[str],
    read_state: Callable[[], dict[str, Any]],
    write_state: Callable[[dict[str, Any]], None],
    kill_tripped: Callable[[], bool],
    unpark: Callable[[Any, list[dict[str, Any]]], Any],
    park: Callable[[Any, list[dict[str, Any]], float], Any],
    alert: Callable[[str, str], None],
    risk_check: Callable[[], dict[str, Any]],
    soft: float,
    hard: float,
    now: datetime | None = None,
    variant: FleetVariant = F1,
    owner_kept: Callable[[str], bool] = lambda symbol: False,
) -> dict[str, Any]:
    """The account's whole hourly cycle while a FLEET-V1 variant owns it.
    ``owner_kept``: holdings the owner has decided stay untouched (never traded
    either way); leaving those alone is expected and raises no alarm."""
    now = now or datetime.now(timezone.utc)
    live = engine.get_positions()
    rows = engine.get_db_positions(bot_id)
    close_flat_rows(engine, bot_id, live, rows)

    if kill_tripped():
        return {"status": "kill switch tripped: no trading"}

    state = read_state() or {}
    today_ny = now.astimezone(NEW_YORK).date()
    account = engine.get_account()
    dd_before = state.get("drawdown") or {}
    dd = update_drawdown(dd_before, account.get("last_equity"), today_ny, soft=soft, hard=hard)
    if dd != dd_before:
        state = {**state, "drawdown": dd}
        write_state(state)
        if dd.get("mode") != dd_before.get("mode") and dd_before:
            alert("critical" if dd["mode"] == "halt" else "error",
                  f"{variant.registration}: drawdown mode {dd_before.get('mode')} -> {dd['mode']} "
                  f"(drawdown {dd.get('drawdown', 0):.1%} from high-water mark {dd.get('hwm', 0):,.0f})")
    mode = dd.get("mode", "normal")

    if not engine.is_market_open():
        return {"status": "market closed", "mode": mode}

    status = "no rebalance due"
    cap = sleeve_capital(account, live, vault=vault, cash_park=cash_park)
    bars = fetch_fleet_bars(fetch_bars, cap.held, now, variant)
    marked = daily_mark(state, bars, cap.equity, float(account["equity"]))
    if marked is not None:
        state = marked
        write_state(state)
    due = fleet_due(bars, today_ny, state, mode, variant)
    if due is not None:
        signal_day, core, key = due
        attempts = int(state.get("attempts", 0)) + 1 if state.get("key") == key else 1
        # Record the attempt BEFORE any order, so a crash mid-way cannot loop.
        base = {"key": key, "attempts": attempts, "signal_day": signal_day.isoformat(), "at": now.isoformat()}
        if variant.has_core:               # X1 holds no shares: SPY's votes would only mislead a reader
            base.update(votes=core["votes"], exposure=round(core["exposure"], 4), vol20=round(core["vol20"], 4))
        write_state({**state, **base, "done": False})
        try:
            report = execute_rebalance(engine, bot_id=bot_id, bars=bars, signal_day=signal_day,
                                       vault=vault, cash_park=cash_park, unpark=unpark,
                                       risk_check=risk_check,
                                       plan_fn=partial(compute_fleet_plan, variant=variant, mode=mode),
                                       registration=variant.registration,
                                       exit_reason=variant.exit_reason)
        except Exception as exc:
            msg = f"{variant.registration} rebalance attempt {attempts} crashed: {type(exc).__name__}: {exc}"
            write_state({**state, **base, "done": False, "errors": [msg[:300]]})
            alert("critical", msg)
            log.exception(msg)
            return {"status": f"rebalance attempt {attempts} crashed", "mode": mode}
        targets = report["plan"].get("weights", {})
        write_state({**state, **base, "done": report["done"], "errors": report["errors"][:10],
                     "targets": targets})
        log.info(f"{variant.registration} rebalance | key={key} | attempt {attempts} | {report}")
        if report["unprotected"]:
            alert("critical", f"{variant.registration}: positions without a protective stop: {report['unprotected']}")
        elif report["errors"]:
            alert("error", f"{variant.registration} rebalance attempt {attempts} had errors: {report['errors'][:5]}")
        untouched = {sym: why for sym, why in (report["plan"].get("skipped") or {}).items()
                     if not owner_kept(sym)}
        if untouched:
            alert("error", f"{variant.registration}: symbols left untouched: {untouched}")
        status = f"rebalanced ({key})" if report["done"] else f"rebalance attempt {attempts} incomplete"

    acct = engine.get_account()
    park(engine, engine.get_positions(), acct["cash"])
    return {"status": status, "mode": mode}
