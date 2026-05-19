import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { format } from "date-fns";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Clock,
  Terminal,
  TrendingUp,
} from "lucide-react";
import { useEffect, useState } from "react";
import "./_group.css";

const bots = [
  {
    id: "oracle",
    name: "Oracle",
    icon: "🔮",
    exchange: "Alpaca",
    asset: "Stocks",
    equity: 90288,
    pnl: -9712,
    pnlPct: -9.71,
    status: "STALE",
    openTrades: 0,
    strategy: "momentum stocks NYSE hours",
    color: "#ef4444",
    conditions: "Z-Score > 2.1 | Min Profit 0.5% | NYSE hours only",
    trades: [
      { sym: "NVDA", dir: "SHORT", pnl: -2100 },
      { sym: "AAPL", dir: "LONG", pnl: 890 },
      { sym: "META", dir: "SHORT", pnl: -1450 },
    ],
    winRate: 45,
    wl: "45W 55L",
    openPositions: [],
  },
  {
    id: "spy-qqq",
    name: "SPY/QQQ Trend",
    icon: "📈",
    exchange: "Alpaca",
    asset: "ETFs",
    equity: 110081,
    pnl: 10081,
    pnlPct: 10.08,
    status: "LIVE",
    openTrades: 1,
    strategy: "trend-following ETF rotation",
    color: "#22c55e",
    conditions: "Z-Entry 2.0 | Z-Exit 0.3 | Trail 1.5% | Stop 3%",
    trades: [
      { sym: "SPY", dir: "LONG", pnl: 234 },
      { sym: "QQQ", dir: "SHORT", pnl: -112 },
      { sym: "SPY", dir: "LONG", pnl: 445 },
    ],
    winRate: 68,
    wl: "68W 32L",
    openPositions: ["SPY (LONG)"],
  },
  {
    id: "jerome",
    name: "Jerome",
    icon: "🏛️",
    exchange: "Alpaca",
    asset: "Macro",
    equity: 100000,
    pnl: 0,
    pnlPct: 0.0,
    status: "LIVE",
    openTrades: 0,
    strategy: "LLM-driven macro commodity futures",
    color: "#3b82f6",
    conditions: "LLM analysis at 9AM + 9PM UTC | Groq/Gemini powered",
    trades: [],
    winRate: 0,
    wl: "0W 0L",
    openPositions: [],
  },
  {
    id: "forex-gump",
    name: "Forex Gump",
    icon: "🧭",
    exchange: "Oanda",
    asset: "Forex",
    equity: 102639,
    pnl: 2639,
    pnlPct: 2.64,
    status: "LIVE",
    openTrades: 5,
    strategy: "G10 currency trend",
    color: "#22c55e",
    conditions: "G10 pairs | ATR-based stops | 4hr cycles",
    trades: [
      { sym: "EURUSD", dir: "LONG", pnl: 412 },
      { sym: "GBPUSD", dir: "SHORT", pnl: -89 },
      { sym: "GBPJPY", dir: "LONG", pnl: 677 },
    ],
    winRate: 52,
    wl: "152W 140L",
    openPositions: ["EURUSD", "GBPJPY", "AUDUSD", "USDJPY", "EURGBP"],
  },
  {
    id: "listing-pump",
    name: "Listing Pump",
    icon: "🚀",
    exchange: "Kraken",
    asset: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPct: 0,
    status: "LIVE",
    openTrades: 0,
    strategy: "new exchange listing momentum",
    color: "#a855f7",
    conditions: "signal thresholds vary | 24/7 crypto",
    trades: [],
    winRate: 0,
    wl: "0W 0L",
    openPositions: [],
  },
  {
    id: "event-trader",
    name: "Event Trader",
    icon: "⚡",
    exchange: "Kraken",
    asset: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPct: 0,
    status: "LIVE",
    openTrades: 0,
    strategy: "macro event volatility trades",
    color: "#a855f7",
    conditions: "signal thresholds vary | 24/7 crypto",
    trades: [],
    winRate: 0,
    wl: "0W 0L",
    openPositions: [],
  },
  {
    id: "depeg-hunter",
    name: "Depeg Hunter",
    icon: "🎯",
    exchange: "Kraken",
    asset: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPct: 0,
    status: "LIVE",
    openTrades: 0,
    strategy: "stablecoin depeg arbitrage",
    color: "#a855f7",
    conditions: "signal thresholds vary | 24/7 crypto",
    trades: [],
    winRate: 0,
    wl: "0W 0L",
    openPositions: [],
  },
  {
    id: "memecoin",
    name: "Memecoin Velocity",
    icon: "🌙",
    exchange: "Kraken",
    asset: "Crypto Wild",
    equity: 100000,
    pnl: 0,
    pnlPct: 0,
    status: "LIVE",
    openTrades: 0,
    strategy: "meme token velocity breakouts",
    color: "#a855f7",
    conditions: "signal thresholds vary | 24/7 crypto",
    trades: [],
    winRate: 0,
    wl: "0W 0L",
    openPositions: [],
  },
];

