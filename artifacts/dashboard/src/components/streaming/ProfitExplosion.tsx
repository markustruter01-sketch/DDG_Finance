import { motion, AnimatePresence } from "framer-motion";
import type { CelebrationTrade } from "./useRealCelebrations";

interface ProfitExplosionProps {
  trade: CelebrationTrade | null;
}

function Particle({ index, total }: { index: number; total: number }) {
  const angle = (index / total) * Math.PI * 2;
  const distance = 40 + Math.random() * 100;
  const dx = Math.cos(angle) * distance;
  const dy = Math.sin(angle) * distance;
  const size = 3 + Math.random() * 5;
  const isDollar = index % 4 === 0;

  return (
    <motion.div
      className="absolute"
      style={{
        left: "50%",
        top: "50%",
        width: isDollar ? "auto" : size,
        height: isDollar ? "auto" : size,
        fontSize: isDollar ? "14px" : undefined,
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
          <div className="absolute inset-0 overflow-hidden">
            {Array.from({ length: 20 }).map((_, i) => (
              <Particle key={`${trade.id}-${i}`} index={i} total={20} />
            ))}
          </div>

          <motion.div
            className="relative z-10 rounded-2xl border-2 border-green-400/50 bg-slate-950/90 backdrop-blur-xl px-10 py-6 text-center"
            style={{
              boxShadow: "0 0 40px rgba(34,197,94,0.3), 0 0 80px rgba(34,197,94,0.15), inset 0 0 30px rgba(34,197,94,0.05)",
              maxWidth: "500px",
            }}
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          >
            <motion.div
              className="absolute inset-0 rounded-2xl border-2 border-green-400/30"
              animate={{
                borderColor: ["rgba(34,197,94,0.4)", "rgba(34,197,94,0.15)", "rgba(34,197,94,0.4)"],
                boxShadow: [
                  "0 0 20px rgba(34,197,94,0.3)",
                  "0 0 40px rgba(34,197,94,0.15)",
                  "0 0 20px rgba(34,197,94,0.3)",
                ],
              }}
              transition={{ duration: 1, repeat: Infinity }}
            />

            <motion.div
              className="text-5xl mb-3"
              animate={{ scale: [1, 1.15, 1] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
            >
              {trade.icon}
            </motion.div>

            <div className="text-[10px] uppercase tracking-[0.2em] text-green-400/60 font-bold mb-1">
              Profit Locked In
            </div>

            <div className="text-base font-bold text-white mb-2">
              {trade.bot}
            </div>

            <motion.div
              className="text-3xl font-black font-mono text-green-400 mb-2"
              style={{
                textShadow: "0 0 20px rgba(34,197,94,0.6), 0 0 40px rgba(34,197,94,0.3)",
              }}
              animate={{ scale: [1, 1.05, 1] }}
              transition={{ duration: 1, repeat: Infinity, ease: "easeInOut" }}
            >
              +${Math.abs(trade.pnlUsd).toFixed(2)}
            </motion.div>

            <div className="text-xs text-white/50 font-mono">
              {trade.symbol}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
