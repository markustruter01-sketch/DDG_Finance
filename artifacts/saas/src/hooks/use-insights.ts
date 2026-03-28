/**
 * use-insights.ts
 * React Query hook for /saas-api/insights
 * Auto-refreshes every 60 seconds to stay in sync with the bot's cycle.
 */

import { useQuery } from "@tanstack/react-query";
import { apiUrl } from "@/lib/config";

export interface SymbolRow {
  symbol:      string;
  base:        string;
  label:       string;
  status:      "held" | "watching";
  side:        "long" | "short" | null;
  entry_price: number | null;
  size_usd:    number | null;
  entry_time:  string | null;
}

export interface InsightsData {
  portfolio: {
    equity:          number;
    cash:            number;
    deployed:        number;
    positions_count: number;
    deployed_pct:    number;
    total_pnl_pct:   number;
    starting_balance: number;
  };
  symbols:   SymbolRow[];
  sentiment: {
    crypto: { value: number; label: string };
    market: { value: number; label: string };
  };
  cycle_count:  number;
  last_updated: string;
}

async function fetchInsights(): Promise<InsightsData> {
  const res = await fetch(apiUrl("/insights"));
  if (!res.ok) throw new Error(`Insights fetch failed: ${res.status}`);
  return res.json();
}

export function useInsights() {
  return useQuery<InsightsData>({
    queryKey: ["saas-insights"],
    queryFn:  fetchInsights,
    staleTime: 55_000,
    refetchInterval: 60_000,
    retry: 2,
  });
}
