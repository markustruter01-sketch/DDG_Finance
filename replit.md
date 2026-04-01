# Workspace

## Overview

This project is a pnpm workspace monorepo consisting of three main products: an AI Quantitative Trading Platform, a Trading Dashboard, and the AlgoEdge SaaS Platform. The core purpose is to provide an autonomous trading system with a sophisticated monitoring interface and a public-facing platform. The system leverages advanced AI models for market analysis and decision-making, aiming for high efficiency and continuous learning.

## User Preferences

I want iterative development and detailed explanations of changes. Ask before making major architectural changes or introducing new dependencies. Do not make changes to files in the `kraken-bot/` directory or modify any of the existing Kraken bot profiles.

## System Architecture

The project employs a monorepo structure managed by pnpm workspaces.

### AI Quantitative Trading Platform (Python/FastAPI)

- **Runtime**: Python 3.11
- **Framework**: FastAPI + Uvicorn
- **LLM**: Groq (Llama 3.3 70B Versatile) for market analysis and regime classification.
- **Database**: PostgreSQL (primary) with SQLite fallback, used for trade journaling, vault ledger, ratchet stops, and performance snapshots.
- **Architecture**:
    - `main.py`: FastAPI app routing.
    - `config/settings.py`: Pydantic BaseSettings for configuration.
    - `data/`: Integrates various market data sources.
    - `analysis/`: Contains core AI logic, including Groq LLM integration, RAG feedback, post-mortem analysis, and a rule engine for permanent hardcoded rules derived from past failures. Key components include `Inspector Rekt` (HITL auditor) and `gemini_auditor` (AI self-critic). Includes mechanisms for LLM budget management and response caching.
    - `notifications/`: Discord webhook alerts for trading events.
    - `portfolio/`: Implements Kelly Criterion sizing and allocation logic.
    - `execution/`: Manages Alpaca broker interactions, kill switch, and order execution with slippage tracking. Features a `short_scanner.py` for bear market strategies.
    - `core/`: Handles APScheduler-based scheduling, pipeline orchestration, and market clock.
- **Regime-Switching Architecture (v4.0)**:
    - Fixed 8-asset universe (SPY, QQQ, TLT, GLD, BTC/USD, ETH/USD, ATOM/USD, SGOV).
    - 3-step regime model (Bull/Bear/Sideways) determined by LLM based on moving averages, dictating dynamic asset allocation.
    - Variable slot count (1-6) with Python-enforced even-weight sizing. Prioritizes capital preservation by defaulting to SGOV if no high-conviction trades align.
- **Key Features**: Dual-mode 24/7 trading (market hours and crypto-only), 15-minute intraday cycles for rapid learning, smart data caching, Groq budget guardrails, pre-LLM signal guardrails (TemporalQuarantine, MultiSourceConsensus, PriceToSentimentDivergence), and a shared risk library (`shared/`) with `RiskProfile`, `ExitBracket`, `CircuitBreaker`, and `VaRCircuitBreaker`.
- **RAG Memory Architecture**: A 4-phase Retrieval-Augmented Generation memory layer:
    1.  **Database Schema Expansion**: Enhanced `trades` and added `execution_post_mortems` tables.
    2.  **Deterministic Post-Mortem Logging**: Structured logging of trade outcomes and lessons.
    3.  **Context-Aware Prompt Injection**: Dynamically injects relevant historical trade lessons into LLM prompts based on the current market regime.
    4.  **Permanent Hardcoded Rules**: Automatically derives and injects non-negotiable rules into LLM system prompts from recurring failure patterns.

### Trading Dashboard (React/Vite)

- **Framework**: React 19 + Vite
- **Styling**: Tailwind CSS v4
- **State Management**: TanStack React Query
- **UI/UX**: Dark terminal-themed interface, mobile-responsive design with a sticky bottom tab bar for mobile. Features gamification elements for bot performance (streaks, XP, ranks, kill boards).
- **Key Components**: `TradeWorkflowBar`, `Dashboard` (main view), `CorrelationMatrix`, `SentimentGauges`, `EconomicCalendarBanner`, `RiskMetricsPanel`, `AttributionPanel`, `BacktesterPanel`, `ControlPanel`, `SystemHealthModal` (live architecture monitoring).

### Kraken Bot Fleet (Multi-Bot System)

