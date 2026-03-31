# Workspace

## Overview

pnpm workspace monorepo with three main products:
1. **AI Quantitative Trading Platform** (Python/FastAPI) — autonomous trading system
2. **Trading Dashboard** (React/Vite) — dark terminal-themed private monitoring UI at `/`
3. **AlgoEdge SaaS Platform** (React/Vite) — public-facing SaaS platform at `/saas/` (all 5 stages complete)

**`Technical_Logic_Blueprint.md`** — Full system architecture whitepaper. Updated March 2026 to cover all Hybrid Agentic Architecture upgrades through Stage 4. Dual-audience format: Simple Explanation (teen-friendly) + Advanced Technical (audit-grade) for every section. 29-shape canvas diagram also maintained in sync.

## Trading Platform (Python/FastAPI)

Located in `trading-platform/`. A private, automated AI-driven quantitative trading system.

### Stack
- **Runtime**: Python 3.11
- **Framework**: FastAPI + Uvicorn
- **Brokerage**: Alpaca API (Paper Trading)
- **Data Sources**: FRED API, Alpaca Market Data, NewsAPI
- **LLM**: Groq (Llama 3.3 70B Versatile)
- **Database**: PostgreSQL (primary) with SQLite fallback; trade journal, vault ledger, ratchet stops, performance snapshots
- **Validation**: Pydantic v2
- **Scheduling**: APScheduler (5 jobs: 15-min intraday full-market cycle, 15-min 24/7 crypto-only cycle, evening post-mortem, daily auditor at 4:30 PM ET, Gemini self-critic at 4:15 AM ET)

### Architecture
- `main.py` — FastAPI app with `APIRouter(prefix=API_PREFIX)` where `API_PREFIX` defaults to env var (set to `/trading-api` in artifact config)
- `config/settings.py` — Pydantic BaseSettings
- `data/` — FRED, Alpaca Market Data, NewsAPI, yfinance, sentiment (Fear & Greed), on-chain BTC data, economic calendar
- `analysis/` — Trade journal, post-mortem, Groq LLM, RAG feedback, analyzer, **Inspector Rekt** (HITL auditor at 4:30 PM ET), **gemini_auditor** (Gemini self-critic pre-market auditor at 4:15 AM ET — writes `logs/veto_conditions.json`), **gemini_context_sanitizer** (HTML strip, news dedup, float rounding, 8-hour chunking for token budget management), attribution breakdown, backtester, **learning_journal** (persistent LLM insight ledger), **learning_snapshot** (cross-deploy knowledge persistence), **input_sanitizer** (strips news descriptions + deduplicates headlines before LLM injection), **hardcoded_exits** (per-asset-class SL/TP table applied post-parse), **llm_response_cache** (MD5-keyed 90-min response cache, prevents redundant Groq calls when signals unchanged), **rule_engine** (Phase 4 permanent rules: scans execution_post_mortems for 3+ identical failure patterns, promotes to hardcoded_rules table, injects as non-negotiable RULE constraints into every LLM system prompt)
- `notifications/` — Discord webhook alerts (trades, kills, sweeps, audits, blackouts)
- `portfolio/` — Kelly Criterion sizing, allocation logic
- `execution/` — Alpaca broker wrapper (v2.1: `place_short_order`, `buy_to_cover`, `place_short_stop_order`, `check_shortable`, `initial_margin`), kill switch (5% drawdown guard), order executor with slippage tracking, **short_scanner.py** (Bear Engine algo short scanner: Z-score >2.0 + RSI >68 signal, 35% max exposure, 15% per-position cap, ATR ratchet, mean-reversion exit at Z<0.3, 5% trailing stop)
- `core/` — Scheduler (APScheduler), pipeline orchestration, market clock, `degradation_tracker.py` (PostgreSQL event log with per-component escalating de-dup: kraken_api/platform_core→1800s base TTL, http→300s, others→900s; each repeat doubles the quiet window up to 7200s max)

