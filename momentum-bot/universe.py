"""Weekly top-50 universe refresh. Race-safe via week-boundary ts + ON CONFLICT."""
import os
import sys
import requests
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_TP   = os.path.abspath(os.path.join(_HERE, "..", "trading-platform"))
if _TP not in sys.path: sys.path.insert(0, _TP)
sys.path.insert(0, _HERE)
from db.postgres import get_conn

COINGECKO_TOP50 = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=50&page=1"
)


def _week_boundary_utc() -> datetime:
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=now.weekday())


def _binance_pair(symbol: str) -> str:
    sym = symbol.upper()
    for candidate in [f"{sym}/USDT", f"1000{sym}/USDT", f"{sym}/USD"]:
        return candidate
    return f"{sym}/USDT"


def refresh_if_needed() -> list:
    week_ts = _week_boundary_utc()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, binance_pair FROM momentum_universe WHERE refresh_ts = %s",
                (week_ts,),
            )
            rows = cur.fetchall()
            if rows:
                return [{"symbol": r[0], "binance_pair": r[1]} for r in rows]
            resp = requests.get(COINGECKO_TOP50, timeout=20)
            resp.raise_for_status()
            coins = resp.json()
            for c in coins:
                sym  = c["symbol"].upper()
                pair = _binance_pair(sym)
                cur.execute(
                    "INSERT INTO momentum_universe "
                    "    (refresh_ts, symbol, market_cap_usd, binance_pair) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (week_ts, sym, c.get("market_cap"), pair),
                )
            cur.execute(
                "SELECT symbol, binance_pair FROM momentum_universe WHERE refresh_ts = %s",
                (week_ts,),
            )
            return [{"symbol": r[0], "binance_pair": r[1]} for r in cur.fetchall()]
