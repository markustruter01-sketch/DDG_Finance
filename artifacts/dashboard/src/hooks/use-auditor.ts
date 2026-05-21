import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

export interface AICommentary {
  commentary: string;
  generated_at: string | null;
  cached: boolean;
  cache_age_seconds: number;
  throttled?: boolean;
  budget_exhausted?: boolean;
  error?: string;
}

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

export interface PairLearningSymbol {
  bot_id: string;
  symbol: string;
  hurst: number | null;
  adf_pvalue: number | null;
  status: "active" | "paused";
  pause_until: string | null;
  pause_reason: string | null;
  updated_at: string | null;
  wins: number;
  losses: number;
  total_trades: number;
  win_rate: number | null;
  total_pnl: number;
  last_trade_at: string | null;
}

export interface FleetSymbol {
  symbol: string;
  avg_hurst: number | null;
  avg_adf_pvalue: number | null;
  total_wins: number;
  total_losses: number;
  total_pnl: number;
  any_paused: boolean;
  pause_reason: string | null;
  bot_count: number;
}

export interface AdaptiveParam {
  bot_id: string;
  params: Record<string, number>;
  metrics: Record<string, number>;
  reasons: Record<string, string>;
  adapted_at: string | null;
  lookback_n: number;
}

export interface RecentTrade {
  bot_id: string;
  symbol: string;
  side: string;
  pnl_usd: number;
  closed_at: string | null;
}

export interface PairLearningData {
  symbols: PairLearningSymbol[];
  fleet_symbols: FleetSymbol[];
  adaptive_params: AdaptiveParam[];
  recent_trades: RecentTrade[];
  total_symbols: number;
  paused_count: number;
  active_count: number;
  bot_slot_total: number;
  bot_slot_paused: number;
  bot_slot_active: number;
  total_trade_count: number;
  kraken_trade_count: number;
  alpaca_trade_count: number;
}

export interface MathAuditDetail {
  audit_timestamp: string;
  bot_id: string;
  formula_name: string;
  bot_output: number;
  auditor_output: number;
  discrepancy_pct: number;
  status: "PASS" | "WARN" | "FAIL";
  severity: "INFO" | "WARNING" | "CRITICAL";
  notes: string;
  audit_mode: string;
}

export interface MathAuditSummary {
  status: string;
  pass: number;
  warn: number;
  fail: number;
  last_audit_ts: string;
  total_logged: number;
  details: MathAuditDetail[];
}

export interface MathAuditRecentRow {
  audit_timestamp: string;
  bot_id: string;
  formula_name: string;
  bot_output: number;
  auditor_output: number;
  discrepancy_pct: number;
  status: "PASS" | "WARN" | "FAIL";
  severity: "INFO" | "WARNING" | "CRITICAL";
  notes: string;
  audit_mode: string;
}

export interface AuditIssue {
  file: string;
  function: string;
  issue: string;
  recommendation: string;
}

export interface AuditParameterConcern {
  file: string;
  issue: string;
  recommendation: string;
}

export interface ClaudeCodeIssue {
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  file: string;
  function: string;
  issue: string;
  recommendation: string;
}

export interface ClaudeBotAssessment {
  bot_id: string;
  verdict: "GOOD" | "WARNING" | "CRITICAL";
  win_rate_assessment: string;
  pnl_assessment: string;
  parameter_assessment: string;
  flags: string[];
}

export interface ClaudeActionItem {
  priority: number;
  category: string;
  action: string;
  impact: string;
}

export interface ClaudeParamRecommendation {
  bot_id: string;
  parameter: string;
  current_value: string;
  recommended_value: string;
  reasoning: string;
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

export function useAuditorReport() {
  return useQuery<AuditorResponse>({
    queryKey: ["/auditor/report"],
    queryFn: async () => (await api.get("/auditor/report")).data,
    refetchInterval: useVisibleInterval(60000),
    staleTime: 55_000,
    retry: 1,
  });
}

export function useAdminLearningSnapshot() {
  return useQuery<{ exported_at: string | null; llm_learnings_count: number }>({
    queryKey: ["/admin/learning-snapshot"],
    queryFn: async () => (await api.get("/admin/learning-snapshot")).data,
    refetchInterval: useVisibleInterval(300_000),
    retry: false,
    staleTime: 120_000,
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
    refetchInterval: useVisibleInterval(30000),
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
    refetchInterval: useVisibleInterval(60_000),
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

export function useLearningJournal(regime?: string, category?: string, limit = 50) {
  const params = new URLSearchParams();
  if (regime) params.set("regime", regime);
  if (category) params.set("category", category);
  params.set("limit", String(limit));
  return useQuery<{ count: number; entries: LearningEntry[] }>({
    queryKey: ["/learning-journal", regime, category, limit],
    queryFn: async () => (await api.get(`/learning-journal?${params.toString()}`)).data,
    refetchInterval: useVisibleInterval(120_000),
    retry: false,
    staleTime: 60_000,
  });
}

export function usePairLearning() {
  return useQuery<PairLearningData>({
    queryKey: ["/pair-learning"],
    queryFn: async () => (await api.get("/pair-learning")).data,
    refetchInterval: useVisibleInterval(60_000),
    retry: false,
    staleTime: 30_000,
  });
}

export function useMathAuditSummary(hours: number = 24) {
  return useQuery<MathAuditSummary>({
    queryKey: ["/admin/math-audit/summary", hours],
    queryFn: async () => (await api.get(`/admin/math-audit/summary?hours=${hours}`)).data,
    refetchInterval: useVisibleInterval(60_000),
    retry: false,
    staleTime: 30_000,
  });
}

export function useMathAuditRecent(limit: number = 30, statusFilter: "ALL" | "FAIL" | "WARN" | "PASS" = "ALL") {
  return useQuery<{ status: string; rows: MathAuditRecentRow[]; count: number }>({
    queryKey: ["/admin/math-audit/recent", limit, statusFilter],
    queryFn: async () =>
      (await api.get(`/admin/math-audit/recent?limit=${limit}&status_filter=${statusFilter}`)).data,
    refetchInterval: useVisibleInterval(30_000),
    retry: false,
    staleTime: 15_000,
  });
}
