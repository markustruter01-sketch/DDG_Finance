"""Atlas V2's account (jerome_macro): the FLEET-V1 variant sleeve_runtime/fleet_accounts.py names.

FLEET-V1-C1 (the fleet's equity core alone) until the lock; then FLEET-V1-X1,
the cross-asset trend rule alone (roadmap v2, V2-03; Markus D2 = B, 22 Nov 2026).

Owner's decision 3 Nov 2026, after VOL-V1 failed its exploration bar
(research_harness/explore/VOL-V1-PLAN.md, Amendment 1): the third account
runs F1's geared S&P/Nasdaq trend core without the cross-asset sleeve, so the
2027 comparison answers whether F1's 35% in bonds, gold, commodities and the
dollar earns its place. Same rules, executor, stops and governor as Atlas
(sleeve_runtime/fleet_live.py, variant C1); exploration and held-out figures
in research_harness/exploration_log.jsonl and ledger.jsonl (FLEET-V1).

Replaces the Emerging Markets bot (bot3_hard_assets_strategy). On its first
cycle the executor sells legacy holdings that have an open ledger row and
freezes (never trades, reports) any that do not; the vault and SGOV stay.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

BOT_ID = "jerome_macro"
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"


def run_bullion_cycle(profile: dict[str, Any] | None = None, db_id: int | None = None) -> dict[str, Any]:
    """Live cycle. Only called by the runner, which enforces bots_state.paused."""
    from alpaca_etf_engine import AlpacaEtfEngine
    from fleet_account import run_fleet_account
    from sleeve_runtime.fleet_live import ACCOUNTS

    profile = profile or {}
    engine = AlpacaEtfEngine(
        api_key=profile.get("ALPACA_API_KEY") or os.environ.get("ALPACA_JEROME_API_KEY", ""),
        secret_key=profile.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_JEROME_SECRET_KEY", ""),
        base_url=profile.get("ALPACA_BASE_URL", ALPACA_BASE_URL),
        bot_ids=(BOT_ID,),
    )
    live = engine.get_positions()
    engine.reconcile_protective_stops(BOT_ID, engine.get_db_positions(BOT_ID))
    variant = ACCOUNTS[BOT_ID]
    result = run_fleet_account(engine, bot_id=BOT_ID, variant=variant, label="Atlas V2", live_positions=live)
    logger.info(f"Atlas V2 | {variant.registration} live cycle | {result['status']}")
    return result
