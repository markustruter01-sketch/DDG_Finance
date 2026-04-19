from .system import system_router
from .portfolio import portfolio_router
from .control import control_router
from .admin import admin_router
from .kraken import kraken_router
from .forex import forex_router
from .alerts import alerts_router
from .fleet_chat import fleet_chat_router
from .ai_impact import ai_impact_router
from .code_export import code_export_router
from .new_bots import new_bots_router
from .claude_review import claude_review_router

ALL_ROUTERS = [
    system_router,
    portfolio_router,
    control_router,
    admin_router,
    kraken_router,
    forex_router,
    alerts_router,
    fleet_chat_router,
    ai_impact_router,
    code_export_router,
    new_bots_router,
    claude_review_router,
]
