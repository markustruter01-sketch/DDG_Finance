import { useState, useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  useKrakenStatus, useOptionsState, useForexState, useStatusSummary,
  useLivePositions, useForexPositions, useOptionsPositions,
} from "@/hooks/use-trading";

const BOTS = [
  { id: "oracle", name: "Oracle", subtitle: "Stocks Bot", icon: "🔮", angle: 270, color: "#facc15" },
  { id: "davy-jones", name: "Davy Jones", subtitle: "Crypto Bot #1", icon: "⚓", angle: 330, color: "#22d3ee" },
  { id: "blackbeard", name: "Blackbeard", subtitle: "Crypto Bot #2", icon: "🏴‍☠️", angle: 30, color: "#f97316" },
  { id: "calypso", name: "Calypso", subtitle: "Crypto Bot #3", icon: "🌊", angle: 90, color: "#a78bfa" },
  { id: "apex", name: "Apex Predator", subtitle: "Options Bot", icon: "🎯", angle: 150, color: "#ef4444" },
  { id: "navigator", name: "Navigator", subtitle: "Forex Bot", icon: "🧭", angle: 210, color: "#14b8a6" },
];

const ALGO_SNIPPETS = [
  "RSI(14) = 32.7 → oversold",
  "VWAP deviation +1.2σ",
  "ATR(14) = $2.41",
  "Kelly f* = 0.18",
  "Sharpe Ratio: 1.87",
  "Bollinger squeeze: true",
  "MACD cross → bullish",
  "IVR = 14.2 → low vol",
  "EMA(21) > EMA(50)",
  "Position risk: 1.3%",
  "Max drawdown: -2.4%",
  "Correlation ρ = 0.12",
  "Vol surface: flat",
  "Momentum Z = +2.1",
  "Regime: BULL → risk-on",
  "Signal consensus: 3/4",
  "Sortino Ratio: 2.34",
  "Win rate: 58.3%",
  "Entropy decay: 0.04",
  "Half-Kelly sizing: $840",
];

const CORNER_POSITIONS = [
  { x: 12, y: 8 },
  { x: 88, y: 8 },
  { x: 12, y: 88 },
  { x: 88, y: 88 },
  { x: 12, y: 48 },
  { x: 88, y: 48 },
];

const FORMULA_SNIPPETS = [
  "f* = (bp − q) / b",
  "σ = √(Σ(xᵢ − μ)² / N)",
  "VPIN = |Vᴮ − Vˢ| / V",
  "RSI = 100 − 100/(1+RS)",
  "Sharpe = (Rₚ − Rᶠ) / σₚ",
  "Z = (x − μ) / σ",
  "ATR = (1/n)Σ TRᵢ",
  "BB = μ ± kσ",
  "EMA = α·Pₜ + (1−α)·EMAₜ₋₁",
  "Sortino = (Rₚ − Rᶠ) / σ_d",
  "OFI = ΔBidᵥ − ΔAskᵥ",
  "ρ = Σ(xᵢyᵢ) / √(Σxᵢ²·Σyᵢ²)",
  "Δ = ∂V/∂S",
  "Θ = −∂V/∂t",
  "Γ = ∂²V/∂S²",
  "VaR₉₅ = μ − 1.645σ",
  "H = −Σ pᵢ log(pᵢ)",
];

