"""2027 predictions: Markus and the three AI council members each lock a thesis
before 2027 starts (Markus asked 20 Nov 2026 16:59 Brisbane).

Each entry: a short macro thesis in words, plus a forecast for every market
below (direction and % change from the 31 Dec 2026 close to the 31 Dec 2027
close) and three US numbers for December 2027. Entries are append-only; until
the lock any author may file again (every version is kept), and the newest
entry filed before the lock is the one scored. After the lock nothing can be
filed for 2027. The predictions never bind anyone's trades: they are scored
on their own.

Scoring (January 2028, from prices and FRED, stated now so nobody can bend it):
- Markets: 1 point for each right direction ("flat" = within +/-2%), then the
  average miss in percentage points between forecast and actual change.
- US numbers: average miss for CPI inflation (Dec/Dec %, FRED CPIAUCSL), the
  Fed funds upper target (FRED DFEDTARU, 31 Dec 2027) and unemployment
  (FRED UNRATE, Dec 2027).
- Most right is: most direction points; ties broken by the smaller average miss.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from twins import engine

YEAR = 2027
LOCK_AT = datetime(YEAR, 1, 1, 0, 0, tzinfo=engine.NEW_YORK)
FLAT_BAND_PCT = 2.0
MAX_THESIS = 4000

# key: (label, priced by) — ETFs from Alpaca, pairs from OANDA daily candles
MARKETS: dict[str, tuple[str, str]] = {
    "SPY": ("US shares, S&P 500 (SPY)", "SPY"),
    "QQQ": ("US tech, Nasdaq 100 (QQQ)", "QQQ"),
    "IEF": ("US 7-10 year Treasury bonds (IEF)", "IEF"),
    "GLD": ("Gold (GLD)", "GLD"),
    "DBC": ("Broad commodities (DBC)", "DBC"),
    "UUP": ("US dollar index (UUP)", "UUP"),
    "EUR_USD": ("EUR/USD", "EUR_USD"),
    "USD_JPY": ("USD/JPY", "USD_JPY"),
    "AUD_USD": ("AUD/USD", "AUD_USD"),
}
MACRO: dict[str, str] = {
    "us_cpi_2027_pct": "US CPI inflation, Dec 2026 to Dec 2027 (%)",
    "fed_funds_upper_end_2027": "Fed funds target, upper bound, 31 Dec 2027 (%)",
    "us_unemployment_dec_2027": "US unemployment rate, Dec 2027 (%)",
}
DIRECTIONS = ("up", "flat", "down")

DDL = """
CREATE TABLE IF NOT EXISTS year_predictions (
    id          BIGSERIAL PRIMARY KEY,
    year        INTEGER NOT NULL,
    author      TEXT NOT NULL,            -- 'Markus' or a council role (member_1..3)
    model       TEXT,                     -- the AI model that wrote it, if any
    thesis      TEXT NOT NULL,
    forecasts   JSONB NOT NULL,
    filed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_hash   TEXT,
    hash        TEXT NOT NULL
);
DO $$ BEGIN
  CREATE TRIGGER year_predictions_append_only BEFORE UPDATE OR DELETE ON year_predictions
  FOR EACH ROW EXECUTE FUNCTION twins_append_only();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""


def ensure_schema(get_conn) -> None:
    from twins import store
    store.ensure_schema(get_conn)                # creates twins_append_only()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(DDL)


