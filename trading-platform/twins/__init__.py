"""AI twins: pretend accounts beside each bot. No orders, ever.

Spec: claude/finance-ai-twins-build-spec.md (Fable, 15 Nov 2026). Registration:
research_harness/registrations/TWINS-V1.json.

Each night the research simulator (research_harness/harness/portfolio.py, the
engine every backtest and the G4 shadow use) replays every twin from its start
using its append-only decision log. Nothing is carried from night to night, so
nothing can drift; the mirror twin proves the engine against the real account.

Isolation (spec rule 13): this package reads prices and the platform's own
tables only. It never imports the order path (sleeve_runtime.trend_executor,
core.oanda_trader, execution.*, broker SDKs, kraken-bot strategies) and never
builds a trading client. tests/test_twins_isolation.py proves it.
"""

import sys
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[2])
if _REPO not in sys.path:
    sys.path.append(_REPO)  # research_harness; appended so trading-platform's own packages still win
