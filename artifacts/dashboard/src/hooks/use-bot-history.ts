import { useQuery } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

export interface BotDay {
  date: string;
  equity: number | null;
  daily_return: number | null;   // server-computed fraction (0.01 = 1%)
  deployed_pct: number | null;   // fraction of equity invested
  positions: number | null;
}

export interface BotHistoryResponse {
  days: number;
  bots: Record<string, BotDay[]>;
}

/** Per-engine daily closes from bot_daily_returns (GET /fleet/bot-history). */
export function useBotHistory(days = 90) {
  return useQuery<BotHistoryResponse>({
    queryKey: ["fleet-bot-history", days],
    queryFn: async () => (await api.get(`/fleet/bot-history?days=${days}`)).data,
    refetchInterval: useVisibleInterval(10 * 60_000),
    staleTime: 5 * 60_000,
  });
}
