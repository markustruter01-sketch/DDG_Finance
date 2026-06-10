---
name: Oracle OOS Pass A baseline
description: First-ever Oracle OOS baseline — 5 windows, Alpaca SIP data, no MSE. These numbers are the baseline for Pass B comparison.
---

## Oracle OOS Pass A — Official Baseline (2026-06-10)

**Data source**: Alpaca SIP (consolidated tape, adjustment=all)  
**Range**: 2018-01-01 → 2024-12-31  
**Cache**: `trading-platform/.local/oos_data/universe_sip_2018-01-01_2024-12-31.pkl`  
**Universe**: 245/245 tickers loaded  
**Script**: `trading-platform/analysis/oracle_oos_validation.py`  

### Results

| Window  | Sharpe  | MaxDD  | WR    | Trades | TotRet  |
|---------|---------|--------|-------|--------|---------|
| 2019    | +1.411  | 6.6%   | 60.8% | 107    | +17.5%  |
| 2020    | +1.363  | 14.6%  | 53.3% | 150    | +33.7%  |
| 2021    | -0.153  | 13.0%  | 50.4% | 123    | -4.1%   |
| 2022    | -0.059  | 12.8%  | 44.9% | 136    | -2.7%   |
| 2023-24 | +0.561  | 17.0%  | 52.5% | 238    | +16.4%  |
| **POOLED (concat)** | **+0.599** | 17.0% | 52.4% | 754 | |

### Sanity gates: ALL PASSED
- No MaxDD ≥ 99% in any window (data-gap MTM bug absent)
- No single-day equity swing > 50%
- Trade counts plausible per window (107–238)
- 2020 COVID: kill-switch (≥5% daily DD) fired exactly 1 day during Feb-Mar crash

### Coverage — missing tickers per window
Missing = IPO after window start only (expected, excluded per-window):
- 2019: 13 missing (CRWD, NET, DDOG, PLTR, ARM, UBER, ABNB, DASH, SNOW, COIN, GEHC, RBLX, NU)
- 2020: 9 missing (PLTR, ARM, ABNB, DASH, SNOW, COIN, GEHC, RBLX, NU)
- 2021: 5 missing (ARM, COIN, GEHC, RBLX, NU)
- 2022: 2 missing (ARM, GEHC)
- 2023-24: 1 missing (ARM)

### Key architectural facts
- **IEX is banned for this run**: starts 2020-07-27, cannot cover 2019 or COVID warmup.
- **SIP confirmed**: 61 bars Q1-2018 each for SPY/AAPL/MSFT/XOM/JPM (HTTP 200).
- **No invented target**: the 0.156 figure was Jerome v2/Buck Futures (commodity ETFs, 12 tickers). Wrong strategy, discarded. This table IS the Oracle baseline.
- **Pass B success bar**: must be pre-registered explicitly by user before running MSE-augmented version. Pass B = MSE-augmented (CRISIS/BEAR/BULL gates, safe-haven rotation, vol sizing, cooldowns, sector caps) — NOT "transaction costs + slippage."
- **Strategy constants** (lock-step with algo_scanner.py): EMA20/50, ADX≥25 entry/<20 exit, ATR×2.0 stop, TRAIL_TRIGGER=2.5, RISK=1.5%, MAX_POS=20%, 5L+2S slots, MAX_HOLD=15d, KILLSWITCH=5% daily DD.