### v4.0 — Regime-Switching Architecture
- **Fixed 8-asset universe** — SPY, QQQ (equity), TLT, GLD (safe_haven), BTC/USD, ETH/USD, ATOM/USD (crypto_spot), SGOV (cash)
- **3-step regime model** — Python calculates 3-month MA (63 bars) + 6-month MA (126 bars) → LLM classifies Bull/Bear/Sideways → dynamic allocation
- **Bull Regime** — 100% capital in top 1–3 equity/crypto assets with positive momentum (both MAs), evenly weighted
- **Bear Regime** — 100% capital in TLT/GLD with positive momentum; if both negative → 100% SGOV
- **Sideways Regime** — Mean-reversion plays (max 2, conviction ≥ 0.80) or 100% SGOV
- **Variable slot count** — 1–6 slots (replaces rigid 10-slot model); Python enforces even-weight sizing
- **Never force a trade** — If no high-conviction setup aligns with momentum → 100% SGOV; SGOV is a valid complete output

### Key Features
- **Dual-mode 24/7 trading** — Full regime-switching (market hours), crypto-only/BTC+ETH+ATOM (off-hours)
- **15-minute intraday cycles** — ~26 analysis+execution cycles per market day for maximum learning
- **24/7 crypto cycles** — BTC/USD, ETH/USD, ATOM/USD via Alpaca native crypto (GTC orders, $25 min notional)
- **Smart data caching** — FRED macro data (1hr TTL, skipped in crypto-only), NewsAPI (1hr TTL, halved from 30min to reduce Groq token budget pressure), Alpaca market data (always fresh, 6-month lookback)
- **Groq budget guardrails** — `analysis/groq_budget.py` singleton tracks daily token usage (100K TPD limit), enforces 90-min minimum interval between regime LLM calls (returns cached regime if throttled), caps auto-commentary at 4/day per endpoint; `force=True` bypasses call-count cap but NOT zero-budget (budget check runs before force bypass), all counters reset at midnight UTC; commentary endpoints return HTTP 200 graceful fallback (not 429) when budget is exhausted; on Groq API failure the commentary cache `ts` is advanced by (TTL − 300s) so the next retry waits 5 min instead of retrying every request
- **LLM response cache** — `analysis/llm_response_cache.py` MD5-keyed cache (90-min TTL) keyed on `call_type|regime_band|top_tickers_sorted|sentiment_band`; `get_or_call()` is the single integration point in both retry functions; budget counters skip on cache hits; `GET /admin/token-usage` + `POST /admin/llm-cache/invalidate` endpoints
- **Pre-LLM signal guardrails** — `analysis/signal_guard.py` runs three guards before every Groq call (Step 3.5): (1) **TemporalQuarantine** (hard, skips LLM): blocks Fri 14:00→Mon 09:30 ET and ±30min around economic calendar blackout events — returns cached regime if available; (2) **MultiSourceConsensus** (soft): removes single-source headlines with no cross-category topic corroboration, reducing noisy input; (3) **PriceToSentimentDivergence** (soft): downgrades market sentiment one band (Greed→Neutral, Extreme Greed→Greed) when SPY 5-day avg volume < 20-day avg volume. Guard results exposed in `GET /status` under `signal_guard` key. All guards fail-open (non-fatal exceptions fall through to raw data)
- **Shared risk library** — `shared/` at repo root is imported by both bots via `sys.path.insert(0, REPO_ROOT)`: `RiskProfile` (60/40 ring-fence, reserve buffer, daily loss limit, `to_dict()`), `ExitBracket` (stop/TP/trail-activation levels, ATR-based or fixed-%, `compute_exit_levels()` convenience fn), `CircuitBreaker` (stateless `check_circuit_breaker()` fn + stateful class with `record()`/`check_and_trip()`/`reset()`), **`VaRCircuitBreaker`** (parametric 99% 1-period VaR CB: `record_return()` / `check_and_trip()` / `reset()` / `to_dict()`; trips when estimated tail loss > configurable limit, 6-hr pause). 59 unit tests in `trading-platform/tests/test_shared_lib.py`.
- **Variable Kelly slots** — 1–6 slots, even-weight Python override (not LLM arithmetic), normalised to ≤ 100% equity
- **SQLite RAG trade journal** — losses/wins/slippage injected into LLM system prompt (unified for ETF and crypto trades)
- **Strict LLM state awareness** — analyzer aborts with RuntimeError if account state fetch fails
- **Slippage tracking** — `intended_price` + `actual_fill_price` columns; post-mortem uses actual fill price as entry
- **Auto-trading toggle** — scheduler jobs start PAUSED; toggle resumes/pauses all 3 jobs; state tracked in module var
- **Pipeline execution lock** — asyncio.Lock prevents overlapping cycles
- **Kill switch** — 5% daily drawdown auto-liquidation, date-based reset (first market-open cycle of each day)
- **Trading mode indicator** — Dashboard shows FULL MARKET / CRYPTO ONLY / IDLE mode in status bar

