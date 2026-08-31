"""Print the read-only durable per-bot return-series report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.research_ledger import read_only_daily_returns_report


if __name__ == "__main__":
    print(json.dumps(read_only_daily_returns_report(), indent=2, default=str))