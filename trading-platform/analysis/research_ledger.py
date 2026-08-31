"""Immutable research specifications and complete daily bot return snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from core.bot_registry import active_bots
from core.market_clock import ET, is_nyse_session_date, previous_nyse_session_date

RESEARCH_BOT_IDS = tuple(bot.id for bot in active_bots())
# Kept as a compatibility alias for older research scripts.
EXPECTED_BOTS = RESEARCH_BOT_IDS
STALE_AFTER_SECONDS = 25 * 60
MEANINGFUL_HISTORY_THRESHOLD = 60
VAULT_SYMBOLS = frozenset(("BIL", "VOO"))

RESEARCH_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS research_ledger (
    experiment_id    BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    strategy_family  TEXT NOT NULL,
    bot_id           TEXT,
    hypothesis       TEXT NOT NULL,
    parameters       JSONB NOT NULL,
    pass_bar         JSONB NOT NULL,
    data_window      JSONB NOT NULL,
    variations_tested INT NOT NULL,
    spec_hash        TEXT,
    results          JSONB,
    results_at       TIMESTAMPTZ,
    outcome          TEXT,
    went_live        BOOLEAN NOT NULL DEFAULT FALSE,
    went_live_at     TIMESTAMPTZ,
    notes            TEXT,
    backfilled       BOOLEAN NOT NULL DEFAULT FALSE,
    sizing_model     TEXT CHECK (
        sizing_model IS NULL
        OR sizing_model IN ('cash_constrained', 'event_compounded', 'unknown')
    )
);

ALTER TABLE research_ledger
    ADD COLUMN IF NOT EXISTS sizing_model TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'research_ledger_sizing_model_check'
          AND conrelid = 'research_ledger'::regclass
    ) THEN
        ALTER TABLE research_ledger
            ADD CONSTRAINT research_ledger_sizing_model_check
            CHECK (
                sizing_model IS NULL
                OR sizing_model IN ('cash_constrained', 'event_compounded', 'unknown')
            );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION research_ledger_spec_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.hypothesis IS DISTINCT FROM NEW.hypothesis
       OR OLD.parameters IS DISTINCT FROM NEW.parameters
       OR OLD.pass_bar IS DISTINCT FROM NEW.pass_bar
       OR OLD.data_window IS DISTINCT FROM NEW.data_window
    THEN
        RAISE EXCEPTION
            'research_ledger locked spec cannot be modified for experiment_id=%',
            OLD.experiment_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS research_ledger_spec_immutable_trigger
    ON research_ledger;
CREATE TRIGGER research_ledger_spec_immutable_trigger
BEFORE UPDATE ON research_ledger
FOR EACH ROW EXECUTE FUNCTION research_ledger_spec_immutable();

DROP FUNCTION IF EXISTS register_experiment(
    TEXT, TEXT, TEXT, JSONB, JSONB, JSONB, INT, TEXT, BOOLEAN,
    TIMESTAMPTZ, TEXT, BOOLEAN
);

CREATE OR REPLACE FUNCTION register_experiment(
    p_strategy_family TEXT,
    p_bot_id TEXT,
    p_hypothesis TEXT,
    p_parameters JSONB,
    p_pass_bar JSONB,
    p_data_window JSONB,
    p_variations_tested INT,
    p_sizing_model TEXT,
    p_spec_hash TEXT DEFAULT NULL,
    p_went_live BOOLEAN DEFAULT FALSE,
    p_went_live_at TIMESTAMPTZ DEFAULT NULL,
    p_notes TEXT DEFAULT NULL,
    p_backfilled BOOLEAN DEFAULT FALSE
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    new_id BIGINT;
BEGIN
    IF p_sizing_model IS NULL
       OR p_sizing_model NOT IN ('cash_constrained', 'event_compounded', 'unknown')
    THEN
        RAISE EXCEPTION
            'research_ledger sizing_model must be cash_constrained, event_compounded, or unknown';
    END IF;

    INSERT INTO research_ledger (
        strategy_family, bot_id, hypothesis, parameters, pass_bar,
        data_window, variations_tested, spec_hash, went_live, went_live_at,
        notes, backfilled, sizing_model
    ) VALUES (
        p_strategy_family, p_bot_id, p_hypothesis, p_parameters, p_pass_bar,
        p_data_window, p_variations_tested, p_spec_hash, p_went_live,
        p_went_live_at, p_notes, p_backfilled, p_sizing_model
    )
    RETURNING experiment_id INTO new_id;
    RETURN new_id;
END;
$$;

CREATE OR REPLACE FUNCTION record_results(
    p_experiment_id BIGINT,
    p_results JSONB,
    p_outcome TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE research_ledger
       SET results = p_results,
           results_at = NOW(),
           outcome = p_outcome
     WHERE experiment_id = p_experiment_id
       AND results IS NULL;
    IF NOT FOUND THEN
        IF EXISTS (
            SELECT 1 FROM research_ledger
             WHERE experiment_id = p_experiment_id
               AND results IS NOT NULL
        ) THEN
            RAISE EXCEPTION
                'research_ledger results already recorded for experiment_id=%',
                p_experiment_id;
        END IF;
        RAISE EXCEPTION
            'research_ledger experiment_id=% does not exist',
            p_experiment_id;
    END IF;
END;
$$;
"""

