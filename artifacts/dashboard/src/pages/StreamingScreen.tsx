import { useLocation } from "wouter";
import { LayoutDashboard, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { GlobalHUD } from "@/components/streaming/GlobalHUD";
import { Scoreboard } from "@/components/streaming/Scoreboard";
import { NerveCenter } from "@/components/streaming/NerveCenter";
import { SignalRadar } from "@/components/streaming/SignalRadar";
import { VaultDisplay } from "@/components/streaming/VaultDisplay";
import { BotLeaderboard } from "@/components/streaming/BotLeaderboard";
import { AchievementFeed } from "@/components/streaming/AchievementFeed";
import { TradeSpeedometer } from "@/components/streaming/TradeSpeedometer";
import { ProfitExplosion } from "@/components/streaming/ProfitExplosion";
import { SalesTicker } from "@/components/streaming/SalesTicker";
import { SessionStats } from "@/components/streaming/SessionStats";
import { useSimulatedFeed } from "@/components/streaming/useSimulatedFeed";

function StreamingNavBar() {
  const [, navigate] = useLocation();
  const streamColor = "#f43f5e";

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 px-3 pb-4 pt-1 pointer-events-none">
      <div className="flex items-center justify-center gap-2 sm:gap-3 max-w-xs mx-auto pointer-events-auto">
        <button
          onClick={() => navigate("/")}
          className="relative flex flex-col items-center justify-center rounded-2xl transition-all duration-300 min-w-[56px] sm:min-w-[64px] py-2.5 px-3 sm:px-4 bg-slate-900/80 backdrop-blur-xl border border-white/[0.06] hover:border-blue-500/40 hover:bg-slate-800/80 group"
        >
          <span className="text-slate-400 group-hover:text-blue-400 transition-colors">
            <LayoutDashboard className="h-6 w-6" />
          </span>
          <span className="text-[9px] font-bold tracking-wider uppercase mt-1 text-slate-500 group-hover:text-blue-400 transition-colors">
            Dashboard
          </span>
        </button>
        <button
          className={cn(
            "relative flex flex-col items-center justify-center rounded-2xl transition-all duration-300 min-w-[56px] sm:min-w-[64px]",
            "py-2.5 px-3 sm:px-4 shadow-lg scale-105"
          )}
          style={{
            background: `linear-gradient(135deg, ${streamColor}20, ${streamColor}10)`,
            borderWidth: 1,
            borderStyle: "solid",
            borderColor: `${streamColor}50`,
            boxShadow: `0 4px 24px ${streamColor}25, 0 0 0 1px ${streamColor}15`,
          }}
        >
          <span className="relative" style={{ color: streamColor }}>
            <Radio className="h-6 w-6" />
            <span
              className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full animate-pulse"
              style={{ background: streamColor, boxShadow: `0 0 6px ${streamColor}` }}
            />
          </span>
          <span className="text-[9px] font-bold tracking-wider uppercase mt-1" style={{ color: streamColor }}>
            Live
          </span>
        </button>
      </div>
    </nav>
  );
}

export default function StreamingScreen() {
  const { trades, explosion, wins, losses, botStats, achievements, tradesPerHour } = useSimulatedFeed(15);

  return (
    <div className="h-screen bg-slate-950 flex flex-col overflow-hidden">
      <ProfitExplosion trade={explosion} />
      <AchievementFeed achievements={achievements} />

      <div className="flex-1 flex flex-col p-3 gap-2 pb-12 min-h-0">
        <GlobalHUD />

        <div className="flex-1 grid grid-cols-12 gap-2 min-h-0">
          <div className="col-span-3 min-h-0 flex flex-col gap-2">
            <Scoreboard wins={wins} losses={losses} trades={trades} />
            <div className="shrink-0">
              <TradeSpeedometer tradesPerHour={tradesPerHour} totalTrades={wins + losses} />
            </div>
            <div className="shrink-0">
              <BotLeaderboard botStats={botStats} />
            </div>
          </div>

          <div className="col-span-6 min-h-0 overflow-hidden rounded-xl border border-indigo-500/10 bg-slate-900/40">
            <NerveCenter />
          </div>

          <div className="col-span-3 min-h-0 flex flex-col gap-2">
            <div className="shrink-0">
              <SignalRadar />
            </div>
            <div className="shrink-0">
              <VaultDisplay />
            </div>
            <SessionStats botStats={botStats} trades={trades} wins={wins} losses={losses} />
          </div>
        </div>
      </div>

      <SalesTicker />
      <StreamingNavBar />
    </div>
  );
}
