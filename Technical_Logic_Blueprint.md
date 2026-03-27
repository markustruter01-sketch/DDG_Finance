# Technical Logic Blueprint
## AI-Driven Quantitative Trading Platform — Deep-Learning Research Document

---

## I. Mathematical Core

### Regime Classification via Moving Average Crossover

The system's primary directional signal derives from a dual-timeframe momentum framework applied across a fixed eight-asset universe: SPY, QQQ (equity), TLT, GLD (safe haven), BTC/USD, ETH/USD, ATOM/USD (crypto spot), and SGOV (cash proxy). For each asset, the data layer computes two Simple Moving Averages from daily closing prices fetched via yfinance with a six-month lookback window. The three-month moving average spans 63 trading bars, calculated as MA₆₃ = (1/63) × Σ Close_{t-i} for i = 0 to 62, while the six-month moving average spans 126 bars using the same arithmetic mean formula. An asset is classified as having "positive momentum" on a given timeframe when its latest closing price exceeds the corresponding moving average. The LLM receives both momentum labels — `momentum_3mo` and `momentum_6mo` — as structured fields in its analysis prompt, along with the raw price data, and is instructed to classify the macro regime as Bull, Bear, or Sideways according to a codified rule matrix.

In a Bull regime, the system expects GDP growth, low unemployment, a declining VIX, and positive credit spreads; the LLM is permitted to allocate across three to seven risk assets (equities, crypto, commodities) that exhibit positive momentum on both timeframes. In a Bear regime — signaled by recession indicators, rising unemployment, VIX above 25, and tightening credit — the LLM is restricted to one to four safe-haven assets (TLT, IEF, GLD, SLV) that still show positive momentum. The Sideways regime represents mixed macro signals and range-bound price action, permitting zero to three mean-reversion plays on oversold assets or, if no high-conviction setup exists, a full allocation to SGOV. This last condition — defaulting to 100% cash when conviction is insufficient — is a core architectural principle: the system never forces a trade.

### RSI Computation and Overheated-Asset Detection

The Relative Strength Index is calculated using Wilder's smoothing method across a 14-period lookback. For each daily bar, the algorithm computes the magnitude of upward price changes (gains) and downward changes (losses), then applies an exponential moving average with a smoothing factor of 1/14 to both series independently. The RSI formula is RSI = 100 − [100 / (1 + Average_Gain / Average_Loss)]. Values above 75 flag an asset as "overheated" on the RSI dimension, while values below 25 would flag it as oversold — a potential mean-reversion candidate in Sideways regimes.

### Z-Score Statistical Deviation

The system also computes a 200-day Z-score for each asset, measuring how far the current price has deviated from its long-run mean in standard-deviation units. The formula is Z = (Price_latest − μ₂₀₀) / σ₂₀₀, where μ₂₀₀ is the arithmetic mean and σ₂₀₀ the standard deviation of the trailing 200 daily closes. A Z-score exceeding 2.0 marks an asset as statistically overheated. The executor enforces a hard policy: any overheated asset (Z > 2.0 or RSI > 75) receives a 50% notional allocation cut, with the redirected capital rerouted to SGOV. This is not an LLM decision — it is a deterministic Python guardrail that fires after the LLM's allocation but before order placement, ensuring the system cannot chase parabolic moves regardless of the model's conviction.

### Volatility Measurement and Calm-versus-Volatile Differentiation

The system quantifies realized volatility using a 20-day rolling window of log returns. Daily log returns are computed as r_d = ln(P_t / P_{t-1}), and annualized volatility is derived as Vol₂₀d = √(Var(r_{last 20}) × 252) × 100, expressed as a percentage. This value is injected into the LLM prompt alongside the RSI and Z-score, allowing the model to calibrate its conviction scores against recent price dispersion. A custom Market Fear and Greed Index, computed internally from SPY's technical profile, provides an additional volatility signal: volatility below 12% contributes a +5 "calm" score, while volatility above 30% applies a −10 "volatile" penalty. The combined sentiment score, on a 0–100 scale, flows into the LLM's context and is independently displayed on the dashboard's sentiment gauges.

### 2× ATR Ratchet Trailing Stops

