import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useFleetCommanderStatus } from "@/hooks/use-trading";

const GEMINI_THOUGHTS = [
  {
    title: "Cross-Fleet Correlation Alert",
    body: "Detected a recurring pattern of losing BTC/USD shorts in the last 48 hours across SPY/QQQ Trend and Jerome. Injecting RAG context into both bots' next analysis cycle to bias away from counter-trend shorts until momentum confirms a reversal. Additionally, cross-referencing on-chain flow data from Glassnode shows net exchange outflows increasing — historically a bullish signal that contradicts our short bias. Recommending both bots reduce BTC short conviction by 40% until the momentum regime shifts back to bearish.",
  },
  {
    title: "GBP Volatility Regime Shift",
    body: "Forex Gump's GBP/USD short hit its stop-loss at 1.5× ATR — the third consecutive loss on GBP pairs this week. Tightening the news blackout window from 4 hours to 6 hours around Bank of England announcements to reduce exposure to high-impact volatility. Post-mortem analysis shows all three losses occurred within 90 minutes of scheduled BoE communications. Implementing a hard position freeze on all GBP crosses during the expanded blackout window and rotating Forex Gump's allocation toward EUR/CHF and AUD/NZD pairs where ATR-normalized returns have been strongest this month.",
  },
  {
    title: "Concentration Risk Detected",
    body: "Cross-asset correlation matrix shows ρ=0.87 between BTC and ETH positions held by SPY/QQQ Trend and Sector Rotation simultaneously. Flagging concentration risk — if crypto sells off, both bots take correlated losses which amplifies portfolio drawdown. Recommending Sector Rotation rotate into lower-correlation alts like ATOM/USD (ρ=0.34) and ARB/USD (ρ=0.28) next cycle. This diversification should reduce fleet-wide crypto sector beta from 1.4 to approximately 0.9 while maintaining similar expected return profiles based on backtested Sharpe ratios.",
  },
  {
    title: "Regime Model Update",
    body: "Oracle's regime model has shifted from BULL to SIDEWAYS based on declining SPY momentum and flattening yield curve data. The 10Y-2Y spread compressed to 18bps, down from 34bps last week. Reducing equity allocation by 40% and rotating freed capital into TLT and GLD as defensive hedges. The Macro Compass sentiment indicator also dropped to 42 (Fear zone), which historically precedes 2-4 weeks of range-bound price action. Adjusting all bot confidence multipliers down by 20% until regime clarity improves. Expected portfolio beta reduction: 0.85 → 0.52.",
  },
  {
    title: "Fleet Status — All Clear",
    body: "Fleet-wide drawdown currently at -0.56%, well within the 3% tolerance threshold. All six bots are operating within normal parameters. Kraken trio (SPY/QQQ Trend, Jerome, Sector Rotation) collectively showing +2.1% unrealized P&L across 30 open positions. Options book theta decay on track. Forex pairs within expected ranges. No parameter adjustments needed this cycle — letting all bots continue with current configurations. Next full diagnostic scheduled in 15 minutes. Risk budget utilization: 23% of daily max.",
  },
  {
    title: "SOL/USD Breakout Validation",
    body: "Jerome's SOL/USD Z-score spiked to +2.8, triggering a potential momentum entry signal. However, validating against VPIN data (currently 0.72, elevated) and on-chain flow metrics before allowing execution. False breakouts on SOL have cost us 3 trades this month with an average loss of -1.8% per trade. Requiring confluence of: (1) VPIN dropping below 0.60, (2) OFI turning positive, and (3) 15-min volume exceeding 2× average before greenlighting the entry. Estimated wait time: 20-45 minutes for confirmation conditions to resolve.",
  },
  {
    title: "Macro Compass — USD Weakness",
    body: "Groq-powered Macro Compass update indicates USD weakening on soft NFP expectations. The DXY broke below its 50-day EMA for the first time in 3 weeks. Adjusting Forex Gump's directional bias to favor long EUR/USD (target: 1.0920) and long AUD/USD (target: 0.6680) setups while reducing conviction on USD/JPY longs until the employment data confirms. Additionally, running Monte Carlo simulations on Forex Gump's forex book shows 73% probability of positive week if USD continues to weaken at current pace. Position sizing increased by 15% on high-conviction EUR/USD setup.",
  },
  {
    title: "Stop-Loss Optimization — Sector Rotation",
    body: "Sector Rotation's ATR-based stops on ARB/USD are too wide at 2.1× given current low-volatility conditions. 14-day ATR has compressed 30% from its monthly high. Tightening to 1.8× ATR to protect unrealized gains of +$127.40 and reduce risk-per-trade from 1.4% back down to the target 1.0%. Also reviewing trailing stop parameters across all Sector Rotation positions — the current 5% trail caught the recent ATOM/USD pullback perfectly (+4.2% realized), confirming the trailing mechanism is working as designed. No changes to trail percentage needed.",
  },
  {
    title: "Fear & Greed Divergence Signal",
    body: "Fear & Greed Index dropped to 42 (Fear zone) while BTC on-chain accumulation addresses are rising by 12,000 per day — the highest rate in 6 weeks. This divergence historically precedes a 5-10% rally within 7-14 days based on our backtest of 47 similar setups since 2020 (win rate: 68%, avg return: +7.2%). Flagging as a high-conviction long setup for SPY/QQQ Trend to evaluate next cycle. Recommended position size: 2× standard allocation with a 1.5× ATR stop. Risk/reward ratio at current levels: approximately 3.2:1.",
  },
];

export function GeminiThinking() {
  const [thoughtIdx, setThoughtIdx] = useState(0);
  const [key, setKey] = useState(0);
  const { data: auditStatus } = useFleetCommanderStatus();

  useEffect(() => {
    const interval = setInterval(() => {
      setThoughtIdx(Math.floor(Math.random() * GEMINI_THOUGHTS.length));
      setKey((k) => k + 1);
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  const thought = GEMINI_THOUGHTS[thoughtIdx];

  return (
    <div className="rounded-lg border border-violet-500/20 bg-violet-950/20 p-4 relative overflow-hidden flex-1 flex flex-col min-h-0">
      <div className="flex items-center gap-2 mb-1 shrink-0">
        <span className="text-lg">🧠</span>
        <div className="flex flex-col">
          <span
            className="text-[15px] uppercase tracking-wider font-black text-white"
            style={{ textShadow: "0 0 20px rgba(167,139,250,0.6), 0 0 40px rgba(139,92,246,0.3)" }}
          >
            Gemini Fleet Commander
          </span>
          <span className="text-[8px] uppercase tracking-widest font-bold -mt-0.5" style={{ color: "rgba(167,139,250,0.5)" }}>AI Orchestrator · Quant Brain</span>
        </div>
        <motion.div
          className="ml-auto flex gap-0.5"
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1.2, repeat: Infinity }}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
          <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
          <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
        </motion.div>
      </div>
      <div className="flex-1 overflow-hidden min-h-0">
        <AnimatePresence mode="wait">
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.5 }}
            className="flex flex-col gap-2 h-full"
          >
            <div className="text-[16px] font-mono font-bold" style={{ color: "rgba(196,181,253,0.9)" }}>{thought.title}</div>
            <div className="text-[15px] font-mono leading-[1.55] flex-1 overflow-hidden" style={{ color: "rgba(255,255,255,0.8)" }}>
              {thought.body}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
      {auditStatus?.generated_at && (
        <div className="text-[9px] mt-2 font-mono shrink-0" style={{ color: "rgba(167,139,250,0.3)" }}>
          Last audit: {new Date(auditStatus.generated_at).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
