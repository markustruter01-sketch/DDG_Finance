---
name: Oracle OOS Validation Results
description: Out-of-sample backtest results for Oracle (Stock Trend Follower v1.0) — 5-window framework, MARGINAL verdict.
---

## Script
`kraken-bot/oracle_oos_validation.py`

## Parameters locked (from live code)
- EMA20/50, ADX14 (entry ≥25, exit <20), ATR14 ×2.0
- TRAIL_TRIGGER=2.5 (live constant in algo_scanner.py L74 — docstrings say 1.5, WRONG)
- RISK=1.5%/trade, 20% position cap, 5L+2S slots, 15td max hold, 5% kill switch DD
- Universe: 245 tickers, 244 loaded (HES skipped — no Yahoo data), warm-up from 2018-01-01

## Results by window

| Window    | Return  | Sharpe | MaxDD | WR   | Verdict |
|-----------|---------|--------|-------|------|---------|
| W1 2019   | +8.4%   | 0.625  | 13.1% | 54%  | PASS    |
| W2 2020   | +54.0%  | 1.822  | 17.4% | 54%  | PASS    |
| W3 2021   | +13.6%  | 0.733  | 13.8% | 57%  | PASS    |
| W4 2022   | -10.5%  | -0.423 | 19.1% | 46%  | FAIL    |
| W5 2023-24| +2.3%   | 0.154  | 19.0% | PASS |         |
| POOLED    | +67.8%  | 0.156  | —     | 51%  |         |

## Criteria (3/4 met — MARGINAL)
- ✅ Positive return+Sharpe ≥4/5 windows: 4/5
- ✅ No window MaxDD > 20%: all ≤19.1%
- ❌ Pooled Sharpe ≥ 0.5: only 0.156 (dragged by W4 2022 and weak W5 2023-24)
- ✅ Survived 2020+2022 stress: W2=17.4%, W4=19.1%

## VERDICT: ⚠️ MARGINAL

## Interpretation
- Strategy shows genuine edge (4/5 window passes, never breaches 20% DD)
- W4 2022 loss (-10.5%) expected: pure trend-follower in a rate-hike bear market
- Pooled Sharpe dragged low by W4 drag + W5 range-bound chop (2.3% in 2 years)
- Leveraged ETFs (TQQQ/SOXL/UPRO) in universe boost W2 2020 outsized (+54%)
- Shorts contributed modestly; short signal filter (RSI 25-60, ema20<ema50) is selective

## Skipped tickers per window
- W1 2019: ABNB, ARM, COIN, DASH, GEHC, HES, NU, PLTR, RBLX, SNOW (10 total)
- W2 2020: ARM, COIN, GEHC, HES, NU, RBLX (6 total)
- W3 2021: ARM, GEHC, HES (3 total)
- W4 2022: ARM, HES (2 total)
- W5 2023-24: HES (1 total)

## Fidelity compromises (7 flagged in script)
1. Daily bars (not live 15-min)
2. Shorts assume all shortable (no borrow check)
3. Min-hold 4h → 1 trading day
4. Kill switch 5% on daily open-to-close delta
5. After-hours crypto cycle excluded
6. TRAIL_TRIGGER=2.5 (corrected from docstring 1.5)
7. Indicators via pandas EWM ≈ Wilder (converges after ~50-bar warmup)
