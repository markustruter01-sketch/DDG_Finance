# AI twins — forward test registration (TWINS-V2)
Written by Claude (Fable 5.2), Sun 15 Nov 2026 ~18:00 Brisbane, before any twin exists. Markus: "Yes, I agree" (15 Nov 17:50), then audited once more as an outsider (changes listed at the end). Registered when merged to main; after that nothing below changes (any change = new dated version, reported separately).
Belongs to: `claude/finance-ai-twins-build-spec.md` (rules 8 and 12), `claude/finance-2027-plan.md` (item 17). Does not change the Forex council registration v3.

## The question
End of 2027, per bot: did it do better with the AI or without it?

## What is compared
| Bot | Without AI | With AI |
|---|---|---|
| 1, 2, 3 | the bot's mirror twin (the real account's own holdings, through the pretend-account engine) | AI twin: the 3-AI council picks the holdings |
| 4 Forex | rules twin: fixed rule below | the Forex mirror twin (the real AI account's holdings, through the engine) |
- Both sides of every verdict go through the SAME engine, so an engine or cost error hits both alike. The real account is the proof that the mirror is true (it must stay inside its tolerance), and is always shown beside it.
- Also shown beside each: "always fully invested" and "S&P 500 buy and hold, dividends included" (Forex: S&P only).

## Period
- Start: the first session after the strategy lock (planned Mon 23 Nov 2026), every twin with its bot's real balance that day.
- Both sides of a verdict are measured over the SAME dates. If a bot's AI twin (or the Forex rules twin) starts later than 23 Nov, that bot's verdict runs from that later date for both sides.
- First report 30 Jun 2027 (report only). Verdict 31 Dec 2027.
- The week before the start is rehearsal: not counted.

## Forex rule (the "without AI" side for Bot 4)
The baseline already registered as FX-BT1 on 11 Oct 2026, before any data was pulled. No new rule, nothing tuned.
- Pairs: EUR_USD, USD_JPY, GBP_USD, AUD_USD, USD_CAD, USD_CHF, NZD_USD.
- Once per New York day, after the 17:00 close, per pair: LONG if close > 100-day average and 63-day return > 0; SHORT if close < 100-day average and 63-day return < 0; else FLAT.
- Stop: 2.0 x ATR(14), fixed at entry. Exit when the call changes or the stop is hit. A stopped pair may re-enter at the next daily decision if its call still stands.
- Size: 0.5% of equity risked to the stop. At most 4 open; if more qualify, strongest first by |63-day return| / (ATR/close). Gross at most 2.0x equity.
- Fills: next hourly bar's open after the decision (FX-BT1 filled at the daily close; this is the one difference, forced by "no hindsight").
- Costs: measured spread and OANDA financing (financing must be in the engine before the first counted day; review condition A).
- Known history (FX-BT1, 2008–Oct 2026, hypothetical, financing left out): −17.6% total, worst fall −33.9%, 792 trades, 24.5% wins. Expect this rule to make about nothing. A different rule would give a different answer; this one was fixed first.

## AI twins (Bots 1–3)
- Same asset list as the bot, same leverage limit, same stop rule, same costs.
- Council: the three Forex council members, model ids pinned and dated, lowest randomness. One vote per trading day after the close: target weights. 3 valid replies = average of the three; 2 = average of the two; fewer = missed vote (hold).
- An invalid reply (outside the list or the limit) counts as no reply.
- A vote is refused if it is written after the bar it would fill on has opened.
- The AI's running cost in dollars is charged to the AI twin's balance each month. For Forex the council's cost is charged to the mirror side the same way.
- Versions chain: when a model or prompt changes, the new version carries on the same pretend account. The verdict is on the whole chain; each version is also reported on its own.
- Bot 3: the AI picks up to 50 from the bot's own top-150 momentum list.

## Measures (all reported, good or bad)
1. Total return after costs, 23 Nov 2026 – 31 Dec 2027. MAIN.
2. Worst fall (largest peak-to-trough drop of daily equity). SECOND.
3. Reported only: votes counted, missed votes, per-vote score at 5 and 20 trading days, turnover, AI cost in dollars, "veto only" result (derived), both baselines.

## Verdict per bot
- "Counts" only if all hold: the bot's mirror stayed inside its tolerance; missed votes at most 10% of voting days; at least 200 counted votes (Bots 1–3) or 60 closed trades on each side (Forex).
- Margin M = 2.0 percentage points. Differences smaller than M are a tie.
- AI BETTER: return higher by more than M, and worst fall not deeper by more than M.
- BOT BETTER: the same the other way round. (Forex: the "bot" side is the rules twin.)
- MIXED: anything else.
- NOT ENOUGH EVIDENCE: a "counts" condition failed.
- Luck check, attached to every AI BETTER or BOT BETTER: take the daily return of one side minus the other; t = average / (standard deviation / square root of the number of days). "CLEAR" if t is 2.0 or more in the winner's favour; otherwise "COULD BE LUCK".
- Extra bar for Bots 1–3: an AI twin that does not beat "always fully invested" by more than M has shown nothing, whatever it did against the bot.
- What a verdict earns: AI BETTER + CLEAR earns the AI a real account in 2028 (Forex: the council has justified itself over the simple rule). AI BETTER + COULD BE LUCK earns another year of the same test, nothing more. Anything else: the rules stay in charge.
- If this verdict and the Forex council's own registration (v3, scorecard against the baseline) disagree, both are reported; this account-level result answers the with/without question.

## Limits, stated up front
- One year, one market period. About 270 trading days. Bots 1 and 2 make few rule decisions, so their real side rests on roughly a dozen decisions.
- The pretend side has no real fills. The mirror measures that error; the margin covers it.
- Forex compares a real account with a pretend one; Bots 1–3 the other way round.
- The AI cannot be backtested (it remembers history). This forward record is the only evidence.
- The numbers 2.0 points, 10%, 200 votes, 60 trades and t of 2.0 are judgement calls made before any result, not derived.
- Expect COULD BE LUCK. Two geared share strategies can differ by many points in a year by chance; a CLEAR result in one year needs a large, steady edge. Four bots are judged, so one lucky "better" is likely; that is why luck is tested per bot.
- Outages and pauses hit the real bot (and so its mirror) but not the AI twin, which only misses votes. Sessions a bot spent paused are counted and shown; above 5% of sessions the verdict is flagged "bot was held back".
- The council members today are free-tier or preview models. They may be withdrawn or changed by their providers during the year; each change is a new version (see chain rule).

## Stop rules
- A model or prompt change, or a member failing 5+ trading days in a row: new dated version; old and new both run 10 trading days; results reported per version.
- AI monthly cost cap hit: votes become "missed", never silently skipped.
- Mirror outside tolerance: that bot's twin results are flagged untrusted until explained.

## Record keeping for the year-end (build requirements)
- Month-end freeze: on the first day of each month the figures for the month just ended (each twin's equity, return, worst fall, votes, missed, AI cost, last decision hash) are written once to an append-only table and never recomputed. The nightly replay may revise history when price data is revised; any difference from a frozen figure above 0.1 points is shown, not hidden.
- Off-site copy: the same month-end figures and each twin's last decision hash are committed to GitHub monthly, so the record survives the loss of the database and a cut-off decision log can be detected.
- Year-end numbers are produced by code written before the first counted vote, from this document. No hand calculation.

## Changes from the version shown to Markus at 17:45 (outsider audit, same evening, before any twin existed)
1. Both sides of each verdict now go through the same engine (mirror vs AI twin), instead of real account vs pretend account.
2. Luck check added; a real account in 2028 needs AI BETTER + CLEAR (stricter than before).
3. AI cost is charged to the AI side.
4. Model/prompt versions chain into one account.
5. Same dates for both sides; pause days counted and flagged.
6. Month-end freeze and off-site copy.
7. Margin simplified to 2.0 points (the mirror tolerance now guards the engine, not the margin).
