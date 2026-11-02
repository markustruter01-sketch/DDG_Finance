"""Momentum's account (spy_qqq_trend): MOMO-V2, a forward-only paper experiment.

50 S&P 500 members by 12-1 momentum, equal weight, with brakes on the book
itself (research_harness/explore/MOMO-V2-PLAN.md; runtime
sleeve_runtime/momo_live.py). Replaces the FLEET-V1-C1 control (2 Nov 2026,
owner's decision): its first monthly cycle sells whatever the account holds
that is not in the 50 (G4 + DBMF's or C1's holdings), keeping the vault.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

BOT_ID = "spy_qqq_trend"
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
UNIVERSE_TIMEOUT_SECONDS = 30


def _http_get(url: str) -> bytes:
    import requests

    resp = requests.get(url, timeout=UNIVERSE_TIMEOUT_SECONDS,
                        headers={"User-Agent": "Mozilla/5.0 (DDG Finance research)"})
    resp.raise_for_status()
    return resp.content


def run_momo_account_cycle(profile: dict[str, Any] | None = None, db_id: int | None = None) -> dict[str, Any]:
    """Live cycle. Only called by the runner, which enforces bots_state.paused."""
    from alpaca_etf_engine import AlpacaEtfEngine
    from core import bot_state
    from core.degradation_tracker import record_degradation
    from core.kill_switch import latch_tripped
    from core.risk_governor import new_risk_check
    from core.risk_limits import HARD_DRAWDOWN, SOFT_DRAWDOWN
    from gear_account import sleeve_exclusions
    from sgov_parking import park_idle_cash, unpark_for_entry
    from sleeve_runtime.momo_live import EXIT_REASON, REGISTRATION, STATE_KEY, run_momo_cycle
    from sleeve_runtime.sp500_universe import load_sp500
    from sleeve_runtime.trend_v1b import alpaca_bar_fetcher

    profile = profile or {}
    engine = AlpacaEtfEngine(
        api_key=profile.get("ALPACA_API_KEY") or os.environ.get("ALPACA_BB_API_KEY", ""),
        secret_key=profile.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        base_url=profile.get("ALPACA_BASE_URL", ALPACA_BASE_URL),
    )
    live = engine.get_positions()
    engine.reconcile_protective_stops(BOT_ID, engine.get_db_positions(BOT_ID))
    vault, parked = sleeve_exclusions(BOT_ID, live)
    result = run_momo_cycle(
        engine,
        bot_id=BOT_ID,
        fetch_bars=alpaca_bar_fetcher(engine.api),
        fetch_universe=lambda: load_sp500(_http_get),
        vault=vault,
        cash_park=parked,
        read_state=lambda: (bot_state.read_metadata(BOT_ID) or {}).get(STATE_KEY, {}),
        write_state=lambda st: bot_state.merge_metadata(BOT_ID, {STATE_KEY: st}),
        kill_tripped=latch_tripped,
        unpark=lambda e, lv: unpark_for_entry(e, "MomoV2", lv),
        park=lambda e, lv, cash: park_idle_cash(e, "MomoV2", lv, cash),
        alert=lambda severity, msg: record_degradation(
            component=BOT_ID, severity=severity, error_type=EXIT_REASON, message=msg[:500], bot_id=BOT_ID),
        risk_check=new_risk_check,
        soft=SOFT_DRAWDOWN,
        hard=HARD_DRAWDOWN,
    )
    logger.info(f"Momentum | {REGISTRATION} live cycle | {result['status']}")
    return result
