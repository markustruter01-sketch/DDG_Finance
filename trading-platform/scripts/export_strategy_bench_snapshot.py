#!/usr/bin/env python3
"""Export a compact, read-only Strategy Bench snapshot from Helium research."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.research_postgres import get_research_conn
from research.strategy_bench_catalog import fetch_live_catalog


DEFAULT_OUTPUT = ROOT / "data" / "strategy_bench_snapshot.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="snapshot destination (defaults to trading-platform/data)",
    )
    args = parser.parse_args()

    snapshot = fetch_live_catalog(get_research_conn)
    snapshot["source"] = "helium_research_database_snapshot"
    snapshot["source_label"] = "Helium research database · read-only export"
    snapshot["snapshot_as_of"] = snapshot["generated_at"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"Exported {snapshot['row_counts']['experiments']} experiments and "
        f"{snapshot['row_counts']['exploration_runs']} exploration runs "
        f"({args.output.stat().st_size} bytes)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())