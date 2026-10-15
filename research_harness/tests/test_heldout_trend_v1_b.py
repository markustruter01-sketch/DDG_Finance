"""The TREND-V1-B held-out runner: pinned data, run once, recorded."""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta

import pytest

from research_harness.explore.trend_v1 import UNIVERSE
from research_harness.harness import registry
from research_harness.harness.store import BarStore
from research_harness.heldout import trend_v1_b


def _series(n, seed, start=date(2018, 1, 1)):
    rng, px, out, d = random.Random(seed), 100.0, [], start
    while len(out) < n:
        if d.weekday() < 5:
            o = px
            px *= math.exp(0.0003 + rng.gauss(0, 0.01))
            out.append({"day": d, "open": o, "high": max(o, px) * 1.001, "low": min(o, px) * 0.999, "close": px})
        d += timedelta(days=1)
    return out


def _setup(tmp_path):
    store = BarStore(tmp_path / "data")
    reg = json.loads((registry.REGISTRATIONS_DIR / "TREND-V1-B.json").read_text())
    (etf_ds, _), (rates_ds, _) = sorted(reg["data"].items(), key=lambda kv: not kv[0].startswith("etf"))
    store.write_dataset(etf_ds, source="synthetic",
                        bars_by_symbol={s: _series(2300, i) for i, s in enumerate(UNIVERSE)})
    store.write_dataset(rates_ds, source="synthetic", fields=("day", "rate"), positive_fields=(),
                        bars_by_symbol={"DTB3": [{"day": date(2017, 12, 29), "rate": 0.02}]})
    return store, reg, etf_ds, rates_ds


def test_refuses_data_that_differs_from_the_pinned_hashes(tmp_path):
    store, *_ = _setup(tmp_path)
    with pytest.raises(RuntimeError, match="pinned manifest"):
        trend_v1_b.run(store, ledger=tmp_path / "ledger.jsonl", record=False)


def test_runs_once_records_and_refuses_a_second_test(tmp_path):
    store, reg, etf_ds, rates_ds = _setup(tmp_path)
    reg["data"] = {etf_ds: store.manifest_hash(etf_ds), rates_ds: store.manifest_hash(rates_ds)}
    regdir = tmp_path / "regs"
    regdir.mkdir()
    (regdir / "TREND-V1-B.json").write_text(json.dumps(reg))
    ledger = tmp_path / "ledger.jsonl"
    out = trend_v1_b.run(store, directory=regdir, ledger=ledger)
    assert out["window"][0] == "2021-01-01"
    assert out["pass_bar"]["2_fleet_correlation_and_sharpe"] == "NOT YET TESTABLE"
    assert out["verdict"].startswith(("BAR 1 PASSED", "FAIL"))
    entry = json.loads(ledger.read_text().splitlines()[0])
    assert entry["kind"] == "holdout_test" and entry["registration_id"] == "TREND-V1-B"
    with pytest.raises(registry.RegistrationError, match="already had"):
        trend_v1_b.run(store, directory=regdir, ledger=ledger)


def test_real_registration_is_well_formed():
    reg = registry.load_registration("TREND-V1-B")
    assert reg["universe"] == UNIVERSE and len(reg["data"]) == 2
    assert all(len(h) == 64 for h in reg["data"].values())