const recentTrades = [
  { bot: "SPY/QQQ", sym: "SPY", dir: "LONG", pnl: 234, time: "10:31:44" },
  { bot: "Forex Gump", sym: "EURUSD", dir: "LONG", pnl: 412, time: "10:15:22" },
  { bot: "SPY/QQQ", sym: "QQQ", dir: "SHORT", pnl: -112, time: "09:45:00" },
  { bot: "Oracle", sym: "NVDA", dir: "SHORT", pnl: -2100, time: "09:30:05" },
  { bot: "Forex Gump", sym: "GBPUSD", dir: "SHORT", pnl: -89, time: "08:12:10" },
];

export function DarkTerminal() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const formatMoney = (val: number) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(val);
  };

  const sortedBots = [...bots].sort((a, b) => b.pnl - a.pnl);

  return (
    <div className="flex h-[860px] w-[1400px] flex-col overflow-hidden bg-[#0a0e1a] text-slate-300 font-['Inter'] dark">
      {/* Header */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-800/60 bg-[#0d1117] px-4">
        <div className="flex items-center gap-4">
          <Terminal className="h-5 w-5 text-slate-400" />
          <h1 className="font-['JetBrains_Mono'] text-sm font-bold tracking-wider text-slate-200">
            FLEET_COMMAND_v2.4
          </h1>
          <div className="flex items-center gap-2 rounded bg-emerald-500/10 px-2 py-0.5 border border-emerald-500/20">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
            </span>
            <span className="font-['JetBrains_Mono'] text-xs font-bold text-emerald-400">
              SYSTEM LIVE
            </span>
          </div>
        </div>

        <div className="flex items-center gap-6 font-['JetBrains_Mono'] text-xs">
          <div className="flex items-center gap-2">
            <span className="text-slate-500">HEALTH:</span>
            <span className="text-emerald-400">OPTIMAL</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-slate-500">LATENCY:</span>
            <span className="text-emerald-400">24ms</span>
          </div>
          <div className="flex items-center gap-2 text-slate-400">
            <Clock className="h-3.5 w-3.5" />
            {format(time, "HH:mm:ss 'UTC'")}
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar */}
        <aside className="w-[340px] shrink-0 border-r border-slate-800/60 bg-[#0d1117] flex flex-col">
          <div className="p-5 flex flex-col gap-6">
            {/* Fleet Totals */}
            <div>
              <h2 className="mb-4 text-xs font-semibold tracking-widest text-slate-500">
                FLEET OVERVIEW
              </h2>
              <div className="flex flex-col gap-1">
                <div className="text-3xl font-bold text-white font-['JetBrains_Mono'] tracking-tight">
                  $803,007
                </div>
                <div className="flex items-center gap-2 text-sm font-['JetBrains_Mono']">
                  <TrendingUp className="h-4 w-4 text-emerald-500" />
                  <span className="text-emerald-500 font-bold">+$3,007</span>
                  <span className="text-emerald-500/80">(+0.38%)</span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                <div className="text-[10px] uppercase text-slate-500 mb-1">Active Bots</div>
                <div className="font-['JetBrains_Mono'] text-lg font-semibold text-slate-200">7/8</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                <div className="text-[10px] uppercase text-slate-500 mb-1">Open Pos</div>
                <div className="font-['JetBrains_Mono'] text-lg font-semibold text-slate-200">6</div>
              </div>
            </div>

            <Separator className="bg-slate-800" />

            {/* PnL Ladder */}
            <div>
              <h2 className="mb-3 text-xs font-semibold tracking-widest text-slate-500">
                PNL LADDER
              </h2>
              <div className="flex flex-col gap-2">
                {sortedBots.map((bot) => (
                  <div key={bot.id} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: bot.color }} />
                      <span className="w-24 truncate">{bot.name}</span>
                    </div>
                    <span
                      className={`font-['JetBrains_Mono'] ${
                        bot.pnl > 0
                          ? "text-emerald-400"
                          : bot.pnl < 0
                          ? "text-rose-400"
                          : "text-slate-500"
                      }`}
                    >
                      {bot.pnl > 0 ? "+" : ""}
                      {bot.pnl === 0 ? "$0" : formatMoney(bot.pnl)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Recent Trades Feed */}
          <div className="flex-1 overflow-hidden border-t border-slate-800/60 flex flex-col">
            <div className="bg-[#0a0e1a] p-3 border-b border-slate-800/60 sticky top-0 z-10 flex items-center justify-between">
              <h2 className="text-xs font-semibold tracking-widest text-slate-500">
                LIVE FEED
              </h2>
              <Activity className="h-3.5 w-3.5 text-slate-500" />
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2 font-['JetBrains_Mono'] text-[10px]">
              {recentTrades.map((trade, i) => (
                <div key={i} className="flex flex-col gap-1 p-2 rounded bg-slate-900/40 border border-slate-800/40">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">{trade.time}</span>
                    <span className="text-slate-400 font-bold">{trade.bot}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className={trade.dir === "LONG" ? "text-emerald-400" : "text-rose-400"}>
                        {trade.dir}
                      </span>
                      <span className="text-slate-300">{trade.sym}</span>
                    </div>
                    <span className={trade.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {trade.pnl >= 0 ? "+" : ""}
                      ${Math.abs(trade.pnl)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Right Panel - Grid */}
        <main className="flex-1 p-4 grid grid-cols-4 grid-rows-2 gap-4 bg-[#0a0e1a] overflow-hidden">
          {bots.map((bot) => (
            <div
              key={bot.id}
              className="relative flex flex-col rounded-xl border border-slate-800/60 bg-[#0d1117] overflow-hidden shadow-2xl transition-colors hover:border-slate-700/80"
            >
              {/* Left Accent Bar */}
              <div
                className="absolute left-0 top-0 bottom-0 w-1 opacity-80"
                style={{ backgroundColor: bot.color }}
              />

              <div className="p-4 pl-5 flex flex-col h-full">
                {/* Tile Header */}
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-base leading-none">{bot.icon}</span>
                      <h3 className="font-semibold text-slate-200 leading-none">{bot.name}</h3>
                    </div>
                    <div className="flex items-center gap-1 text-[9px] font-['JetBrains_Mono'] text-slate-500 uppercase tracking-wider">
                      <span>{bot.exchange}</span>
                      <span>·</span>
                      <span>{bot.asset}</span>
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className={`font-['JetBrains_Mono'] text-[8px] px-1 py-0 h-4 rounded-sm uppercase tracking-wider border-opacity-30 ${
                      bot.status === "LIVE"
                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/50"
                        : "bg-amber-500/10 text-amber-400 border-amber-500/50"
                    }`}
                  >
                    {bot.status}
                  </Badge>
                </div>

                {/* Equity & PnL */}
                <div className="mb-3">
                  <div className="font-['JetBrains_Mono'] text-xl font-bold text-white tracking-tight">
                    {formatMoney(bot.equity)}
                  </div>
                  <div
                    className={`flex items-center gap-1 font-['JetBrains_Mono'] text-[11px] font-semibold ${
                      bot.pnl > 0
                        ? "text-emerald-400"
                        : bot.pnl < 0
                        ? "text-rose-400"
                        : "text-slate-500"
                    }`}
                  >
                    {bot.pnl > 0 ? (
                      <ArrowUpRight className="h-3 w-3" />
                    ) : bot.pnl < 0 ? (
                      <ArrowDownRight className="h-3 w-3" />
                    ) : (
                      <div className="h-3 w-3" />
                    )}
                    <span>
                      {bot.pnl > 0 ? "+" : ""}
                      {formatMoney(bot.pnl)}
                    </span>
                    <span className="opacity-80">
                      ({bot.pnl > 0 ? "+" : ""}
                      {bot.pnlPct}%)
                    </span>
                  </div>
                </div>

                {/* Open Positions / Activity */}
                <div className="mb-3 bg-[#0a0e1a] rounded p-1.5 border border-slate-800/40">
                  <div className="flex justify-between items-center mb-0.5 text-[9px] text-slate-500 uppercase tracking-wider">
                    <span>Open Positions</span>
                    <span className="font-['JetBrains_Mono'] text-slate-300 font-bold">{bot.openTrades}</span>
                  </div>
                  <div className="font-['JetBrains_Mono'] text-[9px] text-slate-400 truncate h-[14px]">
                    {bot.openPositions.length > 0 ? (
                      bot.openPositions.join(", ")
                    ) : (
                      <span className="text-slate-600">None</span>
                    )}
                  </div>
                </div>

                {/* Entry Conditions / Params */}
                <div className="mb-3">
                  <div className="text-[8px] uppercase tracking-widest text-slate-500 mb-0.5">
                    Params
                  </div>
                  <div className="font-['JetBrains_Mono'] text-[9px] text-slate-400 leading-tight bg-[#0a0e1a] p-1.5 rounded border border-slate-800/40 h-[38px] overflow-hidden">
                    {bot.conditions}
                  </div>
                </div>

                {/* Last 3 Trades */}
                <div className="mb-3">
                  <div className="text-[8px] uppercase tracking-widest text-slate-500 mb-0.5">
                    Recent Trades
                  </div>
                  <div className="space-y-[2px]">
                    {bot.trades.length > 0 ? (
                      bot.trades.slice(0, 3).map((t, i) => (
                        <div key={i} className="flex justify-between items-center text-[9px] font-['JetBrains_Mono'] bg-[#0a0e1a] px-1.5 py-[3px] rounded border border-slate-800/40">
                          <div className="flex items-center gap-1.5">
                            <span className={t.dir === "LONG" ? "text-emerald-400" : "text-rose-400"}>
                              {t.dir.substring(0, 1)}
                            </span>
                            <span className="text-slate-300">{t.sym}</span>
                          </div>
                          <span className={t.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                            {t.pnl >= 0 ? "+" : ""}{formatMoney(t.pnl)}
                          </span>
                        </div>
                      ))
                    ) : (
                      <div className="text-[9px] font-['JetBrains_Mono'] text-slate-600 bg-[#0a0e1a] px-1.5 py-[3px] rounded border border-slate-800/40 flex justify-center">
                        No recent trades
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex-1" />

                {/* Win Rate / Stats */}
                {bot.winRate > 0 ? (
                  <div className="space-y-1 mt-auto">
                    <div className="flex justify-between text-[9px] font-['JetBrains_Mono'] text-slate-400">
                      <span>Win Rate {bot.winRate}%</span>
                      <span>{bot.wl}</span>
                    </div>
                    <div className="h-1 w-full bg-slate-800 overflow-hidden rounded-full">
                      <div 
                        className={`h-full ${bot.pnl >= 0 ? "bg-emerald-500" : "bg-rose-500"}`} 
                        style={{ width: `${bot.winRate}%` }} 
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1 mt-auto opacity-50">
                    <div className="flex justify-between text-[9px] font-['JetBrains_Mono'] text-slate-400">
                      <span>Awaiting Data</span>
                      <span>0W 0L</span>
                    </div>
                    <div className="h-1 w-full bg-slate-800 overflow-hidden rounded-full"></div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </main>
      </div>
    </div>
  );
}
