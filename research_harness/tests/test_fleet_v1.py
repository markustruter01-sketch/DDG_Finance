"""FLEET-V1 step 4: sleeves, overfit checks and the exploration runner (synthetic data only)."""

from __future__ import annotations

import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from research_harness.explore import fleet_v1 as fv  # noqa: E402
from research_harness.harness import overfit  # noqa: E402
from research_harness.harness.portfolio import HistoryView  # noqa: E402
from research_harness.sleeves import core_v1, xasset_v1  # noqa: E402


def weekdays(first: date, n: int) -> list[date]:
    out, d = [], first
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars(days, closes):
    out, prev = [], None
    for d, c in zip(days, closes):
        out.append({"day": d, "open": prev or c, "high": max(c, prev or c), "low": min(c, prev or c), "close": c})
        prev = c
    return out


def walk(n, seed, drift=0.0003, vol=0.01):
    rng = random.Random(seed)
    c = [100.0]
    for _ in range(n - 1):
        c.append(c[-1] * (1 + drift + vol * rng.gauss(0, 1)))
    return c


# ── sleeve 1 ──────────────────────────────────────────────────────────────────
def test_votes_and_exposure_follow_the_plan():
    up = [100 * 1.001 ** i for i in range(300)]
    assert core_v1.votes(up) == 3
    assert core_v1.votes(up[:252]) is None
    assert core_v1.target_exposure(3, 0.10) == pytest.approx(1.5)          # calm, three votes
    assert core_v1.target_exposure(3, 0.30) == pytest.approx(0.75)         # vol halves it
    assert core_v1.target_exposure(2, 0.10) == pytest.approx(1.0)
    assert core_v1.target_exposure(1, 0.10) == pytest.approx(0.5)
    assert core_v1.target_exposure(1, 0.90) == 0.0                         # 0.083 < 0.10 -> cash
    assert core_v1.target_exposure(0, 0.10) == 0.0


@pytest.mark.parametrize("e", [0.0, 0.3, 0.75, 1.0, 1.2, 1.5])
@pytest.mark.parametrize("cid", ["C1", "C2"])
def test_two_x_decomposition_gives_the_target_exposure_with_gross_at_most_one(e, cid):
    mix = core_v1.MIXES[cid]
    w = core_v1.weights_for(e, mix)
    buffer = (1 - core_v1.CASH_BUFFER) if e > 1 else 1.0
    assert core_v1.exposure(w) == pytest.approx(e * buffer)
    assert sum(w.values()) <= 1.0 + 1e-12
    assert all(x >= 0 for x in w.values())
    for idx, m in mix.items():                                             # exposure per index = m_i x E
        one, two = core_v1.INSTRUMENTS[idx]
        assert w.get(one, 0) + 2 * w.get(two, 0) == pytest.approx(m * e * buffer)
    if e <= 1:
        assert not set(w) & {"SSO", "QLD"}
    if cid == "C2":
        assert set(w) <= {"SPY", "SSO"}


def test_core_rebalances_only_on_vote_change_or_new_month():
    days = weekdays(date(2000, 1, 3), 400)
    closes = walk(400, 1)
    view = HistoryView({"SPY": bars(days, closes)})
    log: list = []
    strat = core_v1.make_strategy("C2", log)
    calls = []
    for d in days:
        view.today = d
        if strat(d, view) is not None:
            calls.append(d)
    rows = {r[0]: r for r in log}
    prev = None
    for d in days:
        if d not in rows:
            continue
        v = rows[d][1]
        expected = prev is None or v != prev[1] or (d.year, d.month) != (prev[0].year, prev[0].month)
        assert (d in calls) == expected
        prev = rows[d]


def _signal_log(make, sym, days, closes):
    view = HistoryView({sym: bars(days, closes)})
    log: list = []
    strat = make(log)
    for d in days:
        view.today = d
        strat(d, view)
    return log


def test_core_signal_has_no_look_ahead():
    days = weekdays(date(2000, 1, 3), 500)
    a = walk(500, 2)
    b = a[:400] + [x * 0.5 for x in a[400:]]                              # same until day 400
    la = _signal_log(lambda lg: core_v1.make_strategy("C1", lg), "SPY", days, a)
    lb = _signal_log(lambda lg: core_v1.make_strategy("C1", lg), "SPY", days, b)
    cut = days[400]
    assert [r for r in la if r[0] < cut] == [r for r in lb if r[0] < cut]
    assert [r for r in la if r[0] >= cut] != [r for r in lb if r[0] >= cut]


