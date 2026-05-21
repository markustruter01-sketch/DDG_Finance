import { useQuery } from "@tanstack/react-query";
import { api, useVisibleInterval } from "./use-trading-client";

export interface TradeJournal {
  summary: { total: number; active: number; wins: number; losses: number; avg_pnl: number };
  trades: Array<{
    trade_id: string;
    date: string;
    ticker: string;
    asset_class: string;
    conviction_score: number;
    pnl_percentage: number;
    original_thesis: string;
    status: string;
    source?: string;
    pnl_usd?: number | null;
    realized_pnl?: number | null;
    side?: string;
    direction?: string;
    exit_reason?: string | null;
  }>;
}

export interface RagEntry {
  trade_id: string;
  date: string;
  ticker: string;
  asset_class: string;
  conviction_score: number;
  pnl_percentage: number;
  original_thesis: string;
}

export interface RagLosses {
  count: number;
  losses: RagEntry[];
}

export interface RagWins {
  count: number;
  wins: RagEntry[];
}

export interface RecentTradeItem {
  trade_id: string;
  symbol: string;
  pnl_pct: number;
  pnl_usd: number | null;
  exit_reason: string | null;
  closed_at: string;
  status: "Closed_Win" | "Closed_Loss";
}

export interface RecentTrades {
  count: number;
  trades: RecentTradeItem[];
}

export interface NewsFeedArticle {
  title: string;
  source: string;
  category: string;
  published_at: string;
  url: string;
}

export interface NewsFeedData {
  articles: NewsFeedArticle[];
  error?: string;
}

export function useJournal() {
  return useQuery<TradeJournal>({
    queryKey: ["/journal"],
    queryFn: async () => (await api.get("/journal")).data,
    refetchInterval: useVisibleInterval(30_000),
    staleTime: 25_000,
  });
}

export function useRagLosses() {
  return useQuery<RagLosses>({
    queryKey: ["/journal/losses"],
    queryFn: async () => (await api.get("/journal/losses?n=5")).data,
  });
}

export function useRagWins() {
  return useQuery<RagWins>({
    queryKey: ["/journal/wins"],
    queryFn: async () => (await api.get("/journal/wins?n=3")).data,
  });
}

export function useRecentTrades(n = 20) {
  return useQuery<RecentTrades>({
    queryKey: ["/journal/recent", n],
    queryFn: async () => (await api.get(`/journal/recent?n=${n}`)).data,
    staleTime: 60_000,
  });
}

export function useRagWinsExtended(n = 10) {
  return useQuery<RagWins>({
    queryKey: ["/journal/wins/extended", n],
    queryFn: async () => (await api.get(`/journal/wins?n=${n}`)).data,
    staleTime: 60_000,
  });
}

export function useNewsFeed() {
  return useQuery<NewsFeedData>({
    queryKey: ["/portfolio/news-feed"],
    queryFn: async () => (await api.get("/portfolio/news-feed")).data,
    refetchInterval: useVisibleInterval(300_000),
    retry: 1,
    staleTime: 240_000,
  });
}
