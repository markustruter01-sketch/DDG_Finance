# Platform description

This is a pnpm workspace containing a Python/FastAPI trading API, a React/Vite
dashboard, and a separately hosted Python runner. Static code and workflow
configuration establish registration and wiring; they do not by themselves prove
that a runner process is currently deployed or running.

## Current Alpaca paper bots

The executable fleet is the three-tuple registration in
`kraken-bot/runner.py`, not the historical names still present in compatibility
code:

1. **`oracle`** — Global ETF Trend. It is wired to
   `kraken-bot/asia_trend_strategy.py:run_asia_cycle`. The current profile calls
   this `etf_trend_global` and covers SPY/QQQ plus Asia-Pacific and emerging-market
   ETFs. The module uses the shared EMA50/200 trend engine, scale-outs, trailing
   stops, and exit management. Its configured runner interval is one hour.
2. **`spy_qqq_trend`** — the canonical ID whose legacy profile key is
   `bot2_spy_qqq`. It is wired to
   `kraken-bot/bot2_momentum_strategy.py:run_bot2_cycle`. The current module is a
   single-stock 12-1 momentum strategy using a 252-session lookback, a
   liquidity-screened universe, top-20 equal weighting, and monthly rebalancing.
   It is paused in both the profile and the strategy module.
3. **`jerome_macro`** — Jerome hard-assets sleeve. It is wired to
   `kraken-bot/bot3_hard_assets_strategy.py:run_bot3_cycle` and covers BTC/USD,
   ETH/USD, GLD, and SLV, with vault symbols BIL and VOO. The profile and module
   currently set this bot as unpaused, but its actual execution still depends on
   runner mode, database pause alignment, and lock checks.

All three profiles use Alpaca's paper endpoint. The runner defaults to
read-only mode unless explicitly configured otherwise. The runner's current
checked-in registration is evidence of code wiring, not evidence of live order
execution.

# Verified architecture

## Trading API and scheduler

`trading-platform/main.py` starts the FastAPI application, asserts the
authoritative PostgreSQL connection, starts APScheduler, starts the alert
subsystem, and registers additional snapshot, audit, retention, and Fleet
Commander jobs.

`trading-platform/core/scheduler.py` contains the recurring safety, reconciliation,
liveness, postmortem, audit, benchmark, walk-forward, snapshot, and vault jobs.
The old `intraday_cycle` function remains as compatibility code but is not
registered as an active job and returns before running the retired stock scanner.
`evening_postmortem` is registered on weekdays at 16:10 ET.

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
It routes the home, streaming, research-bench, and system-health surfaces and
uses the API server artifact. The checked-in repository does not establish that
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
- **Forex Navigator:** retired. `forex-engine/` and API compatibility routes
  remain on disk, but startup explicitly prevents its resurrection and no
  scheduler job invokes it.
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

The current read-only connection metadata establishes two separate database
contexts:

- Development shell database host: `helium`
- Production database host: `ep-nameless-hill-am20q7xg.c-5.us-east-1.aws.neon.tech`

These databases must not be merged, substituted, or used interchangeably.
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