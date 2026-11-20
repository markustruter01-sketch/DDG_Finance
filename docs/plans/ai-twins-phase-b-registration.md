# AI twins Phase B — build and additions (TWINS-V2, audit AU6)
Written by Claude (Opus 5.5), Fri 20 Nov 2026 ~13:30 Brisbane. Markus said yes to AU6 on 20 Nov 12:34 Brisbane. This file adds to `ai-twins-2027-registration.md` (TWINS-V2); it changes nothing in it. Registered when merged; a change after that = a new dated version.

## What is built (code: `trading-platform/twins/ai_council.py`)
- **AI twins of Atlas, Atlas V2 and Momentum** exactly as TWINS-V2 describes: the three Forex council members (same models, same model-calling code) each reply with target weights; 3 valid replies = average, 2 = average of two, fewer = missed vote (hold). An invalid reply (a symbol off the list, a negative weight, weights above the limit, more than 50 names for Momentum) counts as no reply.
  - Atlas: SPY, QQQ, SSO, QLD, IEF, GLD, DBC, UUP. Atlas V2: SPY, QQQ, SSO, QLD. Momentum: up to 50 names from its top-150 by 12-1 momentum. All: weights add to at most 1.0 (no borrowing; 2x funds allowed), the rest in T-bills (BIL), the bot's stop (20%).
  - Start: the night after the first night the code runs, with the bot's real balance as its mirror twin last recorded it.
- **New: "AI may reduce or skip" twins** of three league lines: T-15X, S-MOMO-CAP, D-XTREND. The AI sees the line's rule weights and may keep 0% to 100% of each holding. It cannot add or increase anything. Not mentioned = kept. The rest goes to T-bills. Start balance 100,000 fake dollars. Same engine, costs and stops as the line.
- **What the models see**: today's date and, per asset, its 20-, 63- and 252-session return, 20-session volatility, whether it is above its 200-session average, and the twin's current weights (and the rule weights for the reduce-or-skip twins). No news, no account details.
- **When**: once per US session, at the end of the nightly twins job (after the 17:15 New York close run); filled at the next session's open by the engine. A twin votes at most once per session.
- **Record**: every model call is kept (append-only `twin_votes`): prompt, reply, model, tokens' cost, time taken, and why a reply was rejected.

## AI cost
- Cost per call = tokens x list price (USD per million tokens, checked 20 Nov 2026): Groq gpt-oss-120b 0.15 in / 0.60 out; OpenRouter Nemotron ":free" 0 / 0; Gemini 3 Flash preview 0.50 in / 3.00 out.
- INFERRED: Gemini's hidden "thinking" tokens may be missing from the count the council code returns, so its cost can be understated. UNKNOWN: whether the Gemini key is on a free tier (then the real cost is 0).
- Charged to each AI twin's balance monthly: a month's total comes off from the first valued day of the next month.
- **Cap (PROPOSED, needs Markus's yes): 10 US dollars a month for all AI twins together.** When reached, votes become "missed", never silently skipped.

## Not in this build
- The Forex rules twin (Bot 4's "without AI" side): the Shadow League line FX-BT1 already runs this rule on daily bars; the hourly-fill version TWINS-V2 describes is not built yet.
- The Forex council's own AI cost charged to the Forex mirror twin: the council records no token cost today.
- Dated model ids: pinned at the lock (AU8) as a new version.

## Pass and verdict
As TWINS-V2 for the bot AI twins. The reduce-or-skip twins are reported beside their league line (same dates): return after costs, worst fall, days with a reduction, AI cost. Proposed verdict, same margin as TWINS-V2: AI helped if its return is higher by more than 2.0 points and its worst fall not deeper by more than 2.0 points; luck check as TWINS-V2. Goes into the version 1 files at the lock.
