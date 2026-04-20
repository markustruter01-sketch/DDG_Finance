# Overview

This project is a pnpm workspace monorepo designed to deliver an AI Quantitative Trading Platform and a Trading Dashboard. Its primary goal is to provide an autonomous trading system with advanced monitoring capabilities, leveraging AI for market analysis and decision-making to achieve high efficiency and continuous learning.

# User Preferences

I want iterative development and detailed explanations of changes. Ask before making major architectural changes or introducing new dependencies. Do not make changes to files in the `kraken-bot/` directory or modify any of the existing Kraken bot profiles.

# System Architecture

The project employs a monorepo structure using pnpm workspaces, integrating several key components:

## AI Quantitative Trading Platform (Python/FastAPI)

-   **Runtime/Framework**: Python 3.11, FastAPI + Uvicorn.
-   **LLM Usage**: Groq (Forex Navigator only), Oracle #1 is LLM-free.
-   **Trading Engines**:
    -   **Poseidon Statistical Arbitrage Engine**: 15-min cycle, dynamic pair discovery, Z-score, ADF, hedge ratio drift for entry.
    -   **Navigator Forex Engine**: 4-hour H4 cycle, expanded active pair universe, RSI-based signals, per-pair logging.
    -   **Oracle #1 Engine (Stock Trend Follower v1.0)**: Deterministic EMA20/EMA50 crossover + ADX≥25 trend-following scanner for 253 NYSE/NASDAQ stocks. ATR-based Kelly sizing (1.5% equity risk / ATR×2.0, max 20%), 5L + 2S max slots. Trailing stops (ATR×2.0, ratchets after 1.5×ATR profit), EMA-reversal, ADX-weakness, and 15-day max-hold exits. 4-hour min-hold. 15-min cycles during market hours.
-   **Oracle Profit Reserve**: 15% of winning Oracle trade gross profit swept to a DB ledger.
-   **Database**: PostgreSQL (primary), SQLite (fallback) for journaling and snapshots.
-   **Architecture**: Modular pipeline design, RAG Memory for post-mortem logging and rule derivation.
-   **Scheduler**: Manages `intraday_cycle` and `evening_postmortem` jobs.
-   **Key Features**: 15-minute intraday cycles, smart data caching, kill switch, ratchet stops, slippage tracking, shared risk library.
-   **Diagnostic Report**: Comprehensive overhaul with 10 new sections for auditing, parameter monitoring, performance analysis, and system health.

## Trading Dashboard (React/Vite)

-   **Framework/Styling**: React 19 + Vite, Tailwind CSS v4.
-   **State Management/Routing**: TanStack React Query, wouter v3.
-   **UI/UX**: Dark terminal-themed, mobile-responsive with gamification elements.
-   **Key Components**: `TradeWorkflowBar`, `Dashboard`, `CorrelationMatrix`, `SentimentGauges`, `EconomicCalendarBanner`, `RiskMetricsPanel`, `AttributionPanel`, `BacktesterPanel`, `ControlPanel`, `SystemHealthModal`.
-   **Home Page**: FleetStatusBar, FleetPerformanceHero, Equity Trend sparklines, Fleet Equity Curve chart, ConsolidatedPositionsTable, CombinedTradeHistorySection, FleetCommanderPanel, VaultPanel, RiskMetricsPanel, BottomNav.
-   **Streaming Page**: Gamified broadcast overlay with Global HUD, Win/Loss scoreboard, Nerve Center bot network visualization, News & Macro Intelligence, Signal Radar, Profit Explosion overlay.

## Kraken Bot Fleet (Multi-Bot System)

-   **Description**: Three 24/7 paper-trading crypto bots (`davy-jones`, `blackbeard`, `calypso`) with distinct risk profiles.
-   **Stack**: Python 3.11, Kraken (via ccxt), PostgreSQL.
-   **Architecture**: Configurable profiles, DB isolation, dynamic VPIN scaling, robust risk management, ATR-based dynamic stops.
-   **Regime Isolation**: Crypto-specific regime classification (`crypto_regime.json`) for Kraken bots.
-   **Correlation Matrix**: Monitors Pearson correlation between bot classes, triggering position auto-scaling on systemic shocks.
-   **WebSocket Feed**: Utilizes `wss://ws.kraken.com/v2` for sub-second price updates with REST fallback.
-   **Dynamic VPIN**: Adaptive VPIN threshold based on 30-day rolling mean.
-   **Consecutive-Loss Circuit Breaker**: Per-bot loss streak tracking with cooldowns.
-   **Strategies**: Davy Jones (mean_reversion), Blackbeard (flow_sentiment), Calypso (trend_following).

