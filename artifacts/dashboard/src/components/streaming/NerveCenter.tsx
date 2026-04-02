import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  useKrakenStatus, useOptionsState, useForexState, useStatusSummary,
} from "@/hooks/use-trading";

const BOTS = [
  { id: "oracle", name: "Oracle", subtitle: "Stocks Bot", icon: "🔮", angle: 270, color: "#facc15" },
  { id: "davy-jones", name: "Davy Jones", subtitle: "Crypto Bot #1", icon: "⚓", angle: 330, color: "#22d3ee" },
  { id: "blackbeard", name: "Blackbeard", subtitle: "Crypto Bot #2", icon: "🏴‍☠️", angle: 30, color: "#f97316" },
  { id: "calypso", name: "Calypso", subtitle: "Crypto Bot #3", icon: "🌊", angle: 90, color: "#a78bfa" },
  { id: "apex", name: "Apex Predator", subtitle: "Options Bot", icon: "🎯", angle: 150, color: "#ef4444" },
  { id: "navigator", name: "Navigator", subtitle: "Forex Bot", icon: "🧭", angle: 210, color: "#14b8a6" },
];

const ALGO_SNIPPETS = [
  "RSI(14) = 32.7 → oversold",
  "VWAP deviation +1.2σ",
  "ATR(14) = $2.41",
  "Kelly f* = 0.18",
  "Sharpe Ratio: 1.87",
  "Bollinger squeeze: true",
  "MACD cross → bullish",
  "IVR = 14.2 → low vol",
  "EMA(21) > EMA(50)",
  "Position risk: 1.3%",
  "Max drawdown: -2.4%",
  "Correlation ρ = 0.12",
  "Vol surface: flat",
  "Momentum Z = +2.1",
  "Regime: BULL → risk-on",
  "Signal consensus: 3/4",
  "Sortino Ratio: 2.34",
  "Win rate: 58.3%",
  "Entropy decay: 0.04",
  "Half-Kelly sizing: $840",
];

const CORNER_POSITIONS = [
  { x: 12, y: 8 },
  { x: 88, y: 8 },
  { x: 12, y: 88 },
  { x: 88, y: 88 },
  { x: 12, y: 48 },
  { x: 88, y: 48 },
];

