import { motion } from "framer-motion";

interface TradeSpeedometerProps {
  totalTrades: number;
}

export function TradeSpeedometer({ totalTrades }: TradeSpeedometerProps) {
  const maxTrades = 200;
  const pct = Math.min(totalTrades / maxTrades, 1);
  const hue = 120 - pct * 120;
  const color = `hsl(${hue}, 80%, 55%)`;

  return (
    <div className="rounded-lg border border-white/5 bg-slate-900/60 px-2.5 py-2">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[8px] uppercase tracking-widest text-blue-400/50 font-bold">Total Trades</span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <div className="relative h-2 rounded-full bg-slate-800 overflow-hidden">
            <motion.div
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ background: `linear-gradient(90deg, #22c55e, ${color})` }}
              animate={{ width: `${pct * 100}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
            />
          </div>
        </div>
        <motion.div
          key={totalTrades}
          initial={{ scale: 1.2 }}
          animate={{ scale: 1 }}
          className="text-base font-mono font-black min-w-[32px] text-right"
          style={{ color, textShadow: `0 0 10px ${color}60` }}
        >
          {totalTrades}
        </motion.div>
      </div>
    </div>
  );
}
