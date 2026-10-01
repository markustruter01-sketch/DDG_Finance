import { getBotIdentity } from "./identity";

// Fictional sandbox-only examples matching the dashboard service response shapes.
const recentIso = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();

const fleetEquity = {
  fleet_total: { equity: 312_480, pnl: 12_480, pnl_pct: 4.16, win_rate: 0.64 },
  oracle: { equity: 104_820, pnl: 4_820, pnl_pct: 4.82, paused: false, positions: 2, stale: false },
  spy_qqq_trend: { equity: 108_140, pnl: 8_140, pnl_pct: 8.14, paused: false, positions: 1, stale: false },
  jerome_macro: { equity: 99_520, pnl: -480, pnl_pct: -0.48, paused: false, positions: 1, stale: false },
};

const trades = [
  { trade_id: "demo-001", bot_id: "spy_qqq_trend", ticker: "QQQ", status: "Closed_Win", date: recentIso(4), pnl_usd: 426, realized_pnl: 426, pnl_percentage: 1.28 },
  { trade_id: "demo-002", bot_id: "oracle", ticker: "VTI", status: "Closed_Win", date: recentIso(19), pnl_usd: 188, realized_pnl: 188, pnl_percentage: 0.74 },
  { trade_id: "demo-003", bot_id: "jerome_macro", ticker: "EEM", status: "Closed_Loss", date: recentIso(43), pnl_usd: -92, realized_pnl: -92, pnl_percentage: -0.38 },
  { trade_id: "demo-004", bot_id: "spy_qqq_trend", ticker: "SPY", status: "Closed_Win", date: recentIso(75), pnl_usd: 315, realized_pnl: 315, pnl_percentage: 0.91 },
  { trade_id: "demo-005", bot_id: "oracle", ticker: "VEA", status: "Closed_Win", date: recentIso(112), pnl_usd: 141, realized_pnl: 141, pnl_percentage: 0.55 },
  { trade_id: "demo-006", bot_id: "jerome_macro", ticker: "IEMG", status: "Closed_Win", date: recentIso(165), pnl_usd: 204, realized_pnl: 204, pnl_percentage: 0.82 },
];

export const mockHealthData = {
  timestamp: Date.now(),
  status: "degraded" as const,
  nodes: {
    platform_core: { label: "Platform Core", level: "green" as const, latency_ms: 42, data_age_s: null, detail: "Core services responding normally." },
    bot_oracle: { label: getBotIdentity("oracle").displayName, level: "green" as const, latency_ms: 86, data_age_s: 12, detail: "Strategy heartbeat received." },
    bot_spy_qqq_trend: { label: getBotIdentity("spy_qqq_trend").displayName, level: "green" as const, latency_ms: 91, data_age_s: 8, detail: "Strategy heartbeat received." },
    bot_jerome_macro: { label: getBotIdentity("jerome_macro").displayName, level: "yellow" as const, latency_ms: 248, data_age_s: 44, detail: "Latest strategy heartbeat is slower than its normal interval.", kick_pending: false },
    alpaca_api: { label: "Alpaca API", level: "green" as const, latency_ms: 124, data_age_s: null, detail: "Broker API reachable." },
    data_pipeline: { label: "Data Pipeline", level: "green" as const, latency_ms: 63, data_age_s: 9, detail: "Market snapshots flowing normally." },
    alert_system: { label: "Alert System", level: "green" as const, latency_ms: 38, data_age_s: null, detail: "Alert delivery is operational." },
    degradation_events: { label: "Degradation Events", level: "yellow" as const, latency_ms: null, data_age_s: 44, detail: "One recent slow heartbeat is being monitored." },
    equity_manager: { label: "Equity Manager", level: "green" as const, latency_ms: 52, data_age_s: 15, detail: "Fleet equity aggregation is current." },
    analysis_layer: { label: "Analysis Layer", level: "unknown" as const, latency_ms: null, data_age_s: null, detail: "Analysis checks are not included in this sample report." },
  },
} as const;