def check(thesis: str, forecasts: dict[str, Any]) -> dict[str, Any]:
    """The forecasts in the stored shape; ValueError if anything is missing or odd."""
    thesis = (thesis or "").strip()
    if len(thesis) < 50:
        raise ValueError("write the thesis in at least a few sentences (50+ characters)")
    if len(thesis) > MAX_THESIS:
        raise ValueError(f"thesis is longer than {MAX_THESIS} characters")
    out: dict[str, Any] = {"markets": {}, "macro": {}}
    markets = forecasts.get("markets") or {}
    for key in MARKETS:
        m = markets.get(key)
        if not isinstance(m, dict) or m.get("direction") not in DIRECTIONS:
            raise ValueError(f"{key}: direction must be up, flat or down")
        pct = m.get("change_pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not -90 <= pct <= 300:
            raise ValueError(f"{key}: change % must be a number between -90 and 300")
        d = m["direction"]
        if (d == "up" and pct <= 0) or (d == "down" and pct >= 0) or (d == "flat" and abs(pct) > FLAT_BAND_PCT):
            raise ValueError(f"{key}: direction {d} does not match {pct}%")
        out["markets"][key] = {"direction": d, "change_pct": round(float(pct), 2) + 0.0}   # + 0.0: never -0.0 (see store._no_negative_zero)
    macro = forecasts.get("macro") or {}
    for key in MACRO:
        v = macro.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not -5 <= v <= 30:
            raise ValueError(f"{key}: a number between -5 and 30")
        out["macro"][key] = round(float(v), 2) + 0.0
    return out


def _hash(prev: str | None, row: dict[str, Any]) -> str:
    body = json.dumps({"prev": prev, **row}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def file(get_conn, now: datetime, *, author: str, thesis: str, forecasts: dict[str, Any],
         model: str | None = None) -> dict[str, Any]:
    if now >= LOCK_AT:
        raise ValueError(f"{YEAR} predictions locked at the start of {YEAR}")
    clean = check(thesis, forecasts)
    ensure_schema(get_conn)
    row = {"year": YEAR, "author": author, "model": model, "thesis": thesis.strip(), "forecasts": clean,
           "filed_at": now.astimezone(timezone.utc).isoformat()}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("LOCK TABLE year_predictions IN SHARE ROW EXCLUSIVE MODE")
        cur.execute("SELECT hash FROM year_predictions ORDER BY id DESC LIMIT 1")
        last = cur.fetchone()
        digest = _hash(last[0] if last else None, row)
        cur.execute("INSERT INTO year_predictions (year, author, model, thesis, forecasts, filed_at, prev_hash, hash) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s) RETURNING id",
                    (YEAR, author, model, row["thesis"], json.dumps(clean), now, last[0] if last else None, digest))
        return {**row, "id": cur.fetchone()[0], "hash": digest}


def read(get_conn) -> dict[str, Any]:
    """The newest entry per author (the one that counts), with how many versions each filed."""
    ensure_schema(get_conn)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, author, model, thesis, forecasts, filed_at FROM year_predictions "
                    "WHERE year = %s AND filed_at < %s ORDER BY id", (YEAR, LOCK_AT))
        rows = cur.fetchall()
    latest: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for pid, author, model, thesis, fc, at in rows:
        counts[author] = counts.get(author, 0) + 1
        latest[author] = {"id": pid, "author": author, "model": model, "thesis": thesis,
                          "forecasts": fc if isinstance(fc, dict) else json.loads(fc), "filed_at": at.isoformat()}
    return {"year": YEAR, "lock_at": LOCK_AT.isoformat(), "locked": datetime.now(timezone.utc) >= LOCK_AT,
            "markets": {k: v[0] for k, v in MARKETS.items()}, "macro": MACRO, "flat_band_pct": FLAT_BAND_PCT,
            "entries": [dict(v, versions=counts[a]) for a, v in latest.items()]}


# ── the AI council's predictions ─────────────────────────────────────────────
SYSTEM = ("You are a global macro investor writing your forecast for the calendar year " + str(YEAR) + ". "
          "Be specific and commit to numbers. Reply with one JSON object only, no other text.")


def ask_prompt(levels: dict[str, Any], macro_now: dict[str, Any], today: str) -> str:
    shape = {"thesis": "your macro view for the year in 150-400 words: growth, inflation, central banks, "
                       "the dollar, risks, and why",
             "forecasts": {"markets": {k: {"direction": "up|flat|down", "change_pct": 0.0} for k in MARKETS},
                           "macro": {k: 0.0 for k in MACRO}}}
    return ("Forecast each market's change from the 31 Dec " + str(YEAR - 1) + " close to the 31 Dec " + str(YEAR)
            + " close (flat = within +/-2%), and the three US numbers. Markets: "
            + json.dumps({k: v[0] for k, v in MARKETS.items()}) + ". US numbers: " + json.dumps(MACRO)
            + ". Reply in exactly this shape: " + json.dumps(shape)
            + "\nData as of " + today + " (latest close, change over the last year %): " + json.dumps(levels)
            + "\nLatest US data (FRED): " + json.dumps(macro_now))


def ask_council(get_conn, now: datetime, levels: dict[str, Any], macro_now: dict[str, Any], *,
                call: Callable[[str, str, str], dict[str, Any]] | None = None,
                roles: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Ask each council member once; file every valid reply. One reply per member, no retries
    beyond the council code's own one."""
    if call is None or roles is None:
        from forex_council import VOTERS, call_model
        call, roles = call or call_model, roles or VOTERS
    user = ask_prompt(levels, macro_now, now.astimezone(engine.NEW_YORK).date().isoformat())
    out: dict[str, Any] = {}
    for role in roles:
        try:
            res = call(role, SYSTEM, user)
            raw = res["raw"]
            obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            filed = file(get_conn, now, author=role, thesis=obj.get("thesis", ""),
                         forecasts=obj.get("forecasts") or {}, model=res.get("model"))
            out[role] = {"filed": filed["id"], "model": res.get("model")}
        except Exception as exc:
            out[role] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return out
