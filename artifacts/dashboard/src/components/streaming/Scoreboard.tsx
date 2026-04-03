import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { OpenPosition } from "./useRealFeed";

interface ScoreboardProps {
  wins: number;
  losses: number;
  openPositions: OpenPosition[];
}

function formatPnlUsd(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1000) return `${v >= 0 ? "+" : "-"}$${(abs / 1000).toFixed(1)}k`;
  if (abs >= 100) return `${v >= 0 ? "+" : "-"}$${abs.toFixed(0)}`;
  return `${v >= 0 ? "+" : "-"}$${abs.toFixed(2)}`;
}

const RELOAD_INTERVAL = 15000;
const STAGGER_DELAY = 0.07;
const NEGATIVE_SLOTS = 5;

function PositionRow({ pos, cycle }: { pos: OpenPosition; cycle: number }) {
  const isUp = pos.pnlPct >= 0;
  const color = isUp ? "#00ff88" : "#ff8c00";
  const bgColor = isUp ? "rgba(34,197,94,0.03)" : "rgba(249,115,22,0.03)";

  return (
    <motion.div
      key={`${cycle}-${pos.id}`}
      initial={{ opacity: 0, x: -30, scaleY: 0.6 }}
      animate={{ opacity: 1, x: 0, scaleY: 1 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="flex items-center gap-1.5 px-2.5 py-1 border-b border-white/[0.03] font-mono origin-top"
      style={{ backgroundColor: bgColor }}
    >
      <span className="text-[10px] shrink-0">{pos.icon}</span>
      <span className="text-[8px] shrink-0 opacity-50 max-w-[52px] truncate">{pos.bot}</span>
      <span className="text-[9px] truncate" style={{ color: "rgba(148,163,184,0.7)" }}>
        {pos.side.toUpperCase()} {pos.symbol}
      </span>
      <span className="ml-auto flex items-center gap-1.5 shrink-0">
        <motion.span
          className="text-[9px] font-bold"
          style={{ color }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
        >
          {formatPnlUsd(pos.pnlUsd)}
        </motion.span>
        <motion.span
          className="text-[9px] opacity-60"
          style={{ color }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.6 }}
          transition={{ delay: 0.15 }}
        >
          {isUp ? "+" : ""}{pos.pnlPct.toFixed(2)}%
        </motion.span>
      </span>
    </motion.div>
  );
}

export function Scoreboard({ wins, losses, openPositions }: ScoreboardProps) {
  const [cycle, setCycle] = useState(0);
  const [visibleCount, setVisibleCount] = useState(openPositions.length);

  useEffect(() => {
    const interval = setInterval(() => {
      setVisibleCount(0);
      setCycle((c) => c + 1);
    }, RELOAD_INTERVAL);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (visibleCount >= openPositions.length) return;
    const timer = setTimeout(() => {
      setVisibleCount((c) => c + 1);
    }, STAGGER_DELAY * 1000);
    return () => clearTimeout(timer);
  }, [visibleCount, openPositions.length, cycle]);

  const positivePositions = [...openPositions].filter(p => p.pnlPct >= 0).sort((a, b) => b.pnlPct - a.pnlPct);
  const negativePositions = [...openPositions].filter(p => p.pnlPct < 0).sort((a, b) => b.pnlPct - a.pnlPct);
  const bottomSlots = negativePositions.slice(0, NEGATIVE_SLOTS);
  const combined = [...positivePositions, ...bottomSlots];

  return (
    <div className="flex flex-col gap-2 flex-1 min-h-0">
      <div className="grid grid-cols-2 gap-2 shrink-0">
        <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-2 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-t from-green-500/10 to-transparent" />
          <div className="relative">
            <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(74,222,128,0.6)" }}>WINS</div>
            <motion.div
              key={wins}
              initial={{ scale: 1.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="text-2xl font-mono font-black"
              style={{ color: "#4ade80", textShadow: "0 0 20px rgba(34,197,94,0.6), 0 0 40px rgba(34,197,94,0.3)" }}
            >
              {wins}
            </motion.div>
          </div>
        </div>
        <div className="rounded-xl border border-orange-500/30 bg-orange-500/5 p-2 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-t from-orange-500/10 to-transparent" />
          <div className="relative">
            <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(251,146,60,0.6)" }}>LOSSES</div>
            <motion.div
              key={losses}
              initial={{ scale: 1.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="text-2xl font-mono font-black"
              style={{ color: "#fb923c", textShadow: "0 0 20px rgba(249,115,22,0.6), 0 0 40px rgba(249,115,22,0.3)" }}
            >
              {losses}
            </motion.div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden rounded-lg border border-white/5 bg-slate-900/60 min-h-0 flex flex-col">
        <div className="px-3 py-2.5 border-b border-white/10 shrink-0 flex items-center justify-between">
          <motion.span
            className="text-[16px] uppercase font-black tracking-wider"
            style={{ color: "#ffffff", textShadow: "0 0 10px rgba(255,255,255,0.15)" }}
            animate={{ opacity: [0.7, 1, 0.7] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
          >
            Open Positions
          </motion.span>
          <span className="text-[12px] font-mono font-bold px-2 py-0.5 rounded-md border border-cyan-400/20" style={{ color: "#22d3ee", backgroundColor: "rgba(34,211,238,0.1)" }}>{openPositions.length}</span>
        </div>
        <div className="flex-1 overflow-hidden min-h-0">
          <AnimatePresence mode="sync">
            {combined.slice(0, visibleCount).map((pos) => (
              <PositionRow key={`${cycle}-${pos.id}`} pos={pos} cycle={cycle} />
            ))}
          </AnimatePresence>
          {openPositions.length === 0 && (
            <div className="text-[9px] font-mono text-center py-4" style={{ color: "rgba(148,163,184,0.3)" }}>No open positions</div>
          )}
        </div>
      </div>
    </div>
  );
}
