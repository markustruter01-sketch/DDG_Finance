import { motion } from "framer-motion";

interface TradeSpeedometerProps {
  tradesPerHour: number;
  totalTrades: number;
}

export function TradeSpeedometer({ tradesPerHour, totalTrades }: TradeSpeedometerProps) {
  const maxRate = 60;
  const pct = Math.min(tradesPerHour / maxRate, 1);
  const hue = 120 - pct * 120;
  const color = `hsl(${hue}, 80%, 55%)`;

  return (
    <div className="rounded-xl border border-white/5 bg-slate-900/60 p-3">
      <div className="text-[9px] uppercase tracking-widest text-blue-400/50 font-bold mb-2">Trade Velocity</div>
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <div className="relative h-3 rounded-full bg-slate-800 overflow-hidden">
            <motion.div
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ background: `linear-gradient(90deg, #22c55e, ${color})` }}
              animate={{ width: `${pct * 100}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
            />
          </div>
          <div className="flex justify-between mt-1">
            <span className="text-[8px] text-muted-foreground/30 font-mono">0</span>
            <span className="text-[8px] text-muted-foreground/30 font-mono">{maxRate}/hr</span>
          </div>
        </div>
        <div className="text-right">
          <motion.div
            key={tradesPerHour}
            initial={{ scale: 1.2 }}
            animate={{ scale: 1 }}
            className="text-xl font-mono font-black"
            style={{ color, textShadow: `0 0 10px ${color}60` }}
          >
            {tradesPerHour}
          </motion.div>
          <div className="text-[8px] text-muted-foreground/40 font-mono">trades/hr</div>
        </div>
      </div>
      <div className="text-[9px] text-muted-foreground/30 font-mono mt-1">{totalTrades} total this session</div>
    </div>
  );
}
