# DDG Finance — start here (for any Claude picking this up)

Last updated: Tue 17 Nov 2026 ~09:30 Brisbane (UTC+10) by Claude (Fable 5.2): reading order and the 17 Nov notice only. "Live state" and "Next work" below are still from Wed 11 Nov (Opus 5.5) and are older than the roadmap.
Read in this order:
1. This file (how to work, Replit facts, publish rules).
2. `fund-roadmap-2026-11-17.md` — AGREED (Markus 17 Nov): the road from today to a self-running fund (fix window, Shadow League, Allocator in shadow, staged real money). **This is the target.**
3. `fund-roadmap-build-guide-for-opus.md` — how Opus 5.5 builds that roadmap alone (no Fable in the loop). Since 17 Nov it also holds Part B: the whole-company build list (audit fixes and growth builds in the other DDG repos), to be worked while the Finance gate runs.
4. `finance-2027-plan.md` — the earlier plan, its checklist and the dated status entries. **The running history; add a Status entry after every work session.** Where it differs from the roadmap, the roadmap wins.
5. `order-path-audit-2026-11-16.md` — every code path that can place an order, findings F1 to F5, and the "must never happen" list.
6. `forex-council-2027-registration.md` and `ai-twins-2027-registration.md` — registered forward tests (do not edit; new versions are new dated files).

No secret values are in these files or anywhere in this repo. Secrets live in Replit Secrets only (names may be mentioned, never values).

## What DDG Finance is
In-house algorithmic trading platform (paper only). 3 Alpaca paper accounts (cap: 3, all in use) + 1 OANDA practice account. Goal: an honest public track record; strategies lock 21–22 Nov 2026, record starts Mon 23 Nov 2026 (if the 5-clean-day gate is met), runs all of 2027. Not open to outside money, not financial advice.

| Account (bot_id) | Name on dashboard | Strategy now | 2027 plan |
|---|---|---|---|
| oracle | Atlas | FLEET-V1-F1 (65% S&P/Nasdaq trend up to 1.5x + 35% bonds/gold/commodities/dollar trend) | see plan line-up |
| jerome_macro | Atlas V2 | FLEET-V1-C1 (S&P/Nasdaq trend up to 1.5x) + owner-kept BTC (no crypto rule: protected by its stop, never added to; ETH sold 14 Nov) | Defensive stocks at the lock |
| spy_qqq_trend | Momentum | MOMO-V2 (top 50 S&P 500 stocks by 12-1 momentum, monthly, trend brake); in cash since 3 Nov | Bot 3 = MOMO-V2 ~70% + gold/silver trend ~30% |
| forex_ai | Forex | 3-AI council vote, 0.5% risk/trade, max 4 trades | Bot 4 |

