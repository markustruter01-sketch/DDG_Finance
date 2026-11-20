"""Shadow League leaderboard (roadmap Phase 1, item 4). Read-only.

One row per line: the four real accounts (each one's real equity as recorded
beside its mirror twin), the three yardsticks and the shadows. Every figure is
computed here from the twins tables; the dashboard only formats it.

Columns:
- return after costs since the line started;
- worst fall (largest peak-to-trough drop of daily equity);
- days in cash: sessions whose latest decision held only BIL (T-bills). From
  the decision log, so a day a stop emptied a holding is not counted (shadows);
  real accounts: not computed (null);
- gap to the S&P 500: the line's return minus Y-SPX's over the same days;
- curve: [day, return % since start] for every valued day (League page charts);
- luck check: deflated Sharpe ratio adjusted for the number of shadows tried
  (research_harness/harness/overfit.deflated_sharpe). "clear" at DSR >= 0.95,
  "could be luck" below, "too few days" under MIN_LUCK_DAYS. The 0.95 and the
  day minimum are PROVISIONAL (Opus 19 Nov): Markus fixes them before the lock.
"""

from __future__ import annotations

import bisect
from datetime import date
from typing import Any

from core.fleet_capital import RUN_START, bot_starting_capital
from research_harness.harness.overfit import deflated_sharpe, sharpe_per_period, variance
from research_harness.league.base import CASH

N_TRIALS = 16          # shadows declared in the roadmap (the forex three included), counted up front
MIN_LUCK_DAYS = 60
LUCK_CLEAR = 0.95
REAL_BOTS = ("oracle", "jerome_macro", "spy_qqq_trend", "forex_ai")
COUNCIL_BOT, COUNCIL_LINE = "forex_ai", "FX-COUNCIL"     # registrations/league/FX-COUNCIL.json


def worst_fall(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def daily_returns(curve: list[tuple[date, float]]) -> list[float]:
    return [curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve)) if curve[i - 1][1] > 0]


def days_in_cash(curve_days: list[date], decisions: list[tuple[date, dict[str, float] | None]]) -> int | None:
    live = sorted(((d, w) for d, w in decisions if w is not None), key=lambda x: x[0])   # same day: keep order
    if not live:
        return None
    keys = [d for d, _ in live]
    n = 0
    for day in curve_days:
        i = bisect.bisect_right(keys, day)
        if i and set(live[i - 1][1]) <= {CASH, "Y-CASH"}:      # T-bills, or an Allocator fund's cash line
            n += 1
    return n


