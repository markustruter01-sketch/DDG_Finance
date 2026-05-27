export interface ArchNode {
  id: string;
  label: string;
  subtitle: string;
  col: 0 | 1 | 2 | 3 | 4;
  row: number;
  color: string;
  description: string;
}

export interface ArchEdge {
  id: string;
  from: string;
  to: string;
  label?: string;
}

export interface ArchFlow {
  id: string;
  label: string;
  description: string;
  nodeIds: string[];
  edgeIds: string[];
  steps: string[];
}

export const COLUMN_LABELS: Record<number, string> = {
  0: "BOTS",
  1: "API LAYER",
  2: "DATABASE",
  3: "EXTERNAL SERVICES",
  4: "LLMs",
};

export const COLUMN_COLORS: Record<number, string> = {
  0: "#f97316",
  1: "#22d3ee",
  2: "#8b5cf6",
  3: "#10b981",
  4: "#f59e0b",
};

export const NODES: ArchNode[] = [
  {
    id: "bot_oracle",
    label: "Oracle",
    subtitle: "Apex Predator · Alpaca",
    col: 0, row: 0,
    color: "#8b5cf6",
    description: "Momentum scanner and short-executor. Trades stocks and crypto via Alpaca. Runs on a 15-minute cycle scanning for momentum breakouts.",
  },
  {
    id: "bot_blackbeard",
    label: "Jerome Macro",
    subtitle: "Commodity ETF · Alpaca",
    col: 0, row: 1,
    color: "#f97316",
    description: "Macro commodity ETF trader. Uses the ALPACA_JEROME credentials. Trades GLD, SLV, USO and related commodity ETFs. 15-min cycle via runner.py.",
  },
  {
    id: "bot_davy_jones",
    label: "SPY/QQQ Trend",
    subtitle: "Trend Follow · Kraken",
    col: 0, row: 2,
    color: "#22d3ee",
    description: "SPY and QQQ trend-following bot. Uses ALPACA_BB credentials. Runs on a 60-min cycle inside runner.py alongside Jerome.",
  },
  {
    id: "bot_navigator",
    label: "Forex Gump",
    subtitle: "Forex Navigator · Oanda",
    col: 0, row: 3,
    color: "#10b981",
    description: "Foreign exchange pair trader. Scans 10 major FX pairs using a USD-bias regime filter. Managed by the dedicated forex_engine process.",
  },
  {
    id: "bot_poseidon",
    label: "Poseidon",
    subtitle: "Pairs Trading · Kraken",
    col: 0, row: 4,
    color: "#3b82f6",
    description: "Crypto pairs-trading engine. Looks for co-integration breakdowns between correlated crypto assets on Kraken and fades the spread.",
  },
  {
    id: "bot_kc",
    label: "Kraken Trend",
    subtitle: "Trend Follow · Kraken",
    col: 0, row: 5,
    color: "#ec4899",
    description: "Modernised Kraken trend-following bot (kraken-current). Uses EMA crossover + ATR volatility filter on BTC and ETH pairs.",
  },

  {
    id: "api_runner",
    label: "Bot Runner",
    subtitle: "runner.py · portfolio writes",
    col: 1, row: 1,
    color: "#22d3ee",
    description: "Single Python process managing the blackbeard and bot2_spy_qqq bot threads. Writes bot_portfolio rows every cycle and exposes a /health endpoint on port 8099.",
  },
  {
    id: "api_trading",
    label: "Trading API",
    subtitle: "FastAPI · uvicorn",
    col: 1, row: 2,
    color: "#22d3ee",
    description: "Central FastAPI server running on port 8000. Hosts all trading routes: /control, /portfolio, /kraken, /forex, /fleet/equity, /system, /claude_review, /reports.",
  },
  {
    id: "api_fleet_equity",
    label: "Fleet Equity",
    subtitle: "/fleet/equity endpoint",
    col: 1, row: 3,
    color: "#22d3ee",
    description: "Aggregates equity from all bots into a single fleet_total object. Reads bot_portfolio rows, applies starting-capital fallbacks, writes hourly equity_snapshots.",
  },
  {
    id: "api_control",
    label: "Fleet Control",
    subtitle: "/control · halt / pause",
    col: 1, row: 0,
    color: "#22d3ee",
    description: "Fleet-level control endpoints: HALT FLEET (writes fleet_halt flag), Rebalance, Liquidate All, per-bot pause/resume. Writes to bots_state and fleet_halt tables.",
  },
  {
    id: "api_system",
    label: "System Health",
    subtitle: "/system · health",
    col: 1, row: 4,
    color: "#22d3ee",
    description: "Health checker and stale-bot detection. Monitors bot_portfolio.last_updated per-bot thresholds and surfaces degradation events. Manual intervention required on stale detection.",
  },
  {
    id: "api_claude_review",
    label: "Claude Review",
    subtitle: "/claude_review · post-mortems",
    col: 1, row: 5,
    color: "#22d3ee",
    description: "Reads the last N closed trades and ships them to Anthropic Claude for post-mortem analysis. Stores insights in llm_learnings table.",
  },

  {
    id: "db_bot_portfolio",
    label: "bot_portfolio",
    subtitle: "equity · cash · positions",
    col: 2, row: 0,
    color: "#8b5cf6",
    description: "One row per bot. Stores current equity_usd, cash_usd, and open positions JSON. Updated every runner.py cycle (every 15–60 min). Source of truth for /fleet/equity.",
  },
  {
    id: "db_trades",
    label: "trades",
    subtitle: "All closed P&L records",
    col: 2, row: 1,
    color: "#8b5cf6",
    description: "Master trade ledger. Every closed position from every bot inserts a row with symbol, entry/exit price, pnl_usd, win/loss, and audit metadata.",
  },
  {
    id: "db_kraken_trades",
    label: "kraken_trades",
    subtitle: "Kraken execution log",
    col: 2, row: 2,
    color: "#8b5cf6",
    description: "Separate execution log for Kraken-based bots. Stores raw order IDs, filled quantities, and fee data from the Kraken WebSocket feed.",
  },
  {
    id: "db_bots_state",
    label: "bots_state",
    subtitle: "heartbeat · status · flags",
    col: 2, row: 3,
    color: "#8b5cf6",
    description: "Per-bot heartbeat table. Each bot writes last_heartbeat, status (running/paused/error), and a free-text error field. Auto-Heal reads this to detect stale bots.",
  },
  {
    id: "db_equity_snapshots",
    label: "equity_snapshots",
    subtitle: "Hourly fleet curve data",
    col: 2, row: 4,
    color: "#8b5cf6",
    description: "Time-series of fleet equity. Written every 15 minutes by the Trading API lifespan. Powers the Fleet Equity Curve chart on the Performance tab.",
  },
  {
    id: "db_llm_learnings",
    label: "llm_learnings",
    subtitle: "AI insights · post-mortems",
    col: 2, row: 5,
    color: "#8b5cf6",
    description: "Structured insights produced by Claude post-mortem reviews and Gemini fleet audits. Each row has a bot_id, insight text, severity, and a hardcoded_rule flag.",
  },

  {
    id: "ext_alpaca",
    label: "Alpaca",
    subtitle: "Paper trading API",
    col: 3, row: 0,
    color: "#10b981",
    description: "Alpaca Markets paper trading API. Two separate accounts: PA37SP8ID1XU (Jerome Macro) and PA3X9UBVZ6T8 (SPY/QQQ Trend). REST + WebSocket streaming.",
  },
  {
    id: "ext_kraken",
    label: "Kraken",
    subtitle: "Crypto exchange",
    col: 3, row: 1,
    color: "#10b981",
    description: "Kraken cryptocurrency exchange. Used by SPY/QQQ Trend, Poseidon, and Kraken Trend bots via the Kraken REST and WebSocket API.",
  },
  {
    id: "ext_oanda",
    label: "Oanda",
    subtitle: "Forex broker",
    col: 3, row: 2,
    color: "#10b981",
    description: "Oanda forex broker REST API. Used exclusively by Forex Gump for EUR/USD, GBP/USD, USD/JPY and 7 other major FX pairs.",
  },
  {
    id: "ext_data",
    label: "Market Data",
    subtitle: "yfinance · FRED · NewsAPI",
    col: 3, row: 3,
    color: "#10b981",
    description: "Multiple market data providers: yfinance for historical OHLCV, FRED (Federal Reserve) for macro indicators like DXY and fed funds rate, NewsAPI for sentiment.",
  },
  {
    id: "ext_alerts",
    label: "Discord / TG",
    subtitle: "Push alert channels",
    col: 3, row: 4,
    color: "#10b981",
    description: "Alert Manager routes critical degradation events and trade notifications to Discord webhooks and Telegram bots. Triggered by the Trading API /alerts route.",
  },

  {
    id: "llm_gemini",
    label: "Google Gemini",
    subtitle: "Fleet Commander · Audits",
    col: 4, row: 1,
    color: "#f59e0b",
    description: "Primary LLM for fleet-level reasoning. Powers the Fleet Commander chat (/fleet_chat), regime classification, and 24-hour math audit summaries.",
  },
  {
    id: "llm_claude",
    label: "Anthropic Claude",
    subtitle: "Post-mortems · Review",
    col: 4, row: 2,
    color: "#f59e0b",
    description: "Used for trade post-mortem analysis (/claude_review) and the Claude Brief button. Receives a structured JSON of recent trades and returns structured insights.",
  },
  {
    id: "llm_groq",
    label: "Groq",
    subtitle: "Fast analysis · Budget logic",
    col: 4, row: 3,
    color: "#f59e0b",
    description: "Low-latency LLM for time-sensitive inference: investor-style P&L commentary, rapid regime checks, and budget reasoning for smaller position sizing decisions.",
  },
];

