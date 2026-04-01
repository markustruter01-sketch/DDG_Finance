import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";

const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";

const api = axios.create({ baseURL: BASE });

// --- Types ---

export interface SystemHealth {
  status: string;
  version: string;
  system_status: "online" | "degraded" | "offline";
  status_reason: string;
  scheduler_job_count: number;
  last_run_status: string;
  error_count: number;
}

export interface PlatformStatus {
  market: { is_open: boolean; next_open: string | null };
  kill_switch: { tripped: boolean; drawdown_pct: number; opening_equity: number | null; threshold_pct: number };
  scheduler_jobs: Array<{ id: string; name: string; next_fire_utc: string }>;
  last_run: {
    last_run_utc: string | null;
    last_run_status: string;
    run_count: number;
    error_count: number;
    last_allocation: any[] | null;
    last_exec_result: any;
    cycle_interval: string;
    groq_using_fallback?: boolean;
  };
  auto_trading: boolean;
  cycle_interval: string;
  trading_mode: string;
  data_cache: Array<{ name: string; ttl_seconds: number; cached: boolean; age_seconds: number; hits: number; misses: number }>;
  groq?: {
    last_success_at: string | null;
    cache_age_min: number | null;
    cache_valid: boolean;
    regime: string | null;
    using_fallback: boolean;
    tokens_used_today: number;
    tokens_remaining: number;
    token_budget_total: number;
    pct_used: number;
    budget_exhausted?: boolean;
    regime_calls_today: number;
    commentary_calls_today: Record<string, number>;
    regime_interval_min: number;
    commentary_daily_cap: number;
    next_regime_eligible_at: string | null;
    regime_call_eligible: boolean;
  };
}

export interface EquitySnapshot {
  id: number;
  ts: string;
  alpaca_equity: number;
  kraken_equity: number;
  total_equity: number;
  regime: string | null;
  source: string;
}

export interface PortfolioData {
  account: { equity: number; cash: number; buying_power: number; initial_margin: number; trading_blocked: boolean };
  positions: Array<{
    symbol: string;
    qty: number;
    avg_entry_price: number;
    current_price: number;
    market_value: number;
    unrealized_pl: number;
    unrealized_plpc: number;
  }>;
  open_orders: Array<any>;
}

export interface PositionHealth {
  score: number;
  label: string;
  color: string;
}

export interface LivePosition {
  symbol: string;
  qty: number;
  side: string;
  avg_entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  asset_class: string;
  conviction_score: number | null;
  kelly_fraction: number | null;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  stop_loss_price: number | null;
  take_profit_price: number | null;
  original_thesis: string | null;
  health_score: PositionHealth | null;
}

export interface LivePositionsData {
  count: number;
  positions: LivePosition[];
}

export interface AllocationPlan {
  status: string;
  run_utc: string;
  regime: string | null;
  allocation: Array<{
    slot: number;
    ticker: string;
    asset_class: string;
    conviction_score: number;
    kelly_fraction: number;
    stop_loss_pct: number;
    take_profit_pct: number;
    thesis: string;
  }> | null;
}

export interface TradeJournal {
  summary: { total: number; active: number; wins: number; losses: number; avg_pnl: number };
  trades: Array<{
    trade_id: string;
    date: string;
    ticker: string;
    asset_class: string;
    conviction_score: number;
    pnl_percentage: number;
    original_thesis: string;
    status: string;
  }>;
}

export interface RagEntry {
  trade_id: string;
  date: string;
  ticker: string;
  asset_class: string;
  conviction_score: number;
  pnl_percentage: number;
  original_thesis: string;
}

export interface RagLosses {
  count: number;
  losses: RagEntry[];
}

export interface RagWins {
  count: number;
  wins: RagEntry[];
}

export interface PerformanceSnapshot {
  date: string;
  equity: number;
  daily_pnl_pct: number;
  cumulative_pnl_pct: number;
  win_rate: number;
  trades_placed: number;
}

export interface PerformanceHistory {
  count: number;
  snapshots: PerformanceSnapshot[];
}

export interface PerformanceSummary {
  total_days: number | null;
  total_trades: number | null;
  best_day_pct: number | null;
  worst_day_pct: number | null;
  avg_win_rate: number | null;
  max_cumulative_pnl_pct: number | null;
  min_cumulative_pnl_pct: number | null;
  latest_equity: number | null;
  total_return_pct: number | null;
  latest_date: string | null;
  avg_conviction: number | null;
}

