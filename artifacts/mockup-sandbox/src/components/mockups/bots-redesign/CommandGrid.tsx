import React from "react";
import { Activity, Clock, ShieldAlert, BarChart3, TrendingUp, AlertTriangle } from "lucide-react";
import "./_group.css";

type Trade = { symbol: string; pnl: number; isWin: boolean };

type Bot = {
  id: string;
  name: string;
  icon: string;
  platform: string;
  assetClass: string;
  equity: number;
  pnl: number;
  pnlPercent: number;
  status: "LIVE" | "STALE" | "STOPPED";
  openTrades: string[];
  strategy: string;
  accentColor: string;
  conditions: string[];
  recentTrades: Trade[];
  winRate: number;
};

const BOTS: Bot[] = [
  {
    id: "oracle",
    name: "Oracle",
    icon: "🔮",
    platform: "Alpaca",
    assetClass: "Stocks",
    equity: 90288,
    pnl: -9712,
    pnlPercent: -9.71,
    status: "STALE",
    openTrades: [],
    strategy: "Momentum stocks NYSE hours",
    accentColor: "#f43f5e", // Rose
    conditions: ["Z-Score > 2.1", "Min Profit 0.5%", "NYSE hours"],
    winRate: 42,
    recentTrades: [
      { symbol: "NVDA", pnl: -2100, isWin: false },
      { symbol: "AAPL", pnl: 890, isWin: true },
      { symbol: "META", pnl: -1450, isWin: false },
    ],
  },
  {
    id: "spy-qqq",
    name: "SPY/QQQ Trend",
    icon: "📈",
    platform: "Alpaca",
    assetClass: "ETFs",
    equity: 110081,
    pnl: 10081,
    pnlPercent: 10.08,
    status: "LIVE",
    openTrades: ["SPY"],
    strategy: "Trend-following ETF rotation",
    accentColor: "#3b82f6", // Blue
    conditions: ["Z-Entry 2.0", "Z-Exit 0.3", "Trail 1.5%"],
    winRate: 68,
    recentTrades: [
      { symbol: "SPY", pnl: 234, isWin: true },
      { symbol: "QQQ", pnl: -112, isWin: false },
      { symbol: "SPY", pnl: 445, isWin: true },
    ],
  },
  {
    id: "jerome",
    name: "Jerome",
    icon: "🏛️",
    platform: "Alpaca",
    assetClass: "Macro",
    equity: 100000,
    pnl: 0,
    pnlPercent: 0,
    status: "LIVE",
    openTrades: [],
    strategy: "LLM-driven macro commodity futures",
    accentColor: "#eab308", // Yellow
    conditions: ["9AM + 9PM UTC", "Groq/Gemini"],
    winRate: 0,
    recentTrades: [],
  },
  {
    id: "forex-gump",
    name: "Forex Gump",
    icon: "🧭",
    platform: "Oanda",
    assetClass: "Forex",
    equity: 102639,
    pnl: 2639,
    pnlPercent: 2.64,
    status: "LIVE",
    openTrades: ["EURUSD", "GBPJPY", "AUDUSD", "USDJPY", "EURGBP"],
    strategy: "G10 currency trend",
    accentColor: "#10b981", // Emerald
    conditions: ["G10 pairs", "ATR stops", "4hr cycles"],
    winRate: 55,
    recentTrades: [
      { symbol: "EURUSD", pnl: 412, isWin: true },
      { symbol: "GBPUSD", pnl: -89, isWin: false },
      { symbol: "GBPJPY", pnl: 677, isWin: true },
    ],
  },
  {
    id: "listing-pump",
    name: "Listing Pump",
    icon: "🚀",
    platform: "Kraken",
    assetClass: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPercent: 0,
    status: "LIVE",
    openTrades: [],
    strategy: "New exchange listing momentum",
    accentColor: "#a855f7", // Purple
    conditions: ["Signal thresholds vary", "24/7 crypto"],
    winRate: 0,
    recentTrades: [],
  },
  {
    id: "event-trader",
    name: "Event Trader",
    icon: "⚡",
    platform: "Kraken",
    assetClass: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPercent: 0,
    status: "LIVE",
    openTrades: [],
    strategy: "Macro event volatility trades",
    accentColor: "#f97316", // Orange
    conditions: ["Signal thresholds vary", "24/7 crypto"],
    winRate: 0,
    recentTrades: [],
  },
  {
    id: "depeg-hunter",
    name: "Depeg Hunter",
    icon: "🎯",
    platform: "Kraken",
    assetClass: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPercent: 0,
    status: "LIVE",
    openTrades: [],
    strategy: "Stablecoin depeg arbitrage",
    accentColor: "#0ea5e9", // Sky
    conditions: ["Signal thresholds vary", "24/7 crypto"],
    winRate: 0,
    recentTrades: [],
  },
  {
    id: "memecoin-velocity",
    name: "Memecoin Velocity",
    icon: "🌙",
    platform: "Kraken",
    assetClass: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPercent: 0,
    status: "LIVE",
    openTrades: [],
    strategy: "Meme token velocity breakouts",
    accentColor: "#ec4899", // Pink
    conditions: ["Signal thresholds vary", "24/7 crypto"],
    winRate: 0,
    recentTrades: [],
  },
];

