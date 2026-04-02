import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import type { SimulatedTrade } from "./useSimulatedFeed";

interface ScoreboardProps {
  wins: number;
  losses: number;
  trades: SimulatedTrade[];
}

export function Scoreboard({ wins, losses, trades }: ScoreboardProps) {
  return (
    <div className="flex flex-col h-full gap-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-4 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-t from-green-500/10 to-transparent" />
          <div className="relative">
            <div className="text-[10px] uppercase tracking-widest text-green-400/60 font-bold mb-1">WINS</div>
            <motion.div
              key={wins}
              initial={{ scale: 1.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="text-4xl font-mono font-black text-green-400"
              style={{ textShadow: "0 0 20px rgba(34,197,94,0.6), 0 0 40px rgba(34,197,94,0.3)" }}
            >
              {wins}
            </motion.div>
          </div>
        </div>
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-t from-red-500/10 to-transparent" />
          <div className="relative">
            <div className="text-[10px] uppercase tracking-widest text-red-400/60 font-bold mb-1">LOSSES</div>
            <motion.div
              key={losses}
              initial={{ scale: 1.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="text-4xl font-mono font-black text-red-400"
              style={{ textShadow: "0 0 20px rgba(239,68,68,0.6), 0 0 40px rgba(239,68,68,0.3)" }}
            >
              {losses}
            </motion.div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden rounded-xl border border-white/5 bg-slate-900/60">
        <div className="px-3 py-2 border-b border-white/5 text-[9px] uppercase font-bold tracking-widest text-muted-foreground/50">
          Closed Trades Feed
        </div>
        <div className="h-[calc(100%-32px)] overflow-y-auto scrollbar-thin">
          <AnimatePresence initial={false}>
            {trades.map((trade) => (
              <motion.div
                key={trade.id}
                initial={{ opacity: 0, x: -30, height: 0 }}
                animate={{ opacity: 1, x: 0, height: "auto" }}
                exit={{ opacity: 0, x: 30, height: 0 }}
                transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 border-b border-white/[0.03] text-xs font-mono",
                  trade.isWin ? "bg-green-500/[0.03]" : "bg-red-500/[0.03]"
                )}
              >
                <span className="text-sm shrink-0">{trade.isWin ? "🚀" : "📉"}</span>
                <span className="text-[10px]">{trade.icon}</span>
                <span className="text-muted-foreground/70 truncate">{trade.bot} closed {trade.symbol}:</span>
                <span className={cn("ml-auto font-bold shrink-0", trade.isWin ? "text-green-400" : "text-red-400")}>
                  {trade.pnlUsd >= 0 ? "+" : ""}${Math.abs(trade.pnlUsd).toFixed(2)}
                </span>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
