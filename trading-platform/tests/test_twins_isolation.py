"""The twins cannot reach the order path (spec rule 13)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TWINS = ROOT / "twins"
ORDER_PATH = ("sleeve_runtime.trend_executor", "core.oanda_trader", "execution", "alpaca_trade_api",
              "alpaca.trading", "kraken", "runner", "forex_execution", "fleet_account", "gear_account",
              "momo_strategy", "asia_trend_strategy", "bullion_strategy", "sgov_parking")
ORDER_WORDS = ("submit_order", "cancel_order", "replace_order", "close_position", "close_trade",
               "place_order", "TradingClient", "OandaTrader", "tradeapi", "market_order")


def test_importing_every_twin_module_loads_no_order_code():
    # Also everything the jobs import lazily, at run time.
    code = (
        "import json, sys\n"
        "import twins.job, twins.engine, twins.store, twins.prices, twins.config, twins.league\n"
        "import research_harness.league.families, sleeve_runtime.sp500_universe\n"
        "import sleeve_runtime.gear_shadow, sleeve_runtime.trend_v1b, core.oanda_client, core.build_info\n"
        "import core.bot_registry, core.symbols, core.degradation_tracker, config.settings\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}:{ROOT.parent}", "FRED_API_KEY": "dummy",
           "NEWS_API_KEY": "dummy", "GROQ_API_KEY": "dummy"}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
                         env=env)
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    hits = [m for m in loaded if any(m == p or m.startswith(p + ".") for p in ORDER_PATH)]
    assert hits == []


def test_twin_source_names_no_order_call_and_imports_nothing_from_the_order_path():
    for path in sorted(TWINS.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            for name in names:
                assert not any(name == p or name.startswith(p + ".") for p in ORDER_PATH), (path.name, name)
            if isinstance(node, (ast.Name, ast.Attribute)):
                ident = node.id if isinstance(node, ast.Name) else node.attr
                assert ident not in ORDER_WORDS, (path.name, ident)


def test_the_oanda_client_the_twins_use_only_reads():
    src = (ROOT / "core" / "oanda_client.py").read_text()
    for verb in (".post(", ".put(", ".patch(", ".delete(", "method="):
        assert verb not in src