## Live state (11 Nov 2026)
- Published 10 Nov 21:12 UTC from main `97086b5` (PRs #91–#97). Post-checks clean.
- Morning check 11 Nov 02:17 UTC: 0 open alarms; daily health message "All good"; all 4 bots cycling; broker and ledger agree; Forex vote ran 22:16 UTC.
- New since 10 Nov: workspace DB sessions read-only (`PGOPTIONS` in `.replit` `[userenv.development]`; a deliberate write needs a `PGOPTIONS=` prefix); 30-day log copy (`runtime_log`); daily health Discord 08:40 Brisbane; live-vs-research daily check (`live_research_check`, `GET /fleet/live-check`); Home cards show rule + Holds; outside heartbeat (inert until secrets `HEARTBEAT_URL_RUNNER` / `HEARTBEAT_URL_API` are set).
- OPEN PR #98: engine set-up once per process (fixes a ledger-table deadlock seen 22:14 UTC 10 Nov) + current_qty repair scoped to the account's own rows (latent cross-account write). Needs review, merge, and a publish with the US market closed.

## 🔴 What changed on 17 Nov 2026 (read before the older sections)
- The 5-day gate (Mon 16 – Fri 20 Nov) is STOPPED by Markus. New order: fix window, then ONE new gate on the final system, then the lock (about 12–13 Dec).
- The roadmap is agreed. At the lock, Defensive stocks replaces Atlas V2's strategy.
- 🔴 NO CRYPTO, FULL STOP (Markus 17 Nov): no account or system trades any crypto. Buys are refused in code (PR #117); sells still work so the last BTC stays protected until it is sold. No new trading accounts or paid services.
- Tests now run on GitHub for every pull request and on main (`.github/workflows/tests.yml`). Green before any merge.
- NOT known when written: whether PR #108 (order-path fixes) is published; the result of the Mon 16 Nov session and rehearsal.

## Next work (in order) — see the plan's "Agency queue"
1. PR #98 review → merge → publish (market closed).
2. Order-path audit + "must never happen" tests on the fake broker (plan item 7).
3. Rehearsal run on Momentum's account (🔴 real 1-share paper orders; Momentum paused, market open; `PGOPTIONS= python3 kraken-bot/rehearsal.py --live`).
4. Clean-up: single failed read raising alarm rows (needs 2 in a row); PASS lines logged at WARNING; `buy_market` client ids not bot-tagged; dead `bots_state` rows (bot2_spy_qqq, depeg_hunter, forex_gump, kraken_trend); retire the old Navigator forex engine routes (they query missing tables `forex_trades`, `forex_portfolio`).
5. Decisions with Markus: trading-API secret compiled into the dashboard bundle (K1); `ENFORCE_DRAWDOWN_LIMITS` (record-only today).
6. Strategy lock registrations (plan item 17) before 21–22 Nov. Note for Bot 3: the momentum list is heavily one theme (memory/storage/chip equipment) — consider a sector cap.
7. Public Finance page on ddg.limited (built in the DDG-Control repo, see its docs/plans/README.md; this platform stays private; data flows out only through the existing hourly push to `/api/inbound/fleet`). Open question for Markus: public record from 23 Nov (labelled pre-launch) or 1 Jan 2027.

## How to work (Markus's rules)
- Short, simple words. Numbered [ME]/[REPLIT] steps placed right above the copy block they belong to. 🔴 for anything risky, costly or irreversible.
- Never invent facts, numbers, times or behaviour. Say what is unknown. Say where each number came from.
- Always look for a better option B before doing option A.
- Check the date/time before anything market-related. Markus is in Brisbane (UTC+10, no DST).
- Process: Opus builds and opens PRs; Fable reviews, merges and publishes. Finance publishes **only while the US market is closed** (after 21:00 UTC, before 14:30 UTC), with read-only checks before and after.
- Stop and ask Markus before: production DB writes, placing/cancelling orders, changing stops, leverage or strategy rules, anything irreversible.

## Replit (app "DDG - Finance", replId 479b9041-b193-4ed4-a556-02be48b883b3)
- The workspace git remote for GitHub is named **`gh`**. Sync = `git fetch gh` + **normal merge** of `gh/main` (never fast-forward-only; every publish adds a "Published your App" commit).
- Have every Replit task write its answer to `.local/claude_reports/NAME.txt` (git-ignored) and read it with the read-file tool; long answers time out.
- Read-only checks: say READ-ONLY explicitly (SELECT only, Alpaca GET only, no restarts).
- The workspace `DATABASE_URL` is the production database (now read-only by default in the workspace).
- Publishing does not run migrations; new tables are created by code at runtime (additive only).
- After a publish the new runner may wait up to ~15 min for the old runner's leases (status `awaiting_leases`).

## Local tests (sandbox)
- Postgres 16 local test DB: `postgresql://postgres@ep-nameless-hill-localtest:54329/qt_test` (needs `/etc/hosts` alias `127.0.0.1 ep-nameless-hill-localtest`; data dir `/var/tmp/qtpg/data`). Dummy env: `FRED_API_KEY=x NEWS_API_KEY=x GROQ_API_KEY=x`.
- kraken-bot + sleeve_runtime tests from the repo root; trading-platform tests from `trading-platform/`. Tests never touch production (conftest guards).
- Baseline 11 Nov: trading-platform 989 pass / 1 skip; kraken-bot + sleeve_runtime 282 pass.
