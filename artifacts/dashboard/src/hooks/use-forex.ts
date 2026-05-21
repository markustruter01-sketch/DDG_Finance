import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

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
  starting_capital?: number;
  circuit_breaker_active?: boolean;
  circuit_breaker_reason?: string | null;
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
  original_sl?: number;
  trailing_sl?: number;
  highest_price?: number | null;
  lowest_price?: number | null;
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
    refetchInterval: useVisibleInterval(10_000),
    retry: false,
    staleTime: 5_000,
  });
}

export function useForexPositions() {
  return useQuery<{ positions: ForexPosition[]; count: number }>({
    queryKey: ["/forex/positions"],
    queryFn: async () => (await api.get("/forex/positions")).data,
    refetchInterval: useVisibleInterval(10_000),
    retry: false,
    staleTime: 5_000,
  });
}

export function useForexTrades() {
  return useQuery<{ trades: ForexTrade[]; count: number }>({
    queryKey: ["/forex/trades"],
    queryFn: async () => (await api.get("/forex/trades")).data,
    refetchInterval: useVisibleInterval(15_000),
    retry: false,
    staleTime: 10_000,
  });
}

export function useForexVault() {
  return useQuery<{ vault_total_usd: number; sweeps: ForexVaultSweep[] }>({
    queryKey: ["/forex/vault"],
    queryFn: async () => (await api.get("/forex/vault")).data,
    refetchInterval: useVisibleInterval(10_000),
    retry: false,
    staleTime: 5_000,
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
