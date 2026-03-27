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
- **Database**: SQLite trade journal with RAG feedback loop
- **Validation**: Pydantic v2
- **Scheduling**: APScheduler (3 jobs: morning analysis, intraday kill switch, evening post-mortem)

### Architecture
- `main.py` — FastAPI app with `APIRouter(prefix=API_PREFIX)` where `API_PREFIX` defaults to env var (set to `/trading-api` in artifact config)
- `config/settings.py` — Pydantic BaseSettings
- `data/` — FRED, Alpaca Market Data, NewsAPI async clients
- `analysis/` — Trade journal (SQLite), post-mortem reconciliation, Groq LLM client, RAG feedback injection, analyzer pipeline
- `portfolio/` — Kelly Criterion sizing, allocation logic
- `execution/` — Alpaca broker wrapper, kill switch (5% drawdown guard), order executor with slippage tracking
- `core/` — Scheduler (APScheduler), pipeline orchestration, market clock

### Key Features
- **10 Kelly-Criterion-sized slots** across Crypto, Commodity ETFs, Currency ETFs, Wildcard categories
- **SQLite RAG trade journal** — losses/wins/slippage injected into LLM system prompt
- **Strict LLM state awareness** — analyzer aborts with RuntimeError if account state fetch fails
- **Slippage tracking** — `intended_price` + `actual_fill_price` columns; post-mortem uses actual fill price as entry
- **Auto-trading toggle** — scheduler jobs start PAUSED; toggle resumes/pauses all 3 jobs; state tracked in module var
- **Kill switch** — 5% daily drawdown auto-liquidation

### API Endpoints (all prefixed with API_PREFIX)
- `GET /health` — System health
- `GET /status` — Full system status with scheduler info
- `GET /portfolio` — Alpaca account summary
- `GET /positions/live` — Live open positions from Alpaca
- `GET /allocation/latest` — Most recent LLM allocation
- `GET /performance` — Equity curve data
- `GET /performance/summary` — P&L summary stats
- `GET /journal` — All trade journal entries
- `GET /journal/wins` — Top N winning trades
- `GET /journal/losses` — Top N losing trades
- `GET /ai/commentary` — Latest LLM analysis commentary
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
- `TradeWorkflowBar.tsx` — Start Analysis + Auto-Trading toggle (power button with green glow + pulsing dot)
- `StatusBar.tsx` — ONLINE/OFFLINE status, market state, kill switch state
- `PortfolioCards.tsx` — Equity, cash, buying power
- `AIBrainSection.tsx` — LLM thoughts/commentary display
- `LivePositionsTable.tsx` — Real-time positions with unrealised P&L
- Performance analytics, journal tables, slippage display

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
