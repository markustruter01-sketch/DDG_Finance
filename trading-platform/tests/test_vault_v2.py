"""VAULT-V2 (sleeve_runtime/VAULT-V2-SPEC.md): monthly 10% high-water skim,
BIL only, the VOO sold once, the dashboard summary."""

from __future__ import annotations

import pathlib
import sys
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from execution import per_bot_vault as vault  # noqa: E402

NY = ZoneInfo("America/New_York")


# ── the rule ────────────────────────────────────────────────────────────────

def test_skim_is_ten_percent_of_the_new_high_and_the_mark_resets_after_it():
    skim, mark = vault.hwm_skim(103_000.0, 100_000.0)
    assert skim == 300.0
    assert mark == 102_700.0                    # post-skim trading equity


@pytest.mark.parametrize("equity", [100_000.0, 99_000.0, 80_000.0])
def test_no_skim_at_or_below_the_mark_and_the_mark_stays(equity):
    assert vault.hwm_skim(equity, 100_000.0) == (0.0, 100_000.0)


def test_a_recovering_month_skims_nothing_until_the_old_high_is_passed():
    mark = 100_000.0
    for equity in (90_000.0, 95_000.0, 99_999.0):      # up month after month, still under the mark
        skim, mark = vault.hwm_skim(equity, mark)
        assert skim == 0.0 and mark == 100_000.0
    skim, mark = vault.hwm_skim(101_000.0, mark)
    assert skim == 100.0 and mark == 100_900.0          # only the gain above the old high


def test_plan_seeds_then_skims_once_a_month():
    seed = vault.plan_skim(month="2026-11", trading_equity=95_000.0, mark=None, mark_month=None, skimmed_months=set())
    assert seed == {"action": "seed", "mark_after": 95_000.0, "amount": 0.0}
    same_month = vault.plan_skim(month="2026-11", trading_equity=99_000.0, mark=95_000.0,
                                 mark_month="2026-11", skimmed_months=set())
    assert same_month["action"] == "none"                # the seed month never skims
    dec = vault.plan_skim(month="2026-12", trading_equity=99_000.0, mark=95_000.0,
                          mark_month="2026-11", skimmed_months=set())
    assert dec == {"action": "skim", "amount": 400.0, "mark_before": 95_000.0, "mark_after": 98_600.0}
    again = vault.plan_skim(month="2026-12", trading_equity=99_500.0, mark=98_600.0,
                            mark_month="2026-12", skimmed_months={"2026-12"})
    assert again["action"] == "none"
    down = vault.plan_skim(month="2027-01", trading_equity=97_000.0, mark=98_600.0,
                           mark_month="2026-12", skimmed_months=set())
    assert down["action"] == "below_mark" and down["amount"] == 0.0 and down["mark_after"] == 98_600.0


def test_every_contribution_goes_to_bil():
    assert vault.split_contribution(123.45) == (123.45, 0.0)
    assert vault.split_contribution(-5) == (0.0, 0.0)


@pytest.mark.parametrize("today, expected", [
    (date(2026, 11, 2), date(2026, 12, 1)),
    (date(2026, 12, 10), date(2027, 1, 1)),       # a holiday: the job runs anyway, on the prior close
    (date(2027, 4, 20), date(2027, 5, 3)),        # 1 May 2027 is a Saturday
])
def test_next_skim_day_is_the_first_weekday_of_next_month(today, expected):
    assert vault.next_skim_day(today) == expected


def test_the_per_trade_hook_and_quarterly_rebalance_are_gone():
    assert not hasattr(vault, "record_profitable_close")
    assert not hasattr(vault, "run_quarterly_rebalance")
    assert vault.SKIM_RATE == 0.10


# ── the job, against a recording database ───────────────────────────────────

class _Cursor:
    def __init__(self, db):
        self.db, self.description, self._rows, self._one = db, [], [], None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        assert sql.count("%s") == len(params or ()), sql
        q = " ".join(sql.split()).lower()
        self.db.executed.append((q, params))
        self._rows, self._one = [], None
        for prefix, rows in self.db.selects.items():
            if q.startswith(prefix):
                self._rows = list(rows)
        if "returning id" in q:
            self._one = (1,)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one if self._one is not None else (self._rows[0] if self._rows else None)


class _DB:
    def __init__(self, selects):
        self.selects, self.executed = selects, []

    @contextmanager
    def conn(self):
        db = self

        class _Conn:
            def cursor(self):
                return _Cursor(db)
        yield _Conn()

    def writes(self, table):
        return [(q, p) for q, p in self.executed if not q.startswith("select") and table in q.split("(")[0]]


