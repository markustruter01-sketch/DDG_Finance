# Overview

This project is a pnpm workspace monorepo comprising an AI Quantitative Trading Platform, a Trading Dashboard, and the AlgoEdge SaaS Platform. Its primary goal is to deliver an autonomous trading system with advanced monitoring and a public-facing platform. The system uses AI for market analysis and decision-making, aiming for high efficiency and continuous learning.

# User Preferences

I want iterative development and detailed explanations of changes. Ask before making major architectural changes or introducing new dependencies. Do not make changes to files in the `kraken-bot/` directory or modify any of the existing Kraken bot profiles.

# System Architecture

The project uses a monorepo structure managed by pnpm workspaces and includes:

## AI Quantitative Trading Platform (Python/FastAPI)

-   **Runtime**: Python 3.11
-   **Framework**: FastAPI + Uvicorn
-   **LLM**: Groq used only by Forex Navigator (USD bias). Oracle #1 is now fully LLM-free. Gemini is no longer used by any stock trading path.
-   **Poseidon Statistical Arbitrage Engine (Bot #7)**: 15-min cycle. Dynamic pair discovery screens top-250 coins for cointegration. Entry thresholds: Z-score ≥ 1.5, ADF p < 0.20, hedge ratio drift ≤ 25%. Hurst exponent is computed and logged but NOT used as a gate (ADF on the spread is the sole stationarity test). MAX_POSITIONS=5, POSITION_VALUE_PCT=15% (max 75% deployed). Fallback pair set has 10 pair definitions (5 majors + 5 idiosyncratic). Files: `poseidon/config.py`, `poseidon/pairs_engine.py`, `poseidon/main.py`.
-   **Navigator Forex Engine (Bot #6)**: 4-hour H4 cycle. Active pair universe expanded to 10: EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, EUR/GBP, AUD/JPY, GBP/JPY, EUR/JPY. RSI thresholds relaxed: oversold 30→35, overbought 70→65. Per-pair INFO logging added showing RSI, bias, and signal outcome on every scan. Hard whitelist (`_PERMITTED_PAIRS` in `forex_engine.py`) and active PAIRS list (`forex_config.py`) must be kept in sync. Cross pairs (EUR/GBP, AUD/JPY, GBP/JPY, EUR/JPY) are direction-agnostic (not biased by USD direction from Groq).
-   **Oracle #1 Engine (Pure Momentum v3.1)**: Fully rewritten as a pure deterministic momentum scanner. `algo_scanner.py` scores ~250 NYSE/NASDAQ stocks using `composite_score = 5d×0.20 + 20d×0.50 + 60d×0.30`. Top 3 longs (score≥5.0, RSI 30-70, price>EMA20) + bottom 1 short (score<0, RSI 30-70, price<EMA20, ETB check). Stop-loss floor raised 4%→6%, take-profit floor raised 6%→9%. 4-hour minimum hold gate in `_close_stale_positions` prevents rotation exits before positions mature. Fixed 10% Kelly sizing until 30 closed trades, then half-Kelly capped at 15%. No SGOV, no JEPQ, no LLM, no regime switching. Runs every 15 min during NYSE market hours only. `oracle_short_executor.py` handles shortability checks and short order placement.
-   **Oracle Profit Reserve**: 15% of each winning Oracle trade's gross profit is swept to a DB ledger (`oracle_profit_reserve` table). Tracked in diagnostic report. Not reinvested — held as a separate reserve.
-   **Database**: PostgreSQL (primary) with SQLite fallback for trade journaling, vault ledger, ratchet stops, and performance snapshots.
-   **Architecture**: Modular design — pipeline.py → run_algo_scan → RegimeAnalysisOutput(regime="Sideways") → execute_allocations → execute_oracle_shorts. No LLM involvement in Oracle's trade path.
-   **Scheduler**: 2 registered jobs — `intraday_cycle` (Mon-Fri every 15 min, 09:01-15:46 ET) and `evening_postmortem` (Mon-Fri 16:10 ET). `crypto_cycle` and `gemini_self_critic` retired.
-   **Key Features**: 15-minute intraday cycles (NYSE hours), smart data caching, kill switch, ratchet stops, slippage tracking, and a shared risk library.
-   **RAG Memory Architecture**: A 4-phase Retrieval-Augmented Generation layer for deterministic post-mortem logging, context-aware prompt injection, and deriving permanent hardcoded rules from failure patterns.
-   **10-Addition Diagnostic Report Overhaul (COMPLETE)**: `report_sections.py` now includes 10 new sections wired into `export_diagnostic_report()` in `portfolio.py`:
    -   ADD 1: Live Code Parameter Snapshot (Oracle, Kraken ×3, Navigator, Poseidon) — reads from DB + code + live_state.json at report time
    -   ADD 2: Cycle Execution Audit Log (Oracle scan funnel, Kraken signal table, Poseidon pair table)
    -   ADD 3: Parameter Integrity / Drift Monitor — compares current kraken_adaptive_params vs baseline in `logs/param_baseline.json`
    -   ADD 4: Filter Effectiveness (7-day rolling) — VPIN blocks, Oracle RSI/score/EMA funnel, Poseidon ADF pass rate
    -   ADD 5: Fleet Health Scorecard (0-100 score, all 8 bots, top of report)
    -   ADD 6: Execution Quality — All Bots (expanded from Oracle-only, includes Kraken fees, Navigator spreads, Poseidon legs)
    -   ADD 7: Daily P&L Attribution — per-bot per-day table from equity_snapshots deltas, last 7 trading days
    -   ADD 8: Open Position Risk Summary — all open positions across all bots with stop distances
    -   ADD 9: System Infrastructure Status — heartbeats, data connection ages, scheduler jobs, system errors
    -   ADD 10: Changes Since Last Report — equity/param/trade/regime diffs; state saved to `logs/last_report_state.json`

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
-   **Stage 3/3.5 — Regime Isolation + Macro Defense**: Kraken bots now read `crypto_regime.json` (independent crypto classification from Crypto Fear & Greed + BTC 24h change + BTC dominance scoring) instead of inheriting equity-driven `market_regime.json`. Equity contagion only applies when rolling 60-day Pearson correlation > 0.6. Stage 3.5 additions: (1) BTC dominance now scored (rising dom + fear = bearish alts), (2) 3-cycle regime transition cooldown prevents whipsaw longs on brief bounces, (3) confidence gate (< 0.67 defaults to Bear), (4) tightened contrarian scout (RSI<20 @ 1.5% equity, was RSI<25 @ 3%), (5) regime history tracking (previous_regime + regime_changed in JSON).
-   **Correlation Matrix**: Rolling 60-day Pearson correlation between all 4 bot classes (Alpaca, Kraken, Options, Forex). When max correlation > 0.85 (systemic shock), positions auto-scale to 50%. File: `correlation_state.json`.
-   **WebSocket Feed**: `ws_feed.py` connects to `wss://ws.kraken.com/v2` for sub-second price updates with auto-reconnect (10x backoff). REST polling remains as fallback.
-   **Dynamic VPIN**: `vpin_adaptive.py` replaces hardcoded 0.82 threshold with 30-day rolling mean + 1.5σ (floor 0.60, ceiling 0.95).
-   **Consecutive-Loss Circuit Breaker**: Per-bot loss streak tracking in `main.py`. Calypso=8 losses/12h cooldown, Blackbeard=6/8h, Davy Jones=12/6h. Blocks new entries only (existing positions still managed). Streak restored from DB on restart. Status reported as `paused_loss_streak` in heartbeat. Dashboard GlobalHUD shows blinking `{N}L` badge during cooldown.
-   **Bot Strategies**: Davy Jones = `mean_reversion` (scalp), Blackbeard = `flow_sentiment` (swing, order flow imbalance + VPIN + RSI + volume), Calypso = `trend_following` (swing). Blackbeard and Calypso are swing bots (1h candles); Davy Jones is a scalp bot.
-   **Flow Sentiment Strategy** (`flow_sentiment.py`): Blackbeard's strategy. Primary signal: order flow imbalance (buy_vol/total_vol >0.65 long, <0.35 short). Filters: VPIN <0.75, VPIN spike block >0.85, RSI 40-60, volume >1.5× 20-MA. Exits: 2.0× ATR SL, 3.0× ATR TP, 24h max hold, 1h min hold. Max 5 positions.

## Bot #5: Apex Predator Options Engine

-   **Strategy**: 100% LLM-free quant options engine using Alpaca Options API.
-   **Signals**: IVR < 20 threshold + Bollinger Band squeeze detection.
-   **Trades**: ATM Long Straddle construction (30-45 DTE) on a 158-ticker watchlist (expanded from 105: added financials, healthcare, energy, industrials, consumer, materials, REITs, international ADRs).
-   **Sizing**: Half-Kelly position sizing with a 5% capital fence.
-   **Schedule**: APScheduler CronTrigger at 10am, 12pm, 2pm, and 3:30 PM ET (4 scans/day).
-   **Persistence**: SQLite persistence for state, positions, and trades.
-   **API Endpoints**: Comprehensive set of endpoints for state, positions, pending trades, and control actions.
-   **Dashboard Tab**: Dedicated "Options" tab with capital fence cards, volatility scanner, and trade approval queue.

## Bot #6: The Navigator — Forex Swing Engine

-   **Strategy**: H4 (4-hour) swing trading on 39 FX pairs (7 majors, 19 crosses including CHF/JPY, 13 exotics including TRY, PLN, DKK, HKD, INR, KRW, THB, CZK).
-   **LLM Usage**: Groq Macro Compass for USD directional bias only; execution is 100% algorithmic. Gemini fallback (`gemini-2.0-flash`) activates when Groq is rate-limited (429) or budget-throttled.
-   **Data Source**: Yahoo Finance API.
-   **Cross-Pair Conversion**: Pre-fetches reference prices (JPY=X, CHF=X, CAD=X, NZDUSD=X, AUDUSD=X, GBPUSD=X) at cycle start for accurate P&L on cross-pairs (EUR/JPY, GBP/JPY, AUD/NZD, etc.).
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