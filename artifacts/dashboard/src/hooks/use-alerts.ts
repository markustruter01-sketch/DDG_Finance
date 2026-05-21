import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

export interface AlertConfig {
  enabled: boolean;
  interval_minutes: number;
  min_pnl_usd: number;
  min_pnl_pct: number;
  telegram_enabled: boolean;
  discord_enabled: boolean;
}

export interface AlertStatus {
  queue_size: number;
  config: AlertConfig;
  last_flush: string | null;
  telegram_configured: boolean;
  discord_configured: boolean;
}

export function useAlertStatus() {
  return useQuery<AlertStatus>({
    queryKey: ["/alerts/status"],
    queryFn: async () => (await api.get("/alerts/status")).data,
    refetchInterval: useVisibleInterval(30000),
  });
}

export function useAlertConfig() {
  return useQuery<AlertConfig>({
    queryKey: ["/alerts/config"],
    queryFn: async () => (await api.get("/alerts/config")).data,
  });
}

export function useUpdateAlertConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (config: Partial<AlertConfig>) => (await api.post("/alerts/config", config)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/alerts/config"] });
      qc.invalidateQueries({ queryKey: ["/alerts/status"] });
    },
  });
}

export function useTestAlert() {
  return useMutation({
    mutationFn: async () => (await api.post("/alerts/test")).data,
  });
}

export function useFlushAlerts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/alerts/flush")).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/alerts/status"] });
    },
  });
}