export const EDGES: ArchEdge[] = [
  { id: "e_bb_runner",      from: "bot_blackbeard",   to: "api_runner",       label: "cycle" },
  { id: "e_dj_runner",      from: "bot_davy_jones",   to: "api_runner",       label: "cycle" },
  { id: "e_runner_alpaca",  from: "api_runner",        to: "ext_alpaca",       label: "read account" },
  { id: "e_runner_kraken",  from: "api_runner",        to: "ext_kraken",       label: "read account" },
  { id: "e_runner_db",      from: "api_runner",        to: "db_bot_portfolio", label: "write equity" },
  { id: "e_oracle_alpaca",  from: "bot_oracle",        to: "ext_alpaca",       label: "execute" },
  { id: "e_nav_oanda",      from: "bot_navigator",     to: "ext_oanda",        label: "execute" },
  { id: "e_pos_kraken",     from: "bot_poseidon",      to: "ext_kraken",       label: "execute" },
  { id: "e_kc_kraken",      from: "bot_kc",            to: "ext_kraken",       label: "execute" },
  { id: "e_api_trades",     from: "api_trading",       to: "db_trades",        label: "log P&L" },
  { id: "e_api_state",      from: "api_trading",       to: "db_bots_state",    label: "heartbeat" },
  { id: "e_fleet_portfolio",from: "api_fleet_equity",  to: "db_bot_portfolio", label: "read" },
  { id: "e_fleet_snap",     from: "api_fleet_equity",  to: "db_equity_snapshots", label: "write" },
  { id: "e_review_claude",  from: "api_claude_review", to: "llm_claude",       label: "prompt" },
  { id: "e_claude_store",   from: "llm_claude",        to: "db_llm_learnings", label: "store" },
  { id: "e_trades_review",  from: "db_trades",         to: "api_claude_review",label: "feed" },
  { id: "e_system_state",   from: "api_system",        to: "db_bots_state",    label: "monitor" },
  { id: "e_control_state",  from: "api_control",       to: "db_bots_state",    label: "halt/pause" },
  { id: "e_data_api",       from: "ext_data",          to: "api_trading",      label: "price feeds" },
  { id: "e_api_alerts",     from: "api_trading",       to: "ext_alerts",       label: "push alerts" },
  { id: "e_gemini_api",     from: "llm_gemini",        to: "api_trading",      label: "fleet decisions" },
];

