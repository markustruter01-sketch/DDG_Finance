# MOMO-V2 plan: large-cap stock momentum with its own brakes — a FORWARD-ONLY paper experiment

Written by Claude (Fable 5.1), Mon 2 Nov 2026 ~19:10 Brisbane, after MOMO-V1
failed (its plan, Verdict section). Markus: stocks must be in the 2027
comparison; paper money is free; call it what it is.

## What this is and is not
- This is an **experiment run forward on Momentum's paper account from merge
  to 31 Dec 2027**. It makes **no claim from history**. Our only clean stock
  panel (2018-) has just shown it cannot be trusted for this question
  (survivorship, small-cap junk, one regime), so no backtest is run as
  evidence. An information-only backtest may be run later if someone wants
  to look; it cannot change the rules below.
- Attempt count after this plan: 10 stock-momentum attempts on this platform.
- Why it may work where MOMO-V1 did not: (1) the universe is the S&P 500's
  members, not "most traded", so the book cannot fill with speculative
  small caps; (2) 50 names instead of 20, closer to the diversified
  portfolios the literature measures; (3) the brakes read the **book
  itself**, not the S&P 500, so a momentum crash inside a healthy index is
  seen. Each of these is a documented reason MOMO-V1's design failed, not a
  tuned parameter.

## Rules (fixed now)
1. **Universe.** The S&P 500's current members (free source: State Street's
   SPY holdings file, published daily; fallback: the iShares IVV holdings
   file). Common stock only; one share class per company (the one in the
   index). Read on each monthly signal day; no history needed.
2. **Ranking.** 12-1 momentum: close 21 sessions ago / close 252 sessions
   ago − 1, from Alpaca daily adjusted bars. Top **50**, **equal weight** (2%
   of the invested amount each).
3. **Book index.** Each session, the equal-weight index of the *currently
   selected* 50 names (rebased at each monthly selection; a name's return
   series is its own). This is what the brakes read.
4. **Brakes (book-level).**
   - **Trend:** the book is held only while the book index's close is above
     its 100-session simple average (Gayed & Bilello's rule applied to the
     book, not the market). Below it: the whole book is sold to cash until
     the next monthly signal day on which it is above again.
   - **Volatility:** invested fraction s = min(1, 0.15 / vol20 of the book
     index), re-read daily, applied at the monthly rebalance and whenever the
     trend brake changes state. No gearing; never above 100%.
   - **Stops:** 20% below the fill price on every name, re-set at each
     rebalance (platform standing rule). A stopped name's 2% waits in cash
     until the next monthly selection.
   - The account's 15%/22% governor and the fleet kill switch apply on top.
5. **Rebalance.** Names re-ranked at the first session close of each month;
   trade at the next session (first hourly cycle). Between months, only the
   trend brake can trade (all out, or all back in at the current s).
6. **Cash.** SGOV.
7. **Costs assumed (for the shadow):** 5 bp per trade, SEC fee 0.3 bp on
   sales. Whole shares; $100k over 50 names is $2k a name, so sub-$2,000
   share prices are fine; any name whose price exceeds a 2% slot is skipped
   that month and reported.

## What is measured (the 2027 paper year, same days as the other accounts)
Return on total equity (vault included), Sharpe (excess T-bills), worst
fall, time in cash, trend-brake flips, stops hit, turnover, costs, and the
book index itself (so the brakes can be judged apart from the picks).

## Pass bar (31 Dec 2027; a fail is a fail)
1. Return ≥ S&P 500's + 2 points. 2. Worst fall no worse than −25% and no
worse than 0.75 × the S&P 500's. 3. Sharpe ≥ the S&P 500's. Passing one
paper year is not proof; it earns a second year and a registration.

## Live build (Opus, after FLEET-V1's test fix)
- `sleeve_runtime/momo_live.py` on Momentum's account: the executor FLEET-V1
  uses (whole shares, stops, SGOV parking, governor). Universe loader with
  the two declared sources and a fail-loud path (no list → no trade, alert).
  Book index and brakes computed from completed Alpaca bars each cycle;
  state (names, s, trend on/off, last signal day) in bots_state.metadata.
- Dashboard card: the 50 names with weights and P&L, s, the trend brake
  state, the book index vs its 100-day average, drawdown meter.
- Tests (synthetic): 12-1 ranking; equal weight 2%; trend brake uses the
  book index not SPY; s ≤ 1; no trade between months except the brake;
  stopped name excluded until the next selection; universe loader fails
  loud on an empty list.
- Fable: order-path review before merge.
