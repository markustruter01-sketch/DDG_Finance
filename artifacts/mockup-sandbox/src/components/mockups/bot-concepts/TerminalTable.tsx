import React from "react";

const bots = [
  { name: "Oracle", status: "LIVE", equity: "$100,000", pnl: "+$0", pnlPct: "+0.0%", wl: "132/178", wr: "42.6%", open: 5, tags: ["CSX", "ELV", "MET", "MRVL", "MS"], color: "#22d3ee" },
  { name: "SPY/QQQ Trend", status: "LIVE", equity: "$100,000", pnl: "+$0", pnlPct: "—", wl: "0/0", wr: "—", open: 0, tags: [], color: "#3b82f6" },
  { name: "Jerome", status: "LIVE", equity: "$102,448", pnl: "+$2,448", pnlPct: "+2.4%", wl: "0/0", wr: "—", open: 2, tags: ["ENS", "WLD"], color: "#f97316" },
  { name: "Sector Rotation", status: "LIVE", equity: "$100,000", pnl: "+$0", pnlPct: "—", wl: "0/0", wr: "—", open: 0, tags: [], color: "#a855f7" },
  { name: "Defensive Guard", status: "LIVE", equity: "$100,000", pnl: "+$0", pnlPct: "—", wl: "0/0", wr: "—", open: 0, tags: [], color: "#10b981" },
  { name: "Macro Bond", status: "LIVE", equity: "$100,000", pnl: "+$0", pnlPct: "—", wl: "0/0", wr: "—", open: 0, tags: [], color: "#eab308" },
  { name: "Forex Gump", status: "PAUSED", equity: "$99,799", pnl: "-$201", pnlPct: "-0.2%", wl: "4/12", wr: "25%", open: 5, tags: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD"], color: "#06b6d4" },
  { name: "Poseidon", status: "LIVE", equity: "$100,015", pnl: "+$15", pnlPct: "+0.0%", wl: "8/11", wr: "42%", open: 0, tags: [], color: "#8b5cf6" },
  { name: "Kraken Trend", status: "LIVE", equity: "$100,128", pnl: "+$128", pnlPct: "+0.1%", wl: "9/25", wr: "26%", open: 0, tags: [], color: "#0ea5e9" },
];

export default function TerminalTable() {
  return (
    <div className="w-full h-full min-h-screen font-mono text-sm" style={{ backgroundColor: "#030712", color: "#e2e8f0" }}>
      <div className="max-w-7xl mx-auto p-4 flex flex-col gap-2">
        
        {/* HEADER */}
        <div className="flex justify-between items-end pb-2 border-b" style={{ borderColor: "rgba(52, 211, 153, 0.3)" }}>
          <div className="text-lg font-bold" style={{ color: "#34d399" }}>▶ BOT FLEET TERMINAL</div>
          <div className="flex gap-4 text-xs">
            <div><span style={{ color: "#475569" }}>EQUITY:</span> $902,374</div>
            <div><span style={{ color: "#475569" }}>P&L:</span> <span style={{ color: "#34d399" }}>+$2,374</span></div>
            <div><span style={{ color: "#475569" }}>WR:</span> 36.6%</div>
          </div>
        </div>

        {/* TABLE CONTENT */}
        <div className="w-full">
          {/* COL HEADERS */}
          <div className="flex py-2 px-3 text-xs font-semibold uppercase tracking-wider border-b" style={{ borderColor: "rgba(52, 211, 153, 0.2)", color: "#475569" }}>
            <div className="w-[18%]">BOT</div>
            <div className="w-[10%]">STATUS</div>
            <div className="w-[12%] text-right">EQUITY</div>
            <div className="w-[10%] text-right">P&L</div>
            <div className="w-[8%] text-right">PNL%</div>
            <div className="w-[10%] text-right">W/L</div>
            <div className="w-[10%] text-right">WIN RATE</div>
            <div className="w-[7%] text-right">OPEN</div>
            <div className="w-[15%] pl-4">POSITIONS</div>
          </div>

          {/* ROWS */}
          <div className="flex flex-col border-b" style={{ borderColor: "rgba(52, 211, 153, 0.1)" }}>
            {bots.map((bot, i) => {
              const isEven = i % 2 === 0;
              const isPaused = bot.status === "PAUSED";
              const isZero = bot.pnl === "+$0";
              const isLoss = bot.pnl.startsWith("-");
              
              const pnlColor = isLoss ? "#f87171" : isZero ? "#475569" : "#34d399";
              
              const rowStyle: React.CSSProperties = {
                backgroundColor: isPaused ? "rgba(251, 191, 36, 0.03)" : isEven ? "rgba(255, 255, 255, 0.015)" : "transparent",
                borderLeft: isPaused ? "2px solid #fbbf24" : "2px solid transparent",
              };

              return (
                <div 
                  key={bot.name}
                  className="flex items-center py-2 px-3 group transition-colors cursor-default hover:bg-white/5"
                  style={rowStyle}
                  onMouseEnter={(e) => {
                    if (!isPaused) e.currentTarget.style.borderLeft = "2px solid #34d399";
                  }}
                  onMouseLeave={(e) => {
                    if (!isPaused) e.currentTarget.style.borderLeft = "2px solid transparent";
                  }}
                >
                  <div className="w-[18%] flex items-center gap-2 font-bold truncate">
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: bot.color }} />
                    <span style={{ color: bot.color }}>{bot.name}</span>
                  </div>
                  
                  <div className="w-[10%]">
                    <span 
                      className="text-[10px] px-1.5 py-0.5 rounded border font-bold"
                      style={{ 
                        color: isPaused ? "#fbbf24" : "#34d399",
                        borderColor: isPaused ? "rgba(251, 191, 36, 0.3)" : "rgba(52, 211, 153, 0.3)",
                        backgroundColor: isPaused ? "rgba(251, 191, 36, 0.1)" : "rgba(52, 211, 153, 0.1)"
                      }}
                    >
                      {isPaused ? "⚠ PAUSED" : "● LIVE"}
                    </span>
                  </div>
                  
                  <div className="w-[12%] text-right tabular-nums">{bot.equity}</div>
                  
                  <div className="w-[10%] text-right tabular-nums font-semibold" style={{ color: pnlColor }}>
                    {bot.pnl}
                  </div>
                  
                  <div className="w-[8%] text-right tabular-nums text-xs" style={{ color: pnlColor }}>
                    {bot.pnlPct}
                  </div>
                  
                  <div className="w-[10%] text-right tabular-nums text-xs">
                    {bot.wl === "0/0" ? (
                      <span style={{ color: "#475569" }}>—</span>
                    ) : (
                      <>
                        <span style={{ color: "#34d399" }}>{bot.wl.split('/')[0]}</span>
                        <span style={{ color: "#475569" }}>/</span>
                        <span style={{ color: "#f87171" }}>{Number(bot.wl.split('/')[1]) - Number(bot.wl.split('/')[0])}</span>
                      </>
                    )}
                  </div>
                  
                  <div className="w-[10%] text-right tabular-nums">
                    {bot.wr === "—" ? <span style={{ color: "#475569" }}>—</span> : bot.wr}
                  </div>
                  
                  <div className="w-[7%] text-right tabular-nums">
                    {bot.open > 0 ? (
                      <span style={{ color: "#34d399" }}>{bot.open}</span>
                    ) : (
                      <span style={{ color: "#475569" }}>—</span>
                    )}
                  </div>
                  
                  <div className="w-[15%] pl-4 flex flex-wrap gap-1">
                    {bot.tags.length > 0 ? (
                      bot.tags.map(tag => (
                        <span key={tag} className="text-[9px] px-1 bg-white/5 border border-white/10 rounded text-slate-300">
                          {tag}
                        </span>
                      ))
                    ) : (
                      <span style={{ color: "#475569" }}>—</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* FOOTER */}
        <div className="flex justify-between items-center pt-2 text-xs font-mono" style={{ color: "#475569" }}>
          <div>8 LIVE / 1 PAUSED · 7 OPEN POSITIONS</div>
          <div>REFRESHED 3s AGO · <span style={{ color: "#34d399" }}>● ALL SYSTEMS LIVE</span></div>
        </div>

      </div>
    </div>
  );
}

export { TerminalTable };
