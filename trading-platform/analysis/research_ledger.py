"""Immutable research specifications and complete daily bot return snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger

EXPECTED_BOTS = ("oracle", "spy_qqq_trend", "jerome_macro")
# The runner writes bot_portfolio once per cycle. All three bots use
# LOOP_SLEEP_SECONDS = 3600 (kraken-bot/config.py lines 34, 70, 109), so a
# healthy bot's row is routinely up to an hour old. Two missed cycles means
# the runner has stopped, not that it is between beats. The runner itself
# uses three intervals for lease loss (kraken-bot/runner.py:357); this is
# deliberately tighter so the return series notices a dead runner first.
STALE_AFTER_SECONDS = 2 * 60 * 60

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

ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS equity_start NUMERIC;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS equity_end NUMERIC;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS trading_capital_base NUMERIC;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS calculation_method TEXT;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS vault_excluded_value NUMERIC;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS backfilled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS computed_at TIMESTAMPTZ;
ALTER TABLE bot_daily_returns
    ADD COLUMN IF NOT EXISTS is_canonical BOOLEAN NOT NULL DEFAULT FALSE;
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


def snapshot_daily_returns(*, snapshot_date: date | None = None) -> dict[str, Any]:
    """Write all three bot rows atomically; never write a partial fleet."""
    from core.degradation_tracker import record_degradation
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
            outcomes = []
            for bot_id, equity, cash, positions, last_updated in rows:
                stale = (
                    last_updated is None
                    or (now - last_updated.astimezone(timezone.utc)).total_seconds()
                    > STALE_AFTER_SECONDS
                )
                try:
                    equity_close = float(equity)
                except (TypeError, ValueError):
                    equity_close = None
                if (
                    equity_close is None
                    or not math.isfinite(equity_close)
                    or equity_close <= 0
                ):
                    reason = (
                        "equity_missing"
                        if equity is None
                        else "equity_non_numeric"
                        if equity_close is None
                        else "equity_non_finite"
                        if not math.isfinite(equity_close)
                        else "equity_non_positive"
                    )
                    message = (
                        f"{bot_id} portfolio has unusable equity; "
                        f"skipping daily-return row ({reason})"
                    )
                    logger.error(f"Research ledger | {message}")
                    record_degradation(
                        component="data_pipeline",
                        severity="error",
                        error_type="daily_return_invalid_equity",
                        message=message,
                        detail=f"equity={equity!r}",
                        bot_id=bot_id,
                    )
                    outcomes.append(
                        {
                            "bot_id": bot_id,
                            "status": "skipped",
                            "reason": reason,
                        }
                    )
                    continue

                if stale:
                    stale_reason = (
                        "last_updated_missing"
                        if last_updated is None
                        else "last_updated_exceeded_threshold"
                    )
                    source = f"bot_portfolio_stale:{stale_reason}"
                    calculation_method = "equity_pct_change_stale_last_known"
                    message = (
                        f"{bot_id} portfolio stale; writing NULL daily_return "
                        f"and preserving last-known equity ({stale_reason})"
                    )
                    logger.error(f"Research ledger | {message}")
                    record_degradation(
                        component="data_pipeline",
                        severity="error",
                        error_type="daily_return_portfolio_stale",
                        message=message,
                        detail=(
                            f"last_updated={last_updated!r}; "
                            f"threshold_seconds={STALE_AFTER_SECONDS}"
                        ),
                        bot_id=bot_id,
                    )
                else:
                    source = "bot_portfolio_fresh"
                    calculation_method = "equity_pct_change"

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
                equity_open = float(previous[0]) if previous else None
                daily_return = (
                    (equity_close / equity_open) - 1
                    if not stale and equity_open not in (None, 0)
                    else None
                )
                deployed_pct = deployed / equity_close if equity_close else None
                cur.execute(
                    """
                    INSERT INTO bot_daily_returns
                        (date, bot_id, equity_open, equity_close, daily_return,
                         cash, positions_held, deployed_pct, benchmark_return,
                         equity_start, equity_end, trading_capital_base,
                         source, calculation_method, source_timestamp,
                         vault_excluded_value, backfilled, computed_at, is_canonical)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (date, bot_id) DO UPDATE SET
                        equity_open=EXCLUDED.equity_open,
                        equity_close=EXCLUDED.equity_close,
                        daily_return=EXCLUDED.daily_return,
                        cash=EXCLUDED.cash,
                        positions_held=EXCLUDED.positions_held,
                        deployed_pct=EXCLUDED.deployed_pct,
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
                        is_canonical=EXCLUDED.is_canonical
                    WHERE bot_daily_returns.is_canonical IS NOT TRUE
                    """,
                    (
                        snapshot_date, bot_id, equity_open, equity_close,
                        daily_return, cash, held, deployed_pct, benchmark_return,
                        None, None, None, source, calculation_method,
                        last_updated, None, False, now, False,
                    ),
                )
                if cur.rowcount == 0:
                    message = (
                        f"{bot_id} daily-return row is canonical; "
                        "snapshot path refused to overwrite it"
                    )
                    logger.error(f"Research ledger | {message}")
                    record_degradation(
                        component="data_pipeline",
                        severity="error",
                        error_type="daily_return_canonical_conflict",
                        message=message,
                        detail=f"date={snapshot_date.isoformat()}",
                        bot_id=bot_id,
                    )
                    outcomes.append(
                        {
                            "bot_id": bot_id,
                            "status": "skipped",
                            "reason": "canonical_row_exists",
                        }
                    )
                    continue
                output.append(
                    {
                        "date": str(snapshot_date),
                        "bot_id": bot_id,
                        "equity_close": equity_close,
                        "stale": stale,
                    }
                )
                outcomes.append(
                    {
                        "date": str(snapshot_date),
                        "bot_id": bot_id,
                        "equity_close": equity_close,
                        "daily_return": daily_return,
                        "stale": stale,
                        "status": "stale" if stale else "written",
                    }
                )
            stale_count = sum(item.get("status") == "stale" for item in outcomes)
            skipped_count = sum(item.get("status") == "skipped" for item in outcomes)
            return {
                "status": "completed_with_skips" if skipped_count else "written",
                "rows": output,
                "outcomes": outcomes,
                "stale_count": stale_count,
                "skipped_count": skipped_count,
            }