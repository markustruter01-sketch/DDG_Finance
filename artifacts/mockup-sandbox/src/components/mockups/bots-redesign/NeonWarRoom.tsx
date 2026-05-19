import React from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import "./_group.css";

const bots = [
  {
    name: "ORACLE",
    emoji: "🔮",
    platform: "Alpaca · Stocks",
    equity: "$90,288",
    pnl: "-$9,712",
    pnlPercent: "-9.71%",
    status: "STALE",
    openPositions: 0,
    openPositionsList: [],
    strategy: "MOMENTUM STOCKS NYSE",
    winLoss: "⚡22W / 💀14L",
    color: "#ff00ff", // Magenta
    trades: [
      { asset: "NVDA", pnl: "-$2,100" },
      { asset: "AAPL", pnl: "+$890" },
      { asset: "META", pnl: "-$1,450" },
    ],
    signal: "Z-SCORE > 2.1 | MIN PROFIT 0.5%",
  },
  {
    name: "SPY/QQQ TREND",
    emoji: "📈",
    platform: "Alpaca · ETFs",
    equity: "$110,081",
    pnl: "+$10,081",
    pnlPercent: "+10.08%",
    status: "LIVE",
    openPositions: 1,
    openPositionsList: ["SPY"],
    strategy: "TREND ETF ROTATION",
    winLoss: "⚡45W / 💀12L",
    color: "#00f3ff", // Cyan
    trades: [
      { asset: "SPY", pnl: "+$234" },
      { asset: "QQQ", pnl: "-$112" },
      { asset: "SPY", pnl: "+$445" },
    ],
    signal: "Z-ENTRY 2.0 | Z-EXIT 0.3",
  },
  {
    name: "JEROME",
    emoji: "🏛️",
    platform: "Alpaca · Macro",
    equity: "$100,000",
    pnl: "$0",
    pnlPercent: "0.0%",
    status: "LIVE",
    openPositions: 0,
    openPositionsList: [],
    strategy: "LLM MACRO FUTURES",
    winLoss: "⚡0W / 💀0L",
    color: "#ffaa00", // Orange
    trades: [],
    signal: "LLM @ 9AM/9PM UTC",
  },
  {
    name: "FOREX GUMP",
    emoji: "🧭",
    platform: "Oanda · Forex",
    equity: "$102,639",
    pnl: "+$2,639",
    pnlPercent: "+2.64%",
    status: "LIVE",
    openPositions: 5,
    openPositionsList: ["EURUSD", "GBPJPY", "AUDUSD", "USDJPY", "EURGBP"],
    strategy: "G10 CURRENCY TREND",
    winLoss: "⚡32W / 💀18L",
    color: "#39ff14", // Green
    trades: [
      { asset: "EURUSD", pnl: "+$412" },
      { asset: "GBPUSD", pnl: "-$89" },
      { asset: "GBPJPY", pnl: "+$677" },
    ],
    signal: "G10 PAIRS | ATR STOPS",
  },
  {
    name: "LISTING PUMP",
    emoji: "🚀",
    platform: "Kraken · Crypto",
    equity: "$100,000",
    pnl: "$0",
    pnlPercent: "0.0%",
    status: "LIVE",
    openPositions: 0,
    openPositionsList: [],
    strategy: "NEW EXCHANGE LISTING",
    winLoss: "⚡0W / 💀0L",
    color: "#ff00ff",
    trades: [],
    signal: "24/7 MOMENTUM SPY",
  },
  {
    name: "EVENT TRADER",
    emoji: "⚡",
    platform: "Kraken · Crypto",
    equity: "$100,000",
    pnl: "$0",
    pnlPercent: "0.0%",
    status: "LIVE",
    openPositions: 0,
    openPositionsList: [],
    strategy: "MACRO EVENT VOL",
    winLoss: "⚡0W / 💀0L",
    color: "#00f3ff",
    trades: [],
    signal: "VOLATILITY SPIKE",
  },
  {
    name: "DEPEG HUNTER",
    emoji: "🎯",
    platform: "Kraken · Crypto",
    equity: "$100,000",
    pnl: "$0",
    pnlPercent: "0.0%",
    status: "LIVE",
    openPositions: 0,
    openPositionsList: [],
    strategy: "STABLECOIN ARB",
    winLoss: "⚡0W / 💀0L",
    color: "#ff003c",
    trades: [],
    signal: "DEPEG DETECTED",
  },
  {
    name: "MEME VELOCITY",
    emoji: "🌙",
    platform: "Kraken · Crypto",
    equity: "$100,000",
    pnl: "$0",
    pnlPercent: "0.0%",
    status: "LIVE",
    openPositions: 0,
    openPositionsList: [],
    strategy: "VELOCITY BREAKOUTS",
    winLoss: "⚡0W / 💀0L",
    color: "#39ff14",
    trades: [],
    signal: "MOMENTUM LOCK",
  },
];

