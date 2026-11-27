# Platform description

This is a pnpm workspace containing a Python/FastAPI trading API, a React/Vite
dashboard, and a separately hosted Python runner. Static code and workflow
configuration establish registration and wiring; they do not by themselves prove
that a runner process is currently deployed or running.

## Current accounts (updated 27 Nov 2026)

Four paper accounts, registered in `kraken-bot/runner.py`. No crypto on any
account or system (owner, 17 Nov 2026; buys refused in code). Start balances and
the run start (9 Nov 2026) are in `trading-platform/core/fleet_capital.py`.

1. **`oracle` (Atlas)** — Alpaca paper. Runner slot
   `asia_trend_strategy.run_asia_cycle`; with the profile flag
   `FLEET_SLEEVE_LIVE` it runs FLEET-V1-F1 (`sleeve_runtime/fleet_live.py`): the
   geared S&P/Nasdaq trend core plus a cross-asset sleeve. The module's own
   header still describes the old Asia ETF strategy; the flag decides.
2. **`jerome_macro` (Atlas V2)** — Alpaca paper.
   `bullion_strategy.run_bullion_cycle` runs FLEET-V1-C1: the same trend core
   without the cross-asset sleeve. At the strategy lock (12-13 Dec 2026) it becomes FLEET-V1-X1, the
   cross-asset trend rule alone (Markus, 22 Nov, roadmap v2 D2 = B). X1 is built
   and switched off until then.
3. **`spy_qqq_trend` (Momentum)** — Alpaca paper.
   `momo_strategy.run_momo_account_cycle` runs MOMO-V2
   (`sleeve_runtime/momo_live.py`): 50 S&P 500 members by 12-1 momentum, with
   brakes on the book.
4. **`forex_ai` (Forex)** — OANDA practice account.
   `forex_ai_strategy.run_forex_cycle`: a three-AI council on seven US-dollar
   pairs (`docs/plans/forex-council-2027-registration.md`).

Around them, with no orders: the pretend-account engine (`trading-platform/twins/`),
the Shadow League of 22 strategies plus 8 yardsticks
(`research_harness/league/`), and the Allocator (`research_harness/league/allocator.py`).
The runner registration is evidence of code wiring, not of live order execution.

# Verified architecture

## Trading API and scheduler

`trading-platform/main.py` starts the FastAPI application, asserts the
authoritative PostgreSQL connection, starts APScheduler, starts the alert
subsystem, and registers additional snapshot, audit, retention, and Fleet
Commander jobs.

`trading-platform/core/scheduler.py` contains the recurring safety, reconciliation,
liveness, postmortem, audit, benchmark, snapshot, and vault jobs (the nightly
walk-forward check was retired on 22 Nov 2026).
The old `intraday_cycle` function remains as compatibility code but is not
registered as an active job and returns before running the retired stock scanner.
`evening_postmortem` is registered on weekdays at 16:10 ET.
Published monitoring registers both the authenticated trading-API probe and the
runner probe from the same explicit liveness enablement. The runner probe accepts
the fixed colocated health URL or an HTTPS `/health` URL whose hostname exactly
matches `RUNNER_HEALTH_ALLOWED_HOST`; arbitrary endpoints are rejected.

## Persistence and learning

PostgreSQL is the authoritative fleet database when the platform starts. A
SQLite journal/local-development fallback remains in compatibility code, but it
is not a second production authority. The platform must not silently merge the
development and production databases.

Learning and postmortem code is present and wired through
`trading-platform/analysis/feedback_injection.py`,
`post_mortem_lessons.py`, `learning_journal.py`, and
`learning_snapshot.py`. Snapshot export is registered from
`trading-platform/main.py`. Actual LLM-backed execution is conditional on its
configured dependencies.

The Oracle profit reserve is current infrastructure: winning Oracle closes
record 15% of raw profit through `oracle_exit_manager.py` and the
`add_oracle_profit_contribution` database function. The former independent
high-water-mark sweep is disabled; this does not establish a separate scheduled
reserve sweep.

## Dashboard, health, and alerts

The current frontend is the React/Vite application in `artifacts/dashboard`.
It routes Home (`/`), League (`/league`), Forex (`/forex`), Research
(`/bench`) and Controls (`/controls`), and uses the API server artifact. The checked-in repository does not establish that
the dashboard workflow is currently running.

`GET /system/health-architecture` is implemented in
`trading-platform/routes/system.py` and consumed by
`SystemHealthModal.tsx` and `StreamingHealthScreen.tsx`. Health uses portfolio
freshness and bot-cycle liveness; stale or unavailable required data must not
appear healthy.

The alert subsystem is implemented in
`trading-platform/notifications/alert_manager.py`, `telegram.py`, and
`discord.py`, with routes in `trading-platform/routes/alerts.py`. Discord is
optional and uses the configured webhook for the daily fleet P&L digest and
critical liveness, kill-switch, exit, and deployment-hash alerts.
Discord delivery lifecycle outcomes are stored in `discord_alert_events` without
webhook URLs or payloads. The protected `GET /trading-api/alerts/audit` endpoint
returns recent attempted, sent, skipped, and failed outcomes.

## Fleet Commander

`trading-platform/analysis/fleet_commander.py` and
`fleet_enforcer.py` are current code. `main.py` dynamically imports the
commander and registers one daily audit at 17:00 ET. The stale module text that
claims six daily runs and six bots is not current architecture. Actual Gemini
execution is conditional on configured credentials and network access.

## Retired or compatibility-only components

The following old descriptions were checked against imports, runner
registration, scheduler registration, and startup code:

