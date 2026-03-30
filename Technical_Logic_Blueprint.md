# AlgoEdge & Davy Jones — Complete Technical Reference Whitepaper
## AI-Driven Quantitative Trading Platform — Full System Architecture Document

> **Audit Notice:** This document is a complete, self-contained description of every algorithm, rule, risk system, data flow, and architectural decision in this platform. It is written to enable an independent AI or human auditor to fully evaluate the system's design quality, risk management soundness, and overall fitness for purpose — without access to the source code. Every section covers intent, mechanics, mathematical formulas, and design tradeoffs.

> **Last Updated:** March 2026 — reflects Hybrid Agentic Architecture Stages 0–4

---

## System Map

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ALGOEDGE AI TRADING ECOSYSTEM                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌─────────────────────────────┐    ┌──────────────────────────────────┐   ║
║  │  PLATFORM A: ALPACA BOT     │    │  PLATFORM B: DAVY JONES (KRAKEN) │   ║
║  │  (Equities + Crypto)        │    │  (Crypto 24/7 Mean Reversion)    │   ║
║  │                             │    │                                  │   ║
║  │  ► Groq Llama 3.3 70B LLM   │    │  ► RSI + Z-Score mean reversion  │   ║
║  │  ► Alpaca Paper Trading      │    │  ► Adaptive parameter self-tuning│   ║
║  │  ► RAG Learning Loop         │    │  ► OFI / VAMP / VPIN micro alpha │   ║
║  │  ► Gemini Self-Critic        │    │  ► Leaky-bucket penalty tracker  │   ║
║  │  ► VaR Circuit Breaker       │    │  ► Shared risk library           │   ║
║  └──────────────┬──────────────┘    └────────────────┬─────────────────┘   ║
║                 │                                    │                      ║
║                 └────────────┬───────────────────────┘                      ║
║                              │                                               ║
║                    ┌─────────▼─────────┐                                    ║
║                    │  SHARED CORE LIB  │                                    ║
║                    │  RiskProfile      │                                    ║
║                    │  ExitBracket      │                                    ║
║                    │  CircuitBreaker   │                                    ║
║                    │  DataValidator    │                                    ║
║                    └─────────┬─────────┘                                    ║
║                              │                                               ║
║              ┌───────────────┼───────────────┐                              ║
║              ▼               ▼               ▼                              ║
║  ┌───────────────┐  ┌──────────────┐  ┌────────────────┐                   ║
║  │  PostgreSQL   │  │  Dashboard   │  │ AlgoEdge SaaS  │                   ║
║  │  (Trade Log,  │  │  (React 19)  │  │ (Public SaaS)  │                   ║
║  │  Vault, etc.) │  │              │  │                │                   ║
║  └───────────────┘  └──────────────┘  └────────────────┘                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

# PART A: THE ALPACA AI TRADING PLATFORM

---

## Section I — Mathematical Core: Price Signal Computation

### Simple Explanation

> **Think of it like this:** Imagine you're watching the price of a stock. Instead of just looking at today's price, the system calculates *averages* over the past few months to understand the trend. If the current price is above the average, things are going up. If it's below, things are going down. It also checks if a stock has gone up too fast recently (like a basketball that got thrown upward — it'll come back down). All these numbers feed into the AI, which then decides what to buy.

```
 PRICE TREND DETECTOR
 ─────────────────────
  Today's price:  $150        🔼 ABOVE both averages → Positive Momentum
  3-month average: $140
  6-month average: $130

  Today's price:  $120        🔽 BELOW both averages → Negative Momentum
  3-month average: $140
  6-month average: $130

 RSI HEAT GAUGE  (0 = freezing cold, 100 = overheating)
 ────────────────────────────────────────────────────────
  [============================░░░░░░░░░░░░] RSI 60 → Normal
  [==========================================] RSI 75+ → OVERHEATED ⚠
  [═══░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] RSI 25- → Oversold 📉
```

### Advanced Technical Specification

#### 1.1 Dual-Timeframe Moving Average Momentum

The system's primary directional signal derives from a dual-timeframe momentum framework applied across a fixed multi-asset universe. For each asset, two Simple Moving Averages (SMAs) are computed from daily closing prices with a six-month lookback window via the Alpaca Market Data API.

- **3-Month SMA (MA₆₃):** `MA₆₃ = (1/63) × Σ Close_{t-i}` for i = 0 to 62
- **6-Month SMA (MA₁₂₆):** `MA₁₂₆ = (1/126) × Σ Close_{t-i}` for i = 0 to 125

An asset is classified as having "positive momentum" when `Close_latest > MA`. Both momentum labels (`momentum_3mo`, `momentum_6mo`) are passed as structured fields to the LLM prompt.

#### 1.2 SPY 20-Day EMA Anchor (v4.3+)

A critical hardened gate uses the SPY 20-day Exponential Moving Average as a macro anchor for Bull regime confirmation. Unlike the SMA, the EMA applies decaying weights:

`EMAₜ = Closeₜ × k + EMA_{t-1} × (1 - k)` where `k = 2 / (20 + 1) ≈ 0.0952`

The flag `spy_above_ema_20 = (SPY_Close > EMA_20)` acts as a **hard gate**: even if the LLM classifies the regime as Bull, Bull-regime allocations (including leveraged risk) are blocked unless SPY is above its 20-day EMA. This prevents the LLM from chasing false rallies.

#### 1.3 RSI — Relative Strength Index

RSI is calculated using Wilder's smoothing method across a 14-period lookback:

```
Step 1: For each bar t, compute:
  Gain_t = max(Close_t - Close_{t-1}, 0)
  Loss_t = max(Close_{t-1} - Close_t, 0)

Step 2: Wilder smoothed averages:
  Avg_Gain = EMA(Gain, alpha=1/14)
  Avg_Loss = EMA(Loss, alpha=1/14)

Step 3: RSI = 100 − [100 / (1 + Avg_Gain / Avg_Loss)]
```

Thresholds: RSI > 75 → "overheated" (50% notional cut). RSI < 25 → "oversold" (mean-reversion candidate in Sideways regime).

#### 1.4 Z-Score Statistical Deviation

Measures how many standard deviations the current price deviates from its 200-day mean:

`Z = (Price_latest − μ₂₀₀) / σ₂₀₀`

where μ₂₀₀ = arithmetic mean of 200 trailing closes and σ₂₀₀ = their standard deviation.

**Z > 2.0 triggers a 50% notional allocation cut** — a deterministic Python guardrail that fires *after* LLM allocation but *before* order placement. The redirected capital goes to SGOV. This is not an LLM decision and cannot be overridden by the model.

#### 1.5 Realized Volatility

20-day rolling log-return standard deviation, annualized:

`r_d = ln(P_t / P_{t-1})`  
`Vol₂₀d = √(Var(r_{last 20}) × 252) × 100`  (expressed as %)

The internal Market Fear & Greed Index incorporates volatility: Vol < 12% → +5 "calm" score; Vol > 30% → −10 "volatile" penalty.

#### 1.6 2× ATR Volatility-Adaptive Trailing Stop (Ratchet)

ATR uses a 14-period lookback on 30 days of OHLC data:
- `TR_t = max(High_t − Low_t,  |High_t − Prev_Close_t|,  |Low_t − Prev_Close_t|)`
- `ATR = (1/14) × Σ TR_{t-i}` for i = 0 to 13

Initial stop at fill: `Stop_0 = Fill_Price − (2.0 × ATR)` (1.5× ATR for leveraged ETFs)  
Fallback if ATR unavailable: `Stop_0 = Fill_Price × 0.98`  
Floor: `max($0.01, Stop_0)`

**Ratchet rule (one-way only):**  
`Proposed = Current_Price − 2.0 × ATR`  
If `Proposed > Current_Stop`: update stop, cancel/replace GTC order on broker.  
If `Proposed ≤ Current_Stop`: do nothing. The stop never widens.

Ratchet state persisted to `ratchet_stops` PostgreSQL table (symbol, stop_price, fill_price, atr, last_updated).

---

## Section II — Extended Asset Universe and Regime Classification

### Simple Explanation

> **Think of it like this:** The system trades 19+ different investments — from regular stocks (SPY, QQQ) to gold (GLD), bonds (TLT), crypto (Bitcoin), and even special "turbo" stocks (TQQQ, SOXL) that move 3× as much as the market. It sorts all of these into three moods: **Bull** (everything's going up — take risks), **Bear** (market's crashing — hide in safe stuff), or **Sideways** (confused — sit in cash or play small). The AI decides which mood we're in and acts accordingly.

