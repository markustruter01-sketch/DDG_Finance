"""FLEET-V1 step 3: data fetchers, reconstructions and calibration (synthetic data only)."""

from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from research_harness import fetch  # noqa: E402
from research_harness.harness.costs import SymbolCosts  # noqa: E402
from research_harness.harness.store import BarStore  # noqa: E402
from research_harness.recon import calibrate as cb  # noqa: E402
from research_harness.recon import reconstruct as rc  # noqa: E402


def weekdays(first: date, n: int) -> list[date]:
    out, d = [], first
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars_from(levels: list[tuple[date, float]]) -> list[dict]:
    return [{"day": d, "open": v, "high": v, "low": v, "close": v} for d, v in levels]


# ── fetchers ──────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_fetch_fred_writes_decimal_rates_and_honours_the_lock(tmp_path):
    csv_text = "observation_date,DGS10\n2010-12-30,3.40\n2010-12-31,.\n2011-01-03,3.36\n"
    store = BarStore(tmp_path)
    calls = []

    def get(url, params):
        calls.append(params)
        return _Resp(csv_text)

    fetch.fetch_fred(store, "r", ["DGS10"], "2010-12-01", "2010-12-31", http_get=get,
                     locked_from=date(2011, 1, 1))
    rates = store.load_rates("r", "DGS10", start=date(2010, 1, 1), end=date(2010, 12, 31))
    assert rates == {date(2010, 12, 30): pytest.approx(0.034)}       # '.' dropped, % -> decimal
    assert calls[0]["id"] == "DGS10"
    assert store.manifest("r")["locked_from"] == "2011-01-01"


def test_fetch_fred_fails_loudly_on_empty_window(tmp_path):
    with pytest.raises(RuntimeError, match="no observations"):
        fetch.fetch_fred(BarStore(tmp_path), "r", ["DTB3"], "2010-01-01", "2010-01-31",
                         http_get=lambda u, p: _Resp("observation_date,DTB3\n2011-03-01,0.10\n"))


def test_parse_shiller_rows_reads_months_and_skips_unpublished():
    rows = [
        ["Date", "P", "D"],                 # header
        [1987.01, 264.5, 8.3],
        [1987.1, 280.2, 8.6],               # 1987.1 is October, not January
        [1987.11, 245.0, 8.7],
        [2026.09, 6500.0, ""],              # dividend not yet published
        [2026.1, 6600.0, 0.0],
    ]
    out = fetch.parse_shiller_rows(rows, date(1985, 1, 1), date(2026, 12, 31))
    assert [r["day"] for r in out] == [date(1987, 1, 1), date(1987, 10, 1), date(1987, 11, 1)]
    assert out[1]["dividend"] == pytest.approx(8.6)


# ── costs ─────────────────────────────────────────────────────────────────────
def test_symbol_costs_per_symbol_and_sell_fee():
    c = SymbolCosts(per_trade_bps={"SPY": 5.0, "SSO": 10.0}, sell_fee_bps=0.3,
                    short_borrow_bps_yr=0.0, financing_spread_bps_yr=50.0)
    assert c.trade_cost_for("SPY", 10_000) == pytest.approx(5.0)
    assert c.trade_cost_for("SPY", -10_000) == pytest.approx(5.3)
    assert c.trade_cost_for("SSO", 10_000) == pytest.approx(10.0)
    with pytest.raises(KeyError):
        c.trade_cost_for("QQQ", 10_000)


# ── reconstructions ───────────────────────────────────────────────────────────
def test_align_carries_forward_never_back():
    cal = weekdays(date(2000, 1, 3), 5)
    out = rc.align({cal[1]: 1.0, cal[3]: 2.0}, cal)
    assert out == [(cal[1], 1.0), (cal[2], 1.0), (cal[3], 2.0), (cal[4], 2.0)]


def test_sp500_tr_pays_dividend_once_on_first_session_of_month():
    days = [date(2000, 1, 28), date(2000, 1, 31), date(2000, 2, 1), date(2000, 2, 2)]
    price = [(d, 100.0) for d in days]
    tr = rc.sp500_tr(price, [{"day": date(1999, 11, 1), "dividend": 12.0},   # paid Feb (lag 3)
                             {"day": date(2000, 2, 1), "dividend": 24.0}])   # paid May: not here
    assert rc.SHILLER_LAG_MONTHS == 3
    assert tr[1][1] == pytest.approx(100.0)
    assert tr[2][1] == pytest.approx(101.0)           # Nov's 12/12 = 1 point on 1 Feb
    assert tr[3][1] == pytest.approx(101.0)           # not again on 2 Feb


def test_bond_tr_matches_declared_formula():
    y = 0.06
    d = (1 - (1 + y / 2) ** -20) / (y / 2)
    assert rc.bond_duration(y) == pytest.approx(d)
    cal = weekdays(date(2000, 1, 3), 3)
    tr = rc.bond_tr([(cal[0], 0.06), (cal[1], 0.06), (cal[2], 0.07)])
    assert tr[1][1] / tr[0][1] - 1 == pytest.approx(0.06 / 252)
    assert tr[2][1] / tr[1][1] - 1 == pytest.approx(-d * 0.01 + 0.06 / 252)