function formatMoney(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatMoneyDetailed(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function CommandGrid() {
  return (
    <div className="w-full h-screen min-h-[860px] bg-[#0A0D14] text-slate-300 font-sans flex flex-col overflow-hidden relative selection:bg-indigo-500/30">
      {/* Background grid texture */}
      <div 
        className="absolute inset-0 z-0 pointer-events-none opacity-[0.03]" 
        style={{
          backgroundImage: `linear-gradient(rgba(255, 255, 255, 0.2) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 255, 255, 0.2) 1px, transparent 1px)`,
          backgroundSize: '20px 20px'
        }}
      />

      {/* Header Bar */}
      <div className="h-10 bg-[#111622] border-b border-slate-800/80 flex items-center px-4 justify-between shrink-0 z-10 shadow-sm relative">
        <div className="flex items-center gap-6 h-full">
          <div className="flex items-center gap-2 font-['Space_Grotesk'] text-slate-100 font-bold tracking-tight">
            <ShieldAlert className="w-4 h-4 text-indigo-400" />
            <span>FLEET COMMAND</span>
          </div>
          <div className="w-px h-4 bg-slate-800" />
          <div className="flex items-center gap-4 text-xs font-mono">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">CAPITAL:</span>
              <span className="text-slate-200 font-medium">$803,007</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">PNL:</span>
              <span className="text-emerald-400 font-medium">+$3,007 (+0.38%)</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono h-full">
          <div className="flex items-center gap-1.5 bg-slate-800/50 px-2 py-1 rounded">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse-live"></span>
            <span className="text-slate-300">7 LIVE</span>
          </div>
          <div className="flex items-center gap-1.5 bg-amber-900/20 text-amber-500 px-2 py-1 rounded border border-amber-900/30">
            <Clock className="w-3 h-3" />
            <span>1 STALE (NYSE CLOSED)</span>
          </div>
          <div className="w-px h-4 bg-slate-800" />
          <div className="flex items-center gap-2 text-indigo-300">
            <Activity className="w-3.5 h-3.5" />
            <span>6 OPEN POSITIONS</span>
          </div>
        </div>
      </div>

      {/* Grid Content */}
      <div className="flex-1 grid grid-cols-4 grid-rows-2 gap-[1px] bg-slate-800/50 p-[1px] z-10">
        {BOTS.map((bot) => (
          <div 
            key={bot.id} 
            className="bg-[#0D111A] flex flex-col relative overflow-hidden group"
          >
            {/* Accent styling */}
            <div 
              className="absolute left-0 top-0 bottom-0 w-[3px]"
              style={{ backgroundColor: bot.accentColor }}
            />
            <div 
              className="absolute top-0 left-0 right-0 h-[40px] opacity-10 pointer-events-none"
              style={{ background: `linear-gradient(to bottom, ${bot.accentColor}, transparent)` }}
            />

            {/* Card Header */}
            <div className="px-4 py-3 flex justify-between items-start border-b border-slate-800/50 shrink-0">
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-lg leading-none filter drop-shadow-sm">{bot.icon}</span>
                  <h3 className="font-['Space_Grotesk'] text-slate-100 font-semibold tracking-tight text-sm">
                    {bot.name}
                  </h3>
                </div>
                <div className="text-[10px] text-slate-500 font-mono uppercase tracking-wider pl-7 flex items-center gap-1">
                  <span>{bot.platform}</span>
                  <span className="opacity-40">•</span>
                  <span>{bot.assetClass}</span>
                </div>
              </div>

              {bot.status === "LIVE" ? (
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-sm bg-emerald-950/40 border border-emerald-900/50 shadow-[0_0_10px_rgba(16,185,129,0.1)]">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-live" />
                  <span className="text-[9px] font-mono font-bold text-emerald-400">LIVE</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-sm bg-amber-950/40 border border-amber-900/50">
                  <Clock className="w-2.5 h-2.5 text-amber-500" />
                  <span className="text-[9px] font-mono font-bold text-amber-500">STALE</span>
                </div>
              )}
            </div>

            {/* Primary Metrics */}
            <div className="px-4 py-3 grid grid-cols-2 gap-4 border-b border-slate-800/50 shrink-0">
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-slate-500 font-mono uppercase">Equity</span>
                <span className="font-mono text-lg text-slate-200 tracking-tight">
                  {formatMoney(bot.equity)}
                </span>
              </div>
              <div className="flex flex-col gap-1 items-end">
                <span className="text-[10px] text-slate-500 font-mono uppercase">P&L</span>
                <div className="flex items-baseline gap-1.5">
                  <span className={`font-mono text-lg tracking-tight ${bot.pnl > 0 ? 'text-emerald-400' : bot.pnl < 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                    {bot.pnl > 0 ? '+' : ''}{formatMoneyDetailed(bot.pnl)}
                  </span>
                  <span className={`text-[10px] font-mono ${bot.pnlPercent > 0 ? 'text-emerald-500' : bot.pnlPercent < 0 ? 'text-rose-500' : 'text-slate-500'}`}>
                    ({bot.pnlPercent > 0 ? '+' : ''}{bot.pnlPercent.toFixed(2)}%)
                  </span>
                </div>
              </div>
            </div>

            {/* Middle Section: Strategy & Open Positions */}
            <div className="flex-1 flex flex-col justify-center px-4 py-3 gap-3 min-h-0">
              <div className="flex justify-between items-center text-[11px] font-mono">
                <div className="text-slate-400 flex items-center gap-1.5">
                  <Activity className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Open Trades:</span>
                </div>
                {bot.openTrades.length > 0 ? (
                  <div className="flex flex-wrap justify-end gap-1 max-w-[120px]">
                    {bot.openTrades.map(sym => (
                      <span key={sym} className="px-1.5 py-[1px] bg-indigo-950/50 text-indigo-300 border border-indigo-900/50 rounded-sm whitespace-nowrap">
                        {sym}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-slate-600">None</span>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="text-[10px] text-slate-500 font-mono uppercase">Conditions</div>
                <div className="flex flex-wrap gap-1.5">
                  {bot.conditions.map((cond, i) => (
                    <span key={i} className="text-[10px] px-1.5 py-0.5 bg-[#181E29] text-slate-300 border border-slate-800 rounded whitespace-nowrap">
                      {cond}
                    </span>
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-2 mt-1">
                <div className="text-[10px] text-slate-500 font-mono w-14 shrink-0">Win Rate</div>
                <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden flex">
                  {bot.winRate > 0 ? (
                    <>
                      <div className="h-full bg-emerald-500/80" style={{ width: `${bot.winRate}%` }} />
                      <div className="h-full bg-rose-500/80" style={{ width: `${100 - bot.winRate}%` }} />
                    </>
                  ) : (
                    <div className="h-full w-full bg-slate-800" />
                  )}
                </div>
                <div className="text-[10px] font-mono text-slate-400 w-8 text-right">
                  {bot.winRate > 0 ? `${bot.winRate}%` : '--'}
                </div>
              </div>
            </div>

            {/* Footer: Recent Trades Table */}
            <div className="bg-[#0B0E15] px-4 py-2 mt-auto border-t border-slate-800/30 h-[72px] shrink-0">
              <div className="text-[9px] text-slate-500 font-mono uppercase mb-1.5">Recent Closed</div>
              {bot.recentTrades.length > 0 ? (
                <div className="flex flex-col gap-1">
                  {bot.recentTrades.slice(0, 3).map((trade, i) => (
                    <div key={i} className="flex justify-between items-center text-[10px] font-mono leading-none">
                      <span className="text-slate-400">{trade.symbol}</span>
                      <span className={trade.isWin ? "text-emerald-400" : "text-rose-400"}>
                        {trade.isWin ? '+' : ''}{trade.pnl}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex items-center justify-center h-full pb-4 text-[10px] text-slate-600 font-mono italic">
                  No recent trades
                </div>
              )}
            </div>

          </div>
        ))}
      </div>
    </div>
  );
}