```
 THE ASSET UNIVERSE
 ──────────────────────────────────────────────────────────────────
 🏦 EQUITIES:   SPY  QQQ  XLK  XLF  XLV  XLE  IWM
 🛡 SAFE HAVEN: TLT  IEF  GLD  SLV
 🛢 COMMODITY:  USO  PDBC
 ₿  CRYPTO:     BTC/USD  ETH/USD
 ⚡ TURBO:      TQQQ  SOXL  UPRO   ← 3× leveraged, Bull-only!
 💵 CASH:       SGOV

 REGIME DECISION TREE
 ───────────────────────────────────────
 GDP up? VIX low? Stocks above averages?
   ├── YES → BULL  → 3-7 risk assets
   └── NO  → Are things crashing?
               ├── YES → BEAR → 1-4 safe havens
               └── MAYBE → SIDEWAYS → 0-3 mean-reversion / cash
```

### Advanced Technical Specification

#### 2.1 Asset Universe (v4.3)

The system trades across 22 instruments in five categories:

| Category | Tickers | Order Type | Min Notional |
|---|---|---|---|
| Equities (Sectors) | SPY, QQQ, XLK, XLF, XLV, XLE, IWM | DAY | $100 |
| Safe Havens / Bonds | TLT, IEF, GLD, SLV | DAY | $100 |
| Commodities | USO, PDBC | DAY | $100 |
| Crypto Spot | BTC/USD, ETH/USD | GTC | $25 |
| Leveraged Risk | TQQQ, SOXL, UPRO | DAY | $100 |
| Cash Equivalent | SGOV | DAY | $100 |
| Vault (Auto-Sweep) | JEPQ | DAY | $1.00 |

#### 2.2 Regime Classification Matrix

The LLM receives structured data and is instructed to classify the macro regime:

| Regime | Conditions | Permitted Allocations |
|---|---|---|
| **Bull** | GDP growth, VIX < 20, positive momentum, SPY above EMA-20 | 3–7 risk assets including leveraged risk |
| **Bear** | Recession signals, rising unemployment, VIX > 25, credit tightening | 1–4 safe havens with positive momentum |
| **Sideways** | Mixed macro, range-bound price action | 0–3 mean-reversion plays or 100% SGOV |

#### 2.3 Leveraged Risk Satellite (v4.3)

TQQQ (3× Nasdaq), SOXL (3× Semiconductors), and UPRO (3× S&P 500) are gated by three conditions:
1. Regime must be **Bull** (never Bear, never Sideways)
2. SPY must be **above its 20-day EMA** (hard anchor gate)
3. Combined notional across all three leveraged positions ≤ **20% of equity** (`MAX_LEVERAGED_PCT = 0.20`)

ATR stop multiplier for leveraged ETFs is **1.5× ATR** (tighter than the standard 2×), recognizing their higher realized volatility.

#### 2.4 Kelly Criterion Position Sizing

Half-Kelly formulation:

`f* = p − q/b`  
where `p` = LLM conviction score (0.0–1.0), `q = 1 − p`, `b = take_profit_pct / |stop_loss_pct|`

Applied caps:  
`Kelly_Half = f* × KELLY_MULTIPLIER (0.50)`  
`Kelly_Applied = min(Kelly_Half, MAX_KELLY_FRACTION (0.20))`

If `Kelly_Applied ≤ 0`, the slot defaults to SGOV (negative expected value = forced cash).

**Even-weight override:** All active (non-SGOV) slots with sufficient conviction receive equal weight `1/N` where N = active slot count, then normalization ensures total ≤ 100% equity.

**Per-position hard cap (v4.4):** No single position may exceed `MAX_POSITION_PCT = 15%` of equity, regardless of Kelly output.

---

## Section III — The Learning Framework: Retrieval-Augmented Generation Loop

### Simple Explanation

> **Think of it like this:** The AI keeps a diary of every trade it makes — wins and losses. Before making new trades, it reads its own diary to remind itself what worked and what didn't. If it bought GameStop last week and lost money, it'll see that in its diary and (hopefully) not do the same thing again. The more trades it makes, the smarter the diary gets. It's like getting a personalized report card every trading cycle.

```
 THE LEARNING LOOP (runs every 15 minutes during market hours)
 ──────────────────────────────────────────────────────────────────
 
  ┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
  │  TRADE WINS  │────▶│                 │────▶│   AI BRAIN       │
  │  (3 recent)  │     │   PROMPT        │     │   (Groq Llama)   │
  └──────────────┘     │   BUILDER       │     │                  │
  ┌──────────────┐     │                 │     │  "I lost 8% on   │
  │  TRADE LOSSES│────▶│  Market data +  │     │   XLE last week  │
  │  (5 recent)  │     │  News headlines │     │   so I'll avoid  │
  └──────────────┘     │  + Sentiment +  │     │   energy today"  │
                        │  Economic cal  │     └────────┬─────────┘
                        └─────────────────┘             │
                                                         ▼
                                                  New Allocations
                                                  → Executed as Orders
                                                  → Added to Diary
```

### Advanced Technical Specification

#### 3.1 Phase 1: Trade Journaling and Outcome Storage

Every trade the LLM proposes is logged to the `trades` PostgreSQL table at execution time with: ticker, asset_class, conviction_score, original_thesis (natural language), intended_price, fill_price, slippage (basis points). Status is initially "Active."

On close: `update_trade_outcome()` computes realized P&L% and sets status to `Closed_Win` (P&L ≥ 0) or `Closed_Loss` (P&L < 0).

#### 3.2 Phase 2: Asymmetric Retrieval

Each analysis cycle retrieves: **5 most recent losses** (biased to prevent repeated mistakes) + **3 most recent wins** (pattern reinforcement). Retrieval is recency-based via SQL — no vector embeddings required.

#### 3.3 Phase 3: Multi-Source Prompt Injection

The LLM system prompt is enriched with:
- **Loss block** (framed as "CRITICAL — LEARNING FROM PAST FAILURES"): ticker, P&L%, original thesis, explicit instruction to avoid repeating the logic
- **Win block**: reinforcement of successful patterns
- **Slippage warnings**: "worst offender" tickers where execution friction was highest
- **Crypto/Market Fear & Greed indices** (0–100 scale, sourced from external APIs)
- **Economic calendar** with active blackout status (FOMC, NFP, CPI events within ±30-minute window)
- **P&L attribution** by regime and asset class
- **Portfolio risk metrics**: Sharpe ratio, annualized volatility from performance snapshots
- **Correlation warnings**: pairs with Pearson correlation > 0.85

#### 3.4 Phase 4: Groq LLM Inference

Model: **Groq Llama 3.3 70B Versatile** at temperature 0.4. Output: structured JSON allocation plan with regime label, per-slot conviction scores (0.0–1.0), take-profit and stop-loss levels, and natural-language theses.

Output is validated against Pydantic schemas before any order is placed. Invalid or unparseable responses abort the cycle without executing any trades.

#### 3.5 LLM Response Cache (Stage 2)

To avoid redundant Groq calls on quiet days (stable signals, low news volume):
- **Cache key:** MD5 of `(call_type + momentum fingerprint + news fingerprint)`
- **TTL:** 90 minutes (configurable via `LLM_CACHE_TTL_MINUTES` env var)
- **Backing:** JSON file (`data/llm_response_cache.json`) — survives short restarts
- Skips the Groq API call entirely and returns the cached regime JSON if key matches

Expected savings: 1–3 Groq calls/day on low-volatility days.

---

## Section IV — Algorithmic Guardrails

### Simple Explanation

> **Think of it like this:** These are the emergency brakes. No matter how confident the AI is, these hard rules can override everything. Imagine if you were betting at a casino with $1,000: you'd tell yourself "if I lose $50, I'm done for the day." That's the kill switch. There's also a "piggy bank" system that automatically saves 20% of every profit into a dividend-paying fund — like putting coins in a jar.

