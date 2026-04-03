import { useState, useEffect, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNewsFeed } from "@/hooks/use-trading";

const CATEGORY_META: Record<string, { icon: string; color: string }> = {
  macro: { icon: "🏛️", color: "#facc15" },
  crypto: { icon: "₿", color: "#22d3ee" },
  commodities: { icon: "🛢️", color: "#f97316" },
  currencies: { icon: "💱", color: "#a78bfa" },
  markets: { icon: "📊", color: "#10b981" },
};

const FALLBACK_HEADLINES = [
  { title: "Federal Reserve holds rates steady, signals data-dependent approach", source: "Reuters", category: "macro", published_at: "", url: "" },
  { title: "Bitcoin consolidates near key support as institutional demand grows", source: "CoinDesk", category: "crypto", published_at: "", url: "" },
  { title: "S&P 500 futures point to cautious open amid global uncertainty", source: "Bloomberg", category: "markets", published_at: "", url: "" },
  { title: "Gold prices edge higher as safe-haven demand persists", source: "MarketWatch", category: "commodities", published_at: "", url: "" },
  { title: "Dollar index steady as traders await inflation data release", source: "Reuters", category: "currencies", published_at: "", url: "" },
  { title: "Ethereum network activity surges with DeFi protocol launches", source: "CoinTelegraph", category: "crypto", published_at: "", url: "" },
  { title: "Treasury yields dip as bond market prices in rate cut expectations", source: "CNBC", category: "macro", published_at: "", url: "" },
  { title: "Crude oil rallies on OPEC+ supply cut extension signals", source: "Bloomberg", category: "commodities", published_at: "", url: "" },
  { title: "EUR/USD tests resistance as ECB policy divergence narrows", source: "Financial Times", category: "currencies", published_at: "", url: "" },
  { title: "Nasdaq tech rally broadens as AI spending forecasts lift sentiment", source: "Yahoo Finance", category: "markets", published_at: "", url: "" },
  { title: "Crypto market cap surpasses $3 trillion milestone", source: "CoinDesk", category: "crypto", published_at: "", url: "" },
  { title: "Global PMI data signals manufacturing sector stabilization", source: "Reuters", category: "macro", published_at: "", url: "" },
];

const SOURCE_ICONS: Record<string, string> = {
  Bloomberg: "📊",
  Reuters: "📰",
  CNBC: "📺",
  "Yahoo Finance": "💹",
  "The Wall Street Journal": "📰",
  MarketWatch: "📈",
  CoinDesk: "₿",
  CoinTelegraph: "₿",
  "Financial Times": "📰",
};

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

export function NewsIntelligence() {
  const { data, isLoading, isError, refetch } = useNewsFeed();
  const apiArticles = data?.articles ?? [];
  const [visibleIdx, setVisibleIdx] = useState(0);

  const articles = useMemo(() => {
    if (apiArticles.length > 0) return apiArticles;
    return FALLBACK_HEADLINES;
  }, [apiArticles]);

  const isFallback = apiArticles.length === 0 && articles.length > 0;

  useEffect(() => {
    if (apiArticles.length > 0) return;
    const retryTimer = setInterval(() => {
      refetch();
    }, 120_000);
    return () => clearInterval(retryTimer);
  }, [apiArticles.length, refetch]);

  useEffect(() => {
    if (articles.length <= 3) return;
    const interval = setInterval(() => {
      setVisibleIdx((prev) => (prev + 3) % articles.length);
    }, 7000);
    return () => clearInterval(interval);
  }, [articles.length]);

  const visibleArticles = articles.length > 0
    ? articles.slice(visibleIdx, visibleIdx + 3).concat(
        visibleIdx + 3 > articles.length
          ? articles.slice(0, (visibleIdx + 3) - articles.length)
          : []
      )
    : [];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[14px]">📡</span>
          <span className="text-[13px] uppercase tracking-widest font-bold" style={{ color: "rgba(34,211,238,0.5)" }}>News & Macro Intelligence</span>
        </div>
        <span className="text-[11px] font-mono" style={{ color: "rgba(34,211,238,0.3)" }}>
          {isFallback ? "market briefing" : `${articles.length} feeds`}
        </span>
      </div>

      <div className="rounded-lg border border-cyan-500/15 bg-slate-900/60 overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={visibleIdx}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.4 }}
          >
            {visibleArticles.length === 0 && (
              <div className="flex flex-col items-center justify-center py-8 gap-2">
                <div className="text-[14px] font-mono text-center" style={{ color: "rgba(148,163,184,0.4)" }}>
                  {isLoading ? "Fetching news feeds..." : isError ? "News API temporarily unavailable" : "Loading news feeds..."}
                </div>
                <motion.div
                  className="h-0.5 w-20 bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent rounded-full"
                  animate={{ opacity: [0.3, 0.8, 0.3] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              </div>
            )}
            {visibleArticles.map((article, i) => {
              const meta = CATEGORY_META[article.category] ?? { icon: "📰", color: "#64748b" };
              const srcIcon = SOURCE_ICONS[article.source] ?? "📰";
              return (
                <div
                  key={`${article.title}-${i}`}
                  className="px-3 py-2.5 border-b border-white/[0.04] flex items-start gap-2.5"
                >
                  <span className="text-[14px] mt-0.5 shrink-0">{meta.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-mono leading-snug line-clamp-2" style={{ color: "rgba(255,255,255,0.85)" }}>
                      {article.title}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[11px]">{srcIcon}</span>
                      <span className="text-[11px] font-mono truncate" style={{ color: meta.color + "99" }}>
                        {article.source}
                      </span>
                      <span className="text-[10px] font-mono" style={{ color: "rgba(255,255,255,0.2)" }}>·</span>
                      <span className="text-[10px] font-mono uppercase" style={{ color: meta.color + "60" }}>
                        {article.category}
                      </span>
                      {article.published_at && (
                        <>
                          <span className="text-[10px] font-mono" style={{ color: "rgba(255,255,255,0.2)" }}>·</span>
                          <span className="text-[10px] font-mono" style={{ color: "rgba(255,255,255,0.3)" }}>{timeAgo(article.published_at)}</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
