import { motion } from "framer-motion";

const TICKER_TEXT = "Want the quantitative and algorithmic math behind this system? Learn to build your *own* system with our complete educational PDF blueprint, covering math, risk metrics, models, and white paper for $49.99 USD. Join the Discord for community discussions, check the links in the stream description for the guide.";

export function SalesTicker() {
  return (
    <div className="relative overflow-hidden border-t border-cyan-500/20 bg-slate-950/90 py-2">
      <div className="absolute left-0 top-0 bottom-0 w-16 bg-gradient-to-r from-slate-950 to-transparent z-10" />
      <div className="absolute right-0 top-0 bottom-0 w-16 bg-gradient-to-l from-slate-950 to-transparent z-10" />
      <motion.div
        className="flex whitespace-nowrap text-xs font-mono"
        animate={{ x: ["0%", "-50%"] }}
        transition={{ duration: 30, repeat: Infinity, ease: "linear" }}
      >
        <span className="text-cyan-400/70 px-8">📘 {TICKER_TEXT}</span>
        <span className="text-cyan-400/40 px-4">•</span>
        <span className="text-cyan-400/70 px-8">📘 {TICKER_TEXT}</span>
        <span className="text-cyan-400/40 px-4">•</span>
      </motion.div>
    </div>
  );
}