```
 EMERGENCY BRAKES IN ORDER OF SEVERITY
 ──────────────────────────────────────────────────────────
 🛑 VaR CIRCUIT BREAKER  — Too much risk → block new trades
 🛑 KILL SWITCH          — Lost >5% today → close everything, stop
 🛑 OVERHEATED ASSET     — Z>2 or RSI>75 → cut allocation 50%
 🛑 WASH SALE GUARD      — Closed loss <30 days ago → block rebuy
 🛑 MARGIN BLOCK         — No cash left → block new positions
 🚦 LEVERAGED CAP        — Turbo stocks >20% total → block
 🚦 PER-POSITION CAP     — Single position >15% equity → cap it

 PROFIT PIGGY BANK (DA-HWM Vault)
 ──────────────────────────────────────────────────────────
  Your equity crosses a new record high?
  ┌────────────────────────────────────────────┐
  │  PROFIT DETECTED! Sweep 20% into JEPQ     │
  │  (JEPQ = high-yield dividend ETF)         │
  │  New "high water mark" set at this level  │
  │  Next sweep requires NEW profit above it  │
  └────────────────────────────────────────────┘
```

### Advanced Technical Specification

#### 4.1 Daily Drawdown Kill Switch

Captures `opening_equity` at market open. On every 15-minute cycle:

`drawdown = (opening_equity − current_equity) / opening_equity`

If `drawdown ≥ CB_THRESHOLD (default 0.05 = 5%)`:
1. Sets internal `_tripped = True` flag
2. Calls `close_all_positions()` — market sell orders on all holdings
3. Logs CRITICAL alert, fires Discord notification
4. Blocks all further trading for remainder of day (short-circuits subsequent checks)

State is **in-memory only** (not persisted). Process restart resets it — an intentional "manual intervention via process management" escape hatch.

#### 4.2 VaR Circuit Breaker (Stage 4 — Executor-Level)

Before executing any allocation cycle, the executor computes portfolio-level 1-day Value-at-Risk via historical simulation (see Section VIII for full VaR methodology):

```python
var_pct    = compute_daily_var(current_positions, confidence=0.95)
var_usd    = var_pct × invested_usd          # scale to dollar amount
limit_usd  = daily_loss_limit_pct × equity   # equity-relative threshold
var_tripped = var_usd > limit_usd
```

If `var_tripped = True`: **all new entries are blocked** for the cycle. Existing positions are unaffected (stops still ratchet, post-mortem still runs). The reason `"var_circuit_breaker"` is logged per blocked slot. The system does NOT liquidate — it simply prevents adding new exposure.

Critical design note: `var_pct` is a fraction of *invested capital*, not total equity. The USD conversion is mandatory before comparing against an equity-relative limit.

#### 4.3 Overheated Asset Guardrail

Fires deterministically *after* LLM allocation, *before* order placement, for any asset where `Z > 2.0` OR `RSI > 75`:
- Notional allocation cut by 50% (`OVERHEAT_CUT_RATIO = 0.50`)
- Redirected 50% placed into SGOV (cash equivalent)
- ATR ratchet stop placed at 2× ATR (1.5× for leveraged ETFs)

This is a Python rule, not an LLM decision, and is completely non-negotiable.

#### 4.4 DA-HWM Profit Sweep Mechanism

The Distribution-Adjusted High Water Mark prevents JEPQ's own appreciation from triggering circular sweeps:

`DA_Equity = Current_Equity − max(0, JEPQ_Unrealized_PnL)`

`Eligible_Profit = max(0, DA_Equity − HWM)`

Sweep condition: `Eligible_Profit > 0` AND `0.20 × Eligible_Profit > $1.00` (Alpaca minimum order)

Sweep amount: `Sweep = 0.20 × Eligible_Profit`  
Post-sweep HWM: `HWM_new = DA_Equity − Sweep`

DRIP (Dividend Reinvestment Plan) is **explicitly disabled** system-wide to prevent fractional tax lots that could trigger wash sales outside the system's tracking scope.

Vault state persisted to `vault_ledger` PostgreSQL table: HWM, total_vaulted_usd, sweep_count, last_sweep_date, DA_adjustment.

---

## Section V — Data Circuit Breakers (Stage 1 — Hybrid Agentic Architecture)

### Simple Explanation

> **Think of it like this:** Before the AI even looks at market data, the system checks that the data is actually real and fresh. It's like a bouncer at a club checking IDs. If Bitcoin's price comes back as "$0" or "error", the bouncer says "fake ID, you're not getting in" — the trade cycle is cancelled before the AI even sees the bad data. This prevents the AI from making decisions based on garbage information.

```
 DATA QUALITY BOUNCER
 ────────────────────────────────────────────────
  Market data arrives ──▶  [VALIDATOR]
                                │
              ┌─────────────────┼─────────────────────┐
              ▼                 ▼                     ▼
         Is data          Any prices           SPY corr
         stale?           zero or NaN?         makes sense?
         (>5 min old)     (data error)         (cross-check)
              │                 │                     │
           FAIL ──▶ ❌ BLOCK ENTIRE CYCLE         FAIL ──▶ ❌ BLOCK
           PASS ──▶ ✅ Continue to AI analysis
```

### Advanced Technical Specification

The `validate_snapshot()` function in `shared/market_snapshot_validator.py` runs before any analysis cycle and raises `DataCircuitBreakerError` if data quality fails. Four independent guard layers:

#### 5.1 Staleness Guard

`market_data["fetched_at"]` is compared to `datetime.utcnow()`.  
Threshold: **5 minutes** for equity data, **2 minutes** for crypto.  
If stale: entire cycle is skipped, previous regime cached.

#### 5.2 NaN / Missing Value Guard

Any `None`, `NaN`, or missing value in the `closes`, `rsi`, `zscore`, or `volatility` fields for any asset in the primary universe triggers a circuit break. Partial data is not acceptable for LLM analysis — the prompt context would be misleading.

#### 5.3 Zero-Price Guard

Any asset returning `price = 0.0` (exchange feed error, API timeout) blocks the cycle. A zero price would produce infinite Z-scores and undefined Kelly fractions.

#### 5.4 Cross-Asset Correlation Guard

Computes a fast Pearson correlation between SPY 20-day returns and QQQ 20-day returns. If `|corr(SPY, QQQ)| < 0.4` — an implausibly low correlation for these two highly-correlated instruments — this signals a data feed divergence (e.g., one feed lagging a corporate action or split). The cycle is blocked pending the next data refresh.

The `ValidationResult` datatype carries: `valid: bool`, `reason: str`, `severity: str ("warning" | "error" | "critical")`, and `failed_checks: list[str]`.

---

## Section VI — Agentic Statefulness & Cycle Memory (Stage 2)

### Simple Explanation

> **Think of it like this:** Originally, the AI had "goldfish memory" — each 15-minute cycle it forgot everything from the last one. Now it keeps notes between cycles. It remembers: "Last cycle I was in Bull mode, this is what I decided." It also has three security guards that check the news and market vibes before even letting the AI look at anything, so we don't waste expensive AI calls on garbage signals.

```
 AGENTIC MEMORY LAYERS
 ────────────────────────────────────────────────────
  [CYCLE STATE]     Remembers last regime, last trade time,
                    current macro theme between restarts

  [SIGNAL GUARDS]   Three filters run BEFORE the AI:
   Guard 1: "Is this news confirmed by >1 source?"
   Guard 2: "Is there a major economic event happening right now?"
   Guard 3: "Is the market unusually quiet compared to its volume?"

  [GROQ BUDGET]     Tracks daily AI token usage (limit: 100,000/day)
                    Rate-limits calls if budget is running low

  [LLM CACHE]       If nothing changed from last cycle, skip the AI call
                    and reuse the previous answer (saves tokens + time)
```

### Advanced Technical Specification

#### 6.1 Cycle State Persistence

The `data/cycle_state.py` module maintains a persistent in-process state store written to disk after each cycle. Fields include: `last_regime`, `last_analysis_timestamp`, `consecutive_sideways_cycles`, `last_allocation_plan`, and `macro_theme_label`. On restart, the previous state is restored, preventing the system from treating the first post-restart cycle as if it were day one with no context.

#### 6.2 Signal Guard Layer (Three Independent Guards)

`analysis/signal_guard.py` runs three composable guards in sequence before any LLM call. Each guard returns a `GuardResult(name, passed, reason, severity: "hard"|"soft")`.

**Guard 1: Multi-Source Consensus Guard (SOFT)**  
Filters news headlines that appear in only one source. Requires a headline to appear in at least 2 of the 5 news sources before it is passed to the LLM. Prevents single-source FUD or hype from polluting the AI's news context.  
Output: `filtered_headlines` (subset of all_headlines).

**Guard 2: Temporal Quarantine Guard (HARD)**  
Blocks ALL analysis during:
- Friday 14:00 → Monday 09:30 ET (weekend illiquidity window)
- ±30 minutes around economic blackout events: FOMC, NFP, CPI, PCE, Jobs Report

