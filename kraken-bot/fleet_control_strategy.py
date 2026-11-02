"""Momentum's account (spy_qqq_trend): FLEET-V1's equity core alone (C1).

A forward control for FLEET-V1-F1 on Atlas's account: the same core rules
without the cross-asset sleeve, so the platform shows month by month what
the cross-asset sleeve costs or saves. Information only; not a strategy
choice. Spec: sleeve_runtime/FLEET-V1-LIVE-SPEC.md section 1.

Replaces bot2_momentum_strategy (single-stock momentum, retired 30 Oct 2026,
then GEAR-V2-A2's forward test). Any stock still held without an open
alpaca_etf_positions row is frozen by the executor (never traded, reported),
so a leftover Momentum position cannot be sold blind.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

BOT_ID = "spy_qqq_trend"
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"


def run_control_cycle(profile: dict[str, Any] | None = None, db_id: int | None = None) -> dict[str, Any]:
    """Live cycle. Only called by the runner, which enforces bots_state.paused."""
    from alpaca_etf_engine import AlpacaEtfEngine
    from fleet_account import run_fleet_account
    from sleeve_runtime.fleet_live import C1

    profile = profile or {}
    engine = AlpacaEtfEngine(
        api_key=profile.get("ALPACA_API_KEY") or os.environ.get("ALPACA_BB_API_KEY", ""),
        secret_key=profile.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        base_url=profile.get("ALPACA_BASE_URL", ALPACA_BASE_URL),
    )
    live = engine.get_positions()
    engine.reconcile_protective_stops(BOT_ID, engine.get_db_positions(BOT_ID))
    result = run_fleet_account(engine, bot_id=BOT_ID, variant=C1, label="FleetC1", live_positions=live)
    logger.info(f"Control | FLEET-V1-C1 live cycle | {result['status']}")
    return result