- Three 24/7 paper-trading crypto bots (`davy-jones`, `blackbeard`, `calypso`) with distinct risk profiles.
- **Stack**: Python 3.11, Kraken (via ccxt in paper mode), PostgreSQL (isolated `bot_id` columns for data).
- **Architecture**: Configurable profiles, DB isolation, and file isolation per bot. Dynamic VPIN scaling and robust risk management specific to each bot's profile.

### Bot #5: Apex Predator Options Engine

- **File**: `trading-platform/options_engine.py`
- **Strategy**: 100% LLM-free pure quant options engine using Alpaca Options API.
- **Signals**: IVR (Implied Volatility Rank) < 20 threshold + Bollinger Band squeeze detection (20-day, 6-month low bandwidth).
- **Trades**: ATM Long Straddle construction (30-45 DTE) on watchlist (SPY, QQQ, NVDA, TSLA).
- **Sizing**: Half-Kelly position sizing with 5% capital fence of total account equity.
- **Schedule**: APScheduler CronTrigger at 3:30 PM ET daily.
- **State**: SQLite persistence in `trading-platform/_options_state/` (state.json, positions.json, pending.json, trades.db).
- **API Endpoints**: GET `/options/state`, `/options/positions`, `/options/pending`; POST `/options/approve`, `/options/reject`, `/options/toggle`, `/options/scan`, `/options/close`.
- **Dashboard Tab**: 5th tab "Options" (Crosshair icon) with capital fence cards, volatility scanner, pending trade approval queue, open position cards with Greeks.

### Bot #6: The Navigator — Forex Swing Engine

- **Directory**: `forex-engine/`
- **Strategy**: H4 (4-hour) swing trading on 5 major FX pairs (EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CHF).
- **LLM Usage**: Groq Macro Compass only — 1 call per 4h cycle for USD directional bias (USD_BULLISH/USD_BEARISH/NEUTRAL). Uses shared `groq_budget.py` singleton. All execution is 100% algorithmic.
- **Data Source**: yfinance (OANDA-ready structure for future live trading).
- **Entry Signals**: RSI(14) oversold (<30) or overbought (>70), filtered by USD bias directional alignment.
- **Risk Management**: SL = 1.5× ATR(14), TP = 3.0× ATR(14) giving 1:2 R:R. Max 1.5% risk per trade, max 5 open positions, max 10% position size.
- **Capital**: $100k paper (PostgreSQL-backed). Capital Vault sweeps 20% of profits above HWM every Friday 4PM EST.
- **News Blackout**: Checks free economic calendar API; skips new entries if high-impact event within 4h.
- **RAG Loop**: Injects last 5 losing trades into Groq prompt to avoid repeating mistakes.
- **DB Tables**: `forex_heartbeat` (id=10), `forex_portfolio` (id=10), `forex_trades`, `forex_vault`.
- **Config**: `forex-engine/config.py` — BOT_ID="navigator", BOT_DB_ID=10.
- **Schedule**: APScheduler IntervalTrigger every 4 hours in trading-api lifespan.
- **API Endpoints**: GET `/forex/state`, `/forex/positions`, `/forex/trades`, `/forex/vault`; POST `/forex/toggle`, `/forex/scan`.
- **Dashboard Tab**: 6th tab "Forex" (Globe icon) with teal color scheme, 7-card metrics grid, positions table, H4 scanner results, trade history, vault sweeps.
- **EXPECTED_JOB_COUNT**: 10 (5 trading + 5 startup: auto_heal, learning_snapshot, equity_heartbeat, options_apex_predator, forex_navigator).

### Artifact Configuration

- Services are defined in `artifact.toml`, including `web` (React Dashboard), `trading-api` (FastAPI), and three `kraken-bot` instances.
- Deployment target must be `vm` for persistent operation.

## External Dependencies

- **Brokerage**: Alpaca API (Paper Trading)
- **Data Sources**: FRED API, Alpaca Market Data, NewsAPI, yfinance, Fear & Greed Index, on-chain BTC data, economic calendar.
- **LLM**: Groq (specifically Llama 3.3 70B Versatile).
- **Database**: PostgreSQL, SQLite.
- **Notifications**: Discord webhooks.
- **Crypto Exchange**: Kraken (via ccxt library).
- **Scheduling**: APScheduler.