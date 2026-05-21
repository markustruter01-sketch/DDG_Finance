import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./use-trading-client";

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
  starting_capital?: number;
  circuit_breaker_active?: boolean;
  circuit_breaker_reason?: string | null;
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
  max_loss_pct?: number;
  profit_target_pct?: number;
  dte_remaining?: number | null;
}

export interface OptionsPendingTrade extends OptionsPosition {
  status: "pending_approval";
}

export function useOptionsState() {
  return useQuery<OptionsState>({
    queryKey: ["/options/state"],
    queryFn: async () => ({ status: "retired", active: false, positions: [], pending: [] } as unknown as OptionsState),
    enabled: false,
    retry: false,
    staleTime: Infinity,
  });
}

export function useOptionsPositions() {
  return useQuery<{ positions: OptionsPosition[]; count: number }>({
    queryKey: ["/options/positions"],
    queryFn: async () => ({ positions: [], count: 0 }),
    enabled: false,
    retry: false,
    staleTime: Infinity,
  });
}

export function useOptionsPending() {
  return useQuery<{ pending: OptionsPendingTrade[]; count: number }>({
    queryKey: ["/options/pending"],
    queryFn: async () => ({ pending: [], count: 0 }),
    enabled: false,
    retry: false,
    staleTime: Infinity,
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