export const FLOWS: ArchFlow[] = [
  {
    id: "jerome_trade",
    label: "Jerome Trade Cycle",
    description: "How Jerome Macro reads its Alpaca account and writes its equity to the database every 15 minutes.",
    nodeIds: ["bot_blackbeard", "api_runner", "ext_alpaca", "db_bot_portfolio"],
    edgeIds: ["e_bb_runner", "e_runner_alpaca", "e_runner_db"],
    steps: [
      "bot_blackbeard completes its trade logic cycle (15 min interval)",
      "runner.py calls _write_portfolio_from_alpaca() for the blackbeard bot",
      "API call to Alpaca paper account PA37SP8ID1XU → returns equity, cash, positions",
      "Runner upserts one row into bot_portfolio (bot_id = jerome_macro)",
      "Fleet Equity endpoint picks up the fresh row on next poll",
    ],
  },
  {
    id: "spy_qqq_trade",
    label: "SPY/QQQ Trend Cycle",
    description: "Independent 60-min cycle for the SPY/QQQ bot using a separate Alpaca account.",
    nodeIds: ["bot_davy_jones", "api_runner", "ext_alpaca", "ext_kraken", "db_bot_portfolio"],
    edgeIds: ["e_dj_runner", "e_runner_alpaca", "e_runner_kraken", "e_runner_db"],
    steps: [
      "bot2_spy_qqq thread fires on its 3600s cycle inside runner.py",
      "ALPACA_BB_KEY credentials used → connects to account PA3X9UBVZ6T8",
      "Trend signal evaluated against SPY and QQQ ETFs",
      "Order placed via Alpaca REST if signal crosses threshold",
      "Portfolio row updated: bot_id = spy_qqq_trend, equity ≈ $111k, pos = 1",
    ],
  },
  {
    id: "llm_postmortem",
    label: "LLM Post-Mortem",
    description: "How closed trades are shipped to Claude for AI-driven analysis and stored as learnings.",
    nodeIds: ["db_trades", "api_claude_review", "llm_claude", "db_llm_learnings"],
    edgeIds: ["e_trades_review", "e_review_claude", "e_claude_store"],
    steps: [
      "User triggers Claude Brief or the scheduled post-mortem job fires",
      "/claude_review endpoint reads the last 30 closed trades from db_trades",
      "Structured JSON payload sent to Anthropic Claude (claude-3-5-sonnet)",
      "Claude returns structured insights: patterns, rule violations, suggestions",
      "Insights inserted into llm_learnings with bot_id, severity, and hardcoded_rule flags",
    ],
  },
  {
    id: "fleet_halt",
    label: "Fleet Halt Signal",
    description: "How the HALT FLEET button propagates a stop signal to all running bots.",
    nodeIds: ["api_control", "db_bots_state", "api_system", "bot_oracle", "bot_blackbeard", "bot_davy_jones", "bot_navigator", "bot_poseidon", "bot_kc"],
    edgeIds: ["e_control_state", "e_system_state"],
    steps: [
      "User clicks HALT FLEET button on the dashboard",
      "POST /control/halt writes fleet_halt=true to the database flag table",
      "Each bot's main loop checks the fleet_halt flag at the start of every cycle",
      "Bots detect the flag and immediately enter paused state",
      "Auto-Heal /system monitors bots_state and confirms all bots show status=paused",
    ],
  },
  {
    id: "equity_snapshot",
    label: "Equity Snapshot",
    description: "How the fleet equity curve is built up over time from per-bot portfolio rows.",
    nodeIds: ["api_fleet_equity", "db_bot_portfolio", "db_equity_snapshots"],
    edgeIds: ["e_fleet_portfolio", "e_fleet_snap"],
    steps: [
      "Trading API lifespan registers a 15-minute interval heartbeat job",
      "/fleet/equity aggregates equity_usd from all active bot_portfolio rows",
      "Fleet total computed: sum of all bot equities minus starting capital for P&L",
      "Row inserted into equity_snapshots: alpaca, kraken, forex, total columns",
      "Dashboard Performance tab queries equity_snapshots for the equity curve chart",
    ],
  },
  {
    id: "oracle_trade",
    label: "Oracle Execution",
    description: "How the Oracle (Apex Predator) momentum scanner executes a trade via Alpaca.",
    nodeIds: ["bot_oracle", "ext_alpaca", "api_trading", "db_trades"],
    edgeIds: ["e_oracle_alpaca", "e_api_trades"],
    steps: [
      "Oracle scans momentum signals across its watchlist on a 15-min cycle",
      "Signal crosses threshold → ORDER submitted to Alpaca via REST API",
      "Alpaca fills the order and returns execution details",
      "Trading API logs the position open in db_trades (status = open)",
      "On position close, pnl_usd is calculated and the trade row is finalised",
    ],
  },
  {
    id: "autoheal",
    label: "Auto-Heal Loop",
    description: "How the system detects stale bots and automatically attempts to kick-restart them.",
    nodeIds: ["api_system", "db_bots_state", "ext_alerts"],
    edgeIds: ["e_system_state", "e_api_alerts"],
    steps: [
      "Claude report reconciliation runs on demand or scheduled",
      "Reads bot_portfolio.last_updated per-bot, computes age against per-bot thresholds",
      "Bot with age > threshold → degradation_tracker records bot_stale_workflow HIGH severity",
      "Stale flag appears in reconciliation_flags and errors_window of the Claude report",
      "Manual restart of the stale workflow is required — no auto-remediation layer",
    ],
  },
  {
    id: "gemini_fleet",
    label: "Gemini Fleet Command",
    description: "How Gemini powers the Fleet Commander chat and regime decisions.",
    nodeIds: ["llm_gemini", "api_trading", "db_bots_state", "db_llm_learnings"],
    edgeIds: ["e_gemini_api", "e_api_state"],
    steps: [
      "User opens Fleet Commander chat or regime check triggers automatically",
      "Trading API assembles context: equity data, recent trades, heartbeat status",
      "Prompt sent to Google Gemini with structured JSON context",
      "Gemini returns regime classification (BULL/BEAR/SIDEWAYS) + fleet recommendation",
      "Response stored in fleet_commander_chat table; insights written to llm_learnings",
    ],
  },
];
