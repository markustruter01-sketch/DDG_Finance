import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { RealTrade } from "./useRealFeed";

interface ScoreboardProps {
  wins: number;
  losses: number;
  recentTrades: RealTrade[];
}

function formatPnlUsd(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1000) return `${v >= 0 ? "+" : "-"}$${(abs / 1000).toFixed(1)}k`;
  if (abs >= 100) return `${v >= 0 ? "+" : "-"}$${abs.toFixed(0)}`;
  if (abs >= 0.01) return `${v >= 0 ? "+" : "-"}$${abs.toFixed(2)}`;
  return "$0.00";
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

const RELOAD_INTERVAL = 15000;
const STAGGER_DELAY = 0.06;
const MAX_VISIBLE = 20;

const BOT_COLORS: Record<string, string> = {
  "Oracle": "#8b5cf6",
  "Davy Jones": "#22d3ee",
  "Blackbeard": "#ef4444",
  "Calypso": "#3b82f6",
  "Apex Predator": "#f59e0b",
  "Navigator": "#a78bfa",
};

function getBotAbbrev(name: string): string {
  if (name === "Davy Jones") return "DJ";
  if (name === "Blackbeard") return "BB";
  if (name === "Calypso") return "CAL";
  if (name === "Apex Predator") return "APEX";
  if (name === "Navigator") return "NAV";
  if (name === "Oracle") return "ORC";
  return name.slice(0, 3).toUpperCase();
}

function TradeRow({ trade, cycle }: { trade: RealTrade; cycle: number }) {
  const isWin = trade.isWin;
  const color = isWin ? "#00ff88" : "#ff8c00";
  const bgColor = isWin ? "rgba(34,197,94,0.04)" : "rgba(249,115,22,0.04)";
  const botColor = BOT_COLORS[trade.bot] ?? "#64748b";

  return (
    <motion.div
      key={`${cycle}-${trade.id}`}
      initial={{ opacity: 0, x: -30, scaleY: 0.6 }}
      animate={{ opacity: 1, x: 0, scaleY: 1 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.04] font-mono origin-top"
      style={{ backgroundColor: bgColor }}
    >
      <span
        className="shrink-0 flex items-center gap-1.5 rounded-lg px-2 py-1"
        style={{
          backgroundColor: `${botColor}18`,
          border: `1px solid ${botColor}35`,
        }}
      >
        <span className="text-[14px] leading-none">{trade.icon}</span>
        <span className="text-[10px] font-black uppercase tracking-wider leading-none" style={{ color: botColor }}>
          {getBotAbbrev(trade.bot)}
        </span>
      </span>
      <span className="text-[12px] font-semibold truncate" style={{ color: "rgba(203,213,225,0.85)" }}>
        {trade.symbol}
      </span>
      <span className="ml-auto flex items-center gap-2 shrink-0">
        {trade.pnlUsd !== 0 && (
          <span
            className="text-[12px] font-bold"
            style={{ color }}
          >
            {formatPnlUsd(trade.pnlUsd)}
          </span>
        )}
        <span
          className="text-[12px] font-bold"
          style={{ color }}
        >
          {trade.pnlPct >= 0 ? "+" : ""}{trade.pnlPct.toFixed(2)}%
        </span>
        <span className="text-[10px]" style={{ color: "rgba(148,163,184,0.4)" }}>
          {timeAgo(trade.date)}
        </span>
      </span>
    </motion.div>
  );
}

export function Scoreboard({ wins, losses, recentTrades }: ScoreboardProps) {
  const [cycle, setCycle] = useState(0);
  const [visibleCount, setVisibleCount] = useState(recentTrades.length);

  useEffect(() => {
    const interval = setInterval(() => {
      setVisibleCount(0);
      setCycle((c) => c + 1);
    }, RELOAD_INTERVAL);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (visibleCount >= Math.min(recentTrades.length, MAX_VISIBLE)) return;
    const timer = setTimeout(() => {
      setVisibleCount((c) => c + 1);
    }, STAGGER_DELAY * 1000);
    return () => clearTimeout(timer);
  }, [visibleCount, recentTrades.length, cycle]);

  const visible = recentTrades.slice(0, MAX_VISIBLE);

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
            Recent Trades
          </motion.span>
          <span className="text-[13px] font-mono font-bold px-2.5 py-0.5 rounded-md border border-cyan-400/20" style={{ color: "#22d3ee", backgroundColor: "rgba(34,211,238,0.1)" }}>{recentTrades.length}</span>
        </div>
        <div className="flex-1 overflow-auto min-h-0">
          <AnimatePresence mode="sync">
            {visible.slice(0, visibleCount).map((trade) => (
              <TradeRow key={`${cycle}-${trade.id}`} trade={trade} cycle={cycle} />
            ))}
          </AnimatePresence>
          {recentTrades.length === 0 && (
            <div className="text-[12px] font-mono text-center py-6" style={{ color: "rgba(148,163,184,0.3)" }}>No closed trades yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
