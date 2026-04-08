import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import type { RealTrade, OpenPosition } from "./useRealFeed";
import { onTradePulse } from "./tradePulseEvents";

interface ScoreboardProps {
  wins: number;
  losses: number;
  recentTrades: RealTrade[];
  openPositions: OpenPosition[];
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
const MAX_CLOSED = 6;
const MAX_OPEN = 6;

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
  const usdPositive = trade.pnlUsd >= 0;
  const pctPositive = trade.pnlPct >= 0;
  const netPositive = trade.pnlUsd !== 0 ? usdPositive : pctPositive;
  const usdColor = usdPositive ? "#00ff88" : "#ff8c00";
  const pctColor = netPositive ? "#00ff88" : "#ff8c00";
  const bgColor = netPositive ? "rgba(34,197,94,0.04)" : "rgba(249,115,22,0.04)";
  const botColor = BOT_COLORS[trade.bot] ?? "#64748b";

  return (
    <div
      className="flex items-center gap-2 px-3 py-2 border-b font-mono"
      style={{ backgroundColor: bgColor, borderBottomColor: "rgba(255,255,255,0.04)" }}
    >
      <span
        className="shrink-0 flex items-center gap-1.5 rounded-lg px-2 py-1"
        style={{
          backgroundColor: `${botColor}18`,
          border: `1px solid ${botColor}35`,
        }}
      >
        <span style={{ fontSize: 14, lineHeight: 1 }}>{trade.icon}</span>
        <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", lineHeight: 1, color: botColor }}>
          {getBotAbbrev(trade.bot)}
        </span>
      </span>
      {trade.side && (
        <span
          className="shrink-0 rounded px-1 py-0.5"
          style={{
            fontSize: 9,
            fontWeight: 900,
            letterSpacing: "0.05em",
            lineHeight: 1,
            color: trade.side === "short" ? "#f87171" : "#4ade80",
            backgroundColor: trade.side === "short" ? "rgba(248,113,113,0.1)" : "rgba(74,222,128,0.1)",
            border: `1px solid ${trade.side === "short" ? "rgba(248,113,113,0.2)" : "rgba(74,222,128,0.2)"}`,
          }}
        >
          {trade.side === "short" ? "SHORT" : "LONG"}
        </span>
      )}
      <span style={{ fontSize: 12, fontWeight: 600, color: "rgba(203,213,225,0.85)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {trade.symbol}
      </span>
      <span className="ml-auto flex items-center gap-2 shrink-0">
        {trade.pnlUsd !== 0 && (
          <span style={{ fontSize: 12, fontWeight: 700, color: usdColor }}>
            {formatPnlUsd(trade.pnlUsd)}
          </span>
        )}
        <span style={{ fontSize: 12, fontWeight: 700, color: pctColor }}>
          {pctPositive ? "+" : ""}{trade.pnlPct.toFixed(2)}%
        </span>
        <span style={{ fontSize: 10, color: "rgba(148,163,184,0.4)" }}>
          {timeAgo(trade.date)}
        </span>
      </span>
    </div>
  );
}

function OpenPositionRow({ position }: { position: OpenPosition }) {
  const usdPositive = position.pnlUsd >= 0;
  const pctPositive = position.pnlPct >= 0;
  const netPositive = position.pnlUsd !== 0 ? usdPositive : pctPositive;
  const usdColor = usdPositive ? "#00ff88" : "#ff8c00";
  const pctColor = netPositive ? "#00ff88" : "#ff8c00";
  const bgColor = netPositive ? "rgba(34,197,94,0.03)" : "rgba(249,115,22,0.03)";
  const botColor = BOT_COLORS[position.bot] ?? "#64748b";

  return (
    <div
      className="flex items-center gap-2 px-3 py-2 border-b font-mono"
      style={{ backgroundColor: bgColor, borderBottomColor: "rgba(255,255,255,0.04)" }}
    >
      <span
        className="shrink-0 flex items-center gap-1.5 rounded-lg px-2 py-1"
        style={{
          backgroundColor: `${botColor}18`,
          border: `1px solid ${botColor}35`,
        }}
      >
        <span style={{ fontSize: 14, lineHeight: 1 }}>{position.icon}</span>
        <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", lineHeight: 1, color: botColor }}>
          {getBotAbbrev(position.bot)}
        </span>
      </span>
      {position.side && (
        <span
          className="shrink-0 rounded px-1 py-0.5"
          style={{
            fontSize: 9,
            fontWeight: 900,
            letterSpacing: "0.05em",
            lineHeight: 1,
            color: position.side === "short" ? "#f87171" : "#4ade80",
            backgroundColor: position.side === "short" ? "rgba(248,113,113,0.1)" : "rgba(74,222,128,0.1)",
            border: `1px solid ${position.side === "short" ? "rgba(248,113,113,0.2)" : "rgba(74,222,128,0.2)"}`,
          }}
        >
          {position.side === "short" ? "SHORT" : "LONG"}
        </span>
      )}
      <span style={{ fontSize: 12, fontWeight: 600, color: "rgba(203,213,225,0.85)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {position.symbol}
      </span>
      <span className="ml-auto flex items-center gap-2 shrink-0">
        {position.pnlUsd !== 0 && (
          <span style={{ fontSize: 12, fontWeight: 700, color: usdColor }}>
            {formatPnlUsd(position.pnlUsd)}
          </span>
        )}
        <span style={{ fontSize: 12, fontWeight: 700, color: pctColor }}>
          {pctPositive ? "+" : ""}{position.pnlPct.toFixed(2)}%
        </span>
        <LiveDot />
      </span>
    </div>
  );
}

function LiveDot() {
  return (
    <span className="shrink-0 flex items-center gap-1">
      <motion.span
        style={{
          display: "inline-block",
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: "#22d3ee",
          boxShadow: "0 0 6px rgba(34,211,238,0.8)",
        }}
        animate={{ opacity: [1, 0.3, 1] }}
        transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
      />
    </span>
  );
}

export function Scoreboard({ wins, losses, recentTrades, openPositions }: ScoreboardProps) {
  const [cycle, setCycle] = useState(0);
  const [visibleCount, setVisibleCount] = useState(recentTrades.length);
  const [winPulse, setWinPulse] = useState(false);
  const [lossPulse, setLossPulse] = useState(false);

  useEffect(() => {
    const unsub = onTradePulse((ev) => {
      if (ev.type === "win") {
        setWinPulse(true);
        setTimeout(() => setWinPulse(false), 1000);
      } else {
        setLossPulse(true);
        setTimeout(() => setLossPulse(false), 1000);
      }
    });
    return unsub;
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setVisibleCount(0);
      setCycle((c) => c + 1);
    }, RELOAD_INTERVAL);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (visibleCount >= Math.min(recentTrades.length, MAX_CLOSED)) return;
    const timer = setTimeout(() => {
      setVisibleCount((c) => c + 1);
    }, STAGGER_DELAY * 1000);
    return () => clearTimeout(timer);
  }, [visibleCount, recentTrades.length, cycle]);

  const visibleClosed = recentTrades.slice(0, MAX_CLOSED);
  const visibleOpen = openPositions.slice(0, MAX_OPEN);

  return (
    <div className="flex flex-col gap-2 flex-1 min-h-0">
      <div className="grid grid-cols-2 gap-2 shrink-0">
        <motion.div
          className="rounded-xl border border-green-500/30 bg-green-500/5 p-2 text-center relative overflow-hidden"
          animate={winPulse ? {
            scale: [1, 1.12, 0.95, 1.08, 1],
            boxShadow: [
              "0 0 0px rgba(34,197,94,0)",
              "0 0 30px rgba(34,197,94,0.8), 0 0 60px rgba(34,197,94,0.4)",
              "0 0 10px rgba(34,197,94,0.3)",
              "0 0 25px rgba(34,197,94,0.6), 0 0 50px rgba(34,197,94,0.3)",
              "0 0 0px rgba(34,197,94,0)",
            ],
            borderColor: [
              "rgba(34,197,94,0.3)",
              "rgba(74,222,128,1)",
              "rgba(34,197,94,0.5)",
              "rgba(74,222,128,0.8)",
              "rgba(34,197,94,0.3)",
            ],
          } : { scale: 1, boxShadow: "0 0 0px transparent", borderColor: "rgba(34,197,94,0.3)" }}
          transition={winPulse ? { duration: 1, ease: "easeInOut" } : { duration: 0.3 }}
        >
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
        </motion.div>
        <motion.div
          className="rounded-xl border border-orange-500/30 bg-orange-500/5 p-2 text-center relative overflow-hidden"
          animate={lossPulse ? {
            scale: [1, 1.12, 0.95, 1.08, 1],
            boxShadow: [
              "0 0 0px rgba(249,115,22,0)",
              "0 0 30px rgba(249,115,22,0.8), 0 0 60px rgba(249,115,22,0.4)",
              "0 0 10px rgba(249,115,22,0.3)",
              "0 0 25px rgba(249,115,22,0.6), 0 0 50px rgba(249,115,22,0.3)",
              "0 0 0px rgba(249,115,22,0)",
            ],
            borderColor: [
              "rgba(249,115,22,0.3)",
              "rgba(251,146,60,1)",
              "rgba(249,115,22,0.5)",
              "rgba(251,146,60,0.8)",
              "rgba(249,115,22,0.3)",
            ],
          } : { scale: 1, boxShadow: "0 0 0px transparent", borderColor: "rgba(249,115,22,0.3)" }}
          transition={lossPulse ? { duration: 1, ease: "easeInOut" } : { duration: 0.3 }}
        >
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
        </motion.div>
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
        <div className="overflow-hidden" style={{ flex: "1 1 0" }}>
          {visibleClosed.slice(0, visibleCount).map((trade) => (
            <TradeRow key={`${cycle}-${trade.id}`} trade={trade} cycle={cycle} />
          ))}
          {recentTrades.length === 0 && (
            <div className="text-[12px] font-mono text-center py-6" style={{ color: "rgba(148,163,184,0.3)" }}>No closed trades yet</div>
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-cyan-500/10 bg-slate-900/60 min-h-0 flex flex-col" style={{ flex: "1 1 0" }}>
        <div className="px-3 py-2.5 border-b border-white/10 shrink-0 flex items-center justify-between">
          <span
            className="text-[16px] uppercase font-black tracking-wider flex items-center gap-2"
            style={{ color: "#22d3ee", textShadow: "0 0 10px rgba(34,211,238,0.2)" }}
          >
            Open Trades
            <LiveDot />
          </span>
          <span className="text-[13px] font-mono font-bold px-2.5 py-0.5 rounded-md border border-cyan-400/20" style={{ color: "#22d3ee", backgroundColor: "rgba(34,211,238,0.1)" }}>{openPositions.length}</span>
        </div>
        <div className="overflow-hidden" style={{ flex: "1 1 0" }}>
          {visibleOpen.map((pos) => (
            <OpenPositionRow key={pos.id} position={pos} />
          ))}
          {openPositions.length === 0 && (
            <div className="text-[12px] font-mono text-center py-6" style={{ color: "rgba(148,163,184,0.2)" }}>No open positions</div>
          )}
        </div>
      </div>
    </div>
  );
}
