import { GlobalHUD } from "@/components/streaming/GlobalHUD";
import { Scoreboard } from "@/components/streaming/Scoreboard";
import { NerveCenter } from "@/components/streaming/NerveCenter";
import { SignalRadar } from "@/components/streaming/SignalRadar";
import { ProfitExplosion } from "@/components/streaming/ProfitExplosion";
import { SalesTicker } from "@/components/streaming/SalesTicker";
import { useSimulatedFeed } from "@/components/streaming/useSimulatedFeed";

export default function StreamingScreen() {
  const { trades, explosion, wins, losses } = useSimulatedFeed(20);

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col overflow-hidden">
      <ProfitExplosion trade={explosion} />

      <div className="flex-1 flex flex-col p-4 gap-4">
        <GlobalHUD />

        <div className="flex-1 grid grid-cols-12 gap-4 min-h-0">
          <div className="col-span-3 min-h-0 overflow-hidden">
            <Scoreboard wins={wins} losses={losses} trades={trades} />
          </div>

          <div className="col-span-6 min-h-0 overflow-hidden rounded-xl border border-indigo-500/10 bg-slate-900/40">
            <NerveCenter />
          </div>

          <div className="col-span-3 min-h-0 overflow-y-auto">
            <SignalRadar />
          </div>
        </div>
      </div>

      <SalesTicker />
    </div>
  );
}
