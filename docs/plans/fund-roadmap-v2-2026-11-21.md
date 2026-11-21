# DDG Finance roadmap v2: a macro-led fund for 2027
## With build orders for Opus 5.5

Written by Claude (Fable 5.2), Sat 21 Nov 2026, 11:30 Brisbane, at Markus's request (11:10 and 11:14 Brisbane). Amended about 12:30 Brisbane the same day, at his requests (11:36, 12:00, 12:05): the backdrop was brought up to Friday's close (2.2), and the long view and the thesis were added (section 2.4, decisions D12 to D14, rule 10, orders V2-18 to V2-23). D14 holds three changes to the build itself that the research suggested. Amended again about 13:30, after his questions at 13:08 and 13:14: how the fund hedges and what that costs, a walk-forward fund as the AI's rule-based rival, and the old walk-forward check that still runs (section 2.5, decisions D15 to D17, orders V2-24 to V2-26). The same pass found and filled a gap in V2-08: its look-backs had no history to use in January (the warm-up).

**Status: PROPOSED.** It becomes the plan when Markus says yes to section 4. It amends `fund-roadmap-2026-11-17.md` (agreed 17 Nov). Where the two differ, this file wins. Everything else in the 17 Nov roadmap, and every "Rule that never bends" in `fund-roadmap-build-guide-for-opus.md`, stays.

