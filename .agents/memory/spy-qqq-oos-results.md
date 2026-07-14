---
name: SPY/QQQ OOS validation results
description: Results of spy_qqq_oos_validation.py harness run. Pre-registered, no tuning.
---

## Verdict: MARGINAL (fails 2022 survivability)

| Window | Return | MaxDD | Sharpe |
|--------|--------|-------|--------|
| 2019   | +5.2%  | 5.0%  | 0.926  |
| 2020   | +15.5% | 8.9%  | 1.275  |
| 2021   | +7.8%  | 4.1%  | 1.060  |
| 2022   | -5.0%  | 5.0%  | -1.889 |
| 2023-24| +17.0% | 7.1%  | 1.143  |
| POOLED |        |       | 0.877  |

## Pass criteria results
- Pooled Sharpe ≥ 0.5: ✓ PASS (0.877)
- MaxDD ≤ 20% every window: ✓ PASS (worst 8.9%)
- Positive in 2020: ✓ PASS (+15.5%)
- Positive in 2022: ✗ FAIL (-5.0%)
- ≥3/5 positive: ✓ PASS (4/5)

## Key findings
1. **2022 failure is structural**: 4 quick entries in Jan 2022 (EMA50 still above EMA200 at year open), all exited via `price_below_ema50` within 2 weeks. Bot then sat in cash the rest of 2022. MaxDD only 5.0% — capital well protected. The loss is mechanically unavoidable; EMA cross confirmed bear market ~2 weeks too late.

2. **3-day exit (Discrepancy #2) dominated turnover** — as-coded (all-80-bars scan):
   - 2020: 45/57 trades (79%) were 3-day exits
   - 2023-24: 24/52 trades (46%) were 3-day exits
   - Pathological whipsaw: once any 3-day drop enters the 80-day window, bot exits → re-enters next bar → exits again next min-hold → repeat. Fixed in bot2 safety fixes (last-3-bars only).

3. **2022 re-run with fix #2**: identical result (-5.0%, 0 3-day exits). Fix #2 does not change 2022 outcome.

4. **TP2 almost never fires**: 4 total fires across 6 years. 3-day exit churn prevented positions from holding long enough to hit +12%. TP2 is effectively dead code as-coded.

5. **Trailing stop never fired** in any window — EMA50 and 3-day exits always closed first.

## Harness file
`kraken-bot/spy_qqq_oos_validation.py` — standalone, reads Yahoo Finance, no DB/Alpaca.
