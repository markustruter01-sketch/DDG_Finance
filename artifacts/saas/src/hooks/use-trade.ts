/**
 * use-trade.ts
 * React Query hooks for Stage 5 execution middleware.
 *
 * useSaasPortfolio()  — polls /saas-api/trade/portfolio every 30s
 * useExecuteTrade()   — mutation: POST /saas-api/trade/execute
 * useCloseTrade()     — mutation: POST /saas-api/trade/close
 *
 * Live-mode credentials are read from localStorage and injected automatically
 * into every mutation so callers don't need to think about them.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiUrl } from "@/lib/config";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SaasPosition {
  side:        "long" | "short";
  entry_price: number;
  size_usd:    number;
  size_units:  number;
  entry_time:  string;
  entry_fee:   number;
}

export interface SaasTrade {
  action:      "open" | "close";
  symbol:      string;
  side?:       string;
  size_usd?:   number;
  price?:      number;
  pnl?:        number;
  exit_price?: number;
  fee:         number;
  time:        string;
}

export interface SaasPortfolioData {
  equity:           number;
  cash:             number;
  deployed:         number;
  starting_balance: number;
  pnl_pct:          number;
  positions:        Record<string, SaasPosition>;
  positions_count:  number;
  recent_trades:    SaasTrade[];
}

export interface TradeResult {
  status:         "executed" | "closed" | "error";
  mode?:          "paper" | "live";
  symbol?:        string;
  side?:          string;
  size_usd?:      number;
  fill_price?:    number;
  fee?:           number;
  pnl?:           number;
  cash_remaining?: number;
  cash_now?:      number;
  order_id?:      string;
  message?:       string;
}

// ── Credential helpers ────────────────────────────────────────────────────────

function getLiveMode(): boolean {
  try { return JSON.parse(localStorage.getItem("algoedge_live_mode") ?? "false"); }
  catch { return false; }
}

function getKrakenKeys(): { apiKey: string; apiSecret: string } | null {
  try {
    const raw = localStorage.getItem("algoedge_kraken");
    if (!raw) return null;
    const { apiKey, apiSecret } = JSON.parse(raw);
    if (!apiKey || !apiSecret) return null;
    return { apiKey, apiSecret };
  } catch { return null; }
}

export function getTradeMode(): "paper" | "live" {
  if (getLiveMode() && getKrakenKeys()) return "live";
  return "paper";
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

export function useSaasPortfolio() {
  return useQuery<SaasPortfolioData>({
    queryKey: ["saas-portfolio"],
    queryFn: async () => {
      const res = await fetch(apiUrl("/trade/portfolio"));
      if (!res.ok) throw new Error(`Portfolio fetch failed: ${res.status}`);
      return res.json();
    },
    staleTime: 25_000,
    refetchInterval: 30_000,
    retry: 1,
  });
}

export function useExecuteTrade() {
  const qc = useQueryClient();
  return useMutation<
    TradeResult,
    Error,
    { symbol: string; side: "long" | "short"; size_pct: number }
  >({
    mutationFn: async ({ symbol, side, size_pct }) => {
      const live = getLiveMode();
      const keys = getKrakenKeys();
      const body: Record<string, unknown> = { symbol, side, size_pct };
      if (live && keys) {
        body.use_live = true;
        body.api_key  = keys.apiKey;
        body.api_secret = keys.apiSecret;
      }
      const res = await fetch(apiUrl("/trade/execute"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["saas-portfolio"] });
      qc.invalidateQueries({ queryKey: ["saas-insights"] });
    },
  });
}

export function useCloseTrade() {
  const qc = useQueryClient();
  return useMutation<TradeResult, Error, { symbol: string }>({
    mutationFn: async ({ symbol }) => {
      const live = getLiveMode();
      const keys = getKrakenKeys();
      const body: Record<string, unknown> = { symbol };
      if (live && keys) {
        body.use_live   = true;
        body.api_key    = keys.apiKey;
        body.api_secret = keys.apiSecret;
      }
      const res = await fetch(apiUrl("/trade/close"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["saas-portfolio"] });
      qc.invalidateQueries({ queryKey: ["saas-insights"] });
    },
  });
}