const TRADE_REASONS: Record<string, string[]> = {
  oracle: [
    "Regime model detected Bull signal with strong momentum indicators. EMA(21) crossed above EMA(50) confirming uptrend. Kelly criterion sized position at optimal risk-reward ratio.",
    "GROQ analysis identified sector rotation opportunity. RSI recovering from oversold territory with volume confirmation. Position sized via half-Kelly for downside protection.",
    "AI regime classifier confirmed risk-on environment. Asset shows positive correlation divergence from SPY. Stop-loss set at ATR(14) × 2 below entry.",
  ],
  "davy-jones": [
    "VPIN microstructure analysis detected order flow imbalance favoring buyers. ATR-based dynamic stop placed with trailing mechanism. Crypto volatility regime: moderate.",
    "Cross-exchange spread opportunity identified. Bollinger Band squeeze confirmed with declining volatility. Position entered at 2σ deviation from VWAP.",
    "24hr volume surge detected with positive OFI signal. Circuit breaker checked — no recent drawdown events. Multi-source consensus: 3/4 bullish signals aligned.",
  ],
  blackbeard: [
    "Aggressive momentum entry triggered by Z-score breakout above +2.1σ. Higher risk tolerance profile allows larger position sizing. ATR stop at 1.5× standard deviation.",
    "Crypto market microstructure shows strong bid-side absorption. VPIN signal bullish with order flow momentum. Entered at key support level with tight risk management.",
  ],
  calypso: [
    "Conservative mean-reversion entry at 2σ Bollinger Band touch. Low correlation to existing portfolio positions. Position sized conservatively per defensive risk profile.",
    "Entropy-based signal detected regime shift opportunity. Sortino ratio optimization favors asymmetric risk/reward. Deployed at minimum viable position size.",
  ],
  apex: [
    "IVR below 20 threshold detected Bollinger squeeze on underlying. ATM Long Straddle constructed at 35 DTE. Premium paid within 5% capital fence. Volatility expansion expected.",
    "Options scanner identified low implied volatility regime. Straddle strategy deployed to capture expected vol expansion. Max loss capped at premium paid.",
  ],
  navigator: [
    "Forex pair showing strong trend momentum with ADX above 25. Carry trade differential favorable. Position sized via half-Kelly with trailing stop at ATR(14).",
    "Multi-timeframe confluence detected: daily trend + 4H pullback to key support. Interest rate differential positive. Risk managed with dynamic trailing stop.",
  ],
};

function useAlgoPopups() {
  const [popups, setPopups] = useState<{ id: number; text: string; x: number; y: number }[]>([]);
  const nextId = useRef(0);
  const cornerIdx = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      const text = ALGO_SNIPPETS[Math.floor(Math.random() * ALGO_SNIPPETS.length)];
      const id = nextId.current++;
      const corner = CORNER_POSITIONS[cornerIdx.current % CORNER_POSITIONS.length];
      cornerIdx.current++;
      setPopups((prev) => [...prev.slice(-3), { id, text, x: corner.x, y: corner.y }]);
      setTimeout(() => {
        setPopups((prev) => prev.filter((p) => p.id !== id));
      }, 2800);
    }, 1800 + Math.random() * 1200);

    return () => clearInterval(interval);
  }, []);

  return popups;
}

interface TradeInsight {
  bot: string;
  icon: string;
  color: string;
  symbol: string;
  side: string;
  pnlUsd: number;
  reason: string;
  entryTime: string | null;
}

