"""One-off Forex council dry run: live OANDA sheet -> council -> printed summary.

Nothing is written to the database and no orders exist. Prints no keys, no
prompts and no raw replies: only per-call status, token use and parsed calls.
Run from the repo root:  python kraken-bot/forex_council_dryrun.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trading-platform"))

from core.oanda_client import OandaClient  # noqa: E402
from forex_council import run_council  # noqa: E402
from forex_quant_desk import build_signal_sheet  # noqa: E402


def main() -> int:
    with OandaClient() as client:
        sheet = build_signal_sheet(client)
    usable = [r for r in sheet["rows"] if "error" not in r]
    print(f"sheet: {len(usable)}/{len(sheet['rows'])} pairs usable; errors={sheet['errors']}")
    record = run_council(sheet["rows"])
    for call in record["calls"]:
        print(f"call ok: {call['role']} {call['provider']} {call['model']} usage={call['usage']}")
    for error in record["errors"]:
        print(f"error: {error}")
    print(f"status: {record['status']} low_confidence={record.get('low_confidence')}")
    for d in record["decisions"]:
        print(
            f"decision: {d['pair']} {d['direction']} conv={d['conviction']} "
            f"stop={d['stop_atr_multiple']}xATR sided={d['sided_with']} baseline={d['baseline']}"
        )
    return 0 if record["status"] == "shadow" else 1


if __name__ == "__main__":
    raise SystemExit(main())
