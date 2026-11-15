"""Wires a FLEET-V1 variant (sleeve_runtime/fleet_live.py) to one Alpaca account.

The single place where the live callbacks are chosen, shared by Atlas
(oracle, FLEET-V1-F1) and Momentum's account (spy_qqq_trend, the C1
control): bar feed, vault and parked-cash exclusions, bots_state metadata,
kill-switch latch, SGOV parking, alerts, the fleet risk governor and the
drawdown limits (core/risk_limits.py). Same shape as gear_account.py.
"""

from __future__ import annotations

from typing import Any

from core.bot_registry import OWNER_KEPT  # the executor never trades them; not an alarm
from gear_account import sleeve_exclusions


def run_fleet_account(engine, *, bot_id: str, variant, label: str,
                      live_positions: list[dict]) -> dict[str, Any]:
    """One hourly cycle of ``variant`` on ``bot_id``'s account."""
    from core import bot_state
    from core.degradation_tracker import record_degradation
    from core.kill_switch import latch_tripped
    from core.risk_governor import new_risk_check
    from core.risk_limits import HARD_DRAWDOWN, SOFT_DRAWDOWN
    from core.symbols import canonical_symbol
    from sgov_parking import park_idle_cash, unpark_for_entry
    from sleeve_runtime.fleet_live import run_fleet_cycle
    from sleeve_runtime.trend_v1b import alpaca_bar_fetcher

    vault, parked = sleeve_exclusions(bot_id, live_positions)
    return run_fleet_cycle(
        engine,
        bot_id=bot_id,
        fetch_bars=alpaca_bar_fetcher(engine.api),
        vault=vault,
        cash_park=parked,
        read_state=lambda: (bot_state.read_metadata(bot_id) or {}).get(variant.state_key, {}),
        write_state=lambda st: bot_state.merge_metadata(bot_id, {variant.state_key: st}),
        kill_tripped=latch_tripped,
        unpark=lambda e, live: unpark_for_entry(e, label, live),
        park=lambda e, live, cash: park_idle_cash(e, label, live, cash),
        alert=lambda severity, msg: record_degradation(
            component=bot_id, severity=severity, error_type=variant.exit_reason,
            message=msg[:500], bot_id=bot_id),
        risk_check=new_risk_check,
        soft=SOFT_DRAWDOWN,
        hard=HARD_DRAWDOWN,
        variant=variant,
        owner_kept=lambda symbol: canonical_symbol(symbol) in OWNER_KEPT.get(bot_id, frozenset()),
    )