// --- Hooks ---

export function useSystemHealth() {
  return useQuery<SystemHealth>({
    queryKey: ["/health"],
    queryFn: async () => (await api.get("/health")).data,
    refetchInterval: 10000,
    retry: 1,
  });
}

export function usePlatformStatus() {
  return useQuery<PlatformStatus>({
    queryKey: ["/status"],
    queryFn: async () => (await api.get("/status")).data,
    refetchInterval: 10000,
  });
}

export function usePortfolio() {
  return useQuery<PortfolioData>({
    queryKey: ["/portfolio"],
    queryFn: async () => (await api.get("/portfolio")).data,
    refetchInterval: 30000,
  });
}

export function useLivePositions() {
  return useQuery<LivePositionsData>({
    queryKey: ["/positions/live"],
    queryFn: async () => (await api.get("/positions/live")).data,
    refetchInterval: 30000,
  });
}

export function useLatestAllocation() {
  return useQuery<AllocationPlan>({
    queryKey: ["/allocation/latest"],
    queryFn: async () => (await api.get("/allocation/latest")).data,
  });
}

export function useJournal() {
  return useQuery<TradeJournal>({
    queryKey: ["/journal"],
    queryFn: async () => (await api.get("/journal")).data,
  });
}

export function useRagLosses() {
  return useQuery<RagLosses>({
    queryKey: ["/journal/losses"],
    queryFn: async () => (await api.get("/journal/losses?n=5")).data,
  });
}

export function useRagWins() {
  return useQuery<RagWins>({
    queryKey: ["/journal/wins"],
    queryFn: async () => (await api.get("/journal/wins?n=3")).data,
  });
}

export interface RecentTradeItem {
  trade_id: string;
  symbol: string;
  pnl_pct: number;
  pnl_usd: number | null;
  exit_reason: string | null;
  closed_at: string;
  status: "Closed_Win" | "Closed_Loss";
}

export interface RecentTrades {
  count: number;
  trades: RecentTradeItem[];
}

export function useRecentTrades(n = 20) {
  return useQuery<RecentTrades>({
    queryKey: ["/journal/recent", n],
    queryFn: async () => (await api.get(`/journal/recent?n=${n}`)).data,
    staleTime: 60_000,
  });
}

export function useRagWinsExtended(n = 10) {
  return useQuery<RagWins>({
    queryKey: ["/journal/wins/extended", n],
    queryFn: async () => (await api.get(`/journal/wins?n=${n}`)).data,
    staleTime: 60_000,
  });
}

export function usePerformanceHistory() {
  return useQuery<PerformanceHistory>({
    queryKey: ["/performance"],
    queryFn: async () => (await api.get("/performance")).data,
  });
}

export function usePerformanceSummary() {
  return useQuery<PerformanceSummary>({
    queryKey: ["/performance/summary"],
    queryFn: async () => (await api.get("/performance/summary")).data,
  });
}

export interface AICommentary {
  commentary: string;
  generated_at: string | null;
  cached: boolean;
  cache_age_seconds: number;
  throttled?: boolean;
  budget_exhausted?: boolean;
  error?: string;
}

export function useAICommentary() {
  return useQuery<AICommentary>({
    queryKey: ["/ai/commentary"],
    queryFn: async () => (await api.get("/ai/commentary")).data,
    staleTime: 1000 * 60 * 25,
    retry: 1,
  });
}

export function useRefreshCommentary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.get("/ai/commentary?force=true")).data as AICommentary,
    onSuccess: (data) => {
      qc.setQueryData(["/ai/commentary"], data);
    },
  });
}

// --- Vault ---

export interface VaultState {
  initialised: boolean;
  id?: number;
  hwm?: number;
  total_vaulted_usd?: number;
  total_sweeps?: number;
  vault_symbol?: string;
  last_sweep_date?: string | null;
  last_sweep_amount?: number | null;
  message?: string;
}

export function useVault() {
  return useQuery<VaultState>({
    queryKey: ["/vault"],
    queryFn: async () => (await api.get("/vault")).data,
    refetchInterval: 60000,
  });
}

