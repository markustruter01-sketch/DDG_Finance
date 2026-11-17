"""The daily closing snapshot runs after the US close on both sides of the clock change (fix window item 4)."""
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

NY = pytz.timezone("America/New_York")


def _trigger():
    import core.scheduler as cs  # imported here, like test_always_active_jobs
    scheduler = AsyncIOScheduler()
    cs._register_jobs(scheduler)
    return scheduler.get_job("daily_bot_returns_snapshot").trigger


def _next_run(after_utc: datetime) -> datetime:
    return _trigger().get_next_fire_time(None, after_utc)


def test_winter_runs_after_the_close():
    # Tue 17 Nov 2026 (EST, UTC-5): the close is 21:00 UTC. The old 20:15 UTC run was before it.
    run = _next_run(datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc))
    assert run.astimezone(timezone.utc) == datetime(2026, 11, 17, 22, 25, tzinfo=timezone.utc)
    assert run.astimezone(NY).hour * 60 + run.astimezone(NY).minute > 16 * 60


def test_summer_runs_after_the_close():
    # Tue 16 Jun 2026 (EDT, UTC-4): the close is 20:00 UTC.
    run = _next_run(datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc))
    assert run.astimezone(timezone.utc) == datetime(2026, 6, 16, 21, 25, tzinfo=timezone.utc)
    assert run.astimezone(NY).hour * 60 + run.astimezone(NY).minute > 16 * 60


def test_both_clock_change_days():
    # The US clock changes on 8 Mar 2026 and 1 Nov 2026; the next weekday runs stay after the close.
    for day in (datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc), datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)):
        local = _next_run(day).astimezone(NY)
        assert (local.hour, local.minute) == (17, 25)


def test_the_row_is_dated_by_the_new_york_trading_day():
    import core.scheduler as cs
    # 22:25 UTC on 17 Nov is 17:25 on 17 Nov in New York; 01:00 UTC on 18 Nov is still 17 Nov there.
    assert str(cs.new_york_date(datetime(2026, 11, 17, 22, 25, tzinfo=timezone.utc))) == "2026-11-17"
    assert str(cs.new_york_date(datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc))) == "2026-11-17"


def test_published_deployment_registers_its_jobs(monkeypatch):
    """18 Nov 2026: a name used only in the published branch (_et) went missing and the publish crashed.
    Register the jobs as the published deployment does."""
    import core.scheduler as cs
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    scheduler = AsyncIOScheduler()
    cs._register_jobs(scheduler)
    assert scheduler.get_job("deploy_hash_check_startup") is not None
