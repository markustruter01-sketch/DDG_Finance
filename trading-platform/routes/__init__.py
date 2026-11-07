from .system import system_router
from .portfolio import portfolio_router
from .control import control_router
from .admin import admin_router
from .kraken_ohlcv import router as kraken_ohlcv_router
from .alerts import alerts_router
from .fleet_chat import fleet_chat_router
from .ai_impact import ai_impact_router
from .new_bots import new_bots_router
from .claude_review import claude_review_router
from .claude_context import claude_context_router
from .fleet_equity import fleet_equity_router
from .claude_report import router as claude_report_router
from .scorecard import scorecard_router
from .market_state_route import router as market_state_router
from .entry_windows import router as entry_windows_router
from .strategy_bench import router as strategy_bench_router
from .fleet_v1 import fleet_v1_router
from .momo_v2 import momo_v2_router
from .comparison import comparison_router
from .forex_council_log import forex_council_log_router
from .connections import connections_router

ALL_ROUTERS = [
    system_router,
    portfolio_router,
    control_router,
    admin_router,
    kraken_ohlcv_router,
    alerts_router,
    fleet_chat_router,
    ai_impact_router,
    new_bots_router,
    claude_review_router,
    claude_context_router,
    fleet_equity_router,
    claude_report_router,
    scorecard_router,
    market_state_router,
    entry_windows_router,
    strategy_bench_router,
    fleet_v1_router,
    momo_v2_router,
    comparison_router,
    forex_council_log_router,
    connections_router,
]