export function useManualSweep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (dry_run: boolean = false) =>
      (await api.post(`/vault/sweep?dry_run=${dry_run}`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/vault"] }),
  });
}

// --- Auditor Agent ---

export interface AuditFinding {
  check: string;
  passed: boolean;
  severity: "INFO" | "WARNING" | "ALERT" | "HOLD";
  message: string;
  details: Record<string, any>;
}

export interface AuditReport {
  run_at: string;
  overall: "ALL_CLEAR" | "REVIEW_RECOMMENDED" | "ACTION_REQUIRED" | "never_run";
  total_checks: number;
  failed_checks: number;
  alert_count: number;
  findings: AuditFinding[];
  recommendations: string[];
  report_path: string;
}

export interface AuditorResponse {
  status: string;
  message?: string;
  report: AuditReport | null;
}

export function useAuditorReport() {
  return useQuery<AuditorResponse>({
    queryKey: ["/auditor/report"],
    queryFn: async () => (await api.get("/auditor/report")).data,
    refetchInterval: 60000,
    retry: 1,
  });
}

export function useTriggerAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/auditor/run")).data,
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ["/auditor/report"] }), 30000);
    },
  });
}

export function useAuditorPerformance() {
  return useQuery<{
    status: string;
    run_at?: string;
    days_analysed?: number;
    alpaca?: { total: number; wins: number; losses: number; win_rate: number | null; avg_pnl: number | null };
    kraken?: { total: number; wins: number; losses: number; win_rate: number | null; avg_pnl: number | null };
    narrative?: string;
  }>({
    queryKey: ["/auditor/performance"],
    queryFn: async () => (await api.get("/auditor/performance")).data,
    refetchInterval: 30000,
    retry: 1,
  });
}

export function useTriggerPerformanceAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (days: number = 10) =>
      (await api.post(`/auditor/performance/run?days=${days}`)).data,
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ["/auditor/performance"] }), 15000);
    },
  });
}

export function useLearningSnapshotInfo() {
  return useQuery<{
    status: string;
    llm_learnings_count?: number;
    has_kraken_params?: boolean;
    kraken_params_n?: number;
    exported_at?: string;
    file_size_bytes?: number;
    message?: string;
  }>({
    queryKey: ["/admin/learning-snapshot"],
    queryFn: async () => (await api.get("/admin/learning-snapshot")).data,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useSyncLearningSnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/admin/learning-snapshot/export")).data,
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ["/admin/learning-snapshot"] }), 4000);
    },
  });
}

// --- Mutations ---

export function useRunAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: { dry_run: boolean; force: boolean }) => {
      return (await api.post("/run", data)).data;
    },
    onSuccess: () => { qc.invalidateQueries(); }
  });
}

export function useTripKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/kill")).data,
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useResetKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: { opening_equity?: number }) => (await api.post("/kill/reset", data)).data,
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useRunPostMortem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/run/postmortem")).data,
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useToggleAutoTrading() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (enabled: boolean) => (await api.post("/auto-trading", { enabled })).data,
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useForceRebalance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/rebalance")).data,
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useCloseAndReallocate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (symbol: string) => (await api.post(`/rebalance/${encodeURIComponent(symbol)}`)).data,
    onSuccess: () => qc.invalidateQueries(),
  });
}

// --- Correlation Matrix ---

export interface CorrelationData {
  tickers: string[];
  matrix: Record<string, Record<string, number>>;
  warnings: Array<{ pair: string[]; correlation: number; risk: string }>;
  held_positions: string[];
  error?: string;
}

export function useCorrelation() {
  return useQuery<CorrelationData>({
    queryKey: ["/correlation"],
    queryFn: async () => (await api.get("/correlation")).data,
    refetchInterval: 120000,
    retry: 1,
  });
}

// --- Sentiment ---

export interface SentimentIndex {
  value: number | null;
  label: string;
  source?: string;
  error?: string;
  components?: Record<string, any>;
}

export interface SentimentData {
  crypto_fear_greed: SentimentIndex;
  market_fear_greed: SentimentIndex;
  cached: boolean;
  cache_age_seconds: number;
}

export function useSentiment() {
  return useQuery<SentimentData>({
    queryKey: ["/sentiment"],
    queryFn: async () => (await api.get("/sentiment")).data,
    refetchInterval: 120000,
    retry: 1,
  });
}

