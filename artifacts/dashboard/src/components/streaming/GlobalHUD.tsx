import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  useStatusSummary, useKrakenFleetSummary, useOptionsState, useForexState,
  useJournal, useKrakenPerformance, useKrakenStatus,
} from "@/hooks/use-trading";
import { AnimatedValue } from "./AnimatedValue";


const cardVariants = {
  hidden: { opacity: 0, y: -20, scale: 0.95 },
  visible: (i: number) => ({
    opacity: 1, y: 0, scale: 1,
    transition: { delay: i * 0.1, duration: 0.5, ease: [0.22, 1, 0.36, 1] as const },
  }),
};

const C = {
  green: "#4ade80",
  greenDim: "rgba(74,222,128,0.7)",
  orange: "#fb923c",
  orangeDim: "rgba(251,146,60,0.7)",
  cyan: "#22d3ee",
  violet: "#a78bfa",
  violetLight: "#ddd6fe",
  amber: "#fbbf24",
  blue: "#60a5fa",
  emerald: "#34d399",
  yellow: "#facc15",
  white: "#ffffff",
  label: "rgba(148,163,184,0.6)",
  labelDim: "rgba(148,163,184,0.4)",
  labelDimmer: "rgba(148,163,184,0.5)",
  sub: "rgba(148,163,184,0.5)",
  slate300: "rgba(203,213,225,0.9)",
};

const BOT_DEFS = [
  { name: "Oracle", icon: "🔮", color: "#8b5cf6", statusKey: "oracle" as const },
  { name: "Davy Jones", icon: "⚓", color: "#22d3ee", statusKey: "davy-jones" as const },
  { name: "Blackbeard", icon: "🏴‍☠️", color: "#ef4444", statusKey: "blackbeard" as const },
  { name: "Calypso", icon: "🌊", color: "#3b82f6", statusKey: "calypso" as const },
  { name: "Apex", icon: "🎯", color: "#f59e0b", statusKey: "apex" as const },
  { name: "Navigator", icon: "🧭", color: "#a78bfa", statusKey: "navigator" as const },
];

function SleepZzz({ color }: { color: string }) {
  return (
    <div className="absolute z-20" style={{ top: -4, right: 4, pointerEvents: "none" }}>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="absolute font-black"
          style={{
            color: color + "cc",
            fontSize: [13, 17, 11][i],
            left: [0, 14, 26][i],
            top: 0,
            textShadow: `0 0 6px ${color}60`,
          }}
          animate={{
            y: [-4, -30 - i * 8],
            x: [0, 6 + i * 5],
            opacity: [0, 1, 0],
          }}
          transition={{
            duration: 2.5,
            repeat: Infinity,
            delay: i * 0.7,
            ease: "easeOut",
          }}
        >
          z
        </motion.span>
      ))}
    </div>
  );
}