### API Endpoints (all prefixed with API_PREFIX)
- `GET /health` — System health
- `GET /status` — Full system status with scheduler info + blackout state
- `GET /portfolio` — Alpaca account summary
- `GET /positions/live` — Live open positions from Alpaca (includes composite health_score per position)
- `GET /allocation/latest` — Most recent LLM allocation
- `GET /performance` — Equity curve data
- `GET /performance/summary` — P&L summary stats
- `GET /performance/attribution` — P&L attribution by regime, asset class, conviction, timing quality
- `GET /performance/risk-metrics` — Sharpe, Sortino, Max Drawdown, Calmar, Volatility, Annualised Return
- `GET /correlation` — Pearson correlation matrix across held positions (30-day closes)
- `GET /calendar` — Economic calendar with upcoming events + blackout window state
- `GET /sentiment` — Crypto + Market Fear & Greed indices
- `GET /onchain` — Bitcoin on-chain data (hashrate, mempool, fees, supply)
- `POST /backtest` — Momentum strategy backtester simulation (lookback_days param)
- `GET /journal` — All trade journal entries
- `GET /journal/wins` — Top N winning trades
- `GET /journal/losses` — Top N losing trades
- `GET /ai/commentary` — Latest LLM analysis commentary
- `GET /auditor/report` — Latest HITL audit report (JSON)
- `POST /auditor/run` — Trigger manual audit cycle
- `POST /rebalance` — Force close sellable positions + run fresh pipeline
- `POST /run` — Trigger analysis cycle
- `POST /run/postmortem` — Trigger post-mortem
- `POST /kill` — Trip kill switch
- `POST /kill/reset` — Reset kill switch
- `GET /auto-trading` — Get auto-trading state
- `POST /auto-trading` — Toggle auto-trading
- `GET /system/health-architecture` — Real-time health metrics for all subsystems (platform core, Alpaca, Kraken, data pipeline, equity manager)
- `GET /kraken/auto-trading` — Kraken bot pause state
- `POST /kraken/auto-trading` — Pause/resume Kraken bot (writes control.json)
- `GET /admin/token-usage` — Per-call-type Groq token breakdown (regime/crypto/commentary/unknown) + LLM cache hit/miss stats
- `POST /admin/llm-cache/invalidate` — Clear the LLM response cache (forces fresh Groq call next cycle)
- `GET /admin/risk-profile` — Live Alpaca risk profile state: ring-fenced % (60%), deployed %, reserve buffer USD, max single-position USD, is_breached flag; powered by `shared/risk_profile.py`

## Dashboard (React/Vite)

Located in `artifacts/dashboard/`. Dark terminal-themed monitoring UI.

### Stack
- **Framework**: React 19 + Vite
- **Styling**: Tailwind CSS v4
- **State**: TanStack React Query
- **Charts**: Recharts

### Mobile Responsive Design
- **Breakpoint**: `useIsMobile()` hook at 768px (aligned with Tailwind `md:` breakpoint)
- **Header**: "Quant Terminal" → "QT" on mobile; emergency buttons are icon-only; Market/Kill Switch shown as compact colored dots
- **Portfolio Metrics**: Total Equity card spans full width on mobile; 2-col grid vs 5-col desktop
- **Positions**: `MobilePositionCard` component renders stacked cards on mobile; full 12-column table on desktop
- **AI Sections**: Brain/Shield SVGs scale down (w-24 h-24); CRT overlay and EquityEcho disabled on mobile for performance
- **Modals**: ConfirmModal slides up as bottom sheet on mobile instead of centered dialog
- **Touch Targets**: All interactive buttons have min-h-[44px] on mobile

### Key Components
- `TradeWorkflowBar.tsx` — Alpaca auto-trading toggle, Kraken bot toggle, Whitepaper, System Health Architecture button
- `Dashboard.tsx` — Main dashboard page with all sections; AI brain = "The Degen Oracle", auditor = "Inspector Rekt". Mobile-responsive with a **sticky bottom tab bar** (`md:hidden`) with 4 tabs: Overview (portfolio metrics + live positions + **CombinedTradeHistorySection**), Kraken (bot + crypto performance), Alpaca (Oracle + Auditor + stock performance), More (risk, calendar, tools, system health). Tab state managed via `useState<Tab>('overview')`; sections toggled via `mobileHide(tabs)` CSS helper. On desktop all sections are always rendered in the full grid layout.
  - **CombinedTradeHistorySection** (new, Overview tab): merges the last 50 Alpaca trades (`useRecentTrades(50)`) with the last 50 Kraken trades (`useKrakenPerformance().recent_trades`), sorts by date descending, shows top 40. Columns: Bot badge (KRK/ALP), Asset, P&L %, P&L $, Date. Header shows combined W/L/Win-rate/Total P&L. Both data sources from PostgreSQL.
