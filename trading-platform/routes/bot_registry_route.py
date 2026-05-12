"""
Read-only API endpoint exposing the bot registry to frontend.
"""
from fastapi import APIRouter, HTTPException
from core.bot_registry import to_dict_list, fleet_starting_capital, fleet_bot_count
from core.bot_state import get_all_states, get_bot_state, get_portfolio, get_all_portfolios

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


@router.get("/bots/portfolios")
def get_all_portfolios_route():
    """Return bot_portfolio rows for all bots (fleet equity calculation)."""
    return {"portfolios": get_all_portfolios()}


@router.get("/bots/{bot_id}/portfolio")
def get_bot_portfolio_route(bot_id: str):
    """Return bot_portfolio row for one bot by canonical or legacy ID."""
    p = get_portfolio(bot_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"No portfolio for {bot_id}")
    return p
