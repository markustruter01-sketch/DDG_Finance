export interface ArchNode {
  id: string; label: string; subtitle: string; col: 0 | 1 | 2 | 3 | 4; row: number; color: string; description: string;
}
export interface ArchEdge { id: string; from: string; to: string; label?: string; }
export interface ArchFlow { id: string; label: string; description: string; nodeIds: string[]; edgeIds: string[]; steps: string[]; }

export const COLUMN_LABELS: Record<number, string> = { 0: "BOTS", 1: "API LAYER", 2: "DATABASE", 3: "EXTERNAL SERVICES", 4: "LLMs" };
export const COLUMN_COLORS: Record<number, string> = { 0: "#f97316", 1: "#22d3ee", 2: "#8b5cf6", 3: "#10b981", 4: "#f59e0b" };

const bot = (id: string, label: string, row: number, color: string, description: string): ArchNode => ({ id, label, subtitle: "Alpaca ETF fleet", col: 0, row, color, description });
const api = (id: string, label: string, row: number, description: string): ArchNode => ({ id, label, subtitle: "FastAPI endpoint", col: 1, row, color: "#22d3ee", description });
const db = (id: string, label: string, row: number): ArchNode => ({ id, label, subtitle: "PostgreSQL table", col: 2, row, color: "#8b5cf6", description: `Current production table: ${label}.` });

export const NODES: ArchNode[] = [
  bot("bot_oracle", "Oracle / US Core", 0, "#a78bfa", "Momentum and risk-managed ETF execution for the US Core allocation."),
  bot("bot_spy_qqq", "SPY/QQQ Trend", 1, "#22d3ee", "Trend-following execution for the SPY and QQQ ETF allocation."),
  bot("bot_jerome", "Jerome Macro", 2, "#fb923c", "Macro ETF execution for the Emerging Markets allocation."),
  api("api_runner", "Bot Runner", 0, "Runs the three active Alpaca ETF strategy loops and writes portfolio heartbeats."),
  api("api_trading", "Trading API", 1, "FastAPI service for fleet control, positions, performance, health, audit, and analysis."),
  api("api_equity", "Fleet Equity", 2, "Server-computed fleet equity and win rate; the dashboard consumes this as the SSOT."),
  api("api_health", "System Health", 3, "Health architecture endpoint with active Alpaca fleet and service nodes."),
  db("db_bot_portfolio", "bot_portfolio", 0), db("db_trades", "trades", 1),
  db("db_fleet_snapshots", "fleet_equity_snapshots", 2), db("db_fleet_history", "fleet_equity_history", 3),
  db("db_etf_positions", "alpaca_etf_positions", 4), db("db_shadow_signals", "shadow_signals", 5),
  db("db_degradations", "system_degradations", 6), db("db_audit", "math_audit_log", 7),
  { id: "ext_alpaca", label: "Alpaca", subtitle: "US equities API", col: 3, row: 1, color: "#10b981", description: "Broker API used by the active ETF fleet." },
  { id: "llm_gemini", label: "Gemini", subtitle: "Analysis only", col: 4, row: 0, color: "#f59e0b", description: "Analysis and Fleet Commander context; never a trading engine." },
  { id: "llm_claude", label: "Claude", subtitle: "Analysis only", col: 4, row: 1, color: "#f59e0b", description: "Report and post-mortem analysis; never a trading engine." },
  { id: "llm_groq", label: "Groq", subtitle: "Analysis only", col: 4, row: 2, color: "#f59e0b", description: "Regime and commentary analysis; never a trading engine." },
];

export const EDGES: ArchEdge[] = [
  { id: "e_oracle_runner", from: "bot_oracle", to: "api_runner", label: "cycle" },
  { id: "e_spy_runner", from: "bot_spy_qqq", to: "api_runner", label: "cycle" },
  { id: "e_jerome_runner", from: "bot_jerome", to: "api_runner", label: "cycle" },
  { id: "e_runner_portfolio", from: "api_runner", to: "db_bot_portfolio", label: "heartbeat" },
  { id: "e_runner_alpaca", from: "api_runner", to: "ext_alpaca", label: "orders" },
  { id: "e_api_equity", from: "api_trading", to: "api_equity", label: "aggregate" },
  { id: "e_equity_snap", from: "api_equity", to: "db_fleet_snapshots", label: "snapshot" },
  { id: "e_api_trades", from: "api_trading", to: "db_trades", label: "audit" },
  { id: "e_api_positions", from: "api_trading", to: "db_etf_positions", label: "positions" },
  { id: "e_api_signals", from: "api_trading", to: "db_shadow_signals", label: "shadow ledger" },
  { id: "e_api_degradations", from: "api_health", to: "db_degradations", label: "health" },
  { id: "e_api_math", from: "api_trading", to: "db_audit", label: "math audit" },
  { id: "e_gemini", from: "llm_gemini", to: "api_trading", label: "analysis" },
  { id: "e_claude", from: "llm_claude", to: "api_trading", label: "reports" },
  { id: "e_groq", from: "llm_groq", to: "api_trading", label: "regime" },
];

export const FLOWS: ArchFlow[] = [
  { id: "fleet_execution", label: "ETF Fleet Execution", description: "A strategy cycle evaluates signals, submits orders to Alpaca, and records the resulting state.", nodeIds: ["bot_oracle", "bot_spy_qqq", "bot_jerome", "api_runner", "ext_alpaca", "db_bot_portfolio", "db_trades"], edgeIds: ["e_oracle_runner", "e_spy_runner", "e_jerome_runner", "e_runner_alpaca", "e_runner_portfolio", "e_api_trades"], steps: ["Active ETF bot evaluates its watchlist", "Runner submits an order to Alpaca", "Portfolio and trade state are persisted", "Fleet equity reflects the server-side result"] },
  { id: "equity_snapshot", label: "Fleet Equity Snapshot", description: "The API aggregates the active fleet and records its mark-to-market history.", nodeIds: ["api_equity", "db_bot_portfolio", "db_fleet_snapshots", "db_fleet_history"], edgeIds: ["e_equity_snap"], steps: ["Read active bot portfolio rows", "Compute fleet_total server-side", "Record snapshot and history", "Dashboard reads the canonical response"] },
  { id: "analysis_only", label: "Analysis Layer", description: "Gemini, Claude, and Groq provide analysis and reporting only.", nodeIds: ["llm_gemini", "llm_claude", "llm_groq", "api_trading"], edgeIds: ["e_gemini", "e_claude", "e_groq"], steps: ["API assembles current context", "Analysis model returns commentary or report", "No model is permitted to submit trades"] },
];