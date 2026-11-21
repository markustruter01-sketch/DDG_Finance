"""Read-only check of the macro label and flags on past sessions (roadmap v2, V2-06 and V2-19).

    python -m twins.macro_check 2025-04-01 2025-04-30

Fetches Alpaca daily bars (GET only) for the macro symbols and prints, for each
US session in the range, the confirmed label, that session's own label, the six
votes and the four flags. Writes nothing and places nothing. Used to check the
rules by hand on recorded dates before they are registered.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

from research_harness.harness.portfolio import HistoryView
from research_harness.league import macro_state as ms

HISTORY_DAYS = 800          # calendar days before the first session: 200-session averages + the 252-session walk


def rows(first: date, last: date, fetch=None, now: datetime | None = None) -> list[dict]:
    from twins import prices
    from twins.engine import NEW_YORK

    now = now or datetime.now(NEW_YORK)
    bars = prices.alpaca_daily(list(ms.SYMBOLS), first - timedelta(days=HISTORY_DAYS), now, fetch=fetch)
    calendar = tuple(b["day"] for b in bars.get("SPY", []))
    view = HistoryView(bars)
    return [{"day": d, **ms.state(view, calendar, d)} for d in calendar if first <= d <= last]


def main(argv: list[str]) -> int:
    first, last = date.fromisoformat(argv[1]), date.fromisoformat(argv[2])
    for r in rows(first, last):
        on = [f for f in ms.FLAGS if r["flags"].get(f)]
        v = r["votes"] or {}
        print(f"{r['day']}  label={r['label']}  raw={r['raw_label']}  "
              f"votes={''.join('1' if v.get(k) else '0' for k in ('spy', 'iwm', 'hyg_ief', 'dbc', 'uso', 'tip_ief'))}  "
              f"flags={','.join(on) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
