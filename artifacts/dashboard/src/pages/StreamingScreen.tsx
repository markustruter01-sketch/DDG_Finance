import { useState, useEffect, useCallback } from "react";
import { GlobalHUD } from "@/components/streaming/GlobalHUD";
import { Scoreboard } from "@/components/streaming/Scoreboard";
import { NerveCenter } from "@/components/streaming/NerveCenter";
import { NewsIntelligence } from "@/components/streaming/NewsIntelligence";
import { VaultDisplay } from "@/components/streaming/VaultDisplay";
import { SalesTicker } from "@/components/streaming/SalesTicker";
import { ClaudeThinking } from "@/components/streaming/ClaudeThinking";
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

export default function StreamingScreen() {
  const { trades, wins, losses } = useRealFeed(30);
  const celebrations = useRealCelebrations();
  const scale = useViewportScale();

  const cutoff24h = Date.now() - 24 * 60 * 60 * 1000;
  const recent24h = trades.filter(t => new Date(t.date).getTime() > cutoff24h);
  const wins24h = recent24h.filter(t => t.isWin).length;
  const losses24h = recent24h.filter(t => !t.isWin).length;

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
            <div className="col-span-3 min-h-0 flex flex-col">
              <Scoreboard wins={wins} losses={losses} recentTrades={trades} />
            </div>

            <div className="col-span-6 min-h-0 flex flex-col gap-1.5 relative">
              <div className="flex-1 rounded-xl border border-indigo-500/10 bg-slate-900/40 min-h-0 overflow-visible">
                <NerveCenter wins24h={wins24h} losses24h={losses24h} />
              </div>
              <ProfitExplosion trade={celebrations.explosion} />
            </div>

            <div className="col-span-3 min-h-0 flex flex-col gap-2">
              <div className="shrink-0">
                <NewsIntelligence />
              </div>
              <VaultDisplay />
              <ClaudeThinking />
            </div>
          </div>
        </div>

        <SalesTicker />
      </div>
    </div>
  );
}