def test_levered_is_twice_minus_financing_and_fee():
    cal = weekdays(date(2000, 1, 3), 3)
    under = [(cal[0], 100.0), (cal[1], 101.0), (cal[2], 99.99)]
    rf = {cal[0]: 0.05}
    lev = rc.levered(under, rf, fee=0.0095)
    drag = (0.05 + 0.005) / 252 + 0.0095 / 252
    assert lev[1][1] / lev[0][1] - 1 == pytest.approx(2 * 0.01 - drag)
    assert lev[2][1] / lev[1][1] - 1 == pytest.approx(2 * (99.99 / 101 - 1) - drag)


def test_add_yield_accrues_daily():
    cal = weekdays(date(2000, 1, 3), 253)
    s = rc.add_yield([(d, 100.0) for d in cal], 0.008)
    assert s[-1][1] / s[0][1] == pytest.approx((1 + 0.008 / 252) ** 252)


def test_splice_meets_etf_on_its_first_day():
    cal = weekdays(date(2000, 1, 3), 10)
    recon = [(d, 100.0 * 1.01 ** i) for i, d in enumerate(cal)]
    etf = bars_from([(d, 50.0 * 1.02 ** i) for i, d in enumerate(cal[5:])])
    out = rc.splice(recon, etf)
    assert [b["day"] for b in out] == cal
    assert out[4]["close"] == pytest.approx(50.0 / 1.01)       # rebuilt return kept, level scaled
    assert out[5] == etf[0]                                     # real ETF from its first day
    assert out[1]["open"] == out[0]["close"]                    # close-to-close bars before


def test_splice_without_etf_is_the_rebuilt_series():
    cal = weekdays(date(2000, 1, 3), 3)
    out = rc.splice([(d, 10.0 + i) for i, d in enumerate(cal)], None)
    assert [b["close"] for b in out] == [10.0, 11.0, 12.0]


def _world(n: int = 600, etf_from: int = 300):
    cal = weekdays(date(1999, 1, 4), n)
    wave = [(d, 100.0 * (1 + 0.1 * math.sin(i / 40)) * 1.0003 ** i) for i, d in enumerate(cal)]
    idx = {s: bars_from(wave) for s in rc.INDEX.values()}
    rates = {"DTB3": {cal[0]: 0.04}, "DGS10": {d: 0.05 + 0.005 * math.sin(i / 50) for i, (d, _) in enumerate(wave)}}
    shiller = [{"day": date(y, m, 1), "dividend": 1.2} for y in (1999, 2000, 2001) for m in range(1, 13)]
    built = rc.build(idx, {}, rates, shiller)
    etfs = {}
    for sym, name in rc.REAL_ETF.items():
        if name in built["recon"]:
            etfs[sym] = bars_from(built["recon"][name][etf_from:])
    return idx, etfs, rates, shiller, cal


def test_build_produces_every_instrument_on_one_calendar():
    idx, etfs, rates, shiller, cal = _world()
    out = rc.build(idx, etfs, rates, shiller)
    assert set(out["instruments"]) == set(rc.REAL_ETF) - {"GLD"}     # no gold source, no GLD given
    for bars in out["instruments"].values():
        assert [b["day"] for b in bars] == cal
    out = rc.build(idx, {**etfs, "GLD": bars_from([(d, 1.0) for d in cal[400:]])}, rates, shiller)
    assert out["instruments"]["GLD"][0]["day"] == cal[400]           # real GLD only


def test_calibration_of_an_exact_reconstruction_has_no_gap():
    idx, etfs, rates, shiller, _ = _world()
    rep = cb.calibrate(idx, etfs, rates, shiller)
    p = rep["pairs"]["SSO_R vs SSO"]
    assert p["correlation"] == pytest.approx(1.0)
    assert p["return_gap"] == pytest.approx(0.0, abs=1e-12)
    assert p["haircut"] == pytest.approx(0.0, abs=1e-12)
    assert "GOLD vs GLD" in rep["missing"]
    assert {"GSCI + T-bill vs DBC", "DXY + T-bill vs UUP", "NDX_TR 1.5% vs QQQ"} <= set(rep["pairs"])


def test_haircut_only_when_the_etf_fell_further():
    cal = weekdays(date(2000, 1, 3), 100)
    etf = [(d, 100.0 - (30.0 if 40 <= i < 60 else 0.0)) for i, d in enumerate(cal)]
    shallow = [(d, 100.0 - (10.0 if 40 <= i < 60 else 0.0)) for i, d in enumerate(cal)]
    deep = [(d, 100.0 - (50.0 if 40 <= i < 60 else 0.0)) for i, d in enumerate(cal)]
    assert cb.compare(shallow, etf)["haircut"] == pytest.approx(0.20)
    assert cb.compare(deep, etf)["haircut"] == 0.0


def test_calibration_never_reads_past_exploration():
    cal = weekdays(date(2010, 6, 1), 200)                      # runs into 2011
    s = [(d, 100.0 + i) for i, d in enumerate(cal)]
    assert cb.compare(s, s)["last"] <= "2010-12-31"
