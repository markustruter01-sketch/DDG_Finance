"""VOL-V1 step 2: the gate x PUT model, the V2 estimate, selection, the PUT pull
(synthetic data only; the plan's one exploration run is Fable's)."""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from research_harness import fetch  # noqa: E402
from research_harness.explore import vol_v1 as ev  # noqa: E402
from research_harness.sleeves import vol_v1  # noqa: E402


def weekdays(first: date, n: int) -> list[date]:
    out, d = [], first
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def walk(n, seed, drift=0.0003, vol=0.01, start=100.0):
    rng = random.Random(seed)
    c = [start]
    for _ in range(n - 1):
        c.append(c[-1] * (1 + drift + vol * rng.gauss(0, 1)))
    return c


# ── the gate ──────────────────────────────────────────────────────────────────
def test_gate_is_fleet_v1s_dial_capped_at_one():
    calm_up = [100 * 1.001 ** i for i in range(300)]
    assert vol_v1.gate_n(calm_up) == 1.0                          # three votes, calm: full notional
    assert vol_v1.gate_n(calm_up[:252]) is None                   # not enough history
    down = [100 * 0.999 ** i for i in range(300)]
    assert vol_v1.gate_n(down) == 0.0


def test_gate_scales_by_votes_and_volatility_and_cuts_below_ten_percent(monkeypatch):
    from research_harness.sleeves import core_v1
    monkeypatch.setattr(core_v1, "votes", lambda c: 2)
    monkeypatch.setattr(core_v1, "vol20", lambda c: 0.30)
    assert vol_v1.gate_n([1.0] * 300) == pytest.approx(2 / 3 * 0.5)
    monkeypatch.setattr(core_v1, "votes", lambda c: 1)
    monkeypatch.setattr(core_v1, "vol20", lambda c: 0.60)
    assert vol_v1.gate_n([1.0] * 300) == 0.0                     # 1/3 x 0.25 = 0.083 < 0.10


# ── PUT cycles and V2 ─────────────────────────────────────────────────────────
def test_roll_days_are_third_fridays_or_the_day_before_a_holiday():
    assert vol_v1.third_friday(2026, 11) == date(2026, 11, 20)
    days = weekdays(date(2026, 11, 2), 40)
    days.remove(date(2026, 11, 20))                               # a holiday Friday
    assert vol_v1.roll_days(days)[0] == date(2026, 11, 19)
    assert vol_v1.roll_days(days)[1] == date(2026, 12, 18)


def test_v2_takes_seventy_percent_of_the_premium_and_losses_from_two_percent_lower():
    flat = vol_v1.v2_cycle_return(r_put=0.015, cash=0.004, spx_start=100, spx_end=101)
    assert flat["loss"] == 0.0 and flat["premium"] == pytest.approx(0.011)
    assert flat["r_v2"] == pytest.approx(0.004 + 0.7 * 0.011)
    crash = vol_v1.v2_cycle_return(r_put=-0.085, cash=0.004, spx_start=100, spx_end=90)
    assert crash["loss"] == pytest.approx(0.10) and crash["loss_v2"] == pytest.approx(0.08)
    assert crash["premium"] == pytest.approx(-0.085 - 0.004 + 0.10)
    assert crash["r_v2"] == pytest.approx(0.004 + 0.7 * 0.011 - 0.08)


def test_v2_levels_hit_each_cycles_estimate_and_keep_puts_daily_shocks():
    days = weekdays(date(2001, 1, 2), 90)
    put = dict(zip(days, walk(90, 1, vol=0.008)))
    spx = dict(zip(days, walk(90, 2)))
    rf = {d: 0.0001 for d in days}
    v2 = vol_v1.v2_levels(put, spx, rf)
    rolls = vol_v1.roll_days(days)
    a, b = rolls[0], rolls[1]
    seg = [d for d in days if a < d <= b]
    cash = 1.0
    for _ in seg:
        cash *= 1.0001
    est = vol_v1.v2_cycle_return(put[b] / put[a] - 1, cash - 1, spx[a], spx[b])
    assert v2[b] / v2[a] - 1 == pytest.approx(est["r_v2"], abs=1e-12)
    # inside the cycle every day moves with PUT times one constant factor
    ratios = [(v2[d] / v2[p]) / (put[d] / put[p]) for p, d in zip(seg, seg[1:])]
    assert max(ratios) - min(ratios) < 1e-12


# ── the model ─────────────────────────────────────────────────────────────────
def _eq(curve):
    return {p[0]: p[1] for p in curve}


def _series(days, start=1000.0, step=0.0):
    return {d: start * (1 + step) ** i for i, d in enumerate(days)}


