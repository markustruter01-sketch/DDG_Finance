# DDG Finance — status log

The target is `fund-roadmap-2026-11-17.md` (agreed by Markus 17 Nov 2026). How to build it: `fund-roadmap-build-guide-for-opus.md`.
This file is the running history only: add a dated Status entry after every work session (newest at the bottom).
The original 10 Nov plan, its checklist and Steps 3–4 are archived unchanged in `archive/finance-2027-plan-original-to-17-nov.md` (superseded). Code comments that cite "finance-2027-plan.md Step N item N" point to that archived file.
MASTER COPY: this file in GitHub. The claude.ai Project doc `claude/finance-2027-plan.md` mirrors it; whoever edits one updates the other in the same session.

## Status entries

### Status 12–13 Nov (Opus 5.5)
- Markus decided (12 Nov): drawdown limits stay record-only (paper); the PUBLIC record starts 1 Jan 2027 (ddg.limited/finance counts from the first push on or after 1 Jan Brisbane, S&P 500 from the 31 Dec close). The internal run start still restarts once at the lock.
- PR #98 (engine table set-up once; current_qty repair only on own rows) merged and published 11 Nov. PR #100 (fleet push: holdings by group + S&P 500 benchmark) merged, published 12 Nov 23:35 UTC (US closed). Post-check 23:59 UTC: 4 bots cycling, 0 open alarms, stops match (oracle QQQ/SPY; jerome_macro SPY/QQQ/ETH/BTC; spy_qqq_trend none); 6 ERROR lines 23:36–23:38 were the new runner waiting for the old one's oracle lease (5 read; same pattern). First push with holdings landed 23:41 UTC; live at ddg.limited/finance.
- ddg.limited/finance live (DDG-Control #79). Holdings note explains Vault (BIL) and forex gross exposure >100% (in DDG-Control #80).
- K1 (secret in the dashboard bundle): checked 13 Nov from outside, anonymous: /, /trading-api/health and /trading-api/bots all 307 to Replit's ReplShield. The bundle is not public. DECISION (Opus, for Markus): accepted risk while private; must be fixed (operator login) before the dashboard is ever made public or anyone else gets Replit access.
- Outside heartbeat (PR #97): built but OFF: HEARTBEAT_URL_RUNNER / HEARTBEAT_URL_API not set in production (checked 13 Nov, names only). DDG Control's Connections panel shows Finance "stale" after 3 h without a push, but only shows it (Control is autoscale: no timer to send a message). Markus to create two healthchecks.io checks if he wants a message when Finance goes silent.
- Fix list: (a) + (b) built, PR #101 (UNKNOWN needs two runs in a row; only failing lines warn). (c) not doing: each bot has its own Alpaca account; changing id prefixes risks own-order matching. (d) left: 0 alarm rows for the dead bots_state ids since 10 Nov.
- Alarms since 10 Nov 00:00 UTC (read 13 Nov 00:12 UTC): 4 invariant rows total, all resolved (2 were the 21:04 UTC blip #101 fixes). Nothing else.
- STILL NEEDS FABLE before Sat 21 Nov: item 7 (order-path audit, "must never happen" list) and item 17 (registrations, pass bars, Bot 3 exact rules incl. a sector cap on the momentum list). Rehearsal (#94) still needs Markus's go (🔴 real 1-share paper orders, Momentum paused, market open).

### Status 13–14 Nov (Opus 5.5)
- PR #101 (one UNKNOWN blip no longer alarms) merged, published 13 Nov 01:15 UTC; post-check clean.
- 🔴 INCIDENT 13 Nov 03:00 UTC: OANDA practice API answered 401/504 on and off (workspace token works; /v3/accounts flipped 504/200/401 within seconds = OANDA flaky, not our token). The armed kill switch tripped (fleet_equity_unknown, then missing_account every ~5 min) and paused ALL four bots for the whole Fri 13 Nov US session. Holdings stayed protected (Atlas QQQ/SPY stops; DBC/UUP stop-exempt by design; Atlas V2 SPY/QQQ/BTC/ETH stops; Momentum cash; Forex 4 trades with stop-losses). No orders placed by anyone.
- DECISION (Markus 14 Nov 05:20 Brisbane: "the kill switch is causing 99% more harm than good, FIX IT"): kill switch ALERT ONLY. PR #102: KILL_SWITCH_ARMED = "false" in .replit [userenv.shared] (the designed owner switch; no code path change). It still checks every 5 min and records would-trip warnings; never pauses bots. Every automatic trip so far (7 Nov Forex records, 9 Nov stop re-arm, 13 Nov OANDA) froze the fleet for a data problem. Before real money: re-design (one broker's read failure affects only that bot, after several failed checks in a row).
- Plan for the publish (after 21:00 UTC 13 Nov): publish #102 → confirm no new trip → reset latch (restore_latch + reset with KILL_SWITCH_RESET_CONFIRMATION) → resume all four bots → republish so the API starts with the latch clear → post-check.
- 5-clean-day gate: the Fri 13 Nov session was an incident (fleet frozen). FABLE to decide whether the gate restarts and whether the 21–22 Nov lock moves.
- Rehearsal (Markus said go, 14 Nov 05:09): blocked on 13 Nov by the tripped latch. Scheduled check-in trig_01GJhJyKGnPicAraZogHFr8a fires 16 Nov 15:05 UTC (Mon session) to run it.
- DDG Stripe (Markus 14 Nov): STRIPE_DDG_SECRET_KEY set in Hypest, Control and Finance; all DDG money goes to the Digital Dynamics Stripe account. Cattle Dog Coffee keeps its own Stripe account (run with a partner; only tax/admin under DDG).

### Status 15 Nov (Opus 5.5): AI twins Phase A built, PR #103 (open)
- Spec: Project doc `claude/finance-ai-twins-build-spec.md` (decisions: `claude/finance-ai-shadow-decisions-2026-11-15.md`). Code `trading-platform/twins/`; registration `research_harness/registrations/TWINS-V1.json`. No orders, ever.
- 11 twins: mirror + baseline_full + baseline_spy for oracle, jerome_macro, spy_qqq_trend; mirror (OANDA hourly bars) + baseline_spy for forex_ai. All of a bot's twins start with that account's real balance (without owner-kept BTC/ETH) on the first nightly run after the publish.
- Jobs: twins_hourly (:55 New York: change log of pauses/resumes/builds; Forex mirror read) and twins_nightly (17:15 New York weekdays: account reads at the close, replay, mirror check, hash check). Both keep running when a bot is paused.
- Mirror check: alarm above a provisional 1.0 point gap. FABLE sets the real tolerance after one week of mirror data.
- Recorded-day test (real accounts after the 13 Nov close): engine valuation = Alpaca equity to the cent on all three accounts; mirror gap under 0.003 points.
- Found: `bot_daily_returns.equity_close` is snapshotted 19:15–20:15 UTC, before the 21:00 UTC close since US clocks changed (13 Nov Atlas: 87,079.77 recorded vs 87,124.70 at the close). The twins value at the close. FABLE: decide whether the snapshot moves after the close before the record restarts at the lock.
- Read from code: council models Groq `openai/gpt-oss-120b`, OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, Google `gemini-3-flash-preview`, temperature 0.2. None is a dated id (spec rule 5 wants dated ids and lowest randomness). The council logs token counts per call, not dollars.
- Next: FABLE reviews #103 → Markus merges → OPUS publishes with the US market closed, read-only pre/post checks → FABLE writes the Forex rule and the pass marks → OPUS builds Phase B.

### Status 15 Nov evening (Opus 5.5)
- AI twins Phase A LIVE: PR #103 + #104 (Fable's review fixes) merged, published 15 Nov 07:16 UTC (US closed). Pre-check clean; post-check: 4 bots unpaused, holdings unchanged, 6 twin tables + append-only/no-truncate guards created, first change_log row 07:55 UTC. Twins are created by the first nightly run (Mon 17:15 New York = Tue 08:15 Brisbane). Fable's review: Project doc `claude/finance-ai-twins-phase-a-review-2026-11-15.md`.
- TWINS-V2 REGISTERED (PR #105, merged 15 Nov): Forex rule = FX-BT1 baseline; pass marks; luck check (t >= 2.0 for "clear"); both sides through the same engine; AI cost charged to the AI side; month-end freeze + GitHub copy. `docs/plans/ai-twins-2027-registration.md`.
- 🔴 ETH (owner-kept, Atlas V2) SOLD BY ITS STOP: Alpaca stop-limit order 4e844e8b filled Sat 14 Nov 14:24:36 UTC, 2.222351339 ETH at avg 1852.12 (two fills). Entry was 2471.48: about −$1,376 on the line. Markus 15 Nov 18:16 Brisbane: no rebuy. Ledger row bot3_positions id 2 closed by hand (owner-approved production write; before/after recorded), change_log row 2. Cause of the hourly critical alarms since 14 Nov 16:39 UTC: nothing closed the row, because the old Bot 3 code that handled crypto stop fills no longer runs on this account. Same will happen if the BTC stop fills: TO FIX (Opus) before then.
- Weekend alarm fixes (PR, this session): reconciliation records one alarm per open mismatch (was one critical row per hourly run); OANDA reads retry once on a 401 and each retry is logged, with a 24 h count in the daily health message (orders are never retried); twins mirror treats an owner-kept sale as money arriving, not engine error; ETH removed from OWNER_KEPT (BTC stays).
- OANDA 401s continued all weekend (4 Forex execution attempts failed while the market was closed; reconciliation and the kill-switch report saw the same). The retry count will show how often it happens on trading days.
- Next: FABLE: Bot 1-4 registrations, order-path audit (item 7), the daily-returns snapshot timing (before the close since 1 Nov). OPUS: crypto stop-fill ledger close for BTC; Phase B.

### Status 16 Nov (Opus 5.5)
- GATE RESTARTED (Markus 16 Nov 05:20 Brisbane, "yes"): the 5 clean sessions are now Mon 16 – Fri 20 Nov. The 21–22 Nov lock holds if all five are clean. Tonight's rehearsal (real 1-share paper orders) counts as clean if it ends reconciled.
- ITEM 7 DONE (audit): `docs/plans/order-path-audit-2026-11-16.md` (Project copy `claude/finance-order-path-audit-2026-11-16.md`). 🔴 F1: a timed-out Alpaca order can be sent twice (our duplicate-id retry). F2: Forex records an unclear order answer as "not filled". F3: unprotected windows up to ~1 h (alarm within 15 min). F4: vault ignores pause and the kill latch. F5: no timeout on Alpaca calls.
- Next: OPUS builds F1 + F2 + F4 with tests (one PR); FABLE reviews; publish at the lock weekend with the cutover (engine change, not during the gate).

### Status 17 Nov (Fable 5.2)
- 🔴 GATE STOPPED (Markus 17 Nov 08:39 Brisbane: "I am making the call now... let's stop this 5-day testing window"). Reason: the gate was proving the old order engine; PR #108 (audit F1/F2/F4, an engine change) was due to publish at the lock weekend, after the gate. The Mon 16 – Fri 20 Nov window no longer counts.
- NEW ORDER (Markus agreed): 1) fix window: everything that changes running code goes in now; 2) ONE new 5-session gate on that final system, nothing merged during it; 3) lock and start the weekend after. The 21–22 Nov lock moves (about 5–6 Dec if the fix window takes a week). The public record start (1 Jan 2027) is unchanged.
- Fix window list (code-changing; each a small PR, tests green, published with the US market closed): publish #108; time limits on broker calls (audit F5); BTC stop-fill ledger close; daily snapshot after the US close; kill switch per bot (one broker's failed reads pause only that bot, after several in a row); delete dead code (short selling, old Navigator forex routes, the 17 Aug one-time job, dead bots_state rows); display-name table (keys `oracle`, `jerome_macro`, `spy_qqq_trend`, `forex_ai` never change); outside heartbeat on (needs Markus: two monitor URLs).
- Not in the fix window: folder renames (e.g. kraken-bot) and wider tidy-up: risk without a reliability gain, and they cannot happen after the lock.
- This PR: automatic tests on GitHub (`.github/workflows/tests.yml`), so every later fix is checked before merge. No running code changed.
- NOT known when written: whether #108 is published; the result of the Mon 16 Nov session and rehearsal. Read from outside only (ddg.limited push 16 Nov 22:27 UTC: 4 bots unpaused, fleet equity 365,797.04).

- ROADMAP AGREED (Markus 17 Nov 09:17 Brisbane): `fund-roadmap-2026-11-17.md` is the target from here; where it differs from the line-up above, the roadmap wins. Defensive stocks replaces Atlas V2's strategy at the lock; lock moves to about 12–13 Dec; no new trading accounts or paid services. Opus 5.5 builds it alone per `fund-roadmap-build-guide-for-opus.md`.

### Status 17 Nov evening (Opus 5.5)
- 🔴 NO CRYPTO, FULL STOP (Markus 17 Nov): "none of the accounts at all trade any crypto... on any of the platforms, on any of the systems". Reason: Bitcoin security breaches.
- PR #117: every order that would buy crypto (coin pairs, crypto funds such as IBIT/GBTC/ETHA) is refused before it is sent and logged critical, on every Alpaca client (shared session from #116) and on OANDA. Sells still work.
- Fix window item "BTC stop-fill ledger close" becomes "crypto exit closes its ledger row" (BTC sold by stop or by Markus).
- PR #116 (time limits on broker calls, F5) merged; not yet published.
- PUBLISHED 17 Nov ~07:16 UTC (US closed): #116 (broker time limits) and #117 (no-crypto guard). Tests in the workspace before publish: 293 + 1,097 passed. Outside check after: ddg.limited push 07:16 UTC, 4 bots unpaused. Alarms and broker-vs-ledger: NOT checked from inside (UNKNOWN).
- 🔴 BTC SOLD (Markus 17 Nov 17:38 Brisbane: "Yes, sell the Bitcoin"). Stop a21f0320 cancelled; one market sell 0.097758577 BTC/USD filled 07:41:36 UTC at avg 64,519.74 (order 25ae6d82). Entry 78,973.10: about −$1,413 on the line (arithmetic). bot3_positions id 1 closed, bot_portfolio BTC item removed, change_log row 16 (owner-approved production write; before/after in `.local/claude_reports/btc-sale.txt`). No crypto left on any account. OWNER_KEPT emptied in code (PR "BTC sold").
- (superseded) WAITING ON MARKUS: whether to sell the remaining owner-kept BTC now (an order: needs his yes); publish approval for #116/#117 (US market closed); the live website still says the Finance bots read/hold crypto.

### Status 18 Nov morning (Opus 5.5)
- PUBLISHED 17 Nov ~10:07 UTC (US closed): #119 (BTC sold, OWNER_KEPT empty) and #120 (daily closing snapshot at 17:25 New York time, all year). First run at the new time: 17 Nov 22:25 UTC.
- READ-ONLY HEALTH CHECK, production, 17 Nov 20:44 UTC (`.local/claude_reports/health-20261118.txt`): all four bots unpaused and cycling (last success 20:09–20:40 UTC); reconciliation 20:10 UTC clean; OANDA's 4 open trades match `forex_ai_trades` exactly; Alpaca holdings match the ledgers (BIL/SGOV are cash parking; SGOV only in the portfolio mirror, reconciliation clean). No crypto on the 3 Alpaca or the OANDA account. Kraken account balance UNKNOWN (no read access checked).
- 11 unresolved alarms, all stale: 6 forex HTTP 401 (14–15 Nov, Forex has cycled cleanly since), 1 forex stale-workflow (15 Nov), 4 "unresolved high-severity" meta rows. Closing them is a production write: ASK MARKUS.
- `bot_daily_returns` 14–16 Nov rows were taken ~19:40–19:59 UTC, i.e. before the 21:00 UTC close (the #120 bug). Not rewritten.
- PRs open: #121 kill switch per bot (item 5; stays unarmed), #122 dead code (item 7, code part). Item 6 (momentum brake) was done 11 Nov (status "ITEM 14 CLOSED": index and averages agree on two feeds; per-name check from Alpaca bars).
- WAITING ON MARKUS: merge #121/#122; yes to close the 11 stale alarms; yes to delete dead `bots_state` rows; arm the kill switch (after #121 is live); two free heartbeat monitor URLs (item 8); where to keep the database backups (item 8b).


### Status 19 Nov evening (Opus 5.5)
- Markus 19 Nov ~16:53 Brisbane: "Clean up the older files and start on phase 0. Build as many of the phases ... as you possibly can until you absolutely need me here to merge things."
- Phase 0 code items: all built. Items 2, 4, 5, 7 (code part) were merged before today (#116, #120, #121, #122). Today: the rest of item 7, PR #129 (retired Forex Navigator deleted: `forex-engine/`, the never-registered `routes/forex.py`, its loaders, two dead `forex_trades` queries). The display-name table already exists as one source: `core/bot_registry.py` (`display_name`), served by `/bot-registry`, read by the dashboard (VERIFIED: `artifacts/dashboard/src/lib/bot-identity.ts`). Items 8 and 8b need Markus (below).
- PR #128 (docs only): the 10 Nov plan archived unchanged in `archive/`; this file is now the status log; README points to one source each.
- PR #130: Shadow League core (Phase 1 orders 1–5): 13 shadows + 3 yardsticks run as twins accounts (`bot_id` "league"), decided nightly by pure strategy functions (`research_harness/league/`), valued by the existing twins replay. One registration file per line (`research_harness/registrations/league/`). Version 0 = proving run, not the record. No orders, no new tables, no new paid service.
- PR #131 (stacked on #130): leaderboard API `GET /league/leaderboard` + dashboard "League" page (Phase 1 order 7).
- Tests, local Postgres 16, on the #131 branch: trading-platform 1,138 pass / 1 skip; kraken-bot + sleeve_runtime 293 pass. GitHub tests green on #128, #129, #130 and #131 (checked 19 Nov evening Brisbane).
- NOT BUILT, next: the 3 forex shadows (recommended: FX-COUNCIL = the existing Forex mirror twin; FX-BT1 = TWINS-V2's Forex rules twin, built once on hourly OANDA bars with its ATR stop checked each hour; FX-TREND = a new rule, needs Markus's yes); monthly slippage re-measure from real fills (Phase 1 order 3, second half); month-end freeze + GitHub copy (Phase 2 / TWINS-V2). Phase 3 (Allocator) and 3a (outside views) not started: the guide dates them Jan–Mar 2027 and 3a needs Markus's sources first.
- WAITING ON MARKUS: (1) merge #128, #129, #130, then #131, and publish with the US market closed; (2) yes/no on the PROPOSED rules in the league registration files (listed in PR #130); (3) pass-bar numbers for "came close" / "clearly smaller worst fall" and the luck-check threshold (provisional 0.95, 60 days); (4) unchanged from 18 Nov: close the 11 stale alarms, delete dead `bots_state` rows, arm the kill switch, two free heartbeat monitor URLs (item 8), where to keep the database dumps (item 8b).
- UNKNOWN: whether #121, #122, #124, #125, #127 are published (no inside check today).

### Status 20 Nov early morning (Opus 5.5)
- MERGED by Markus 19 Nov ~18:50 UTC (US market open; not yet published): #128, #129, #130, #132 (leaderboard; #131 had merged into the old branch), #133 (forex lines), #134 (month-end freeze), #135 (execution cost from real fills).
- OPEN: #136 Allocator in shadow, rules version (regime label, funds (a) equal and (b) rules, limits 40% / 1.5x / 15% fall). AI fund (c) not built: needs Markus's yes on AI cost.
- The league now has every roadmap line: 4 real accounts, 3 yardsticks, 16 shadows (FX-COUNCIL = the Forex mirror twin), plus the two Allocator funds once #136 merges.
- New tables (all additive, append-only where marked): twin_month_freeze (append-only), execution_slippage, allocator_labels (append-only). New scheduled job: slippage_daily (17:50 New York, read-only).
- WAITING ON MARKUS: publish with the US market closed (after 07:00 Brisbane); yes/no on every PROPOSED rule (league registrations, FX-TREND, ALLOCATOR-V1); pass-bar numbers; optional GITHUB_RECORDS_REPO / GITHUB_RECORDS_TOKEN for the monthly copy; and the 18 Nov list (stale alarms, dead bots_state rows, kill switch, heartbeat URLs, backup location).
- NEXT: front-end reshuffle once Markus has seen the League page live; Phase 3a needs Markus's sources and cost yes first.

### Status 20 Nov 05:50 Brisbane (Opus 5.5): pass bars set
- MARKUS 20 Nov 05:50 Brisbane agreed the pass-bar numbers Opus proposed (roadmap Phase 4):
  - "Came close" to the S&P 500 = within 2 percentage points a year of its return, after costs.
  - "Clearly smaller worst fall" = at least one third smaller than the S&P 500's worst fall over the same period.
  - The Allocator passes if fund (b) beat fund (a) by at least 1 percentage point a year, after costs.
  - Luck check (already agreed): deflated Sharpe >= 0.95, at least 60 days, 16 tries.
- These go into the league and Allocator registration files as version 1 at the lock (no edit to version 0 files).
- Still to come from Markus: the two heartbeat monitor URLs and the backup location (agreed in principle, not yet given).

### Status 20 Nov midday Brisbane (Opus 5.5): first league night, audit orders, publishes
- First league night (19 Nov NY close, read-only check): 18 league accounts started and valued; Allocator first label "rough down"; 8 real fills measured for costs. Two faults found and fixed:
  - S-MOMO-CAP made no decision: SSGA's Sector column was "-" for all 500 members. Fix #145 (sectors from the iShares IVV file; a missed night with a reason if none). UNKNOWN until 20 Nov night: whether IVV gives real sectors from Replit.
  - forex_ai mirror twin failed nightly since 17 Nov (OANDA HTTP 400): it asked for "CHF_USD". Fix #142.
- Audit orders done: AU1 #141 (Forex in the comparison), AU3 #143 (stale text), AU4 #144 (AI impact route removed), AU5 #148 (overnight financing in forex twins; Markus chose option A 20 Nov 11:32), AU9 #149 (dumps to F:\Backups\DDG-Finance on Markus's PC, removed from the repo; history not rewritten). Front end: #146 (gains green, losses amber), #147 (League v2).
- Published 20 Nov 11:42 and 12:01 Brisbane, US market closed, read-only pre and post checks: holdings and stops unchanged, 8/8 positions covered by stops, reconciliation clean, runner handover normal.
- MARKUS 20 Nov 12:34 Brisbane agreed all recommendations:
  - AU6 yes: build the AI twins of Atlas, Atlas V2, Momentum (TWINS-V2 Phase B) and an "AI may reduce or skip" twin of T-15X, S-MOMO-CAP, D-XTREND. No orders, no new account. Register before the lock (12-13 Dec).
  - AU7 yes: Forex lines pass on return above zero after costs AND above FX-BT1; diversifiers judged by what they add to the equal-money fund. Goes into the version 1 files at the lock.
  - AU8 yes: pin dated model ids for the council at the lock as a new council version; a free model ending mid-year = a new dated version.
  - AU10 yes: delete bots_state rows bot2_spy_qqq and forex_gump (row-count guard 2).
  - Kill switch stays report-only until the per-bot version is built and proven.
- Still from Markus: UptimeRobot heartbeat URL for the runner.
- Next (Opus): Forex, Research and Controls page redesigns; phone tab bar and Home card carousel; ddg.limited public PC/phone view; AU6 build.

### Status 22 Nov morning Brisbane (Opus 5.5): roadmap v2 adopted, thesis page, first GATE orders
- MARKUS 22 Nov 05:47 Brisbane: roadmap v2 (`fund-roadmap-v2-2026-11-21.md`) and the thesis (`fund-thesis-2027.md`) are "the ultimate source of truth"; "make sure that we match this fund roadmap exactly"; the thesis is the public paper. Read as: yes to D1 and to the recommended answer of every decision. Still asked explicitly before acting (roadmap rule 2 and README): 🔴 D2 (what Atlas V2 trades at the lock), D17 (stopping the old walk-forward job), the V2-23 write of table F to the production database.
- Open PRs (Opus cannot merge from this session; Markus merges):
  - #173 V2-00: roadmap v2 + thesis in docs/plans, README reading order, build-guide pointer (docs only). `macro-research-2026-11-21.md` NOT added: not supplied yet.
  - #174 Paper page: `scripts/thesis_page.py` builds `artifacts/dashboard/public/paper.html` word for word from the thesis file (test: every sentence on the page; source SHA-256 printed). Replaces the 3 Nov paper.
  - DDG-Control #161: the same page at ddg.limited/thesis/index.html + "Read the 2027 thesis" button on /finance. Markus approves the button words before publish.
  - #175 V2-04 + Y-GOLD: D-OIL, H-ASSET, T-GLOBAL, FX-CARRY, D-TIPS, and yardsticks Y-MF, Y-PERM, Y-TIPS, Y-INS, Y-GOLD (version 0 files). Luck-check tries 17 → 22.
  - #176 V2-06 + V2-19 (stacked on #175): macro label, six votes, four flags; append-only `macro_state` table; read by no rule. `python -m twins.macro_check` for the hand checks.
- Tests (local Postgres 16, 22 Nov): trading-platform 1,224 passed / 1 skipped; kraken-bot + sleeve_runtime 295 passed.
- UNKNOWN until the first night after publish: Alpaca daily bars for USO, XLE, EFA, EEM, TLT, TIP, DBMF, TAIL, IWM, HYG; whether TAIL still trades.
- Next (Opus): V2-05 macro tape + V2-18 long-view panel (GATE, by Fri 4 Dec); V2-01 evidence table; V2-07, V2-08 (with warm-up), V2-09, V2-24, V2-25 for intake 1; V2-16 intake page; V2-22 drills.

### Status 22 Nov morning Brisbane (Opus 5.5): roadmap v2 merged and published
- MARKUS 22 Nov 06:22 Brisbane: merged #173–#176 and DDG-Control #161, published ddg.limited; "You're okay to publish DDG Finance now"; 🔴 D2 = B (recommended: Atlas V2 becomes the cross-asset trend rule FLEET-V1-X1 at the lock); D17 = A ("Retire the old one"). #176 had merged into its stacked base, not main: carried to main as #177 (Opus's stacking mistake). #177 and #178 merged 06:29.
- Pre-publish READ-ONLY check, production, 21 Nov 20:32 UTC (`.local/claude_reports/prepublish-20261122.txt`): Alpaca market closed. Holdings: oracle BIL, DBC 131, QQQ 10, SGOV, SPY 14, UUP 385, VOO dust; jerome_macro BIL, QQQ 14, SGOV, SPY 19; spy_qqq_trend BIL, SGOV. Stops: QQQ and SPY on oracle and jerome_macro (527.61 / 584.16); all 4 OANDA trades have stop-losses. No stop on BIL/SGOV (cash parking), DBC/UUP (trend-exit lines by design) or VOO dust. Reconciliation 19:52 UTC clean. Runner leases all held by the published runner, last cycles 19:40–19:52 UTC. Last league night: session 20 Nov, 18 shadows.
- V2-26 step 1, what the old walk-forward job wrote on its last five nights (16–20 Nov, 22:30 UTC): oracle AMBER every night, trailing-90d Sharpe −10.83 against a floor of −0.153, "below floor" count 17 → 21; jerome_macro DISQUALIFIED; spy_qqq_trend INSUFFICIENT_DATA (floor −1.889). Shown in /claude-report, /reports and the dashboard hook (unused on screen) only. None of it describes the strategies the accounts run now. Left over: table `kraken_wfo_results` (definition in `db/postgres.py`), kept.
- Workspace synced to main 9e53876 (normal merge, HEAD 5ff01349). Published 22 Nov morning Brisbane, Sat 21 Nov New York (deployment 42bce971, status success), US market closed.
- Post-publish READ-ONLY check, 21 Nov 20:44 UTC (`.local/claude_reports/postpublish-20261122.txt`): published revision created 20:34:39 UTC (running hash UNKNOWN: /trading-api/version is behind ReplShield). Holdings, open stop orders and OANDA trades identical to the pre-check, line by line. All four bots cycled successfully at 20:39 UTC on the new runner; six "Runner lock REFUSED" lines for oracle 20:37–20:39 UTC were the normal lease handover, gone once the old heartbeat went stale. Reconciliation 20:41 UTC clean. No application ERROR lines. "Registered: nightly_walk_forward" not in the logs (as intended); the twins check asked for the wrong wording (the real line is "Registered: twins_hourly ... + twins_nightly"), so confirm on Monday night that the league ran.
- Expected on the first league night after publish (Mon 23 Nov, New York): 10 new pretend accounts (29 in all) and the first `macro_state` rows. FX-CARRY decides once financing rates are stored (they are, from 20 Nov).
- Next (Opus): 🔴 V2-03 (FLEET-V1-X1 for jerome_macro, switch off until the lock; rehearsal first); V2-05 + V2-18 (GATE, by Fri 4 Dec); the macro_check hand checks on Replit.

### Status 26 Nov morning Brisbane (Opus 5.5): platform audit (Markus: "make sure everything is running smoothly")
- Merged since 22 Nov: #181 V2-03 build (switch off), #182 repo renames, #183 Night Glass motion on the dashboard, #184 comments. Published 24 Nov 01:26 UTC (deployment revision 6c972955, built from main 6a3e376); post-publish stop check clean (24 Nov).
- Live, READ-ONLY (Replit agent on production, 25 Nov 20:30–20:51 UTC, US market open):
  - The runner is alive, heartbeat seconds old. All four bots cycle hourly, last 19:34–19:40 UTC; none paused. Fleet halt off. Kill switch not armed (alert-only by the 14 Nov decision) and not tripped.
  - Stops: QQQ 527.61 / SPY 584.16 on oracle and jerome_macro; all 4 OANDA trades have stop-losses. Stop coverage PASS 20:30; reconciliation clean 19:33 and 20:33.
  - Equity: oracle 85,436.34; jerome_macro 76,300.81; spy_qqq_trend 99,197.89; OANDA NAV 103,433.72.
  - Twins nightly 24 Nov 22:15: all 29 league accounts wrote a value; macro_state for 23 and 24 Nov reads "reflation".
  - Live checks: no flags. DDG Control push: ok. Database backup: ok (24 Nov 22:00).
- Found and fixed (PR #186):
  1. Two `twin_ledger_broken` alarms were false alarms. FX-CARRY's row 50 hashed a JPY carry of -0.0, and the database stores numbers without the sign of zero. Proved: the stored hash matches with JPY = -0.0. Fix: -0.0 is never stored or hashed; older rows pass only when the sign of a zero is the sole difference; the alarm clears on the first night every chain is intact.
  2. `test_human` read the wall clock (the Me account started "today"), so CI fails from 25 Nov on. The account now starts from the first trade's time.
  3. The ddg.limited showcase skipped `/league/leaderboard` 24 times in 48 hours on a 20 s timeout. Now 90 s, and its success lines reach the log.
  4. The vault backfill queried the deleted `forex_trades` table on every startup (Postgres error per publish). It now skips and marks itself done.
- Found, needs Markus:
  - DDG Control has no `/api/inbound/finance/forex-ai-switch`. Finance's hourly read gets 401 from Control's `/inbound` guard and keeps the last state: the AI stays on unless Finance's own switch is off.
  - `HEARTBEAT_URL_RUNNER` and `HEARTBEAT_URL_API` are not set (asked 11 Nov): nothing outside Replit notices if the platform stops.
- Still open for the GATE (merge and publish by Fri 4 Dec, market closed):
  - V2-05 macro tape and V2-18 long-view panel: not built.
  - V2-03's Momentum v2 (weekly re-entry, 25% sector cap): not built, 🔴 order path.
  - V2-06/V2-19 hand checks (`python -m twins.macro_check`): not run.
  - Atlas V2's display name at the lock: not asked.
- Open PRs: #185 (Me page names, sectors, % wheel), #162 (AU13 proposal), #186 (this audit's fixes; merge before #185, whose CI hits the clock test).

### Status 27 Nov morning Brisbane (Fable 5.2): audit, luck check fixed
- Audit of main `3de860f` against the thesis and roadmap v2: Project doc `claude/finance-audit-2026-11-27.md`. Nothing live was read.
- FIXED (this PR): the luck check scored raw returns, not returns over T-bills (`twins/leaderboard.py`). A line parked in BIL would have read "clear" after 60 days with no skill, and its raw Sharpe widened the spread every other line is judged against. Now each day's return has Y-CASH's taken off. Forex lines are not reduced (their idle money earns no T-bill interest in the engine). `luck_rule.basis` says which reading the board used. FOR MARKUS: say no if forex lines should also be reduced; it is a pass-bar detail and goes into the version 1 files at the lock either way.
- `replit.md`: Atlas V2 becomes FLEET-V1-X1 (not Defensive stocks), 22 lines and 8 yardsticks, walk-forward job retired.
- Tests here: research_harness 172 passed; the leaderboard's three pure tests passed with the platform imports stubbed. The full platform suite was NOT run here (no packages); GitHub's run is the check.
- OUTSIDE MONITORING, checked 27 Nov from outside, anonymous: `/trading-api/liveness` answers 302 to Replit's sign-in (ReplShield, private deployment), the same as on 13 Nov. An UptimeRobot monitor that calls the app's address therefore reaches Replit's sign-in page, not the app, and cannot tell whether the platform is alive. UNKNOWN: what Markus's two UptimeRobot monitors point at. The built route is the other direction: the platform calls out (`HEARTBEAT_URL_RUNNER`, `HEARTBEAT_URL_API`), which works through a private deployment. The 26 Nov production read found both unset.
- 🔴 STILL OPEN, needs Markus: the 3 Sep production and development database dumps are in this public repo's git history (commits `f51aef6`, `63a1592`); #149 removed the files only. Make the repo private, or rewrite history and change every token that was in the database that day.
- Not built, due Fri 4 Dec (GATE): Momentum v2 (🔴 order path), V2-05, V2-18; the V2-06/V2-19 hand checks. Not started: V2-01, V2-02, V2-07, V2-08, V2-09, V2-14, V2-16, V2-20 to V2-25.

## Not doing
- Any crypto, on any account or system, full stop (Markus 17 Nov; was "no crypto sleeve", 10 Nov). Coins, pairs and crypto funds. Buys refused in code (PR #117). The last BTC was sold 17 Nov (owner-approved); no crypto is held anywhere.
- A fourth Alpaca paper account (cap is 3).
- Jane Street Kaggle data (anonymised high-speed data; we run no such models).
- Conviction-based Forex leverage before 60 trades show an edge.
