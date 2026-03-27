# Workspace

## Overview

pnpm workspace monorepo with two main products:
1. **AI Quantitative Trading Platform** (Python/FastAPI) — autonomous trading system
2. **Trading Dashboard** (React/Vite) — dark terminal-themed monitoring UI

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
- **Scheduling**: APScheduler (4 jobs: 15-min intraday full-market cycle, 15-min 24/7 crypto-only cycle, evening post-mortem, daily auditor at 4:30 PM ET)

### Architecture
- `main.py` — FastAPI app with `APIRouter(prefix=API_PREFIX)` where `API_PREFIX` defaults to env var (set to `/trading-api` in artifact config)
- `config/settings.py` — Pydantic BaseSettings
- `data/` — FRED, Alpaca Market Data, NewsAPI, yfinance, sentiment (Fear & Greed), on-chain BTC data, economic calendar
- `analysis/` — Trade journal, post-mortem, Groq LLM, RAG feedback, analyzer, **auditor agent** (HITL), attribution breakdown, backtester
- `notifications/` — Discord webhook alerts (trades, kills, sweeps, audits, blackouts)
- `portfolio/` — Kelly Criterion sizing, allocation logic
- `execution/` — Alpaca broker wrapper, kill switch (5% drawdown guard), order executor with slippage tracking
- `core/` — Scheduler (APScheduler), pipeline orchestration, market clock

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
- **Smart data caching** — FRED macro data (1hr TTL, skipped in crypto-only), NewsAPI (30min TTL), Alpaca market data (always fresh, 6-month lookback)
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

## Dashboard (React/Vite)

Located in `artifacts/dashboard/`. Dark terminal-themed monitoring UI.

### Stack
- **Framework**: React 19 + Vite
- **Styling**: Tailwind CSS v4
- **State**: TanStack React Query
- **Charts**: Recharts

### Key Components
- `TradeWorkflowBar.tsx` — Start Analysis + Auto-Trading toggle
- `Dashboard.tsx` — Main dashboard page with all sections
- `CorrelationMatrix.tsx` — Pearson correlation heatmap with high-correlation warnings
- `SentimentGauges.tsx` — Dual SVG ring gauges for Crypto + Market Fear & Greed
- `EconomicCalendarBanner.tsx` — Blackout banner (red alert) + upcoming events list
- `RiskMetricsPanel.tsx` — Sharpe/Sortino/MaxDD/Calmar/Volatility/Return cards
- `AttributionPanel.tsx` — P&L breakdown by regime, asset class, conviction with win-rate bars
- `BacktesterPanel.tsx` — Momentum strategy backtester with equity curve chart and trade log
- `ControlPanel.tsx` — Mission Control buttons (kill switch, analysis, post-mortem)

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

## Required Secrets
- `FRED_API_KEY` — fred.stlouisfed.org
- `NEWS_API_KEY` — newsapi.org
- `ALPACA_API_KEY` — Alpaca paper trading key ID
- `ALPACA_SECRET_KEY` — Alpaca paper trading secret
- `GROQ_API_KEY` — Groq free API (llama-3.3-70b-versatile)

## Monorepo Structure

```text
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
│   │   └── .replit-artifact/  # artifact.toml (2 services)
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