def _fake_gate(monkeypatch, by_day: dict[date, float | None], gate_days):
    index = {i + 1: by_day.get(d) for i, d in enumerate(gate_days)}
    monkeypatch.setattr(vol_v1, "gate_n", lambda closes: index[len(closes)])


def test_a_roll_is_traded_next_open_and_earns_from_the_day_after(monkeypatch):
    days = weekdays(date(2001, 1, 29), 10)                        # 29 Jan .. 9 Feb 2001
    feb1 = date(2001, 2, 1)
    _fake_gate(monkeypatch, {d: (0.5 if d >= feb1 else None) for d in days}, days)
    asset = {d: 100.0 * 1.01 ** i for i, d in enumerate(days)}    # +1% a day
    log: list = []
    curve = _eq(vol_v1.model(asset, _series(days), _series(days, 1000), {days[0]: 0.0},
                              days[0], days[-1], option_costs=False, log=log))
    i = days.index(feb1)
    assert curve[days[i + 1]] / curve[feb1] == pytest.approx(1.0)        # still N = 0 the next day
    fee = 0.5 * vol_v1.COST_BPS_PER_LEG / 1e4
    assert curve[days[i + 2]] / curve[days[i + 1]] == pytest.approx((1 - fee) * 1.005)
    assert [r["kind"] for r in log] == ["roll"]


def test_a_broken_gate_exits_and_stays_out_until_the_next_roll(monkeypatch):
    days = weekdays(date(2001, 1, 29), 30)
    feb1, feb12, mar1 = date(2001, 2, 1), date(2001, 2, 12), date(2001, 3, 1)
    gate = {}
    for d in days:
        if d < feb1:
            gate[d] = None
        elif d < feb12:
            gate[d] = 0.8
        elif d < date(2001, 2, 15):
            gate[d] = 0.0                                         # breaks
        else:
            gate[d] = 0.8                                         # recovers mid-month: no re-entry
    _fake_gate(monkeypatch, gate, days)
    asset = {d: 100.0 * 1.01 ** i for i, d in enumerate(days)}
    log: list = []
    curve = _eq(vol_v1.model(asset, _series(days), _series(days, 1000), {days[0]: 0.0},
                              days[0], days[-1], log=log))
    assert [r["kind"] for r in log] == ["roll", "exit", "roll"]
    assert log[1]["day"] == feb12 and log[2]["day"] == mar1
    flat = [d for d in days if days.index(feb12) + 2 <= days.index(d) <= days.index(mar1) + 1]
    for p, d in zip(flat, flat[1:]):
        assert curve[d] == pytest.approx(curve[p])                # out: earns cash (0 here)


def test_roll_costs_are_two_legs_of_two_bp_plus_contract_fees(monkeypatch):
    days = weekdays(date(2001, 1, 29), 30)
    _fake_gate(monkeypatch, {d: (None if d < date(2001, 2, 1) else 0.6) for d in days}, days)
    log: list = []
    vol_v1.model(_series(days, 100), _series(days), _series(days, 1000), {days[0]: 0.0},
                 days[0], days[-1], log=log)
    first, second = log[0], log[1]
    fee = 0.6 * 0.65 / (1000 * 0.10 * 100)                        # strike $100, 100 shares
    assert first["cost"] == pytest.approx(0.6 * 2e-4 + fee)      # open only
    assert second["cost"] == pytest.approx(2 * (0.6 * 2e-4 + fee))  # close + open


def test_ungated_is_the_asset_itself():
    days = weekdays(date(2001, 1, 2), 50)
    asset = dict(zip(days, walk(50, 3)))
    curve = vol_v1.model(asset, asset, _series(days), {days[0]: 0.05}, days[0], days[-1], ungated=True)
    assert curve[-1][1] == pytest.approx(asset[days[-1]] / asset[days[0]])


# ── selection ─────────────────────────────────────────────────────────────────
B = {"cagr": 0.10, "sharpe": 0.40, "max_dd": -0.50}
PUT = {"cagr": 0.09, "sharpe": 0.50, "max_dd": -0.32}


def test_selection_needs_all_four_checks_and_picks_the_higher_cagr():
    good = {"cagr": 0.095, "sharpe": 0.60, "max_dd": -0.22}
    better = {"cagr": 0.105, "sharpe": 0.58, "max_dd": -0.24}
    out = ev.select({"V1": good, "V2": better}, B, PUT)
    assert out["selected"] == "V2"
    tie = {"cagr": 0.098, "sharpe": 0.58, "max_dd": -0.24}         # within half a point: V1
    assert ev.select({"V1": good, "V2": tie}, B, PUT)["selected"] == "V1"