function useAlgoPopups() {
  const [popups, setPopups] = useState<{ id: number; text: string; x: number; y: number }[]>([]);
  const nextId = useRef(0);
  const cornerIdx = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      const text = ALGO_SNIPPETS[Math.floor(Math.random() * ALGO_SNIPPETS.length)];
      const id = nextId.current++;
      const corner = CORNER_POSITIONS[cornerIdx.current % CORNER_POSITIONS.length];
      cornerIdx.current++;
      setPopups((prev) => [...prev.slice(-3), { id, text, x: corner.x, y: corner.y }]);
      setTimeout(() => {
        setPopups((prev) => prev.filter((p) => p.id !== id));
      }, 2800);
    }, 1800 + Math.random() * 1200);

    return () => clearInterval(interval);
  }, []);

  return popups;
}


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

  const algoPopups = useAlgoPopups();
  const [scanY, setScanY] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setScanY((prev) => (prev >= 100 ? 0 : prev + 0.5));
    }, 30);
    return () => clearInterval(interval);
  }, []);

  const cx = 200;
  const cy = 160;
  const radius = 110;

  const activeCount = Object.values(botActive).filter(Boolean).length;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="text-[9px] uppercase tracking-widest text-indigo-400/50 font-bold text-center pt-1 shrink-0">Nerve Center</div>

      <div className="flex-1 flex items-center justify-center relative p-2 min-h-0 overflow-hidden">
        <div
          className="absolute left-0 right-0 pointer-events-none z-20"
          style={{
            top: `${scanY}%`,
            height: "2px",
            background: "linear-gradient(90deg, transparent, rgba(34,211,238,0.2), rgba(34,211,238,0.4), rgba(34,211,238,0.2), transparent)",
            boxShadow: "0 0 6px rgba(34,211,238,0.25), 0 0 14px rgba(34,211,238,0.1)",
            transition: "top 30ms linear",
          }}
        />
        <div
          className="absolute left-0 right-0 pointer-events-none z-20"
          style={{
            top: `${scanY}%`,
            height: "30px",
            background: "linear-gradient(180deg, rgba(34,211,238,0.03), transparent)",
            transform: "translateY(-100%)",
          }}
        />

        <svg viewBox="0 0 400 380" className="w-full h-full max-w-full max-h-full" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="brainGlow" cx="50%" cy="48%" r="50%">
              <stop offset="0%" stopColor="rgba(99,102,241,0.2)" />
              <stop offset="50%" stopColor="rgba(139,92,246,0.08)" />
              <stop offset="100%" stopColor="rgba(99,102,241,0)" />
            </radialGradient>
            <radialGradient id="brainCore" cx="50%" cy="48%" r="30%">
              <stop offset="0%" stopColor="rgba(167,139,250,0.25)" />
              <stop offset="100%" stopColor="rgba(99,102,241,0)" />
            </radialGradient>
            <filter id="neonGlow">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="heavyGlow">
              <feGaussianBlur stdDeviation="8" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          <circle cx={cx} cy={cy} r={85} fill="url(#brainGlow)" />
          <circle cx={cx} cy={cy} r={55} fill="url(#brainCore)" />

          <motion.circle
            cx={cx} cy={cy} r={58}
            fill="none"
            stroke="rgba(139,92,246,0.15)"
            strokeWidth={1}
            animate={{ scale: [1, 1.36, 1], opacity: [0.3, 0, 0.3] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeOut" }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />
          <motion.circle
            cx={cx} cy={cy} r={48}
            fill="none"
            stroke="rgba(99,102,241,0.2)"
            strokeWidth={1}
            animate={{ scale: [1, 1.55, 1], opacity: [0.4, 0, 0.4] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeOut", delay: 1.5 }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />
          <motion.circle
            cx={cx} cy={cy} r={42}
            fill="none"
            stroke="rgba(167,139,250,0.12)"
            strokeWidth={1.5}
            animate={{ scale: [1, 2.25, 1], opacity: [0.2, 0, 0.2] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeOut", delay: 0.8 }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />

          <motion.circle
            cx={cx} cy={cy} r={38}
            fill="rgba(99,102,241,0.06)"
            stroke="rgba(129,140,248,0.5)"
            strokeWidth={2}
            filter="url(#heavyGlow)"
            animate={{ opacity: [0.5, 1, 0.5], scale: [0.97, 1.03, 0.97] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />

          <motion.text
            x={cx} y={cy - 5}
            textAnchor="middle" fontSize="30"
            animate={{ scale: [1, 1.1, 1], opacity: [0.8, 1, 0.8] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
            style={{ transformOrigin: `${cx}px ${cy - 5}px` }}
          >
            🧠
          </motion.text>
          <text x={cx} y={cy + 22} textAnchor="middle" fill="rgba(167,139,250,0.8)" fontSize="8" fontWeight="bold">QUANT BRAIN</text>
          <motion.text
            x={cx} y={cy + 33}
            textAnchor="middle" fill="rgba(129,140,248,0.5)" fontSize="7"
            animate={{ opacity: [0.3, 0.7, 0.3] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          >
            {activeCount}/6 NODES ACTIVE
          </motion.text>

          {BOTS.map((bot) => {
            const rad = (bot.angle * Math.PI) / 180;
            const bx = cx + Math.cos(rad) * radius;
            const by = cy + Math.sin(rad) * radius;
            const active = botActive[bot.id] ?? false;

            const dx = bx - cx;
            const dy = by - cy;
            const midX = cx + dx;
            const midY = cy;
            const orthoPath = Math.abs(dx) > Math.abs(dy)
              ? `M ${cx} ${cy} L ${midX} ${midY} L ${bx} ${by}`
              : `M ${cx} ${cy} L ${cx} ${by} L ${bx} ${by}`;

            return (
              <g key={bot.id}>
                {active && (
                  <>
                    <motion.path
                      d={orthoPath}
                      stroke={bot.color}
                      strokeWidth={2}
                      fill="none"
                      filter="url(#neonGlow)"
                      animate={{ opacity: [0.2, 0.7, 0.2] }}
                      transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                    />
                    <motion.circle
                      r={4}
                      fill={bot.color}
                      filter="url(#neonGlow)"
                    >
                      <animateMotion
                        dur="2s"
                        repeatCount="indefinite"
                        path={orthoPath}
                      />
                    </motion.circle>
                  </>
                )}
                {!active && (
                  <path
                    d={orthoPath}
                    stroke="rgba(100,116,139,0.35)"
                    strokeWidth={1}
                    strokeDasharray="6 4"
                    fill="none"
                  />
                )}

                {active && (
                  <motion.circle
                    cx={bx} cy={by} r={30}
                    fill="none"
                    stroke={bot.color}
                    strokeWidth={1}
                    animate={{ opacity: [0.1, 0.4, 0.1], scale: [0.93, 1.14, 0.93] }}
                    transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                    style={{ transformOrigin: `${bx}px ${by}px` }}
                  />
                )}

                <circle
                  cx={bx} cy={by} r={24}
                  fill={active ? `${bot.color}15` : "rgba(30,30,40,0.6)"}
                  stroke={active ? bot.color : "rgba(100,116,139,0.3)"}
                  strokeWidth={active ? 2.5 : 1}
                  filter={active ? "url(#neonGlow)" : undefined}
                />

                <text x={bx} y={by + 5} textAnchor="middle" fontSize="18">{bot.icon}</text>
                <text
                  x={bx} y={by + 35}
                  textAnchor="middle"
                  fill={active ? bot.color : "rgba(100,116,139,0.5)"}
                  fontSize="6.5"
                  fontWeight="bold"
                >
                  {bot.name.toUpperCase()}
                </text>
                <text
                  x={bx} y={by + 44}
                  textAnchor="middle"
                  fill={active ? `${bot.color}99` : "rgba(100,116,139,0.35)"}
                  fontSize="5"
                >
                  ({bot.subtitle})
                </text>

                {!active && (
                  <text x={bx + 20} y={by - 15} fontSize="11">💤</text>
                )}
              </g>
            );
          })}

        </svg>

        <AnimatePresence>
          {algoPopups.map((popup) => (
            <motion.div
              key={popup.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.8 }}
              className="absolute pointer-events-none font-mono font-bold text-white tracking-wide"
              style={{
                left: `${popup.x}%`,
                top: `${popup.y}%`,
                transform: "translate(-50%, -50%)",
                fontSize: "11px",
                textShadow: "0 0 12px rgba(99,220,241,0.8), 0 0 30px rgba(99,220,241,0.4)",
                whiteSpace: "nowrap",
              }}
            >
              {popup.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

    </div>
  );
}
