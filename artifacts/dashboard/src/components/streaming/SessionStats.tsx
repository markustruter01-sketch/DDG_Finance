import { cn } from "@/lib/utils";
import type { BotStats, SimulatedTrade } from "./useSimulatedFeed";

interface SessionStatsProps {
  botStats: Record<string, BotStats>;
  trades: SimulatedTrade[];
  wins: number;
  losses: number;
}

export function SessionStats({ botStats, trades, wins, losses }: SessionStatsProps) {
  const allBots = Object.values(botStats).filter((b) => b.trades > 0);
  const totalPnl = allBots.reduce((s, b) => s + b.totalPnl, 0);
  const totalTrades = wins + losses;
  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : "0.0";

  const bestTrade = trades.length > 0
    ? trades.reduce((best, t) => t.pnlUsd > best.pnlUsd ? t : best, trades[0])
    : null;
  const worstTrade = trades.length > 0
    ? trades.reduce((worst, t) => t.pnlUsd < worst.pnlUsd ? t : worst, trades[0])
    : null;

  const bestBot = allBots.length > 0
    ? allBots.reduce((best, b) => b.totalPnl > best.totalPnl ? b : best, allBots[0])
    : null;

  const avgPnl = totalTrades > 0 ? totalPnl / totalTrades : 0;

  const rows = [
    { label: "Win Rate", value: `${winRate}%`, color: Number(winRate) >= 50 ? "text-green-400" : "text-red-400" },
    { label: "Session P&L", value: `${totalPnl >= 0 ? "+" : ""}$${Math.abs(totalPnl).toFixed(0)}`, color: totalPnl >= 0 ? "text-green-400" : "text-red-400" },
    { label: "Avg Trade", value: `${avgPnl >= 0 ? "+" : ""}$${Math.abs(avgPnl).toFixed(2)}`, color: avgPnl >= 0 ? "text-green-400" : "text-red-400" },
    { label: "Best Trade", value: bestTrade ? `+$${bestTrade.pnlUsd.toFixed(0)} ${bestTrade.symbol}` : "—", color: "text-emerald-400" },
    { label: "Worst Trade", value: worstTrade && worstTrade.pnlUsd < 0 ? `-$${Math.abs(worstTrade.pnlUsd).toFixed(0)} ${worstTrade.symbol}` : "—", color: "text-red-400" },
    { label: "Top Bot", value: bestBot ? `${bestBot.icon} ${bestBot.name}` : "—", color: "text-amber-400" },
  ];

  return (
    <div className="flex flex-col gap-1.5 shrink-0">
      <div className="text-[9px] uppercase tracking-widest text-violet-400/50 font-bold">Session Analytics</div>
      <div className="flex-1 rounded-lg border border-white/5 bg-slate-900/60 overflow-hidden">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between px-2.5 py-[5px] border-b border-white/[0.03] last:border-b-0">
            <span className="text-[9px] text-muted-foreground/50 font-mono">{row.label}</span>
            <span className={cn("text-[10px] font-mono font-bold", row.color)}>{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
