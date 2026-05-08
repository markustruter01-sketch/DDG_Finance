"""
Read-only API endpoint exposing the bot registry to frontend.
"""
from fastapi import APIRouter
from core.bot_registry import to_dict_list, fleet_starting_capital, fleet_bot_count

router = APIRouter()

@router.get("/bot-registry")
def get_bot_registry():
    return {
        "bots": to_dict_list(),
        "fleet_starting_capital": fleet_starting_capital(),
        "fleet_bot_count": fleet_bot_count(),
    }
