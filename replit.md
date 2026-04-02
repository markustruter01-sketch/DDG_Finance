# Overview

This project is a pnpm workspace monorepo comprising an AI Quantitative Trading Platform, a Trading Dashboard, and the AlgoEdge SaaS Platform. Its primary goal is to deliver an autonomous trading system with advanced monitoring and a public-facing platform. The system uses AI for market analysis and decision-making, aiming for high efficiency and continuous learning.

# User Preferences

I want iterative development and detailed explanations of changes. Ask before making major architectural changes or introducing new dependencies. Do not make changes to files in the `kraken-bot/` directory or modify any of the existing Kraken bot profiles.

# System Architecture

The project uses a monorepo structure managed by pnpm workspaces and includes:

## AI Quantitative Trading Platform (Python/FastAPI)

-   **Runtime**: Python 3.11
-   **Framework**: FastAPI + Uvicorn
-   **LLM**: Groq (Llama 3.3 70B Versatile) for market analysis and regime classification.
-   **Database**: PostgreSQL (primary) with SQLite fallback for trade journaling, vault ledger, ratchet stops, and performance snapshots.
-   **Architecture**: Modular design including components for data integration, AI analysis (with RAG feedback, post-mortem analysis, and a rule engine), notifications, portfolio management (Kelly Criterion), and execution management (Alpaca integration, kill switch, slippage tracking).
-   **Regime-Switching Architecture**: Dynamically adjusts asset allocation across a fixed 8-asset universe (SPY, QQQ, TLT, GLD, BTC/USD, ETH/USD, ATOM/USD, SGOV) based on a 3-step Bull/Bear/Sideways regime model determined by the LLM.
-   **Key Features**: 24/7 dual-mode trading, 15-minute intraday cycles, smart data caching, LLM budget guardrails, pre-LLM signal guardrails (TemporalQuarantine, MultiSourceConsensus, PriceToSentimentDivergence), and a shared risk library.
-   **RAG Memory Architecture**: A 4-phase Retrieval-Augmented Generation layer for deterministic post-mortem logging, context-aware prompt injection, and deriving permanent hardcoded rules from failure patterns.

## Trading Dashboard (React/Vite)

-   **Framework**: React 19 + Vite
-   **Styling**: Tailwind CSS v4
-   **State Management**: TanStack React Query
-   **Routing**: wouter v3 (lightweight)
-   **UI/UX**: Dark terminal-themed, mobile-responsive interface with gamification elements for bot performance.
-   **Key Components**: `TradeWorkflowBar`, `Dashboard`, `CorrelationMatrix`, `SentimentGauges`, `EconomicCalendarBanner`, `RiskMetricsPanel`, `AttributionPanel`, `BacktesterPanel`, `ControlPanel`, `SystemHealthModal` (live architecture monitoring).
-   **Dashboard Home Page** (`/`): Single-page layout with: FleetStatusBar (regime header + 6 bot tiles with status/cycles/last cycle timestamp), FleetPerformanceHero (equity, trades, win rate), Equity Trend sparklines, Fleet Equity Curve chart, ConsolidatedPositionsTable (unified cross-bot positions with sortable columns: Bot/Symbol/Side/Qty/Entry/Current/Size/P&L + bot filter tabs), CombinedTradeHistorySection (7 per-bot filter tabs with full trade columns), FleetCommanderPanel + VaultPanel side-by-side, RiskMetricsPanel. BottomNav (Home/CMD/Live) for page-level navigation.
-   **Streaming Page** (`/streaming`): Gamified broadcast overlay for Twitch/YouTube streaming. Lazy-loaded via React.lazy(). Features: Global HUD (4 glowing metric cards with pulsating Platform Balance), Win/Loss scoreboard with scrolling trade feed, Nerve Center bot network visualization with Trade Insight dialogue box (rotates through top 10 trades with AI reasoning), News & Macro Intelligence panel (3 headlines at a time with fallback when NewsAPI rate-limited), analog clock-flip digit animations (AnimatedValue), formula ticker, 6-slot Signal Radar, Profit Explosion overlay (triggered on >$50 wins), and Sales Ticker footer. Components in `src/components/streaming/`.
-   **Dashboard Features**: CollapsibleSection wrapper for positions/trades (collapsed by default), ExportReportButton (downloads trading report from `/trading-api/export/report`), equity trend sparklines for all 6 bots including Apex/Navigator derived from PnL/equity ratios.

## Kraken Bot Fleet (Multi-Bot System)

