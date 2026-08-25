"""Immutable research specifications and complete daily bot return snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger

EXPECTED_BOTS = ("oracle", "spy_qqq_trend", "jerome_macro")
STALE_AFTER_SECONDS = 25 * 60

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
    backfilled       BOOLEAN NOT NULL DEFAULT FALSE
);

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

CREATE OR REPLACE FUNCTION register_experiment(
    p_strategy_family TEXT,
    p_bot_id TEXT,
    p_hypothesis TEXT,
    p_parameters JSONB,
    p_pass_bar JSONB,
    p_data_window JSONB,
    p_variations_tested INT,
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
    INSERT INTO research_ledger (
        strategy_family, bot_id, hypothesis, parameters, pass_bar,
        data_window, variations_tested, spec_hash, went_live, went_live_at,
        notes, backfilled
    ) VALUES (
        p_strategy_family, p_bot_id, p_hypothesis, p_parameters, p_pass_bar,
        p_data_window, p_variations_tested, p_spec_hash, p_went_live,
        p_went_live_at, p_notes, p_backfilled
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
    UNIQUE (date, bot_id)
);
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
                    %s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s
                )""",
                (
                    strategy_family, bot_id, hypothesis,
                    json.dumps(parameters), json.dumps(pass_bar),
                    json.dumps(data_window), variations_tested, spec_hash,
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


def snapshot_daily_returns(*, snapshot_date: date | None = None) -> dict[str, Any]:
    """Write all three bot rows atomically; never write a partial fleet."""
    from db.postgres import get_conn

    snapshot_date = snapshot_date or datetime.now(timezone.utc).date()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bot_id, equity_usd, cash_usd, positions, last_updated
                  FROM bot_portfolio
                 WHERE bot_id = ANY(%s)
                """,
                (list(EXPECTED_BOTS),),
            )
            rows = cur.fetchall()
            found = {row[0] for row in rows}
            missing = sorted(set(EXPECTED_BOTS) - found)
            if missing:
                logger.error(
                    "Research ledger | refusing partial daily snapshot: "
                    f"found={len(rows)}/{len(EXPECTED_BOTS)} missing={missing}"
                )
                return {"status": "skipped", "reason": "missing_bots", "missing": missing}

            now = datetime.now(timezone.utc)
            cur.execute(
                """
                SELECT recorded_at::date, spy_close
                  FROM market_state
                 WHERE spy_close IS NOT NULL
                   AND recorded_at::date <= %s
                 GROUP BY recorded_at::date, spy_close
                 ORDER BY recorded_at::date DESC, MAX(recorded_at) DESC
                 LIMIT 2
                """,
                (snapshot_date,),
            )
            benchmark_rows = cur.fetchall()
            benchmark_return = None
            if len(benchmark_rows) >= 2 and benchmark_rows[1][1]:
                benchmark_return = (
                    float(benchmark_rows[0][1]) / float(benchmark_rows[1][1])
                ) - 1
            output = []
            for bot_id, equity, cash, positions, last_updated in rows:
                stale = (
                    last_updated is None
                    or (now - last_updated.astimezone(timezone.utc)).total_seconds()
                    > STALE_AFTER_SECONDS
                )
                if stale:
                    logger.warning(
                        f"Research ledger | {bot_id} portfolio stale; "
                        "using last-known equity and flagging in logs"
                    )
                held, deployed = _positions_summary(positions)
                cur.execute(
                    """
                    SELECT equity_close FROM bot_daily_returns
                     WHERE bot_id = %s AND date < %s
                     ORDER BY date DESC LIMIT 1
                    """,
                    (bot_id, snapshot_date),
                )
                previous = cur.fetchone()
                equity_close = float(equity or 0)
                equity_open = float(previous[0]) if previous else None
                daily_return = (
                    (equity_close / equity_open) - 1
                    if equity_open not in (None, 0)
                    else None
                )
                deployed_pct = deployed / equity_close if equity_close else None
                cur.execute(
                    """
                    INSERT INTO bot_daily_returns
                        (date, bot_id, equity_open, equity_close, daily_return,
                         cash, positions_held, deployed_pct, benchmark_return)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (date, bot_id) DO UPDATE SET
                        equity_open=EXCLUDED.equity_open,
                        equity_close=EXCLUDED.equity_close,
                        daily_return=EXCLUDED.daily_return,
                        cash=EXCLUDED.cash,
                        positions_held=EXCLUDED.positions_held,
                        deployed_pct=EXCLUDED.deployed_pct,
                        benchmark_return=EXCLUDED.benchmark_return
                    """,
                    (
                        snapshot_date, bot_id, equity_open, equity_close,
                        daily_return, cash, held, deployed_pct, benchmark_return,
                    ),
                )
                output.append(
                    {
                        "date": str(snapshot_date),
                        "bot_id": bot_id,
                        "equity_close": equity_close,
                        "stale": stale,
                    }
                )
            return {"status": "written", "rows": output}