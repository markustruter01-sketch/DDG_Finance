import React from "react";

const bots = [
  { rank: 1, name: "Jerome", status: "LIVE", pnl: 2448, pnlStr: "+$2,448", wr: "—", open: 2, exchange: "Alpaca · Macro", emoji: "🦅", color: "#f97316" },
  { rank: 2, name: "Kraken Trend", status: "LIVE", pnl: 128, pnlStr: "+$128", wr: "26%", open: 0, exchange: "Kraken · Crypto", emoji: "🐙", color: "#0ea5e9" },
  { rank: 3, name: "Poseidon", status: "LIVE", pnl: 15, pnlStr: "+$15", wr: "42%", open: 0, exchange: "Kraken · Crypto", emoji: "🔱", color: "#8b5cf6" },
  { rank: 4, name: "Oracle", status: "LIVE", pnl: 0, pnlStr: "+$0", wr: "42.6%", open: 5, exchange: "Alpaca · Stocks", emoji: "👁️", color: "#22d3ee" },
  { rank: 5, name: "SPY/QQQ Trend", status: "LIVE", pnl: 0, pnlStr: "+$0", wr: "—", open: 0, exchange: "Alpaca · ETFs", emoji: "📈", color: "#3b82f6" },
  { rank: 6, name: "Sector Rotation", status: "LIVE", pnl: 0, pnlStr: "+$0", wr: "—", open: 0, exchange: "Alpaca · Sectors", emoji: "🔄", color: "#a855f7" },
  { rank: 7, name: "Defensive Guard", status: "LIVE", pnl: 0, pnlStr: "+$0", wr: "—", open: 0, exchange: "Alpaca · Defensive", emoji: "🛡️", color: "#10b981" },
  { rank: 8, name: "Macro Bond", status: "LIVE", pnl: 0, pnlStr: "+$0", wr: "—", open: 0, exchange: "Alpaca · Bonds", emoji: "📜", color: "#eab308" },
  { rank: 9, name: "Forex Gump", status: "PAUSED", pnl: -201, pnlStr: "-$201", wr: "25%", open: 5, exchange: "Oanda · Forex", emoji: "💱", color: "#06b6d4" },
];

export function Leaderboard() {
  const maxPnl = 2448;

  return (
    <div className="flex flex-col h-[100dvh] w-full bg-[#020617] text-white font-sans overflow-hidden">
      {/* HEADER */}
      <div className="flex items-center justify-between p-6 border-b border-white/10 shrink-0">
        <div>
          <h1 className="text-2xl font-black tracking-tight flex items-center gap-2">
            🏁 BOT FLEET LEADERBOARD
          </h1>
          <p className="text-sm text-slate-400 mt-1 uppercase tracking-widest font-medium">Ranked by all-time P&L</p>
        </div>
        <div className="text-right">
          <div className="text-3xl font-black text-emerald-400 tracking-tight">+$2,374</div>
          <div className="text-sm text-slate-400 font-medium">Total Fleet P&L • $902,374 Equity</div>
        </div>
      </div>

      {/* LEADERBOARD LIST */}
      <div className="flex-1 flex flex-col p-6 gap-3 overflow-hidden">
        {bots.map((bot, idx) => {
          if (bot.status === "PAUSED") {
            return (
              <React.Fragment key={bot.name}>
                <div className="flex items-center gap-4 my-2 opacity-50 shrink-0">
                  <div className="h-[1px] flex-1 bg-white/20"></div>
                  <div className="text-xs tracking-widest uppercase font-bold text-slate-400">PAUSED BOTS</div>
                  <div className="h-[1px] flex-1 bg-white/20"></div>
                </div>
                <BotRow bot={bot} maxPnl={maxPnl} />
              </React.Fragment>
            );
          }
          return <BotRow key={bot.name} bot={bot} maxPnl={maxPnl} />;
        })}
      </div>

      {/* FOOTER */}
      <div className="p-4 border-t border-white/10 bg-black/20 shrink-0 flex items-center justify-between text-xs text-slate-400 uppercase tracking-widest font-semibold">
        <div className="flex gap-4">
          <span className="text-slate-300">Equity: $902,374</span>
          <span className="text-emerald-400">P&L: +$2,374</span>
          <span className="text-slate-300">Win Rate: 36.6%</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> 8 LIVE</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-500"></span> 1 PAUSED</span>
          <span className="text-slate-500">|</span>
          <span>7 OPEN POSITIONS</span>
        </div>
      </div>
    </div>
  );
}