## Bot #5: Apex Predator Options Engine

-   **Strategy**: LLM-free quant options engine using Alpaca Options API.
-   **Signals**: IVR < 20 and Bollinger Band squeeze detection.
-   **Trades**: ATM Long Straddles (30-45 DTE) on an expanded 158-ticker watchlist.
-   **Sizing**: Half-Kelly sizing with a 5% capital fence.
-   **Schedule**: APScheduler CronTrigger, 4 scans/day.
-   **Persistence**: SQLite for state, positions, and trades.
-   **Dashboard Integration**: Dedicated "Options" tab.

## Bot #6: The Navigator — Forex Swing Engine

-   **Strategy**: H4 (4-hour) swing trading on 39 FX pairs.
-   **LLM Usage**: Groq Macro Compass for USD directional bias only; algorithmic execution.
-   **Data Source**: Yahoo Finance API.
-   **Risk Management**: ATR-based SL/TP, max 1.5% risk per trade, max 10 open positions.
-   **Capital**: $100k paper (PostgreSQL-backed) with a Capital Vault.
-   **News Blackout**: Skips entries during high-impact economic events.
-   **RAG Loop**: Injects losing trades into Groq prompt to refine strategy.
-   **Schedule**: APScheduler IntervalTrigger every 4 hours.
-   **Dashboard Integration**: Dedicated "Forex" tab.

## Gemini Fleet Commander (All-Bot AI Audit)

-   **AI Model**: Gemini Flash (`gemini-3-flash-preview`).
-   **Schedule**: 6× daily via APScheduler.
-   **Scope**: Audits all 6 bots using export reports.
-   **Enforcement**: `fleet_enforcer.py` applies Kraken parameter adjustments and veto conditions.
-   **Persistence**: `fleet_audit.json`, `fleet_audit_history.json`, `veto_conditions.json`.
-   **Dashboard Integration**: `FleetCommanderPanel.tsx` displays audit verdicts.

## Platform-Wide Refactor (Completed Apr 2026)

-   **Metrics SSoT**: `trading-platform/core/metrics.py` — single source of truth for `win_rate`, `profit_factor`, `risk_metrics` (Sharpe/Sortino/max DD/Calmar/vol). All callers consolidated (kraken.py, new_bots.py, report_sections.py, portfolio.py). Uses ddof=1 consistently; ratios gated at n≥10; annualised at n≥30.
-   **DB Column Migration**: `kraken_current_trades.pnl` renamed to `pnl_usd`. Updated in db_utils.py, report_sections.py, kraken.py (fleet-summary), and all SQL queries.
-   **RSI Consistency**: `forex-engine/indicators.py` now uses Wilder's EMA smoothing (matches `kraken-bot/logic.py`). Previously used SMA.
-   **Dead Code**: `trading-platform/routes/options.py` removed (router was never registered in main.py). Options hooks in frontend disabled (`enabled: false`) to stop 404 polling.
-   **Sharpe/Sortino Consolidation**: All 3 separate implementations in `portfolio.py` now call `_compute_risk_metrics` from core.metrics (fixed ddof=0 bug in block 3).

## Alert Notification System

-   **Channels**: Telegram Bot API and Discord webhooks (optional).
-   **Queue**: JSON-persisted batched queue (`data/alert_queue.json`).
-   **Config**: `data/alert_config.json` for preferences.
-   **Durability**: Queue cleared only after successful dispatch.

## System Health Architecture

-   **Visualization**: `SystemHealthModal.tsx` visualizes health of 9 key system nodes.
-   **API**: `GET /system/health-architecture` provides real-time health data.

# External Dependencies

-   **Brokerage**: Alpaca API (Paper Trading).
-   **Data Sources**: FRED API, Alpaca Market Data, NewsAPI, yfinance, Fear & Greed Index, on-chain BTC data, economic calendar.
-   **LLM**: Groq (Llama 3.3 70B Versatile), Google Gemini Flash (`gemini-3-flash-preview`).
-   **Database**: PostgreSQL, SQLite.
-   **Notifications**: Discord webhooks, Telegram Bot API.
-   **Crypto Exchange**: Kraken (via ccxt library).
-   **Scheduling**: APScheduler.