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
  };
}

export interface PortfolioData {
  account: { equity: number; cash: number; buying_power: number; trading_blocked: boolean };
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

export interface LivePosition {
  symbol: string;
  qty: number;
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
}

export interface LivePositionsData {
  count: number;
  positions: LivePosition[];
}

export interface AllocationPlan {
  status: string;
  run_utc: string;
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