function BotStatusBox({ name, icon, color, active, index }: {
  name: string; icon: string; color: string; active: boolean; index: number;
}) {
  return (
    <motion.div
      custom={index + 4}
      variants={cardVariants}
      initial="hidden"
      animate="visible"
      className="relative rounded-lg bg-slate-900/60"
      style={{
        flex: "1 1 0%",
        minWidth: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        padding: "6px 6px",
        overflow: "visible",
        border: `1px solid ${active ? color + "50" : color + "25"}`,
      }}
    >
      {active && (
        <motion.div
          className="absolute inset-0 rounded-lg"
          style={{
            border: `1.5px solid ${color}`,
            borderRadius: "0.5rem",
          }}
          animate={{
            opacity: [0.2, 0.7, 0.2],
            boxShadow: [
              `0 0 4px ${color}30, inset 0 0 4px ${color}10`,
              `0 0 12px ${color}50, inset 0 0 8px ${color}20`,
              `0 0 4px ${color}30, inset 0 0 4px ${color}10`,
            ],
          }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        />
      )}
      {!active && <SleepZzz color={color} />}
      <span
        className="leading-none relative z-10"
        style={{ fontSize: 14, opacity: active ? 1 : 0.5 }}
      >
        {icon}
      </span>
      <span
        className="text-[9px] font-black uppercase tracking-wider leading-none relative z-10 truncate"
        style={{ color: active ? color : color + "60" }}
      >
        {name}
      </span>
      {active && (
        <motion.span
          className="absolute top-1 right-1.5 h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: color, boxShadow: `0 0 4px ${color}` }}
          animate={{ opacity: [1, 0.3, 1] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        />
      )}
    </motion.div>
  );
}

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

  const pnlColor = grandPnlPct >= 0 ? C.green : C.orange;

  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");

  const botActive = {
    oracle: !!(summary?.auto_trading && summary?.market_open),
    "davy-jones": !!(djStatus.data && djStatus.data.status !== "not_started" && !djStatus.data.bot_paused),
    blackbeard: !!(bbStatus.data && bbStatus.data.status !== "not_started" && !bbStatus.data.bot_paused),
    calypso: !!(caStatus.data && caStatus.data.status !== "not_started" && !caStatus.data.bot_paused),
    apex: optState !== undefined && !optState?.paused,
    navigator: fxState !== undefined && !fxState?.paused,
  };

  const pnlUsd = grandTotal - startTotal;

  return (
    <div className="flex flex-col gap-1.5 shrink-0">
      <div className="flex gap-2">
        <div className="w-1/2 rounded-xl border border-violet-500/20 bg-slate-900/80 px-4 py-2.5 flex flex-col justify-center overflow-hidden">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="space-y-1.5"
          >
            <h2
              className="text-[18px] font-black uppercase tracking-wide leading-tight"
              style={{ color: C.violetLight, textShadow: "0 0 12px rgba(139,92,246,0.4)" }}
            >
              Welcome!
            </h2>
            <p className="text-[15px] leading-[1.5] font-medium" style={{ color: C.slate300 }}>
              Experience the power of our six fully automated, AI-driven trading algorithms. From{" "}
              <span className="font-bold" style={{ color: C.yellow }}>Stocks</span> and{" "}
              <span className="font-bold" style={{ color: C.cyan }}>Crypto</span> to{" "}
              <span className="font-bold" style={{ color: C.violet }}>FOREX</span> and{" "}
              <span className="font-bold" style={{ color: C.orange }}>Futures</span>, our bots handle it all. Want to launch your own? Message us today—no coding or trading experience required.
            </p>
          </motion.div>
        </div>
        <div className="w-1/2 grid grid-cols-2 gap-1.5">
          <motion.div
            custom={0}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className="relative rounded-xl border border-violet-500/20 px-4 py-2 bg-slate-900/80 overflow-hidden flex items-center justify-center"
          >
            <div className={cn("absolute inset-0 bg-gradient-to-br opacity-50 from-violet-500/20 via-violet-500/5 to-transparent")} />
            <motion.span
              className="font-black tracking-widest uppercase leading-none text-center relative z-10"
              style={{ fontSize: 15, color: C.violetLight, textShadow: "0 0 12px rgba(139,92,246,0.6), 0 0 24px rgba(139,92,246,0.3)" }}
              animate={{ textShadow: ["0 0 12px rgba(139,92,246,0.6), 0 0 24px rgba(139,92,246,0.3)", "0 0 20px rgba(139,92,246,0.8), 0 0 40px rgba(139,92,246,0.5)", "0 0 12px rgba(139,92,246,0.6), 0 0 24px rgba(139,92,246,0.3)"] }}
              transition={{ duration: 3, repeat: Infinity }}
            >
              Powered by:{" "}
              <span style={{ color: "#ffffff", textShadow: "0 0 10px rgba(255,255,255,0.4)" }}>DIGITAL DYNAMICS</span>{" "}
              <span style={{ color: C.cyan, textShadow: "0 0 10px rgba(34,211,238,0.5)" }}>Group</span>
            </motion.span>
          </motion.div>

          <motion.div
            custom={1}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className={cn(
              "relative rounded-xl border px-4 py-2 bg-slate-900/80 overflow-hidden flex items-center",
              grandPnlPct >= 0 ? "border-green-500/30" : "border-orange-500/30"
            )}
          >
            <div className={cn("absolute inset-0 bg-gradient-to-br opacity-50", grandPnlPct >= 0 ? "from-green-500/20 via-green-500/5 to-transparent" : "from-orange-500/20 via-orange-500/5 to-transparent")} />
            <div className="relative z-10 flex items-center gap-3 w-full">
              <span className="uppercase tracking-widest font-extrabold shrink-0" style={{ fontSize: 14, color: C.labelDimmer }}>Combined P&L:</span>
              <span className="font-mono font-bold tracking-tight" style={{ fontSize: 22, color: pnlColor }}>
                <AnimatedValue value={`${grandPnlPct >= 0 ? "+" : ""}${grandPnlPct.toFixed(2)}%`} />
              </span>
              <span className="font-mono font-semibold ml-auto" style={{ fontSize: 16, color: pnlColor }}>
                {pnlUsd >= 0 ? "+" : "-"}${Math.abs(pnlUsd).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </span>
            </div>
          </motion.div>

          <motion.div
            custom={2}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className="relative rounded-xl border border-green-500/30 px-4 py-2 bg-slate-900/80 overflow-hidden flex items-center"
          >
            <div className={cn("absolute inset-0 bg-gradient-to-br opacity-50 from-green-500/20 via-green-500/5 to-transparent")} />
            <div className="relative z-10 flex items-center gap-3 w-full">
              <span className="uppercase tracking-widest font-extrabold shrink-0" style={{ fontSize: 14, color: C.labelDimmer }}>Balance:</span>
              <motion.span
                className="font-mono font-bold tracking-tight"
                style={{ fontSize: 24, color: C.green }}
                animate={{ textShadow: ["0 0 8px rgba(34,197,94,0.3)", "0 0 20px rgba(34,197,94,0.6)", "0 0 8px rgba(34,197,94,0.3)"] }}
                transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
              >
                <AnimatedValue value={`$${grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
              </motion.span>
            </div>
          </motion.div>

          <motion.div
            custom={3}
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            className="relative rounded-xl border border-amber-500/30 px-4 py-2 bg-slate-900/80 overflow-hidden flex items-center"
          >
            <div className={cn("absolute inset-0 bg-gradient-to-br opacity-50 from-amber-500/20 via-amber-500/5 to-transparent")} />
            <div className="relative z-10 flex items-center gap-3 w-full">
              <span className="uppercase tracking-widest font-extrabold shrink-0" style={{ fontSize: 14, color: C.labelDimmer }}>Trades:</span>
              <span className="font-mono font-bold tracking-tight" style={{ fontSize: 24, color: C.white }}>
                <AnimatedValue value={`${totalTrades}`} />
              </span>
              <span className="font-mono font-semibold ml-auto" style={{ fontSize: 16, color: C.amber }}>
                {winRate.toFixed(1)}% WR
              </span>
            </div>
          </motion.div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, width: "100%", position: "relative", zIndex: 10 }}>
        {BOT_DEFS.map((bot, i) => (
          <BotStatusBox
            key={bot.statusKey}
            name={bot.name}
            icon={bot.icon}
            color={bot.color}
            active={botActive[bot.statusKey]}
            index={i}
          />
        ))}
      </div>
    </div>
  );
}
