"""FLEET-V1 step 7: the held-out runner heldout/fleet_v1_f1.py (synthetic data only)."""

from __future__ import annotations

import inspect
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from research_harness.explore import fleet_v1 as fv  # noqa: E402
from research_harness.harness import registry  # noqa: E402
from research_harness.harness.store import BarStore  # noqa: E402
from research_harness.heldout import fleet_v1_f1 as f1  # noqa: E402
from research_harness.recon import reconstruct as rc  # noqa: E402

LOCK = date(2011, 1, 1)
FIRST, LAST = date(2008, 1, 2), date(2021, 3, 31)


def weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def walk_bars(days, seed, drift=0.0003, vol=0.01):
    rng, c, out = random.Random(seed), 100.0, []
    for d in days:
        prev = c
        c *= 1 + drift + vol * rng.gauss(0, 1)
        out.append({"day": d, "open": prev, "high": max(c, prev) * 1.002,
                    "low": min(c, prev) * 0.998, "close": c})
    return out


def split(rows):
    return [r for r in rows if r["day"] < LOCK], [r for r in rows if r["day"] >= LOCK]


def write(store: BarStore, ds: str, data: dict, **kw):
    open_part = {s: split(r)[0] for s, r in data.items()}
    locked_part = {s: split(r)[1] for s, r in data.items()}
    store.write_dataset(ds, source="synthetic", bars_by_symbol=open_part, locked_from=LOCK, **kw)
    store.write_dataset(ds, source="synthetic", bars_by_symbol=locked_part, locked=True, **kw)


@pytest.fixture
def setup(tmp_path):
    days = weekdays(FIRST, LAST)
    store = BarStore(tmp_path / "data")
    write(store, fv.DATASETS["index"], {s: walk_bars(days, i) for i, s in enumerate(rc.INDEX.values())})
    write(store, fv.DATASETS["etf"], {s: walk_bars(days, 10 + i) for i, s in enumerate(rc.REAL_ETF)})
    rates = {"DTB3": [{"day": d, "rate": 0.02} for d in days],
             "DGS10": [{"day": d, "rate": 0.03 + 0.005 * ((i // 250) % 2)} for i, d in enumerate(days)]}
    write(store, fv.DATASETS["rates"], rates, fields=("day", "rate"), positive_fields=())
    months = sorted({date(d.year, d.month, 1) for d in days})
    write(store, fv.DATASETS["shiller"], {"SP500": [{"day": m, "price": 1000.0, "dividend": 20.0} for m in months]},
          fields=("day", "price", "dividend"))
    reg = json.loads((registry.REGISTRATIONS_DIR / "FLEET-V1-F1.json").read_text())
    reg["data"] = {**reg["data"], **{ds: store.manifest_hash(ds) for ds in fv.DATASETS.values()}}
    regs = tmp_path / "regs"
    regs.mkdir()
    (regs / "FLEET-V1-F1.json").write_text(json.dumps(reg))
    paths = dict(directory=regs, ledger=tmp_path / "ledger.jsonl", run_starts=tmp_path / "starts.jsonl")
    return store, paths


def test_runner_end_to_end_writes_one_ledger_line(setup):
    store, paths = setup
    out = f1.run(store, **paths)
    assert out["verdict"] == "PASS" or out["verdict"].startswith("FAIL: ")
    assert out["test"]["window"] == ["2011-01-01", "2020-12-31"]
    assert out["spent_information_only"]["label"] == "information only, spent"
    for k in ("F1", "C1", "S2", "B"):
        s = out["test"]["series"][k]
        assert s["exact"] is not None and "correlation_to_B" in s
        assert s["max_gross_leverage"] <= 1.0 + 1e-6, k
    assert "signal" in out["test"]["series"]["C1"] and "signal" in out["test"]["series"]["S2"]
    assert len(out["test"]["pass_bar"]["items"]) == 5
    lines = paths["ledger"].read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["registration_id"] == "FLEET-V1-F1" and entry["kind"] == "holdout_test"
    assert entry["result"]["verdict"] == out["verdict"]
    for ds in fv.DATASETS.values():
        assert entry["data_manifests"][ds] == store.manifest_hash(ds)
        assert entry["data_manifests"][f"{ds}/_locked"] == store.locked_manifest_hash(ds)


def test_second_start_is_refused(setup):
    store, paths = setup
    f1.run(store, record=False, **paths)                  # started but not recorded
    with pytest.raises(registry.RegistrationError, match="already started"):
        f1.run(store, **paths)


def test_second_run_after_recording_is_refused(setup):
    store, paths = setup
    f1.run(store, **paths)
    with pytest.raises(registry.RegistrationError):
        f1.run(store, **paths)
    assert len(paths["ledger"].read_text().splitlines()) == 1


def test_mismatched_data_refused_before_the_start_is_spent(setup):
    store, paths = setup
    reg_path = paths["directory"] / "FLEET-V1-F1.json"
    reg = json.loads(reg_path.read_text())
    reg["data"]["fleet_etf_y"] = "0" * 64
    reg_path.write_text(json.dumps(reg))
    with pytest.raises(RuntimeError, match="pinned manifest hash"):
        f1.run(store, **paths)
    assert not paths["run_starts"].exists()


def test_pass_bar_evaluation():
    b = {"cagr": 0.10, "sharpe": 0.50, "max_dd": -0.34}
    good = {"cagr": 0.11, "sharpe": 0.61, "max_dd": -0.20}
    ok = f1.evaluate_pass_bar(good, b, 0.97)
    assert ok["all_met"] and ok["failed"] == []
    bad = f1.evaluate_pass_bar({"cagr": 0.09, "sharpe": 0.55, "max_dd": -0.20}, b, 0.97)
    assert bad["failed"] == ["1_cagr_ge_B", "2_sharpe_ge_B_plus_0.10"]
    dd = f1.evaluate_pass_bar({**good, "max_dd": -0.26}, b, 0.97)       # below the -25% floor
    assert dd["failed"] == ["3_max_dd_ge_-25%_and_smaller_than_B"]
    dd2 = f1.evaluate_pass_bar({**good, "max_dd": -0.22}, {**b, "max_dd": -0.21}, 0.97)  # deeper than B
    assert dd2["failed"] == ["3_max_dd_ge_-25%_and_smaller_than_B"]
    ds = f1.evaluate_pass_bar(good, b, 0.95)                             # must be strictly above
    assert ds["failed"] == ["4_deflated_sharpe_gt_0.95"]
    roll = f1.evaluate_pass_bar(good, b, 0.99, rolling_met=False)
    assert len(roll["failed"]) == 1 and roll["failed"][0].startswith("5_")


def test_exploration_defaults_stay_fractional():
    for fn in (fv._sim, fv.run_core, fv.run_xasset, fv.run_hold):
        p = inspect.signature(fn).parameters
        assert p["whole_shares"].default is False and p["grant"].default is None
    assert fv.HELDOUT_WHOLE_SHARES is True
