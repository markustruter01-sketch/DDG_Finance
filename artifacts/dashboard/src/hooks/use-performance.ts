import { useQuery } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";
import type { EquitySnapshot } from "./use-portfolio";

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

export interface CorrelationData {
  tickers: string[];
  matrix: Record<string, Record<string, number>>;
  warnings: Array<{ pair: string[]; correlation: number; risk: string }>;
  held_positions: string[];
  error?: string;
}

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

export interface AIIntervention {
  id: number;
  ts: string;
  source: string;
  overall_verdict: string;
  bot_verdicts: Record<string, string>;
  param_changes: Array<{
    bot_id: string;
    reasoning: string;
    ZSCORE_ENTRY?: number;
    ZSCORE_EXIT?: number;
    STOP_LOSS_PCT?: number;
    TRAIL_PCT?: number;
    MIN_NET_PROFIT_PCT?: number;
  }>;
  vetoed_tickers: string[];
  critique_summary: string;
  critique_flags: string[];
  conditions: Array<{ type: string; value?: number; ticker?: string }>;
  equity_at_time: number | null;
  performance_before: { trades: number; wins: number; win_rate: number | null; net_pnl: number } | null;
  performance_after: { trades: number; wins: number; win_rate: number | null; net_pnl: number } | null;
  impact?: "helped" | "hurt" | "neutral";
}

export interface AIImpactTimeline {
  equity_curve: Array<{
    ts: string;
    alpaca_equity: number;
    kraken_equity: number;
    options_equity: number;
    forex_equity: number;
    total_equity: number;
    regime: string | null;
  }>;
  interventions: AIIntervention[];
  summary: {
    total_interventions: number;
    helped: number;
    hurt: number;
    neutral: number;
  };
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

export function useCorrelation() {
  return useQuery<CorrelationData>({
    queryKey: ["/correlation"],
    queryFn: async () => (await api.get("/correlation")).data,
    refetchInterval: useVisibleInterval(120000),
    retry: 1,
  });
}

export function useSentiment() {
  return useQuery<SentimentData>({
    queryKey: ["/sentiment"],
    queryFn: async () => (await api.get("/sentiment")).data,
    refetchInterval: useVisibleInterval(120000),
    retry: 1,
  });
}

export function useAttribution() {
  return useQuery<AttributionData>({
    queryKey: ["/performance/attribution"],
    queryFn: async () => (await api.get("/performance/attribution")).data,
    refetchInterval: useVisibleInterval(120000),
  });
}

export function useRiskMetrics() {
  return useQuery<RiskMetrics>({
    queryKey: ["/performance/risk-metrics"],
    queryFn: async () => (await api.get("/performance/risk-metrics")).data,
    refetchInterval: useVisibleInterval(30_000),
    staleTime: 25_000,
  });
}

export function useEquityCurve(limit = 500) {
  return useQuery<{ count: number; source: string; snapshots: EquitySnapshot[] }>({
    queryKey: ["/performance/equity-curve", limit],
    queryFn: async () => {
      const res = (await api.get(`/performance/equity-curve?limit=${limit}`)).data;
      return { count: res.count, source: res.source, snapshots: res.curve ?? [] };
    },
    refetchInterval: useVisibleInterval(60_000),
    retry: false,
    staleTime: 30_000,
  });
}

export function useAIImpactTimeline() {
  return useQuery<AIImpactTimeline>({
    queryKey: ["/ai-impact/timeline"],
    queryFn: async () => (await api.get("/ai-impact/timeline")).data,
    refetchInterval: useVisibleInterval(120_000),
    retry: 1,
    staleTime: 60_000,
  });
}

export function useWeeklyReview() {
  return useQuery({
    queryKey: ["weekly-review"],
    queryFn: () => api.get("/fleet/weekly-review").then(r => r.data),
    refetchInterval: 5 * 60 * 1000,
    staleTime: 60_000,
  });
}

export function useReviewFlags() {
  return useQuery({
    queryKey: ["review-flags"],
    queryFn: () => api.get("/review-flags").then(r => r.data),
    refetchInterval: 10 * 60 * 1000,
  });
}
