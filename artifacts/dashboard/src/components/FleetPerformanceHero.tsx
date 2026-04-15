import { useMemo } from "react";
import { cn, formatCurrency } from "@/lib/utils";
import {
  useStatusSummary, useKrakenFleetSummary, useJournal, usePerformanceHistory,
  useKrakenPerformance, useKrakenStatus, useOptionsState, useForexState,
  usePoseidonState, useKrakenCurrentState,
} from "@/hooks/use-trading";
import { BOT_THEMES, MiniSparkline, type KrakenTradeEntry } from "@/lib/dashboard-shared";

export function FleetPerformanceHero() {
  const { data: summary } = useStatusSummary();
  const { data: fleetSummary } = useKrakenFleetSummary();
  const { data: journal } = useJournal();
  const { data: perfHistory } = usePerformanceHistory();
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: poseidonState } = usePoseidonState();
  const { data: kcState } = useKrakenCurrentState();
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");

  const alpacaEquity = summary?.portfolio_totals.equity ?? 0;
  const krakenFleetEquity = fleetSummary?.total_equity_usd ?? 0;
  const optionsEquity = optState?.total_equity ?? 100_000;
  const forexEquity = fxState?.total_equity ?? 100_000;
  const poseidonEquity = poseidonState?.total_equity ?? 100_000;
  const kcEquity = kcState?.total_equity ?? 100_000;
  // krakenFleetEquity now includes Poseidon (#7) and Kraken Current (#8) — don't add them again
  const grandTotal = alpacaEquity + krakenFleetEquity + optionsEquity + forexEquity;

  const alpacaWins = journal?.summary?.wins ?? 0;
  const alpacaTotal = journal?.summary?.total ?? 0;

  const botPerfList = [
    { id: "davy-jones", perf: djPerf.data, status: djStatus.data },
    { id: "blackbeard", perf: bbPerf.data, status: bbStatus.data },
    { id: "calypso", perf: caPerf.data, status: caStatus.data },
  ];
  const allPerfs = botPerfList.map(b => b.perf).filter(Boolean);
  const krakenWins = allPerfs.reduce((s, p) => s + (p?.win_count ?? 0), 0);
  const krakenTotal = allPerfs.reduce((s, p) => s + (p?.total_trades ?? 0), 0);

  const optionsWins = optState?.total_wins ?? 0;
  const optionsTotal = optState?.total_trades ?? 0;
  const forexWins = fxState?.total_wins ?? 0;
  const forexTotal = fxState?.total_trades ?? 0;

  const totalWins = alpacaWins + krakenWins + optionsWins + forexWins;
  const totalTrades = alpacaTotal + krakenTotal + optionsTotal + forexTotal;
  const combinedWinRate = totalTrades > 0 ? (totalWins / totalTrades) * 100 : null;

  const alpacaBestPct = journal?.trades?.length
    ? Math.max(0, ...journal.trades.map(t => t.pnl_percentage ?? 0))
    : 0;
  const alpacaWorstPct = journal?.trades?.length
    ? Math.min(0, ...journal.trades.map(t => t.pnl_percentage ?? 0))
    : 0;
  const krakenBestPct = Math.max(0, ...allPerfs.map(p => p?.best_trade_pct ?? 0));
  const krakenWorstPct = Math.min(0, ...allPerfs.map(p => p?.worst_trade_pct ?? 0));
  const bestKrakenPct = Math.max(alpacaBestPct, krakenBestPct);
  const worstKrakenPct = Math.min(alpacaWorstPct, krakenWorstPct);

  const todayStr = new Date().toISOString().slice(0, 10);

  const todayPerformers = useMemo(() => {
    type Performer = { name: string; icon: string; dailyPnl: number };
    const results: Performer[] = [];

    botPerfList.forEach((b) => {
      const trades = b.perf?.recent_trades ?? [];
      const theme = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      const todayTrades = trades.filter((t: KrakenTradeEntry) => t.closed_at?.startsWith(todayStr));
      const dailyPnl = todayTrades.reduce((sum: number, t: KrakenTradeEntry) => sum + (t.pnl_pct ?? 0), 0);
      results.push({ name: b.status?.bot_name ?? b.id, icon: theme.icon, dailyPnl });
    });

    const oracleTodayTrades = journal?.trades?.filter(t => t.date?.startsWith(todayStr)) ?? [];
    const oracleDailyPnl = oracleTodayTrades.reduce((sum, t) => sum + (t.pnl_percentage ?? 0), 0);
    results.push({ name: "Oracle", icon: "🔮", dailyPnl: oracleDailyPnl });

    const optionsPnlToday = optState?.total_pnl ?? 0;
    results.push({ name: "Apex Predator", icon: "🎯", dailyPnl: optionsPnlToday > 0 ? optionsPnlToday : 0 });

    const forexPnlToday = fxState?.total_pnl ?? 0;
    results.push({ name: "Navigator", icon: "🧭", dailyPnl: forexPnlToday > 0 ? forexPnlToday : 0 });

    const poseidonPnl = poseidonState?.total_pnl ?? 0;
    results.push({ name: "Poseidon", icon: "🔱", dailyPnl: poseidonPnl });

    const kcPnl = kcState?.total_pnl ?? 0;
    results.push({ name: "Kraken Current", icon: "🌊", dailyPnl: kcPnl });

    const sorted = [...results].sort((a, b) => b.dailyPnl - a.dailyPnl);
    const best = sorted[0] ?? null;
    const worst = sorted[sorted.length - 1] ?? null;
    return { best, worst };
  }, [djPerf.data, bbPerf.data, caPerf.data, journal, todayStr, optState, fxState]);

  const botSparklines = useMemo(() => {
    const krakenLines = botPerfList.map((b) => {
      const trades = b.perf?.recent_trades ?? [];
      const theme = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      let cum = 0;
      const curve = [0, ...trades.map((t: KrakenTradeEntry) => { cum += (t.pnl_pct ?? 0); return cum; })];
      return { id: b.id, name: b.status?.bot_name ?? b.id, icon: theme.icon, accent: theme.accent, curve };
    });

    const oracleSnapshots = perfHistory?.snapshots ?? [];
    const oracleCurve = oracleSnapshots.length > 1
      ? oracleSnapshots.slice(-20).map(s => s.cumulative_pnl_pct)
      : [0];
    krakenLines.unshift({ id: "oracle", name: "Oracle", icon: "🔮", accent: "#facc15", curve: oracleCurve });
    const optPnl = optState?.total_pnl ?? 0;
    const optEquity = optState?.total_equity ?? 100_000;
    const optPct = optEquity > 0 ? (optPnl / optEquity) * 100 : 0;
    krakenLines.push({ id: "options", name: "Apex", icon: "🎯", accent: "#ef4444", curve: optPct !== 0 ? [0, optPct * 0.3, optPct * 0.6, optPct * 0.8, optPct] : [0] });

    const fxPnl = fxState?.total_pnl ?? 0;
    const fxEquity = fxState?.total_equity ?? 100_000;
    const fxPct = fxEquity > 0 ? (fxPnl / fxEquity) * 100 : 0;
    krakenLines.push({ id: "forex", name: "Navigator", icon: "🧭", accent: "#14b8a6", curve: fxPct !== 0 ? [0, fxPct * 0.25, fxPct * 0.5, fxPct * 0.75, fxPct] : [0] });

    const psPnl = poseidonState?.total_pnl ?? 0;
    const psEq = poseidonState?.total_equity ?? 100_000;
    const psPct = psEq > 0 ? (psPnl / psEq) * 100 : 0;
    krakenLines.push({ id: "poseidon", name: "Poseidon", icon: "🔱", accent: "#8b5cf6", curve: psPct !== 0 ? [0, psPct * 0.25, psPct * 0.5, psPct * 0.75, psPct] : [0] });

    const kcPnlVal = kcState?.total_pnl ?? 0;
    const kcEqVal = kcState?.total_equity ?? 100_000;
    const kcPct = kcEqVal > 0 ? (kcPnlVal / kcEqVal) * 100 : 0;
    krakenLines.push({ id: "kraken-current", name: "KC", icon: "🌊", accent: "#06b6d4", curve: kcPct !== 0 ? [0, kcPct * 0.25, kcPct * 0.5, kcPct * 0.75, kcPct] : [0] });

    return krakenLines;
  }, [djPerf.data, bbPerf.data, caPerf.data, perfHistory, optState, fxState, poseidonState, kcState]);

  // fleet-summary has 5 bots (DJ+BB+Cal+Poseidon+KC) + 3 external (Oracle, Apex, Navigator)
  const botCount = (fleetSummary?.bot_count ?? 5) + 3;
  const stats = [
    { label: "Fleet Equity", value: formatCurrency(grandTotal), color: "text-white", sub: `${botCount} bots · 6 capital pools` },
    { label: "Total Trades", value: String(totalTrades), color: "text-white", sub: `${totalWins}W / ${totalTrades - totalWins}L` },
    { label: "Fleet Win Rate", value: combinedWinRate != null ? `${combinedWinRate.toFixed(1)}%` : "—", color: combinedWinRate != null && combinedWinRate >= 50 ? "text-green-400" : "text-amber-400", sub: "all bots combined" },
    { label: "Best Today", value: todayPerformers.best ? `${todayPerformers.best.icon} ${todayPerformers.best.name}` : "—", color: "text-green-400", sub: todayPerformers.best ? `${todayPerformers.best.dailyPnl >= 0 ? "+" : ""}${todayPerformers.best.dailyPnl.toFixed(2)}% daily P&L` : "no trades today" },
    { label: "Worst Today", value: todayPerformers.worst ? `${todayPerformers.worst.icon} ${todayPerformers.worst.name}` : "—", color: todayPerformers.worst && todayPerformers.worst.dailyPnl < 0 ? "text-red-400" : "text-muted-foreground", sub: todayPerformers.worst ? `${todayPerformers.worst.dailyPnl >= 0 ? "+" : ""}${todayPerformers.worst.dailyPnl.toFixed(2)}% daily P&L` : "no trades today" },
    { label: "Best/Worst Trade", value: bestKrakenPct > 0 || worstKrakenPct < 0 ? `+${bestKrakenPct.toFixed(1)}% / ${worstKrakenPct.toFixed(1)}%` : "—", color: "text-amber-400", sub: "fleet all-time extremes" },
  ];

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
