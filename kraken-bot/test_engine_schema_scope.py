"""Engine set-up runs once per process; legacy repairs touch only the account's own rows.

11 Nov 2026: every cycle built a new engine per account, its ALTER TABLE took an
exclusive lock on the ledger table and two bots cycling together deadlocked
(22:14 UTC). The current_qty repair also compared EVERY bot's rows with THIS
account's broker positions (SPY is held by two accounts).
"""
from __future__ import annotations

from broker_harness import FakeAlpaca, db_exec, make_engine, needs_db

import alpaca_etf_engine as etf_engine_module


def _row(bot_id: str, symbol: str, status: str, qty: float, current_qty) -> int:
    return db_exec(
        """INSERT INTO alpaca_etf_positions (bot_id, symbol, qty, current_qty, entry_price, notional_usd, status)
           VALUES (%s, %s, %s, %s, 100, %s, %s) RETURNING id""",
        (bot_id, symbol, qty, current_qty, qty * 100, status))[0][0]


def _current(row_id: int):
    v = db_exec("SELECT current_qty FROM alpaca_etf_positions WHERE id = %s", (row_id,))[0][0]
    return None if v is None else float(v)


@needs_db
def test_repairs_touch_only_this_accounts_rows(monkeypatch):
    broker = FakeAlpaca(prices={"SPY": 700.0, "QQQ": 600.0}, positions={"SPY": 32.0}, cash=10_000.0)
    engine = make_engine(monkeypatch, broker, bot_ids=("oracle", "jerome_macro"))
    mine_open = _row("oracle", "SPY", "open", 32, None)
    mine_closed = _row("oracle", "QQQ", "closed", 5, 5)
    theirs_open = _row("jerome_macro", "SPY", "open", 46, None)      # other account also holds SPY
    theirs_closed = _row("jerome_macro", "QQQ", "closed", 7, 7)

    engine.bot_ids = ("oracle",)
    engine._backfill_current_qty()
    assert _current(mine_open) == 32.0 and _current(mine_closed) == 0.0
    assert _current(theirs_open) is None and _current(theirs_closed) == 7.0   # untouched

    engine.bot_ids = ()                                                   # no ids: repairs nothing
    db_exec("UPDATE alpaca_etf_positions SET current_qty = NULL WHERE id = %s", (mine_open,))
    engine._backfill_current_qty()
    assert _current(mine_open) is None


@needs_db
def test_table_set_up_runs_once_per_process(monkeypatch):
    broker = FakeAlpaca(prices={"SPY": 700.0}, cash=10_000.0)
    engine = make_engine(monkeypatch, broker)
    calls = []
    monkeypatch.setattr(etf_engine_module, "_SCHEMA_READY", False)
    monkeypatch.setattr(etf_engine_module.AlpacaEtfEngine, "_ensure_schema_once",
                        lambda self: calls.append(1) or True)
    for _ in range(3):
        engine._ensure_schema()
    assert calls == [1]
