export function WhitepaperContent() {
  return (
    <div className="max-w-4xl mx-auto px-8 py-10 text-slate-200 leading-relaxed">
      <header className="mb-12 text-center">
        <h1 className="text-3xl font-bold text-white mb-4 leading-tight">
          AlgoEdge &amp; SPY/QQQ Trend — Complete Technical Reference
        </h1>
        <div className="h-px w-32 mx-auto bg-indigo-500/50 my-6" />
        <p className="text-sm text-slate-400 italic max-w-2xl mx-auto">
          A full-system architecture document covering every algorithm, risk system, data flow, and design decision across the AI-driven quantitative trading ecosystem. Hybrid Agentic Architecture — Stages 0–6. Six autonomous bots across equities, crypto, options, and forex. April 2026.
        </p>
        <div className="mt-6 p-4 bg-slate-800/60 border border-indigo-500/20 rounded-lg text-xs text-slate-400 text-left">
          <span className="text-indigo-300 font-semibold">Audit Notice: </span>
          This document is written to enable an independent AI or human auditor to fully evaluate the system's design quality, risk management soundness, and fitness for purpose without access to source code. Each section provides intent, mechanics, mathematical formulas, and design tradeoffs.
        </div>
      </header>

      {/* Section 0 — System Map */}
      <Section title="System Architecture Overview">
        <SimpleBox>
          <p>Think of this like a six-robot fleet with a shared toolbox, a control room, and a notification system that texts you when they make money:</p>
          <AsciiDiagram>{`
  🤖 BOT 1 (Alpaca)           🤖 BOT 2 (SPY/QQQ Trend)    🤖 BOT 3 (Jerome)
  Stocks + Crypto 9-4 PM      24/7 Crypto Kraken        24/7 Crypto Kraken

  🤖 BOT 4 (Sector Rotation)          🤖 BOT 5 (Defensive Guardian)  🤖 BOT 6 (Forex Gump)
  24/7 Crypto Kraken           Options 3:30 PM Daily     Forex H4 Swing Trading

  All share ──▶  🔧 Shared Safety + Alert System  ◀── (circuit breakers, risk)
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         📊 Database  🖥 Dashboard  📱 Telegram/Discord Alerts
          (trade log)  (you see it)  (profit notifications)
          `}</AsciiDiagram>
        </SimpleBox>

        <p>The ecosystem consists of six autonomous trading engines across four asset classes, sharing a common risk infrastructure, a PostgreSQL database, a React dashboard, and a real-time alert notification system:</p>
        <Table
          headers={["Component", "Purpose", "Technology"]}
          rows={[
            ["Alpaca AI Platform (Bot #1)", "Equities + crypto, LLM-driven regime allocation", "Python / FastAPI / Groq Llama 3.3 70B"],
            ["SPY/QQQ Trend (Bot #2)", "24/7 crypto mean-reversion with microstructure alpha", "Python / ccxt / Kraken Pro"],
            ["Jerome (Bot #3)", "24/7 crypto — independent Kraken instance", "Python / ccxt / Kraken Pro"],
            ["Sector Rotation (Bot #4)", "24/7 crypto — independent Kraken instance", "Python / ccxt / Kraken Pro"],
            ["Defensive Guardian (Bot #5)", "Options volatility squeeze — pure quant, zero LLM", "Python / Alpaca Options API"],
            ["Forex Gump (Bot #6)", "Forex H4 swing trading — 5 major pairs", "Python / yfinance / OANDA-ready"],
            ["Shared Core Library", "RiskProfile, ExitBracket, CircuitBreaker, VaR — used by all bots", "Pure Python (shared/)"],
            ["PostgreSQL + SQLite", "Trade journals, vault ledgers, ratchet stops, degradation log", "psycopg2 + sqlite3"],
            ["React Dashboard", "Real-time monitoring, HITL controls, 6-tab multi-bot UI", "React 19 / Vite / TanStack Query"],
            ["Alert System", "Batched profitable trade notifications with configurable frequency", "Telegram Bot API / Discord Webhooks"],

          ]}
        />
      </Section>

      {/* Section 1 */}
      <Section title="Mathematical Core: Regime Classification">
        <SimpleBox>
          <p>The system looks at price trends for 22 different investments and sorts the market into three "moods" — Bullish (take risks), Bearish (hide in safe stuff), or Sideways (sit in cash). Two AIs check whether it's safe to act on those moods.</p>
          <AsciiDiagram>{`
  PRICE TREND CHECK (run every 15 min)
  ──────────────────────────────────────────────────
   Today's SPY price: $520
   3-month average:   $505  ──▶ Above → Positive 🟢
   6-month average:   $490  ──▶ Above → Positive 🟢
   SPY above 20-day EMA?  YES ──▶ Bull gate OPEN 🟢

  RSI OVERHEAT GAUGE  (0 = cold, 100 = boiling)
  ──────────────────────────────────────────────────
   [■■■■■■■■■■■■■░░░] RSI 65 → Normal ✅
   [■■■■■■■■■■■■■■■■] RSI 76 → OVERHEATED → cut 50% ⚠
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Dual-Timeframe Momentum Framework">
          <p>Two Simple Moving Averages drive the primary directional signal across all 22 assets:</p>
          <Formula>MA₆₃ = (1/63) × Σ Close_(t-i) for i = 0 to 62 (3-month)</Formula>
          <Formula>MA₁₂₆ = (1/126) × Σ Close_(t-i) for i = 0 to 125 (6-month)</Formula>
          <p>An asset has "positive momentum" when <Mono>Close_latest &gt; MA</Mono>. Both labels (<Mono>momentum_3mo</Mono>, <Mono>momentum_6mo</Mono>) flow into the LLM prompt as structured fields.</p>
        </SubSection>

        <SubSection title="SPY EMA-20 Anchor Gate (v4.3)">
          <p>A hardened macro gate prevents Bull-regime and leveraged allocations unless SPY is above its 20-day Exponential Moving Average:</p>
          <Formula>EMAₜ = Closeₜ × k + EMA_(t-1) × (1 − k),  k = 2/(20+1) ≈ 0.0952</Formula>
          <p>If <Mono>spy_above_ema_20 = False</Mono>, all Bull-mode and leveraged ETF allocations are blocked regardless of LLM output. This prevents chasing false rallies.</p>
        </SubSection>

        <SubSection title="RSI and Z-Score Overheated Guards">
          <p><strong>RSI (Wilder's smoothing, 14-period):</strong></p>
          <Formula>RSI = 100 − [100 / (1 + Avg_Gain / Avg_Loss)]</Formula>
          <p><strong>200-day Z-Score:</strong></p>
          <Formula>Z = (Price_latest − μ₂₀₀) / σ₂₀₀</Formula>
          <p>When <Mono>Z &gt; 2.0</Mono> OR <Mono>RSI &gt; 75</Mono>: allocation cut 50%, redirected to SGOV. This fires <em>after</em> LLM output but <em>before</em> order placement — it cannot be overridden by the model.</p>
        </SubSection>

        <SubSection title="Macro-Regime Logic Matrix">
          <Table
            headers={["Regime", "Conditions", "Permitted Allocations"]}
            rows={[
              ["Bull", "GDP growth, VIX < 20, SPY above EMA-20", "3–7 risk assets; leveraged ETFs allowed (≤20% total)"],
              ["Bear", "VIX > 25, rising unemployment, credit stress", "1–4 safe havens with positive momentum"],
              ["Sideways", "Mixed signals, range-bound prices", "0–3 mean-reversion plays or 100% SGOV"],
            ]}
          />
        </SubSection>

        <SubSection title="Extended Asset Universe (v4.3 — 22 Assets)">
          <Table
            headers={["Category", "Tickers", "Order Type"]}
            rows={[
              ["Equities (Sectors)", "SPY, QQQ, XLK, XLF, XLV, XLE, IWM", "DAY min $100"],
              ["Safe Havens / Bonds", "TLT, IEF, GLD, SLV", "DAY min $100"],
              ["Commodities", "USO, PDBC", "DAY min $100"],
              ["Crypto Spot", "BTC/USD, ETH/USD", "GTC min $25"],
              ["Leveraged Risk ⚡", "TQQQ, SOXL, UPRO (3× ETFs)", "DAY — Bull-only, ≤20% combined"],
              ["Cash Equivalent", "SGOV", "DAY"],
              ["Vault (Sweep Only)", "JEPQ", "DAY — LLM cannot sell"],
            ]}
          />
          <p>Leveraged ETFs use a tighter <Mono>1.5× ATR</Mono> stop (vs. standard 2× ATR) reflecting their higher realized volatility.</p>
        </SubSection>

        <SubSection title="Volatility Measurement">
          <Formula>r_d = ln(P_t / P_(t-1))</Formula>
          <Formula>Vol₂₀d = √(Var(r_(last 20)) × 252) × 100</Formula>
          <p>Injected into the LLM prompt and contributes to the internal Fear &amp; Greed score: Vol &lt; 12% → +5 calm bonus; Vol &gt; 30% → −10 volatile penalty.</p>
        </SubSection>
      </Section>

      {/* Section 2 — Data Circuit Breakers */}
      <Section title="Data Circuit Breakers (Stage 1)">
        <SimpleBox>
          <p>Before the AI even sees market data, four "bouncers" check that the data is real. If Bitcoin comes back as $0, or if data is more than 5 minutes old, the whole cycle is cancelled. Garbage in = garbage trades.</p>
          <AsciiDiagram>{`
  DATA QUALITY BOUNCER
  ──────────────────────────────────────────────────
   Market data arrives ──▶ [VALIDATOR]
                                │
      ┌───────────────┬─────────┴──────────┬──────────────┐
      ▼               ▼                    ▼              ▼
  Stale?          Any NaN /           Any price       SPY↔QQQ
  (>5 min)        missing?            = zero?         corr < 0.4?
      │               │                    │              │
   FAIL ─────────────────────────── ALL → ❌ BLOCK CYCLE
   PASS ─────────────────────────── ALL → ✅ Proceed to AI
          `}</AsciiDiagram>
        </SimpleBox>

        <p>The <Mono>validate_snapshot()</Mono> function in the shared library raises <Mono>DataCircuitBreakerError</Mono> on any of four failure modes. The analysis cycle is skipped and the previous cached regime is held.</p>

        <SubSection title="The Four Guard Layers">
          <Table
            headers={["Guard", "Trigger", "Severity"]}
            rows={[
              ["Staleness", "market_data.fetched_at > 5 min ago (2 min for crypto)", "Critical — skip cycle"],
              ["NaN / Missing", "Any None or NaN in closes, RSI, zscore, or volatility for any primary asset", "Critical — skip cycle"],
              ["Zero-Price", "Any asset returning price = 0.0 (feed error / API timeout)", "Critical — skip cycle"],
              ["Correlation", "Pearson corr(SPY 20d, QQQ 20d) < 0.4 — implausibly low, signals feed divergence", "Critical — skip cycle"],
            ]}
          />
          <p>The <Mono>ValidationResult</Mono> carries: <Mono>valid: bool</Mono>, <Mono>reason: str</Mono>, <Mono>severity</Mono>, and <Mono>failed_checks: list[str]</Mono>.</p>
        </SubSection>
      </Section>

      {/* Section 3 — Signal Guards & Cycle Memory */}
      <Section title="Signal Guards &amp; Agentic Cycle Memory (Stage 2)">
        <SimpleBox>
          <p>Originally the AI had "goldfish memory" — it forgot everything between 15-minute cycles. Now it remembers its last decision. It also runs three security guards that filter out bad signals BEFORE wasting any AI tokens. And it tracks its daily token budget so it never runs out.</p>
          <AsciiDiagram>{`
  SIGNAL GUARDS (run BEFORE calling the AI — free!)
  ──────────────────────────────────────────────────
   Guard 1: Is this news confirmed by >1 source?  [SOFT]
            NO → Remove headline, AI doesn't see it
   Guard 2: Is there a major event right now?      [HARD]
            FOMC/NFP/CPI ±30min OR Fri 2pm–Mon 9:30am
            YES → BLOCK entire cycle, use cached regime
   Guard 3: Is market volume suspiciously low?     [SOFT]
            5-day avg < 20-day avg + sentiment = Greed
            YES → Downgrade "Greed" to "Neutral"

  GROQ BUDGET TRACKER
  ──────────────────────────────────────────────────
   [■■■■■■■░░░░░░░░░░░░░] 35,000 / 100,000 tokens used today
   Min 90min between regime calls  |  Max 4 commentary calls/day
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Guard 1: Multi-Source Consensus (SOFT)">
          <p>Filters news headlines that appear in only one source. Requires confirmation from at least 2 of 5 news sources before a headline enters the LLM prompt. Prevents single-source FUD or hype from skewing the AI's analysis.</p>
          <p>Output: <Mono>filtered_headlines</Mono> — a clean subset passed to the LLM.</p>
        </SubSection>

        <SubSection title="Guard 2: Temporal Quarantine (HARD)">
          <p>Blocks all analysis during high-noise windows:</p>
          <ul className="list-disc ml-6 space-y-1 text-sm">
            <li>Friday 14:00 → Monday 09:30 ET (weekend illiquidity)</li>
            <li>±30 minutes around: FOMC, NFP, CPI, PCE, Jobs Report</li>
          </ul>
          <p>When hard-blocked: entire cycle skipped, cached regime returned, zero Groq tokens consumed.</p>
        </SubSection>

        <SubSection title="Guard 3: Price-to-Sentiment Divergence (SOFT)">
          <p>When SPY's 5-day average volume is below its 20-day average AND sentiment is "Greed" or "Extreme Greed": the sentiment band is downgraded one step. Prevents the AI from acting on bullish crowd sentiment during low-conviction, low-volume conditions.</p>
        </SubSection>

        <SubSection title="Groq Daily Token Budget Manager">
          <Table
            headers={["Constraint", "Default", "Env Variable"]}
            rows={[
              ["Min interval between regime calls", "90 minutes", "GROQ_MIN_REGIME_INTERVAL_MINUTES"],
              ["Max auto commentary calls/day", "4 per endpoint", "GROQ_COMMENTARY_DAILY_CAP"],
              ["Hard daily token cap", "100,000 tokens", "GROQ_DAILY_TOKEN_BUDGET"],
            ]}
          />
          <p>All counters reset at midnight UTC. The <Mono>force=True</Mono> flag on commentary bypasses the daily cap but never the hard token budget.</p>
        </SubSection>

        <SubSection title="LLM Response Cache (90-min TTL)">
          <p>Prevents redundant Groq calls when market signals haven't materially changed:</p>
          <ul className="list-disc ml-6 space-y-1 text-sm">
            <li><strong>Cache key:</strong> MD5 hash of <Mono>(call_type + momentum_fingerprint + news_fingerprint)</Mono></li>
            <li><strong>TTL:</strong> 90 minutes (configurable via <Mono>LLM_CACHE_TTL_MINUTES</Mono>)</li>
            <li><strong>Backing:</strong> <Mono>data/llm_response_cache.json</Mono> — survives short restarts</li>
          </ul>
          <p>Expected savings: 1–3 Groq calls/day on quiet days where signals are stable across consecutive 15-minute cycles.</p>
        </SubSection>

        <SubSection title="Cycle State Persistence &amp; Degradation Tracker">
          <p><Mono>data/cycle_state.py</Mono> persists: last_regime, last_analysis_timestamp, consecutive_sideways_cycles, last_allocation_plan across restarts. The degradation tracker records every system failure to PostgreSQL with de-duplication (15–30 min TTL per event type) and exponential escalation (doubles wait time per re-occurrence, capped at 4 hours).</p>
        </SubSection>
      </Section>

      {/* Section 4 — RAG Loop */}
      <Section title="The Learning Framework: Relational RAG Loop">
        <SimpleBox>
          <p>The AI keeps a diary of every trade. Before making new trades, it reads its own diary to avoid repeating mistakes. It fetches more losses than wins on purpose — learning from failure is more valuable than celebrating success.</p>
          <AsciiDiagram>{`
  THE LEARNING LOOP (every 15 min during market hours)
  ──────────────────────────────────────────────────────
  ┌─────────────────┐   ┌──────────────────┐
  │ 5 Recent LOSSES │──▶│                  │──▶ Groq Llama 3.3 70B
  │ 3 Recent WINS   │──▶│  PROMPT BUILDER  │       │
  │ Market data     │──▶│  + Sentiment     │    Allocations
  │ News headlines  │──▶│  + Econ Calendar │    → Orders
  │ Correlation map │──▶│  + Fear/Greed    │    → Added to Diary
  └─────────────────┘   └──────────────────┘    (loop closes)
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Phase 1: Trade Journaling">
          <p>Every executed trade is logged to the <Mono>trades</Mono> PostgreSQL table: ticker, asset_class, conviction_score, original_thesis (natural language), intended_price, fill_price, slippage (basis points). Status = "Active" until closed.</p>
          <p>On close: <Mono>update_trade_outcome()</Mono> sets status to <Mono>Closed_Win</Mono> (P&amp;L ≥ 0) or <Mono>Closed_Loss</Mono> (P&amp;L &lt; 0).</p>
        </SubSection>

        <SubSection title="Phase 2: Asymmetric Retrieval">
          <p>Retrieves <strong>5 most recent losses</strong> (bias toward failure avoidance) + <strong>3 most recent wins</strong> (pattern reinforcement). Pure recency-based SQL — no vector embeddings or similarity search. The relational schema is the memory; the SQL query is the retrieval mechanism.</p>
          <Table
            headers={["Feature", "Our Relational RAG", "Traditional Vector RAG"]}
            rows={[
              ["Logic Type", "Structured, temporal, exact SQL", "Semantic and approximate"],
              ["Auditability", "High — explicit logic chains", "Low — black-box similarity scores"],
              ["Compliance Use", "Critical for 30-day wash-sale lookback", "Cannot enforce precise date constraints"],
            ]}
          />
        </SubSection>

        <SubSection title="Phase 3: Multi-Source Prompt Injection">
          <p>The enriched LLM system prompt includes:</p>
          <ul className="list-disc ml-6 space-y-1 text-sm">
            <li><strong>Loss block</strong> framed as "CRITICAL — LEARNING FROM PAST FAILURES" with original thesis per trade</li>
            <li><strong>Win block</strong> reinforcing successful patterns</li>
            <li><strong>Slippage warnings</strong> highlighting worst-offender tickers</li>
            <li><strong>Crypto + Market Fear &amp; Greed indices</strong> (0–100)</li>
            <li><strong>Economic calendar blackout</strong> status (FOMC, NFP, CPI within ±30 min)</li>
            <li><strong>P&amp;L attribution</strong> by regime and asset class</li>
            <li><strong>Pearson correlation warnings</strong> for pairs with corr &gt; 0.85</li>
          </ul>
        </SubSection>

        <SubSection title="Phase 4: Groq Inference">
          <p>Model: <Mono>Llama 3.3 70B Versatile</Mono> at temperature 0.4. Output: structured JSON allocation plan — regime label, slot allocations with conviction scores (0–1), take-profit/stop-loss levels, natural-language theses. Validated against Pydantic schemas before any order is placed. Invalid JSON = cycle abort.</p>
        </SubSection>
      </Section>

      {/* Section 5 — Gemini Auditor */}
      <Section title="Gemini Daily Self-Critic Auditor (Stage 3)">
        <SimpleBox>
          <p>Every morning at 4:15 AM, before the market opens, a second AI (Google's Gemini) looks at yesterday's trades and asks: "Did my colleague do something stupid?" It writes a report card and flags any stocks it thinks should be blocked for today.</p>
          <AsciiDiagram>{`
  GEMINI SELF-CRITIC AUDITOR (runs 4:15 AM ET daily)
  ──────────────────────────────────────────────────────
   Yesterday's data: trades + equity curve + system events
              │
              ▼
   [GEMINI FLASH AI] — adversarial audit
   Checks: inflated conviction? bad regime? wash-sale blindness?
              │
              ▼  veto_conditions.json
   ┌──────────────────────────────────────────┐
   │  verdict: "CAUTION"                      │
   │  vetoed_tickers: ["TSLA", "NVDA"]       │
   │  conditions: [max_conviction_cap: 0.85]  │
   └──────────────────────────────────────────┘
              │
              ▼
   Today's trading AI reads this → blocks vetoed tickers
   If Gemini is offline → fail-open → trading proceeds normally ✅
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Audit Pipeline">
          <ol className="list-decimal ml-6 space-y-2 text-sm">
            <li><strong>Data collection:</strong> Prior day's trade records, equity snapshots, degradation events from PostgreSQL</li>
            <li><strong>Sanitization:</strong> <Mono>gemini_context_sanitizer.py</Mono> compacts payload, redacts secrets, truncates thesis strings</li>
            <li><strong>Token budget:</strong> If payload &gt; 80% of context window, equity time-series chunked into 8-hour windows; Gemini called per chunk; results merged (union of vetoes)</li>
            <li><strong>Adversarial prompting:</strong> System prompt instructs Gemini to act as a hostile auditor</li>
            <li><strong>Response validation:</strong> Pydantic schema — invalid JSON = no file written</li>
          </ol>
        </SubSection>

        <SubSection title="Seven Adversarial Audit Targets">
          <Table
            headers={["Audit Target", "What Gemini Looks For"]}
            rows={[
              ["Conviction inflation", "Scores clustered above 0.85 with mediocre outcomes"],
              ["Regime contradiction", "Bear regime label with aggressive crypto buys"],
              ["Wash-sale blindness", "Same ticker appearing in losses then wins within 30 days"],
              ["Data anomalies", "Impossible P&L (>20% in one 15-min cycle), static equity"],
              ["Overconcentration", "Single ticker >15% of allocation budget"],
              ["Repeated degradations", "Same component failing >3× in one day"],
              ["Thesis quality", "Hindsight language, vague rationale, copy-pasted text"],
            ]}
          />
        </SubSection>

        <SubSection title="Output Schema &amp; Veto Enforcer">
          <p>Output written to <Mono>logs/veto_conditions.json</Mono> atomically (temp file → rename). The <Mono>core/veto_enforcer.py</Mono> reads it before every order with a 5-minute in-process cache.</p>
          <p><strong>Fail-open guarantee:</strong> If Gemini is unreachable, the DB query fails, or JSON can't be parsed — the previous <Mono>veto_conditions.json</Mono> is left untouched and <Mono>is_vetoed()</Mono> returns <Mono>False</Mono>. The auditor's absence never blocks the primary bot.</p>
          <p>Model: <Mono>gemini-3-flash-preview</Mono> via Replit AI Integrations proxy — never calls <Mono>gemini.google.com</Mono> directly.</p>
        </SubSection>
      </Section>

      {/* Section 6 — Risk Guardrails */}
      <Section title="Algorithmic Risk Guardrails">
        <SimpleBox>
          <p>These are the emergency brakes. No matter how confident the AI is, these hard rules override everything. They fire in strict order — outer gates first, then inner gates — before any order reaches the exchange.</p>
          <AsciiDiagram>{`
  COMPLETE RISK GATE CHAIN (Alpaca Platform)
  ──────────────────────────────────────────────────────────────
  1. 🚦 DATA CIRCUIT BREAKER    — Stale/NaN/zero data → skip cycle
  2. 🚦 SIGNAL GUARDS (HARD)    — Temporal quarantine → skip cycle
  3. 🛑 KILL SWITCH (5%)        — Daily drawdown too big → liquidate ALL
  4. 🛑 VaR CIRCUIT BREAKER     — Portfolio risk too high → block new entries
  5. 🛑 GEMINI VETO             — Ticker blocked by auditor → skip
  6. 🛑 WASH SALE (30d)         — Recent loss in similar ticker → skip
  7. 🚦 ZERO-KELLY FILTER       — Negative edge → force SGOV
  8. 🚦 OVERHEATED GUARD        — Z>2 / RSI>75 → cut 50%, reroute
  9. 🚦 LEVERAGED CAP (20%)     — Too much turbo exposure → block
  10. 🚦 POSITION CAP (15%)      — Too concentrated → cap
  11. 🚦 SPY EMA ANCHOR          — Bull entry only if SPY above EMA-20
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Kill Switch: 5% Daily Drawdown">
          <p>Captures <Mono>opening_equity</Mono> at market open. Every 15-minute cycle:</p>
          <Formula>drawdown = (opening_equity − current_equity) / opening_equity</Formula>
          <p>If <Mono>drawdown ≥ 0.05</Mono>: trips internally, calls <Mono>close_all_positions()</Mono> (market sells all holdings), fires Discord alert, blocks all trading for remainder of day. State is <strong>in-memory only</strong> — a process restart clears it (intentional manual-intervention escape hatch).</p>
        </SubSection>

        <SubSection title="VaR Circuit Breaker (Stage 4 — Historical Simulation)">
          <p>Before executing any allocation cycle, the executor computes portfolio 1-day Value-at-Risk using historical simulation over the last 30 days:</p>
          <Formula>var_pct = −percentile(sorted_daily_pnl, 5%)  [95% confidence]</Formula>
          <Formula>var_usd = var_pct × invested_usd</Formula>
          <Formula>var_tripped = var_usd &gt; daily_loss_limit_pct × total_equity</Formula>
          <p><strong>Critical contract:</strong> <Mono>var_pct</Mono> is a fraction of <em>invested capital</em>, not total equity. The USD scaling step is mandatory before comparison against the equity-relative limit.</p>
          <p>When tripped: all new entries blocked for the cycle. Existing positions, ratchet stops, and vault sweeps are unaffected. Reason <Mono>"var_circuit_breaker"</Mono> logged per blocked slot. Fail-open: VaR = 0.0 on any data failure.</p>
        </SubSection>

        <SubSection title="2× ATR Ratchet Trailing Stop">
          <p>ATR computed over 14-period lookback on 30 days of OHLC data:</p>
          <Formula>TR_t = max(High_t − Low_t, |High_t − Prev_Close|, |Low_t − Prev_Close|)</Formula>
          <Formula>ATR = (1/14) × Σ TR_(t-i) for i = 0 to 13</Formula>
          <Formula>Stop_initial = Fill_Price − 2.0 × ATR  (1.5× for leveraged ETFs)</Formula>
          <p><strong>Ratchet rule (one-way only):</strong> Every 15 minutes — if <Mono>Current_Price − 2×ATR &gt; Current_Stop</Mono>: update and replace GTC order on broker. Never widen. Persisted to <Mono>ratchet_stops</Mono> table.</p>
        </SubSection>

        <SubSection title="DA-HWM Profit Vault Sweep">
          <p>Routes 20% of new trading alpha into JEPQ (high-yield income ETF). The Distribution-Adjusted High Water Mark prevents JEPQ's own returns from triggering circular sweeps:</p>
          <Formula>DA_Equity = Current_Equity − max(0, JEPQ_Unrealized_PnL)</Formula>
          <Formula>Eligible_Profit = max(0, DA_Equity − HWM)</Formula>
          <p>Sweep condition: <Mono>Eligible_Profit &gt; 0</Mono> AND <Mono>0.20 × Eligible_Profit &gt; $1.00</Mono>. Post-sweep HWM: <Mono>HWM_new = DA_Equity − Sweep</Mono>. DRIP explicitly disabled to prevent fractional wash-sale tax lots.</p>
        </SubSection>

        <SubSection title="Position Sizing: Half-Kelly Criterion">
          <Formula>f* = p − q/b   (Full Kelly)</Formula>
          <Formula>Kelly_Applied = min(f* × 0.50, MAX_KELLY_FRACTION=0.20)</Formula>
          <p>Where: <Mono>p</Mono> = LLM conviction score, <Mono>q = 1 − p</Mono>, <Mono>b = take_profit_pct / |stop_loss_pct|</Mono>. If <Mono>Kelly_Applied ≤ 0</Mono> → slot defaults to SGOV (negative expected value).</p>
          <p><strong>Even-weight override:</strong> All non-SGOV slots with sufficient conviction receive equal weight <Mono>1/N</Mono>. Normalization pass ensures total ≤ 100% equity. Per-position hard cap: 15% of equity.</p>
        </SubSection>
      </Section>

      {/* Section 7 — Wash Sale */}
      <Section title="Regulatory Compliance: Wash Sale Similarity Matrix">
        <SimpleBox>
          <p>IRS rules say: if you sell a stock at a loss, you can't buy a "nearly identical" one within 30 days or you lose the tax deduction. The system automatically knows that SPY and VOO are basically the same thing — so if it lost money on SPY, it won't touch VOO for 30 days either.</p>
        </SimpleBox>

        <SubSection title="Similarity Groups">
          <Table
            headers={["Group", "Substantially Identical Assets"]}
            rows={[
              ["US Equity", "SPY, IVV, VOO"],
              ["Tech", "XLK, VGT, FTEC"],
              ["Long Bonds", "TLT, EDV, VGLT"],
              ["Gold", "GLD, IAU, SGOL"],
              ["Bitcoin", "IBIT, GBTC, BTCUSD, BTC/USD"],
              ["Ethereum", "ETHA, ETHUSD, ETH/USD"],
              ["Income", "JEPQ, JEPI, SCHD, DIVO"],
              ["(+ 7 more)", "Financials, Healthcare, Energy, Int. Bonds, Silver, Oil, Commodity"],
            ]}
          />
        </SubSection>

        <SubSection title="30-Day Enforcement Logic">
          <p>Every buy order calls <Mono>check_wash_sale(ticker)</Mono>:</p>
          <ol className="list-decimal ml-6 space-y-1 text-sm">
            <li>Compute cutoff: <Mono>today − 30 days</Mono></li>
            <li>Retrieve similarity set for proposed ticker</li>
            <li>Query <Mono>trades</Mono> for <Mono>Closed_Loss</Mono> in that set within window</li>
            <li>If found: skip order, redirect to SGOV, log compliance WARNING</li>
          </ol>
          <p>Runs on every buy including rebalances. Digital assets treated as securities proactively to future-proof against legislative changes to wash-sale rules.</p>
        </SubSection>
      </Section>

      {/* Section 8 — SPY/QQQ Trend */}
      <Section title="SPY/QQQ Trend: Kraken Crypto Bot">
        <SimpleBox>
          <p>A second, fully independent robot trades cryptocurrency on Kraken 24/7. Its strategy is simple: when a coin drops sharply below its normal price AND looks "oversold," buy it expecting a bounce. When it bounces back, sell it. It also checks the market's "order book" for suspicious activity before entering.</p>
          <AsciiDiagram>{`
  MEAN REVERSION STRATEGY
  ──────────────────────────────────────────────────────────────
   Normal BTC range: $60,000 - $65,000

   BTC drops to $55,000 ──▶ Z-Score < -1.5 AND RSI < 40
                             → BUY (expecting bounce) 📈

   BTC recovers to $62,000 ──▶ Z-Score crosses 0 OR RSI > 65
                             → SELL and take profit ✅

   Circuit breaker: BTC drops >3% in 30 min → pause 6 hours ⛔
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Statistical Entry and Exit Logic">
          <p><strong>Z-Score entry:</strong></p>
          <Formula>Z = (Close_latest − μ_window) / σ_window   (window = 20 bars)</Formula>
          <p>Enter when <Mono>Z &lt; −1.5</Mono> AND <Mono>RSI(14) &lt; 40</Mono>. Exit when <Mono>Z &gt; +0.5</Mono> OR <Mono>RSI &gt; 65</Mono>.</p>
          <p><strong>Profit floor gate:</strong> Position never closed unless profit &gt; <Mono>MIN_NET_PROFIT_PCT (0.6%)</Mono> — covers ~0.52% Kraken Pro fees. Prevents cycling in and out at break-even.</p>
          <p><strong>Position sizing:</strong> <Mono>position_usd = equity × 5% × (1 − cash_reserve)</Mono>. Max 20% per position. Max 3 simultaneous positions.</p>
        </SubSection>

        <SubSection title="Flash-Crash Circuit Breaker">
          <p>Rolling price deque over 30-minute window. If <Mono>current_price &lt; window_max × (1 − 0.03)</Mono>: pause all trading for 6 hours. Prevents aggressive buying during genuine market collapses (exchange hacks, regulatory announcements).</p>
        </SubSection>

        <SubSection title="Adaptive Parameter Self-Tuning (every 6 hours)">
          <p>Reviews last 20 closed trades and nudges parameters within ±40% of factory defaults:</p>
          <Table
            headers={["Parameter", "Adapts When", "Direction"]}
            rows={[
              ["ZSCORE_ENTRY", "Win rate < 40%", "Raise (be more selective)"],
              ["ZSCORE_ENTRY", "Win rate > 70%", "Lower (capture more trades)"],
              ["STOP_LOSS_PCT", "Stop-outs frequent/large", "Tighten"],
              ["TRAIL_PCT", "Trailing fires too early", "Widen"],
              ["MIN_NET_PROFIT_PCT", "Break-even exits common", "Raise"],
            ]}
          />
          <p>Hard floor: <Mono>MIN_NET_PROFIT_PCT</Mono> always exceeds the 0.52% fee floor. Persisted to <Mono>adaptive_params.json</Mono> and <Mono>kraken_adaptive_params</Mono> PostgreSQL table.</p>
        </SubSection>
      </Section>

      {/* Section 9 — Microstructure */}
      <Section title="Microstructure Alpha Signals (Stage 4 — Kraken)">
        <SimpleBox>
          <p>Before entering a trade, the bot peeks at the live "order book" — every pending buy and sell order on Kraken. Three numbers tell it whether it's safe to enter right now.</p>
          <AsciiDiagram>{`
  THE THREE MICROSTRUCTURE SENSORS
  ──────────────────────────────────────────────────────────────
   ORDER BOOK snapshot:
   Buyers: ████████░░ (80 units @ $62,000)
   Sellers: ████░░░░░░ (40 units @ $62,100)

   OFI = (80 − 40) / 120 = +0.33 → Buy pressure ✅
   (Long entry needs OFI ≥ +0.02)

   VAMP = depth-weighted avg of bid side + ask side prices
        = $62,045 → Buyers are paying up slightly

   VPIN = |buy_vol − sell_vol| / total_vol  across 50 buckets
        = 0.85 → DANGER: One side totally dominates ❌
        (Block if VPIN ≥ 0.80 — "smart money" is all on one side)
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Order-Flow Imbalance (OFI)">
          <p>Computed from live <Mono>fetch_order_book()</Mono> snapshot across top 5 bid/ask levels:</p>
          <Formula>OFI = (bid_depth − ask_depth) / (bid_depth + ask_depth)   ∈ [−1, +1]</Formula>
          <p>+1 = all depth on buy side; −1 = all depth on sell side. Long entry gate: <Mono>OFI ≥ +0.02</Mono>. Short entry gate: <Mono>OFI ≤ −0.02</Mono>.</p>
        </SubSection>

        <SubSection title="Volume-Adjusted Mid Price (VAMP)">
          <p>Depth-weighted average price using top 10 levels each side:</p>
          <Formula>VWAP_bid = Σ(price_i × size_i) / Σsize_i   for bids[:10]</Formula>
          <Formula>VAMP = (VWAP_bid + VWAP_ask) / 2.0   (absolute USD)</Formula>
          <p>Detects whether buyers or sellers are paying up relative to the mid-market price.</p>
        </SubSection>

        <SubSection title="Volume-Synchronised Probability of Informed Trading (VPIN)">
          <p><Mono>build_trade_buckets()</Mono> groups <Mono>fetch_trades()</Mono> output into fixed $5,000 USD buckets. Each bucket accumulates trades until total USD cost ≥ $5,000:</p>
          <Formula>VPIN = Σ|buy_vol_i − sell_vol_i| / Σtotal_vol_i   (last 50 buckets)</Formula>
          <p>Range: [0, 1]. 0 = perfectly balanced; 1 = entirely one-sided (toxic/informed flow).</p>
          <Table
            headers={["VPIN Level", "Meaning", "Action"]}
            rows={[
              ["< 0.65", "Normal flow", "Entry allowed (if OFI passes)"],
              ["0.65 – 0.70", "Elevated risk", "is_elevated_vpin() = True — logged"],
              ["> 0.70", "Suspicious flow", "Pre-check in main loop → skip entry"],
              ["≥ 0.80", "Toxic flow block", "entry_filter() hard blocks all entries"],
            ]}
          />
        </SubSection>

        <SubSection title="Entry Gate Chain">
          <p>Full gate sequence before any Kraken order is placed:</p>
          <ol className="list-decimal ml-6 space-y-1 text-sm">
            <li>Penalty throttle: bucket &gt; 80% of 15pt ceiling → skip cycle</li>
            <li>VPIN pre-check: VPIN &gt; 0.70 → skip entry (main loop level)</li>
            <li><Mono>entry_filter(side)</Mono>: VPIN ≥ 0.80 hard block → OFI directional gate</li>
            <li>RSI confirmation: RSI &lt; 40 for long entry</li>
            <li>Z-Score gate: Z &lt; −1.5 for long entry</li>
            <li>MAX_POSITIONS = 3: no new entry if 3 already open</li>
            <li>Cash reserve check: sufficient balance available</li>
          </ol>
        </SubSection>
      </Section>

      {/* Section 10 — Penalty Tracker */}
      <Section title="Kraken API Penalty Tracker &amp; Rate Protection">
        <SimpleBox>
          <p>Kraken penalizes you for pressing buttons too fast. You get 15 points before it cuts you off, and you earn back 1 point every second. The bot tracks this in real-time and automatically pauses at 80% capacity (12 points), giving the bucket time to refill.</p>
          <AsciiDiagram>{`
  LEAKY BUCKET PENALTY TRACKER
  ──────────────────────────────────────────────────────────────
   [■■■■░░░░░░░░░░░]  4/15 pts  → Safe ✅
   [■■■■■■■■■■■■░░░]  12/15 pts → THROTTLED ⚠ (80% limit)
   [■■■■■■■■■■■■■■■]  15/15 pts → Max — wait for drain ❌

   Drains: 1 point per second automatically
   Placing order: +1 point
   Cancelling order: +2 points
   State saved to JSON → survives bot restarts!
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Leaky-Bucket Mathematics">
          <p>Constants: <Mono>MAX_POINTS=15</Mono> · <Mono>PLACEMENT_COST=+1</Mono> · <Mono>CANCELLATION_COST=+2</Mono> · <Mono>DECAY_RATE=1pt/sec</Mono> · <Mono>THROTTLE_THRESHOLD=0.80 (12pt)</Mono></p>
          <p>Decay formula on every method call:</p>
          <Formula>points = max(0.0, points − elapsed_seconds × 1.0)</Formula>
          <p><Mono>is_throttled()</Mono> returns <Mono>True</Mono> when <Mono>points ≥ 12.0</Mono>. When throttled: main loop skips order placement and cancellations, enters read-only polling mode until bucket drains naturally.</p>
          <p><strong>Persistence:</strong> State written atomically via temp-file rename to <Mono>penalty_state.json</Mono> after every mutation. On load, elapsed wall-clock time since last save is applied as decay — penalty counter is accurate across restarts.</p>
        </SubSection>
      </Section>

      {/* Section 11 — Bot #5: Defensive Guardian Options */}
      <Section title="Bot #5: Defensive Guardian — Pure Quant Options Engine">
        <SimpleBox>
          <p>A 100% math-driven options bot with zero AI involvement. It watches four highly liquid stocks (SPY, QQQ, NVDA, TSLA) and waits for a rare moment when volatility is compressed AND prices are coiling in a tight range. When both conditions align, it buys a "straddle" — betting that a big move is coming, without needing to know the direction.</p>
          <AsciiDiagram>{`
  VOLATILITY SQUEEZE STRATEGY
  ──────────────────────────────────────────────────────────────
   NORMAL: Bollinger Bands wide, IV high
           → No trade. Wait.

   SQUEEZE DETECTED:
   ┌─────────────────────────────────────────┐
   │ IVR < 20    (implied vol at yearly low)  │
   │ BB Width at 6-month minimum (coiling)    │
   │ BOTH must be true simultaneously         │
   └─────────────────────────────────────────┘
           → BUY Long Straddle (ATM Call + ATM Put, 30-45 DTE)

   Capital fence: 5% of total account equity
   Execution: Once daily at 3:30 PM ET
   100% paper trading — real Alpaca market data
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Strategy: Volatility Squeeze Detection">
          <p><strong>Implied Volatility Rank (IVR):</strong></p>
          <Formula>IVR = (IV_current − IV_52w_low) / (IV_52w_high − IV_52w_low) × 100</Formula>
          <p>Entry gate: <Mono>IVR &lt; 20</Mono> — current implied volatility must be in the bottom 20% of its yearly range. This means options are "cheap" relative to recent history.</p>
          <p><strong>Bollinger Band Squeeze:</strong></p>
          <Formula>BB_Width = (Upper_Band − Lower_Band) / SMA_20</Formula>
          <p>Entry gate: Current <Mono>BB_Width</Mono> must be at or below its 126-day (6-month) minimum. This detects price compression — the coiling spring before a breakout.</p>
        </SubSection>

        <SubSection title="Trade Construction">
          <Table
            headers={["Parameter", "Value", "Rationale"]}
            rows={[
              ["Structure", "Long Straddle (ATM Call + ATM Put)", "Profits from any large move regardless of direction"],
              ["DTE Target", "30–45 days", "Enough time for the squeeze to resolve without excessive theta decay"],
              ["Watchlist", "SPY, QQQ, NVDA, TSLA", "Highest options liquidity — tight spreads, deep order books"],
              ["Capital Fence", "5% of total equity", "Hard isolation from the rest of the portfolio"],
              ["Sizing", "Half-Kelly Criterion", "Uses historical win/loss ratio after 10+ completed trades"],
              ["Execution", "3:30 PM ET daily scan", "APScheduler CronTrigger — captures end-of-day volatility compression"],
            ]}
          />
        </SubSection>

        <SubSection title="Paper Trading Simulation">
          <p>Starting capital: <Mono>$100,000</Mono> (isolated paper account). All trades simulated with real-time Alpaca options chain data. State persisted to <Mono>_options_state/</Mono> directory: positions, pending approvals, and SQLite trade journal.</p>
          <p>Position management includes unrealized P&amp;L tracking via live option snapshot prices and manual close capability from the dashboard.</p>
        </SubSection>
      </Section>

      {/* Section 12 — Bot #6: Forex Gump Forex */}
      <Section title="Bot #6: Forex Gump — Forex Swing-Trading Engine">
        <SimpleBox>
          <p>A Groq-assisted forex swing trader that holds positions for hours to days across five major currency pairs. It uses RSI and ATR indicators on 4-hour candles, combined with an AI "Compass" that reads macro news to determine directional bias. The vault system automatically sweeps 20% of profits above the high-water mark into a separate reserve.</p>
          <AsciiDiagram>{`
  FOREX SWING STRATEGY (4-hour cycle)
  ──────────────────────────────────────────────────────────────
   5 Major Pairs: EUR/USD  GBP/USD  USD/JPY  AUD/USD  USD/CHF

   ENTRY CONDITIONS:
   ┌──────────────────────────────────────────┐
   │ RSI(14) < 30  →  Oversold → BUY         │
   │ RSI(14) > 70  →  Overbought → SELL      │
   │ Groq Compass bias must AGREE             │
   │ Max 5 positions open simultaneously      │
   └──────────────────────────────────────────┘

   RISK MANAGEMENT:
   Stop Loss:  1.5 × ATR(14)
   Take Profit: 3.0 × ATR(14)    (2:1 reward-risk ratio)
   Max risk per trade: 1.5% of equity
   Max position size: 10% of equity

   VAULT: 20% of new profits above HWM → swept to reserve
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Currency Pair Configuration">
          <Table
            headers={["yfinance Symbol", "Label", "Quote Convention", "Pip Size"]}
            rows={[
              ["EURUSD=X", "EUR/USD", "Counter-USD (price = USD per EUR)", "0.0001"],
              ["GBPUSD=X", "GBP/USD", "Counter-USD", "0.0001"],
              ["JPY=X", "USD/JPY", "Base-USD (price = JPY per USD)", "0.01"],
              ["AUDUSD=X", "AUD/USD", "Counter-USD", "0.0001"],
              ["CHF=X", "USD/CHF", "Base-USD", "0.0001"],
            ]}
          />
          <p><strong>USD-base pair handling:</strong> For JPY=X and CHF=X, P&amp;L is calculated by dividing by the exit price to convert from the foreign currency to USD. This affects <Mono>get_positions()</Mono>, <Mono>get_paper_equity()</Mono>, and the live state writer.</p>
        </SubSection>

        <SubSection title="Groq Compass (AI Directional Bias)">
          <p>Before scanning for entries, the engine calls Groq Llama 3.3 70B with a macro-economic prompt. The AI returns a directional bias per pair: <Mono>bullish</Mono>, <Mono>bearish</Mono>, or <Mono>neutral</Mono>. Technical RSI signals must align with the AI bias for an entry to fire.</p>
          <p><strong>Throttle &amp; fallback:</strong> If Groq rate-limits or throws an exception, the engine falls back to the most recently cached bias. The system never blocks on a failed AI call.</p>
        </SubSection>

        <SubSection title="Risk &amp; Vault System">
          <Table
            headers={["Parameter", "Value"]}
            rows={[
              ["Max risk per trade", "1.5% of equity"],
              ["Max position size", "10% of equity"],
              ["Max open positions", "5 simultaneous"],
              ["Stop loss", "1.5 × ATR(14)"],
              ["Take profit", "3.0 × ATR(14)"],
              ["Vault sweep", "20% of equity above HWM"],
              ["HWM update rule", "Only after a successful vault sweep"],
            ]}
          />
          <p><strong>High-Water Mark design:</strong> The HWM is never updated on every cycle — it only advances inside <Mono>perform_vault_sweep()</Mono> after profits have been swept. This is the standard hedge fund HWM pattern that prevents phantom sweeps on volatile equity curves.</p>
        </SubSection>

        <SubSection title="Journal &amp; Persistence">
          <p>Trade journal in SQLite (<Mono>forex_journal.db</Mono>) with two tables: <Mono>trades</Mono> (ticket_id PK, pair, direction, entry/exit prices, P&amp;L in pips and USD) and <Mono>withdrawable_vault</Mono> (total swept, sweep count, last sweep timestamp). Paper positions persisted to <Mono>navigator_live_state.json</Mono>.</p>
        </SubSection>
      </Section>

      {/* Section 13 — Notification Alert System */}
      <Section title="Trade Alert Notification System">
        <SimpleBox>
          <p>When any bot closes a profitable trade, it gets queued into a notification system that batches alerts and sends them to your phone via Telegram (or Discord). You can control how often you get alerts — from every 5 minutes to once a day — directly from the dashboard.</p>
        </SimpleBox>

        <SubSection title="Architecture">
          <p>Every bot hooks into the <Mono>alert_manager</Mono> on profitable trade close. Alerts are queued to <Mono>data/alert_queue.json</Mono> and flushed on a configurable timer (default: 60 minutes). Both Telegram Bot API and Discord webhooks are supported simultaneously.</p>
          <Table
            headers={["Channel", "Setup", "Cost"]}
            rows={[
              ["Telegram", "@BotFather → create bot → set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID", "Free forever"],
              ["Discord", "Server Settings → Webhooks → copy URL → set DISCORD_WEBHOOK_URL", "Free forever"],
            ]}
          />
        </SubSection>

        <SubSection title="Configurable Parameters">
          <Table
            headers={["Setting", "Default", "Range"]}
            rows={[
              ["Alert interval", "60 minutes", "5 min – 24 hours"],
              ["Min P&L % filter", "0%", "0–100%"],
              ["Min P&L $ filter", "$0", "$0–$10,000"],
              ["Telegram toggle", "Enabled", "On/Off"],
              ["Discord toggle", "Enabled", "On/Off"],
            ]}
          />
          <p>All settings adjustable via <Mono>POST /trading-api/alerts/config</Mono> or the dashboard Alerts panel. Test connection: <Mono>POST /trading-api/alerts/test</Mono>.</p>
        </SubSection>
      </Section>

      {/* Section 14 — Groq / Hardware */}
      <Section title="AI Inference: Groq LPU &amp; Llama 3.3 70B">
        <SimpleBox>
          <p>The AI runs on Groq's special chip, which is purpose-built for AI reasoning. It's dramatically faster than traditional AI hardware. This matters because market windows are short — a slow AI means stale decisions.</p>
        </SimpleBox>

        <SubSection title="Groq LPU Architecture">
          <p>Traditional GPUs co-locate compute with High Bandwidth Memory (HBM) externally. Groq co-locates SRAM with compute on-die, providing ~24× memory bandwidth advantage (~80 TB/s vs. H100's 3.35 TB/s).</p>
          <Table
            headers={["Metric", "Groq LPU (Llama 3.3 70B)", "Traditional GPU"]}
            rows={[
              ["Inference speed", "~300–500 tokens/sec", "~60–150 tokens/sec"],
              ["Latency (TTFT)", "~0.2–0.3 seconds", "~0.5–1.0+ seconds"],
              ["Determinism", "Zero variance (clockwork)", "Variable (jitter)"],
            ]}
          />
          <p><strong>Zero variance</strong> is the critical property: if a task is scheduled for 280ms, it takes exactly 280ms every time. Traditional AI has "jitter" that can delay time-sensitive allocations.</p>
        </SubSection>

        <SubSection title="Llama 3.3 70B Performance">
          <Table
            headers={["Benchmark", "Accuracy", "Financial Utility"]}
            rows={[
              ["MMLU", "86.0%", "General macro reasoning"],
              ["MATH", "77.0%", "Quantitative validation"],
              ["HumanEval", "88.4%", "JSON structure formatting"],
              ["MGSM", "91.1%", "Multi-step problem solving"],
            ]}
          />
        </SubSection>
      </Section>

      {/* Section 12 — Dashboard */}
      <Section title="Dashboard Architecture: Dual-Agent Interface">
        <SimpleBox>
          <p>The dashboard is the cockpit. Two AI characters live side by side — one that trades, one that audits the trader. Emergency buttons always visible. Most important info shown first.</p>
          <AsciiDiagram>{`
  DASHBOARD LAYOUT (urgent → less urgent, top to bottom)
  ──────────────────────────────────────────────────────────────
  TIER 1 [URGENT]:  Kill switch 🟢/🔴 | Portfolio $ | Live positions
                    Economic calendar (upcoming risky events)
  TIER 2 [HEALTH]:  Risk metrics | Sentiment gauges | Correlations
  TIER 3 [AI]:      🧠 Degen Oracle (trades)  |  🛡 Inspector Rekt (audits)
  TIER 4 [TOOLS]:   Backtester | Trade journal | Vault | Mission Control
  ALWAYS VISIBLE:   Kill switch status bar
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="TanStack React Query Polling Cadence">
          <Table
            headers={["Data", "Interval", "Rationale"]}
            rows={[
              ["Kill switch / system health", "10s", "Near-real-time for crisis response"],
              ["Portfolio equity / positions", "30s", "Balance freshness vs. API load"],
              ["Growth vault / auditor report", "60s", "Lower volatility, less frequent"],
              ["Correlation matrix / sentiment", "120s", "Computed rarely, no high-freq need"],
              ["AI commentary", "25-min staleTime + 90s manual poll", "Respects Groq token budget"],
            ]}
          />
        </SubSection>

        <SubSection title="The Degen Oracle &amp; Inspector Rekt">
          <p><strong>The Degen Oracle</strong> (primary strategy agent): Pulsing neural network SVG. Displays LLM commentary. Click reveals allocation thesis, Kelly fractions, conviction rings, "What Worked / What Failed" split view.</p>
          <p><strong>Inspector Rekt</strong> (HITL auditor): Animated shield with scanning eye. Displays status badge (ALL_CLEAR / REVIEW_RECOMMENDED / ACTION_REQUIRED). Five audit categories:</p>
          <Table
            headers={["Category", "What It Checks"]}
            rows={[
              ["Regime Integrity", "LLM classification vs. independently computed SMA/EMA heuristics"],
              ["Compliance", "Wash sale exposure, 30-day loss window cross-reference"],
              ["RAG Bias Detection", "Implausible win rates, hindsight language in theses"],
              ["Phantom Drawdown", "Kill switch proximity (danger zone: within 0.5% of threshold)"],
              ["Ratchet Stop Integrity", "Stop prices below entry prices, within ATR distance, not stale"],
            ]}
          />
          <p>Each finding severity: <strong>INFO</strong> (green) · <strong>WARNING</strong> (amber) · <strong>ALERT</strong> (red) · <strong>HOLD</strong> (orange, compliance violations).</p>
        </SubSection>

        <SubSection title="Human-in-the-Loop Override Controls">
          <Table
            headers={["Action", "Type", "Effect"]}
            rows={[
              ["Run Analysis (Dry Run)", "Non-destructive", "Full pipeline preview without order placement"],
              ["Run Analysis (LIVE)", "Destructive", "Real order placement — explicit live-risk confirmation"],
              ["Run Post-Mortem", "Non-destructive", "Close positions, compute P&L, update journal"],
              ["Reset Kill Switch", "System", "Clear tripped state, re-init equity baseline"],
              ["Trip Kill Switch", "Emergency 🔴", "Immediate market-sell all + halt trading"],
            ]}
          />
        </SubSection>
      </Section>

      {/* Section 13 — Infrastructure */}
      <Section title="Operational Infrastructure">
        <SimpleBox>
          <p>The plumbing behind everything: a database that never loses a trade, a clock that knows every NYSE holiday, automatic retries when the internet hiccups, and a scheduler that runs four separate jobs at exactly the right time every day.</p>
        </SimpleBox>

        <SubSection title="Database Schema">
          <Table
            headers={["Table", "Purpose"]}
            rows={[
              ["trades", "Trade journal — ticker, conviction, P&L%, thesis, fill/intended price, slippage, status"],
              ["performance_snapshots", "Daily equity and P&L metrics (post-mortem output)"],
              ["vault_ledger", "Profit sweep state — HWM, vaulted USD, sweep count, DA adjustment"],
              ["ratchet_stops", "Active trailing stops — symbol, stop_price, fill_price, ATR, last_updated"],
              ["system_degradations", "Health events from degradation tracker"],
              ["kraken_adaptive_params", "Kraken bot's self-tuned parameter set (JSONB)"],
            ]}
          />
          <p>Primary: PostgreSQL (<Mono>psycopg2</Mono> ThreadedConnectionPool, min=1, max=8). Fallback: SQLite (identical function signatures, transparent switch via <Mono>is_pg_available()</Mono>).</p>
        </SubSection>

        <SubSection title="APScheduler Jobs (17 Registered)">
          <Table
            headers={["Job", "Schedule", "Action"]}
            rows={[
              ["Intraday analysis", "Every 15min, Mon–Fri 09:01–15:46 ET", "Data → guards → LLM → execute → journal"],
              ["Crypto-only", "Every 15min, 24/7 — only when NYSE closed", "BTC/USD, ETH/USD on Alpaca GTC"],
              ["Post-mortem", "16:10 ET weekdays", "Close positions, P&L, journal update, profit sweep"],
              ["Daily auditor", "16:30 ET weekdays", "Inspector Rekt full audit"],
              ["Gemini self-critic", "04:15 AM ET", "Pre-market audit, veto_conditions.json write"],
              ["Auto-heal monitor", "Every 2min, always active", "Self-healing for degraded components"],
              ["Learning snapshot", "Every 6 hours", "Export learning data for cross-restart seeding"],
              ["Equity heartbeat", "Every 1 hour", "Combined equity snapshot (Alpaca + Kraken + Forex)"],
              ["Defensive Guardian scan", "3:30 PM ET daily", "Options volatility squeeze scan → long straddle"],
              ["Forex Gump cycle", "Every 4 hours (immediate first)", "Forex pair scan → RSI + Groq → entry/exit"],
              ["Kraken WFO", "Sunday 02:00 AM UTC", "Walk-forward parameter optimisation for all 3 Kraken bots"],
              ["Kraken Backtester", "Sunday 02:30 AM UTC", "Full OHLCV price-based backtest on historical candles"],
              ["Regime health snapshot", "Every 30min", "Kraken health snapshots & regime-multiplier evaluation"],
              ["Fleet diagnostics (×3)", "Every 5min per bot", "Reads DB params, emits JSON diagnostics — never writes"],
              ["Adaptive params flush", "Every 15min", "Persist in-memory parameter adjustments to PostgreSQL"],
              ["Position heartbeat", "Every 3min", "Kraken portfolio equity & position-count update"],
              ["Circuit-breaker reset", "Every 1 hour", "Re-enable bots after timed circuit-breaker window"],
            ]}
          />
          <p>All jobs paused by default on startup. Operator must explicitly enable auto-trading. The system never starts trading autonomously on launch.</p>
        </SubSection>

        <SubSection title="API Resilience">
          <p>All Alpaca broker calls wrapped in full-jitter exponential backoff:</p>
          <Formula>delay = random.uniform(0, min(60s, 1s × 2^attempt))</Formula>
          <p>Max 5 retries before allowing failure. Global rate limiter: 300ms minimum between any two Alpaca calls. Market timing via Alpaca <Mono>/v2/clock</Mono> API (holiday-aware, irregular-session-aware).</p>
        </SubSection>
      </Section>

      {/* Section 15 — Test Framework */}
      <Section title="Testing Framework: 317 Automated Tests">
        <SimpleBox>
          <p>317 automated tests make sure every part of the system works correctly — like a full quality-control checklist before a car leaves the factory. All tests run offline (no network needed) and produce the exact same result every time.</p>
        </SimpleBox>

        <SubSection title="Test Coverage">
          <Table
            headers={["Module", "Tests", "Coverage"]}
            rows={[
              ["test_signal_guard", "~45", "3 guards, edge cases, integration"],
              ["test_groq_budget", "~30", "Token counting, rate limits, midnight resets"],
              ["test_llm_cache", "~30", "Cache hit/miss, TTL, fingerprinting"],
              ["test_shared_lib", "~45", "RiskProfile, ExitBracket, CB, VaR parametric"],
              ["test_data_integrity", "~50", "Snapshot validation, staleness, NaN, correlation"],
              ["test_gemini_auditor", "~50", "Response parsing, veto logic, fail-open, chunking"],
              ["test_microstructure", "~117", "OFI/VAMP/VPIN order-book + OHLCV fallback + ExecutorVaRGate"],
            ]}
          />
          <p><strong>Design principles:</strong> All external dependencies mocked (yfinance, Groq, Gemini, Alpaca, Kraken, PostgreSQL). Zero live network calls. Fully deterministic — no random seeds, no timing dependencies.</p>
        </SubSection>
      </Section>

      {/* Section 16 — Walk-Forward Optimizer */}
      <Section title="Stage 5: Walk-Forward Parameter Optimizer">
        <SimpleBox>
          <p>Every Sunday at 2:00 AM UTC, the system runs a rolling-window optimisation for all three Kraken bots. It picks the RSI thresholds and volatility filters that would have worked best over the past 30 days, then validates them on the following 10-day holdout period — so it can never "cheat" by looking at data it will trade on.</p>
          <AsciiDiagram>{`
  WALK-FORWARD OPTIMISER (Sunday 02:00 AM UTC — all 3 bots)
  ──────────────────────────────────────────────────────────
  Historical candles (last 40 days)
       │
       ▼
  ┌──────────────────────────────────┐
  │  IN-SAMPLE WINDOW (days 1–30)   │  ← grid search over params
  │  Test 100s of param combos      │  RSI lo/hi, vol filter, BB std
  │  → pick highest Sharpe ratio    │
  └──────────────────────────────────┘
       │   best params ↓
  ┌──────────────────────────────────┐
  │  OUT-OF-SAMPLE WINDOW (day 31–40)│  ← holdout validation
  │  Run best params on unseen data  │
  │  → accept only if profitable     │
  └──────────────────────────────────┘
       │   validated params ↓
  ┌──────────────────────────────────┐
  │  kraken_wfo_results (PostgreSQL) │  ← stored with bot_id + score
  │  kraken_adaptive_params          │  ← bot's live params updated
  └──────────────────────────────────┘
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Parameter Search Space">
          <Table
            headers={["Parameter", "Search Range", "Default"]}
            rows={[
              ["RSI lower threshold", "20 – 35 (step 5)", "25"],
              ["RSI upper threshold", "65 – 80 (step 5)", "72"],
              ["Volatility filter σ", "1.5 – 3.0 (step 0.5)", "2.0"],
              ["Bollinger Band std", "1.5 – 2.5 (step 0.5)", "2.0"],
              ["Trend confirmation window", "5 – 20 bars", "10"],
            ]}
          />
          <p>The grid exhausts all combinations inside the in-sample window (typical: 500–2,000 backtests per bot per run). The objective function is the Sharpe ratio of simulated closed trades — not raw P&amp;L, to avoid high-variance lucky streaks.</p>
        </SubSection>

        <SubSection title="Regime Multiplier">
          <p>The WFO result feeds a <strong>regime multiplier</strong> applied to every new position's size. The multiplier maps Sharpe tertiles to position scaling:</p>
          <Table
            headers={["Sharpe on Holdout", "Multiplier", "Meaning"]}
            rows={[
              ["≥ 1.0", "1.0×", "Full conviction — normal sizing"],
              ["0.3 – 1.0", "0.75×", "Moderate — slight reduction"],
              ["< 0.3", "0.5×", "Cautious — half-size until re-optimised"],
            ]}
          />
          <p>Current regime: all three Kraken bots at <Mono>0.5×</Mono> (Crypto-Risk-Off). Multiplier resets each Sunday after the WFO completes.</p>
        </SubSection>

        <SubSection title="Safety Design">
          <p><strong>Fail-open guarantee:</strong> If the WFO fails (API outage, insufficient candle history, DB error) the existing adaptive params are left untouched. Bots never receive an empty parameter set. <strong>Holdout gate:</strong> If validated P&amp;L is negative on the holdout window, the new params are discarded and the previous week's values are preserved — the optimiser cannot push a losing configuration live.</p>
        </SubSection>
      </Section>

      {/* Section 17 — OHLCV Backtester */}
      <Section title="Stage 6: True OHLCV Price-Based Backtester">
        <SimpleBox>
          <p>Every Sunday at 2:30 AM UTC (30 minutes after the WFO), the system runs a proper historical replay for each Kraken bot. Unlike a simple "did our signal fire?" check, this backtester processes real Open/High/Low/Close/Volume candles bar by bar — meaning entries, exits, and stop-losses all happen at realistic prices, not after-the-fact closes.</p>
          <AsciiDiagram>{`
  OHLCV BACKTESTER (Sunday 02:30 AM UTC — per bot, all pairs)
  ──────────────────────────────────────────────────────────────
  historical_prices table (7,200+ candles, 30-day lookback)
  BTC/USD, ETH/USD, SOL/USD · 15-min bars
       │
       ▼
  ┌──────────────────────────────────────────────────────────┐
  │  BAR-BY-BAR SIMULATION                                  │
  │  For each 15-min candle:                                │
  │    open  → check for entry signal (RSI + BB + trend)   │
  │    high  → check stop-loss / take-profit trigger        │
  │    low   → check stop-loss trigger (worst-case fill)    │
  │    close → fallback signal re-evaluation                │
  │  Realistic fills: open price + 0.1% slippage            │
  │  Fees: 0.26% maker/taker (Kraken Pro schedule)          │
  └──────────────────────────────────────────────────────────┘
       │
       ▼
  ┌──────────────────────────────────────────────────────────┐
  │  kraken_backtest_results (PostgreSQL)                   │
  │  bot_id · pair · win_rate · profit_factor · total_return│
  │  sharpe · max_drawdown · total_trades · run_at          │
  └──────────────────────────────────────────────────────────┘
          `}</AsciiDiagram>
        </SimpleBox>

        <SubSection title="Confirmed Backtest Results (Last Run)">
          <Table
            headers={["Bot", "Win Rate", "Profit Factor", "Net Return", "Trades"]}
            rows={[
              ["SPY/QQQ Trend", "43.3%", "0.98", "−2.1%", "~60"],
              ["Jerome", "42.0%", "1.15", "+79.0%", "~71"],
              ["Sector Rotation", "44.3%", "1.02", "+4.3%", "~68"],
            ]}
          />
          <p>Results persist in PostgreSQL and are displayed live on the Analytics tab of the dashboard. The backtester ingested 7,200 OHLCV candles (2,400 per pair × 3 pairs) and ran bar-by-bar across the 30-day lookback window. Jerome's outsized net return reflects a concentrated winning streak on ETH/USD during high-volatility periods.</p>
        </SubSection>

        <SubSection title="Why OHLCV Matters">
          <Table
            headers={["Approach", "Stop-Loss Accuracy", "Entry Fill Price", "Overfitting Risk"]}
            rows={[
              ["Close-only backtest (old)", "Triggers only at bar close — too late", "Closing price (unrealistic)", "High — signals cherry-picked at hindsight"],
              ["OHLCV bar-by-bar (Stage 6)", "Uses bar Low to detect intra-bar stop hit", "Opening price + slippage (realistic)", "Low — in-sample/holdout split enforced"],
            ]}
          />
          <p>The critical difference: a stop at $40,000 BTC may be triggered by the bar's Low ($39,800) even if Close is $40,500. Close-only backtests miss this and systematically overstate win rates.</p>
        </SubSection>

        <SubSection title="Data Ingestion">
          <p>The OHLCV ingestor (<Mono>analysis/ingest_kraken_ohlcv.py</Mono>) fetches 720 candles per pair (15-min intervals, 30-day window) from the Kraken REST API, deduplicates by timestamp, and inserts into the <Mono>historical_prices</Mono> table. A <Mono>needs_ingest()</Mono> guard skips re-ingestion if ≥ 100 valid candles already exist per pair, preventing redundant API calls on scheduler restarts.</p>
        </SubSection>
      </Section>

      {/* Appendix */}
      <Section title="Appendix: Complete Risk Hierarchy">
        <p>The ordered sequence of gates that fire before any order is placed on the Alpaca platform:</p>
        <Table
          headers={["#", "Gate", "Action on Failure"]}
          rows={[
            ["1", "Market hours / blackout period check", "Skip cycle"],
            ["2", "Data circuit breaker (4 guards)", "Skip cycle, hold cached regime"],
            ["3", "Signal guard: temporal quarantine (HARD)", "Skip cycle, return cached regime"],
            ["4", "Signal guard: consensus + divergence (SOFT)", "Filter headlines / adjust sentiment"],
            ["5", "Kill switch: daily drawdown ≥ 5%", "Liquidate all positions, halt day"],
            ["6", "VaR circuit breaker: var_usd > limit_usd", "Block all new entries for cycle"],
            ["7", "Gemini veto enforcer", "Skip specific ticker, redirect to SGOV"],
            ["8", "Wash sale compliance (30-day)", "Skip order, redirect to SGOV"],
            ["9", "Zero-Kelly filter (Kelly ≤ 0)", "Force SGOV allocation"],
            ["10", "Overheated guard (Z>2 or RSI>75)", "Cut 50%, reroute to SGOV"],
            ["11", "Leveraged risk cap (>20% total)", "Block leveraged entry"],
            ["12", "Per-position cap (>15% equity)", "Cap notional, leave remainder in cash"],
            ["13", "SPY EMA-20 anchor (Bull-only)", "Block Bull/leveraged entry if SPY < EMA-20"],
            ["14", "Margin block (cash ≤ 0)", "Block order entirely"],
          ]}
        />

        <div className="mt-4 p-4 bg-indigo-950/40 border border-indigo-500/20 rounded-lg text-xs text-slate-400">
          <span className="text-indigo-300 font-semibold">System Status: </span>
          Hybrid Agentic Architecture Stages 0–6 complete. 317 tests passing. Eight bots operational across equities, crypto, options, and forex. Gemini self-critic auditing daily at 04:15 AM ET. Microstructure alpha active on Kraken order-book primary path. VaR circuit breaker live in executor. Walk-Forward Optimizer runs every Sunday 02:00 AM UTC across all 3 Kraken bots. OHLCV price-based backtester confirmed working — 7,200 candles ingested, results persisted (SPY/QQQ Trend WR=43.3%, Jerome PF=1.15/+79% net, Sector Rotation WR=44.3%). Telegram/Discord alert system active with configurable frequency. $800k total paper capital deployed across the fleet.
        </div>
      </Section>

      <div className="h-12" />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="text-xl font-bold text-white mb-4 pb-2 border-b border-indigo-500/30">{title}</h2>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h3 className="text-base font-semibold text-indigo-300 mb-3">{title}</h3>
      <div className="space-y-3 text-sm">{children}</div>
    </div>
  );
}

function SimpleBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-6 p-4 bg-emerald-950/40 border border-emerald-500/30 rounded-lg">
      <div className="flex items-center gap-2 mb-3">
        <span className="px-2 py-0.5 bg-emerald-500/20 border border-emerald-500/40 rounded-full text-xs font-semibold text-emerald-300 uppercase tracking-wide">
          Simple Explanation
        </span>
      </div>
      <div className="space-y-2 text-sm text-slate-300">{children}</div>
    </div>
  );
}

function AsciiDiagram({ children }: { children: string }) {
  return (
    <pre className="mt-3 p-3 bg-slate-900/80 border border-slate-700/50 rounded text-xs text-emerald-300 font-mono whitespace-pre overflow-x-auto leading-relaxed">
      {children}
    </pre>
  );
}

function Mono({ children }: { children: React.ReactNode }) {
  return <code className="px-1.5 py-0.5 bg-slate-800 border border-white/10 rounded text-indigo-300 text-xs font-mono">{children}</code>;
}

function Formula({ children }: { children: React.ReactNode }) {
  return (
    <div className="my-3 px-4 py-3 bg-slate-800/60 border border-indigo-500/20 rounded-lg font-mono text-sm text-indigo-200 text-center">
      {children}
    </div>
  );
}

function Table({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="my-4 overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="text-left px-3 py-2 bg-slate-800/80 border border-white/10 text-indigo-300 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-2 border border-white/10 text-slate-300">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
