import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { CelebrationTrade } from "./useRealCelebrations";

const BH_X_PCT = 50;
const BH_Y_PCT = 43;

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
      transition={{ duration: 1.2 + Math.random() * 0.8, ease: [0.22, 1, 0.36, 1], delay: Math.random() * 0.3 }}
    >
      {isDollar ? (
        isWin ? "\u{1F4B0}" : "\u{1F4CA}"
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

function AtomizeParticle({ index, total }: { index: number; total: number }) {
  const angle = (index / total) * Math.PI * 2 + (Math.random() - 0.5) * 0.5;
  const distance = 80 + Math.random() * 120;
  const dx = Math.cos(angle) * distance;
  const dy = Math.sin(angle) * distance;
  const size = 1 + Math.random() * 3;
  const delay = Math.random() * 0.6;

  return (
    <motion.div
      className="absolute rounded-full"
      style={{
        left: `${20 + Math.random() * 60}%`,
        top: `${20 + Math.random() * 60}%`,
        width: size,
        height: size,
        backgroundColor: `hsl(${20 + Math.random() * 15}, 80%, ${50 + Math.random() * 30}%)`,
        boxShadow: `0 0 ${size * 3}px hsl(25, 80%, 50%)`,
      }}
      initial={{ x: 0, y: 0, opacity: 1, scale: 1 }}
      animate={{ x: dx, y: dy, opacity: [1, 0.6, 0], scale: [1, 0.5, 0] }}
      transition={{ duration: 1.8 + Math.random() * 0.7, ease: "easeOut", delay }}
    />
  );
}

function EnergyPulse({ parentRef }: { parentRef: React.RefObject<HTMLDivElement | null> }) {
  const el = parentRef.current;
  const cx = el ? el.offsetWidth * (BH_X_PCT / 100) : 0;
  const cy = el ? el.offsetHeight * (BH_Y_PCT / 100) : 0;

  return (
    <motion.div
      className="absolute pointer-events-none z-50"
      style={{ left: cx, top: cy }}
      initial={{ opacity: 1 }}
      animate={{ opacity: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
    >
      {[0, 1, 2].map((ring) => (
        <motion.div
          key={ring}
          className="absolute rounded-full"
          style={{
            border: "1.5px solid",
            borderColor: ring === 0
              ? "rgba(34,197,94,0.7)"
              : ring === 1
                ? "rgba(52,211,153,0.5)"
                : "rgba(167,243,208,0.3)",
          }}
          initial={{ width: 20, height: 20, x: -10, y: -10, opacity: 1 }}
          animate={{
            width: 200 + ring * 90,
            height: 200 + ring * 90,
            x: -(100 + ring * 45),
            y: -(100 + ring * 45),
            opacity: 0,
          }}
          transition={{ duration: 0.7, ease: "easeOut", delay: ring * 0.1 }}
        />
      ))}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 30,
          height: 30,
          x: -15,
          y: -15,
          backgroundColor: "rgba(34,197,94,0.9)",
          boxShadow: "0 0 60px rgba(34,197,94,0.8), 0 0 120px rgba(34,197,94,0.4)",
        }}
        initial={{ scale: 1, opacity: 1 }}
        animate={{ scale: [1, 2.5, 0], opacity: [1, 0.8, 0] }}
        transition={{ duration: 0.6, ease: "easeOut" }}
      />
    </motion.div>
  );
}

export function ProfitExplosion({ trade }: ProfitExplosionProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const pos = useMemo(() => {
    if (!trade) return { x: 50, y: 50 };
    return {
      x: 15 + Math.random() * 70,
      y: 10 + Math.random() * 60,
    };
  }, [trade?.id]);

  const isWin = trade?.isWin ?? true;

  const [pulseId, setPulseId] = useState<string | null>(null);
  const lastTradeRef = useRef<{ id: string; isWin: boolean } | null>(null);

  useEffect(() => {
    if (trade) {
      lastTradeRef.current = { id: trade.id, isWin: trade.isWin };
    }
  }, [trade]);

  useEffect(() => {
    if (!trade && lastTradeRef.current?.isWin) {
      const tid = lastTradeRef.current.id;
      const timer = setTimeout(() => setPulseId(tid), 1900);
      return () => clearTimeout(timer);
    }
  }, [trade]);

  useEffect(() => {
    if (pulseId) {
      const timer = setTimeout(() => setPulseId(null), 900);
      return () => clearTimeout(timer);
    }
  }, [pulseId]);

  const getExitXY = useCallback(() => {
    const el = containerRef.current;
    if (!el) return { x: 0, y: 0 };
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    const targetX = w * (BH_X_PCT / 100);
    const targetY = h * (BH_Y_PCT / 100);
    const currentX = w * (pos.x / 100);
    const currentY = h * (pos.y / 100);
    return { x: targetX - currentX, y: targetY - currentY };
  }, [pos.x, pos.y]);

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

  const exitOffset = getExitXY();

  return (
    <div ref={containerRef} className="absolute inset-0 pointer-events-none" style={{ zIndex: 50 }}>
      <AnimatePresence>
        {trade && (
          <motion.div
            key={trade.id}
            className="absolute pointer-events-none"
            style={{
              left: `${pos.x}%`,
              top: `${pos.y}%`,
              marginLeft: "-112px",
              marginTop: "-80px",
            }}
            initial="enter"
            animate="visible"
            exit="exit"
            variants={{
              enter: { opacity: 0, scale: 1, x: 0, y: 0, filter: "blur(0px)" },
              visible: {
                opacity: 1,
                scale: 1,
                x: 0,
                y: 0,
                filter: "blur(0px)",
                transition: { duration: 0.3 },
              },
              exit: isWin
                ? {
                    x: exitOffset.x,
                    y: exitOffset.y,
                    scale: 0.02,
                    opacity: 0,
                    transition: { duration: 2, ease: "easeInOut" },
                  }
                : {
                    scale: 1.08,
                    opacity: 0,
                    filter: "blur(12px)",
                    transition: { duration: 2, ease: "easeInOut" },
                  },
            }}
            role="alert"
          >
            <div className="absolute overflow-hidden" style={{ width: 200, height: 200, left: 12, top: -20 }}>
              {Array.from({ length: 12 }).map((_, i) => (
                <Particle key={`${trade.id}-${i}`} index={i} total={12} isWin={isWin} />
              ))}
            </div>

            {!isWin && (
              <motion.div
                className="absolute overflow-visible"
                style={{ width: 240, height: 240, left: -8, top: -40 }}
                initial={{ opacity: 0 }}
                exit={{ opacity: 1 }}
                transition={{ duration: 0.3 }}
              >
                {Array.from({ length: 24 }).map((_, i) => (
                  <AtomizeParticle key={`atomize-${trade.id}-${i}`} index={i} total={24} />
                ))}
              </motion.div>
            )}

            <div
              className={`relative z-10 rounded-xl border ${borderColor} px-5 py-4 text-center`}
              style={{
                boxShadow: bgShadow,
                width: "225px",
                backgroundColor: "rgba(2,6,23,0.95)",
              }}
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
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {pulseId && <EnergyPulse key={pulseId} parentRef={containerRef} />}
      </AnimatePresence>
    </div>
  );
}
