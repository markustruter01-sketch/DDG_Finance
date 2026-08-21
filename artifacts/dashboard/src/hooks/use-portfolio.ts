import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

export interface EquitySnapshot {
  id: number;
  ts: string;
  alpaca_equity: number;
  kraken_equity: number;
  options_equity: number;
  forex_equity: number;
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
  bot_id?: string;
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

export interface VaultState {
  initialised: boolean;
  id?: number;
  hwm?: number;
  total_vaulted_usd?: number;
  total_sweeps?: number;
  vault_symbol?: string;
  last_sweep_date?: string | null;
  last_sweep_amount?: number | null;
  vaulted_24h?: number;
  message?: string;
}

export interface VaultSnapshot {
  date: string;
  daily_vaulted: number;
  cumulative_vaulted: number;
}

export interface VaultHistory {
  count: number;
  snapshots: VaultSnapshot[];
  total_vaulted_usd: number;
}

export interface BotEquity {
  equity: number;
  pnl: number;
  pnl_pct: number;
  starting: number;
  cash?: number;
  positions: number;
  source: string;
  last_updated?: string | null;
  stale?: boolean;
  paused?: boolean;
  win_rate?: number | null;
  pnl_24h?: number | null;
  pnl_24h_pct?: number | null;
  heartbeat_mins_ago?: number;
}

export interface FleetEquityData {
  oracle: BotEquity;
  spy_qqq_trend: BotEquity;
  jerome_macro: BotEquity;
  buck_futures?: BotEquity;
  fleet_total: BotEquity;
  generated_at: string;
  errors: string[];
}

export interface BotRegistryEntry {
  id: string;
  display_name: string;
  short_name: string;
  icon: string;
  color: string;
  strategy_label: string;
  asset_class: string;
  exchange: string;
  starting_capital: number;
  db_id: number | null;
  status: "active" | "paused" | "retired";
  display_order: number;
  legacy_aliases: string[];
  trading_hours: string;
  cycle_minutes: number;
}

export interface BotRegistryResponse {
  bots: BotRegistryEntry[];
  fleet_starting_capital: number;
  fleet_bot_count: number;
}

export function usePortfolio() {
  return useQuery<PortfolioData>({
    queryKey: ["/portfolio"],
    queryFn: async () => (await api.get("/portfolio")).data,
    refetchInterval: useVisibleInterval(30000),
    staleTime: 25_000,
  });
}

export function useLivePositions() {
  return useQuery<LivePositionsData>({
    queryKey: ["/positions/live"],
    queryFn: async () => (await api.get("/positions/live")).data,
    refetchInterval: useVisibleInterval(15_000),
    staleTime: 12_000,
  });
}

export function useLatestAllocation() {
  return useQuery<AllocationPlan>({
    queryKey: ["/allocation/latest"],
    queryFn: async () => (await api.get("/allocation/latest")).data,
    staleTime: 60_000,
  });
}

export function useVault() {
  return useQuery<VaultState>({
    queryKey: ["/vault"],
    queryFn: async () => (await api.get("/vault")).data,
    refetchInterval: useVisibleInterval(15_000),
    staleTime: 12_000,
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

export function useVaultHistory(days = 90) {
  return useQuery<VaultHistory>({
    queryKey: ["/vault/history", days],
    queryFn: async () => (await api.get(`/vault/history?days=${days}`)).data,
    refetchInterval: useVisibleInterval(120_000),
    staleTime: 90_000,
    retry: 1,
  });
}

export function useFleetEquity() {
  return useQuery<FleetEquityData>({
    queryKey: ["fleet-equity"],
    queryFn: async () => (await api.get("/fleet/equity")).data,
    refetchInterval: useVisibleInterval(15_000),
    staleTime: 10_000,
    retry: 1,
  });
}

export function useBotRegistry() {
  return useQuery<BotRegistryResponse>({
    queryKey: ["bot-registry"],
    queryFn: async () => {
      const res = await api.get("/bot-registry");
      return res.data;
    },
    staleTime: 60_000,
  });
}

// ── Fleet equity history ───────────────────────────────────────────────────────

export interface FleetHistoryPoint { date: string; total_equity: number }
export interface FleetHistoryResponse { history: FleetHistoryPoint[] }

export function useFleetHistory() {
  return useQuery<FleetHistoryResponse>({
    queryKey: ["fleet-equity-history"],
    queryFn: async () => (await api.get("/fleet/equity-history")).data,
    staleTime: 300_000,
    refetchInterval: useVisibleInterval(600_000),
    retry: 1,
  });
}

