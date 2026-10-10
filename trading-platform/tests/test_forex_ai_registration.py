from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis import health_monitor, micro_auditor, research_ledger
from core import bot_liveness, bot_registry, bot_state, fleet_equity
from notifications import discord
from routes import bot_registry_route, fleet_equity as fleet_equity_route, system


WORKSPACE = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def forex_strategy(monkeypatch):
    # The runner puts kraken-bot/ on sys.path; do the same for sibling imports.
    monkeypatch.syspath_prepend(str(WORKSPACE / "kraken-bot"))
    return _load_module(
        "test_forex_ai_strategy",
        WORKSPACE / "kraken-bot" / "forex_ai_strategy.py",
    )


@pytest.fixture
def runner_module():
    return _load_module(
        "test_forex_ai_runner",
        WORKSPACE / "kraken-bot" / "runner.py",
    )


def test_registry_returns_four_nonretired_bots_and_keeps_gump_retired():
    assert len(bot_registry.BOT_REGISTRY) == 5
    assert bot_registry.BOT_REGISTRY["forex_gump"].status == "retired"
    assert bot_registry.active_bot_ids() == [
        "oracle",
        "spy_qqq_trend",
        "jerome_macro",
        "forex_ai",
    ]

    response = bot_registry_route.get_bot_registry()
    assert response["fleet_bot_count"] == 4
    assert len(response["bots"]) == 4
    forex = next(bot for bot in response["bots"] if bot["id"] == "forex_ai")
    assert forex["status"] == "paused"
    assert forex["display_name"] == "Forex"
    assert forex["subtitle"] == "AI Currency Trading"
    assert forex["exchange"] == "oanda"
    assert forex["asset_class"] == "forex"


def test_runtime_bot_lists_use_registry_ids(runner_module):
    expected = tuple(bot_registry.active_bot_ids())

    assert bot_state.ACTIVE_BOT_IDS == set(expected)
    assert fleet_equity_route.ACTIVE_BOT_IDS == set(expected)
    assert research_ledger.EXPECTED_BOTS == expected
    assert bot_liveness.ACTIVE_BOTS == expected
    assert health_monitor.ACTIVE_BOTS == expected
    assert micro_auditor.ACTIVE_BOTS == expected
    assert tuple(discord._ACTIVE_BOTS) == expected
    assert system._HEALTH_ACTIVE_BOTS == expected
    assert tuple(bot_id for bot_id, *_ in runner_module.BOTS) == (
        "oracle",
        "jerome_macro",
        "spy_qqq_trend",
        "forex_ai",
    )


def test_health_monitor_supports_read_only_forex_without_trade_rows(monkeypatch):
    class _Cursor:
        def __init__(self):
            self.description = []
            self.row = None
            self.trade_filter = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params=()):
            if query.count("%s") != len(params):
                raise AssertionError("SQL placeholder mismatch")
            normalized = " ".join(query.lower().split())
            if "from bots_state" in normalized:
                self.description = [
                    ("bot_id",), ("paused",), ("pause_reason",), ("status",),
                    ("equity_usd",), ("cash_usd",), ("open_positions",),
                    ("last_heartbeat",), ("error_message",),
                ]
                self.row = (
                    "forex_ai", True, "read-only monitor", "paused",
                    125000.0, 120000.0, 0, None, "",
                )
            elif "from bot_portfolio" in normalized:
                self.description = [
                    ("bot_id",), ("equity_usd",), ("cash_usd",),
                    ("positions",), ("last_updated",),
                ]
                self.row = ("forex_ai", 125000.0, 120000.0, [], None)
            elif "from bot_cycle_health" in normalized:
                self.description = [
                    ("bot_id",), ("last_cycle_start",), ("last_cycle_end",),
                    ("last_success_at",), ("cycle_count",),
                    ("consecutive_failures",), ("last_error",), ("status",),
                ]
                self.row = ("forex_ai", None, None, None, 1, 0, None, "paused")
            elif "from trades" in normalized:
                self.trade_filter = params
                self.row = (0, None)
            elif "from fleet_equity_snapshots" in normalized:
                self.row = (0, None)
            else:
                self.row = (0, None)

        def fetchone(self):
            return self.row

    class _Connection:
        def __init__(self):
            self.cursor_value = _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.cursor_value

    connection = _Connection()
    monkeypatch.setattr(health_monitor, "is_pg_available", lambda: True)
    monkeypatch.setattr(health_monitor, "get_conn", lambda: connection)

    result = health_monitor._load_bot("forex_ai")

    assert result["status"] == "PAUSED"
    assert connection.cursor_value.trade_filter == ([],)