-   Three 24/7 paper-trading crypto bots (`davy-jones`, `blackbeard`, `calypso`) with distinct risk profiles.
-   **Stack**: Python 3.11, Kraken (via ccxt in paper mode), PostgreSQL (isolated `bot_id` columns).
-   **Architecture**: Configurable profiles, DB isolation, and file isolation per bot. Features dynamic VPIN scaling, robust risk management, and ATR-based dynamic stops.
-   **RAG TTL Decay**: Filters LLM insights to a 48-hour window to prevent stale context.

## Bot #5: Apex Predator Options Engine

-   **Strategy**: 100% LLM-free quant options engine using Alpaca Options API.
-   **Signals**: IVR < 20 threshold + Bollinger Band squeeze detection.
-   **Trades**: ATM Long Straddle construction (30-45 DTE) on a 106-ticker watchlist.
-   **Sizing**: Half-Kelly position sizing with a 5% capital fence.
-   **Schedule**: APScheduler CronTrigger daily at 3:30 PM ET.
-   **Persistence**: SQLite persistence for state, positions, and trades.
-   **API Endpoints**: Comprehensive set of endpoints for state, positions, pending trades, and control actions.
-   **Dashboard Tab**: Dedicated "Options" tab with capital fence cards, volatility scanner, and trade approval queue.

## Bot #6: The Navigator — Forex Swing Engine

-   **Strategy**: H4 (4-hour) swing trading on 30 FX pairs.
-   **LLM Usage**: Groq Macro Compass for USD directional bias only; execution is 100% algorithmic.
-   **Data Source**: Yahoo Finance API.
-   **Risk Management**: SL = 1.5× ATR(14), TP = 3.0× ATR(14), max 1.5% risk per trade, max 10 open positions.
-   **Capital**: $100k paper (PostgreSQL-backed) with a Capital Vault sweeping 20% of profits above HWM weekly.
-   **News Blackout**: Skips new entries if a high-impact economic event is within 4 hours.
-   **RAG Loop**: Injects last 5 losing trades into Groq prompt to avoid repeating mistakes.
-   **Schedule**: APScheduler IntervalTrigger every 4 hours.
-   **API Endpoints**: Endpoints for state, positions, trades, journal, vault, and control actions.
-   **Dashboard Tab**: Dedicated "Forex" tab with metrics grid, positions table, scanner results, trade history, and vault sweeps.

## Gemini Fleet Commander (All-Bot AI Audit)

-   **AI Model**: Gemini Flash (`gemini-3-flash-preview`).
-   **Schedule**: 6× daily via APScheduler.
-   **Scope**: Audits all 6 bots via full export reports.
-   **Enforcement**: `fleet_enforcer.py` applies Kraken parameter adjustments within hard bounds and writes veto conditions.
-   **Persistence**: `fleet_audit.json`, `fleet_audit_history.json`, `veto_conditions.json`.
-   **API Endpoints**: For status, history, and manual runs.
-   **Dashboard**: `FleetCommanderPanel.tsx` displays audit verdicts, parameter adjustments, and critique flags.

## Alert Notification System

-   **Channels**: Telegram Bot API and Discord webhooks (both optional).
-   **Queue**: JSON-persisted batched queue (`data/alert_queue.json`) with configurable digest intervals.
-   **Config**: `data/alert_config.json` for enabling, interval, min P&L, and channel preferences.
-   **API Endpoints**: For configuring, checking status, testing, and flushing alerts.
-   **Dashboard**: AlertSettingsPanel component in the More tab for control.
-   **Durability**: Queue cleared only after successful dispatch to at least one channel.

## System Health Architecture (9-Node Diagram)

-   **Component**: `artifacts/dashboard/src/components/SystemHealthModal.tsx` visualizes the health of 9 key system nodes.
-   **API**: GET `/system/health-architecture` returns real-time health data.

# External Dependencies

-   **Brokerage**: Alpaca API (Paper Trading)
-   **Data Sources**: FRED API, Alpaca Market Data, NewsAPI, yfinance, Fear & Greed Index, on-chain BTC data, economic calendar.
-   **LLM**: Groq (Llama 3.3 70B Versatile), Google Gemini Flash (`gemini-3-flash-preview`).
-   **Database**: PostgreSQL, SQLite.
-   **Notifications**: Discord webhooks, Telegram Bot API.
-   **Crypto Exchange**: Kraken (via ccxt library).
-   **Scheduling**: APScheduler.