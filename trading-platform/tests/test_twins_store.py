"""AI twins tables: append-only logs, the hash chain, write-once real-account values."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from twins import store
from twins_pg import make_get_conn, needs_pg

T0 = datetime(2026, 11, 16, 21, tzinfo=timezone.utc)


def _setup():
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    store.ensure_schema(get_conn)          # idempotent: a second startup changes nothing
    assert store.create_account(get_conn, twin_id="oracle:mirror:v1", bot_id="oracle", kind="mirror", version=1,
                                bars="alpaca_daily", start_at=T0, start_equity=86_919.04, config={"max_gross": 10})
    assert not store.create_account(get_conn, twin_id="oracle:mirror:v1", bot_id="oracle", kind="mirror",
                                    version=1, bars="alpaca_daily", start_at=T0, start_equity=1.0, config={})
    return get_conn


@needs_pg
def test_decision_chain_links_and_detects_tampering():
    get_conn = _setup()
    a = store.append_decision(get_conn, twin_id="oracle:mirror:v1", decided_at=T0, step_at=T0,
                              weights={"SPY": 0.5, "SSO": 0.25}, inputs={"qty": {"SPY": 10.0}, "at": T0},
                              inputs_ref="bot_portfolio")
    b = store.append_decision(get_conn, twin_id="oracle:mirror:v1", decided_at=T0, step_at=T0,
                              weights=None, missed=True, reason="account unreadable")
    assert a["prev_hash"] is None and b["prev_hash"] == a["hash"]
    rows = store.decisions(get_conn, "oracle:mirror:v1")
    assert store.verify_chain(rows) == []
    assert store.accounts(get_conn)[0]["start_equity"] == 86_919.04

    # The database refuses edits and deletes.
    for sql in ("UPDATE twin_decisions SET reason = 'x'", "DELETE FROM twin_decisions",
                "TRUNCATE twin_decisions CASCADE"):
        with pytest.raises(Exception, match="append-only"):
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(sql)
    # Someone with owner rights switches the guard off and edits a row: the chain says so.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE twin_decisions DISABLE TRIGGER twin_decisions_append_only")
        cur.execute("UPDATE twin_decisions SET weights = '{\"SPY\": 1.0}'::jsonb WHERE id = %s", (a["id"],))
        cur.execute("ALTER TABLE twin_decisions ENABLE TRIGGER twin_decisions_append_only")
    problems = store.verify_chain(store.decisions(get_conn, "oracle:mirror:v1"))
    assert problems == [f"decision {a['id']}: content does not match its hash"]


@needs_pg
def test_hash_does_not_depend_on_the_session_time_zone():
    get_conn = _setup()
    store.append_decision(get_conn, twin_id="oracle:mirror:v1", decided_at=T0, step_at=T0, weights={"SPY": 1.0})
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'Australia/Brisbane'")
        cur.execute("SELECT step_at FROM twin_decisions")
        assert cur.fetchone()[0].utcoffset().total_seconds() == 36_000
    assert store.verify_chain(store.decisions(get_conn, "oracle:mirror:v1")) == []


@needs_pg
def test_a_missed_decision_has_no_weights():
    get_conn = _setup()
    with pytest.raises(ValueError):
        store.append_decision(get_conn, twin_id="oracle:mirror:v1", decided_at=T0, step_at=T0,
                              weights={"SPY": 1.0}, missed=True)
    with pytest.raises(KeyError):
        store.append_decision(get_conn, twin_id="nobody:mirror:v1", decided_at=T0, step_at=T0, weights={})


@needs_pg
def test_real_account_value_is_written_once_and_the_replay_never_touches_it():
    get_conn = _setup()
    day = date(2026, 11, 16)
    assert store.record_ref(get_conn, "oracle:mirror:v1", day, 86_900.0, T0)
    assert not store.record_ref(get_conn, "oracle:mirror:v1", day, 1.0, T0)
    store.upsert_equity(get_conn, "oracle:mirror:v1", [(day, 86_950.0, 0.99)])
    store.upsert_equity(get_conn, "oracle:mirror:v1", [(day, 86_951.0, 0.99)])   # a re-run
    store.set_gaps(get_conn, "oracle:mirror:v1", {day: 0.12})
    (row,) = store.equity_rows(get_conn, "oracle:mirror:v1")
    assert (row["equity"], row["ref_equity"], row["gap_pp"]) == (86_951.0, 86_900.0, 0.12)


@needs_pg
def test_change_log_is_append_only():
    get_conn = _setup()
    store.log_change(get_conn, kind="pause", summary="Atlas paused: test", source="test", bot_id="oracle")
    store.log_change(get_conn, kind="publish", summary="running build abc1234", source="test",
                     detail={"commit": "abc1234"})
    assert store.last_change(get_conn, ("pause", "resume"), "oracle")["kind"] == "pause"
    assert store.last_change(get_conn, ("publish",))["detail"] == {"commit": "abc1234"}
    assert store.last_change(get_conn, ("pause",), "jerome_macro") is None
    with pytest.raises(Exception, match="append-only"):
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM change_log")


@needs_pg
def test_fills_upsert_is_a_rerun_not_a_duplicate():
    get_conn = _setup()
    fill = {"filled_at": T0, "symbol": "SPY", "n": 0, "decision_id": None, "qty": 10.0, "price": 500.0,
            "cost": 0.25, "reason": "rebalance"}
    store.upsert_fills(get_conn, "oracle:mirror:v1", [fill])
    store.upsert_fills(get_conn, "oracle:mirror:v1", [{**fill, "price": 499.0}])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*), max(price) FROM twin_fills")
        assert cur.fetchone() == (1, 499.0)


# ── -0.0: the database keeps no sign on zero (FX-CARRY, 23 Nov 2026) ─────────────────────────
_FX_CARRY_ROW = {   # production row 50, read 25 Nov 2026; its JPY carry was -0.0 when hashed
    "id": 50, "twin_id": "league:FX-CARRY:v0", "prev_hash": None, "missed": False, "reason": "FX-CARRY",
    "decided_at": datetime(2026, 11, 23, 22, 15, 0, 688083, tzinfo=timezone.utc),
    "step_at": datetime(2026, 11, 23, 21, tzinfo=timezone.utc), "inputs_ref": "research_harness.league.families",
    "weights": {"AUD_USD": 0.2397189147, "CAD_USD": -0.3962924248, "CHF_USD": -0.2742950264,
                "EUR_USD": -0.331197585, "GBP_USD": 0.3138343786, "JPY_USD": 0.2210779476},
    "inputs": {"d": {"AUD": 0.0097, "CAD": -0.0165, "CHF": -0.04095, "EUR": -0.0145, "GBP": 0.00035,
                     "JPY": 0.0, "NZD": -0.0121, "USD": 0.0},
               "long": ["AUD", "GBP", "JPY"], "short": ["EUR", "CAD", "CHF"], "state": "hold"},
    "hash": "ff1cc44373127e4431345ed3575ee080364f041e31f2ba29db898dc5a2b9de0e"}


def test_old_row_that_lost_a_zero_sign_still_checks_clean_but_tampering_does_not():
    assert store.verify_chain([_FX_CARRY_ROW]) == []
    tampered = {**_FX_CARRY_ROW, "weights": {**_FX_CARRY_ROW["weights"], "AUD_USD": 0.3}}
    assert store.verify_chain([tampered]) == ["decision 50: content does not match its hash"]
    moved = {**_FX_CARRY_ROW, "inputs": {**_FX_CARRY_ROW["inputs"], "long": ["AUD", "GBP", "NZD"]}}
    assert store.verify_chain([moved]) == ["decision 50: content does not match its hash"]


@needs_pg
def test_negative_zero_is_stored_and_hashed_as_zero():
    get_conn = _setup()
    store.append_decision(get_conn, twin_id="oracle:mirror:v1", decided_at=T0, step_at=T0,
                          weights={"SPY": -0.0, "TLT": -3.3e-11}, inputs={"d": {"JPY": -0.0}, "list": [-0.0, 1.0]})
    rows = store.decisions(get_conn, "oracle:mirror:v1")
    assert store.verify_chain(rows) == []
    assert rows[-1]["weights"] == {"SPY": 0.0, "TLT": 0.0} and str(rows[-1]["inputs"]["d"]["JPY"]) == "0.0"
