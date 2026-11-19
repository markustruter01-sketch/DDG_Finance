"""The Allocator in shadow (roadmap Phase 3, rules version). No orders.

Nightly, inside the league run (it has the prices and the S&P 500 list): the
regime label for each session asked about is written once to the append-only
allocator_labels table. The two shadow funds ("equal", "rules") are then
computed from those labels and the league lines' own values
(research_harness/league/allocator.run_fund): deterministic, so the
leaderboard recomputes them on every read. After the replay, check() raises
one alarm the first time a fund falls 15% from its high (it then holds cash).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from research_harness.harness.portfolio import HistoryView
from research_harness.league import allocator as alloc
from twins import engine, store
from twins.config import DAILY

START_EQUITY = 100_000.0
FUNDS = {"equal": "ALLOC-EQUAL", "rules": "ALLOC-RULES"}
NAMES = {"equal": "Allocator (a): equal money to every line", "rules": "Allocator (b): rules by regime"}


def record_labels(get_conn, view: HistoryView, universe: tuple[str, ...], days: list[date], now: datetime) -> dict:
    out = {}
    for d in days:
        view.today = d
        m = alloc.measurements(view, universe)
        if m is None:
            out[d.isoformat()] = "not enough data"
            continue
        lab = alloc.label(m)
        store.record_label(get_conn, d, lab, m, now)
        out[d.isoformat()] = lab
    return out


def inputs(get_conn) -> dict[str, Any]:
    """Labels, and each current-version league line's daily returns, family and exposure."""
    from twins import league

    labels = {r["day"]: r["label"] for r in store.labels(get_conn)}
    returns, families, exposure, days = {}, {}, {}, set()
    for acct in store.accounts(get_conn):
        if acct["bot_id"] != league.LEAGUE_BOT or acct["version"] != league.LEAGUE_VERSION:
            continue
        sid, fam = acct["config"].get("registration"), acct["config"].get("family")
        rows = [r for r in store.equity_rows(get_conn, acct["twin_id"]) if r["equity"]]
        prev = acct["start_equity"]
        returns[sid] = {}
        for r in rows:
            returns[sid][r["day"]] = r["equity"] / prev - 1
            prev = r["equity"]
            days.add(r["day"])
        decs = sorted((engine.step_of(d["step_at"], DAILY), d["weights"])
                      for d in store.decisions(get_conn, acct["twin_id"]) if not d["missed"])
        exposure[sid], k, cur = {}, 0, None
        for r in rows:
            while k < len(decs) and decs[k][0] <= r["day"]:
                cur = decs[k][1]
                k += 1
            exposure[sid][r["day"]] = alloc.line_exposure(cur)
        if fam != "yardstick":
            families[sid] = fam
    return {"labels": labels, "returns": returns, "families": families, "exposure": exposure,
            "days": sorted(d for d in days if labels and d >= min(labels))}


def funds(get_conn) -> dict[str, dict[str, Any]]:
    x = inputs(get_conn)
    if not x["days"] or alloc.CASH_LINE not in x["returns"] or not x["families"]:
        return {}
    return {mode: alloc.run_fund(mode, x["days"], x["labels"], x["returns"], x["families"], x["exposure"])
            for mode in FUNDS}


def lines_for_board(get_conn) -> tuple[list[dict[str, Any]], str | None]:
    """Leaderboard rows for the two funds, and the latest regime label."""
    rows = []
    for mode, res in funds(get_conn).items():
        rows.append({"id": FUNDS[mode], "name": NAMES[mode], "kind": "allocator", "family": "allocator",
                     "start_equity": START_EQUITY,
                     "curve": [(d, START_EQUITY * e) for d, e in res["curve"]],
                     "decisions": [(x["day"], {k: v for k, v in x["weights"].items()}) for x in res["decisions"]]})
    labs = store.labels(get_conn)
    return rows, (labs[-1]["label"] if labs else None)


def check(get_conn, now: datetime, alarm: Callable[..., None]) -> dict[str, Any]:
    out = {}
    for mode, res in funds(get_conn).items():
        out[mode] = {"equity": round(res["curve"][-1][1], 6) if res["curve"] else None,
                     "tripped": res["tripped"].isoformat() if res["tripped"] else None}
        kind = f"allocator_tripped_{mode}"
        if res["tripped"] and not store.last_change(get_conn, (kind,)):
            store.log_change(get_conn, kind=kind, source="twins:allocator", at=now,
                             summary=f"shadow fund {FUNDS[mode]} fell 15% from its high on {res['tripped']}: "
                                     "now all cash until a human resets it",
                             detail={"tripped": res["tripped"].isoformat()})
            alarm("error", "allocator_fund_stopped",
                  f"Shadow fund {FUNDS[mode]} fell 15% from its high ({res['tripped']}) and moved to cash. "
                  "It stays in cash until Markus resets it. No real money is involved.")
    return out
