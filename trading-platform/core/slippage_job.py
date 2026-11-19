"""Execution cost measured from the real Alpaca fills (roadmap Phase 1 order 3:
"recalibrated monthly from the real accounts' fills"). Read-only: it lists
filled orders and price bars; it never places, changes or cancels anything.

For every filled order on the three Alpaca paper accounts:
- market orders: the fill price against the price when the order was sent
  (the open of the first one-minute bar at or after it was submitted);
- stop orders: the fill price against the stop price (gaps through a stop);
- limit orders are left out (the price was chosen, not paid).
Slippage is signed as a cost: a buy above the reference, or a sell below it,
is positive basis points.

The monthly summary sets the median measured cost beside the league's cost
model (twins.config.SHARE_COSTS: 2 bps half spread + 3 bps slippage = 5 bps a
trade). Nothing changes the model automatically: a gap is a decision for
Markus, applied going forward as a new dated version, never to history.
"""

from __future__ import annotations

import os
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from loguru import logger

from core.live_check_job import ACCOUNT_KEYS
from core.no_crypto import is_crypto

MODEL_BPS = 5.0              # twins.config.SHARE_COSTS: half spread 2 + slippage 3 (test checks it)
LOOKBACK_DAYS = 5            # each night re-reads the last few days; stored orders are skipped
DDL = """
CREATE TABLE IF NOT EXISTS execution_slippage (
    order_id      TEXT PRIMARY KEY,
    bot_id        TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL,
    order_type    TEXT NOT NULL,
    qty           DOUBLE PRECISION NOT NULL,
    fill_price    DOUBLE PRECISION NOT NULL,
    ref_price     DOUBLE PRECISION NOT NULL,
    ref_kind      TEXT NOT NULL,
    submitted_at  TIMESTAMPTZ,
    filled_at     TIMESTAMPTZ NOT NULL,
    slippage_bps  DOUBLE PRECISION NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def cost_bps(side: str, fill: float, ref: float) -> float:
    """Signed as a cost: buying above, or selling below, the reference is positive."""
    sign = 1.0 if side == "buy" else -1.0
    return round(sign * (fill / ref - 1) * 1e4, 3)


def first_minute_open(bars: list[dict[str, Any]], at: datetime) -> float | None:
    """The open of the first one-minute bar starting at or after ``at``'s minute."""
    floor = at.replace(second=0, microsecond=0)
    for b in sorted(bars, key=lambda x: x["t"]):
        if _ts(b["t"]) >= floor:
            return float(b["o"])
    return None


def measure(bot_id: str, order: Any, minute_bars: Callable[[str, datetime, datetime], list[dict[str, Any]]]
            ) -> dict[str, Any] | None:
    """One filled order -> one row, or None (not measurable or not ours to measure)."""
    g = (order.get if isinstance(order, dict) else lambda k: getattr(order, k, None))  # legs may be plain dicts
    qty, fill = float(g("filled_qty") or 0), float(g("filled_avg_price") or 0)
    symbol, side, kind = str(g("symbol") or ""), str(g("side") or ""), str(g("type") or g("order_type") or "")
    filled_at, submitted_at = _ts(g("filled_at")), _ts(g("submitted_at"))
    if qty <= 0 or fill <= 0 or not filled_at or side not in ("buy", "sell") or is_crypto(symbol):
        return None
    if kind == "market":
        if not submitted_at:
            return None
        ref = first_minute_open(minute_bars(symbol, submitted_at, filled_at + timedelta(minutes=1)), submitted_at)
        ref_kind = "minute_open_at_submit"
    elif kind in ("stop", "stop_limit"):
        ref = float(g("stop_price") or 0) or None
        ref_kind = "stop_price"
    else:
        return None
    if not ref or ref <= 0:
        return None
    return {"order_id": str(g("id")), "bot_id": bot_id, "symbol": symbol, "side": side, "order_type": kind,
            "qty": qty, "fill_price": fill, "ref_price": ref, "ref_kind": ref_kind, "submitted_at": submitted_at,
            "filled_at": filled_at, "slippage_bps": cost_bps(side, fill, ref)}