// --- Economic Calendar ---

export interface BlackoutState {
  active: boolean;
  event?: string;
  event_time_et?: string;
  window_minutes?: number;
  message?: string;
}

export interface CalendarEvent {
  name: string;
  date: string;
  time_et: string;
  days_away: number;
}

export interface CalendarData {
  blackout: BlackoutState;
  upcoming_events: CalendarEvent[];
  event_count: number;
}

export function useEconomicCalendar() {
  return useQuery<CalendarData>({
    queryKey: ["/calendar"],
    queryFn: async () => (await api.get("/calendar")).data,
    refetchInterval: 60000,
  });
}

// --- Performance Attribution ---

export interface AttributionBucket {
  count: number;
  total_pnl_pct: number;
  avg_pnl_pct: number;
  win_rate: number;
}

export interface AttributionData {
  total_trades: number;
  closed_trades: number;
  regime_attribution: Record<string, AttributionBucket>;
  asset_class_attribution: Record<string, AttributionBucket>;
  conviction_attribution: Record<string, AttributionBucket>;
  timing_quality: {
    trades_with_fill_data: number;
    avg_slippage_pct: number | null;
    max_slippage_pct: number | null;
    worst_fills: Array<{ ticker: string; slippage_pct: number; date: string }>;
  };
  stop_quality: {
    stop_triggered_count: number;
    stop_avg_pnl_pct: number | null;
    avg_loss_when_stopped: number | null;
  };
  overall: {
    total_pnl_pct: number;
    avg_pnl_pct: number;
    win_rate: number;
    wins: number;
    losses: number;
  };
}

export function useAttribution() {
  return useQuery<AttributionData>({
    queryKey: ["/performance/attribution"],
    queryFn: async () => (await api.get("/performance/attribution")).data,
    refetchInterval: 120000,
  });
}

// --- Risk Metrics ---

export interface RiskMetrics {
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown_pct: number | null;
  calmar_ratio: number | null;
  volatility_annual_pct: number | null;
  annualised_return_pct: number | null;
  data_points: number;
  period_days: number;
  message?: string;
}

export function useRiskMetrics() {
  return useQuery<RiskMetrics>({
    queryKey: ["/performance/risk-metrics"],
    queryFn: async () => (await api.get("/performance/risk-metrics")).data,
    refetchInterval: 120000,
  });
}

// --- Backtest ---

export interface BacktestResult {
  initial_equity: number;
  final_equity: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  equity_curve: Array<{ date: string; equity: number; positions_held: number }>;
  trades: Array<{
    ticker: string;
    entry_date: string;
    exit_date: string;
    entry_price: number;
    exit_price: number;
    pnl_pct: number;
    reason: string;
  }>;
  error?: string;
}

export function useRunBacktest() {
  return useMutation<BacktestResult, Error, number>({
    mutationFn: async (lookback_days: number = 90) =>
      (await api.post(`/backtest?lookback_days=${lookback_days}`)).data,
  });
}

// --- On-Chain Data ---

export interface OnChainData {
  hashrate: { hashrate_gh_s: number } | null;
  mempool: { mempool_tx_count: number; mempool_vsize_bytes: number } | null;
  fee_estimates: {
    fastest_fee_sat_vb: number;
    half_hour_fee_sat_vb: number;
    hour_fee_sat_vb: number;
    economy_fee_sat_vb: number;
  } | null;
  supply: {
    total_btc_mined: number;
    supply_mined_pct: number;
    remaining_btc: number;
  } | null;
  cached: boolean;
  cache_age_seconds: number;
}

export function useOnChainData() {
  return useQuery<OnChainData>({
    queryKey: ["/onchain"],
    queryFn: async () => (await api.get("/onchain")).data,
    refetchInterval: 120000,
    retry: 1,
  });
}

// --- Emergency Controls ---

export interface LiquidateResult {
  status: string;
  positions_closed: Array<{ symbol: string; order_id: string | null }>;
  positions_held: Array<{ symbol: string; reason: string }>;
  errors: Array<{ symbol: string; error: string }>;
  kill_switch: string;
  market_open: boolean;
  pending_liquidation: boolean;
  fill_note: string;
  message: string;
}

