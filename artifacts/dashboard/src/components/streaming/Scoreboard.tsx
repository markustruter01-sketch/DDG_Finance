import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import type { RealTrade } from "./useRealFeed";

interface ScoreboardProps {
  wins: number;
  losses: number;
  trades: RealTrade[];
}

export function Scoreboard({ wins, losses, trades }: ScoreboardProps) {
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
        <div className="px-2.5 py-1.5 border-b border-white/5 text-[8px] uppercase font-bold tracking-widest text-muted-foreground/50 shrink-0">
          Closed Trades Feed
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0">
          <AnimatePresence initial={false}>
            {trades.map((trade) => (
              <motion.div
                key={trade.id}
                initial={{ opacity: 0, x: -30, height: 0 }}
                animate={{ opacity: 1, x: 0, height: "auto" }}
                exit={{ opacity: 0, x: 30, height: 0 }}
                transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1 border-b border-white/[0.03] font-mono",
                  trade.isWin ? "bg-green-500/[0.03]" : "bg-red-500/[0.03]"
                )}
              >
                <span className="text-[10px] shrink-0">{trade.isWin ? "🚀" : "📉"}</span>
                <span className="text-[9px]">{trade.icon}</span>
                <span className="text-[9px] text-muted-foreground/70 truncate">{trade.bot} closed {trade.symbol}:</span>
                <span className={cn("ml-auto text-[10px] font-bold shrink-0", trade.isWin ? "text-green-400" : "text-red-400")}>
                  {trade.pnlPct >= 0 ? "+" : ""}{trade.pnlPct.toFixed(2)}%
                </span>
              </motion.div>
            ))}
          </AnimatePresence>
          {trades.length === 0 && (
            <div className="text-[9px] text-muted-foreground/30 font-mono text-center py-4">No closed trades yet...</div>
          )}
        </div>
      </div>
    </div>
  );
}
