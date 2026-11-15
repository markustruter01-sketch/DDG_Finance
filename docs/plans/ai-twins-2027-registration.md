# AI twins — forward test registration (TWINS-V2), PROPOSED
Written by Claude (Fable 5.2), Sun 15 Nov 2026 ~18:00 Brisbane, before any twin exists. Needs Markus's yes; then nothing below changes (any change = new dated version, reported separately).
Belongs to: `claude/finance-ai-twins-build-spec.md` (rules 8 and 12), `claude/finance-2027-plan.md` (item 17). Does not change the Forex council registration v3.

## The question
End of 2027, per bot: did it do better with the AI or without it?

## What is compared
| Bot | Without AI | With AI |
|---|---|---|
| 1, 2, 3 | the real paper account (rules only) | AI twin: pretend account, the 3-AI council picks the holdings |
| 4 Forex | rules twin: pretend account, fixed rule below | the real OANDA account (the AI council) |
Also shown beside each: "always fully invested" and "S&P 500 buy and hold" (Forex: S&P only).

## Period
- Start: the first session after the strategy lock (planned Mon 23 Nov 2026), every twin with its bot's real balance that day.
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
- Bot 3: the AI picks up to 50 from the bot's own top-150 momentum list.

## Measures (all reported, good or bad)
1. Total return after costs, 23 Nov 2026 – 31 Dec 2027. MAIN.
2. Worst fall (largest peak-to-trough drop of daily equity). SECOND.
3. Reported only: votes counted, missed votes, per-vote score at 5 and 20 trading days, turnover, AI cost in dollars, "veto only" result (derived), both baselines.

## Verdict per bot
- "Counts" only if all hold: the bot's mirror stayed inside its tolerance; missed votes at most 10% of voting days; at least 200 counted votes (Bots 1–3) or 60 closed trades on each side (Forex).
- Margin M = the larger of 2.0 percentage points and twice that bot's mirror tolerance. Differences smaller than M are a tie.
- AI BETTER: return higher by more than M, and worst fall not deeper by more than M.
- BOT BETTER: the same the other way round.
- MIXED: anything else.
- NOT ENOUGH EVIDENCE: a "counts" condition failed.
- Extra bar for Bots 1–3: an AI twin that does not beat "always fully invested" by more than M has shown nothing, whatever it did against the bot.
- For Forex the "bot" side is the rules twin and the "AI" side is the real account.
- Bots 1–3: only AI BETTER earns the AI a real account in 2028. Forex: only AI BETTER means the council has justified itself over the simple rule.

## Limits, stated up front
- One year, one market period. About 270 trading days. Bots 1 and 2 make few rule decisions, so their real side rests on roughly a dozen decisions.
- The pretend side has no real fills. The mirror measures that error; the margin covers it.
- Forex compares a real account with a pretend one; Bots 1–3 the other way round.
- The AI cannot be backtested (it remembers history). This forward record is the only evidence.
- The numbers 2.0 points, 10%, 200 votes and 60 trades are judgement calls made before any result, not derived.

## Stop rules
- A model or prompt change, or a member failing 5+ trading days in a row: new dated version; old and new both run 10 trading days; results reported per version.
- AI monthly cost cap hit: votes become "missed", never silently skipped.
- Mirror outside tolerance: that bot's twin results are flagged untrusted until explained.
