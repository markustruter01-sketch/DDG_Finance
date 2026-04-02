import { motion } from "framer-motion";
import {
  useKrakenStatus, useOptionsState, useForexState, useStatusSummary,
} from "@/hooks/use-trading";

const BOTS = [
  { id: "oracle", name: "Oracle", icon: "🔮", angle: 0, color: "#facc15" },
  { id: "davy-jones", name: "Davy Jones", icon: "⚓", angle: 60, color: "#22d3ee" },
  { id: "blackbeard", name: "Blackbeard", icon: "🏴‍☠️", angle: 120, color: "#f97316" },
  { id: "calypso", name: "Calypso", icon: "🌊", angle: 180, color: "#a78bfa" },
  { id: "apex", name: "Apex Predator", icon: "🎯", angle: 240, color: "#ef4444" },
  { id: "navigator", name: "Navigator", icon: "🧭", angle: 300, color: "#14b8a6" },
];

export function NerveCenter() {
  const { data: summary } = useStatusSummary();
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();

  const botActive: Record<string, boolean> = {
    oracle: !!(summary?.market_open),
    "davy-jones": !!(djStatus.data && djStatus.data.status !== "not_started" && !djStatus.data.bot_paused),
    blackbeard: !!(bbStatus.data && bbStatus.data.status !== "not_started" && !bbStatus.data.bot_paused),
    calypso: !!(caStatus.data && caStatus.data.status !== "not_started" && !caStatus.data.bot_paused),
    apex: !!(optState && !optState.paused),
    navigator: !!(fxState && !fxState.paused),
  };

  const cx = 200;
  const cy = 200;
  const radius = 140;

  return (
    <div className="flex flex-col items-center justify-center h-full">
      <div className="text-[9px] uppercase tracking-widest text-indigo-400/50 font-bold mb-3">Nerve Center</div>
      <svg viewBox="0 0 400 400" className="w-full max-w-md">
        <defs>
          <radialGradient id="brainGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(99,102,241,0.15)" />
            <stop offset="100%" stopColor="rgba(99,102,241,0)" />
          </radialGradient>
          <filter id="neonGlow">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <circle cx={cx} cy={cy} r={60} fill="url(#brainGlow)" />
        <motion.circle
          cx={cx} cy={cy} r={35}
          fill="rgba(99,102,241,0.08)"
          stroke="rgba(129,140,248,0.4)"
          strokeWidth={2}
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        />
        <text x={cx} y={cy - 5} textAnchor="middle" fill="rgba(167,139,250,0.9)" fontSize="22">🧠</text>
        <text x={cx} y={cy + 18} textAnchor="middle" fill="rgba(167,139,250,0.7)" fontSize="8" fontWeight="bold">QUANT BRAIN</text>

        {BOTS.map((bot) => {
          const rad = (bot.angle * Math.PI) / 180;
          const bx = cx + Math.cos(rad) * radius;
          const by = cy + Math.sin(rad) * radius;
          const active = botActive[bot.id] ?? false;

          return (
            <g key={bot.id}>
              <motion.line
                x1={cx} y1={cy} x2={bx} y2={by}
                stroke={active ? bot.color : "rgba(100,116,139,0.2)"}
                strokeWidth={active ? 2 : 1}
                strokeDasharray={active ? "none" : "4 4"}
                animate={active ? { opacity: [0.3, 0.8, 0.3] } : { opacity: 0.2 }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
              />

              {active && (
                <motion.circle
                  cx={bx} cy={by} r={28}
                  fill="none"
                  stroke={bot.color}
                  strokeWidth={1}
                  opacity={0.3}
                  animate={{ opacity: [0.1, 0.4, 0.1] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                />
              )}

              <circle
                cx={bx} cy={by} r={22}
                fill={active ? `${bot.color}15` : "rgba(30,30,40,0.6)"}
                stroke={active ? bot.color : "rgba(100,116,139,0.3)"}
                strokeWidth={active ? 2 : 1}
                filter={active ? "url(#neonGlow)" : undefined}
              />

              <text x={bx} y={by - 2} textAnchor="middle" fontSize="16">
                {bot.icon}
              </text>
              <text
                x={bx} y={by + 14}
                textAnchor="middle"
                fill={active ? bot.color : "rgba(100,116,139,0.5)"}
                fontSize="6"
                fontWeight="bold"
              >
                {bot.name.toUpperCase()}
              </text>

              {!active && (
                <text x={bx + 18} y={by - 14} fontSize="10">💤</text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