class _ReadOnlyOanda:
    def __init__(self, *, summary=None, positions=None, error=None):
        self.summary = summary or {
            "currency": "USD",
            "nav": Decimal("125000.25"),
            "balance": Decimal("120000.00"),
        }
        self.positions = positions or [
            {"instrument": "EUR_USD", "long": {"units": "100"}},
            {"instrument": "AUD_USD", "short": {"units": "50"}},
        ]
        self.error = error
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def account_summary(self):
        self.calls.append("account_summary")
        if self.error:
            raise self.error
        return self.summary

    def open_positions(self):
        self.calls.append("open_positions")
        return self.positions

    # Quant desk reads (Phase 3). No data here, so every pair reports an error
    # and a flat baseline; the account monitor result must be unaffected.
    def tradeable_instruments(self):
        self.calls.append("tradeable_instruments")
        return []

    def daily_candles(self, instrument, *, count):
        self.calls.append(f"daily_candles:{instrument}")
        return []

    def current_bid_ask(self, instrument):
        self.calls.append(f"current_bid_ask:{instrument}")
        return {"spread": Decimal("0.0001")}


def test_forex_cycle_only_reads_account_and_open_positions_and_writes_usd_state(
    monkeypatch,
    forex_strategy,
):
    client = _ReadOnlyOanda()
    writes = []
    monkeypatch.setattr(
        forex_strategy,
        "write_heartbeat",
        lambda *args, **kwargs: writes.append(("heartbeat", args, kwargs)),
    )
    monkeypatch.setattr(
        forex_strategy,
        "write_portfolio",
        lambda *args, **kwargs: writes.append(("portfolio", args, kwargs)),
    )

    result = forex_strategy.run_forex_cycle(client_factory=lambda: client)

    read_only_calls = {"account_summary", "open_positions", "tradeable_instruments"}
    assert client.calls[:3] == ["account_summary", "open_positions", "tradeable_instruments"]
    assert all(
        call in read_only_calls
        or call.startswith(("daily_candles:", "current_bid_ask:"))
        for call in client.calls
    )
    sheet = result.pop("signal_sheet")
    assert result == {
        "bot_id": "forex_ai",
        "currency": "USD",
        "equity_usd": 125000.25,
        "cash_usd": 120000.0,
        "open_positions": 2,
    }
    assert len(sheet["rows"]) == 7
    assert all(row["baseline"]["direction"] == "flat" for row in sheet["rows"])
    assert writes[0] == (
        "heartbeat",
        ("forex_ai",),
        {
            "equity": 125000.25,
            "cash": 120000.0,
            "positions": 2,
            "status": "paused",
        },
    )
    assert writes[1] == (
        "portfolio",
        ("forex_ai",),
        {
            "cash": 120000.0,
            "equity": 125000.25,
            "positions": client.positions,
        },
    )


@pytest.mark.parametrize(
    ("summary", "error", "message"),
    [
        (
            {"currency": "EUR", "nav": Decimal("125000"), "balance": Decimal("120000")},
            None,
            "requires a USD",
        ),
        (
            None,
            RuntimeError("OANDA unavailable"),
            "OANDA unavailable",
        ),
    ],
)
def test_forex_cycle_fails_without_writing_on_oanda_or_currency_error(
    monkeypatch,
    forex_strategy,
    summary,
    error,
    message,
):
    writes = []
    client = _ReadOnlyOanda(summary=summary, error=error)
    monkeypatch.setattr(
        forex_strategy,
        "write_heartbeat",
        lambda *args, **kwargs: writes.append(("heartbeat", args, kwargs)),
    )
    monkeypatch.setattr(
        forex_strategy,
        "write_portfolio",
        lambda *args, **kwargs: writes.append(("portfolio", args, kwargs)),
    )

    with pytest.raises((ValueError, RuntimeError), match=message):
        forex_strategy.run_forex_cycle(client_factory=lambda: client)
    assert writes == []


def _route_portfolio_rows(*, forex_equity=125000.0, include_forex=True):
    now = datetime.now(timezone.utc)
    bot_ids = bot_registry.active_bot_ids()
    if not include_forex:
        bot_ids = [bot_id for bot_id in bot_ids if bot_id != "forex_ai"]
    return [
        {
            "bot_id": bot_id,
            "equity_usd": forex_equity if bot_id == "forex_ai" else 100000.0,
            "starting_usd": 100000.0,
            "cash_usd": 80000.0,
            "positions": [],
            "last_updated": now,
        }
        for bot_id in bot_ids
    ]


