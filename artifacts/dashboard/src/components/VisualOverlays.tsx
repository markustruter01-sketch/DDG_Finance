import { useIsMobile } from "@/hooks/use-mobile";
import { useLatestAllocation, useStatusSummary } from "@/hooks/use-trading";
import { motion } from "framer-motion";

export function CRTOverlay() {
  const isMobile = useIsMobile();
  if (isMobile) return null;
  return (
    <div className="fixed inset-0 pointer-events-none z-[9998] overflow-hidden">
      <div
        className="crt-scanline absolute left-0 right-0 h-[3px]"
        style={{
          background: "linear-gradient(to bottom, transparent, rgba(99,102,241,0.055), transparent)",
          boxShadow: "0 0 10px rgba(99,102,241,0.07)",
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.28) 100%)",
        }}
      />
    </div>
  );
}

export function RegimeGlow() {
  const { data: alloc } = useLatestAllocation();
  const regime = alloc?.regime;
  const cfg = regime === "Bear"
    ? { color: "rgba(239,68,68,0.18)", glow: "rgba(239,68,68,0.14)", key: "bear" }
    : regime === "Neutral"
    ? { color: "rgba(245,158,11,0.15)", glow: "rgba(245,158,11,0.11)", key: "neutral" }
    : { color: "rgba(34,197,94,0.14)", glow: "rgba(34,197,94,0.10)", key: "bull" };
  if (!regime) return null;
  return (
    <motion.div
      key={cfg.key}
      className="fixed left-0 top-0 bottom-0 w-[3px] pointer-events-none z-[9997]"
      initial={{ opacity: 0 }}
      animate={{ opacity: [0.45, 1, 0.45] }}
      transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
      style={{ background: cfg.color, boxShadow: `3px 0 24px ${cfg.glow}` }}
    />
  );
}

export function EquityEcho() {
  const isMobile = useIsMobile();
  const { data } = useStatusSummary();
  if (isMobile || !data) return null;
  const equity = data.portfolio_totals.equity;
  const isProfit = equity >= 100000;
  const magnitude = Math.min(Math.abs(equity - 100000) / 20000, 1);
  const baseAlpha = 0.035 + magnitude * 0.055;
  return (
    <motion.div
      key={isProfit ? "profit" : "loss"}
      className="fixed inset-0 pointer-events-none z-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 2.5, ease: "easeInOut" }}
      style={{
        background: isProfit
          ? `radial-gradient(ellipse at 50% 100%, rgba(59,130,246,${baseAlpha}) 0%, transparent 60%)`
          : `radial-gradient(ellipse at 50% 100%, rgba(245,158,11,${baseAlpha}) 0%, transparent 60%)`,
      }}
    />
  );
}
