import { useQuery } from "@tanstack/react-query";
import { isNYSEOpen } from "@/lib/dashboard-shared";
import { api as fleetApi } from "@/hooks/use-trading-client";

// ── Canonical types ───────────────────────────────────────────────────────────

export interface BotSlice {
  equity: number;
  starting: number;
  pnl: number;
  pnl_pct: number;
  positions: number;
  stale: boolean;
  paused: boolean;
  win_rate: number | null;
  last_updated: string | null;
}

export type FleetEquityResp = {
  oracle?: BotSlice;
  spy_qqq_trend?: BotSlice;
  jerome_macro?: BotSlice;
  /** Retired May 2026 — kept in type for graceful fallback rendering only; always stale */
  buck_futures?: BotSlice;
  fleet_total?: {
    equity: number;
    pnl: number;
    pnl_pct: number;
    pnl_24h: number | null;
    pnl_24h_pct: number | null;
    positions: number;
    win_rate: number | null;
  };
  generated_at?: string;
};

export interface LivePos {
  bot_id?: string;
  symbol: string;
  qty: number;
  side: string;
  avg_entry_price: number;
  market_value?: number;
  current_price?: number;
  unrealized_pl: number;
  unrealized_plpc: number;
}

export interface LivePositionsResponse {
  positions: LivePos[];
  count: number;
  positions_by_bot: Partial<Record<"oracle" | "spy_qqq_trend" | "jerome_macro", {
    positions: LivePos[];
    count: number;
    strategy_count: number;
  }>>;
}

export interface MarketState { regime?: string }

export interface StatusSummary {
  kill_switch?: { tripped: boolean };
  kill_switch_tripped?: boolean;
  kill_switch_armed?: boolean;
}

export interface EntryWindow {
  label: string;
  timezone: "UTC";
  mode: "fixed_window" | "runner_interval" | "event_driven";
  is_open: boolean;
  entry_interval_seconds?: number;
  window_start_utc: string | null;
  window_end_utc: string | null;
  next_window_start_utc: string | null;
  source: string;
}

export interface EntryWindowsResponse {
  server_time_utc: string;
  windows: Partial<Record<"oracle" | "spy_qqq_trend" | "jerome_macro", EntryWindow>>;
}

export type RunnerVerdict = "ALIVE" | "STALE" | "ABSENT";

export interface RunnerStatusResponse {
  verdict: RunnerVerdict;
  age_seconds: number | null;
  threshold_seconds: number;
  instance_token: string | null;
  pid: number | null;
  environment: string | null;
  execution_mode: string | null;
  started_at: string | null;
  last_beat_at: string | null;
  loop_count: number | null;
  bots_registered: number | null;
  status: string | null;
  row: Record<string, unknown> | null;
}

// ── Status logic (market-hours aware, Rule 27-safe) ──────────────────────────

export type BotStatus = "LIVE" | "MKT_CLOSED" | "DOWN" | "IDLE";

/**
 * Derive bot status from fleet/equity data.
 * - Market closed → MKT_CLOSED (neutral) for all bots, regardless of staleness
 * - Market open + stale → DOWN
 * - Market open + ADX-paused (isADXBot=true) → IDLE-BY-DESIGN
 * - Otherwise → LIVE
 */
export function getBotStatus(
  bot: BotSlice | undefined,
  mktOpen: boolean,
  isADXBot = false,
): BotStatus {
  if (!bot) return "MKT_CLOSED";
  if (!mktOpen) return "MKT_CLOSED";
  if (bot.paused && isADXBot) return "IDLE";
  if (bot.stale) return "DOWN";
  return "LIVE";
}

export const STATUS_COLORS: Record<BotStatus, string> = {
  LIVE:       "#22c55e",
  MKT_CLOSED: "#64748b",
  DOWN:       "#ef4444",
  IDLE:       "#eab308",
};

export const STATUS_LABELS: Record<BotStatus, string> = {
  LIVE:       "LIVE",
  MKT_CLOSED: "MKT CLOSED",
  DOWN:       "DOWN",
  IDLE:       "IDLE-BY-DESIGN",
};

// ── Formatters (no arithmetic — just display helpers) ────────────────────────

export function fmtEq(v: number | null | undefined) {
  return v == null ? "—" : `$${Math.round(v).toLocaleString()}`;
}
export function fmtPct(v: number | null | undefined) {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}
export function fmtDollar(v: number | null | undefined) {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const s = v >= 0 ? "+" : "-";
  if (abs >= 1_000_000) return `${s}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)     return `${s}$${(abs / 1_000).toFixed(1)}k`;
  return `${s}$${abs.toFixed(0)}`;
}

// ── Shared data hook ──────────────────────────────────────────────────────────

export function useFleetData() {
  const mktOpen = isNYSEOpen();

  const { data: fleet } = useQuery<FleetEquityResp>({
    queryKey: ["fleet-equity"],
    queryFn: () => fleetApi.get("/fleet/equity").then((r) => r.data),
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
  });

  const { data: market } = useQuery<MarketState>({
    queryKey: ["market-state"],
    queryFn: () => fleetApi.get("/market-state").then((r) => r.data),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });

  const { data: summary } = useQuery<StatusSummary>({
    queryKey: ["status-summary"],
    queryFn: () => fleetApi.get("/status/summary").then((r) => r.data),
    refetchInterval: 10_000,
    staleTime: 8_000,
    retry: 1,
  });

  const { data: livePosResp } = useQuery<LivePositionsResponse>({
    queryKey: ["positions-live"],
    queryFn: () => fleetApi.get("/positions/live").then((r) => r.data),
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
  });

  const { data: reportData } = useQuery<{
    walk_forward_status?: Array<{ bot_id: string; wf_status: string | null }>;
  }>({
    queryKey: ["claude-report-wf"],
    queryFn: () => fleetApi.get("/claude-report").then((r) => r.data),
    refetchInterval: 5 * 60_000,
    staleTime: 4 * 60_000,
    retry: false,
  });

  const { data: entryWindowData } = useQuery<EntryWindowsResponse>({
    queryKey: ["fleet-entry-windows"],
    queryFn: () => fleetApi.get("/fleet/entry-windows").then((r) => r.data),
    refetchInterval: 60_000,
    staleTime: 45_000,
    retry: 1,
  });

  const runnerStatusQuery = useQuery<RunnerStatusResponse>({
    queryKey: ["runner-status"],
    queryFn: () => fleetApi.get("/runner/status").then((r) => r.data),
    refetchInterval: 5_000,
    staleTime: 2_000,
    retry: false,
  });

  const allPos   = livePosResp?.positions ?? [];
  const positionsByBot = livePosResp?.positions_by_bot;
  const wfMap    = new Map(
    (reportData?.walk_forward_status ?? []).map((r) => [r.bot_id, r.wf_status]),
  );

  return {
    fleet,
    mktOpen,
    oracle:  fleet?.oracle,
    spy:     fleet?.spy_qqq_trend,
    jerome:  fleet?.jerome_macro,
    total:   fleet?.fleet_total,
    allPos,
    positionsByBot,
    wfMap,
    regime:      market?.regime,
    killTripped: summary == null
      ? null
      : summary.kill_switch?.tripped ?? summary.kill_switch_tripped ?? null,
    killSwitchArmed: summary?.kill_switch_armed ?? null,
    lastCycle:   fleet?.generated_at,
    entryWindows: entryWindowData?.windows,
    runnerStatus: runnerStatusQuery.data,
    runnerStatusError: runnerStatusQuery.isError,
  };
}