def minute_fetcher(api) -> Callable[[str, datetime, datetime], list[dict[str, Any]]]:
    def fetch(symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        for feed in ("sip", "iex"):
            try:
                raw = api.get_bars(symbol, "1Min", start=start.replace(second=0, microsecond=0).isoformat(),
                                   end=end.isoformat(), adjustment="raw", feed=feed)
                return [{"t": b["t"], "o": b["o"]} for b in raw._raw]
            except Exception:                  # the next feed; an empty answer means not measurable
                continue
        return []
    return fetch


def run_daily(now: datetime | None = None, *, api_factory: Callable[[str], Any] | None = None,
              get_conn=None) -> dict[str, Any]:
    """Measure every filled order from the last few days not measured yet."""
    if get_conn is None:
        from db.postgres import get_conn
    if api_factory is None:
        from core.broker_http import alpaca_rest

        def api_factory(bot_id: str):
            key, secret = ACCOUNT_KEYS[bot_id]
            return alpaca_rest(os.environ.get(key, ""), os.environ.get(secret, ""),
                               base_url="https://paper-api.alpaca.markets")
    now = now or datetime.now(timezone.utc)
    after = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("SELECT order_id FROM execution_slippage WHERE filled_at >= %s", (after,))
        have = {r[0] for r in cur.fetchall()}
    report: dict[str, Any] = {}
    for bot_id in ACCOUNT_KEYS:
        try:
            api = api_factory(bot_id)
            orders = api.list_orders(status="closed", after=after, limit=500, direction="asc", nested=True)
            flat = []
            for o in orders:                       # bracket legs (stops) are nested under their parent
                flat.append(o)
                flat += list(getattr(o, "legs", None) or [])
            oid = lambda o: str(o.get("id") if isinstance(o, dict) else getattr(o, "id", ""))  # noqa: E731
            rows = [r for o in flat if oid(o) not in have
                    and (r := measure(bot_id, o, minute_fetcher(api)))]
        except Exception as exc:
            logger.warning(f"slippage | {bot_id}: orders unreadable: {type(exc).__name__}: {exc}")
            report[bot_id] = f"unreadable: {type(exc).__name__}"
            continue
        with get_conn() as conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    "INSERT INTO execution_slippage (order_id, bot_id, symbol, side, order_type, qty, fill_price, "
                    "ref_price, ref_kind, submitted_at, filled_at, slippage_bps) VALUES "
                    "(%(order_id)s, %(bot_id)s, %(symbol)s, %(side)s, %(order_type)s, %(qty)s, %(fill_price)s, "
                    "%(ref_price)s, %(ref_kind)s, %(submitted_at)s, %(filled_at)s, %(slippage_bps)s) "
                    "ON CONFLICT (order_id) DO NOTHING", r)
        report[bot_id] = {"measured": len(rows)}
    return report


def summary(get_conn, month: date) -> dict[str, Any]:
    """Median and mean measured cost per account and order type for a month, beside the model."""
    end = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("SELECT bot_id, order_type, slippage_bps FROM execution_slippage "
                    "WHERE filled_at >= %s AND filled_at < %s", (month, end))
        rows = cur.fetchall()
    groups: dict[str, list[float]] = {}
    for bot_id, kind, bps in rows:
        groups.setdefault(f"{bot_id}:{'market' if kind == 'market' else 'stop'}", []).append(float(bps))
    market = [b for k, v in groups.items() if k.endswith(":market") for b in v]
    out = {"month": f"{month:%Y-%m}", "model_bps": MODEL_BPS, "groups": {
        k: {"fills": len(v), "median_bps": round(statistics.median(v), 2), "mean_bps": round(statistics.fmean(v), 2)}
        for k, v in sorted(groups.items())}}
    out["market_fills"] = ({"fills": len(market), "median_bps": round(statistics.median(market), 2),
                             "above_model": statistics.median(market) > MODEL_BPS} if market else {"fills": 0})
    return out
