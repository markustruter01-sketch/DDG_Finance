"""
Read-only API endpoint exposing the bot registry to frontend.
"""
from fastapi import APIRouter, HTTPException
from core.bot_registry import to_dict_list, fleet_starting_capital, fleet_bot_count
from core.bot_state import get_all_states, get_bot_state

router = APIRouter()


@router.get("/bot-registry")
def get_bot_registry():
    return {
        "bots": to_dict_list(),
        "fleet_starting_capital": fleet_starting_capital(),
        "fleet_bot_count": fleet_bot_count(),
    }


@router.get("/bots/state")
def get_all_bot_states():
    """Return bots_state rows for all bots (canonical IDs, pause state, live heartbeat)."""
    return {"bots": get_all_states()}


@router.get("/bots/{bot_id}/state")
def get_single_bot_state(bot_id: str):
    """Return the bots_state row for one bot by canonical ID."""
    state = get_bot_state(bot_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found in bots_state")
    return state