export function useFleetEquity() { return { data: fleetEquity }; }
export function useLivePositions() {
  const positions = [
    { bot_id: "oracle", symbol: "VTI", unrealized_pl: 642 },
    { bot_id: "oracle", symbol: "VEA", unrealized_pl: 218 },
    { bot_id: "spy_qqq_trend", symbol: "QQQ", unrealized_pl: 1_140 },
    { bot_id: "jerome_macro", symbol: "EEM", unrealized_pl: -86 },
  ];
  return { data: { positions, positions_by_bot: {
    oracle: { count: 2, positions: positions.filter((p) => p.bot_id === "oracle") },
    spy_qqq_trend: { count: 1, positions: positions.filter((p) => p.bot_id === "spy_qqq_trend") },
    jerome_macro: { count: 1, positions: positions.filter((p) => p.bot_id === "jerome_macro") },
  } } };
}
export function useJournal() {
  const wins = trades.filter((trade) => trade.status === "Closed_Win").length;
  return { data: { trades, summary: { total: trades.length, wins, avg_pnl: 0.65 } }, isLoading: false, isError: false };
}
export function useBotRegistry() {
  return { data: { bots: [
    { id: "oracle", exchange: "alpaca", asset_class: "stocks", color: "purple", status: "active" },
    { id: "spy_qqq_trend", exchange: "alpaca", asset_class: "equity_etf", color: "cyan", status: "active" },
    { id: "jerome_macro", exchange: "alpaca", asset_class: "macro_etf", color: "orange", status: "active" },
  ] }, isLoading: false, isError: false };
}
export function useRiskMetrics() {
  return { data: { sharpe_ratio: 1.24, sortino_ratio: 1.76, max_drawdown_pct: 6.8, calmar_ratio: 0.82, volatility_annual_pct: 18.4, annualised_return_pct: 14.2, insufficient_data: false, data_points: 72, period_days: 90, message: null }, isLoading: false, isError: false };
}
export function useMathAuditSummary(_hours?: number) { return { data: { pass: 1842, warn: 14, fail: 2, total_logged: 1858 } }; }
export function useMathAuditRecent(_limit?: number, _scope?: string) {
  return { data: { rows: [
    { status: "PASS", formula_name: "Sharpe Ratio", bot_id: "spy_qqq_trend", audit_timestamp: recentIso(1) },
    { status: "WARN", formula_name: "Sortino Ratio", bot_id: "oracle", audit_timestamp: recentIso(3) },
    { status: "PASS", formula_name: "Drawdown Check", bot_id: "jerome_macro", audit_timestamp: recentIso(7) },
    { status: "FAIL", formula_name: "Volatility Bounds", bot_id: "oracle", audit_timestamp: recentIso(12) },
    { status: "PASS", formula_name: "Calmar Ratio", bot_id: "spy_qqq_trend", audit_timestamp: recentIso(18) },
    { status: "PASS", formula_name: "Equity Reconciliation", bot_id: "jerome_macro", audit_timestamp: recentIso(24) },
  ] } };
}
export function useAttribution() { return { data: { overall: { win_rate: 64, avg_pnl_pct: 0.7 } } }; }
export function useSentiment() { return { data: { market_fear_greed: { value: 58 } } }; }
export function useStatusSummary() {
  return { data: { groq: { regime: "Bull" }, system_health: { system_status: "online" }, market_open: true, kill_switch_tripped: false, position_count: 4, auto_trading: true } };
}
export function useVault() { return { data: { total_vaulted_usd: 18_420 } }; }
export function useVaultHistory(_days?: number) {
  const snapshots = Array.from({ length: 12 }, (_, i) => {
    const cumulative = 9_200 + i * 820 + (i % 3) * 115;
    return { date: new Date(Date.now() - (11 - i) * 7 * 86_400_000).toISOString().slice(0, 10), cumulative_vaulted: cumulative, daily_vaulted: i % 3 === 0 ? 310 : 0 };
  });
  return { data: { snapshots, total_vaulted_usd: 18_420 }, isLoading: false };
}