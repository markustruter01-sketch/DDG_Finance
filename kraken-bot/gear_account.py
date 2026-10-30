"""Wires a gear variant (sleeve_runtime/gear_live.py) to one Alpaca account.

The single place where the live callbacks are chosen, shared by Atlas
(oracle, G4) and Momentum's account (spy_qqq_trend, G4 with DBMF in the
safe gear): bar feed, vault and parked-cash exclusions, bots_state metadata,
kill-switch latch, SGOV parking, alerts and the fleet risk governor.
"""

from __future__ import annotations

from typing import Any

from core.cash_park import CASH_PARK_SYMBOLS, is_cash_park
from core.symbols import canonical_symbol


def sleeve_exclusions(bot_id: str, live_positions: list[dict]) -> tuple[set[str], set[str]]:
    """(vault symbols, parked-cash symbols) for this account."""
    from core.kill_switch import _vault_symbols
    vault = {canonical_symbol(s) for s in _vault_symbols(bot_id)}
    parked = {canonical_symbol(s) for s in CASH_PARK_SYMBOLS}
    parked |= {p["symbol"] for p in live_positions if is_cash_park(p.get("symbol"))}
    return vault, parked


def run_gear_account(engine, *, bot_id: str, variant, label: str,
                     live_positions: list[dict]) -> dict[str, Any]:
    """One hourly cycle of ``variant`` on ``bot_id``'s account."""
    from core import bot_state
    from core.degradation_tracker import record_degradation
    from core.kill_switch import latch_tripped
    from core.risk_governor import new_risk_check
    from sgov_parking import park_idle_cash, unpark_for_entry
    from sleeve_runtime.gear_live import run_gear_cycle
    from sleeve_runtime.trend_v1b import alpaca_bar_fetcher

    vault, parked = sleeve_exclusions(bot_id, live_positions)
    return run_gear_cycle(
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
        variant=variant,
    )
