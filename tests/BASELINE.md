# Test Baseline

Date: 2026-09-05

## Full suite

```text
Tracked test files: 38
Passed test files: 37
Failed test files: 1
Total tests collected: 560
Total tests passed: 559
Total tests failed: 1
Warnings: 1
```

Known failure:
`kraken-bot/test_bot2_momentum.py::test_first_trading_day_skips_weekend_and_january_holiday`

The failure is the pre-existing Bot 2 first-trading-day holiday behavior. No
other tests failed in the full workspace-root run.