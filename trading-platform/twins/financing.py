"""Forex overnight financing for pretend accounts (audit AU5, Markus 20 Nov: option A).

The real Forex account pays or earns interest on every position held over
OANDA's 17:00 New York roll. The pretend copies (the council's mirror twin and
the league's forex lines) now carry the same cost:

- Each night the OANDA rates for the registered pairs are read (read-only) and
  stored in twin_fx_financing (append-only): yearly long and short rates and
  how many days each weekday's roll charges (OANDA's financingDaysOfWeek, so
  weekends are charged on the day OANDA charges them).
- At every roll a twin holds a position, it is charged (at the rates read the
  evening before; the nightly read runs after that day's roll)
  notional (US dollars at that close) x rate x days charged / 365.
  A long position in a USD_XXX pair is a short in the simulator's XXX_USD, so
  a long synthetic uses the pair's short rate (and the other way round).
- The charge is added to the twin's equity from that roll on. It does not
  change position sizes (a second-order effect on accounts this size).
- A roll with no stored rate is not charged and is counted in "no_rate_rolls":
  rates are recorded from 20 Nov 2026 only, so earlier rolls stay uncharged.

INFERRED, to be checked against the real account through the mirror gap:
OANDA's exact formula converts the base-currency amount; US-dollar notional x
rate / 365 is the same idea at the size of these positions.
"""

from __future__ import annotations

import bisect
from datetime import date, datetime
from typing import Any

from twins import engine
from twins.config import DAILY

WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
YEAR_DAYS = 365


def pairs() -> tuple[str, ...]:
    from research_harness.league.forex import PAIRS
    return PAIRS


def parse(instruments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OANDA instrument details -> one rate row per registered pair. Fails loudly on a missing field."""
    wanted = set(pairs())
    out = []
    for ins in instruments:
        if ins.get("name") not in wanted:
            continue
        fin = ins.get("financing")
        if not isinstance(fin, dict) or "longRate" not in fin or "shortRate" not in fin:
            raise ValueError(f"{ins.get('name')}: OANDA gave no financing rates")
        days = {d["dayOfWeek"]: int(d["daysCharged"]) for d in fin.get("financingDaysOfWeek") or []}
        if set(days) != set(WEEKDAYS):
            raise ValueError(f"{ins['name']}: financingDaysOfWeek is incomplete: {sorted(days)}")
        out.append({"pair": ins["name"], "long_rate": float(fin["longRate"]),
                    "short_rate": float(fin["shortRate"]), "days_charged": days})
    missing = wanted - {r["pair"] for r in out}
    if missing:
        raise ValueError(f"OANDA instrument list is missing {sorted(missing)}")
    return out


def _roll_date(step: Any, bars_kind: str) -> date | None:
    """The New York date of a 17:00 roll at the close of this step, or None."""
    if bars_kind == DAILY:                          # league forex bars: one per forex day, labelled by its close
        return step
    close = engine.step_close(step, bars_kind).astimezone(engine.NEW_YORK)
    return close.date() if close.time() == engine.FOREX_DAY_CLOSE else None


def apply(curve: list[tuple[Any, float, float]], fills: list[dict[str, Any]], bars: dict[str, list[dict[str, Any]]],
          bars_kind: str, rates: list[dict[str, Any]]) -> tuple[list[tuple[Any, float, float]], dict[str, Any]]:
    """The curve with financing added from each roll on, plus a summary."""
    pair_of = {engine.synthetic(p): p for p in pairs()}
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(rates, key=lambda r: r["day"]):
        by_pair.setdefault(r["pair"], []).append(r)
    keys = {p: [r["day"] for r in rows] for p, rows in by_pair.items()}
    closes = {s: {b["day"]: b["close"] for b in rows} for s, rows in bars.items()}
    order = sorted(fills, key=lambda f: (f["filled_at"], f["symbol"], f["n"]))

    held: dict[str, float] = {}
    i, cum, rolls, no_rate = 0, 0.0, 0, 0
    out = []
    for step, eq, gross in curve:
        roll = _roll_date(step, bars_kind)
        if roll is not None:
            at = engine.step_close(step, bars_kind)
            while i < len(order) and order[i]["filled_at"] <= at:
                f = order[i]
                held[f["symbol"]] = held.get(f["symbol"], 0.0) + f["qty"]
                i += 1
            for sym, qty in held.items():
                if abs(qty) < 1e-9 or sym not in pair_of:
                    continue
                pair = pair_of[sym]
                j = bisect.bisect_left(keys.get(pair, []), roll)     # rates read the evening before
                px = closes.get(sym, {}).get(step)
                if not j or px is None:
                    no_rate += 1
                    continue
                r = by_pair[pair][j - 1]
                long_synth = qty > 0
                same_side = sym == pair                      # XXX_USD: the synthetic is the pair
                rate = r["long_rate"] if long_synth == same_side else r["short_rate"]
                days = int(r["days_charged"][WEEKDAYS[roll.weekday()]])
                cum += abs(qty) * px * rate * days / YEAR_DAYS
                rolls += 1
        out.append((step, eq + cum, gross))
    return out, {"financing_usd": round(cum, 2), "rolls_charged": rolls, "no_rate_rolls": no_rate}


def read_and_record(get_conn, now: datetime, client_factory=None) -> int:
    """Read today's rates from OANDA (read-only) and store them. Returns rows added."""
    from twins import store
    if client_factory is None:
        from core.oanda_client import OandaClient as client_factory
    with client_factory() as client:
        rows = parse(client.tradeable_instruments())
    return store.record_fx_rates(get_conn, now.astimezone(engine.NEW_YORK).date(), rows)