BOT_DAILY_RETURNS_DDL = """
CREATE TABLE IF NOT EXISTS bot_daily_returns (
    id                BIGSERIAL PRIMARY KEY,
    date              DATE NOT NULL,
    bot_id            TEXT NOT NULL,
    equity_open       NUMERIC,
    equity_close      NUMERIC NOT NULL,
    daily_return      NUMERIC,
    cash              NUMERIC,
    positions_held    INT,
    deployed_pct      NUMERIC,
    benchmark_return  NUMERIC,
    equity_start      NUMERIC,
    equity_end        NUMERIC,
    trading_capital_base NUMERIC,
    source            TEXT,
    calculation_method TEXT,
    source_timestamp  TIMESTAMPTZ,
    vault_excluded_value NUMERIC,
    backfilled        BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at       TIMESTAMPTZ,
    is_canonical      BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (date, bot_id)
);

ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS equity_start NUMERIC;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS equity_end NUMERIC;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS trading_capital_base NUMERIC;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS calculation_method TEXT;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS vault_excluded_value NUMERIC;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS backfilled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS computed_at TIMESTAMPTZ;
ALTER TABLE bot_daily_returns ADD COLUMN IF NOT EXISTS is_canonical BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_bot_daily_returns_canonical
    ON bot_daily_returns (bot_id, date)
    WHERE is_canonical;
"""


