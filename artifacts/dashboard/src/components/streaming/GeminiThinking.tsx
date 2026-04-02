import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useFleetCommanderStatus } from "@/hooks/use-trading";

const GEMINI_THOUGHTS = [
  "Detected a recurring pattern of losing BTC/USD shorts in the last 48 hours across Davy Jones and Blackbeard. Injecting RAG context into both bots' next analysis cycle to bias away from counter-trend shorts until momentum confirms a reversal.",
  "Navigator's GBP/USD short hit its stop-loss at 1.5× ATR — the third consecutive loss on GBP pairs this week. Tightening the news blackout window from 4 hours to 6 hours around Bank of England announcements to reduce exposure to high-impact volatility.",
  "Cross-asset correlation matrix shows ρ=0.87 between BTC and ETH positions held by Davy Jones and Calypso simultaneously. Flagging concentration risk and recommending Calypso rotate into lower-correlation alts like ATOM/USD and ARB/USD next cycle.",
  "Apex Predator's capital fence is at 3.2% of the 5% max allocation. IVR readings across the watchlist are still elevated above 20, so no new straddle entries are warranted. Holding current positions and letting theta decay work in our favor.",
  "Oracle's regime model has shifted from BULL to SIDEWAYS based on declining SPY momentum and flattening yield curve data. Reducing equity allocation by 40% and rotating freed capital into TLT and GLD as defensive hedges.",
  "Fleet-wide drawdown currently at -0.56%, well within the 3% tolerance threshold. All risk parameters are nominal. No parameter adjustments needed — letting all six bots continue operating with current configurations.",
  "Blackbeard's SOL/USD Z-score spiked to +2.8, triggering a potential momentum entry signal. Validating against VPIN data and on-chain flow metrics before allowing execution — false breakouts on SOL have cost us 3 trades this month.",
  "Macro Compass update from Groq indicates USD weakening on soft NFP expectations. Adjusting Navigator's directional bias to favor long EUR/USD and AUD/USD setups while reducing conviction on USD/JPY longs until data confirms.",
  "Calypso's ATR-based stops on ARB/USD are too wide at 2.1× given current low-volatility conditions. Tightening to 1.8× ATR to protect unrealized gains and reduce risk-per-trade from 1.4% back down to the target 1.0%.",
  "Fear & Greed Index dropped to 42 (Fear zone) while BTC on-chain accumulation addresses are rising. This divergence historically precedes a 5-10% rally — flagging as a high-conviction long setup for Davy Jones to evaluate next cycle.",
];

export function GeminiThinking() {
  const [thought, setThought] = useState(GEMINI_THOUGHTS[0]);
  const [key, setKey] = useState(0);
  const { data: auditStatus } = useFleetCommanderStatus();

  useEffect(() => {
    const interval = setInterval(() => {
      setThought(GEMINI_THOUGHTS[Math.floor(Math.random() * GEMINI_THOUGHTS.length)]);
      setKey((k) => k + 1);
    }, 6000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="rounded-lg border border-violet-500/20 bg-violet-950/20 p-2.5 relative overflow-hidden">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-xs">✨</span>
        <span className="text-[8px] uppercase tracking-widest text-violet-400/70 font-bold">Gemini Fleet Commander — Thinking</span>
        <motion.div
          className="ml-auto flex gap-0.5"
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1.2, repeat: Infinity }}
        >
          <span className="h-1 w-1 rounded-full bg-violet-400" />
          <span className="h-1 w-1 rounded-full bg-violet-400" />
          <span className="h-1 w-1 rounded-full bg-violet-400" />
        </motion.div>
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={key}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.5 }}
          className="text-[10px] font-mono text-white/90 leading-relaxed"
        >
          {thought}
        </motion.div>
      </AnimatePresence>
      {auditStatus?.generated_at && (
        <div className="text-[8px] text-violet-400/30 mt-1 font-mono">
          Last audit: {new Date(auditStatus.generated_at).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
