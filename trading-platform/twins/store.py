"""The twins' own tables. Additive only: CREATE ... IF NOT EXISTS, no change to
any existing table.

- twin_accounts: one row per twin and version (start step, start balance, config).
- twin_decisions: APPEND-ONLY (database trigger). Each row carries the hash of
  the twin's previous row; verify_chain() re-checks every link nightly.
- twin_votes: APPEND-ONLY. One row per AI model call (Phase B).
- twin_fills, twin_equity_daily: derived. Rebuilt by the nightly replay from
  the decision log (deterministic, so a re-run gives the same rows; prices
  sit on the dividend-adjusted scale of the latest fetch). The mirror's
  real-account columns (ref_equity, ref_at, ref_holdings: the cash and share
  counts read at the close) are recorded facts, written once when the account
  is read and never touched by the replay.
- change_log: APPEND-ONLY. Every pause, resume, publish, manual action and
  rule change, dated.

Every function takes get_conn (a context manager yielding a psycopg2
connection), so tests run on a throwaway local Postgres.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Callable

DDL = """
CREATE TABLE IF NOT EXISTS twin_accounts (
    twin_id       TEXT PRIMARY KEY,
    bot_id        TEXT NOT NULL,
    kind          TEXT NOT NULL,
    version       INTEGER NOT NULL,
    bars          TEXT NOT NULL,
    start_at      TIMESTAMPTZ NOT NULL,
    start_equity  DOUBLE PRECISION NOT NULL,
    config        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retired_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS twin_decisions (
    id          BIGSERIAL PRIMARY KEY,
    twin_id     TEXT NOT NULL REFERENCES twin_accounts (twin_id),
    decided_at  TIMESTAMPTZ NOT NULL,
    step_at     TIMESTAMPTZ NOT NULL,
    weights     JSONB,
    missed      BOOLEAN NOT NULL DEFAULT FALSE,
    reason      TEXT NOT NULL DEFAULT '',
    inputs      JSONB NOT NULL DEFAULT '{}'::jsonb,
    inputs_ref  TEXT,
    prev_hash   TEXT,
    hash        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_twin_decisions_twin ON twin_decisions (twin_id, id);

CREATE TABLE IF NOT EXISTS twin_votes (
    id               BIGSERIAL PRIMARY KEY,
    twin_id          TEXT NOT NULL REFERENCES twin_accounts (twin_id),
    decision_id      BIGINT REFERENCES twin_decisions (id),
    role             TEXT NOT NULL,
    model_requested  TEXT NOT NULL,
    model_returned   TEXT,
    prompt           TEXT NOT NULL,
    inputs           JSONB NOT NULL,
    reply            TEXT,
    cost_usd         DOUBLE PRECISION,
    latency_ms       INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS twin_fills (
    twin_id      TEXT NOT NULL REFERENCES twin_accounts (twin_id),
    filled_at    TIMESTAMPTZ NOT NULL,
    symbol       TEXT NOT NULL,
    n            SMALLINT NOT NULL,
    decision_id  BIGINT,
    qty          DOUBLE PRECISION NOT NULL,
    price        DOUBLE PRECISION NOT NULL,
    cost         DOUBLE PRECISION NOT NULL,
    reason       TEXT NOT NULL,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (twin_id, filled_at, symbol, n)
);

CREATE TABLE IF NOT EXISTS twin_equity_daily (
    twin_id      TEXT NOT NULL REFERENCES twin_accounts (twin_id),
    day          DATE NOT NULL,
    equity       DOUBLE PRECISION,
    gross        DOUBLE PRECISION,
    ref_equity   DOUBLE PRECISION,
    ref_at       TIMESTAMPTZ,
    ref_holdings JSONB,
    gap_pp       DOUBLE PRECISION,
    computed_at  TIMESTAMPTZ,
    PRIMARY KEY (twin_id, day)
);

CREATE TABLE IF NOT EXISTS change_log (
    id       BIGSERIAL PRIMARY KEY,
    at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bot_id   TEXT,
    kind     TEXT NOT NULL,
    summary  TEXT NOT NULL,
    detail   JSONB NOT NULL DEFAULT '{}'::jsonb,
    source   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_log_kind ON change_log (kind, bot_id, id DESC);

CREATE OR REPLACE FUNCTION twins_append_only() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;
"""

APPEND_ONLY = ("twin_decisions", "twin_votes", "change_log")
_TRIGGERS = "".join(f"""
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = '{t}_append_only') THEN
        CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t}
        FOR EACH ROW EXECUTE FUNCTION twins_append_only();
    END IF;
END $$;
""" for t in APPEND_ONLY)

GetConn = Callable[[], Any]


def ensure_schema(get_conn: GetConn) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(DDL + _TRIGGERS)


# ── hashing ───────────────────────────────────────────────────────────────────
def _iso(value: Any) -> Any:
    if isinstance(value, datetime):          # the same instant hashes the same in any time zone
        return value.astimezone(timezone.utc).isoformat()
    return value.isoformat() if isinstance(value, date) else value


def decision_hash(prev_hash: str | None, row: dict[str, Any]) -> str:
    body = {k: _iso(row[k]) for k in ("twin_id", "decided_at", "step_at", "weights", "missed",
                                       "reason", "inputs", "inputs_ref")}
    canonical = json.dumps({"prev": prev_hash, "row": body}, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── accounts ──────────────────────────────────────────────────────────────────
_ACCOUNT_COLS = "twin_id, bot_id, kind, version, bars, start_at, start_equity, config, created_at, retired_at"


def _account(row: tuple) -> dict[str, Any]:
    keys = [c.strip() for c in _ACCOUNT_COLS.split(",")]
    out = dict(zip(keys, row))
    out["config"] = out["config"] if isinstance(out["config"], dict) else json.loads(out["config"] or "{}")
    out["start_equity"] = float(out["start_equity"])
    return out


def create_account(get_conn: GetConn, *, twin_id: str, bot_id: str, kind: str, version: int,
                   bars: str, start_at: datetime, start_equity: float, config: dict[str, Any]) -> bool:
    """Insert a twin; False if it already exists (never overwritten)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO twin_accounts (twin_id, bot_id, kind, version, bars, start_at, start_equity, config)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT (twin_id) DO NOTHING""",
            (twin_id, bot_id, kind, version, bars, start_at, start_equity, json.dumps(config, sort_keys=True)))
        return cur.rowcount == 1


def accounts(get_conn: GetConn, *, active_only: bool = True) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_ACCOUNT_COLS} FROM twin_accounts"
                    + (" WHERE retired_at IS NULL" if active_only else "") + " ORDER BY twin_id")
        return [_account(r) for r in cur.fetchall()]


# ── decisions (append-only, hash-chained) ─────────────────────────────────────
def append_decision(get_conn: GetConn, *, twin_id: str, decided_at: datetime, step_at: datetime,
                    weights: dict[str, float] | None, inputs: dict[str, Any] | None = None,
                    inputs_ref: str | None = None, missed: bool = False, reason: str = "") -> dict[str, Any]:
    if missed != (weights is None):
        raise ValueError("a missed decision has no weights, and only a missed one")
    row = {"twin_id": twin_id, "decided_at": decided_at, "step_at": step_at,
           "weights": {k: round(float(v), 10) for k, v in sorted(weights.items())} if weights is not None else None,
           "missed": missed, "reason": reason, "inputs": inputs or {}, "inputs_ref": inputs_ref}
    with get_conn() as conn, conn.cursor() as cur:
        # One writer per twin at a time: the account row is the lock.
        cur.execute("SELECT 1 FROM twin_accounts WHERE twin_id = %s FOR UPDATE", (twin_id,))
        if cur.fetchone() is None:
            raise KeyError(f"no twin {twin_id}")
        cur.execute("SELECT hash FROM twin_decisions WHERE twin_id = %s ORDER BY id DESC LIMIT 1", (twin_id,))
        last = cur.fetchone()
        prev = last[0] if last else None
        digest = decision_hash(prev, row)
        cur.execute(
            """INSERT INTO twin_decisions (twin_id, decided_at, step_at, weights, missed, reason,
                                           inputs, inputs_ref, prev_hash, hash)
               VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s) RETURNING id""",
            (twin_id, decided_at, step_at, json.dumps(row["weights"]) if weights is not None else None,
             missed, reason, json.dumps(row["inputs"], sort_keys=True, default=str), inputs_ref, prev, digest))
        return {**row, "id": cur.fetchone()[0], "prev_hash": prev, "hash": digest}


_DECISION_COLS = "id, twin_id, decided_at, step_at, weights, missed, reason, inputs, inputs_ref, prev_hash, hash"


def decisions(get_conn: GetConn, twin_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_DECISION_COLS} FROM twin_decisions WHERE twin_id = %s ORDER BY id", (twin_id,))
        keys = [c.strip() for c in _DECISION_COLS.split(",")]
        out = []
        for r in cur.fetchall():
            d = dict(zip(keys, r))
            for k in ("weights", "inputs"):
                if isinstance(d[k], str):
                    d[k] = json.loads(d[k])
            out.append(d)
        return out


def verify_chain(rows: list[dict[str, Any]]) -> list[str]:
    """Problems in one twin's decision chain (rows in id order); empty = intact."""
    problems, prev = [], None
    for r in rows:
        if r["prev_hash"] != prev:
            problems.append(f"decision {r['id']}: previous-row link broken")
        if decision_hash(r["prev_hash"], r) != r["hash"]:
            problems.append(f"decision {r['id']}: content does not match its hash")
        prev = r["hash"]
    return problems


# ── derived rows ──────────────────────────────────────────────────────────────
def upsert_fills(get_conn: GetConn, twin_id: str, fills: list[dict[str, Any]]) -> None:
    if not fills:
        return
    with get_conn() as conn, conn.cursor() as cur:
        for f in fills:
            cur.execute(
                """INSERT INTO twin_fills (twin_id, filled_at, symbol, n, decision_id, qty, price, cost, reason)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (twin_id, filled_at, symbol, n) DO UPDATE SET
                       decision_id = EXCLUDED.decision_id, qty = EXCLUDED.qty, price = EXCLUDED.price,
                       cost = EXCLUDED.cost, reason = EXCLUDED.reason, computed_at = NOW()""",
                (twin_id, f["filled_at"], f["symbol"], f["n"], f["decision_id"], f["qty"],
                 f["price"], f["cost"], f["reason"]))


def upsert_equity(get_conn: GetConn, twin_id: str, points: list[tuple[date, float, float]]) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        for day, equity, gross in points:
            cur.execute(
                """INSERT INTO twin_equity_daily (twin_id, day, equity, gross, computed_at)
                   VALUES (%s, %s, %s, %s, NOW())
                   ON CONFLICT (twin_id, day) DO UPDATE SET
                       equity = EXCLUDED.equity, gross = EXCLUDED.gross, computed_at = NOW()""",
                (twin_id, day, equity, gross))


def record_ref(get_conn: GetConn, twin_id: str, day: date, ref_equity: float, ref_at: datetime,
               holdings: dict[str, Any] | None = None) -> bool:
    """The real account for the mirror check. Written once per day."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO twin_equity_daily (twin_id, day, ref_equity, ref_at, ref_holdings)
               VALUES (%s, %s, %s, %s, %s::jsonb)
               ON CONFLICT (twin_id, day) DO UPDATE SET ref_equity = EXCLUDED.ref_equity,
                   ref_at = EXCLUDED.ref_at, ref_holdings = EXCLUDED.ref_holdings
               WHERE twin_equity_daily.ref_equity IS NULL""",
            (twin_id, day, ref_equity, ref_at, json.dumps(holdings, sort_keys=True) if holdings else None))
        return cur.rowcount == 1


