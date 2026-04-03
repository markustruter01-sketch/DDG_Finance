import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { CelebrationTrade } from "./useRealCelebrations";

interface ProfitExplosionProps {
  trade: CelebrationTrade | null;
}

function Particle({ index, total, isWin }: { index: number; total: number; isWin: boolean }) {
  const angle = (index / total) * Math.PI * 2;
  const distance = 20 + Math.random() * 50;
  const dx = Math.cos(angle) * distance;
  const dy = Math.sin(angle) * distance;
  const size = 2 + Math.random() * 3;
  const isDollar = index % 5 === 0;

  const hueBase = isWin ? 120 : 25;
  const hueRange = isWin ? 40 : 20;

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
        isWin ? "💰" : "📊"
      ) : (
        <div
          className="rounded-full"
          style={{
            width: size,
            height: size,
            backgroundColor: `hsl(${hueBase + Math.random() * hueRange}, 80%, ${50 + Math.random() * 30}%)`,
            boxShadow: `0 0 ${size * 2}px hsl(${hueBase + Math.random() * hueRange}, 80%, 50%)`,
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

  const isWin = trade?.isWin ?? true;

  const borderColor = isWin ? "border-green-400/50" : "border-orange-400/50";
  const bgShadow = isWin
    ? "0 0 24px rgba(34,197,94,0.3), 0 0 48px rgba(34,197,94,0.15)"
    : "0 0 24px rgba(249,115,22,0.3), 0 0 48px rgba(249,115,22,0.15)";
  const labelColor = isWin ? "text-green-400/60" : "text-orange-400/60";
  const labelText = isWin ? "Profit Locked In" : "Loss Absorbed";
  const amountColor = isWin ? "text-green-400" : "text-orange-400";
  const amountShadow = isWin
    ? "0 0 14px rgba(34,197,94,0.6), 0 0 28px rgba(34,197,94,0.3)"
    : "0 0 14px rgba(249,115,22,0.6), 0 0 28px rgba(249,115,22,0.3)";
  const borderAnimColor = isWin
    ? ["rgba(34,197,94,0.4)", "rgba(34,197,94,0.15)", "rgba(34,197,94,0.4)"]
    : ["rgba(249,115,22,0.4)", "rgba(249,115,22,0.15)", "rgba(249,115,22,0.4)"];
  const borderAnimShadow = isWin
    ? ["0 0 10px rgba(34,197,94,0.3)", "0 0 20px rgba(34,197,94,0.15)", "0 0 10px rgba(34,197,94,0.3)"]
    : ["0 0 10px rgba(249,115,22,0.3)", "0 0 20px rgba(249,115,22,0.15)", "0 0 10px rgba(249,115,22,0.3)"];

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
              <Particle key={`${trade.id}-${i}`} index={i} total={12} isWin={isWin} />
            ))}
          </div>

          <motion.div
            className={`relative z-10 rounded-xl border ${borderColor} bg-slate-950/95 backdrop-blur-xl px-5 py-4 text-center`}
            style={{
              boxShadow: bgShadow,
              width: "225px",
            }}
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          >
            <motion.div
              className={`absolute inset-0 rounded-xl border ${borderColor.replace("/50", "/30")}`}
              animate={{
                borderColor: borderAnimColor,
                boxShadow: borderAnimShadow,
              }}
              transition={{ duration: 1, repeat: Infinity }}
            />

            <motion.div
              className="text-3xl mb-1.5"
              animate={{ scale: [1, 1.15, 1] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
            >
              {trade.icon}
            </motion.div>

            <div className={`text-[9px] uppercase tracking-[0.15em] ${labelColor} font-bold`}>
              {labelText}
            </div>

            <div className="text-[13px] font-bold text-white mb-1.5">
              {trade.bot}
            </div>

            <motion.div
              className={`text-xl font-black font-mono ${amountColor} mb-1`}
              style={{ textShadow: amountShadow }}
              animate={{ scale: [1, 1.05, 1] }}
              transition={{ duration: 1, repeat: Infinity, ease: "easeInOut" }}
            >
              {isWin ? "+" : "-"}${Math.abs(trade.pnlUsd).toFixed(2)}
            </motion.div>

            <div className="text-[10px] text-white/50 font-mono">
              {trade.symbol}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
