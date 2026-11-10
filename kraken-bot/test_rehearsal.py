"""The rehearsal script (kraken-bot/rehearsal.py) against the fake broker."""
from __future__ import annotations

from broker_harness import FakeAlpaca, db_exec, ledger, make_engine, needs_db
import rehearsal

PRICES = {"SPY": 700.0, "UGL": 95.0, "AGQ": 60.0, "BIL": 91.5, "SGOV": 100.0}


def _bot3(monkeypatch, **kw):
    broker = FakeAlpaca(prices=dict(PRICES), cash=92_000.0, **kw)
    broker.positions.update({"BIL": 61.33, "SGOV": 10.393})      # Bot 3 on 10 Nov: cash only
    engine = make_engine(monkeypatch, broker, bot_ids=("rehearsal",))
    return broker, engine


@needs_db
def test_full_rehearsal_passes_and_leaves_the_account_as_it_was(monkeypatch):
    broker, engine = _bot3(monkeypatch)
    lines = []
    assert rehearsal.run(engine, bot_paused=True, live=True, out=lines.append) == 0
    assert [l.split()[0] for l in lines] == ["PASS"] * 6 + ["CLEAN:"]
    assert "UGL: tradable" in lines[5] and "AGQ: tradable" in lines[5]
    assert {s: q for s, q in broker.positions.items()} == {"BIL": 61.33, "SGOV": 10.393}
    assert broker.open_stops("SPY") == [] and ledger("rehearsal") == {}
    # every order it sent carried its own owner tag, never the strategy's
    sent = [kw for m, _, kw in broker.log if m == "submit_order"]
    assert sent and all(o.client_order_id.split("-", 1)[1].startswith(("etf-buy-", "etf-stop-rehearsal-", "etf-exit-rehearsal-"))
                        for o in broker.orders.values())


@needs_db
def test_rehearsal_passes_with_the_9_nov_list_lag(monkeypatch):
    broker, engine = _bot3(monkeypatch, cancel_lag_s=300)
    lines = []
    assert rehearsal.run(engine, bot_paused=True, live=True, out=lines.append) == 0, lines


@needs_db
def test_untradable_fund_is_reported_not_failed(monkeypatch):
    broker, engine = _bot3(monkeypatch)
    del broker.prices["AGQ"]
    lines = []
    assert rehearsal.run(engine, bot_paused=True, live=True, out=lines.append) == 0
    assert "AGQ: NOT tradable" in lines[5]


@needs_db
def test_dry_run_and_blocked_runs_send_nothing(monkeypatch):
    broker, engine = _bot3(monkeypatch)
    out = []
    assert rehearsal.run(engine, bot_paused=True, live=False, out=out.append) == 0
    assert out[0].startswith("DRY RUN")
    assert rehearsal.run(engine, bot_paused=False, live=True, out=out.append) == 2
    broker.market_open = False
    assert rehearsal.run(engine, bot_paused=True, live=True, out=out.append) == 2
    broker.market_open = True
    broker.positions["SPY"] = 5.0                       # strategy holding: not an idle account
    assert rehearsal.run(engine, bot_paused=True, live=True, out=out.append) == 2
    assert not [m for m, _, _ in broker.log if m in ("submit_order", "cancel_order", "replace_order")]


@needs_db
def test_failed_step_stops_flattens_and_reports(monkeypatch):
    broker, engine = _bot3(monkeypatch)
    broker.reject_next("stop", n=3)                     # step 1 cannot protect its share
    lines = []
    assert rehearsal.run(engine, bot_paused=True, live=True, out=lines.append) == 1
    assert lines[0].startswith("FAIL  1 buy 1 SPY")
    assert "SPY" not in broker.positions and ledger("rehearsal") == {}
    assert lines[-1].startswith("CLEAN")
