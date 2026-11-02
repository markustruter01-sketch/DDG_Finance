# FLEET-V1-F1 live build — specification (Fable 5.1, 2 Nov 2026)

Owner's decision (Markus, 2 Nov 2026 16:45 Brisbane): run the F1 fleet as the
platform's strategy. Goal restated: roughly half the index's drawdowns, ~10%
a year, after costs. F1's record: held-out 2011-2020 8.6%/yr, worst fall -16%
(index 13.7%, -34%); spent 2021-2026 12.2%/yr, -16% (index 14.6%, -24%).
It FAILED its registered "beat the index" bar; it is run for what it did
pass. Ledger: research_harness/ledger.jsonl, FLEET-V1-F1.

Rules are the registered candidate, unchanged: research_harness/sleeves/core_v1.py
(cid C1), research_harness/sleeves/xasset_v1.py, 65/35. Nothing here may
change a rule. Where live execution must differ from the backtest, the
difference is listed in "Live differences" and measured by the shadow.

## 1. Accounts (Alpaca PAPER until section 6 is met)
| account | today | becomes |
|---|---|---|
| Atlas / `oracle` | GEAR-V1-G4 live | **FLEET-V1-F1** (this spec) |
| Momentum / `spy_qqq_trend` | G4 + DBMF forward test | **C1 alone** (F1's core without sleeve 2): the standing control that shows, forward, what sleeve 2 costs or saves. Information only. |
| `jerome_macro` | hard assets, unpaused in code | **paused** pending an owner decision (audit open item). Not deleted. |
Forex council, Bot 2 momentum, the retired LLM pipeline and `POST /run`: deleted (section 5).

## 2. Signal (once per session, from COMPLETED daily bars)
- Bars: Alpaca daily bars with `adjustment="all"` (dividend- and split-adjusted), because the backtest's votes, vol and TSMOM were on adjusted series. Unadjusted bars would change votes around ex-dividend days. Reject a bar set whose last day is not the previous NY session (`MAX_BAR_AGE_DAYS`, existing guard).
- Core (on SPY): `core_v1.votes` (253 closes), `core_v1.vol20`, `core_v1.target_exposure`, `core_v1.weights_for(E, MIXES["C1"])`. Rebalance when votes change or on the first session of a month — `trend_executor.signal_day_if_due` + a stored last-votes value, exactly as `gear_live` stores the last gear.
- Cross-asset (IEF, GLD, DBC, UUP): `xasset_v1.target_weights` on the first session of each month only. A line with fewer than 253 completed closes is off.
- Fleet targets for the one account: `w[sym] = 0.65 * core[sym] + 0.35 * xasset[sym]`; everything else SGOV. Whenever EITHER sleeve is due, recompute the whole vector from current account equity (so the 65/35 split is reset at every core event, not daily as in the backtest — see Live differences).

## 3. Execution
- `trend_executor.execute_rebalance` with the fleet targets; whole shares; the executor's 1% buffer. Orders on the first hourly cycle after the signal day's close while the market is open (existing behaviour).
- Stops: 20% protective stop on SPY/SSO/QQQ/QLD, re-set at each rebalance (as G4). **No stops on IEF/GLD/DBC/UUP** — the executor must accept `stop=None` for those symbols; if it cannot today, add it with a test. A stopped core holding stays flat until the next core event.
- Idle cash parked in SGOV (`sgov_parking.py`), as now.
- Never borrow; gross ≤ 1. Assert it in the plan builder (raise, don't clamp).

## 4. Risk governor (plan: "Before any live use")
- `trading-platform/core/risk_limits.py`: `ENFORCE_DRAWDOWN_LIMITS = True`, soft 15% (halve all targets until equity recovers to the high-water mark × 0.95), hard 22% (flat to SGOV, trading halted until an owner clears it). Drawdown is measured from the account's high-water mark since the F1 cutover, on closing equity.
- Kill switch armed by default; one owner action disarms. Both states shown on the dashboard and written to the ledger on change.

## 5. Deletions (audit, 2 Nov; keep tests green after each)
`kraken-bot/forex_*.py` and their tests; `bot2_momentum_strategy.py`, `bot2_spy_qqq.py`; the `POST /run` route and the retired LLM decision pipeline it reaches; `artifacts/mockup-sandbox`; dead compatibility code the deletions orphan. `research_harness/` is never touched by this work. List what will be removed in the PR description before removing it.

## 6. Before any REAL money (owner gate; none of it is this build)
90 days of paper fills logged against the backtest's assumed prices (`costs_paid` vs assumed 5/10 bp); the measured cost replaces the assumption in a new registration; public paper record from 2027-01-01 with the pass bar beside it. Live use is an owner decision recorded in the ledger.

## 7. Dashboard (`artifacts/dashboard`)
Replace every G4/forex/LLM element. Three pages:
- **Home**: equity vs SPY since cutover (paper); current votes, vol20, E; each cross-asset line on/off with its weight; held vs target per symbol; drawdown vs the 15%/22% lines; kill-switch state.
- **Bench**: the FLEET-V1 record as logged — exploration table (B, C1, C2, F1, F2, A0, N1, N2), the held-out result with its FAIL verdict and the figures, the spent window; the C1 control account beside F1 forward.
- **Controls**: pause/resume, disarm/arm kill switch, clear a hard halt, cutover log. Nothing that edits a rule.
The API serves these from the ledger, the exploration log and the runtime state; no number on the dashboard is computed in the browser.

## Live differences from the backtest (to be measured by `gear_shadow`-style shadow from day 1)
1. Fleet weights reset at core events and month starts, not daily.
2. Fills on the first hourly cycle, not the open.
3. 1% buffer always (backtest: only when E > 1).
4. Alpaca adjusted bars, not Yahoo's; small differences in adjustment history are possible.
5. SGOV yield instead of DTB3 − 0.50%.

## Tests Opus must add (synthetic data)
- Fleet target vector = 0.65·core + 0.35·xasset for a hand-made state; gross ≤ 1; SGOV takes the remainder.
- Core due only on vote change or month start; xasset due only on month start; a day with neither produces no orders.
- Stops present on core symbols only.
- Soft and hard drawdown actions fire at 15%/22% and not before; hard halt needs an owner clear.
- Kill switch armed by default.
- Parity: given a window of bars, the live target vector equals what `research_harness` would hold the next session (allowing for the buffer), on a synthetic 300-day series.

## Review before merge to the live account (Fable)
Order path end to end, the parity test, and the risk governor. Opus requests this review in the PR; it does not merge to the account without it.