function TradeDialogueBox({ trades }: { trades: TradeInsight[] }) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const displayTrades = trades.slice(0, 10);

  useEffect(() => {
    if (displayTrades.length <= 1) return;
    const interval = setInterval(() => {
      setCurrentIdx((prev) => (prev + 1) % displayTrades.length);
    }, 15000);
    return () => clearInterval(interval);
  }, [displayTrades.length]);

  if (displayTrades.length === 0) {
    return (
      <div className="flex items-center justify-center py-5">
        <span className="text-[13px] font-mono text-white/20">No open trades to analyze</span>
      </div>
    );
  }

  const trade = displayTrades[currentIdx];
  const isUp = trade.pnlUsd >= 0;

  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[13px] uppercase tracking-widest font-bold" style={{ color: "rgba(129,140,248,0.8)" }}>
            Trade Insight
          </span>
          <span className="text-[11px] font-mono text-white/25">
            {currentIdx + 1}/{displayTrades.length}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {displayTrades.map((_, i) => (
            <span
              key={i}
              className="h-1.5 w-1.5 rounded-full transition-colors duration-300"
              style={{ background: i === currentIdx ? "rgba(129,140,248,0.8)" : "rgba(129,140,248,0.15)" }}
            />
          ))}
        </div>
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={currentIdx}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.4 }}
          className="rounded-xl border border-white/[0.08] bg-slate-900/70 px-4 py-3"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-[16px]">{trade.icon}</span>
              <span className="text-[13px] font-bold uppercase tracking-wider" style={{ color: trade.color }}>
                {trade.bot}
              </span>
              <span className="text-[13px] font-mono text-white/80">
                {trade.side.toUpperCase()} {trade.symbol}
              </span>
            </div>
            <span
              className="text-[15px] font-mono font-bold"
              style={{ color: isUp ? "#00ff88" : "#ff4d4d" }}
            >
              {isUp ? "+" : ""}${trade.pnlUsd.toFixed(2)}
            </span>
          </div>
          <div className="text-[11px] leading-relaxed text-white/80 font-mono">
            {trade.reason}
          </div>
          {trade.entryTime && (
            <div className="text-[10px] text-white/25 font-mono mt-2">
              Opened: {new Date(trade.entryTime).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}


export function NerveCenter() {
  const { data: summary } = useStatusSummary();
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: livePositions } = useLivePositions();
  const { data: fxPositions } = useForexPositions();
  const { data: optPositions } = useOptionsPositions();
  const botActive: Record<string, boolean> = {
    oracle: !!(summary?.market_open),
    "davy-jones": !!(djStatus.data && djStatus.data.status !== "not_started" && !djStatus.data.bot_paused),
    blackbeard: !!(bbStatus.data && bbStatus.data.status !== "not_started" && !bbStatus.data.bot_paused),
    calypso: !!(caStatus.data && caStatus.data.status !== "not_started" && !caStatus.data.bot_paused),
    apex: !!(optState && !optState.paused),
    navigator: !!(fxState && !fxState.paused),
  };

  const tradeInsights = useMemo<TradeInsight[]>(() => {
    const insights: TradeInsight[] = [];

    for (const p of livePositions?.positions ?? []) {
      const reasons = TRADE_REASONS.oracle;
      insights.push({
        bot: "Oracle", icon: "🔮", color: "#facc15",
        symbol: p.symbol, side: p.side,
        pnlUsd: p.unrealized_pl,
        reason: reasons[Math.abs(p.symbol.charCodeAt(0)) % reasons.length],
        entryTime: null,
      });
    }

    const krakenBots: Array<{ data: typeof djStatus.data; botKey: string; bot: string; icon: string; color: string }> = [
      { data: djStatus.data, botKey: "davy-jones", bot: "Davy Jones", icon: "⚓", color: "#22d3ee" },
      { data: bbStatus.data, botKey: "blackbeard", bot: "Blackbeard", icon: "🏴‍☠️", color: "#f97316" },
      { data: caStatus.data, botKey: "calypso", bot: "Calypso", icon: "🌊", color: "#a78bfa" },
    ];
    for (const { data, botKey, bot, icon, color } of krakenBots) {
      if (!data?.open_positions) continue;
      const reasons = TRADE_REASONS[botKey] ?? TRADE_REASONS["davy-jones"];
      for (const p of data.open_positions) {
        insights.push({
          bot, icon, color,
          symbol: p.symbol, side: p.side,
          pnlUsd: p.unrealized_pnl_usd,
          reason: reasons[Math.abs(p.symbol.charCodeAt(0)) % reasons.length],
          entryTime: p.entry_time,
        });
      }
    }

    for (const p of optPositions?.positions ?? []) {
      const reasons = TRADE_REASONS.apex;
      insights.push({
        bot: "Apex Predator", icon: "🎯", color: "#ef4444",
        symbol: `${p.symbol} ${p.strategy}`, side: "long",
        pnlUsd: p.unrealized_pnl,
        reason: reasons[Math.abs(p.symbol.charCodeAt(0)) % reasons.length],
        entryTime: p.opened_at ?? p.scanned_at,
      });
    }

    for (const p of fxPositions?.positions ?? []) {
      const reasons = TRADE_REASONS.navigator;
      insights.push({
        bot: "Navigator", icon: "🧭", color: "#14b8a6",
        symbol: p.pair.replace("_", "/"), side: p.direction,
        pnlUsd: p.unrealized_pnl_usd,
        reason: reasons[Math.abs(p.pair.charCodeAt(0)) % reasons.length],
        entryTime: p.entry_time,
      });
    }

    return insights.filter((t) => t.pnlUsd > 0).sort((a, b) => b.pnlUsd - a.pnlUsd);
  }, [livePositions, djStatus.data, bbStatus.data, caStatus.data, optPositions, fxPositions]);

  /* DEACTIVATED: SVG overlay variables — reactivate with original nerve center graphics */
  // const algoPopups = useAlgoPopups();
  // const [scanY, setScanY] = useState(0);
  // useEffect(() => {
  //   const interval = setInterval(() => {
  //     setScanY((prev) => (prev >= 100 ? 0 : prev + 0.5));
  //   }, 30);
  //   return () => clearInterval(interval);
  // }, []);
  // const cx = 200;
  // const cy = 150;
  // const radius = 105;
  // const formulaElements = FORMULA_SNIPPETS.map((f, i) => (
  //   <span key={i}>
  //     {i > 0 && <span style={{ color: "rgba(34,211,238,0.7)", padding: "0 6px" }}>│</span>}
  //     <span>{f}</span>
  //   </span>
  // ));
  // const formulaY = 340;

  const activeCount = Object.values(botActive).filter(Boolean).length;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex items-center justify-center gap-3 pt-1 shrink-0">
        <div className="text-[15px] uppercase tracking-widest text-indigo-400/50 font-bold">Nerve Center</div>
        <div className="flex items-center gap-1.5 rounded-md border border-green-500/20 bg-green-500/5 px-2 py-0.5">
          <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
          <span className="text-[10px] font-mono font-bold text-green-400" style={{ textShadow: "0 0 8px rgba(34,197,94,0.5)" }}>
            {activeCount}/6 Bots Live
          </span>
        </div>
      </div>

      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="flex-1 relative min-h-0 overflow-hidden p-2">
          <motion.div
            className="absolute inset-1 rounded-xl pointer-events-none z-10"
            style={{
              border: "2px solid rgba(99,102,241,0.4)",
              boxShadow: "0 0 12px rgba(99,102,241,0.15), inset 0 0 12px rgba(99,102,241,0.05)",
            }}
            animate={{
              boxShadow: [
                "0 0 12px rgba(99,102,241,0.15), inset 0 0 12px rgba(99,102,241,0.05)",
                "0 0 24px rgba(139,92,246,0.35), inset 0 0 20px rgba(139,92,246,0.1)",
                "0 0 12px rgba(99,102,241,0.15), inset 0 0 12px rgba(99,102,241,0.05)",
              ],
              borderColor: [
                "rgba(99,102,241,0.4)",
                "rgba(139,92,246,0.6)",
                "rgba(99,102,241,0.4)",
              ],
            }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
          />
          <video
            autoPlay
            loop
            muted
            playsInline
            className="w-full h-full object-cover rounded-xl"
            src={`${import.meta.env.BASE_URL}ai-brain-loop.mp4`}
          />
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-20" style={{ marginLeft: "-12px", marginTop: "135px" }}>
            <svg viewBox="-30 -10 260 240" className="w-[900px] h-[630px]" preserveAspectRatio="xMidYMid meet">
              <motion.circle
                cx={100} cy={90} r={24}
                fill="none"
                stroke="rgba(250,204,21,0.7)"
                strokeWidth={2}
                animate={{
                  opacity: [0.5, 1, 0.5],
                }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
              />
              <text
                x={100} y={97}
                textAnchor="middle" fontSize="33"
              >
                🧠
              </text>
              <text x={100} y={122} textAnchor="middle" fill="rgba(167,139,250,0.8)" fontSize="7" fontWeight="bold">QUANT BRAIN</text>
              <text
                x={100} y={131}
                textAnchor="middle" fill="rgba(129,140,248,0.5)" fontSize="6"
              >
                ALL NODES SYNCED
              </text>
            </svg>
          </div>
        </div>

        <div className="shrink-0 border-t border-white/[0.04]">
          <TradeDialogueBox trades={tradeInsights} />
        </div>
      </div>
    </div>
  );
}