def _canonical_spec(
    strategy_family: str,
    bot_id: str | None,
    hypothesis: str,
    parameters: dict[str, Any],
    pass_bar: dict[str, Any],
    data_window: dict[str, Any],
    variations_tested: int,
) -> str:
    payload = {
        "strategy_family": strategy_family,
        "bot_id": bot_id,
        "hypothesis": hypothesis,
        "parameters": parameters,
        "pass_bar": pass_bar,
        "data_window": data_window,
        "variations_tested": variations_tested,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def ensure_research_tables() -> None:
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(RESEARCH_LEDGER_DDL)
            cur.execute(BOT_DAILY_RETURNS_DDL)


def register_experiment(
    *,
    strategy_family: str,
    bot_id: str | None,
    hypothesis: str,
    parameters: dict[str, Any],
    pass_bar: dict[str, Any],
    data_window: dict[str, Any],
    variations_tested: int,
    sizing_model: str,
    went_live: bool = False,
    went_live_at: datetime | None = None,
    notes: str | None = None,
    backfilled: bool = False,
) -> int:
    spec_hash = _canonical_spec(
        strategy_family, bot_id, hypothesis, parameters, pass_bar,
        data_window, variations_tested,
    )
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT register_experiment(
                    %s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s
                )""",
                (
                    strategy_family, bot_id, hypothesis,
                    json.dumps(parameters), json.dumps(pass_bar),
                    json.dumps(data_window), variations_tested, sizing_model, spec_hash,
                    went_live, went_live_at, notes, backfilled,
                ),
            )
            return int(cur.fetchone()[0])


def record_results(
    experiment_id: int,
    results: dict[str, Any],
    outcome: str,
) -> None:
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT record_results(%s,%s::jsonb,%s)",
                (experiment_id, json.dumps(results), outcome),
            )


def _positions_summary(positions: Any) -> tuple[int, float]:
    if not isinstance(positions, list):
        return 0, 0.0
    held = 0
    deployed = 0.0
    for position in positions:
        if not isinstance(position, dict):
            continue
        value = float(
            position.get("value_usd")
            or position.get("market_value")
            or position.get("size")
            or 0
        )
        if abs(value) > 1.0:
            held += 1
            deployed += abs(value)
    return held, deployed


def enriched_snapshot_from_portfolio(portfolio: dict[str, Any]) -> dict[str, Any] | None:
    """Build a vault-separated snapshot row without contacting a broker."""
    total = portfolio.get("equity_usd")
    positions = portfolio.get("positions")
    if total is None or not isinstance(positions, list):
        return None
    vault_value = 0.0
    for position in positions:
        if not isinstance(position, dict):
            continue
        if str(position.get("symbol", "")).upper() not in VAULT_SYMBOLS:
            continue
        vault_value += abs(float(
            position.get("market_value")
            or position.get("value_usd")
            or 0.0
        ))
    total = float(total)
    trading_equity = total - vault_value
    if trading_equity < 0:
        return None
    return {
        "bot_id": portfolio["bot_id"],
        "total_equity_usd": total,
        "vault_value_usd": vault_value,
        "trading_equity_usd": trading_equity,
        "capital_base_usd": trading_equity,
        "snapshot_source": "portfolio_with_vault_exclusion",
    }


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _snapshot_is_enriched(row: tuple) -> bool:
    """Only a snapshot with explicit vault separation is a live source."""
    return row[2] is not None and row[3] is not None and row[4] is not None


def _prefer_snapshot(current: tuple | None, candidate: tuple) -> tuple:
    """Prefer enriched data, then the latest timestamp for a session."""
    if current is None:
        return candidate
    if _snapshot_is_enriched(candidate) != _snapshot_is_enriched(current):
        return candidate if _snapshot_is_enriched(candidate) else current
    return candidate if candidate[0] >= current[0] else current


def _snapshot_values(row: tuple, *, allow_pre_vault: bool) -> dict[str, Any] | None:
    """Convert a fleet snapshot into return-accounting values."""
    snapshot_ts, equity, vault_value, trading_equity, capital_base, source = row
    if _snapshot_is_enriched(row):
        return {
            "equity": float(trading_equity),
            "capital_base": float(capital_base),
            "vault_excluded_value": float(vault_value),
            "source": source or "enriched_fleet_snapshot",
            "snapshot_ts": snapshot_ts,
        }
    if allow_pre_vault and equity is not None:
        return {
            "equity": float(equity),
            "capital_base": float(equity),
            "vault_excluded_value": 0.0,
            "source": "pre_vault_total_equity_snapshot",
            "snapshot_ts": snapshot_ts,
        }
    return None


def _latest_session_snapshots(cur: Any, bot_id: str, end_date: date) -> dict[date, tuple]:
    cur.execute(
        """
        SELECT
            (snapshot_ts AT TIME ZONE 'America/New_York')::date AS session_date,
            snapshot_ts, equity_usd, vault_value_usd, trading_equity_usd,
            capital_base_usd, snapshot_source
          FROM fleet_equity_snapshots
         WHERE bot_id = %s
           AND (snapshot_ts AT TIME ZONE 'America/New_York')::date <= %s
         ORDER BY session_date ASC, snapshot_ts ASC
        """,
        (bot_id, end_date),
    )
    latest: dict[date, tuple] = {}
    for session_date, snapshot_ts, equity, vault, trading, capital, source in cur.fetchall():
        if not is_nyse_session_date(session_date):
            continue
        latest[session_date] = _prefer_snapshot(latest.get(session_date), (
            snapshot_ts, equity, vault, trading, capital, source
        ))
    return latest


def _benchmark_return(cur: Any, snapshot_date: date) -> float | None:
    """Read a benchmark only when two distinct NYSE samples exist."""
    cur.execute(
        """
        SELECT (recorded_at AT TIME ZONE 'America/New_York')::date, spy_close
          FROM market_state
         WHERE spy_close IS NOT NULL
           AND (recorded_at AT TIME ZONE 'America/New_York')::date <= %s
         ORDER BY recorded_at DESC
        """,
        (snapshot_date,),
    )
    latest: dict[date, float] = {}
    for session_date, close in cur.fetchall():
        if is_nyse_session_date(session_date) and session_date not in latest:
            latest[session_date] = float(close)
    dates = sorted(latest, reverse=True)
    if len(dates) < 2 or latest[dates[1]] == 0:
        return None
    return latest[dates[0]] / latest[dates[1]] - 1.0


def _insert_canonical_return(
    cur: Any,
    *,
    session_date: date,
    bot_id: str,
    opening: dict[str, Any],
    closing: dict[str, Any],
    benchmark_return: float | None,
    backfilled: bool,
    computed_at: datetime,
) -> None:
    denominator = opening["capital_base"]
    if denominator <= 0 or closing["equity"] <= 0:
        raise ValueError("canonical return requires positive trading capital")
    daily_return = closing["equity"] / denominator - 1.0
    cur.execute(
        """
        INSERT INTO bot_daily_returns
            (date, bot_id, equity_open, equity_close, daily_return,
             benchmark_return, equity_start, equity_end, trading_capital_base,
             source, calculation_method, source_timestamp, vault_excluded_value,
             backfilled, computed_at, is_canonical)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
        ON CONFLICT (date, bot_id) DO UPDATE SET
            equity_open=EXCLUDED.equity_open,
            equity_close=EXCLUDED.equity_close,
            daily_return=EXCLUDED.daily_return,
            benchmark_return=EXCLUDED.benchmark_return,
            equity_start=EXCLUDED.equity_start,
            equity_end=EXCLUDED.equity_end,
            trading_capital_base=EXCLUDED.trading_capital_base,
            source=EXCLUDED.source,
            calculation_method=EXCLUDED.calculation_method,
            source_timestamp=EXCLUDED.source_timestamp,
            vault_excluded_value=EXCLUDED.vault_excluded_value,
            backfilled=EXCLUDED.backfilled,
            computed_at=EXCLUDED.computed_at,
            is_canonical=TRUE
        """,
        (
            session_date, bot_id, opening["equity"], closing["equity"],
            daily_return, benchmark_return, opening["equity"], closing["equity"],
            opening["capital_base"],
            closing["source"], "trading_equity_pct_change",
            closing["snapshot_ts"], closing["vault_excluded_value"],
            backfilled, computed_at,
        ),
    )


def snapshot_daily_returns(*, snapshot_date: date | None = None) -> dict[str, Any]:
    """Write live, vault-separated rows for the requested NYSE session.

    Missing bots or missing source samples are reported individually.  No
    synthetic, stale, zero-filled, or non-session row is written.
    """
    from db.postgres import get_conn

    snapshot_date = snapshot_date or datetime.now(ET).date()
    if not is_nyse_session_date(snapshot_date):
        return {"status": "skipped", "reason": "not_nyse_session", "date": str(snapshot_date)}
    previous_date = previous_nyse_session_date(snapshot_date)
    written: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            benchmark = _benchmark_return(cur, snapshot_date)
            computed_at = datetime.now(timezone.utc)
            for bot_id in RESEARCH_BOT_IDS:
                snapshots = _latest_session_snapshots(cur, bot_id, snapshot_date)
                opening = _snapshot_values(
                    snapshots.get(previous_date), allow_pre_vault=False
                ) if snapshots.get(previous_date) else None
                closing = _snapshot_values(
                    snapshots.get(snapshot_date), allow_pre_vault=False
                ) if snapshots.get(snapshot_date) else None
                if (
                    not opening
                    or not closing
                    or opening["equity"] <= 0
                    or closing["equity"] <= 0
                ):
                    unavailable.append({"bot_id": bot_id, "date": str(snapshot_date)})
                    continue
                _insert_canonical_return(
                    cur,
                    session_date=snapshot_date,
                    bot_id=bot_id,
                    opening=opening,
                    closing=closing,
                    benchmark_return=benchmark,
                    backfilled=False,
                    computed_at=computed_at,
                )
                written.append({
                    "date": str(snapshot_date),
                    "bot_id": bot_id,
                    "equity_start": opening["equity"],
                    "equity_end": closing["equity"],
                    "daily_return": closing["equity"] / opening["equity"] - 1.0,
                    "source": closing["source"],
                })
    return {
        "status": "written" if written else "skipped",
        "date": str(snapshot_date),
        "previous_session": str(previous_date),
        "rows": written,
        "unavailable": unavailable,
    }


def get_bot_daily_returns(
    bot_id: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Read only canonical, trading-only rows for one bot."""
    from db.postgres import get_conn

    clauses = ["bot_id = %s", "is_canonical = TRUE"]
    params: list[Any] = [bot_id]
    if start_date:
        clauses.append("date >= %s")
        params.append(start_date)
    if end_date:
        clauses.append("date <= %s")
        params.append(end_date)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT date, bot_id, equity_start, equity_end,
                       trading_capital_base, daily_return, source,
                       calculation_method, source_timestamp,
                       vault_excluded_value, backfilled, computed_at
                  FROM bot_daily_returns
                 WHERE {' AND '.join(clauses)}
                 ORDER BY date ASC
                """,
                tuple(params),
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    result = []
    for row in rows:
        item = dict(zip(columns, row))
        item["date"] = item["date"].isoformat()
        for key, value in item.items():
            if hasattr(value, "isoformat") and key != "date":
                item[key] = value.isoformat()
        result.append(item)
    return result


def get_fleet_daily_returns(
    bot_ids: tuple[str, ...] | list[str] | None = None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Return daily returns on the exact common-date intersection."""
    bot_ids = tuple(bot_ids or RESEARCH_BOT_IDS)
    series = {bot_id: get_bot_daily_returns(
        bot_id, start_date=start_date, end_date=end_date
    ) for bot_id in bot_ids}
    by_date = {
        bot_id: {row["date"]: float(row["daily_return"]) for row in rows
                 if row["daily_return"] is not None}
        for bot_id, rows in series.items()
    }
    common_dates = sorted(set.intersection(
        *(set(values) for values in by_date.values())
    )) if by_date else []
    return {
        "bot_ids": list(bot_ids),
        "dates": common_dates,
        "returns": {
            bot_id: [by_date[bot_id][day] for day in common_dates]
            for bot_id in bot_ids
        },
        "coverage": {bot_id: len(values) for bot_id, values in by_date.items()},
        "common_data_points": len(common_dates),
    }


def fleet_sharpe_report(
    bot_ids: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Report fleet Sharpe inputs and meaningful-history availability."""
    from core.metrics import risk_metrics

    aligned = get_fleet_daily_returns(bot_ids)
    metrics = {
        bot_id: risk_metrics(values)["sharpe_ratio"]
        for bot_id, values in aligned["returns"].items()
    }
    enough_to_calculate = aligned["common_data_points"] >= 10
    meaningful = aligned["common_data_points"] >= MEANINGFUL_HISTORY_THRESHOLD
    return {
        **aligned,
        "sharpe_ratio": metrics,
        "calculation_gate": {"minimum_observations": 10, "met": enough_to_calculate},
        "meaningful_history": {
            "threshold": MEANINGFUL_HISTORY_THRESHOLD,
            "status": "PROPOSED",
            "met": meaningful,
        },
        "risk_free_rate_annual": 0.05,
        "periods_per_year": 252,
        "std_definition": "sample_ddof_1",
    }


def backfill_daily_returns(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Backfill canonical rows from development fleet snapshots only.

    Enriched snapshots are always preferred.  A legacy total-equity snapshot is
    usable only before that bot's vault activation timestamp.  This function
    reports post-activation gaps instead of manufacturing observations.
    """
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        return {"status": "blocked", "reason": "production_backfill_forbidden"}
    if not os.environ.get("DATABASE_URL"):
        return {"status": "blocked", "reason": "development_database_required"}

    from db.postgres import get_conn

    end_date = end_date or datetime.now(ET).date()
    query = """
        SELECT bot_id,
               (snapshot_ts AT TIME ZONE 'America/New_York')::date AS session_date,
               snapshot_ts, equity_usd, vault_value_usd, trading_equity_usd,
               capital_base_usd, snapshot_source
          FROM fleet_equity_snapshots
         WHERE bot_id = ANY(%s)
    """
    params: list[Any] = [list(RESEARCH_BOT_IDS)]
    if start_date:
        # Include a buffer so the first requested session can compare against
        # the prior NYSE session even when that session is a holiday-adjacent
        # date.
        query += " AND (snapshot_ts AT TIME ZONE 'America/New_York')::date >= %s"
        params.append(start_date - timedelta(days=10))
    query += " AND (snapshot_ts AT TIME ZONE 'America/New_York')::date <= %s"
    params.append(end_date)
    query += " ORDER BY bot_id, session_date ASC, snapshot_ts ASC"

    planned: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "status": "dry_run" if dry_run else "written",
        "start_date": str(start_date) if start_date else None,
        "end_date": str(end_date),
        "bots": {},
        "rows": 0,
        "unsupported_post_vault_dates": [],
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bot_id, activated_at FROM per_bot_vault_accounts WHERE bot_id = ANY(%s)",
                (list(RESEARCH_BOT_IDS),),
            )
            activation = {bot_id: activated_at for bot_id, activated_at in cur.fetchall()}
            cur.execute(query, tuple(params))
            snapshots: dict[str, dict[date, tuple]] = {
                bot_id: {} for bot_id in RESEARCH_BOT_IDS
            }
            for (
                bot_id, session_date, snapshot_ts, equity, vault, trading, capital, source
            ) in cur.fetchall():
                if not is_nyse_session_date(session_date):
                    continue
                candidate = (
                    snapshot_ts, equity, vault, trading, capital, source
                )
                bot_snapshots = snapshots.setdefault(bot_id, {})
                bot_snapshots[session_date] = _prefer_snapshot(
                    bot_snapshots.get(session_date),
                    candidate,
                )

            computed_at = datetime.now(timezone.utc)
            for bot_id in RESEARCH_BOT_IDS:
                activated_at = activation.get(bot_id)
                usable: dict[date, dict[str, Any]] = {}
                unsupported: list[str] = []
                for session_date, row in snapshots.get(bot_id, {}).items():
                    before_activation = (
                        activated_at is None
                        or row[0] < activated_at
                    )
                    values = _snapshot_values(row, allow_pre_vault=before_activation)
                    if values:
                        usable[session_date] = values
                    elif activated_at is not None and session_date >= activated_at.date():
                        unsupported.append(str(session_date))

                bot_report = {
                    "snapshot_dates": len(snapshots.get(bot_id, {})),
                    "usable_snapshot_dates": len(usable),
                    "unsupported_post_vault_dates": sorted(unsupported),
                    "rows": 0,
                    "first_date": None,
                    "last_date": None,
                }
                if unsupported:
                    report["unsupported_post_vault_dates"].append({
                        "bot_id": bot_id,
                        "dates": sorted(unsupported),
                    })

                for session_date in sorted(usable):
                    if start_date and session_date < start_date:
                        continue
                    if session_date <= (start_date or date.min):
                        continue
                    previous = previous_nyse_session_date(session_date)
                    opening = usable.get(previous)
                    closing = usable[session_date]
                    if not opening or opening["equity"] <= 0:
                        continue
                    planned.append({
                        "session_date": session_date,
                        "bot_id": bot_id,
                        "opening": opening,
                        "closing": closing,
                    })
                    bot_report["rows"] += 1

                if bot_report["rows"]:
                    dates = [
                        item["session_date"] for item in planned
                        if item["bot_id"] == bot_id
                    ]
                    bot_report["first_date"] = str(min(dates))
                    bot_report["last_date"] = str(max(dates))
                report["bots"][bot_id] = bot_report

            if not dry_run:
                for item in planned:
                    _insert_canonical_return(
                        cur,
                        session_date=item["session_date"],
                        bot_id=item["bot_id"],
                        opening=item["opening"],
                        closing=item["closing"],
                        benchmark_return=None,
                        backfilled=True,
                        computed_at=computed_at,
                    )
    report["rows"] = len(planned)
    return report


def read_only_daily_returns_report() -> dict[str, Any]:
    """Return an auditable report without changing database state."""
    from db.postgres import get_conn

    report: dict[str, Any] = {
        "schema": {},
        "canonical_rows": {},
        "source_coverage": {},
        "backfill_preview": backfill_daily_returns(dry_run=True),
        "fleet_sharpe": None,
        "production_publish_required": True,
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type
                  FROM information_schema.columns
                 WHERE table_name IN ('bot_daily_returns', 'fleet_equity_snapshots')
                 ORDER BY table_name, ordinal_position
                """
            )
            for table, column, data_type in cur.fetchall():
                report["schema"].setdefault(table, []).append({
                    "column": column,
                    "type": data_type,
                })
            cur.execute(
                """
                SELECT bot_id, COUNT(*), MIN(date), MAX(date)
                  FROM bot_daily_returns
                 WHERE is_canonical = TRUE
                 GROUP BY bot_id ORDER BY bot_id
                """
            )
            for bot_id, count, first, last in cur.fetchall():
                report["canonical_rows"][bot_id] = {
                    "count": count,
                    "first_date": str(first),
                    "last_date": str(last),
                }
            cur.execute(
                """
                SELECT bot_id, snapshot_source, COUNT(*),
                       MIN((snapshot_ts AT TIME ZONE 'America/New_York')::date),
                       MAX((snapshot_ts AT TIME ZONE 'America/New_York')::date)
                  FROM fleet_equity_snapshots
                 GROUP BY bot_id, snapshot_source
                 ORDER BY bot_id, snapshot_source
                """
            )
            for bot_id, source, count, first, last in cur.fetchall():
                report["source_coverage"].setdefault(bot_id, []).append({
                    "source": source,
                    "count": count,
                    "first_date": str(first),
                    "last_date": str(last),
                })
            cur.execute(
                """
                SELECT bot_id, date, equity_start, equity_end, daily_return, source
                  FROM bot_daily_returns
                 WHERE is_canonical = TRUE
                 ORDER BY bot_id, date ASC
                """
            )
            samples: dict[str, list[dict[str, Any]]] = {}
            for bot_id, row_date, start, end, daily, source in cur.fetchall():
                if start is None or end is None or daily is None:
                    continue
                samples.setdefault(bot_id, []).append({
                    "date": str(row_date),
                    "equity_start": float(start),
                    "equity_end": float(end),
                    "daily_return": float(daily),
                    "source": source,
                })
            report["canonical_samples"] = {
                bot_id: {"first_five": rows[:5], "last_five": rows[-5:]}
                for bot_id, rows in samples.items()
            }
    try:
        report["fleet_sharpe"] = fleet_sharpe_report()
    except Exception as exc:
        report["fleet_sharpe"] = {"status": "unavailable", "reason": str(exc)}
    report["thresholds"] = {
        "risk_free_rate_annual": 0.05,
        "periods_per_year": 252,
        "sharpe_calculation_minimum_observations": 10,
        "meaningful_history_threshold": MEANINGFUL_HISTORY_THRESHOLD,
        "meaningful_history_status": "PROPOSED",
    }
    return report