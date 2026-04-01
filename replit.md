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
- **Key Components**: `TradeWorkflowBar`, `Dashboard` (main view ~5000 lines), `CorrelationMatrix`, `SentimentGauges`, `EconomicCalendarBanner`, `RiskMetricsPanel`, `AttributionPanel`, `BacktesterPanel`, `ControlPanel`, `SystemHealthModal` (live architecture monitoring).
- **Extracted Components** (from Dashboard.tsx consolidation):
  - `src/lib/dashboard-shared.tsx` — Shared utilities, gamification (streak/XP/ranks), animation helpers, market status, BOT_THEMES
  - `src/components/PortfolioSummary.tsx` — CombinedPortfolioSummary with 4 capital pools (US Equities, Crypto Fleet, Options, Forex), grand total $600k
  - `src/components/FleetPerformanceHero.tsx` — Fleet-wide equity/trades/win-rate hero stats including options + forex
  - `src/components/CommandersLog.tsx` — All 6 agent cards with XP/rank/recent trades
  - `src/components/PositionCards.tsx` — KrakenPositionCard, AlpacaPositionCard, ThesisModal
  - `src/components/LivePositionsSection.tsx` — Combined live positions across all bots
  - `src/components/OptionsSection.tsx` — Full options trading dashboard tab
  - `src/components/ForexSection.tsx` — Full forex trading dashboard tab with positions/history/scanner/vault
  - `src/components/VisualOverlays.tsx` — CRTOverlay, RegimeGlow, EquityEcho visual effects

### Kraken Bot Fleet (Multi-Bot System)

- Three 24/7 paper-trading crypto bots (`davy-jones`, `blackbeard`, `calypso`) with distinct risk profiles.
- **Stack**: Python 3.11, Kraken (via ccxt in paper mode), PostgreSQL (isolated `bot_id` columns for data).
- **Architecture**: Configurable profiles, DB isolation, and file isolation per bot. Dynamic VPIN scaling and robust risk management specific to each bot's profile.
- **Blacklist**: `BLACKLIST = ["ALGO/USD"]` in `kraken-bot/config.py` — skips evaluation and force-closes any open positions on blacklisted assets.
- **ATR Dynamic Stops**: Per-bot `ATR_STOP_MULTIPLIER` (Davy Jones: 1.5x conservative, Blackbeard/Calypso: 2.0x aggressive). Used in both `get_atr_stop_price()` and `get_position_size()` for consistent risk sizing.
- **RAG TTL Decay**: `get_top_learnings_for_prompt()` and `get_journal_entries()` filter insights to 48-hour window (`last_seen >= NOW() - INTERVAL '48 hours'`) to prevent stale/conflicting LLM context.

### Bot #5: Apex Predator Options Engine

- **File**: `trading-platform/options_engine.py`
- **Strategy**: 100% LLM-free pure quant options engine using Alpaca Options API.
- **Signals**: IVR (Implied Volatility Rank) < 20 threshold + Bollinger Band squeeze detection (20-day, 6-month low bandwidth).
- **Trades**: ATM Long Straddle construction (30-45 DTE) on 106-ticker watchlist (ETFs, mega-cap tech, financials, healthcare, energy, industrials, consumer, commodities).
- **Data Feed**: Uses `feed='iex'` for Alpaca paper trading (SIP requires paid subscription).
- **Rate Limiting**: 1.5s pause every 5 tickers to avoid Alpaca API rate limits. Full scan ~15 minutes.
- **Sizing**: Half-Kelly position sizing with 5% capital fence of total account equity.
- **Schedule**: APScheduler CronTrigger at 3:30 PM ET daily.
- **State**: SQLite persistence in `trading-platform/_options_state/` (state.json, positions.json, pending.json, trades.db).
- **API Endpoints**: GET `/options/state`, `/options/positions`, `/options/pending`; POST `/options/approve`, `/options/reject`, `/options/toggle`, `/options/scan`, `/options/close`.
- **Dashboard Tab**: 5th tab "Options" (Crosshair icon) with capital fence cards, volatility scanner, pending trade approval queue, open position cards with Greeks.

### Bot #6: The Navigator — Forex Swing Engine

