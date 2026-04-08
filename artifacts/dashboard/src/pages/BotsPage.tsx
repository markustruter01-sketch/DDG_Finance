import { useMemo } from "react";
import { useKrakenBots, useAIImpactTimeline, type AIIntervention } from "@/hooks/use-trading";
import { BotCard } from "@/components/BotCard";
import { Loader2, Bot } from "lucide-react";

function derivePreviousParams(
  interventions: AIIntervention[] | undefined
): Record<string, Record<string, number>> {
  if (!interventions || interventions.length < 2) return {};
  const sorted = [...interventions].sort(
    (a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()
  );

  const result: Record<string, Record<string, number>> = {};

  const lastChanges: Record<string, Set<string>> = {};
  for (const pc of sorted[0]?.param_changes ?? []) {
    if (!pc.bot_id) continue;
    if (!lastChanges[pc.bot_id]) lastChanges[pc.bot_id] = new Set();
    const keys = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"] as const;
    for (const k of keys) {
      if (pc[k] !== undefined) lastChanges[pc.bot_id].add(k);
    }
  }

  for (let i = 1; i < sorted.length; i++) {
    const intervention = sorted[i];
    for (const pc of intervention.param_changes ?? []) {
      if (!pc.bot_id) continue;
      const changedInLast = lastChanges[pc.bot_id];
      if (!changedInLast) continue;
      if (!result[pc.bot_id]) result[pc.bot_id] = {};
      const keys = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"] as const;
      for (const k of keys) {
        if (pc[k] !== undefined && changedInLast.has(k) && result[pc.bot_id][k] == null) {
          result[pc.bot_id][k] = pc[k] as number;
        }
      }
    }
    const allFilled = Object.entries(lastChanges).every(([botId, params]) =>
      [...params].every((p) => result[botId]?.[p] != null)
    );
    if (allFilled) break;
  }

  return result;
}

export default function BotsPage() {
  const { data: bots, isLoading: botsLoading } = useKrakenBots();
  const { data: aiTimeline } = useAIImpactTimeline();

  const previousParams = useMemo(
    () => derivePreviousParams(aiTimeline?.interventions),
    [aiTimeline]
  );

  const isLoading = botsLoading;

  return (
    <div className="min-h-screen bg-slate-950 pb-24">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-slate-950/95 backdrop-blur-xl px-4 py-3">
        <div className="max-w-7xl mx-auto flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
            <Bot className="w-4 h-4 text-amber-400" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white leading-none">Bots</h1>
            <p className="text-[10px] text-slate-500">Kraken trading fleet</p>
          </div>
          {bots && (
            <span className="ml-auto text-[11px] text-slate-500">{bots.length} bot{bots.length !== 1 ? "s" : ""}</span>
          )}
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 pt-5">
        {isLoading && (
          <div className="flex items-center justify-center py-24">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 text-slate-500 animate-spin" />
              <span className="text-xs text-slate-600">Loading bots...</span>
            </div>
          </div>
        )}

        {!isLoading && (!bots || bots.length === 0) && (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-14 h-14 rounded-2xl bg-slate-800/60 border border-white/[0.06] flex items-center justify-center mb-4">
              <Bot className="w-7 h-7 text-slate-600" />
            </div>
            <h2 className="text-base font-bold text-white mb-1">No bots found</h2>
            <p className="text-sm text-slate-500 max-w-xs">
              No trading bots are currently registered. Check the API connection.
            </p>
          </div>
        )}

        {!isLoading && bots && bots.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {bots.map((bot) => (
              <BotCard
                key={bot.bot_id}
                botId={bot.bot_id}
                displayName={bot.display_name}
                strategyLabel={bot.strategy_label}
                previousParams={previousParams[bot.bot_id]}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