- `CorrelationMatrix.tsx` — Pearson correlation heatmap with high-correlation warnings
- `SentimentGauges.tsx` — Dual SVG ring gauges for Crypto + Market Fear & Greed
- `EconomicCalendarBanner.tsx` — Blackout banner (red alert) + upcoming events list
- `RiskMetricsPanel.tsx` — Sharpe/Sortino/MaxDD/Calmar/Volatility/Return cards
- `AttributionPanel.tsx` — P&L breakdown by regime, asset class, conviction with win-rate bars
- `BacktesterPanel.tsx` — Momentum strategy backtester with equity curve chart and trade log
- `ControlPanel.tsx` — Mission Control buttons (kill switch, analysis, post-mortem)
- `SystemHealthModal.tsx` — Live architecture diagram with SVG nodes, animated glowing wires, health levels (green/yellow/red), and test control panel with scenario presets (simulate 404, 500, rate limits, stale data, allocation breach, total failure)
- `SystemHealthCard` (in Dashboard.tsx) — Inline bottom-of-page health panel with: 7-day daily event sparkline, 24h event count vs &lt;10/day target, de-duplicated active alerts with **plain-English explanations**, resolution type badge (Clears on its own / Needs attention), and trading impact badge (Trading not affected / May affect next trade / Trading may be paused)

### API Communication
- **Dev**: Replit router sends `/trading-api/*` to port 8000 (artifact multi-service routing)
- **Production**: Same path-based routing via artifact.toml services config
- `API_PREFIX=/trading-api` set in artifact.toml `[services.env]` for both dev and prod

## Artifact Configuration

The dashboard artifact (`artifacts/dashboard/.replit-artifact/artifact.toml`) defines two services:
1. **web** — Vite dev server (port 23183), serves the React dashboard at `/`
2. **trading-api** — Python uvicorn (port 8000), serves the FastAPI API at `/trading-api`

Production config:
- Web: static build from `artifacts/dashboard/dist/public` with SPA rewrite `/* → /index.html`
- API: uvicorn with 1 worker, `API_PREFIX=/trading-api`, health check at `/trading-api/health`

**IMPORTANT**: Deployment target must be `vm` (Reserved VM) for 24/7 scheduler operation. The scheduler, kill switch state, and SQLite DB require a persistent process.

## Dashboard Gamification (Task #20)

Both bot agent cards in the dashboard now include three gamification layers:

### Utilities (module-level in Dashboard.tsx)
- `computeStreak(trades)` — walks newest-first trade array, returns `{count, direction}` ("win"/"loss"/"none")
- `computeXP(wins, total)` — `wins×100 + total×10`
- `KRAKEN_RANKS` — pirate ladder: Deckhand(0) → Able Seaman(500) → First Mate(1000) → Quartermaster(2500) → Captain(5000) → Davy Jones Himself(10000+)
- `ORACLE_RANKS` — degen ladder: Paper Hands(0) → Bag Holder(500) → Ape Mode(1000) → Diamond Hands(2500) → Galaxy Brain(5000) → The Degen Oracle(10000+)

### Components
- `StreakChip` — streak badge with amber glow at 3W+, red pulse at 5W+
- `XPRankBar` — compact progress bar showing current rank → next rank threshold
- `KillBoardPanel` — collapsible "☠️ N Kills" / "🎯 N Kills" chip; expands to show profitable trades with LEVIATHAN KILL/APE MODE badges

### Data Sources
- **Kraken streak**: `useKrakenStatus().data.recent_trades` (reversed newest-first)
- **Kraken XP**: `useKrakenPerformance().data.{win_count, total_trades}`
- **Kraken Kill Board**: `krakenStatus.recent_trades` (filter pnl_pct > 0), LEVIATHAN KILL badge at ≥3%
- **Alpaca streak**: new `useRecentTrades(20)` hook → `/trading-api/journal/recent?n=20`
- **Alpaca XP**: `useJournal().data.summary.{wins, total}`
- **Alpaca Kill Board**: `useRagWinsExtended(10)` → `/journal/wins?n=10`, APE MODE badge at ≥5%