def build(lines: list[dict[str, Any]], n_trials: int) -> list[dict[str, Any]]:
    """lines: dicts with id, name, kind (real/yardstick/shadow), family, start_equity,
    curve [(day, equity)], decisions [(day, weights)] (shadows only)."""
    spx = next((ln for ln in lines if ln["id"] == "Y-SPX"), None)
    spx_by_day = dict(spx["curve"]) if spx else {}
    shadow_sharpes = [sharpe_per_period(daily_returns(ln["curve"])) for ln in lines
                      if ln["kind"] == "shadow" and len(ln["curve"]) > 2]
    var_sr = variance(shadow_sharpes) if len(shadow_sharpes) > 1 else 0.0
    out = []
    for ln in lines:
        curve = [(d, v) for d, v in ln["curve"] if v and v > 0]
        row: dict[str, Any] = {k: ln[k] for k in ("id", "name", "kind", "family")}
        row.update(days=len(curve), first_day=curve[0][0].isoformat() if curve else None,
                   last_day=curve[-1][0].isoformat() if curve else None, equity=None, return_pct=None,
                   worst_fall_pct=None, days_in_cash=None, gap_to_spx_pp=None, luck=None, dsr=None,
                   curve=[])
        if not curve:
            out.append(row)
            continue
        base = ln.get("start_equity") or curve[0][1]
        ret = curve[-1][1] / base - 1
        row.update(equity=round(curve[-1][1], 2), return_pct=round(100 * ret, 2),
                   worst_fall_pct=round(100 * worst_fall([base] + [v for _, v in curve]), 2),
                   curve=[[d.isoformat(), round(100 * (v / base - 1), 3)] for d, v in curve])
        if ln["kind"] != "real":
            row["days_in_cash"] = days_in_cash([d for d, _ in curve], ln.get("decisions") or [])
        same = [(d, spx_by_day[d]) for d, _ in curve if d in spx_by_day]
        if spx and same and ln["id"] != "Y-SPX":
            first = same[0][0]
            mine = dict(curve)
            spx_ret = same[-1][1] / spx_by_day[first] - 1
            line_ret = mine[same[-1][0]] / mine[first] - 1
            row["gap_to_spx_pp"] = round(100 * (line_ret - spx_ret), 2)
        r = daily_returns(curve)
        if len(r) < MIN_LUCK_DAYS:
            row["luck"] = "too few days"
        elif ln["kind"] == "shadow":
            dsr = deflated_sharpe(r, None, n_trials, var_sr)["dsr"]
            row["dsr"] = round(dsr, 4)
            row["luck"] = "clear" if dsr >= LUCK_CLEAR else "could be luck"
        out.append(row)
    order = {"human": 0, "real": 1, "yardstick": 2, "ai": 3, "shadow": 4, "allocator": 5}
    return sorted(out, key=lambda x: (order.get(x["kind"], 3), -(x["return_pct"] if x["return_pct"] is not None
                                                                   else -1e9)))


def read(get_conn) -> dict[str, Any]:
    """Every line's curve from the twins tables (current league version only)."""
    from core.bot_registry import display_name
    from research_harness.league import families
    from twins import engine, league, store
    from twins.config import DAILY

    lines: list[dict[str, Any]] = []
    for acct in store.accounts(get_conn):
        if acct["bot_id"] == league.LEAGUE_BOT:
            if acct["version"] != league.LEAGUE_VERSION:
                continue
            sid = acct["config"].get("registration")
            strat = families.BY_ID.get(sid)
            rows = store.equity_rows(get_conn, acct["twin_id"])
            decs = [(engine.step_of(r["step_at"], DAILY), r["weights"])
                    for r in store.decisions(get_conn, acct["twin_id"])]
            lines.append({"id": sid, "name": strat.name if strat else sid, "kind": acct["kind"],
                          "family": acct["config"].get("family"), "start_equity": acct["start_equity"],
                          "curve": [(r["day"], r["equity"]) for r in rows], "decisions": decs})
        elif acct["kind"] == "mirror" and acct["bot_id"] in REAL_BOTS:
            rows = store.equity_rows(get_conn, acct["twin_id"])
            # The real account on the board = the same numbers as Home (21 Nov fix): each day's closing
            # balance (bot_daily_returns) against its start balance on RUN_START (core/fleet_capital.py).
            # The mirror twin's own reference balances measure the share book only, so they jumped when
            # Atlas V2's last crypto was sold for cash on 17 Nov and showed +7.9% while Home showed -5.6%.
            lines.append({"id": acct["bot_id"], "name": display_name(acct["bot_id"]), "kind": "real",
                          "family": "real account", "start_equity": bot_starting_capital(acct["bot_id"]),
                          "curve": real_closes(get_conn, acct["bot_id"])})
            if acct["bot_id"] == COUNCIL_BOT:      # the council's shadow line = its mirror, engine-valued
                decs = [(r["step_at"].astimezone(engine.NEW_YORK).date(), r["weights"])
                        for r in store.decisions(get_conn, acct["twin_id"]) if not r["missed"]]
                lines.append({"id": COUNCIL_LINE, "name": "Forex AI council (mirror twin)", "kind": "shadow",
                              "family": "forex", "start_equity": acct["start_equity"],
                              "curve": [(r["day"], r["equity"]) for r in rows if r["equity"]], "decisions": decs})
    lines += _ai_and_human(get_conn)
    from twins import allocator
    fund_rows, regime = allocator.lines_for_board(get_conn)
    lines += fund_rows
    n_trials = max(N_TRIALS, sum(1 for ln in lines if ln["kind"] == "shadow"))
    return {"league_version": league.LEAGUE_VERSION,
            "note": ("Version 0 is the proving run, not the record." if league.LEAGUE_VERSION == 0 else ""),
            "luck_rule": {"clear_at_dsr": LUCK_CLEAR, "min_days": MIN_LUCK_DAYS, "n_trials": n_trials,
                          "status": "provisional"},
            "regime": regime,
            "rows": build(lines, n_trials)}