# ── sleeve 2 ──────────────────────────────────────────────────────────────────
def test_line_weight_caps_and_votes():
    calm = [100 * 1.001 ** i * (1 + 0.0005 * (-1) ** i) for i in range(300)]   # tiny vol -> cap
    assert xasset_v1.line_weight(calm) == pytest.approx(xasset_v1.MAX_WEIGHT)
    down = list(reversed(calm))
    assert xasset_v1.line_weight(down) == 0.0                              # no votes -> flat
    assert xasset_v1.line_weight(calm[:200]) == 0.0                        # not enough history


def test_sleeve2_gross_scaled_pro_rata_to_one():
    days = weekdays(date(2000, 1, 3), 300)
    calm = [100 * 1.001 ** i * (1 + 0.0005 * (-1) ** i) for i in range(300)]
    view = HistoryView({s: bars(days, calm) for s in xasset_v1.LINES})
    view.today = days[-1]
    w = xasset_v1.target_weights(view)
    assert set(w) == set(xasset_v1.LINES)
    assert sum(w.values()) == pytest.approx(1.0)                           # 4 x 0.40 scaled to 1
    assert all(x == pytest.approx(0.25) for x in w.values())


def test_sleeve2_divisor_stays_four_with_one_line_on():
    days = weekdays(date(2000, 1, 3), 300)
    noisy = walk(300, 3, drift=0.002, vol=0.01)                            # vol ~16%: below the cap
    view = HistoryView({"IEF": bars(days, noisy)})
    view.today = days[-1]
    w = xasset_v1.target_weights(view)
    vol = xasset_v1.vol63(noisy)
    assert w == {"IEF": pytest.approx(min(0.40, 0.10 / vol / 4))}


def test_sleeve2_monthly_and_no_look_ahead():
    days = weekdays(date(2000, 1, 3), 500)
    a = walk(500, 4)
    b = a[:400] + [x * 2 for x in a[400:]]
    la = _signal_log(lambda lg: xasset_v1.make_strategy(lg, ("IEF",)), "IEF", days, a)
    lb = _signal_log(lambda lg: xasset_v1.make_strategy(lg, ("IEF",)), "IEF", days, b)
    assert len({(d.year, d.month) for d, _ in la}) == len(la)              # once a month
    cut = days[400]
    assert [r for r in la if r[0] < cut] == [r for r in lb if r[0] < cut]


# ── overfit ───────────────────────────────────────────────────────────────────
def test_expected_max_sharpe_grows_with_trials():
    assert overfit.expected_max_sharpe(1, 0.01) == 0.0
    vals = [overfit.expected_max_sharpe(n, 0.01) for n in (2, 5, 19, 100)]
    assert vals == sorted(vals) and vals[0] > 0


def test_deflated_sharpe_properties():
    rng = random.Random(5)
    r = [0.0005 + 0.01 * rng.gauss(0, 1) for _ in range(2500)]
    one = overfit.deflated_sharpe(r, None, 1, 0.0)
    many = overfit.deflated_sharpe(r, None, 19, 0.0004)
    assert 0 < many["dsr"] < one["dsr"] < 1                                 # more trials -> lower
    better = overfit.deflated_sharpe([x + 0.0005 for x in r], None, 19, 0.0004)
    assert better["dsr"] > many["dsr"]
    sk, ku = overfit.skew_kurt([rng.gauss(0, 1) for _ in range(20000)])
    assert abs(sk) < 0.1 and abs(ku - 3) < 0.15


def test_probabilistic_sharpe_is_half_at_the_benchmark():
    assert overfit.probabilistic_sharpe(0.05, 0.05, 1000, 0.0, 3.0) == pytest.approx(0.5)


def test_block_shuffle_keeps_shares_and_month_blocks():
    days = weekdays(date(2000, 1, 3), 300)
    labels = [f"{d.year}-{d.month}" for d in days]
    out = overfit.block_shuffle(days, labels, random.Random(1))
    assert sorted(out) == sorted(labels)
    assert out != labels
    blocks = overfit.month_blocks(days, labels)
    i = 0
    while i < len(out):                                                     # whole blocks only
        blk = next(b for b in blocks if b[0] == out[i] and out[i:i + len(b)] == b)
        i += len(blk)


def test_percentile():
    assert overfit.percentile([1, 2, 3, 4, 5], 50) == 3
    assert overfit.percentile(list(range(101)), 95) == pytest.approx(95)