If hard-blocked: the cycle is skipped entirely, the previous cached regime is returned, and no Groq token is consumed.

**Guard 3: Price-to-Sentiment Divergence Guard (SOFT)**  
If SPY's 5-day average volume < SPY's 20-day average volume AND the current sentiment band is "Greed" or "Extreme Greed": the sentiment band is downgraded one step (Greed → Neutral, Extreme Greed → Greed). This prevents the LLM from acting on bullish crowd sentiment during low-conviction, low-volume market conditions.  
Output: `adjusted_sentiment` (None if no change, otherwise the downgraded label).

#### 6.3 Groq Daily Token Budget Manager

`analysis/groq_budget.py` tracks daily token consumption and enforces three constraints:

| Constraint | Default | Configuration |
|---|---|---|
| Minimum interval between regime calls | 90 minutes | `GROQ_MIN_REGIME_INTERVAL_MINUTES` |
| Max auto-triggered commentary calls per endpoint | 4/day | `GROQ_COMMENTARY_DAILY_CAP` |
| Hard daily token budget | 100,000 TPD | `GROQ_DAILY_TOKEN_BUDGET` |

Counters reset at midnight UTC. The budget module provides `can_call_regime()`, `record_regime_call()`, `can_call_commentary(ep, force)`, and `budget_status()` (for the API status endpoint). The `force=True` flag on commentary allows manual dashboard refreshes to bypass the daily cap but not the hard token budget.

#### 6.4 Degradation Tracker

`core/degradation_tracker.py` records every detected system failure or health event to PostgreSQL's `system_degradations` table with fields: component, severity, error_type, message, detail, timestamp.

De-duplication logic suppresses repeated identical events within a rolling TTL window (15 min default; 30 min for stale-data events; 5 min for HTTP 500/503 errors) with exponential escalation: each re-occurrence after the TTL doubles the wait time (capped at 4 hours). This prevents the log from filling with thousands of identical "yfinance failed" entries during extended outages while still alerting on genuine escalations.

---

## Section VII — Gemini Daily Self-Critic Auditor (Stage 3)

### Simple Explanation