**How this was made.** Read-only review of `quant-terminal` at commit `2447d4a` (main after PR #167, 21 Nov 10:51 Brisbane), the research ledger and the status log. Nothing was run: no test, no backtest, no model call. The long view rests on web research done the same day and written up in `macro-research-2026-11-21.md`. What its author expects of the platform is in `fund-thesis-2027.md`. For section 2.5 the full git history was fetched, read-only, at about 13:20; main was then at `ceccb8a` (PR #171). This session could not write to GitHub, so order V2-00 puts the three files in the repo.

**Not advice.** This is a plan for building and testing software on paper money. It is not financial or tax advice. No step can promise a profit.

**Marks.** VERIFIED = read in the code or ledger at `2447d4a`. PROPOSED = a rule or number chosen here, not tested, needs Markus's yes. UNKNOWN = could not check.

**Left out on purpose** (already built at `2447d4a`; do not rebuild): Phase 0 items 1 to 4, 6, 7 and 8b; the Shadow League (17 shadows, 3 yardsticks), its leaderboard, month-end freeze and cost check from fills; Allocator funds (a) and (b); the AI twins and AI veto twins; overnight financing in the forex twins; the one-currency-cap forex line; Markus's own pretend account; the dashboard redesign.

---

## 1. The end state

On 31 December 2027 DDG Finance holds:

1. **A full-year record that cannot be quietly changed** (append-only, hashed, frozen each month) for the 4 real paper accounts, Markus's own account, about 25 rule strategies, 8 yardsticks and 7 funds built from them.
2. **Answers, after costs, to five questions:**
   - Which fund, if any, is worth real money? Judged on a replay of history plus 2027, not on one year alone.
   - Did the macro layer add anything over a plain risk-balanced mix?
   - Did the outside views (Gromen, Bianco) and Markus's own views add anything?
   - Did the AI add anything after its bill, and did it beat a plain walk-forward rule given the same powers (D16)?
   - What did each protection cost, and what did it save (D15)?
3. **The same answers after tax and in Australian dollars,** against simply holding an index fund.
4. **An engine with a year of clean nights,** so real money in 2028 is a small step.
5. **The long view on record** (section 2.4): slow gauges of debt, money and conflict; four daily flags; every result also shown after inflation and beside a "just hold gold" yardstick; and our rules tested in eras unlike the last 20 years (1929–49, 1966–82, Japan after 1989). So the 2027 result is read against more than one kind of market. Context only: no rule reads it.

The shape of the fund: **macro data decides how much goes to each kind of asset; rule strategies decide what is held inside each kind; views and AI sit on top and are measured one layer at a time.**

---

## 2. What we already know

### 2.1 Our own registered tests (VERIFIED, `research_harness/ledger.jsonl`)

| Registered test | Dates | Result after costs | S&P 500, same dates |
|---|---|---|---|
| FLEET-V1-F1 (today's Atlas) | 2011–2020 | 8.59% a year, worst fall −15.7%, Sharpe 0.77. Failed 2 of 5 bars ("return at least the index", "Sharpe 0.10 above the index") | 13.65% a year, −33.7%, Sharpe 0.80 |
| FLEET-V1-C1 (share-trend core) | 2011–2020 | 11.74% a year, −24.6%, Sharpe 0.72 | as above |
| FLEET-V1 S2 (bonds, gold, commodities, dollar trend alone) | 2011–2020 | 1.98% a year, −8.7%, Sharpe 0.39, moves against the S&P (correlation −0.14) | as above |
| Same three, later look | 2021–Oct 2026 | F1 12.2%, −16.2%, 0.75 · C1 15.08%, −26.8%, 0.68 · S2 5.86%, −3.7%, 0.61 | 14.62% a year, −24.5%, 0.71 |
| GEAR-V1-G4 | 2021–Oct 2026 | 18.05% a year, −24.5%, 0.76. Failed (fall not smaller) | 15.18%, −24.5%, 0.74 |
| TREND-V1-B | 2021–Oct 2026 | 3.59% a year, −7.4%, Sharpe 0.07 | as above |
| FX-BT1 (forex trend baseline) | Nov 2008–Oct 2026 | −1.08% a year, −33.9%, Sharpe −0.02 | — |

Sharpe here is return over T-bills divided by volatility, as the ledger reports it. FX-BT1's figure is before T-bills are taken off.

**What it means.**
- These strategies gave about the index's return for the risk taken, with smaller falls. None beat the index outright. The forex trend baseline lost money over 18 years.
- So no single line will carry the fund. The gain has to come from mixing things that do not move together, from the macro layer, and from smaller falls.
- A fund Sharpe near 1 after costs would be a very good result. 1.5 needs more independent sources than exist today. (My estimate, not a forecast.)

### 2.2 The backdrop at the close on Fri 20 Nov 2026 (sources in section 11)

- Shares: the S&P 500 closed at 6,910, down 3.7% on the day and 8.6% on the week, its seventh fall in a row. It is more than 10% below its 6 October record. The Nasdaq is now down for the year. AI shares lead the selling.
- Oil: Brent was about US$96 a week earlier, after two weekly falls from above US$100. A US–Iran war since February has repeatedly shut the Strait of Hormuz.
- Gold: about US$3,515, a 14.5-month low and roughly a third below its early-2026 peak. Central banks bought 321 tonnes in the third quarter, the most since late 2024. The dollar is near a one-year high.
- Inflation and rates: prices rose 3.7% in the year to September and an estimated 3.9% to 4.0% to October. The central bank's rate is 3.75% to 4.00% and a rise in December is fully priced. The 10-year yield is 4.93% after weeks above 5%. The yield after inflation is about 2.7%, the highest since 2008.
- Debt: a US$2.0 trillion deficit in the year to September, and a record for any October last month.
- Shares, gold and bonds have fallen together for most of the autumn. Bonds have not cushioned shares.

### 2.3 Markus's view, and how the plan treats it

Markus (21 Nov): shares will have a very hard time in 2027; gold and oil will do very well.

Parts of the backdrop fit that view: inflation pressure, an energy shock from a war, and shares in a correction. Parts do not, today: gold is at a 14.5-month low, about a third below its peak, and oil has come off its high. The reason matters. The central bank is raising rates, not printing, and gold fell the same way in 1980–82 while inflation was still high. A view says "hold it now". A trend rule says "hold it when it turns". Nobody can know which is right.

So the plan does not bet the platform on the view. It makes sure the view is **held, measured and able to pay** in three ways:

1. **Markus's own account** (VERIFIED: `trading-platform/twins/human.py`; the 2027 record opens at the 31 Dec 2026 close; gold, oil and commodity funds are in its list). He holds the view directly, with a reason on every trade.
2. **Lines that profit if he is right:** gold trend (exists), oil trend, a hard-assets basket (new, V2-04). Fund (m) moves to 45% hard assets when the macro data reads "inflation up, growth down" (V2-09).
3. **His views as scored cards,** beside Gromen's and Bianco's (V2-10, V2-11).

### 2.4 The long view, and how the plan treats it

Markus (21 Nov, 11:36): we may be at the end of a cycle of about 100 years. The next 10 years may look like the last 500, not the last 20. Keep that in the platform's reading of the macro picture, **as understanding, not as a driver of investment.**

The research is in `macro-research-2026-11-21.md`: Dalio's Big Cycle, the independent long records behind it, what forecasters expect and what each gains from saying it, and my own reading with odds (its Part 6). In short:

- **The worry is fair.** The last 20 years had falling rates, bonds that cushioned shares, quiet inflation, US shares beating the world, and exchanges that stayed open. Over 100 years or more, none of that is normal. Our rebuilt price history starts in 1985 (VERIFIED: `research_harness/recon/reconstruct.py`), so nothing we run has been through 1929–49 or 1966–82.
- **The pressures Dalio lists can be measured, and they are high:** US debt about to pass its 1946 record, central banks holding more gold than US government bonds, a record count of conflicts.
- **Today the US is tightening, not printing.** History says that road usually ends when the pain becomes political. It also says hard assets can fall a long way before it does: gold is down a third from its peak.
- **The record does not say hard assets always win.** Over 125 years shares beat gold in every country with a full record. Gold lost about 85% of its buying power from 1980 to 2001. A debt crisis can begin with falling prices, when cash and bonds win.
- **What worked in every era:** holding things that do not move together, following trends, and staying able to trade. The fund is already built that way.
- **Nobody has a date.**

So nothing in sections 3 to 9 becomes a bet on the long view. Four things are added, all for reading and testing (rule 10 in section 6):

1. A panel of slow gauges, with every result also shown after inflation and beside a "just hold gold" yardstick (V2-18).
2. Four daily flags for the kind of day the last 20 years rarely had (V2-19).
3. Our rules run through other eras: 1929–49, 1966–82, Japan after 1989 (V2-20, V2-21).
4. Drills for a world that breaks: a closed market, a frozen fund, a long outage (V2-22).

**Separate from the long view: three gaps in the build (decision D14).** The same research showed things that are simply missing or mislabelled, whatever the next decade brings:

1. **No inflation-linked bonds anywhere in the fund.** They are the most direct protection against inflation, and US ones now pay about 2.7% a year on top of inflation, the most since 2008. The fund has gold, oil and commodities for that job and nothing with a contract behind it.
2. **A "defensive" bucket that cannot always defend.** D-RP always holds bonds (VERIFIED: `RP_LINES` in `research_harness/league/families.py`, no trend test). This autumn shares, gold and bonds fell together. A defensive line should be able to step aside.
3. **No gauge for tight money.** Whether the central bank is fighting inflation or funding the government decided gold's year in 1980–82 and again in 2026. The plan had no flag for it.

### 2.5 Hedging and walk-forward, and how the plan treats them

Markus (21 Nov, 13:08): should the system hedge its bets, so that even when we are wrong we still win a little, and should that be tested over the year? (13:14): should a walk-forward system be tested too, in case the AI turns out not to be worth including?

**Hedging.** The fund already hedges, in the four ways that need no forecast:

1. **It spreads.** Fund (r) sizes four unlike buckets by risk, and fund (m) keeps some of each bucket under every label. Whichever way the world goes, part of the fund is on that side.
2. **It steps aside.** Every trend line moves to T-bills when its market turns down, and T-bills pay close to 4% today (the central bank's rate is 3.75% to 4.00%, section 2.2).
3. **It caps opinions.** The views of Markus, Gromen and Bianco move at most 15% of fund (v). The AI may only reduce.
4. **It brakes.** A cap on the fund's own volatility, and all cash after a 15% fall.

No fund can have a hedge that wins a little in every case. Protection is paid for in the years it was not needed. And in a stretch like this autumn, when shares, bonds and gold fell together, only cash and the step-aside rules helped.

One kind of protection is left out on purpose: bought insurance (put options). The published tests say it has cost more than it saved, and that trend rules gave protection more cheaply, except in very fast crashes, where bought insurance pays first (sources in section 11). So the plan does not buy it. It measures it (D15): a yardstick that buys insurance, and a table of what every protection cost and saved.

The literal version of "even when wrong, still up a little" does exist: hold most of the money in T-bills and risk only the interest. With bills near 4% and the usual rule of risking four to five times that cushion, about a fifth of the fund would be at risk. It would earn little more than cash. It is parked as an intake idea (V2-24), not built.

**Walk-forward.** A walk-forward rule re-fits itself on a rolling window of recent results and is then judged on the days that follow. As a way of testing, the platform already works like this: every rule is locked first and judged only on later days (the hold-out, then all of 2027). The question here is walk-forward as a strategy.

- **The platform had one** (VERIFIED in the git history): `trading-platform/analysis/walk_forward.py`, a weekly optimiser for the three Kraken bots of that time. Added 11 April 2026, moved to an archive folder 25 August, deleted 16 October in the dead-code clean-up. It recommended new stop and take-profit levels and ranked symbols from 7-day windows of trades. It should not come back: the windows were far too short to mean anything, most of today's lines decide once a month, and every line's numbers are locked for 2027 (rule 3).
- **The idea is still worth a test,** in the one form that fits a locked year: re-fit the fund's weights, not the lines' rules. Fund (w) (D16) gives a short rule exactly the powers the AI has in fund (c): keep less of a bucket, or none of it.
- **AI does not make it pointless.** It is free, it gives the same answer every time, and it can be replayed on history, which no AI can (V2-02, step 6). If the AI cannot beat it, the AI was not what added the value (section 8).
- **What still runs under the name "walk-forward" is something else:** a nightly check that grades each share account against reference numbers set in July and August, for strategies the accounts no longer run (D17, V2-26).

---

## 3. The design: four layers, each measured against the one below

| Layer | What it is | State at `2447d4a` |
|---|---|---|
| L0 Lines | Pure rule strategies. Each holds shares, hard assets, bonds or currencies by its own rule | 17 shadows and 3 yardsticks built. 5 lines and 5 yardsticks added here; 3 view lines later |
| L1 Macro tape and macro state | A daily record of free macro data, and a four-way label (growth up or down, inflation up or down) worked out from market prices | Not built. A FRED client and a news desk exist to reuse |
| L2 Views | Each stated view from Gromen, Bianco and Markus becomes a dated card. Cards are scored against what happened | Not built (roadmap Phase 3a, not started) |
| L3 AI council | Reads L1 and L2. May only reduce or skip | AI twins built (they see prices only). Fund (c) not built |

**Seven shadow funds. Each comparison answers one question.**

| Fund | Rule in one line | Compared with | Question |
|---|---|---|---|
| (a) equal money — built | Every line the same share | yardsticks | Is a naive mix enough? |
| (b) market mood V1 — built | The 19 Nov table (ALLOCATOR-V1) | (a) | The agreed test: (b) beats (a) by 1 point a year |
| (r) equal risk — new | Four buckets sized by risk, a volatility cap, a coded brake | (a) | Does balancing risk beat equal money? **The base to beat** |
| (m) macro regime — new | Bucket shares set by the macro label | (r) | Does macro data add? |
| (v) views — new | 85% fund (m), 15% the three view lines | (m) | Do the views add? |
| (c) AI — roadmap fund (c) | Fund (m) with the AI council allowed to reduce or skip | (m) | Does the AI add after its bill? |
| (w) walk-forward — new (D16) | Fund (m) with a short rule allowed to reduce or skip: it keeps less of a bucket whose own recent record is poor. The AI's powers, no AI | (m), and (c) | Does re-fitting to recent results add? Can the AI beat a rule with the same reach? |

Buckets, used by (r), (m), (v), (c), (w): **shares** = every line in families trend, stocks, short_term · **hard** = D-GOLD, D-OIL, H-ASSET · **defensive** = D-XTREND, D-RP · **forex** = family forex. Yardsticks and view lines are never inside (a), (b), (r) or (m).

**If D14 is yes, the defensive bucket is D-XTREND and D-TIPS.** D-RP leaves the buckets, because it always holds bonds and cannot step aside. It stays in the league and in funds (a) and (b), unchanged.

One flaw in (b) worth knowing: its table gives forex 10% to 25% of the fund, split across lines whose registered baseline lost money over 18 years (VERIFIED: `TABLE` in `research_harness/league/allocator.py`; FX-BT1 in the ledger). Funds (r) and (m) cap forex at 15% and 10%.

**Beside the four layers sits the long view** (section 2.4): slow gauges, four flags, and tests in other eras. People and reports read it. No line, fund or table does.

---

## 4. Decisions for Markus

| # | Decision | Recommended |
|---|---|---|
| D1 | This plan as a whole | Yes |
| D2 | 🔴 The third share account (`jerome_macro`, "Atlas V2") at the lock: **A** Defensive stocks, as agreed 17 Nov · **B** the cross-asset trend rule alone (bonds, gold, commodities, dollar: "FLEET-V1-X1") · **C** the new hard-assets basket (H-ASSET) | **B.** With A, three of the four real accounts hold mostly shares, against your own view. B reuses live code that already trades these four funds inside Atlas; A and C have no live code and must be built and rehearsed by 4 Dec. Know what B is: steady and small (about 2% a year 2011–2020, 5.9% a year 2021–Oct 2026, falls under 9%). Defensive stocks keeps running as shadow S-DEF; H-ASSET starts as a shadow |
| D3 | New lines (V2-04): D-OIL, H-ASSET, T-GLOBAL, FX-CARRY, yardsticks Y-MF and Y-PERM | Yes to all. If time is short: H-ASSET, D-OIL, T-GLOBAL, Y-MF |
| D4 | Fund rules (r) and (m) (V2-08, V2-09), counted from Mon 4 Jan 2027, not from April | Yes. They need no AI, so there is no reason to lose a quarter |
| D5 | Fund (c) sits on fund (m), not on (b). This changes the roadmap's "(c) against (b)" | Yes |
| D6 | Outside views: confirm the sources in V2-10; say whether you hold paid subscriptions and what their terms allow; yes to an AI cost cap of US$5 a month for making cards (PROPOSED) | Yes |
| D7 | Your own views as cards and a view line (V-MARKUS). First three cards from your 21 Nov message: shares down, gold up, oil up; time frame 2027; strength 3 of 3 | Yes |
| D8 | Size of the views sleeve in fund (v): 15% or 30% | 15% for 2027. The views have no scored record yet |
| D9 | The January 2028 decision rule in section 8 | Yes |
| D10 | Tax and currency: send the three questions in V2-15 to your accountant. A very small real account in 2027 to measure real fills | Send the questions now. No new account in 2027 (the roadmap rule stands); decide again at the July intake |
| D11 | Still waiting from the status log: yes or no on every PROPOSED rule in the league files, FX-TREND and ALLOCATOR-V1; the heartbeat monitor address; arming the per-bot kill switch | — |
| D12 | The long view (section 2.4; V2-18 to V2-22): the panel, the four flags, the tests in other eras, the drills, the Y-GOLD yardstick and the "after inflation" columns. Context only: no rule reads any of it, and the paper never goes into an AI prompt | Yes. It adds no bet. If time is short: V2-19 (a few lines inside V2-06), then V2-20, then the rest |
| D13 | The thesis (`fund-thesis-2027.md`): what the platform is, why it is built this way, and 54 numbered expectations with odds. Hashed at the lock, scored in January 2028 (V2-23) | Read it first and tell me what reads wrong. Then yes |
| D14 | Three changes to the build that the research suggested (section 2.4, last part). They are not bets on the long view. **(1)** A line and a yardstick for inflation-linked Treasuries: D-TIPS and Y-TIPS (V2-04). **(2)** The defensive bucket of funds (r), (m), (v), (c), (w) becomes D-XTREND and D-TIPS; D-RP leaves the buckets and stays in the league (section 3). **(3)** A fourth flag, "tight money" (V2-19) | Yes to all three. Each is small, none has been run on data, and now is the only clean time to make them: before anything is registered. You can take any one without the others; (2) needs (1), or the bucket has one line |
| D15 | Hedges, measured (section 2.5; V2-24). **(1)** A table, on the League page and in the month-end report, of what each protection cost and what it saved. Display only. **(2)** A yardstick that buys insurance: Y-INS, 90% SPY and 10% TAIL, a listed fund that holds Treasuries and buys put options on the S&P 500 | Yes to both. No new bet. The fund already hedges by spreading, stepping aside, capping and braking; this shows the price of each. A floor fund ("cannot end a year down") is parked, not built: it would be about four-fifths T-bills |
| D16 | Fund (w), walk-forward (section 2.5; V2-25): fund (m) with a short rule that keeps less of a bucket when the bucket's own record over the last 3, 6 and 12 months is poor. The powers of the AI in fund (c), with no AI. Section 8 then asks the AI to beat it | Yes. It is the fair rival for the AI, it costs nothing to run, and unlike the AI it can be replayed on history. Low in the build order: intake 1 if the warm-up is ready, else intake 2, which is when fund (c) starts anyway |
| D17 | The old nightly "walk-forward validation" job (V2-26). It still runs, and grades the three share accounts against reference numbers set in July and August, for strategies they no longer run. **A** retire it · **B** re-seed it from the evidence table of V2-01, as information only | **A.** The mirror twins and the league's pass bars already do this job on the 2027 record, and its written protocol (halve size after 60 red days, by hand) has no place in a locked year |

**What Opus can start today, with no decision:** V2-00, V2-01, V2-02 steps 1 to 6, V2-05, V2-06, V2-07, V2-16, the code for V2-04, V2-08, V2-09, V2-18 to V2-22, V2-24 and V2-25 on branches, including the plan file of V2-20, and step 1 of V2-26 (the report).
**Waits for a yes:** V2-03 (D2), registering any new line or fund (D3, D4), V2-02 step 7 (D11), V2-10 to V2-12 (D5 to D8), V2-14 (D9), merging V2-18 to V2-22 and registering Y-GOLD (D12), V2-23 (D13), registering D-TIPS and Y-TIPS, the bucket change and the fourth flag (D14), registering Y-INS and merging the protection table (D15), registering fund (w) (D16), stopping or re-seeding the old check (D17).

---

## 5. Dates

| When | What |
|---|---|
| Now to **Fri 4 Dec** | Build window. Anything that touches the nightly job or the order path must be merged and published by Fri 4 Dec, US market closed. What is not ready waits for the January intake. Do not cram |
| Mon 7 – Fri 11 Dec | The gate. Nothing merges. Work on branches (the replay, the other-eras tests of V2-20 and V2-21, docs, draft pull requests) and on Part B |
| Sat 12 – Sun 13 Dec | The lock. Version 1 registrations. Real-account changes switched on |
| 14 – 31 Dec | Additive, shadow-only pull requests may merge (market closed, tests green, no order-path file) |
| **Sat 2 – Sun 3 Jan 2027** | **Intake 1.** The first US session of 2027 is Mon 4 Jan, so anything registered here still has the whole year. Funds (a), (b), (r), (m) registered, and (w) if the warm-up is ready (V2-25). Lines that missed the lock |
| 3–4 Apr, 3–4 Jul, 2–3 Oct 2027 | Intakes 2, 3, 4. Fund (v), fund (c) and the view lines start at intake 2 at the earliest |
| Each month end | Freeze and one-page report (built) plus the macro page (V2-17) |
| 1 Jul 2027 | Australian capital gains rules change (V2-15) |
| January 2028 | The decision, by the rule in section 8 |

---

## 6. Rules for Opus (added to "Rules that never bend")

1. **Verify first.** Every "Where" below was read at `2447d4a`. Main has moved since. Confirm each path. If an order is already done in main, mark it DONE with the pull request number and move on.
2. 🔴 **Order path.** V2-03 changes what a real account trades. Stop and ask before merging; rehearse first; publish with the market closed.
3. **No tuning.** Every rule and number marked PROPOSED here was written on 21 Nov without being run on any data. Build it exactly as written. If a replay shows a rule is poor, report it. Do not adjust it. A changed rule is a new id and one more try in the luck check.
4. **Hold-out.** Data from 1 Jan 2021 is read only by one registered test per candidate (`research_harness/harness/holdout.py`, `registry.py`). Never read a locked file by hand. The warm-up of V2-08 works out line returns inside those years from the nightly feed, as look-back inputs only: it is stored unseen and shown nowhere.
5. **Macro data.** Free sources only. Append-only: a value is stored as first seen and never overwritten. The macro state (V2-06) reads only market prices, which are never revised. Revised numbers (inflation, jobs, debt) are for reports and the AI.
6. **Views and AI can never** place an order, raise gearing, move a stop or clear a pause. In funds (v) and (c) their reach is bounded exactly as written.
7. **No crypto.** A view about crypto is stored as topic "other" with no direction and is never used.
8. **Paid text is never stored.** Our own one-sentence summary and the link only.
9. After every merged pull request: a Status entry in `finance-2027-plan.md`, and mark the order DONE here.
10. **The long view is context.** No rule, table, weight, stop or brake reads the long-view panel, the flags, the other-eras results or `macro-research-2026-11-21.md`. No single "cycle score" is ever worked out. The research file is never pasted into an AI prompt; the AI gets the same dated numbers the page shows. Anything learned from the other-eras tests enters only through the intake (V2-16), as a new id.

---

## 7. Work orders

Tags: **[GATE]** merge and publish by Fri 4 Dec · **[LOCK]** switched on 12–13 Dec · **[JAN]** intake 1 · **[APR]** intake 2 · **[BRANCH]** research on a branch, no deadline on merging. One pull request per order unless it says otherwise.

### V2-00 Put this plan in the repo — today, docs only
**DONE 22 Nov 2026, PR #173** (research file still to come from Markus).
- Add this file as `docs/plans/fund-roadmap-v2-2026-11-21.md`, and beside it `macro-research-2026-11-21.md` (the research file) and `fund-thesis-2027.md` (the thesis).
- `docs/plans/README.md`: add this file to the reading order straight after the 17 Nov roadmap, with the words "amends the roadmap; wins where they differ". Put the thesis first in the reading order, as "start here: what the platform is, why, and what we expect". List the research file as "background; not a rule".
- `fund-roadmap-build-guide-for-opus.md`: one line at the top of Part A pointing here. Do not edit the 17 Nov roadmap; it is the record of what was agreed.
- Done when: merged.

### V2-01 Evidence table from what is already measured — [BRANCH], start now
- Why: several league lines are the same rule as a strategy that already had its one held-out test. Use those results. Do not test them again.
- Build: `docs/plans/league-evidence-2026-11.md`. One row per league line: the registered test it matches (if any), dates, return a year, Sharpe, worst fall, verdict, ledger entry.
- Matches to confirm in code before using: T-F1 = FLEET-V1-F1 · T-15X = FLEET-V1-C1 (the `core_v1` rule at a 1.5 ceiling, mix C1) · D-XTREND = FLEET-V1 sleeve S2 (`xasset_v1`) · FX-BT1 = FX-BT1 · S-MOMO = MOMO-V2. Check the rebalance timing is the same before quoting a number.
- Sources: `research_harness/ledger.jsonl`, `exploration_log.jsonl`, `explore/*-PLAN.md`.
- Done when: every line has a row that says "measured (where)" or "never measured".

### V2-02 Replay the lines never measured — [BRANCH]; results wanted by the lock
- Why: one year cannot pass the luck check (252 days; a real 1.5 Sharpe would still read "could be luck"). History gives the test its power. Markus asked for this on 21 Nov.
- Build: `research_harness/explore/league_replay.py` and `LEAGUE-REPLAY-PLAN.md`, in the pattern of the GEAR and FLEET plans.
  1. **Data.** Fetch what is missing, free, with the documented two-part pattern: `python -m research_harness.fetch yahoo --dataset <new name> --symbols AGG,RSP,BIL,UUP,USO,XLE,EFA,EEM,TLT,TIP,HYG,IWM,DBMF,TAIL --start 1998-01-01 --end 2020-12-31 --locked-from 2021-01-01`, then the locked part with `--locked`. Datasets are immutable; a new pull gets a new name. Missing at `2447d4a` (VERIFIED): AGG, RSP, BIL; UUP only 2007–2010 and 2018–2024.
  2. **Adapter.** Wrap each league `Strategy` for `harness.portfolio.simulate` using `league.base.decide` (the one rebalance rule) and a `Context` whose calendar is SPY's days. Costs: `research_harness.explore.gear_v1.COSTS` (the league's own). Cash: BIL where it exists; before that, a cash line built from the T-bill rate (DTB3), stated in the report.
  3. **Open run:** first possible day to 31 Dec 2020. `simulate` allows this without a registration.
  4. **Lines:** every rule line marked "never measured" in V2-01, the new lines of V2-04, and funds (a), (r), (m) and (w) through their pure functions on the replayed line returns. Y-INS from April 2017, when its insurance fund began. Fund (b) needs the share-breadth measure, which has no history before 2019; replay it only where the data exists and say so.
  5. **Stock lines:** S-MOMO and S-DEF on the `momo_panel` dataset (2018–2024, includes delisted names, but it is a top-500-by-rank list, not S&P membership: say so). S-MOMO-CAP: skip, there is no sector history.
  6. **Cannot be replayed, ever:** FX-COUNCIL and every AI twin (a language model has already read the past), and the view lines.
  7. 🔴 **One registered run, 1 Jan 2021 to 31 Oct 2026,** for the same set: commit `research_harness/registrations/LEAGUE-REPLAY-V1.json` first (all `REQUIRED_FIELDS` plus the structured `lock`), then `registry.begin_locked_run("LEAGUE-REPLAY-V1", "holdout_test")`, run, `record_run`. One shot. Only after Markus has said yes to the rules.
- Report (`docs/plans/league-replay-report.md`), per line and per fund: return a year, volatility, Sharpe over T-bills, worst fall, each calendar year, correlation with fund (a), the `harness/fleet.evaluate_sleeve` result. For funds also: how many times the 15% stop tripped and what the next 12 months did. For fund (w): the share of months each bucket was cut. And the protection table of V2-24 for both windows.
- Done when: the report holds both windows; the ledger holds the entry; no rule was edited after a run.

### V2-03 Real accounts at the lock — [GATE] build, [LOCK] switch on · 🔴 order path · needs D2
- **If D2 = B (recommended):** a third fleet variant with no share core.
  - `sleeve_runtime/fleet_live.py`: `X1 = FleetVariant("FLEET-V1-X1", "fleet_v1_x1", "fleet_v1_x1_rebalance", 0.00, 1.00)`; add to `VARIANTS` (VERIFIED: F1 is 0.65/0.35, C1 is 1.00/0.00). Check every place that assumes a variant holds the share core; a variant with core weight 0 must not ask for, size or trade the four share funds.
  - `trading-platform/core/stop_policy.py`: `STOP_EXEMPT["jerome_macro"] = TREND_EXIT_LINES` (these four funds carry no stop by design; the monthly call is the exit). Confirm the kill switch's "every position has a stop" check treats this account as it treats Atlas.
  - Places that name FLEET-V1-C1 for this account (found by search; confirm): `kraken-bot/bullion_strategy.py`, `kraken-bot/config.py`, `kraken-bot/runner.py`, and under `trading-platform/`: `core/live_check_job.py` (`STATE_KEYS`), `routes/fleet_v1.py` (`ACCOUNTS`), `core/ddg_push.py`, `core/bot_registry.py` (label), `twins/config.py` (`baseline_weights`).
  - Display name: ask Markus (the account is called "Atlas V2" today).
  - Cutover: rehearse as `kraken-bot/rehearsal.py` does; at the lock sell the C1 holdings and start X1; restart `RUN_START` once (`core/fleet_capital.py`), as the old guide's Phase 1 order 8 says.
- **If D2 = A:** build live Defensive stocks as the old guide says (Phase 1 orders 5 and 8). No live code exists for it (VERIFIED: nothing in `sleeve_runtime/`).
- **Either way, Momentum's new version** (weekly re-entry check, 25% sector cap): old guide Phase 1 order 6. Not in the live code (VERIFIED: `sleeve_runtime/momo_live.py`, `MIDMONTH_REENTRY = False`, no sector cap). The shadow S-MOMO-CAP is the reference.
- Done when: rehearsal clean; tests green; merged and published by 4 Dec with the switch off; switched on at the lock after Markus's yes.

### V2-04 New lines — [GATE], else [JAN] · needs D3
**DONE (version 0) 22 Nov 2026, PR #175, published 22 Nov.** Registration at the lock or intake 1 after 5 nights of values.
All rules PROPOSED. Each is a pure function in `research_harness/league/families.py` (forex: `forex.py`), one registration file in `research_harness/registrations/league/` with the same fields as `D-XTREND.json`, and a test that checks the holdings by hand on two recorded dates. "Trend votes" always means the existing rule: how many of "close above its own close 63, 126 and 252 sessions ago" hold (`core_v1.votes`).

| Id | Family | When | Rule |
|---|---|---|---|
| **D-OIL** | diversifier | monthly | 100% oil fund USO when USO has at least 2 of 3 trend votes, else T-bills. The same rule as D-GOLD on another fund: turn `_gold` into one function that takes the symbol, and prove D-GOLD's output is unchanged |
| **H-ASSET** | diversifier | monthly | Four slots of 25%: GLD (gold), USO (oil), DBC (commodities), XLE (energy shares). A slot is on when its fund has at least 2 of 3 trend votes. An on slot holds 25% × min(1, 0.20 ÷ its 63-session volatility) (`xasset_v1.vol63`). The rest in T-bills. No stops |
| **T-GLOBAL** | trend | monthly, and when any vote count changes | Three slots of one third: SPY (US), EFA (developed, non-US), EEM (emerging). Each slot holds one third × E, where E is the Atlas rule at a 1.0 ceiling on that fund's own closes (`atlas_exposure(closes, 1.0)`). The rest in T-bills. 20% stop per holding (`core_v1.STOP_PCT`) |
| **FX-CARRY** | forex | monthly | For each of the 7 non-dollar currencies, d = the yearly interest gap for holding it against the US dollar, from the latest row in `twin_fx_financing`: (long rate − short rate) ÷ 2 for XXX_USD pairs, the negative of that for USD_XXX pairs. The dollar's d is 0. Confirm the sign in `twins/financing.py`: a currency that pays you to hold it has d above 0. Rank the 8. Long the top 3, short the bottom 3. Each leg sized like FX-TREND (10% a year volatility target, 63 sessions) divided by 6, placed through the dollar pairs with `signed_weight`; a leg that is the dollar itself needs no trade. Gross at most 2.0. No stops. A missing rate = no decision, with the reason. League strategies are pure, so the function reads no database: `twins/league.py` passes the rates in through a new `Context` field |
| **Y-MF** | yardstick | once | 100% DBMF, a managed-futures fund. Asks: can one cheap fund do the diversifier job? |
| **Y-PERM** | yardstick | monthly | 25% each SPY, TLT, GLD, BIL. A mix that needs no forecast |
| **D-TIPS** (D14) | diversifier | monthly | 100% TIP, a fund of inflation-linked Treasuries, when TIP has at least 2 of 3 trend votes, else T-bills. The same one function as D-GOLD and D-OIL |
| **Y-TIPS** (D14) | yardstick | once | 100% TIP, bought once and held. Asks: did plain inflation-linked bonds do the job, and did they beat gold held (Y-GOLD)? |
| **Y-INS** (D15) | yardstick | monthly | 90% SPY, 10% TAIL, shaped like Y-6040. TAIL is a listed fund that holds Treasuries and, by its manager's description, spends about 1% of its assets each month on put options on the S&P 500. Confirm it still trades. Asks: does bought insurance pay for itself? |

- Check the nightly price feed has daily bars for USO, XLE, EFA, EEM, TLT, TIP, DBMF and TAIL (`families.fixed_symbols()` picks up new symbols by itself).
- `N_TRIALS` in `trading-platform/twins/leaderboard.py` rises by the number of new shadow lines (17 → 21 with the first four, 22 with D-TIPS; yardsticks are not tries). Update `candidates_declared` in the new files.
- Pass bars in the new files: the family bars Markus agreed on 20 Nov (AU7).
- Carry warning to write into FX-CARRY's file: carry tends to fall together with shares in a panic. It is a return source, not a hedge.
- Done when: each new line writes a value on 5 nights in a row (version 0), then is registered at the lock or at intake 1.

### V2-05 Macro tape — [GATE], else [JAN]
- Why: Markus wants the fund to take in macro data heavily. Today the platform keeps only the latest value of about ten series and uses them in no league rule (VERIFIED: `trading-platform/data/fred_client.py`).
- Build: a new package `trading-platform/macro/` (outside `twins/`; it must not import the order path, so add it to the import list in `trading-platform/tests/test_twins_isolation.py`).
  - `macro/series.py`, the one committed list. Each entry: id, plain name, group, source, how often, revised yes or no.
  - **FRED** (free; the key is already in settings). The ids below are from memory: **check each on FRED before committing; drop any that does not resolve and list it in the pull request.** Rates: DFF, DGS2, DGS10, DGS30, T10Y2Y, T10Y3M, THREEFYTP10. Inflation: T5YIE, T10YIE, T5YIFR, DFII10, CPIAUCSL, CPILFESL, PCEPILFE. Credit and stress: BAMLH0A0HYM2, BAMLC0A0CM, NFCI, VIXCLS. Dollar: DTWEXBGS. Energy: DCOILWTICO, DCOILBRENTEU. Government debt: GFDEBTN, GFDEGDQ188S, A091RC1Q027SBEA, MTSDS133FMS, FDHBFIN. Money: WALCL, RRPONTSYD, WTREGEN, M2SL. Growth and jobs: UNRATE, ICSA, PAYEMS, INDPRO, UMCSENT.
  - **Prices** (the existing daily bar feed): SPY, IWM, EFA, EEM, IEF, TLT, TIP, HYG, GLD, USO, DBC, XLE, UUP, ITA.
  - **World events** (free): a daily count of news articles from GDELT for four fixed searches: war or conflict; sanctions or tariffs; oil supply; debt ceiling, shutdown or downgrade. The host is already on the allowlist in `kraken-bot/forex_news.py`; reuse its safe fetch.
  - Table `macro_observations`, made at runtime, additive, append-only: series, date of the value, value, when first seen, source, backfilled yes or no. A revision is a new row.
  - Job `macro_daily`, once a day after the US close. A failed source raises at most one alarm per source per day and never blocks a trading or twins job.
  - Backfill history once, with every backfilled row marked, so nobody mistakes it for what was known on the day.
  - `GET /macro/state` and a "Macro" card on the League page: today's label, the six votes (V2-06) and twelve tiles (10-year yield, 2-year yield, curve, expected inflation, real yield, high-yield spread, dollar, oil, gold, S&P trend, small-company trend, government deficit), each with its value, its date and its source.
- Done when: 5 nights of rows for every series; a test proves a stored row is never updated; every tile shows a date and a source.

### V2-06 Macro state — [GATE], else [JAN]
**DONE (code, storage) 22 Nov 2026, PRs #176/#177, published 22 Nov.** Still to do: hand check on three recorded dates (`python -m twins.macro_check`).
All PROPOSED. Pure, prices only: `research_harness/league/macro_state.py`, in the style of `league/allocator.py`.
- **Growth votes:** SPY above its 200-session average · IWM above its 200-session average · the ratio HYG ÷ IEF above its own 200-session average (risky bonds beating safe bonds). Growth is "up" on 2 of 3.
- **Inflation votes:** DBC above its 200-session average · USO above its 200-session average · the ratio TIP ÷ IEF above its own 200-session average (inflation-protected bonds beating plain bonds). Inflation is "up" on 2 of 3.
- **Label:** goldilocks (growth up, inflation down) · reflation (up, up) · stagflation (down, up) · bust (down, down).
- A new label counts only after 5 sessions in a row. Until then yesterday's label stands.
- Also stored each day, not used by any table: "bonds are hedging" (63-session correlation of SPY and IEF daily returns below zero), "rough" (the V1 measure), dollar trend (UUP above its 200-session average).
- Stored once a day in an append-only `macro_state` table, the way `allocator_labels` is.
- The nightly job must fetch the bars these votes need (SPY, IWM, HYG, IEF, TIP, DBC, USO, UUP, and TLT and GLD for the flags of V2-19); `families.fixed_symbols()` only lists what the strategies hold.
- Done when: labels for three recorded dates match a hand calculation; the five-session rule has a test.

### V2-07 Leaderboard: what each line adds — [JAN]
Display only; no rule reads these. In `trading-platform/twins/leaderboard.py` (`build`) and `artifacts/dashboard/src/pages/LeaguePage.tsx`:
- Per line: Sharpe over T-bills (against Y-CASH); correlation with fund (a); "adds to the fund" = fund (a)'s Sharpe with the line minus without it (reuse `research_harness/harness/fleet.evaluate_sleeve`).
- Board header: "independent lines" = N ÷ (1 + (N − 1) × average correlation between lines).
- Australian-dollar return per line and per fund, from the AUD_USD daily closes the league already fetches (`twins/league.oanda_daily`).
- Done when: a test with two identical lines reads correlation 1 and "independent lines" 1.

### V2-08 Fund (r), equal risk — [JAN] · needs D4
All PROPOSED. Pure functions in a new `research_harness/league/funds_v2.py`; leave `allocator.py` (V1) untouched. Wire into `trading-platform/twins/allocator.py` (`FUNDS`, `NAMES`) as `ALLOC-RISK`.
- Buckets as in section 3. A bucket's daily return is the plain average of its lines' returns.
- Bucket weight in proportion to 1 ÷ max(its 63-session volatility, 4% a year), scaled to add to 100%. Forex capped at 15%; the excess to cash. Equal split inside a bucket. First session of each month.
- V1's limits unchanged (`limited`: 40% a line, 1.5x exposure) and V1's 5 bps cost for moving money.
- **Volatility cap:** s = min(1, 10% ÷ the fund's own 21-session volatility before any cut). Worked out at each week's first session; changed only when s has moved by more than 0.10. The cut part sits in cash.
- **Brake V2:** a 15% fall from the high means all cash (the number Markus agreed). The way back is coded: keep a ghost curve (the same fund as if it had never stopped). Come back when 20 sessions have passed since the stop and the ghost curve closes above its own 50-session average. Come back at half weights for 20 sessions, then full. The high restarts at the come-back value. Record the ghost curve always.
- **Also record, always,** for every fund that uses this cap and brake: the raw curve (no volatility cap, no brake), beside the ghost curve (cap on, brake off). V2-24 shows what the cap and the brake each cost and saved.
- **Warm-up** (added 21 Nov, 13:30; it was missing). The look-backs here (63 sessions of bucket returns, 21 of the fund's own) and in fund (w) (252 sessions) reach back before the league's first night. On 4 Jan the league will hold about 30 sessions, so without this the rule cannot be worked out as written.
  - Fill the look-backs with warm-up returns: each rule line's own pure function, run over the 320 sessions before the fund's first counted session, on the nightly feed's recorded prices, through the adapter of V2-02 step 2.
  - Store them once, in a table of their own (`league_warmup`: line, day, return), append-only, read only by `funds_v2.py`. No page, route or report shows them and nobody reads them by hand: those sessions fall inside the hold-out years (rule 4), and looking at them would spend the one-shot test. They are inputs to a look-back, never a result.
  - A line has no warm-up when its inputs cannot be rebuilt for past days: FX-COUNCIL (an AI cannot be replayed), FX-CARRY (its stored interest rates begin with their table) and the lines that pick single shares (S-MOMO, S-MOMO-CAP, S-DEF). Confirm the list. In a warm-up session a bucket's average is taken over the lines that have a return.
  - Funds (m) and (w) also need the macro label for the warm-up sessions. Work it out with the pure function of V2-06 on the same prices, in memory. `macro_state` holds only labels recorded on their own day.
  - The fund runs through the warm-up sessions only to fill its look-backs, holding cash until a look-back has its full length. Its record starts at its first counted session: value 1.0, high 1.0, brake not tripped.
  - Check the feed has daily bars from 1 July 2024 for every symbol those lines hold (320 sessions, plus the lines' own 252). Report anything missing.
  - **If the warm-up is not ready at intake 1,** funds (r) and (m) still start on 4 Jan. Each look-back then uses the league's own stored values (version 0 and version 1) for as many sessions as there are. Until a bucket has 20 sessions it is given the average volatility of the buckets that do; until the fund has 21 sessions of its own, s = 1. The registration files say which start was used. Fund (w) cannot start without the warm-up.
  - Tests: the counted record starts at 1.0 with the brake not tripped; a test fails if `leaderboard.py` or any route reads `league_warmup`.
- Register `research_harness/registrations/league/ALLOC-RISK.json`.
- Done when: tests for the limits, for a stop and a come-back on a made-up curve, and for the volatility cut.

### V2-09 Fund (m), macro regime — [JAN] · needs D4
All PROPOSED. Same file, wired as `ALLOC-MACRO`. Bucket shares by label, in percent:

| Label | Shares | Hard | Defensive | Forex | Cash |
|---|---|---|---|---|---|
| goldilocks | 60 | 10 | 15 | 5 | 10 |
| reflation | 45 | 30 | 5 | 5 | 15 |
| stagflation | 10 | 45 | 5 | 10 | 30 |
| bust | 10 | 15 | 40 | 10 | 25 |

- Equal split inside a bucket. Rebalanced at the first session of a month and when the confirmed label changes. V1's limits. The volatility cap and Brake V2 of fund (r).
- A line decides its own holdings. If gold's trend is off, D-GOLD holds T-bills, so "45% hard" can be mostly cash. That is intended: macro sets the room, trend fills it.
- Register `ALLOC-MACRO.json`. The luck check for funds counts the funds as its tries.
- Done when: tests show the weights move only after the label has held 5 sessions, and never break a limit.

### V2-10 Outside views: collect, card, score — build Dec to Feb, live by [APR] · needs D6, D7
This is roadmap Phase 3a, orders 1 to 9 in the old guide, unchanged, plus:
- **Sources to confirm with Markus** (found by search on 21 Nov; check that each feed exists and what its terms allow; nothing behind a login):
  - Jim Bianco: the "Talking Data" podcast (Arbor Research & Trading); the Bianco Research public podcast and video feed; public interview transcripts.
  - Luke Gromen: public posts at lukegromen.substack.com; the "Luke Gromen – FFTT, LLC" podcast feed; public transcripts of interviews (for example MacroVoices). The paid "Tree Rings" letter is never used.
- Reuse what exists: the safe fetch in `kraken-bot/forex_news.py` (HTTPS only, host allowlist, no redirects, size cap, text treated as data) and the checked model calls in `kraken-bot/forex_council.py`.
- **A drop box (new):** a small form on the Me page where Markus pastes a link and, in his own words, the view he took from it: person, topic, direction, strength 1 to 3, time frame. Stored as a card marked "entered by Markus". For a two-hour podcast this beats any scraper.
- **Markus as a third voice (D7):** his own views are cards with person = Markus, scored like the others.
- Topics: rates, dollar, oil, shares, gold, bonds, commodities, other.
- Done when (unchanged from the roadmap): 20 days of cards with no missed day; the scoreboard shows hit rates per person and topic.

### V2-11 View lines — [APR]
All PROPOSED. V-GROMEN, V-BIANCO, V-MARKUS: what you would hold if you simply followed each person.
- Fixed map: shares → SPY, gold → GLD, oil → USO, commodities → DBC, bonds → IEF, dollar → UUP. Six slots of one sixth.
- A slot is held when that person's current card for the topic says "up": one third of the slot at strength 1, two thirds at 2, all of it at 3. Otherwise T-bills. "Rates up" counts as "bonds down" when there is no bonds card.
- Checked every session; changes only when a card changes.
- Pure, like every league line: the nightly job passes each person's current cards in through `Context`; the function reads no database.
- New family `views` (add to `FAMILIES` in `league/base.py`). `twins/allocator.inputs` must leave this family out of every fund except the sleeve in (v).
- Start only after V2-10's 20 clean days. They count as three more tries.

### V2-12 Funds (v) and (c) — [APR] · needs D5, D8, and the AI-cost yes the roadmap already requires
- **Fund (v):** 85% fund (m)'s weights, 15% split equally across the three view lines. Nothing else. No AI in the sizing.
- **Fund (c):** fund (m), with the AI council allowed to keep between 0% and 100% of each bucket (reduce or skip, never add); the rest to cash. Its prompt carries the macro label, the six votes, the twelve tiles, the long-view gauges and flags as dated numbers (V2-18, V2-19; rule 10), the news digest the forex council already gets, and the current view cards. Its note must list each view it used and say agree or disagree (roadmap 3a order 6). A new `VOTE_VERSION` in `twins/ai_council.py`; cost inside `MONTHLY_CAP_USD`.
- Done when: a test proves neither fund can exceed fund (m)'s exposure limits, and that (c) can only reduce.

### V2-13 Give the AI twins the macro pack — [JAN]
The AI twins see prices only (VERIFIED: `prompt` and `_row` in `twins/ai_council.py`). Add the macro label, votes and tiles to the prompt, and the long-view gauges and flags as dated numbers (V2-18, V2-19; no text from the research file, rule 10), as a new dated vote version, started at intake 1 so 2027 runs on one version. Model ids pinned at the lock (AU8, agreed).

### V2-14 Write down the January 2028 rule — before 31 Dec · needs D9
`docs/plans/phase4-decision-rule-2027.md`, from section 8, hashed into the lock record.

### V2-15 Tax and currency — Markus and his accountant; Opus prepares
- One page of questions for the accountant:
  1. Would automated daily or monthly trading be treated as share trading (ordinary income) or as investing (capital gains)?
  2. Who should hold the account: Markus, a company, or a super fund?
  3. US-listed funds held by an Australian resident: dividend withholding, and any US estate tax exposure.
- Background for that talk: from 1 July 2027 the 50% capital gains discount is replaced by cost-base indexation with a 30% minimum tax on some gains, and the first stage is law (ATO page, section 11). Indexation is for assets held more than 12 months, so a strategy that turns positions over inside a year would get none of it.
- After the answers: one dated file of assumptions (source: the accountant's letter) and an after-tax estimate column. **Opus invents no tax rule.**
- The Australian-dollar columns come from V2-07.

### V2-16 Intake: how a new idea gets in — docs, by the lock
`docs/plans/intake/README.md`: one page per idea (the rule, the data, why it should not move with the lines we have), a registration, a replay inside the hold-out rules, counted as a try, merged only at an intake weekend after 5 clean nights on version 0. The ideas parked in the research file ("Ideas parked for the intake") start here, like any other.

### V2-17 Month-end macro page — [JAN]
Add to the monthly report (`trading-platform/twins/month_end.py`): the label for each day, the tiles, each voice's scored calls, and the funds against the yardsticks in US and Australian dollars and after inflation. From V2-24: the protection table. From V2-18 and V2-19: the long-view gauges with their dates, the days each flag was on, and each fund's return on those days and on the rest.

### V2-18 Long-view panel — with V2-05 if it fits [GATE], else [JAN] · needs D12
- Why: section 2.4. The gauges that Dalio and the long records point to, kept where the fund's macro picture is read. For reading only (rule 10).
- Build: a group `long_cycle` in `macro/series.py`, fetched and stored like every V2-05 series.

| # | Gauge | Made from | How often |
|---|---|---|---|
| 1 | Federal debt held by the public, % of the economy | FRED FYGFGDQ188S | quarterly |
| 2 | Federal interest cost as a share of federal income | A091RC1Q027SBEA ÷ FGRECPT | quarterly |
| 3 | Federal deficit, % of the economy | FRED FYFSGDA188S | yearly |
| 4 | Share of federal debt held abroad | FDHBFIN ÷ GFDEBTN | quarterly |
| 5 | The dollar's share of world currency reserves | IMF reserve data brief (COFER) | quarterly, by hand |
| 6 | Gold's share of central-bank reserves | European Central Bank yearly report, or the World Gold Council | yearly, by hand |
| 7 | 10-year yield after inflation | DFII10 | daily |
| 8 | Cash rate after inflation | DFF minus the 12-month change in CPIAUCSL | monthly |
| 9 | Shares and bonds, 3-year link | correlation of SPY and IEF daily returns over 756 sessions | daily |
| 10 | Shares priced in gold | SPY ÷ GLD | daily |
| 11 | US shares against the rest of the world | SPY ÷ EFA | daily |
| 12 | Armed conflicts involving a state | Uppsala Conflict Data Program yearly count | yearly, by hand |

- The FRED ids are from memory: check each; drop and list any that fails (as in V2-05).
- By-hand gauges: one committed file, `trading-platform/macro/manual_long_cycle.csv` (gauge, date of the value, value, link, entered on). `macro_daily` loads it into `macro_observations`. A correction is a new row. First rows, from the research file: dollar share 57.13% (first quarter of 2026); gold share 27% (end of 2025); conflicts 65 (2025). When building, enter the newest published value for each, with its link.
- Display: a "Long view" card under the Macro card. Each gauge shows its value, date and source, and a bar showing where today sits between the lowest and highest values stored. Beside gauge 1, note the 1946 record (106%). No colours that mean good or bad. No total and no score (rule 10).
- **After inflation.** On the month-end page every fund and yardstick also shows its return minus the change in CPIAUCSL over the same months. The index arrives about a month late: use the latest month published and print its date.
- **Yardstick Y-GOLD:** 100% GLD, bought once and held (`_fixed({"GLD": 1.0})`, family `yardstick`, a registration file shaped like `Y-SPX.json`). It asks: would simply holding gold have beaten all of this? Yardsticks are not tries.
- Done when: every gauge shows a value, a date and a source; Y-GOLD writes a value on 5 nights in a row; a test fails if any file under `research_harness/league/` or `trading-platform/twins/allocator.py` mentions `long_cycle`.

### V2-19 Four daily flags — inside V2-06 · needs D12 (the fourth needs D14)
**DONE (code, storage) 22 Nov 2026, PRs #176/#177.** Still to do: show the fast flag for April 2025 (`python -m twins.macro_check 2025-04-01 2025-04-30`); shown on the Macro card with V2-05.
All PROPOSED. Prices only. Worked out in `research_harness/league/macro_state.py` and stored each day in `macro_state`, beside "bonds are hedging". Shown on the Macro card. Read by no table and no fund (rule 10).
- **Three-way sell-off, fast:** SPY, TLT and UUP each closed lower than 21 sessions earlier. US shares, long US bonds and the dollar falling together means money leaving the country, not moving around inside it.
- **Three-way sell-off, slow:** SPY, TLT and UUP each below their own 200-session average.
- **Hard assets lead:** GLD ÷ SPY and DBC ÷ SPY each above their own 200-session average.
- **Tight money** (D14): TIP below its own 200-session average and UUP above its own. Inflation-linked bonds falling means the yield after inflation is rising; with the dollar rising too, money is getting dearer. Gold fell through this in 1980–82 and in autumn 2026.
- Done when: each flag matches a hand calculation on three recorded dates; the pull request shows the fast flag for every session of April 2025, a month when shares, bonds and the dollar fell together (if the flag never comes on, report it and do not change the rule); a test fails if `funds_v2.py` or `twins/allocator.py` mentions a flag.

### V2-20 Other eras, part 1: the share-trend rule on daily prices — [BRANCH]; the gate week is a good slot · information only · needs D12
- Why: nothing we run has seen a market before 1985. What does the Atlas share-trend rule do in 1929–32, in 1966–82, and in Japan after 1989?
- Pattern: `research_harness/explore/G4-STRESS-1985-PLAN.md`, `g4_stress_1985.py`, `tests/test_g4_stress_1985.py`. **Write and commit `research_harness/explore/LONG-STRESS-PLAN.md` before any data is pulled.** One run. Logged in `exploration_log.jsonl` as information only.
- Rule: T-1X as registered (`atlas_exposure(closes, 1.0)`; first session of each month and when the vote count changes; 20% stop re-set at each rebalance), on one instrument, the index itself (`core_v1.MIXES["C2"]`). Say in the report that T-1X also holds a 40% Nasdaq-100 leg, which has no history before 1985.
- Data: new datasets, nothing after 31 Dec 2020 (rule 4).
  - `python -m research_harness.fetch yahoo --dataset index_long_y_<date> --symbols ^GSPC,^N225 --start 1927-12-01 --end 2020-12-31`. First days expected, from memory: late December 1927 and January 1965. Report what arrives.
  - `fetch shiller --dataset shiller_long_<date> --start 1927-01-01 --end 2020-12-31`, for dividends.
  - `fetch fred`: DTB3 from 1954 (daily); TB3MS from 1934 and CPIAUCNS from 1913 (monthly). The `fred` fetch stores every value divided by 100 in a field called `rate`; for the price index only ratios are used.
- US instrument: `recon.reconstruct.sp500_tr` (price plus Shiller dividends) as close-only bars (`recon.reconstruct.close_to_close`), so a decision read at one close fills at the next.
- Japan: the Nikkei price index in yen, no dividends, cash at 0%. Say that this understates both the rule and buy-and-hold.
- US cash: DTB3 from 1954; TB3MS held flat inside each month for 1934–53; 0% before 1934. Say so.
- Costs: `research_harness.explore.gear_v1.COSTS`. Say that trading cost much more before the 1970s.
- Windows. US: from the first day with 253 closes to 31 Dec 2006, and inside it 1929–32 · 1937–42 · 1946–49 · 1966–82 · 1973–74 · 1987 · 2000–02. Japan: 1966–89 · 1990–2012 · 2013–20.
- Check: the same build over 2007–2020 beside the same rule on real SPY bars. Print the gap.
- Report, `docs/plans/other-eras-report.md`. For the rule and for buy-and-hold in each window: return a year, the same after inflation (US only), worst fall, Sharpe over cash, share of days invested, longest time below an earlier high.
- No pass bar. Not a try in the luck check, because nothing is chosen from it. A poor result is a finding for Markus (rule 3).
- Done when: the plan's commit comes before the data's; the report is written; no rule was edited.

### V2-21 Other eras, part 2: the fund's shape on monthly prices — [BRANCH] · information only · needs D12 · wanted by intake 2
- Why: part 1 has shares only. The question here is whether the hard and defensive buckets do their jobs when the era changes.
- The same plan file, in its own section, written before the data is pulled. Monthly, month-end values, 1928 to 2020.
- Series. All free. The addresses and ids are from memory: check each and write what was used into the plan.

| Series | From | Made from |
|---|---|---|
| Shares | 1928 | part 1's rebuilt US series, month-end |
| Bonds, 10-year | 1928 | the long-rate column of Shiller's file (extend `parse_shiller_rows`; read the column positions from the sheet's header), through the formula in `recon.reconstruct.bond_tr` in monthly form (yield ÷ 12; monthly change in yield) |
| Cash | 1934 | TB3MS; 0% before |
| Gold | April 1968 | the World Bank's monthly commodity prices (the "Pink Sheet"). Before 1968 the price was fixed, and Americans could not hold gold: no gold line before then |
| Commodities | 1928 | AQR, "Commodities for the Long Run: Index Level Data, Monthly" (an equal-weight futures index): its excess return plus the cash rate |
| Prices | 1928 | CPIAUCNS |

- Terms of use: read AQR's terms on the download page before committing a copy. If they do not clearly allow it, keep the file out of the repo and commit only its address, date and hash.
- Rules: monthly twins of the league rules. PROPOSED, fixed here, never tuned. A decision made at one month-end earns from the next month. "Votes" = the month-end value is above its value 3, 6 and 12 months earlier. "Volatility" = the standard deviation of the last 12 monthly returns × √12. A line joins a fund in the first month it exists.
  - **M-T** (twin of T-1X): shares × votes ÷ 3; the rest in cash.
  - **M-GOLD** (twin of D-GOLD): all gold on 2 or 3 votes, else cash. From April 1969.
  - **M-COM** (stands in for D-OIL and H-ASSET): all commodities on 2 or 3 votes, else cash.
  - **M-XT** (twin of D-XTREND): bonds, gold, commodities; a slot is 25% when it has 2 or 3 votes; the rest in cash. The dollar slot stays empty: there is no clean free series.
  - **M-RP** (twin of D-RP): shares, bonds and, from 1968, gold, each weighted by 1 ÷ its volatility.
  - Held and never traded: all shares · 60/40 · a quarter each of shares, bonds, gold and cash (from 1968) · all cash · all gold (from 1968).
  - **Fund (a):** equal money across M-T, M-GOLD, M-COM, M-XT, M-RP. **Fund (r):** buckets shares = M-T, hard = M-GOLD and M-COM, defensive = M-XT and M-RP; bucket weight in proportion to 1 ÷ max(volatility, 4%). No forex. No volatility cap and no brake: those are tested on daily prices in V2-02.
  - Fund (m) is not run: its votes need funds that did not exist. Say so.
  - No twin for D-TIPS (D14): these bonds did not exist before 1997. If D14 is yes, the defensive bucket here is M-XT alone, and M-RP is reported as a line outside the fund.
  - Cost: 10 bps of each trade. Say that costs were higher then.
- Eras: 1929–49 · 1950–65 · 1966–82 · 1983–99 · 2000–20 · all.
- Report (the same file as part 1), per era and per line, mix and fund: return a year, the same after inflation, worst fall at month-ends, longest time below an earlier high after inflation. One summary table of what won and lost in each era; it replaces the "Five eras" table in the research file.
- Print these limits in the report: month-end prices hide falls inside a month; US only, and the US is the country that did not break; the commodity index could not be bought as one fund in those years; bond returns before 1953 come from yearly yields.
- No pass bar. Not a try in the luck check (as in V2-20).
- Done when: both parts are in the report; the plan's commit comes before the data's; no rule was edited.

### V2-22 World-breaks drills — tests and a one-page runbook · [JAN] · needs D12
- Why: the New York exchange shut for four and a half months in 1914. In November 2025 the world's largest futures exchange stopped for 11 hours over a cooling fault. Over ten years the fund will meet something like it.
- Build: six drills as tests on made-up data (pattern: `kraken-bot/rehearsal.py`, `kraken-bot/fake_alpaca.py`, the league and twins tests). Each drill writes down what the code does today. 🔴 **A drill that shows a flaw in the order path is a finding for Markus: stop and ask. Do not fix it in the same pull request.**
  1. **The market is shut for 30 sessions** (no bars for anything). No job crashes. No decision is written. At most one alarm a day. On the first session back, the league and the twins carry on from the right session, and a month start that fell inside the closure is rebalanced then.
  2. **The reopening gap.** A held fund's first price back is 30% lower. The twins engine fills a stop at the open when the price gaps through it (VERIFIED: `research_harness/harness/portfolio.simulate`); prove it with a test. What the live paper accounts' stop orders do is UNKNOWN: report it.
  3. **One held fund stops trading** for 30 sessions while the market is open. The line keeps the last price; the leaderboard marks the holding stale after 3 sessions; no rule treats a missing price as a vote.
  4. **Our own outage of 20 sessions** (host, database or broker out of reach). Past `CATCH_UP_SESSIONS` (15) the league skips the older sessions and reports them, and a skipped month start is a lost rebalance (VERIFIED: `run_days` in `trading-platform/twins/league.py`). Show it, and list it as a finding.
  5. **One bad price:** a single close ten times too high or too low. Does any line trade on it? Does the leaderboard show it as a real gain or loss? Report.
  6. **Orders refused for 5 sessions.** Retries are bounded, one alarm, and no doubled orders when it clears. If `order-path-audit-2026-11-16.md` already proves this, cite it and skip.
- Runbook, `docs/plans/world-breaks-runbook.md`, one page: for each drill, what the system does by itself, what Markus does, and what is never done (for example a hand-placed order to "catch up" with no note in the log).
- Done when: the six drills run with the other tests; the findings are in the Status log; the runbook is merged.

### V2-23 The thesis on record — docs, by the lock · needs D13
- `docs/plans/fund-thesis-2027.md` says what the platform is, why it is built this way, and what its author (Claude, Fable 5.2) expects of 2027. Its section "Expectations to score" is a numbered list with a probability on every line.
- At the lock: hash the file into the lock record, as V2-14 does for the decision rule. After that it does not change. A correction is a dated note at the end, never an edit.
- Before the predictions lock (`LOCK_AT` in `trading-platform/twins/predictions.py`, 1 Jan 2027 New York time): file the thesis's table F (nine markets, three US numbers, and the paragraph in words) in `year_predictions` under the author "Fable 5.2", model `claude-fable-5-2`. `predictions.file` takes any author (VERIFIED); the route only files for Markus. 🔴 This is a write to the production database: ask Markus first, and do it with the market closed. Change nothing else. The entry is then scored by the same rule as everyone else's.
- January 2028: score every numbered expectation right or wrong from the frozen record, in `docs/plans/thesis-scorecard-2028-01.md`. Print the Brier score: the average of (probability − outcome)², where the outcome is 1 or 0. Opus scores; Markus signs. No expectation is re-worded after the fact.
- Done when: the hash is in the lock record; in January 2028, the scorecard exists.

### V2-24 Hedges, measured — [JAN] · a display and one yardstick · needs D15
- Why: section 2.5. The fund protects itself by spreading, stepping aside, capping and braking. None of that is free. Show the price of each, beside the one protection the fund does not hold: bought insurance.
- **Yardstick Y-INS:** the row in V2-04. Registered like Y-6040. Yardsticks are not tries.
- **The table, "What each protection cost and saved".** Display only: built in `trading-platform/twins/leaderboard.py` (`build`), shown as a card on the League page and in the month-end report (V2-17). No rule and no fund reads it.

| Protection | With it | Without it |
|---|---|---|
| Stepping aside, shares | The mirror twins of Atlas and Atlas V2 | Their baseline twins (`baseline_full` in `twins/config.py`: the same funds held at the full limit, never in cash; built) |
| Stepping aside, gold | D-GOLD | Y-GOLD |
| Stepping aside, inflation-linked bonds (D14) | D-TIPS | Y-TIPS |
| Balancing by risk | Fund (r) | Fund (a) |
| Volatility cap | The ghost curve of fund (r), and of fund (m) | Its raw curve (V2-08) |
| Brake | Fund (r), and fund (m) | Its ghost curve |
| The AI may reduce or skip | Each AI veto twin; fund (c) | Its base line; fund (m) |
| A rule may reduce or skip (D16) | Fund (w) | Fund (m) |
| Bought insurance | Y-INS | Y-SPX |
| A mix that needs no forecast | Y-PERM | Y-SPX |

- Columns, over the dates both sides have (print the dates): return and worst fall of each side; **cost** = return without, minus return with, in points (below zero means the protection paid for itself); **fall saved** = worst fall without, minus worst fall with, in points.
- Under the table, in fixed words: "Protection is paid for in the years it was not needed. Judge it over more than one year." The replay report (V2-02) carries the same table for both of its windows.
- **Parked, not built: a floor fund.** Most of the money in T-bills and only a cushion at risk, so the fund cannot end a calendar year below where it began. With bills near 4% and a multiplier of 5, about a fifth of the fund would sit in fund (r) at the start of a year. It needs no options and no new data. Its known faults: a sharp fall between two rebalances can break the floor, and after a fall it can sit in cash for the rest of the year. If Markus wants it measured, it enters through the intake (V2-16).
- Done when: Y-INS writes a value on 5 nights in a row; a test with a made-up pair shows the right cost and fall saved; every row prints its dates.

### V2-25 Fund (w), walk-forward — [JAN] if the warm-up of V2-08 is ready, else [APR] · needs D16
All PROPOSED. A pure function in `funds_v2.py`, wired into `trading-platform/twins/allocator.py` as `ALLOC-WALK`.
- Why: section 2.5. The rule-based rival to the AI: the base and the reach of fund (c), with no AI.
- **Base:** fund (m), exactly: its bucket shares by label, its equal split inside a bucket, V1's limits and V1's cost for moving money.
- **Over-cash curve.** For each bucket, the running product of (1 + the bucket's daily return − the cash line's daily return). A bucket's daily return is the plain average of its lines' returns (V2-08). The curve is worked out whether or not fund (w) holds the bucket.
- **Keep-fraction.** At the first session of each month, a bucket's votes = how many of these hold: its curve stands above its own value 63, 126 and 252 sessions ago. The bucket keeps votes ÷ 3 of the share fund (m) gives it. The rest goes to cash. This is the house trend rule (`core_v1.votes`) pointed at our own results instead of a market price.
- The fractions hold until the next month's first session. When the label changes inside a month, fund (m)'s new bucket shares are used with the fractions already set.
- The volatility cap and Brake V2 of fund (r), worked on fund (w)'s own curve.
- **Reduce only.** Fund (w) never holds more of a bucket than fund (m) does that day, and never touches a line's own rule.
- Needs 252 sessions of bucket returns before its first decision: the warm-up of V2-08.
- **Why this is walk-forward, and what is left out.** Each decision is fitted on a rolling window of past results and then judged on the month that follows. It re-fits the fund's weights. It does not re-fit any line's numbers: those are locked (rule 3). The deleted optimiser's tuning of stop and take-profit levels does not come back.
- Replay: fund (w) is in V2-02 step 4.
- Register `ALLOC-WALK.json`. One more try in the luck check for funds.
- Done when: a test where one bucket loses steadily for a year shows its share cut to zero at the next month start; a test proves fund (w) never holds more of any bucket than fund (m); a test proves that changing returns after a date changes no decision on or before that date.

### V2-26 The old walk-forward check — step 1 now; step 2 needs D17
**DONE 22 Nov 2026: step 1 in the status log; step 2 (D17 = A, Markus 22 Nov 06:22) PR #178, published 22 Nov.**
- **What it is** (VERIFIED at `2447d4a`): `trading-platform/analysis/arc2_walk_forward.py`, run by the job `nightly_walk_forward` in `trading-platform/core/scheduler.py` (Monday to Friday, 17:30 New York; in `_ALWAYS_ACTIVE_JOBS`). Each night it works out 30- and 90-day figures from closed trades for `oracle`, `spy_qqq_trend` and `jerome_macro`, grades each GREEN, AMBER, RED or INSUFFICIENT_DATA against stored reference numbers, and writes the grade to `bot_evaluation_history`. It is read by `routes/claude_report.py` (`_build_walk_forward_status` and the text section "WALK-FORWARD VALIDATION (ARC 2)"), `routes/reports.py` and the dashboard hook `artifacts/dashboard/src/hooks/useFleetData.ts`.
- **What is wrong** (VERIFIED: `_OOS_ENVELOPE` and `_STRATEGY_PARAMS` in that file): the reference numbers describe strategies these accounts no longer run. `oracle`: an Asia-Pacific fund trend rule, seeded 7 Aug 2026. `jerome_macro`: an emerging-markets rule, seeded 11 Aug. `spy_qqq_trend`: a 50/200-day average rule, numbers dated 14 Jul. Today the accounts run FLEET-V1-F1, FLEET-V1-C1 and MOMO-V2, whose live code was added on 2 Nov. A grade from this job says nothing about them. The protocol in the file's header (red for 60 days: halve size; 120 days: halt entries; done by hand) is not among the 2027 rules.
- **Step 1, now, no decision:** write in the Status log what the job wrote on the last five nights, and every place a person can see it. UNKNOWN from here.
- **Step 2, if D17 = A (recommended):** stop the job (remove it from the scheduler and from `_ALWAYS_ACTIVE_JOBS`), remove its section from the two reports and its status from the dashboard hook, and keep the table columns and their history. Mark the module retired in its first line; do not delete it in the same pull request. Publish with the market closed.
- **If D17 = B:** new reference numbers from the evidence table of V2-01, every grade labelled "information only", and the protocol text removed.
- Also left over from the deleted optimiser (section 2.5): the definition of the table `kraken_wfo_results` in `trading-platform/db/postgres.py`. Leave the table; note it in the Status log.
- Done when: the Status log holds the five-night report, and the job is stopped or re-seeded as Markus chose.

---

## 8. The January 2028 decision (amends roadmap Phase 4; all PROPOSED)

The line bars Markus agreed on 20 Nov stay. Added:

1. **What can be promoted is a fund, not a line.** Picking the best of two dozen lines after one year is picking mostly luck.
2. **Evidence is the replay plus 2027.** A line or fund with no replay (anything with AI or views in it) is judged only against the fund it sits on.
3. **A fund passes if, after costs, over its counted 2027 dates it:**
   - beat T-bills (Y-CASH); and
   - matched or beat the S&P 500, or came within 2 points a year with a worst fall at least one third smaller (the agreed numbers); and
   - did the same against the better of 60/40 and the permanent mix (Y-6040, Y-PERM); and
   - clears the luck check (deflated Sharpe 0.95) on replay and 2027 together, counting the funds as the tries.
4. **Which fund:** (r) by default. (m) replaces it only if (m) beat (r) by at least 1 point a year in 2027 and was not worse in the replay. (v) replaces (m) only if it beat (m) by 1 point after card costs. (c) replaces its base only if it beat (m) by 1 point after its AI bill. One point is the margin Markus agreed for (b) over (a).
   - **If D16 is yes:** (w) replaces (m) on the terms (m) had to meet against (r): 1 point a year in 2027 and not worse in the replay. And (c) must also have ended ahead of (w) over the dates both ran. An AI that cannot beat a short rule with the same powers has not earned its bill. If fund (w) was never built, this clause falls away.
   - If more than one of (v), (c) and (w) qualifies, take the one with the highest return after costs over the dates they all ran. A tie goes to the simpler: (w), then (v), then (c).
5. **Voices:** a voice keeps its place in 2028 only if its view line beat T-bills and at least 20 of its cards have been scored with more than half right.
6. **Beside every number:** the same figure after tax and in Australian dollars, against holding an index fund.
7. **If no fund passes, the answer is an index fund.** Unchanged, and still a valid result.
8. A passing fund runs on the real paper accounts for 3 months before any real money (roadmap Phase 4 item 4). That is when the code that turns a fund into orders is built.
9. **Read against the era.** Beside every fund: the days 2027 spent under each macro label and each flag, its return after inflation and against Y-GOLD, its result in other eras (V2-20, V2-21), and what its protections cost and saved (V2-24). No pass bar. It is there so the choice is made knowing what kind of year 2027 was, and what the fund did in other kinds.
10. **Score the thesis** (V2-23): every numbered expectation in `fund-thesis-2027.md` marked right or wrong, before the decision is discussed.

---

## 9. Real money (roadmap Phase 5): what is added

The staged steps (10%, 30%, 100%) and the conditions stay. Added before any money:
- The live brokers have confirmed in writing that they accept an Australian resident, and what converting Australian dollars costs.
- The holder and tax treatment are settled (V2-15).
- In the first year of real money, views and AI may only reduce or skip, whatever the shadows showed.
- Markus and his advisers have answered the long-view questions (research file, "Questions for real money"): one country, one broker and one currency, or more; what protects the account if a broker fails or a market shuts for months; whether some hard-asset holding should not depend on a US-listed fund. Not for Opus, and not advice.

---

## 10. Carried over, still open, unchanged

From the status log (20 Nov midday) and the code at `2447d4a`:
- **Phase 0:** arm the per-bot kill switch after Markus's yes (`.replit` still has `KILL_SWITCH_ARMED = "false"`, VERIFIED); the outside heartbeat (waiting for the monitor address); the gate, 7–11 Dec. Deleting the two dead `bots_state` rows (agreed, AU10): UNKNOWN whether done.
- **The lock:** version 1 registration files with the agreed pass bars (AU7) and dated model ids (AU8); `LEAGUE_VERSION` 0 → 1 (`twins/league.py`); `VERSION` → 2 (`twins/config.py`); `RUN_START` restarted once; the mirror tolerance number (`MIRROR_GUARD_PP` is a provisional 1.0).
- **2027:** no rule changes; month-end freeze and report; live-against-shadow gap each quarter.
- **From the 20 Nov audit:** the research paper rewritten once at the lock; the trading-API secret in the dashboard bundle (a blocker for any public dashboard). UNKNOWN whether either is done.
- **Front end:** the public Finance view on ddg.limited (old guide, front-end order 3). UNKNOWN whether done.

---

## 11. Limits and sources

**Not checked:** nothing was run. The live system, the database and the brokers were not read. The FRED ids and the feed addresses in V2-05, V2-10 and V2-18 are unverified, and so are the first dates and data addresses of the long series in V2-20 and V2-21. Every PROPOSED rule is untested by design. What the old walk-forward check writes each night was not read (V2-26 asks for it). Whether TAIL has daily bars in the nightly feed was not checked. Another agent was working in the repo: main was at `ceccb8a` (PR #171) at 13:20 on 21 Nov, and of the files named in V2-24 to V2-26 only `routes/claude_report.py` had changed since `2447d4a` (4 lines).

**Code and records:** `quant-terminal` at `2447d4a`; `research_harness/ledger.jsonl`; `docs/plans/finance-2027-plan.md`.

**Backdrop (close of Fri 20 Nov 2026).** The full list is in `macro-research-2026-11-21.md`, Part 9, tags [M1] to [M9]. The main ones:
- The Friday close: https://spectrumlocalnews.com/nc/coastal/business/2026/11/20/wall-street-nov-20-2026 · https://www.cnbc.com/2026/11/19/stock-market-today-live-updates.html
- Gold: https://cappnotes.substack.com/p/closing-look-friday-november-20-2026 · https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-q3-2026/central-banks
- Oil: https://www.nationthailand.com/news/world/40073488 · above US$100 in late October: https://www.babypips.com/analysis/financial-forex-market-weekly-recap-october-23-2026
- Dollar at a one-year high: https://www.advisorperspectives.com/commentaries/2026/11/17/gold-taken-punch-fed-could-throw
- Inflation and the central bank: https://kpmg.com/us/en/articles/2026/october-2026-cpi.html · https://stockanalysis.com/news/us-cpi-rises-october-2026/
- Yields: https://theedgemalaysia.com/node/826232 · https://alfred.stlouisfed.org/series?seid=DFII10
- Deficit: https://www.cbo.gov/publication/61986 · https://kfgo.com/?p=1374066
- Shares and bonds moving together: https://www.troweprice.com/financial-intermediary/us/en/insights/articles/2026/q4/resetting-expectations-for-diversification-twenty-twenty-seven-global-market-outlook.html

**The long view and the thesis:** `macro-research-2026-11-21.md` (sources in its Part 9) · `fund-thesis-2027.md`.

**Hedging and walk-forward (section 2.5).**
- Bought insurance on shares, tested on the Cboe index that buys a put option every month: https://www.aqr.com/Insights/Research/White-Papers/Pathetic-Protection-The-Elusive-Benefits-of-Protective-Puts · its numbers in short (July 1986 to May 2016: the same return as a plain mix of shares and cash, with a worst fall of 32.1% against 20.9%): https://www.cxoadvisory.com/equity-options/do-protective-equity-index-puts-work-well/
- Put options against trend rules as protection in a crash: https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/Journal-of-Systematic-Investing-Vol-1-Issue-1--Tail-Risk-Hedging-AQR.pdf?sc_lang=en
- Weigh the source: both papers are from AQR, a firm that sells trend funds. The index data they use is public, and Y-INS will show the same thing on our own record or it will not.
- The insurance fund inside Y-INS: https://cambriafunds.com/TAIL
- The floor rule and its usual multiplier of 4 or 5: https://en.wikipedia.org/wiki/Constant_proportion_portfolio_insurance
- The deleted optimiser and the old check: the git history of `quant-terminal` (commits `04f7eda9` added, `601704f7` archived, `1290ae65` deleted; `648b13c6` added the check).

**Tax:** https://www.ato.gov.au/individuals-and-families/investments-and-assets/capital-gains-tax/capital-gains-tax-reform · https://www.pwc.com.au/insights/federal-budget-tax-analysis-and-insights/investment.html

**View sources found:** https://podcasts.apple.com/us/podcast/talking-data/id1529310480 · https://podwise.ai/podcasts/29379 · https://lukegromen.substack.com · https://podwise.ai/podcasts/23343 · https://macrovoices.com/podcast-transcripts/1352-luke-gromen-why-the-gold-recycling-trade-is-accelerating
