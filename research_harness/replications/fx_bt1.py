"""Replicate FX-BT1 through the harness: shared data store, shared metrics.

Proves the harness reproduces a registered result before any new strategy is
trusted to it. Recorded in the ledger as a replication, never a new test.
The original figures stay as registered; nothing is overwritten.

    python -m research_harness.replications.fx_bt1 --dataset oanda_fx_ba_to_2026-10-10
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "trading-platform", ROOT / "kraken-bot"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

from research_harness.harness import metrics, registry  # noqa: E402
from research_harness.harness.store import BarStore  # noqa: E402

REG_ID = "FX-BT1"
DATA_START = date(2000, 1, 1)


def compare(original: dict[str, Any], got: dict[str, Any]) -> dict[str, Any]:
    """Match at the precision the original was reported at."""
    out = {}
    for key, want in original.items():
        if key == "read_from":
            continue
        have = got.get(key)
        if have is None:
            out[key] = {"want": want, "got": None, "match": False}
            continue
        decimals = len(str(want).split(".")[1]) if "." in str(want) else 0
        out[key] = {"want": want, "got": have, "match": round(have, decimals) == want}
    return out


def run(dataset: str, store: BarStore | None = None, *, record: bool = True) -> dict[str, Any]:
    import forex_baseline_backtest as fx

    store = store or BarStore()
    reg = registry.begin_run(REG_ID, "replication")
    data = {
        pair: store.load(dataset, pair, start=DATA_START, end=fx.LAST_DAY, registration_id=REG_ID)
        for pair in reg["universe"]
    }
    data = {p: b for p, b in data.items() if b}
    result = fx.run_backtest(data)
    summary = metrics.summarize(result["curve"], result["trades"],
                                cost_label="OPTIMISTIC: omits financing")
    original_stats = fx.stats(result["curve"], result["trades"])
    same_formula = all(summary[k] == v for k, v in original_stats.items())
    checks = compare(reg["original_result"], summary)
    reproduced = same_formula and all(c["match"] for c in checks.values())
    out = {
        "dataset": dataset,
        "data": {p: f"{len(b)} bars {b[0]['day']}..{b[-1]['day']}" for p, b in data.items()},
        "summary": summary,
        "harness_metrics_match_original_formula": same_formula,
        "vs_registered": checks,
        "reproduced": reproduced,
    }
    if record:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                    text=True, cwd=ROOT).stdout.strip() or None
        except OSError:
            commit = None
        registry.record_run(reg, "replication", out,
                            data_manifest_hashes={dataset: store.manifest_hash(dataset)},
                            code_commit=commit)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    a = ap.parse_args(argv)
    out = run(a.dataset)
    text = json.dumps(out, indent=2, default=str)
    print(text)
    report = ROOT / ".local" / "claude_reports" / "FX-BT1-REPLICATION.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n")
    return 0 if out["reproduced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
