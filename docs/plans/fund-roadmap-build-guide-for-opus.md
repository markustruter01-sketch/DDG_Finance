# Build guide for Opus 5.5: Finance first, then the whole-company list

Written by Claude (Fable 5.2), Tue 17 Nov 2026. Part B added the same day. You (Opus 5.5) are the only builder. Fable is NOT in the loop: do not wait for a Fable review, a Fable spec or a Fable decision. Where older notes say "FABLE decides", you propose, write the reason down, and Markus decides.

**Handover (applies to Part A and Part B).** Several Opus sessions on different accounts share this work. Before you start, read `DDG_Control/docs/handover/README.md`. After every merged pull request, add an entry there and mark the order here "DONE, date, PR number". A session can run out of usage without warning: never leave work uncommitted; push a draft pull request that says what is left.

**Two parts, in this order:**
- **Part A — DDG Finance.** The plan you are building is `fund-roadmap-2026-11-17.md` (same folder). Markus agreed to it on 17 Nov 2026 (plan agreed; Defensive stocks replaces Atlas V2 at the lock; lock moves to about 12 to 13 Dec).
- **Part B — the rest of the company.** Fixes from the company audit and builds from the growth plan. Start Part B when Part A's Phase 0 items 1 to 8 are published and the gate (item 9) is running. Nothing may merge in this repo during the gate, so those days are for Part B in the other repos.

Part A dates always win. If Phase 1 work is due, do it before any Part B work.

---

# Part A — DDG Finance

**Roadmap v2 (21 Nov 2026) amends this part: `fund-roadmap-v2-2026-11-21.md`, work orders V2-00 to V2-26. Where the two differ, v2 wins. Its rules are added to "Rules that never bend" below.**

## Read first, in this order
1. `docs/plans/README.md` (how to work, Replit facts, publish rules).
2. `docs/plans/finance-2027-plan.md` (history; see "Status 17 Nov": the old gate is stopped).
3. `docs/plans/fund-roadmap-2026-11-17.md` (the target).
4. `docs/plans/order-path-audit-2026-11-16.md` (findings F1 to F5 and the "must never happen" list).
5. `.agents/memory/MEMORY.md` and any memory file named for the area you are about to touch.

