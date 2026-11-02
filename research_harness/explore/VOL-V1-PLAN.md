# VOL-V1 plan: trend-gated S&P 500 put-writing (declared before any new run)

Written by Claude (Fable 5.1), Mon 2 Nov 2026 ~17:20 Brisbane, at Markus's
instruction (three accounts, three strategies, compared through 2027). No
VOL-V1 code exists when this is committed.

## Why this exists
- The variance risk premium: buyers of index put options pay more than the
  options are worth on average, because crash protection is valuable to
  them (Bakshi & Kapadia 2003; Carr & Wu 2009). Systematically selling that
  protection has earned equity-like returns at lower volatility for forty
  years: the CBOE S&P 500 PutWrite index (PUT) returned about the same as
  the S&P 500 from 1986 to the 2020s at roughly two-thirds of its
  volatility, with shallower drawdowns in slow bear markets (2000-02) and
  similar ones in fast crashes (1987, 2008, 2020).
- It is the second most documented premium after momentum, it is reachable
  with free data (CBOE publishes PUT's daily history) and free execution
  (Alpaca paper accounts allow cash-secured puts), and its bad months only
  partly overlap momentum's, so it is a real third leg next to F1 and MOMO.
- Honest framing: this is a Sharpe engine more than a return engine. It
  beats the S&P on return only in flat and slowly rising years; in a
  straight-up year it lags (the upside is capped at the premium).

## Honesty notes
- **Hindsight.** The designer has seen every year of the data. The forward
  paper year is the test; the history is a sanity check.
- **Attempt count.** Options strategies on this platform before this plan:
  0 pre-registered (an "options_state" folder exists; nothing was ever
  tested). N = 2 (this plan's candidates) + 19 (FLEET-V1's count, shared
  dial) = 21 for the deflated Sharpe, to be conservative.
- **Fast crashes.** A sold put loses roughly like the index on the way down
  until it is closed. The trend gate exits after a trend breaks, not before
  a gap. Expect losses of 15-25% in a 2020-style month; this is stated now
  so it is not a surprise later. The 22% account governor applies.
- **Modelling gap.** The PUT index sells one ATM monthly put on the whole
  notional, collateralised in T-bills, rolled at expiry. Live, the account
  sells a whole number of SPY contracts (100 shares each: about $65k
  notional per contract at today's prices), so a $100k account holds ONE
  contract and the rest in SGOV. Granularity is reported as a live
  difference and the shadow tracks the gap.

## The strategy (all values fixed now)
1. **Instrument.** SPY puts, standard monthly expiry, strike the nearest
   listed strike at or just below the SPY close on the signal day (ATM),
   cash-secured (collateral = strike x 100 per contract, held in SGOV).
2. **Gate (FLEET-V1's dial, unchanged).** Votes v on the S&P TR series over
   {63, 126, 252}; s = min(1, 0.15 / vol20). Target notional fraction
   **N = (v/3) x s, capped at 1.0** of account equity; N < 0.10 -> no puts.
3. **Roll.** On the first session of each month at the close: close any
   open put (buy to close at the next open) and sell the new month's put for
   the number of contracts = floor(N x equity / (strike x 100)). Between
   rolls, if the vote count drops so that N falls below 0.10, close at the
   next open and stay out until the next roll.
4. **No stops on the option** (the gate is the exit); **no leverage**: the
   number of contracts is always covered by cash.
5. **Cash.** SGOV.

## Candidates (complete)
| id | what |
|---|---|
| V1 | As above (ATM, monthly, N = (v/3) x s) |
| V2 | As above but 2% out of the money (strike at or below 0.98 x close): less premium, fewer losses; tests whether the gate or the strike should carry the risk |

Controls and nulls (reported, never selectable): B (S&P 500 TR); PUT (the
CBOE index, ungated, same window: what the gate adds); N1 (gated SPY
holding at the same N: is the premium worth more than just owning the
index at that size); F1 on the same window.

## Data
- CBOE PUT index daily history (free download from cboe.com; declared
  primary). Fallback: none free at daily frequency; if the download is
  unavailable the plan STOPS and reports.
- Backtest method: the strategy's return on a day = the gate's N applied to
  the PUT index's daily return, plus (1 - N) x cash. V2 (2% OTM) cannot be
  built from PUT alone; it is estimated as PUT with the premium scaled by a
  declared factor of 0.70 and the loss floor raised by 2% of notional,
  flagged as an approximation, and judged live rather than historically.
- Gate series: FLEET-V1's SPY adjusted and DTB3 datasets.
- Costs: 2 bp of notional per roll leg plus $0.65 per contract; cash
  DTB3 - 0.50%.

## Windows
Warm-up 1986-07..1987-12; **exploration 1988-01-01..2010-12-31**; **held-out
2011-01-01..2020-12-31** (locked rows; one read, under the FLEET-V1 lock
mechanism with a new registration); spent 2021-2026 information only;
**forward paper 2027** is the test that counts.

## Selection (exploration)
Among V1, V2 satisfying ALL of: (a) Sharpe (excess T-bills) >= B's + 0.15;
(b) max drawdown no worse than -25% and no worse than 0.6 x B's; (c) CAGR
>= B's - 1 point; (d) Sharpe above PUT's (the gate must add something): the
higher CAGR; ties within 0.5 point to V1. None -> VOL-V1 FAILED.

## Pass bar (held-out 2011-2020; again for the 2027 paper year)
1. Sharpe >= B's + 0.15. 2. Max drawdown no worse than -25% and no worse
than 0.6 x B's. 3. CAGR >= B's - 1 point. 4. Deflated Sharpe > 0.95, N = 21.
A fail is a fail.

## Live (Alpaca paper, Bullion's account, from merge)
New executor (`sleeve_runtime/vol_live.py`) on Alpaca's options API: sell to
open / buy to close, limit orders at the mid with a 2-tick allowance,
cancelled and re-tried on the next hourly cycle if unfilled; the contract
count is never more than cash covers; collateral in SGOV is sold only as
needed. Assignment: if a put is assigned, the SPY shares are sold at the
next open and the roll continues. The kill switch's missing-stop check must
treat short puts as covered when the cash is there (a stop-policy entry,
as FLEET-V1's cross-asset lines). Daily shadow of the model's return vs the
account's from day 1.

## Process
1. Fable: this plan. 2. Opus: PUT data pull (Replit), `sleeves/vol_v1.py`
(gate x PUT model), `explore/vol_v1.py`, tests. 3. Fable: review, one
exploration run, registration, one held-out run. 4. Opus: options executor
and live runtime, dashboard panel; this is the largest new plumbing on the
platform and ships last. 5. Fable: order-path review (assignment, cover,
collateral) before merge.
