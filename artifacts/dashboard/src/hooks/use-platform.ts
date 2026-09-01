import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

export interface SystemHealth {
  status: string;
  auth_mode: "enforced" | "bypass";
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
  emergency_regime?: {
    active: boolean;
    triggered_at: string | null;
    spy_change_pct: number | null;
    threshold_pct: number;
    recovery_pct: number;
  };
  alpaca_maintenance?: boolean;
}

export interface StatusSummary {
  system_health: {
    system_status: "online" | "degraded" | "offline";
    scheduler_job_count: number;
    last_run_status: string;
    error_count: number;
    run_count: number;
  };
  portfolio_totals: { equity: number; cash: number; buying_power: number; initial_capital?: number };
  position_count: number;
  bot_statuses: Record<string, { display_name: string; status: string }>;
  alert_queue_size: number;
  market_open: boolean;
  next_market_open: string | null;
  kill_switch_tripped: boolean;
  alpaca_maintenance: boolean;
  trading_mode: string;
  afterhours_crypto?: {
    active: boolean;
    position_count: number;
    unrealized_pnl: number;
    positions: { symbol: string; market_value: number; unrealized_pl: number; qty: number }[];
  };
  groq: {
    pct_used: number;
    tokens_used_today: number;
    token_budget_total: number;
    budget_exhausted: boolean;
    using_fallback: boolean;
    regime?: string;
    cache_age_min?: number;
  } | null;
  emergency_regime: {
    active: boolean;
    spy_change_pct?: number;
  } | null;
  scheduler_jobs: { id: string; name: string; next_fire_utc: string }[];
  auto_trading: boolean;
}

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

export interface SystemRestartResult {
  status: string;
  pipeline_state: Record<string, any>;
  scheduler_jobs: number;
  kill_switch: Record<string, any>;
  message: string;
}

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

export function useStatusSummary() {
  return useQuery<StatusSummary>({
    queryKey: ["/status/summary"],
    queryFn: async () => (await api.get("/status/summary")).data,
    refetchInterval: useVisibleInterval(8_000),
    retry: 1,
    staleTime: 5_000,
  });
}

export function useSystemHealth() {
  return useQuery<SystemHealth>({
    queryKey: ["/health"],
    queryFn: async () => (await api.get("/health")).data,
    refetchInterval: useVisibleInterval(30000),
    staleTime: 25_000,
    retry: 1,
  });
}

export function usePlatformStatus() {
  return useQuery<PlatformStatus>({
    queryKey: ["/status"],
    queryFn: async () => (await api.get("/status")).data,
    refetchInterval: useVisibleInterval(30000),
    staleTime: 25_000,
  });
}

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

export function useEconomicCalendar() {
  return useQuery<CalendarData>({
    queryKey: ["/calendar"],
    queryFn: async () => (await api.get("/calendar")).data,
    refetchInterval: useVisibleInterval(60000),
  });
}

export function useDegradationLog(hours = 48) {
  return useQuery<{ window_hours: number; total: number; stats: DegradationStats; events: DegradationEvent[] }>({
    queryKey: ["/system/degradations", hours],
    queryFn: async () => (await api.get(`/system/degradations?hours=${hours}&limit=100`)).data,
    refetchInterval: useVisibleInterval(60_000),
    retry: false,
    staleTime: 30_000,
  });
}

export function useDegradationReport(hours = 24) {
  return useMutation({
    mutationFn: async () => {
      const res = await api.get(`/system/degradations/report?hours=${hours}`, { timeout: 30000 });
      return res.data.report as string;
    },
  });
}

export function useDegradationHealth() {
  return useQuery<{ window_hours: number; total: number; stats: DegradationStats; events: DegradationEvent[] }>({
    queryKey: ["/system/degradations/health"],
    queryFn: async () => (await api.get("/system/degradations?hours=168&limit=500")).data,
    refetchInterval: useVisibleInterval(120_000),
    retry: false,
    staleTime: 60_000,
  });
}

export function useOnChainData() {
  return useQuery<OnChainData>({
    queryKey: ["/onchain"],
    queryFn: async () => (await api.get("/onchain")).data,
    refetchInterval: useVisibleInterval(120000),
    retry: 1,
  });
}

export function useFleetHaltStatus() {
  return useQuery({
    queryKey: ["fleet-halt-status"],
    queryFn: () => api.get("/fleet/halt/status").then(r => r.data),
    refetchInterval: 15_000,
  });
}

export function useFleetHalt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) =>
      api.post(`/fleet/halt?reason=${encodeURIComponent(reason)}`).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fleet-halt-status"] }),
  });
}

export function useFleetResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/fleet/resume").then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fleet-halt-status"] }),
  });
}