export function NeonWarRoom() {
  return (
    <div className="min-h-screen w-full bg-synth-grid text-white overflow-hidden flex flex-col font-['Space_Grotesk'] selection:bg-fuchsia-500 selection:text-white">
      {/* Header */}
      <header className="relative h-24 border-b border-fuchsia-900/50 flex items-center justify-between px-8 bg-black/60 backdrop-blur-sm overflow-hidden z-10">
        <div className="absolute inset-0 w-full h-[2px] bg-cyan-400/20 animate-scanline pointer-events-none" />
        
        <div className="flex items-center gap-6">
          <h1 className="text-4xl font-black tracking-widest font-['Orbitron'] text-fuchsia-500 animate-flicker" style={{ color: "var(--neon-magenta)" }}>
            WAR ROOM
          </h1>
          <div className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-red-950/40 border border-red-500/50">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="text-red-400 font-bold text-xs uppercase tracking-wider">1 BOT STALE (NYSE CLOSED)</span>
          </div>
        </div>

        <div className="flex items-center gap-8">
          <div className="flex flex-col items-end">
            <span className="text-xs text-cyan-400/70 font-mono tracking-widest uppercase">Fleet Equity</span>
            <span className="text-3xl font-bold font-mono text-cyan-400 drop-shadow-[0_0_8px_rgba(0,243,255,0.6)]">
              $803,007
            </span>
          </div>
          <div className="flex flex-col items-end border-l border-white/10 pl-8">
            <span className="text-xs text-green-400/70 font-mono tracking-widest uppercase">Fleet P&L</span>
            <span className="text-2xl font-bold font-mono text-green-400 drop-shadow-[0_0_8px_rgba(57,255,20,0.6)]">
              +$3,007 <span className="text-lg opacity-80">(+0.38%)</span>
            </span>
          </div>
        </div>
      </header>

      {/* Grid */}
      <main className="flex-1 p-8 overflow-y-auto">
        <div className="grid grid-cols-4 gap-6 max-w-[1800px] mx-auto">
          {bots.map((bot, i) => {
            const isPositive = bot.pnl.startsWith("+");
            const isNegative = bot.pnl.startsWith("-");
            const pnlColor = isPositive ? "text-green-400" : isNegative ? "text-red-400" : "text-gray-400";
            const pnlShadow = isPositive 
              ? "drop-shadow-[0_0_8px_rgba(57,255,20,0.6)]" 
              : isNegative 
                ? "drop-shadow-[0_0_8px_rgba(255,0,60,0.6)]" 
                : "";

            return (
              <Card 
                key={i}
                className="relative bg-[#0a0011]/80 backdrop-blur-md border-0 rounded-xl overflow-hidden group hover:scale-[1.02] transition-transform duration-300"
                style={{
                  boxShadow: `0 0 15px -5px ${bot.color}, inset 0 0 20px -10px ${bot.color}`,
                  border: `1px solid ${bot.color}40`,
                }}
              >
                {/* Top accent bar */}
                <div className="h-1 w-full" style={{ backgroundColor: bot.color, boxShadow: `0 0 10px ${bot.color}` }} />
                
                <div className="p-5 flex flex-col h-full gap-4">
                  {/* Header */}
                  <div className="flex justify-between items-start">
                    <div className="flex items-center gap-3">
                      <span className="text-3xl filter drop-shadow-md">{bot.emoji}</span>
                      <div>
                        <h2 className="font-['Orbitron'] font-bold text-lg tracking-wider" style={{ color: bot.color, textShadow: `0 0 8px ${bot.color}80` }}>
                          {bot.name}
                        </h2>
                        <div className="text-xs text-white/50 font-mono tracking-widest">{bot.platform}</div>
                      </div>
                    </div>
                    <div className="flex flex-col items-end">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-bold tracking-widest text-white/70">{bot.status}</span>
                        <div 
                          className="w-2.5 h-2.5 rounded-full animate-pulse-glow" 
                          style={{ 
                            backgroundColor: bot.status === 'LIVE' ? 'var(--neon-green)' : 'var(--neon-red)',
                            color: bot.status === 'LIVE' ? 'var(--neon-green)' : 'var(--neon-red)'
                          }} 
                        />
                      </div>
                      <Badge variant="outline" className="bg-black/40 text-[10px] border-white/10 font-mono text-white/60">
                        {bot.winLoss}
                      </Badge>
                    </div>
                  </div>

                  {/* Numbers */}
                  <div className="grid grid-cols-2 gap-4 py-2">
                    <div>
                      <div className="text-[10px] text-white/40 uppercase tracking-widest mb-1">Equity</div>
                      <div className="text-2xl font-mono font-bold text-white drop-shadow-[0_0_5px_rgba(255,255,255,0.5)]">
                        {bot.equity}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-white/40 uppercase tracking-widest mb-1 text-right">P&L</div>
                      <div className={`text-xl font-mono font-bold text-right ${pnlColor} ${pnlShadow}`}>
                        {bot.pnl} <span className="text-sm opacity-80 block">{bot.pnlPercent}</span>
                      </div>
                    </div>
                  </div>

                  {/* Active Positions */}
                  <div>
                    <div className="text-[10px] text-white/40 uppercase tracking-widest mb-2 flex justify-between">
                      <span>Open Positions</span>
                      <span className="text-white/80 font-mono">{bot.openPositions}</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5 min-h-[24px]">
                      {bot.openPositionsList.length > 0 ? (
                        bot.openPositionsList.map((pos, idx) => (
                          <span 
                            key={idx} 
                            className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-cyan-950/50 text-cyan-400 border border-cyan-500/30"
                            style={{ boxShadow: "0 0 5px rgba(0,243,255,0.2)" }}
                          >
                            {pos}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs font-mono text-white/20 italic">No active trades</span>
                      )}
                    </div>
                  </div>

                  {/* Entry Signal */}
                  <div className="mt-auto pt-4 border-t border-white/10">
                    <div className="text-[10px] text-white/40 uppercase tracking-widest mb-1">Entry Config</div>
                    <div className="font-mono text-xs text-white/80 truncate">
                      <span className="text-fuchsia-400 mr-2">»</span>
                      {bot.signal}
                    </div>
                  </div>

                  {/* Tiny Trades Table */}
                  {bot.trades.length > 0 && (
                    <div className="mt-2 bg-black/40 rounded border border-white/5 overflow-hidden">
                      <Table className="max-w-full text-xs">
                        <TableBody>
                          {bot.trades.map((t, idx) => (
                            <TableRow key={idx} className="border-b-white/5 hover:bg-white/5">
                              <TableCell className="py-1 px-2 font-mono text-white/70">{t.asset}</TableCell>
                              <TableCell className={`py-1 px-2 text-right font-mono font-bold ${t.pnl.startsWith('+') ? 'text-green-400' : 'text-red-400'}`}>
                                {t.pnl}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      </main>
    </div>
  );
}