def _patch_fleet_route(monkeypatch, portfolios):
    monkeypatch.setattr(bot_state, "get_all_portfolios", lambda: portfolios)
    monkeypatch.setattr(
        bot_state,
        "get_all_states",
        lambda: [
            {"bot_id": bot_id, "paused": bot_id == "forex_ai"}
            for bot_id in bot_registry.active_bot_ids()
        ],
    )
    monkeypatch.setattr(fleet_equity_route, "_fetch_win_rates", lambda: {})
    monkeypatch.setattr(
        fleet_equity_route,
        "_fetch_24h_mark_to_market",
        lambda bot_ids: {bot_id: None for bot_id in bot_ids},
    )


def test_dashboard_fleet_equity_includes_forex_nav_and_paused_state(monkeypatch):
    _patch_fleet_route(monkeypatch, _route_portfolio_rows())

    result = fleet_equity_route._fetch_fleet_equity()

    assert result["forex_ai"]["equity"] == 125000.0
    assert result["forex_ai"]["paused"] is True
    assert result["fleet_total"]["equity"] == 425000.0


def test_dashboard_fleet_equity_refuses_partial_rows_or_invalid_forex_nav(monkeypatch):
    _patch_fleet_route(
        monkeypatch,
        _route_portfolio_rows(include_forex=False),
    )
    with pytest.raises(RuntimeError, match="refusing partial fleet equity"):
        fleet_equity_route._fetch_fleet_equity()

    _patch_fleet_route(monkeypatch, _route_portfolio_rows(forex_equity=None))
    with pytest.raises(RuntimeError, match="OANDA USD NAV"):
        fleet_equity_route._fetch_fleet_equity()


class _SnapshotCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        placeholders = sql.count("%s")
        if placeholders != len(params):
            raise AssertionError(
                f"SQL placeholder mismatch: {placeholders} placeholders "
                f"for {len(params)} parameters"
            )
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class _SnapshotConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_value


def test_scheduler_fleet_snapshot_queries_every_registry_bot(monkeypatch):
    from core import scheduler

    ids = bot_registry.active_bot_ids()
    now = datetime.now(timezone.utc)
    rows = [
        (bot_id, 125000.0 if bot_id == "forex_ai" else 100000.0, now)
        for bot_id in ids
    ]
    cursor = _SnapshotCursor(rows)
    monkeypatch.setattr("db.postgres.is_pg_available", lambda: True)
    monkeypatch.setattr(
        "db.postgres.get_conn",
        lambda: _SnapshotConnection(cursor),
    )
    monkeypatch.setattr(
        fleet_equity_route,
        "_fetch_fleet_equity",
        lambda: {"fleet_total": {"equity": 425000.0}},
    )

    result = asyncio.run(scheduler._snapshot_fleet_equity(dry_run=True))

    assert result["bot_count"] == 4
    assert result["total_equity"] == 425000.0
    assert "ANY(%s)" in cursor.sql
    assert cursor.params == (ids,)


def test_runner_pause_alignment_requires_existing_matching_forex_state(
    monkeypatch,
    runner_module,
):
    monkeypatch.setattr(
        runner_module,
        "BOTS",
        [("forex_ai", "forex_ai_strategy", "run_forex_cycle")],
    )
    monkeypatch.setattr(
        runner_module,
        "_profile_for_bot",
        lambda _bot_id: {"BOT_PAUSED": True},
    )
    monkeypatch.setattr(runner_module, "_heartbeat_ok", True)
    monkeypatch.setattr(runner_module, "_bs_normalise", lambda bot_id: bot_id)
    monkeypatch.setattr(
        runner_module.importlib,
        "import_module",
        lambda _module_name: SimpleNamespace(BOT_PAUSED=True),
    )

    monkeypatch.setattr(runner_module, "_bs_get_state", lambda _bot_id: {})
    assert runner_module._assert_pause_alignment() is False

    monkeypatch.setattr(
        runner_module,
        "_bs_get_state",
        lambda _bot_id: {"paused": False},
    )
    assert runner_module._assert_pause_alignment() is False

    monkeypatch.setattr(
        runner_module,
        "_bs_get_state",
        lambda _bot_id: {"paused": True},
    )
    assert runner_module._assert_pause_alignment() is True


def test_forex_profile_and_database_seed_are_paused_and_hourly():
    config = _load_module(
        "test_forex_ai_config",
        WORKSPACE / "kraken-bot" / "config.py",
    )
    profile = config.BOT_PROFILES["forex_ai"]
    assert profile["BOT_PAUSED"] is True
    assert profile["LOOP_SLEEP_SECONDS"] == 3600

    source = (WORKSPACE / "trading-platform" / "db" / "postgres.py").read_text()
    assert (
        "('forex_ai',            TRUE, 'Paused: read-only OANDA monitor', 0, NULL)"
        in source
    )
    assert "ON CONFLICT (bot_id) DO NOTHING" in source