- **Directory**: `forex-engine/`
- **Strategy**: H4 (4-hour) swing trading on 30 FX pairs (7 majors, 18 crosses, 5 exotics).
- **LLM Usage**: Groq Macro Compass only — 1 call per 4h cycle for USD directional bias (USD_BULLISH/USD_BEARISH/NEUTRAL). Uses shared `groq_budget.py` singleton. All execution is 100% algorithmic.
- **Data Source**: Direct Yahoo Finance API (`query1.finance.yahoo.com/v8/finance/chart/`) with yfinance fallback. Hourly bars resampled to H4.
- **Cross-Pair USD Conversion**: Centralized `get_quote_to_usd()` in `forex_config.py`. Converts P&L from quote currency to USD for all pair types: counter_usd (1.0), base_usd (1/price), cross pairs (via `CROSS_QUOTE_USD` reference pair mapping). Used in `paper_engine.py` (equity calc, position close), `forex_engine.py` (position sizing, live state display, size_usd calc).
- **Entry Signals**: RSI(14) oversold (<30) or overbought (>70), filtered by USD bias directional alignment.
- **Risk Management**: SL = 1.5× ATR(14), TP = 3.0× ATR(14) giving 1:2 R:R. Max 1.5% risk per trade, max 10 open positions, max 10% position size.
- **Capital**: $100k paper (PostgreSQL-backed). Capital Vault sweeps 20% of profits above HWM every Friday 4PM EST.
- **News Blackout**: Checks free economic calendar API; skips new entries if high-impact event within 4h.
- **RAG Loop**: Injects last 5 losing trades into Groq prompt to avoid repeating mistakes.
- **DB Tables**: `forex_heartbeat` (id=10), `forex_portfolio` (id=10), `forex_trades`, `forex_vault`.
- **Config**: `forex-engine/forex_config.py` — BOT_ID="navigator", BOT_DB_ID=10. Renamed from `config.py` to avoid shadowing by `trading-platform/config/` package.
- **DB Module**: `forex-engine/forex_nav_db.py` — Renamed from `db.py` to avoid shadowing by `trading-platform/db/` package.
- **Schedule**: APScheduler IntervalTrigger every 4 hours in trading-api lifespan. Uses timezone-aware `datetime.now(ET)` for `next_run_time` to avoid naive-UTC-vs-ET mismatch with the AsyncIOScheduler configured for America/New_York.
- **Trade Journal**: SQLite `forex-engine/forex_journal.db` — mirrors open/close trades for RAG loop sourcing. Preferred over PostgreSQL for loser retrieval.
- **API Endpoints**: GET `/forex/state`, `/forex/positions`, `/forex/trades`, `/forex/journal`, `/forex/vault`; POST `/forex/toggle`, `/forex/pause`, `/forex/resume`, `/forex/scan`.
- **Dashboard Tab**: 6th tab "Forex" (Globe icon) with teal color scheme, 7-card metrics grid, positions table, H4 scanner results, trade history, vault sweeps.
- **EXPECTED_JOB_COUNT**: 16 (5 trading + 5 startup + 6 fleet commander: auto_heal, learning_snapshot, equity_heartbeat, options_apex_predator, forex_navigator, fleet_commander_0415/0945/1200/1500/1700/2200).

### Gemini Fleet Commander (All-Bot AI Audit)

- **Files**: `trading-platform/analysis/fleet_commander.py`, `trading-platform/analysis/fleet_enforcer.py`
- **AI Model**: Gemini Flash (`gemini-3-flash-preview`) via user's own `GOOGLE_GEMINI_API_KEY` (direct Google API, not Replit proxy)
- **Schedule**: 6× daily via APScheduler — 04:15, 09:45, 12:00, 15:00, 17:00, 22:00 ET
- **Scope**: Audits all 6 bots (Oracle, Davy Jones, Blackbeard, Calypso, Apex Predator, Navigator) via the full export report
- **Enforcement**: `fleet_enforcer.py` applies Kraken param adjustments within hard BOUNDS (±1 step/cycle), writes veto conditions with 6h TTL. HOLD verdict always writes blocking veto state. Fail-open if enforcement fails.
- **Concurrency**: Threading lock prevents duplicate simultaneous runs
- **Token Tracking**: In-memory daily counter (prompt/completion/total tokens, call count)
- **Persistence**: `trading-platform/logs/fleet_audit.json` (latest), `fleet_audit_history.json` (last 24 runs), `veto_conditions.json` (active vetos)
- **API Endpoints**: GET `/admin/fleet-commander/status`, GET `/admin/fleet-commander/history`, POST `/admin/fleet-commander/run`
- **Dashboard**: `FleetCommanderPanel.tsx` on Overview tab — verdict badges, per-bot verdicts, param adjustments with before/after, critique flags, schedule, 24h history, token counter, "Run Now" button

### Artifact Configuration

- Services are defined in `artifact.toml`, including `web` (React Dashboard), `trading-api` (FastAPI), and three `kraken-bot` instances.
- Deployment target must be `vm` for persistent operation.

## External Dependencies

- **Brokerage**: Alpaca API (Paper Trading)
- **Data Sources**: FRED API, Alpaca Market Data, NewsAPI, yfinance, Fear & Greed Index, on-chain BTC data, economic calendar.
- **LLM**: Groq (Llama 3.3 70B Versatile), Google Gemini Flash (`gemini-3-flash-preview`) for Fleet Commander audits.
- **Database**: PostgreSQL, SQLite.
- **Notifications**: Discord webhooks, Telegram Bot API (configurable alert digests for profitable trades).
- **Crypto Exchange**: Kraken (via ccxt library).
- **Scheduling**: APScheduler.

## Alert Notification System

- **Files**: `trading-platform/notifications/telegram.py`, `trading-platform/notifications/alert_manager.py`, `trading-platform/notifications/discord.py`
- **Channels**: Telegram Bot API + Discord webhooks (both optional, independent)
- **Queue**: JSON-persisted batched queue (`data/alert_queue.json`) with configurable digest interval (5min–24hr)
- **Config**: `data/alert_config.json` — `enabled`, `interval_minutes`, `min_pnl_usd`, `telegram_enabled`, `discord_enabled`
- **API Endpoints**: GET `/alerts/config`, `/alerts/status`; POST `/alerts/config`, `/alerts/test`, `/alerts/flush`
- **Dashboard**: AlertSettingsPanel component in More tab — toggle, frequency grid, min P&L input, test/flush buttons
- **Bot Hooks**: All bots call `enqueue_profitable_trade()` on profitable close (Kraken, Forex, Options)
- **Durability**: Queue only cleared after at least one channel successfully dispatches
- **Setup**: User must set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in Secrets for Telegram; `DISCORD_WEBHOOK_URL` for Discord

## System Health Architecture (9-Node Diagram)

- **Component**: `artifacts/dashboard/src/components/SystemHealthModal.tsx`
- **Nodes**: platform_core, alpaca_api, kraken_api, data_pipeline, equity_manager, rag_engine, options_bot, forex_bot, alert_system
- **Wires**: Orthogonal (L-shaped) SVG paths with animated data-packet dots
- **Test Controls**: 8 scenario presets including "Total Failure" (all 9 nodes red)
- **API**: GET `/system/health-architecture` returns real-time health for all 9 nodes