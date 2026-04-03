import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  useStatusSummary, useKrakenFleetSummary, useOptionsState, useForexState,
  useJournal, useKrakenPerformance, useKrakenStatus,
} from "@/hooks/use-trading";
import { AnimatedValue } from "./AnimatedValue";
import ddgLogo from "@assets/DDG_Logo_1775195516809.png";

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

  const alpacaEquity = summary?.portfolio_totals?.equity != null
    ? summary.portfolio_totals.equity
    : 100_000;

  const krakenEquity = fleet?.total_equity_usd != null && fleet.total_equity_usd > 0
    ? fleet.total_equity_usd
    : (fleet?.total_starting_usd ?? 300_000);

  const optionsEquity = optState?.total_equity != null ? optState.total_equity : 100_000;
  const forexEquity = fxState?.total_equity != null ? fxState.total_equity : 100_000;
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

  const cards = [
    {
      label: "POWERED_BY_LOGO",
      value: "",
      sub: "",
      glow: "from-violet-500/20 via-violet-500/5 to-transparent",
      border: "border-violet-500/30",
      isLogo: true,
    },
    {
      label: "COMBINED P&L",
      isCombinedPnl: true,
      value: `${grandPnlPct >= 0 ? "+" : ""}${grandPnlPct.toFixed(2)}%`,
      dailyPct: `${grandPnlPct >= 0 ? "+" : ""}${grandPnlPct.toFixed(2)}%`,
      dailyUsd: `${grandTotal - startTotal >= 0 ? "+" : "-"}$${Math.abs(grandTotal - startTotal).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      sub: "",
      glow: grandPnlPct >= 0 ? "from-green-500/20 via-green-500/5 to-transparent" : "from-orange-500/20 via-orange-500/5 to-transparent",
      border: grandPnlPct >= 0 ? "border-green-500/30" : "border-orange-500/30",
    },
    {
      label: "PLATFORM BALANCE",
      value: `$${grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      sub: `${grandPnlPct >= 0 ? "+" : ""}${grandPnlPct.toFixed(2)}% daily P&L`,
      glow: "from-green-500/20 via-green-500/5 to-transparent",
      border: "border-green-500/30",
      valueColor: "text-green-400",
      isPlatformBalance: true,
    },
    {
      label: "TRADE ANALYTICS",
      value: `${totalTrades} Trades Total`,
      sub: `${winRate.toFixed(1)}% Win Rate`,
      glow: "from-amber-500/20 via-amber-500/5 to-transparent",
      border: "border-amber-500/30",
    },
  ];

  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");

  const activePools = [
    summary?.auto_trading !== undefined,
    djStatus.data && djStatus.data.status !== "not_started" && !djStatus.data.bot_paused,
    bbStatus.data && bbStatus.data.status !== "not_started" && !bbStatus.data.bot_paused,
    caStatus.data && caStatus.data.status !== "not_started" && !caStatus.data.bot_paused,
    optState !== undefined,
    fxState !== undefined,
  ].filter(Boolean).length;

  const drawdownPct = startTotal > 0 ? Math.min(0, ((grandTotal - startTotal) / startTotal) * 100) : 0;
  const profitFactor = totalTrades > 0 && (totalTrades - totalWins) > 0
    ? (totalWins / (totalTrades - totalWins)).toFixed(2) : "—";
  const avgTradeSize = totalTrades > 0
    ? `$${Math.round(grandTotal / Math.max(totalTrades, 1)).toLocaleString()}`
    : "—";
  const riskLevel = Math.abs(drawdownPct) < 1 ? "LOW" : Math.abs(drawdownPct) < 3 ? "MODERATE" : "HIGH";
  const riskColor = riskLevel === "LOW" ? "text-green-400" : riskLevel === "MODERATE" ? "text-amber-400" : "text-orange-400";

  const miniMetrics = [
    { label: "MAX DRAWDOWN", value: `${drawdownPct.toFixed(2)}%`, color: drawdownPct === 0 ? "text-green-400" : "text-orange-400" },
    { label: "PROFIT FACTOR", value: profitFactor, color: "text-cyan-400" },
    { label: "RISK LEVEL", value: riskLevel, color: riskColor },
    { label: "SHARPE (EST.)", value: totalTrades > 0 ? ((totalWins / totalTrades * 2 - 1) * 1.5).toFixed(2) : "—", color: "text-violet-400" },
    { label: "EXPOSURE", value: `${activePools}/6 pools`, color: "text-blue-400" },
    { label: "AVG POSITION", value: avgTradeSize, color: "text-amber-400" },
  ];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex gap-2">
        <div className="w-1/2 rounded-xl border border-white/[0.06] bg-slate-900/60 min-h-0" />
        <div className="w-1/2 grid grid-cols-2 lg:grid-cols-4 gap-2">
        {cards.map((card, i) => (
          <motion.div
            key={card.label}
            custom={i}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className={cn(
              "relative rounded-xl border p-3 bg-slate-900/80 overflow-hidden",
              card.border
            )}
          >
            <div className={cn("absolute inset-0 bg-gradient-to-br opacity-50", card.glow)} />
            <div className="relative z-10">
              {"isLogo" in card && card.isLogo ? (
                <div className="flex items-center justify-between h-full min-h-[48px] w-full py-1 pl-1 pr-1">
                  <motion.span
                    className="text-[22px] font-black tracking-wider uppercase text-violet-200 shrink-0 leading-tight"
                    style={{ textShadow: "0 0 12px rgba(139,92,246,0.6), 0 0 24px rgba(139,92,246,0.3)" }}
                    animate={{ textShadow: ["0 0 12px rgba(139,92,246,0.6), 0 0 24px rgba(139,92,246,0.3)", "0 0 20px rgba(139,92,246,0.8), 0 0 40px rgba(139,92,246,0.5)", "0 0 12px rgba(139,92,246,0.6), 0 0 24px rgba(139,92,246,0.3)"] }}
                    transition={{ duration: 3, repeat: Infinity }}
                  >
                    Powered<br/>by
                  </motion.span>
                  <img src={ddgLogo} alt="Digital Dynamics Group" className="h-[74px] w-auto object-contain" />
                </div>
              ) : "isCombinedPnl" in card && card.isCombinedPnl ? (
                <>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] uppercase tracking-widest text-muted-foreground/60 font-bold">{card.label}</span>
                    <span className="text-[9px] uppercase tracking-widest text-muted-foreground/40 font-bold">Daily PnL</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className={cn("text-[22px] font-mono font-bold tracking-tight leading-none", grandPnlPct >= 0 ? "text-green-400" : "text-orange-400")}>
                      <AnimatedValue value={card.value} />
                    </div>
                    <div className="flex flex-col items-end">
                      <span className={cn("text-[13px] font-mono font-bold leading-tight", grandPnlPct >= 0 ? "text-green-400" : "text-orange-400")}>
                        {card.dailyPct}
                      </span>
                      <span className={cn("text-[11px] font-mono font-semibold leading-tight", grandPnlPct >= 0 ? "text-green-400/70" : "text-orange-400/70")}>
                        {card.dailyUsd}
                      </span>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="text-[11px] uppercase tracking-widest text-muted-foreground/60 font-bold mb-1">{card.label}</div>
                  {"isPlatformBalance" in card && card.isPlatformBalance ? (
                    <motion.div
                      className={cn("text-2xl font-mono font-bold tracking-tight", "valueColor" in card && card.valueColor ? card.valueColor : "text-white")}
                      animate={{ textShadow: ["0 0 8px rgba(34,197,94,0.3)", "0 0 20px rgba(34,197,94,0.6)", "0 0 8px rgba(34,197,94,0.3)"], scale: [1, 1.02, 1] }}
                      transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                    >
                      <AnimatedValue value={card.value} />
                    </motion.div>
                  ) : (
                    <div className={cn("text-2xl font-mono font-bold tracking-tight", "valueColor" in card && card.valueColor ? card.valueColor : "text-white")}>
                      <AnimatedValue value={card.value} />
                    </div>
                  )}
                  {card.sub && (
                    <div className="text-[11px] text-muted-foreground/50 mt-0.5 font-mono">
                      <AnimatedValue value={card.sub} />
                    </div>
                  )}
                </>
              )}
            </div>
          </motion.div>
        ))}
        </div>
      </div>

      <div className="grid grid-cols-3 lg:grid-cols-6 gap-1.5">
        {miniMetrics.map((m, i) => (
          <motion.div
            key={m.label}
            custom={i + 4}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className="rounded-lg border border-white/[0.06] bg-slate-900/60 px-2.5 py-1.5"
          >
            <div className="text-[9px] uppercase tracking-widest text-muted-foreground/40 font-bold">{m.label}</div>
            <div className={cn("text-sm font-mono font-bold mt-0.5", m.color)}>
              <AnimatedValue value={m.value} />
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
