"""The auto-trading toggle pauses order-placing jobs only; monitoring keeps running."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler


def test_always_active_ids_are_real_jobs_and_exclude_order_placers():
    import core.scheduler as cs  # imported here: importing it at collection time shadows main.py for other tests

    scheduler = AsyncIOScheduler()
    cs._register_jobs(scheduler)
    ids = {job.id for job in scheduler.get_jobs()}
    assert cs._ALWAYS_ACTIVE_JOBS <= ids
    for order_job in ("per_bot_vault_deployment", "per_bot_vault_monthly_skim",
                      "automated_kill_switch", "scheduled_reconciliation"):
        assert order_job not in cs._ALWAYS_ACTIVE_JOBS
    assert {"standing_invariants", "order_watchdog", "gear_v1_g4_shadow",
            "twins_hourly", "twins_nightly"} <= cs._ALWAYS_ACTIVE_JOBS


def test_vault_v2_retired_the_quarterly_rebalance():
    import core.scheduler as cs

    scheduler = AsyncIOScheduler()
    cs._register_jobs(scheduler)
    ids = {job.id for job in scheduler.get_jobs()}
    assert "per_bot_vault_quarterly_rebalance" not in ids
    assert "per_bot_vault_monthly_skim" in ids