export function useLiquidateAll() {
  const qc = useQueryClient();
  return useMutation<LiquidateResult, Error, void>({
    mutationFn: async () => (await api.post("/emergency/liquidate")).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/portfolio"] });
      qc.invalidateQueries({ queryKey: ["/positions/live"] });
      qc.invalidateQueries({ queryKey: ["/status"] });
    },
  });
}

export interface SystemRestartResult {
  status: string;
  pipeline_state: Record<string, any>;
  scheduler_jobs: number;
  kill_switch: Record<string, any>;
  message: string;
}

// ── Kraken Bot (Multi-bot: Davy Jones, Blackbeard, Calypso) ──────────────────

export interface KrakenBotProfile {
  bot_id: string;
  display_name: string;
  strategy_label: string;
  db_id: number;
}

export function useKrakenBots() {
  return useQuery<KrakenBotProfile[]>({
    queryKey: ["/kraken/bots"],
    queryFn: async () => {
      const res = (await api.get("/kraken/bots")).data;
      const botsObj = res?.bots ?? res;
      if (Array.isArray(botsObj)) return botsObj;
      return Object.entries(botsObj).map(([k, v]: [string, any]) => ({ bot_id: k, ...v }));
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  });
}

export interface KrakenPosition {
  symbol: string;
  side: "long" | "short";
  qty: number;
  entry_price: number;
  current_price: number;
  size_usd: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pct: number;
  entry_time: string;
  best_price: number;
  stop_loss_price: number;
  take_profit_price: number;
}

export interface KrakenStatus {
  bot_id?: string;
  bot_name: string;
  strategy_label?: string;
  paper_trading: boolean;
  bot_paused: boolean;
  status: "running" | "paused_circuit_breaker" | "paused_dashboard" | "not_started" | "error";
  last_updated: string | null;
  cycle_count: number;
  total_equity_usd: number;
  deployed_usd: number;
  deployed_pct: number;
  deployable_ceiling_pct: number;
  cash_reserve_pct: number;
  open_positions: KrakenPosition[];
  position_count: number;
  max_positions: number;
  circuit_breaker: { active: boolean; paused_until: string | null };
  recent_trades: Array<{
    symbol: string;
    side: string;
    entry_price: number;
    exit_price: number;
    pnl_pct: number;
    pnl_usd: number;
    reason: string;
    closed_at: string;
  }>;
  paper_summary: {
    starting_balance_usd: number;
    cash_usd: number;
    total_trades: number;
    win_count: number;
    all_time_pnl_usd: number;
  } | null;
  signals: Array<{
    symbol: string;
    rsi: number | null;
    z_score: number | null;
    price: number | null;
    signal_type: string;
    has_position: boolean;
    pnl_pct: number | null;
  }>;
  thinking_text: string;
  error: string | null;
}

export function useKrakenStatus(botId?: string) {
  const params = botId ? `?bot_id=${botId}` : "";
  return useQuery<KrakenStatus>({
    queryKey: ["/kraken/status", botId ?? "default"],
    queryFn: async () => (await api.get(`/kraken/status${params}`)).data,
    refetchInterval: 30_000,
    retry: false,
  });
}

// ── Kraken Fleet Summary (combined equity across all bots) ────────────────────

export interface KrakenFleetSummary {
  total_equity_usd: number;
  total_cash_usd: number;
  total_starting_usd: number;
  total_trades: number;
  total_wins: number;
  total_pnl_usd: number;
  bot_count: number;
  bots: Array<{
    bot_id: string;
    display_name: string;
    equity_usd: number;
    cash_usd: number;
    starting_balance_usd: number;
    trades: number;
    wins: number;
    pnl_usd: number;
  }>;
}

export function useKrakenFleetSummary() {
  return useQuery<KrakenFleetSummary>({
    queryKey: ["/kraken/fleet-summary"],
    queryFn: async () => (await api.get("/kraken/fleet-summary")).data,
    refetchInterval: 30_000,
    retry: 2,
    retryDelay: 3000,
  });
}

// ── Kraken AI Commentary ──────────────────────────────────────────────────────

export interface KrakenCommentary {
  bot_id?: string;
  commentary: string;
  generated_at: string | null;
  cached: boolean;
  cache_age_seconds: number;
  throttled?: boolean;
  budget_exhausted?: boolean;
  error?: string;
}

export function useKrakenCommentary(botId?: string) {
  const params = botId ? `?bot_id=${botId}` : "";
  return useQuery<KrakenCommentary>({
    queryKey: ["/kraken/commentary", botId ?? "default"],
    queryFn: async () => (await api.get(`/kraken/commentary${params}`)).data,
    staleTime: 1000 * 60 * 25,
    retry: 1,
  });
}

export function useRefreshKrakenCommentary(botId?: string) {
  const qc = useQueryClient();
  const params = botId ? `&bot_id=${botId}` : "";
  return useMutation({
    mutationFn: async () =>
      (await api.get(`/kraken/commentary?force=true${params}`)).data as KrakenCommentary,
    onSuccess: (data) => {
      qc.setQueryData(["/kraken/commentary", botId ?? "default"], data);
    },
  });
}

// ── Kraken Performance Metrics ────────────────────────────────────────────────

export interface KrakenSymbolStats {
  trades: number;
  wins: number;
  total_pnl_pct: number;
  total_pnl_usd: number;
  win_rate_pct: number;
}

export interface KrakenPerformance {
  bot_id?: string;
  data_source: string;
  exchange: string;
  has_data: boolean;
  total_trades: number;
  win_count: number;
  loss_count: number;
  win_rate_pct: number | null;
  total_pnl_pct: number | null;
  total_pnl_usd: number | null;
  best_trade_pct: number | null;
  worst_trade_pct: number | null;
  avg_trade_pct: number | null;
  by_symbol: Record<string, KrakenSymbolStats>;
  recent_trades: KrakenStatus["recent_trades"];
  current_equity: number;
  cycle_count: number;
  bot_status: string;
}

export function useKrakenPerformance(botId?: string) {
  const params = botId ? `?bot_id=${botId}` : "";
  return useQuery<KrakenPerformance>({
    queryKey: ["/kraken/performance", botId ?? "default"],
    queryFn: async () => (await api.get(`/kraken/performance${params}`)).data,
    refetchInterval: 60_000,
    retry: 2,
    retryDelay: 3000,
  });
}

// ── Kraken Bot Auto-Trading Toggle ────────────────────────────────────────────

export function useKrakenAutoTrading(botId?: string) {
  const params = botId ? `?bot_id=${botId}` : "";
  return useQuery<{ bot_id?: string; bot_paused: boolean }>({
    queryKey: ["/kraken/auto-trading", botId ?? "default"],
    queryFn: async () => (await api.get(`/kraken/auto-trading${params}`)).data,
    refetchInterval: 15_000,
    retry: false,
  });
}

export function useToggleKrakenAutoTrading(botId?: string) {
  const qc = useQueryClient();
  const params = botId ? `?bot_id=${botId}` : "";
  return useMutation<{ bot_id?: string; bot_paused: boolean }, Error, boolean>({
    mutationFn: async (bot_paused: boolean) =>
      (await api.post(`/kraken/auto-trading${params}`, { bot_paused })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/kraken/auto-trading", botId ?? "default"] });
      qc.invalidateQueries({ queryKey: ["/kraken/status", botId ?? "default"] });
    },
  });
}

export function useSystemRestart() {
  const qc = useQueryClient();
  return useMutation<SystemRestartResult, Error, void>({
    mutationFn: async () => (await api.post("/system/restart")).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/status"] });
      qc.invalidateQueries({ queryKey: ["/health"] });
    },
  });
}