Position risk management uses a volatility-adaptive trailing stop based on the Average True Range. The ATR is computed using a 14-period lookback on 30 days of daily OHLC data. For each bar, the True Range is TR = max(High − Low, |High − Prev_Close|, |Low − Prev_Close|), and the ATR is the arithmetic mean of the most recent 14 True Range values. When a new position is filled, the initial stop is set at Initial_Stop = Fill_Price − (2.0 × ATR). If ATR data is unavailable (e.g., for newly listed assets), the system falls back to a static 2% stop: Fill_Price × 0.98. The stop price is floored at $0.01 to prevent negative values.

The "ratchet" mechanism ensures the stop only moves in the trade's favor. On every subsequent 15-minute execution cycle, the system computes a proposed new stop as Proposed_Stop = Current_Price − (2.0 × ATR). If Proposed_Stop exceeds the existing stop price, the stop is updated and a new GTC (Good 'Til Canceled) stop-sell order replaces the previous one on the broker. If the proposed stop is lower than or equal to the existing stop, no action is taken — the stop never widens. This creates a one-way ratchet that locks in gains as price advances while giving the position exactly 2× ATR of breathing room, calibrated to the asset's own recent volatility. The ratchet state — including `symbol`, `stop_price`, `fill_price`, `atr`, and `last_updated` — is persisted to the `ratchet_stops` table in PostgreSQL, ensuring continuity across process restarts.

### Kelly Criterion Position Sizing

