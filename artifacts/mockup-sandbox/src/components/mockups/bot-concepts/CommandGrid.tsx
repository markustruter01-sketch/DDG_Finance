import React from "react";
import { TrendingUp, TrendingDown, Activity, AlertTriangle, Circle } from "lucide-react";

export default function CommandGrid() {
  const bots = [
    {
      name: "Oracle",
      status: "LIVE",
      equity: "$100,000",
      pnl: "+$0",
      wl: "132/178",
      wr: "42.6%",
      open: 5,
      exchange: "Alpaca · Stocks",
      positions: ["CSX", "ELV", "MET", "MRVL", "MS"],
      accent: "#22d3ee",
      icon: "🔮"
    },
    {
      name: "SPY/QQQ Trend",
      status: "LIVE",
      equity: "$100,000",
      pnl: "+$0",
      wl: "0/0",
      wr: "—",
      open: 0,
      exchange: "Alpaca · ETFs",
      positions: [],
      accent: "#3b82f6",
      icon: "📈"
    },
    {
      name: "Jerome",
      status: "LIVE",
      equity: "$102,448",
      pnl: "+$2,448",
      wl: "0/0",
      wr: "—",
      open: 2,
      exchange: "Alpaca · Macro",
      positions: ["ENS", "WLD"],
      accent: "#f97316",
      icon: "🦅"
    },
    {
      name: "Sector Rotation",
      status: "LIVE",
      equity: "$100,000",
      pnl: "+$0",
      wl: "0/0",
      wr: "—",
      open: 0,
      exchange: "Alpaca · Sectors",
      positions: [],
      accent: "#a855f7",
      icon: "🔄"
    },
    {
      name: "Defensive Guard",
      status: "LIVE",
      equity: "$100,000",
      pnl: "+$0",
      wl: "0/0",
      wr: "—",
      open: 0,
      exchange: "Alpaca · Defensive",
      positions: [],
      accent: "#10b981",
      icon: "🛡️"
    },
    {
      name: "Macro Bond",
      status: "LIVE",
      equity: "$100,000",
      pnl: "+$0",
      wl: "0/0",
      wr: "—",
      open: 0,
      exchange: "Alpaca · Bonds",
      positions: [],
      accent: "#eab308",
      icon: "🏛️"
    },
    {
      name: "Forex Gump",
      status: "PAUSED",
      equity: "$99,799",
      pnl: "-$201",
      wl: "4/12",
      wr: "25%",
      open: 5,
      exchange: "Oanda · Forex",
      positions: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD"],
      accent: "#06b6d4",
      icon: "💱"
    },
    {
      name: "Poseidon",
      status: "LIVE",
      equity: "$100,015",
      pnl: "+$15",
      wl: "8/11",
      wr: "42%",
      open: 0,
      exchange: "Kraken · Crypto",
      positions: [],
      accent: "#8b5cf6",
      icon: "🌊"
    },
    {
      name: "Kraken Trend",
      status: "LIVE",
      equity: "$100,128",
      pnl: "+$128",
      wl: "9/25",
      wr: "26%",
      open: 0,
      exchange: "Kraken · Crypto",
      positions: [],
      accent: "#0ea5e9",
      icon: "🦑"
    }
  ];

  return (
    <div className="h-screen overflow-hidden flex flex-col font-sans text-slate-200" style={{ backgroundColor: "#020617" }}>
      {/* TOP HEADER BAR */}
      <div className="flex-none h-14 border-b border-slate-800 bg-slate-950/50 flex items-center justify-between px-4 text-sm font-medium">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 text-slate-400">
            <span className="text-emerald-500">⬡</span>
            <span className="tracking-widest text-xs font-black uppercase text-slate-300">BOT FLEET</span>
          </div>
          <div className="flex items-center gap-4 text-slate-400">
            <span>Fleet Equity: <span className="text-slate-200">$902,374</span></span>
            <span>P&L: <span className="text-emerald-500">+$2,374</span></span>
            <span>Win Rate: <span className="text-slate-200">36.6%</span></span>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-slate-300"><Circle size={10} className="fill-emerald-500 text-emerald-500" /> 8 LIVE</span>
            <span className="flex items-center gap-1.5 text-amber-500/80"><AlertTriangle size={12} /> 1 PAUSED</span>
          </div>
          <div className="h-4 w-px bg-slate-800"></div>
          <span className="text-slate-400">Open: <span className="text-slate-200 font-bold">7</span></span>
          <div className="flex items-center gap-2 px-2 py-1 bg-emerald-500/10 rounded-full border border-emerald-500/20 text-emerald-500">
            <Activity size={14} />
            <span className="font-bold">SYSTEM LIVE</span>
          </div>
        </div>
      </div>

      {/* GRID */}
      <div className="flex-1 grid grid-cols-3 grid-rows-3 gap-2 p-2 overflow-hidden bg-[#020617]">
        {bots.map((bot, i) => {
          const isPos = bot.pnl.startsWith("+") && bot.pnl !== "+$0";
          const isNeg = bot.pnl.startsWith("-");
          const pnlColor = isPos ? "text-emerald-500" : isNeg ? "text-rose-500" : "text-slate-400";
          
          return (
            <div 
              key={bot.name}
              className="h-full flex flex-col bg-slate-900/40 rounded-xl overflow-hidden border border-slate-800/60 relative"
              style={{
                borderTop: `2px solid ${bot.accent}`,
                background: `linear-gradient(180deg, ${bot.accent}14 0%, transparent 60%)`
              }}
            >
              {/* HEADER ROW */}
              <div className="flex items-start justify-between p-2.5 pb-1">
                <div className="flex flex-col gap-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-lg leading-none">{bot.icon}</span>
                    <span className="text-[11px] font-black uppercase tracking-wider text-slate-200">{bot.name}</span>
                  </div>
                  <span className="text-[9px] font-medium tracking-wide" style={{ color: bot.accent }}>{bot.exchange}</span>
                </div>
                {bot.status === "LIVE" ? (
                  <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-[9px] font-bold text-emerald-500">
                    <Circle size={6} className="fill-emerald-500" />
                    LIVE
                  </div>
                ) : (
                  <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-[9px] font-bold text-amber-500">
                    <AlertTriangle size={8} />
                    PAUSED
                  </div>
                )}
              </div>

              {/* METRICS CONTENT - Flex 1 to push positions/banner to bottom */}
              <div className="flex-1 flex flex-col justify-center px-3 py-1 gap-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-xl font-black font-mono tracking-tight text-white">{bot.equity}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  {isPos ? <TrendingUp size={14} className={pnlColor} /> : isNeg ? <TrendingDown size={14} className={pnlColor} /> : <span className="w-[14px]"></span>}
                  <span className={`text-[14px] font-black ${pnlColor}`}>{bot.pnl}</span>
                  <span className="text-[10px] text-slate-500 font-medium">P&L</span>
                </div>
              </div>

              {/* STATS ROW */}
              <div 
                className="grid grid-cols-3 text-center py-1.5 mb-1 mx-2" 
                style={{ borderTop: `1px solid ${bot.accent}26` }}
              >
                <div className="flex flex-col items-center">
                  <span className="text-[9px] text-slate-500 font-medium mb-0.5">TRADES</span>
                  <span className="text-[10px] font-bold font-mono text-slate-300">
                    {bot.wl === "0/0" ? <span className="text-slate-600">—</span> : (
                      <>
                        <span className="text-emerald-500">{bot.wl.split('/')[0]}</span>
                        <span className="text-slate-600">/</span>
                        <span className="text-rose-500">{bot.wl.split('/')[1]}</span>
                      </>
                    )}
                  </span>
                </div>
                <div className="flex flex-col items-center">
                  <span className="text-[9px] text-slate-500 font-medium mb-0.5">WIN RATE</span>
                  <div className="flex items-center gap-1 w-full justify-center">
                    <span className="text-[10px] font-bold font-mono text-slate-300">
                      {bot.wr}
                    </span>
                    {bot.wr !== "—" && (
                      <div className="w-8 h-1 bg-slate-800 rounded-full overflow-hidden">
                        <div 
                          className="h-full rounded-full" 
                          style={{ 
                            width: bot.wr, 
                            backgroundColor: bot.accent 
                          }}
                        />
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-center">
                  <span className="text-[9px] text-slate-500 font-medium mb-0.5">OPEN</span>
                  <span className={`text-[10px] font-bold font-mono ${bot.open > 0 ? "text-white" : "text-slate-600"}`}>
                    {bot.open > 0 ? bot.open : "—"}
                  </span>
                </div>
              </div>

              {/* POSITIONS OR BANNER - Fixed bottom height area */}
              <div className="h-7 w-full mt-auto">
                {bot.status === "PAUSED" ? (
                  <div className="w-full h-full bg-amber-500/10 border-t border-amber-500/20 flex items-center justify-center gap-1.5 text-[10px] font-bold text-amber-500">
                    <AlertTriangle size={12} />
                    Paused — exit logic review
                  </div>
                ) : bot.positions.length > 0 ? (
                  <div className="w-full h-full px-2 flex flex-wrap gap-1 items-center overflow-hidden pb-1">
                    {bot.positions.map(p => (
                      <div 
                        key={p} 
                        className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold"
                        style={{ backgroundColor: `${bot.accent}2E`, color: bot.accent }}
                      >
                        {p}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { CommandGrid };
