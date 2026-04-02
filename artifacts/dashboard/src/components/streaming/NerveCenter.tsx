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
    }, 6000);
    return () => clearInterval(interval);
  }, [displayTrades.length]);

  if (displayTrades.length === 0) {
    return (
      <div className="flex items-center justify-center py-3">
        <span className="text-[8px] font-mono text-white/20">No open trades to analyze</span>
      </div>
    );
  }

  const trade = displayTrades[currentIdx];
  const isUp = trade.pnlUsd >= 0;

  return (
    <div className="px-3 py-2">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1">
          <span className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(99,102,241,0.45)" }}>
            Trade Insight
          </span>
          <span className="text-[7px] font-mono text-white/20">
            {currentIdx + 1}/{displayTrades.length}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {displayTrades.map((_, i) => (
            <span
              key={i}
              className="h-1 w-1 rounded-full transition-colors duration-300"
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
          className="rounded-lg border border-white/[0.06] bg-slate-900/60 px-2.5 py-2"
        >
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px]">{trade.icon}</span>
              <span className="text-[8px] font-bold uppercase tracking-wider" style={{ color: trade.color }}>
                {trade.bot}
              </span>
              <span className="text-[8px] font-mono text-white/60">
                {trade.side.toUpperCase()} {trade.symbol}
              </span>
            </div>
            <span
              className="text-[9px] font-mono font-bold"
              style={{ color: isUp ? "#00ff88" : "#ff4d4d" }}
            >
              {isUp ? "+" : ""}${trade.pnlUsd.toFixed(2)}
            </span>
          </div>
          <div className="text-[7px] leading-relaxed text-white/50 font-mono line-clamp-3">
            {trade.reason}
          </div>
          {trade.entryTime && (
            <div className="text-[6px] text-white/20 font-mono mt-1">
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

    return insights.sort((a, b) => Math.abs(b.pnlUsd) - Math.abs(a.pnlUsd));
  }, [livePositions, djStatus.data, bbStatus.data, caStatus.data, optPositions, fxPositions]);

  const algoPopups = useAlgoPopups();
  const [scanY, setScanY] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setScanY((prev) => (prev >= 100 ? 0 : prev + 0.5));
    }, 30);
    return () => clearInterval(interval);
  }, []);

  const cx = 200;
  const cy = 150;
  const radius = 105;

  const activeCount = Object.values(botActive).filter(Boolean).length;

  const formulaText = FORMULA_SNIPPETS.join("   ·   ");
  const formulaY = 340;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex items-center justify-center gap-3 pt-1 shrink-0">
        <div className="text-[9px] uppercase tracking-widest text-indigo-400/50 font-bold">Nerve Center</div>
        <div className="flex items-center gap-1.5 rounded-md border border-green-500/20 bg-green-500/5 px-2 py-0.5">
          <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
          <span className="text-[10px] font-mono font-bold text-green-400" style={{ textShadow: "0 0 8px rgba(34,197,94,0.5)" }}>
            {activeCount}/6 Bots Live
          </span>
        </div>
      </div>

      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="flex-1 flex items-center justify-center relative p-2 min-h-0 overflow-hidden">
          <div
            className="absolute left-0 right-0 pointer-events-none z-20"
            style={{
              top: `${scanY}%`,
              height: "2px",
              background: "linear-gradient(90deg, transparent, rgba(34,211,238,0.2), rgba(34,211,238,0.4), rgba(34,211,238,0.2), transparent)",
              boxShadow: "0 0 6px rgba(34,211,238,0.25), 0 0 14px rgba(34,211,238,0.1)",
              transition: "top 30ms linear",
            }}
          />
          <div
            className="absolute left-0 right-0 pointer-events-none z-20"
            style={{
              top: `${scanY}%`,
              height: "30px",
              background: "linear-gradient(180deg, rgba(34,211,238,0.03), transparent)",
              transform: "translateY(-100%)",
            }}
          />

          <svg viewBox="0 0 400 360" className="w-full h-full max-w-full max-h-full" preserveAspectRatio="xMidYMid meet">
            <defs>
              <radialGradient id="brainGlow" cx="50%" cy="48%" r="50%">
                <stop offset="0%" stopColor="rgba(99,102,241,0.2)" />
                <stop offset="50%" stopColor="rgba(139,92,246,0.08)" />
                <stop offset="100%" stopColor="rgba(99,102,241,0)" />
              </radialGradient>
              <radialGradient id="brainCore" cx="50%" cy="48%" r="30%">
                <stop offset="0%" stopColor="rgba(167,139,250,0.25)" />
                <stop offset="100%" stopColor="rgba(99,102,241,0)" />
              </radialGradient>
              <filter id="neonGlow">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="heavyGlow">
                <feGaussianBlur stdDeviation="8" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <clipPath id="formulaClip">
                <rect x="20" y={formulaY - 2} width="360" height="16" />
              </clipPath>
            </defs>

            <circle cx={cx} cy={cy} r={85} fill="url(#brainGlow)" />
            <circle cx={cx} cy={cy} r={55} fill="url(#brainCore)" />

            <motion.circle
              cx={cx} cy={cy} r={58}
              fill="none"
              stroke="rgba(139,92,246,0.15)"
              strokeWidth={1}
              animate={{ scale: [1, 1.36, 1], opacity: [0.3, 0, 0.3] }}
              transition={{ duration: 3, repeat: Infinity, ease: "easeOut" }}
              style={{ transformOrigin: `${cx}px ${cy}px` }}
            />
            <motion.circle
              cx={cx} cy={cy} r={48}
              fill="none"
              stroke="rgba(99,102,241,0.2)"
              strokeWidth={1}
              animate={{ scale: [1, 1.55, 1], opacity: [0.4, 0, 0.4] }}
              transition={{ duration: 3, repeat: Infinity, ease: "easeOut", delay: 1.5 }}
              style={{ transformOrigin: `${cx}px ${cy}px` }}
            />
            <motion.circle
              cx={cx} cy={cy} r={42}
              fill="none"
              stroke="rgba(167,139,250,0.12)"
              strokeWidth={1.5}
              animate={{ scale: [1, 2.25, 1], opacity: [0.2, 0, 0.2] }}
              transition={{ duration: 4, repeat: Infinity, ease: "easeOut", delay: 0.8 }}
              style={{ transformOrigin: `${cx}px ${cy}px` }}
            />

            <motion.circle
              cx={cx} cy={cy} r={38}
              fill="rgba(99,102,241,0.06)"
              stroke="rgba(129,140,248,0.5)"
              strokeWidth={2}
              filter="url(#heavyGlow)"
              animate={{ opacity: [0.5, 1, 0.5], scale: [0.97, 1.03, 0.97] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
              style={{ transformOrigin: `${cx}px ${cy}px` }}
            />

            <motion.text
              x={cx} y={cy - 5}
              textAnchor="middle" fontSize="30"
              animate={{ scale: [1, 1.1, 1], opacity: [0.8, 1, 0.8] }}
              transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
              style={{ transformOrigin: `${cx}px ${cy - 5}px` }}
            >
              🧠
            </motion.text>
            <text x={cx} y={cy + 22} textAnchor="middle" fill="rgba(167,139,250,0.8)" fontSize="8" fontWeight="bold">QUANT BRAIN</text>
            <motion.text
              x={cx} y={cy + 33}
              textAnchor="middle" fill="rgba(129,140,248,0.5)" fontSize="7"
              animate={{ opacity: [0.3, 0.7, 0.3] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              ALL NODES SYNCED
            </motion.text>

            {BOTS.map((bot) => {
              const rad = (bot.angle * Math.PI) / 180;
              const bx = cx + Math.cos(rad) * radius;
              const by = cy + Math.sin(rad) * radius;
              const active = botActive[bot.id] ?? false;

              const dx = bx - cx;
              const dy = by - cy;
              const midX = cx + dx;
              const midY = cy;
              const orthoPath = Math.abs(dx) > Math.abs(dy)
                ? `M ${cx} ${cy} L ${midX} ${midY} L ${bx} ${by}`
                : `M ${cx} ${cy} L ${cx} ${by} L ${bx} ${by}`;

              return (
                <g key={bot.id}>
                  {active && (
                    <>
                      <motion.path
                        d={orthoPath}
                        stroke={bot.color}
                        strokeWidth={2}
                        fill="none"
                        filter="url(#neonGlow)"
                        animate={{ opacity: [0.2, 0.7, 0.2] }}
                        transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                      />
                      <motion.circle
                        r={4}
                        fill={bot.color}
                        filter="url(#neonGlow)"
                      >
                        <animateMotion
                          dur="2s"
                          repeatCount="indefinite"
                          path={orthoPath}
                        />
                      </motion.circle>
                    </>
                  )}
                  {!active && (
                    <path
                      d={orthoPath}
                      stroke="rgba(100,116,139,0.35)"
                      strokeWidth={1}
                      strokeDasharray="6 4"
                      fill="none"
                    />
                  )}

                  {active && (
                    <motion.circle
                      cx={bx} cy={by} r={30}
                      fill="none"
                      stroke={bot.color}
                      strokeWidth={1}
                      animate={{ opacity: [0.1, 0.4, 0.1], scale: [0.93, 1.14, 0.93] }}
                      transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                      style={{ transformOrigin: `${bx}px ${by}px` }}
                    />
                  )}

                  <circle
                    cx={bx} cy={by} r={24}
                    fill={active ? `${bot.color}15` : "rgba(30,30,40,0.6)"}
                    stroke={active ? bot.color : "rgba(100,116,139,0.3)"}
                    strokeWidth={active ? 2.5 : 1}
                    filter={active ? "url(#neonGlow)" : undefined}
                  />

                  <text x={bx} y={by + 5} textAnchor="middle" fontSize="18">{bot.icon}</text>
                  <text
                    x={bx} y={by + 35}
                    textAnchor="middle"
                    fill={active ? bot.color : "rgba(100,116,139,0.5)"}
                    fontSize="6.5"
                    fontWeight="bold"
                  >
                    {bot.name.toUpperCase()}
                  </text>
                  <text
                    x={bx} y={by + 44}
                    textAnchor="middle"
                    fill={active ? `${bot.color}99` : "rgba(100,116,139,0.35)"}
                    fontSize="5"
                  >
                    ({bot.subtitle})
                  </text>

                  {!active && (
                    <text x={bx + 20} y={by - 15} fontSize="11">💤</text>
                  )}
                </g>
              );
            })}

            <foreignObject x="20" y={formulaY} width="360" height="16" clipPath="url(#formulaClip)">
              <div
                style={{
                  overflow: "hidden",
                  width: "360px",
                  height: "16px",
                }}
              >
                <div
                  className="formula-ticker"
                  style={{
                    display: "flex",
                    whiteSpace: "nowrap",
                    fontFamily: "monospace",
                    fontSize: "7px",
                    color: "rgba(255,255,255,0.7)",
                    letterSpacing: "0.5px",
                  }}
                >
                  <span style={{ paddingRight: "40px" }}>{formulaText}</span>
                  <span style={{ paddingRight: "40px" }}>{formulaText}</span>
                </div>
              </div>
            </foreignObject>

          </svg>

          <AnimatePresence>
            {algoPopups.map((popup) => (
              <motion.div
                key={popup.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.8 }}
                className="absolute pointer-events-none font-mono font-bold text-white tracking-wide"
                style={{
                  left: `${popup.x}%`,
                  top: `${popup.y}%`,
                  transform: "translate(-50%, -50%)",
                  fontSize: "11px",
                  textShadow: "0 0 12px rgba(99,220,241,0.8), 0 0 30px rgba(99,220,241,0.4)",
                  whiteSpace: "nowrap",
                }}
              >
                {popup.text}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>

        <div className="shrink-0 border-t border-white/[0.04]">
          <TradeDialogueBox trades={tradeInsights} />
        </div>
      </div>

      <style>{`
        .formula-ticker {
          animation: formulaScroll 45s linear infinite;
        }
        @keyframes formulaScroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
