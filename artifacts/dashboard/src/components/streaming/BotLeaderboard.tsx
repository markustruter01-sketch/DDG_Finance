import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import type { BotStats } from "./useRealFeed";

interface BotLeaderboardProps {
  botStats: BotStats[];
}

export function BotLeaderboard({ botStats }: BotLeaderboardProps) {
  const sorted = botStats.filter((b) => b.trades > 0);

  if (sorted.length === 0) {
    return (
      <div className="rounded-lg border border-white/5 bg-slate-900/60 px-2.5 py-2">
        <div className="text-[8px] uppercase tracking-widest text-amber-400/50 font-bold mb-1">Bot Leaderboard</div>
        <div className="text-[9px] text-muted-foreground/30 font-mono text-center py-2">Waiting for trades...</div>
      </div>
    );
  }

  const medals = ["🥇", "🥈", "🥉", "4th", "5th", "6th"];

  return (
    <div className="rounded-lg border border-white/5 bg-slate-900/60 px-2.5 py-2">
      <div className="text-[8px] uppercase tracking-widest text-amber-400/50 font-bold mb-1">Bot Leaderboard</div>
      <div className="flex flex-col gap-1">
        <AnimatePresence initial={false}>
          {sorted.map((bot, i) => {
            const winRate = bot.trades > 0 ? ((bot.wins / bot.trades) * 100).toFixed(0) : "0";
            const hasPnlUsd = bot.totalPnl !== 0;
            return (
              <motion.div
                key={bot.name}
                layout
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] as const }}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2 py-1 font-mono",
                  i === 0 ? "bg-amber-500/10 border border-amber-500/20" : "bg-slate-800/40"
                )}
              >
                <span className="text-sm w-6 text-center shrink-0">{i < 3 ? medals[i] : `#${i + 1}`}</span>
                <span className="text-sm shrink-0">{bot.icon}</span>
                <span className="text-[10px] font-bold text-white truncate flex-1">{bot.name}</span>
                <span className="text-[9px] text-muted-foreground/50 shrink-0">{winRate}%</span>
                <span className={cn(
                  "text-[11px] font-bold shrink-0 min-w-[50px] text-right",
                  hasPnlUsd
                    ? (bot.totalPnl >= 0 ? "text-green-400" : "text-orange-400")
                    : (bot.totalPnlPct >= 0 ? "text-green-400" : "text-orange-400")
                )}>
                  {hasPnlUsd
                    ? `${bot.totalPnl >= 0 ? "+" : ""}$${Math.abs(bot.totalPnl).toFixed(0)}`
                    : `${bot.totalPnlPct >= 0 ? "+" : ""}${bot.totalPnlPct.toFixed(1)}%`
                  }
                </span>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
