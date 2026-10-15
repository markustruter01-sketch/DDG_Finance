"""Tests for the run-once migration runner and the 2026-10-15 cleanup migrations."""

from contextlib import contextmanager

import pytest

from db import migrations as m


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self._fetch = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.db.log.append((sql, params))
        s = " ".join(sql.split())
        if s.startswith("SELECT 1 FROM platform_migrations"):
            self._fetch = [(1,)] if params[0] in self.db.applied else []
        elif s.startswith("INSERT INTO platform_migrations"):
            self.db.pending_applied.add(params[0])
        elif s.startswith("SELECT symbol, stop_order_id FROM ratchet_stops"):
            self._fetch = list(self.db.ratchet.items())
        elif s.startswith("DELETE FROM ratchet_stops"):
            gone = [x for x in params[0] if x in self.db.ratchet]
            self.rowcount = len(gone)
            for x in gone:
                self.db.pending_ratchet_deletes.add(x)
        elif s.startswith("SELECT paused FROM bots_state"):
            self._fetch = [] if self.db.forex_paused == "missing" else [(self.db.forex_paused,)]
        elif s.startswith("UPDATE bots_state"):
            self.rowcount = 0 if self.db.forex_paused == "missing" else 1
            self.db.pending_forex_paused = True
        elif s.startswith("UPDATE system_degradations"):
            self.rowcount = self.db.update_rowcounts.pop(0) if self.db.update_rowcounts else 0
        else:
            self.rowcount = 0

    def fetchone(self):
        return self._fetch[0] if self._fetch else None

    def fetchall(self):
        return self._fetch


class FakeDB:
    def __init__(self, ratchet=None, applied=(), update_rowcounts=None, forex_paused=True):
        self.forex_paused = forex_paused
        self.pending_forex_paused = None
        self.ratchet = dict(ratchet if ratchet is not None else m._DEAD_RATCHET_ROWS)
        self.applied = set(applied)
        self.update_rowcounts = list(update_rowcounts or [])
        self.log = []
        self.pending_applied = set()
        self.pending_ratchet_deletes = set()
        self.rollbacks = 0

    @contextmanager
    def get_conn(self):
        conn = self

        class Conn:
            def cursor(self_inner):
                return FakeCursor(conn)

        try:
            yield Conn()
        except Exception:
            self.rollbacks += 1
            self.pending_applied.clear()
            self.pending_ratchet_deletes.clear()
            self.pending_forex_paused = None
            raise
        else:
            if self.pending_forex_paused is not None:
                self.forex_paused = self.pending_forex_paused
                self.pending_forex_paused = None
            self.applied |= self.pending_applied
            for sym in self.pending_ratchet_deletes:
                self.ratchet.pop(sym, None)
            self.pending_applied.clear()
            self.pending_ratchet_deletes.clear()


def _run(db, prod=True):
    return m.apply_pending_migrations(db.get_conn, is_production=lambda: prod)


def test_skips_everything_outside_production():
    db = FakeDB()
    out = _run(db, prod=False)
    assert set(out.values()) == {"skipped-not-production"}
    assert len(db.ratchet) == 17
    assert not db.applied


def test_applies_all_once_in_production():
    db = FakeDB(update_rowcounts=[330, 13, 14, 68, 33, 1, 1])
    out = _run(db)
    assert set(out.values()) == {"applied"}
    assert db.ratchet == {}
    again = _run(db)
    assert set(again.values()) == {"already-applied"}


def test_ratchet_guard_rolls_back_when_table_changed():
    changed = dict(m._DEAD_RATCHET_ROWS)
    changed["EPOL"] = "live-stop-id"  # a row we never reconciled
    db = FakeDB(ratchet=changed, update_rowcounts=[1, 0, 0, 0, 0, 0, 0])
    out = _run(db)
    assert out["2026-10-15-002-delete-dead-ratchet-rows"] == "guard-failed"
    assert len(db.ratchet) == 18  # nothing deleted
    assert "2026-10-15-002-delete-dead-ratchet-rows" not in db.applied


def test_ratchet_guard_rolls_back_when_order_id_changed():
    changed = dict(m._DEAD_RATCHET_ROWS)
    changed["DELL"] = "a-new-stop-order"
    db = FakeDB(ratchet=changed)
    m002 = (m.MIGRATIONS[1],)
    out = m.apply_pending_migrations(db.get_conn, migrations=m002, is_production=lambda: True)
    assert out[m002[0].id] == "guard-failed"
    assert len(db.ratchet) == 17


def test_degradation_sanity_bound_rolls_back():
    db = FakeDB(update_rowcounts=[900, 50, 50, 50, 0, 0, 0])
    m001 = (m.MIGRATIONS[0],)
    out = m.apply_pending_migrations(db.get_conn, migrations=m001, is_production=lambda: True)
    assert out[m001[0].id] == "guard-failed"
    assert m001[0].id not in db.applied


def test_resolve_before_fix_rows_are_time_bounded():
    db = FakeDB(update_rowcounts=[0] * 7)
    m001 = (m.MIGRATIONS[0],)
    m.apply_pending_migrations(db.get_conn, migrations=m001, is_production=lambda: True)
    bounded = [p for s, p in db.log if "AND ts <" in " ".join(s.split())]
    assert len(bounded) == len(m._RESOLVE_BEFORE_FIX)
    assert all(p[2] == m._FIXES_LIVE_AT for p in bounded)
    meta = [s for s, p in db.log if "zero_unresolved_high_severity" in s]
    assert meta, "the meta alert must be resolved"


def test_scheduler_job_status_tolerates_missing_next_run_time(monkeypatch):
    from core import scheduler

    class PendingJob:
        id = "j1"
        name = "pending"

    class FakeScheduler:
        def get_jobs(self):
            return [PendingJob()]

    monkeypatch.setattr(scheduler, "get_scheduler", lambda: FakeScheduler())
    assert scheduler.get_job_status() == [
        {"id": "j1", "name": "pending", "next_fire_utc": "paused"}
    ]


M003 = "2026-10-16-003-preserve-forex-pause"


def _m003(db):
    only = tuple(x for x in m.MIGRATIONS if x.id == M003)
    return m.apply_pending_migrations(db.get_conn, migrations=only, is_production=lambda: True)


def test_m003_pauses_forex_when_db_said_running():
    db = FakeDB(forex_paused=False)
    assert _m003(db)[M003] == "applied"
    assert db.forex_paused is True


def test_m003_no_change_when_already_paused():
    db = FakeDB(forex_paused=True)
    assert _m003(db)[M003] == "applied"
    assert not any(s.startswith("UPDATE bots_state") for s, _ in db.log)


def test_m003_guard_fails_without_forex_row():
    db = FakeDB(forex_paused="missing")
    assert _m003(db)[M003] == "guard-failed"
    assert M003 not in db.applied
