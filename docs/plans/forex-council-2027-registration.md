# Forex AI council — forward test registration (v3)

> Copy of the claude.ai Project doc `businesses/finance/forex-council-2027-registration.md` (11 Nov 2026). Registration text: do not edit; any change is a new dated version.

Version 3, written by Claude, Mon 9 Nov 2026 ~08:30 Brisbane. Replaces the 7 Nov PROPOSED v1 (council v2, start 4 Jan 2027).
Markus, 9 Nov 2026: restart everything now instead of 1 Jan; "I am okay with the drawdown rule". Rest of the pass bar below: shown to Markus 9 Nov, his explicit yes still to be confirmed.
Once confirmed, nothing below changes; any change is a new dated version reported separately.

## What is tested
- Forex AI council v3 (quant-terminal, live from 8 Nov 2026): three AIs (member 1 Groq, member 2 OpenRouter, member 3 Gemini) each pick a direction, strategy, conviction 1-5, stop and prediction per pair, once per New York trading day.
- Vote: 3-0 = full size, 2-1 = half size, no 2-vote majority = stay out. Stop = tightest of the winners.
- Inputs: prices/carry table for 7 USD pairs + central-bank and GDELT headlines.
- Sizing and stops by the rules engine (forex_risk.py): 0.5% risk per trade (half on 2-1), stop 1-4x ATR, max 4 trades, gross <= 2x NAV, no new trades after a 2% daily loss.
- Account: OANDA practice (paper).

## Period
- Start: the 6 Nov 2026 New York close (software restart; no broker reset). Start NAV: $99,586.58 (bot_daily_returns, 6 Nov). Single source in code: trading-platform/core/fleet_capital.py.
- First report: 30 Jun 2027 (report only, no pass/fail). Verdict: 31 Dec 2027.

## Measured (all reported, good or bad)
1. Return after spreads and financing (NAV).
2. Max drawdown of NAV.
3. Trades, win rate, average win / loss.
4. Against holding nothing (0%) and the registered baseline rule (FX-BT1), same days.
5. Scorecard: hit rate and average move at 1, 5, 20 trading days for each AI, the final call, the baseline; final calls by strategy and by conviction (1-5).
6. Predictions: predicted vs actual move per AI.

## Pass bar (at 31 Dec 2027, all of)
- Return after all costs > 0.
- Beats the baseline rule's scored result.
- Max drawdown <= 10% of start NAV. (Markus: OK, 9 Nov.)
- At least 60 closed trades (fewer = "not enough evidence").

## Stop rules
- NAV down 10% from start at any time: trading paused and reviewed with Markus (council keeps logging, no orders).
- A model/prompt change, or a provider failing 5+ days in a row: new dated version.

## Not in this version: conviction-based leverage
Markus asked (9 Nov) for higher leverage when the AIs are very sure. Not added: there is no evidence yet that the AIs' conviction predicts winners (their 1-day hit rate so far is ~37%, below the baseline's ~40%, on 74 calls). From 9 Nov the scorecard scores final calls by conviction. If high-conviction calls clearly win more often over a fair sample, a "conviction sizing" version can be registered as a new dated version and tested separately.

## Caveats
- The baseline rule lost ~1%/yr in the 2008-2026 backtest: beating holding nothing is the real bar.
- LLM councils can't be fairly backtested (models remember history); this forward test is the evidence.
- Free-tier model limits may change; outages are logged.
- Practice fills can differ from real-money fills.