Capital allocation per slot uses a Half-Kelly formulation derived from the classic Kelly Criterion. The full Kelly fraction is f* = p − q/b, where p is the probability of winning (mapped directly from the LLM's conviction score, 0.0 to 1.0), q = 1 − p is the probability of losing, and b is the net odds ratio computed as take_profit_pct / |stop_loss_pct|. The system then applies a conservative 50% multiplier (KELLY_MULTIPLIER = 0.50) to produce a Half-Kelly fraction, and hard-caps the result at 20% of portfolio equity (MAX_KELLY_FRACTION = 0.20). If the calculation yields a non-positive value — indicating negative expected value — the fraction is set to zero and the slot defaults to SGOV. After individual Kelly fractions are computed, the allocator applies an even-weight override: all active (non-SGOV) slots with conviction above the minimum threshold receive equal weight, calculated as 1/N where N is the count of active slots. Finally, a normalization pass ensures total allocation does not exceed 100% of equity by scaling all fractions proportionally if their sum exceeds 1.0.

---

## II. The Learning Framework: Retrieval-Augmented Generation Loop

The platform implements a closed-loop learning system that feeds the LLM's own historical reasoning back into its decision context, creating a form of Retrieval-Augmented Generation built on a relational database rather than a vector store. The loop operates in four phases: storage, retrieval, injection, and decision.

### Phase 1: Trade Journaling and Outcome Storage

Every trade proposed by the LLM is logged to a persistent trade journal at the moment of execution. The journal entry captures the ticker, asset class, conviction score, the LLM's original thesis (a natural-language explanation of its reasoning at trade entry), intended price, actual fill price, and calculated slippage. The trade status is initially set to "Active." When the position is later closed — either by a stop-loss trigger, a take-profit exit, or a portfolio rebalance — the post-mortem process calls `update_trade_outcome`, which computes the realized P&L percentage and updates the status to either "Closed_Win" (if P&L ≥ 0) or "Closed_Loss" (if P&L < 0). This outcome labeling is the foundation of the learning signal.

### Phase 2: Retrieval from the Trade Journal

On each new analysis cycle, the feedback injection module queries the trade journal for the five most recent losses and three most recent wins. This asymmetric retrieval — biasing toward losses — is deliberate: the system prioritizes avoiding repeated mistakes over reinforcing successes. Each retrieved record includes the ticker, asset class, P&L percentage, the LLM's original thesis at entry, and the slippage incurred. The retrieval is purely recency-based rather than similarity-based; there is no embedding or vector search involved. The structured relational schema serves as the memory, and the SQL query itself functions as the retrieval mechanism.

### Phase 3: Prompt Injection and Contextual Framing

The retrieved trade records are formatted into two distinct prompt blocks and injected into the LLM's system prompt. The loss block is framed as "CRITICAL — LEARNING FROM PAST FAILURES" and presents each failed trade with its ticker, P&L percentage, and the model's own thesis, explicitly instructing the LLM: "Review your most recent failed strategies. Adjust your reasoning today to avoid repeating the logic that led to these losses." The win block reinforces successful patterns by showing what worked and why. A separate slippage warning block identifies "worst offender" tickers where execution friction was highest, prompting the model to either avoid those instruments or reduce position sizes.

Beyond the journal feedback, the system now enriches the prompt with real-time market intelligence gathered from five additional data sources: the Crypto and Market Fear & Greed indices (quantifying crowd sentiment), the economic calendar with active blackout status (flagging FOMC, NFP, CPI, and other macro releases within a ±30-minute trading window), P&L attribution statistics broken down by regime and asset class, portfolio-level risk metrics including Sharpe ratio and annualized volatility computed from performance snapshots, and portfolio correlation warnings highlighting any asset pairs with Pearson correlation above 0.85. This multi-source context injection transforms the LLM from a purely technical analyzer into a macro-aware, sentiment-informed, self-critiquing agent.

### Phase 4: Decision and Loop Closure

The augmented system prompt, combining the base strategy rules, the RAG feedback, and the real-time market intelligence, is sent to Groq's Llama 3.3 70B Versatile model with a temperature of 0.4 for the analysis call (balancing creativity with consistency). The model generates a structured JSON allocation plan specifying the regime classification, individual slot allocations with conviction scores, take-profit and stop-loss levels, and natural-language theses for each position. This output is validated against Pydantic schemas, executed by the order engine, and the new trades are journaled — closing the loop. The next cycle's LLM call will retrieve these trades' outcomes, creating a continuous, self-referential learning process where the model literally reads its own past reasoning and adjusts.

---

## III. Algorithmic Guardrails

### The Kill Switch: Daily Drawdown Circuit Breaker

The kill switch implements an intraday drawdown protection mechanism with a default threshold of 5% (configurable via settings). At market open each morning, the `reset()` function captures the account's opening equity as the baseline for the day. On every subsequent execution cycle — approximately every 15 minutes — the `check()` function recomputes the current drawdown as (opening_equity − current_equity) / opening_equity. If this value meets or exceeds the threshold, the switch "trips": it sets an internal flag, immediately calls `close_all_positions()` to liquidate the entire portfolio at market, logs a critical alert, and fires a Discord notification. Once tripped, the switch blocks all further trading for the remainder of the day; the `check()` function returns True immediately on subsequent calls, short-circuiting any analysis or execution logic. The kill switch state is maintained in-memory (not persisted to database), meaning a process restart would clear it — an intentional design choice that allows manual intervention via process management as a last-resort override.

The front-end displays the kill switch state in the global header bar at all times. When armed (normal state), it shows a green "ARMED" indicator. When tripped, the indicator turns red with "TRIPPED" text, and the system status banner shifts to an amber "DEGRADED" state. The Control Panel at the bottom of the dashboard provides two manual override buttons: "Trip Kill Switch" (which opens a confirmation modal before liquidating everything) and "Reset Kill Switch" (which clears the tripped state and re-initializes the equity baseline). Both require explicit user confirmation, implementing the Human-in-the-Loop principle for the most consequential system actions.

### The DA-HWM Profit Sweep Mechanism

The profit sweep system automates capital preservation by routing 20% of new trading profits into JEPQ (a high-yield income ETF) to generate compounding dividend income. The critical innovation is the Distribution-Adjusted High Water Mark (DA-HWM), which prevents JEPQ's own price appreciation or dividends from inflating the equity baseline and triggering circular sweeps. The adjustment formula is DA_Equity = Current_Equity − max(0, JEPQ_Unrealized_PL). By subtracting JEPQ's unrealized profit from the total equity before comparison, the system ensures that only new trading alpha — profits generated by the primary strategy — triggers a sweep.

The sweep eligibility calculation is Eligible_Profit = max(0, DA_Equity − HWM). If eligible profit exists and 20% of it exceeds the $1.00 minimum sweep amount (Alpaca's minimum order size), the system places a market buy order for JEPQ at that dollar amount. After execution, the new HWM is set to DA_Equity − Sweep_Amount, effectively "locking in" the sweep and establishing a new floor for future growth. This means the system must generate fresh alpha above the post-sweep HWM before the next sweep can trigger, preventing double-counting.

The vault state — including the HWM, total vaulted USD, sweep count, last sweep date, and DA adjustment — is persisted to the `vault_ledger` table in PostgreSQL (with SQLite fallback). On first initialization, when no ledger entry exists, the HWM is set to the current equity and no sweep is performed, establishing the initial baseline without generating a spurious sweep on day one. DRIP (Dividend Reinvestment Plan) is explicitly disabled system-wide to prevent the creation of fractional tax lots that could trigger wash sales outside the system's tracking scope.

---

## IV. Operational Infrastructure

### Database Architecture: PostgreSQL with SQLite Fallback

The platform uses a dual-backend persistence architecture centered on PostgreSQL for production with a transparent SQLite fallback for local development or database outages. The PostgreSQL layer is implemented using `psycopg2` with a `ThreadedConnectionPool` configured for 1 minimum and 8 maximum connections. A context manager handles connection lifecycle: acquiring from the pool, committing on success, rolling back on failure, and returning the connection to the pool in all cases.

The database schema is managed through an idempotent `ensure_schema()` function that runs `CREATE TABLE IF NOT EXISTS` statements on startup. The four primary tables are: `trades` (the trade journal with columns for ticker, conviction score, P&L percentage, original thesis, fill prices, and slippage), `performance_snapshots` (daily equity and P&L metrics recorded by the post-mortem process), `vault_ledger` (profit sweep state with HWM and vaulted totals), and `ratchet_stops` (active trailing stop levels with ATR values). Rather than implementing a one-time migration script from SQLite, every database-touching module checks `is_pg_available()` before each operation and branches internally — the same function signatures serve both backends, making the switch invisible to calling code. This approach eliminates migration risk entirely: the system simply begins using PostgreSQL when a connection string is available, with no data migration step required.

### Timezone Synchronization for NYSE Hours

Market hour awareness is centralized in a dedicated market clock module that uses the `America/New_York` timezone exclusively. The primary clock source is the Alpaca `/v2/clock` API endpoint, which returns the authoritative market status including awareness of holidays, early closes, and irregular sessions. The response is parsed to extract `is_open`, `next_open`, and `next_close` timestamps. If the Alpaca API is unreachable, a local fallback implements standard NYSE hours (9:30 AM to 4:00 PM ET) with holiday detection via the `holidays.NYSE()` library, supplemented by a manual holiday list for edge cases. The fallback also handles early-close days (1:00 PM ET) for Black Friday, Christmas Eve, and New Year's Eve. The scheduler uses this clock to gate two types of trading cycles: intraday cycles (every 15 minutes, Monday through Friday, 9:01 AM to 3:46 PM ET) and crypto cycles (every 15 minutes, 24/7, but only firing when the stock market is closed — ensuring the two cycle types never overlap).

### Exponential Backoff and Rate Limiting

API resilience is implemented through a decorator pattern that wraps all Alpaca broker calls. The retry logic specifically targets HTTP 429 (Too Many Requests) responses and applies full-jitter exponential backoff with a base delay of 1.0 seconds and a ceiling of 60.0 seconds. The jitter formula randomizes the actual delay between 0 and the calculated exponential value, preventing thundering-herd effects when multiple coroutines encounter rate limits simultaneously. The maximum retry count is 5 attempts before the call is allowed to fail. Additionally, a global rate limiter enforces a minimum spacing of 300 milliseconds between any two Alpaca API calls, staying safely within the 200 requests-per-minute limit. An async variant of the retry decorator is provided for coroutine-based code paths, maintaining the same backoff parameters while properly awaiting between retries.

---

## V. Risk and Compliance Logic

### The Wash Sale Similarity Matrix

IRS Section 1091 prohibits claiming a tax loss on a security if a "substantially identical" security is purchased within 30 days before or after the sale. The platform enforces this through a predefined similarity matrix that groups ETFs and assets tracking the same underlying index or commodity. The matrix contains 14 similarity groups: US Equity (SPY, IVV, VOO), Tech (XLK, VGT, FTEC), Financials (XLF, VFH), Healthcare (XLV, VHT), Energy (XLE, VDE), Long Bonds (TLT, EDV, VGLT), Intermediate Bonds (IEF, VGIT), Gold (GLD, IAU, SGOL), Silver (SLV, SIVR), Oil (USO, OILU), Commodity Broad (PDBC, DJP), Bitcoin (IBIT, GBTC, BTCUSD, BTC/USD), Ethereum (ETHA, ETHUSD, ETH/USD), and Income (JEPQ, JEPI, SCHD, DIVO).

At runtime, the similarity groups are expanded into a bidirectional lookup map: for any ticker, the system can instantly retrieve its full set of "substantially identical" counterparts as a frozen set. If a ticker is not present in any group, only the ticker itself is considered identical (no false positives from unmapped assets).

### The 30-Day Lookback Enforcement

When the executor prepares to place a buy order, it calls `check_wash_sale(ticker)` before submission. This function computes a cutoff date 30 days before the current date, retrieves the set of similar tickers for the proposed purchase, and queries the trade journal for any record where the status is "Closed_Loss," the ticker matches any member of the similar set, and the close date falls on or after the cutoff. If a matching loss is found, the function returns `blocked=True` with a detailed reason string identifying the conflicting trade, its loss date, and the similarity group. The executor skips the order entirely, logs a compliance warning, and the capital is redirected to SGOV. This check runs on every single buy order, including rebalances, ensuring no wash sale can occur even through indirect exposure to substantially identical assets.

---

## VI. Front-End Architecture and UI/UX Integration

### Component Hierarchy and State Synchronization

The dashboard is a React 19 application built with Vite, styled with Tailwind CSS v4, and managed entirely through TanStack React Query for server state. The application contains no local state management library (no Redux, no Zustand) — all data flows through query hooks that poll the FastAPI backend at calibrated intervals. The polling cadence follows a priority hierarchy: system health and platform status refresh every 10 seconds (ensuring kill switch state is always near-real-time), portfolio equity and live positions refresh every 30 seconds, the growth vault and auditor report refresh every 60 seconds, and lower-priority data like market correlation and sentiment refresh every 120 seconds. The AI commentary endpoint uses a hybrid approach: React Query's `staleTime` is set to 25 minutes (matching the Groq rate limit budget), while a custom `setInterval` in the AI Brain section triggers a refresh mutation every 90 seconds, creating a balanced polling pattern that respects the LLM's token budget while keeping commentary reasonably fresh.

### The Dual-Agent Interface

The dashboard presents two distinct AI personas in side-by-side panels. The first agent, "The Degen Oracle," functions as the primary strategy intelligence. Its visual representation is a pulsing neural network SVG with animated synaptic connections and energy rings, communicating an active, thinking presence. The Oracle's speech bubble displays the LLM's latest market commentary — a 4-6 sentence analysis that now incorporates sentiment data, correlation warnings, economic calendar awareness, and attribution insights, enriched by the multi-source prompt injection described in Section II. When the user clicks the Oracle's avatar, an expanded modal reveals the current strategy thesis, target allocations with Kelly fractions and conviction rings, and a split view of "What Worked" (recent wins with P&L) and "What Failed" (recent losses with the LLM's original reasoning), making the RAG loop's inputs directly visible to the human operator.

The second agent, "Inspector Rekt," serves as the HITL auditor supervisor. Its visual representation is an animated shield with scanning lines and a central "eye" motif, communicating vigilance and oversight. The Inspector displays a real-time status badge (ALL_CLEAR, REVIEW_RECOMMENDED, or ACTION_REQUIRED) and a summary of its latest audit findings. The full audit modal breaks down five categories of automated checks: regime integrity (comparing the primary bot's classification against independently computed heuristics), compliance and wash sale exposure (cross-referencing allocations against the 30-day loss window), RAG look-ahead bias detection (flagging implausible win rates, suspiciously high-conviction wins, and hindsight language in trade theses), phantom drawdown analysis (monitoring proximity to the kill switch threshold and DA-HWM sanity), and ratchet stop integrity (validating that stop prices are below entry prices, within reasonable ATR distance, and not stale). Each finding carries a severity badge — INFO (green), WARNING (amber), ALERT (red), or HOLD (orange, specifically for compliance violations) — allowing the human operator to quickly identify items requiring attention.

### Kill Switch Proximity Visualization

The kill switch state is rendered in the global header bar, visible at all times regardless of scroll position. In the armed state, a shield icon with 60% opacity displays "ARMED" in green text. When tripped, the icon turns fully opaque with bold red "TRIPPED" text, and the system status banner transitions to an amber "DEGRADED" state with a warning message. The auditor's phantom drawdown check specifically monitors the "danger zone" — when daily drawdown is within 0.5% of the kill switch threshold — and surfaces this as an ALERT-severity finding, giving the human operator advance warning before automatic liquidation triggers.

### Human-in-the-Loop Manual Override Architecture

The Control Panel component provides five manual override actions, each gated by a confirmation modal to prevent accidental activation. "Run Analysis (Dry Run)" triggers a full pipeline cycle without executing trades, allowing the operator to preview the LLM's allocation plan. "Run Analysis (LIVE)" executes a real trading cycle with actual order placement, requiring explicit confirmation of the live-execution risk. "Run Post-Mortem" triggers the end-of-day analysis that closes positions, computes P&L, updates the trade journal, and generates performance snapshots. "Reset Kill Switch" clears the tripped state and re-establishes the equity baseline for the next trading day. "Trip Kill Switch" is the emergency button — a red-bordered danger action that, after modal confirmation, immediately liquidates all positions and halts trading. Each action displays the raw JSON API response in an expandable output block, providing the operator with unambiguous confirmation of exactly what the system did.

### Layout Priority and Information Architecture

The dashboard is organized into four priority tiers, structured so the most actionable, time-sensitive information appears first. Tier 1 ("What's Happening Right Now") presents the auto-trading toggle, portfolio metrics (equity, cash, buying power, vault, yield), the live positions table, and the economic calendar — everything a trader needs to assess current exposure without scrolling. Tier 2 ("Portfolio Health and Risk") groups risk metrics, sentiment gauges, and the correlation matrix in a unified three-column risk zone, followed by performance charts alongside P&L attribution. Tier 3 ("AI Intelligence") places the Oracle and Inspector side-by-side, followed by the best/worst trade hero cards. Tier 4 ("Tools and History") houses the strategy backtester, allocation plans, trade journal, learning context, vault management, and mission control. This hierarchy ensures that in a crisis — a kill switch trip, a blackout event, or a sudden drawdown — the operator sees the critical information immediately upon loading the dashboard.

---

## VII. Scheduling and Pipeline Orchestration

The system operates four APScheduler jobs, each bound to specific time windows and market conditions. The primary intraday cycle runs every 15 minutes from 9:01 AM to 3:46 PM ET, Monday through Friday, executing the full pipeline: data refresh, indicator computation, RAG feedback retrieval, LLM analysis, allocation validation, order execution, and journal logging. The crypto-only cycle runs every 15 minutes around the clock but only fires when the stock market is closed, trading BTC/USD, ETH/USD, and ATOM/USD via Alpaca's native crypto infrastructure with GTC orders and a $25 minimum notional. The evening post-mortem runs at 4:10 PM ET on weekdays, closing the day's positions, computing realized P&L, updating the trade journal, generating performance snapshots, and running the profit sweep logic. The daily audit runs at 4:30 PM ET — 20 minutes after the post-mortem — giving the auditor a complete picture of the day's activity including closed positions and final P&L. All four jobs are paused by default on startup; the operator must explicitly enable auto-trading via the dashboard toggle or the API endpoint before any automated execution begins.

---

*This document represents the complete functional profile of the system as of its current deployment state, covering the mathematical foundations, machine learning feedback architecture, risk management guardrails, infrastructure resilience patterns, regulatory compliance logic, and human-interface design. Each section is written to provide sufficient technical depth for a deep-learning research system to understand, model, and reason about the platform's behavioral characteristics.*
