import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
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

export function Scoreboard({ wins, losses, openPositions }: ScoreboardProps) {
  return (
    <div className="flex flex-col gap-2 flex-1 min-h-0">
      <div className="grid grid-cols-2 gap-2 shrink-0">
        <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-2 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-t from-green-500/10 to-transparent" />
          <div className="relative">
            <div className="text-[9px] uppercase tracking-widest text-green-400/60 font-bold">WINS</div>
            <motion.div
              key={wins}
              initial={{ scale: 1.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="text-2xl font-mono font-black text-green-400"
              style={{ textShadow: "0 0 20px rgba(34,197,94,0.6), 0 0 40px rgba(34,197,94,0.3)" }}
            >
              {wins}
            </motion.div>
          </div>
        </div>
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-2 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-t from-red-500/10 to-transparent" />
          <div className="relative">
            <div className="text-[9px] uppercase tracking-widest text-red-400/60 font-bold">LOSSES</div>
            <motion.div
              key={losses}
              initial={{ scale: 1.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="text-2xl font-mono font-black text-red-400"
              style={{ textShadow: "0 0 20px rgba(239,68,68,0.6), 0 0 40px rgba(239,68,68,0.3)" }}
            >
              {losses}
            </motion.div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden rounded-lg border border-white/5 bg-slate-900/60 min-h-0 flex flex-col">
        <div className="px-3 py-2.5 border-b border-white/10 shrink-0 flex items-center justify-between">
          <motion.span
            className="text-[16px] uppercase font-black tracking-wider text-white"
            style={{ textShadow: "0 0 10px rgba(255,255,255,0.15)" }}
            animate={{ opacity: [0.7, 1, 0.7] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
          >
            Open Positions
          </motion.span>
          <span className="text-[12px] font-mono font-bold text-cyan-400 bg-cyan-400/10 px-2 py-0.5 rounded-md border border-cyan-400/20">{openPositions.length}</span>
        </div>
        <div className="flex-1 overflow-hidden min-h-0">
          {openPositions.map((pos) => {
            const isUp = pos.pnlPct >= 0;
            return (
              <div
                key={pos.id}
                className="flex items-center gap-1.5 px-2.5 py-1 border-b border-white/[0.03] font-mono"
                style={{ backgroundColor: isUp ? "rgba(34,197,94,0.03)" : "rgba(239,68,68,0.03)" }}
              >
                <span className="text-[10px] shrink-0">{pos.icon}</span>
                <span className="text-[8px] shrink-0 opacity-50 max-w-[52px] truncate">{pos.bot}</span>
                <span className="text-[9px] truncate" style={{ color: "rgba(148,163,184,0.7)" }}>
                  {pos.side.toUpperCase()} {pos.symbol}
                </span>
                <span className="ml-auto flex items-center gap-1.5 shrink-0">
                  <span
                    className="text-[9px] font-bold"
                    style={{ color: isUp ? "#00ff88" : "#ff4d4d" }}
                  >
                    {formatPnlUsd(pos.pnlUsd)}
                  </span>
                  <span
                    className="text-[9px] opacity-60"
                    style={{ color: isUp ? "#00ff88" : "#ff4d4d" }}
                  >
                    {isUp ? "+" : ""}{pos.pnlPct.toFixed(2)}%
                  </span>
                </span>
              </div>
            );
          })}
          {openPositions.length === 0 && (
            <div className="text-[9px] text-muted-foreground/30 font-mono text-center py-4">No open positions</div>
          )}
        </div>
      </div>
    </div>
  );
}
