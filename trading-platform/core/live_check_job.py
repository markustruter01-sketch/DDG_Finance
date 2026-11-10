"""Daily live-versus-research check and its monthly report (plan Step 2 item 12).

The comparison itself is sleeve_runtime/live_check.py (pure, read-only). This
module wires it: bots_state for each sleeve's last decision, bot_portfolio for
holdings, each account's own Alpaca keys for its live feed, Yahoo for the
research feed; one row per account per day in live_research_check. On the
first weekday of a month the previous month's summary goes to Discord.
Published deployment only (the scheduler checks). No orders, no bots_state writes.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.append(_ROOT)  # sleeve_runtime and research_harness live at the repo root

# Same key names the Home page's live positions use (routes/portfolio.py).
ACCOUNT_KEYS = {
    "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
    "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
}
STATE_KEYS = {"oracle": "fleet_v1_f1", "jerome_macro": "fleet_v1_c1", "spy_qqq_trend": "momo_v2"}

DDL = """
CREATE TABLE IF NOT EXISTS live_research_check (
    day DATE NOT NULL, bot_id TEXT NOT NULL, payload JSONB NOT NULL,
    flagged BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (day, bot_id))
"""


def _cached(fetch):
    """Share downloads between accounts in one run (F1 and C1 read the same ETFs)."""
    memo: dict[tuple[str, date], list] = {}

    def wrapped(symbols: list[str], start: date):
        need = [s for s in symbols if (s, start) not in memo]
        if need:
            for s, rows in fetch(need, start).items():
                memo[(s, start)] = rows
        return {s: memo.get((s, start), []) for s in symbols}
    return wrapped


def run_daily(now: datetime | None = None) -> dict[str, Any]:
    import alpaca_trade_api as tradeapi

    from core import bot_state
    from core.cash_park import CASH_PARK_SYMBOLS
    from db.postgres import get_conn
    from execution.per_bot_vault import VAULT_BIL_SYMBOL, VAULT_VOO_SYMBOL
    from sleeve_runtime import live_check
    from sleeve_runtime.trend_v1b import alpaca_bar_fetcher

    now = now or datetime.now(timezone.utc)
    research = _cached(live_check.yahoo_fetcher())
    portfolios = {p["bot_id"]: p for p in bot_state.get_all_portfolios()}
    rows: dict[str, dict[str, Any]] = {}
    for bot_id, (key_env, secret_env) in ACCOUNT_KEYS.items():
        api = tradeapi.REST(os.environ.get(key_env, ""), os.environ.get(secret_env, ""),
                            base_url="https://paper-api.alpaca.markets")
        p = portfolios.get(bot_id) or {}
        state = (bot_state.read_metadata(bot_id) or {}).get(STATE_KEYS[bot_id], {})
        rows[bot_id] = live_check.check_account(
            bot_id, live_fetch=alpaca_bar_fetcher(api), research_fetch=research, state=state,
            equity=p.get("equity_usd"), positions=p.get("positions"), now=now,
            vault={VAULT_BIL_SYMBOL, VAULT_VOO_SYMBOL}, cash_park=set(CASH_PARK_SYMBOLS))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        for bot_id, row in rows.items():
            cur.execute(
                "INSERT INTO live_research_check (day, bot_id, payload, flagged) VALUES (%s, %s, %s::jsonb, %s) "
                "ON CONFLICT (day, bot_id) DO UPDATE SET payload = EXCLUDED.payload, flagged = EXCLUDED.flagged, created_at = now()",
                (row.get("day") or now.date().isoformat(), bot_id, json.dumps(row, default=str), bool(row["flags"])))
    for bot_id, row in rows.items():
        logger.info(f"Live vs research | {bot_id} | {row.get('kind')} | flags: {row['flags'] or 'none'}")
    return rows


def month_summary(month: str) -> dict[str, Any]:
    """month = 'YYYY-MM'. Reads the stored rows; computes nothing new."""
    from db.postgres import get_conn
    from sleeve_runtime import live_check

    first = date.fromisoformat(f"{month}-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    rows: list[dict[str, Any]] = []
    with get_conn() as conn, conn.cursor() as cur:  # read-only: no DDL here
        cur.execute("SELECT to_regclass('public.live_research_check')")
        if cur.fetchone()[0] is not None:
            cur.execute("SELECT bot_id, day, payload FROM live_research_check WHERE day >= %s AND day < %s ORDER BY day",
                        (first, nxt))
            rows = [{"bot_id": b, "day": d, "payload": p if isinstance(p, dict) else json.loads(p)}
                    for b, d, p in cur.fetchall()]
    summary = live_check.monthly_summary(rows, month)
    summary["lines"] = live_check.summary_lines(summary)
    return summary


def send_monthly(today: date | None = None) -> dict[str, Any]:
    """On the first weekday of a month: last month's summary to Discord."""
    from notifications.discord import COLOR_AMBER, COLOR_GREEN, _embed, _send_async

    today = today or datetime.now(timezone.utc).date()
    last = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    summary = month_summary(f"{last:%Y-%m}")
    flagged = any(b["days_flagged"] for b in summary["bots"].values())
    title = f"DDG Finance · live vs research, {last:%B %Y}: {'⚠️ differences' if flagged else '✅ agrees'}"
    _send_async({"embeds": [_embed(title, "\n".join(summary["lines"])[:3900], COLOR_AMBER if flagged else COLOR_GREEN)]},
                alert_type="live_vs_research", title=title)
    return summary