@pytest.fixture
def fake(monkeypatch):
    import db.postgres

    def install(selects, *, equity=103_000.0, prices=None):
        d = _DB(selects)
        monkeypatch.setattr(db.postgres, "get_conn", d.conn)
        monkeypatch.setattr(db.postgres, "is_pg_available", lambda: True)
        monkeypatch.setattr(vault, "vault_enabled", lambda: True)
        monkeypatch.setattr(vault, "ensure_schema", lambda: None)
        monkeypatch.setattr(vault, "_broker_equity", lambda bot_id: equity)
        monkeypatch.setattr(vault, "_latest_vault_prices",
                            lambda bot_id, symbols: {s: (prices or {"BIL": 91.5})[s] for s in symbols})
        return d
    return install


ACCOUNTS = "select a.bot_id, a.cash_usd"
SKIMMED = "select bot_id, month from per_bot_vault_skims"


def test_month_start_skims_ten_percent_of_trading_equity_above_the_mark(fake):
    # Vault: $50 cash + 20 BIL at 91.50 = $1,880. Broker equity 103,000 -> trading 101,120.
    d = fake({ACCOUNTS: [("oracle", 50.0, 0.0, 100_000.0, "2026-11", 20.0, 0.0)], SKIMMED: []})
    out = vault.run_monthly_skim(now=datetime(2026, 12, 1, 8, 45, tzinfo=NY))
    bot = out["bots"][0]
    assert bot["trading_equity"] == 101_120.0 and bot["vault_value"] == 1_880.0
    assert bot["action"] == "skim" and bot["amount"] == 112.0 and bot["mark_after"] == 101_008.0
    (ledger_sql, ledger), = d.writes("per_bot_vault_skims")
    assert ledger == ("oracle", "2026-12", date(2026, 12, 1), 103_000.0, 1_880.0, 101_120.0, 100_000.0, 101_008.0, 112.0)
    assert d.writes("per_bot_vault_marks")[0][1] == (101_008.0, "2026-12", "oracle")
    assert d.writes("per_bot_vault_contributions")[0][1][1] == "hwm-2026-12"
    assert d.writes("per_bot_vault_deployment_queue")[0][1] == ("oracle", 112.0)
    assert d.writes("per_bot_vault_value_history")


def test_a_down_month_writes_the_ledger_row_and_moves_nothing(fake):
    d = fake({ACCOUNTS: [("oracle", 0.0, 0.0, 110_000.0, "2026-11", 0.0, 0.0)], SKIMMED: []})
    out = vault.run_monthly_skim(now=datetime(2026, 12, 1, 8, 45, tzinfo=NY))
    assert out["bots"][0]["action"] == "below_mark"
    assert d.writes("per_bot_vault_skims")[0][1][-1] == 0.0
    assert not d.writes("per_bot_vault_deployment_queue")
    assert not d.writes("per_bot_vault_contributions")
    assert not [w for w in d.writes("per_bot_vault_accounts")]


def test_the_rest_of_the_month_only_records_the_daily_value(fake):
    d = fake({ACCOUNTS: [("oracle", 0.0, 0.0, 100_000.0, "2026-12", 0.0, 0.0)], SKIMMED: [("oracle", "2026-12")]})
    out = vault.run_monthly_skim(now=datetime(2026, 12, 2, 8, 45, tzinfo=NY))
    assert out["bots"][0]["action"] == "none"
    assert [q.split()[2] for q, _ in d.executed if not q.startswith("select")] == ["per_bot_vault_value_history"]


def test_the_first_run_seeds_the_mark_without_skimming(fake):
    d = fake({ACCOUNTS: [("oracle", 0.0, 0.0, None, None, 0.0, 0.0)], SKIMMED: []})
    out = vault.run_monthly_skim(now=datetime(2026, 11, 3, 8, 45, tzinfo=NY))
    assert out["bots"][0]["action"] == "seed"
    assert d.writes("per_bot_vault_marks")[0][1] == ("oracle", 103_000.0, "2026-11")
    assert not d.writes("per_bot_vault_skims")


def test_the_job_does_nothing_while_the_vault_is_off(monkeypatch):
    monkeypatch.setattr(vault, "vault_enabled", lambda: False)
    assert vault.run_monthly_skim()["status"] == "blocked"
    assert vault.run_voo_liquidation(market_open=True)["status"] == "blocked"


# ── the one-time VOO sale ───────────────────────────────────────────────────

LIQ = "select a.bot_id, coalesce(h.qty, 0)"