def real_closes(get_conn, bot_id: str) -> list[tuple[date, float]]:
    """A real account's closing balance each day from RUN_START, as Home reads it (/fleet/bot-history)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT date, equity_close FROM bot_daily_returns WHERE bot_id = %s AND date >= %s "
                    "AND equity_close IS NOT NULL AND COALESCE(source, '') <> 'portfolio_with_vault_exclusion' "
                    "ORDER BY date", (bot_id, RUN_START))
        return [(d, float(v)) for d, v in cur.fetchall()]


def _ai_and_human(get_conn) -> list[dict[str, Any]]:
    """The AI twins (current version) and Markus's own account (newest version)."""
    from core.bot_registry import display_name
    from twins import ai_council, engine, human, store
    from twins.config import DAILY

    want = {t.twin_id: t for t in ai_council.twins()}
    accts = store.accounts(get_conn)
    mine = sorted((a for a in accts if a["bot_id"] == human.HUMAN_BOT), key=lambda a: a["version"])[-1:]
    out = []
    for acct in [a for a in accts if a["twin_id"] in want] + mine:
        rows = store.equity_rows(get_conn, acct["twin_id"])
        decs = [(engine.step_of(r["step_at"], DAILY), r["weights"]) for r in store.decisions(get_conn, acct["twin_id"])]
        if acct["kind"] == "human":
            line = {"id": "HUMAN", "name": "Markus" + (" (practice)" if acct["version"] == 0 else ""),
                    "kind": "human", "family": "human"}
        else:
            tw = want[acct["twin_id"]]
            name = (f"{display_name(tw.base)} with AI" if tw.kind == "ai"
                    else f"{tw.base}, AI may cut or skip")
            line = {"id": f"AI-{tw.base}", "name": name, "kind": "ai", "family": "ai"}
        out.append({**line, "start_equity": acct["start_equity"],
                    "curve": [(r["day"], r["equity"]) for r in rows if r["equity"]], "decisions": decs})
    return out


def records(get_conn) -> dict[str, Any]:
    """Record keeping at a glance (Home card): decision logs intact, last league
    night, last frozen month, trade costs vs the model, outside heartbeat set up."""
    import os
    from datetime import date as _date

    from core.slippage_job import MODEL_BPS, summary
    from twins import store

    accts = store.accounts(get_conn, active_only=False)
    broken = [a["twin_id"] for a in accts if store.verify_chain(store.decisions(get_conn, a["twin_id"]))]
    last_run = store.last_change(get_conn, ("league_run",), "league")
    frozen = store.frozen(get_conn)
    costs = summary(get_conn, _date.today().replace(day=1))
    return {
        "logs": {"lines": len(accts), "broken": broken},
        "league_last_run": last_run["at"].isoformat() if last_run and last_run.get("at") else None,
        "last_frozen_month": max((f["month"] for f in frozen), default=None),
        "costs": {"model_bps": MODEL_BPS, **costs.get("market_fills", {})},
        "heartbeat": {"runner": bool(os.getenv("HEARTBEAT_URL_RUNNER", "").strip()),
                      "api": bool(os.getenv("HEARTBEAT_URL_API", "").strip())},
    }
