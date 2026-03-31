# Workspace

## Overview

This project is a pnpm workspace monorepo consisting of three main products: an AI Quantitative Trading Platform, a Trading Dashboard, and the AlgoEdge SaaS Platform.

The **AI Quantitative Trading Platform** is an autonomous trading system designed to execute trades based on AI-driven analysis. It aims for continuous operation and intelligent adaptation to market regimes.

The **Trading Dashboard** serves as a private, dark terminal-themed monitoring interface for the AI trading platform. It provides real-time insights, performance metrics, and control functionalities.

The **AlgoEdge SaaS Platform** is a public-facing platform.

The overarching goal is to create a robust, intelligent, and user-friendly ecosystem for quantitative trading, leveraging advanced AI and a resilient system architecture.

## User Preferences

I prefer iterative development, with clear communication before significant changes are made. I value detailed explanations of complex features and architectural decisions.

## System Architecture

The monorepo is structured with `pnpm workspaces` and includes `Python/FastAPI` for the trading logic and `React/Vite` for the frontends.

### Trading Platform (Python/FastAPI)

The trading platform is located in `trading-platform/` and is built with Python 3.11, FastAPI, and Uvicorn. It integrates with Alpaca API for paper trading, uses PostgreSQL (with SQLite fallback) for data persistence, and leverages Groq (Llama 3.3 70B Versatile) for LLM capabilities. APScheduler manages five critical jobs for market cycles, auditing, and self-criticism.

**Key Architectural Concepts:**
- **Regime-Switching Architecture (v4.0):** Employs a fixed 8-asset universe (equities, safe-havens, crypto, cash) and a 3-step regime model (Bull/Bear/Sideways) determined by moving averages and LLM classification. This drives dynamic capital allocation.
- **Hybrid Agentic Architecture:** Incorporates LLM-driven analysis with deterministic guardrails and rule engines.
- **RAG Memory Architecture (4-Phase):**
    - **Phase 1: Database Schema Expansion:** Extended trade and post-mortem tables for RAG data.
    - **Phase 2: Deterministic Post-Mortem Logging:** Structured lessons are logged for every trade close.
    - **Phase 3: Context-Aware Prompt Injection:** Relevant historical trade data (wins/losses) and post-mortem lessons are injected into LLM prompts based on the current market regime.
    - **Phase 4: Permanent Hardcoded Rules:** System identifies recurring failure patterns from post-mortems and promotes them to non-negotiable hardcoded rules injected into every LLM system prompt.
- **Guardrails and Safety Mechanisms:**
    - **Groq Budget Guardrails:** Manages token usage with daily limits, minimum call intervals, and graceful fallbacks.
    - **Pre-LLM Signal Guardrails:** Implements TemporalQuarantine (market hour blackouts), MultiSourceConsensus (news filtering), and PriceToSentimentDivergence to refine LLM input.
    - **Shared Risk Library:** Includes `RiskProfile`, `ExitBracket`, `CircuitBreaker`, and `VaRCircuitBreaker` for robust risk management across the system.
    - **Kill Switch:** A 5% daily drawdown auto-liquidation mechanism with a daily reset.
- **Efficient Data Handling:** Smart data caching for FRED macro data, NewsAPI, and Alpaca market data to optimize API calls and token usage.

### Dashboard (React/Vite)

The dashboard, located in `artifacts/dashboard/`, is a React 19 application built with Vite, styled using Tailwind CSS v4, and manages state with TanStack React Query. Recharts is used for data visualization.

**UI/UX Decisions:**
- **Dark Terminal Theme:** Provides a focused, private monitoring experience.
- **Mobile Responsive Design:** Utilizes a `useIsMobile()` hook and Tailwind's `md:` breakpoint for adaptive layouts, compacting information and optimizing touch targets on smaller screens. Features like `Sticky Bottom Tab Bar` (`CombinedTradeHistorySection`), `MobilePositionCard`, and modal transformations ensure a consistent experience.
- **Gamification:** Includes `StreakChip`, `XPRankBar`, and `KillBoardPanel` components with bot-specific ranks and badges to engage the user.

**Key Features:**
- **Real-time Monitoring:** Displays portfolio metrics, live positions, P&L summaries, and performance attribution.
- **Control Panel:** Allows manual triggers for analysis cycles, post-mortems, kill switch activation, and auto-trading toggles.
- **System Health:** Provides detailed health metrics of all subsystems with plain-English explanations and trading impact assessments.

### Artifact Configuration

The `.replit-artifact/artifact.toml` configures two services: `web` (Vite dev server) and `trading-api` (Python Uvicorn server), enabling path-based routing. For 24/7 scheduler operation and persistence, the deployment target is `vm`.

## External Dependencies

- **Brokerage/Trading API:** Alpaca API (Paper Trading)
- **Data Sources:**
    - FRED API (macroeconomic data)
    - Alpaca Market Data
    - NewsAPI
    - yfinance
    - Fear & Greed Index
    - On-chain BTC data
- **LLM:** Groq (llama-3.3-70b-versatile)
- **Database:** PostgreSQL (primary), SQLite (fallback)
- **Notifications:** Discord webhooks
- **Frontend Libraries:**
    - React 19
    - Vite
    - Tailwind CSS v4
    - TanStack React Query
    - Recharts
- **Scheduling:** APScheduler