## Rules that never bend
1. No new trading accounts, no new paid services, no new paid data. Free tiers only. Ask Markus before anything that could add a cost (extra AI calls, Replit Agent credits).
2. Account keys never change: `oracle`, `jerome_macro`, `spy_qqq_trend`, `forex_ai`. Names shown to people come from one display-name table.
3. One change per pull request. The GitHub test run (`.github/workflows/tests.yml`) must be green before you ask for a merge. Never weaken or delete a test to get green; if a test is wrong, say why in the pull request.
4. Publish only with the US market closed (after 21:00 UTC, before 14:30 UTC), with read-only checks before and after, as README describes.
5. Stop and ask Markus before: production database writes, placing or cancelling orders, changing stops, gearing or strategy rules, anything that cannot be undone.
6. Never invent a number or a result. Write VERIFIED (with file and line), INFERRED or UNKNOWN.
7. After every work session add a dated "Status" entry to `finance-2027-plan.md`: what changed, what was published, what is unknown, what is next.
8. You review your own work, since no second model does: before asking for a merge, re-read the whole diff once as a hostile reviewer and list in the pull request what could go wrong and how you checked it.
9. **No crypto, full stop (Markus, 17 Nov 2026).** No account, platform or system trades any cryptocurrency: no coins, no crypto pairs, no crypto funds (IBIT, GBTC, ETHA…), in no strategy, shadow, yardstick, Allocator or AI suggestion. The order guard (`trading-platform/core/no_crypto.py`, PR #117) refuses every crypto buy; never weaken or bypass it. Selling the last BTC needs Markus's yes like any order.

## Phase 0 work orders (in this order)
Each line: what to build, where to start looking, and the test that proves it. File paths come from the audit and notes; confirm each in the code before editing.

1. **Publish PR #108.** DONE (published; inside post-check still owed). Pre-check, publish, post-check. Proof: post-check clean, four bots cycling.
2. **Time limits on broker calls (F5).** DONE 17 Nov, PR #116, published. Start: `kraken-bot/alpaca_etf_engine.py`, `trading-platform/execution/broker.py`, `trading-platform/core/oanda_trader.py`. Proof: fake-broker test where a call hangs; the cycle ends with an alarm, no second order.
3. **Crypto exit closes its ledger row.** DONE 17 Nov by hand with the owner-approved BTC sale (row closed, OWNER_KEPT emptied); no crypto remains, so no code path is needed. No crypto anywhere (Markus 17 Nov; the buy guard is PR #117). Start: status entry of 15 Nov (ETH case) and the code that tracks owner-kept holdings. Proof: test that replays a filled BTC stop or sale; the row closes once, no repeating alarm, and BTCUSD leaves `OWNER_KEPT`.
4. **Daily snapshot after the US close.** DONE 17 Nov, PR #120, published. Start: where `bot_daily_returns.equity_close` is written (scheduler). Proof: test with a fixed clock on both sides of the US clock change.
5. **Kill switch per bot.** Start: `trading-platform/core/kill_switch.py`; `.replit` holds `KILL_SWITCH_ARMED="false"`. Build: a failed read from one broker affects only that bot, and only after 3 failed checks in a row. Proof: tests for one bad broker (only that bot pauses), one blip (nobody pauses), and recovery. Arm it only after Markus says yes.
6. **Momentum brake check.** DONE 11 Nov (finance-2027-plan, "ITEM 14 CLOSED": right on both feeds). Recompute the book index, 100-day average and volatility by hand from Alpaca bars for the dates in the 10 Nov note. If the code is wrong, fix it with a test; if it is right, write that down. Do not change the strategy rule here.
7. **Dead code and names.** BUILT 19 Nov: code part #122 (merged 17 Nov) + Navigator #129 (open); display names already one source (`core/bot_registry.py`). `bots_state` rows still need Markus. Delete: short-selling paths, old Navigator forex routes, the 17 Aug one-time job, dead `bots_state` rows (rows need Markus's yes: production write). Add the display-name table. Do NOT rename folders. Proof: test suite green, nothing imports the deleted modules.
8. **Outside heartbeat.** Needs two free monitor URLs from Markus set as `HEARTBEAT_URL_RUNNER` and `HEARTBEAT_URL_API`. Proof: both monitors show a ping.
8b. **Database copies out of GitHub (from the company audit).** `backups/` holds database dump files, including a copy of production. Ask Markus where he wants them kept (his own drive; no new paid service). After he confirms he has them: remove the dump files from the repo, add `backups/*.dump*` to `.gitignore`, keep the manifest text files. Old git history still holds the files; rewriting history needs Markus's yes and is not needed while the repo stays private. Proof: test suite green; `backups/` holds no dump.
9. **Gate.** Five US sessions, nothing merged, daily read-only check written into the plan. Any incident restarts the count. **While the gate runs, work on Part B.**

## Phase 1 work orders: Shadow League (December 2026)
Build on `trading-platform/twins/` and `research_harness/registrations/`. Do not write a second engine.
1. BUILT 19 Nov, PR #130 (open): orders 1, 2, 4 (13 share shadows + 3 yardsticks; forex 3 not yet), 5, 6. Order 3: shared cost model reused from twins; monthly re-measure NOT built. Order 7: PR #131 (open). Registration format: one JSON file per strategy, hashed and dated, same pattern as `TWINS-V2`. Fields: rules, universe, rebalance day, gearing, stops, pass mark, data needed.
2. Strategy interface: a pure function from "prices up to today" to "target holdings". No broker calls, no clock reads inside it. Each shadow is a twin with fake starting money.
3. Cost model, one module used by every shadow: slippage per trade, borrowing interest on geared holdings, AI cost. Start from written estimates; add a monthly job that re-measures slippage from the four real accounts' fills.
4. Build the 16 shadows and 3 yardsticks listed in the roadmap, one pull request per family, each with a test on recorded prices that checks the holdings by hand for two dates.
5. Defensive stocks: the 50 S&P 500 stocks with the lowest price volatility over the past 252 trading days, equal weight, first trading day of the month. Price data only.
6. Momentum changes (weekly brake re-check, 25% sector cap) are a NEW dated strategy version. If sector data would need a paid source, use a free, committed sector list and say so.
7. Leaderboard page in `artifacts/dashboard`: return after costs, worst fall, days in cash, gap to S&P 500, luck check.
8. Lock weekend: registrations merged, Atlas V2's account cut over to Defensive stocks (rehearse on the idle account first, as `kraken-bot/rehearsal.py` does), `RUN_START` in `trading-platform/core/fleet_capital.py` restarted once.
Proof for the phase: all 23 lines write a value on 5 nights in a row; the four mirror twins match their real accounts within the agreed tolerance.

## Phase 2: 2027
No rule changes. Month-end job: freeze, hash, copy to GitHub, one-page report. Quarterly: live versus shadow gap per real bot; a growing gap means fix the cost model going forward, never rewrite history.

## Phase 3 work orders: Allocator in shadow (build Jan to Mar 2027)
1. Regime label once a day from four measurements built from existing price data only: S&P 500 against its 200-day average; 20-day volatility against its own one-year middle value; direction of a Treasury fund over 60 days; share of S&P 500 stocks above their own 200-day average. Four labels: calm up, rough up, calm down, rough down. Register the exact numbers before the first run.
2. Allocation table per label, registered before the first run.
3. Limits in code, tested: 40% cap per strategy, 1.5x total gearing, 15% fall from the high means cash and an alarm.
4. Three shadow funds: equal money; rules Allocator; rules Allocator plus AI reduce-or-skip. The AI version needs Markus's yes first (extra AI cost).
5. No orders from any of this. It only reads shadow results and writes its own shadow record.

## Phase 3a work orders: outside views (Gromen, Bianco) in the AI layer
Read the roadmap's Phase 3a first. Build in this order, one pull request each. Nothing here sends an order.
1. **Ask Markus first:** the exact public sources for each person (links), whether he holds paid subscriptions and what their terms allow, and a yes on the monthly AI cost. Do not guess sources. Do not scrape anything behind a login or paywall.
2. **Source list:** one committed file listing each allowed source (person, link, type). The collector reads only what is in this file.
3. **Collector:** a daily job (after the US close) that fetches new public items from the list. Store: person, date published, link, title, and a hash of the fetched text for de-duplication. Do not store the full text. A failed fetch files one alarm per source per day at most and never blocks trading jobs.
4. **View cards:** one AI call per new item producing a fixed JSON card: person, date, topic (rates, dollar, oil, shares, gold, bonds, other), direction (up, down, neutral, unclear), strength (1 to 3), time frame, one-sentence summary in our own words, link. Validate the JSON; reject and log anything else. Crypto topics are stored as `other` with no direction and are never passed to the council as a suggestion.
5. **Current-view table:** latest card per person per topic, with a weight that halves every 30 days (register the number). A newer card on the same topic replaces the old one.
6. **Council input:** the AI council's prompt for shadow fund (c) gets the current-view table. Its written note must list each view it used and say agree or disagree with a reason. Test: a note with no such list is rejected.
7. **Limits, tested:** the council's output type stays "reduce or skip". A test proves that no card content can raise a position, raise gearing, move a stop or clear a pause.
8. **Scoreboard:** for each card, record the market move over the card's time frame (from price data we already have) and whether the view was right. Show per person, per topic hit rates on the dashboard next to the leaderboard. Append-only.
9. **Registration:** hash and date the source list, card format, decay number and council prompt before fund (c) starts in April 2027. Changing any of them later is a new dated version.
Proof for the phase: 20 days of cards with no missed day; every fund (c) council note cites its views; the limits test is green.

## Front-end work orders (designs approved by Markus 20 Nov 2026 06:06 Brisbane)
Approved mock-up (2 PC screens, 4 iPhone screens, Night Glass v5 unchanged): https://claude.ai/artifact/JKWUEVj1QSBgY6pNCrWhVH. One PR each, tests and `tsc` green, front end only, published with the US market closed.
1. **PC:** nav Home · League · Forex · Research (Bench renamed) · Controls · Paper. Home keeps hero, chart and account cards and adds three bottom cards: League top 5, Allocator (a) vs (b) with tonight's mood, Record keeping (decision logs, month frozen, trade costs vs model, outside monitor). League page: family filter, one table for every line, detail panel for the picked line (chart vs S&P 500, rule in plain words, pass bar).
2. **Phone (Apple Human Interface Guidelines):** bottom tab bar Home · League · Forex · More; large titles; touch targets 44 pt or more; grouped lists that push a detail screen with Back; League filters as a scrolling chip row; Pause/Resume only on Controls behind a confirm sheet.
3. **Public Finance view on ddg.limited (Markus 20 Nov 06:06):** on ddg.limited's Finance section, a visitor picks **PC view** or **Phone view**; a full-screen pop-up opens showing the Finance app as it looks on that device — a **visual, read-only** copy: no controls, no buttons that act, nothing that can pause, resume or change anything.
   - Build it in DDG-Control (`artifacts/ddg-control/site/`), not by exposing the Finance dashboard: the Finance dashboard bundle holds the trading-API secret (K1, status 13 Nov) and must never be made public.
   - Data: only what Finance already pushes to DDG Control each hour (`/api/inbound/fleet`), plus any new league/Allocator fields added to that push in the same PR (figures only: no keys, no account numbers, no order ids). No call from the public page to the Finance API.
   - Same Night Glass look and the same layouts as items 1 and 2: PC view in a desktop-shaped frame, phone view in a phone-shaped frame (no fake status bar). Close button, Escape key, and focus trapped inside the pop-up while open (accessibility).
   - Wording: paper money, not financial advice, not open to outside money; before 1 Jan 2027 it says the public record starts then (Markus 12 Nov). Markus approves the words before publish.
   - Done when: both views open from ddg.limited/finance on a phone and a PC, show the latest pushed figures, and an outside check confirms the public page makes no request to the Finance API.

## Phases 4 and 5
Do not start them. In January 2028 produce the scorecard exactly as the roadmap's Phase 4 defines it, including the case "nothing passed". Real money is Markus's decision alone.

## If you are stuck
Stop, write what you know and do not know into the plan's Status entry, and ask Markus one clear question with your recommended answer.

---

# Part B — the rest of the company

## Read first
1. `DDG_Control/docs/plans/README.md` (company map, how to work with Markus).
2. `DDG_Control/docs/plans/company-audit-2026-11-17.md` (what is wrong and why).
3. `DDG_Control/docs/plans/growth-plan-2026-11-17.md` (where the money is and why).
4. The start-here file of the repo you are about to touch: `DDG_Coffee/docs/plans/README.md`, `DDG_Hypest/docs/HYPEST-BUILD-PLAN.md`, and each repo's `AGENTS.md` or `replit.md` if present.

## Rules for Part B
1. **Four repos only**, all under GitHub user `markustruter01-sketch`: `DDG_Control`, `DDG_Coffee`, `DDG_Hypest`, `DDG_Finance`. (Renamed and made private by Markus on 22 Nov 2026: `DDG-Control` → `DDG_Control`, `cattle-dog-coffee` → `DDG_Coffee`, `ddg-hypest` → `DDG_Hypest`, `quant-terminal` → `DDG_Finance`. GitHub forwards the old names; never create a new repo with an old name.) Never open, clone or read any other repo on that account. They are not DDG.
2. Each repo's own rules win over this list. If they clash, stop and ask Markus.
3. One change per pull request. Checks green before you ask for a merge. Never weaken a test.
4. **Name no charity in anything the public can see** until Markus says a partnership is signed. The wording is "animal charities".
5. Never put a price, a total or a discount in the browser's hands. The server works out all money.
6. Never print, commit or paste a secret, a customer's details or a database address.
7. **Stop and ask Markus before:** new or changed Stripe products or prices, anything on a live Stripe account, production data changes, any new service or cost, any words about law, health, money or charity that the public will read, and any publish of Cattle Dog Coffee that changes the database (he must press Publish on the Replit website for those).
8. Replit Agent tasks and AI calls cost money. Batch them. Have each Replit task write a short report to `.local/claude_reports/NAME.txt` and read that.
9. **Do not build a kit before a client has paid a deposit.** Do not build Hypest features before the demand test says to.
10. Simple English in every note, page and pull request. Write VERIFIED, INFERRED or UNKNOWN.
11. After each session: add a dated status entry to that repo's start-here file, and tick the order in this list (add "DONE, date, PR number").

## State on 17 Nov 2026 (VERIFIED by Fable)
- **Done, do not redo:** charity wording changed to "animal charities" on the coffee store and ddg.limited (coffee PR #15, Control PR #87); ddg.limited says "Raised", not "Given", and "four businesses"; Hypest tells search engines not to list it (PR #44); coffee postage by weight, admin postage screen, delivery notes, `/admin` path (coffee PRs #12 to #14).
- **Live:** ddg.limited and Hypest were published on 17 Nov after those changes (check the status entries for the result).
- **Not live:** Cattle Dog Coffee. The live store still ran the old build on 17 Nov (its `/api/config` had no `shipping` field). The database changed, so only Markus can publish it, on the Replit website. Until he does, nothing from coffee PR #12 onward is live, including the charity wording.
- **Some audit items came from notes and may be out of date.** The coffee API already has `lib/refunds.ts`, `lib/rate-limit.ts`, `lib/test-hardening.ts` and `routes/charity-payouts.ts`, and the store has `CharityPayoutsPage.tsx`. Read the code before you build anything.
- **How paths are written below:** in `DDG_Control`, `DDG_Coffee` and `DDG_Hypest`, a path starting `routes/` or `lib/` means under `artifacts/api-server/src/`. The two exceptions are the shared packages at the repo root: `lib/db` and `lib/pricing-core`. Confirm every path in the code before editing; INFERRED until you have opened the file.

## Decisions Markus made on 17 Nov (VERIFIED, his words in chat)
- The growth plan is approved. Build is the main effort. This means effort and order of work. **It does not mean a big new system. Build nothing that is not a numbered order in this list.**
- **No talking and nobody he knows.** Clients come only in writing, from strangers who have shown they want a build. Never contact, list or suggest anyone Markus knows or deals with (friends, family, Coffee Alliance, coffee customers, market contacts).
- **You never send a message, proposal or email yourself.** You find, draft and build. Markus presses send. He creates every account (they need his identity).
- Prices: listed prices stay. First five clients: website $1,300, store $6,500, platform or app $9,750, AI assistant $3,250.
- DDG has Markus's full-time week. He already makes social content.
- Open: whether B2.1 (coffee gifts) goes before the Finance fixes. Ask him first thing.

## B0 — Client engine. Do this first in Part B, before B1.
Read the growth plan, section 3, "How to get clients". Small pieces only.

**B0.1 Founding offer on ddg.limited.** Start: `artifacts/ddg-control/site/content.ts`, `Build.tsx`. Show "first five clients" prices beside the listed ones, and a count of places left that Markus sets by hand. Markus approves the words.

**B0.2 Written-only intake.** Start: `Build.tsx`, `routes/build.ts`, `routes/quotes.ts`. The form collects enough to quote without a call (what the business does, pages or features wanted, examples they like, deadline, budget band). The page says plainly: "We work in writing. No calls needed." Then B2.3 (instant reply and draft quote).

**B0.3 Marketplace pack.** No code. Write `DDG_Control/docs/sales/`: an Upwork profile draft, three proposal templates (website, store, AI helper), and a one-page check of which Australian job boards still take web jobs and what each charges (VERIFIED from each site's own pages, with links). Markus creates the accounts.

**B0.4 Proposal helper.** When Markus pastes a job post into chat, you return: fit (yes or no, one line why), a written proposal, and a small mock-up page he can link. Skip posts that demand calls. No scraping of sites that forbid it.

**B0.5 Signal list for mock-up emails.** Only after B0.1 to B0.4. Apply the two-signal filter in the growth plan exactly. Ten businesses at most per batch, strangers only, public information only. For each: the signals with links, a mock-up, a draft email with DDG's name, ABN and an opt-out line. Markus sends. Ask him to clear the wording with his lawyer before the first batch.

**B0.6 Channel scoreboard.** In Control (`pages/Clients.tsx`): per channel, sent, replies, paid jobs, AI cost, Markus's minutes. Show the stop rule: no paid job after 40 tries means pause.

## Jobs only Markus can do (do not wait on these; remind him in each status entry)
- Press Publish for Cattle Dog Coffee on the Replit website.
- 2-step login on GitHub, Replit, both Stripe accounts, the domain company, Google, brokers, bank.
- Lawyer: DDG Build contract; Hypest terms, privacy and waiver. Broker: insurance. Accountant: GST and company structure.
- Turn on daily database backups in Replit for Coffee and Hypest.
- Create free uptime monitors (you give him the addresses, order B1.11).
- Sign the charity agreement; pay the charity in $100 lots.
- Confirm prices for kits and founding clients.

## B1 — Safety net (from the audit). Do these first, in this order.

**B1.1 Security headers on ddg.limited and the coffee store.**
- Repos: `DDG_Control`, `DDG_Coffee`. One pull request each.
- Start: copy the approach in `DDG_Hypest/artifacts/api-server/src/lib/security-headers.ts`. Add it in each repo's `artifacts/api-server/src/app.ts`. Turn off the "X-Powered-By" header.
- Care: start the content policy in report-only mode. ddg.limited draws a 3D scene and loads a Replit script (`i.replit.com/script.js`); the store redirects to Stripe. The web pages themselves are static files served by Replit, not by the API: check each `artifacts/*/.replit-artifact/artifact.toml` for a way to set headers on them. If there is none, write UNKNOWN and protect the API only.
- Proof: a test that the headers are present on the health route (`/api/healthz`); in the preview the home page, checkout redirect and admin still work.

**B1.2 Automatic type check for DDG Control.**
- Start: copy `DDG_Coffee/.github/workflows/typecheck.yml`.
- Proof: green on its own pull request.

**B1.3 Privacy page for ddg.limited.**
- Start: `artifacts/ddg-control/site/Site.tsx` (routes and footer), `content.ts` (words), `Build.tsx` (the form already says "We only use your details to reply").
- Build: one short page: what the Build form collects (name, email, project notes), why, who sees it, how to ask for deletion, how to contact DDG. Link it in the footer and under the form.
- Ask first: Markus approves the words.

**B1.4 Coffee legal pages catch up.**
- Start: `artifacts/store/src/components/store/PrivacyPolicyContent.tsx`, `ShippingReturnsContent.tsx`.
- Build: privacy page lists delivery instructions and the "dog in the yard" answer (asked on the Stripe checkout page, saved on the order). Shipping page says postage depends on the total weight; do not hard-code the amounts (they are set in admin). Update both "Last updated" dates.
- Ask first: Markus approves the words.

**B1.5 Real sitemap for the coffee store.**
- VERIFIED 17 Nov: `/sitemap.xml` returns the home page. `artifacts/store/public/robots.txt` exists.
- Build: `artifacts/store/public/sitemap.xml` listing the public pages; point to it from `robots.txt`.

**B1.6 Refunds made inside Stripe.**
- Notes say a refund done in Stripe does not update the order. `lib/refunds.ts`, `routes/stripe-webhook.ts` and `lib/stripe-webhook-events.ts` exist: read them and write down what is and is not handled before building.
- Build only the gap: a refund event marks the order refunded, and the bag count and charity total go down to match.
- Proof: a test in the style of `lib/test-order-money.ts` using a recorded event.
- Ask first: adding an event to the live Stripe webhook is Markus's click.

**B1.7 Coffee hardening list.**
- Start: the open items in `DDG_Coffee/docs/plans/README.md`; then `lib/rate-limit.ts` and `lib/test-hardening.ts` to see what already exists.
- Build: one pull request per item still open (checkout rate limit, which sites may call the API, safe waitlist export, admin login code scope).

**B1.8 One source for coffee prices.**
- Start: `lib/pricing-core/src/index.ts` (the only place sums belong), `artifacts/store/src/App.tsx`, `artifacts/store/src/lib/types.ts`.
- Build: the shop page shows what `pricing-core` and the API say; it re-computes nothing.
- Proof: `lib/test-pricing.ts` passes; no second copy of a postage or discount formula in `artifacts/store`.

**B1.9 One GST meter for the whole company.**
- Why: the $75,000 line counts all DDG sales together. The coffee admin meter counts coffee only.
- Start (DDG-Control): `artifacts/ddg-control/src/pages/Money.tsx`, `artifacts/api-server/src/routes/finance.ts`, `routes/overview.ts`, `lib/cdc-store.ts`, `lib/hypest-store.ts`, `routes/quotes.ts`.
- Build: last 12 months of sales, all businesses added, against $75,000, plus a simple forward look (last 3 months times 4). In the coffee admin (`artifacts/store/src/components/admin/DashboardScreen.tsx`) add the words "Coffee only. Whole company: see DDG Control."
- Proof: a test with fixed inputs, in the style of `test-finance-cdc-summary.ts`.

**B1.10 Charity: "Raised" and "Paid", in $100 lots.**
- Start (coffee): `routes/charity-progress.ts`, `routes/charity-payouts.ts`, `artifacts/store/src/components/admin/CharityScreen.tsx`, `components/store/CharityPayoutsPage.tsx`, `Hero.tsx`. Read first: payout recording already exists.
- Build: (a) the admin shows a clear prompt each time the unpaid amount reaches another $100; (b) the store and ddg.limited show "Paid so far" beside "Raised". For ddg.limited: Coffee's `routes/ddg.ts` adds the paid total to its summary; Control's `lib/cdc-store.ts` reads it; `routes/public.ts` adds it to `/api/public/summary`; `site/Site.tsx` shows it.
- Leave the admin-only placeholder text alone. Rule 4 applies to everything public.

**B1.11 Uptime addresses and runbooks.**
- Build: in each repo, `docs/runbooks/incidents.md` (site down, wrong charge, data leak, bot misbehaving; five lines each: how you notice, first step, who to tell, how to undo, where the logs are) and `docs/runbooks/restore.md` (how to bring the database back from a backup).
- Give Markus the exact health addresses to watch. All three APIs answer at `/api/healthz` (VERIFIED in `routes/health.ts` of each repo, 17 Nov).

**B1.12 Bot keys.**
- Start (DDG-Control): `artifacts/api-server/src/lib/bot-keys.ts`, `routes/bots.ts`, `routes/auth.ts`.
- Build: a table in the notes of what each key (FREYA, TYR, HEIMDALL, PLUTUS, DDG_BOT_KEY) may call. Narrow each key to its job. Each key can be switched off alone.
- Proof: one test per key that a route outside its job answers "not allowed".

**B1.13 Hypest launch checklist.**
- Build: `DDG_Hypest/docs/LAUNCH-CHECKLIST.md`: lawyer-reviewed pages replace the drafts in `artifacts/hypest-web/src/pages/legal-page.tsx`; robots tag in `artifacts/hypest-web/index.html` back to "index, follow"; `STRIPE_LIVE_APPROVED`; own domain; support mailbox working; insurance. You write the list. Markus decides each line.

## B2 — Money builds (from the growth plan). After B1, in this order unless Markus changes it.

**B2.1 Coffee gifts. DATE-SENSITIVE: live by Mon 30 Nov 2026 or leave it for 2027. Ask Markus if it should jump the queue.**
- Start: `artifacts/api-server/src/routes/checkout.ts`, `lib/delivery-notes.ts`, `artifacts/store/src/components/store/CartDrawer.tsx`, `SubscriptionPlansPage.tsx`.
- Build, smallest version first: a "This is a gift" choice that adds a gift-note field at checkout (two custom fields are used today; confirm Stripe's limit in its documentation before adding a third) and shows the note on the order in admin. Then, only with Markus's yes (new Stripe prices): pre-paid 3 and 6 month gift subscriptions.
- Proof: test checkout in the Stripe sandbox shows the field; the note is saved on a paid test order.

**B2.2 Kits on ddg.limited.**
- Start: `artifacts/ddg-control/site/content.ts` (the services list and `CARE`), `Build.tsx`.
- Build: three kits (Shop, Control room, Front desk), each with a set-up price and a monthly price. Custom prices stay.
- Ask first: Markus confirms every price and every sentence.

**B2.3 Enquiry: instant reply and a draft quote.**
- Start: `artifacts/api-server/src/routes/build.ts`, `routes/quotes.ts`, `lib/email.ts`, `test-quotes.ts`, `artifacts/ddg-control/src/pages/Clients.tsx`, and `docs/plans/ddg-build-plan.md` for what is already built.
- Build: a new enquiry sends the person a plain "we got it" email and creates a draft quote in Control. Nothing with a price goes to a client without Markus's click.
- Proof: `test-quotes.ts` extended; one test enquiry in the preview.

**B2.4 Case studies.**
- Build: three short pages on ddg.limited: the coffee store, DDG Control, the Finance platform. Facts only. Blur any email address or private number in screenshots.

**B2.5 Profit per bag and per plan.**
- VERIFIED: Control already estimates coffee profit (`artifacts/api-server/src/lib/cdc-store.ts`, `test-cattle-dog-profit.ts`).
- Build: show profit per bag size and per subscription plan on Control's Money page, with a line for Markus's packing time (he types the hours).

**B2.6 Scoreboard in Control.**
- Start: `artifacts/ddg-control/src/pages/Home.tsx`, `routes/overview.ts`, `routes/metrics.ts`.
- Build: four numbers. Monthly repeating income (coffee subscriptions + kit and care plans + Hypest members). Cash in this week, by business. Markus's hours this week, by business (he types them). AI and hosting cost this month (he types them).

**B2.7 Partner links for rescue groups.**
- Ask first: Markus has the written agreement wording and has checked the fundraising rules (audit, section 3.1).
- Start (coffee): `lib/db/src/schema/`, `artifacts/api-server/src/lib/schema-ensure.ts` (the pattern for new tables), `routes/checkout.ts`, `routes/stripe-webhook.ts`, `routes/admin.ts`.
- Build: a `partners` table (name, code, cents per bag, active). A link with the partner's code is remembered in the cart; the browser sends only the code, the server looks up the amount. The code is saved on the Stripe session and the order. Admin screen: bags and amount owed per partner. Public page explaining the programme with an enquiry form.
- This changes the database: Markus publishes on the Replit website.
- Proof: tests for a valid code, an unknown code, an inactive partner, and a refund.

**B2.8 Friend codes, review request, parcel card page.**
- Start: `lib/loyalty.ts`, `routes/promo-codes.ts`, `lib/email.ts` (read what exists first).
- Build: a friend code that gives both people a discount once; an email asking for a review ten days after dispatch; one page for the QR code on the parcel card with three links (Hypest waitlist, the novel when ready, the friend code).

**B2.9 Office plan page.**
- Build: a page for a standing monthly order of 1 kg bags with an enquiry form. No new payment flow until an office says yes.

**B2.10 Hypest demand test. No new training features.**
- Start: `DDG_Hypest/artifacts/hypest-web` and `docs/HYPEST-BUILD-PLAN.md`.
- Build: three public "coming soon" pages (service fitness tests; train for a date; shift workers), each with a waitlist form and a clear "yes, email me" tick. Only these three pages may be listed by search engines; the app stays hidden. Count sign-ups and visits per page where Markus can see them.
- Then, in Stripe test mode only: a yearly plan. And measure AI cost per member (start in `artifacts/api-server/src/coaching` and `billing`).
- Ask first: the words on each page. No live payments.

**B2.11 One email list.**
- Build: a sign-up box with a "yes, email me" tick on ddg.limited, the coffee footer and the Hypest waitlist. Save the date and the source. Every email carries an unsubscribe link.
- Ask first: before adding any mail-sending service.

**B2.12 Kit 1 "Shop". Only after a client has paid a deposit.**
- Start: `DDG_Coffee`.
- Build: move the brand name, colours, words, product list, postage rules and charity text into one settings file. Write `docs/NEW-SHOP.md`: how to stand up a copy for a client (new Replit app, new database, the client's own Stripe keys in Replit Secrets, their domain). Clients never share a database.
- Proof: a demo shop with a made-up brand runs from the same code.

**B2.13 Shared base. After Kit 1.**
- Build: one small package with the security headers, health route, rate limit, GitHub check file and start-here template. Move each repo onto it one at a time.

**B2.14 Kit 3 "Front desk". Only after a client asks and pays.**
- Build: web chat and email first. A hard cost cap per client. Each client's data kept apart.

**B2.15 Monthly numbers post.**
- Build: a job that drafts a short public post from `/api/public/summary` for Freya. Markus approves before anything is posted.

**B2.16 Novel sale page. Only when Markus says the book is ready.**
- Build: pay, then an emailed download link that expires. Reuse the coffee checkout. No new service.

## If you are stuck on Part B
Same as Part A: stop, write VERIFIED / INFERRED / UNKNOWN in the repo's status entry, and ask Markus one clear question with your recommended answer.