function BotRow({ bot, maxPnl }: { bot: any; maxPnl: number }) {
  const isFirst = bot.rank === 1;
  const isNegative = bot.pnl < 0;
  
  // Calculate bar width (up to 80% of container)
  const widthPercent = bot.pnl === 0 ? 0 : Math.min((Math.abs(bot.pnl) / maxPnl) * 80, 80);

  return (
    <div 
      className={`
        flex items-center gap-4 flex-1 min-h-0 rounded-lg border px-4 transition-all
        ${isFirst ? 'bg-amber-500/5 border-amber-500/20' : 'bg-white/5 border-white/5'}
        ${bot.status === 'PAUSED' ? 'opacity-60 grayscale-[0.5]' : ''}
      `}
    >
      {/* LEFT: Rank & Identity */}
      <div className="flex items-center gap-4 w-64 shrink-0">
        <div className={`text-2xl font-black w-8 text-center ${isFirst ? 'text-amber-400' : 'text-slate-500'}`}>
          {isFirst ? '👑' : `#${bot.rank}`}
        </div>
        <div className="flex items-center gap-3">
          <div className="text-2xl bg-black/20 w-10 h-10 rounded-full flex items-center justify-center border border-white/10">
            {bot.emoji}
          </div>
          <div className="flex flex-col">
            <div className={`font-bold truncate ${isFirst ? 'text-amber-400' : 'text-slate-200'}`}>
              {bot.name}
            </div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
              {bot.exchange}
            </div>
          </div>
        </div>
      </div>

      {/* MIDDLE: Proportional Bar */}
      <div className="flex-1 flex items-center relative h-full py-2">
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-[2px] bg-white/5 rounded-full" />
        
        {bot.pnl !== 0 && (
          <div className="relative w-full h-8 flex items-center">
            {/* The bar */}
            <div 
              className={`h-6 rounded-sm transition-all duration-1000 ${isNegative ? 'absolute right-full mr-[2px] origin-right bg-rose-500/80' : ''}`}
              style={{
                width: `${widthPercent}%`,
                background: !isNegative ? `linear-gradient(90deg, ${bot.color}ff, ${bot.color}40)` : undefined,
                boxShadow: isFirst ? `0 0 20px ${bot.color}40` : 'none'
              }}
            />
          </div>
        )}
      </div>

      {/* RIGHT: Stats */}
      <div className="flex items-center justify-end gap-6 w-80 shrink-0">
        <div className="flex gap-2">
          {bot.wr !== "—" && (
            <div className="px-2.5 py-1 rounded bg-black/30 border border-white/5 text-xs font-mono text-slate-300">
              WR <span className="text-white">{bot.wr}</span>
            </div>
          )}
          {bot.open > 0 && (
            <div className="px-2.5 py-1 rounded bg-black/30 border border-white/5 text-xs font-mono text-slate-300">
              OPN <span className="text-white">{bot.open}</span>
            </div>
          )}
        </div>
        
        <div className={`text-xl font-mono font-black w-24 text-right
          ${bot.pnl > 0 ? 'text-emerald-400' : bot.pnl < 0 ? 'text-rose-400' : 'text-slate-500'}
        `}>
          {bot.pnlStr}
        </div>

        <div className={`
          px-2.5 py-1 text-[10px] font-black uppercase tracking-widest rounded-sm w-16 text-center
          ${bot.status === 'LIVE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'}
        `}>
          {bot.status}
        </div>
      </div>
    </div>
  );
}

export default Leaderboard;