- **Poseidon statistical arbitrage:** retired. No live implementation is
  registered; backups, task history, and schema compatibility strings remain.
- **Forex Navigator:** retired and deleted (19 Nov 2026): `forex-engine/`,
  `routes/forex.py` (never registered) and the `_get_forex_*` loaders are gone.
  The old `forex_trades` / `forex_portfolio` tables do not exist in production.
- **Old Oracle stock scanner:** retired/replaced. Legacy pipeline and exit
  infrastructure remains, while the active Oracle runner slot uses the
  consolidated ETF strategy above.
- **Kraken `davy-jones`, `blackbeard`, and `calypso`:** retired as execution
  bots. Legacy logic, state files, aliases, and UI/schema labels remain, but
  they are not in the current runner registration.
- **Apex Predator options engine:** retired. Its options route and active
  options registration are absent; legacy state and historical files remain.
- **`intraday_cycle`:** retired/disabled for the old stock pipeline. It exists
  as a hard-stopped compatibility function, not an active scheduled cycle.

Legacy names in compatibility code, dashboard labels, registry aliases, and
database schema do not prove that the corresponding retired strategy is running.

# Database separation

The current environment exposes three different database references and they
must not be merged, substituted, or used interchangeably:

- `DATABASE_URL` is the live platform's authoritative DSN, currently configured
  for `ep-odd-grass-amdyd29o.c-5.us-east-1.aws.neon.tech`, but its credentials
  currently reject authentication.
- `DEV_DATABASE_URL` is `ep-green-dust-ann2oyjg.c-6.us-east-1.aws.neon.tech`;
  its read-only research-table check reports that `research_ledger` is absent.
- `NEON_DATABASE_URL` is the production database at
  `ep-nameless-hill-am20q7xg.c-5.us-east-1.aws.neon.tech`; its
  `research_ledger` and `bot2_sp500_prices` tables currently contain zero rows.

The historical Helium research connection was recovered from the authorized
workspace environment snapshot at `.cache/replit/env/latest.json`. A
read-only connection using that snapshot reached configured host `helium`,
`current_database()` `heliumdb`, and confirmed 20 `research_ledger` rows plus
10,206,487 `bot2_sp500_prices` rows. The snapshot is recovery evidence, not an
application override: do not copy it into `DATABASE_URL`, `NEON_DATABASE_URL`,
or the live trading configuration. `trading-platform/db/postgres.py` resolves
only `DATABASE_URL`/matching `PG*` variables, and the Strategy Bench currently
uses that shared connection through `get_conn()`.

When reporting connection diagnostics, log the `HOST` only; never log a
connection string, password, token, or other credential.

# Standing working rules

## RAW OUTPUT

Print actual values, rows and code. Never substitute a prose summary for numbers
that were asked for.

## NO FABRICATION

Never invent a number, threshold, duration, timestamp or fact. If something is
not known, say so plainly and say what read would establish it.

## ASSERT, DO NOT NARRATE

Where a task states an expected value, compare and return PASS or FAIL with both
numbers and the difference. A verdict is harder to misread than a printout.

## PRECONDITION CHECK BEFORE EXECUTING

Before starting any task, check the instructions for three faults and report what
you found:

1. A step that depends on state an earlier step destroys.
2. A DONE WHEN that conflicts with a DO NOT.
3. An asserted number or duration with no stated source.

If any is present, say so and ask before proceeding.

## FLOAT COMPARISON

Compare prices and quantities as floats with `1e-8` tolerance. Never compare
them as strings. A trailing zero is not a mismatch.

## ROW-COUNT GUARDS

Every destructive database transaction carries a row-count assertion that rolls
back on any other number.

## NEVER PUBLISH

Only Markus publishes. State clearly when a change requires a publish and which
files.

## FAIL LOUDLY

Never write `x or fallback_value`. Absence of data is a finding, never a healthy
result.

## FINAL REPORT IN ONE COPY BLOCK
Every task ends with a written report, separate from any progress narration. Progress
commentary does not satisfy this. The report answers each numbered step in the task in
order, contains the raw output requested, and ends with the FACTS block.
The entire report goes in ONE fenced code block so it can be copied in a single action.
Never split it across multiple blocks. If the content contains backticks, use a longer
fence delimiter rather than splitting.
If a task is long, the report is still required. Length is not a reason to summarise.

## `kraken-bot/` EDIT BOUNDARY

Do not modify retired Kraken-era modules, legacy control/state files, or bot
profiles by default. The three current runner strategy modules may be edited
only when the current user explicitly requests that specific change and the task
scope names the affected module. Before editing any `kraken-bot/` strategy,
verify its runner registration, profile, pause state, and broker/database
boundaries. Never infer permission to change live strategy code from a task
about another component, and never change trading behavior, orders, positions,
stops, or bot activation unless explicitly requested.

## FACTS BLOCK

End every task report with:

FACTS
files_changed: <count and list>
rows_changed: <count and which tables, or NONE>
tests_run: <suite name and pass count, or NONE>
publish_required: <yes/no and which files>
git_head: <commit hash>
working_tree: <clean/dirty>
broker_mutations: <NONE, or every order placed, cancelled or modified>

Every field appears even when the answer is NONE.

# Evidence boundary

This file describes code and checked-in configuration verified during the audit.
It does not claim that a process is running merely because a module, workflow
entry, database row, legacy alias, or dashboard label exists. Re-check current
runtime state before reporting execution, liveness, broker state, or database
contents.

## Agent reporting
- Do not post progress updates while working. Reply once, at the end.
- Put the entire reply in one fenced code block, ending with a FACTS
  block.