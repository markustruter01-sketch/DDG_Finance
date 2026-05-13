import React, { useState } from 'react';

interface BotStats {
  name: string;
  emoji: string;
  status: string;
  equity: string;
  pnl: string;
  pnlValue: number;
  winLoss: string;
  winRate: string;
  open: number;
  exchange: string;
  color: string;
  accent: string;
}

const bots: BotStats[] = [
  // Row 1
  { name: 'Oracle', emoji: '🔮', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlValue: 0, winLoss: '132/178', winRate: '42.6%', open: 5, exchange: 'Alpaca · Stocks [CSX, ELV, MET, MRVL, MS]', color: 'rgba(51, 65, 85, 0.7)', accent: '#22d3ee' },
  { name: 'SPY/QQQ Trend', emoji: '📈', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlValue: 0, winLoss: '0/0', winRate: '—', open: 0, exchange: 'Alpaca · ETFs', color: 'rgba(51, 65, 85, 0.7)', accent: '#3b82f6' },
  { name: 'Jerome', emoji: '🦅', status: 'LIVE', equity: '$102,448', pnl: '+$2,448', pnlValue: 2448, winLoss: '0/0', winRate: '—', open: 2, exchange: 'Alpaca · Macro [ENS, WLD]', color: 'rgba(16, 185, 129, 0.85)', accent: '#f97316' },
  // Row 2
  { name: 'Sector Rotation', emoji: '🔄', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlValue: 0, winLoss: '0/0', winRate: '—', open: 0, exchange: 'Alpaca · Sectors', color: 'rgba(51, 65, 85, 0.7)', accent: '#a855f7' },
  { name: 'Defensive Guard', emoji: '🛡️', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlValue: 0, winLoss: '0/0', winRate: '—', open: 0, exchange: 'Alpaca · Defensive', color: 'rgba(51, 65, 85, 0.7)', accent: '#10b981' },
  { name: 'Macro Bond', emoji: '📜', status: 'LIVE', equity: '$100,000', pnl: '+$0', pnlValue: 0, winLoss: '0/0', winRate: '—', open: 0, exchange: 'Alpaca · Bonds', color: 'rgba(51, 65, 85, 0.7)', accent: '#eab308' },
  // Row 3
  { name: 'Forex Gump', emoji: '🏃', status: 'PAUSED', equity: '$99,799', pnl: '-$201', pnlValue: -201, winLoss: '4/12', winRate: '25%', open: 5, exchange: 'Oanda · Forex [EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD]', color: 'rgba(239, 68, 68, 0.6)', accent: '#06b6d4' },
  { name: 'Poseidon', emoji: '🔱', status: 'LIVE', equity: '$100,015', pnl: '+$15', pnlValue: 15, winLoss: '8/11', winRate: '42%', open: 0, exchange: 'Kraken · Crypto', color: 'rgba(16, 185, 129, 0.2)', accent: '#8b5cf6' },
  { name: 'Kraken Trend', emoji: '🐙', status: 'LIVE', equity: '$100,128', pnl: '+$128', pnlValue: 128, winLoss: '9/25', winRate: '26%', open: 0, exchange: 'Kraken · Crypto', color: 'rgba(16, 185, 129, 0.45)', accent: '#0ea5e9' }
];