def set_gaps(get_conn: GetConn, twin_id: str, gaps: dict[date, float]) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        for day, gap in gaps.items():
            cur.execute("UPDATE twin_equity_daily SET gap_pp = %s WHERE twin_id = %s AND day = %s",
                        (gap, twin_id, day))


def equity_rows(get_conn: GetConn, twin_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT day, equity, gross, ref_equity, ref_at, ref_holdings, gap_pp
                       FROM twin_equity_daily WHERE twin_id = %s ORDER BY day""", (twin_id,))
        keys = ("day", "equity", "gross", "ref_equity", "ref_at", "ref_holdings", "gap_pp")
        rows = [dict(zip(keys, r)) for r in cur.fetchall()]
    for r in rows:
        if isinstance(r["ref_holdings"], str):
            r["ref_holdings"] = json.loads(r["ref_holdings"])
    return rows


# ── change log (append-only) ──────────────────────────────────────────────────
def log_change(get_conn: GetConn, *, kind: str, summary: str, source: str,
               bot_id: str | None = None, detail: dict[str, Any] | None = None,
               at: datetime | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO change_log (at, bot_id, kind, summary, detail, source)
               VALUES (COALESCE(%s, NOW()), %s, %s, %s, %s::jsonb, %s) RETURNING id""",
            (at, bot_id, kind, summary[:500], json.dumps(detail or {}, sort_keys=True, default=str), source))
        return cur.fetchone()[0]


def last_change(get_conn: GetConn, kinds: tuple[str, ...], bot_id: str | None = None) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, at, bot_id, kind, summary, detail FROM change_log
               WHERE kind = ANY(%s) AND bot_id IS NOT DISTINCT FROM %s ORDER BY id DESC LIMIT 1""",
            (list(kinds), bot_id))
        r = cur.fetchone()
    if r is None:
        return None
    detail = r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}")
    return {"id": r[0], "at": r[1], "bot_id": r[2], "kind": r[3], "summary": r[4], "detail": detail}