### New Backend
- `trading-platform/analysis/trade_journal.py`: `get_recent_trades_combined(limit)` — returns last N wins+losses combined, ordered by date DESC
- `trading-platform/main.py`: `GET /trading-api/journal/recent?n=20` endpoint

## RAG Memory Architecture (4-Phase — COMPLETE)

The trading system has a 4-phase Retrieval-Augmented Generation memory layer that makes the LLM smarter with every trade.

### Phase 1: Database Schema Expansion — DONE
- Extended `trades` table with RAG columns: `regime_at_entry`, `time_in_trade_hours`, `exit_reason`, `realized_pnl`, `slippage_pct`
- Created `execution_post_mortems` table for deterministic Python-generated lesson text
- Added DB functions: `close_trade()`, `log_post_mortem()`, `get_post_mortems()`, `get_position_entry_times()`

### Phase 2: Deterministic Post-Mortem Logging — DONE
- `analysis/post_mortem_lessons.py`: 7-branch lesson rule matrix (ratchet_stop, time_exit, algo_cover, allocation_sell, manual, bear_hedge, unknown × win/loss × short-hold) with structured prefixes: `[EXECUTION FAILURE]`, `[THESIS FAILURE]`, `[THESIS WIN]`, `[EXECUTION WIN]`, `[MANUAL EXIT]`, `[AUDIT NOTE]`
- Three deterministic hooks write to `execution_post_mortems` on every trade close:
  1. Evening reconciliation (`post_mortem.py`) — detects ratchet stops via Alpaca order type `"stop"`, calls `close_trade()` + `log_post_mortem()`
  2. 5-day 3× ETF exits (`hardcoded_exits.py`) — captures `entry_ts`, generates `time_exit` lesson
  3. Algo short covers (`short_scanner.py`) — captures `entry_ts`, generates `algo_cover` lesson

### Phase 3: Context-Aware Prompt Injection — DONE
- `trade_journal.py`: `get_contextual_losses()` + `get_contextual_wins()` query `trades` WHERE `regime_at_entry EXACTLY MATCHES` the current regime; asset-class priority sort (bear_hedge first in Bear, equity first in Bull, safe_haven first in Sideways); falls back to FIFO with explicit cross-regime disclaimer
- `feedback_injection.py`: Removed FIFO `LOSS_FEEDBACK_TEMPLATE` / `WIN_FEEDBACK_TEMPLATE`; replaced with `[RELEVANT HISTORICAL CONTEXT]` block that attaches lesson text from `execution_post_mortems` for each matched trade; `_REGIME_PRIORITY_CLASS` auto-infers asset-class priority from regime
- `analyzer.py`: Loads cached regime from `market_regime.json` and passes as `current_regime=` to prompt builder

### Phase 4: Permanent Hardcoded Rules — DONE
- `db/postgres.py`: `hardcoded_rules` table (ticker, regime, exit_reason, failure_count, rule_text, active); `upsert_hardcoded_rule()` + `get_hardcoded_rules()`
- `analysis/rule_engine.py`: `rollup_permanent_rules(threshold=3)` — SQL GROUP BY (ticker, regime, exit_reason) WHERE pnl_pct < 0 HAVING COUNT >= 3; generates `RULE [EXECUTION FAILURE/THESIS FAILURE/etc]: ...` text; upserts to `hardcoded_rules` (ON CONFLICT DO UPDATE); `get_active_rules()` + `build_permanent_rules_block()` for prompt injection
- `analysis/post_mortem.py`: Phase 4 rollup runs automatically after every evening post-mortem cycle (non-fatal hook)
- `analysis/feedback_injection.py`: `build_permanent_rules_block()` injected immediately after base system prompt — rules are labelled NON-NEGOTIABLE and treated with equal weight to the 10% position-sizing hard cap; regime-matched rules shown first, cross-regime rules appended

## Kraken Bot ("Davy Jones' Portfolio")

Located in `kraken-bot/`. Standalone 24/7 paper-trading crypto bot scanning 50 pairs on 1h candles.