export interface ExportReportResult {
  report: string;
  generated_at: string;
  char_count: number;
  line_count: number;
}

export function useExportReport() {
  return useMutation<ExportReportResult, Error, void>({
    mutationFn: async () => (await api.get("/export/report")).data,
  });
}

export function useEquityCurve(limit = 500) {
  return useQuery<{ count: number; snapshots: EquitySnapshot[] }>({
    queryKey: ["/performance/equity-curve", limit],
    queryFn: async () => (await api.get(`/performance/equity-curve?limit=${limit}`)).data,
    refetchInterval: 60_000,
    retry: false,
    staleTime: 30_000,
  });
}

export interface LearningEntry {
  id: number;
  insight_text: string;
  regime: "Bull" | "Bear" | "Sideways" | "Crypto" | string;
  category: "macro" | "momentum" | "risk" | "position" | "crypto" | string;
  first_seen: string | null;
  last_seen: string | null;
  confirmed_count: number;
  confidence_score: number;
}

export function useLearningJournal(regime?: string, category?: string, limit = 50) {
  const params = new URLSearchParams();
  if (regime) params.set("regime", regime);
  if (category) params.set("category", category);
  params.set("limit", String(limit));
  return useQuery<{ count: number; entries: LearningEntry[] }>({
    queryKey: ["/learning-journal", regime, category, limit],
    queryFn: async () => (await api.get(`/learning-journal?${params.toString()}`)).data,
    refetchInterval: 120_000,
    retry: false,
    staleTime: 60_000,
  });
}