@pytest.mark.parametrize("bad, check", [
    ({"cagr": 0.095, "sharpe": 0.54, "max_dd": -0.22}, "a_sharpe_ge_B_plus_0.15"),
    ({"cagr": 0.095, "sharpe": 0.60, "max_dd": -0.26}, "b_max_dd_ge_-25%_and_0.6xB"),
    ({"cagr": 0.085, "sharpe": 0.60, "max_dd": -0.22}, "c_cagr_ge_B_minus_1pt"),
])
def test_each_check_can_fail_the_plan(bad, check):
    out = ev.select({"V1": bad, "V2": bad}, B, PUT)
    assert out["verdict"] == "VOL-V1 FAILED" and out["checks"]["V1"][check] is False


def test_the_gate_must_beat_ungated_put():
    v = {"cagr": 0.095, "sharpe": 0.60, "max_dd": -0.20}
    assert ev.select({"V1": v, "V2": v}, B, {**PUT, "sharpe": 0.61})["verdict"] == "VOL-V1 FAILED"
    small_b = {"cagr": 0.10, "sharpe": 0.40, "max_dd": -0.30}    # 0.6 x B = -18%
    assert ev.select({"V1": v, "V2": v}, small_b, PUT)["checks"]["V1"]["b_max_dd_ge_-25%_and_0.6xB"] is False


# ── the runner (synthetic) ────────────────────────────────────────────────────
def test_explore_runs_end_to_end_on_synthetic_data():
    days = weekdays(date(1986, 7, 1), 4300)                       # to about 2003
    spy = dict(zip(days, walk(len(days), 4, drift=0.0004)))
    spx = dict(zip(days, walk(len(days), 5, start=250)))
    put = dict(zip(days, walk(len(days), 6, drift=0.0003, vol=0.006)))
    dtb3 = {days[0]: 0.04}
    out = ev.explore(put, spy, spx, dtb3, window=(date(1988, 1, 1), days[-1]))
    assert set(out["candidates"]) == {"V1", "V2"}
    assert {"B", "PUT", "N1"} <= set(out["controls"])
    assert out["selection"]["verdict"] in ("SELECTED", "VOL-V1 FAILED")
    assert out["candidates"]["V1"]["gate"]["rolls"] > 150
    assert set(out["deflated_sharpe_exploration"]) == {"V1", "V2"}


def test_the_run_never_reads_past_the_exploration_window(monkeypatch):
    ends = []

    class Store:
        def load(self, ds, sym, *, start, end, **k):
            ends.append(end)
            return []

        def load_rates(self, ds, s, *, start, end, **k):
            ends.append(end)
            return {}

    class Stop(Exception):
        pass

    def stop(*a, **k):
        raise Stop

    monkeypatch.setattr(ev.rc, "build", stop)
    with pytest.raises(Stop):
        ev.run(Store(), log_path=None)
    assert ends and max(ends) == date(2010, 12, 31) < ev.HELDOUT[0]


def test_the_run_stops_without_the_put_data(tmp_path):
    from research_harness.harness.store import BarStore
    with pytest.raises(SystemExit, match="no fallback"):
        ev.run(BarStore(tmp_path), log_path=None)


# ── the PUT pull ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Cboe data is provided for information only\n\nDATE,PUT\n06/30/1986,100.00\n07/01/1986,100.42\n01/03/2011,1,234.50\n",
    "DATE,OPEN,HIGH,LOW,CLOSE\n1986-06-30,100,100,100,100.00\n1986-07-01,100,101,99,100.42\n2011-01-03,1,1,1,1234.50\n",
])
def test_cboe_csv_parses_both_layouts(text):
    text = text.replace("1,234.50", '"1,234.50"')
    rows = fetch.parse_cboe_index_csv(text, "PUT")
    assert rows[0] == {"day": date(1986, 6, 30), "close": 100.0}
    assert rows[-1]["close"] == 1234.5


def test_the_put_pull_writes_an_open_part_that_stops_before_the_held_out(tmp_path):
    from research_harness.harness.store import BarStore

    class Resp:
        text = "DATE,PUT\n12/30/2010,500\n12/31/2010,501\n"

        def raise_for_status(self):
            pass

    store = BarStore(tmp_path)
    m = fetch.fetch_cboe_put(store, "vol_put_cboe", "1986-06-30", "2010-12-31",
                             http_get=lambda url, params=None: Resp(), locked_from=date(2011, 1, 1))
    assert m["locked_from"] == "2011-01-01" and m["symbols"]["PUT"]["rows"] == 2
    assert store.load("vol_put_cboe", "PUT", start=date(2010, 1, 1), end=date(2010, 12, 31))[-1]["close"] == 501.0