### Stack
- **Runtime**: Python 3.11
- **Exchange**: Kraken (via ccxt) — paper mode with simulated $100K balance
- **Database**: PostgreSQL (`kraken_heartbeat`, `kraken_portfolio`, `kraken_trades`)
- **Microstructure**: OFI + VAMP + VPIN entry filter (order-book primary)

### Key Files
- `config.py` — All tunable parameters (single source of truth)
- `logic.py` — Pure math (RSI, Z-score, ATR, position sizing, `VPINDecayTracker`)
- `main.py` — Trading loop, cycle logic, regime sync
- `db.py` — PostgreSQL schema and CRUD
- `paper_engine.py` — Paper trading simulator

### Dynamic VPIN Scaling (Stages 3 & 3.5)
- **Dynamic VPIN cap**: When 24h volume > 1.5× trailing 30-candle mean, VPIN entry threshold relaxes from 0.65 → 0.82
- **VPIN Decay**: `VPINDecayTracker` in `logic.py` — after 4 consecutive high-VPIN cycles with stabilizing ATR (current ≤ previous), decays effective VPIN by 10%/cycle, floor at 30%
- **Contrarian Scout**: RSI < 25 in Bear/RISK-OFF regime allows 3% equity Tier 1 entry despite VPIN block
- **Deep Oversold Bypass**: RSI < 20 bypasses VPIN entirely for 1% equity micro-lot
- **Volume history**: Module-level `dict[str, deque(maxlen=30)]` in `main.py` tracks per-symbol candle volumes

### Risk Management
- 20% cash reserve, 10% max per position (7.5% in Bear), 10 max positions (5 in Bear)
- 1.5% hard stop, 5% trailing profit, 0.8% min net profit gate
- ATR-based position sizing (ATR_PERIOD=14, ATR_MULTIPLIER=1.5)
- Circuit breaker: >10% drop in 5min → 2hr pause
- RiskProfile reserve ceiling enforced before any entry logic

## Required Secrets
- `FRED_API_KEY` — fred.stlouisfed.org
- `NEWS_API_KEY` — newsapi.org
- `ALPACA_API_KEY` — Alpaca paper trading key ID
- `ALPACA_SECRET_KEY` — Alpaca paper trading secret
- `GROQ_API_KEY` — Groq free API (llama-3.3-70b-versatile)

## Monorepo Structure

```text
├── shared/                    # Shared risk infrastructure (both bots import this)
│   ├── __init__.py            # Re-exports RiskProfile, ExitBracket, CircuitBreaker, VaRCircuitBreaker
│   ├── risk_profile.py        # Portfolio risk envelope (60/40 ring-fence, reserves, caps)
│   ├── exit_bracket.py        # Exit-level calculator (stop/TP/trail, ATR-based or fixed %)
│   ├── circuit_breaker.py     # Flash-crash detector (stateless fn + stateful class)
│   └── var_circuit_breaker.py # Parametric VaR circuit breaker (99% 1-period, configurable limit + pause)
├── trading-platform/          # Python FastAPI trading API
│   ├── main.py                # FastAPI app + router
│   ├── config/                # Settings
│   ├── data/                  # FRED, Alpaca, News clients
│   ├── analysis/              # Journal, post-mortem, Groq, RAG, analyzer
│   ├── portfolio/             # Kelly criterion, allocator
│   ├── execution/             # Broker, kill switch, executor
│   └── core/                  # Scheduler, pipeline, market clock
├── artifacts/
│   ├── dashboard/             # React dashboard (Vite)
│   │   ├── src/
│   │   │   ├── components/    # UI components
│   │   │   ├── hooks/         # React Query hooks (use-trading.ts)
│   │   │   └── lib/           # Utils, API client
│   │   └── .replit-artifact/  # artifact.toml (2 services: web + trading-api)
│   ├── saas/                  # AlgoEdge public SaaS platform (React/Vite)
│   │   ├── src/
│   │   │   ├── lib/config.ts  # BASE_URL + SAAS_API_BASE constants
│   │   │   ├── pages/         # Placeholder.tsx (Stage 4 replaces content)
│   │   │   └── App.tsx        # Wouter router: /, /dashboard, /settings
│   │   └── .replit-artifact/  # artifact.toml (2 services: web + saas-api)
│   ├── api-server/            # Express API (unused, legacy)
│   └── mockup-sandbox/        # Canvas preview server
├── lib/                       # Shared TS libraries
├── pnpm-workspace.yaml
└── .replit
```

## Stack (Monorepo)

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
