import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { CelebrationTrade } from "./useRealCelebrations";

interface ProfitExplosionProps {
  trade: CelebrationTrade | null;
}

function Particle({ index, total }: { index: number; total: number }) {
  const angle = (index / total) * Math.PI * 2;
  const distance = 20 + Math.random() * 50;
  const dx = Math.cos(angle) * distance;
  const dy = Math.sin(angle) * distance;
  const size = 2 + Math.random() * 3;
  const isDollar = index % 5 === 0;

  return (
    <motion.div
      className="absolute"
      style={{
        left: "50%",
        top: "50%",
        width: isDollar ? "auto" : size,
        height: isDollar ? "auto" : size,
        fontSize: isDollar ? "10px" : undefined,
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
  const pos = useMemo(() => {
    if (!trade) return { x: 50, y: 50 };
    return {
      x: 15 + Math.random() * 70,
      y: 10 + Math.random() * 60,
    };
  }, [trade?.id]);

  return (
    <AnimatePresence>
      {trade && (
        <motion.div
          key={trade.id}
          className="absolute z-30 pointer-events-none"
          style={{
            left: `${pos.x}%`,
            top: `${pos.y}%`,
            transform: "translate(-50%, -50%)",
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          role="alert"
        >
          <div className="absolute inset-0 overflow-hidden" style={{ width: 200, height: 200, left: -100, top: -100 }}>
            {Array.from({ length: 12 }).map((_, i) => (
              <Particle key={`${trade.id}-${i}`} index={i} total={12} />
            ))}
          </div>

          <motion.div
            className="relative z-10 rounded-xl border border-green-400/50 bg-slate-950/95 backdrop-blur-xl px-4 py-3 text-center"
            style={{
              boxShadow: "0 0 20px rgba(34,197,94,0.3), 0 0 40px rgba(34,197,94,0.15)",
              width: "180px",
            }}
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          >
            <motion.div
              className="absolute inset-0 rounded-xl border border-green-400/30"
              animate={{
                borderColor: ["rgba(34,197,94,0.4)", "rgba(34,197,94,0.15)", "rgba(34,197,94,0.4)"],
                boxShadow: [
                  "0 0 10px rgba(34,197,94,0.3)",
                  "0 0 20px rgba(34,197,94,0.15)",
                  "0 0 10px rgba(34,197,94,0.3)",
                ],
              }}
              transition={{ duration: 1, repeat: Infinity }}
            />

            <motion.div
              className="text-2xl mb-1"
              animate={{ scale: [1, 1.15, 1] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
            >
              {trade.icon}
            </motion.div>

            <div className="text-[7px] uppercase tracking-[0.15em] text-green-400/60 font-bold">
              Profit Locked In
            </div>

            <div className="text-[10px] font-bold text-white mb-1">
              {trade.bot}
            </div>

            <motion.div
              className="text-lg font-black font-mono text-green-400 mb-0.5"
              style={{
                textShadow: "0 0 12px rgba(34,197,94,0.6), 0 0 24px rgba(34,197,94,0.3)",
              }}
              animate={{ scale: [1, 1.05, 1] }}
              transition={{ duration: 1, repeat: Infinity, ease: "easeInOut" }}
            >
              +${Math.abs(trade.pnlUsd).toFixed(2)}
            </motion.div>

            <div className="text-[8px] text-white/50 font-mono">
              {trade.symbol}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
