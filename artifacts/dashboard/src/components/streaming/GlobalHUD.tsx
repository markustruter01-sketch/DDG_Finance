import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  useStatusSummary, useKrakenFleetSummary, useOptionsState, useForexState,
  useJournal, useKrakenPerformance, useKrakenStatus,
} from "@/hooks/use-trading";

const cardVariants = {
  hidden: { opacity: 0, y: -20, scale: 0.95 },
  visible: (i: number) => ({
    opacity: 1, y: 0, scale: 1,
    transition: { delay: i * 0.1, duration: 0.5, ease: [0.22, 1, 0.36, 1] as const },
  }),
};

export function GlobalHUD() {
  const { data: summary } = useStatusSummary();
  const { data: fleet } = useKrakenFleetSummary();
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: journal } = useJournal();
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");

  const alpacaEquity = summary?.portfolio_totals?.equity ?? 0;
  const krakenEquity = fleet?.total_equity_usd ?? 0;
  const optionsEquity = optState?.total_equity ?? 100_000;
  const forexEquity = fxState?.total_equity ?? 100_000;
  const grandTotal = alpacaEquity + krakenEquity + optionsEquity + forexEquity;
  const startTotal = 600_000;
  const grandPnlPct = startTotal > 0 ? ((grandTotal - startTotal) / startTotal) * 100 : 0;

  const alpacaWins = journal?.summary?.wins ?? 0;
  const alpacaTotal = journal?.summary?.total ?? 0;
  const krakenWins = [djPerf, bbPerf, caPerf].reduce((s, p) => s + (p.data?.win_count ?? 0), 0);
  const krakenTotal = [djPerf, bbPerf, caPerf].reduce((s, p) => s + (p.data?.total_trades ?? 0), 0);
  const optWins = optState?.total_wins ?? 0;
  const optTotal = optState?.total_trades ?? 0;
  const fxWins = fxState?.total_wins ?? 0;
  const fxTotal = fxState?.total_trades ?? 0;
  const totalWins = alpacaWins + krakenWins + optWins + fxWins;
  const totalTrades = alpacaTotal + krakenTotal + optTotal + fxTotal;
  const winRate = totalTrades > 0 ? (totalWins / totalTrades) * 100 : 0;

  const oracleActive = !!(summary?.market_open);
  const djActive = !!(djStatus.data && djStatus.data.status !== "not_started" && !djStatus.data.bot_paused);
  const bbActive = !!(bbStatus.data && bbStatus.data.status !== "not_started" && !bbStatus.data.bot_paused);
  const caActive = !!(caStatus.data && caStatus.data.status !== "not_started" && !caStatus.data.bot_paused);
  const apexActive = !!(optState && !optState.paused);
  const navActive = !!(fxState && !fxState.paused);
  const activeBots = [oracleActive, djActive, bbActive, caActive, apexActive, navActive].filter(Boolean).length;

  const cards = [
    {
      label: "FLEET STATUS",
      value: `${activeBots}/6 Bots Live`,
      sub: `${activeBots > 0 ? "actively trading" : "standing by"} · 4 capital pools`,
      glow: activeBots > 0 ? "from-green-500/20 via-green-500/5 to-transparent" : "from-amber-500/20 via-amber-500/5 to-transparent",
      border: activeBots > 0 ? "border-green-500/30" : "border-amber-500/30",
    },
    {
      label: "COMBINED P&L",
      value: `${grandPnlPct >= 0 ? "+" : ""}${grandPnlPct.toFixed(2)}%`,
      sub: `$${grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })} fleet total`,
      glow: grandPnlPct >= 0 ? "from-green-500/20 via-green-500/5 to-transparent" : "from-red-500/20 via-red-500/5 to-transparent",
      border: grandPnlPct >= 0 ? "border-green-500/30" : "border-red-500/30",
    },
    {
      label: "VAULT BALANCE",
      value: `$${grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      sub: "available fleet equity",
      glow: "from-cyan-500/20 via-cyan-500/5 to-transparent",
      border: "border-cyan-500/30",
    },
    {
      label: "TRADE ANALYTICS",
      value: `${totalTrades} Trades Total`,
      sub: `${winRate.toFixed(1)}% Win Rate`,
      glow: "from-amber-500/20 via-amber-500/5 to-transparent",
      border: "border-amber-500/30",
    },
  ];

  const drawdownPct = startTotal > 0 ? Math.min(0, ((grandTotal - startTotal) / startTotal) * 100) : 0;
  const profitFactor = totalTrades > 0 && (totalTrades - totalWins) > 0
    ? (totalWins / (totalTrades - totalWins)).toFixed(2) : "—";
  const avgTradeSize = totalTrades > 0
    ? `$${Math.round(grandTotal / Math.max(totalTrades, 1)).toLocaleString()}`
    : "—";
  const riskLevel = Math.abs(drawdownPct) < 1 ? "LOW" : Math.abs(drawdownPct) < 3 ? "MODERATE" : "HIGH";
  const riskColor = riskLevel === "LOW" ? "text-green-400" : riskLevel === "MODERATE" ? "text-amber-400" : "text-red-400";

  const miniMetrics = [
    { label: "MAX DRAWDOWN", value: `${drawdownPct.toFixed(2)}%`, color: drawdownPct === 0 ? "text-green-400" : "text-red-400" },
    { label: "PROFIT FACTOR", value: profitFactor, color: "text-cyan-400" },
    { label: "RISK LEVEL", value: riskLevel, color: riskColor },
    { label: "SHARPE (EST.)", value: winRate > 50 ? ((winRate / 100 * 2 - 1) * 1.5).toFixed(2) : "0.00", color: "text-violet-400" },
    { label: "EXPOSURE", value: `${activeBots}/6 pools`, color: "text-blue-400" },
    { label: "AVG POSITION", value: avgTradeSize, color: "text-amber-400" },
  ];

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {cards.map((card, i) => (
          <motion.div
            key={card.label}
            custom={i}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className={cn(
              "relative rounded-xl border p-4 bg-slate-900/80 overflow-hidden",
              card.border
            )}
          >
            <div className={cn("absolute inset-0 bg-gradient-to-br opacity-50", card.glow)} />
            <div className="relative z-10">
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-bold mb-2">{card.label}</div>
              <div className="text-lg font-mono font-bold text-white tracking-tight">{card.value}</div>
              <div className="text-[10px] text-muted-foreground/50 mt-1 font-mono">{card.sub}</div>
            </div>
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-3 lg:grid-cols-6 gap-2">
        {miniMetrics.map((m, i) => (
          <motion.div
            key={m.label}
            custom={i + 4}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className="rounded-lg border border-white/[0.06] bg-slate-900/60 px-3 py-2"
          >
            <div className="text-[7px] uppercase tracking-widest text-muted-foreground/40 font-bold">{m.label}</div>
            <div className={cn("text-sm font-mono font-bold mt-0.5", m.color)}>{m.value}</div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
