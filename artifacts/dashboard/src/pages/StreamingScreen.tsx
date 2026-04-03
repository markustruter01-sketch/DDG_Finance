import { useLocation } from "wouter";
import { useState, useEffect, useCallback } from "react";
import { LayoutDashboard, Radio, Anchor, Globe, TrendingUp, LineChart, Settings, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";
import { GlobalHUD } from "@/components/streaming/GlobalHUD";
import { Scoreboard } from "@/components/streaming/Scoreboard";
import { NerveCenter } from "@/components/streaming/NerveCenter";
import { NewsIntelligence } from "@/components/streaming/NewsIntelligence";
import { VaultDisplay } from "@/components/streaming/VaultDisplay";
import { BotLeaderboard } from "@/components/streaming/BotLeaderboard";
import { TradeSpeedometer } from "@/components/streaming/TradeSpeedometer";
import { SalesTicker } from "@/components/streaming/SalesTicker";
import { GeminiThinking } from "@/components/streaming/GeminiThinking";
import { useRealFeed } from "@/components/streaming/useRealFeed";
import { ProfitExplosion } from "@/components/streaming/ProfitExplosion";
import { AchievementFeed } from "@/components/streaming/AchievementFeed";
import { useRealCelebrations } from "@/components/streaming/useRealCelebrations";

const REF_W = 1920;
const REF_H = 1080;

function useViewportScale() {
  const getScale = useCallback(() => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    return Math.min(w / REF_W, h / REF_H);
  }, []);

  const [scale, setScale] = useState(getScale);

  useEffect(() => {
    const onResize = () => setScale(getScale());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [getScale]);

  return scale;
}

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, color: "#3b82f6", path: "/" },
  { id: "kraken", label: "Kraken", icon: Anchor, color: "#22d3ee" },
  { id: "alpaca", label: "Alpaca", icon: TrendingUp, color: "#10b981" },
  { id: "options", label: "Options", icon: BarChart3, color: "#f59e0b" },
  { id: "forex", label: "Forex", icon: Globe, color: "#8b5cf6" },
  { id: "analytics", label: "Analytics", icon: LineChart, color: "#6366f1" },
  { id: "cmd", label: "CMD", icon: Settings, color: "#64748b" },
  { id: "live", label: "Live", icon: Radio, color: "#f43f5e", active: true },
];

function StreamingNavBar() {
  const [, navigate] = useLocation();

  return (
    <div className="shrink-0 px-3 py-1.5">
      <div className="flex items-center justify-center gap-1.5 mx-auto">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = item.active;
          const isLink = !!item.path;

          return (
            <button
              key={item.id}
              onClick={isLink ? () => navigate(item.path!) : undefined}
              className={cn(
                "relative flex flex-col items-center justify-center rounded-xl transition-all duration-200 min-w-[56px] py-1.5 px-3",
                isActive
                  ? "scale-105"
                  : "bg-slate-900/60 backdrop-blur-xl border border-white/[0.06] hover:border-white/10 hover:bg-slate-800/60"
              )}
              style={isActive ? {
                background: `linear-gradient(135deg, ${item.color}20, ${item.color}10)`,
                borderWidth: 1,
                borderStyle: "solid",
                borderColor: `${item.color}50`,
                boxShadow: `0 2px 12px ${item.color}25, 0 0 0 1px ${item.color}15`,
              } : undefined}
            >
              <span className="relative" style={{ color: isActive ? item.color : "#64748b" }}>
                <Icon className="h-4 w-4" />
                {isActive && (
                  <span
                    className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full animate-pulse"
                    style={{ background: item.color, boxShadow: `0 0 4px ${item.color}` }}
                  />
                )}
              </span>
              <span
                className="text-[7px] font-bold tracking-wider uppercase mt-0.5"
                style={{ color: isActive ? item.color : "#475569" }}
              >
                {item.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function StreamingScreen() {
  const { trades, wins, losses, botStats, totalTrades, openPositions } = useRealFeed(20);
  const celebrations = useRealCelebrations();
  const scale = useViewportScale();

  return (
    <div className="h-screen w-screen bg-slate-950 overflow-hidden flex items-center justify-center">
      <div
        style={{
          width: REF_W,
          height: REF_H,
          transform: `scale(${scale})`,
          transformOrigin: "center center",
        }}
        className="relative flex flex-col overflow-hidden"
      >
        <AchievementFeed achievements={celebrations.achievements} />
        <div className="flex-1 flex flex-col p-3 gap-2 min-h-0">
          <GlobalHUD />

          <div className="flex-1 grid grid-cols-12 gap-2 min-h-0">
            <div className="col-span-3 min-h-0 flex flex-col gap-2">
              <Scoreboard wins={wins} losses={losses} openPositions={openPositions} />
              <div className="shrink-0">
                <TradeSpeedometer totalTrades={totalTrades} />
              </div>
              <div className="shrink-0">
                <BotLeaderboard botStats={botStats} />
              </div>
            </div>

            <div className="col-span-6 min-h-0 flex flex-col gap-1.5">
              <div className="flex-1 overflow-hidden rounded-xl border border-indigo-500/10 bg-slate-900/40 min-h-0 relative">
                <NerveCenter />
                <ProfitExplosion trade={celebrations.explosion} />
              </div>
              <StreamingNavBar />
            </div>

            <div className="col-span-3 min-h-0 flex flex-col gap-2">
              <div className="shrink-0">
                <NewsIntelligence />
              </div>
              <VaultDisplay />
              <GeminiThinking />
            </div>
          </div>
        </div>

        <SalesTicker />
      </div>
    </div>
  );
}
