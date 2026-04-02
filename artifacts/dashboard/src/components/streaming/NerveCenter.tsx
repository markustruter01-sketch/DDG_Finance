import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  useKrakenStatus, useOptionsState, useForexState, useStatusSummary,
  useFleetCommanderStatus,
} from "@/hooks/use-trading";

const BOTS = [
  { id: "oracle", name: "Oracle", icon: "🔮", angle: 270, color: "#facc15" },
  { id: "davy-jones", name: "Davy Jones", icon: "⚓", angle: 330, color: "#22d3ee" },
  { id: "blackbeard", name: "Blackbeard", icon: "🏴‍☠️", angle: 30, color: "#f97316" },
  { id: "calypso", name: "Calypso", icon: "🌊", angle: 90, color: "#a78bfa" },
  { id: "apex", name: "Apex Predator", icon: "🎯", angle: 150, color: "#ef4444" },
  { id: "navigator", name: "Navigator", icon: "🧭", angle: 210, color: "#14b8a6" },
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

const GEMINI_THOUGHTS = [
  "Analyzing cross-asset correlation matrix for regime shift signals...",
  "Reviewing 48hr RAG window: 3 losing BTC shorts → adjusting bias...",
  "Fleet capital allocation within risk bounds. No parameter adjustments needed.",
  "Detected elevated VPIN on ETH/USD — flagging for Davy Jones review...",
  "Running post-mortem on Navigator's GBP/USD short: SL hit at 1.5×ATR...",
  "Macro Compass update: USD weakening — bullish bias for EUR, AUD pairs...",
  "Checking Apex Predator capital fence: 3.2% utilized of 5% max...",
  "Oracle regime classification: SIDEWAYS → reducing equity allocation 40%...",
  "Blackbeard momentum scan: SOL/USD Z-score +2.8 → potential entry...",
  "Evaluating fleet-wide drawdown: -0.56% — well within tolerance...",
  "Cross-referencing Fear & Greed Index (42) with BTC on-chain data...",
  "Calypso ATR-based stop recalc: tightening from 2.1× to 1.8× on ARB...",
];

function useAlgoPopups() {
  const [popups, setPopups] = useState<{ id: number; text: string; x: number; y: number }[]>([]);
  const nextId = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      const text = ALGO_SNIPPETS[Math.floor(Math.random() * ALGO_SNIPPETS.length)];
      const id = nextId.current++;
      const x = 30 + Math.random() * 340;
      const y = 30 + Math.random() * 340;
      setPopups((prev) => [...prev.slice(-4), { id, text, x, y }]);
      setTimeout(() => {
        setPopups((prev) => prev.filter((p) => p.id !== id));
      }, 2800);
    }, 1800 + Math.random() * 1200);

    return () => clearInterval(interval);
  }, []);

  return popups;
}

function useGeminiThinking() {
  const [thought, setThought] = useState(GEMINI_THOUGHTS[0]);
  const [key, setKey] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setThought(GEMINI_THOUGHTS[Math.floor(Math.random() * GEMINI_THOUGHTS.length)]);
      setKey((k) => k + 1);
    }, 6000);
    return () => clearInterval(interval);
  }, []);

  return { thought, key };
}

