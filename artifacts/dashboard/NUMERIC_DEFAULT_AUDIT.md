# Dashboard numeric-default audit

The dashboard now distinguishes a real API value of `0` from a missing value. Nullable API values render as `—`, `unavailable`, or `UNKNOWN`; arithmetic is only performed after the required inputs are present.

## Determinate fixes

| Area | Source | Fields audited | Zero meaning |
| --- | --- | --- | --- |
| Portfolio summary | `/fleet/equity`, `/portfolio`, `/positions/live`, `/vault` | equity, P&L, cash, buying power, vault value/P&L | Zero is legitimate when returned; missing stays unavailable |
| Fleet performance and weekly review | `/fleet/equity`, `/journal`, `/performance` | equity, daily P&L, trade counts, best/worst values, sparklines | Zero is legitimate; absent journal/equity data is not a zero |
| Home fleet and export | `/fleet/equity`, `/positions/live` | ship-card values, fleet totals, copied status | Zero is legitimate; missing is `—` |
| Live position cards | `/positions/live`, after-hours position data | quantities, market values, unrealized P&L and percentages | Zero is legitimate; missing position metrics stay unavailable |
| Streaming feed/cards | `/journal`, `/fleet/equity`, `/positions/live` | trade P&L, bot P&L, counts, open-position totals | Zero is legitimate; missing feed values stay unavailable |
| Math audit summary | `/admin/math-audit/summary` | pass/warn/fail totals, checks run, active paths | Zero is legitimate; incomplete summaries do not produce totals |
| Correlation matrix | `/correlation` | matrix cells | A returned zero is legitimate; a missing cell renders `—` |
| Shared kill-board helpers | journal/kill-board payloads | streak and P&L values | Missing P&L does not become a winning/losing zero |
| Celebration feed | `/journal`, `/positions/live`, `/fleet/equity` | source trade P&L and fleet stats | Missing source rows are skipped; placeholder trades were removed |

## Intentionally unchanged / cannot determine

- `ui/progress.tsx` and the sentiment gauge use zero only for SVG/CSS geometry; the displayed sentiment already remains `—` when unavailable.
- `StreamingPerformanceScreen` uses zero only for a bar width when no data point exists; the metric label remains unavailable.
- Alert form state uses zero as the user-editable default for a minimum P&L threshold; queue/config semantics need an API contract before changing.
- Degradation severity maps use zero for absent severity buckets; an absent bucket conventionally means no events, but this is not guaranteed by the current response type.
- System-health scenario overrides use explicit zero latency in simulated HTTP-error fixtures, not live API data.
- Known-empty weekly arrays use zero counts only when the endpoint returned the array; an unavailable endpoint remains unavailable.

No reconciliation, broker, runner, database-write, or publishing path was changed.