import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

export interface KrakenBotProfile {
  bot_id: string;
  display_name: string;
  strategy_label: string;
  db_id: number;
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
  status: "running" | "paused_circuit_breaker" | "paused_loss_streak" | "paused_dashboard" | "not_started" | "error";
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
  circuit_breaker: {
    active: boolean;
    paused_until: string | null;
    flash_crash?: { active: boolean; paused_until: string | null };
    loss_streak?: {
      consecutive_losses: number;
      limit: number;
      active: boolean;
      paused_until: string | null;
      cooldown_hours: number;
    };
  };
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
    vpin?: number | null;
    ofi?: number | null;
    conviction?: number | null;
  }>;
  thinking_text: string;
  error: string | null;
}

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
  trades_today?: number;
}

export interface ExportReportResult {
  report: string;
  char_count: number;
  line_count: number;
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
    refetchInterval: useVisibleInterval(60_000),
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  });
}

export function useKrakenStatus(botId?: string) {
  const params = botId ? `?bot_id=${botId}` : "";
  return useQuery<KrakenStatus>({
    queryKey: ["/kraken/status", botId ?? "default"],
    queryFn: async () => (await api.get(`/kraken/status${params}`)).data,
    refetchInterval: useVisibleInterval(8_000),
    retry: false,
  });
}

export function useKrakenFleetSummary() {
  return useQuery<KrakenFleetSummary>({
    queryKey: ["/kraken/fleet-summary"],
    queryFn: async () => (await api.get("/kraken/fleet-summary")).data,
    refetchInterval: useVisibleInterval(8_000),
    retry: 2,
    retryDelay: 3000,
  });
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

export function useKrakenPerformance(botId?: string) {
  const params = botId ? `?bot_id=${botId}` : "";
  return useQuery<KrakenPerformance>({
    queryKey: ["/kraken/performance", botId ?? "default"],
    queryFn: async () => (await api.get(`/kraken/performance${params}`)).data,
    refetchInterval: useVisibleInterval(10_000),
    retry: 2,
    retryDelay: 3000,
  });
}

export function useKrakenAutoTrading(botId?: string) {
  const params = botId ? `?bot_id=${botId}` : "";
  return useQuery<{ bot_id?: string; bot_paused: boolean }>({
    queryKey: ["/kraken/auto-trading", botId ?? "default"],
    queryFn: async () => (await api.get(`/kraken/auto-trading${params}`)).data,
    refetchInterval: useVisibleInterval(15_000),
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

export function useForceResume(botId: string) {
  const qc = useQueryClient();
  return useMutation<{ bot_id: string; status: string; message: string }, Error, void>({
    mutationFn: async () => (await api.post(`/kraken/${botId}/force-resume`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/kraken/status", botId] });
      qc.invalidateQueries({ queryKey: ["/kraken/auto-trading", botId] });
    },
  });
}

export function useExportReport() {
  return useMutation<ExportReportResult, Error, void>({
    mutationFn: async () => {
      const res = await api.get("/claude-report.txt?days=1", { responseType: "text" });
      const text = typeof res.data === "string" ? res.data : String(res.data);
      const lineCount = parseInt(res.headers["x-report-lines"] || "0", 10) || text.split("\n").length;
      const charCount = parseInt(res.headers["x-report-chars"] || "0", 10) || text.length;
      return { report: text, char_count: charCount, line_count: lineCount };
    },
  });
}
