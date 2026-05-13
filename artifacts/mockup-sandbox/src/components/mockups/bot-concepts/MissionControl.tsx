import React, { useState } from 'react';

const FLEET_DATA = [
  { name: 'Oracle', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlVal: 0, wl: '132/178', wr: '42.6%', open: 5, exchange: 'Alpaca · Stocks', color: '#22d3ee', emoji: '🔮', isPaused: false },
  { name: 'SPY/QQQ Trend', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlVal: 0, wl: '0/0', wr: '—', open: 0, exchange: 'Alpaca · ETFs', color: '#3b82f6', emoji: '📈', isPaused: false },
  { name: 'Sector Rotation', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlVal: 0, wl: '0/0', wr: '—', open: 0, exchange: 'Alpaca · Sectors', color: '#a855f7', emoji: '🔄', isPaused: false },
  { name: 'Defensive Guard', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlVal: 0, wl: '0/0', wr: '—', open: 0, exchange: 'Alpaca · Defensive', color: '#10b981', emoji: '🛡️', isPaused: false },
  { name: 'Macro Bond', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlVal: 0, wl: '0/0', wr: '—', open: 0, exchange: 'Alpaca · Bonds', color: '#eab308', emoji: '🏛️', isPaused: false },
  { name: 'Forex Gump', status: 'PAUSED', equity: '$99,799', pnl: '-$201', pnlVal: -201, wl: '4/12', wr: '25%', open: 5, exchange: 'Oanda · Forex', color: '#06b6d4', emoji: '🏃', isPaused: true },
  { name: 'Poseidon', status: 'LIVE', equity: '$100,015', pnl: '+$15', pnlVal: 15, wl: '8/11', wr: '42%', open: 0, exchange: 'Kraken · Crypto', color: '#8b5cf6', emoji: '🔱', isPaused: false },
  { name: 'Kraken Trend', status: 'LIVE', equity: '$100,128', pnl: '+$128', pnlVal: 128, wl: '9/25', wr: '26%', open: 0, exchange: 'Kraken · Crypto', color: '#0ea5e9', emoji: '🦑', isPaused: false }
];