export function NerveCenter() {
  const { data: summary } = useStatusSummary();
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: auditStatus } = useFleetCommanderStatus();

  const botActive: Record<string, boolean> = {
    oracle: !!(summary?.market_open),
    "davy-jones": !!(djStatus.data && djStatus.data.status !== "not_started" && !djStatus.data.bot_paused),
    blackbeard: !!(bbStatus.data && bbStatus.data.status !== "not_started" && !bbStatus.data.bot_paused),
    calypso: !!(caStatus.data && caStatus.data.status !== "not_started" && !caStatus.data.bot_paused),
    apex: !!(optState && !optState.paused),
    navigator: !!(fxState && !fxState.paused),
  };

  const algoPopups = useAlgoPopups();
  const { thought, key: thoughtKey } = useGeminiThinking();

  const cx = 200;
  const cy = 185;
  const radius = 125;

  const activeCount = Object.values(botActive).filter(Boolean).length;

  return (
    <div className="flex flex-col h-full">
      <div className="text-[9px] uppercase tracking-widest text-indigo-400/50 font-bold text-center pt-2">Nerve Center</div>

      <div className="flex-1 flex items-center justify-center relative">
        <svg viewBox="0 0 400 380" className="w-full max-w-md">
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

          <circle cx={cx} cy={cy} r={80} fill="url(#brainGlow)" />
          <circle cx={cx} cy={cy} r={50} fill="url(#brainCore)" />

          <motion.circle
            cx={cx} cy={cy} r={55}
            fill="none"
            stroke="rgba(139,92,246,0.15)"
            strokeWidth={1}
            animate={{ scale: [1, 1.36, 1], opacity: [0.3, 0, 0.3] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeOut" }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />
          <motion.circle
            cx={cx} cy={cy} r={45}
            fill="none"
            stroke="rgba(99,102,241,0.2)"
            strokeWidth={1}
            animate={{ scale: [1, 1.55, 1], opacity: [0.4, 0, 0.4] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeOut", delay: 1.5 }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />
          <motion.circle
            cx={cx} cy={cy} r={40}
            fill="none"
            stroke="rgba(167,139,250,0.12)"
            strokeWidth={1.5}
            animate={{ scale: [1, 2.25, 1], opacity: [0.2, 0, 0.2] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeOut", delay: 0.8 }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />

          <motion.circle
            cx={cx} cy={cy} r={35}
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
            textAnchor="middle" fontSize="24"
            animate={{ scale: [1, 1.1, 1], opacity: [0.8, 1, 0.8] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
            style={{ transformOrigin: `${cx}px ${cy - 5}px` }}
          >
            🧠
          </motion.text>
          <text x={cx} y={cy + 18} textAnchor="middle" fill="rgba(167,139,250,0.8)" fontSize="7" fontWeight="bold">QUANT BRAIN</text>
          <motion.text
            x={cx} y={cy + 28}
            textAnchor="middle" fill="rgba(129,140,248,0.5)" fontSize="6"
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

            return (
              <g key={bot.id}>
                {active && (
                  <>
                    <motion.line
                      x1={cx} y1={cy} x2={bx} y2={by}
                      stroke={bot.color}
                      strokeWidth={2}
                      filter="url(#neonGlow)"
                      animate={{ opacity: [0.2, 0.7, 0.2] }}
                      transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                    />
                    <motion.g
                      animate={{ opacity: [1, 0] }}
                      transition={{ duration: 2, repeat: Infinity, ease: "linear", delay: Math.random() * 2 }}
                    >
                      <motion.circle
                        cx={cx} cy={cy} r={4}
                        fill={bot.color}
                        filter="url(#neonGlow)"
                        animate={{
                          x: [0, bx - cx],
                          y: [0, by - cy],
                        }}
                        transition={{ duration: 2, repeat: Infinity, ease: "linear", delay: Math.random() * 2 }}
                      />
                    </motion.g>
                  </>
                )}
                {!active && (
                  <line
                    x1={cx} y1={cy} x2={bx} y2={by}
                    stroke="rgba(100,116,139,0.15)"
                    strokeWidth={1}
                    strokeDasharray="4 4"
                  />
                )}

                {active && (
                  <motion.circle
                    cx={bx} cy={by} r={28}
                    fill="none"
                    stroke={bot.color}
                    strokeWidth={1}
                    animate={{ opacity: [0.1, 0.4, 0.1], scale: [0.93, 1.14, 0.93] }}
                    transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                    style={{ transformOrigin: `${bx}px ${by}px` }}
                  />
                )}

                <circle
                  cx={bx} cy={by} r={22}
                  fill={active ? `${bot.color}15` : "rgba(30,30,40,0.6)"}
                  stroke={active ? bot.color : "rgba(100,116,139,0.3)"}
                  strokeWidth={active ? 2 : 1}
                  filter={active ? "url(#neonGlow)" : undefined}
                />

                <text x={bx} y={by - 2} textAnchor="middle" fontSize="16">{bot.icon}</text>
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

          <AnimatePresence>
            {algoPopups.map((popup) => (
              <motion.text
                key={popup.id}
                x={popup.x}
                y={popup.y}
                initial={{ opacity: 0, y: popup.y + 10 }}
                animate={{ opacity: 0.6, y: popup.y }}
                exit={{ opacity: 0, y: popup.y - 15 }}
                transition={{ duration: 0.8 }}
                fill="rgba(99,220,241,0.5)"
                fontSize="6.5"
                fontFamily="monospace"
                textAnchor="middle"
              >
                {popup.text}
              </motion.text>
            ))}
          </AnimatePresence>
        </svg>
      </div>

      <div className="px-3 pb-3">
        <div className="rounded-lg border border-violet-500/20 bg-violet-950/20 p-2.5 relative overflow-hidden">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-xs">✨</span>
            <span className="text-[8px] uppercase tracking-widest text-violet-400/70 font-bold">Gemini Fleet Commander — Thinking</span>
            <motion.div
              className="ml-auto flex gap-0.5"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1.2, repeat: Infinity }}
            >
              <span className="h-1 w-1 rounded-full bg-violet-400" />
              <span className="h-1 w-1 rounded-full bg-violet-400" />
              <span className="h-1 w-1 rounded-full bg-violet-400" />
            </motion.div>
          </div>
          <AnimatePresence mode="wait">
            <motion.div
              key={thoughtKey}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.5 }}
              className="text-[10px] font-mono text-violet-300/60 leading-relaxed"
            >
              {thought}
            </motion.div>
          </AnimatePresence>
          {auditStatus?.generated_at && (
            <div className="text-[8px] text-violet-400/30 mt-1 font-mono">
              Last audit: {new Date(auditStatus.generated_at).toLocaleTimeString()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
