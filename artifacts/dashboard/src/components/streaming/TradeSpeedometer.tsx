import { motion } from "framer-motion";

interface TradeSpeedometerProps {
  totalTrades: number;
  trades24h: number;
}

export function TradeSpeedometer({ totalTrades, trades24h }: TradeSpeedometerProps) {
  const maxTrades = 200;
  const pct = Math.min(totalTrades / maxTrades, 1);
  const hue = 120 - pct * 120;
  const color = `hsl(${hue}, 80%, 55%)`;

  const max24h = 50;
  const pct24h = Math.min(trades24h / max24h, 1);
  const hue24h = 120 - pct24h * 120;
  const color24h = `hsl(${hue24h}, 80%, 55%)`;

  return (
    <div className="rounded-lg border border-white/5 bg-slate-900/60 px-2.5 py-2">
      <div className="flex gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(96,165,250,0.5)" }}>Total Trades</span>
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

        <div className="w-px bg-white/5" />

        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(34,211,238,0.5)" }}>24h Trades</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <div className="relative h-2 rounded-full bg-slate-800 overflow-hidden">
                <motion.div
                  className="absolute inset-y-0 left-0 rounded-full"
                  style={{ background: `linear-gradient(90deg, #06b6d4, ${color24h})` }}
                  animate={{ width: `${pct24h * 100}%` }}
                  transition={{ duration: 0.8, ease: "easeOut" }}
                />
              </div>
            </div>
            <motion.div
              key={trades24h}
              initial={{ scale: 1.2 }}
              animate={{ scale: 1 }}
              className="text-base font-mono font-black min-w-[32px] text-right"
              style={{ color: color24h, textShadow: `0 0 10px ${color24h}60` }}
            >
              {trades24h}
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}
