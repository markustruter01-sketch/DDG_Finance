import { useMemo } from "react";
import { cn, formatCurrency } from "@/lib/utils";
import {
  useStatusSummary, useJournal, usePerformanceHistory,
  useForexState, useFleetEquity, useBotRegistry,
} from "@/hooks/use-trading";
import { MiniSparkline } from "@/lib/dashboard-shared";
import { getFleetBotCount } from "@/lib/fleet-capital";

export function FleetPerformanceHero() {
  const { data: summary }      = useStatusSummary();
  const { data: fleetEq }      = useFleetEquity();
  const { data: registry }     = useBotRegistry();
  const { data: journal }      = useJournal();
  const { data: perfHistory }  = usePerformanceHistory();
  const { data: fxState }      = useForexState();

  const grandTotal = fleetEq?.fleet_total?.equity ?? 0;

  // Fleet win rate — server-computed from canonical trade tables (30d window)
  const serverWinRate = fleetEq?.fleet_total?.win_rate;
  const combinedWinRate = serverWinRate != null ? serverWinRate * 100 : null;

  const alpacaWins  = journal?.summary?.wins ?? 0;
  const alpacaTotal = journal?.summary?.total ?? 0;

  const todayStr = new Date().toISOString().slice(0, 10);

  const todayPerformers = useMemo(() => {
    type Performer = { name: string; icon: string; dailyPnl: number };
    const results: Performer[] = [];

    const oracleTodayTrades = journal?.trades?.filter(t => t.date?.startsWith(todayStr)) ?? [];
    const oracleDailyPnl = oracleTodayTrades.reduce((sum, t) => sum + (t.pnl_percentage ?? 0), 0);
    results.push({ name: "Oracle", icon: "🔮", dailyPnl: oracleDailyPnl });

    const sorted = [...results].sort((a, b) => b.dailyPnl - a.dailyPnl);
    const best  = sorted[0] ?? null;
    const worst = sorted[sorted.length - 1] ?? null;
    return { best, worst };
  }, [journal, todayStr]);

  const alpacaBestPct  = journal?.trades?.length ? Math.max(0, ...journal.trades.map(t => t.pnl_percentage ?? 0)) : 0;
  const alpacaWorstPct = journal?.trades?.length ? Math.min(0, ...journal.trades.map(t => t.pnl_percentage ?? 0)) : 0;

  const botSparklines = useMemo(() => {
    const lines: Array<{ id: string; name: string; icon: string; accent: string; curve: number[] }> = [];

    const oracleSnapshots = perfHistory?.snapshots ?? [];
    const oracleCurve = oracleSnapshots.length > 1
      ? oracleSnapshots.slice(-20).map(s => s.cumulative_pnl_pct)
      : [0];
    lines.push({ id: "oracle", name: "Oracle", icon: "🔮", accent: "#facc15", curve: oracleCurve });

    const fxPnl    = fxState?.total_pnl ?? 0;
    const fxEquity = fxState?.total_equity ?? 1;
    const fxPct    = fxEquity > 0 ? (fxPnl / fxEquity) * 100 : 0;
    if (fxPct !== 0) {
      lines.push({ id: "forex", name: "Navigator", icon: "🧭", accent: "#14b8a6", curve: [0, fxPct * 0.5, fxPct] });
    }

    return lines;
  }, [perfHistory, fxState]);

  const botCount = getFleetBotCount(registry, fleetEq);
  const totalTrades = alpacaTotal;

  const stats = [
    {
      label: "Fleet Equity",
      value: formatCurrency(grandTotal),
      color: "text-white",
      sub: `${botCount} bots · 4 capital pools`,
    },
    {
      label: "Total Trades",
      value: String(totalTrades),
      color: "text-white",
      sub: `${alpacaWins}W / ${totalTrades - alpacaWins}L`,
    },
    {
      label: "Fleet Win Rate",
      value: combinedWinRate != null ? `${combinedWinRate.toFixed(1)}%` : "—",
      color: combinedWinRate != null && combinedWinRate >= 50 ? "text-green-400" : "text-amber-400",
      sub: "30d · all bots",
    },
    {
      label: "Best Today",
      value: todayPerformers.best ? `${todayPerformers.best.icon} ${todayPerformers.best.name}` : "—",
      color: "text-green-400",
      sub: todayPerformers.best ? `${todayPerformers.best.dailyPnl >= 0 ? "+" : ""}${todayPerformers.best.dailyPnl.toFixed(2)}% daily P&L` : "no trades today",
    },
    {
      label: "Worst Today",
      value: todayPerformers.worst ? `${todayPerformers.worst.icon} ${todayPerformers.worst.name}` : "—",
      color: todayPerformers.worst && todayPerformers.worst.dailyPnl < 0 ? "text-red-400" : "text-muted-foreground",
      sub: todayPerformers.worst ? `${todayPerformers.worst.dailyPnl >= 0 ? "+" : ""}${todayPerformers.worst.dailyPnl.toFixed(2)}% daily P&L` : "no trades today",
    },
    {
      label: "Best/Worst Trade",
      value: alpacaBestPct > 0 || alpacaWorstPct < 0 ? `+${alpacaBestPct.toFixed(1)}% / ${alpacaWorstPct.toFixed(1)}%` : "—",
      color: "text-amber-400",
      sub: "fleet all-time extremes",
    },
  ];

  // suppress unused warning — summary used for side-effect (react-query prefetch)
  void summary;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-white/5 bg-gradient-to-br from-slate-900/80 to-slate-950/60 p-3">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground/60 mb-1">{s.label}</div>
            <div className={cn("text-base font-mono font-bold truncate", s.color)}>{s.value}</div>
            <div className="text-[8px] text-muted-foreground/40 mt-0.5">{s.sub}</div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-4 px-1">
        <span className="text-[8px] uppercase font-bold tracking-wider text-muted-foreground/30">Equity Trend</span>
        {botSparklines.map((b) => (
          <div key={b.id} className="flex items-center gap-1.5">
            <span className="text-[10px]">{b.icon}</span>
            <MiniSparkline data={b.curve} color={b.accent} />
          </div>
        ))}
      </div>
    </div>
  );
}