// ── System Degradation Log ─────────────────────────────────────────────────

export interface DegradationEvent {
  id: number;
  ts: string;
  component: string;
  severity: "critical" | "error" | "warning";
  error_type: string;
  message: string;
  detail: string | null;
  resolved_at: string | null;
}

export interface DegradationStats {
  [component: string]: { critical?: number; error?: number; warning?: number };
}

export function useDegradationLog(hours = 48) {
  return useQuery<{ window_hours: number; total: number; stats: DegradationStats; events: DegradationEvent[] }>({
    queryKey: ["/system/degradations", hours],
    queryFn: async () => (await api.get(`/system/degradations?hours=${hours}&limit=100`)).data,
    refetchInterval: 60_000,
    retry: false,
    staleTime: 30_000,
  });
}

export function useDegradationReport(hours = 24) {
  return useMutation({
    mutationFn: async () => {
      const res = await api.get(`/system/degradations/report?hours=${hours}`);
      return res.data.report as string;
    },
  });
}

export function useDegradationHealth() {
  return useQuery<{ window_hours: number; total: number; stats: DegradationStats; events: DegradationEvent[] }>({
    queryKey: ["/system/degradations/health"],
    queryFn: async () => (await api.get("/system/degradations?hours=168&limit=500")).data,
    refetchInterval: 120_000,
    retry: false,
    staleTime: 60_000,
  });
}

export interface OptionsGreeks {
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega?: number | null;
}

export interface OptionsLeg {
  symbol: string;
  strike: number;
  expiry: string;
  dte: number;
  mid_price: number;
  iv: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  bid: number;
  ask: number;
}

export interface OptionsScanResult {
  symbol: string;
  spot_price?: number;
  bollinger_bandwidth: number;
  bollinger_min_6m: number;
  is_squeeze: boolean;
  ivr: number;
  ivr_pass: boolean;
  chain_size?: number;
  signal: boolean;
  status: string;
}

export interface OptionsState {
  status: string;
  paused: boolean;
  last_scan: string | null;
  last_scan_results: OptionsScanResult[];
  capital_fence_pct: number;
  fenced_capital: number;
  total_equity: number;
  paper_mode: boolean;
  paper_equity: number;
  cycle_count: number;
  total_trades: number;
  total_wins: number;
  total_pnl: number;
  error: string | null;
  positions_count: number;
  pending_count: number;
  deployed_capital: number;
  current_value: number;
  unrealized_pnl: number;
}

export interface OptionsPosition {
  id: string;
  symbol: string;
  strategy: string;
  spot_price: number;
  call: OptionsLeg;
  put: OptionsLeg;
  contracts: number;
  premium_per_contract: number;
  total_cost: number;
  ivr: number;
  bollinger_bandwidth: number;
  kelly_fraction: number;
  win_rate: number;
  wl_ratio: number;
  fenced_capital: number;
  available_capital: number;
  scanned_at: string;
  opened_at?: string;
  status: string;
  current_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export interface OptionsPendingTrade extends OptionsPosition {
  status: "pending_approval";
}

export function useOptionsState() {
  return useQuery<OptionsState>({
    queryKey: ["/options/state"],
    queryFn: async () => (await api.get("/options/state")).data,
    refetchInterval: 10_000,
    retry: false,
    staleTime: 5_000,
  });
}

export function useOptionsPositions() {
  return useQuery<{ positions: OptionsPosition[]; count: number }>({
    queryKey: ["/options/positions"],
    queryFn: async () => (await api.get("/options/positions")).data,
    refetchInterval: 10_000,
    retry: false,
    staleTime: 5_000,
  });
}

export function useOptionsPending() {
  return useQuery<{ pending: OptionsPendingTrade[]; count: number }>({
    queryKey: ["/options/pending"],
    queryFn: async () => (await api.get("/options/pending")).data,
    refetchInterval: 10_000,
    retry: false,
    staleTime: 5_000,
  });
}

export function useApproveOptionsTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tradeId: string) => (await api.post("/options/approve", { trade_id: tradeId })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/options/pending"] });
      qc.invalidateQueries({ queryKey: ["/options/positions"] });
      qc.invalidateQueries({ queryKey: ["/options/state"] });
    },
  });
}

