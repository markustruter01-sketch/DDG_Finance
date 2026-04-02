import { motion, AnimatePresence } from "framer-motion";
import type { SimulatedTrade } from "./useSimulatedFeed";

interface ProfitExplosionProps {
  trade: SimulatedTrade | null;
}

function Particle({ index, total }: { index: number; total: number }) {
  const angle = (index / total) * Math.PI * 2;
  const distance = 80 + Math.random() * 200;
  const dx = Math.cos(angle) * distance;
  const dy = Math.sin(angle) * distance;
  const size = 4 + Math.random() * 8;
  const isDollar = index % 4 === 0;

  return (
    <motion.div
      className="absolute"
      style={{
        left: "50%",
        top: "50%",
        width: isDollar ? "auto" : size,
        height: isDollar ? "auto" : size,
        fontSize: isDollar ? "20px" : undefined,
      }}
      initial={{ x: 0, y: 0, scale: 0, opacity: 1 }}
      animate={{ x: dx, y: dy, scale: isDollar ? [0, 1.5, 0] : [0, 1.2, 0], opacity: [1, 0.8, 0] }}
      transition={{
        duration: 1.2 + Math.random() * 0.8,
        ease: [0.22, 1, 0.36, 1],
        delay: Math.random() * 0.3,
      }}
    >
      {isDollar ? (
        "💰"
      ) : (
        <div
          className="rounded-full"
          style={{
            width: size,
            height: size,
            backgroundColor: `hsl(${120 + Math.random() * 40}, 80%, ${50 + Math.random() * 30}%)`,
            boxShadow: `0 0 ${size * 2}px hsl(${120 + Math.random() * 40}, 80%, 50%)`,
          }}
        />
      )}
    </motion.div>
  );
}

export function ProfitExplosion({ trade }: ProfitExplosionProps) {
  return (
    <AnimatePresence>
      {trade && (
        <motion.div
          key={trade.id}
          className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          role="alert"
        >
          <motion.div
            className="absolute inset-0"
            style={{ boxShadow: "inset 0 0 100px rgba(34,197,94,0.3), inset 0 0 200px rgba(34,197,94,0.1)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 1, 0.7, 1, 0.7] }}
            transition={{ duration: 2, repeat: Infinity }}
          />

          <motion.div
            className="absolute inset-0 border-[4px] border-green-400/60 rounded-lg"
            animate={{
              borderColor: ["rgba(34,197,94,0.6)", "rgba(34,197,94,0.2)", "rgba(34,197,94,0.6)"],
              boxShadow: [
                "0 0 30px rgba(34,197,94,0.4)",
                "0 0 60px rgba(34,197,94,0.2)",
                "0 0 30px rgba(34,197,94,0.4)",
              ],
            }}
            transition={{ duration: 1, repeat: Infinity }}
          />

          <div className="absolute inset-0 overflow-hidden">
            {Array.from({ length: 30 }).map((_, i) => (
              <Particle key={`${trade.id}-${i}`} index={i} total={30} />
            ))}
          </div>

          <motion.div
            className="relative text-center z-10"
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          >
            <motion.div
              className="text-2xl md:text-3xl font-black text-white mb-4"
              animate={{ scale: [1, 1.05, 1] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              🎉 VICTORY! QUANT FLEET PROFIT LOCKED IN! 🎉
            </motion.div>

            <motion.div
              className="text-5xl md:text-7xl font-black font-mono text-green-400 mb-4"
              style={{
                textShadow: "0 0 40px rgba(34,197,94,0.8), 0 0 80px rgba(34,197,94,0.4), 0 0 120px rgba(34,197,94,0.2)",
              }}
              animate={{ scale: [1, 1.08, 1] }}
              transition={{ duration: 1, repeat: Infinity, ease: "easeInOut" }}
            >
              +${Math.abs(trade.pnlUsd).toFixed(2)} USD
            </motion.div>

            <div className="text-sm text-muted-foreground/70 font-mono">
              {trade.icon} {trade.bot} · {trade.symbol}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