> **Think of it like this:** Every morning at 4:15 AM, before the market opens, a second AI (Google's Gemini) looks at yesterday's trades and asks "Did my colleague (the trading AI) do something stupid?" It writes a report card: "Clean" means everything looks fine, "Caution" means some concerns, "Hold" means something is seriously wrong and certain stocks should be blocked today. The trading AI has to listen to this report.

```
 GEMINI SELF-CRITIC AUDITOR (runs daily 4:15 AM ET)
 ────────────────────────────────────────────────────────────
  Yesterday's data arrives:
  - All trades made
  - Equity curve (profits/losses)
  - System health events
  - Position sizes vs risk limits
         │
         ▼
  [GEMINI FLASH AI] asks:
  "Did the other AI cheat? Use hindsight? Size positions wrong?"
         │
         ▼
  OUTPUT: veto_conditions.json
  ┌──────────────────────────────────────────────────┐
  │  verdict: "CAUTION"                              │
  │  vetoed_tickers: ["TSLA", "NVDA"]               │
  │  conditions: [max_conviction_cap: 0.85]          │
  │  critique: "Conviction scores were inflated..."  │
  └──────────────────────────────────────────────────┘
  → Today's trading AI reads this and blocks vetoed tickers
```

### Advanced Technical Specification

#### 7.1 Audit Pipeline

The `analysis/gemini_auditor.py` module runs as an APScheduler job at **04:15 AM ET** daily (before market open). Sequence:

1. **Data collection:** Fetches prior day's trade records, performance snapshots, `system_degradations` events, and equity time-series from PostgreSQL
2. **Payload sanitization:** `gemini_context_sanitizer.py` compacts the payload, removes PII, truncates excessively long thesis strings, and redacts API keys/secrets
3. **Token budget check:** If payload exceeds 80% of Gemini's context window, the equity time-series is chunked into 8-hour windows and Gemini is called once per chunk; results are merged (union of vetoed tickers and conditions)
4. **Adversarial prompting:** System prompt instructs Gemini to act as a hostile auditor looking for:
   - Conviction-score inflation or inconsistency (e.g., wins clustering at high conviction)
   - Regime-label contradictions (Bear regime with high-risk crypto buys)
   - Position-sizing violations relative to risk profile
   - Repeated ticker vetoes (wash-sale blindness — buying repeatedly after losses)
   - Data-quality anomalies (impossible P&L percentages, static equity for hours)
5. **Response validation:** Pydantic schema validates JSON structure before writing

#### 7.2 Output Schema (`veto_conditions.json`)

```json
{
    "generated_at":   "<ISO-8601 UTC>",
    "valid_until":    "<ISO-8601 UTC>",
    "vetoed_tickers": ["AAPL", "TSLA"],
    "conditions": [
        {"type": "vpin_threshold",     "value": 0.7},
        {"type": "news_blacklist",     "ticker": "META"},
        {"type": "max_conviction_cap", "value": 0.85}
    ],
    "critique_summary": "<2-4 sentence prose summary>",
    "critique_flags":   ["<issue 1>", "<issue 2>"],
    "overall_verdict":  "CAUTION | CLEAN | HOLD"
}
```

#### 7.3 Veto Enforcer (`core/veto_enforcer.py`)

Before every order placement, `is_vetoed(ticker)` checks `veto_conditions.json`:
- Results cached in-process for **5 minutes** (TTL) to avoid repeated disk reads
- File parsed on first call, cache refreshed on expiry
- Expiry check: `now < valid_until` — expired vetoes are silently ignored
- **Fail-open:** If the file doesn't exist, can't be parsed, or is expired → `is_vetoed()` returns `False` (trading proceeds normally). The auditor's absence never blocks the primary bot.

Model used: **Gemini 3 Flash Preview** (`gemini-3-flash-preview`) via Replit AI Integrations proxy endpoint: `{AI_INTEGRATIONS_GEMINI_BASE_URL}/models/{model}:generateContent`.

---

## Section VIII — Value-at-Risk Circuit Breaker (Stage 4 — Executor-Level)

### Simple Explanation

> **Think of it like this:** Before placing any new trades, the system asks: "Based on how much my current investments have moved in the past month, what's the worst single-day loss I should realistically expect?" If that worst-case number is already too scary, the system says "too risky today — no new trades." It's like a weather forecast: if there's a 95% chance of a storm, you don't add more picnic items to an already-loaded table.

```
 HOW VALUE-AT-RISK WORKS
 ────────────────────────────────────────────────────────────
  Step 1: Look at the last 30 days of actual price moves
          for everything we currently hold

  Step 2: Replay all those days: "What would we have
          lost on our worst 5% of days?"

  Step 3: Convert that % into actual dollars
          (VaR% × dollars invested = VaR in $)

  Step 4: Compare to limit (e.g. 2% of total equity)
          VaR$ > limit$ → ❌ Block new trades this cycle
          VaR$ ≤ limit$ → ✅ Safe to proceed

  EXAMPLE:
  $50,000 invested, VaR = 3% of invested = $1,500 risk
  Limit = 2% × $100,000 equity = $2,000
  $1,500 < $2,000 → safe ✅
```

### Advanced Technical Specification

#### 8.1 Historical Simulation VaR (`portfolio/var_calculator.py`)

Method: Non-parametric historical simulation (no distributional assumptions). Implemented in `compute_daily_var(positions, confidence=0.95, lookback_days=30)`.

**Algorithm:**
1. Extract symbols from `positions` list (each dict: `symbol`, `market_value`)
2. Map broker symbols to yfinance tickers (e.g., `BTCUSD → BTC-USD`)
3. Fetch `lookback_days + 10` calendar days of daily closing prices via `yfinance.download()`
4. Compute portfolio daily P&L series:
   ```
   For each day i:
     day_pnl = Σ [(price_{i+1} - price_i) / price_i × (market_value_j / total_invested)]
   ```
5. Sort `portfolio_pnl` ascending
6. `var_pct = -percentile(sorted_pnl, (1 - confidence) × 100)` → loss as a positive fraction

**Return contract:** `var_pct` is a fraction of **invested capital** (sum of `market_value` entries), NOT of total account equity. This distinction is critical for the executor comparison:

`var_usd = var_pct × invested_usd`  
`limit_usd = daily_loss_limit_pct × total_equity`  
`var_tripped = var_usd > limit_usd`

**Graceful failures:** Returns `0.0` (no block) if: empty positions, yfinance network failure, fewer than 5 trading days of data, or any parsing exception. Fail-open ensures the executor is never paralyzed by a data dependency.

#### 8.2 Executor VaR Gate

At the start of `execute_allocations()`:
```python
positions  = get_positions()
var_pct    = compute_daily_var(positions)
var_usd    = var_pct * _invested_usd
var_tripped = var_usd > daily_loss_limit_pct * equity
```

If tripped: `_execute_slot(slot, var_tripped=True)` is called for every slot. The slot function immediately skips the buy order, logs `reason="var_circuit_breaker"`, and returns — regardless of conviction score, Kelly fraction, or regime. **No exemptions exist.** SGOV will still be purchased for zero-kelly slots via normal zero-kelly logic. Vault sweeps run separately after the allocation loop and are unaffected.

---

## Section IX — Operational Infrastructure

### Simple Explanation

> **Think of it like this:** This is the plumbing behind the scenes. The database stores every trade and keeps backups. The system knows exactly what time the stock market opens and closes (accounting for holidays!). If the internet hiccups, the system waits and tries again automatically instead of crashing. And a scheduler makes sure everything happens at exactly the right time — like an alarm clock for trading.

```
 THE TRADING CLOCK SYSTEM
 ──────────────────────────────────────────────────────────────────
  9:01 AM ET ──▶ First intraday cycle begins (every 15 min)
 11:00 AM ET ──▶ ... still trading ...
  3:46 PM ET ──▶ Last intraday cycle (market closes at 4 PM)
  4:10 PM ET ──▶ Post-mortem: close positions, record results
  4:30 PM ET ──▶ Gemini Auditor: grade yesterday's trades
  4:15 AM ET ──▶ (next day) Gemini Self-Critic writes report card

  After 4 PM & weekends → Crypto mode: BTC/ETH only (24/7)
```

### Advanced Technical Specification

#### 9.1 Database Architecture

Primary: **PostgreSQL** with `psycopg2` `ThreadedConnectionPool` (min=1, max=8 connections). Context manager handles acquire → commit on success → rollback on exception → release. Fallback: transparent SQLite with identical function signatures; `is_pg_available()` checked per-operation.

**Schema tables (idempotent `CREATE TABLE IF NOT EXISTS` on startup):**

| Table | Purpose |
|---|---|
| `trades` | Trade journal (ticker, conviction, P&L%, thesis, fill/intended price, slippage, status) |
| `performance_snapshots` | Daily equity and P&L metrics (post-mortem output) |
| `vault_ledger` | Profit sweep state (HWM, vaulted USD, sweep count, DA adjustment) |
| `ratchet_stops` | Active trailing stops (symbol, stop_price, fill_price, ATR, last_updated) |
| `system_degradations` | System health events from degradation tracker |
| `kraken_adaptive_params` | Kraken bot's self-tuned parameter set (JSONB) |

#### 9.2 Market Clock and Timezone Synchronization

Primary source: Alpaca `/v2/clock` API (authoritative, holiday-aware, irregular-session-aware).  
Local fallback: `America/New_York` timezone, standard NYSE hours (09:30–16:00), holiday detection via `holidays.NYSE()` library plus manual overrides for early closes (Black Friday, Christmas Eve, New Year's Eve at 13:00 ET).

#### 9.3 Exponential Backoff and Rate Limiting

Targets HTTP 429 (rate limit) responses with full-jitter exponential backoff:
- Base delay: 1.0 seconds; ceiling: 60.0 seconds
- Jitter: `delay = random.uniform(0, min(ceil, base × 2^attempt))`
- Max retries: 5 before allowing failure
- Global rate limiter: minimum 300ms spacing between any two Alpaca API calls

Async variant available for coroutine-based code paths.

#### 9.4 APScheduler Jobs

| Job | Schedule | Action |
|---|---|---|
| Intraday analysis | Every 15 min, Mon–Fri 09:01–15:46 ET | Full pipeline: data refresh → guards → LLM → execute → journal |
| Crypto-only | Every 15 min, 24/7, fires only when NYSE closed | BTC/USD, ETH/USD on Alpaca GTC orders |
| Post-mortem | 16:10 ET weekdays | Close positions, P&L computation, journal updates, profit sweep |
| Gemini Auditor | 16:30 ET weekdays | Daily self-critic run, veto_conditions.json write |
| Gemini Self-Critic | 04:15 AM ET | Pre-market audit, veto_conditions.json for the new day |

All jobs paused by default. Operator enables via dashboard auto-trading toggle or API endpoint. The system never starts trading autonomously on launch.

---

# PART B: DAVY JONES' PORTFOLIO — KRAKEN CRYPTO BOT

---

## Section X — Core Strategy: Mean Reversion with RSI Filter

### Simple Explanation

> **Think of it like this:** "Davy Jones' Portfolio" is a second, independent robot that only trades cryptocurrency on Kraken, 24/7. Its strategy is simple: when Bitcoin (or other coins) drops sharply below its normal price range AND looks "oversold" (price fell too fast), buy it — expecting it to bounce back. When it bounces back to normal, sell it. It's like buying a phone when it goes on sale and selling it when the price goes back up.

```
 MEAN REVERSION STRATEGY
 ───────────────────────────────────────────────────────────
  Normal price range: $60,000 - $65,000
  
  BTC drops to $55,000 ──▶ "Too cheap!" (Z-score < -1.5, RSI < 40)
                            BUY with small position (% of equity)
                                    │
                                    ▼
  BTC recovers to $62,000 ──▶ "Back to normal" (Z-score crosses 0)
                            SELL and take profit ✅

  Circuit breaker: If BTC crashes >3% in 30 minutes
                   STOP trading for 6 hours ⛔
```

### Advanced Technical Specification

#### 10.1 Statistical Entry Logic

**Z-Score:** Computed on `ZSCORE_WINDOW` (default 20) bars of closing price.  
`Z = (Close_latest − μ_window) / σ_window`  
Entry when `Z < −ZSCORE_ENTRY (default −1.5)` — price significantly below mean.  
Exit when `Z > ZSCORE_EXIT (default 0.5)` — mean reversion substantially complete.

**RSI Confirmation:** Only enter if `RSI_14 < RSI_OVERSOLD (default 40)`.  
Exit also triggered if `RSI_14 > RSI_OVERBOUGHT (default 65)` (momentum exhaustion).

**Position Sizing:** `position_usd = equity × RISK_FRACTION (default 5%) × (1 − CASH_RESERVE)`.  
Hard cap: `max_position_usd = equity × MAX_POSITION_FRACTION (default 20%)`.  
Hard cap on simultaneous positions: `MAX_POSITIONS = 3`.

**Exit Profit Floor:** `MIN_NET_PROFIT_PCT` (default 0.6%) — a position will not be closed unless the profit exceeds the fee floor (covering ~0.52% Kraken Pro fees). This prevents the bot from cycling out of positions just to break even.

**Trailing Stop:** `TRAIL_PCT (default 2%)` — trailing stop placed `TRAIL_PCT` below the highest price seen since entry.

#### 10.2 Flash-Crash Circuit Breaker

Monitors a rolling price deque over `CB_WINDOW_MINUTES (default 30)` minutes. If the current price is more than `CB_PRICE_DROP_PCT (default 3%)` below the window high: pause all trading for `CB_PAUSE_HOURS (default 6)` hours.

This prevents the bot from aggressively buying during a genuine market collapse (e.g., exchange hack, regulatory announcement) by treating sudden sharp drops as structurally different from mean-reversion opportunities.

#### 10.3 Symbols Traded

Default: BTC/USD, ETH/USD on Kraken Pro via ccxt library. Paper mode uses a simulated $100,000 virtual portfolio tracked in `paper_portfolio.json`. Live mode requires `KRAKEN_API_KEY` and `KRAKEN_SECRET_KEY` environment secrets.

---

## Section XI — Adaptive Parameter Self-Tuning (Kraken)

### Simple Explanation

> **Think of it like this:** The Kraken bot can adjust its own settings every 6 hours based on how well it's been doing. If it keeps stopping out too quickly, it automatically loosens the stop. If its entry signals are too aggressive (too many losses), it becomes more selective. It's like a golfer who adjusts their swing based on how the last few holes went.

```
 ADAPTIVE TUNING (every 6 hours)
 ─────────────────────────────────────────────────────────────
  REVIEW: Last 20 trades

  Win rate < 40%?  → Tighten ZSCORE_ENTRY (be more selective)
  Win rate > 70%?  → Loosen ZSCORE_ENTRY (capture more trades)
  
  Too many stop-outs?
    → Tighten STOP_LOSS_PCT (stop sooner to limit damage)
  
  Trailing fires too early (good trades getting cut)?
    → Widen TRAIL_PCT (give more room to breathe)

  All parameters stay within ±40% of their factory defaults
  → Cannot drift into dangerously aggressive settings
```

### Advanced Technical Specification

`kraken-bot/adaptive_params.py` runs every `ADAPT_EVERY_HOURS (default 6)` hours. It reads the last `LOOKBACK_TRADES` closed trades from `paper_portfolio.json` (or PostgreSQL in live mode) and computes:

- **Win rate:** `wins / total_closed`
- **Avg loss per trade:** `mean(abs(pnl) for losing trades)`
- **Stop-out frequency:** `stop_outs / total_closed`
- **Trailing-exit rate:** `trail_exits / total_closed`
- **Break-even exit rate:** `breakeven_exits / total_closed`

Based on these metrics, each parameter is nudged within a ±40% band from factory defaults:

| Parameter | Adapts When | Direction |
|---|---|---|
| `ZSCORE_ENTRY` | Win rate poor | Raise (more selective) |
| `ZSCORE_ENTRY` | Win rate strong | Lower (more aggressive) |
| `ZSCORE_EXIT` | Winners cut short | Lower (let them run) |
| `STOP_LOSS_PCT` | Stop-outs frequent/large | Tighten |
| `TRAIL_PCT` | Trailing fires too early | Widen |
| `MIN_NET_PROFIT_PCT` | Break-even exits common | Raise |

Hard floor: `MIN_NET_PROFIT_PCT` always exceeds the fee floor (0.52%) — the bot can never be configured to exit at a guaranteed loss.

Adapted parameters written to `adaptive_params.json` (survives restarts) and to the `kraken_adaptive_params` PostgreSQL table (for dashboard visibility).

---

## Section XII — Microstructure Alpha Signals (Stage 4 — Kraken)

### Simple Explanation

> **Think of it like this:** Before the bot enters a trade, it peeks at the crypto market's "order book" — the list of every pending buy and sell order. Three numbers tell it whether it's a good time to enter:
> - **OFI (Order Flow Imbalance):** Are there more buyers than sellers right now?
> - **VAMP (Volume-Adjusted Mid Price):** What's the "real" fair price considering all orders?
> - **VPIN (Probability of Informed Trading):** Are suspicious "smart money" traders making very one-sided moves? (If yes = danger!)

```
 THE THREE MICROSTRUCTURE SENSORS
 ─────────────────────────────────────────────────────────────────
  ORDER BOOK (live snapshot):
  Buyers wanting to buy: ████████░░ (80 units @ ~$62,000)
  Sellers wanting to sell: ████░░░░░░ (40 units @ ~$62,100)
  
  OFI = (buy_depth - sell_depth) / total = +0.33 → buy pressure ✅
  
  VAMP = depth-weighted average of buy side and sell side prices
       = $62,045 (slightly above midpoint → buyers paying up)
  
  VPIN (using last 200 trades, grouped in $5,000 buckets):
  Each bucket: buy_vol vs sell_vol. If one side totally dominates...
  VPIN = Σ|buy-sell| / Σtotal = 0.85 → DANGER (smart money one-sided) ❌
  
  ENTRY GATES:
  Long trade allowed? OFI > +0.02 AND VPIN < 0.80
  Short trade allowed? OFI < -0.02 AND VPIN < 0.80
```

### Advanced Technical Specification

All three metrics are computed live from the Kraken order book (`ccxt.fetch_order_book()`) and recent trades (`ccxt.fetch_trades(limit=200)`). OHLCV-based fallback functions exist for testing and exchange outages.

#### 12.1 Order-Flow Imbalance (OFI)

`compute_ofi(order_book, levels=5)` aggregates the top 5 bid and ask levels:

```
bid_depth = Σ size_i  for i in bids[:5]
ask_depth = Σ size_i  for i in asks[:5]
OFI = (bid_depth − ask_depth) / (bid_depth + ask_depth)
```

Range: `[−1, +1]`. +1 = all depth on buy side; −1 = all depth on sell side.  
Long entry threshold: `OFI ≥ OFI_LONG_MIN = +0.02`  
Short entry threshold: `OFI ≤ OFI_SHORT_MAX = −0.02`

#### 12.2 Volume-Adjusted Mid Price (VAMP)

`compute_vamp(order_book, levels=10)` computes depth-weighted average price for each side:

```
VWAP_bid = Σ(price_i × size_i) / Σ size_i   for bids[:10]
VWAP_ask = Σ(price_i × size_i) / Σ size_i   for asks[:10]
VAMP = (VWAP_bid + VWAP_ask) / 2.0
```

Expressed in absolute USD. Used to detect price pressure direction and in the dashboard status log.

#### 12.3 Volume-Synchronised Probability of Informed Trading (VPIN)

`build_trade_buckets(recent_trades, bucket_size_usd=$5,000)` groups the ccxt `fetch_trades()` output into fixed-dollar volume buckets. Each bucket accumulates trades until total USD cost exceeds `bucket_size_usd`:

```
For each trade: cost = price × amount (or trade["cost"] if available)
  If side == "buy": bucket["buy_vol"] += cost
  Else:             bucket["sell_vol"] += cost
  bucket["total_vol"] += cost
  If total_vol >= bucket_size: seal bucket, start new one
```

`compute_vpin(buckets, n_buckets=50)` over the most recent 50 buckets:

```
VPIN = Σ|buy_vol_i − sell_vol_i| / Σtotal_vol_i   for i in last 50 buckets
```

Range: `[0, 1]`. 0 = perfectly balanced; 1 = entirely one-sided (toxic/informed flow).  
Elevated risk threshold: `VPIN_HIGH_THRESH = 0.65`  
Hard block threshold: `VPIN_BLOCK_THRESH = 0.80` — blocks **all** new entries  
Defensive pre-entry gate in main loop: `VPIN > 0.70` → skip entry (more conservative than the filter's formal threshold)

#### 12.4 MicrostructureSignal Composite Gate

`MicrostructureSignal.entry_filter(side)` combines all three in priority order:

1. If `VPIN ≥ 0.80` → blocked, reason: `"VPIN={x} >= block_threshold=0.80 (toxic flow)"`
2. If `side == "long"` AND `OFI < +0.02` → blocked, reason: `"sell-side pressure"`
3. If `side == "short"` AND `OFI > −0.02` → blocked, reason: `"buy-side pressure"`
4. Otherwise: `allowed = True, reason = "microstructure confirmed"`

In the live main loop, an additional pre-check fires before `entry_filter()`: if VPIN > 0.70, the cycle is skipped at the main-loop level (before even constructing the full signal).

---

## Section XIII — Kraken Penalty Tracker (API Rate Protection)

### Simple Explanation

> **Think of it like this:** Kraken's API is like a vending machine that penalizes you for pressing buttons too fast. You get 15 points before it cuts you off, and you earn back 1 point every second. Placing an order costs 1 point; cancelling an order costs 2 points. The bot keeps track of this in real-time and automatically pauses when it has used 80% of its points — giving the bucket time to refill before making more trades.

```
 LEAKY BUCKET PENALTY TRACKER
 ─────────────────────────────────────────────────────────────────
  [■■■■■░░░░░░░░░░]  Points used: 4/15  → Safe ✅
  [■■■■■■■■■■■■░░░]  Points used: 12/15 → Throttled ⚠ (80% threshold)
  [■■■■■■■■■■■■■■■]  Points used: 15/15 → Max! Wait for refill ❌
  
  Drains at 1 point/second automatically
  Placing order → +1 point
  Cancelling order → +2 points
  
  State saved to disk → survives bot restarts!
```

### Advanced Technical Specification

`kraken-bot/penalty_tracker.py` implements a continuous leaky-bucket model:

**Constants:**
```
MAX_POINTS        = 15.0
PLACEMENT_COST    = 1.0  (per order placement)
CANCELLATION_COST = 2.0  (per order cancellation)
DECAY_RATE_PER_SEC = 1.0  (points drained per wall-clock second)
THROTTLE_THRESHOLD = 0.80  (throttle at 80% of ceiling = 12.0 points)
```

**Decay formula:** On every method call, elapsed wall-clock seconds since `_last_tick` are computed and drained:  
`points = max(0.0, points − elapsed_seconds × 1.0)`

**is_throttled():** `return points ≥ 12.0` — when True, the main loop skips new order placement and cancellation, entering read-only polling mode until the bucket naturally drains below the threshold.

**Persistence:** State written atomically (`tmp_file → os.replace()`) to `penalty_state.json` after every `record_placement()` and `record_cancellation()`. On load, elapsed wall-clock time since last save is applied as decay before restoring `_points`. This means the penalty counter is accurate even across process restarts.

---

# PART C: SHARED RISK INFRASTRUCTURE

---

## Section XIV — Shared Core Library

### Simple Explanation

> **Think of it like this:** Both robots (the Alpaca bot and the Kraken bot) share a toolbox of safety equipment. Instead of each robot having its own separate version, they both use the same set of tested, proven tools. This means a safety fix applies to both bots at once — no duplication, no inconsistency.

```
 SHARED TOOLBOX (used by BOTH bots)
 ─────────────────────────────────────────────────────────────────
  🔧 RiskProfile      — "How much can we bet? What's our reserve?"
  🔧 ExitBracket      — "Calculate stop-loss and take-profit levels"
  🔧 CircuitBreaker   — "Did price drop too fast? Stop trading!"
  🔧 VaRCircuitBreaker — "Too much statistical risk? Pause entries"
  🔧 DataValidator    — "Is this market data fresh and real?"
```

### Advanced Technical Specification

`shared/` is a pure-Python package on `sys.path` from the repository root. Both bots import it at startup via:

```python
sys.path.insert(0, repo_root)
from shared import RiskProfile, ExitBracket, CircuitBreaker, VaRCircuitBreaker
from shared.market_snapshot_validator import validate_snapshot
```

#### 14.1 RiskProfile

Encapsulates the portfolio-level risk envelope: `max_single_position_pct`, `cash_reserve_pct`, `max_simultaneous_positions`, `ring_fence_amount` (capital never risked). Provides `is_acceptable(notional, equity)` → `bool`.

#### 14.2 ExitBracket

Calculates stop-loss and take-profit levels given fill price, ATR, and risk/reward ratio. Handles edge cases: minimum stop distance, maximum stop distance (cap at 5% below fill), and LETF multiplier (1.5× instead of 2× ATR for leveraged ETFs).

#### 14.3 CircuitBreaker (Flash-Crash Detector)

Rolling price deque over a configurable window. `check(current_price) → bool`. Returns True (breaker tripped) if the current price is more than `threshold_pct` below the window's maximum. Fires pre-entry in both bots.

#### 14.4 VaRCircuitBreaker (Parametric, Shared Library)

A **parametric** (Gaussian) VaR implementation for fast computation when historical data is unavailable. Uses the formula:

`VaR_parametric = −(μ_return − z_score × σ_return) × portfolio_value`

where `z_score` is the standard normal quantile at the confidence level (e.g., z = 2.326 for 99%). This is distinct from the executor's historical simulation VaR — it serves as a lightweight first-pass check in the shared library, while the executor uses the more accurate historical simulation for final gate decisions.

#### 14.5 Market Snapshot Validator

`validate_snapshot(market_data) → ValidationResult` — the Data Circuit Breaker described in Section V. Used by the Alpaca platform before any LLM call.

---

# PART D: ALGOEDGE SAAS PLATFORM

---

## Section XV — AlgoEdge Public SaaS Platform

### Simple Explanation

> **Think of it like this:** AlgoEdge is a public-facing website where anyone can sign up, pay a monthly subscription, and access a paper-trading version of the AI trading system. Real money is never at risk — it's all simulated. Subscribers see the AI's trades, portfolio, and performance in real-time. Think of it as a "demo mode" for the system that you pay to access.

```
 ALGOEDGE SAAS OVERVIEW
 ─────────────────────────────────────────────────────────────────
  User visits AlgoEdge.io
        │
        ├──▶ Free tier: See basic strategy info
        │
        ├──▶ Paid tier ($X/month via Stripe):
        │     ├── Real-time paper portfolio performance
        │     ├── Live AI trade signals & reasoning
        │     └── Historical backtests & analytics
        │
        └──▶ API (for developers): JSON endpoints
             for trade history, performance, positions
```

### Advanced Technical Specification

The AlgoEdge SaaS platform (`artifacts/saas/`) is a separate React + Vite frontend backed by a FastAPI Python API running on port 8099. It is architecturally separate from the trading platform's dashboard (port 8000 API, Vite frontend).

#### 15.1 Paper Portfolio Engine

A fully isolated `saas_paper_portfolio.json` tracks the SaaS demonstration portfolio. It mirrors the trading platform's strategy but runs with an independent capital pool (`PAPER_STARTING_BALANCE`). Real broker API calls are never made from the SaaS layer.

#### 15.2 Stripe Payment Integration

Subscription management uses the Stripe API (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`). Webhook endpoints handle: `checkout.session.completed`, `customer.subscription.deleted`, `invoice.payment_failed`. Subscriber access is gated by checking Stripe subscription status in the API middleware before returning paid-tier data.

#### 15.3 API Endpoints

`saas_router.py` provides: `/saas/portfolio` (current positions), `/saas/performance` (equity curve), `/saas/signals` (latest AI trade signals), `/saas/trades` (trade history). Authentication is via Stripe subscription validation.

---

# PART E: DASHBOARD AND FRONT-END ARCHITECTURE

---

## Section XVI — React Dashboard Architecture

### Simple Explanation

> **Think of it like this:** The dashboard is the cockpit of the airplane. It shows you everything happening in real-time: your money, your trades, whether the AI is happy or confused, and big red buttons for emergencies. There are two AI characters — one that trades ("The Degen Oracle") and one that audits the trader ("Inspector Rekt"). Both show their reasoning in plain English so you always know what's happening.

```
 DASHBOARD LAYOUT (top to bottom, most urgent first)
 ─────────────────────────────────────────────────────────────────
 TIER 1 (URGENT):  Auto-trading toggle | Portfolio $ | Live positions
                   Economic calendar (upcoming risky events)
 
 TIER 2 (HEALTH):  Risk metrics | Sentiment gauges | Correlations
                   Performance chart | P&L by regime
 
 TIER 3 (AI):      [Degen Oracle] — makes trades, shows reasoning
                   [Inspector Rekt] — audits the Oracle, flags issues
                   Best/worst trade cards
 
 TIER 4 (TOOLS):   Backtester | Trade journal | Learning context
                   Vault management | Mission control (manual buttons)
 
 ALWAYS VISIBLE:   Kill switch status (ARMED 🟢 / TRIPPED 🔴)
```

### Advanced Technical Specification

#### 16.1 Technology Stack

React 19 + Vite + Tailwind CSS v4 + TanStack React Query. No global state library (Redux/Zustand) — all state via React Query server-state hooks.

#### 16.2 Polling Cadence

| Data | Interval | Rationale |
|---|---|---|
| System health, kill switch | 10 seconds | Near-real-time for crisis response |
| Portfolio equity, positions | 30 seconds | Balance between freshness and API load |
| Growth vault, auditor report | 60 seconds | Lower volatility, less frequent updates needed |
| Correlation matrix, sentiment | 120 seconds | Computed rarely, no need for high-frequency refresh |
| AI commentary | 25-min staleTime + 90-sec manual poll | Respects Groq token budget |

#### 16.3 The Dual-Agent Interface

**The Degen Oracle** (primary strategy agent): Pulsing neural network SVG with animated synaptic connections. Displays latest LLM market commentary. Click reveals: strategy thesis, target allocations with Kelly fractions and conviction rings, split "What Worked / What Failed" view of RAG loop inputs.

**Inspector Rekt** (HITL auditor agent): Animated shield with scanning eye motif. Displays status badge (ALL_CLEAR / REVIEW_RECOMMENDED / ACTION_REQUIRED) and latest audit findings across five categories:

1. **Regime Integrity** — LLM classification vs. independently computed heuristics
2. **Compliance** — Wash sale exposure, 30-day loss window cross-reference
3. **RAG Bias Detection** — Implausible win rates, hindsight language detection, suspiciously high-conviction wins
4. **Phantom Drawdown** — Kill switch proximity monitoring (danger zone: within 0.5% of threshold), DA-HWM sanity check
5. **Ratchet Stop Integrity** — Stop prices below entry prices, within reasonable ATR distance, not stale

Each finding carries: INFO (green) / WARNING (amber) / ALERT (red) / HOLD (orange, compliance violations).

#### 16.4 Human-in-the-Loop Manual Override Architecture

Five control panel actions, each behind a confirmation modal:

| Action | Type | Effect |
|---|---|---|
| Run Analysis (Dry Run) | Non-destructive | Full pipeline without orders — preview LLM plan |
| Run Analysis (LIVE) | Destructive | Real order placement with confirmation of live-risk |
| Run Post-Mortem | Non-destructive | Close-of-day position close, P&L, journal update |
| Reset Kill Switch | System | Clear tripped state, re-initialize equity baseline |
| Trip Kill Switch | Emergency | Market-sell all positions immediately, halt trading |

---

# PART F: SYSTEM-WIDE RISK AND GOVERNANCE

---

## Section XVII — Wash Sale Compliance

### Simple Explanation

> **Think of it like this:** The IRS has a rule: if you sell a stock at a loss, you can't buy a "nearly identical" version of it within 30 days, or you can't claim the tax deduction. The system automatically prevents this. It knows that SPY and VOO are basically the same thing (both track the S&P 500), so if it lost money selling SPY, it won't buy VOO either for 30 days.

### Advanced Technical Specification

#### 17.1 Similarity Matrix

14 predefined wash-sale groups covering ETF equivalents:

| Group | Members |
|---|---|
| US Equity | SPY, IVV, VOO |
| Tech | XLK, VGT, FTEC |
| Long Bonds | TLT, EDV, VGLT |
| Gold | GLD, IAU, SGOL |
| Bitcoin | IBIT, GBTC, BTCUSD, BTC/USD |
| Ethereum | ETHA, ETHUSD, ETH/USD |
| Income | JEPQ, JEPI, SCHD, DIVO |
| (+ 7 more groups) | Financials, Healthcare, Energy, Intermediate Bonds, Silver, Oil, Commodity Broad |

Groups are expanded into bidirectional lookup maps at startup. Unmapped tickers are only identical to themselves (no false positives).

#### 17.2 30-Day Enforcement

On every buy order: `check_wash_sale(ticker)` checks for any `Closed_Loss` trade where the ticker matches any member of the similar set AND `close_date >= today − 30 days`. If found: `blocked=True`, order skipped, capital redirected to SGOV, compliance WARNING logged. Runs on every buy order including rebalances.

---

## Section XVIII — Testing Framework

### Simple Explanation

> **Think of it like this:** 317 automated tests run to make sure every part of the system works correctly. Think of them like a quality-control checklist before a car leaves the factory. Every math formula, every safety rule, every AI guardrail gets tested automatically every time the code changes.

```
 317 AUTOMATED TESTS ACROSS 7 MODULES
 ──────────────────────────────────────────────────────────────
  Signal Guard    — 3 guards, edge cases, integration
  Groq Budget     — token counting, rate limits, resets
  LLM Cache       — cache hit/miss, TTL, fingerprinting
  Shared Library  — RiskProfile, ExitBracket, CB, VaR
  Data Integrity  — snapshot validation, staleness, NaN, corr
  Gemini Auditor  — response parsing, veto logic, fail-open
  Microstructure  — OFI, VAMP, VPIN (117 tests, 13 classes)
                    ├── Order-book primary API tests
                    ├── OHLCV backward-compat tests
                    ├── MicrostructureSignal factory tests
                    ├── PenaltyTracker (persist, decay, throttle)
                    ├── Parametric VaR tests
                    ├── VaRCircuitBreaker tests
                    └── ExecutorVaRGate (5 tests proving skip behavior)
  
  All yfinance calls mocked (no live network dependency in tests)
  All tests deterministic — no random seeds, no timing dependencies
```

### Advanced Technical Specification

Test command:
```bash
cd trading-platform && python3 -m unittest \
  tests.test_signal_guard tests.test_groq_budget tests.test_llm_cache \
  tests.test_shared_lib tests.test_data_integrity tests.test_gemini_auditor \
  tests.test_microstructure -v
```

**Test isolation:** All external dependencies (yfinance, Groq API, Gemini API, Alpaca API, Kraken API, PostgreSQL) are mocked using `unittest.mock.patch`. Tests are fully offline and produce deterministic results regardless of network or market state.

**Coverage design:** Each module's test class targets: normal operation (golden path), edge cases (empty inputs, zero values, boundary conditions), failure modes (network errors, malformed data), and integration (cross-module interactions like ExecutorVaRGate tests that exercise `compute_daily_var()` → `execute_allocations()` interaction).

---

## Appendix A — Complete Risk Hierarchy

The following is the ordered sequence of risk checks that fire before any order is placed, from outermost to innermost:

```
1. MARKET HOURS CHECK          Is the market open? Is it a blackout period?
2. DATA CIRCUIT BREAKER        Is the market data fresh, non-null, non-zero?
3. SIGNAL GUARD (HARD)         Temporal quarantine? (Fri PM → Mon AM, ±30min events)
4. SIGNAL GUARD (SOFT)         Multi-source consensus, sentiment divergence
5. KILL SWITCH CHECK           Has today's drawdown exceeded 5%?
6. VaR CIRCUIT BREAKER         Does portfolio VaR exceed the daily loss limit?
7. GEMINI VETO CHECK           Is this ticker blocked by the daily auditor?
8. WASH SALE COMPLIANCE        Was this or a similar ticker closed at a loss <30 days ago?
9. ZERO-KELLY FILTER           Is Kelly fraction ≤ 0? → Force SGOV
10. OVERHEATED ASSET FILTER    Is Z>2 or RSI>75? → Cut 50%, route to SGOV
11. LEVERAGED CAP CHECK        Would this push leveraged risk above 20% total?
12. PER-POSITION CAP CHECK     Would this exceed 15% of equity in one position?
13. MARGIN BLOCK               Is remaining cash ≤ 0?
14. SPY EMA ANCHOR (BULL ONLY) Is SPY above its 20-day EMA?
    ─────────────────────────────────────────────────────────────────────────
    ORDER PLACED (if all gates passed)
```

For Kraken (Davy Jones), the order of gates is:

```
1. CIRCUIT BREAKER             >3% price drop in 30 minutes → 6hr pause
2. PENALTY THROTTLE            Kraken API penalty bucket >80% → skip cycle
3. VPIN PRE-CHECK              VPIN > 0.70 → skip entry
4. MICROSTRUCTURE FILTER       OFI directional gate + VPIN formal block (≥0.80)
5. RSI CONFIRMATION            RSI > RSI_OVERSOLD threshold → no entry
6. Z-SCORE ENTRY GATE          Z > −ZSCORE_ENTRY threshold → no entry
7. MAX POSITIONS               ≥ MAX_POSITIONS open → no new entry
8. CASH RESERVE                Position notional > available equity → skip
    ─────────────────────────────────────────────────────────────────────────
    ORDER PLACED (if all gates passed)
```

---

## Appendix B — Environment Variables and Secrets

| Secret | Purpose | Required By |
|---|---|---|
| `ALPACA_API_KEY` | Alpaca paper trading broker | Alpaca platform |
| `ALPACA_SECRET_KEY` | Alpaca paper trading broker | Alpaca platform |
| `GROQ_API_KEY` | Groq Llama 3.3 70B inference | Alpaca platform |
| `KRAKEN_API_KEY` | Kraken Pro exchange (live mode) | Kraken bot |
| `KRAKEN_SECRET_KEY` | Kraken Pro exchange (live mode) | Kraken bot |
| `NEWS_API_KEY` | NewsAPI.org headlines | Alpaca platform |
| `FRED_API_KEY` | FRED economic data | Alpaca platform |
| `DATABASE_URL` | PostgreSQL connection string | Both platforms |
| `STRIPE_SECRET_KEY` | Stripe subscription billing | AlgoEdge SaaS |
| `STRIPE_PUBLISHABLE_KEY` | Stripe frontend checkout | AlgoEdge SaaS |
| `AI_INTEGRATIONS_GEMINI_BASE_URL` | Gemini via Replit proxy | Gemini auditor |

---

*This document represents the complete functional, mathematical, and architectural profile of the AlgoEdge quantitative trading ecosystem as of March 2026, incorporating all Hybrid Agentic Architecture upgrades through Stage 4. It is intended for technical audit, independent review, and strategic assessment of the platform's design quality, risk governance, and operational soundness.*