export default function HexHeatMap() {
  const [hoveredBot, setHoveredBot] = useState<BotStats | null>(null);

  const renderHex = (bot: BotStats, index: number) => {
    const isPaused = bot.status === 'PAUSED';
    return (
      <div 
        key={bot.name}
        className="absolute group transition-transform duration-300 hover:scale-110 hover:z-50 cursor-pointer"
        style={{
          width: '160px',
          height: '185px',
        }}
        onMouseEnter={() => setHoveredBot(bot)}
        onMouseLeave={() => setHoveredBot(null)}
      >
        <div 
          className="absolute inset-0 transition-all duration-300"
          style={{
            clipPath: 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)',
            background: bot.color,
            border: isPaused ? 'none' : 'none', 
          }}
        />
        {/* Fake border using a slightly smaller inner hexagon */}
        <div 
          className="absolute transition-all duration-300 pointer-events-none"
          style={{
            top: '1px', left: '1px', right: '1px', bottom: '1px',
            clipPath: 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)',
            background: isPaused ? 'transparent' : 'transparent',
            boxShadow: `inset 0 0 0 1px ${isPaused ? '#fbbf24' : 'rgba(255,255,255,0.1)'}`,
          }}
        />
        {/* Glow border on hover */}
        <div 
          className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
          style={{
            clipPath: 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)',
            boxShadow: `inset 0 0 20px ${bot.accent}`,
          }}
        />
        
        {isPaused && (
          <div className="absolute top-6 right-8 text-amber-400 text-xs z-10 font-bold bg-slate-900/80 w-5 h-5 rounded-full flex items-center justify-center border border-amber-400/50" title="Paused">
            !
          </div>
        )}
        
        <div className="absolute inset-0 flex flex-col items-center justify-center p-4 text-center z-10 pointer-events-none">
          <span className="text-3xl mb-1 drop-shadow-md">{bot.emoji}</span>
          <span className="text-[10px] font-bold uppercase text-white/90 leading-tight mb-1">{bot.name}</span>
          <span className="text-[12px] font-black text-white">{bot.pnl}</span>
          <span className="text-[9px] text-white/60 mt-1">{bot.winRate !== '—' ? `WR: ${bot.winRate}` : 'NO TRADES'}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-[#020617] text-slate-50 flex flex-col font-sans overflow-hidden">
      <header className="p-6 md:p-8 flex-shrink-0 z-20">
        <h1 className="text-2xl md:text-3xl font-black tracking-tight text-white flex items-center gap-2">
          <span className="text-emerald-400">⬡</span> FLEET HEAT MAP
        </h1>
        <p className="text-slate-400 text-sm mt-1 mb-4">Colour intensity = performance heat</p>
      </header>

      <main className="flex-grow flex flex-col items-center justify-center relative z-10 py-4">
        {/* Honeycomb Grid - Using relative container with absolute positioning for precise layout */}
        <div className="relative" style={{ width: '480px', height: '500px' }}>
          {/* Row 1: y=0 */}
          <div className="absolute" style={{ top: '0px', left: '0px' }}>{renderHex(bots[0], 0)}</div>
          <div className="absolute" style={{ top: '0px', left: '160px' }}>{renderHex(bots[1], 1)}</div>
          <div className="absolute" style={{ top: '0px', left: '320px' }}>{renderHex(bots[2], 2)}</div>
          
          {/* Row 2: offset half hex width (80px), y = 185 * 0.75 = 138.75px */}
          <div className="absolute" style={{ top: '140px', left: '80px' }}>{renderHex(bots[3], 3)}</div>
          <div className="absolute" style={{ top: '140px', left: '240px' }}>{renderHex(bots[4], 4)}</div>
          <div className="absolute" style={{ top: '140px', left: '400px' }}>{renderHex(bots[5], 5)}</div>
          
          {/* Row 3: no offset, y = 185 * 1.5 = 277.5px */}
          <div className="absolute" style={{ top: '280px', left: '0px' }}>{renderHex(bots[6], 6)}</div>
          <div className="absolute" style={{ top: '280px', left: '160px' }}>{renderHex(bots[7], 7)}</div>
          <div className="absolute" style={{ top: '280px', left: '320px' }}>{renderHex(bots[8], 8)}</div>
        </div>

        {/* Hover Tooltip Overlay */}
        <div 
          className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none transition-all duration-300 z-[100] ${hoveredBot ? 'opacity-100 scale-100' : 'opacity-0 scale-95'}`}
        >
          {hoveredBot && (
            <div className="bg-slate-900/95 backdrop-blur-md border border-slate-700 p-5 rounded-xl shadow-2xl shadow-black w-80">
              <div className="flex justify-between items-start mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-2xl">{hoveredBot.emoji}</span>
                  <div>
                    <h3 className="font-bold text-white leading-tight">{hoveredBot.name}</h3>
                    <span className={`inline-block px-2 py-0.5 rounded text-[9px] uppercase font-bold ${hoveredBot.status === 'LIVE' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}`}>
                      {hoveredBot.status}
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`font-black ${hoveredBot.pnlValue > 0 ? 'text-emerald-400' : hoveredBot.pnlValue < 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                    {hoveredBot.pnl}
                  </div>
                  <div className="text-[10px] text-slate-400">{hoveredBot.equity} EQ</div>
                </div>
              </div>
              
              <div className="grid grid-cols-2 gap-3 mb-3 text-xs bg-slate-950/50 p-3 rounded-lg">
                <div>
                  <span className="block text-slate-500 mb-1">Win/Loss</span>
                  <span className="font-mono">{hoveredBot.winLoss}</span>
                </div>
                <div>
                  <span className="block text-slate-500 mb-1">Win Rate</span>
                  <span className="font-mono">{hoveredBot.winRate}</span>
                </div>
                <div>
                  <span className="block text-slate-500 mb-1">Open Pos</span>
                  <span className="font-mono">{hoveredBot.open}</span>
                </div>
                <div>
                  <span className="block text-slate-500 mb-1">Status</span>
                  <span className="font-mono flex items-center gap-1">
                    <span className={`w-1.5 h-1.5 rounded-full ${hoveredBot.status === 'LIVE' ? 'bg-emerald-400' : 'bg-amber-400'}`}></span>
                    {hoveredBot.status}
                  </span>
                </div>
              </div>
              
              <div>
                <span className="block text-[10px] uppercase text-slate-500 mb-1 font-bold">Exchange / Universe</span>
                <div className="text-xs text-slate-300 break-words">{hoveredBot.exchange}</div>
              </div>
            </div>
          )}
        </div>
      </main>

      <footer className="p-6 border-t border-slate-800/50 bg-slate-950/30 flex-shrink-0 z-20 flex flex-col items-center gap-6">
        <div className="flex flex-wrap gap-6 text-sm justify-center w-full max-w-4xl">
          <div className="flex items-center gap-2 bg-slate-900 px-3 py-1.5 rounded-full border border-slate-800">
            <span className="text-slate-500 text-xs font-bold uppercase">Equity</span>
            <span className="font-mono font-bold">$902,374</span>
          </div>
          <div className="flex items-center gap-2 bg-slate-900 px-3 py-1.5 rounded-full border border-slate-800">
            <span className="text-slate-500 text-xs font-bold uppercase">P&L</span>
            <span className="font-mono font-bold text-emerald-400">+$2,374</span>
          </div>
          <div className="flex items-center gap-2 bg-slate-900 px-3 py-1.5 rounded-full border border-slate-800">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></div>
            <span className="text-slate-300">8 LIVE / 1 PAUSED</span>
          </div>
          <div className="flex items-center gap-2 bg-slate-900 px-3 py-1.5 rounded-full border border-slate-800">
            <span className="text-slate-300">7 OPEN POSITIONS</span>
          </div>
        </div>
        
        {/* Heat Legend */}
        <div className="flex items-center gap-4 text-[10px] font-bold uppercase tracking-wider text-slate-400">
          <span>Losing</span>
          <div className="flex w-64 h-2 rounded-full overflow-hidden">
            <div className="h-full bg-rose-500/60 flex-1"></div>
            <div className="h-full bg-slate-700/70 flex-1 border-l border-r border-slate-900"></div>
            <div className="h-full bg-emerald-500/20 flex-1"></div>
            <div className="h-full bg-emerald-500/45 flex-1 border-l border-slate-900"></div>
            <div className="h-full bg-emerald-500/85 flex-1 border-l border-slate-900"></div>
          </div>
          <span>Profitable</span>
        </div>
      </footer>
    </div>
  );
}

export { HexHeatMap };
