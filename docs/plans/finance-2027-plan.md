# DDG Finance — plan to the 2027 test year
Written by Claude (Fable 5.2), Tue 10 Nov 2026; last updated Sun 15 Nov ~19:15 Brisbane (twins Phase A live, TWINS-V2 registered, ETH stop fill, weekend alarm fixes). Agreed by Markus 10 Nov.
Roles: FABLE = diagnosis, strategy, specs, pass bars, reviews. OPUS = coding. MARKUS = decisions and things only he can click.
Target: strategies locked the weekend of 21–22 Nov, record starts Mon 23 Nov 2026 (needs the 5-clean-day gate first).
Constraint (Markus 10 Nov): Alpaca paper accounts are capped at 3 and all 3 are in use. No fourth account.
MASTER COPY: this file in GitHub (quant-terminal `docs/plans/finance-2027-plan.md`). The claude.ai Project doc `claude/finance-2027-plan.md` mirrors it; whoever edits one updates the other in the same session.

## Line-up (agreed 10 Nov; cutover not done)
| Bot | Account | Strategy | Note |
|---|---|---|---|
| 1 Preferred | to decide at cutover | FLEET-V1-C1: geared S&P/Nasdaq trend, up to 1.5x, vol-targeted, cash when trend off | 2021–2026 (spent window): 15.1%/yr vs 14.6%, worst fall −26.8% vs −24.5% |
| 2 Cowboy | to decide at cutover | GEAR-V1-G4: same idea up to 2x | 2021–Oct 2026: 18.05% vs 15.18%, same worst fall. Lost ~41% in 2000–02 reconstruction |
| 3 Experiment | spy_qqq_trend | MOMO-V2 stock momentum (about 70%) + geared gold/silver trend sleeve (about 30%). Exact rules and split by FABLE before start | forward-only, no claim from history |
| 4 Forex | forex_ai | 3-AI vote, risk 0.5%/trade (option A) | scorecard also shows what 2x and 4x would have made; leverage only after 60 trades show an edge |
- FLEET-V1-F1 (today's Atlas) continues as a no-orders shadow.
- Nothing has passed a clean test. The 2021–2026 window has been used several times; the paper record is the test.
- SUPERSEDED 17 Nov (no crypto, full stop; see Status 17 Nov). Was: DECIDED (Markus 10 Nov): the leftover BTC/ETH in jerome_macro STAYS (frozen holding with its stops, about 15% of that account on 10 Nov: BTC ~$7.3k, ETH ~$4.7k of ~$80k). No crypto strategy anywhere else. Reports must show that account's result with and without the crypto line so the strategy's own record is readable.

### Bot 3 detail
- Stock part: MOMO-V2 (research_harness/explore/MOMO-V2-PLAN.md): top 50 S&P 500 stocks by 12-1 momentum, equal weight, book-level trend and volatility brakes, 20% stops, monthly. Markus 2 Nov: stocks must be in the comparison.
- State 10 Nov: all cash (BIL/SGOV). bots_state metadata: key=2026-11|out|normal, trend_on=false, index=100, sma100=125.056, vol20=0.563, s=0.266, 50 names. Never bought a stock since 3 Nov; cannot re-enter before the December signal day.
- ⚠️ TO CHECK (FABLE then OPUS): index 100 vs a 100-day average of 125 and 56% volatility on a 50-stock book look too extreme. Either the momentum names really fell ~20% (S&P fell 4.4% on 5 Nov) or the book index is calculated wrongly (rebase / split-adjusted bars). Recompute by hand from Alpaca bars.
- Gold/silver sleeve (Markus 10 Nov: no crypto sleeve; leverage on steadier assets instead). Shape only; FABLE fixes the numbers at registration:
  - Hold gold (and a smaller silver line) only while each is above its own trend; cash (SGOV) otherwise.
  - Leverage up to 2x while the trend is on and volatility is low, through 2x funds (UGL gold, AGQ silver — availability on Alpaca paper UNVERIFIED) or the plain funds GLD/SLV; no margin borrowing. Same gearbox pattern the engine already runs for G4.
  - Sized by volatility: silver moves about as much as shares, so it gets a smaller line than gold.
  - Stop on every holding, set from the asset's own normal daily range, not a fixed tight percentage.
  - Known history (handoff v9): a permanent commodity sleeve and EMA trend on commodity ETFs failed out-of-sample (experiments 8/9); levering low-volatility ETFs with Alpaca margin at 6.25% interest lost about 20–25% over 2008–2022. This sleeve differs (gold/silver only, trend-gated, no margin interest); it stays an experiment with a pre-set pass bar.
  - Forex-style leverage is Bot 4's job (OANDA); Alpaca does not trade currencies.

## AI harness (Markus 10 Nov)
Runs all year as a SHADOW (no orders); decide at end of 2027 whether to switch it on.
- For every bot decision (buy/sell/rebalance, each stock for Bot 3), the 3-AI council (Forex harness, with news) votes agree / reduce / veto, with reasons.
- Two records per bot: "bot alone" (real paper account) and "bot + AI" (computed, same costs).
- Shadow limits: AI can only reduce or skip, never add; at most halve; a vote expires after N days unless renewed; bot rules and stops still apply.
- Scoring: 5- and 20-day outcome after each reduce/veto vs normal days; year-end return, worst fall, Sharpe for both records.
- Pass bar and N written by FABLE before the first logged vote. Model versions and training cutoffs recorded; a model/prompt change = new dated version.
- Cannot be backtested (LLM memory). Verdict may need the full year.

## Record start
- Current: RUN_START = 2026-11-09 (trading-platform/core/fleet_capital.py, PR #90): oracle 86,919.04; jerome_macro 80,155.66; spy_qqq_trend 99,178.36; forex_ai 99,469.35.
- Restarts once more at the strategy lock, then never again.
- Home chart: one point per trading day. Annual return / Sharpe / volatility show from 20 trading days.

## Checklist
### Step 1 — get trading again: DONE except the last confirmation
1–4. [x] Diagnosis; stops re-placed by hand; PR #89 stop safety (reviewed, one bug fixed, merged, published 9 Nov 22:41 UTC); PR #90 run start (published 10 Nov 03:04 UTC). Post-checks clean.
   Incident summary (9 Nov 15:13 UTC): Atlas partial sells of SPY/QQQ cancelled the stops and the re-arm failed 4 times (likely Alpaca's open-orders list still showing the cancelled stops); kill switch paused all bots 15:46 UTC; paused bots never ran so nothing re-armed; Atlas V2 false ledger mismatch (wrong table); SGOV close failed on float rounding.
5. [x] Markus reset the kill switch 10 Nov 07:23 UTC (17:23 Brisbane). [ ] FABLE confirms all four bots cycle (check scheduled 08:23 UTC) and after the US open (14:30 UTC): reconciliation clean, stops in place.
6. [x] Forex first 3-AI vote logged for 9 Nov: all three members, 7 decisions, no errors, no orders (bots were paused).

### Step 2 — reliability (10–20 Nov). OPUS builds, FABLE specs and reviews
7. FABLE: audit the whole order path; write the "must never happen" list (position without a stop >60 s; order while paused; dev process touching the live DB; publish with open non-protective orders).
8. OPUS: separate Finance's dev workspace from the production database (dev DATABASE_URL = production NEON: restarting the dev API runs startup SQL on live data). Until fixed every Replit sync prompt must say DO NOT RESTART WORKFLOWS.
   [built: PR #92] Workspace sessions read-only via PGOPTIONS in [userenv.development]; API skips schema setup, runner exits when read-only. After the sync, restart workspace workflows once to pick it up; then check SHOW transaction_read_only = on and that production still writes.
9. OPUS: rehearsal before live, WITHOUT a new account (3-account cap):
   a. Until the 23 Nov start: Bot 3's account (spy_qqq_trend) is all cash and idle, and its record restarts on 23 Nov anyway. Use it as the rehearsal account: bot paused during a rehearsal, tiny orders (1 share), own client-order-id prefix and a separate ledger tag so nothing mixes with strategy rows, everything closed and reconciled clean at the end. Scenario script prints pass/fail: buy, top-up, partial sell, full close, stop re-arm, 2x-fund buy (UGL/AGQ check).
   b. After the start: no live-account rehearsals; new code is proven on the fake broker (10) and replay (11) first, then goes live on ONE bot for a session before the others.
   [built: PR #94, stacked on #93] kraken-bot/rehearsal.py. Run: Momentum paused, market open, `PGOPTIONS= python3 kraken-bot/rehearsal.py --live`. Answers UGL/AGQ availability. Not run yet.
10. OPUS: broker-quirk tests — a fake broker that misbehaves (open-orders list lagging a cancel, rejected order, partial fill, 429 rate limit, feed drop, price gap through a stop) and tests that every holding ends up protected or alarmed.
   [built: PR #93] 10 quirk tests pass. Found and fixed: stop-free buys (DBC/GLD/UUP) were missing from the trades journal. Found, not fixed: buy_market client ids not bot-tagged.
11. OPUS: replay test — run a recorded real market day (bars + the day's orders) through each bot's cycle offline.
   [built: PR #93] 9 Nov Atlas replay: old code reproduces the incident; fixed code protected at 0/5/300 s cancel lag.
12. OPUS + FABLE: live-versus-research check — a monthly report comparing each bot's actual holdings with what the research code says for the same days; includes the price-feed difference (live falls back to IEX bars).
   [built: PR #96] Daily row per account (Alpaca feed vs Yahoo, same registered rules), monthly Discord summary on the 1st, GET /fleet/live-check. MOMO selection from ~500 names not re-run. FABLE: confirm the flag thresholds (0.5% close, 2 pt weight, 1% index, 5% name).
13. OPUS: alarms — auto-resolve stale rows so a new alarm means something (4 unresolved on 10 Nov; keep it there); daily automatic health check pushed to Discord; keep deployment logs >24 h; fix the 2 tests failing on main (test_forex_ai_registration four-bots, test_invariants cycle_freshness all-paused); bots_state status/paused mismatch after a kill-switch reset.
   [built: PR #91] All six parts. Still open after publish, need a decision (FABLE + MARKUS): daily_return_portfolio_stale (1) and fleet_v1_c1_rebalance (1, the ETH "frozen" note; recurs monthly while BTC/ETH sit in that account: downgrade to warning or resolve by hand).
13b. OPUS (Markus 10 Nov): Home page bot cards show what each bot holds, in plain words, so the strategy can be read off the card:
   - A compact "Holds" line or mini bar per card: each asset group as % of that account's equity, largest first, e.g. "S&P 500 28% · Nasdaq 19% · Commodities 4% · Dollar 13% · Cash 36%". Leveraged funds say so ("S&P 500 2x 40%"). Percentages are of account equity and sum to 100% (cash/T-bills and vault shown as their own items; crypto as its own item on jerome_macro).
   - Forex card: each open pair with direction and size as % of account (e.g. "EUR/USD short 39%"), plus gross exposure.
   - One short rule line under the name (what it does and its limit, e.g. "S&P + Nasdaq trend, up to 1.5x"), taken from the bot registry: one source, no second list in the front end.
   - Data from live positions already served to the Home page (no new broker calls); symbol -> group map in one place on the server.
   - Must still fit Overview on one screen at 1366x768 and 1600x900 with no scrolling; check phone.
   [built: PR #95] Checked at 1366x768, 1600x900, phone (mock data). The card bottoms were already cut off on main at both sizes; short cards now drop the mini chart/meter/stats so Holds shows.
14. FABLE: check the Momentum book index (Bot 3 detail above); OPUS fixes if wrong.
15. FABLE: re-check two older open items — the dashboard bundle holding the trading-API secret (K1), and drawdown limits being record-only (ENFORCE_DRAWDOWN_LIMITS). Decide with Markus.
16. Gate: 5 trading days with no incident (sessions Tue 10, Wed 11, Thu 12, Fri 13, Mon 16 Nov) before any strategy change. Front-end-only changes (13b) may publish during the gate, market closed, with the usual pre/post checks.

### Step 2 status (Wed 11 Nov 07:30 Brisbane): items 8–13b LIVE
- Reviewed by FABLE, merged (PRs #91–#97), published 10 Nov 21:12 UTC (workspace c28586d = main 97086b5). Pre- and post-checks clean: same holdings and stops, reconciliation clean, all four bots cycled 21:13 UTC.
- Review fixes: #93 test helper could have deleted live ledger rows if run in the workspace (guard now starts before any test loads); log copy connection leak; live check treated missing research data as agreement; rehearsal rows now counted by invariants.
- Alarm clean-up (Markus 11 Nov: "alarms need to mean something"):
  - Forex weekly audit "off schema": FALSE (JSONB does not keep key order). Fixed; audit on live data now returns 0 findings.
  - ETH "frozen" on Atlas V2: expected (owner-kept BTC/ETH). No longer alarms; any other untouched holding still does.
  - daily_return_portfolio_stale, would_trip, bot_paused_ledger_mismatch, close_failed: now clear themselves; all cleared by the first resolver run.
  - "Bots stale" after a reset: fixed (counts from the resume).
  - One-off resolve of the 6 weekly_audit rows + row 10138 (owner-approved production write, 11 Nov).
- New: workspace database sessions are read-only (verified live: SHOW transaction_read_only = on; a deliberate write needs the `PGOPTIONS=` prefix). 30-day log copy `runtime_log` (verified filling). Daily health message 08:40 Brisbane. Live-vs-research daily row 17:40 New York. Home cards show rule + Holds. Outside heartbeat (PR #97): inert until Markus adds secrets HEARTBEAT_URL_RUNNER / HEARTBEAT_URL_API (healthchecks.io or similar).
- Replit sync facts: git remote is `gh`; use a normal merge (never fast-forward-only); report to .local/claude_reports/NAME.txt and read it with read_app_file.
- Fix list found during publish: (a) one failed broker read raises invariant alarm rows at once (2 rows at 21:04 UTC; should need two in a row); (b) standing_invariants logs every PASS line at WARNING while any check fails (log noise); (c) buy_market client ids not bot-tagged; (d) four dead bots_state rows (bot2_spy_qqq, depeg_hunter, forex_gump, kraken_trend).
- Not run: rehearsal (#94). Needs Momentum paused + market open; `PGOPTIONS= python3 kraken-bot/rehearsal.py --live`.

### Morning checks (11 Nov, read 02:17 UTC)
- Open alarms: 0 (the 264 "no open alarms" rows cleared on their own). First daily health message sent 22:40 UTC: "✅ All good".
- Live vs research, first day (10 Nov): Atlas and Atlas V2 agree exactly (same votes, exposure and weights on Alpaca SIP and Yahoo; largest close gap IEF 0.34%). Momentum agrees (index 105.52 vs 105.51, average 124.55 vs 124.56); one flag: TGT close 0.7% apart.
- ITEM 14 CLOSED, not a bug. The Momentum book index is right: both feeds give the same numbers, and per-name check (Alpaca bars, 11 Nov) shows the 50 names had a median +102% 12-1 return then a median −27% in the month before selection; 31 of 50 fell more than 20%. The trend brake kept Bot 3 in cash as designed. For registration (item 17): the list is heavily one theme (memory, storage, chip equipment: SNDK, INTC, STX, WDC, MU, LRCX, AMAT, KLAC...); consider a sector cap.
- Found: engine deadlock at 22:14 UTC + latent cross-account ledger repair → PR #98 (open, needs review; publish market closed).
- Noise: the old Navigator forex engine's routes still query missing tables (forex_trades, forex_portfolio) when the dashboard polls them: retire.

### Agency queue (Markus 11 Nov: "Go" + "deliver it as close to perfect as you can")
1. Momentum book index check (item 14) using the first live-vs-research rows.
2. Order-path audit + "must never happen" tests (item 7).
3. Rehearsal run (🔴 real 1-share paper orders).
4. Clean-up: fix list (a)–(d).
5. Decisions with Markus: trading-API secret in the dashboard bundle (K1); ENFORCE_DRAWDOWN_LIMITS.
6. Strategy lock registrations (item 17) before 21–22 Nov.
7. Public Finance page on ddg.limited (Markus 11 Nov 07:06): performance, holdings, strategy paper incl. failed tests, how the platform works; trading platform stays private, data flows out only via the existing hourly push. Open question: public record from 23 Nov (labelled pre-launch) or 1 Jan 2027.

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

### Status 18 Nov morning (Opus 5.5)
- PUBLISHED 17 Nov ~10:07 UTC (US closed): #119 (BTC sold, OWNER_KEPT empty) and #120 (daily closing snapshot at 17:25 New York time, all year). First run at the new time: 17 Nov 22:25 UTC.
- READ-ONLY HEALTH CHECK, production, 17 Nov 20:44 UTC (`.local/claude_reports/health-20261118.txt`): all four bots unpaused and cycling (last success 20:09–20:40 UTC); reconciliation 20:10 UTC clean; OANDA's 4 open trades match `forex_ai_trades` exactly; Alpaca holdings match the ledgers (BIL/SGOV are cash parking; SGOV only in the portfolio mirror, reconciliation clean). No crypto on the 3 Alpaca or the OANDA account. Kraken account balance UNKNOWN (no read access checked).
- 11 unresolved alarms, all stale: 6 forex HTTP 401 (14–15 Nov, Forex has cycled cleanly since), 1 forex stale-workflow (15 Nov), 4 "unresolved high-severity" meta rows. Closing them is a production write: ASK MARKUS.
- `bot_daily_returns` 14–16 Nov rows were taken ~19:40–19:59 UTC, i.e. before the 21:00 UTC close (the #120 bug). Not rewritten.
- PRs open: #121 kill switch per bot (item 5; stays unarmed), #122 dead code (item 7, code part). Item 6 (momentum brake) was done 11 Nov (status "ITEM 14 CLOSED": index and averages agree on two feeds; per-name check from Alpaca bars).
- WAITING ON MARKUS: merge #121/#122; yes to close the 11 stale alarms; yes to delete dead `bots_state` rows; arm the kill switch (after #121 is live); two free heartbeat monitor URLs (item 8); where to keep the database backups (item 8b).

### Status 17 Nov evening (Opus 5.5)
- 🔴 NO CRYPTO, FULL STOP (Markus 17 Nov): "none of the accounts at all trade any crypto... on any of the platforms, on any of the systems". Reason: Bitcoin security breaches.
- PR #117: every order that would buy crypto (coin pairs, crypto funds such as IBIT/GBTC/ETHA) is refused before it is sent and logged critical, on every Alpaca client (shared session from #116) and on OANDA. Sells still work.
- Fix window item "BTC stop-fill ledger close" becomes "crypto exit closes its ledger row" (BTC sold by stop or by Markus).
- PR #116 (time limits on broker calls, F5) merged; not yet published.
- PUBLISHED 17 Nov ~07:16 UTC (US closed): #116 (broker time limits) and #117 (no-crypto guard). Tests in the workspace before publish: 293 + 1,097 passed. Outside check after: ddg.limited push 07:16 UTC, 4 bots unpaused. Alarms and broker-vs-ledger: NOT checked from inside (UNKNOWN).
- 🔴 BTC SOLD (Markus 17 Nov 17:38 Brisbane: "Yes, sell the Bitcoin"). Stop a21f0320 cancelled; one market sell 0.097758577 BTC/USD filled 07:41:36 UTC at avg 64,519.74 (order 25ae6d82). Entry 78,973.10: about −$1,413 on the line (arithmetic). bot3_positions id 1 closed, bot_portfolio BTC item removed, change_log row 16 (owner-approved production write; before/after in `.local/claude_reports/btc-sale.txt`). No crypto left on any account. OWNER_KEPT emptied in code (PR "BTC sold").
- (superseded) WAITING ON MARKUS: whether to sell the remaining owner-kept BTC now (an order: needs his yes); publish approval for #116/#117 (US market closed); the live website still says the Finance bots read/hold crypto.

### Step 3 — lock strategies (weekend 21–22 Nov, market closed)
17. FABLE: registration + pass bar for Bots 1–4 and for the AI shadow, written before the start; exact Bot 3 rules (stock / gold-silver split, trend rule, gearing, stop width).
18. OPUS: cutover rehearsed per 9a first, then live (one account F1 -> G4, F1 shadow, labels Bot 1/2/3/4, gold/silver sleeve on Bot 3), Forex 2x/4x "what if" columns, AI shadow harness. FABLE reviews before it goes live.

### Step 4 — run (from Mon 23 Nov if the gate and Step 3 are met)
19. No rule changes until 31 Dec 2027; any change is a new dated version reported separately.
20. FABLE monthly review: every number, good or bad, bot alone vs bot + AI, live vs research, Bot 1 with and without its crypto line.
21. Real money only after 90 clean paper days and measured costs.

## Not doing
- Any crypto, on any account or system, full stop (Markus 17 Nov; was "no crypto sleeve", 10 Nov). Coins, pairs and crypto funds. Buys refused in code (PR #117). The last BTC in jerome_macro is only protected by its stop until it is sold.
- A fourth Alpaca paper account (cap is 3).
- Jane Street Kaggle data (anonymised high-speed data; we run no such models).
- Conviction-based Forex leverage before 60 trades show an edge.