def test_voo_is_sold_once_and_the_proceeds_are_queued_for_bil(fake, monkeypatch):
    sells = []
    monkeypatch.setattr(vault, "_orders_today", {})
    monkeypatch.setattr(vault, "_submit_vault_sell",
                        lambda bot_id, symbol, qty, tag: sells.append((symbol, qty)) or
                        {"order_id": "sell-1", "client_order_id": "c", "status": "accepted", "qty": qty})
    d = fake({LIQ: [("oracle", 3.0, 1800.0, None, None, None)]})
    out = vault.run_voo_liquidation(market_open=True)
    assert sells == [("VOO", 3.0)] and out["bots"][0]["action"] == "submitted"
    assert d.writes("per_bot_vault_liquidations")[0][1] == ("oracle", "sell-1", 3.0)

    monkeypatch.setattr(vault, "_read_vault_order", lambda bot_id, oid: {
        "status": "filled", "filled_qty": 3.0, "filled_avg_price": 610.0, "replaced_by": None})
    d = fake({LIQ: [("oracle", 3.0, 1800.0, "sell-1", "submitted", None)]})
    out = vault.run_voo_liquidation(market_open=True)
    assert out["bots"][0] == {"bot_id": "oracle", "action": "sold", "qty": 3.0, "proceeds": 1830.0, "left": 0.0}
    assert d.writes("per_bot_vault_holdings")[0][1] == (0.0, 0.0, "oracle")
    assert d.writes("per_bot_vault_deployment_queue")[0][1] == ("oracle", 1830.0)
    assert "status = 'complete'" in d.writes("per_bot_vault_liquidations")[0][0]

    d = fake({LIQ: [("oracle", 0.0, 0.0, "sell-1", "complete", None)]})
    sells.clear()
    assert vault.run_voo_liquidation(market_open=True)["bots"] == [] and sells == []


def test_voo_sale_waits_for_the_open_and_for_an_open_voo_buy(fake, monkeypatch):
    monkeypatch.setattr(vault, "_submit_vault_sell", lambda *a: pytest.fail("sold while it should wait"))
    fake({LIQ: [("oracle", 3.0, 1800.0, None, None, None)]})
    assert vault.run_voo_liquidation(market_open=False)["bots"][0]["reason"] == "market_closed"
    fake({LIQ: [("oracle", 3.0, 1800.0, None, None, "voo-buy-open")]})
    assert vault.run_voo_liquidation(market_open=True)["bots"][0]["reason"] == "open_voo_buy"


# ── the dashboard card ──────────────────────────────────────────────────────

def test_summary_view_reports_value_income_and_distance_from_the_mark():
    hist = [{"recorded_at": date(2026, 11, d), "trading_capital": 100_000.0 + d * 100,
             "vault_value": 2_000.0 + d, "combined_total": 102_000.0 + d * 101} for d in range(2, 31)]
    # The 1 Dec row is written before that morning's $300 skim lands in the vault.
    hist += [{"recorded_at": date(2026, 12, 1), "trading_capital": 103_000.0,
              "vault_value": 2_031.0, "combined_total": 105_031.0},
             {"recorded_at": date(2026, 12, 2), "trading_capital": 103_100.0,
              "vault_value": 2_332.5, "combined_total": 105_432.5}]
    out = vault.summary_view(
        today=date(2026, 12, 2),
        accounts=[{"bot_id": "oracle", "seed_amount": 2_000.0, "cumulative_contributions": 300.0,
                   "mark": 102_700.0, "mark_month": "2026-12", "bil_qty": 25.0, "voo_qty": 0.0}],
        history={"oracle": hist},
        contributions={"oracle": [{"created_at": date(2026, 12, 1), "skim_amount": 300.0}]})
    bot = out["bots"][0]
    assert out["next_skim"] == "2027-01-01" and out["total"] == 2_332.5
    assert bot["money_in"] == 2_300.0 and bot["income_lifetime"] == 32.5
    assert bot["income_month"] == 1.5                       # 2,332.5 - 2,031 - the 300 skim
    assert bot["contributions_year"] == 300.0
    assert bot["from_mark"] == pytest.approx(103_100.0 / 102_700.0 - 1, abs=1e-4)
    assert bot["yield_30d_realized"] is not None


def test_summary_view_is_empty_before_the_first_daily_mark():
    out = vault.summary_view(today=date(2026, 11, 2), accounts=[
        {"bot_id": "oracle", "seed_amount": 0, "cumulative_contributions": 0, "mark": None,
         "mark_month": None, "bil_qty": 0, "voo_qty": 0}], history={}, contributions={})
    assert out["total"] is None and out["bots"][0]["value"] is None and out["bots"][0]["from_mark"] is None
