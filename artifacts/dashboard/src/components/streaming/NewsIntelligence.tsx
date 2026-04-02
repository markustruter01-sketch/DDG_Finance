import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNewsFeed } from "@/hooks/use-trading";

const CATEGORY_META: Record<string, { icon: string; color: string }> = {
  macro: { icon: "🏛️", color: "#facc15" },
  crypto: { icon: "₿", color: "#22d3ee" },
  commodities: { icon: "🛢️", color: "#f97316" },
  currencies: { icon: "💱", color: "#a78bfa" },
  markets: { icon: "📊", color: "#10b981" },
};

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
  const { data } = useNewsFeed();
  const articles = data?.articles ?? [];
  const [visibleIdx, setVisibleIdx] = useState(0);

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
        <span className="text-[8px] font-mono text-cyan-400/30">{articles.length} feeds</span>
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
              <div className="text-[9px] text-muted-foreground/30 font-mono text-center py-6">
                Loading news feeds...
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