function MiniCard({ bot }: { bot: typeof FLEET_DATA[0] }) {
  const [isHovered, setIsHovered] = useState(false);
  
  return (
    <div 
      className="p-4 rounded-xl transition-all duration-300 relative flex flex-col justify-between"
      style={{
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        border: `1px solid ${isHovered ? bot.color : bot.isPaused ? '#d97706' : 'rgba(255,255,255,0.05)'}`,
        boxShadow: isHovered ? `0 0 15px ${bot.color}40` : bot.isPaused ? '0 0 10px rgba(217,119,6,0.2)' : 'none',
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{bot.emoji}</span>
          <div>
            <div className="text-white font-bold text-sm">{bot.name}</div>
            <div className="text-slate-400 text-xs tracking-wider uppercase">{bot.exchange}</div>
          </div>
        </div>
        <div 
          className="text-[10px] font-bold px-2 py-0.5 rounded-sm tracking-wider"
          style={{
            backgroundColor: bot.isPaused ? '#d9770620' : '#10b98120',
            color: bot.isPaused ? '#fbbf24' : '#34d399',
            border: `1px solid ${bot.isPaused ? '#d9770640' : '#10b98140'}`
          }}
        >
          {bot.status}
        </div>
      </div>
      
      <div className="mt-4 flex items-end justify-between">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Equity</div>
          <div className="text-xl font-black font-mono text-white">{bot.equity}</div>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">P&L</div>
          <div className="text-lg font-bold font-mono" style={{ color: bot.pnlVal > 0 ? '#4ade80' : bot.pnlVal < 0 ? '#f87171' : '#94a3b8' }}>
            {bot.pnl}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MissionControl() {
  return (
    <div className="h-screen w-full bg-[#020617] flex flex-row overflow-hidden font-sans select-none">
      
      {/* LEFT PANEL */}
      <div className="w-[42%] relative flex flex-col justify-between" style={{ borderRight: '1px solid rgba(249, 115, 22, 0.2)', boxShadow: '1px 0 30px rgba(249, 115, 22, 0.1)' }}>
        
        {/* Decorative Top */}
        <div className="p-8 text-center w-full">
          <div className="inline-flex items-center gap-2 text-[#fbbf24] text-xs font-bold uppercase tracking-[0.2em]">
            <span>★</span>
            <span>Top Performer</span>
            <span>★</span>
          </div>
        </div>

        {/* Center Content */}
        <div className="flex-1 flex flex-col items-center justify-center relative p-8">
          {/* Glow Orb */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] rounded-full pointer-events-none" 
               style={{ background: 'radial-gradient(circle, rgba(249,115,22,0.15) 0%, rgba(2,6,23,0) 70%)', filter: 'blur(40px)' }} />
               
          {/* Avatar Area */}
          <div className="relative mb-8">
            <div className="absolute inset-0 rounded-full animate-[ping_3s_cubic-bezier(0,0,0.2,1)_infinite]" style={{ border: '2px solid rgba(249,115,22,0.4)' }}></div>
            <div className="w-40 h-40 flex items-center justify-center rounded-full bg-black/40 border border-[#f97316]/30 shadow-[0_0_30px_rgba(249,115,22,0.2)] backdrop-blur-sm relative z-10">
              <span className="text-[6rem]">🏦</span>
            </div>
          </div>

          <div className="text-center relative z-10">
            <h1 className="text-5xl font-black text-white uppercase tracking-[0.15em] mb-2 drop-shadow-lg">Jerome</h1>
            <h2 className="text-[#f97316] text-sm font-bold uppercase tracking-[0.3em] opacity-90">Alpaca · Macro</h2>
          </div>

          <div className="w-16 h-1 bg-[#f97316] my-8 rounded-full shadow-[0_0_10px_rgba(249,115,22,0.5)]"></div>

          <div className="flex flex-col items-center gap-1 mb-8 relative z-10">
            <div className="text-4xl font-black font-mono text-white tracking-tight">$102,448</div>
            <div className="text-6xl font-black text-[#4ade80] tracking-tighter" style={{ filter: 'drop-shadow(0 0 20px rgba(74,222,128,0.4))' }}>
              +$2,448 <span className="text-3xl opacity-80">· +2.4%</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-12 gap-y-6 text-center mt-4 w-full max-w-md bg-black/20 p-6 rounded-2xl border border-white/5 relative z-10">
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Open Positions</div>
              <div className="text-xl font-bold text-white">2</div>
            </div>
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Positions</div>
              <div className="flex justify-center gap-2 mt-1">
                <span className="bg-blue-500/20 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded text-xs font-bold">ENS</span>
                <span className="bg-blue-500/20 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded text-xs font-bold">WLD</span>
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Win Rate</div>
              <div className="text-xl font-bold text-slate-400">—</div>
            </div>
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Status</div>
              <div className="mt-1 flex justify-center">
                <span className="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-3 py-1 rounded text-xs font-bold tracking-widest">
                  LIVE
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Decorative Bottom */}
        <div className="p-6 text-center border-t border-white/5 bg-white/[0.01]">
          <div className="text-xs text-slate-500 font-bold uppercase tracking-[0.2em]">
            👑 Best Performer · Bot Fleet Commander
          </div>
        </div>
      </div>

      {/* RIGHT PANEL */}
      <div className="flex-1 flex flex-col p-8">
        <div className="flex items-end justify-between mb-8 pb-6 border-b border-white/10">
          <div>
            <h2 className="text-3xl font-black text-white tracking-wider mb-2">FLEET OVERVIEW</h2>
            <div className="flex items-center gap-3 text-sm font-bold uppercase tracking-widest">
              <span className="text-slate-400">Total Equity:</span>
              <span className="text-white font-mono text-lg">$902,374</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-400 uppercase tracking-widest mb-1 font-bold">Fleet P&L</div>
            <div className="text-2xl font-black font-mono text-[#4ade80]" style={{ filter: 'drop-shadow(0 0 10px rgba(74,222,128,0.3))' }}>
              +$2,374 <span className="text-lg opacity-80">· 36.6% WR</span>
            </div>
          </div>
        </div>

        <div className="flex-1 grid grid-cols-2 gap-4 auto-rows-max overflow-y-auto pr-2 custom-scrollbar">
          {FLEET_DATA.map((bot, i) => (
            <MiniCard key={i} bot={bot} />
          ))}
        </div>

        <div className="mt-6 pt-6 border-t border-white/5 flex items-center justify-between text-xs font-bold uppercase tracking-widest text-slate-500">
          <div className="flex gap-6">
            <span className="text-white">8 Bots Live</span>
            <span className="text-[#fbbf24]">1 Paused</span>
            <span>7 Open Positions</span>
          </div>
          <div className="flex items-center gap-2 text-[#4ade80]">
            <div className="w-2 h-2 rounded-full bg-[#4ade80] animate-pulse"></div>
            All Systems Monitored
          </div>
        </div>
      </div>

      <style dangerouslySetInnerHTML={{__html: `
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: rgba(255,255,255,0.1);
          border-radius: 10px;
        }
      `}} />
    </div>
  );
}

export { MissionControl };