export function useRejectOptionsTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tradeId: string) => (await api.post("/options/reject", { trade_id: tradeId })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/options/pending"] });
      qc.invalidateQueries({ queryKey: ["/options/state"] });
    },
  });
}

export function useToggleOptionsBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/options/toggle")).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/options/state"] });
    },
  });
}

export function useOptionsManualScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/options/scan")).data,
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["/options/state"] });
        qc.invalidateQueries({ queryKey: ["/options/pending"] });
      }, 3000);
    },
  });
}

export function useCloseOptionsPosition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tradeId: string) => (await api.post("/options/close", { trade_id: tradeId })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/options/positions"] });
      qc.invalidateQueries({ queryKey: ["/options/state"] });
    },
  });
}

export interface ForexState {
  status: string;
  paused: boolean;
  cycle_count: number;
  usd_bias: string;
  news_blackout: boolean;
  last_scan: string | null;
  last_scan_results: ForexScanResult[];
  paper_mode: boolean;
  paper_equity: number;
  total_equity: number;
  position_count: number;
  total_trades: number;
  total_wins: number;
  total_pnl: number;
  hwm_usd: number;
  vault_total_usd: number;
  error: string | null;
}

export interface ForexScanResult {
  pair: string;
  price?: number;
  atr?: number;
  rsi?: number;
  bias_filter?: string;
  signal?: string | null;
  status?: string;
  error?: string;
}

export interface ForexPosition {
  pair: string;
  direction: string;
  entry_price: number;
  current_price: number;
  sl_price: number;
  tp_price: number;
  units: number;
  size_usd: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pips: number;
  entry_time: string;
}

export interface ForexTrade {
  id: number;
  pair: string;
  direction: string;
  entry_price: number;
  exit_price: number | null;
  sl_price: number;
  tp_price: number;
  units: number;
  llm_thesis: string | null;
  status: string;
  entry_time: string;
  exit_time: string | null;
  pnl_pips: number | null;
  pnl_usd: number | null;
}

export interface ForexVaultSweep {
  sweep_date: string;
  amount: number;
  running_total: number;
  equity_at_sweep: number;
}

export function useForexState() {
  return useQuery<ForexState>({
    queryKey: ["/forex/state"],
    queryFn: async () => (await api.get("/forex/state")).data,
    refetchInterval: 10_000,
    retry: false,
    staleTime: 5_000,
  });
}

export function useForexPositions() {
  return useQuery<{ positions: ForexPosition[]; count: number }>({
    queryKey: ["/forex/positions"],
    queryFn: async () => (await api.get("/forex/positions")).data,
    refetchInterval: 10_000,
    retry: false,
    staleTime: 5_000,
  });
}

export function useForexTrades() {
  return useQuery<{ trades: ForexTrade[]; count: number }>({
    queryKey: ["/forex/trades"],
    queryFn: async () => (await api.get("/forex/trades")).data,
    refetchInterval: 15_000,
    retry: false,
    staleTime: 10_000,
  });
}

export function useForexVault() {
  return useQuery<{ vault_total_usd: number; sweeps: ForexVaultSweep[] }>({
    queryKey: ["/forex/vault"],
    queryFn: async () => (await api.get("/forex/vault")).data,
    refetchInterval: 30_000,
    retry: false,
    staleTime: 20_000,
  });
}

export function useToggleForexBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/forex/toggle")).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/forex/state"] });
    },
  });
}

export function useForexManualScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/forex/scan")).data,
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["/forex/state"] });
        qc.invalidateQueries({ queryKey: ["/forex/positions"] });
        qc.invalidateQueries({ queryKey: ["/forex/trades"] });
      }, 5000);
    },
  });
}
