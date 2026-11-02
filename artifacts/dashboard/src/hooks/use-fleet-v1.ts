/** FLEET-V1 reads (trading-platform/routes/fleet_v1.py). Every number is a
 *  server value; the browser only formats it. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, useVisibleInterval } from "@/hooks/use-trading-client";

export type DrawdownMode = "normal" | "soft" | "halt";

export interface FleetAccount {
  bot_id: string;
  registration: string;
  role: string;
  core_weight: number;
  xasset_weight: number;
  signal_day: string | null;
  votes: number | null;
  vol20: number | null;
  exposure: number | null;
  targets: Record<string, number>;
  last_rebalance_key: string | null;
  last_rebalance_at: string | null;
  last_rebalance_done: boolean | null;
  attempts: number | null;
  errors: string[];
  since_cutover: {
    from: string; to: string; account_return: number; spy_price_return: number; note: string;
  } | null;
  drawdown: {
    mode: DrawdownMode;
    halted: boolean;
    drawdown: number | null;
    high_water_mark: number | null;
    closing_equity: number | null;
    as_of: string | null;
    error: string | null;
    cleared_by: string | null;
    cleared_at: string | null;
  };
}

export interface FleetState {
  accounts: FleetAccount[];
  limits: { soft: number; hard: number; enforced: boolean; soft_action: string; hard_action: string };
  kill_switch: { armed: boolean; tripped: boolean };
  stop_free: Record<string, string[]>;
}

export interface Figures {
  cagr: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  max_drawdown_after_haircut?: number | null;
  vol_pct?: number | null;
  correlation_to_B?: number | null;
}

export interface FleetRecord {
  plan: string;
  exploration: {
    window: [string, string];
    ran_at: string;
    code_commit: string | null;
    series: Record<string, Figures | null>;
    n2_sharpe_p95: number | null;
    selected: string | null;
    selection_verdict: string | null;
    rolling_win_share: Record<string, number | null>;
  } | null;
  heldout: {
    registration: string;
    ran_at: string;
    code_commit: string | null;
    verdict: string | null;
    test: { window: [string, string]; series: Record<string, Figures | null>;
            pass_bar: Record<string, boolean> | null; deflated_sharpe: number | null };
    spent: { window: [string, string] | null; label: string | null; series: Record<string, Figures | null> };
  } | null;
}

export const FLEET_STATE_KEY = ["/fleet-v1/state"];

export function useFleetV1State() {
  const interval = useVisibleInterval(60_000);
  return useQuery({
    queryKey: FLEET_STATE_KEY,
    queryFn: async () => (await api.get("/fleet-v1/state")).data as FleetState,
    refetchInterval: interval,
  });
}

export function useFleetV1Record() {
  return useQuery({
    queryKey: ["/fleet-v1/record"],
    queryFn: async () => (await api.get("/fleet-v1/record")).data as FleetRecord,
    staleTime: 10 * 60_000,
  });
}

export function useClearHalt(botId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (token: string) =>
      (await api.post(`/fleet-v1/${botId}/clear-halt`, { confirmation_token: token, by: "dashboard" })).data as FleetAccount,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: FLEET_STATE_KEY });
      qc.invalidateQueries({ queryKey: ["/momo-v2/state"] });
    },
  });
}

// ── MOMO-V2 (Momentum's account) ─────────────────────────────────────────────
export interface MomoState {
  bot_id: string;
  registration: string;
  role: string;
  month: string | null;
  selection_day: string | null;
  universe_source: string | null;
  names: string[];
  targets: Record<string, number>;
  held: "in" | "out" | null;
  why: string | null;
  trend_on: boolean | null;
  invested_fraction: number | null;
  book_index: number | null;
  book_sma100: number | null;
  book_vol20: number | null;
  stopped: string[];
  skipped_unaffordable: string[];
  last_rebalance_key: string | null;
  last_rebalance_at: string | null;
  last_rebalance_done: boolean | null;
  attempts: number | null;
  errors: string[];
  since_cutover: FleetAccount["since_cutover"];
  drawdown: { mode: DrawdownMode; halted: boolean; drawdown: number | null; high_water_mark: number | null;
              as_of: string | null; error: string | null };
}

export const MOMO_STATE_KEY = ["/momo-v2/state"];

export function useMomoV2State() {
  const interval = useVisibleInterval(60_000);
  return useQuery({
    queryKey: MOMO_STATE_KEY,
    queryFn: async () => (await api.get("/momo-v2/state")).data as MomoState,
    refetchInterval: interval,
  });
}
