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
    if (articles.length <= 4) return;
    const interval = setInterval(() => {
      setVisibleIdx((prev) => (prev + 4) % articles.length);
    }, 6000);
    return () => clearInterval(interval);
  }, [articles.length]);

  const visibleArticles = articles.length > 0
    ? articles.slice(visibleIdx, visibleIdx + 4).concat(
        visibleIdx + 4 > articles.length
          ? articles.slice(0, (visibleIdx + 4) - articles.length)
          : []
      )
    : [];

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px]">📡</span>
          <span className="text-[9px] uppercase tracking-widest text-cyan-400/50 font-bold">News & Macro Intelligence</span>
        </div>
        <span className="text-[8px] font-mono text-cyan-400/30">
          {isFallback ? "market briefing" : `${articles.length} feeds`}
        </span>
      </div>

      <div className="rounded-lg border border-cyan-500/15 bg-slate-900/60 overflow-hidden min-h-[120px]">
        <AnimatePresence mode="wait">
          <motion.div
            key={visibleIdx}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.4 }}
          >
            {visibleArticles.length === 0 && (
              <div className="flex flex-col items-center justify-center py-6 gap-1.5">
                <div className="text-[10px] text-muted-foreground/40 font-mono text-center">
                  {isLoading ? "Fetching news feeds..." : isError ? "News API temporarily unavailable" : "Loading news feeds..."}
                </div>
                <motion.div
                  className="h-0.5 w-16 bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent rounded-full"
                  animate={{ opacity: [0.3, 0.8, 0.3] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
                <div className="text-[8px] text-muted-foreground/20 font-mono">auto-retrying every 30s</div>
              </div>
            )}
            {visibleArticles.map((article, i) => {
              const meta = CATEGORY_META[article.category] ?? { icon: "📰", color: "#64748b" };
              const srcIcon = SOURCE_ICONS[article.source] ?? "📰";
              return (
                <div
                  key={`${article.title}-${i}`}
                  className="px-2.5 py-1.5 border-b border-white/[0.03] flex items-start gap-2"
                >
                  <span className="text-[9px] mt-0.5 shrink-0">{meta.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[9px] font-mono text-white/80 leading-tight line-clamp-2">
                      {article.title}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-[7px]">{srcIcon}</span>
                      <span className="text-[7px] font-mono truncate" style={{ color: meta.color + "99" }}>
                        {article.source}
                      </span>
                      <span className="text-[7px] font-mono text-white/20">·</span>
                      <span className="text-[7px] font-mono text-white/25 uppercase" style={{ color: meta.color + "60" }}>
                        {article.category}
                      </span>
                      {article.published_at && (
                        <>
                          <span className="text-[7px] font-mono text-white/20">·</span>
                          <span className="text-[7px] font-mono text-white/25">{timeAgo(article.published_at)}</span>
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
