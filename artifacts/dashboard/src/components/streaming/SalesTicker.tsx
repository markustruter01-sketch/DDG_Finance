import { motion } from "framer-motion";

const TICKER_TEXT = "Want the quantitative and algorithmic math behind this system? Learn to build your *own* system with our complete educational PDF blueprint, covering math, risk metrics, models, and white paper for $49.99 USD. Join the Discord for community discussions, check the links in the stream description for the guide.";

const WARNING_TEXT = "⚠️ WARNING: This is not financial advice, only a system demonstration. Past performance does not guarantee future results. Trade at your own risk.";

export function SalesTicker() {
  return (
    <div className="relative overflow-hidden border-t border-cyan-500/20 bg-slate-950/90 py-2.5 shrink-0">
      <div className="absolute left-0 top-0 bottom-0 w-16 bg-gradient-to-r from-slate-950 to-transparent z-10" />
      <div className="absolute right-0 top-0 bottom-0 w-16 bg-gradient-to-l from-slate-950 to-transparent z-10" />
      <motion.div
        className="flex whitespace-nowrap font-mono"
        style={{ fontSize: "15px" }}
        animate={{ x: ["0%", "-50%"] }}
        transition={{ duration: 40, repeat: Infinity, ease: "linear" }}
      >
        <span className="text-cyan-400/80 px-8">📘 {TICKER_TEXT}</span>
        <span className="text-yellow-400/60 px-6">|</span>
        <span className="text-red-400/90 px-8 font-bold">{WARNING_TEXT}</span>
        <span className="text-cyan-400/40 px-6">|</span>
        <span className="text-cyan-400/80 px-8">📘 {TICKER_TEXT}</span>
        <span className="text-yellow-400/60 px-6">|</span>
        <span className="text-red-400/90 px-8 font-bold">{WARNING_TEXT}</span>
        <span className="text-cyan-400/40 px-6">|</span>
      </motion.div>
    </div>
  );
}
