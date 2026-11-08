"""The 2027 comparison: the three paper accounts and the S&P 500 on the same days.

GET /fleet/comparison returns, from the run start (core.fleet_capital.RUN_START):
- `rows`: per common day, each account's return since the first common day and
  SPY's, for the home chart (one line per account, S&P in white);
- `accounts`: per account, return, SPY over the same days, worst fall and
  (from 20 days) annualised Sharpe;
- `fleet`: the same stats for all four accounts together (incl. Forex), plus
  (from 20 days) annualised return and volatility, for the Home headline.

Account equity is bot_daily_returns.equity_close, broker equity including the
vault (VAULT-V2 section 3: a skim never makes an account look worse). SPY is
benchmark_snapshots.spy_close (price return). Every figure is computed here;
the browser only formats it.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from fastapi import APIRouter
from loguru import logger

comparison_router = APIRouter()

from core.fleet_capital import RUN_START, START_EQUITY

ACCOUNTS = ("oracle", "spy_qqq_trend", "jerome_macro")
FLEET = tuple(START_EQUITY)
CUTOVER = RUN_START
MIN_SHARPE_DAYS = 20


def _stats(values: list[float]) -> dict[str, Any]:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    rets = [b / a - 1 for a, b in zip(values, values[1:])]
    sharpe = vol = annual = None
    if len(rets) >= MIN_SHARPE_DAYS:
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        sharpe = round(mean / sd * math.sqrt(252), 2) if sd > 0 else None
        vol = round(sd * math.sqrt(252), 6)
        annual = round((values[-1] / values[0]) ** (252 / len(rets)) - 1, 6)
    return {"return": round(values[-1] / values[0] - 1, 6), "worst_fall": round(worst, 6), "sharpe": sharpe,
            "volatility": vol, "annual": annual}


def race_view(equity: dict[str, dict[str, float]], spy: dict[str, float], since: str = CUTOVER) -> dict[str, Any]:
    """Pure. `equity[bot][day]` and `spy[day]` are closes keyed by ISO date.
    Uses only days on which SPY and every account with data have a close."""
    present = [b for b in ACCOUNTS if equity.get(b)]
    days = sorted(d for d in spy if d >= since and spy[d] and all(equity[b].get(d) for b in present))
    out: dict[str, Any] = {"since": since, "days": len(days), "rows": [], "spy": None, "fleet": None,
                           "accounts": {b: None for b in ACCOUNTS},
                           "note": "Same days for every line; accounts on total equity incl. vault; SPY price return"}
    if len(days) < 2 or not present:
        return out
    first = days[0]
    for d in days:
        row: dict[str, Any] = {"date": d, "spy": round(spy[d] / spy[first] - 1, 6)}
        for b in present:
            row[b] = round(equity[b][d] / equity[b][first] - 1, 6)
        out["rows"].append(row)
    out["spy"] = _stats([spy[d] for d in days])
    fleet_days = [d for d in days if all(equity.get(b, {}).get(d) for b in FLEET)]
    if len(fleet_days) >= 2:
        out["fleet"] = {**_stats([sum(equity[b][d] for b in FLEET) for d in fleet_days]), "days": len(fleet_days)}
    for b in present:
        out["accounts"][b] = {**_stats([equity[b][d] for d in days]), "spy_same_days": out["spy"]["return"],
                              "equity": round(equity[b][days[-1]], 2)}
    return out


@comparison_router.get("/fleet/comparison", tags=["Fleet"])
async def fleet_comparison(since: str = CUTOVER) -> dict[str, Any]:
    def read() -> dict[str, Any]:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return race_view({}, {}, since)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bot_id, date::text, equity_close FROM bot_daily_returns
                    WHERE bot_id = ANY(%s) AND date >= %s::date AND equity_close IS NOT NULL
                      AND COALESCE(source, '') <> 'portfolio_with_vault_exclusion'
                    """, (list(FLEET), since))
                equity: dict[str, dict[str, float]] = {}
                for bot_id, day, eq in cur.fetchall():
                    equity.setdefault(bot_id, {})[day] = float(eq)
                cur.execute("SELECT snapshot_date::text, spy_close FROM benchmark_snapshots "
                            "WHERE snapshot_date >= %s::date AND spy_close IS NOT NULL", (since,))
                spy = {d: float(c) for d, c in cur.fetchall()}
        return race_view(equity, spy, since)

    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        logger.error(f"comparison | read failed: {type(exc).__name__}: {exc}")
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="comparison unavailable")
