import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { isNYSEOpen } from "@/lib/dashboard-shared";

const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";
const fleetApi = axios.create({ baseURL: BASE });

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
    pnl_24h: number;
    pnl_24h_pct: number;
    positions: number;
    win_rate: number | null;
  };
  generated_at?: string;
};

export interface LivePos {
  symbol: string;
  qty: number;
  side: string;
  avg_entry_price: number;
  current_price?: number;
  unrealized_pl: number;
  unrealized_plpc: number;
}

export interface MarketState { regime?: string }

export interface StatusSummary {
  kill_switch?: { tripped: boolean };
  kill_switch_tripped?: boolean;
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

export function fmtEq(v: number) {
  return `$${Math.round(v).toLocaleString()}`;
}
export function fmtPct(v: number) {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}
export function fmtDollar(v: number) {
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

  const { data: livePosResp } = useQuery<{ positions: LivePos[] }>({
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

  const allPos   = livePosResp?.positions ?? [];
  const spyPos   = allPos.filter((p) => ["SPY", "QQQ"].includes(p.symbol));
  const otherPos = allPos.filter((p) => !["SPY", "QQQ"].includes(p.symbol));
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
    spyPos,
    otherPos,
    wfMap,
    regime:      market?.regime,
    killTripped: summary?.kill_switch?.tripped ?? summary?.kill_switch_tripped,
    lastCycle:   fleet?.generated_at,
  };
}
