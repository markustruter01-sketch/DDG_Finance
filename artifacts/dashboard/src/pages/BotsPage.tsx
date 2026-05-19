import {
  useFleetEquity,
  useKrakenPerformance,
  useKrakenStatus,
  useForexState,
  useForexPositions,
  usePortfolio,
  useRecentTrades,
  type ForexPosition,
} from "@/hooks/use-trading";
import { Activity, ArrowDownRight, ArrowUpRight, Clock, Terminal, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";

const STARTING = 100_000;
const FLEET_STARTING = 800_000;

function fmt$(v: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(v);
}

interface BotDef {
  id: string;
  name: string;
  icon: string;
  exchange: string;
  asset: string;
  color: string;
  params: string;
}

const BOT_DEFS: BotDef[] = [
  { id: "oracle",            name: "Oracle",           icon: "🔮", exchange: "Alpaca", asset: "Stocks",      color: "#22d3ee", params: "Z-Score > 2.1 | Min Profit 0.5% | NYSE hours only" },
  { id: "spy_qqq_trend",     name: "SPY/QQQ Trend",    icon: "📈", exchange: "Alpaca", asset: "ETFs",        color: "#3b82f6", params: "Z-Entry 2.0 | Z-Exit 0.3 | Trail 1.5% | Stop 3%" },
  { id: "jerome_macro",      name: "Jerome",           icon: "🏛️", exchange: "Alpaca", asset: "Macro",       color: "#f97316", params: "LLM analysis at 9AM + 9PM UTC | Groq/Gemini powered" },
  { id: "forex_gump",        name: "Forex Gump",       icon: "🧭", exchange: "Oanda",  asset: "Forex",       color: "#06b6d4", params: "G10 pairs | ATR-based stops | 4hr cycles" },
  { id: "listing_pump",      name: "Listing Pump",     icon: "🚀", exchange: "Kraken", asset: "Crypto Wild", color: "#a855f7", params: "New exchange listing momentum | 24/7 crypto" },
  { id: "event_trader",      name: "Event Trader",     icon: "⚡", exchange: "Kraken", asset: "Crypto Wild", color: "#a855f7", params: "Macro event volatility trades | 24/7 crypto" },
  { id: "depeg_hunter",      name: "Depeg Hunter",     icon: "🎯", exchange: "Kraken", asset: "Crypto Wild", color: "#a855f7", params: "Stablecoin depeg arbitrage | 24/7 crypto" },
  { id: "memecoin_velocity", name: "Memecoin Velocity",icon: "🌙", exchange: "Kraken", asset: "Crypto Wild", color: "#a855f7", params: "Meme token velocity breakouts | 24/7 crypto" },
];

interface BotSnap extends BotDef {
  equity: number | null;
  pnl: number | null;
  pnlPct: number | null;
  paused: boolean;
  stale: boolean;
  wins: number;
  losses: number;
  openCount: number;
  openSymbols: string[];
  recentTrades: Array<{ sym: string; dir: string; pnl: number }>;
}

interface FeedEntry {
  bot: string;
  sym: string;
  dir: string;
  pnl: number;
  time: string;
}

function statusLabel(bot: BotSnap) {
  if (bot.paused) return "PAUSED";
  if (bot.stale)  return "STALE";
  return "LIVE";
}

function statusClasses(bot: BotSnap) {
  if (bot.paused) return { badge: "bg-amber-500/10 text-amber-400 border-amber-500/40",  dot: "bg-amber-500" };
  if (bot.stale)  return { badge: "bg-slate-500/10 text-slate-400 border-slate-500/30",  dot: "bg-slate-500" };
  return          { badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/40", dot: "bg-emerald-500" };
}

function BotTile({ bot }: { bot: BotSnap }) {
  const pnlColor = bot.pnl == null ? "#64748b" : bot.pnl >= 0 ? "#34d399" : "#f87171";
  const wr = (bot.wins + bot.losses) > 0 ? (bot.wins / (bot.wins + bot.losses)) * 100 : null;
  const sc = statusClasses(bot);

  return (
    <div className="relative flex flex-col rounded-xl border border-slate-800/60 bg-[#0d1117] overflow-hidden transition-colors hover:border-slate-700/60">
      {/* Left accent bar */}
      <div className="absolute left-0 top-0 bottom-0 w-[3px]" style={{ backgroundColor: bot.color }} />

      <div className="p-3 pl-4 flex flex-col h-full gap-2.5">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className="text-sm leading-none">{bot.icon}</span>
              <span className="text-[12px] font-semibold text-slate-200 leading-none">{bot.name}</span>
            </div>
            <div className="text-[9px] font-mono text-slate-500 uppercase tracking-wider">
              {bot.exchange} · {bot.asset}
            </div>
          </div>
          <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded-sm border text-[8px] font-mono font-bold uppercase tracking-wider ${sc.badge}`}>
            {!bot.paused && !bot.stale && (
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${sc.dot}`} />
              </span>
            )}
            {(bot.paused || bot.stale) && <span className={`h-1.5 w-1.5 rounded-full ${sc.dot}`} />}
            {statusLabel(bot)}
          </div>
        </div>

        {/* Equity + PnL */}
        <div>
          <div className="font-mono text-[18px] font-bold text-white leading-tight">
            {bot.equity != null ? fmt$(bot.equity) : "—"}
          </div>
          <div className="flex items-center gap-1 font-mono text-[10px] font-semibold" style={{ color: pnlColor }}>
            {bot.pnl != null && bot.pnl > 0 && <ArrowUpRight className="h-3 w-3" />}
            {bot.pnl != null && bot.pnl < 0 && <ArrowDownRight className="h-3 w-3" />}
            {bot.pnl != null && bot.pnl === 0 && <div className="h-3 w-3" />}
            <span>
              {bot.pnl != null
                ? `${bot.pnl > 0 ? "+" : ""}${fmt$(bot.pnl)}`
                : "—"}
            </span>
            {bot.pnlPct != null && (
              <span className="opacity-70">
                ({bot.pnlPct > 0 ? "+" : ""}{bot.pnlPct.toFixed(2)}%)
              </span>
            )}
          </div>
        </div>

        {/* Open positions */}
        <div className="bg-[#0a0e1a] rounded p-1.5 border border-slate-800/40">
          <div className="flex justify-between items-center mb-0.5 text-[8px] text-slate-500 uppercase tracking-wider">
            <span>Open Positions</span>
            <span className="font-mono text-slate-300 font-bold">{bot.openCount}</span>
          </div>
          <div className="font-mono text-[8px] text-slate-400 truncate h-[12px]">
            {bot.openSymbols.length > 0
              ? bot.openSymbols.map(s => s.replace("/USD", "").replace("USD", "")).join(", ")
              : <span className="text-slate-600">None</span>}
          </div>
        </div>

        {/* Params */}
        <div>
          <div className="text-[7px] uppercase tracking-widest text-slate-600 mb-0.5">Params</div>
          <div className="font-mono text-[8px] text-slate-400 leading-snug bg-[#0a0e1a] p-1.5 rounded border border-slate-800/40 h-8 overflow-hidden">
            {bot.params}
          </div>
        </div>

        {/* Recent Trades */}
        <div className="flex-1">
          <div className="text-[7px] uppercase tracking-widest text-slate-600 mb-1">Recent Trades</div>
          <div className="space-y-[2px]">
            {bot.recentTrades.length > 0 ? (
              bot.recentTrades.slice(0, 3).map((t, i) => (
                <div
                  key={i}
                  className="flex justify-between items-center text-[8px] font-mono bg-[#0a0e1a] px-1.5 py-[2px] rounded border border-slate-800/40"
                >
                  <div className="flex items-center gap-1">
                    <span className={t.dir === "long" || t.dir === "LONG" ? "text-emerald-400" : "text-rose-400"}>
                      {(t.dir === "long" || t.dir === "LONG") ? "L" : "S"}
                    </span>
                    <span className="text-slate-300">{t.sym}</span>
                  </div>
                  <span className={t.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                    {t.pnl >= 0 ? "+" : ""}{fmt$(t.pnl)}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-[8px] font-mono text-slate-600 bg-[#0a0e1a] px-1.5 py-[2px] rounded border border-slate-800/40 text-center">
                No recent trades
              </div>
            )}
          </div>
        </div>

        {/* Win rate bar */}
        <div className="space-y-1 mt-auto">
          {wr != null ? (
            <>
              <div className="flex justify-between text-[8px] font-mono text-slate-400">
                <span>Win Rate {wr.toFixed(0)}%</span>
                <span>{bot.wins}W {bot.losses}L</span>
              </div>
              <div className="h-1 w-full bg-slate-800 overflow-hidden rounded-full">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(wr, 100)}%`,
                    backgroundColor: wr >= 50 ? "#34d399" : wr >= 38 ? "#fbbf24" : "#f87171",
                  }}
                />
              </div>
            </>
          ) : (
            <>
              <div className="flex justify-between text-[8px] font-mono text-slate-600">
                <span>Awaiting Data</span>
                <span>0W 0L</span>
              </div>
              <div className="h-1 w-full bg-slate-800 rounded-full" />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BotsPage() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const { data: fleetEq }    = useFleetEquity();
  const { data: portfolio }  = usePortfolio();
  const { data: davyPerf }   = useKrakenPerformance("davy-jones");
  const { data: davySt }     = useKrakenStatus("davy-jones");
  const { data: bbPerf }     = useKrakenPerformance("blackbeard");
  const { data: bbSt }       = useKrakenStatus("blackbeard");
  const { data: forexState } = useForexState();
  const { data: forexPosRaw }= useForexPositions();
  const { data: recentData } = useRecentTrades(10);

  // Oracle open positions
  const oracleSymbols = (portfolio?.positions ?? [])
    .filter(p => (p.market_value ?? 0) > 10)
    .map(p => p.symbol);

  // Forex open positions
  const forexPos: ForexPosition[] = Array.isArray(forexPosRaw)
    ? (forexPosRaw as ForexPosition[])
    : ((forexPosRaw as { positions?: ForexPosition[] } | null)?.positions ?? []);
  const forexSymbols = forexPos.map(p => p.pair);

  function krakenTrades(st: typeof davySt) {
    return (st?.recent_trades ?? []).slice(0, 3).map(t => ({
      sym: t.symbol,
      dir: t.side,
      pnl: t.pnl_usd,
    }));
  }

  // Oracle recent trades from journal
  const oracleTrades = (recentData?.trades ?? []).slice(0, 3).map(t => ({
    sym: t.symbol,
    dir: (t.pnl_pct ?? 0) >= 0 ? "long" : "short",
    pnl: t.pnl_usd ?? 0,
  }));

  function mkSnap(def: BotDef, overrides: Partial<BotSnap>): BotSnap {
    return { ...def, equity: null, pnl: null, pnlPct: null, paused: false, stale: false, wins: 0, losses: 0, openCount: 0, openSymbols: [], recentTrades: [], ...overrides };
  }

  function fromFleet(id: keyof typeof fleetEq) {
    const b = (fleetEq as Record<string, { equity?: number; pnl?: number; pnl_pct?: number; stale?: boolean } | undefined> | undefined)?.[id as string];
    if (!b) return { equity: null, pnl: null, pnlPct: null, stale: false };
    return {
      equity: b.equity ?? null,
      pnl: b.pnl ?? (b.equity != null ? b.equity - STARTING : null),
      pnlPct: b.pnl_pct ?? (b.equity != null ? ((b.equity - STARTING) / STARTING) * 100 : null),
      stale: b.stale ?? false,
    };
  }

  const bots: BotSnap[] = [
    mkSnap(BOT_DEFS[0], {
      ...fromFleet("oracle"),
      openCount: oracleSymbols.length,
      openSymbols: oracleSymbols,
      recentTrades: oracleTrades,
    }),
    mkSnap(BOT_DEFS[1], {
      ...fromFleet("spy_qqq_trend"),
      paused: davySt?.bot_paused ?? false,
      wins: davyPerf?.win_count ?? 0,
      losses: davyPerf?.loss_count ?? 0,
      openCount: davySt?.open_positions?.length ?? 0,
      openSymbols: (davySt?.open_positions ?? []).map(p => p.symbol),
      recentTrades: krakenTrades(davySt),
    }),
    mkSnap(BOT_DEFS[2], {
      ...fromFleet("jerome_macro"),
      paused: bbSt?.bot_paused ?? false,
      wins: bbPerf?.win_count ?? 0,
      losses: bbPerf?.loss_count ?? 0,
      openCount: bbSt?.open_positions?.length ?? 0,
      openSymbols: (bbSt?.open_positions ?? []).map(p => p.symbol),
      recentTrades: krakenTrades(bbSt),
    }),
    mkSnap(BOT_DEFS[3], {
      ...fromFleet("forex_gump"),
      paused: forexState?.paused ?? false,
      wins: forexState?.total_wins ?? 0,
      losses: (forexState?.total_trades ?? 0) - (forexState?.total_wins ?? 0),
      openCount: forexPos.length,
      openSymbols: forexSymbols,
    }),
    mkSnap(BOT_DEFS[4], { ...fromFleet("listing_pump") }),
    mkSnap(BOT_DEFS[5], { ...fromFleet("event_trader") }),
    mkSnap(BOT_DEFS[6], { ...fromFleet("depeg_hunter") }),
    mkSnap(BOT_DEFS[7], { ...fromFleet("memecoin_velocity") }),
  ];

  // Fleet totals
  const ft = fleetEq?.fleet_total;
  const fleetEquity  = ft?.equity  ?? bots.reduce((s, b) => s + (b.equity ?? STARTING), 0);
  const fleetPnl     = ft?.pnl     ?? (fleetEquity - FLEET_STARTING);
  const fleetPnlPct  = ft?.pnl_pct ?? (fleetPnl / FLEET_STARTING) * 100;
  const activeBots   = bots.filter(b => !b.paused).length;
  const openTotal    = bots.reduce((s, b) => s + b.openCount, 0);
  const pnlColor     = fleetPnl >= 0 ? "#34d399" : "#f87171";

  // PNL Ladder — sorted by pnl desc
  const ladder = [...bots].sort((a, b) => (b.pnl ?? 0) - (a.pnl ?? 0));

  // Live feed — combine kraken + oracle trades
  const feed: FeedEntry[] = [
    ...(davySt?.recent_trades ?? []).slice(0, 5).map(t => ({
      bot: "SPY/QQQ", sym: t.symbol, dir: t.side, pnl: t.pnl_usd,
      time: t.closed_at ? new Date(t.closed_at).toLocaleTimeString("en-US", { hour12: false }) : "—",
    })),
    ...(bbSt?.recent_trades ?? []).slice(0, 5).map(t => ({
      bot: "Jerome", sym: t.symbol, dir: t.side, pnl: t.pnl_usd,
      time: t.closed_at ? new Date(t.closed_at).toLocaleTimeString("en-US", { hour12: false }) : "—",
    })),
    ...(recentData?.trades ?? []).slice(0, 5).map(t => ({
      bot: "Oracle", sym: t.symbol, dir: (t.pnl_pct ?? 0) >= 0 ? "long" : "short", pnl: t.pnl_usd ?? 0,
      time: t.closed_at ? new Date(t.closed_at).toLocaleTimeString("en-US", { hour12: false }) : "—",
    })),
  ].sort((a, b) => b.time.localeCompare(a.time)).slice(0, 12);

  return (
    <div className="flex flex-col bg-[#0a0e1a] text-slate-300 overflow-hidden" style={{ height: "100dvh", paddingBottom: "88px" }}>
      {/* ── Header ── */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-slate-800/60 bg-[#0d1117] px-4">
        <div className="flex items-center gap-3">
          <Terminal className="h-4 w-4 text-slate-400" />
          <span className="font-mono text-[12px] font-bold tracking-wider text-slate-200">
            FLEET_COMMAND_v2.4
          </span>
          <div className="flex items-center gap-1.5 rounded bg-emerald-500/10 px-2 py-0.5 border border-emerald-500/20">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
            </span>
            <span className="font-mono text-[9px] font-bold text-emerald-400 tracking-widest">SYSTEM LIVE</span>
          </div>
        </div>
        <div className="flex items-center gap-5 font-mono text-[10px]">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">HEALTH:</span>
            <span className="text-emerald-400 font-bold">OPTIMAL</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">BOTS:</span>
            <span className="text-emerald-400 font-bold">{activeBots}/8</span>
          </div>
          <div className="flex items-center gap-1.5 text-slate-400">
            <Clock className="h-3 w-3" />
            <span>{now.toLocaleTimeString("en-US", { hour12: false })} UTC</span>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left Sidebar ── */}
        <aside className="w-[260px] shrink-0 border-r border-slate-800/60 bg-[#0d1117] flex flex-col overflow-hidden">
          <div className="p-4 flex flex-col gap-4">
            {/* Fleet Overview */}
            <div>
              <div className="text-[9px] font-semibold tracking-widest text-slate-500 mb-2">FLEET OVERVIEW</div>
              <div className="font-mono text-[26px] font-bold text-white tracking-tight leading-none">
                {fmt$(fleetEquity)}
              </div>
              <div className="flex items-center gap-1.5 mt-1 font-mono text-[11px]">
                <TrendingUp className="h-3.5 w-3.5" style={{ color: pnlColor }} />
                <span style={{ color: pnlColor }} className="font-bold">
                  {fleetPnl >= 0 ? "+" : ""}{fmt$(fleetPnl)}
                </span>
                <span style={{ color: pnlColor }} className="opacity-70">
                  ({fleetPnlPct >= 0 ? "+" : ""}{fleetPnlPct.toFixed(2)}%)
                </span>
              </div>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-2.5">
                <div className="text-[8px] uppercase text-slate-500 mb-0.5">Active Bots</div>
                <div className="font-mono text-[15px] font-semibold text-slate-200">{activeBots}/8</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-2.5">
                <div className="text-[8px] uppercase text-slate-500 mb-0.5">Open Pos</div>
                <div className="font-mono text-[15px] font-semibold text-slate-200">{openTotal}</div>
              </div>
            </div>

            {/* Divider */}
            <div className="h-px bg-slate-800" />

            {/* PNL Ladder */}
            <div>
              <div className="text-[9px] font-semibold tracking-widest text-slate-500 mb-2">PNL LADDER</div>
              <div className="flex flex-col gap-1.5">
                {ladder.map(bot => (
                  <div key={bot.id} className="flex items-center justify-between text-[10px]">
                    <div className="flex items-center gap-1.5">
                      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: bot.color }} />
                      <span className="w-28 truncate text-slate-400">{bot.name}</span>
                    </div>
                    <span
                      className="font-mono font-semibold"
                      style={{
                        color: (bot.pnl ?? 0) > 0 ? "#34d399" : (bot.pnl ?? 0) < 0 ? "#f87171" : "#475569",
                      }}
                    >
                      {(bot.pnl ?? 0) > 0 ? "+" : ""}
                      {bot.pnl != null ? fmt$(bot.pnl) : "$0"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Live Feed */}
          <div className="flex-1 overflow-hidden border-t border-slate-800/60 flex flex-col min-h-0">
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800/40">
              <span className="text-[9px] font-semibold tracking-widest text-slate-500">LIVE FEED</span>
              <Activity className="h-3 w-3 text-slate-500" />
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5 font-mono text-[9px]">
              {feed.length > 0 ? feed.map((t, i) => (
                <div
                  key={i}
                  className="flex flex-col gap-0.5 p-1.5 rounded bg-slate-900/40 border border-slate-800/30"
                >
                  <div className="flex items-center justify-between text-slate-500">
                    <span>{t.time}</span>
                    <span className="text-slate-400 font-bold">{t.bot}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1">
                      <span className={t.dir === "long" || t.dir === "buy" ? "text-emerald-400" : "text-rose-400"}>
                        {t.dir === "long" || t.dir === "buy" ? "LONG" : "SHORT"}
                      </span>
                      <span className="text-slate-300">{t.sym.replace("/USD", "")}</span>
                    </div>
                    <span className={t.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {t.pnl >= 0 ? "+" : ""}${Math.abs(t.pnl).toFixed(0)}
                    </span>
                  </div>
                </div>
              )) : (
                <div className="text-slate-600 text-center pt-4">No recent trades</div>
              )}
            </div>
          </div>
        </aside>

        {/* ── Bot Grid ── */}
        <main className="flex-1 p-3 grid grid-cols-4 grid-rows-2 gap-3 bg-[#0a0e1a] overflow-hidden">
          {bots.map(bot => (
            <BotTile key={bot.id} bot={bot} />
          ))}
        </main>
      </div>
    </div>
  );
}