# ── runner ────────────────────────────────────────────────────────────────────
def test_rolling_windows_fit_inside_exploration():
    w = fv.rolling_windows()
    assert len(w) == 15
    assert w[0] == (date(1987, 1, 1), date(1996, 12, 31))
    assert w[-1][1] <= fv.EXPLORE[1]


def test_haircut_uses_only_rebuilt_instruments():
    cuts = {"SPX_TR vs SPY": 0.02, "SSO_R vs SSO": 0.07, "QLD_R vs QLD": 0.12,
            "NDX_TR 0.8% vs QQQ": 0.05, "UST10_TR vs IEF": 0.01,
            "GSCI plain vs DBC": 0.03, "GSCI + T-bill vs DBC": 0.04,
            "DXY plain vs UUP": 0.02, "DXY + T-bill vs UUP": 0.0}
    until = {"SPY": date(1993, 1, 29), "SSO": date(2006, 6, 21), "QQQ": date(1999, 3, 10),
             "QLD": date(2006, 6, 21), "IEF": date(2002, 7, 30), "DBC": date(2006, 2, 6),
             "UUP": date(2007, 3, 1)}
    assert fv.haircut_for("C2", date(1987, 1, 1), until, cuts) == pytest.approx(0.07)
    assert fv.haircut_for("C1", date(1987, 1, 1), until, cuts) == pytest.approx(0.12)
    assert fv.haircut_for("C1", date(2007, 1, 1), until, cuts) == 0.0     # real ETFs throughout
    assert fv.haircut_for("S2", date(1987, 1, 1), until, cuts) == pytest.approx(0.04)
    assert fv.haircut_for("C2", date(1987, 1, 1), until, {}) is None       # never guessed


def test_selection_rule_and_ties():
    b = {"cagr": 0.10, "sharpe": 0.50, "max_dd": -0.50}
    nums = {"C1": {"cagr": 0.13, "sharpe": 0.75, "max_dd": -0.2},
            "C2": {"cagr": 0.12, "sharpe": 0.74, "max_dd": -0.2},
            "F1": {"cagr": 0.12, "sharpe": 0.90, "max_dd": -0.2},
            "F2": {"cagr": 0.09, "sharpe": 1.20, "max_dd": -0.2}}             # fails (a)
    dd = {k: -0.25 for k in nums}
    r = fv.select(nums, dd, b, n1_sharpe=0.55, n2_p95=0.70)
    assert r["selected"] == "F1" and "F2" not in r["qualified"]
    nums["F1"]["sharpe"] = 0.76                                              # within 0.02 of C1/C2
    assert fv.select(nums, dd, b, 0.55, 0.70)["selected"] == "C2"           # simplest wins
    dd["C2"] = -0.31
    assert fv.select(nums, dd, b, 0.55, 0.70)["selected"] == "C1"
    assert fv.select(nums, dd, b, 0.55, 0.80)["verdict"] == "FAILED"        # none beats N2


def test_cash_rate_floored_at_zero():
    assert fv.cash_rate({date(2010, 1, 4): 0.001, date(2007, 1, 2): 0.05}) == {
        date(2010, 1, 4): 0.0, date(2007, 1, 2): pytest.approx(0.045)}


def test_exploration_runs_end_to_end_on_synthetic_data():
    days = weekdays(date(1985, 10, 1), 1500)                               # to ~1991
    instr = {s: bars(days, walk(len(days), i + 10)) for i, s in
             enumerate(("SPY", "SSO", "QQQ", "QLD", "IEF", "GLD", "DBC", "UUP"))}
    dtb3 = {days[0]: 0.06}
    out = fv.explore(instr, dtb3, {}, {}, window=(date(1987, 1, 1), date(1990, 12, 31)),
                     n2_draws=3, rebuild=lambda y: instr)
    assert set(out["candidates"]) == {"C1", "C2", "F1", "F2"}
    assert set(out["controls"]) == {"B", "A0", "N1", "S2", "N2"}
    assert out["selection"]["verdict"] in ("SELECTED", "FAILED")
    assert out["controls"]["N2"]["draws"] == 3
    for k, s in {**out["candidates"], **out["controls"]}.items():
        if k != "N2":
            assert s["max_gross_leverage"] <= 1.0 + 1e-6, k
    assert set(out["ndx_dividend_sensitivity"]) == {"0.0%", "1.5%"}
