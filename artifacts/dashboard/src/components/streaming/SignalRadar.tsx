import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  useKrakenStatus, useOptionsState, useForexState, useStatusSummary,
  useLivePositions,
} from "@/hooks/use-trading";

const slotVariants = {
  hidden: { opacity: 0, x: 20 },
  visible: (i: number) => ({
    opacity: 1, x: 0,
    transition: { delay: 0.3 + i * 0.08, duration: 0.4, ease: [0.22, 1, 0.36, 1] as const },
  }),
};

export function SignalRadar() {
  const { data: summary } = useStatusSummary();
  const { data: positions } = useLivePositions();
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();

  const alpacaCount = positions?.positions?.length ?? 0;
  const djPos = djStatus.data?.position_count ?? 0;
  const bbPos = bbStatus.data?.position_count ?? 0;
  const caPos = caStatus.data?.position_count ?? 0;
  const optPos = optState?.positions_count ?? 0;
  const fxPos = fxState?.position_count ?? 0;

  const djSignal = djStatus.data?.signals?.[0];
  const bbSignal = bbStatus.data?.signals?.[0];
  const caSignal = caStatus.data?.signals?.[0];

  const slots = [
    {
      name: "Oracle",
      icon: "🔮",
      active: !!(summary?.market_open),
      signal: alpacaCount > 0 ? `⚡ Holding ${alpacaCount} position${alpacaCount > 1 ? "s" : ""}` : "Scanning for setups...",
      color: "#facc15",
    },
    {
      name: "Davy Jones",
      icon: "⚓",
      active: !!(djStatus.data && djStatus.data.status !== "not_started" && !djStatus.data.bot_paused),
      signal: djSignal ? `⚡ ${djSignal.symbol} RSI ${djSignal.rsi}` : djPos > 0 ? `Holding ${djPos} position${djPos > 1 ? "s" : ""}` : "Scanning crypto...",
      color: "#22d3ee",
    },
    {
      name: "Blackbeard",
      icon: "🏴‍☠️",
      active: !!(bbStatus.data && bbStatus.data.status !== "not_started" && !bbStatus.data.bot_paused),
      signal: bbSignal ? `⚡ ${bbSignal.symbol} RSI ${bbSignal.rsi}` : bbPos > 0 ? `Holding ${bbPos} position${bbPos > 1 ? "s" : ""}` : "Scanning crypto...",
      color: "#f97316",
    },
    {
      name: "Calypso",
      icon: "🌊",
      active: !!(caStatus.data && caStatus.data.status !== "not_started" && !caStatus.data.bot_paused),
      signal: caSignal ? `⚡ ${caSignal.symbol} RSI ${caSignal.rsi}` : caPos > 0 ? `Holding ${caPos} position${caPos > 1 ? "s" : ""}` : "Scanning crypto...",
      color: "#a78bfa",
    },
    {
      name: "Apex Predator",
      icon: "🎯",
      active: !!(optState && !optState.paused),
      signal: optPos > 0 ? `⚡ ${optPos} active spread${optPos > 1 ? "s" : ""}` : "💤 Awaiting options setup",
      color: "#ef4444",
    },
    {
      name: "Navigator",
      icon: "🧭",
      active: !!(fxState && !fxState.paused),
      signal: fxPos > 0 ? `⚡ ${fxPos} FX position${fxPos > 1 ? "s" : ""}` : fxState?.news_blackout ? "⚠️ News blackout" : "Scanning H4...",
      color: "#14b8a6",
    },
  ];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-[9px] uppercase tracking-widest text-cyan-400/50 font-bold">Signal Radar</div>
      {slots.map((slot, i) => (
        <motion.div
          key={slot.name}
          custom={i}
          variants={slotVariants}
          initial="hidden"
          animate="visible"
          className={cn(
            "rounded-lg border px-2.5 py-1.5 transition-all",
            slot.active
              ? "border-white/10 bg-slate-900/80"
              : "border-white/5 bg-slate-950/60 opacity-50"
          )}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs">{slot.icon}</span>
            <span className="text-[10px] font-bold text-white uppercase tracking-wide">{slot.name}</span>
            <span className={cn("text-[9px] font-mono ml-auto truncate max-w-[55%] text-right", slot.active ? "text-muted-foreground/60" : "text-muted-foreground/30")}>
              {slot.active ? slot.signal : `💤 Sleeping`}
            </span>
            {slot.active && (
              <motion.div
                className="h-1.5 w-1.5 rounded-full shrink-0"
                style={{ backgroundColor: slot.color }}
                animate={{ opacity: [0.4, 1, 0.4], scale: [0.9, 1.1, 0.9] }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
              />
            )}
          </div>
        </motion.div>
      ))}
    </div>
  );
}
