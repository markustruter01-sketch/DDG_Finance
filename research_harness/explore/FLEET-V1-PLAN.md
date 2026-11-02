# FLEET-V1 plan: a three-sleeve fleet tested on forty years (declared before any data was pulled)

Written by Claude (Fable 5.1), Mon 2 Nov 2026 ~14:00 Brisbane. No index, yield,
gold, commodity or dollar history has been pulled into the harness for this plan,
and no FLEET-V1 code has been written or run, when this is committed.

## Why this exists (Markus, 2 Nov 2026)
- Platform goal: beat the S&P 500 on compounded return over 20 years, with a
  better Sharpe ratio and a smaller worst fall, through a possible recession.
  Everything free or built in-house.
- The audit of 2 Nov found that nothing in the repository has passed its own
  pre-registered test; the live G4 gearbox beat SPY on return (18.0% vs 15.2%,
  2021-2026) with an equal worst fall (-24.5%) and a statistically identical
  Sharpe (0.76 vs 0.74), and lost 41% in the 2000-2002 reconstruction. Its
  extra return is leverage, not signal. The fleet is one bet.
- This plan tests a fleet whose sleeves disagree with each other, on 35 years
  of exploration data and a 10-year held-out window, with the trial count
  declared and corrected for.

## Honesty notes (read before any result)
- **Attempt count.** Trend-timing attempts before this plan: at least 15
  (GEAR-V2-PLAN's count). This plan adds four candidates, so the deflated
  Sharpe ratio below is computed with N = 19 independent trials. If that is
  an undercount, say so in the result.
- **Hindsight.** The designer knows the broad history of every crisis in both
  windows, and that GEAR-V1 explored 2007-2020 and tested 2021-2026. The
  post-2021 window has been read twice for the same core and is **spent**: it
  is reported for information only, never as evidence. The 2011-2020 held-out
  window was inside GEAR-V1's exploration, but under different rules; it is
  the strongest honest option left. Every rule below is copied from published
  work (cited) or is a stated design value; nothing is fitted on our data.
- **Where any extra return comes from.** The leverage in the core when trends
  and volatility allow it. The trend ensemble and the volatility target exist
  to cut whipsaw and drawdown enough for the leverage to be survivable; the
  cross-asset sleeve exists for the years equities give back. If the unlevered
  candidate (C2 at 1.0x) matches the levered ones on Sharpe, it wins (simpler).
- **Reconstruction.** Real 2x ETFs start in 2006, real bond and gold ETFs in
  2002-2004. Before that every instrument is reconstructed from index levels
  and yields. Each reconstruction is calibrated against its real ETF where
  both exist and the measured gap is reported and carried as a haircut. The
  G4 stress test's reconstruction understated the real 2007-2020 drawdown by
  7.5 points; expect the same direction here.
- **Dividends.** S&P 500 total return is reconstructed from the price index
  plus Shiller's monthly dividend series. Nasdaq-100 dividends before 1999 use
  a declared constant 0.8% a year (its yield has ranged 0.5-1.2%); sensitivity
  at 0% and 1.5% is reported. All benchmarks use the same series.

## The fleet (all values fixed now; the candidate set is complete)

### Sleeve 1: geared equity core
Signal read once a day at the close on the S&P 500 total-return series;
trades go out at the next open.

1. **Trend votes.** Three time-series momentum tests on the S&P 500 TR
   series: the close is above its close 63, 126 and 252 sessions ago
   (Moskowitz, Ooi & Pedersen 2012; the 3/6/12-month ensemble is the
   harness's existing `blend_63_126_252`, declared 16 Oct for TREND-V1).
   Votes v = number of tests that are true, 0 to 3.
2. **Volatility scale.** s = min(1, 0.15 / vol20), where vol20 is the
   annualised 20-session realised volatility of the S&P 500 TR series
   (sample standard deviation of simple returns x sqrt 252). 15% is a design
   value: the long-run volatility of the S&P 500 and the "above its 200-day
   average" regime volatility (14.7%) reported by Gayed & Bilello 2016.
3. **Target exposure.** E = 1.5 x (v / 3) x s, capped at 1.5. E below 0.10
   is set to 0 (T-bills). So: three votes in calm markets = 1.5x; two votes =
   up to 1.0x; one vote = up to 0.5x; none = cash. Volatility only ever
   reduces exposure.
4. **Equity mix.** m = 60% S&P 500 / 40% Nasdaq-100 (design value: keeps the
   Nasdaq tilt that drove G4's return while cutting the concentration that
   drove its 2000-2002 fall).
5. **Instruments.** For each index i with mix share m_i: if E <= 1, hold the
   1x instrument at weight m_i x E. If E > 1, hold all available dollars
   (gross = 1 minus the 1% cash buffer) split as 1x weight m_i x (2 - E) and
   2x weight m_i x (E - 1), so that exposure = m_i x E. At E = 1.5 that is
   half 1x and half 2x, G4's structure. No borrowing ever; gross <= 1.0.
   Live instruments: SPY/SSO, QQQ/QLD. Idle cash: SGOV.
6. **Rebalance.** When the vote count changes, and at the first session
   close of each month (to the current E). Not on volatility changes alone.
7. **Stops.** 20% below the rebalance reference price on every holding,
   re-set at each rebalance (the platform's standing rule, copied from
   TREND-V1-B and G4). A stopped holding stays in T-bills until the next
   rebalance.

### Sleeve 2: cross-asset trend
Monthly, at the first session close of each month; trade at the next open.

1. **Lines (four).** US Treasury 10-year total return (live: IEF), gold
   (GLD), broad commodities (DBC), US dollar index (UUP). International
   equities are left out: no free daily history before 2001, and they add
   little in the crises this sleeve exists for.
2. **Trend call per line.** The same three-vote ensemble as sleeve 1 on the
   line's own series. Long when v >= 2, otherwise flat (T-bills). Long only;
   shorting is an owner decision not taken here.
3. **Weights.** Standard time-series-momentum sizing: w_i = (0.10 / vol63_i)
   / 4 for lines that are on, where vol63 is the 63-session annualised
   realised volatility; each capped at 0.40; gross <= 1.0 (scale down pro
   rata if the sum exceeds 1). 10% is the sleeve's volatility target (design
   value; diversified trend funds run 10-15%). The divisor is always 4 so
   weights do not inflate when fewer lines are on.
4. **Stops.** None: the monthly trend call is the exit (Hurst, Ooi &
   Pedersen 2017 use no stops). Recorded as a deliberate difference from the
   platform's standing rule.

### Sleeve 3: cash floor
SGOV (backtest: FRED DTB3 minus 0.50% a year, see Costs). Holds whatever
sleeves 1 and 2 are not using, plus the fleet's unallocated share.

### Fleet weights
F = 65% sleeve 1 + 35% sleeve 2, combined by the harness's existing rule
(`harness/fleet.py`: constant weights, rebalanced daily). Live accounts would
drift between monthly rebalances; the gap is reported from the forward shadow.

## Candidate set (complete; nothing may be added after seeing results)
| id | what |
|---|---|
| C1 | Sleeve 1 alone, mix 60/40, as above |
| C2 | Sleeve 1 alone, mix 100% S&P 500 (tests whether the Nasdaq tilt is needed) |
| F1 | 65% C1 + 35% sleeve 2 |
| F2 | 65% C2 + 35% sleeve 2 |

Reported alongside, never selectable:
| id | control or null |
|---|---|
| B | S&P 500 TR buy-and-hold |
| A0 | GEAR-V1-G4 exactly as registered, on the reconstructed instruments |
| N1 | Constant 1.2x S&P 500 (G4's average exposure) with no signal |
| N2 | Random-gear null: G4's time-in-gear shares, gear sequence shuffled in
|    | monthly blocks, 1,000 draws; the 95th percentile of Sharpe is reported |
| S2 | Sleeve 2 alone (so its standalone Sharpe and its correlation to B are visible) |

## Data (pulled later, in one go, into immutable datasets with manifest hashes)
Primary source Stooq (daily, free, long history); Yahoo chart API v8 as the
declared fallback for any series Stooq lacks; FRED for rates; Shiller for
dividends. Range 1985-01-01 to 2026-10-31.

| series | primary | fallback | real ETF for calibration |
|---|---|---|---|
| S&P 500 price | Stooq `^spx` | Yahoo `^GSPC` | SPY from 1993 |
| S&P 500 dividends (monthly) | Shiller `ie_data.xls` (econ.yale.edu) | multpl.com S&P dividend yield | |
| Nasdaq-100 price | Stooq `^ndx` | Yahoo `^NDX` | QQQ from 1999 |
| 10-year Treasury yield | FRED `DGS10` | | IEF from 2002 |
| Gold spot | Stooq `xauusd` | FRED `GOLDAMGBD228NLBM` to its end | GLD from 2004 |
| Commodities | Stooq `^spgsci` or Yahoo `^SPGSCI` (S&P GSCI) | declared fallback basket: equal-weight crude `cl.f`, copper `hg.f`, gold, rolled continuous from Stooq | DBC from 2006 |
| US dollar index | Stooq `usdidx` or Yahoo `DX-Y.NYB` | FRED `DTWEXM` (monthly, broad) | UUP from 2007 |
| 3-month T-bill | FRED `DTB3` | | |

Reconstructions (declared formulas):
- **S&P 500 TR** = price index with Shiller's monthly dividend reinvested on
  the first session of each month.
- **Treasury 10-year TR** from DGS10: daily return = -D x dy + y/252, with
  modified duration D = (1 - (1 + y/2)^-20) / (y/2) for a par 10-year bond,
  y the prior day's yield, dy the yield change (Swinkels 2019 method).
- **2x instruments** = 2 x the underlying's daily return - (DTB3 + 0.50%)/252
  borrowed on the extra 1x - fee/252, with fees SSO 0.89%, QLD 0.95%, UBT
  0.95%, UGL 0.95% a year (ProShares, read 2 Nov 2026).
- **Calibration**: for every reconstructed series with a real ETF, report the
  annualised return difference, the correlation of daily returns, and the
  max-drawdown difference over the overlap. The max-drawdown difference is
  the haircut applied (added) to every reported drawdown of a strategy that
  holds that instrument in the reconstructed era. Haircuts are reported, not
  fitted, and cannot change selection.

## Costs (assumptions stated, nothing omitted)
- Commission 0 (Alpaca). Half-spread + slippage per trade: 2 + 3 bp for SPY,
  QQQ, IEF, GLD; 5 + 5 bp for SSO, QLD, UBT, UGL, DBC, UUP (wider books).
  SEC fee 0.3 bp on every sale.
- Cash earns DTB3 minus 0.50% a year (Alpaca sweeps paid 3.56% against a
  ~4.0% T-bill rate in Sep 2026; SGOV's fee and spread are inside that).
- No borrowing, so no margin interest. No shorts, so no borrow fees.
- Whole shares in the real-ETF era; fractional in the reconstructed era
  (index levels), as the G4 stress amendment did.

## Windows
- **Warm-up**: 1985-10-01 (Nasdaq-100 start) to 1986-12-31.
- **Exploration**: 1987-01-01 to 2010-12-31 (includes 1987, 1990, 1994, 1998,
  2000-2002, 2008). Earlier bars are warm-up only.
- **Held-out**: 2011-01-01 to 2020-12-31. Untouched until ONE registered
  candidate is tested once. The harness lock is extended to cover it
  (Process step 1).
- **Spent**: 2021-01-01 to 2026-10-31. Reported for information only.
- **Rolling**: every 10-year window starting 1 Jan 1987 to 1 Jan 2011,
  stepped one year (25 windows), reported for exploration-period candidates.

## How the candidate is chosen (exploration, 1987-2010)
Among C1, C2, F1, F2 that satisfy ALL of: (a) CAGR >= B's; (b) Sharpe (excess
T-bills) >= B's + 0.10; (c) max drawdown, after haircut, no worse than -30%;
(d) Sharpe above N2's 95th percentile and above N1's: the one with the highest
Sharpe. Ties within 0.02 go to the simpler candidate (C2, C1, F2, F1). If none
qualifies, FLEET-V1 is FAILED and nothing is registered; no variant is tried.

## Pass bar for the held-out test (2011-2020, registered with the candidate)
All after costs and haircuts, against B on the same window:
1. CAGR >= B's.
2. Sharpe (excess T-bills) >= B's + 0.10.
3. Max drawdown no worse than -25% and smaller than B's.
4. Deflated Sharpe ratio (Bailey & Lopez de Prado 2014) with N = 19 trials,
   the exploration-period variance of Sharpe across candidates, and the
   held-out skew and kurtosis: probability > 0.95.
5. Rolling check: Sharpe above B's in at least 70% of the 25 rolling 10-year
   exploration windows (reported from exploration; a fail here is a fail).

A fail is reported as a fail. Reported every time: return, CAGR, volatility,
Sharpe (rf 0 and excess T-bills), max drawdown (raw and haircut), time at each
exposure level, vote changes, fills, stops hit, turnover, average and max
exposure, correlation to B, sleeve-2 standalone figures, every control and
null, the three dividend sensitivities, and the worst rolling 3-year stretch
against B.

## Before any live use (even if it passes)
- Fleet drawdown limits must be enforced (`ENFORCE_DRAWDOWN_LIMITS = True`,
  15% soft, 22% hard) and the kill switch armed. Owner decision.
- Alpaca paper fills logged against the backtest's assumed prices for 90
  days; the measured cost replaces the assumption in the next registration.
- Forward shadow (no orders) from registration; the public paper record from
  1 Jan 2027 with this pass bar published beside it.

## Process (who does what; "Opus" steps need no judgment, "Fable" steps do)
1. **Fable, now:** this plan is committed before any FLEET-V1 code or data.
2. **Opus:** make the hold-out lock mechanical. `harness/holdout.py` must
   check the registration's declared universe, window and single-use flag,
   and cover both 2011-2020 and 2021-2026 for FLEET-V1 registrations. Move
   post-2011 rows of the new datasets into a separate directory that only
   `registry.begin_run` may open.
3. **Opus:** data layer. `research_harness.fetch stooq|fred|shiller` commands;
   reconstruction module `research_harness/data/reconstruct.py` with the
   formulas above; calibration report `research_harness/data/calibrate.py`;
   one immutable dataset per source, manifests hashed. Run on the DDG -
   Finance Replit (this container cannot reach the vendors). Pull only the
   warm-up and exploration range first; the held-out and spent ranges are
   pulled into the locked directory by a separate command.
4. **Opus:** sleeves and tests. `sleeves/core_v1.py` (sleeve 1),
   `sleeves/xasset_v1.py` (sleeve 2), `explore/fleet_v1.py` (candidates,
   controls, nulls, rolling windows), `harness/overfit.py` (deflated Sharpe,
   random-gear null), all with synthetic-data tests in `tests/` proving no
   look-ahead (a shifted series must change the signal only after the shift),
   exposure caps, gross <= 1, and the 2x decomposition.
5. **Fable:** read the code once for look-ahead, sign errors and spec drift
   before any real data run. Fixes go in as commits that cite this plan.
6. **Fable:** one exploration run, result to `exploration_log.jsonl`;
   selection by the rule above; registration file written.
7. **Fable:** one held-out run, result to `ledger.jsonl`; verdict; report.
8. **Opus, in parallel from step 2:** platform cleanup per the audit (arm the
   kill switch, enforce limits, delete `POST /run` and the forex council,
   remove dead code). Never touches research_harness.
