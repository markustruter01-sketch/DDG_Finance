# DDG Finance — start here (for any Claude picking this up)

Repository: `markustruter01-sketch/DDG_Finance` (named `quant-terminal` until 22 Nov 2026; GitHub forwards the old name). Private. Replit app "DDG - Finance".

Last updated: Thu 19 Nov 2026 ~17:00 Brisbane (UTC+10) by Claude (Opus 5.5): old plan archived, stale "Live state" and "Next work" sections replaced by pointers (one source each).

Read in this order:
0. `fund-thesis-2027.md` — **start here: what the platform is, why, and what we expect.** Written by Claude (Fable 5.2) 21 Nov 2026; hashed into the lock record 12–13 Dec and never edited after (corrections are dated notes at the end). Shown to the public as the research paper.
1. This file (how to work, Replit facts, publish rules).
2. `fund-roadmap-2026-11-17.md` — AGREED (Markus 17 Nov): the road from today to a self-running fund (fix window, Shadow League, Allocator in shadow, staged real money). **This is the target.**
2a. `fund-roadmap-v2-2026-11-21.md` — **amends the roadmap; wins where they differ.** The macro-led fund: four layers, seven funds, work orders V2-00 to V2-26. Markus said yes 22 Nov 2026 (see the status log).
2b. `macro-research-2026-11-21.md` — background; not a rule. No strategy, fund, table or AI prompt reads it (roadmap v2, rule 10).
3. `fund-roadmap-build-guide-for-opus.md` — the work orders, phase by phase, each marked DONE with date and PR when finished. **This is the "next work" list.** Part B is the whole-company build list, worked while the Finance gate runs.
4. `finance-2027-plan.md` — the status log. **The latest Status entry (bottom of the file) is the live state.** Add a Status entry after every work session.
5. `order-path-audit-2026-11-16.md` — every code path that can place an order, findings F1 to F5, and the "must never happen" list.
6. `forex-council-2027-registration.md` and `ai-twins-2027-registration.md` — registered forward tests (do not edit; new versions are new dated files).
7. `archive/` — superseded documents, kept unchanged for history. Do not work from them.

No secret values are in these files or anywhere in this repo. Secrets live in Replit Secrets only (names may be mentioned, never values).

## What DDG Finance is
In-house algorithmic trading platform (paper only). 3 Alpaca paper accounts (cap: 3, all in use) + 1 OANDA practice account. Goal: an honest public track record. Dates (roadmap): fix window, then one 5-session gate (target Mon 7 – Fri 11 Dec 2026), strategy lock about Sat 12 – Sun 13 Dec, public record from 1 Jan 2027, runs all of 2027. Not open to outside money, not financial advice.

| Account (bot_id) | Name on dashboard | Strategy now | At the lock (roadmap Phase 1) |
|---|---|---|---|
| oracle | Atlas | FLEET-V1-F1 (65% S&P/Nasdaq trend up to 1.5x + 35% bonds/gold/commodities/dollar trend) | Atlas (trend, 1.5x) |
| jerome_macro | Atlas V2 | FLEET-V1-C1 (S&P/Nasdaq trend up to 1.5x). No crypto (BTC sold 17 Nov) | Defensive stocks replaces it |
| spy_qqq_trend | Momentum | MOMO-V2 (top 50 S&P 500 stocks by 12-1 momentum, monthly, trend brake) | Momentum (fixed brake, weekly re-entry, 25% sector cap) |
| forex_ai | Forex | 3-AI council vote, 0.5% risk/trade, max 4 trades | Forex AI council |

🔴 NO CRYPTO, FULL STOP (Markus 17 Nov): no account or system trades any crypto. Buys are refused in code (PR #117). No new trading accounts or paid services.
Tests run on GitHub for every pull request and on main (`.github/workflows/tests.yml`). Green before any merge.

## How to work (Markus's rules)
- Short, simple words. Numbered [ME]/[REPLIT] steps placed right above the copy block they belong to. 🔴 for anything risky, costly or irreversible.
- Never invent facts, numbers, times or behaviour. Say what is unknown. Say where each number came from.
- Always look for a better option B before doing option A.
- Check the date/time before anything market-related. Markus is in Brisbane (UTC+10, no DST).
- Process: Opus builds, reviews its own diff as a hostile reviewer and opens PRs; Markus merges. Finance publishes **only while the US market is closed** (after 21:00 UTC, before 14:30 UTC), with read-only checks before and after.
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
